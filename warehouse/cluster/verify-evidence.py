#!/usr/bin/env python3
"""Reject local-only or failed runs; record application-specific YARN evidence."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen


APPLICATION_RE = re.compile(r"application_\d+_\d+")


def application_ids(log: str) -> list[str]:
    return sorted(set(APPLICATION_RE.findall(log)))


def require_success(app: dict, expected_type: str) -> None:
    if app.get("applicationType") != expected_type:
        raise ValueError(f"{app.get('id')}: expected {expected_type}, got {app.get('applicationType')}")
    if app.get("state") != "FINISHED" or app.get("finalStatus") != "SUCCEEDED":
        raise ValueError(f"{app.get('id')}: not FINISHED/SUCCEEDED")
    if app.get("unmanagedApplication"):
        raise ValueError(f"{app.get('id')}: expected a YARN-managed application")
    if expected_type == "TEZ":
        counters = dict(re.findall(r"\b(submittedDAGs|successfulDAGs|failedDAGs|killedDAGs)=(\d+)\b", app.get("diagnostics", "")))
        if counters != {"submittedDAGs": "1", "successfulDAGs": "1", "failedDAGs": "0", "killedDAGs": "0"}:
            raise ValueError(f"{app.get('id')}: missing exactly one successful Tez DAG and zero failures")


def exact_rows(path: Path, expected: list[str]) -> None:
    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if rows != expected:
        raise ValueError(f"Unexpected result in {path.name}: {rows!r}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("Usage: python3 verify-evidence.py ARTIFACT_DIRECTORY")
    artifacts = Path(argv[1]).resolve()
    source = Path(__file__).resolve().parent
    if artifacts.joinpath("hdfs-roundtrip.txt").read_bytes() != source.joinpath("smoke/words.txt").read_bytes():
        raise ValueError("HDFS roundtrip differs from the exact input bytes")
    exact_rows(artifacts / "wordcount-result.tsv", ["hdfs\t1", "hive\t2", "yarn\t3"])
    exact_rows(artifacts / "hive-smoke-result.tsv", ["alpha\t15", "beta\t20"])
    job_ids = {}
    for kind, filename in (("MAPREDUCE", "mapreduce-smoke.log"), ("TEZ", "hive-smoke.log")):
        ids = application_ids((artifacts / filename).read_text(encoding="utf-8", errors="replace"))
        if len(ids) != 1:
            raise ValueError(f"Expected exactly one {kind} application in {filename}; got {ids}")
        job_ids[kind] = ids[0]
    applications = {}
    for kind, app_id in job_ids.items():
        previous = None
        for _ in range(60):
            with urlopen(f"http://127.0.0.1:18088/ws/v1/cluster/apps/{app_id}", timeout=10) as response:
                app = json.load(response)["app"]
            state = app.get("state")
            if state != previous:
                print(f"{kind} {app_id}: {state}/{app.get('finalStatus')}", flush=True)
                previous = state
            if state in {"FINISHED", "FAILED", "KILLED"}:
                break
            time.sleep(2)
        (artifacts / f"{kind.lower()}-yarn-application.json").write_text(json.dumps(app, indent=2) + "\n", encoding="utf-8")
        require_success(app, kind)
        applications[kind.lower()] = app
    evidence = {
        "status": "PASS",
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": artifacts.name,
        "scope": "Single-node pseudo-distributed HDFS + YARN + Hive/Tez acceptance, synthetic smoke input only",
        "image": "apache/hive:4.0.1@sha256:5194161ef50b80875f937dff04936df047cbe894e9727ab8f0606349345b1bd3",
        "versions": {"hive": "4.0.1", "hadoop": "3.3.6", "tez": "0.10.4", "java": "8u342"},
        "hdfs_roundtrip": "byte_equal",
        "input_sha256": {name: sha256(source / "smoke" / name) for name in ("words.txt", "values.tsv")},
        "expected_mapreduce": {"hdfs": 1, "hive": 2, "yarn": 3},
        "expected_hive": {"alpha": 15, "beta": 20},
        "applications": applications,
        "limits": "Not production, distributed HA, Kerberos, Kafka, HBase, or business-data validation",
    }
    (artifacts / "acceptance.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
