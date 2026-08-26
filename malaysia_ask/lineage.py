# -*- coding: utf-8 -*-
"""Table-level lineage for the demo warehouse. Not column-level, not Atlas."""
from __future__ import annotations

LAYER_ORDER = {"ods": 0, "dim": 1, "dwd": 2, "ads": 3, "metric": 4, "doc": 5}

NODES: list[dict] = [
    {
        "object_name": "ods.brand_year_anchor",
        "layer": "ods",
        "object_kind": "table",
        "table_name": "ods_brand_year_anchor",
        "grain": "year, brand",
        "owner": "demo.metrics",
        "version": "2026.08.2",
        "note": "公开报道的品牌年 TIV 锚。Chery / Others 是演示残差。不是 MAA 原始明细。",
        "aliases": ["ods", "年锚", "公开报道", "820752", "锚"],
    },
    {
        "object_name": "dim.brand",
        "layer": "dim",
        "object_kind": "table",
        "table_name": "dim_brand",
        "grain": "brand",
        "owner": "demo.metrics",
        "version": "2026.08.2",
        "note": "品牌维。origin = national 仅 Perodua、Proton。",
        "aliases": ["品牌", "国产", "origin"],
    },
    {
        "object_name": "dim.model",
        "layer": "dim",
        "object_kind": "table",
        "table_name": "dim_model",
        "grain": "model",
        "owner": "demo.metrics",
        "version": "2026.08.2",
        "note": "车型维。能源 ice / hybrid / ev。",
        "aliases": ["车型", "能源", "ev"],
    },
    {
        "object_name": "dim.region",
        "layer": "dim",
        "object_kind": "table",
        "table_name": "dim_region",
        "grain": "region",
        "owner": "demo.metrics",
        "version": "2026.08.2",
        "note": "区域维：巴生谷 / 柔佛 / 槟城 / 霹雳 / 沙巴 / 砂拉越 / 其他。",
        "aliases": ["区域", "州", "巴生谷"],
    },
    {
        "object_name": "dwd.fact_month",
        "layer": "dwd",
        "object_kind": "table",
        "table_name": "fact_month",
        "grain": "year, month, model, region",
        "owner": "demo.metrics",
        "version": "2026.08.2",
        "note": "明细事实表。tiv_units 与 registration_units 分列。月×区×车型是种子拆分。",
        "aliases": ["dwd", "明细", "fact_month", "哪张表", "从哪来", "溯源"],
    },
    {
        "object_name": "ads.brand_year",
        "layer": "ads",
        "object_kind": "table",
        "table_name": "ads_brand_year",
        "grain": "year, brand",
        "owner": "demo.metrics",
        "version": "2026.08.2",
        "note": "品牌年汇总。全年、无区域、无能源筛选时问品牌合计走这张表。",
        "aliases": ["ads", "汇总", "全年合计"],
    },
    {
        "object_name": "ads.brand_month",
        "layer": "ads",
        "object_kind": "table",
        "table_name": "ads_brand_month",
        "grain": "year, month, brand",
        "owner": "demo.metrics",
        "version": "2026.08.2",
        "note": "品牌月汇总。带车型或区域筛选时仍走 DWD。",
        "aliases": ["ads", "各月"],
    },
    {
        "object_name": "metric.tiv",
        "layer": "metric",
        "object_kind": "metric",
        "table_name": "fact_month",
        "grain": "year, month, brand/model/region",
        "owner": "demo.metrics",
        "version": "2026.08.1",
        "note": "协会口径批发（TIV-style）。列 tiv_units。问「销量」且未指定时不停在这套数上猜。",
        "aliases": ["tiv", "批发", "协会", "协会口径"],
    },
    {
        "object_name": "metric.registration",
        "layer": "metric",
        "object_kind": "metric",
        "table_name": "fact_month",
        "grain": "year, month, brand/model/region",
        "owner": "demo.metrics",
        "version": "2026.08.1",
        "note": "上牌 / 注册量。列 registration_units。与 TIV 允许对不上。",
        "aliases": ["上牌", "注册", "jpj", "registration"],
    },
    {
        "object_name": "metric.share",
        "layer": "metric",
        "object_kind": "metric",
        "table_name": None,
        "grain": "same as numerator",
        "owner": "demo.metrics",
        "version": "2026.08.1",
        "note": "份额。分子分母必须同一指标、同一时间、同一筛选。",
        "aliases": ["份额", "市占", "share"],
    },
    {
        "object_name": "metric.yoy",
        "layer": "metric",
        "object_kind": "metric",
        "table_name": None,
        "grain": "year vs year-1",
        "owner": "demo.metrics",
        "version": "2026.08.1",
        "note": "同比。(本期 − 去年同期) / 去年同期。去年为 0 则空。",
        "aliases": ["同比", "yoy"],
    },
    {
        "object_name": "metric.national",
        "layer": "metric",
        "object_kind": "metric",
        "table_name": "dim_brand",
        "grain": "brand.origin = national",
        "owner": "demo.metrics",
        "version": "2026.08.1",
        "note": "国产车仅 Perodua + Proton。不是「马来西亚生产的都算」。",
        "aliases": ["国产", "national", "宝腾"],
    },
    {
        "object_name": "doc.口径",
        "layer": "doc",
        "object_kind": "document",
        "table_name": None,
        "grain": None,
        "owner": "demo.metrics",
        "version": "2026.08.2",
        "note": "docs/口径.md。口径问句检索这篇，不走 SQL。",
        "aliases": ["口径", "owner", "版本", "定义"],
    },
    {
        "object_name": "doc.分层",
        "layer": "doc",
        "object_kind": "document",
        "table_name": None,
        "grain": None,
        "owner": "demo.metrics",
        "version": "2026.08.2",
        "note": "演示分层 ODS / DIM / DWD / ADS。不是企业 Atlas。",
        "aliases": ["分层", "数仓", "血缘", "几层"],
    },
]

