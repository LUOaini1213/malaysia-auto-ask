-- 马来西亚汽车市场问数演示库
-- 品牌全年合计锚定公开 MAA/报道口径；月×区×车型是按种子拆出来的演示数，不是协会原始明细。

CREATE TABLE dim_brand (
  brand_id     INTEGER PRIMARY KEY,
  brand_name   TEXT NOT NULL UNIQUE,
  origin       TEXT NOT NULL CHECK (origin IN ('national', 'non_national')),
  notes        TEXT
);

CREATE TABLE dim_model (
  model_id     INTEGER PRIMARY KEY,
  brand_id     INTEGER NOT NULL REFERENCES dim_brand(brand_id),
  model_name   TEXT NOT NULL,
  body         TEXT NOT NULL,
  energy       TEXT NOT NULL CHECK (energy IN ('ice', 'hybrid', 'ev')),
  price_band   TEXT NOT NULL,
  UNIQUE (brand_id, model_name)
);

CREATE TABLE dim_region (
  region_id    INTEGER PRIMARY KEY,
  region_name  TEXT NOT NULL UNIQUE,
  region_name_zh TEXT NOT NULL
);

CREATE TABLE metric_dict (
  metric_key   TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  definition   TEXT NOT NULL,
  grain        TEXT NOT NULL,
  owner        TEXT NOT NULL,
  version      TEXT NOT NULL
);

CREATE TABLE fact_month (
  year         INTEGER NOT NULL,
  month        INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
  model_id     INTEGER NOT NULL REFERENCES dim_model(model_id),
  region_id    INTEGER NOT NULL REFERENCES dim_region(region_id),
  tiv_units    INTEGER NOT NULL CHECK (tiv_units >= 0),
  registration_units INTEGER NOT NULL CHECK (registration_units >= 0),
  PRIMARY KEY (year, month, model_id, region_id)
);

CREATE INDEX idx_fact_brand_time ON fact_month(year, month, model_id);
CREATE INDEX idx_fact_region ON fact_month(region_id, year);
