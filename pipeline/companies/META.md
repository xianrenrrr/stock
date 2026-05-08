# META -- 综合提取 / All mentions across our research

_Aggregated from 18 mentions across 6 reports. Auto-generated; rerun via `python scripts/compress_dives_to_companies.py`._

---

## From tech_dive #37: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T02:09_

> ## 3. Demand magnitude / 需求量级
2026E hyperscaler AI capex: MSFT $80–100B, META $60–75B, GOOG $75–85B, AMZN $100–110B, ORCL $25–30B, xAI $15–25B = **$355–425B aggregate**. HBM TAM: 2024 $16B → 2025 ~$35–40B → **2026E ~$60–80B** → 2027E $90–110B. HBM = 40–45% of DRAM revenue by 2026 (vs 8% in 2023). Cube units 2026E: ~24–28M.

> **A. Hyperscaler capex pulled >15% YoY** — two of {MSFT, META, GOOG, AMZN} cut FY26 capex >15% before 2026-08 + NVIDIA DC seq. decline >10%. Verifiable via 10-Qs/calls. Breaks the demand pillar.

## From tech_dive #38: 技术深挖: TSMC CoWoS-L vs Intel EMIB vs Samsung X-Cube: 2.5D adv...
_2026-05-07T02:24_

> 4. **Customer concentration risk** — oligopsony every layer. NVIDIA was ~60–65% of CoWoS in 2024, normalizing to ~50% (NVIDIA+AMD ~70–75% of CoWoS-L 2026); 6 end-buyers (MSFT/META/GOOG/AMZN/ORCL/xAI) dominate; TSMC ~90% of leading-edge packaging; Ibiden+Unimicron+Shinko ~65% of giant substrate; ASMPT+Hanmi ~80% of TCB; **Ajinomoto ~100% on ABF film — single most concentrated chokepoint in the entire chain.** Asymmetric two-way dependency illustrated by the 2024-Q4 → 2025-Q1 CoWoS reallocation episode.

## From tech_dive #40: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T02:34_

> ```
Hyperscaler capex pool   (MSFT / META / GOOG / AMZN / Oracle / xAI)
       │  ~$50–80k per Blackwell-Ultra / Rubin / MI400 board

> **At the hyperscaler layer (end demand):**
- **Top 4 (MSFT + META + GOOG + AMZN) = 75–80%** of GPU-board demand pulling HBM through.
- Adding Oracle + xAI + Tesla = **88–92%**.

> - **Observable signal**: MSFT, META, GOOG, or AMZN explicitly lowers AI/data-center capex guidance by 15%+ on a quarterly call, OR delays a major build-out (Stargate, Saudi PIF, Memphis cluster) by ≥6 months. Specific phrases to watch: *"capex normalizing,"* *"deferring next phase,"* *"reassessing utilization."*
- **Why it falsifies**: The HBM TAM math ($60–80B in 2026E) is anchored to $355–425B aggregate hyperscaler capex. A 15% cut at any one of the Top 4 is **~$10–15B of GPU board demand removed**, propagating to **~$3–5B less HBM demand** at current mix. NVIDIA's Q/Q sequential growth flips negative; SK hynix HBM revenue plan misses by ≥10%.

> 中文:**追到买单的人** — 不是看 NVIDIA,要看 MSFT/META/GOOG/AMZN 的 capex 是否真砍。任一家砍 15%+ → HBM TAM 缺口 $3–5B,链条所有名字下修。

## From tech_dive #41: 技术深挖: TSMC CoWoS-L vs Intel EMIB vs Samsung X-Cube: 2.5D adv...
_2026-05-07T02:44_

> ```
Hyperscaler / OEM (MSFT, META, GOOG, AMZN, ORCL, xAI, Tesla, sovereign clouds)
   │  pays $30k–$45k per Blackwell B200, $60k–$80k per GB200 NVL72 slot

> **中文.** 链条 7 段:**云厂/OEM(MSFT/META/GOOG/AMZN/Oracle/xAI/Tesla/主权云)→ 加速器设计公司(NVDA/AMD/Broadcom-定制 ASIC/Marvell-定制 ASIC)→ 晶圆 + 封装代工(TSMC、Intel Foundry、Samsung Foundry)→ OSAT 组装与最终测试(Amkor、ASE/SPIL、KYEC)→ HBM 供应商(SK 海力士第一、Micron 第二、三星追赶)→ ABF 有机基板(Ibiden ~30%、Unimicron ~20%、Nan Ya PCB、Shinko、AT&S、Kinsus)→ 工具/耗材(ASML、AMAT、TEL、LRCX、Disco、BESI、ASMPT、Hanmi、Camtek、Onto、信越/住友 Bakelite)。**

> - **CoWoS-S 全硅 interposer vs. CoWoS-L 桥 — 拐点 ~3× reticle / ~2500 mm² interposer 面积**。低于这条线 S 划得来,高于这条线 L 显著便宜且良率更好(没有易碎的大 Si 板)。Blackwell、Rubin、MI350+、TPU v6+ 全部迁 L,就是这条逻辑。
- **EMIB vs. CoWoS — 单位成本 EMIB 便宜 $1.5-3k/套,但卡在产能与客户结构**。真正拐点是 **CoWoS 配额不够时,愿意二源到 Intel 18A 的 hyperscaler 拿 EMIB 换早交付 + ~10-15% 封装成本下降**。MSFT/META/AWS 2025-2026 在定制 ASIC 上评估这条路径。

