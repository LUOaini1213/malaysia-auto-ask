# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from malaysia_ask.ask import ask
from malaysia_ask.db import seed, connect, DB_PATH
from malaysia_ask.lineage import walk_upstream


class AskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()

    def test_brand_year_anchor(self):
        conn = connect(DB_PATH)
        n = conn.execute(
            """
            SELECT SUM(f.tiv_units) FROM fact_month f
            JOIN dim_model m ON m.model_id=f.model_id
            JOIN dim_brand b ON b.brand_id=m.brand_id
            WHERE f.year=2025 AND b.brand_name='Perodua'
            """
        ).fetchone()[0]
        self.assertEqual(n, 359904)

    def test_tiv_not_equal_registration(self):
        conn = connect(DB_PATH)
        row = conn.execute(
            "SELECT SUM(tiv_units), SUM(registration_units) FROM fact_month WHERE year=2025"
        ).fetchone()
        self.assertNotEqual(row[0], row[1])

    def test_hitl_sales_word(self):
        r = ask("2025谁卖得最好")
        self.assertTrue(r["hitl"])
        self.assertIsNone(r["sql"])

    def test_explicit_tiv(self):
        r = ask("2025全年协会口径TIV哪家第一")
        self.assertFalse(r["hitl"])
        self.assertEqual(r["rows"][0]["name"], "Perodua")
        self.assertIn("tiv_units", r["sql"])
        self.assertEqual(r["trace"]["scan"], "ads.brand_year")
        self.assertIn("ads.brand_year", r["lineage"]["path"])

    def test_month_uses_dwd(self):
        r = ask("2025年12月TIV品牌排名")
        self.assertFalse(r["hitl"])
        self.assertEqual(r["trace"]["scan"], "dwd.fact_month")
        self.assertIn("fact_month", r["sql"])

    def test_ads_matches_ods_anchor(self):
        conn = connect(DB_PATH)
        ads = conn.execute(
            """
            SELECT a.tiv_units FROM ads_brand_year a
            JOIN dim_brand b ON b.brand_id=a.brand_id
            WHERE a.year=2025 AND b.brand_name='Perodua'
            """
        ).fetchone()[0]
        ods = conn.execute(
            "SELECT tiv_units FROM ods_brand_year_anchor WHERE year=2025 AND brand_name='Perodua'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(ads, 359904)
        self.assertEqual(ods, 359904)

    def test_retrieve_tiv_vs_registration(self):
        r = ask("TIV和上牌有什么区别")
        self.assertFalse(r["hitl"])
        self.assertEqual(r["task"], "retrieve")
        self.assertIsNone(r["sql"])
        objs = {h["object"] for h in r["retrieve"]}
        self.assertTrue("metric.tiv" in objs or "metric.registration" in objs)

    def test_retrieve_share_formula(self):
        r = ask("份额怎么算")
        self.assertEqual(r["task"], "retrieve")
        objs = {h["object"] for h in r["retrieve"]} | set(r["lineage"]["path"])
        self.assertIn("metric.share", objs)

    def test_lineage_tiv_reaches_ods(self):
        w = walk_upstream("metric.tiv")
        self.assertIn("ods.brand_year_anchor", w["path"])
        self.assertIn("dwd.fact_month", w["path"])

    def test_brief_blocks_sales_word(self):
        from malaysia_ask.brief import draft_note

        p = draft_note("2025谁卖得最好")
        self.assertTrue(p["blocked"])
        self.assertIsNone(p["draft"])

    def test_brief_has_confirm_flag(self):
        from malaysia_ask.brief import draft_note

        p = draft_note("2025全年协会口径TIV哪家第一")
        self.assertFalse(p["blocked"])
        self.assertTrue(p["needs_confirm"])
        self.assertIn("Perodua", p["draft"])
        self.assertIn("须人确认", p["draft"])


if __name__ == "__main__":
    unittest.main()
