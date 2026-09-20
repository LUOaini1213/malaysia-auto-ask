"""Verified marginal aggregates -> one atomic, versioned MySQL snapshot."""
from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .common import ARTIFACTS, DATASET, METRIC, SOURCE, connect, digest

KINDS = {"total", "month", "maker", "fuel", "state", "month_maker", "month_fuel"}
PINS = {
    "hive_aggregates.tsv": "c2950a114e7dabcea0d760fe2031f12fd937a3e1ef3adc2d3e6f5bd9e36317b6",
    "validation.json": "7e60ab0c57973074fb8f69f71afb1d0262be731fcdfeca40245f8122d6d97113",
    "evidence_manifest.json": "0dc3c230ec4792f8ad756dcc62e8e6cd2463d8cf78f64df45694239404b7416d",
}
ORACLE = Path(__file__).with_name("inputs") / "expected_aggregates.tsv"
ORACLE_HASH = "73a00db82a41ea68a54763328fbbc1972abb9e0bc73a5025ab3275d528b5c301"


def parse_rows(text):
    rows = {}
    for number, fields in enumerate(csv.reader(io.StringIO(text), delimiter="\t"), 1):
        if len(fields) != 4:
            raise ValueError(f"INVALID_SCHEMA at row {number}")
        kind, key1, key2, count = fields
        if kind not in KINDS or not all([key1, key2]) or max(len(key1), len(key2)) > 128:
            raise ValueError(f"INVALID_DIMENSION at row {number}")
        if not re.fullmatch(r"[1-9][0-9]*", count):
            raise ValueError(f"INVALID_COUNT at row {number}")
        key = (kind, key1, key2)
        if key in rows:
            raise ValueError(f"DUPLICATE_AGGREGATE at row {number}")
        rows[key] = int(count)
        if kind == "month" and not (re.fullmatch(r"20\d{2}", key1) and re.fullmatch(r"0[1-9]|1[0-2]", key2)):
            raise ValueError("INVALID_MONTH")
        if kind.startswith("month_") and not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", key1):
            raise ValueError("INVALID_MONTH")
    if not rows or {key[0] for key in rows} != KINDS:
        raise ValueError("MISSING_AGGREGATE_FAMILY")
    total = rows.get(("total", "ALL", "ALL"))
    for kind in KINDS - {"total"}:
        if sum(v for k, v in rows.items() if k[0] == kind) != total:
            raise ValueError(f"TOTAL_MISMATCH:{kind}")
    for key, value in rows.items():
        if key[0] == "month":
            month = key[1] + "-" + key[2]
            for dim in ["month_maker", "month_fuel"]:
                if sum(v for k, v in rows.items() if k[0] == dim and k[1] == month) != value:
                    raise ValueError(f"MONTH_MISMATCH:{month}:{dim}")
    return rows


def load_snapshot(source_dir=SOURCE):
    source_dir = Path(source_dir)
    for name, expected in PINS.items():
        if digest(source_dir / name) != expected:
            raise ValueError(f"SOURCE_HASH_MISMATCH:{name}")
    if digest(ORACLE) != ORACLE_HASH:
        raise ValueError("ORACLE_HASH_MISMATCH")
    validation = json.loads((source_dir / "validation.json").read_text(encoding="utf-8"))
    if validation.get("status") != "passed" or not validation.get("aggregate_comparison", {}).get("passed"):
        raise ValueError("HIVE_VALIDATION_NOT_PASSED")
    if not validation.get("yarn_applications") or not all(x["succeeded"] for x in validation["yarn_applications"]):
        raise ValueError("YARN_JOB_NOT_SUCCEEDED")
    rows = parse_rows((source_dir / "hive_aggregates.tsv").read_text(encoding="utf-8"))
    oracle = parse_rows(ORACLE.read_text(encoding="utf-8"))
    if rows != oracle or len(rows) != validation["aggregate_comparison"]["compared_groups"]:
        raise ValueError("HIVE_PYTHON_RECONCILIATION_FAILED")
    if rows[("total", "ALL", "ALL")] != validation["expected_total"]:
        raise ValueError("SOURCE_TOTAL_MISMATCH")
    version = validation["run_id"] + "_" + PINS["hive_aggregates.tsv"][:12]
    source = {"dataset": DATASET, "version": version, "data_asof": "2026-08-31",
        "hashes": {"hive_aggregates_sha256": PINS["hive_aggregates.tsv"], "oracle_aggregates_sha256": ORACLE_HASH,
                   "validation_sha256": PINS["validation.json"], "evidence_manifest_sha256": PINS["evidence_manifest.json"]},
        "official_url": "https://data.gov.my/data-catalogue/registration_transactions_car",
        "license": "CC BY 4.0; source JPJ / data.gov.my", "upstream_run_id": validation["run_id"],
        "metric_definition": METRIC, "mysql_aggregate_rows": len(rows),
        "represented_registration_rows": validation["expected_total"],
        "available_dimensions": sorted(KINDS),
        "limitation": "MySQL stores frozen marginal aggregates, not registration-level records. No maker x fuel or month x office joint table."}
    return source, rows


