# JPJ 汽车登记数据仓库

在现有汽车市场问数项目上增加真实公开数据处理链路，用于练习和验证数据工程工作。数据来自马来西亚陆路交通局（JPJ），经过 Python 校验及年月分区后写入 HDFS，由 Hive SQL 在 YARN / Tez 上转换为 ORC 明细和月度汇总，再与原始文件的独立 Python 汇总逐项对账。

2026-09-18 已将验收通过的 **1,536 项 Hive 汇总**接入真实 MySQL 8.4.6 和默认网页。查询带 SQL、指标口径、来源版本与哈希；旧 SQLite 模拟演示明确保留在 `/demo`，不能混作真实记录。启动与 API 合同见 [serving/README.md](serving/README.md)。MySQL 查询层不保存原始百万行登记明细。

## 数据与口径

- [官方数据目录](https://data.gov.my/data-catalogue/registration_transactions_car)：Car Registration Transactions，CC BY 4.0。
- 本次下载：2025 年、2026 年官方 Parquet 文件；目录截至 **2026-08-31**，官方更新时间 **2026-09-10**。
- 每行代表一次汽车登记。登记数量不等于批发、销售、进口或库存；不与演示中的 MAA TIV 相加。
- `state` 表示办理登记的 JPJ 办公室或合作门户，不能当成车主所在地。`Rakan Niaga` 保留为门户类别。
- 公开字段相同的两行可能是两笔真实登记，不能按日期、品牌、车型直接去重。用文件 SHA-256 和源文件行号记录本次快照的来源身份。
- 2026 为部分年度，同比只使用两年都存在的月份。目录和文件均不含个人身份信息。
- 品牌分析合并同一名称的大小写差异，本次发现 `BMW/Bmw`、`McLaren/Mclaren`；仓库明细及跨引擎对账仍保留原标签。不同拼写或品牌集团关系不自动合并。

## 实现

```text
官方 Parquet → 下载检查、SHA-256、来源元数据
            → Python 日期/字段校验 → 暂存 → 按年发布、按月分区 TSV
            → HDFS 独立运行目录 → Hive ODS 外部表
            → Hive / Tez on YARN → DWD 分区 ORC
            → ADS 年月 × 品牌 × 燃料 × 登记办公室汇总
            → 原始 Parquet 的 Python Counter 对账 → 分析与验收 JSON
            → 冻结汇总及来源校验 → MySQL 版本化事务导入
            → 只读固定 SQL API → 真实网页 / Civil Buddy 工具
```

代码按文件或年度快照重跑：未变化且产物完整的年度跳过，源文件变化则重建该年；发布前失败保留旧的有效年度输出。它不是逐行 CDC，也没有宣称多节点高可用。每次 Hive 验收使用独立数据库和 HDFS 路径，保留失败记录，避免一次失败覆盖之前的结果。

## 复跑

Python 3.10+ 和 `jpj/requirements.txt` 中的 PyArrow 用于公共数据处理。Hive 集群另外需要 Linux Docker，Windows 使用 WSL Ubuntu-24.04。集群为单节点实验环境，固定官方 Apache 镜像，资源和停止方式见 [cluster/README.md](cluster/README.md)。

在仓库根目录执行：

```powershell
python -m pip install -r warehouse/jpj/requirements.txt
python warehouse/jpj/pipeline.py download
python warehouse/jpj/pipeline.py build
python warehouse/jpj/pipeline.py check
python -m unittest discover -s warehouse/jpj/tests -v
python -m unittest discover -s warehouse/jpj/hive -p "test_*.py" -v

pwsh -NoProfile -File warehouse/cluster/start.ps1
# 按 cluster/README.md 等待服务就绪后：
python warehouse/jpj/hive/run_hive.py
```

在 Linux 中用 `bash warehouse/cluster/start.sh` 启动，随后运行相同的 Python 命令。

再次运行 `build` 会检查源文件及产物指纹；下载端默认使用经过校验的本地快照。拉取下一次官方更新时，先核对 `jpj/data_sources.json` 中的发布范围和截至日期，再运行 `download --refresh` 和 `build --data-asof YYYY-MM-DD`。新增年份也要先在来源清单中登记官方 URL。

## 验收与结果

2026-09-17 全量验收已通过：**1,436,804 条记录、20 个分区、1,536 项 Hive / Python 汇总全部一致**；实际 YARN 应用 `application_1789657920441_0006` 成功结束。原始记录与来源身份计数一致，日期分区和身份异常均为零。详见 [验收与分析报告](evidence/20260917_152407_7272aa/result.md)。

- `artifacts/python/`：下载/构建摘要、各年 DQ 与产物清单、独立汇总、全量对账结果。
- `artifacts/hive/<run_id>/`：输入分区快照、执行 SQL、HDFS 列表、各命令日志、Hive 结果、YARN 应用状态和 `validation.json`。
- 只有源文件行数、全部汇总、唯一来源身份、日期分区，以及真实 YARN 应用终态都通过，`validation.json` 才写 `status: passed`。
- `business_summary.json` 给出相同月份的同比、纯电登记占比和品牌统计。它仅在完整验收通过后生成。
- `data/`、`artifacts/` 和运行状态不提交 Git；可分享的小型验收快照单独放在 `evidence/`。

验收通过后可执行 `python warehouse/jpj/hive/snapshot_evidence.py warehouse/artifacts/hive/<run_id>` 生成小型证据快照，包括来源清单、统计结果、验收 JSON、实际 SQL 和完整日志的哈希。生成本地快照不会上传或发布到 GitHub。

只更新分析口径、无需重新运行集群时，使用 `python warehouse/jpj/hive/run_hive.py --analyse-existing warehouse/artifacts/hive/<run_id>`。它先核对已通过的冻结输出，再重建业务报告；不会把这一步记成新的 HDFS/YARN 执行。

本次全量集成曾遇到 Hive 4.0.1 的结果缓存问题：`INSERT OVERWRITE DIRECTORY` 完成却把结果写入 `_resultscache_`，目标文件不存在；验收脚本正确记录失败。症状与 Apache [HIVE-28620](https://issues.apache.org/jira/browse/HIVE-28620) 一致。业务 SQL 显式关闭 `hive.query.results.cache.enabled`，随后重新执行并检查实际输出，而不把进程退出码或 DAG 成功单独视作验收通过。

停止专属实验集群：

```powershell
pwsh -NoProfile -File warehouse/cluster/stop.ps1
```

## 面试时能解释什么

从来源的登记口径和合法重复行开始，展示数据为什么按年月分区；说明一次中断如何避免发布半个年度，以及第二次运行为什么不会重复累计；然后展示真实 YARN 应用和 SQL 结果如何与独立 Python 汇总核对。当前实现是在 AI 辅助下补做并验证的单节点项目，不能替代独立掌握、生产集群运维经验或未做过的 Spark、Doris、Kettle 经历。

技术参考：[Apache Hive 安装](https://hive.apache.org/docs/latest/admin/manual-installation/)、[Hive DDL](https://hive.apache.org/docs/latest/language/languagemanual-ddl/)、[Hadoop 单节点配置](https://hadoop.apache.org/docs/r3.3.6/hadoop-project-dist/hadoop-common/SingleCluster.html)。
