# -*- coding: utf-8 -*-
"""Every JPJ number on the first screen and in the warehouse READMEs, against evidence.

tests/test_readme_numbers.py pins the legacy demo's numbers. This file pins the
real-data headline (1,436,804 / 1,536 / 20 partitions / 30 tests / 130 query
checks / the 2026-11-03 refresh re-run) to the committed evidence files, and the
first-screen demo summary to the evaluation artifacts. Standard library only.
"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_filter_contract import ORACLE_COMBINATIONS  # noqa: E402

EVIDENCE = ROOT / "warehouse" / "evidence" / "20260917_152407_7272aa"
VALIDATION = json.loads((EVIDENCE / "validation.json").read_text(encoding="utf-8"))
ACCEPTANCE = json.loads((ROOT / "warehouse" / "serving" / "evidence" / "20260918" / "acceptance.json")
                        .read_text(encoding="utf-8"))
REFRESH = json.loads((ROOT / "warehouse" / "evidence" / "refresh_check_20261103.json").read_text(encoding="utf-8"))
LAST_RUN = json.loads((ROOT / "eval" / "last_run.json").read_text(encoding="utf-8"))
ABLATION = json.loads((ROOT / "eval" / "ablation.json").read_text(encoding="utf-8"))

TOTAL = VALIDATION["expected_total"]
GROUPS = VALIDATION["aggregate_comparison"]["compared_groups"]
PARTITIONS = VALIDATION["partition_files"]
TESTS = ACCEPTANCE["tests"]["run"]
RECON = ACCEPTANCE["query_reconciliation_count"]


def n(text):
    return int(text.replace(",", ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class EvidenceIsSelfConsistent(unittest.TestCase):
    def test_the_sources_agree_before_the_readmes_are_checked(self):
        self.assertEqual(VALIDATION["status"], "passed")
        self.assertEqual(ACCEPTANCE["status"], "passed")
        self.assertEqual(ACCEPTANCE["tests"], {"run": TESTS, "failures": 0, "errors": 0, "skipped": 0})
        self.assertEqual(ACCEPTANCE["exact_hive_python_mysql_groups"], GROUPS)
        self.assertEqual(ACCEPTANCE["source"]["represented_registration_rows"], TOTAL)
        self.assertEqual(len(ACCEPTANCE["query_reconciliations"]), RECON)
        self.assertTrue(all(q["passed"] for q in ACCEPTANCE["query_reconciliations"]))
        partitions = json.loads((EVIDENCE / "input_partitions.json").read_text(encoding="utf-8"))
        self.assertEqual(len(partitions), PARTITIONS)
        self.assertEqual(sum(p["rows"] for p in partitions), TOTAL)
        self.assertTrue(REFRESH["identical"])
        self.assertEqual((REFRESH["rows"], REFRESH["aggregate_rows"]), (TOTAL, GROUPS))


class Readmes(unittest.TestCase):
    def grab(self, text, pattern, count=1):
        hits = re.findall(pattern, text)
        self.assertEqual(len(hits), count, f"{pattern!r} should match {count} time(s), got {len(hits)}")
        return hits[0]

    def test_root_first_screen(self):
        readme = read("README.md")
        head = readme[:readme.index("## JPJ registration warehouse")]
        self.assertEqual(n(self.grab(head, r"([\d,]+) official JPJ car registrations")), TOTAL)
        self.assertEqual(n(self.grab(head, r"run into ([\d,]+) aggregates")), GROUPS)
        agree, recon = self.grab(head, r"agree on all ([\d,]+) aggregates, and (\d+) query reconciliations")
        self.assertEqual((n(agree), int(recon)), (GROUPS, RECON))
        self.assertEqual(n(self.grab(head, r"rebuilds the ([\d,]+) aggregates")), REFRESH["aggregate_rows"])
        self.assertEqual(int(self.grab(head, r"(\d+) template × filter combinations")), ORACLE_COMBINATIONS)
        cases, answered, stopped = self.grab(head, r"(\d+)-question suite it answers (\d+) and stops (\d+)")
        summary = LAST_RUN["summary"]
        self.assertEqual((int(cases), int(answered), int(stopped)),
                         (summary["n"], summary["n_expect_answer"], summary["n_hitl"]))
        silent = self.grab(head, r"with the guard off all (\d+) get a silent answer")
        self.assertEqual(f"{silent}/{stopped}", ABLATION["B_ablation_guard_off"]["无提示猜测"])
        self.assertLessEqual(len([ln for ln in head.splitlines() if ln.strip()]), 10, "first screen should stay short")

    def test_root_jpj_sections(self):
        readme = read("README.md")
        self.assertEqual(n(self.grab(readme, r"\*\*([\d,]+) official JPJ registration records\*\*")), TOTAL)
        self.assertEqual(n(self.grab(readme, r"\*\*([\d,]+) aggregate rows\*\*")), GROUPS)
        t, g, r = self.grab(readme, r"MySQL acceptance: (\d+) tests, ([\d,]+) reconciled aggregates and (\d+) query checks")
        self.assertEqual((int(t), n(g), int(r)), (TESTS, GROUPS, RECON))
        self.assertEqual(int(self.grab(readme, r"re-runs the (\d+) tests")), TESTS)
        self.assertEqual(n(self.grab(readme, r"\*\*([\d,]+) 条登记记录\*\*")), TOTAL)
        p, g = self.grab(readme, r"\*\*(\d+) 个分区、([\d,]+) 项跨引擎汇总核对全部通过\*\*")
        self.assertEqual((int(p), n(g)), (PARTITIONS, GROUPS))
        t, g, r = self.grab(readme, r"(\d+) 项测试、([\d,]+) 项三方汇总对账和 (\d+) 项查询核对")
        self.assertEqual((int(t), n(g), int(r)), (TESTS, GROUPS, RECON))
        self.assertEqual(n(self.grab(readme, r"\*\*([\d,]+) 项冻结汇总\*\*")), GROUPS)

    def test_warehouse_readme(self):
        text = read("warehouse/README.md")
        self.assertEqual(n(self.grab(text, r"\*\*([\d,]+) 项 Hive 汇总\*\*")), GROUPS)
        rows, parts, groups = self.grab(text, r"\*\*([\d,]+) 条记录、(\d+) 个分区、([\d,]+) 项 Hive / Python 汇总全部一致\*\*")
        self.assertEqual((n(rows), int(parts), n(groups)), (TOTAL, PARTITIONS, GROUPS))
        y2026 = REFRESH["years"]["2026"]
        file_rows, excluded, kept, groups = self.grab(
            text, r"2026 年文件 ([\d,]+) 行，排除 ([\d,]+) 行，保留 ([\d,]+) 行，独立 Python 汇总的 ([\d,]+) 项")
        self.assertEqual(n(file_rows), y2026["rows"] + y2026["excluded_after_data_asof"])
        self.assertEqual(n(excluded), y2026["excluded_after_data_asof"])
        self.assertEqual((n(kept), n(groups)), (REFRESH["rows"], REFRESH["aggregate_rows"]))
        self.assertNotIn("面试", text)

    def test_serving_readme(self):
        text = read("warehouse/serving/README.md")
        g, t = self.grab(text, r"\*\*([\d,]+) 项汇总\*\*代表上游 \*\*([\d,]+) 次汽车登记\*\*")
        self.assertEqual((n(g), n(t)), (GROUPS, TOTAL))
        self.assertEqual(int(self.grab(text, r"- (\d+) 项测试全部通过，无跳过")), TESTS)
        self.assertEqual(n(self.grab(text, r"- ([\d,]+) 项 Hive / 独立 Python / MySQL 汇总逐项相等")), GROUPS)
        self.assertEqual(int(self.grab(text, r"- (\d+) 项查询对账通过")), RECON)
        t, g, r = self.grab(text, r"（(\d+) 项运行、0 跳过、([\d,]+) 组、同样的 (\d+) 项核对")
        self.assertEqual((int(t), n(g), int(r)), (TESTS, GROUPS, RECON))


class ServeEntryPoint(unittest.TestCase):
    def test_default_mode_without_pymysql_explains_instead_of_crashing(self):
        code = ("import runpy, sys; sys.modules['pymysql'] = None; sys.argv = ['serve.py']; "
                f"runpy.run_path({str(ROOT / 'scripts' / 'serve.py')!r}, run_name='__main__')")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertIn("python scripts/serve.py --demo", done.stderr)
        self.assertIn("warehouse/serving/requirements.txt", done.stderr)


if __name__ == "__main__":
    unittest.main()
