from __future__ import annotations

import unittest

from warehouse.serving.common import QueryError
from warehouse.serving.queries import prepare_query, route_question
from warehouse.serving.store import SOURCE, load_snapshot, parse_rows

CATALOG = {"version": "test", "available_months": [f"2026-{m:02}" for m in range(1, 9)],
           "makers": ["BYD", "TESLA", "BMW"], "fuels": ["electric", "petrol"]}


class Contracts(unittest.TestCase):
    def assert_error(self, code, query_id="monthly_registrations", **params):
        with self.assertRaises(QueryError) as got:
            prepare_query(query_id, params, CATALOG)
        self.assertEqual(code, got.exception.code)

    def test_real_snapshot_exact_three_way_contract(self):
        source, rows = load_snapshot()
        self.assertEqual(len(rows), 1536)
        self.assertEqual(rows[("total", "ALL", "ALL")], 1436804)
        self.assertEqual(source["data_asof"], "2026-08-31")

    def test_duplicate_aggregate_refused(self):
        text = (SOURCE / "hive_aggregates.tsv").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "DUPLICATE_AGGREGATE"):
            parse_rows(text + text.splitlines()[0] + "\n")

    def test_bad_count_refused(self):
        with self.assertRaisesRegex(ValueError, "INVALID_COUNT"):
            parse_rows("total\tALL\tALL\t-1\n")

    def test_family_total_mismatch_refused(self):
        text = (SOURCE / "hive_aggregates.tsv").read_text(encoding="utf-8").replace("1436804", "1436805", 1)
        with self.assertRaisesRegex(ValueError, "TOTAL_MISMATCH"):
            parse_rows(text)

    def test_missing_period_refused(self):
        self.assert_error("MISSING_PARAMETERS", start_month="2026-01")

    def test_partial_year_cannot_be_answered_as_full_year(self):
        self.assert_error("OUT_OF_COVERAGE", start_month="2026-01", end_month="2026-12")

    def test_sales_not_answered_as_registrations(self):
        self.assert_error("METRIC_MISMATCH", start_month="2026-01", end_month="2026-08", metric="sales")

    def test_unsupported_filter_never_dropped(self):
        self.assert_error("UNSUPPORTED_FILTER", start_month="2026-01", end_month="2026-08", state="Johor")

    def test_maker_fuel_joint_filter_refused(self):
        self.assert_error("UNSUPPORTED_FILTER", "fuel_monthly", start_month="2026-01", end_month="2026-08", fuel="electric", maker="BYD")

    def test_case_normalization_is_explicit(self):
        p, _, args, _ = prepare_query("brand_compare", {"start_month": "2026-01", "end_month": "2026-08", "makers": ["byd", " Tesla "]}, CATALOG)
        self.assertEqual(p["makers"], ["BYD", "TESLA"])
        self.assertEqual(args[:2], ("BYD", "TESLA"))

    def test_duplicate_normalized_makers_refused(self):
        self.assert_error("DUPLICATE_MAKERS", "brand_compare", start_month="2026-01", end_month="2026-08", makers=["BYD", "byd"])

    def test_sql_injection_brand_is_not_catalog_value(self):
        self.assert_error("UNKNOWN_MAKER", start_month="2026-01", end_month="2026-08", maker="BYD' OR 1=1--")

    def test_limit_bool_not_integer(self):
        self.assert_error("INVALID_LIMIT", "maker_ranking", start_month="2026-01", end_month="2026-08", limit=True)

    def test_unknown_query_and_invalid_type(self):
        for q in ["DROP TABLE", ["monthly_registrations"], None]:
            with self.assertRaises(QueryError): prepare_query(q, {}, CATALOG)

    def test_question_full_match_rejects_unseen_conditions(self):
        with self.assertRaises(QueryError) as got:
            route_question("2026-01至2026-08 每月登记量 只看柔佛车主")
        self.assertEqual(got.exception.code, "CLARIFICATION_REQUIRED")

    def test_question_sales_guard(self):
        with self.assertRaises(QueryError) as got:
            route_question("2026-01至2026-08 BYD销量")
        self.assertEqual(got.exception.code, "METRIC_MISMATCH")

    def test_known_question_routes_without_llm(self):
        q, p = route_question("2026-01至2026-08 BYD和TESLA登记量对比")
        self.assertEqual(q, "brand_compare"); self.assertEqual(p["makers"], ["BYD", "TESLA"])


if __name__ == "__main__": unittest.main()
