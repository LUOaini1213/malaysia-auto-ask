# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from .db import connect, seed, DB_PATH, METRICS
from .intent import parse
from .lineage import lineage_for_scan
from .retrieve import retrieve
from .templates import render, scan_for


def metric_row(key: str) -> dict:
    for m in METRICS:
        if m[0] == key:
            return {
                "metric_key": m[0],
                "display_name": m[1],
                "definition": m[2],
                "grain": m[3],
                "owner": m[4],
                "version": m[5],
            }
    return {}


def ask(question: str, db_path=None, force: bool = False) -> dict[str, Any]:
    """force=True 关掉停问护栏，按朴素默认强行作答（消融实验用）。"""
    path = db_path or DB_PATH
    if not path.exists():
        seed(path)
    intent = parse(question, force=force)
    out: dict[str, Any] = {
        "question": question,
        "hitl": intent.hitl,
        "hitl_reason": intent.hitl_reason,
        "hitl_code": intent.hitl_code,
        "guesses": list(intent.guesses),
        "forced": bool(force),
        "task": intent.task,
        "metric": intent.metric,
        "params": intent.params(),
        "sql": None,
        "rows": [],
        "metric_dict": metric_row(intent.metric) if intent.metric else None,
        "retrieve": None,
        "lineage": None,
        "mode": "hitl" if intent.hitl else None,
        "trace": {
            "parser": "rules",
            "whitelist": True,
            "notes": intent.notes,
        },
    }
    if intent.task == "retrieve":
        pack = retrieve(question)
        out["mode"] = "retrieve"
        out["retrieve"] = pack["hits"]
        out["lineage"] = pack["lineage"]
        out["trace"]["retrieve_method"] = pack["method"]
        out["trace"]["notes"].append(pack["note"])
        return out
    if intent.hitl or not intent.task or not intent.metric:
        out["mode"] = "hitl"
        return out

    params = intent.params()
    scan = scan_for(intent.task, params)
    sql = render(intent.task, intent.metric, scan)
    if intent.task == "yoy_brand":
        params["year_ly"] = (intent.year or 0) - 1
    conn = connect(path)
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    out["sql"] = " ".join(sql.split())
    out["rows"] = rows
    out["template_id"] = intent.task
    out["mode"] = "sql"
    out["trace"]["scan"] = scan
    out["lineage"] = lineage_for_scan(intent.metric, scan)
    return out
