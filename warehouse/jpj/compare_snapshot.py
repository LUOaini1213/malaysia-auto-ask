"""Compare a fresh Python build with the committed 2026-09-17 aggregates.

Run after `pipeline.py download`, `build` and `check`. It reads only local build
artifacts and the committed frozen input, so it needs no network and no cluster:

    python warehouse/jpj/compare_snapshot.py
    python warehouse/jpj/compare_snapshot.py --record warehouse/evidence/refresh_check_YYYYMMDD.json

Exit 1 when the fresh independent-oracle aggregates differ from
warehouse/serving/inputs/expected_aggregates.tsv (compared after normalising line
endings, because the committed file is kept byte-for-byte with CRLF endings).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

WAREHOUSE = Path(__file__).resolve().parents[1]
COMMITTED = WAREHOUSE / "serving" / "inputs" / "expected_aggregates.tsv"


def lines(path: Path) -> list[str]:
    return path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8").splitlines()


def compare(artifact_dir: Path) -> dict:
    summary = json.loads((artifact_dir / "build_summary.json").read_text(encoding="utf-8"))
    check_report = json.loads((artifact_dir / "check_report.json").read_text(encoding="utf-8"))
    fresh, committed = lines(artifact_dir / "expected_aggregates.tsv"), lines(COMMITTED)
    fresh_set, committed_set = set(fresh), set(committed)
    years = {}
    for year, item in sorted(summary["years"].items()):
        snapshot = item.get("snapshot") or {}
        years[year] = {"source_sha256": item["source_sha256"], "rows": item["rows"],
                       "excluded_after_data_asof": item.get("excluded_after_data_asof", 0),
                       "after_asof_policy": item.get("after_asof_policy", "reject_year"),
                       "matches_recorded_snapshot": snapshot.get("matches_recorded_snapshot")}
    digest = hashlib.sha256("\n".join(fresh).encode("utf-8") + b"\n").hexdigest()
    committed_digest = hashlib.sha256("\n".join(committed).encode("utf-8") + b"\n").hexdigest()
    return {
        "data_asof": summary["data_asof"],
        "check_status": check_report.get("status"),
        "years": years,
        "rows": summary["oracle"]["rows"],
        "aggregate_rows": len(fresh),
        "committed_aggregate_rows": len(committed),
        "only_in_fresh": len(fresh_set - committed_set),
        "only_in_committed": len(committed_set - fresh_set),
        "fresh_aggregates_sha256_lf": digest,
        "committed_aggregates_sha256_lf": committed_digest,
        "identical": fresh == committed and check_report.get("status") == "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artifact-dir", type=Path, default=WAREHOUSE / "artifacts" / "python")
    parser.add_argument("--record", type=Path, help="Also write the comparison to this JSON file")
    args = parser.parse_args()
    result = compare(args.artifact_dir)
    if args.record:
        result = {"checked_at": datetime.now(timezone.utc).date().isoformat(),
                  "commands": ["python warehouse/jpj/pipeline.py download",
                               "python warehouse/jpj/pipeline.py build --exclude-after-asof",
                               "python warehouse/jpj/pipeline.py check",
                               "python warehouse/jpj/compare_snapshot.py --record <this file>"],
                  **result}
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.record:
        args.record.write_bytes(text.encode("utf-8"))
    print(text, end="")
    if not result["identical"]:
        print("MISMATCH: fresh aggregates differ from the committed snapshot", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
