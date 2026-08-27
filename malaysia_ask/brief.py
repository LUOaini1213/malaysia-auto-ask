# -*- coding: utf-8 -*-
"""Draft a note for an overseas desk. Never send by itself. HITL copy only."""
from __future__ import annotations

from typing import Any

from .ask import ask


HEADER = (
    "【演示稿 · 须人确认后才能发给一线】\n"
    "数据是马来西亚公开 TIV 年锚 + 种子拆分，不是 MAA/JPJ 原始明细，不是吉利业务。\n"
)


def _table_lines(rows: list[dict], limit: int = 8) -> str:
    if not rows:
        return "（无出数）"
    keys = list(rows[0].keys())
    lines = [" | ".join(keys)]
    for row in rows[:limit]:
        lines.append(" | ".join(str(row[k]) for k in keys))
    return "\n".join(lines)


def draft_from_result(question: str, result: dict[str, Any]) -> dict[str, Any]:
    """Turn an ask() result into a desk note. HITL questions produce no draft."""
    out = {
        "question": question,
        "blocked": False,
        "reason": "",
        "draft": None,
        "needs_confirm": True,
        "mode": result.get("mode"),
    }
    if result.get("hitl"):
        out["blocked"] = True
        out["reason"] = result.get("hitl_reason") or "口径不清，不能起草。"
        out["draft"] = None
        return out

    md = result.get("metric_dict") or {}
    body = [HEADER, "问句：" + question.strip()]
    if md:
        body.append(
            "口径：%s。owner %s。version %s。"
            % (md.get("display_name") or md.get("metric_key") or "", md.get("owner") or "", md.get("version") or "")
        )
        if md.get("definition"):
            body.append("定义：" + md["definition"])

    if result.get("mode") == "retrieve":
        hits = result.get("retrieve") or []
        body.append("口径检索（词重叠，无向量库）：")
        for h in hits[:3]:
            body.append("- %s（%s）" % (h.get("title") or "", h.get("object") or ""))
        path = (result.get("lineage") or {}).get("path") or []
        if path:
            body.append("血缘：" + " → ".join(path[:8]))
        body.append("\n请确认口径后再转发。不要改数字、不要补库外市场。")
        out["draft"] = "\n".join(body)
        return out

    scan = (result.get("trace") or {}).get("scan") or ""
    if scan:
        body.append("扫描表：" + scan)
    if result.get("sql"):
        body.append("SQL（白名单模板）：" + result["sql"])
    body.append("结果：")
    body.append(_table_lines(result.get("rows") or []))
    lin = (result.get("lineage") or {}).get("path") or []
    if lin:
        body.append("表级血缘：" + " → ".join(lin[:8]))
    body.append("\n请核对口径和年份后再发给海外销售/售后。未确认不得当作官方数。")
    out["draft"] = "\n".join(body)
    return out


def draft_note(question: str, db_path=None) -> dict[str, Any]:
    r = ask(question, db_path=db_path)
    pack = draft_from_result(question, r)
    pack["ask"] = r
    return pack
