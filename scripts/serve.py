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
from malaysia_ask.brief import draft_note  # noqa: E402
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
<p class="note">品牌全年合计锚定公开 TIV 报道；月×区×车型是固定种子拆分的演示数据。分层 / 血缘 / 口径检索都在本机 SQLite 上跑，口径检索走词重叠。</p>
<p class="ex">
  <a href="/desk">海外一线工作台</a>
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


DESK = """<!doctype html>
<meta charset="utf-8">
<title>MY overseas desk (demo)</title>
<style>
body{font-family:sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#222}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
.card{background:#f4f7fb;border:1px solid #d5dee8;padding:12px 14px;min-width:180px}
.card .k{color:#666;font-size:12px}.card .v{font-size:22px;font-weight:700}
.warn{background:#fff3cd;padding:10px;border:1px solid #e6d89a}
.note{color:#666;font-size:13px}
input{width:62%%;padding:8px} button{padding:8px 14px}
pre{background:#f4f4f4;padding:10px;overflow:auto;white-space:pre-wrap}
.path{font-size:13px;color:#334}
a{margin-right:10px}
</style>
<h1>海外一线工作台（演示）</h1>
<p class="note">给区域销售看年锚、问数、复制说明草稿。草稿必须勾选确认才能复制。</p>
<p><a href="/">问数页</a><a href="/desk">刷新看板</a></p>
<div class="cards">%(cards)s</div>
<p class="path">用户路径：看板 → 问句 → 出数或停问 → 人确认 → 复制草稿。见 docs/产品PRD.md</p>
<form>
  <input name="q" value="%(q)s" placeholder="2025全年协会口径TIV哪家第一">
  <button>问并起草</button>
</form>
%(body)s
"""


def kpi_cards() -> str:
    seed()
    rank = ask("2025全年协会口径TIV哪家第一")
    share = ask("2025年Perodua TIV份额")
    split = ask("2025全年国产车和非国产车TIV")
    top = (rank.get("rows") or [{}])[0]
    sh = (share.get("rows") or [{}])[0]
    nat = next((r for r in (split.get("rows") or []) if r.get("name") == "national"), {})
    items = [
        ("2025 TIV 第一名", str(top.get("name") or "—"), str(top.get("units") or "") + " 辆"),
        ("Perodua TIV 份额", str(sh.get("share_pct") or "—") + "%", "同一指标、全年"),
        ("国产 origin=national", str(nat.get("units") or "—"), "仅 Perodua + Proton"),
    ]
    html = []
    for k, v, sub in items:
        html.append(
            '<div class="card"><div class="k">%s</div><div class="v">%s</div><div class="k">%s</div></div>'
            % (escape(k), escape(v), escape(sub))
        )
    return "".join(html)


def render_desk_body(q: str) -> str:
    if not q:
        return "<p class=\"note\">问一句再起草。例：2025全年协会口径TIV哪家第一；TIV和上牌有什么区别；2025谁卖得最好。</p>"
    pack = draft_note(q)
    parts = [render_body(pack["ask"])]
    if pack.get("blocked"):
        parts.append(
            '<div class="warn"><b>不起草</b><br>%s<br>口径不清或库外市场，不能发给一线。</div>'
            % escape(pack.get("reason") or "")
        )
        return "".join(parts)
    parts.append("<h3>给海外同事的说明草稿</h3>")
    parts.append("<pre id=\"draft\">%s</pre>" % escape(pack.get("draft") or ""))
    parts.append(
        '<p><label><input type="checkbox" id="ok" onchange="document.getElementById(\'copy\').disabled=!this.checked"> '
        "我已核对口径和年份，确认后复制</label> "
        '<button id="copy" type="button" disabled '
        "onclick=\"navigator.clipboard.writeText(document.getElementById('draft').innerText)\">复制草稿</button></p>"
    )
    return "".join(parts)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path not in ("/", "/ask", "/desk"):
            self.send_error(404)
            return
        qs = parse_qs(u.query)
        q = (qs.get("q") or [""])[0]
        want_json = (qs.get("format") or [""])[0] == "json"
        if want_json:
            payload = json.dumps(
                draft_note(q) if (u.path == "/desk" and q) else (ask(q) if q else {}),
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if u.path == "/desk":
            html = DESK % {
                "cards": kpi_cards(),
                "q": escape(q, quote=True),
                "body": render_desk_body(q),
            }
        else:
            body = render_body(ask(q)) if q else ""
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
    print("desk http://127.0.0.1:%s/desk" % port)
    HTTPServer(("127.0.0.1", port), H).serve_forever()
