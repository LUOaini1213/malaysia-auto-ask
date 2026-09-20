#!/usr/bin/env bash
set -euo pipefail
CLUSTER_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACTS="$(cd -- "$CLUSTER_DIR/.." && pwd)/artifacts/cluster"
mkdir -p "$ARTIFACTS"
RUN_ID="acceptance_$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ARTIFACTS="$ARTIFACTS/$RUN_ID"
mkdir "$RUN_ARTIFACTS"
docker exec -u hive -e RUN_ID="$RUN_ID" malaysia-warehouse-cluster bash /cluster/check-in-container.sh 2>&1 | tee "$RUN_ARTIFACTS/acceptance.log" "$ARTIFACTS/acceptance.log"
for FILE in hdfs-roundtrip.txt wordcount-result.tsv hive-smoke-result.tsv mapreduce-smoke.log hive-smoke.log; do
  docker cp "malaysia-warehouse-cluster:/runtime/$FILE" "$RUN_ARTIFACTS/$FILE"
done
docker cp malaysia-warehouse-cluster:/runtime/logs/hiveserver2.log "$RUN_ARTIFACTS/hiveserver2.log"
docker exec -u hive malaysia-warehouse-cluster yarn application -list -appStates ALL > "$RUN_ARTIFACTS/yarn-applications.txt" 2>&1
python3 "$CLUSTER_DIR/verify-evidence.py" "$RUN_ARTIFACTS"
cp "$RUN_ARTIFACTS/acceptance.json" "$ARTIFACTS/acceptance.json"
echo "Verified evidence: $RUN_ARTIFACTS/acceptance.json"
