# JPJ 真实登记数据查询层

把已经实际运行并验收的 Hive 结果接到 MySQL、只读 API 和网页，让问数结果可追溯。此层使用 2026-09-17 冻结快照：2025-01 至 2026-08，**1,536 项汇总**代表上游 **1,436,804 次汽车登记**。MySQL 保存汇总，不保存这 143 万条明细。

默认网页 `http://127.0.0.1:8777/`（`/desk` 同入口）；右上角可切到 `/demo`、`/demo/desk` 旧模拟演示。页面来源、口径和颜色标记区分两套数据。真实入口不使用 TIV 模拟值补缺。规则解析和固定 SQL 不调用大模型。

## 本机启动

在仓库根目录执行。需要 Python 3.10+、Docker；Windows 使用已有 WSL `Ubuntu-24.04` 中的 Docker daemon。依赖装入项目 venv，不修改全局 Python。

```powershell
python -m venv warehouse/runtime/mysql-venv
$jpjPython = 'warehouse/runtime/mysql-venv/Scripts/python.exe'
& $jpjPython -m pip install -r warehouse/serving/requirements.txt
& $jpjPython -m warehouse.serving.ops start
& $jpjPython -m warehouse.serving.store
& $jpjPython scripts/serve.py
# 浏览器 http://127.0.0.1:8777/
```

Linux 对应 venv 解释器为 `warehouse/runtime/mysql-venv/bin/python`；生命周期脚本在 Linux 直接调用 Docker。此次真实验收环境是 Windows + WSL Ubuntu-24.04；没有把 Linux 原生启动写成已验证结果。无需为查询层重跑 Hive 或再次下载明细。冻结输入与独立 Python 汇总均随代码保留。

`ops start` 创建专属容器 `jpj-mysql-serving-20260918`、卷 `jpj-mysql-serving-20260918-data`。固定官方镜像：

```text
mysql:8.4.6@sha256:869218921e61d6c3c89820955d63cca42971f0e3e6c1e2792247bbd944ebc6e9
```

MySQL 仅映射 `127.0.0.1:13306`，限制 2 CPU、1.5 GiB 内存、256 MiB buffer pool 和 40 连接；关闭 MySQL X 端口。API 只监听 `127.0.0.1:8777`。脚本不修改其他容器、Hive 服务或全局 WSL 设置。Windows 下专属 `docker wait` 隐藏进程维持 WSL；停止此容器后该进程自然退出。

随机凭据与 MySQL root 配置只写 `warehouse/runtime/mysql-serving/`，已被 Git 忽略。不要将该目录放进作品集或日志。API 使用仅有本库 `SELECT` 权限的 `jpj_reader`；导入使用无 DDL 权限的 writer；建表与授予权限由初始化过程完成。API 再使用只读事务，返回元数据和结果来自同一次一致读取。

停止：先在 API 终端按 Ctrl+C，再执行以下命令；数据卷保留，重复启动不重新累计汇总。

```powershell
& $jpjPython -m warehouse.serving.ops stop
& $jpjPython -m warehouse.serving.ops status
```

仅运行原标准库模拟演示：`python scripts/serve.py --demo`，端口 8766。

## 接口合同

`GET /api/catalog` 返回数据集、版本、月份覆盖、品牌、燃料类别、支持的查询和不可用维度。`POST /api/query` 请求必须且仅包含 `query_id`、`parameters`；Content-Type 为 `application/json`。

| query_id | 必填 parameters | 可选 parameters |
| --- | --- | --- |
| `monthly_registrations` | `start_month`, `end_month` | `maker`, `metric` |
| `brand_compare` | `start_month`, `end_month`, `makers`（2 至 8 个不同品牌） | `metric` |
| `maker_ranking` | `start_month`, `end_month` | `limit`（1 至 30，默认 10）, `metric` |
| `fuel_monthly` | `start_month`, `end_month` | `fuel`, `metric` |

月份为 `YYYY-MM`；每个指定月份都必须存在。唯一指标 `registrations`，省略时显式规范化为此值。品牌依据 catalog 校验，只规范大小写与两端空格；不推断集团关系。固定品牌或燃料的月序列补零，原始标签仍保存在表中。

```json
{"query_id":"brand_compare","parameters":{"start_month":"2026-01","end_month":"2026-08","makers":["BYD","TESLA"],"metric":"registrations"}}
```

实测 `rows` 为 BYD 7,472 次、TESLA 3,733 次。响应还包含 `query_id`, `parameters`, `columns`, `source`（dataset/version/hashes/官方来源/截至日）, `metric_definition`, `sql`, `sql_bindings`, `routing`。SQL 的值始终参数绑定，API 不接受任意 SQL。

