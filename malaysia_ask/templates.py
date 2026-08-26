# -*- coding: utf-8 -*-
"""Whitelist SQL only. Parameters are bound, never concatenated from the question."""
from __future__ import annotations

TEMPLATES = {
    "brand_rank": """
SELECT b.brand_name AS name,
       SUM(f.{col}) AS units
FROM fact_month f
JOIN dim_model m ON m.model_id = f.model_id
JOIN dim_brand b ON b.brand_id = m.brand_id
WHERE f.year = :year
  AND (:month IS NULL OR f.month = :month)
  AND (:region_id IS NULL OR f.region_id = :region_id)
  AND (:energy IS NULL OR m.energy = :energy)
  AND (:origin IS NULL OR b.origin = :origin)
GROUP BY b.brand_name
ORDER BY units DESC
""",
    "model_rank": """
SELECT b.brand_name || ' ' || m.model_name AS name,
       SUM(f.{col}) AS units
FROM fact_month f
JOIN dim_model m ON m.model_id = f.model_id
JOIN dim_brand b ON b.brand_id = m.brand_id
WHERE f.year = :year
  AND (:month IS NULL OR f.month = :month)
  AND (:region_id IS NULL OR f.region_id = :region_id)
  AND (:brand_id IS NULL OR b.brand_id = :brand_id)
  AND (:energy IS NULL OR m.energy = :energy)
GROUP BY b.brand_name, m.model_name
ORDER BY units DESC
LIMIT 15
""",
    "brand_total": """
SELECT b.brand_name AS name,
       SUM(f.{col}) AS units
FROM fact_month f
JOIN dim_model m ON m.model_id = f.model_id
JOIN dim_brand b ON b.brand_id = m.brand_id
WHERE f.year = :year
  AND (:month IS NULL OR f.month = :month)
  AND (:region_id IS NULL OR f.region_id = :region_id)
  AND b.brand_id = :brand_id
GROUP BY b.brand_name
""",
    "region_rank": """
SELECT r.region_name AS name,
       r.region_name_zh AS name_zh,
       SUM(f.{col}) AS units
FROM fact_month f
JOIN dim_region r ON r.region_id = f.region_id
JOIN dim_model m ON m.model_id = f.model_id
JOIN dim_brand b ON b.brand_id = m.brand_id
WHERE f.year = :year
  AND (:month IS NULL OR f.month = :month)
  AND (:brand_id IS NULL OR b.brand_id = :brand_id)
GROUP BY r.region_id
ORDER BY units DESC
""",
    "month_trend": """
SELECT f.month,
       SUM(f.{col}) AS units
FROM fact_month f
JOIN dim_model m ON m.model_id = f.model_id
JOIN dim_brand b ON b.brand_id = m.brand_id
WHERE f.year = :year
  AND (:brand_id IS NULL OR b.brand_id = :brand_id)
  AND (:region_id IS NULL OR f.region_id = :region_id)
GROUP BY f.month
ORDER BY f.month
""",
    "share": """
SELECT b.brand_name AS name,
       SUM(f.{col}) AS units,
       ROUND(100.0 * SUM(f.{col}) / (
         SELECT SUM(f2.{col}) FROM fact_month f2
         JOIN dim_model m2 ON m2.model_id = f2.model_id
         JOIN dim_brand b2 ON b2.brand_id = m2.brand_id
         WHERE f2.year = :year
           AND (:month IS NULL OR f2.month = :month)
           AND (:region_id IS NULL OR f2.region_id = :region_id)
       ), 1) AS share_pct
FROM fact_month f
JOIN dim_model m ON m.model_id = f.model_id
JOIN dim_brand b ON b.brand_id = m.brand_id
WHERE f.year = :year
  AND (:month IS NULL OR f.month = :month)
  AND (:region_id IS NULL OR f.region_id = :region_id)
  AND (:brand_id IS NULL OR b.brand_id = :brand_id)
GROUP BY b.brand_name
ORDER BY units DESC
""",
    "yoy_brand": """
SELECT b.brand_name AS name,
       SUM(CASE WHEN f.year = :year THEN f.{col} ELSE 0 END) AS units,
       SUM(CASE WHEN f.year = :year_ly THEN f.{col} ELSE 0 END) AS units_ly,
       CASE WHEN SUM(CASE WHEN f.year = :year_ly THEN f.{col} ELSE 0 END) = 0 THEN NULL
            ELSE ROUND(100.0 * (
              SUM(CASE WHEN f.year = :year THEN f.{col} ELSE 0 END)
              - SUM(CASE WHEN f.year = :year_ly THEN f.{col} ELSE 0 END)
            ) / SUM(CASE WHEN f.year = :year_ly THEN f.{col} ELSE 0 END), 1)
       END AS yoy_pct
FROM fact_month f
JOIN dim_model m ON m.model_id = f.model_id
JOIN dim_brand b ON b.brand_id = m.brand_id
WHERE f.year IN (:year, :year_ly)
  AND (:month IS NULL OR f.month = :month)
  AND (:region_id IS NULL OR f.region_id = :region_id)
  AND (:brand_id IS NULL OR b.brand_id = :brand_id)
GROUP BY b.brand_name
ORDER BY units DESC
""",
    "origin_split": """
SELECT b.origin AS name,
       SUM(f.{col}) AS units
FROM fact_month f
JOIN dim_model m ON m.model_id = f.model_id
JOIN dim_brand b ON b.brand_id = m.brand_id
WHERE f.year = :year
  AND (:month IS NULL OR f.month = :month)
GROUP BY b.origin
ORDER BY units DESC
""",
}


