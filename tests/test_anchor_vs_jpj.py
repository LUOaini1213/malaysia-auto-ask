# -*- coding: utf-8 -*-
"""The demo-anchor vs JPJ table in README.md, pinned to eval/anchor_vs_jpj.json.

The artifact itself is pinned to a fresh run (scripts/anchor_vs_jpj.py --check,
also run in CI). This file pins the README's table and the sentences that
interpret it, so neither can drift from the committed data.
"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
ARTIFACT = json.loads((ROOT / "eval" / "anchor_vs_jpj.json").read_text(encoding="utf-8"))
MINUS = "−"


def _int(text):
    return int(text.replace(",", ""))


class AnchorVsJpj(unittest.TestCase):
    def section(self):
        start = README.index("## 演示锚点与仓内 JPJ 登记数对照")
        return README[start:README.index("## 演示分层", start)]

    def test_artifact_matches_a_fresh_run(self):
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "anchor_vs_jpj.py"), "--check"],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_every_table_row_matches_the_artifact(self):
        section = self.section()
        seen = 0
        for brand in ARTIFACT["brands"]:
            m = re.search(rf"^\| {re.escape(brand['brand'])} \| ([\d,]+) \| ([\d,]+) \| ([{MINUS}\-]?[\d.]+)% \|$",
                          section, re.M)
            self.assertIsNotNone(m, f"README table has no row for {brand['brand']}")
            with self.subTest(brand=brand["brand"]):
                self.assertEqual(_int(m.group(1)), brand["demo_anchor"])
                self.assertEqual(_int(m.group(2)), brand["jpj_registrations"])
                self.assertEqual(float(m.group(3).replace(MINUS, "-")), brand["difference_pct"])
            seen += 1
        self.assertEqual(seen, 7)
        m = re.search(r"^\| 合计（演示含 Others） \| ([\d,]+) \| ([\d,]+) \|", section, re.M)
        self.assertEqual((_int(m.group(1)), _int(m.group(2))), (ARTIFACT["demo_total"], ARTIFACT["jpj_total"]))

    def test_interpretation_follows_the_artifact(self):
        section = self.section()
        self.assertEqual(ARTIFACT["exact_matches"], ["Perodua", "BYD"])
        self.assertIn("Perodua、BYD 两个锚点与 JPJ 登记数逐台相等", section)
        proton = next(b for b in ARTIFACT["brands"] if b["brand"] == "Proton")
        self.assertEqual(int(re.search(r"Proton 只差 (\d+) 台", section).group(1)), proton["difference"])
        self.assertEqual(ARTIFACT["honda_above_toyota"], {"demo_anchor": True, "jpj": False})
        self.assertIn("JPJ 里 Toyota 高于 Honda", section)
        # The first screen states the same finding.
        self.assertIn('two of its 2025 "TIV" anchors equal JPJ registration counts exactly', README)
        self.assertEqual(len(ARTIFACT["exact_matches"]), 2)

    def test_the_unsupported_market_claim_is_gone(self):
        self.assertNotIn("这与真实市场一致", README)


if __name__ == "__main__":
    unittest.main()
