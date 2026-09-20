"""Finite SQL templates. Unsupported dimensions and ambiguous metrics are errors."""
from __future__ import annotations

import json
import re
from decimal import Decimal

from .common import DATASET, METRIC, QueryError, connect

SPECS = {
    "monthly_registrations": {"required": ["start_month", "end_month"], "optional": ["maker", "metric"],
        "description": "月份区间登记量，可选一个品牌；包含无登记的零值月份"},
    "brand_compare": {"required": ["start_month", "end_month", "makers"], "optional": ["metric"],
        "description": "同月份区间多个品牌的登记量对比；品牌仅合并大小写差异"},
    "maker_ranking": {"required": ["start_month", "end_month"], "optional": ["limit", "metric"],
        "description": "月份区间品牌登记量排名"},
    "fuel_monthly": {"required": ["start_month", "end_month"], "optional": ["fuel", "metric"],
        "description": "月份区间燃料类型登记量；不支持附加品牌筛选"},
}


def metadata(cur):
    cur.execute("SELECT v.source_json FROM dataset_versions v JOIN active_dataset a ON v.version=a.version WHERE a.singleton=1")
    row = cur.fetchone()
    if not row:
        raise QueryError("NO_ACTIVE_DATASET", "尚未导入已验证的JPJ快照", status=503)
    source = json.loads(row["source_json"])
    version = source["version"]
    cur.execute("SELECT `year_month` FROM aggregates WHERE version=%s AND dimension='month' ORDER BY `year_month`", (version,))
    months = [r["year_month"] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT maker_norm FROM aggregates WHERE version=%s AND dimension='maker' ORDER BY maker_norm", (version,))
    makers = [r["maker_norm"] for r in cur.fetchall()]
    cur.execute("SELECT fuel FROM aggregates WHERE version=%s AND dimension='fuel' ORDER BY fuel", (version,))
    fuels = [r["fuel"] for r in cur.fetchall()]
    return {"dataset": DATASET, "version": version, "source": source, "available_months": months,
            "makers": makers, "fuels": fuels, "metric_definition": METRIC,
            "routing": "fixed SQL templates and deterministic rules; no LLM",
            "queries": [{"query_id": key, "parameters": {"required": value["required"], "optional": value["optional"]},
                         "description": value["description"]} for key, value in SPECS.items()],
            "unsupported": ["sales/TIV", "owner location", "maker x fuel", "month x state", "model/colour/vehicle_type filters", "arbitrary SQL"]}


def get_catalog():
    with connect() as connection:
        with connection.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            connection.begin()
            result = metadata(cur)
        connection.rollback()
    return result


def month_sequence(start, end):
    y, m = map(int, start.split("-")); end_y, end_m = map(int, end.split("-"))
    result = []
    while (y, m) <= (end_y, end_m):
        result.append(f"{y:04}-{m:02}")
        m += 1
        if m == 13: y, m = y + 1, 1
    return result


def prepare_query(query_id, parameters, catalog):
    if not isinstance(query_id, str) or query_id not in SPECS:
        raise QueryError("UNKNOWN_QUERY", "只接受catalog列出的固定查询", {"supported": list(SPECS)})
    if not isinstance(parameters, dict):
        raise QueryError("INVALID_PARAMETERS", "parameters必须为JSON对象")
    spec = SPECS[query_id]
    extras = set(parameters) - set(spec["required"] + spec["optional"])
    if extras:
        raise QueryError("UNSUPPORTED_FILTER", "这些条件没有对应联合维度，不能静默丢弃", {"parameters": sorted(extras)})
    missing = [key for key in spec["required"] if key not in parameters]
    if missing:
        raise QueryError("MISSING_PARAMETERS", "请明确必要查询条件", {"parameters": missing})
    p = dict(parameters)
    if p.get("metric", "registrations") != "registrations":
        raise QueryError("METRIC_MISMATCH", "JPJ仅支持登记量；销量/TIV必须使用对应来源，不能用登记量代答")
    p["metric"] = "registrations"
    for key in ["start_month", "end_month"]:
        if not isinstance(p[key], str) or not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", p[key]):
            raise QueryError("INVALID_MONTH", "月份格式必须为YYYY-MM", {"parameter": key})
    if p["start_month"] > p["end_month"]:
        raise QueryError("INVALID_RANGE", "开始月份不能晚于结束月份")
    sequence = month_sequence(p["start_month"], p["end_month"])
    absent = sorted(set(sequence) - set(catalog["available_months"]))
    if absent:
        raise QueryError("OUT_OF_COVERAGE", "该期间并非所有月份都有真实数据，不能以部分年度冒充全年", {"missing_months": absent})
    def maker(value):
        if not isinstance(value, str) or value.strip().upper() not in catalog["makers"]:
            raise QueryError("UNKNOWN_MAKER", "品牌不在当前数据目录，请从catalog选择", {"maker": value})
        return value.strip().upper()
    if "maker" in p: p["maker"] = maker(p["maker"])
    if "makers" in p:
        if not isinstance(p["makers"], list) or not 2 <= len(p["makers"]) <= 8:
            raise QueryError("INVALID_MAKERS", "对比需要2至8个不同品牌")
        p["makers"] = [maker(value) for value in p["makers"]]
        if len(set(p["makers"])) != len(p["makers"]):
            raise QueryError("DUPLICATE_MAKERS", "品牌规范化后重复")
    if "fuel" in p:
        if not isinstance(p["fuel"], str) or p["fuel"] not in catalog["fuels"]:
            raise QueryError("UNKNOWN_FUEL", "燃料类别不在当前catalog中")
    if query_id == "maker_ranking":
        p.setdefault("limit", 10)
        if type(p["limit"]) is not int or not 1 <= p["limit"] <= 30:
            raise QueryError("INVALID_LIMIT", "limit须为1到30的整数")
    version, start, end = catalog["version"], p["start_month"], p["end_month"]
    if query_id == "monthly_registrations":
        if "maker" not in p:
            sql = "SELECT `year_month`, registrations FROM aggregates WHERE version=%s AND dimension='month' AND `year_month` BETWEEN %s AND %s ORDER BY `year_month`"
            args = (version, start, end)
        else:
            sql = "SELECT m.`year_month`, COALESCE(SUM(a.registrations),0) AS registrations FROM aggregates m LEFT JOIN aggregates a ON a.version=m.version AND a.dimension='month_maker' AND a.`year_month`=m.`year_month` AND a.maker_norm=%s WHERE m.version=%s AND m.dimension='month' AND m.`year_month` BETWEEN %s AND %s GROUP BY m.`year_month` ORDER BY m.`year_month`"
            args = (p["maker"], version, start, end)
        columns = ["year_month", "registrations"]
    elif query_id == "brand_compare":
        choices = " UNION ALL ".join(["SELECT %s AS maker"] * len(p["makers"]))
        sql = "SELECT choices.maker, COALESCE(SUM(a.registrations),0) AS registrations FROM (" + choices + ") choices LEFT JOIN aggregates a ON a.version=%s AND a.dimension='month_maker' AND a.maker_norm=choices.maker AND a.`year_month` BETWEEN %s AND %s GROUP BY choices.maker ORDER BY registrations DESC, choices.maker"
        args = (*p["makers"], version, start, end); columns = ["maker", "registrations"]
    elif query_id == "maker_ranking":
        sql = "SELECT maker_norm AS maker, SUM(registrations) AS registrations FROM aggregates WHERE version=%s AND dimension='month_maker' AND `year_month` BETWEEN %s AND %s GROUP BY maker_norm ORDER BY registrations DESC, maker_norm LIMIT %s"
        args = (version, start, end, p["limit"]); columns = ["maker", "registrations"]
    elif "fuel" not in p:
        sql = "SELECT `year_month`,fuel,registrations FROM aggregates WHERE version=%s AND dimension='month_fuel' AND `year_month` BETWEEN %s AND %s ORDER BY `year_month`,fuel"
        args = (version, start, end); columns = ["year_month", "fuel", "registrations"]
    else:
        sql = "SELECT m.`year_month`,%s AS fuel,COALESCE(SUM(a.registrations),0) AS registrations FROM aggregates m LEFT JOIN aggregates a ON a.version=m.version AND a.dimension='month_fuel' AND a.`year_month`=m.`year_month` AND a.fuel=%s WHERE m.version=%s AND m.dimension='month' AND m.`year_month` BETWEEN %s AND %s GROUP BY m.`year_month` ORDER BY m.`year_month`"
        args = (p["fuel"], p["fuel"], version, start, end); columns = ["year_month", "fuel", "registrations"]
    return p, sql, args, columns


def query(query_id, parameters):
    with connect() as connection:
        with connection.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            connection.begin()
            catalog = metadata(cur)
            normalized, sql, arguments, columns = prepare_query(query_id, parameters, catalog)
            cur.execute(sql, arguments)
            rows = [{key: int(v) if isinstance(v, Decimal) else v for key, v in row.items()} for row in cur.fetchall()]
        connection.rollback()
    return {"query_id": query_id, "parameters": normalized, "rows": rows, "columns": columns,
            "source": catalog["source"], "metric_definition": METRIC, "sql": sql,
            "sql_bindings": list(arguments), "routing": "fixed SQL template; no LLM"}


def route_question(question):
    """Intentionally narrow full-match grammar: never discard unseen words."""
    if not isinstance(question, str) or len(question) > 240:
        raise QueryError("INVALID_QUESTION", "问句必须为不超过240字的文本")
    if re.search(r"销量|卖|批发|库存|进口|\bTIV\b|\bsales\b", question, re.I):
        raise QueryError("METRIC_MISMATCH", "这里是真实JPJ登记数据；无法回答销量、TIV、进口或库存")
    q = question.strip()
    prefix = r"(?P<start>20\d{2}-\d{2})\s*(?:至|到)\s*(?P<end>20\d{2}-\d{2})\s*"
    match = re.fullmatch(prefix + r"每月登记量", q)
    if match:
        return "monthly_registrations", {"start_month": match["start"], "end_month": match["end"]}
    match = re.fullmatch(prefix + r"(?P<makers>[A-Za-z0-9 .&()/-]+(?:和[A-Za-z0-9 .&()/-]+)+)登记量对比", q)
    if match:
        return "brand_compare", {"start_month": match["start"], "end_month": match["end"], "makers": [v.strip() for v in match["makers"].split("和")]}
    match = re.fullmatch(prefix + r"品牌登记量排名(?:前(?P<limit>\d+))?", q)
    if match:
        return "maker_ranking", {"start_month": match["start"], "end_month": match["end"], "limit": int(match["limit"] or 10)}
    raise QueryError("CLARIFICATION_REQUIRED", "未完整识别问句，请使用明确模板或下方结构化条件；不会忽略未知筛选条件", {"examples": ["2026-01至2026-08 每月登记量", "2026-01至2026-08 BYD和TESLA登记量对比", "2026-01至2026-08 品牌登记量排名前5"]})
