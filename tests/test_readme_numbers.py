# -*- coding: utf-8 -*-
"""README 里引用的每个数字，都从产物或常量里重算一遍再和 README 原文比。

仓里原来的绑定只到产物为止：`ablation.py --check` 把 eval/ablation.json 钉在
一次新跑上、`eval.py --check` 把 eval/last_run.json 钉住，但**没有任何东西读
README**。于是产物本身不会漂，README 这份纯文本可以静默变陈旧——改了模型、
重生成产物让 CI 变绿，README 里那一堆数就没人拦了。

这个文件补的就是最后一段：用锚定到具体句子的正则把 README 里的数字抠出来，
逐个与 eval/ablation.json、eval/last_run.json、malaysia_ask/db.py 的常量、
tests/test_filter_contract.py 的组合数比较。改 README 的数而不改代码 → 红；
改代码而不改 README → 红。

一位小数的引用（17.5 / −11.7 / 29.4 …）按 round(x, 1) 比，因为 README 那几处
本来就是四舍五入后的写法。
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from malaysia_ask.db import (  # noqa: E402
    BRAND_LAMBDA, DB_PATH, DEFAULT_REGION_BUMP, QUARTER_END_HOLD, REGION_BUMP, connect, seed,
)
from malaysia_ask.intent import HITL_CODES  # noqa: E402
from malaysia_ask.templates import ADS_TEMPLATES, TEMPLATES  # noqa: E402
from test_filter_contract import (  # noqa: E402
    ADS_COMBINATIONS, DWD_COMBINATIONS, ORACLE_COMBINATIONS,
)

README_PATH = ROOT / "README.md"
README = README_PATH.read_text(encoding="utf-8")
ABLATION = json.loads((ROOT / "eval" / "ablation.json").read_text(encoding="utf-8"))
LAST_RUN = json.loads((ROOT / "eval" / "last_run.json").read_text(encoding="utf-8"))

MINUS = "−"  # README 用的是 U+2212，不是 ASCII 连字符


def _num(text):
    return float(text.replace(MINUS, "-").replace("+", ""))


class ReadmeNumbers(unittest.TestCase):
    """每个测试先定位到 README 的某一行，再把行里的数字与产物比。"""

    def line(self, marker):
        hits = [ln for ln in README.splitlines() if marker in ln]
        self.assertEqual(len(hits), 1, f"README 里 {marker!r} 应当恰好出现在一行，实际 {len(hits)} 行")
        return hits[0]

    def grab(self, marker, pattern):
        line = self.line(marker)
        m = re.search(pattern, line)
        self.assertIsNotNone(m, f"{pattern!r} 没能在这一行里匹配到：{line}")
        return m

    # ---------------- 首屏英文段（对 eval/ablation.json 与 eval/last_run.json） ----------------

    def test_the_english_opening_paragraph_matches_the_artifacts(self):
        """首屏那段英文是第一眼读到的地方，它引用的每个数字也要能被产物推翻。

        「up to 17%」是把 abs_max=17.47 向下取整的保守写法，所以既比对整数部分，
        也断言它没有说得比产物大。
        """
        abs_max = ABLATION["口径翻转对照"]["month_value_gap_pct"]["abs_max"]
        quoted = int(self.grab("disagree by up to", r"up to (\d+)% in a given month").group(1))
        self.assertEqual(quoted, int(abs_max))
        self.assertLessEqual(quoted, abs_max)

        a, b = ABLATION["A_baseline_guard_on"], ABLATION["B_ablation_guard_off"]
        m = self.grab("-question suite measures the guard",
                      r"(\d+)-question suite measures the guard: (\d+) answered, (\d+) stopped")
        n_cases, answered, stopped = (int(m.group(i)) for i in (1, 2, 3))
        self.assertEqual(n_cases, LAST_RUN["summary"]["n"])
        self.assertEqual(answered, LAST_RUN["summary"]["n_expect_answer"])
        self.assertEqual(stopped, LAST_RUN["summary"]["n_hitl"])
        self.assertEqual(f"{answered}/{answered}", a["该答的答对"])
        self.assertEqual(f"{stopped}/{stopped}", a["该停的停住"])
        self.assertEqual(answered + stopped, n_cases)

        silent = int(self.grab("with the guard switched off", r"all (\d+) are answered silently").group(1))
        self.assertEqual(f"{silent}/{stopped}", b["无提示猜测"])
        changed = int(self.grab("of them answer a different question", r"^(\d+) of them").group(1))
        self.assertEqual(f"{changed}/{stopped}", b["结论被改变"])

    def test_the_30_22_8_7_repeated_in_the_prose_match_the_artifacts(self):
        """同一批 30 / 22 / 8 / 7 在正文里复述了七八遍，每一处都单独绑一次。

        表格里的那几格本来就有断言，漏网的是散在中文散文和命令注释里的复述——
        改其中一处而不改产物，以前是不会红的。
        """
        summary = LAST_RUN["summary"]
        a, b = ABLATION["A_baseline_guard_on"], ABLATION["B_ablation_guard_off"]
        for marker, pattern, expected in (
            ("题评测重跑", r"# (\d+) 题评测重跑", summary["n"]),
            ("同一批", r"同一批 (\d+) 题跑两次", summary["n"]),
            ("后四行是", r"后四行是 (\d+) 题自测", summary["n"]),
            ("| 准确率 |", r"(\d+) 条出数题", summary["n_expect_answer"]),
            ("护栏关掉后", r"护栏关掉后，(\d+) 条本该停问的题", summary["n_hitl"]),
            ("条故意停", r"^(\d+) 条故意停", summary["n_hitl"]),
            ("里写明", r"写明：(\d+) 条是\*\*按定义\*\*成立", b["结论被改变的依据"]["by_construction"]),
        ):
            with self.subTest(marker=marker):
                self.assertEqual(int(self.grab(marker, pattern).group(1)), expected)
        # 「8 条本该停问」和 A 臂的 8/8 是同一个 8
        self.assertEqual(f"{summary['n_hitl']}/{summary['n_hitl']}", a["该停的停住"])

    # ---------------- λ 表与区域系数（对 malaysia_ask/db.py 的常量） ----------------

    def test_lambda_table_matches_the_constants(self):
        block = self.line("**λ**：当月批发中当月即上牌的比例")
        # bullet 跨三行，取到「季末压货」之前
        start = README.index(block)
        block = README[start:README.index("- **季末压货**", start)]
        for brand, pattern in (
            ("Perodua", r"Perodua\s+([0-9.]+)"),
            ("Proton", r"Proton\s+([0-9.]+)"),
            ("Honda", r"Honda[^（]*（([0-9.]+)）"),
            ("Toyota", r"Toyota[^（]*（([0-9.]+)）"),
            ("BYD", r"BYD[^（]*（([0-9.]+)）"),
            ("Chery", r"Chery[^（]*（([0-9.]+)）"),
        ):
            m = re.search(pattern, block)
            self.assertIsNotNone(m, f"README 的 λ 段里找不到 {brand}")
            with self.subTest(brand=brand):
                self.assertEqual(float(m.group(1)), BRAND_LAMBDA[brand])

    def test_quarter_end_hold_and_region_bumps_match_the_constants(self):
        m = self.grab("**季末压货**", r"([\d/]+) 月 λ 再乘 ([0-9.]+)")
        self.assertEqual(sorted(int(x) for x in m.group(1).split("/")), [3, 6, 9, 12])
        self.assertEqual(float(m.group(2)), QUARTER_END_HOLD)
        m = self.grab("**区域**：上牌发生在终端所在州", r"巴生谷 ([0-9.]+)、东马 ([0-9.]+)、其余 ([0-9.]+)")
        self.assertEqual(float(m.group(1)), REGION_BUMP[1])
        self.assertEqual({float(m.group(2))}, {REGION_BUMP[5], REGION_BUMP[6]})
        self.assertEqual(float(m.group(3)), DEFAULT_REGION_BUMP)

    # ---------------- 公开锚点（对种子库） ----------------

    def test_public_anchors_match_the_seeded_database(self):
        seed()
        conn = connect(DB_PATH)
        total = conn.execute("SELECT SUM(tiv_units) FROM fact_month WHERE year=2025").fetchone()[0]
        perodua = conn.execute(
            "SELECT SUM(f.tiv_units) FROM fact_month f "
            "JOIN dim_model m ON m.model_id = f.model_id JOIN dim_brand b ON b.brand_id = m.brand_id "
            "WHERE f.year=2025 AND b.brand_name='Perodua'").fetchone()[0]
        conn.close()
        m = self.grab("品牌全年合计按公开报道锚定", r"TIV ([\d,]+)；Perodua ([\d,]+)")
        self.assertEqual(int(m.group(1).replace(",", "")), total)
        self.assertEqual(int(m.group(2).replace(",", "")), perodua)
        m = self.grab("公开锚点来源", r"2025 TIV ([\d,]+)")
        self.assertEqual(int(m.group(1).replace(",", "")), total)

    # ---------------- 266 组模板 × 筛选（对 test_filter_contract 的组合数） ----------------

    def test_template_counts_match_the_registry(self):
        self.assertEqual(int(self.grab("个 DWD 模板都支持已解析的月", r"所有 (\d+) 个 DWD 模板").group(1)),
                         len(TEMPLATES))
        self.assertEqual(int(self.grab("个 ADS 模板支持品牌和国产", r"^(\d+) 个 ADS 模板").group(1)),
                         len(ADS_TEMPLATES))

    def test_the_oracle_combination_count_is_the_one_the_tests_run(self):
        m = self.grab("8 个 DWD 模板 × 2 指标 × 11 组筛选",
                      r"(\d+) 个 DWD 模板 × (\d+) 指标 × (\d+) 组筛选 = (\d+)，"
                      r"(\d+) 个 ADS 模板 × (\d+) 指标 × (\d+) 品牌 × (\d+) 国产口径 = (\d+)")
        dwd_t, dwd_metrics, dwd_filters, dwd_total = (int(m.group(i)) for i in (1, 2, 3, 4))
        ads_t, ads_metrics, ads_brands, ads_origins, ads_total = (int(m.group(i)) for i in (5, 6, 7, 8, 9))
        self.assertEqual(dwd_t, len(TEMPLATES))
        self.assertEqual(ads_t, len(ADS_TEMPLATES))
        self.assertEqual(dwd_t * dwd_metrics * dwd_filters, DWD_COMBINATIONS)
        self.assertEqual(dwd_total, DWD_COMBINATIONS)
        self.assertEqual(ads_t * ads_metrics * ads_brands * ads_origins, ADS_COMBINATIONS)
        self.assertEqual(ads_total, ADS_COMBINATIONS)
        # 四处引用 266 的地方：首屏英文段、「怎么跑」里的注释、分层小节、评测表
        self.assertEqual(int(self.grab("the full brand × origin grid for the aggregate",
                                       r"giving \*\*(\d+)\*\*").group(1)),
                         ORACLE_COMBINATIONS)
        self.assertEqual(int(self.grab("含 README 数字重算", r"(\d+) 组模板×筛选").group(1)),
                         ORACLE_COMBINATIONS)
        self.assertEqual(int(self.grab("核对全部 **266 组**", r"全部 \*\*(\d+) 组\*\*").group(1)),
                         ORACLE_COMBINATIONS)
        m = self.grab("| SQL 结果正确性 |", r"\*\*(\d+)/(\d+)\*\*")
        self.assertEqual((int(m.group(1)), int(m.group(2))), (ORACLE_COMBINATIONS, ORACLE_COMBINATIONS))

    # ---------------- 消融两臂（对 eval/ablation.json） ----------------

    def test_ablation_arms_table_matches_the_artifact(self):
        a, b = ABLATION["A_baseline_guard_on"], ABLATION["B_ablation_guard_off"]
        m = self.grab("| 该停的停住 |", r"\*\*(\S+)\*\* \| (\S+) \|")
        self.assertEqual((m.group(1), m.group(2)), (a["该停的停住"], b["该停的停住"]))
        m = self.grab("| 该答的答对 |", r"\*\*(\S+)\*\* \| (\S+)（无回归）")
        self.assertEqual(m.group(1), a["该答的答对"])
        # B 臂那格写的也是 22/22：护栏关掉不会伤到本来就该答对的 22 题，
        # 依据是 forced_regression == 0，两者一起断言才算钉住。
        self.assertEqual(m.group(2), a["该答的答对"])
        self.assertEqual(b["对22题正常问答的回归"], 0)
        m = self.grab("| 无提示猜测 |", r"\| (\d+) \| \*\*(\S+)\*\* \|")
        self.assertEqual(int(m.group(1)), a["静默错答"])
        self.assertEqual(m.group(2), b["无提示猜测"])
        m = self.grab("| 结论被改变 |", r"\| (\d+) \| \*\*(\S+)\*\* \|")
        self.assertEqual(m.group(2), b["结论被改变"])
        self.assertEqual(b["结论被改变的依据"], {"measured": 0, "by_construction": 7})

    def test_stop_reason_table_matches_the_artifact(self):
        dist = ABLATION["停问原因分布"]
        self.assertEqual(int(self.grab("### 停问原因分类", r"（(\d+) 类").group(1)), len(dist))
        self.assertEqual(int(self.grab("### 停问原因分类", r"/ (\d+) 题）").group(1)),
                         sum(v["n"] for v in dist.values()))
        for code, payload in dist.items():
            m = self.grab(f"| `{code}` |", r"\| (\d+) \| ([\d, ]+) \|")
            with self.subTest(code=code):
                self.assertEqual(int(m.group(1)), payload["n"])
                self.assertEqual([x.strip() for x in m.group(2).split(",")], payload["ids"])
        m = self.grab("护栏的 7 个原因码", r"护栏的 (\d+) 个原因码.*在这 (\d+) 题里触发了 (\d+) 个")
        self.assertEqual(int(m.group(1)), len(HITL_CODES))
        self.assertEqual(int(m.group(2)), sum(v["n"] for v in dist.values()))
        self.assertEqual(int(m.group(3)), len(dist))

    # ---------------- 口径翻转对照表（对 eval/ablation.json） ----------------

    def test_metric_flip_table_matches_the_artifact(self):
        flip = ABLATION["口径翻转对照"]
        for marker, field in (("| 月度 top1 翻转 |", "month_rank_diff"),
                              ("| 月度完整排序变化 |", "full_order_diff_month"),
                              ("| 区域 top1 翻转 |", "region_rank_diff")):
            quoted = self.grab(marker, r"\*\*([^*]+)\*\*").group(1).replace(" ", "")
            with self.subTest(field=field):
                self.assertEqual(quoted, flip[field])
        self.assertFalse(flip["full_order_diff_year"])

        m = self.grab("| 品牌年合计口径差 |", r"([\d.]+)% ~ ([\d.]+)%（均值 ([\d.]+)%）")
        year_gap = flip["year_value_gap_pct"]
        self.assertEqual((float(m.group(1)), float(m.group(2)), float(m.group(3))),
                         (year_gap["min"], year_gap["max"], year_gap["mean"]))

    def test_monthly_gap_sentence_matches_every_month_it_quotes(self):
        line = self.line("| **月度口径差** |")
        by_month = ABLATION["口径翻转对照"]["month_value_gap_pct"]["by_month"]
        self.assertEqual(float(re.search(r"最大 ([\d.]+)%", line).group(1)),
                         ABLATION["口径翻转对照"]["month_value_gap_pct"]["abs_max"])
        quoted = re.findall(rf"(\d+) 月 ([+{MINUS}\-]?[\d.]+)%", line)
        self.assertTrue(quoted, "README 应逐月列出它引用的月度口径差")
        for month, value in quoted:
            with self.subTest(month=month):
                self.assertEqual(_num(value), round(by_month[int(month) - 1], 1))

    def test_legacy_model_numbers_match_the_artifact(self):
        legacy = ABLATION["口径翻转对照"]["legacy_flat_bump_model"]
        m = self.grab("| 旧模型（2026-09-02 前", r"常态 \*\*([\d.]+)%\*\*，仅 2025-12 因年末赶量到 ([\d.]+)%")
        self.assertEqual((float(m.group(1)), float(m.group(2))), (legacy["abs_typical"], legacy["abs_max"]))
        m = self.grab("**所以猜口径的危害在数值不在排名**", r"旧模型下两套数几乎逐月相等（([\d.]+)%）")
        self.assertEqual(float(m.group(1)), legacy["abs_typical"])
        # 同一行里的「差到 17%」和首屏英文段的「up to 17%」是同一个 abs_max 向下取整
        abs_max = ABLATION["口径翻转对照"]["month_value_gap_pct"]["abs_max"]
        quoted = int(self.grab("**所以猜口径的危害在数值不在排名**", r"就会差到 (\d+)%").group(1))
        self.assertEqual(quoted, int(abs_max))
        self.assertLessEqual(quoted, abs_max)

    def test_adjacent_brand_gap_sentence_matches_the_artifact(self):
        adj = ABLATION["口径翻转对照"]["adjacent_brand_gap_pct"]
        m = self.grab("2025 年 TIV 排序里最挤的一对是", r"最挤的一对是 \*\*(.+?)\*\*")
        self.assertEqual(m.group(1), adj["tightest_pair"])
        m = self.grab("全年仍差 **", r"全年仍差 \*\*([\d.]+)%\*\*，且 12 个月里 \*\*(\S+)\*\* 都保持这个先后；"
                                      r"而换口径造成的品牌年合计扰动最大只有 \*\*([\d.]+)%\*\*")
        self.assertEqual(float(m.group(1)), adj["tightest_gap_pct"])
        self.assertEqual(m.group(2), adj["months_tightest_pair_keeps_order"])
        self.assertEqual(float(m.group(3)), adj["max_brand_year_metric_gap_pct"])
        # README 的立论要真的成立：最挤的相邻品牌差 > 换口径造成的最大扰动
        self.assertGreater(adj["tightest_gap_pct"], adj["max_brand_year_metric_gap_pct"])

    def test_lambda_sensitivity_sentence_matches_the_artifact(self):
        sens = ABLATION["lambda_sensitivity"]
        rows = sens["rows"]
        m = self.grab("λ 同乘 0.4 ~ 1.2 重算上牌",
                      r"λ 同乘 ([\d.]+) ~ ([\d.]+) 重算上牌：月度数值差从 ([\d.]+)% 一路变到 ([\d.]+)%")
        scales = [r["scale"] for r in rows]
        self.assertEqual(float(m.group(1)), min(scales))
        self.assertEqual(float(m.group(2)), max(scales))
        first = min(rows, key=lambda r: r["scale"])
        last = max(rows, key=lambda r: r["scale"])
        self.assertEqual(float(m.group(3)), round(first["month_gap_abs_max"], 1))
        self.assertEqual(float(m.group(4)), round(last["month_gap_abs_max"], 1))
        line = self.line("λ 同乘 0.4 ~ 1.2 重算上牌")
        m = re.search(r"月度 top1 (\S+?)、区域 top1 (\S+?) 在整个范围内都不翻转", line)
        self.assertIsNotNone(m)
        self.assertTrue(all(r["month_top1_flips"] == m.group(1) for r in rows))
        self.assertTrue(all(r["region_top1_flips"] == m.group(2) for r in rows))
        self.assertIsNone(sens["first_scale_with_any_top1_flip"])

    # ---------------- 评测表（对 eval/last_run.json） ----------------

    def test_eval_table_matches_the_committed_run(self):
        summary = LAST_RUN["summary"]
        m = self.grab("| 准确率 |", r"\*\*(\d+)%\*\*（(\d+)/(\d+)）")
        self.assertEqual(float(m.group(1)) / 100, summary["accuracy"])
        self.assertEqual((int(m.group(2)), int(m.group(3))),
                         (summary["n_template_ok"], summary["n_expect_answer"]))
        m = self.grab("| 成功率 |", r"\*\*(\d+)%\*\*（(\d+)/(\d+)）")
        self.assertEqual(float(m.group(1)) / 100, summary["success_rate"])
        self.assertEqual((int(m.group(2)), int(m.group(3))),
                         (summary["n_answer_ok"], summary["n_expect_answer"]))
        m = self.grab("| 人工干预率 |", r"\*\*([\d.]+)%\*\*（(\d+)/(\d+)）")
        self.assertEqual(float(m.group(1)), round(summary["hitl_rate"] * 100, 1))
        self.assertEqual((int(m.group(2)), int(m.group(3))), (summary["n_hitl"], summary["n"]))
        m = self.grab("| 口径检索 |", r"\*\*(\d+)/(\d+)\*\*")
        self.assertEqual((int(m.group(1)), int(m.group(2))),
                         (summary["retrieve"]["n_ok"], summary["retrieve"]["n"]))
        m = self.grab("问数 30 条（`eval/cases.json`）", r"问数 (\d+) 条.*口径检索 (\d+) 条")
        self.assertEqual(int(m.group(1)), summary["n"])
        self.assertEqual(int(m.group(2)), summary["retrieve"]["n"])


if __name__ == "__main__":
    unittest.main()
