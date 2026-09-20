"""Public JPJ registrations: immutable download, partitioned TSV, DQ and oracle.

The original synthetic application is not imported or modified. A source row is
identified by (file SHA-256, 1-based row ordinal), not its visible vehicle fields.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import urllib.request
import uuid

import pyarrow.parquet as pq

WAREHOUSE = Path(__file__).resolve().parents[1]
SOURCES = json.loads(Path(__file__).with_name("data_sources.json").read_text(encoding="utf-8"))
COLUMNS = ("date_reg", "type", "maker", "model", "colour", "fuel", "state")
TSV_COLUMNS = ("source_sha256", "source_row", "date_reg", "vehicle_type", "maker", "model", "colour", "fuel", "state")
VEHICLE_TYPES = {"motokar", "motokar_pelbagai_utiliti", "jip", "pick_up", "window_van"}
NULL = "\\N"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def remove_owned(path: Path, parent: Path) -> None:
    """Remove only generated child paths; never operate on an unchecked root."""
    resolved, root = path.resolve(), parent.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"Unsafe generated-directory removal: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def download(raw_dir: Path, years: list[int], refresh: bool = False) -> dict:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for year in years:
        url = SOURCES["files"].get(str(year))
        if not url:
            raise ValueError(f"Year {year} has no reviewed official source URL")
        destination = raw_dir / f"cars_{year}.parquet"
        metadata_file = raw_dir / f"cars_{year}.metadata.json"
        if destination.exists() and metadata_file.exists() and not refresh:
            meta = json.loads(metadata_file.read_text(encoding="utf-8"))
            if sha256(destination) == meta.get("source_sha256"):
                result[str(year)] = {"status": "cached", **meta}
                continue
            raise ValueError(f"Raw file checksum mismatch: {destination}; use --refresh to replace")
        temporary = destination.with_suffix(".parquet.part")
        request = urllib.request.Request(url, headers={"User-Agent": "JPJ-public-data-learning-pipeline/1.0"})
        try:
            h, size = hashlib.sha256(), 0
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as out:
                if response.status != 200 or not response.url.startswith("https://storage.data.gov.my/"):
                    raise ValueError("Unexpected official download response or redirect")
                headers = dict(response.headers.items())
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    out.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
            expected_size = headers.get("Content-Length") or headers.get("content-length")
            if expected_size and size != int(expected_size):
                raise ValueError("Incomplete download: Content-Length mismatch")
            parquet = pq.ParquetFile(temporary)
            if set(parquet.schema_arrow.names) != set(COLUMNS):
                raise ValueError(f"Unreviewed source schema: {parquet.schema_arrow.names}")
            metadata = {
                "source_url": url, "catalogue_url": SOURCES["catalogue_url"],
                "license": SOURCES["license"], "license_url": SOURCES["license_url"],
                "downloaded_at": now(), "data_asof": SOURCES["data_asof"],
                "catalogue_last_updated": SOURCES["catalogue_last_updated"],
                "source_sha256": h.hexdigest(), "source_size_bytes": size,
                "parquet_rows": parquet.metadata.num_rows,
                "http_status": 200, "http_headers": headers,
            }
            parquet.close()
            temporary.replace(destination)
            write_json(metadata_file, metadata)
            result[str(year)] = {"status": "downloaded", **metadata}
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
    return result


def source_rows(path: Path):
    parquet = pq.ParquetFile(path)
    if set(parquet.schema_arrow.names) != set(COLUMNS):
        raise ValueError(f"Unexpected source columns: {parquet.schema_arrow.names}")
    for batch in parquet.iter_batches(batch_size=65536, columns=list(COLUMNS)):
        yield from batch.to_pylist()


def normalize(row: dict, year: int, asof: date) -> tuple:
    values = []
    for name in COLUMNS:
        value = row[name]
        if name == "date_reg" and isinstance(value, datetime):
            if any((value.hour, value.minute, value.second, value.microsecond)):
                raise ValueError("timestamp_has_time")
            value = value.date()
        text = value.isoformat() if isinstance(value, date) else str(value).strip() if value is not None else ""
        if name == "date_reg":
            try:
                parsed = date.fromisoformat(text)
            except (ValueError, TypeError):
                raise ValueError("invalid_date") from None
            if parsed.year != year:
                raise ValueError("wrong_source_year")
            if parsed > asof:
                raise ValueError("after_data_asof")
        elif name == "type" and text not in VEHICLE_TYPES:
            raise ValueError("unknown_vehicle_type")
        if not text and name not in ("model", "colour"):
            raise ValueError(f"missing_{name}")
        if any(c in text for c in ("\t", "\r", "\n", "\x00")) or text == NULL:
            raise ValueError(f"unsafe_tsv_{name}")
        values.append(text if text else NULL)
    return tuple(values)


def fingerprints_match(manifest: dict, curated_dir: Path) -> bool:
    expected = {file["path"] for file in manifest.get("files", [])}
    year_dir = curated_dir / f"registration_year={manifest.get('year')}"
    actual = {str(path.relative_to(curated_dir)).replace("\\", "/") for path in year_dir.rglob("*") if path.is_file()}
    if expected != actual:
        return False
    for file in manifest.get("files", []):
        path = curated_dir / file["path"]
        if not path.is_file() or path.stat().st_size != file["bytes"] or sha256(path) != file["sha256"]:
            return False
    return bool(manifest.get("files"))


def build(raw_dir: Path, curated_dir: Path, artifact_dir: Path, years: list[int],
          data_asof: str = "2026-08-31", failure_after_rows: int | None = None) -> dict:
    raw_dir, curated_dir, artifact_dir = map(Path, (raw_dir, curated_dir, artifact_dir))
    curated_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    asof = date.fromisoformat(data_asof)
    results = {}
    for year in sorted(set(years)):
        source = raw_dir / f"cars_{year}.parquet"
        meta = json.loads((raw_dir / f"cars_{year}.metadata.json").read_text(encoding="utf-8"))
        digest = sha256(source)
        if digest != meta.get("source_sha256"):
            raise ValueError(f"Raw checksum mismatch for {year}")
        manifest_file = artifact_dir / f"year_{year}_manifest.json"
        old = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
        if (failure_after_rows is None and old.get("source_sha256") == digest
                and old.get("data_asof") == data_asof and fingerprints_match(old, curated_dir)):
            results[str(year)] = {"status": "skipped", **old}
            continue
        attempt = uuid.uuid4().hex
        staging_parent = curated_dir / ".staging"
        staging = staging_parent / attempt
        year_name = f"registration_year={year}"
        year_stage = staging / year_name
        year_stage.mkdir(parents=True)
        journal_file = artifact_dir / f"year_{year}_attempt.json"
        journal = {"year": year, "attempt_id": attempt, "started_at": now(), "status": "running", "source_sha256": digest}
        write_json(journal_file, journal)
        handles, counts, reasons, samples = {}, Counter(), Counter(), []
        input_rows, accepted = 0, 0
        min_date, max_date = None, None
        try:
            for ordinal, raw in enumerate(source_rows(source), 1):
                input_rows = ordinal
                try:
                    values = normalize(raw, year, asof)
                except ValueError as exc:
                    reasons[str(exc)] += 1
                    if len(samples) < 50:
                        samples.append({"source_row": ordinal, "reason": str(exc)})
                    continue
                month = int(values[0][5:7])
                if month not in handles:
                    partition = year_stage / f"registration_month={month:02d}"
                    partition.mkdir()
                    handles[month] = (partition / "part-00000.tsv").open("w", encoding="utf-8", newline="")
                handles[month].write("\t".join((digest, str(ordinal), *values)) + "\n")
                counts[month] += 1
                accepted += 1
                min_date = values[0] if min_date is None else min(min_date, values[0])
                max_date = values[0] if max_date is None else max(max_date, values[0])
                if failure_after_rows is not None and ordinal >= failure_after_rows:
                    raise RuntimeError(f"Injected batch interruption after {ordinal} rows")
            for handle in handles.values():
                handle.close()
            dq = {"year": year, "source_sha256": digest, "input_rows": input_rows,
                  "accepted_rows": accepted, "rejected_rows": sum(reasons.values()),
                  "reasons": dict(reasons), "rejected_samples": samples,
                  "duplicate_policy": "Preserve all source rows; no visible-field deduplication",
                  "source_identity": ["source_sha256", "source_row"],
                  "min_date": min_date, "max_date": max_date, "checked_at": now()}
            write_json(artifact_dir / f"year_{year}_dq.json", dq)
            if reasons or not accepted:
                raise ValueError(f"Year {year} failed DQ: {dict(reasons)}; input_rows={input_rows}")
            file_records = []
            for file in sorted(year_stage.rglob("*.tsv")):
                month = int(file.parent.name.split("=")[1])
                file_records.append({"path": str(file.relative_to(staging)).replace("\\", "/"),
                                     "rows": counts[month], "bytes": file.stat().st_size, "sha256": sha256(file)})
            manifest = {"year": year, "source_sha256": digest, "source_url": meta.get("source_url"),
                        "license": meta.get("license"), "data_asof": data_asof, "rows": accepted,
                        "min_date": min_date, "max_date": max_date,
                        "columns": list(TSV_COLUMNS), "partitions": ["registration_year", "registration_month"],
                        "null_marker": NULL, "files": file_records, "built_at": now()}
            destination = curated_dir / year_name
            backup = staging / "previous"
            if destination.exists():
                destination.replace(backup)
            try:
                year_stage.replace(destination)
                write_json(manifest_file, manifest)
            except Exception:
                if destination.exists():
                    remove_owned(destination, curated_dir)
                if backup.exists():
                    backup.replace(destination)
                raise
            results[str(year)] = {"status": "built", **manifest}
            journal.update(status="completed", completed_at=now(), rows=accepted)
            write_json(journal_file, journal)
        except Exception as exc:
            journal.update(status="failed", failed_at=now(), error=str(exc), rows_read=input_rows)
            write_json(journal_file, journal)
            raise
        finally:
            for handle in handles.values():
                if not handle.closed:
                    handle.close()
            remove_owned(staging, staging_parent)
    # Oracle is calculated again from the raw source, never by reading the TSV.
    oracle_summary = generate_oracle(raw_dir, artifact_dir, years, data_asof)
    report = {"created_at": now(), "data_asof": data_asof, "years": results, "oracle": oracle_summary}
    write_json(artifact_dir / "build_summary.json", report)
    return report


def oracle_counts(raw_dir: Path, years: list[int], data_asof: str) -> Counter:
    counts = Counter()
    asof = date.fromisoformat(data_asof)
    for year in sorted(set(years)):
        for row in source_rows(Path(raw_dir) / f"cars_{year}.parquet"):
            values = normalize(row, year, asof)
            counts[(year, int(values[0][5:7]), values[2], values[5], values[6])] += 1
    return counts


def write_table(path: Path, header: tuple, rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def generate_oracle(raw_dir: Path, artifact_dir: Path, years: list[int], data_asof: str) -> dict:
    counts = oracle_counts(raw_dir, years, data_asof)
    monthly, maker, fuel, month_maker_fuel, dimensions = Counter(), Counter(), Counter(), Counter(), Counter()
    for (year, month, brand, energy, state), n in counts.items():
        monthly[(year, month)] += n
        maker[(year, brand)] += n
        fuel[(year, energy)] += n
        month_maker_fuel[(year, month, brand, energy)] += n
        for key in (("total", "ALL", "ALL"), ("month", str(year), f"{month:02d}"),
                    ("maker", brand, "ALL"), ("fuel", energy, "ALL"), ("state", state, "ALL"),
                    ("month_maker", f"{year}-{month:02d}", brand), ("month_fuel", f"{year}-{month:02d}", energy)):
            dimensions[key] += n
    write_table(artifact_dir / "oracle_month_maker_fuel.tsv", ("registration_year", "registration_month", "maker", "fuel", "registrations"),
                ((*key, value) for key, value in sorted(month_maker_fuel.items())))
    with (artifact_dir / "expected_aggregates.tsv").open("w", encoding="utf-8", newline="") as stream:
        for key, value in sorted(dimensions.items()):
            stream.write("\t".join((*key, str(value))) + "\n")
    for name, counter, header in (("monthly", monthly, ("registration_year", "registration_month", "registrations")),
                                 ("maker", maker, ("registration_year", "maker", "registrations")),
                                 ("fuel", fuel, ("registration_year", "fuel", "registrations"))):
        write_table(artifact_dir / f"oracle_{name}.tsv", header, ((*key, value) for key, value in sorted(counter.items())))
    summary = {"rows": sum(counts.values()), "month_maker_fuel_groups": len(month_maker_fuel),
               "month_maker_fuel_state_groups": len(counts), "month_groups": len(monthly),
               "expected_aggregate_rows": len(dimensions), "years": sorted(set(years)),
               "data_asof": data_asof, "full_year_comparison_warning": "2026 is partial year; compare matched available months only",
               "monthly": [{"year": y, "month": m, "registrations": n} for (y, m), n in sorted(monthly.items())],
               "method": "Python Counter from a separate pass over raw Parquet, not curated TSV or Hive SQL"}
    write_json(artifact_dir / "expected_aggregates_summary.json", summary)
    return summary


def check(raw_dir: Path, curated_dir: Path, artifact_dir: Path, years: list[int], data_asof: str = "2026-08-31") -> dict:
    observed, reports = Counter(), {}
    for year in sorted(set(years)):
        manifest = json.loads((artifact_dir / f"year_{year}_manifest.json").read_text(encoding="utf-8"))
        digest = sha256(raw_dir / f"cars_{year}.parquet")
        if digest != manifest["source_sha256"] or not fingerprints_match(manifest, curated_dir):
            raise ValueError(f"Source/output fingerprint mismatch for {year}")
        seen = set()
        for record in manifest["files"]:
            file = curated_dir / record["path"]
            month = int(file.parent.name.split("=")[1])
            count = 0
            with file.open(encoding="utf-8", newline="") as stream:
                for values in csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE):
                    if len(values) != len(TSV_COLUMNS):
                        raise ValueError("Invalid TSV field count")
                    source_hash, ordinal, day, _, maker, _, _, fuel, state = values
                    ordinal = int(ordinal)
                    if source_hash != digest or ordinal in seen:
                        raise ValueError("Invalid or duplicate source-row identity")
                    parsed = date.fromisoformat(day)
                    if parsed.year != year or parsed.month != month:
                        raise ValueError("Partition/date mismatch")
                    seen.add(ordinal)
                    observed[(year, month, maker, fuel, state)] += 1
                    count += 1
            if count != record["rows"]:
                raise ValueError("Partition row-count mismatch")
        expected_rows = pq.ParquetFile(raw_dir / f"cars_{year}.parquet").metadata.num_rows
        if len(seen) != expected_rows or min(seen) != 1 or max(seen) != expected_rows:
            raise ValueError("Missing source rows or ordinal outside source range")
        reports[str(year)] = {"rows": len(seen), "unique_source_row_identities": len(seen), "files": len(manifest["files"])}
    expected = oracle_counts(raw_dir, years, data_asof)
    if observed != expected:
        raise ValueError("Curated aggregates differ from independent raw-data oracle")
    result = {"checked_at": now(), "status": "passed", "rows": sum(observed.values()),
              "groups_checked": len(expected), "years": reports,
              "checks": ["exact partition file set", "source/output SHA256", "partition row counts", "partition/date agreement",
                         "source row identities complete and unique", "raw Python oracle reconciliation"]}
    write_json(artifact_dir / "check_report.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("download", "build", "check"))
    parser.add_argument("--years", type=int, nargs="+", default=[2025, 2026])
    parser.add_argument("--raw-dir", type=Path, default=WAREHOUSE / "data/raw")
    parser.add_argument("--curated-dir", type=Path, default=WAREHOUSE / "data/curated")
    parser.add_argument("--artifact-dir", type=Path, default=WAREHOUSE / "artifacts/python")
    parser.add_argument("--data-asof", default=SOURCES["data_asof"])
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--failure-after-rows", type=int)
    args = parser.parse_args()
    if args.command == "download":
        result = download(args.raw_dir, args.years, args.refresh)
    elif args.command == "build":
        result = build(args.raw_dir, args.curated_dir, args.artifact_dir, args.years, args.data_asof, args.failure_after_rows)
    else:
        result = check(args.raw_dir, args.curated_dir, args.artifact_dir, args.years, args.data_asof)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
