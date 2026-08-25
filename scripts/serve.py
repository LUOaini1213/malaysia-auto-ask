# -*- coding: utf-8 -*-
"""Local page: question in, SQL + table + metric dict out. No cloud."""
from __future__ import annotations

import json
import sys
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
body{font-family:sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#222}
input{width:70%;padding:8px} button{padding:8px 14px}
pre{background:#f4f4f4;padding:10px;overflow:auto}
table{border-collapse:collapse} td,th{border:1px solid #ccc;padding:4px 8px}
.warn{background:#fff3cd;padding:10px;border:1px solid #e6d89a}
.note{color:#666;font-size:13px}
</style>
<h1>马来西亚汽车问数（演示）</h1>
<p class="note">品牌全年合计锚定公开 TIV 报道；月×区×车型是种子拆分。不是 MAA 原始明细，不是吉利业务。</p>
<form>
  <input name="q" value="%(q)s" placeholder="2025全年协会口径TIV哪家第一">
  <button>问</button>
</form>
%(body)s
"""


def render_body(r: dict) -> str:
    if r["hitl"]:
        return '<div class="warn"><b>需要人确认</b><br>%s</div>' % r["hitl_reason"]
    md = r.get("metric_dict") or {}
    lines = [
        "<p><b>%s</b> · owner %s · version %s</p>" % (md.get("display_name", ""), md.get("owner", ""), md.get("version", "")),
        "<p>%s</p>" % md.get("definition", ""),
        "<pre>%s</pre>" % (r.get("sql") or ""),
        "<table><tr>",
    ]
    rows = r.get("rows") or []
    if not rows:
        return "".join(lines) + "</tr></table><p>无结果</p>"
    keys = list(rows[0].keys())
    lines.append("".join("<th>%s</th>" % k for k in keys) + "</tr>")
    for row in rows[:20]:
        lines.append("<tr>" + "".join("<td>%s</td>" % row[k] for k in keys) + "</tr>")
    lines.append("</table>")
    return "".join(lines)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path not in ("/", "/ask"):
            self.send_error(404)
            return
        q = (parse_qs(u.query).get("q") or [""])[0]
        body = ""
        if q:
            body = render_body(ask(q))
        html = HTML % {"q": q.replace('"', "&quot;"), "body": body}
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
