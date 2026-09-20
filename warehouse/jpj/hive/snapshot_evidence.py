"""Copy compact evidence from a passed local run into a shareable project folder."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

WAREHOUSE = Path(__file__).resolve().parents[2]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    validation = load(run / "validation.json")
    if validation.get("status") != "passed":
        raise ValueError("Only a passed Hive run can be snapshotted")
    summary = load(run / "business_summary.json")
    python_dir = WAREHOUSE / "artifacts/python"
    check = load(python_dir / "check_report.json")
    if check["status"] != "passed" or check["rows"] != validation["expected_total"]:
        raise ValueError("Python check is not consistent with the accepted Hive run")
    output = WAREHOUSE / "evidence" / validation["run_id"]
    output.mkdir(parents=True, exist_ok=True)
    files = {name: run / name for name in
             ("validation.json", "business_summary.json", "warehouse.sql", "input_partitions.json",
              "hive_aggregates.tsv", "hive_checks.tsv")}
    files.update({name: python_dir / name for name in
                  ("check_report.json", "idempotence_check.json", "year_2025_manifest.json",
                   "year_2026_manifest.json", "year_2025_dq.json", "year_2026_dq.json")})
    evidence_manifest = {"captured_at_utc": datetime.now(timezone.utc).isoformat(),
                         "run_id": validation["run_id"], "files": []}
    for name, source in files.items():
        content = source.read_bytes()
        (output / name).write_bytes(content)
        evidence_manifest["files"].append({"name": name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
    for log in sorted(run.glob("command_*.log")):
        # Retain command log hashes; verbose Tez progress stays in local artifacts.
        if '"yarn", "application", "-status"' in log.read_text(encoding="utf-8"):
            status_name = "yarn_status_" + log.stem + ".txt"
            (output / status_name).write_bytes(log.read_bytes())
            evidence_manifest["files"].append({"name": status_name,
                                               "sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                                               "bytes": log.stat().st_size})
        evidence_manifest["files"].append({"name": "local-artifact/" + log.name,
                                           "sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                                           "bytes": log.stat().st_size})
    (output / "evidence_manifest.json").write_text(json.dumps(evidence_manifest, indent=2), encoding="utf-8")
    previous, current = summary["comparison_years"]
    p, c = str(previous), str(current)
    makers = summary["top_makers_current_comparable_period"]
    lines = [
        "# 真实数据仓库验收与分析", "",
        f"运行：`{validation['run_id']}`；结果：**通过**。", "",
        "数据来源：[马来西亚 JPJ 官方目录](https://data.gov.my/data-catalogue/registration_transactions_car)，CC BY 4.0；截至 2026-08-31。", "",
        f"共 **{check['rows']:,} 条汽车登记、{validation['partition_files']} 个年月分区**；Python 核对 {check['groups_checked']:,} 个组合，Hive 与独立 Python 核对 {validation['aggregate_comparison']['compared_groups']:,} 项汇总，全部一致。",
        "真实 HDFS 存储、Hive 分区 ORC 和 YARN / Tez 作业已执行；原始行号完整且唯一、分区日期无异常。", "",
        "| 同期登记统计 | " + p + " | " + c + " |", "|---|---:|---:|",
        f"| 可比月份 | {','.join(map(str, summary['common_months']))} | {','.join(map(str, summary['common_months']))} |",
        f"| 登记量 | {summary['comparable_registrations'][p]:,} | {summary['comparable_registrations'][c]:,} |",
        f"| 纯电登记量 | {summary['electric_registrations'][p]:,} | {summary['electric_registrations'][c]:,} |",
        f"| 纯电占比 | {summary['electric_share_pct'][p]:.2f}% | {summary['electric_share_pct'][c]:.2f}% |", "",
        f"相同月份的登记量同比变化为 **{summary['comparable_yoy_pct']:+.2f}%**。这里统计的是登记事件，不能改称销量或市场需求。", "",
        "| 本期登记品牌 | 登记量 | 本期占比 |", "|---|---:|---:|",
    ]
    for row in makers[:5]:
        lines.append(f"| {row['maker']} | {row['registrations']:,} | {row['share_pct']:.2f}% |")
    lines += ["", "品牌分析统一去除首尾空白并转为大写，合并同一文本的大小写差异；ODS/DWD/ADS 和跨引擎对账保留原始名称。未自动合并不同拼写或集团品牌。",
              "本次同比范围内识别到的大小写变体：`" + json.dumps(summary.get("maker_case_variants", {}), ensure_ascii=False) + "`。"]
    lines += ["", "YARN 应用：", ""] + [f"- `{a['id']}`：FINISHED / SUCCEEDED。" for a in validation["yarn_applications"]]
    lines += ["", "范围：AI 辅助完成的单节点学习项目；按年度快照发布，支持校验、重复批次跳过和失败恢复。登记办公室/门户字段不代表车主所在地，Rakan Niaga 不作为地理州解释。",
              "", "本报告记录上游数仓验收。冻结汇总可由 MySQL 查询层导入并在默认网页查询，详见 `warehouse/serving/README.md`。原始文件、完整日志与运行状态不纳入 Git；本命令仅生成本地证据快照，不执行上传。", ""]
    (output / "result.md").write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