ADS_TEMPLATES = {
    "brand_rank": """
SELECT b.brand_name AS name,
       SUM(a.{col}) AS units
FROM ads_brand_year a
JOIN dim_brand b ON b.brand_id = a.brand_id
WHERE a.year = :year
  AND (:origin IS NULL OR b.origin = :origin)
GROUP BY b.brand_name
ORDER BY units DESC
""",
    "brand_total": """
SELECT b.brand_name AS name,
       SUM(a.{col}) AS units
FROM ads_brand_year a
JOIN dim_brand b ON b.brand_id = a.brand_id
WHERE a.year = :year
  AND b.brand_id = :brand_id
GROUP BY b.brand_name
""",
    "share": """
SELECT b.brand_name AS name,
       SUM(a.{col}) AS units,
       ROUND(100.0 * SUM(a.{col}) / (
         SELECT SUM(a2.{col}) FROM ads_brand_year a2 WHERE a2.year = :year
       ), 1) AS share_pct
FROM ads_brand_year a
JOIN dim_brand b ON b.brand_id = a.brand_id
WHERE a.year = :year
  AND (:brand_id IS NULL OR b.brand_id = :brand_id)
GROUP BY b.brand_name
ORDER BY units DESC
""",
    "yoy_brand": """
SELECT b.brand_name AS name,
       SUM(CASE WHEN a.year = :year THEN a.{col} ELSE 0 END) AS units,
       SUM(CASE WHEN a.year = :year_ly THEN a.{col} ELSE 0 END) AS units_ly,
       CASE WHEN SUM(CASE WHEN a.year = :year_ly THEN a.{col} ELSE 0 END) = 0 THEN NULL
            ELSE ROUND(100.0 * (
              SUM(CASE WHEN a.year = :year THEN a.{col} ELSE 0 END)
              - SUM(CASE WHEN a.year = :year_ly THEN a.{col} ELSE 0 END)
            ) / SUM(CASE WHEN a.year = :year_ly THEN a.{col} ELSE 0 END), 1)
       END AS yoy_pct
FROM ads_brand_year a
JOIN dim_brand b ON b.brand_id = a.brand_id
WHERE a.year IN (:year, :year_ly)
  AND (:brand_id IS NULL OR b.brand_id = :brand_id)
GROUP BY b.brand_name
ORDER BY units DESC
""",
    "origin_split": """
SELECT b.origin AS name,
       SUM(a.{col}) AS units
FROM ads_brand_year a
JOIN dim_brand b ON b.brand_id = a.brand_id
WHERE a.year = :year
GROUP BY b.origin
ORDER BY units DESC
""",
}


def scan_for(task: str, params: dict | None = None) -> str:
    """Full-year brand totals can use ADS. Region / month / energy still scan DWD."""
    p = params or {}
    if task in ("model_rank", "region_rank", "month_trend"):
        return "dwd.fact_month"
    detail = p.get("month") is not None or p.get("region_id") is not None or p.get("energy") is not None
    if detail:
        return "dwd.fact_month"
    if task in ADS_TEMPLATES:
        return "ads.brand_year"
    return "dwd.fact_month"


def render(template_id: str, metric: str, scan: str = "dwd.fact_month") -> str:
    if metric not in ("tiv", "registration"):
        raise ValueError(metric)
    col = "tiv_units" if metric == "tiv" else "registration_units"
    if scan == "ads.brand_year":
        if template_id not in ADS_TEMPLATES:
            raise KeyError(template_id)
        return ADS_TEMPLATES[template_id].format(col=col)
    if template_id not in TEMPLATES:
        raise KeyError(template_id)
    return TEMPLATES[template_id].format(col=col)
