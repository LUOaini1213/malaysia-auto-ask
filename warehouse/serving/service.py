"""Loopback-only JPJ real-data UI/API; explicit legacy simulation at /demo."""
from __future__ import annotations

import argparse
import json
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pymysql

from .common import QueryError
from .queries import get_catalog, query, route_question


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise QueryError("DUPLICATE_JSON_KEY", "JSON不能包含重复字段", {"field": key}, 400)
        result[key] = value
    return result


def no_nonfinite_constant(value):
    raise QueryError("INVALID_JSON", "JSON不得包含NaN或Infinity", status=400)


class Handler(BaseHTTPRequestHandler):
    server_version = "JPJResearch/1.0"

    def allowed(self):
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            raise QueryError("INVALID_HOST", "本机服务仅接受loopback Host", status=403)
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {"http://" + host for host in hosts}:
            raise QueryError("INVALID_ORIGIN", "不接受跨站请求", status=403)

    def output(self, payload, status=200, content_type="application/json; charset=utf-8"):
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8") if isinstance(payload, (dict, list)) else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        try:
            self.allowed()
            u = urlparse(self.path)
            if u.path in ["/", "/desk"]:
                self.output(Path(__file__).with_name("index.html").read_bytes(), content_type="text/html; charset=utf-8")
            elif u.path == "/api/catalog":
                if u.query: raise QueryError("UNSUPPORTED_PARAMETERS", "catalog不接受参数")
                self.output(get_catalog())
            elif u.path in ["/demo", "/demo/", "/demo/desk"]:
                from malaysia_ask.db import seed
                from malaysia_ask.ask import ask
                from scripts.serve import HTML, DESK, kpi_cards, render_body, render_desk_body
                seed()
                q = (parse_qs(u.query).get("q") or [""])[0]
                if len(q) > 500: raise QueryError("INVALID_QUESTION", "问句过长")
                if u.path.endswith("/desk"):
                    text = DESK % {"q": escape(q, quote=True), "cards": kpi_cards(), "body": render_desk_body(q)}
                else:
                    text = HTML % {"q": escape(q, quote=True), "body": render_body(ask(q)) if q else ""}
                text = text.replace('href="/', 'href="/demo/')
                text = text.replace('href="/demo/desk', 'href="/demo/desk')
                text = text.replace("<h1>", '<p class="warn"><b>当前：模拟演示数据</b> · 与真实JPJ分开运行。<a href="/">切回真实JPJ登记数据</a></p><h1>', 1)
                self.output(text.encode("utf-8"), content_type="text/html; charset=utf-8")
            else:
                raise QueryError("NOT_FOUND", "接口不存在", status=404)
        except QueryError as exc:
            self.output(exc.payload(), exc.status)
        except (pymysql.MySQLError, RuntimeError):
            self.output({"error": {"code": "DATA_UNAVAILABLE", "message": "MySQL数据层未就绪；请检查本地服务与已验证快照导入", "details": {}}}, 503)

    def do_POST(self):
        try:
            self.allowed()
            if self.path not in ["/api/query", "/api/ask"]:
                raise QueryError("NOT_FOUND", "接口不存在", status=404)
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise QueryError("INVALID_CONTENT_TYPE", "请使用application/json", status=415)
            try: length = int(self.headers.get("Content-Length", "0"))
            except ValueError: raise QueryError("INVALID_BODY", "无效的请求长度", status=400)
            if not 0 < length <= 8192:
                raise QueryError("INVALID_BODY", "请求长度须为1至8192字节", status=400)
            try: body = json.loads(self.rfile.read(length).decode("utf-8"), object_pairs_hook=no_duplicate_keys, parse_constant=no_nonfinite_constant)
            except (UnicodeDecodeError, json.JSONDecodeError): raise QueryError("INVALID_JSON", "请求不是有效UTF-8 JSON", status=400)
            if not isinstance(body, dict): raise QueryError("INVALID_BODY", "请求必须为JSON对象", status=400)
            if self.path == "/api/ask":
                if set(body) != {"question"}: raise QueryError("UNSUPPORTED_PARAMETERS", "仅支持question字段")
                query_id, parameters = route_question(body["question"])
            else:
                if set(body) != {"query_id", "parameters"}: raise QueryError("UNSUPPORTED_PARAMETERS", "必须且仅包含query_id、parameters")
                query_id, parameters = body["query_id"], body["parameters"]
            self.output(query(query_id, parameters))
        except QueryError as exc:
            self.output(exc.payload(), exc.status)
        except (pymysql.MySQLError, RuntimeError):
            self.output({"error": {"code": "DATA_UNAVAILABLE", "message": "数据库暂不可用；没有返回替代数据", "details": {}}}, 503)

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8777)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Real JPJ: http://127.0.0.1:{args.port}/ | Explicit simulation: /demo", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__": main()
