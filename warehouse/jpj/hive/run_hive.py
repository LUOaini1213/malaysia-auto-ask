"""Load JPJ partitions into real HDFS, execute Hive on YARN, verify its output.

Run from Windows (WSL Docker) or Linux (Docker). No shell interpolation is used.
The cluster must already be started with warehouse/cluster/start.ps1 or start.sh.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

WAREHOUSE = Path(__file__).resolve().parents[2]
CONTAINER = "malaysia-warehouse-cluster"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validated_partitions(curated: Path, artifact_dir: Path, raw_dir: Path) -> list[dict]:
    """Verify producer manifests, including fields not present in the aggregates."""
    records = []
    for year_dir in sorted(curated.glob("registration_year=*")):
        if not re.fullmatch(r"registration_year=\d{4}", year_dir.name):
            raise ValueError(f"Invalid year partition name: {year_dir.name}")
        year = int(year_dir.name.split("=")[1])
        manifest = json.loads((artifact_dir / f"year_{year}_manifest.json").read_text(encoding="utf-8"))
        if sha256(raw_dir / f"cars_{year}.parquet") != manifest["source_sha256"]:
            raise ValueError(f"Raw source changed since build: {year}")
        for record in manifest["files"]:
            file = (curated / record["path"]).resolve()
            if year_dir.resolve() not in file.parents:
                raise ValueError("Manifest file escapes its annual partition")
            if not file.is_file() or file.stat().st_size != record["bytes"] or sha256(file) != record["sha256"]:
                raise ValueError(f"Curated partition changed since build: {file}")
            records.append({"path": file.relative_to(WAREHOUSE.resolve()).as_posix(),
                            "bytes": record["bytes"], "sha256": record["sha256"], "rows": record["rows"]})
    expected = {(WAREHOUSE / p["path"]).resolve() for p in records}
    actual = {p.resolve() for p in curated.rglob("*") if p.is_file()}
    if not records or expected != actual or len(expected) != len(records):
        raise ValueError("Curated file set is missing, duplicated, or contains unmanifested files")
    return records


def parse_aggregates(text: str) -> dict[tuple[str, str, str], int]:
    result = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) != 4:
            raise ValueError(f"aggregate line {number}: expected 4 columns")
        key = tuple(cells[:3])
        if key in result:
            raise ValueError(f"duplicate aggregate key: {key}")
        value = int(cells[3])
        if value < 0:
            raise ValueError(f"negative count: {key}")
        result[key] = value
    if ("total", "ALL", "ALL") not in result:
        raise ValueError("aggregate total is absent")
    return result


def compare_aggregates(expected: dict, actual: dict) -> dict:
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatches = [
        {"key": list(key), "python": expected[key], "hive": actual[key]}
        for key in sorted(set(expected) & set(actual))
        if expected[key] != actual[key]
    ]
    return {
        "passed": not missing and not extra and not mismatches,
        "compared_groups": len(expected),
        "dimensions": dict(Counter(key[0] for key in expected)),
        "missing": missing, "extra": extra, "mismatches": mismatches,
    }


def validate_checks(text: str, expected_total: int) -> dict:
    actual = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        key, value = line.split("\t")
        if key in actual:
            raise ValueError(f"duplicate quality key: {key}")
        actual[key] = int(value)
    expected = {
        "ods_count": expected_total, "dwd_count": expected_total,
        "distinct_lineage_count": expected_total,
        "invalid_partition_count": 0, "invalid_lineage_count": 0,
    }
    return {"passed": actual == expected, "actual": actual, "expected": expected}


class Cluster:
    def __init__(self, output: Path, distribution: str):
        self.output = output
        self.prefix = ["wsl.exe", "-d", distribution, "--"] if os.name == "nt" else []
        self.sequence = 0
        self.logs: list[str] = []

    def run(self, *args: str, timeout: int = 1200) -> str:
        self.sequence += 1
        command = self.prefix + ["docker", "exec", "-u", "hive", CONTAINER, *args]
        print(f"[{self.sequence}] {' '.join(args[:5])}", flush=True)
        log = self.output / f"command_{self.sequence:02d}.log"
        try:
            completed = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            def decoded(value):
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")
            record = ("COMMAND " + json.dumps(command, ensure_ascii=False) + "\nTIMEOUT\n"
                      + decoded(exc.stdout) + "\nSTDERR\n" + decoded(exc.stderr))
            log.write_text(record, encoding="utf-8")
            self.logs.append(record)
            raise RuntimeError(f"Command timed out; partial output saved to {log}") from exc
        record = (
            "COMMAND " + json.dumps(command, ensure_ascii=False) + "\n"
            + "STDOUT\n" + completed.stdout + "\nSTDERR\n" + completed.stderr
        )
        log.write_text(record, encoding="utf-8")
        self.logs.append(record)
        if completed.returncode:
            raise RuntimeError(f"Command failed ({completed.returncode}); see {log}\n{record[-3500:]}")
        return completed.stdout

    def hdfs(self, *args: str) -> str:
        return self.run("hdfs", "dfs", *args)

    def read_directory(self, directory: str) -> str:
        # UNION ALL may write HIVE_UNION_SUBDIR_n/part files, not flat files.
        # List exact leaves rather than assuming one physical output layout.
        listing = self.hdfs("-ls", "-R", directory)
        files = []
        for line in listing.splitlines():
            if not line.startswith("-"):
                continue
            columns = line.split(None, 7)
            if len(columns) != 8 or not columns[7].startswith(directory + "/"):
                raise ValueError("Unexpected HDFS output listing")
            path = columns[7]
            relative = path[len(directory) + 1:]
            if any(part.startswith(("_", ".")) for part in relative.split("/")):
                continue
            files.append(path)
        if not files:
            raise ValueError(f"No output data files under {directory}")
        return self.hdfs("-cat", *sorted(files))


def business_summary(aggregates: dict) -> dict:
    months = sorted((int(k[1]), int(k[2])) for k in aggregates if k[0] == "month")
    if not months:
        raise ValueError("No monthly observations")
    latest_year = months[-1][0]
    comparison_year = latest_year - 1
    # Only compare identical observed months in both years, never partial/full years.
    common = sorted(
        {month for year, month in months if year == latest_year}
        & {month for year, month in months if year == comparison_year}
    )
    totals = {}
    makers: dict[int, Counter] = {}
    maker_labels: dict[str, set] = {}
    electric = {}
    for year in (comparison_year, latest_year):
        totals[year] = sum(aggregates[("month", str(year), f"{month:02}")] for month in common)
        makers[year] = Counter()
        electric[year] = 0
        for month in common:
            period = f"{year}-{month:02}"
            for (dimension, first, second), count in aggregates.items():
                if first != period:
                    continue
                if dimension == "month_maker":
                    normalized_maker = second.strip().upper()
                    maker_labels.setdefault(normalized_maker, set()).add(second)
                    makers[year][normalized_maker] += count
                elif dimension == "month_fuel" and second == "electric":
                    electric[year] += count
    previous, current = totals[comparison_year], totals[latest_year]
    return {
        "metric": "JPJ car registration transactions (not sales)",
        "analysis_method": "matched-month totals; case-normalized maker labels v1",
        "maker_normalization": "trim and uppercase for analysis only; preserve original labels in ODS/DWD/ADS and reconciliation",
        "maker_case_variants": {key: sorted(labels) for key, labels in sorted(maker_labels.items()) if len(labels) > 1},
        "observed_year_months": [f"{year}-{month:02}" for year, month in months],
        "comparison_years": [comparison_year, latest_year], "common_months": common,
        "comparable_registrations": totals,
        "comparable_yoy_pct": round((current / previous - 1) * 100, 4) if previous else None,
        "electric_registrations": electric,
        "electric_share_pct": {
            year: round(electric[year] / totals[year] * 100, 4) if totals[year] else None
            for year in totals
        },
        "top_makers_current_comparable_period": [
            {"maker": maker, "registrations": value,
             "share_pct": round(value / current * 100, 4) if current else None,
             "previous_registrations": makers[comparison_year][maker]}
            for maker, value in makers[latest_year].most_common(10)
        ],
        "geography_caveat": "state is the JPJ office or partner portal; Rakan Niaga is not a state or residence",
    }


def execute(args: argparse.Namespace) -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    output = WAREHOUSE / "artifacts" / "hive" / run_id
    output.mkdir(parents=True)
    report = {"status": "running", "run_id": run_id,
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "execution_scope": "single-node Docker HDFS + YARN + Hive/Tez lab"}
    report_file = output / "validation.json"
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Evidence: {output}", flush=True)
    try:
        curated = WAREHOUSE / "data" / "curated"
        snapshots = validated_partitions(curated, WAREHOUSE / "artifacts/python", WAREHOUSE / "data/raw")
        oracle_path = Path(args.oracle).resolve()
        expected_text = oracle_path.read_text(encoding="utf-8")
        expected = parse_aggregates(expected_text)
        if expected[("total", "ALL", "ALL")] != sum(p["rows"] for p in snapshots):
            raise ValueError("Oracle total does not match the verified producer manifests")
        # Freeze the oracle and partition manifest with this run's evidence.
        (output / "expected_aggregates.tsv").write_text(expected_text, encoding="utf-8")
        (output / "input_partitions.json").write_text(json.dumps(snapshots, indent=2), encoding="utf-8")
        hdfs_root = f"/warehouse/jpj/runs/{run_id}"
        database = "jpj_" + run_id
        sql = (Path(__file__).with_name("warehouse.sql")).read_text(encoding="utf-8")
        replacements = {"__DATABASE__": database, "__HDFS_INPUT__": hdfs_root + "/curated",
                        "__HDFS_DWD__": hdfs_root + "/dwd", "__HDFS_ADS__": hdfs_root + "/ads",
                        "__HDFS_RESULTS__": hdfs_root + "/results"}
        for token, value in replacements.items():
            sql = sql.replace(token, value)
        sql_path = output / "warehouse.sql"
        sql_path.write_text(sql, encoding="utf-8")
        report.update(database=database, hdfs_prefix=hdfs_root,
                      expected_total=expected[("total", "ALL", "ALL")],
                      partition_files=len(snapshots), oracle_sha256=sha256(oracle_path))
        cluster = Cluster(output, args.distribution)
        cluster.hdfs("-mkdir", "-p", hdfs_root)
        cluster.hdfs("-put", "/warehouse/data/curated", hdfs_root + "/curated")
        hdfs_listing = cluster.hdfs("-ls", "-R", hdfs_root + "/curated")
        (output / "hdfs_listing.txt").write_text(hdfs_listing, encoding="utf-8")
        relative_sql = sql_path.relative_to(WAREHOUSE).as_posix()
        cluster.run("beeline", "-u", "jdbc:hive2://localhost:10000/default", "-n", "hive",
                    "--force=false", "--outputformat=tsv2", "-f", "/warehouse/" + relative_sql)
        actual_text = cluster.read_directory(hdfs_root + "/results/aggregates")
        checks_text = cluster.read_directory(hdfs_root + "/results/checks")
        (output / "hive_aggregates.tsv").write_text(actual_text, encoding="utf-8")
        (output / "hive_checks.tsv").write_text(checks_text, encoding="utf-8")
        actual = parse_aggregates(actual_text)
        report["aggregate_comparison"] = compare_aggregates(expected, actual)
        report["quality_checks"] = validate_checks(checks_text, report["expected_total"])
        # An actual YARN application must be present and finish successfully.
        application_ids = sorted(set(re.findall(r"application_\d+_\d+", "\n".join(cluster.logs))))
        report["yarn_applications"] = []
        for app_id in application_ids:
            final = ""
            for attempt in range(15):
                final = cluster.run("yarn", "application", "-status", app_id, timeout=90)
                if re.search(r"State\s*:\s*(FINISHED|FAILED|KILLED)\b", final):
                    break
                time.sleep(4)
            succeeded = bool(re.search(r"Final-State\s*:\s*SUCCEEDED\b", final))
            report["yarn_applications"].append({"id": app_id, "succeeded": succeeded})
        inputs_unchanged = snapshots == validated_partitions(
            curated, WAREHOUSE / "artifacts/python", WAREHOUSE / "data/raw")
        report["input_files_unchanged_during_run"] = inputs_unchanged
        passed = (report["aggregate_comparison"]["passed"] and report["quality_checks"]["passed"]
                  and bool(application_ids) and all(a["succeeded"] for a in report["yarn_applications"])
                  and inputs_unchanged)
        if not passed:
            raise RuntimeError("Validation did not pass; inspect validation.json and command logs")
        summary = business_summary(actual)
        (output / "business_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        report["status"] = "passed"
    except (KeyboardInterrupt, SystemExit) as exc:
        report["status"] = "interrupted"
        report["error"] = str(exc) or type(exc).__name__
        raise
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        raise
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    return output


def reanalyse(run: Path) -> None:
    """Rebuild analysis from frozen, already accepted Hive exports; no cluster job."""
    validation = json.loads((run / "validation.json").read_text(encoding="utf-8"))
    if validation.get("status") != "passed":
        raise ValueError("Analysis requires a passed warehouse run")
    actual = parse_aggregates((run / "hive_aggregates.tsv").read_text(encoding="utf-8"))
    expected = parse_aggregates((run / "expected_aggregates.tsv").read_text(encoding="utf-8"))
    if not compare_aggregates(expected, actual)["passed"]:
        raise ValueError("Accepted exports no longer match their frozen Python oracle")
    if not validate_checks((run / "hive_checks.tsv").read_text(encoding="utf-8"), validation["expected_total"])["passed"]:
        raise ValueError("Quality checks no longer agree")
    summary = business_summary(actual)
    summary["analysis_generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    summary["derived_from_run"] = validation["run_id"]
    (run / "business_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", default=str(WAREHOUSE / "artifacts/python/expected_aggregates.tsv"))
    parser.add_argument("--distribution", default="Ubuntu-24.04")
    parser.add_argument("--analyse-existing", type=Path, help="Rebuild only the analysis from an accepted local run")
    args = parser.parse_args()
    if args.analyse_existing:
        reanalyse(args.analyse_existing.resolve())
    else:
        execute(args)


if __name__ == "__main__":
    main()
