# -*- coding: utf-8 -*-
"""The evaluation and ablation figures, recomputed rather than stored.

Everything here recomputes from the seeded database and the 30-case suite;
the only stored results it reads are the two committed artifacts, and it
reads them to prove they still equal a fresh run — eval/last_run.json via
scripts/eval.py --check, eval/ablation.json via ablation._compare.

What this file pins is the artifacts. The numbers README.md quotes are
pinned separately, in tests/test_readme_numbers.py, which parses the README
text itself and compares it against those artifacts and against the
constants in malaysia_ask/db.py. Neither file alone stops the README from
drifting; the pair does.
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import ablation  # noqa: E402  (scripts/ablation.py)
from malaysia_ask.ask import ask  # noqa: E402
from malaysia_ask.db import DB_PATH, connect, seed  # noqa: E402


def _load_eval_script():
    spec = importlib.util.spec_from_file_location("eval_script", ROOT / "scripts" / "eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CaseSuiteShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.cases = json.loads((ROOT / "eval" / "cases.json").read_text(encoding="utf-8"))

    def test_thirty_cases_eight_of_which_must_stop(self):
        self.assertEqual(len(self.cases), 30)
        self.assertEqual(sum(1 for c in self.cases if c.get("expect_hitl")), 8)

    def test_guard_on_stops_every_stop_case_with_a_code(self):
        for c in self.cases:
            if not c.get("expect_hitl"):
                continue
            r = ask(c["q"])
            with self.subTest(case=c["id"]):
                self.assertTrue(r["hitl"])
                self.assertTrue(r.get("hitl_code"), "a stop must carry a structured reason code")

    def test_guard_off_answers_every_stop_case_and_records_the_guesses(self):
        for c in self.cases:
            if not c.get("expect_hitl"):
                continue
            r = ask(c["q"], force=True)
            with self.subTest(case=c["id"]):
                self.assertFalse(r["hitl"])
                self.assertTrue(r.get("rows"), "forced mode must return a table")
                self.assertTrue(r.get("guesses"), "every forced answer rests on at least one guess")

    def test_official_eval_script_passes_and_matches_the_committed_run(self):
        module = _load_eval_script()
        # --check 重跑全部 30 + 8 条但不写文件：既跑评测，又把仓里提交的
        # eval/last_run.json 逐字段钉在这次新跑上。仓里那份才是网页上被读到的那份。
        self.assertEqual(module.main(["--check"]), 0)
        summary = json.loads((ROOT / "eval" / "last_run.json").read_text(encoding="utf-8"))["summary"]
        self.assertEqual((summary["n"], summary["n_expect_answer"], summary["n_hitl"]), (30, 22, 8))
        self.assertEqual((summary["success_rate"], summary["accuracy"]), (1.0, 1.0))
        self.assertAlmostEqual(summary["hitl_rate"], 8 / 30, places=4)
        self.assertEqual(summary["retrieve"]["n_ok"], summary["retrieve"]["n"])


class AnchorIntegrity(unittest.TestCase):
    def test_annual_tiv_matches_the_public_anchor_and_registration_is_a_different_series(self):
        seed()
        conn = connect(DB_PATH)
        tiv, reg = conn.execute(
            "SELECT SUM(tiv_units), SUM(registration_units) FROM fact_month WHERE year=2025").fetchone()
        anchor = conn.execute("SELECT SUM(tiv_units) FROM ods_brand_year_anchor WHERE year=2025").fetchone()[0]
        conn.close()
        self.assertEqual(tiv, 820752)
        self.assertEqual(tiv, anchor)
        self.assertNotEqual(tiv, reg)
        self.assertLess(abs(reg - tiv) / tiv, 0.03, "annual totals stay close: the lag nets out")


class AblationClaims(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fresh = ablation.compute()

    def test_guard_arms(self):
        a, b = self.fresh["A_baseline_guard_on"], self.fresh["B_ablation_guard_off"]
        self.assertEqual((a["该停的停住"], a["该答的答对"], a["静默错答"]), ("8/8", "22/22", 0))
        self.assertEqual((b["该停的停住"], b["强行作答"], b["无提示猜测"]), ("0/8", "8/8", "8/8"))
        self.assertEqual(b["结论被改变"], "7/8")
        self.assertEqual(b["结论被改变的依据"], {"measured": 0, "by_construction": 7})
        self.assertEqual(b["对22题正常问答的回归"], 0)

    def test_stop_reasons_fall_into_five_classes(self):
        dist = {k: v["n"] for k, v in self.fresh["停问原因分布"].items()}
        self.assertEqual(dist, {"OUT_OF_SCOPE_ENTITY": 2, "UNDEFINED_TERM": 2, "RELATIVE_TIME": 2,
                                "AMBIGUOUS_METRIC": 1, "YEAR_OUT_OF_RANGE": 1})

    def test_metric_flip_hurts_values_not_rankings(self):
        flip = self.fresh["口径翻转对照"]
        self.assertEqual((flip["month_rank_diff"], flip["region_rank_diff"]), ("0/12", "0/7"))
        self.assertFalse(flip["full_order_diff_year"])
        self.assertGreater(flip["month_value_gap_pct"]["abs_max"], 15.0)
        legacy = flip["legacy_flat_bump_model"]
        self.assertLess(legacy["abs_typical"], 1.0, "the old flat-bump model barely diverged month to month")
        self.assertGreater(flip["month_value_gap_pct"]["abs_max"], legacy["abs_max"])

    def test_lambda_sensitivity_finds_no_flip_in_the_scanned_range(self):
        sens = self.fresh["lambda_sensitivity"]
        self.assertIsNone(sens["first_scale_with_any_top1_flip"])
        scales = [r["scale"] for r in sens["rows"]]
        self.assertIn(1.0, scales)
        self.assertLess(min(scales), 0.5)

    def test_committed_ablation_json_matches_a_fresh_run(self):
        committed = json.loads(ablation.OUT.read_text(encoding="utf-8"))
        self.assertEqual(ablation._compare(self.fresh, committed), [])


if __name__ == "__main__":
    unittest.main()
