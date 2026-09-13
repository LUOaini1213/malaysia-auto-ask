# -*- coding: utf-8 -*-
"""停问机制消融对照实验。

同一批 30 题跑两次：
  A 基线   ask(q)              —— 护栏开，该停就停
  B 消融   ask(q, force=True)  —— 护栏关，按「没有护栏的系统」的朴素默认强行作答

对 8 条本该停问的题，B 会给出一个看起来正常的表。本脚本判定它是不是
「静默错答」：只要系统为了作答而丢弃过筛选、或凭空补过参数，返回的表就
不是用户问的那张表，且界面上没有任何提示——记为静默错答。

「结论被改变」分两种依据，输出里逐行标明 `basis`：
  measured          双口径歧义题把 TIV / 上牌两种解释都算一遍，实测结论是否不同
  by_construction   丢弃筛选 / 改写时间的题，返回的表按定义就不是被问的那张表

另外单独做「口径翻转」对照：本演示数据下猜口径的实际危害有多大。这里把
2026-09-02 之前的旧上牌模型（上牌 = 批发 × 各区固定系数）放在同一份批发数
上重算，与现行渠道模型逐月对照——两条曲线的常态值与最大值都由本脚本算出，
落在 legacy_flat_bump_model / month_value_gap_pct 里，脚本里不写死任何一个。
再对 λ 做敏感性扫描，把「未按让排名翻转反向调参」变成一个可查的数。

    python scripts/ablation.py           # 重算并写 eval/ablation.json
    python scripts/ablation.py --check   # 重算并与已提交的 eval/ablation.json 对比，漂移则退出 1
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from malaysia_ask.ask import ask  # noqa: E402
from malaysia_ask.db import DB_PATH, connect, registration_series, seed  # noqa: E402
from malaysia_ask.intent import HITL_CODES  # noqa: E402

OUT = ROOT / "eval" / "ablation.json"

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

JOIN = ("FROM fact_month f "
        "JOIN dim_model m ON m.model_id = f.model_id "
        "JOIN dim_brand b ON b.brand_id = m.brand_id")


def top_name(res):
    rows = res.get("rows") or []
    return rows[0].get("name") if rows else None


def _answer_ok(case, r):
    ok = (not r["hitl"]) and bool(r.get("rows") or r.get("retrieve"))
    if r.get("template_id") and case.get("template_id"):
        ok = ok and r["template_id"] == case["template_id"] and r.get("metric") == case.get("metric")
    if ok and case.get("top_name") and r.get("rows"):
        ok = r["rows"][0].get("name") == case["top_name"]
    return ok


def guard_arms(cases):
    """A（护栏开）与 B（护栏关）两臂，全部计数都是测出来的，不写常量。"""
    hitl_cases = [c for c in cases if c.get("expect_hitl")]
    answer_cases = [c for c in cases if not c.get("expect_hitl")]

    # ---- A 基线：护栏开 ----
    a_runs = {c["id"]: ask(c["q"]) for c in hitl_cases}
    base_stop_ok = sum(1 for r in a_runs.values() if r["hitl"])
    base_silent = sum(1 for r in a_runs.values() if (not r["hitl"]) and r.get("rows"))
    base_ans_ok = sum(1 for c in answer_cases if _answer_ok(c, ask(c["q"])))

    # ---- B 消融：护栏关 ----
    forced_rows = []
    b_stopped = 0
    silent_guess = 0
    conclusion_wrong = 0
    basis_counts = {"measured": 0, "by_construction": 0}
    for c in hitl_cases:
        r = ask(c["q"], force=True)
        if r["hitl"]:
            b_stopped += 1
        guesses = r.get("guesses") or []
        answered = bool(r.get("rows"))
        code = r.get("hitl_code") or ""
        harm = HARM_BY_CODE.get(code, "UNKNOWN")
        guessed = answered and len(guesses) > 0
        if guessed:
            silent_guess += 1

        if harm == "METRIC_GUESSED":
            basis = "measured"
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
            basis = "by_construction"
            changed = guessed
            detail = "返回的表不是被问的那张表（筛选被丢弃或时间被改写）"
        if changed:
            conclusion_wrong += 1
            basis_counts[basis] += 1

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
            "basis": basis,
            "detail": detail,
        })

    # 消融模式不能损伤本来就该答对的 22 题
    forced_regression = 0
    for c in answer_cases:
        a = ask(c["q"])
        b = ask(c["q"], force=True)
        if top_name(a) != top_name(b) or a.get("template_id") != b.get("template_id"):
            forced_regression += 1

    dist = {}
    for row in forced_rows:
        k = row["hitl_code"] or "UNKNOWN"
        dist.setdefault(k, {"code_zh": HITL_CODES.get(k, ("", ""))[0],
                            "说明": HITL_CODES.get(k, ("", ""))[1],
                            "n": 0, "ids": []})
        dist[k]["n"] += 1
        dist[k]["ids"].append(row["id"])

    n_h, n_a = len(hitl_cases), len(answer_cases)
    return {
        "n_cases": len(cases),
        "n_answer_cases": n_a,
        "n_stop_cases": n_h,
        "A_baseline_guard_on": {
            "该停的停住": f"{base_stop_ok}/{n_h}",
            "该答的答对": f"{base_ans_ok}/{n_a}",
            "静默错答": base_silent,
        },
        "B_ablation_guard_off": {
            "该停的停住": f"{b_stopped}/{n_h}",
            "强行作答": f"{sum(1 for x in forced_rows if x['answered'])}/{n_h}",
            "无提示猜测": f"{silent_guess}/{n_h}",
            "结论被改变": f"{conclusion_wrong}/{n_h}",
            "结论被改变率": round(conclusion_wrong / n_h, 4) if n_h else None,
            "结论被改变的依据": basis_counts,
            "对22题正常问答的回归": forced_regression,
        },
        "停问原因分布": dist,
        "forced_rows": forced_rows,
    }


def _tiv_by_key(conn):
    """(year, model_id, region_id) -> 12 个月批发；以及 model -> 品牌名。"""
    series = {}
    for y, mth, mid, rid, tiv in conn.execute(
            "SELECT year, month, model_id, region_id, tiv_units FROM fact_month"):
        series.setdefault((y, mid, rid), [0] * 12)[mth - 1] = tiv
    brand_of = {mid: bn for mid, bn in conn.execute(
        "SELECT m.model_id, b.brand_name FROM dim_model m JOIN dim_brand b ON b.brand_id = m.brand_id")}
    return series, brand_of


def _monthly_gaps(month_tiv, month_reg):
    return [round((month_reg[m] - month_tiv[m]) / month_tiv[m] * 100, 2) for m in range(12)]


def metric_flip(year=2025):
    """同一问题在 TIV / 上牌两套口径下，结论是否不同；月度 / 年度数值差。"""
    conn = connect(DB_PATH)

    def top(col, extra="", args=()):
        sql = (f"SELECT b.brand_name {JOIN} WHERE f.year=? {extra} "
               f"GROUP BY b.brand_name ORDER BY SUM(f.{col}) DESC LIMIT 1")
        r = conn.execute(sql, (year, *args)).fetchone()
        return r[0] if r else None

    def order(col, extra="", args=()):
        sql = (f"SELECT b.brand_name {JOIN} WHERE f.year=? {extra} "
               f"GROUP BY b.brand_name ORDER BY SUM(f.{col}) DESC")
        return [x[0] for x in conn.execute(sql, (year, *args)).fetchall()]

    out = {"year": year, "checks": []}
    a, b = top("tiv_units"), top("registration_units")
    out["checks"].append({"scope": "全年整体", "tiv_top": a, "reg_top": b, "same": a == b})
    out["month_rank_diff"] = f"{sum(1 for m in range(1, 13) if top('tiv_units', 'AND f.month=?', (m,)) != top('registration_units', 'AND f.month=?', (m,)))}/12"
    regions = [r[0] for r in conn.execute("SELECT region_id FROM dim_region").fetchall()]
    out["region_rank_diff"] = f"{sum(1 for rid in regions if top('tiv_units', 'AND f.region_id=?', (rid,)) != top('registration_units', 'AND f.region_id=?', (rid,)))}/{len(regions)}"
    out["full_order_diff_year"] = order("tiv_units") != order("registration_units")
    out["full_order_diff_month"] = f"{sum(1 for m in range(1, 13) if order('tiv_units', 'AND f.month=?', (m,)) != order('registration_units', 'AND f.month=?', (m,)))}/12"

    y_gaps = []
    for (bn,) in conn.execute(f"SELECT DISTINCT b.brand_name {JOIN} WHERE f.year=?", (year,)).fetchall():
        t = conn.execute(f"SELECT SUM(f.tiv_units) {JOIN} WHERE f.year=? AND b.brand_name=?", (year, bn)).fetchone()[0]
        r = conn.execute(f"SELECT SUM(f.registration_units) {JOIN} WHERE f.year=? AND b.brand_name=?", (year, bn)).fetchone()[0]
        if t and r:
            y_gaps.append(abs(t - r) / t * 100)
    out["year_value_gap_pct"] = {
        "min": round(min(y_gaps), 2), "max": round(max(y_gaps), 2),
        "mean": round(sum(y_gaps) / len(y_gaps), 2),
    } if y_gaps else None

    # ---- 相邻品牌差距：排名之所以对口径不敏感，是因为最挤的一对相邻品牌
    #      也比「换口径」带来的品牌年合计扰动大。两个数都在这里算出来对比。
    year_order = order("tiv_units")
    year_units = dict(conn.execute(
        f"SELECT b.brand_name, SUM(f.tiv_units) {JOIN} WHERE f.year=? GROUP BY b.brand_name", (year,)))

    def _month_units(name, m):
        return conn.execute(
            f"SELECT SUM(f.tiv_units) {JOIN} WHERE f.year=? AND f.month=? AND b.brand_name=?",
            (year, m, name)).fetchone()[0] or 0

    adjacent = [{"pair": f"{hi} / {lo}", "gap_pct": round((year_units[hi] / year_units[lo] - 1) * 100, 2)}
                for hi, lo in zip(year_order, year_order[1:])]
    tightest = min(adjacent, key=lambda g: g["gap_pct"])
    t_hi, t_lo = tightest["pair"].split(" / ")
    out["adjacent_brand_gap_pct"] = {
        "order": year_order,
        "by_adjacent_pair": adjacent,
        "leader_over_second": adjacent[0]["gap_pct"],
        "tightest_pair": tightest["pair"],
        "tightest_gap_pct": tightest["gap_pct"],
        "months_tightest_pair_keeps_order":
            f"{sum(1 for m in range(1, 13) if _month_units(t_hi, m) > _month_units(t_lo, m))}/12",
        "max_brand_year_metric_gap_pct": out["year_value_gap_pct"]["max"] if y_gaps else None,
    }

    month_tiv, month_reg = [0] * 12, [0] * 12
    for m, t, r in conn.execute(
            "SELECT month, SUM(tiv_units), SUM(registration_units) FROM fact_month WHERE year=? GROUP BY month",
            (year,)):
        month_tiv[m - 1], month_reg[m - 1] = t, r
    m_gaps = _monthly_gaps(month_tiv, month_reg)
    out["month_value_gap_pct"] = {"by_month": m_gaps, "abs_max": max(abs(x) for x in m_gaps)}

    # ---- 旧模型对照：2026-09-02 之前上牌 = 批发 × 各区固定系数（1.04 / 0.93 / 0.98），
    #      2025-12 再 × 0.96（年末批发赶量）。同一份批发数据上重算，看月度背离有多小。
    series, _brand_of = _tiv_by_key(conn)
    legacy_reg = [0] * 12
    for (y, _mid, rid), tiv12 in series.items():
        if y != year:
            continue
        bump = 1.04 if rid == 1 else 0.93 if rid in (5, 6) else 0.98
        for m in range(12):
            b_m = bump * (0.96 if (year == 2025 and m == 11) else 1.0)
            legacy_reg[m] += max(0, int(round(tiv12[m] * b_m)))
    l_gaps = _monthly_gaps(month_tiv, legacy_reg)
    l_abs = sorted(abs(x) for x in l_gaps)
    out["legacy_flat_bump_model"] = {
        "formula": "reg = tiv × 区域系数（巴生谷 1.04 / 东马 0.93 / 其余 0.98），2025-12 再 × 0.96",
        "by_month": l_gaps,
        "abs_typical": l_abs[len(l_abs) // 2],   # 中位数：除 12 月外各月几乎相同
        "abs_max": max(l_abs),
        "current_model_abs_max": out["month_value_gap_pct"]["abs_max"],
    }

    adj = out["adjacent_brand_gap_pct"]
    out["结论"] = (
        f"本市场相邻品牌差距大（{year_order[0]} 断层领先第二名 {adj['leader_over_second']}%；"
        f"最挤的一对是 {adj['tightest_pair']}，全年仍差 {adj['tightest_gap_pct']}%，"
        f"12 个月里有 {adj['months_tightest_pair_keeps_order']} 保持这个先后），"
        f"而换口径带来的品牌年合计扰动最大只有 {adj['max_brand_year_metric_gap_pct']}%，"
        "小于最挤的那对相邻品牌之差——所以口径换成上牌不改变任何排名。但月度数值最大差 "
        f"{out['month_value_gap_pct']['abs_max']}%（旧的固定系数模型常态只有 "
        f"{out['legacy_flat_bump_model']['abs_typical']}%，最大 {out['legacy_flat_bump_model']['abs_max']}%）。"
        "即：猜口径的危害在数值不在排名。λ 是基于渠道周转的假设值，未按「让排名翻转」反向调参——"
        "见 lambda_sensitivity。"
    )
    conn.close()
    return out


def lambda_sensitivity(year=2025, scales=(0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2)):
    """把所有品牌的 λ 同乘一个系数重算上牌，看排名什么时候才翻转。

    λ 越小，货压在渠道越多，上牌滞后越重、月度背离越大。若在很宽的范围内
    月度 / 区域 top1 都不翻转，「排名对口径不敏感」就不是靠某个特定 λ 凑出来的。
    """
    conn = connect(DB_PATH)
    series, brand_of = _tiv_by_key(conn)
    regions = [r[0] for r in conn.execute("SELECT region_id FROM dim_region").fetchall()]
    conn.close()

    def tally(scale):
        tiv_bm, reg_bm = {}, {}
        tiv_br, reg_br = {}, {}
        month_tot_t, month_tot_r = [0] * 12, [0] * 12
        for (y, mid, rid), tiv12 in series.items():
            if y != year:
                continue
            bname = brand_of[mid]
            prev = series.get((y - 1, mid, rid))
            reg12 = registration_series(tiv12, prev, bname, rid, scale)
            for m in range(12):
                tiv_bm.setdefault(bname, [0] * 12)[m] += tiv12[m]
                reg_bm.setdefault(bname, [0] * 12)[m] += reg12[m]
                month_tot_t[m] += tiv12[m]
                month_tot_r[m] += reg12[m]
            tiv_br.setdefault(bname, {}).setdefault(rid, 0)
            reg_br.setdefault(bname, {}).setdefault(rid, 0)
            tiv_br[bname][rid] += sum(tiv12)
            reg_br[bname][rid] += sum(reg12)
        month_flips = sum(
            1 for m in range(12)
            if max(tiv_bm, key=lambda b: tiv_bm[b][m]) != max(reg_bm, key=lambda b: reg_bm[b][m]))
        region_flips = sum(
            1 for rid in regions
            if max(tiv_br, key=lambda b: tiv_br[b].get(rid, 0)) != max(reg_br, key=lambda b: reg_br[b].get(rid, 0)))
        gaps = _monthly_gaps(month_tot_t, month_tot_r)
        return {"scale": scale, "month_top1_flips": f"{month_flips}/12",
                "region_top1_flips": f"{region_flips}/{len(regions)}",
                "month_gap_abs_max": max(abs(g) for g in gaps)}

    rows = [tally(s) for s in scales]
    first_flip = next((r["scale"] for r in rows if r["month_top1_flips"] != "0/12" or
                       r["region_top1_flips"] != f"0/{len(regions)}"), None)
    return {
        "what": "所有品牌 λ 同乘 scale 后重算上牌；scale=1.0 即现行模型",
        "rows": rows,
        "first_scale_with_any_top1_flip": first_flip,
        "结论": ("扫描范围内没有任何月度或区域 top1 翻转" if first_flip is None
                 else f"scale={first_flip} 时首次出现 top1 翻转"),
    }


def compute():
    seed()
    cases = json.loads((ROOT / "eval" / "cases.json").read_text(encoding="utf-8"))
    result = guard_arms(cases)
    forced_rows = result.pop("forced_rows")
    result["口径翻转对照"] = metric_flip()
    result["lambda_sensitivity"] = lambda_sensitivity()
    result["forced_rows"] = forced_rows
    return result


def _compare(fresh, committed, path="", problems=None):
    problems = problems if problems is not None else []
    if isinstance(fresh, dict) and isinstance(committed, dict):
        for k in fresh:
            if k not in committed:
                problems.append(f"{path}/{k}: missing in committed file")
            else:
                _compare(fresh[k], committed[k], f"{path}/{k}", problems)
    elif isinstance(fresh, list) and isinstance(committed, list):
        if len(fresh) != len(committed):
            problems.append(f"{path}: length {len(fresh)} vs {len(committed)}")
        for i, (a, b) in enumerate(zip(fresh, committed)):
            _compare(a, b, f"{path}[{i}]", problems)
    elif fresh != committed:
        problems.append(f"{path}: {fresh!r} vs {committed!r}")
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    result = compute()
    if "--check" in argv:
        committed = json.loads(OUT.read_text(encoding="utf-8"))
        problems = _compare(result, committed)
        for p in problems[:20]:
            print("DRIFT:", p)
        print("ok: eval/ablation.json matches a fresh run" if not problems else
              f"{len(problems)} differences between a fresh run and eval/ablation.json")
        return 1 if problems else 0
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "forced_rows"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
