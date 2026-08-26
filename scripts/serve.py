# -*- coding: utf-8 -*-
"""Local page: question in, SQL + table + metric dict + lineage out. No cloud."""
from __future__ import annotations

import json
import sys
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from malaysia_ask.ask import ask  # noqa: E402
from malaysia_ask.db import seed  # noqa: E402

HTML = """<!doctype html>
<meta charset="utf-8">
<title>MY auto ask (demo)</title>
<style>
body{font-family:sans-serif;max-width:920px;margin:24px auto;padding:0 16px;color:#222}
input{width:70%%;padding:8px} button{padding:8px 14px}
pre{background:#f4f4f4;padding:10px;overflow:auto}
table{border-collapse:collapse} td,th{border:1px solid #ccc;padding:4px 8px}
.warn{background:#fff3cd;padding:10px;border:1px solid #e6d89a}
.note{color:#666;font-size:13px}
.ex a{margin-right:12px;font-size:13px}
.layer{display:inline-block;background:#e8eef6;padding:1px 6px;margin-right:4px;font-size:12px}
.hit{border-bottom:1px solid #eee;padding:8px 0}
.score{color:#888;font-size:12px}
</style>
<h1>马来西亚汽车问数（演示）</h1>
<p class="note">品牌全年合计锚定公开 TIV 报道；月×区×车型是种子拆分。不是 MAA 原始明细，不是吉利业务。分层 / 血缘 / 口径检索都是本机演示，不是企业 Atlas，不是向量 RAG。</p>
<p class="ex">
  <a href="/?q=2025全年协会口径TIV哪家第一">全年 TIV 谁第一</a>
  <a href="/?q=TIV和上牌有什么区别">TIV 和上牌</a>
  <a href="/?q=上牌数从哪张表来">数从哪张表来</a>
  <a href="/?q=数仓分哪几层">分哪几层</a>
</p>
<form>
  <input name="q" value="%(q)s" placeholder="2025全年协会口径TIV哪家第一">
  <button>问</button>
</form>
%(body)s
"""


def render_lineage(lin: dict | None) -> str:
    if not lin:
        return ""
    nodes = lin.get("nodes") or []
    edges = lin.get("edges") or []
    if not nodes:
        return ""
    parts = ["<h3>表级血缘</h3><p>"]
    parts.append(" → ".join(
        '<span class="layer">%s</span> %s' % (escape(n.get("layer") or ""), escape(n["object_name"]))
        for n in nodes
    ))
    parts.append("</p><table><tr><th>from</th><th>to</th><th>transform</th></tr>")
    for e in edges[:12]:
        parts.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (escape(e["src"]), escape(e["dst"]), escape(e.get("transform") or ""))
        )
    parts.append("</table>")
    return "".join(parts)


def render_hits(hits: list | None) -> str:
    if not hits:
        return ""
    parts = ["<h3>口径检索（词重叠，无向量库）</h3>"]
    for h in hits:
        parts.append(
            '<div class="hit"><b>%s</b> <span class="score">%s · %.2f</span><br>%s</div>'
            % (
                escape(h.get("title") or ""),
                escape(h.get("object") or ""),
                float(h.get("score") or 0),
                escape((h.get("text") or "")[:400]),
            )
        )
    return "".join(parts)


def render_body(r: dict) -> str:
    if r["hitl"]:
        return '<div class="warn"><b>需要人确认</b><br>%s</div>' % escape(r["hitl_reason"])
    if r.get("mode") == "retrieve":
        return render_hits(r.get("retrieve")) + render_lineage(r.get("lineage"))
    md = r.get("metric_dict") or {}
    scan = (r.get("trace") or {}).get("scan") or ""
    lines = [
        "<p><b>%s</b> · owner %s · version %s · scan %s</p>"
        % (
            escape(md.get("display_name", "")),
            escape(md.get("owner", "")),
            escape(md.get("version", "")),
            escape(scan),
        ),
        "<p>%s</p>" % escape(md.get("definition", "")),
        "<pre>%s</pre>" % escape(r.get("sql") or ""),
        "<table><tr>",
    ]
    rows = r.get("rows") or []
    if not rows:
        return "".join(lines) + "</tr></table><p>无结果</p>" + render_lineage(r.get("lineage"))
    keys = list(rows[0].keys())
    lines.append("".join("<th>%s</th>" % escape(k) for k in keys) + "</tr>")
    for row in rows[:20]:
        lines.append("<tr>" + "".join("<td>%s</td>" % escape(str(row[k])) for k in keys) + "</tr>")
    lines.append("</table>")
    return "".join(lines) + render_lineage(r.get("lineage"))


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path not in ("/", "/ask"):
            self.send_error(404)
            return
        qs = parse_qs(u.query)
        q = (qs.get("q") or [""])[0]
        want_json = (qs.get("format") or [""])[0] == "json"
        if want_json:
            payload = json.dumps(ask(q) if q else {}, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        body = ""
        if q:
            body = render_body(ask(q))
        html = HTML % {"q": escape(q, quote=True), "body": body}
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(fmt % args)


if __name__ == "__main__":
    seed()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    print("http://127.0.0.1:%s" % port)
    HTTPServer(("127.0.0.1", port), H).serve_forever()
