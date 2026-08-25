# malaysia-auto-ask

仓：https://github.com/LUOaini1213/malaysia-auto-ask

马来西亚汽车市场 **问数演示**：自然语言 → 意图 → 白名单 SQL → 表。  
给 Data Agent 岗补 SQL / 库表 / 口径 / 评测，**不是** MAA 官方明细，**不是** 吉利业务。

品牌全年合计按公开报道锚定（2025 年 TIV 820,752；Perodua 359,904 等）。  
月 × 区域 × 车型是固定种子拆出来的演示数。TIV 和上牌是两列，允许对不上。

## 怎么跑

```powershell
cd 04_作品与代码/malaysia-auto-ask
python scripts/seed.py
python scripts/ask_cli.py "2025全年协会口径TIV哪家第一"
python scripts/eval.py
python scripts/serve.py
# 浏览器 http://127.0.0.1:8766
```

无第三方包。Python 3.10+，只用标准库 sqlite3。

## 库表

| 表 | 作用 |
|----|------|
| `dim_brand` | 品牌、国产/非国产 |
| `dim_model` | 车型、能源、价格带 |
| `dim_region` | 巴生谷 / 柔佛 / 槟城 / 霹雳 / 沙巴 / 砂拉越 / 其他 |
| `fact_month` | 年-月-车型-区域：`tiv_units`、`registration_units` |
| `metric_dict` | 指标口径、owner、版本 |

## 口径（问不清就停）

| 指标 | 含义 |
|------|------|
| TIV / 批发 | 协会风格批发。问「销量/卖得好」且没说上牌 → **停，问人** |
| 上牌 | 演示用的注册列，和 TIV 不是同一套数 |
| 份额 | 分子分母同一指标、同一筛选 |
| 国产车 | 只 Perodua + Proton，不是「马来西亚生产的都算」 |

模型不许拼 SQL。只能填白名单模板。每次回答带口径定义、owner、version、SQL。

## 评测（30 条，`eval/cases.json`）

本机最近一次：

| 指标 | 值 | 怎么算 |
|------|----|--------|
| 成功率 | **100%**（22/22） | 该出数的题，模板和结果对 |
| 准确率 | **100%**（22/22） | 模板 + 参数和金标一致 |
| 人工干预率 | **26.7%**（8/30） | 系统停下来问人的比例 |

8 条故意停：没指定 TIV/上牌、相对时间（上个月/今年）、华南、吉利当品牌、豪华车无定义、2026 年库没有。

```powershell
python scripts/eval.py
```

## 红线

- 不把本库写成 MAA/JPJ 原始数或吉利问数产品  
- 不把「填模板」写成生产 NL2SQL  
- 不做 RAG；词条在 `metric_dict` 里直接读  
- Proton 是国产车品牌；库里没有 Geely 品牌行  

公开锚点来源：MAA 2025 TIV 820,752；Perodua / Proton / Honda / Toyota / Mazda 等品牌年为公开报道。其余拆分是演示。
