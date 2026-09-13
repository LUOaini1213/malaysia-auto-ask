"""All SQL aggregations must agree with an independent, row-by-row oracle."""
import itertools
import sqlite3
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from malaysia_ask.ask import ask
from malaysia_ask.db import seed
from malaysia_ask.templates import ADS_TEMPLATES, TEMPLATES, render, scan_for

# 覆盖面在这里算出来，两个测试跑完各自数一遍实际比对了多少组。README 引用的
# 266 绑在同一个常量上（见 tests/test_readme_numbers.py），模板增删时不会各说各话。
METRICS = ("tiv", "registration")
DWD_FILTERS = [
    {}, {"month": 2}, {"region_id": 2}, {"brand_id": 2},
    {"energy": "ev"}, {"energy": "hybrid"}, {"origin": "national"},
    {"origin": "non_national"}, {"energy": "ev", "origin": "national"},
    {"month": 1, "region_id": 2, "brand_id": 1, "energy": "ev", "origin": "national"},
    {"brand_id": 2, "origin": "national"},
]
ADS_BRANDS = (None, 1, 2)
ADS_ORIGINS = (None, "national", "non_national")

DWD_COMBINATIONS = len(TEMPLATES) * len(METRICS) * len(DWD_FILTERS)
ADS_COMBINATIONS = len(ADS_TEMPLATES) * len(METRICS) * len(ADS_BRANDS) * len(ADS_ORIGINS)
ORACLE_COMBINATIONS = DWD_COMBINATIONS + ADS_COMBINATIONS


class FilterContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = sqlite3.connect(":memory:")
        cls.conn.row_factory = sqlite3.Row
        cls.conn.executescript("""
            CREATE TABLE dim_brand (brand_id, brand_name, origin);
            CREATE TABLE dim_model (model_id, brand_id, model_name, energy);
            CREATE TABLE dim_region (region_id, region_name, region_name_zh);
            CREATE TABLE fact_month (year, month, model_id, region_id, tiv_units, registration_units);
            INSERT INTO dim_brand VALUES (1,'B1','national'),(2,'B2','non_national'),(3,'B3','national');
            INSERT INTO dim_model VALUES (1,1,'M1','ev'),(2,1,'M2','ice'),
                (3,2,'M3','ev'),(4,2,'M4','hybrid'),(5,3,'M5','ev'),(6,3,'M6','ice');
            INSERT INTO dim_region VALUES (1,'R1','一区'),(2,'R2','二区');
        """)
        cls.facts = []
        for year, month, region, model in itertools.product((2024, 2025), (1, 2), (1, 2), range(1, 7)):
            brand = (model + 1) // 2
            units = (year - 2023) * 100 + brand * 10 + model + month + region
            fact = dict(year=year, month=month, region_id=region, brand_id=brand,
                        origin="non_national" if brand == 2 else "national",
                        energy={1: "ev", 2: "ice", 3: "ev", 4: "hybrid", 5: "ev", 6: "ice"}[model],
                        model_id=model, tiv=units, registration=units + 7)
            cls.facts.append(fact)
            cls.conn.execute("INSERT INTO fact_month VALUES (?,?,?,?,?,?)",
                             (year, month, model, region, units, units + 7))
        cls.conn.execute("""CREATE TABLE ads_brand_year AS
            SELECT f.year, m.brand_id, SUM(tiv_units) tiv_units, SUM(registration_units) registration_units
            FROM fact_month f JOIN dim_model m ON f.model_id=m.model_id GROUP BY f.year,m.brand_id""")

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def expected(self, task, metric, params):
        def matches(row, market=False):
            return all(value is None or row[key] == value for key, value in params.items()
                       if key not in {"year", "year_ly"} and not (market and key == "brand_id"))

        def key(row):
            if task == "month_trend":
                return row["month"]
            if task == "region_rank":
                return "R" + str(row["region_id"])
            if task == "origin_split":
                return row["origin"]
            if task == "model_rank":
                return f"B{row['brand_id']} M{row['model_id']}"
            return "B" + str(row["brand_id"])

        now, previous = defaultdict(int), defaultdict(int)
        market_total = 0
        for row in self.facts:
            if row["year"] == params["year"] and matches(row, market=True):
                market_total += row[metric]
            if matches(row):
                if row["year"] == params["year"]:
                    now[key(row)] += row[metric]
                elif row["year"] == params["year_ly"]:
                    previous[key(row)] += row[metric]
        result = {}
        keys = now.keys() | previous.keys() if task == "yoy_brand" else now.keys()
        for group in keys:
            values = {"units": now[group]}
            if task == "share":
                values["share_pct"] = round(100 * now[group] / market_total, 1) if market_total else None
            if task == "yoy_brand":
                values["units_ly"] = previous[group]
                values["yoy_pct"] = round(100 * (now[group] - previous[group]) / previous[group], 1) if previous[group] else None
            result[group] = values
        return result

    def actual(self, task, metric, params, scan):
        rows = self.conn.execute(render(task, metric, scan), params).fetchall()
        fields = ("units", "share_pct", "units_ly", "yoy_pct")
        return {row["month" if task == "month_trend" else "name"]:
                {field: row[field] for field in fields if field in row.keys()} for row in rows}

    def test_every_dwd_template_honors_each_dimension_and_combinations(self):
        checked = 0
        for task, metric, selected in itertools.product(TEMPLATES, METRICS, DWD_FILTERS):
            params = dict(year=2025, year_ly=2024, month=None, region_id=None,
                          brand_id=None, energy=None, origin=None)
            params.update(selected)
            with self.subTest(task=task, metric=metric, filters=selected):
                self.assertEqual(self.actual(task, metric, params, "dwd.fact_month"),
                                 self.expected(task, metric, params))
            checked += 1
        self.assertEqual(checked, DWD_COMBINATIONS)

    def test_ads_routing_and_results_preserve_all_available_filters(self):
        checked = 0
        for task, metric, brand, origin in itertools.product(
                ADS_TEMPLATES, METRICS, ADS_BRANDS, ADS_ORIGINS):
            params = dict(year=2025, year_ly=2024, month=None, region_id=None,
                          brand_id=brand, energy=None, origin=origin)
            with self.subTest(task=task, metric=metric, brand=brand, origin=origin):
                self.assertEqual(scan_for(task, params), "ads.brand_year")
                self.assertEqual(self.actual(task, metric, params, "ads.brand_year"),
                                 self.expected(task, metric, params))
                for field, value in (("energy", "ev"), ("month", 1), ("region_id", 1)):
                    self.assertEqual(scan_for(task, {**params, field: value}), "dwd.fact_month")
            checked += 1
        self.assertEqual(checked, ADS_COMBINATIONS)


class QuestionRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / "demo.db"
        seed(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_toyota_ev_does_not_return_all_toyota_sales(self):
        result = ask("2025年纯电丰田TIV多少", db_path=self.path)
        self.assertFalse(result["hitl"])
        self.assertEqual(result["params"]["energy"], "ev")
        self.assertEqual(result["rows"], [])

    def test_ev_monthly_trend_excludes_other_energy(self):
        ev = ask("2025年纯电TIV各月趋势", db_path=self.path)
        all_energy = ask("2025年TIV各月趋势", db_path=self.path)
        self.assertFalse(ev["hitl"])
        self.assertEqual(len(ev["rows"]), 12)
        self.assertTrue(all(e["units"] < a["units"] for e, a in zip(ev["rows"], all_energy["rows"])))

    def test_origin_filter_survives_model_ranking_and_share(self):
        models = ask("2025年国产纯电TIV车型排名", db_path=self.path)
        self.assertFalse(models["hitl"])
        self.assertTrue(models["rows"])
        self.assertTrue(all(row["name"].startswith("Proton ") for row in models["rows"]))
        share = ask("2025年国产车Perodua TIV份额", db_path=self.path)
        self.assertFalse(share["hitl"])
        self.assertEqual(share["rows"][0]["share_pct"], round(100 * 359904 / (359904 + 151564), 1))


if __name__ == "__main__":
    unittest.main()
