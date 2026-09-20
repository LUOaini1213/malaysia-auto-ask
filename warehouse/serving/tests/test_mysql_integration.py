from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pymysql

from warehouse.serving.common import connect
from warehouse.serving.queries import get_catalog, query
from warehouse.serving.service import Handler, ThreadingHTTPServer
from warehouse.serving.store import SOURCE, import_verified, load_snapshot


@unittest.skipUnless(os.environ.get("JPJ_MYSQL_INTEGRATION") == "1", "Set JPJ_MYSQL_INTEGRATION=1 after starting the real project MySQL")
class RealMySQL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.rows = load_snapshot()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)

    def test_mysql_every_frozen_group_matches_hive_and_python(self):
        with connect() as c, c.cursor() as cur:
            cur.execute("SELECT dimension,key1,key2,registrations FROM aggregates WHERE version=%s", (self.source["version"],))
            got = {(r["dimension"], r["key1"], r["key2"]): r["registrations"] for r in cur.fetchall()}
        self.assertEqual(got, self.rows)

    def test_reader_real_update_privilege_is_denied(self):
        with connect() as c, c.cursor() as cur:
            with self.assertRaises(pymysql.MySQLError) as got:
                cur.execute("UPDATE aggregates SET registrations=registrations WHERE 1=0")
            self.assertEqual(got.exception.args[0], 1142)

    def test_read_only_transaction_also_denies_writer_update(self):
        with connect("writer") as c, c.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY"); c.begin()
            with self.assertRaises(pymysql.MySQLError) as got:
                cur.execute("UPDATE aggregates SET registrations=registrations WHERE 1=0")
            self.assertEqual(got.exception.args[0], 1792); c.rollback()

    def test_repeat_import_is_idempotent(self):
        with connect("writer") as c:
            result = import_verified(self.source, self.rows, c)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(get_catalog()["version"], self.source["version"])

    def test_mid_import_failure_rolls_back_all_rows_and_active_pointer(self):
        fake = copy.deepcopy(self.source); fake["version"] = "test-rollback-" + uuid.uuid4().hex
        with connect("writer") as c:
            with self.assertRaisesRegex(RuntimeError, "INJECTED_IMPORT_FAILURE"):
                import_verified(fake, self.rows, c, fail_after=4)
        with connect() as c, c.cursor() as cur:
            for table in ["dataset_versions", "aggregates"]:
                cur.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE version=%s", (fake["version"],))
                self.assertEqual(cur.fetchone()["n"], 0)
        self.assertEqual(get_catalog()["version"], self.source["version"])

    def test_tampered_input_refused_without_replacing_active(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            for name in ["validation.json", "evidence_manifest.json", "hive_aggregates.tsv"]:
                (path / name).write_bytes((SOURCE / name).read_bytes())
            with (path / "hive_aggregates.tsv").open("ab") as h: h.write(b"\n")
            with self.assertRaisesRegex(ValueError, "SOURCE_HASH_MISMATCH"):
                load_snapshot(path)
        self.assertEqual(get_catalog()["version"], self.source["version"])

    def test_known_brand_results_and_explicit_source(self):
        result = query("brand_compare", {"start_month": "2026-01", "end_month": "2026-08", "makers": ["BYD", "TESLA"]})
        self.assertEqual(result["rows"], [{"maker": "BYD", "registrations": 7472}, {"maker": "TESLA", "registrations": 3733}])
        self.assertEqual(result["source"]["hashes"], self.source["hashes"])
        self.assertIn("%s", result["sql"])

    def test_all_month_queries_reconcile_to_oracle(self):
        result = query("monthly_registrations", {"start_month": "2025-01", "end_month": "2026-08"})
        expected = [{"year_month": k[1]+"-"+k[2], "registrations": v} for k,v in sorted(self.rows.items()) if k[0]=="month"]
        self.assertEqual(result["rows"], expected)

    def test_case_variants_are_preserved_then_aggregated(self):
        result = query("monthly_registrations", {"start_month": "2025-01", "end_month": "2026-08", "maker": "BMW"})
        expected = sum(v for k,v in self.rows.items() if k[0] == "month_maker" and k[2].upper() == "BMW")
        self.assertEqual(sum(r["registrations"] for r in result["rows"]), expected)

    def request(self, path, body=None, headers=None):
        req = urllib.request.Request(self.base+path, data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", **(headers or {})})
        return urllib.request.urlopen(req, timeout=10)

    def test_real_http_catalog_and_demo_are_distinct(self):
        with self.request("/api/catalog") as r:
            self.assertEqual(json.load(r)["version"], self.source["version"])
        with self.request("/") as r: self.assertIn("真实公开数据", r.read().decode())
        with self.request("/demo") as r: self.assertIn("当前：模拟演示数据", r.read().decode())

    def test_http_unsupported_filter_returns_structured_error(self):
        with self.assertRaises(urllib.error.HTTPError) as got:
            self.request("/api/query", {"query_id":"monthly_registrations","parameters":{"start_month":"2026-01","end_month":"2026-08","owner_state":"Johor"}})
        self.assertEqual(json.loads(got.exception.read())["error"]["code"], "UNSUPPORTED_FILTER")

    def test_http_cross_origin_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as got:
            self.request("/api/catalog", headers={"Origin":"https://example.com"})
        self.assertEqual(got.exception.code,403)

    def test_http_nonfinite_json_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as got:
            self.request("/api/query", {"query_id":"monthly_registrations","parameters":{"maker":float('nan')}})
        self.assertEqual(json.loads(got.exception.read())["error"]["code"], "INVALID_JSON")


if __name__ == "__main__": unittest.main()
