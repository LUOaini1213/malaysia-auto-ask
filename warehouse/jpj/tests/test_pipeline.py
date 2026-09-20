"""Failure, lineage, and incremental-publication contracts for the JPJ pipeline.

All data is a tiny synthetic fixture. No network access or private data is used.
Run from the repository root with:
    python -m unittest discover -s warehouse/jpj/tests -v
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from warehouse.jpj.pipeline import build, check  # noqa: E402


ASOF = "2026-08-31"
TSV_COLUMNS = (
    "source_sha256", "source_row", "date_reg", "vehicle_type", "maker",
    "model", "colour", "fuel", "state",
)


def registration(day: str, **overrides: object) -> dict:
    row = {
        "date_reg": date.fromisoformat(day),
        "type": "motokar",
        "maker": "PROTON",
        "model": "SAGA",
        "colour": "white",
        "fuel": "petrol",
        "state": "Selangor",
    }
    row.update(overrides)
    return row


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PipelineContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="jpj_pipeline_test_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.curated = self.root / "curated"
        self.artifacts = self.root / "artifacts"
        self.raw.mkdir()

    def write_source(self, year: int, rows: list[dict],
                     date_type: pa.DataType | None = None) -> str:
        path = self.raw / f"cars_{year}.parquet"
        schema = pa.schema([
            ("date_reg", pa.date32() if date_type is None else date_type),
            ("type", pa.string()),
            ("maker", pa.string()),
            ("model", pa.string()),
            ("colour", pa.string()),
            ("fuel", pa.string()),
            ("state", pa.string()),
        ])
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
        digest = sha256(path)
        metadata = {
            "source_url": f"https://storage.data.gov.my/transportation/cars_{year}.parquet",
            "license": "CC BY 4.0",
            "downloaded_at": "2026-09-17T00:00:00+00:00",
            "source_sha256": digest,
            "source_size_bytes": path.stat().st_size,
            "data_asof": ASOF,
        }
        (self.raw / f"cars_{year}.metadata.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )
        return digest

    def run_build(self, years: list[int], **kwargs: object) -> dict:
        result = build(self.raw, self.curated, self.artifacts, years,
                       data_asof=ASOF, **kwargs)
        self.assertIsInstance(result, dict)
        return result

    def tsv_files(self, year: int) -> list[Path]:
        return sorted(self.curated.glob(
            f"registration_year={year}/registration_month=*/*.tsv"
        ))

    def rows(self, year: int) -> list[dict[str, str]]:
        records = []
        for path in self.tsv_files(year):
            with path.open(encoding="utf-8", newline="") as source:
                for fields in csv.reader(source, delimiter="\t"):
                    self.assertEqual(len(fields), len(TSV_COLUMNS), path)
                    self.assertNotEqual(fields[0], "source_sha256",
                                        "Hive data files must not contain a header row")
                    row = dict(zip(TSV_COLUMNS, fields))
                    self.assertEqual(row["date_reg"][:4], str(year))
                    self.assertEqual(path.parent.name,
                                     "registration_month=" + row["date_reg"][5:7])
                    records.append(row)
        return records

    def snapshot(self, year: int) -> dict[str, tuple[str, int]]:
        return {
            str(path.relative_to(self.curated)): (sha256(path), path.stat().st_mtime_ns)
            for path in self.tsv_files(year)
        }

    def assert_rejected_report(self, year: int, expected_rejections: int) -> dict:
        path = self.artifacts / f"year_{year}_dq.json"
        self.assertTrue(path.is_file(), "A rejected batch needs an inspectable DQ report")
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(report["rejected_rows"], expected_rejections)
        self.assertTrue(report["reasons"], "The report must explain the rejected rows")
        self.assertTrue(report["rejected_samples"], "Keep bounded examples for repair")
        self.assertLessEqual(len(report["rejected_samples"]), 50)
        return report

    def test_identical_registrations_are_retained_with_unique_source_keys(self) -> None:
        identical = registration("2026-01-05")
        source_hash = self.write_source(2026, [identical, identical.copy(),
                                               registration("2026-02-01", model=None, colour="")])
        self.run_build([2026])
        actual = self.rows(2026)
        self.assertEqual(len(actual), 3, "Identical registrations are not duplicate ingestion")
        self.assertEqual(Counter(row["date_reg"] for row in actual),
                         {"2026-01-05": 2, "2026-02-01": 1})
        self.assertEqual({row["source_sha256"] for row in actual}, {source_hash})
        keys = {(row["source_sha256"], row["source_row"]) for row in actual}
        self.assertEqual(len(keys), 3)
        row_numbers = sorted(int(row["source_row"]) for row in actual)
        self.assertIn(row_numbers[0], (0, 1))
        self.assertEqual(row_numbers, list(range(row_numbers[0], row_numbers[0] + 3)))
        optional = next(row for row in actual if row["date_reg"] == "2026-02-01")
        self.assertEqual(optional["model"], r"\N")
        self.assertEqual(optional["colour"], r"\N")

    def test_partitioned_dimensions_and_registration_totals_reconcile(self) -> None:
        types = ["motokar", "motokar_pelbagai_utiliti", "jip", "pick_up", "window_van"]
        fixture = [
            registration(f"2026-0{1 + index % 2}-0{index + 1}", type=kind,
                         maker="PROTON" if index % 2 else "PERODUA",
                         fuel="electric" if index == 3 else "petrol",
                         state="Johor" if index % 2 else "Selangor")
            for index, kind in enumerate(types)
        ]
        fixture.append(fixture[0].copy())
        self.write_source(2026, fixture)
        self.run_build([2026])
        actual = self.rows(2026)
        self.assertEqual(len(actual), len(fixture))
        expected_counts = Counter(
            (row["date_reg"].strftime("%Y-%m"), row["maker"], row["fuel"],
             row["state"], row["type"]) for row in fixture
        )
        actual_counts = Counter(
            (row["date_reg"][:7], row["maker"], row["fuel"], row["state"],
             row["vehicle_type"]) for row in actual
        )
        self.assertEqual(actual_counts, expected_counts)
        self.assertEqual(len({(row["source_sha256"], row["source_row"]) for row in actual}),
                         len(fixture))

    def test_official_midnight_microsecond_timestamps_normalize_to_dates(self) -> None:
        fixture = [
            registration("2026-01-01", date_reg=datetime(2026, 1, 1, 0, 0, 0)),
            registration("2026-08-31", date_reg=datetime(2026, 8, 31, 0, 0, 0)),
        ]
        source_hash = self.write_source(2026, fixture, date_type=pa.timestamp("us"))
        source_schema = pq.read_schema(self.raw / "cars_2026.parquet")
        self.assertEqual(source_schema.field("date_reg").type, pa.timestamp("us"))
        self.run_build([2026])
        actual = self.rows(2026)
        self.assertEqual(len(actual), 2)
        self.assertEqual({row["date_reg"] for row in actual}, {"2026-01-01", "2026-08-31"})
        self.assertEqual({row["source_sha256"] for row in actual}, {source_hash})

    def test_non_midnight_timestamps_are_rejected_without_silent_truncation(self) -> None:
        non_midnight = [
            datetime(2026, 1, 1, 1, 0, 0),
            datetime(2026, 1, 1, 0, 1, 0),
            datetime(2026, 1, 1, 0, 0, 1),
            datetime(2026, 1, 1, 0, 0, 0, 1),
        ]
        fixture = [registration("2026-01-01", date_reg=datetime(2026, 1, 1))]
        fixture.extend(registration("2026-01-01", date_reg=value)
                       for value in non_midnight)
        self.write_source(2026, fixture, date_type=pa.timestamp("us"))
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_build([2026])
        self.assertEqual(self.tsv_files(2026), [])
        report = self.assert_rejected_report(2026, 4)
        self.assertEqual(report["reasons"], {"timestamp_has_time": 4})

    def test_rejected_row_preserves_entire_previous_year_and_manifest(self) -> None:
        self.write_source(2026, [registration("2026-01-01"), registration("2026-02-01")])
        self.run_build([2026])
        previous = self.snapshot(2026)
        manifest_path = self.artifacts / "year_2026_manifest.json"
        previous_manifest = manifest_path.read_bytes()
        self.write_source(2026, [registration("2026-01-03"),
                                 registration("2026-03-02", type="unknown_vehicle")])
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_build([2026])
        self.assertEqual(self.snapshot(2026), previous)
        self.assertEqual(manifest_path.read_bytes(), previous_manifest)
        self.assert_rejected_report(2026, 1)
        self.assertFalse((self.curated / "registration_year=2026" /
                          "registration_month=03").exists())

    def test_interrupted_build_keeps_old_publication_then_retry_succeeds(self) -> None:
        self.write_source(2026, [registration("2026-01-01")])
        self.run_build([2026])
        previous = self.snapshot(2026)
        new_hash = self.write_source(2026, [registration("2026-02-01"),
                                            registration("2026-02-02"),
                                            registration("2026-03-01")])
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_build([2026], failure_after_rows=2)
        self.assertEqual(self.snapshot(2026), previous)
        self.run_build([2026])
        actual = self.rows(2026)
        self.assertEqual(len(actual), 3)
        self.assertEqual({row["source_sha256"] for row in actual}, {new_hash})
        self.assertEqual({row["date_reg"] for row in actual},
                         {"2026-02-01", "2026-02-02", "2026-03-01"})
        self.assertFalse((self.curated / "registration_year=2026" /
                          "registration_month=01").exists(),
                         "An atomic replacement must remove stale partitions")

    def test_incremental_year_does_not_rewrite_other_year(self) -> None:
        self.write_source(2025, [registration("2025-12-01")])
        self.run_build([2025])
        previous = self.snapshot(2025)
        manifest_path = self.artifacts / "year_2025_manifest.json"
        previous_manifest = (manifest_path.read_bytes(), manifest_path.stat().st_mtime_ns)
        self.write_source(2026, [registration("2026-01-01"), registration("2026-02-01")])
        self.run_build([2026])
        self.assertEqual(self.snapshot(2025), previous)
        self.assertEqual((manifest_path.read_bytes(), manifest_path.stat().st_mtime_ns),
                         previous_manifest)
        self.assertEqual(len(self.rows(2025)), 1)
        self.assertEqual(len(self.rows(2026)), 2)

    def test_identical_source_is_idempotent_without_rewriting_data(self) -> None:
        self.write_source(2026, [registration("2026-01-01"), registration("2026-02-01")])
        self.run_build([2026])
        previous = self.snapshot(2026)
        self.run_build([2026])
        self.assertEqual(self.snapshot(2026), previous)
        self.assertEqual(len(self.rows(2026)), 2)

    def test_unchanged_source_repairs_tampered_or_missing_output(self) -> None:
        self.write_source(2026, [registration("2026-01-01"), registration("2026-02-01")])
        self.run_build([2026])
        expected = {name: digest for name, (digest, _) in self.snapshot(2026).items()}
        for damage in ("tamper", "delete"):
            with self.subTest(damage=damage):
                target = self.tsv_files(2026)[0]
                if damage == "tamper":
                    target.write_text("tampered\trow\n", encoding="utf-8")
                else:
                    target.unlink()
                self.run_build([2026])
                actual = {name: digest for name, (digest, _) in self.snapshot(2026).items()}
                self.assertEqual(actual, expected,
                                 "A matching source hash cannot excuse corrupt output")
                self.assertEqual(len(self.rows(2026)), 2)

    def test_extra_partition_file_is_rejected_then_removed_on_rebuild(self) -> None:
        self.write_source(2026, [registration("2026-01-01"), registration("2026-02-01")])
        self.run_build([2026])
        expected = {name: digest for name, (digest, _) in self.snapshot(2026).items()}
        original = self.tsv_files(2026)[0]
        rogue = original.with_name("rogue.tsv")
        rogue.write_bytes(original.read_bytes())
        self.assertEqual(len(self.rows(2026)), 3,
                         "A directory-based reader would double-load the copied record")
        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            check(self.raw, self.curated, self.artifacts, [2026], data_asof=ASOF)
        self.run_build([2026])
        self.assertFalse(rogue.exists(), "An unchanged source must still repair extra output files")
        actual = {name: digest for name, (digest, _) in self.snapshot(2026).items()}
        self.assertEqual(actual, expected)
        self.assertEqual(len(self.rows(2026)), 2)
        report = check(self.raw, self.curated, self.artifacts, [2026], data_asof=ASOF)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["rows"], 2)

    def test_future_registration_is_rejected_against_explicit_asof(self) -> None:
        self.write_source(2026, [registration("2026-08-31"), registration("2026-09-01")])
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_build([2026])
        self.assertEqual(self.tsv_files(2026), [])
        self.assert_rejected_report(2026, 1)

    def test_registration_outside_source_year_is_rejected(self) -> None:
        self.write_source(2026, [registration("2025-12-31")])
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_build([2026])
        self.assertEqual(self.tsv_files(2026), [])
        self.assertEqual(self.tsv_files(2025), [])
        self.assert_rejected_report(2026, 1)

    def test_missing_required_fields_cannot_publish_a_partial_batch(self) -> None:
        invalid_rows = [registration("2026-01-01", **{field: None})
                        for field in ("date_reg", "type", "maker", "fuel", "state")]
        self.write_source(2026, [registration("2026-01-01"), *invalid_rows])
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_build([2026])
        self.assertEqual(self.tsv_files(2026), [])
        self.assert_rejected_report(2026, 5)

    def test_declared_hash_mismatch_is_an_integrity_failure(self) -> None:
        self.write_source(2026, [registration("2026-01-01")])
        metadata_path = self.raw / "cars_2026.metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["source_sha256"] = "0" * 64
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_build([2026])
        self.assertEqual(self.tsv_files(2026), [])


if __name__ == "__main__":
    unittest.main()
