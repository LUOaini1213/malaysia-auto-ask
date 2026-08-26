# -*- coding: utf-8 -*-
"""Metric-doc retrieval: token overlap over 口径.md + metric_dict + lineage nodes.

Not a vector DB, not embeddings, not an enterprise RAG product.
"""
from __future__ import annotations

import re
from pathlib import Path

from .db import METRICS
from .lineage import NODES, merge_walks

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "口径.md"

_STOP = {
    "的", "了", "是", "在", "和", "与", "或", "及", "把", "被", "对", "从", "到",
    "有", "没有", "请", "问", "什么", "怎么", "如何", "哪", "这个", "那个",
    "a", "an", "the", "of", "to", "for", "in", "on", "is", "are",
}


def tokenize(text: str) -> set[str]:
    low = (text or "").lower()
    out: set[str] = set()
    for w in re.findall(r"[a-z0-9_]+", low):
        if w not in _STOP and len(w) > 1:
            out.add(w)
    for han in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        if han in _STOP:
            continue
        out.add(han)
        if len(han) >= 2:
            for i in range(len(han) - 1):
                bg = han[i : i + 2]
                if bg not in _STOP:
                    out.add(bg)
    return out


def _md_sections() -> list[dict]:
    if not DOCS.exists():
        return []
    raw = DOCS.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## ", raw)
    chunks = []
    preamble = parts[0].strip()
    if preamble:
        chunks.append(
            {
                "id": "doc:口径",
                "object": "doc.口径",
                "kind": "doc",
                "title": "口径",
                "text": preamble,
                "aliases": ["口径", "owner", "版本", "demo.metrics"],
            }
        )
    for part in parts[1:]:
        lines = part.strip().splitlines()
        if not lines:
            continue
        heading = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        obj = "doc.分层" if heading in ("分层", "血缘") else "doc.口径"
        aliases = [heading]
        if heading in ("分层", "血缘"):
            aliases += ["分层", "数仓", "ods", "dwd", "ads", "血缘", "溯源", "几层"]
        if heading == "tiv":
            aliases += ["tiv", "批发", "协会"]
        if heading == "registration":
            aliases += ["上牌", "注册", "jpj"]
        if heading == "share":
            aliases += ["份额", "市占"]
        if heading == "national":
            aliases += ["国产"]
        chunks.append(
            {
                "id": "doc:" + heading,
                "object": obj,
                "kind": "doc",
                "title": heading,
                "text": body,
                "aliases": aliases,
            }
        )
    return chunks


def _metric_chunks() -> list[dict]:
    chunks = []
    extra = {
        "tiv": ["tiv", "批发", "协会", "协会口径"],
        "registration": ["上牌", "注册", "jpj", "registration"],
        "share": ["份额", "市占", "share", "怎么算"],
        "yoy": ["同比", "yoy"],
        "national": ["国产", "national", "宝腾"],
    }
    for m in METRICS:
        key, name, definition, grain, owner, version = m
        chunks.append(
            {
                "id": "metric:" + key,
                "object": "metric." + key,
                "kind": "metric",
                "title": name,
                "text": "%s 粒度 %s。owner %s。version %s。" % (definition.rstrip("。."), grain, owner, version),
                "aliases": extra.get(key, [key]),
            }
        )
    return chunks


def _node_chunks() -> list[dict]:
    chunks = []
    for n in NODES:
        chunks.append(
            {
                "id": "node:" + n["object_name"],
                "object": n["object_name"],
                "kind": "lineage_node",
                "title": n["object_name"],
                "text": "%s 层 %s。表 %s。%s" % (
                    (n.get("note") or "").rstrip("。."),
                    n["layer"],
                    n.get("table_name") or "无",
                    n.get("grain") or "",
                ),
                "aliases": n.get("aliases") or [],
            }
        )
    return chunks


def chunks() -> list[dict]:
    return _md_sections() + _metric_chunks() + _node_chunks()


def _score(query: str, chunk: dict) -> float:
    q = query.lower()
    boost = 0.0
    for a in chunk.get("aliases") or []:
        if a.lower() in q:
            boost += 2.0
    title = (chunk.get("title") or "").lower()
    if title and title in q:
        boost += 1.5
    qt = tokenize(query)
    ct = tokenize((chunk.get("title") or "") + " " + (chunk.get("text") or ""))
    if not qt or not ct:
        return boost
    inter = qt & ct
    return boost + len(inter) / (len(qt) ** 0.5)


def search(question: str, k: int = 5) -> list[dict]:
    q = (question or "").strip()
    if not q:
        return []
    scored = []
    for ch in chunks():
        s = _score(q, ch)
        if s <= 0:
            continue
        scored.append(
            {
                "id": ch["id"],
                "object": ch["object"],
                "kind": ch["kind"],
                "title": ch["title"],
                "text": ch["text"],
                "score": round(s, 4),
            }
        )
    scored.sort(key=lambda x: (-x["score"], x["id"]))
    return scored[:k]


def infer_focus(question: str, hits: list[dict] | None = None) -> list[str]:
    q = question or ""
    low = q.lower()
    focus: list[str] = []
    if re.search(r"上牌|注册|jpj|registration", low):
        focus.append("metric.registration")
    if "tiv" in low or re.search(r"批发|协会", low):
        focus.append("metric.tiv")
    if re.search(r"份额|市占|share", low):
        focus.append("metric.share")
    if re.search(r"同比|yoy", low):
        focus.append("metric.yoy")
    if re.search(r"国产|national", low):
        focus.append("metric.national")
    if re.search(r"数仓|分层|血缘|ods|dwd|ads|从哪|哪张表|溯源|几层", low):
        focus.extend(["dwd.fact_month", "ods.brand_year_anchor", "ads.brand_year", "doc.分层"])
    if re.search(r"口径|owner|版本|定义", low):
        focus.append("doc.口径")
    if not focus and hits:
        for h in hits[:3]:
            if h.get("object"):
                focus.append(h["object"])
    # unique, keep order
    seen = set()
    out = []
    for x in focus:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def retrieve(question: str, k: int = 5) -> dict:
    hits = search(question, k=k)
    focus = infer_focus(question, hits)
    return {
        "hits": hits,
        "lineage": merge_walks(focus),
        "method": "token-overlap",
        "note": "词重叠检索，无向量库、无外部模型。",
    }
