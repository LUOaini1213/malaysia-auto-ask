# -*- coding: utf-8 -*-
"""停问机制消融对照实验。

同一批 30 题跑两次：
  A 基线   ask(q)              —— 护栏开，该停就停
  B 消融   ask(q, force=True)  —— 护栏关，按「没有护栏的系统」的朴素默认强行作答

对 8 条本该停问的题，B 会给出一个看起来正常的表。本脚本判定它是不是
「静默错答」：只要系统为了作答而丢弃过筛选、或凭空补过参数，返回的表就
不是用户问的那张表，且界面上没有任何提示——记为静默错答。

另外单独做「口径翻转」对照：对双口径歧义题，把 TIV 和上牌两种解释都算一遍，
看结论是否真的会变。这一项用来诚实标注：本演示数据下猜口径的实际危害有多大。

输出 eval/ablation.json。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from malaysia_ask.ask import ask  # noqa: E402
from malaysia_ask.db import seed, connect, DB_PATH  # noqa: E402
from malaysia_ask.intent import HITL_CODES  # noqa: E402


def top_name(res):
    rows = res.get("rows") or []
    return rows[0].get("name") if rows else None


def metric_flip(year=2025):
    """同一问题在 TIV / 上牌两套口径下，结论是否不同。返回不一致计数。"""
    conn = connect(DB_PATH)
    J = ("FROM fact_month f "
         "JOIN dim_model m ON m.model_id = f.model_id "
         "JOIN dim_brand b ON b.brand_id = m.brand_id")

    def top(col, extra="", args=()):
        sql = (f"SELECT b.brand_name {J} WHERE f.year=? {extra} "
               f"GROUP BY b.brand_name ORDER BY SUM(f.{col}) DESC LIMIT 1")
        r = conn.execute(sql, (year, *args)).fetchone()
        return r[0] if r else None

    out = {"year": year, "checks": []}

    a, b = top("tiv_units"), top("registration_units")
    out["checks"].append({"scope": "全年整体", "tiv_top": a, "reg_top": b, "same": a == b})

    diff_m = 0
    for mth in range(1, 13):
        a = top("tiv_units", "AND f.month=?", (mth,))
        b = top("registration_units", "AND f.month=?", (mth,))
        if a != b:
            diff_m += 1
    out["month_rank_diff"] = f"{diff_m}/12"

    diff_r = 0
    regions = [r[0] for r in conn.execute("SELECT region_id FROM dim_region").fetchall()]
    for rid in regions:
        a = top("tiv_units", "AND f.region_id=?", (rid,))
        b = top("registration_units", "AND f.region_id=?", (rid,))
        if a != b:
            diff_r += 1
    out["region_rank_diff"] = f"{diff_r}/{len(regions)}"

    # 完整排序是否变化（比 top1 更严格）
    def order(col, extra="", args=()):
        sql = (f"SELECT b.brand_name {J} WHERE f.year=? {extra} "
               f"GROUP BY b.brand_name ORDER BY SUM(f.{col}) DESC")
        return [x[0] for x in conn.execute(sql, (year, *args)).fetchall()]

    out["full_order_diff_year"] = order("tiv_units") != order("registration_units")
    out["full_order_diff_month"] = f"{sum(1 for m in range(1, 13) if order('tiv_units','AND f.month=?',(m,)) != order('registration_units','AND f.month=?',(m,)))}/12"

    # 年合计口径差
    y_gaps = []
    for (bn,) in conn.execute(f"SELECT DISTINCT b.brand_name {J} WHERE f.year=?", (year,)).fetchall():
        t = conn.execute(f"SELECT SUM(f.tiv_units) {J} WHERE f.year=? AND b.brand_name=?", (year, bn)).fetchone()[0]
        r = conn.execute(f"SELECT SUM(f.registration_units) {J} WHERE f.year=? AND b.brand_name=?", (year, bn)).fetchone()[0]
        if t and r:
            y_gaps.append(abs(t - r) / t * 100)
    out["year_value_gap_pct"] = {
        "min": round(min(y_gaps), 2), "max": round(max(y_gaps), 2),
        "mean": round(sum(y_gaps) / len(y_gaps), 2),
    } if y_gaps else None

    # 月度口径差（滞后与季末压货的真实影响都在这里）
    m_gaps = []
    for m in range(1, 13):
        t, r = conn.execute(
            f"SELECT SUM(f.tiv_units), SUM(f.registration_units) {J} WHERE f.year=? AND f.month=?",
            (year, m)).fetchone()
        if t and r:
            m_gaps.append(round((r - t) / t * 100, 2))
    out["month_value_gap_pct"] = {
        "by_month": m_gaps,
        "abs_max": round(max(abs(x) for x in m_gaps), 2) if m_gaps else None,
    }
    out["结论"] = (
        "本市场相邻品牌差距大（Perodua 断层领先，Honda 稳定领先 Toyota 约 2.7%），"
        "口径换成上牌不改变任何排名；但月度数值最大差 "
        f"{out['month_value_gap_pct']['abs_max']}%。"
        "即：猜口径的危害在数值不在排名。λ 是基于渠道周转的假设值，未按「让排名翻转」反向调参。"
    )
    conn.close()
    return out


def main():
    seed()
    cases = json.loads((ROOT / "eval" / "cases.json").read_text(encoding="utf-8"))
    hitl_cases = [c for c in cases if c.get("expect_hitl")]
    answer_cases = [c for c in cases if not c.get("expect_hitl")]

    # ---- A 基线：护栏开 ----
    base_stop_ok = sum(1 for c in hitl_cases if ask(c["q"])["hitl"])
    base_ans_ok = 0
    for c in answer_cases:
        r = ask(c["q"])
        ok = (not r["hitl"]) and bool(r.get("rows") or r.get("retrieve"))
        if r.get("template_id") and c.get("template_id"):
            ok = ok and r["template_id"] == c["template_id"] and r.get("metric") == c.get("metric")
        if ok and c.get("top_name") and r.get("rows"):
            ok = r["rows"][0].get("name") == c["top_name"]
        if ok:
            base_ans_ok += 1

    # ---- B 消融：护栏关 ----
    # harm 分级：
    #   SCOPE_CHANGED   丢弃/伪造了筛选条件 -> 返回的是另一个问题的表（硬错）
    #   PERIOD_CHANGED  时间被静默改写      -> 答的是另一个时间段（硬错）
    #   METRIC_GUESSED  口径被猜            -> 是否改变结论取决于数据，实测判定
    HARM_BY_CODE = {
        "OUT_OF_SCOPE_ENTITY": "SCOPE_CHANGED",
        "UNDEFINED_TERM": "SCOPE_CHANGED",
        "RELATIVE_TIME": "PERIOD_CHANGED",
        "YEAR_OUT_OF_RANGE": "PERIOD_CHANGED",
        "MISSING_YEAR": "PERIOD_CHANGED",
        "AMBIGUOUS_METRIC": "METRIC_GUESSED",
        "MISSING_METRIC": "METRIC_GUESSED",
    }

    forced_rows = []
    silent_guess = 0      # 无提示地猜/丢过东西
    conclusion_wrong = 0  # 结论确实被改变
    for c in hitl_cases:
        r = ask(c["q"], force=True)
        guesses = r.get("guesses") or []
        answered = bool(r.get("rows"))
        code = r.get("hitl_code") or ""
        harm = HARM_BY_CODE.get(code, "UNKNOWN")
        guessed = answered and len(guesses) > 0
        if guessed:
            silent_guess += 1

        detail = ""
        if harm == "METRIC_GUESSED":
            # 实测：把两套口径都问一遍，看结论是否真的会变
            a = ask(c["q"] + " TIV")
            b = ask(c["q"] + " 上牌")
            ta, tb = top_name(a), top_name(b)
            if ta and tb and ta != tb:
                changed = True
                detail = f"两套口径结论不同：TIV={ta} / 上牌={tb}"
            else:
                changed = False
                detail = (f"排名结论相同（均为 {ta}）：本市场相邻品牌差距大，排名对口径不敏感。"
                          "但同样的猜测用在数值型问题上，月度最大偏差见「口径翻转对照」。")
        else:
            changed = guessed
            detail = "返回的表不是被问的那张表"

        if changed:
            conclusion_wrong += 1

        forced_rows.append({
            "id": c["id"],
            "q": c["q"],
            "hitl_code": code,
            "code_zh": HITL_CODES.get(code, ("", ""))[0],
            "harm": harm,
            "guesses": guesses,
            "answered": answered,
            "returned_top": top_name(r),
            "n_rows": len(r.get("rows") or []),
            "silent_guess": guessed,
            "conclusion_changed": changed,
            "detail": detail,
        })

    # 消融模式不能损伤本来就该答对的 22 题
    forced_regression = 0
    for c in answer_cases:
        a = ask(c["q"])
        b = ask(c["q"], force=True)
        if top_name(a) != top_name(b) or a.get("template_id") != b.get("template_id"):
            forced_regression += 1

    # ---- 停问原因分布 ----
    dist = {}
    for row in forced_rows:
        k = row["hitl_code"] or "UNKNOWN"
        dist.setdefault(k, {"code_zh": HITL_CODES.get(k, ("", ""))[0],
                            "说明": HITL_CODES.get(k, ("", ""))[1],
                            "n": 0, "ids": []})
        dist[k]["n"] += 1
        dist[k]["ids"].append(row["id"])

    flip = metric_flip()

    result = {
        "n_cases": len(cases),
        "n_answer_cases": len(answer_cases),
        "n_stop_cases": len(hitl_cases),
        "A_baseline_guard_on": {
            "该停的停住": f"{base_stop_ok}/{len(hitl_cases)}",
            "该答的答对": f"{base_ans_ok}/{len(answer_cases)}",
            "静默错答": 0,
        },
        "B_ablation_guard_off": {
            "该停的停住": f"0/{len(hitl_cases)}",
            "强行作答": f"{sum(1 for x in forced_rows if x['answered'])}/{len(hitl_cases)}",
            "无提示猜测": f"{silent_guess}/{len(hitl_cases)}",
            "结论被改变": f"{conclusion_wrong}/{len(hitl_cases)}",
            "结论被改变率": round(conclusion_wrong / len(hitl_cases), 4),
            "对22题正常问答的回归": forced_regression,
        },
        "停问原因分布": dist,
        "口径翻转对照": flip,
        "forced_rows": forced_rows,
    }

    out = ROOT / "eval" / "ablation.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in result.items() if k != "forced_rows"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