EDGES: list[dict] = [
    {
        "src": "ods.brand_year_anchor",
        "dst": "dwd.fact_month",
        "transform": "年合计按固定种子拆到月×车型×区域；上牌列再按区域偏置。演示拆分，不是协会明细。",
        "grain": "year,brand → year,month,model,region",
    },
    {
        "src": "dim.brand",
        "dst": "dwd.fact_month",
        "transform": "经 dim_model.brand_id 关联。",
        "grain": "brand_id",
    },
    {
        "src": "dim.model",
        "dst": "dwd.fact_month",
        "transform": "fact_month.model_id = dim_model.model_id",
        "grain": "model_id",
    },
    {
        "src": "dim.region",
        "dst": "dwd.fact_month",
        "transform": "fact_month.region_id = dim_region.region_id",
        "grain": "region_id",
    },
    {
        "src": "dwd.fact_month",
        "dst": "ads.brand_year",
        "transform": "SUM(tiv_units), SUM(registration_units) GROUP BY year, brand_id",
        "grain": "year, brand",
    },
    {
        "src": "dwd.fact_month",
        "dst": "ads.brand_month",
        "transform": "SUM GROUP BY year, month, brand_id",
        "grain": "year, month, brand",
    },
    {
        "src": "dwd.fact_month",
        "dst": "metric.tiv",
        "transform": "列 tiv_units",
        "grain": "same as fact",
    },
    {
        "src": "ads.brand_year",
        "dst": "metric.tiv",
        "transform": "全年品牌合计可走汇总，避免扫月×区×车型。",
        "grain": "year, brand",
    },
    {
        "src": "dwd.fact_month",
        "dst": "metric.registration",
        "transform": "列 registration_units",
        "grain": "same as fact",
    },
    {
        "src": "ads.brand_year",
        "dst": "metric.registration",
        "transform": "全年品牌上牌合计可走汇总。",
        "grain": "year, brand",
    },
    {
        "src": "metric.tiv",
        "dst": "metric.share",
        "transform": "份额分子分母同一指标。选中 TIV 时用 tiv_units。",
        "grain": "same filter",
    },
    {
        "src": "metric.registration",
        "dst": "metric.share",
        "transform": "选中上牌时用 registration_units。",
        "grain": "same filter",
    },
    {
        "src": "metric.tiv",
        "dst": "metric.yoy",
        "transform": "(本年 − 去年) / 去年，同一指标。",
        "grain": "year vs year-1",
    },
    {
        "src": "metric.registration",
        "dst": "metric.yoy",
        "transform": "(本年 − 去年) / 去年，同一指标。",
        "grain": "year vs year-1",
    },
    {
        "src": "dim.brand",
        "dst": "metric.national",
        "transform": "origin = national（Perodua、Proton）",
        "grain": "brand",
    },
    {
        "src": "doc.口径",
        "dst": "metric.tiv",
        "transform": "口径文档约束 TIV 定义与 HITL。",
        "grain": None,
    },
    {
        "src": "doc.口径",
        "dst": "metric.registration",
        "transform": "口径文档约束上牌定义。",
        "grain": None,
    },
    {
        "src": "doc.分层",
        "dst": "ods.brand_year_anchor",
        "transform": "分层说明指向 ODS 年锚。",
        "grain": None,
    },
    {
        "src": "doc.分层",
        "dst": "dwd.fact_month",
        "transform": "分层说明指向 DWD 明细。",
        "grain": None,
    },
    {
        "src": "doc.分层",
        "dst": "ads.brand_year",
        "transform": "分层说明指向 ADS 汇总。",
        "grain": None,
    },
]

