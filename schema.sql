-- 马来西亚汽车市场问数演示库
-- 品牌全年合计锚定公开 MAA/报道口径；月×区×车型是按种子拆出来的演示数，不是协会原始明细。
-- 分层只是演示：ODS 年锚 → DWD 明细 → ADS 汇总。不是企业数仓平台。

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

-- ODS：公开品牌年 TIV 锚。Chery / Others 是演示残差，不是协会官方行。
CREATE TABLE ods_brand_year_anchor (
  year         INTEGER NOT NULL,
  brand_name   TEXT NOT NULL,
  tiv_units    INTEGER NOT NULL CHECK (tiv_units >= 0),
  source_note  TEXT NOT NULL,
  PRIMARY KEY (year, brand_name)
);

-- DWD：年-月-车型-区域。TIV 与上牌分列。
CREATE TABLE fact_month (
  year         INTEGER NOT NULL,
  month        INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
  model_id     INTEGER NOT NULL REFERENCES dim_model(model_id),
  region_id    INTEGER NOT NULL REFERENCES dim_region(region_id),
  tiv_units    INTEGER NOT NULL CHECK (tiv_units >= 0),
  registration_units INTEGER NOT NULL CHECK (registration_units >= 0),
  PRIMARY KEY (year, month, model_id, region_id)
);

-- ADS：品牌年 / 品牌月汇总。全年无区域、无能源筛选时可走这里，不扫明细。
CREATE TABLE ads_brand_year (
  year         INTEGER NOT NULL,
  brand_id     INTEGER NOT NULL REFERENCES dim_brand(brand_id),
  tiv_units    INTEGER NOT NULL,
  registration_units INTEGER NOT NULL,
  PRIMARY KEY (year, brand_id)
);

CREATE TABLE ads_brand_month (
  year         INTEGER NOT NULL,
  month        INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
  brand_id     INTEGER NOT NULL REFERENCES dim_brand(brand_id),
  tiv_units    INTEGER NOT NULL,
  registration_units INTEGER NOT NULL,
  PRIMARY KEY (year, month, brand_id)
);

CREATE TABLE lineage_node (
  object_name  TEXT PRIMARY KEY,
  layer        TEXT NOT NULL CHECK (layer IN ('ods', 'dim', 'dwd', 'ads', 'metric', 'doc')),
  object_kind  TEXT NOT NULL,
  table_name   TEXT,
  grain        TEXT,
  owner        TEXT,
  version      TEXT,
  note         TEXT
);

CREATE TABLE lineage_edge (
  edge_id      INTEGER PRIMARY KEY,
  src          TEXT NOT NULL REFERENCES lineage_node(object_name),
  dst          TEXT NOT NULL REFERENCES lineage_node(object_name),
  transform    TEXT NOT NULL,
  grain        TEXT
);

CREATE INDEX idx_fact_brand_time ON fact_month(year, month, model_id);
CREATE INDEX idx_fact_region ON fact_month(region_id, year);
CREATE INDEX idx_ads_year ON ads_brand_year(year);
CREATE INDEX idx_lineage_dst ON lineage_edge(dst);
