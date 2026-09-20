# Local HDFS + YARN + Hive/Tez lab

This is an actual single-node, pseudo-distributed Hadoop environment for the JPJ public-data warehouse. NameNode, DataNode, ResourceManager, NodeManager and HiveServer2 run as separate JVMs. Hive uses Tez tasks scheduled by YARN; local execution and fetch-only conversion are disabled for the acceptance query.

It is a learning and reproducibility environment, built with AI assistance on 2026-09-17. It demonstrates a local pipeline, not production operations, multi-node reliability, Kerberos, Kafka or HBase experience.

## Start, verify, query and stop

Prerequisites: PowerShell 7 (`pwsh`, used for the actual execution here), WSL distribution `Ubuntu-24.04`, a working Docker daemon in that distribution, and Python 3 in WSL. The wrappers also pass the Windows PowerShell 5.1 parser, but that host's local script-execution policy prevented a `-File` invocation; no policy was changed. The first start downloads the public Apache image (about 1.1 GB compressed); later starts reuse it. No SSH configuration, host Hadoop installation or paid service is required.

From the repository root in PowerShell 7:

```powershell
./warehouse/cluster/start.ps1
./warehouse/cluster/check.ps1
./warehouse/cluster/exec-hive.ps1 -SqlPath ./warehouse/cluster/smoke/inspect.sql
python ./warehouse/jpj/hive/run_hive.py
./warehouse/cluster/stop.ps1
```

`start.ps1` starts the services asynchronously. `check.ps1` waits for readiness, writes a small synthetic dataset, runs MapReduce wordcount and Hive `GROUP BY`, and checks exact results and application-specific YARN completion. The acceptance test normally takes a few minutes. Business ingestion and its independent data reconciliation are implemented in `warehouse/jpj/`, separately from this smoke test.

The Windows wrapper starts a hidden `wsl.exe ... docker wait malaysia-warehouse-cluster` process. This keeps WSL alive after the launching terminal exits. Its owned PID and start time are recorded in `warehouse/artifacts/cluster/wsl-keepalive.json`; it exits naturally when this container stops. No global WSL configuration is changed. Native Linux users can use the equivalent `.sh` scripts directly; WSL users should start through the PowerShell wrapper so the lifetime guard is installed.

`stop.ps1` stops only the container with this project's name and label. It retains the named volume containing HDFS and the metastore. There is intentionally no automatic delete/reset command. The next start preserves earlier data and the tests use new, timestamped HDFS paths and database names.

## Fixed components and isolation

| Component | Fixed value |
| --- | --- |
| Official image | `apache/hive:4.0.1` |
| Pulled image digest | `sha256:5194161ef50b80875f937dff04936df047cbe894e9727ab8f0606349345b1bd3` |
| Hive / Hadoop / Tez / Java | `4.0.1 / 3.3.6 / 0.10.4 / OpenJDK 8u342` |
| Container | `malaysia-warehouse-cluster` |
| Project label | `project=malaysia-auto-ask-hadoop-lab` |
| Persistent volume | `malaysia-warehouse-state`, mounted at `/runtime` |
| Container limits | 6 GB memory, 7 GB memory plus swap, 2 CPUs, 1024 PIDs |
| YARN worker capacity | 3072 MB, 2 virtual cores |
| Tez AM / task allocation | 768 MB each |
| Warehouse mount | repository `warehouse/` → `/warehouse`, read-only |
| Configuration mount | repository `warehouse/cluster/` → `/cluster`, read-only |

Root is used only to create and set ownership on the dedicated runtime volume. The service processes run as `hive`. NameNode formatting and Derby initialization only occur when this dedicated volume has no initialized state. An interrupted, incomplete Derby directory is preserved under a timestamped name before initialization is retried.

All published ports bind to `127.0.0.1`:

| Local endpoint | Purpose |
| --- | --- |
| `http://127.0.0.1:19870` | HDFS NameNode |
| `http://127.0.0.1:18088` | YARN ResourceManager and REST evidence |
| `127.0.0.1:11000` | HiveServer2 JDBC |
| `http://127.0.0.1:11002` | HiveServer2 web interface |

Inside the container, HDFS uses `hdfs://localhost:9000`, and Beeline uses `jdbc:hive2://localhost:10000/default`. The HDFS paths named `/warehouse/...` are in **HDFS**, not the read-only local `/warehouse` source mount. Authentication is disabled for this localhost-only personal lab; these settings must not be exposed as a public service.

## Integration contract

The SQL wrapper accepts a real SQL file anywhere inside this checkout's `warehouse/` directory. It rejects paths outside that directory, passes the path as an argument, and invokes Beeline with `--force=false`. Paths are converted using PowerShell 5.1-compatible methods. The business runner can equivalently call these commands as argument arrays:

