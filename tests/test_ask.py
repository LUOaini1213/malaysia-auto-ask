# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from malaysia_ask.ask import ask
from malaysia_ask.db import seed, connect, DB_PATH


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


if __name__ == "__main__":
    unittest.main()
