"""Run real MySQL acceptance and retain sanitized, reproducible evidence."""
from __future__ import annotations

import io
import json
import unittest
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .common import ARTIFACTS, ROOT, connect
from .queries import get_catalog, prepare_query, query
from .store import load_snapshot


def verify_queries(catalog, oracle):
    checks = []
    months = catalog["available_months"]
    bounds = {"start_month": months[0], "end_month": months[-1]}
    def check(name, actual, expected):
        if actual != expected:
            raise AssertionError(f"CROSS_ENGINE_MISMATCH: {name}")
        checks.append({"query": name, "rows": len(actual), "passed": True})
    monthly = [{"year_month": k[1]+"-"+k[2], "registrations": v}
               for k,v in sorted(oracle.items()) if k[0] == "month"]
    check("monthly_all", query("monthly_registrations", bounds)["rows"], monthly)
    for maker in catalog["makers"]:
        counts = defaultdict(int)
        for k, v in oracle.items():
            if k[0] == "month_maker" and k[2].strip().upper() == maker:
                counts[k[1]] += v
        expected = [{"year_month": m, "registrations": counts[m]} for m in months]
        check("monthly_maker:"+maker, query("monthly_registrations", {**bounds,"maker":maker})["rows"], expected)
    for fuel in catalog["fuels"]:
        expected = [{"year_month":m,"fuel":fuel,"registrations":oracle.get(("month_fuel",m,fuel),0)} for m in months]
        check("monthly_fuel:"+fuel, query("fuel_monthly",{**bounds,"fuel":fuel})["rows"], expected)
    fuels = [{"year_month":k[1],"fuel":k[2],"registrations":v} for k,v in sorted(oracle.items()) if k[0]=="month_fuel"]
    check("all_month_fuels",query("fuel_monthly",bounds)["rows"],fuels)
    for start, end in [(months[0],months[-1]),("2026-01","2026-08"),("2025-06","2025-07")]:
        totals = defaultdict(int)
        for k,v in oracle.items():
            if k[0]=="month_maker" and start <= k[1] <= end:
                totals[k[2].strip().upper()] += v
        ranked = [{"maker":m,"registrations":n} for m,n in sorted(totals.items(),key=lambda x:(-x[1],x[0]))]
        p = {"start_month":start,"end_month":end}
        check(f"ranking:{start}:{end}",query("maker_ranking",{**p,"limit":30})["rows"],ranked[:30])
        expected = [{"maker":m,"registrations":totals[m]} for m in ["BYD","TESLA"]]
        expected.sort(key=lambda r:(-r["registrations"],r["maker"]))
        check(f"brand_compare:{start}:{end}",query("brand_compare",{**p,"makers":["BYD","TESLA"]})["rows"],expected)
    return checks


def capture_plans(catalog):
    plans=[]
    examples=[("monthly_registrations",{"start_month":"2026-01","end_month":"2026-08"}),
              ("monthly_registrations",{"start_month":"2026-01","end_month":"2026-08","maker":"BMW"}),
              ("brand_compare",{"start_month":"2026-01","end_month":"2026-08","makers":["BYD","TESLA"]}),
              ("maker_ranking",{"start_month":"2026-01","end_month":"2026-08","limit":10}),
              ("fuel_monthly",{"start_month":"2026-01","end_month":"2026-08","fuel":"electric"})]
    with connect() as c,c.cursor() as cur:
        cur.execute("SHOW CREATE TABLE aggregates"); schema=cur.fetchone()["Create Table"]
        cur.execute("SHOW INDEX FROM aggregates"); indexes=cur.fetchall()
        cur.execute("SHOW GRANTS"); grants=cur.fetchall()
        cur.execute("SELECT VERSION() AS version"); version=cur.fetchone()["version"]
        for query_id, parameters in examples:
            p,sql,args,_=prepare_query(query_id,parameters,catalog)
            cur.execute("EXPLAIN FORMAT=JSON "+sql,args)
            plan=json.loads(cur.fetchone()["EXPLAIN"])
            cur.execute("EXPLAIN ANALYZE "+sql,args)
            actual=next(iter(cur.fetchone().values()))
            plans.append({"query_id":query_id,"parameters":p,"sql":sql,"sql_bindings":args,"explain_json":plan,"explain_analyze":actual})
    return {"mysql_version":version,"schema":schema,"indexes":indexes,"reader_grants":grants,"plans":plans,
            "interpretation":"Actual plans for 1536 aggregate rows. These are inspection evidence, not a benchmark or an index speedup claim."}


def main():
    import os
    os.environ["JPJ_MYSQL_INTEGRATION"]="1"
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.discover(str(Path(__file__).with_name("tests")))
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (ARTIFACTS/"tests.txt").write_text(stream.getvalue(),encoding="utf-8")
    if not result.wasSuccessful() or result.skipped:
        raise RuntimeError("Tests failed or were skipped; see tests.txt")
    source,oracle=load_snapshot(); catalog=get_catalog()
    with connect() as c,c.cursor() as cur:
        cur.execute("SELECT dimension,key1,key2,registrations FROM aggregates WHERE version=%s",(source["version"],))
        actual={(r["dimension"],r["key1"],r["key2"]):r["registrations"] for r in cur.fetchall()}
    if actual != oracle: raise AssertionError("MySQL/Hive/Python aggregate mismatch")
    checks=verify_queries(catalog,oracle)
    plans=capture_plans(catalog)
    (ARTIFACTS/"schema_and_explain.json").write_text(json.dumps(plans,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    report={"status":"passed","executed_at_utc":datetime.now(timezone.utc).isoformat(),
            "command":"python -m warehouse.serving.verify","mysql_version":plans["mysql_version"],
            "source":source,"tests":{"run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped)},
            "exact_hive_python_mysql_groups":len(oracle),"query_reconciliations":checks,
            "query_reconciliation_count":len(checks),"explain_cases":len(plans["plans"]),
            "scope":"Frozen aggregate serving; MySQL does not store the 1436804 registration detail rows."}
    (ARTIFACTS/"acceptance.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ["status","mysql_version","tests","exact_hive_python_mysql_groups","query_reconciliation_count","explain_cases"]},indent=2))


if __name__=="__main__":main()