```powershell
wsl -d Ubuntu-24.04 -- docker exec -u hive malaysia-warehouse-cluster hdfs dfs -ls /warehouse
wsl -d Ubuntu-24.04 -- docker exec -u hive malaysia-warehouse-cluster beeline -u jdbc:hive2://localhost:10000/default -n hive --force=false --showHeader=true --outputformat=tsv2 -f /warehouse/cluster/smoke/inspect.sql
```

The JPJ runner owns new paths under `/warehouse/jpj/runs/<run-id>` and unique databases. The cluster smoke test owns `/warehouse/lab_acceptance/<run-id>`. Neither flow overwrites the other's input or result directory.

Use `python warehouse/jpj/hive/run_hive.py` for a new business run; it renders a fresh SQL file and database. Do not re-execute an old run's rendered `warehouse.sql`: its table-creation statements refer to an already-existing database.

**Hive 4.0.1 export caveat:** the first real business run completed its DAGs but produced no expected export files because `INSERT OVERWRITE DIRECTORY` was routed into the query-result cache. The reconciliation gate failed correctly. The business SQL explicitly sets `hive.query.results.cache.enabled=false` before running its exports. This matches [Apache HIVE-28620](https://issues.apache.org/jira/browse/HIVE-28620), fixed upstream in 4.1.0. Keep that session setting when adding export queries to this fixed-version lab; a successful DAG alone is not an export/data-quality pass.

## Evidence and validation boundaries

The initial real acceptance on 2026-09-17 produced:

- HDFS `put → cat → byte comparison` equal to the source.
- YARN MapReduce `application_1789657920441_0001`: `FINISHED / SUCCEEDED`, output `hdfs=1, hive=2, yarn=3`.
- Hive Tez `application_1789657920441_0003`: `FINISHED / SUCCEEDED`; ResourceManager diagnostics report one submitted DAG, one successful DAG, zero failed/killed DAGs; SQL output `alpha=15, beta=20`.

Each new acceptance writes logs and machine-readable evidence under `warehouse/artifacts/cluster/acceptance_<UTC>/`. `acceptance.json` records input hashes, exact results, versions and full application-specific YARN REST responses. The current successful summary is also copied to `warehouse/artifacts/cluster/acceptance.json`. Runtime logs, input downloads, volumes and generated data are not source-code deliverables.

The final restart acceptance also passed: `acceptance_20260917T152742Z`, MapReduce `application_1789658875221_0001` and Tez `application_1789658875221_0002`, both `FINISHED / SUCCEEDED`. The completed business run's HDFS path retained the same 86 directories, 72 files and 187,990,698 content bytes after restart; its Hive database remained present. Repeated `start.ps1` reused the same lifetime guard, and the running container survived a 30-second interval without a foreground WSL call. The container was then stopped, its guard exited, and its named volume was retained. These operations are recorded in `warehouse/artifacts/cluster/operations-acceptance.json`. The delivered environment is **stopped**; use `start.ps1` before another query.

`verify-evidence.py` rejects absent YARN IDs, local-only job IDs, unexpected query results, wrong application types, failed/running/killed applications and a Tez session without the expected successful DAG. Its validation tests can run without Docker:

```powershell
python -m unittest discover -s warehouse/cluster/tests -v
```

This smoke test proves the infrastructure path on tiny deterministic input. Business correctness and the public dataset's row/partition/source-identity checks belong to the separate JPJ pipeline acceptance. Neither passing test means the user independently wrote the entire implementation or operated a production cluster.

## Troubleshooting

- Check `wsl -d Ubuntu-24.04 -- docker ps -a` and the owned keepalive PID if the container stops when Windows terminal commands finish. Do not modify global WSL settings or restart unrelated containers.
- Startup service logs are in `/runtime/logs`; inspect with `docker exec malaysia-warehouse-cluster tail -n 100 /runtime/logs/hiveserver2.log` through WSL. `docker logs` alone may be brief because daemon logs are files.
- The bundled Hive/Hadoop/Tez distributions print duplicate SLF4J binding warnings; the acceptance checks establish whether actual execution succeeds.
- Services bind fixed localhost ports. If another application uses a port, startup will fail instead of stopping that application. Change the project port mapping and matching verification URL deliberately.
- Avoid running many business queries or extra smoke tests concurrently with the 2-vcore worker. A YARN session can stay `RUNNING` briefly after its query; acceptance waits for the relevant application's final state.

References: [Apache Hive manual installation](https://hive.apache.org/docs/latest/admin/manual-installation/), [official Hive Docker guide](https://hive.apache.org/docs/latest/admin/setting-up-hive-with-docker/), [Hadoop 3.3.6 single-node setup](https://hadoop.apache.org/docs/r3.3.6/hadoop-project-dist/hadoop-common/SingleCluster.html).
