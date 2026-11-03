# -*- coding: utf-8 -*-
"""Compare the demo's 2025 brand anchors with the repo's own JPJ registrations.

The legacy demo seeds its 2025 brand totals from `malaysia_ask/db.py:BRAND_YEAR`
and calls them TIV-style (wholesale). The warehouse in the same repo holds the
official JPJ registration counts for 2025 (committed Hive aggregates). This
script puts the two side by side so the README can state what they show
instead of asserting that the synthetic data "matches the real market".

Standard library only. Reads committed files, writes eval/anchor_vs_jpj.json.

    python scripts/anchor_vs_jpj.py           # regenerate
    python scripts/anchor_vs_jpj.py --check   # fail if the committed JSON is stale
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from malaysia_ask.db import BRAND_YEAR  # noqa: E402

AGGREGATES = ROOT / "warehouse" / "evidence" / "20260917_152407_7272aa" / "hive_aggregates.tsv"
OUT = ROOT / "eval" / "anchor_vs_jpj.json"
YEAR = 2025
JPJ_MAKER = {"Perodua": "PERODUA", "Proton": "PROTON", "Honda": "HONDA", "Toyota": "TOYOTA",
             "Mazda": "MAZDA", "BYD": "BYD", "Chery": "CHERY"}


def jpj_by_maker(year: int) -> tuple[Counter, int]:
    counts, total = Counter(), 0
    with AGGREGATES.open(encoding="utf-8", newline="") as stream:
        for kind, key1, key2, value in csv.reader(stream, delimiter="\t"):
            if kind == "month_maker" and key1.startswith(f"{year}-"):
                counts[key2.strip().upper()] += int(value)
                total += int(value)
    return counts, total


def build() -> dict:
    anchors = BRAND_YEAR[YEAR]
    jpj, jpj_total = jpj_by_maker(YEAR)
    brands = []
    for brand, maker in JPJ_MAKER.items():
        anchor, registrations = anchors[brand], jpj[maker]
        brands.append({"brand": brand, "jpj_maker_label": maker, "demo_anchor": anchor,
                       "jpj_registrations": registrations, "difference": anchor - registrations,
                       "difference_pct": round(100 * (anchor - registrations) / registrations, 2),
                       "exact_match": anchor == registrations})
    anchor_order = [b["brand"] for b in sorted(brands, key=lambda b: -b["demo_anchor"])]
    jpj_order = [b["brand"] for b in sorted(brands, key=lambda b: -b["jpj_registrations"])]
    by_brand = {b["brand"]: b for b in brands}
    return {
        "year": YEAR,
        "sources": {"demo_anchor": "malaysia_ask/db.py BRAND_YEAR[2025]",
                    "jpj_registrations": str(AGGREGATES.relative_to(ROOT).as_posix()) + " (month_maker rows, maker label upper-cased)"},
        "demo_total": sum(anchors.values()),
        "jpj_total": jpj_total,
        "brands": brands,
        "exact_matches": [b["brand"] for b in brands if b["exact_match"]],
        "demo_anchor_order": anchor_order,
        "jpj_order": jpj_order,
        "honda_above_toyota": {"demo_anchor": by_brand["Honda"]["demo_anchor"] > by_brand["Toyota"]["demo_anchor"],
                               "jpj": by_brand["Honda"]["jpj_registrations"] > by_brand["Toyota"]["jpj_registrations"]},
        "caveats": [
            "JPJ counts registrations, not wholesale TIV; the demo calls its anchors TIV-style.",
            "JPJ counts every vehicle type in the dataset (car, MPV, jeep, pick-up, window van); the committed aggregates have no vehicle-type split, so Toyota includes Hilux-type pick-ups.",
            "Brand labels are matched by upper-cased maker name only; no group consolidation.",
        ],
    }


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    payload = build()
    if "--check" in sys.argv[1:]:
        committed = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if committed != dumps(payload):
            print(f"stale: {OUT.relative_to(ROOT).as_posix()} differs from a fresh run; "
                  "run python scripts/anchor_vs_jpj.py", file=sys.stderr)
            return 1
        print(f"ok: {OUT.relative_to(ROOT).as_posix()} matches a fresh run")
        return 0
    OUT.write_bytes(dumps(payload).encode("utf-8"))
    print(dumps(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
