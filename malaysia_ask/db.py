# -*- coding: utf-8 -*-
"""SQLite seed. Brand-year totals follow public 2024/2025 TIV-style numbers.
Month × region × model splits are synthetic (seed=42).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "malaysia_auto.db"
SCHEMA = ROOT / "schema.sql"

BRANDS = [
    (1, "Perodua", "national", "National marque. 2025 public TIV-style ~359,904."),
    (2, "Proton", "national", "National marque, Geely-backed. 2025 public ~151,564."),
    (3, "Honda", "non_national", "2025 public passenger-style ~72,301."),
    (4, "Toyota", "non_national", "2025 public passenger-style ~70,352 (not full-group TIV)."),
    (5, "Mazda", "non_national", "2025 public ~9,277."),
    (6, "BYD", "non_national", "Anchored to 2025 registration-style ~14,407; TIV vs JPJ may differ."),
    (7, "Chery", "non_national", "Synthetic residual of non-national growth; not an official MAA line."),
    (8, "Others", "non_national", "All remaining TIV (other brands + commercial remainder)."),
]

MODELS = [
    (1, 1, "Bezza", "sedan", "ice", "A"),
    (2, 1, "Myvi", "hatch", "ice", "B"),
    (3, 1, "Axia", "hatch", "ice", "A"),
    (4, 1, "Ativa", "suv", "ice", "B"),
    (5, 1, "Alza", "mpv", "ice", "B"),
    (6, 2, "Saga", "sedan", "ice", "A"),
    (7, 2, "X50", "suv", "ice", "B"),
    (8, 2, "X70", "suv", "ice", "C"),
    (9, 2, "S70", "sedan", "ice", "B"),
    (10, 2, "e.MAS 5", "suv", "ev", "B"),
    (11, 3, "City", "sedan", "ice", "B"),
    (12, 3, "Civic", "sedan", "ice", "C"),
    (13, 3, "HR-V", "suv", "ice", "C"),
    (14, 3, "WR-V", "suv", "ice", "B"),
    (15, 4, "Vios", "sedan", "ice", "B"),
    (16, 4, "Yaris", "hatch", "ice", "B"),
    (17, 4, "Corolla Cross", "suv", "hybrid", "C"),
    (18, 4, "Hilux", "pickup", "ice", "C"),
    (19, 5, "CX-5", "suv", "ice", "C"),
    (20, 5, "Mazda3", "sedan", "ice", "C"),
    (21, 6, "Atto 3", "suv", "ev", "C"),
    (22, 6, "Seal", "sedan", "ev", "C"),
    (23, 7, "Tiggo 8", "suv", "ice", "C"),
    (24, 7, "Omoda 5", "suv", "ice", "B"),
    (25, 8, "Other models", "mix", "ice", "mix"),
]

REGIONS = [
    (1, "Klang Valley", "巴生谷"),
    (2, "Johor", "柔佛"),
    (3, "Penang", "槟城"),
    (4, "Perak", "霹雳"),
    (5, "Sabah", "沙巴"),
    (6, "Sarawak", "砂拉越"),
    (7, "Others", "其他州属"),
]

METRICS = [
    (
        "tiv",
        "TIV / 批发销量",
        "协会口径批发（TIV-style）。问「销量/卖得好」且未指定上牌时，产品应停下来问人，不默认。",
        "year, month, brand/model/region",
        "demo.metrics",
        "2026.08.1",
    ),
    (
        "registration",
        "上牌 / 注册量",
        "JPJ 上牌风格演示列。与 TIV 不是同一口径：同月同车型允许不一致。",
        "year, month, brand/model/region",
        "demo.metrics",
        "2026.08.1",
    ),
    (
        "share",
        "份额",
        "分子分母必须同一指标、同一时间、同一筛选。默认份额用 TIV。",
        "same as numerator",
        "demo.metrics",
        "2026.08.1",
    ),
    (
        "yoy",
        "同比",
        "(本期 − 去年同期) / 去年同期。去年同期为 0 则不出同比。",
        "year-month vs year-12",
        "demo.metrics",
        "2026.08.1",
    ),
    (
        "national",
        "国产车",
        "仅 Perodua + Proton。不是「全部马来西亚生产」。",
        "brand.origin = national",
        "demo.metrics",
        "2026.08.1",
    ),
]

# Public year anchors (units). 2025 TIV 820,752; 2024 TIV 816,747.
BRAND_YEAR = {
    2024: {
        "Perodua": 358102,
        "Proton": 147587,
        "Honda": 81699,
        "Toyota": 71514,
        "Mazda": 14464,
        "BYD": 8000,
        "Chery": 9000,
        "Others": 816747 - (358102 + 147587 + 81699 + 71514 + 14464 + 8000 + 9000),
    },
    2025: {
        "Perodua": 359904,
        "Proton": 151564,
        "Honda": 72301,
        "Toyota": 70352,
        "Mazda": 9277,
        "BYD": 14407,
        "Chery": 15300,
        "Others": 820752 - (359904 + 151564 + 72301 + 70352 + 9277 + 14407 + 15300),
    },
}

MODEL_SHARE = {
    "Perodua": [("Bezza", 0.28), ("Myvi", 0.26), ("Axia", 0.18), ("Ativa", 0.16), ("Alza", 0.12)],
    "Proton": [("Saga", 0.30), ("X50", 0.24), ("X70", 0.18), ("S70", 0.16), ("e.MAS 5", 0.12)],
    "Honda": [("City", 0.34), ("HR-V", 0.28), ("Civic", 0.22), ("WR-V", 0.16)],
    "Toyota": [("Vios", 0.32), ("Hilux", 0.26), ("Corolla Cross", 0.24), ("Yaris", 0.18)],
    "Mazda": [("CX-5", 0.62), ("Mazda3", 0.38)],
    "BYD": [("Atto 3", 0.70), ("Seal", 0.30)],
    "Chery": [("Tiggo 8", 0.55), ("Omoda 5", 0.45)],
    "Others": [("Other models", 1.0)],
}

REGION_SHARE = [
    ("Klang Valley", 0.38),
    ("Johor", 0.14),
    ("Penang", 0.08),
    ("Perak", 0.07),
    ("Sabah", 0.06),
    ("Sarawak", 0.06),
    ("Others", 0.21),
]

# Dec 2025 was a record month (~11% of year). Other months flatter.
MONTH_W = {
    2024: [0.078, 0.075, 0.080, 0.079, 0.082, 0.081, 0.083, 0.082, 0.084, 0.085, 0.086, 0.105],
    2025: [0.076, 0.074, 0.079, 0.078, 0.081, 0.080, 0.082, 0.081, 0.083, 0.086, 0.089, 0.111],
}


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _split(total: int, weights: list[float]) -> list[int]:
    raw = [total * w for w in weights]
    ints = [int(x) for x in raw]
    gap = total - sum(ints)
    order = sorted(range(len(raw)), key=lambda i: (raw[i] - ints[i]), reverse=True)
    i = 0
    while gap > 0:
        ints[order[i % len(ints)]] += 1
        gap -= 1
        i += 1
    while gap < 0:
        ints[order[-(i % len(ints)) - 1]] -= 1
        gap += 1
        i += 1
    return ints


def seed(path: Path | None = None) -> Path:
    p = path or DB_PATH
    if p.exists():
        p.unlink()
    conn = connect(p)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT INTO dim_brand(brand_id, brand_name, origin, notes) VALUES (?,?,?,?)",
        BRANDS,
    )
    conn.executemany(
        "INSERT INTO dim_model(model_id, brand_id, model_name, body, energy, price_band) VALUES (?,?,?,?,?,?)",
        MODELS,
    )
    conn.executemany(
        "INSERT INTO dim_region(region_id, region_name, region_name_zh) VALUES (?,?,?)",
        REGIONS,
    )
    conn.executemany(
        "INSERT INTO metric_dict(metric_key, display_name, definition, grain, owner, version) VALUES (?,?,?,?,?,?)",
        METRICS,
    )

    brand_name = {b[0]: b[1] for b in BRANDS}
    model_by_brand: dict[str, list[tuple[int, str]]] = {}
    for mid, bid, name, *_ in MODELS:
        model_by_brand.setdefault(brand_name[bid], []).append((mid, name))
    region_ids = [(r[0], r[1]) for r in REGIONS]
    r_w = [w for _, w in REGION_SHARE]

    # ---- TIV：按公开报道锚定的年合计往下拆，数值不动 ----
    tiv_series: dict[tuple[int, int, int], list[int]] = {}  # (year, model_id, region_id) -> 12 个月
    for year, brand_tot in BRAND_YEAR.items():
        m_w = MONTH_W[year]
        for bid, bname, *_ in BRANDS:
            month_units = _split(brand_tot[bname], m_w)
            shares = MODEL_SHARE[bname]
            mw = [w for _, w in shares]
            id_by_name = {n: i for i, n in model_by_brand[bname]}
            for month, mu in enumerate(month_units, start=1):
                per_model = _split(mu, mw)
                for (mname, _), units in zip(shares, per_model):
                    mid = id_by_name[mname]
                    per_region = _split(units, r_w)
                    for (rid, _), ru in zip(region_ids, per_region):
                        tiv_series.setdefault((year, mid, rid), [0] * 12)[month - 1] = ru

    # ---- 上牌：批发 -> 上牌之间有渠道库存和上牌滞后 ----
    # reg[m] = lam[m]*tiv[m] + (1-lam[m-1])*tiv[m-1]
    #   lam_b  当月批发中当月就上牌的比例。国产双雄周转快，进口/新势力压渠道库存。
    #   季末（3/6/9/12）厂商压货冲量，当月上牌比例进一步下降。
    #   区域：上牌发生在终端所在州，巴生谷高于批发口径，东马低。
    # 各品牌渠道周转差异（越高＝当月批发当月就上牌，渠道压货越少）
    BRAND_LAMBDA = {
        "Perodua": 0.88,  # 国产龙头，产销紧咬
        "Proton": 0.86,   # 同上
        "Honda": 0.84,    # 零售强、经销商库存薄
        "Toyota": 0.74,   # 更依赖向经销商压批发
        "Mazda": 0.78,
        "BYD": 0.80,      # 新进场但终端走量快
        "Chery": 0.64,    # 铺渠道阶段，库存厚
        "Others": 0.75,
    }
    QUARTER_END_HOLD = 0.90  # 季末当月上牌比例再打九折，货压在渠道
    brand_of_model = {mid: brand_name[bid] for mid, bid, *_ in MODELS}

    def lam_of(bname: str, month: int) -> float:
        lam = BRAND_LAMBDA.get(bname, 0.78)
        if month in (3, 6, 9, 12):
            lam *= QUARTER_END_HOLD
        return lam

    rows = []
    for (year, mid, rid), series in sorted(tiv_series.items()):
        bname = brand_of_model[mid]
        prev_year = tiv_series.get((year - 1, mid, rid))
        region_bump = 1.05 if rid == 1 else 0.92 if rid in (5, 6) else 0.98
        for month in range(1, 13):
            tiv_m = series[month - 1]
            lam_m = lam_of(bname, month)
            if month == 1:
                # 1 月消化的是上一年 12 月压在渠道里的货；无上一年数据时按本年 12 月做稳态近似
                src = prev_year[11] if prev_year else series[11]
                carry = (1 - lam_of(bname, 12)) * src
            else:
                carry = (1 - lam_of(bname, month - 1)) * series[month - 2]
            reg = max(0, int(round((lam_m * tiv_m + carry) * region_bump)))
            rows.append((year, month, mid, rid, tiv_m, reg))

    conn.executemany(
        "INSERT INTO fact_month(year, month, model_id, region_id, tiv_units, registration_units) VALUES (?,?,?,?,?,?)",
        rows,
    )

    anchor_rows = []
    residual = {"Chery", "Others"}
    for year, brand_tot in BRAND_YEAR.items():
        for bname, units in brand_tot.items():
            if bname in residual:
                note = "synthetic residual / not an official MAA line"
            else:
                note = "public TIV-style year total (reported); not a JPJ extract"
            anchor_rows.append((year, bname, units, note))
    conn.executemany(
        "INSERT INTO ods_brand_year_anchor(year, brand_name, tiv_units, source_note) VALUES (?,?,?,?)",
        anchor_rows,
    )
    conn.execute(
        """
        INSERT INTO ads_brand_year(year, brand_id, tiv_units, registration_units)
        SELECT f.year, m.brand_id, SUM(f.tiv_units), SUM(f.registration_units)
        FROM fact_month f
        JOIN dim_model m ON m.model_id = f.model_id
        GROUP BY f.year, m.brand_id
        """
    )
    conn.execute(
        """
        INSERT INTO ads_brand_month(year, month, brand_id, tiv_units, registration_units)
        SELECT f.year, f.month, m.brand_id, SUM(f.tiv_units), SUM(f.registration_units)
        FROM fact_month f
        JOIN dim_model m ON m.model_id = f.model_id
        GROUP BY f.year, f.month, m.brand_id
        """
    )
    from .lineage import rows_for_seed

    node_rows, edge_rows = rows_for_seed()
    conn.executemany(
        "INSERT INTO lineage_node(object_name, layer, object_kind, table_name, grain, owner, version, note) "
        "VALUES (?,?,?,?,?,?,?,?)",
        node_rows,
    )
    conn.executemany(
        "INSERT INTO lineage_edge(edge_id, src, dst, transform, grain) VALUES (?,?,?,?,?)",
        edge_rows,
    )
    conn.commit()
    conn.close()
    return p


if __name__ == "__main__":
    print("seeded", seed())
