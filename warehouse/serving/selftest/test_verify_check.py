"""verify --check must reject a fresh run that drifts from the committed evidence.

Kept outside warehouse/serving/tests so the 30-test acceptance suite that
verify.py discovers (and the README quotes) is unchanged.
Run: python -m unittest discover -s warehouse/serving/selftest -v
"""
from __future__ import annotations

import copy
import json
import unittest

from warehouse.serving.verify import COMMITTED, compare_with_committed


class VerifyCheck(unittest.TestCase):
    def setUp(self):
        self.committed = json.loads(COMMITTED.read_text(encoding="utf-8"))

    def test_committed_evidence_matches_itself(self):
        self.assertEqual(compare_with_committed(copy.deepcopy(self.committed), self.committed), [])
        self.assertEqual(self.committed["tests"], {"run": 30, "failures": 0, "errors": 0, "skipped": 0})
        self.assertEqual(self.committed["exact_hive_python_mysql_groups"], 1536)
        self.assertEqual(self.committed["query_reconciliation_count"], 130)

    def test_each_kind_of_drift_is_reported(self):
        for mutate in (
            lambda r: r["tests"].update(skipped=13),
            lambda r: r["tests"].update(run=17),
            lambda r: r.update(exact_hive_python_mysql_groups=1535),
            lambda r: r.update(query_reconciliation_count=129),
            lambda r: r["query_reconciliations"].pop(),
            lambda r: r["query_reconciliations"][0].update(rows=19),
            lambda r: r["source"].update(represented_registration_rows=1511063),
        ):
            fresh = copy.deepcopy(self.committed)
            mutate(fresh)
            with self.subTest(fresh=mutate):
                self.assertTrue(compare_with_committed(fresh, self.committed))


if __name__ == "__main__":
    unittest.main()
