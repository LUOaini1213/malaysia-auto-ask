#!/usr/bin/env bash
set -euo pipefail
RUN_ID="${RUN_ID:-acceptance_$(date -u +%Y%m%dT%H%M%SZ)}"
[[ "$RUN_ID" =~ ^acceptance_[0-9]{8}T[0-9]{6}Z$ ]] || { echo 'Invalid acceptance run ID' >&2; exit 2; }
RUN_DIR="/warehouse/lab_acceptance/$RUN_ID"
echo "RUN_ID=$RUN_ID"
hadoop version | head -1
java -version
echo 'HDFS write/read round trip:'
HDFS_READY=0
for attempt in $(seq 1 60); do
  if hdfs dfs -test -d /user/hive 2>/dev/null; then HDFS_READY=1; break; fi
  sleep 2
done
[ "$HDFS_READY" = 1 ] || { echo 'HDFS did not become ready' >&2; exit 3; }
hdfs dfs -mkdir -p "$RUN_DIR/input" "$RUN_DIR/hive_input"
hdfs dfs -put /cluster/smoke/words.txt "$RUN_DIR/input/words.txt"
hdfs dfs -cat "$RUN_DIR/input/words.txt" > /runtime/hdfs-roundtrip.txt
cmp /cluster/smoke/words.txt /runtime/hdfs-roundtrip.txt
hdfs dfsadmin -report
echo 'YARN worker:'
yarn node -list -all
echo 'MapReduce wordcount on YARN:'
hadoop jar /opt/hadoop/share/hadoop/mapreduce/hadoop-mapreduce-examples-3.3.6.jar wordcount "$RUN_DIR/input" "$RUN_DIR/wordcount" 2>&1 | tee /runtime/mapreduce-smoke.log
hdfs dfs -cat "$RUN_DIR/wordcount/part-r-00000" > /runtime/wordcount-result.tsv
printf 'hdfs\t1\nhive\t2\nyarn\t3\n' > /runtime/wordcount-expected.tsv
cmp /runtime/wordcount-expected.tsv /runtime/wordcount-result.tsv
echo 'Waiting for HiveServer2:'
HIVE_READY=0
for attempt in $(seq 1 60); do
  if timeout 30 beeline -u jdbc:hive2://localhost:10000/default -n hive --silent=true -e 'show databases' > /runtime/hive-ready.txt 2>&1; then HIVE_READY=1; break; fi
  sleep 2
done
[ "$HIVE_READY" = 1 ] || { cat /runtime/hive-ready.txt; exit 3; }
hdfs dfs -put /cluster/smoke/values.tsv "$RUN_DIR/hive_input/values.tsv"
cat > /runtime/check-hive.sql <<SQL
set hive.execution.engine=tez;
set hive.exec.mode.local.auto=false;
set hive.fetch.task.conversion=none;
CREATE DATABASE $RUN_ID;
CREATE EXTERNAL TABLE $RUN_ID.values_src (category STRING, quantity INT)
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t' STORED AS TEXTFILE LOCATION '$RUN_DIR/hive_input';
SELECT category, SUM(quantity) AS total FROM $RUN_ID.values_src GROUP BY category ORDER BY category;
SQL
beeline -u jdbc:hive2://localhost:10000/default -n hive --force=false --showHeader=false --outputformat=tsv2 -f /runtime/check-hive.sql > /runtime/hive-smoke-result.tsv 2> /runtime/hive-smoke.log
cat /runtime/hive-smoke-result.tsv
grep -qx $'alpha\t15' /runtime/hive-smoke-result.tsv
grep -qx $'beta\t20' /runtime/hive-smoke-result.tsv
echo 'YARN applications after both jobs:'
yarn application -list -appStates ALL
echo 'ACCEPTANCE_PASS: HDFS roundtrip, YARN wordcount, Hive Tez aggregation'
