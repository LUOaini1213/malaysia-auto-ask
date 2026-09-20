-- Rendered by run_hive.py. A fresh database and HDFS prefix isolate each run.
-- JPJ car REGISTRATIONS, not sales. The state column is the registration
-- office/partner portal; Rakan Niaga must remain a separate portal category.
CREATE DATABASE IF NOT EXISTS __DATABASE__;
USE __DATABASE__;
SET hive.exec.dynamic.partition=true;
SET hive.exec.dynamic.partition.mode=nonstrict;
SET hive.exec.max.dynamic.partitions=1000;
SET hive.exec.max.dynamic.partitions.pernode=1000;
SET hive.stats.autogather=false;
SET hive.compute.query.using.stats=false;
-- Hive 4.0.1 complex INSERT OVERWRITE DIRECTORY can target the result cache
-- instead of its requested path (HIVE-28620). Validate physical fresh outputs.
SET hive.query.results.cache.enabled=false;

CREATE EXTERNAL TABLE ods_car_registration (
  source_sha256 STRING,
  source_row BIGINT,
  date_reg STRING,
  vehicle_type STRING,
  maker STRING,
  model STRING,
  colour STRING,
  fuel STRING,
  state STRING
)
PARTITIONED BY (registration_year INT, registration_month INT)
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
STORED AS TEXTFILE
LOCATION '__HDFS_INPUT__'
TBLPROPERTIES ('serialization.null.format'='\\N');
MSCK REPAIR TABLE ods_car_registration;

CREATE EXTERNAL TABLE dwd_car_registration (
  source_sha256 STRING,
  source_row BIGINT,
  date_reg DATE,
  vehicle_type STRING,
  maker STRING,
  model STRING,
  colour STRING,
  fuel STRING,
  state STRING
)
PARTITIONED BY (registration_year INT, registration_month INT)
STORED AS ORC
LOCATION '__HDFS_DWD__'
TBLPROPERTIES ('orc.compress'='SNAPPY', 'transactional'='false');

-- Preserve every legitimate transaction, including identical attribute rows.
INSERT OVERWRITE TABLE dwd_car_registration
PARTITION (registration_year, registration_month)
SELECT source_sha256, source_row, CAST(date_reg AS DATE), vehicle_type,
       maker, model, colour, fuel, state, registration_year, registration_month
FROM ods_car_registration;

CREATE EXTERNAL TABLE ads_monthly_registration (
  maker STRING, fuel STRING, state STRING, registrations BIGINT
)
PARTITIONED BY (registration_year INT, registration_month INT)
STORED AS ORC
LOCATION '__HDFS_ADS__'
TBLPROPERTIES ('orc.compress'='SNAPPY', 'transactional'='false');

INSERT OVERWRITE TABLE ads_monthly_registration
PARTITION (registration_year, registration_month)
SELECT maker, fuel, state, COUNT(*), registration_year, registration_month
FROM dwd_car_registration
GROUP BY registration_year, registration_month, maker, fuel, state;

-- Independent Python oracle is derived from the downloaded source, not ADS.
INSERT OVERWRITE DIRECTORY '__HDFS_RESULTS__/aggregates'
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
STORED AS TEXTFILE
SELECT 'total', 'ALL', 'ALL', SUM(registrations) FROM ads_monthly_registration
UNION ALL
SELECT 'month', CAST(registration_year AS STRING),
       LPAD(CAST(registration_month AS STRING), 2, '0'), SUM(registrations)
FROM ads_monthly_registration GROUP BY registration_year, registration_month
UNION ALL
SELECT 'maker', COALESCE(maker, '__NULL__'), 'ALL', SUM(registrations)
FROM ads_monthly_registration GROUP BY maker
UNION ALL
SELECT 'fuel', COALESCE(fuel, '__NULL__'), 'ALL', SUM(registrations)
FROM ads_monthly_registration GROUP BY fuel
UNION ALL
SELECT 'state', COALESCE(state, '__NULL__'), 'ALL', SUM(registrations)
FROM ads_monthly_registration GROUP BY state
UNION ALL
SELECT 'month_maker', CONCAT(CAST(registration_year AS STRING), '-',
       LPAD(CAST(registration_month AS STRING), 2, '0')),
       COALESCE(maker, '__NULL__'), SUM(registrations)
FROM ads_monthly_registration GROUP BY registration_year, registration_month, maker
UNION ALL
SELECT 'month_fuel', CONCAT(CAST(registration_year AS STRING), '-',
       LPAD(CAST(registration_month AS STRING), 2, '0')),
       COALESCE(fuel, '__NULL__'), SUM(registrations)
FROM ads_monthly_registration GROUP BY registration_year, registration_month, fuel;

INSERT OVERWRITE DIRECTORY '__HDFS_RESULTS__/checks'
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
STORED AS TEXTFILE
SELECT 'ods_count', COUNT(*) FROM ods_car_registration
UNION ALL
SELECT 'dwd_count', COUNT(*) FROM dwd_car_registration
UNION ALL
SELECT 'distinct_lineage_count', COUNT(DISTINCT CONCAT(source_sha256, ':', CAST(source_row AS STRING)))
FROM dwd_car_registration
UNION ALL
SELECT 'invalid_partition_count', COUNT(*) FROM dwd_car_registration
WHERE date_reg IS NULL OR YEAR(date_reg) <> registration_year
   OR MONTH(date_reg) <> registration_month
   OR registration_year IS NULL OR registration_month IS NULL
UNION ALL
SELECT 'invalid_lineage_count', COUNT(*) FROM dwd_car_registration
WHERE source_sha256 IS NULL OR source_sha256 NOT RLIKE '^[0-9a-f]{64}$'
   OR source_row IS NULL OR source_row < 1;
