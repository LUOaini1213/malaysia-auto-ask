"""The release gate rejects changed data and compares equal time windows."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_hive
from run_hive import business_summary, compare_aggregates, parse_aggregates, validate_checks


class ValidationTests(unittest.TestCase):
    def test_detects_changed_missing_and_extra_aggregate(self):
        expected = {("total", "ALL", "ALL"): 5, ("fuel", "electric", "ALL"): 2}
        actual = {("total", "ALL", "ALL"): 5, ("fuel", "petrol", "ALL"): 3}
        self.assertFalse(compare_aggregates(expected, actual)["passed"])
        actual = dict(expected)
        actual[("fuel", "electric", "ALL")] = 1
        self.assertEqual(len(compare_aggregates(expected, actual)["mismatches"]), 1)

    def test_duplicate_keys_are_an_error_not_overwritten(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_aggregates("total\tALL\tALL\t3\ntotal\tALL\tALL\t4\n")

    def test_quality_gate_rejects_duplicate_lineage(self):
        text = ("ods_count\t5\ndwd_count\t5\ndistinct_lineage_count\t4\n"
                "invalid_partition_count\t0\ninvalid_lineage_count\t0\n")
        self.assertFalse(validate_checks(text, 5)["passed"])

    def test_incomplete_year_compares_only_common_months(self):
        values = {("month", "2025", "01"): 100, ("month", "2025", "02"): 900,
                  ("month", "2026", "01"): 120, ("month_fuel", "2026-01", "electric"): 12,
                  ("month_fuel", "2025-01", "electric"): 5,
                  ("month_maker", "2026-01", "B"): 60}
        result = business_summary(values)
        self.assertEqual(result["common_months"], [1])
        self.assertEqual(result["comparable_registrations"], {2025: 100, 2026: 120})
        self.assertEqual(result["comparable_yoy_pct"], 20.0)
        self.assertEqual(result["electric_share_pct"][2026], 10.0)

    def test_analysis_combines_case_variants_but_does_not_drop_records(self):
        values = {("month", "2025", "01"): 10, ("month", "2026", "01"): 12,
                  ("month_maker", "2025-01", "BMW"): 10,
                  ("month_maker", "2026-01", "BMW"): 7,
                  ("month_maker", "2026-01", "bmw"): 5}
        result = business_summary(values)
        first = result["top_makers_current_comparable_period"][0]
        self.assertEqual(first, {"maker": "BMW", "registrations": 12,
                                 "share_pct": 100.0, "previous_registrations": 10})
        self.assertEqual(result["maker_case_variants"], {"BMW": ["BMW", "bmw"]})

    def test_manifest_rejects_changes_to_non_aggregate_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            curated, raw, artifacts = root / "curated", root / "raw", root / "artifacts"
            partition = curated / "registration_year=2026/registration_month=01"
            for path in (partition, raw, artifacts):
                path.mkdir(parents=True)
            source = raw / "cars_2026.parquet"
            source.write_bytes(b"fixture")
            file = partition / "part-00000.tsv"
            file.write_text("colour=red\n", encoding="utf-8")
            manifest = {"source_sha256": run_hive.sha256(source), "files": [{
                "path": file.relative_to(curated).as_posix(), "bytes": file.stat().st_size,
                "sha256": run_hive.sha256(file), "rows": 1}]}
            (artifacts / "year_2026_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(run_hive, "WAREHOUSE", root):
                self.assertEqual(len(run_hive.validated_partitions(curated, artifacts, raw)), 1)
                file.write_text("colour=tan\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "changed since build"):
                    run_hive.validated_partitions(curated, artifacts, raw)
                file.write_text("colour=red\n", encoding="utf-8")
                (partition / "untracked.txt").write_text("unexpected", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "unmanifested"):
                    run_hive.validated_partitions(curated, artifacts, raw)

    def test_timeout_preserves_partial_application_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            cluster = run_hive.Cluster(output, "unused")
            error = subprocess.TimeoutExpired("beeline", 1, output=b"application_123_0001", stderr=b"partial")
            with patch.object(run_hive.subprocess, "run", side_effect=error):
                with self.assertRaisesRegex(RuntimeError, "partial output saved"):
                    cluster.run("beeline", timeout=1)
            self.assertIn("application_123_0001", (output / "command_01.log").read_text(encoding="utf-8"))

    def test_output_reader_handles_union_subdirectories(self):
        with tempfile.TemporaryDirectory() as directory:
            cluster = run_hive.Cluster(Path(directory), "unused")
            listing = ("drwxr-xr-x - hive group 0 2026-09-17 12:00 /result/HIVE_UNION_SUBDIR_1\n"
                       "-rw-r--r-- 1 hive group 9 2026-09-17 12:00 /result/HIVE_UNION_SUBDIR_1/000000_0\n"
                       "-rw-r--r-- 1 hive group 0 2026-09-17 12:00 /result/_SUCCESS\n")
            with patch.object(cluster, "hdfs", side_effect=[listing, "data\n"]) as hdfs:
                self.assertEqual(cluster.read_directory("/result"), "data\n")
                self.assertEqual(hdfs.call_args.args, ("-cat", "/result/HIVE_UNION_SUBDIR_1/000000_0"))


if __name__ == "__main__":
    unittest.main()