`POST /api/ask` 只接收 `{"question":"…"}`，对完整问句做有限规则匹配，目前支持三个模板：

- `2026-01至2026-08 每月登记量`
- `2026-01至2026-08 BYD和TESLA登记量对比`
- `2026-01至2026-08 品牌登记量排名前5`

未完整识别、缺必要条件、销量/TIV、超出月份覆盖、额外筛选都会结构化拒绝。示例错误为 HTTP 422 `{"error":{"code":"UNSUPPORTED_FILTER","message":"…","details":{"parameters":["owner_state"]}}}`。网页一旦开始新请求就清除旧结果；失败时在输入附近和结果区说明本次没有结果。NaN/Infinity、重复 JSON 键、过大请求、非 loopback Host 与跨站 Origin 也拒绝。

## 数据模型、事务和对账

`schema.sql` 中三张表：

- `dataset_versions` 保存源版本、来源 JSON、汇总行数与代表的登记数。
- `aggregates` 的主键为 `(version, dimension, key1, key2)`，数量为无符号整数，有正数约束和版本外键。原标签为 binary collation；规范品牌单独存列。
- `active_dataset` 指向一份已完整对账的有效版本。

导入先校验冻结文件 SHA-256、Hive 验收及实际 YARN 成功状态、独立 Python oracle、维度完整性和总数；再使用数据库命名锁串行导入。一笔事务中写版本和全部汇总、逐项读回对账，最后切换有效版本。中途异常全部回滚；已有版本会再次核对内容，重复导入返回 `unchanged`。更新公开数据需要先完成上游验收，再明确登记新快照和哈希；本次不自动信任任意新文件。

索引包括 `(version, dimension, year_month)`、`(version, dimension, maker_norm, year_month)`、`(version, dimension, fuel, year_month)`。实际 `EXPLAIN ANALYZE` 中，月份使用 `ix_month`，品牌连接使用 `ix_maker_month`，燃料连接使用 `ix_fuel_month`；排名包含聚合和排序。本数据只有 1,536 行，执行计划用于解释访问路径，**没有进行索引前后性能对照，也没有吞吐或加速倍数结论**。

## 实际验收

```powershell
$env:JPJ_MYSQL_INTEGRATION='1'
& $jpjPython -m unittest discover -s warehouse/serving/tests -v
& $jpjPython -m warehouse.serving.verify
```

2026-09-18 实际 MySQL 8.4.6 验收：

- 30 项测试全部通过，无跳过：真实 reader 写入拒绝、只读事务、重复导入、第四行后注入失败并核对回滚、坏源文件拒绝、错误筛选、指标混淆、月份不足、品牌大小写、JSON/Origin 和真实 HTTP。
- 1,536 项 Hive / 独立 Python / MySQL 汇总逐项相等。
- 130 项查询对账通过：全月份、每个规范品牌的月序列、每个燃料类别月序列、全部月燃料、三个期间排名及品牌对比。
- 保存 5 个真实 `EXPLAIN FORMAT=JSON` / `EXPLAIN ANALYZE` 示例及实际 schema、索引、reader grants。

可重跑输出在 `warehouse/artifacts/mysql-serving/`；可分享的小型冻结证据在 [evidence/20260918/](evidence/20260918/)。含 `acceptance.json`、`tests.txt`、`schema_and_explain.json`、`mysql_runtime.json`、`import_result.json` 和文件哈希清单。验证脚本不把单元测试成功等同于网页视觉验收；本次浏览器另核对了真实对比结果、模拟切换和错误后清空旧结果。

## 来源与边界

官方来源：[JPJ Car Registration Transactions](https://data.gov.my/data-catalogue/registration_transactions_car)，CC BY 4.0。Hive 输入来自 `warehouse/evidence/20260917_152407_7272aa/`；独立 Python 汇总为 `inputs/expected_aggregates.tsv`，其生成链路见上游验收报告。原始汇总和四项来源 SHA-256 随 API 返回。官方数据可能继续更新，本网页使用的截止日仍是 **2026-08-31**。

登记不等于销量、批发 TIV、进口或库存；登记办公室不代表车主所在地。冻结边际汇总缺少品牌×燃料、月份×州、车型和颜色联合表，所以拒绝这些查询，不用两个边际合计猜联合分布。服务为本机单节点项目，不提供线上认证、生产高可用、多用户资源隔离、任意 NL2SQL 或大模型语义路由。本次功能由 AI 辅助开发，并完成上述实际运行验证。

技术参考：[官方 MySQL Docker 镜像](https://hub.docker.com/_/mysql)、[MySQL 8.4 用户权限](https://dev.mysql.com/doc/refman/8.4/en/creating-accounts.html)、[EXPLAIN](https://dev.mysql.com/doc/refman/8.4/en/explain.html)。
