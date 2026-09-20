#!/usr/bin/env bash
set -euo pipefail
CONTAINER=malaysia-warehouse-cluster
OWNER="$(docker inspect --format '{{index .Config.Labels "project"}}' "$CONTAINER")"
[ "$OWNER" = malaysia-auto-ask-hadoop-lab ] || { echo 'Refuse to stop a non-project container' >&2; exit 2; }
docker stop --time 30 "$CONTAINER"
echo 'Project stopped. HDFS and metastore remain in malaysia-warehouse-state; no other container changed.'