def import_verified(source, rows, connection, fail_after=None):
    """Caller must validate source first. fail_after is only for rollback testing."""
    version = source["version"]
    with connection.cursor() as cur:
        cur.execute("SELECT GET_LOCK('jpj_serving_import',10) AS acquired")
        if cur.fetchone()["acquired"] != 1:
            raise RuntimeError("IMPORT_LOCK_TIMEOUT")
    try:
        connection.begin()
        with connection.cursor() as cur:
            cur.execute("SELECT version FROM dataset_versions WHERE version=%s", (version,))
            existing = cur.fetchone()
            if existing:
                cur.execute("SELECT dimension,key1,key2,registrations FROM aggregates WHERE version=%s", (version,))
                stored = {(r["dimension"], r["key1"], r["key2"]): r["registrations"] for r in cur.fetchall()}
                if stored != rows:
                    raise ValueError("EXISTING_VERSION_CORRUPTED")
                status = "unchanged"
            else:
                cur.execute("INSERT INTO dataset_versions(version,source_json,aggregate_rows,represented_registration_rows) VALUES (%s,%s,%s,%s)",
                    (version, json.dumps(source, ensure_ascii=False), len(rows), source["represented_registration_rows"]))
                for index, ((kind, key1, key2), count) in enumerate(sorted(rows.items()), 1):
                    month = key1 + "-" + key2 if kind == "month" else key1 if kind.startswith("month_") else None
                    maker = key2.strip().upper() if kind == "month_maker" else key1.strip().upper() if kind == "maker" else None
                    fuel = key2 if kind == "month_fuel" else key1 if kind == "fuel" else None
                    cur.execute("INSERT INTO aggregates(version,dimension,key1,key2,registrations,`year_month`,maker_norm,fuel) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (version, kind, key1, key2, count, month, maker, fuel))
                    if fail_after is not None and index >= fail_after:
                        raise RuntimeError("INJECTED_IMPORT_FAILURE")
                cur.execute("SELECT dimension,key1,key2,registrations FROM aggregates WHERE version=%s", (version,))
                actual = {(r["dimension"], r["key1"], r["key2"]): r["registrations"] for r in cur.fetchall()}
                if actual != rows:
                    raise ValueError("MYSQL_RECONCILIATION_FAILED")
                status = "imported"
            cur.execute("INSERT INTO active_dataset(singleton,version) VALUES (1,%s) ON DUPLICATE KEY UPDATE version=%s", (version, version))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        with connection.cursor() as cur:
            cur.execute("SELECT RELEASE_LOCK('jpj_serving_import')")
        connection.commit()
    return {"status": status, "version": version, "mysql_aggregate_rows": len(rows),
            "represented_registration_rows": source["represented_registration_rows"],
            "reconciled_hive_python_mysql_groups": len(rows), "source": source}


def main():
    source, rows = load_snapshot()
    with connect("writer") as connection:
        result = import_verified(source, rows, connection)
    result["executed_at_utc"] = datetime.now(timezone.utc).isoformat()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "import_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__": main()
