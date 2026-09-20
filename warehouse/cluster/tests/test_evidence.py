import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("evidence", Path(__file__).resolve().parents[1] / "verify-evidence.py")
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)


class EvidenceTests(unittest.TestCase):
    def test_yarn_ids_deduplicate(self):
        self.assertEqual(EVIDENCE.application_ids("application_123_0001 twice application_123_0001"), ["application_123_0001"])

    def test_local_execution_is_not_yarn_evidence(self):
        self.assertEqual(EVIDENCE.application_ids("job_local123_0001 succeeded"), [])

    def test_failed_or_wrong_engine_is_rejected(self):
        good = dict(id="application_123_0001", applicationType="MAPREDUCE", state="FINISHED", finalStatus="SUCCEEDED")
        EVIDENCE.require_success(good, "MAPREDUCE")
        for changes in ({"finalStatus": "FAILED"}, {"state": "RUNNING"}, {"applicationType": "TEZ"}, {"unmanagedApplication": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                EVIDENCE.require_success({**good, **changes}, "MAPREDUCE")

    def test_tez_requires_actual_successful_dag(self):
        app = dict(id="application_123_0001", applicationType="TEZ", state="FINISHED", finalStatus="SUCCEEDED")
        with self.assertRaises(ValueError):
            EVIDENCE.require_success(app, "TEZ")
        EVIDENCE.require_success({**app, "diagnostics": "submittedDAGs=1, successfulDAGs=1, failedDAGs=0, killedDAGs=0"}, "TEZ")
        with self.assertRaises(ValueError):
            EVIDENCE.require_success({**app, "diagnostics": "submittedDAGs=10, successfulDAGs=10, failedDAGs=0, killedDAGs=0"}, "TEZ")

    def test_changed_aggregation_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.tsv"
            path.write_text("alpha\t14\nbeta\t20\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                EVIDENCE.exact_rows(path, ["alpha\t15", "beta\t20"])


if __name__ == "__main__":
    unittest.main()
