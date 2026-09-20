#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then echo 'Usage: exec-hive.sh /warehouse/sql/query.sql' >&2; exit 2; fi
case "$1" in /warehouse/*.sql|/cluster/*.sql) ;; *) echo 'SQL must be a mounted /warehouse or /cluster .sql file' >&2; exit 2;; esac
docker exec -u hive malaysia-warehouse-cluster beeline \
  -u jdbc:hive2://localhost:10000/default -n hive --force=false --showHeader=true --outputformat=tsv2 -f "$1"