_NODE = {n["object_name"]: n for n in NODES}
_UP: dict[str, list[dict]] = {}
for _e in EDGES:
    _UP.setdefault(_e["dst"], []).append(_e)


def node(name: str) -> dict | None:
    n = _NODE.get(name)
    if not n:
        return None
    return {k: v for k, v in n.items() if k != "aliases"}


def walk_upstream(object_name: str, max_nodes: int = 24) -> dict:
    """Sources that feed this object. BFS, table-level only."""
    if object_name not in _NODE:
        return {"focus": [object_name], "nodes": [], "edges": [], "path": []}
    seen_n = {object_name}
    nodes = [node(object_name)]
    edges: list[dict] = []
    seen_e: set[tuple[str, str]] = set()
    queue = [object_name]
    while queue and len(nodes) < max_nodes:
        cur = queue.pop(0)
        for e in _UP.get(cur, []):
            k = (e["src"], e["dst"])
            if k in seen_e:
                continue
            seen_e.add(k)
            edges.append(e)
            if e["src"] not in seen_n:
                seen_n.add(e["src"])
                n = node(e["src"])
                if n:
                    nodes.append(n)
                queue.append(e["src"])
    nodes.sort(key=lambda n: (LAYER_ORDER.get(n["layer"], 9), n["object_name"]))
    path = [n["object_name"] for n in nodes]
    return {"focus": [object_name], "nodes": nodes, "edges": edges, "path": path}


def merge_walks(object_names: list[str]) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen_e: set[tuple[str, str]] = set()
    focus = []
    for name in object_names:
        if name not in _NODE:
            continue
        focus.append(name)
        w = walk_upstream(name)
        for n in w["nodes"]:
            nodes[n["object_name"]] = n
        for e in w["edges"]:
            k = (e["src"], e["dst"])
            if k in seen_e:
                continue
            seen_e.add(k)
            edges.append(e)
    ordered = sorted(nodes.values(), key=lambda n: (LAYER_ORDER.get(n["layer"], 9), n["object_name"]))
    return {
        "focus": focus,
        "nodes": ordered,
        "edges": edges,
        "path": [n["object_name"] for n in ordered],
    }


def lineage_for_scan(metric: str | None, scan: str | None) -> dict:
    """Attach table-level lineage to a SQL answer."""
    focus = []
    if metric in ("tiv", "registration", "share", "yoy", "national"):
        focus.append("metric." + metric)
    if scan == "ads.brand_year":
        focus.append("ads.brand_year")
    elif scan == "ads.brand_month":
        focus.append("ads.brand_month")
    else:
        focus.append("dwd.fact_month")
    return merge_walks(focus)


def rows_for_seed() -> tuple[list[tuple], list[tuple]]:
    node_rows = [
        (
            n["object_name"],
            n["layer"],
            n["object_kind"],
            n.get("table_name"),
            n.get("grain"),
            n.get("owner"),
            n.get("version"),
            n.get("note"),
        )
        for n in NODES
    ]
    edge_rows = [
        (i + 1, e["src"], e["dst"], e["transform"], e.get("grain"))
        for i, e in enumerate(EDGES)
    ]
    return node_rows, edge_rows
