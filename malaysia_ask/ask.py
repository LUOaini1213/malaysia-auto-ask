# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from .db import connect, seed, DB_PATH, METRICS
from .intent import Intent, parse
from .templates import render


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


def ask(question: str, db_path=None) -> dict[str, Any]:
    path = db_path or DB_PATH
    if not path.exists():
        seed(path)
    intent = parse(question)
    out: dict[str, Any] = {
        "question": question,
        "hitl": intent.hitl,
        "hitl_reason": intent.hitl_reason,
        "task": intent.task,
        "metric": intent.metric,
        "params": intent.params(),
        "sql": None,
        "rows": [],
        "metric_dict": metric_row(intent.metric) if intent.metric else None,
        "trace": {
            "parser": "rules",
            "whitelist": True,
            "notes": intent.notes,
        },
    }
    if intent.hitl or not intent.task or not intent.metric:
        return out

    sql = render(intent.task, intent.metric)
    params = intent.params()
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
    return out
