# -*- coding: utf-8 -*-
"""Rule parser. Ambiguous 销量/卖得好 stops for a human. No free SQL."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

BRANDS = {
    "perodua": 1,
    "proton": 2,
    "honda": 3,
    "toyota": 4,
    "mazda": 5,
    "byd": 6,
    "chery": 7,
    "奇瑞": 7,
    "宝腾": 2,
    "丰田": 4,
    "本田": 3,
}

REGIONS = {
    "klang valley": 1,
    "kl": 1,
    "selangor": 1,
    "巴生谷": 1,
    "吉隆坡": 1,
    "雪兰莪": 1,
    "johor": 2,
    "柔佛": 2,
    "新山": 2,
    "penang": 3,
    "槟城": 3,
    "perak": 4,
    "霹雳": 4,
    "sabah": 5,
    "沙巴": 5,
    "sarawak": 6,
    "砂拉越": 6,
    "砂越": 6,
}

ENERGY = {"ev": "ev", "电动": "ev", "纯电": "ev", "hybrid": "hybrid", "混动": "hybrid"}


@dataclass
class Intent:
    task: str | None = None
    metric: str | None = None
    year: int | None = None
    month: int | None = None
    brand_id: int | None = None
    region_id: int | None = None
    energy: str | None = None
    origin: str | None = None
    hitl: bool = False
    hitl_reason: str = ""
    notes: list[str] = field(default_factory=list)

    def params(self) -> dict:
        return {
            "year": self.year,
            "month": self.month,
            "brand_id": self.brand_id,
            "region_id": self.region_id,
            "energy": self.energy,
            "origin": self.origin,
        }


def parse(question: str) -> Intent:
    q = question.strip()
    low = q.lower()
    intent = Intent()

    if re.search(r"华南|华东|华北|吉利(?!.*proton)|geely(?!.*proton)", q, re.I):
        intent.hitl = True
        intent.hitl_reason = "问题里的市场或品牌不在本库（马来西亚 TIV 演示）。吉利不是本库品牌行；Proton 是国产车品牌。"
        return intent
    if re.search(r"豪华|luxury|最近怎么样|帮我看看", q, re.I):
        intent.hitl = True
        intent.hitl_reason = "「豪华/最近怎么样」没有口径。请指定年份、指标（TIV 还是上牌）和品牌或区域。"
        return intent
    if re.search(r"上个月|今年|this year|last month", low):
        intent.hitl = True
        intent.hitl_reason = "库只到 2025-12。请写成「2025年12月」或「2025全年」，不要用相对时间。"
        return intent

    doc_q = bool(
        re.search(
            r"口径|定义|什么意思|怎么算|怎么定义|从哪[来张]|哪张表|哪一层|"
            r"血缘|溯源|有什么区别|还是上牌|还是tiv|owner|版本|"
            r"数仓|分层|\bods\b|\bdwd\b|\bads\b|几层",
            low,
        )
    )
    num_q = bool(
        re.search(r"哪家|第一|排名|多少|总量|合计|趋势|各月|各区域|top|how many|volume", low)
    )
    if doc_q and not num_q:
        intent.task = "retrieve"
        has_reg = bool(re.search(r"上牌|注册|jpj|registration", low))
        has_tiv = "tiv" in low or bool(re.search(r"批发|协会口径", low))
        if has_reg and not has_tiv:
            intent.metric = "registration"
            intent.notes.append("metric=registration")
        elif has_tiv and not has_reg:
            intent.metric = "tiv"
            intent.notes.append("metric=tiv")
        elif re.search(r"份额|市占|share", low):
            intent.metric = "share"
        elif re.search(r"国产|national", low):
            intent.metric = "national"
        intent.notes.append("mode=retrieve")
        return intent

    if re.search(r"上牌|注册|jpj|registration", low):
        intent.metric = "registration"
        intent.notes.append("metric=registration")
    elif "tiv" in low or re.search(r"批发|协会口径", low):
        intent.metric = "tiv"
        intent.notes.append("metric=tiv")
    elif re.search(r"卖得|卖的好|谁最(好|猛|强)|销量|sales", low):
        intent.hitl = True
        intent.hitl_reason = "「销量/卖得好」在本库有两套数：TIV（批发）和上牌。请指定用哪一个。"
        return intent

    y = re.search(r"(20\d{2})", q)
    if y:
        intent.year = int(y.group(1))
        if intent.year not in (2024, 2025):
            intent.hitl = True
            intent.hitl_reason = "库只有 2024 和 2025。"
            return intent
    m = re.search(r"(1[0-2]|[1-9])\s*月|[-/](1[0-2]|0?[1-9])\b|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec", low)
    MONTHS = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    if m:
        token = m.group(0)
        num = re.search(r"\d+", token)
        if num:
            intent.month = int(num.group())
        else:
            for k, v in MONTHS.items():
                if k in token:
                    intent.month = v
    if re.search(r"全年|年度|full year|year total", low):
        intent.month = None
        intent.notes.append("full year")

    if intent.year is None:
        intent.hitl = True
        intent.hitl_reason = "请指定 2024 或 2025。"
        return intent

    for key, bid in BRANDS.items():
        if key in low:
            intent.brand_id = bid
            break
    for key, rid in REGIONS.items():
        if key in low:
            intent.region_id = rid
            break
    for key, ev in ENERGY.items():
        if key in low:
            intent.energy = ev
            break
    non = bool(re.search(r"非国产|non-national|non national", low))
    nat = bool(re.search(r"(^|[^非])国产|national marque|national car", q))
    if nat and non:
        intent.origin = None
    elif nat:
        intent.origin = "national"
    elif non:
        intent.origin = "non_national"

    if re.search(r"同比|yoy", low):
        intent.task = "yoy_brand"
    elif re.search(r"份额|市占|share", low):
        intent.task = "share"
    elif nat and non:
        intent.task = "origin_split"
    elif re.search(r"趋势|各月|monthly|by month", low):
        intent.task = "month_trend"
    elif re.search(r"各区域|哪个州|区域排名|by region", low):
        intent.task = "region_rank"
    elif re.search(r"车型|model|bezza|myvi|saga|x50", low):
        intent.task = "model_rank"
    elif intent.brand_id and re.search(r"多少|总量|合计|how many|volume", low):
        intent.task = "brand_total"
    elif re.search(r"排名|谁|哪家|top|first|第一", q):
        if re.search(r"车型|model", low):
            intent.task = "model_rank"
        else:
            intent.task = "brand_rank"
    else:
        if intent.brand_id:
            intent.task = "brand_total"
        else:
            intent.task = "brand_rank"

    if intent.metric is None:
        intent.hitl = True
        intent.hitl_reason = "请指定 TIV/批发 或 上牌/注册量。"
        return intent

    return intent


def to_dict(intent: Intent) -> dict:
    d = asdict(intent)
    d["params"] = intent.params()
    return d
