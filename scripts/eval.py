# -*- coding: utf-8 -*-
"""30 题问数评测 + 8 条口径检索评测。

    python scripts/eval.py           # 重跑并写 eval/last_run.json
    python scripts/eval.py --check   # 重跑但不写文件，与已提交的 eval/last_run.json
                                     # 逐字段比对，漂移则退出 1

--check 是给 CI 用的：仓里提交的 eval/last_run.json 是面试官在 GitHub 网页上
真正会读到的那份，它必须和当前代码跑出来的结果逐字段相同。比对复用
scripts/ablation.py 的 _compare，两份评测产物用同一套判定。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ablation import _compare  # noqa: E402  (scripts/ablation.py)
from malaysia_ask.ask import ask  # noqa: E402
from malaysia_ask.db import seed  # noqa: E402

OUT = ROOT / "eval" / "last_run.json"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    check = "--check" in argv
    seed()
    cases = json.loads((ROOT / "eval" / "cases.json").read_text(encoding="utf-8"))
    rows = []
    n = len(cases)
    n_hitl = 0
    n_expect_ans = 0
    n_ans_ok = 0
    n_tpl_ok = 0
    n_hitl_ok = 0

    for c in cases:
        r = ask(c["q"])
        expect_hitl = bool(c.get("expect_hitl"))
        got_hitl = bool(r["hitl"])
        if got_hitl:
            n_hitl += 1
        hitl_ok = got_hitl == expect_hitl
        if expect_hitl:
            if hitl_ok:
                n_hitl_ok += 1
            rows.append({"id": c["id"], "ok": hitl_ok, "mode": "hitl", "q": c["q"]})
            continue
        n_expect_ans += 1
        tpl_ok = r.get("template_id") == c.get("template_id") and r.get("metric") == c.get("metric")
        if tpl_ok:
            for k in ("year", "month", "brand_id", "region_id", "energy", "origin"):
                if k in c and r["params"].get(k) != c.get(k):
                    tpl_ok = False
                    break
        top_ok = True
        if c.get("top_name") and r.get("rows"):
            top_ok = r["rows"][0].get("name") == c["top_name"]
        ans_ok = (not got_hitl) and tpl_ok and top_ok and bool(r.get("rows"))
        if tpl_ok:
            n_tpl_ok += 1
        if ans_ok:
            n_ans_ok += 1
        rows.append(
            {
                "id": c["id"],
                "ok": ans_ok,
                "tpl_ok": tpl_ok,
                "mode": "sql",
                "q": c["q"],
                "template": r.get("template_id"),
                "n_rows": len(r.get("rows") or []),
            }
        )

    retrieve_cases = json.loads((ROOT / "eval" / "retrieve_cases.json").read_text(encoding="utf-8"))
    retrieve_rows = []
    n_ret_ok = 0
    for c in retrieve_cases:
        r = ask(c["q"])
        objs = set()
        for h in r.get("retrieve") or []:
            if h.get("object"):
                objs.add(h["object"])
        for name in (r.get("lineage") or {}).get("path") or []:
            objs.add(name)
        ok = (not r.get("hitl")) and r.get("task") == "retrieve" and any(
            x in objs for x in c.get("expect_objects") or []
        )
        if ok:
            n_ret_ok += 1
        retrieve_rows.append(
            {
                "id": c["id"],
                "ok": ok,
                "mode": "retrieve",
                "q": c["q"],
                "objects": sorted(objs)[:12],
            }
        )

    n_ret = len(retrieve_cases)
    summary = {
        "n": n,
        "success_rate": round(n_ans_ok / n_expect_ans, 4) if n_expect_ans else 0,
        "accuracy": round(n_tpl_ok / n_expect_ans, 4) if n_expect_ans else 0,
        "hitl_rate": round(n_hitl / n, 4),
        "n_expect_answer": n_expect_ans,
        "n_answer_ok": n_ans_ok,
        "n_template_ok": n_tpl_ok,
        "n_hitl": n_hitl,
        "n_hitl_expected_ok": n_hitl_ok,
        "hitl_precision_on_expected": round(n_hitl_ok / 8, 4),
        "retrieve": {
            "n": n_ret,
            "n_ok": n_ret_ok,
            "success_rate": round(n_ret_ok / n_ret, 4) if n_ret else 0,
            "method": "token-overlap",
        },
    }
    payload = {"summary": summary, "rows": rows, "retrieve_rows": retrieve_rows}
    drifted = False
    if check:
        committed = json.loads(OUT.read_text(encoding="utf-8"))
        problems = _compare(payload, committed)
        for p in problems[:20]:
            print("DRIFT:", p)
        print("ok: eval/last_run.json matches a fresh run" if not problems else
              f"{len(problems)} differences between a fresh run and eval/last_run.json")
        drifted = bool(problems)
    else:
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    bad = [x for x in rows if not x["ok"]] + [x for x in retrieve_rows if not x["ok"]]
    if bad:
        print("failed", [x["id"] for x in bad])
    passed = n_ans_ok == n_expect_ans and n_hitl_ok == 8 and n_ret_ok == n_ret
    return 0 if passed and not drifted else 1


if __name__ == "__main__":
    raise SystemExit(main())
