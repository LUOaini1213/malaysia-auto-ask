CREATE DATABASE IF NOT EXISTS jpj_serving CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
USE jpj_serving;

CREATE TABLE IF NOT EXISTS dataset_versions (
  version VARCHAR(96) PRIMARY KEY,
  imported_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  source_json JSON NOT NULL,
  aggregate_rows INT UNSIGNED NOT NULL,
  represented_registration_rows BIGINT UNSIGNED NOT NULL,
  CHECK (aggregate_rows > 0)
) ENGINE=InnoDB;

-- Seven marginal aggregate families, not 1.44M registration-level rows.
-- Binary collation preserves original BMW/Bmw labels during reconciliation.
CREATE TABLE IF NOT EXISTS aggregates (
  version VARCHAR(96) NOT NULL,
  dimension VARCHAR(24) NOT NULL,
  key1 VARCHAR(128) NOT NULL,
  key2 VARCHAR(128) NOT NULL,
  registrations BIGINT UNSIGNED NOT NULL,
  `year_month` CHAR(7) NULL,
  maker_norm VARCHAR(128) NULL,
  fuel VARCHAR(64) NULL,
  PRIMARY KEY (version, dimension, key1, key2),
  CONSTRAINT fk_aggregate_version FOREIGN KEY (version) REFERENCES dataset_versions(version),
  CONSTRAINT ck_registration_positive CHECK (registrations > 0),
  INDEX ix_month (version, dimension, `year_month`),
  INDEX ix_maker_month (version, dimension, maker_norm, `year_month`),
  INDEX ix_fuel_month (version, dimension, fuel, `year_month`)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS active_dataset (
  singleton TINYINT NOT NULL PRIMARY KEY,
  version VARCHAR(96) NOT NULL,
  FOREIGN KEY (version) REFERENCES dataset_versions(version),
  CHECK (singleton = 1)
) ENGINE=InnoDB;
