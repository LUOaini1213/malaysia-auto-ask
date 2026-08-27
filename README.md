# malaysia-auto-ask

仓：https://github.com/LUOaini1213/malaysia-auto-ask

马来西亚汽车市场 **问数演示**：自然语言 → 意图 → 白名单 SQL → 表。  
口径问句走 **词重叠检索**（`口径.md` + `metric_dict` + 血缘节点），不是向量 RAG。  
给 Data Agent 岗补 SQL / 分层 / 血缘 / 口径 / 评测。

**不是** MAA 官方明细，**不是** 吉利问数 / 星睿 / Eva，**不是** 企业 Atlas。

品牌全年合计按公开报道锚定（2025 年 TIV 820,752；Perodua 359,904 等）。  
月 × 区域 × 车型是固定种子拆出来的演示数。TIV 和上牌是两列，允许对不上。

## 怎么跑

```powershell
cd 04_作品与代码/malaysia-auto-ask
python scripts/seed.py
python scripts/ask_cli.py "2025全年协会口径TIV哪家第一"
python scripts/ask_cli.py "TIV和上牌有什么区别"
python scripts/ask_cli.py "上牌数从哪张表来"
python scripts/eval.py
python scripts/serve.py
# 浏览器 http://127.0.0.1:8766
# 海外一线工作台 http://127.0.0.1:8766/desk
```

无第三方包。Python 3.10+，只用标准库 sqlite3。

## 演示分层

| 层 | 表 | 作用 |
|----|----|------|
| ODS | `ods_brand_year_anchor` | 公开报道的品牌年 TIV 锚 |
| DIM | `dim_brand` / `dim_model` / `dim_region` | 品牌、车型、区域 |
| DWD | `fact_month` | 年-月-车型-区域：`tiv_units`、`registration_units` |
| ADS | `ads_brand_year` / `ads_brand_month` | 品牌年 / 月汇总 |
| 指标 | `metric_dict` | 口径、owner、版本 |
| 血缘 | `lineage_node` / `lineage_edge` | 表级边，可从指标走回 ODS |

全年、无区域、无能源的品牌合计走 ADS；带月 / 区域 / 能源 / 车型走 DWD。

## 口径（问不清就停）

| 指标 | 含义 |
|------|------|
| TIV / 批发 | 协会风格批发。问「销量/卖得好」且没说上牌 → **停，问人** |
| 上牌 | 演示用的注册列，和 TIV 不是同一套数 |
| 份额 | 分子分母同一指标、同一筛选 |
| 国产车 | 只 Perodua + Proton，不是「马来西亚生产的都算」 |

模型不许拼 SQL。只能填白名单模板。每次出数带口径定义、owner、version、SQL、表级血缘。  
「口径 / 从哪来 / 哪张表」不跑 SQL，返回检索片段和血缘路径。

## 海外一线工作台（`/desk`）

看板卡片 + 问数 + 「给海外同事的说明草稿」。草稿默认不能复制，勾选确认后才能复制。  
产品说明：`docs/产品PRD.md`、`docs/区域产品定义.md`。

不是智能外呼、不是客服、不是座舱 / RoboOS。

## 评测

问数 30 条（`eval/cases.json`）+ 口径检索 8 条（`eval/retrieve_cases.json`）。本机最近一次：

| 指标 | 值 | 怎么算 |
|------|----|--------|
| 成功率 | **100%**（22/22） | 该出数的题，模板和结果对 |
| 准确率 | **100%**（22/22） | 模板 + 参数和金标一致 |
| 人工干预率 | **26.7%**（8/30） | 系统停下来问人的比例 |
| 口径检索 | **8/8** | 命中正确文档或血缘节点（词重叠） |

8 条故意停：没指定 TIV/上牌、相对时间（上个月/今年）、华南、吉利当品牌、豪华车无定义、2026 年库没有。

```powershell
python scripts/eval.py
```

## 红线

- 不把本库写成 MAA/JPJ 原始数或吉利问数产品
- 不把「填模板」写成生产 NL2SQL
- 不把词重叠检索写成向量 RAG / 企业知识库
- 不把 `lineage_edge` 写成企业数仓血缘平台
- 不把 `/desk` 写成外呼、客服或吉利一线工具
- Proton 是国产车品牌；库里没有 Geely 品牌行

公开锚点来源：MAA 2025 TIV 820,752；Perodua / Proton / Honda / Toyota / Mazda 等品牌年为公开报道。其余拆分是演示。