> - **End-buyer concentration on the demand side:** Top-5 hyperscalers (MSFT, META, GOOG, AMZN, ORCL) buy **~70-75% of NVDA datacenter** in 2025 (consensus). Adding xAI + Tesla + Apple + sovereigns (UAE G42, Saudi HUMAIN, Korea, Japan METI-funded) brings top-15 to **~95%**. **An AI capex pause from 3 of those 5 hyperscalers cracks the entire 2.5D revenue stack within 2 quarters.**

> - **工具** — ASML EUV 单源;Disco 在先进薄圆片切割 >80%;BESI + ASMPT 平分 hybrid bonding;Hanmi + Shinkawa 占 TCB。
- **需求端** — 前五云厂(MSFT/META/GOOG/AMZN/ORCL)买走 **~70-75%** NVDA 数据中心收入;加 xAI/Tesla/Apple/主权云,前 15 占 ~95%。**5 家中有 3 家暂停 AI capex,2 季度内整条 2.5D 链子收入塌方。**

> **EN.** The demand-side anchor is **~$330–360B 2025 hyperscaler capex** with continued growth in 2026. **Falsifier:** any one of MSFT, META, GOOG, AMZN cuts FY2026 (or revises FY2026 mid-year) AI capex guide **by ≥20%** at quarterly earnings — e.g., MSFT FY2026 lowered from ~$95B to <$76B, or META 2026 from ~$72B to <$58B, with management citing "training-cluster ROI re-evaluation" or "model-quality plateau." **One** cut from **one** of the top 4 = warning. **Two** cuts from **two** of the top 4 within a single quarter = the consensus AI capex curve breaks, NVDA datacenter forecasts get repriced, CoWoS-L premium evaporates first because it sits at the leading edge.

> **中文.** 需求侧锚是 2025 头部云厂 capex 合计 ~$3,300–3,600 亿、2026 继续增长。**证伪:** MSFT/META/GOOG/AMZN 中**任一家**在季度法说会上将 FY2026 AI 资本开支指引**下修 ≥20%**(MSFT 由 ~$950 亿降至 <$760 亿、META 由 ~$720 亿降至 <$580 亿等),且口径是"训练集群 ROI 重估"或"模型质量平台期"。一家下修 = 警报;**同一季度有两家下修** = 共识 AI 资本开支曲线断裂,NVDA 数据中心重估,CoWoS-L 溢价**第一个蒸发**(它处在最前沿、对边际需求最敏感)。

## From tech_dive #46: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T04:35_

> ```
Hyperscalers (MSFT / META / GOOG / AMZN / ORCL)
        │  $30k–40k per accelerator

> - **2025 hyperscaler AI capex**: MSFT ~$80B, META ~$65B, GOOG ~$75B, AMZN ~$100B, ORCL ~$25B — **$345B combined**, of which ~40–50% is AI infra, ~25% of that is GPU systems
- **HBM bit shipment**: 2024 ~12B Gb-equivalent → 2025 ~24B Gb → **2026 ~45B Gb** (TrendForce, Apr-2025); HBM revenue **$15B (2024) → $35B (2025) → $55–65B (2026)**

> ### 3. **超大规模厂商 AI capex 砍单：2026 H2 任一家 QoQ 削减 >15%**
- **观测点**: MSFT / META / GOOG / AMZN 中任意一家在 **2026 Q3 或 Q4 财报**指引 capex **环比 -15% 以上**且明确归因于 "AI infra rationalization / GPU utilization shortfall"，或 Nvidia 季报 data-center revenue **QoQ -10% 以上**。
- **为什么是证伪**: HBM4 5M stacks/yr 的 2027 假设（Round 2）建立在 Rubin + MI400 + ASIC 共 ~900k 加速器之上 —— 任何一家超大客户砍单 30% 等于 ~150–200k 加速器 = 1.5–2.0M HBM4 stacks 蒸发，整条链定价重设。

## From tech_dive #50: 技术深挖: Foundation models for protein structure prediction pos...
_2026-05-07T05:01_

> 中文:三层 TAM —— 已经"落到合同上"的 AI 制药里程碑总和到 2024 年底 **>$60B**,但**实际收到的上游现金累计仅 ~$3.5B**(年化新增上游 $1.0–1.5B/yr);可触达的大药企研发预算 = top-20 大药企 R&D 共 $180B/yr × 25% 发现/临床前份额 × 10–20% AI 渗透率 = **$4.5–9B/yr 是 Tier-1 整层的天花板**;再上面是超大规模云厂 2025 AI capex(MSFT $80B+/META $60–65B/GOOG $75B/AMZN $100B+, 合计 **$315–325B**)与 NVIDIA Healthcare ~$1B/yr。结论:**AI 药物发现是 NVIDIA 数据中心收入的 ~1%**,是大药企总研发的 ~5%,**对 NVIDIA/超大规模云厂仅是边际生意,对传统 CADD/Schrödinger 是范式级机会**。
