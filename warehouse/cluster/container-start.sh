#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" = 0 ]; then
  mkdir -p /runtime/{hdfs/name,hdfs/data,hadoop/tmp,pids,logs,yarn/local,yarn/logs,hive/scratch,hive/querylog}
  chown -R hive:hive /runtime
  exec su -s /bin/bash hive -c 'exec bash /cluster/container-start.sh'
fi
export HADOOP_CONF_DIR=/cluster/conf
export HIVE_CONF_DIR=/cluster/conf
export TEZ_CONF_DIR=/cluster/conf
export HADOOP_COMMON_HOME=/opt/hadoop HADOOP_HDFS_HOME=/opt/hadoop HADOOP_YARN_HOME=/opt/hadoop HADOOP_MAPRED_HOME=/opt/hadoop
export HADOOP_LOG_DIR=/runtime/logs HADOOP_PID_DIR=/runtime/pids YARN_LOG_DIR=/runtime/logs YARN_PID_DIR=/runtime/pids
export HADOOP_HEAPSIZE_MAX=256 HADOOP_CLIENT_OPTS='-Xmx512m'
export HADOOP_CLASSPATH='/opt/tez/*:/opt/tez/lib/*:/cluster/conf'
export HADOOP_OPTS='-Djava.net.preferIPv4Stack=true'
if [ ! -f /runtime/hdfs/name/current/VERSION ]; then
  hdfs namenode -format -nonInteractive > /runtime/logs/namenode-format.log 2>&1
fi
hdfs --daemon start namenode
hdfs --daemon start datanode
yarn --daemon start resourcemanager
yarn --daemon start nodemanager
for attempt in $(seq 1 60); do
  if hdfs dfs -mkdir -p /user/hive /tmp/hive /warehouse/managed /warehouse/external /warehouse/logs/yarn /apps/tez >/dev/null 2>&1; then break; fi
  sleep 2
done
hdfs dfs -chmod 1777 /tmp /tmp/hive
if ! hdfs dfs -test -e /apps/tez/tez.tar.gz; then
  tar -czf /runtime/tez.tar.gz -C /opt/tez .
  hdfs dfs -put /runtime/tez.tar.gz /apps/tez/tez.tar.gz
fi
cd /runtime/hive
if [ ! -f /runtime/hive/schema-ready ]; then
  if schematool -dbType derby -info > /runtime/logs/metastore-info.log 2>&1; then
    touch /runtime/hive/schema-ready
  else
    if [ -d /runtime/hive/metastore_db ]; then
      mv /runtime/hive/metastore_db "/runtime/hive/metastore_incomplete_$(date +%s)"
    fi
    schematool -dbType derby -initSchema --verbose > /runtime/logs/metastore-init.log 2>&1
    touch /runtime/hive/schema-ready
  fi
fi
export HADOOP_HEAPSIZE=1024
export HADOOP_CLIENT_OPTS='-Xmx1024m -Dhive.log.dir=/runtime/logs -Dhive.log.file=hive-service.log'
export HIVESERVER2_PID_DIR=/runtime/pids
exec hiveserver2 > /runtime/logs/hiveserver2.log 2>&1
