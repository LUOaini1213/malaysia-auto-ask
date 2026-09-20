#!/usr/bin/env bash
set -euo pipefail
CLUSTER_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WAREHOUSE_DIR="$(cd -- "$CLUSTER_DIR/.." && pwd)"
CONTAINER=malaysia-warehouse-cluster
IMAGE=apache/hive:4.0.1@sha256:5194161ef50b80875f937dff04936df047cbe894e9727ab8f0606349345b1bd3
LABEL=malaysia-auto-ask-hadoop-lab
mkdir -p "$WAREHOUSE_DIR/artifacts/cluster"
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  OWNER="$(docker inspect --format '{{index .Config.Labels "project"}}' "$CONTAINER")"
  if [ "$OWNER" != "$LABEL" ]; then echo "Refuse to touch non-project container $CONTAINER" >&2; exit 2; fi
  MOUNTED_CLUSTER="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/cluster"}}{{.Source}}{{end}}{{end}}' "$CONTAINER")"
  if [ "$MOUNTED_CLUSTER" != "$CLUSTER_DIR" ]; then
    echo "Existing project container belongs to a different checkout: $MOUNTED_CLUSTER" >&2
    echo 'Use that checkout or deliberately migrate the project container; refusing an implicit remount.' >&2
    exit 2
  fi
  docker start "$CONTAINER" >/dev/null
else
  docker image inspect "$IMAGE" >/dev/null 2>&1 || docker pull "$IMAGE"
  docker run -d --name "$CONTAINER" --hostname malaysia-warehouse-cluster \
    --label project="$LABEL" --memory 6g --memory-swap 7g --cpus 2 --pids-limit 1024 \
    --user root --entrypoint /bin/bash \
    -p 127.0.0.1:19870:9870 -p 127.0.0.1:18088:8088 \
    -p 127.0.0.1:11000:10000 -p 127.0.0.1:11002:10002 \
    --mount "type=bind,source=$CLUSTER_DIR,target=/cluster,readonly" \
    --mount "type=bind,source=$WAREHOUSE_DIR,target=/warehouse,readonly" \
    --mount type=volume,source=malaysia-warehouse-state,target=/runtime \
    -e HADOOP_CONF_DIR=/cluster/conf -e HIVE_CONF_DIR=/cluster/conf -e TEZ_CONF_DIR=/cluster/conf \
    -e HADOOP_COMMON_HOME=/opt/hadoop -e HADOOP_HDFS_HOME=/opt/hadoop \
    -e HADOOP_YARN_HOME=/opt/hadoop -e HADOOP_MAPRED_HOME=/opt/hadoop \
    -e HADOOP_CLASSPATH='/opt/tez/*:/opt/tez/lib/*:/cluster/conf' \
    "$IMAGE" /cluster/container-start.sh
fi
docker image inspect "$IMAGE" --format '{{json .RepoDigests}}' > "$WAREHOUSE_DIR/artifacts/cluster/image-digests.json"
docker inspect "$CONTAINER" --format '{{json .HostConfig.PortBindings}}' > "$WAREHOUSE_DIR/artifacts/cluster/port-bindings.json"
echo "Started $CONTAINER; run cluster/check.sh for HDFS/YARN/Hive acceptance."
