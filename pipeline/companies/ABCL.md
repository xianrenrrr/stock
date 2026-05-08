# ABCL -- 综合提取 / All mentions across our research

_Aggregated from 114 mentions across 3 reports. Auto-generated; rerun via `python scripts/compress_dives_to_companies.py`._

---

## From tech_dive #43: 技术深挖: AI antibody discovery commercial inflection: AbCellera...
_2026-05-07T03:10_

> # 技术深挖 / Tech deep-dive: AI antibody discovery commercial inflection: AbCellera (ABCL) + Recursion (RXRX) + Schrödinger (SDGR) -- which platform has the cleanest first-in-class IND from AI design, what's the validation evidence, and how to size the pre-clinical pipeline

> # Round 1 / 第一轮 — Technology Closed Loop / 技术闭环
**Topic:** AI antibody discovery — ABCL + RXRX + SDGR
**Date:** 2026-05-06

> - **Sequence–structure co-design (ABCL 主战场).** 输入抗原结构 (AlphaFold2/3 预测或 cryo-EM),用 inverse-folding 模型 (ESM-IF, ProteinMPNN) 或 diffusion 生成模型 (RFdiffusion, Chroma) 直接输出 CDR 序列;再用 ESM-2/3 这类蛋白语言模型做亲和力 + developability 二次评分。ABCL 的差异化是把生成模型挂到自家 **Beacon 微流控单 B 细胞筛选 + Trianni 人源化小鼠免疫库** 上,即 "AI 排序 → optofluidic 单细胞 readout" 的闭环,而不是纯 in-silico de novo。
- **Phenomics + foundation model (RXRX 主战场).** Cell Painting 染色 → 高内涵成像 → 数百万 perturbation × cell line 矩阵 → 用 MolE / Phenom-Beta 自监督模型把图像嵌入到 ~1024 维表征空间,再用 contrastive learning 找 "这个化合物/基因敲低的表型 = 那个已知药物的表型" 的 map-of-biology。底层算力是 NVIDIA H100 集群 BioHive-2 (~2 EFLOPS FP8)。这条线**不是抗体专属**,而是从表型反推靶点 + 苗头化合物。

> 所以本 dive 的"老 incumbent"按平台对应是: **ABCL/Generate/Absci → 替代 hybridoma + phage display**;**SDGR → 替代 HTS + 经典 SBDD**;**RXRX → 替代 target-first reductionist drug discovery (本身是个 paradigm shift,不仅是工艺替换)**。

> - **Time to lead.** ABCL 公开数据:疫情期间 LY-CoV555 (bamlanivimab) 从抗原序列到 IND 候选 **~90 天**,经典 hybridoma 同一里程碑 ~12 个月,**~4× 加速**。
- **Hit rate per screening unit.** Absci 2023 ASH 数据:zero-shot 生成的 anti-HER2 抗体里 **~60% 在首轮即为 binder** (KD < 100 nM),phage display 首轮 panning 后 binder 富集 < 1%,**约 60–100× 命中率**。

> - **Hit rate per screening unit.** Absci 2023 ASH 数据:zero-shot 生成的 anti-HER2 抗体里 **~60% 在首轮即为 binder** (KD < 100 nM),phage display 首轮 panning 后 binder 富集 < 1%,**约 60–100× 命中率**。
- **Epitope coverage.** Single-B-cell + ML 排序 (ABCL Celium) 报告对同一抗原能拿到 **>10 个独立 epitope bin** 的 panel,phage 文库通常富集到 2–3 个 dominant epitope。这个指标对 bispecific / 病毒逃逸应用最关键。
- **Developability up-front.** 训练好的 liability 预测器 (PTM 位点、聚集、polyspecificity、CMC) 把候选过滤前置,GMP 后期 attrition 报告下降 **~30–50%** (Adimab vs ABCL 公开会议数据,口径不一致需谨慎)。

> - **Epitope coverage.** Single-B-cell + ML 排序 (ABCL Celium) 报告对同一抗原能拿到 **>10 个独立 epitope bin** 的 panel,phage 文库通常富集到 2–3 个 dominant epitope。这个指标对 bispecific / 病毒逃逸应用最关键。
- **Developability up-front.** 训练好的 liability 预测器 (PTM 位点、聚集、polyspecificity、CMC) 把候选过滤前置,GMP 后期 attrition 报告下降 **~30–50%** (Adimab vs ABCL 公开会议数据,口径不一致需谨慎)。
- **Cost per de-risked lead.** SDGR 在 Nimbus TYK2 项目 (NDI-034858) 公开:用 FEP+ 替代部分湿实验合成,合成–评估化合物数 **~10× 下降**,Takeda 2023 年以 **$4 B 上限** 收购该资产,反向定价了平台节约的开发成本。

> - **数据 moat 假象.** Recursion 宣称 ~50 PB 表型数据,但 Cell Painting 信号 SNR 在跨批次/跨实验室时 effect size 会缩水 ~3–5×;模型在自家数据 work,在外部 OOD 数据集 (JUMP-CP) 上 performance drop 报告 ~20–40%。
- **Regulatory novelty 风险.** FDA 目前没有 "AI-designed therapeutic" 的专门 guidance;CDER 在 2024 RFI 里要求披露训练数据 + model versioning + 性能漂移监控,实操上对 SDGR/ABCL 已商业化的 hybrid 流程影响小,但对纯 de-novo (Generate/Absci) 的 IND 包审稿周期可能 +6–12 个月。

> - **bamlanivimab / LY-CoV555 (ABCL × Eli Lilly).** 2020-11-09 FDA EUA,**首个 ML/AI-augmented 流程发现的获批抗体**;ABCL 用 Beacon + Celium 在 ~90 天内从 convalescent B cell 中筛出。Lilly 累计交付 >2 M 剂,EUA 在 Omicron 时代撤回但作为流程验证仍是 reference case (10-K, 2021-03)。
- **ABCL 合作管线规模.** ABCL 2024 10-K: **>110 partner-initiated 项目**,**13 个 IND-stage 分子在合作方手中**,合作方包括 Lilly、Pfizer、Merck KGaA、Regeneron、Moderna。其中第一个 ABCL 自有共同开发 (T20 program) 2025 年进入 IND-enabling。

> - **bamlanivimab / LY-CoV555 (ABCL × Eli Lilly).** 2020-11-09 FDA EUA,**首个 ML/AI-augmented 流程发现的获批抗体**;ABCL 用 Beacon + Celium 在 ~90 天内从 convalescent B cell 中筛出。Lilly 累计交付 >2 M 剂,EUA 在 Omicron 时代撤回但作为流程验证仍是 reference case (10-K, 2021-03)。
- **ABCL 合作管线规模.** ABCL 2024 10-K: **>110 partner-initiated 项目**,**13 个 IND-stage 分子在合作方手中**,合作方包括 Lilly、Pfizer、Merck KGaA、Regeneron、Moderna。其中第一个 ABCL 自有共同开发 (T20 program) 2025 年进入 IND-enabling。
- **Schrödinger × Nimbus TYK2.** NDI-034858 (oral allosteric TYK2,后名 zasocitinib) 的 hit-to-lead 由 SDGR FEP+ 主导。**2022-12 Takeda 以 $4 B upfront + earn-outs 收购该资产**;Phase 2b psoriasis 数据 (PASI 75 ~67% at 15 mg) 公布于 2022 EADV。这是迄今 **AI/物理模拟驱动药物发现获得 commercial 验证的最大单笔交易**。

> **Round 1 闭合判断:** 技术层面三家差异比"AI drug discovery"这个 umbrella 词暗示的大得多 — ABCL 是 **wet-AI hybrid (binder discovery)**,SDGR 是 **physics + ML (affinity optimization)**,RXRX 是 **phenomics map-of-biology (target ID)**。后续 round 评估"first-in-class IND from AI design"时必须按各自定义打分,不能用同一把尺。**最干净的"AI-designed first-in-class IND"候选应优先看 SDGR 自有管线 (SGR-1505/2921/3515) 和 ABCL 即将进入 IND 的 T20**;RXRX 的临床资产更接近 repurposing,**不是 round 命题想要的"AI 设计的新分子"**。

> # Round 2 / 第二轮 — Commercial Closed Loop / 商业闭环
**Topic:** AI antibody discovery — ABCL + RXRX + SDGR
**Date:** 2026-05-06

> ### ABCL chain (binder discovery as a service / 抗体发现外包)
```

> ▼
ABCelleraBiologics (ABCL)
   │  ⇣ upstream COGS

> Bruker (former Berkeley Lights) — Beacon optofluidic 仪器 + 耗材
Trianni, Inc. (ABCL 2020 收购) — 人源化转基因小鼠免疫
AWS / on-prem GPU — ESM/AlphaFold inference

> ```
**Key point / 关键点:** ABCL **不卖抗体药**,卖的是 **discovery-stage IP + milestone tail**。2024 财年 license-revenue 部分仅 $24.6 M (10-K),但 royalty-bearing 项目 (~110+ partner-initiated, 13 个 IND-stage) 是真正的 "deferred 收入炸药包"。

> ### ABCL: Cost-per-validated-lead (CPVL) / 单条验证 lead 成本
- **Incumbent (Adimab/Abzena 等纯 phage display):** 业内公开 benchmark ~$1.5–3 M / program 拿 1–3 个 lead 序列 → CPVL **~$0.5–1 M**。

> - **Incumbent (Adimab/Abzena 等纯 phage display):** 业内公开 benchmark ~$1.5–3 M / program 拿 1–3 个 lead 序列 → CPVL **~$0.5–1 M**。
- **ABCL Beacon + AI 排序流程:** 单 program 内部成本 (人 + 耗材 + 算力) 估 ~$0.8–1.2 M,但同一 program 可输出 **>10 epitope bins × 5–10 binders/bin** → CPVL 可压到 **~$15–50 K**,理论 **~10–30× 改善**。
- **跨越点已发生:** 对**非膜蛋白 / 已知结构靶点**,2021 年起 ABCL 已经过线 (即合作方愿意按更高费率付,因为下游 attrition 减少)。**未跨越:** GPCR、ion-channel 复合 epitope,因为结构数据稀缺导致 AI 排序的 prior 弱。

> - **ABCL Beacon + AI 排序流程:** 单 program 内部成本 (人 + 耗材 + 算力) 估 ~$0.8–1.2 M,但同一 program 可输出 **>10 epitope bins × 5–10 binders/bin** → CPVL 可压到 **~$15–50 K**,理论 **~10–30× 改善**。
- **跨越点已发生:** 对**非膜蛋白 / 已知结构靶点**,2021 年起 ABCL 已经过线 (即合作方愿意按更高费率付,因为下游 attrition 减少)。**未跨越:** GPCR、ion-channel 复合 epitope,因为结构数据稀缺导致 AI 排序的 prior 弱。
- **Break-even volume:** 当 partner 一年内做 ≥3 个 program 时,ABCL 流程在 effective $/lead 上完全压倒 phage display (公开 Lilly 内部对比,2022 JPM 演讲披露)。

> - **跨越点已发生:** 对**非膜蛋白 / 已知结构靶点**,2021 年起 ABCL 已经过线 (即合作方愿意按更高费率付,因为下游 attrition 减少)。**未跨越:** GPCR、ion-channel 复合 epitope,因为结构数据稀缺导致 AI 排序的 prior 弱。
- **Break-even volume:** 当 partner 一年内做 ≥3 个 program 时,ABCL 流程在 effective $/lead 上完全压倒 phage display (公开 Lilly 内部对比,2022 JPM 演讲披露)。

> ### Bottom-up shipment / contract volume
- **AI antibody 子赛道:** 全球年开 ~6,000–7,000 个 discovery 项目,其中抗体类 ~25% = ~1,700 个/年。AI 渗透 (含 ABCL/Adimab AI-augmented/Generate/Absci/EvolutionaryScale) ~12% → **~200 个 AI 主导抗体项目/年**,单价 $1.5–3 M → **~$400 M / yr program-fee 池**。**这是 ABCL 真正的"碗"**。
- **AI 软件 (FEP/MD/de-novo design):** Schrödinger + OpenEye + ChemAxon + Cresset 合计 ~$500 M / yr 软件订阅市场,SDGR 占 ~30%。

> ### ABCL
- **Top 3 partners (按累计 program 数 + milestone):** Eli Lilly, Pfizer, Merck KGaA. 历史 LY-CoV555 时期 Lilly 占 single-year revenue >70% (2021)。

> - **当前 (2024 10-K):** 110+ partner-initiated programs,前 5 大合作方贡献约 **45–55% 的 milestone-bearing program 价值**,但 **revenue 集中度已显著下降** (2024 单一最大客户 < 25%)。
- **Risk:** Lilly 内部 OmniAb (Ligand spinoff) 平台 + 自家 AI 团队的"in-source" 趋势 — 若 Lilly 减少外包,ABCL 的"明星账户"消失,但 partner 多样化已部分对冲。

> ### ABCL
- **Now (in-pocket):** 2024 全年收入 $38.7 M (research fees + 少量 milestone)。COVID 高峰期 (2021) 曾达 $377 M (LY-CoV555 royalty + sales),已**回归 baseline**。

> - **2025–2026:** 主要靠 13 个 IND-stage 合作分子推进到 Phase 1/2,milestone 单笔 $5–20 M,**预计年化 $50–80 M**。
- **2027–2029 (catalyst window):** 第一个非-COVID partner asset 进入 Phase 3 / 上市,**royalty stream 真正启动**;ABCL 自有 T20 program (2025 年 IND-enabling) 若顺利 2027 IND,**自有 royalty share 年化 $50–150 M**。
- **判断:** 2024–2026 是"现金消耗 + milestone trickle"窗口 (manageable burn,~$120–150 M / yr,cash $720 M+ runway 到 2028+),2027 是平台兑现的真正 inflection。

> - **已闭环且现金流可见:** **SDGR** > ABCL > RXRX。SDGR 是唯一同时具备 (a) recurring software revenue (b) 已变现的 platform-asset event (Nimbus) (c) 自有 IND 管线 三件套的标的。
- **Platform value vs. asset value 拆分 (sell-side 模型常见错误):**

> - **Platform value vs. asset value 拆分 (sell-side 模型常见错误):**
  - ABCL 当前市值 ($1.0–1.2 B 区间) 隐含的 **platform value ~50%、partner royalty NPV ~30%、cash & T20 自有管线 ~20%**。市场对 royalty NPV 给的 discount 偏狠 (~25%/yr),空间在 partner asset Phase 2/3 读出。
  - SDGR 当前市值 ($1.5–1.8 B 区间) 隐含 **software (DCF, ~5–6× sales) ~$900 M + Nimbus tail ~$200 M + 自有管线 option value ~$300–500 M**。下行支撑在软件部分,上行依赖 SGR-1505 读出。

> - **SDGR 自有 SGR-1505 (MALT1 inhibitor)** — 已在 Phase 1 NHL,2026 上半年读出 dose-escalation,**这是三家平台里最接近"AI 设计 → 自有 IND → 商业里程碑"完整闭环的资产**。
  - **ABCL T20** — 仍在 IND-enabling,验证窗口 2027+。
  - **RXRX REC-2282 / REC-617** — 不是新分子设计,**不符合 round 命题"AI-designed first-in-class"严格定义**。

> **Round 3 应聚焦:** 把上述 platform value vs. asset value 拆分映射到三家具体的可投资 catalyst calendar (2026–2028),并明确 sizing logic — 即在 pre-clinical pipeline 这一资产类别里,如何设定 ABCL : SDGR : RXRX 的相对权重 (含失败概率加权与单个 clinical readout 的 binary risk)。同时回答最初命题:**哪个平台的"first-in-class IND from AI design"最干净 + 有最强 validation evidence**。

> # Round 3 / 第三轮 — Public companies in the chain / 链条上的上市公司
**Topic:** AI antibody discovery — ABCL + RXRX + SDGR
**Date:** 2026-05-06

> ABCL/RXRX/SDGR 本身是 "integrator / platform" 层。**它们的上游不是一条链,而是三条几乎不重叠的链** (round 1/2 已建立),因此 round 3 的链条公司必须按 "为哪一家平台供货" 分别列。下表的颜色编码:🅰 = 主要供 ABCL 链,🅡 = RXRX 链,🅢 = SDGR 链,⚪ = 三家通吃。

> ### 2. **BRKR Bruker Corporation / NASDAQ** 🅰 (主供 ABCL 链)

> - **Specific SKU into this trend / 具体打入该趋势的产品:**
  - **Beacon optofluidic platform** (前身 Berkeley Lights,Bruker 2023-04 以 ~$57.8 M 现金 + ~$22 M 票据收购) — ABCL 的 "Celium" 全系工作流的硬件底座,**单细胞 binder discovery 的事实标准**。装机量 ~250+ 台 (Bruker 2024 10-K 引用 prior BLI 披露),~50% 客户是 ABCL 类 partner pharma + biotech。Beacon Optofluidic 单台 list price ~$1.5–2 M + 高 margin 耗材 (NanoPen™ chips, ~$5–10 K / run)。
  - **timsTOF Pro 2 mass spec** — 用于 antibody intact mass + peptide mapping,DSP 阶段不可少。

> - **Top competitors / 主要竞争者:** 10x Genomics (TXG,~$2 B 市值,Chromium + Visium Spatial,**单细胞 RNA-seq 主战场,不是 functional binder**) ; Sphere Fluidics (UK 私有,Cyto-Mine — 直接对标 Beacon,体量小);Mission Bio (US 私有);Standard BioTools (LAB,前 Fluidigm,~$0.5 B,衰退中)。
- **Vehicle quality / 标的质量:** **Diversified — Beacon 只占 6%**。BRKR 的真正基本面是 mass spec + NMR,与 AI antibody 的关联是"切线"而非"纯 play"。但 **Beacon 是 ABCL 平台不可替代的硬件 — 任何 ABCL 业务扩张直接拉动 Bruker BSI 部门**。Round 2 提到的 "ABCL 单 program $0.8–1.2 M 内部成本" 里,Beacon 耗材 + 折旧约占 ~$150–250 K,**Bruker 是 ABCL 真正的"上游税官"**。

> ### 4. **DHR Danaher Corporation / NYSE** ⚪ + 🅰 (Cytiva 子公司打 ABCL 链)

> - **Cytiva MabSelect SuRe / SuRe pcc / PrismA Protein A resin** — **mAb 纯化的全球事实垄断介质,~70% market share**。任何 AI 设计出的 antibody 进入 process dev 阶段都几乎绕不开 Cytiva resin。单 batch ~$50–200 K 介质成本,作为 "consumable annuity" 长期黏性极强。
  - **Cytiva ÄKTA chromatography systems + Xcellerex single-use bioreactors** — DSP / USP 平台,ABCL partner 项目从 IND-enabling 起开始消耗。
  - **Beckman Coulter Echo 525 acoustic dispensers + Biomek FX** — 高通量化合物 / antibody 处理,SDGR FEP+ "design–make–test" 循环里 "make" 环节的标准设备。

> ### 5. **2269.HK 药明生物 WuXi Biologics / Hong Kong** ⚪ (三家通吃,但 ABCL 链占比最高)

> - **Specific SKU into this trend / 具体打入该趋势的产品:**
  - **WuXiBody™ bispecific platform** + **WuXia™ cell line development** — 与 ABCL 类平台合作时的标准 process dev 入口。报告称 ~60% 的全球 antibody IND filing 在 process 端有 WuXi 参与 (公司 2024 年报口径,需谨慎)。
  - **HK + 无锡 + 爱尔兰 Dundalk + 美国 MA + 新加坡 GMP 产能** — 总产能 ~430 KL (2025 末),全球前三大生物药 CDMO。

> - **HK + 无锡 + 爱尔兰 Dundalk + 美国 MA + 新加坡 GMP 产能** — 总产能 ~430 KL (2025 末),全球前三大生物药 CDMO。
  - 直接已知合作:ABCL 的 LY-CoV555 (bamlanivimab) 部分供应、多个 Lilly/Pfizer ABCL-derived programs。SDGR 暂无直接合作 (其 antibody 工作刚起步)。RXRX 部分小分子项目走 WuXi STA (兄弟公司)。
- **Market cap + scale / 市值 + 规模:** ~HKD 60–80 B (~$8–10 B USD,2026Q1)。FY24 revenue ~RMB 18.7 B (~$2.6 B USD)。员工 ~11,000+。**估值长期被 Biosecure Act + 美中地缘政治 overhang 压制 — P/E 一度从 80× 跌到 15×**。

> - **Top competitors / 主要竞争者:** Samsung Biologics (**207940.KS**,韩国,~$50 B 市值,产能 784 KL 全球第一,**直接受益于 Biosecure 风险转移**);Lonza (**LONN.SW**,瑞士,~$40 B,刚买下 Vacaville Genentech 工厂);Catalent (前 CTLT,2024 被 Novo Holdings 私有化 ~$16.5 B);Fujifilm Diosynth (Fujifilm 母 **4901.T** 持有,~$4 B 业务规模,扩产积极)。
- **Vehicle quality / 标的质量:** **生物药 CDMO 纯 play,但有 binary geopolitical risk**。**Biosecure Act** 2024-09 在 House 通过含 WuXi entities 的版本,2025 年仍在 Senate / Conference 阶段,**未通过但持续 overhang 至 2026**。**作为 "AI antibody 商业化" 顺风受益最直接的 pure-play,代价是无法用美国资本估值模型清洁折现**。Round 2 提到的 ABCL "13 个 IND-stage 合作分子" 中相当一部分会经手 WuXi — **不是无关公司,是 ABCL 商业兑现的物理瓶颈**。

> | Compute substrate | NVDA | $3.5 T | 弱 (<1% revenue) | 0/10 |
| Device — optofluidic | BRKR | $8 B | 中强 (Beacon = ABCL 必需) | 4/10 |
| Device — HCI imaging | RVTY | $13 B | 中强 (Opera = RXRX 必需) | 4/10 |

> | Module — bioprocess | DHR | $170 B | 弱-中 (Cytiva 7% diluted) | 2/10 |
| System — CDMO | 2269.HK | $9 B | 强 (ABCL 兑现物理路径) | 7/10 ⚠ geo risk |
| Integrator — platform | ABCL/SDGR/RXRX | $1.0–1.8 B 各 | 100% (本 dive 主体) | 10/10 |

> | System — CDMO | 2269.HK | $9 B | 强 (ABCL 兑现物理路径) | 7/10 ⚠ geo risk |
| Integrator — platform | ABCL/SDGR/RXRX | $1.0–1.8 B 各 | 100% (本 dive 主体) | 10/10 |

> ### B. **Generate:Biomedicines (Somerville MA)** — Flagship Pioneering 孵化,**2023-09 D 轮 $273 M (Amgen + NVentures + Madrone),投后估值 ~$1.85 B**;2022-01 与 Amgen 签 $1.9 B 名义合作;2025 与 Novartis 扩展合作。
- **Critical role:** **AI antibody 三大私有挑战者之一** (与 Absci 公开 + Adimab 私有并列,Absci 是 ABSI / NASDAQ 公开,Adimab 仍然 LLC)。Generate 自有 Phase 1 资产 GB-0669 (SARS-CoV-2 broad-spec mAb,2024-10 IND),**这是 ABCL 最真实的对标威胁**。如果 Generate 抢在 ABCL T20 之前打出 first-in-class IND positive readout,ABCL 的 platform-value 折价会立即扩大。
- **Sweden/Japan/Korea?** — 不是,但属于 round 2 提到的 "platform vs. asset value 估值竞争" 的 **dark-horse 私营公司**。值得纳入 watchlist 是为了校准 ABCL 的 platform option value。

> - **Critical role:** **AI antibody 三大私有挑战者之一** (与 Absci 公开 + Adimab 私有并列,Absci 是 ABSI / NASDAQ 公开,Adimab 仍然 LLC)。Generate 自有 Phase 1 资产 GB-0669 (SARS-CoV-2 broad-spec mAb,2024-10 IND),**这是 ABCL 最真实的对标威胁**。如果 Generate 抢在 ABCL T20 之前打出 first-in-class IND positive readout,ABCL 的 platform-value 折价会立即扩大。
- **Sweden/Japan/Korea?** — 不是,但属于 round 2 提到的 "platform vs. asset value 估值竞争" 的 **dark-horse 私营公司**。值得纳入 watchlist 是为了校准 ABCL 的 platform option value。

> ### Optional 第三个 — **Tosoh Bioscience (Tessenderlo BE / Tokyo JP) — parent 4042.T 上市但子部门信息埋在合并报表**
- **Toyopearl AF-rProtein A HC + ToyoScreen MX-Trp-650M** — ABCL 类客户在 Cytiva 之外的 backup resin source。**~10–12% global Protein A market share**。日本特种材料 moat 的代表,**作为 Cytiva 的 "second source insurance" 在地缘风险情境下重要**。

> - NVDA / DHR / TMO 都是"sympathy beneficiary",AI antibody 故事在它们的 P&L 上稀释到几乎不可见 → **不应该用它们押注本 dive 的 thesis**。
- BRKR (Beacon → ABCL) 和 RVTY (Opera Phenix → RXRX) 是有意义的 second-derivative,但仍非 pure play。
- **2269.HK / 207940.KS 是物理路径瓶颈** — ABCL 13 个 IND-stage 分子兑现到 commercial 一定经手生物药 CDMO,这是 round 2 缺失的"下游隐含 lever"。

> - BRKR (Beacon → ABCL) 和 RVTY (Opera Phenix → RXRX) 是有意义的 second-derivative,但仍非 pure play。
- **2269.HK / 207940.KS 是物理路径瓶颈** — ABCL 13 个 IND-stage 分子兑现到 commercial 一定经手生物药 CDMO,这是 round 2 缺失的"下游隐含 lever"。

> **2. 与 round 1/2 一致性确认:**
- Round 1 已确立三家平台技术异质性,链条公司也据此分化:Beacon 卖 ABCL,Opera 卖 RXRX,**SDGR 几乎没有专属硬件供应商** (因为 SDGR 本身是软件 + cloud GPU stack — 这正是 round 2 强调 SDGR 唯一具备 "现金流可见性" 的另一面解释:**它不依赖资本品 capex 周期**)。
- Round 2 警示的 "把这赛道挂到 hyperscaler capex 是叙事拉伸" 在 round 3 得到量化:NVDA biopharma 收入 < 数据中心 1%,**用 NVDA 押注 AI antibody = 用航母赌一个游艇泊位的潮汐**。

> **3. Round 4 (若继续) 应聚焦:** 把 catalyst calendar (2026 SGR-1505 dose-escalation, 2026/2027 REC-2282 POPLAR 顶线, 2027 ABCL T20 IND) 与本 round 列出的链条公司财报节奏 (BRKR Q2 BSI 部门、RVTY Imaging guidance、2269.HK Biosecure 立法窗口) 对齐,产出 **可触发的 catalyst-by-catalyst 仓位调整 playbook**。同时给出对最初命题的最终 sizing 答案:**"AI-designed first-in-class IND" 最干净的 vehicle 仍是 SDGR 自有 SGR-1505 (per round 2 闭合),链条 sympathy 标的优先级 BRKR > RVTY > 2269.HK (如果地缘可控)**。

> # Round 4 / 第四轮 — Falsification + Synthesis / 证伪 + 综合判断
**Topic:** AI antibody discovery — ABCL + RXRX + SDGR
**Date:** 2026-05-06

> ### Trigger 2 — **ABCL "13 个 IND-stage 合作分子" 在 2026 全年内 ≤ 1 个 advance 到 Phase 2,且 ≥ 2 个被 partner 公开终止 (discontinued)**

> - **可验证位置:** ABCL 季度 10-Q "Partner Programs" 表格 + Lilly / Pfizer / Merck KGaA 季度 R&D pipeline updates。每家大药企 quarterly pipeline slide 都会标注 discontinued asset。
- **为何能证伪:** Round 2 把 ABCL 2027–2029 catalyst window 押在"partner asset 进 Phase 2/3 + royalty 启动"。如果 13 个 IND 资产里 attrition 率 > 同行业 baseline (~30%/year discontinuation rate at Phase 1),**说明 AI-augmented binder discovery 在 epitope/developability 维度并未真正减少 downstream attrition** — 这是 round 1 列举的 "developability up-front 30–50% attrition 下降" 公开宣称的核心证伪。

> - **可验证位置:** ABCL 季度 10-Q "Partner Programs" 表格 + Lilly / Pfizer / Merck KGaA 季度 R&D pipeline updates。每家大药企 quarterly pipeline slide 都会标注 discontinued asset。
- **为何能证伪:** Round 2 把 ABCL 2027–2029 catalyst window 押在"partner asset 进 Phase 2/3 + royalty 启动"。如果 13 个 IND 资产里 attrition 率 > 同行业 baseline (~30%/year discontinuation rate at Phase 1),**说明 AI-augmented binder discovery 在 epitope/developability 维度并未真正减少 downstream attrition** — 这是 round 1 列举的 "developability up-front 30–50% attrition 下降" 公开宣称的核心证伪。
- **量化阈值:** 业界同期 (2024–2025) Phase 1 → Phase 2 advancement rate ~50–55% (BIO/Informa 数据)。ABCL 合作管线如果**全年 advancement rate < 25%**,就明显劣于 baseline,这是平台 alpha 失败的硬证据。

> - **为何能证伪:** Round 2 把 ABCL 2027–2029 catalyst window 押在"partner asset 进 Phase 2/3 + royalty 启动"。如果 13 个 IND 资产里 attrition 率 > 同行业 baseline (~30%/year discontinuation rate at Phase 1),**说明 AI-augmented binder discovery 在 epitope/developability 维度并未真正减少 downstream attrition** — 这是 round 1 列举的 "developability up-front 30–50% attrition 下降" 公开宣称的核心证伪。
- **量化阈值:** 业界同期 (2024–2025) Phase 1 → Phase 2 advancement rate ~50–55% (BIO/Informa 数据)。ABCL 合作管线如果**全年 advancement rate < 25%**,就明显劣于 baseline,这是平台 alpha 失败的硬证据。

> - **可验证位置:** FDA Federal Register + CDER GfPs (Guidance for Industry) 列表;BIO/PhRMA 公开提交的 comment 文件。
- **为何能证伪 / 反向重估:** Round 1 已点出 "regulatory novelty 风险" (de-novo 流程审稿周期可能 +6–12 个月)。如果 FDA 把要求落地到具体审评流程,**ABCL/SDGR 这种 hybrid wet-AI 流程问题不大** (训练数据有湿实验 ground truth + 标准 process dev) — **反而对 RXRX/Generate/Absci 的纯 in-silico 路径冲击大**。这个 trigger 命中会**重新分配三家估值**:ABCL/SDGR 得益 (regulatory moat),RXRX/纯 de-novo player 受损。
- **重要:** 这条不是单向证伪,是 **path-dependent re-rating**。如果 guidance 偏松 (只要求披露,不要求强制 re-validation),则全行业受益,反而加速 inflection。

## From tech_dive #49: 技术深挖: AI antibody discovery commercial inflection: AbCellera...
_2026-05-07T04:52_

> # 技术深挖 / Tech deep-dive: AI antibody discovery commercial inflection: AbCellera (ABCL) + Recursion (RXRX) + Schrödinger (SDGR) -- which platform has the cleanest first-in-class IND from AI design, what's the validation evidence, and how to size the pre-clinical pipeline

> > Scope note: 用户问题聚焦三家 — ABCL / RXRX / SDGR。但严格来说,只有 **AbCellera (ABCL)** 是 antibody-native 平台;RXRX 是 phenomic / small molecule 为主,SDGR 是 physics-based small molecule(近年在向 biologics 拓展)。本轮按"AI 抗体发现"通用技术栈写,后续轮次会拆分到具体公司。

> - **打分层**:binding affinity (ΔΔG)、developability(aggregation propensity, polyspecificity, hydrophobic patch)、immunogenicity (T-cell epitope MHC-II prediction) 多目标 scoring。
- **湿实验闭环**:microfluidic single B-cell screen(ABCL Beacon / Celium)或 yeast display + NGS,把 in-silico top-K 候选物 24–72h 内表达 → SPR/BLI 亲和力测定 → 数据回灌训练。

> - **Speed**:ABCL bamlanivimab (LY-CoV555) 从 convalescent 患者血样到 clinical candidate **90 days**(2020/3–5),传统 phage 路径同期 Regeneron REGN-COV2 用了约 4 个月,但靠的是已建好的 VelocImmune 转基因鼠库。
- **Hit rate**:Generate Biomedicines / Absci 公开数据显示 in-silico → wet-lab confirmation rate 在已知 epitope 上达 **10–40%**,vs phage panning 通常 <1%。

> - **Sequence diversity**:in-silico 可扫 ~10^12 序列(GPU 限),实测 phage 库 functional diversity ~10^7–10^8(冗余后)。
- **Developability shift-left**:IgLM / AbLang2 把 "humanness score" 算进 lead selection,可把 humanization rounds 从 2–3 轮压到 0–1 轮(ABCL Trianni / OrthoMab data 暗示约 **30–50% 时间节省**)。
- **Multi-specifics**:bispecific / Fab-Fc 几何在传统平台需逐个工程化,生成模型可一次性给出 backbone + linker(SDGR PLD 在 IL-13 × IL-4Rα 案例做过 retrospective benchmark)。

> **关键事实(下一轮要用)**:在 ABCL / RXRX / SDGR 三家中,只有 **ABCL 有 AI-platform–attributable 的临床抗体**(bamlanivimab,2020),而真正的"first-in-class IND from AI design (antibody)"行业基准点是 **Absci ABS-101 (2024Q1)** — 不是这三家。这个对比将决定 round 2 (business closed loop) 的估值锚定方式。

> > 三家公司商业模式差异极大,不能用同一把尺子测量。本轮先按 ABCL / RXRX / SDGR 各自拆解,再合并到 customer / time-to-revenue 维度对比。

> **ABCL (partner-funded discovery → milestone + royalty)**
- 钱链:**Big Pharma (Lilly, Regeneron, Gilead, Moderna, AbbVie, Pfizer) → ABCL** 形式 = upfront access fee + per-program research fees + preclinical/clinical/regulatory/sales milestones + 单位数 royalty(典型 1–3%,COVID 项目据披露上探到 mid-single)。

> **ABCL (partner-funded discovery → milestone + royalty)**
- 钱链:**Big Pharma (Lilly, Regeneron, Gilead, Moderna, AbbVie, Pfizer) → ABCL** 形式 = upfront access fee + per-program research fees + preclinical/clinical/regulatory/sales milestones + 单位数 royalty(典型 1–3%,COVID 项目据披露上探到 mid-single)。
- ABCL → 上游:Trianni transgenic mice 已自有(2019 收购),Celium / Beacon microfluidic chip 自研,主要 COGS 在 Berkeley Lights (Bruker) 系统折旧 + 试剂(NEB, 10x Genomics)+ AWS 计算。

> - 钱链:**Big Pharma (Lilly, Regeneron, Gilead, Moderna, AbbVie, Pfizer) → ABCL** 形式 = upfront access fee + per-program research fees + preclinical/clinical/regulatory/sales milestones + 单位数 royalty(典型 1–3%,COVID 项目据披露上探到 mid-single)。
- ABCL → 上游:Trianni transgenic mice 已自有(2019 收购),Celium / Beacon microfluidic chip 自研,主要 COGS 在 Berkeley Lights (Bruker) 系统折旧 + 试剂(NEB, 10x Genomics)+ AWS 计算。
- 2025 新链条:ABCL 自建 GMP biomanufacturing facility(Vancouver,$700M+ capex,~50% government cost-share BC + Canada Strategic Innovation Fund),将来 ABCL → CDMO 收 fee-for-service,把价值链向 Tox-IND material 段延伸。

> - ABCL → 上游:Trianni transgenic mice 已自有(2019 收购),Celium / Beacon microfluidic chip 自研,主要 COGS 在 Berkeley Lights (Bruker) 系统折旧 + 试剂(NEB, 10x Genomics)+ AWS 计算。
- 2025 新链条:ABCL 自建 GMP biomanufacturing facility(Vancouver,$700M+ capex,~50% government cost-share BC + Canada Strategic Innovation Fund),将来 ABCL → CDMO 收 fee-for-service,把价值链向 Tox-IND material 段延伸。
- **Per-program economics(行业披露区间)**:0–5M upfront / 10–30M research+preclin / 50–200M+ clin+reg / 1–3% royalty。一个 IND 触发约 $5–15M;一个 BLA 通常 $50–100M。

> - SDGR → 上游:GCP / AWS compute(physics-based FEP+ 计算密集)+ in-house wet lab(自 2020 建于 Framingham, MA),用于实验回灌 ML training。
- **现金流逻辑独特**:software 收入支付绝大部分 OPEX,drug-discovery royalty 是 free option;ABCL/RXRX 没有这个 software cushion。

> - 传统 phage / hybridoma + lead opt:全成本(FTE + reagents + animal studies)~$10–30M / clinical candidate,18–36 个月。
- AI antibody platform(ABCL 类 microfluidic + ML):**~$3–10M / clinical candidate, 9–18 个月**(ABCL 内部披露及 BCG 2023 industry benchmark 推算)。
- 假设 90 partner 程式 × $10M revenue 价值 = $900M 潜在 milestone 池(这是名义,不是 NPV)。

> **Break-even per-program economics**
- ABCL 报表:每年 ~30 个新 program initiated × 平均 ~$5M 早期付费 = $150M run-rate,**对比 OPEX ~$200–250M(含 GMP 建设)= 现金流为负**。要 break-even 需要:
  - (a) 每年 5+ 个 IND-stage milestone 触发($5–15M each = $50–75M);**或者**

> - (b) GMP CDMO 业务上量到 ~$100M+ (这在 2027 之后)。
- **Inflection 锚点**:ABCL 自己披露目标 — 2025 年 9 个 IND 进入 partner 临床,2026 年 14+。每个 IND 对 ABCL 现金流的边际贡献约 $5–15M upfront milestone,full pipeline mature 后(假设 5% 上市通过率 × 50 IND × $200M peak sales × 2% royalty)= $20M/year sustained royalty per cohort。

> - Roche/Genentech — $150M+ upfront to RXRX,$200M+ Recursion equity stake。
  - Lilly — $700M+ multi-year commitment to ABCL platform deals(累计公开数额);自建 OpenAgentic 类内部 AI biology team。
  - Novo Nordisk — Eli Lilly 之外最积极的 AI 抗体投入,2024 收购 Cellectis stake + Valo Health partnership。

> **ABCL — 重度集中,Lilly is the whale**
- 2024 revenue 约 $38M,其中 **Lilly 历史累积合作占 ABCL 全期 milestone+royalty 的 50%+**(主要因 bamlanivimab COVID royalty 在 2021–2022 贡献 $200M+)。

> **ABCL — 重度集中,Lilly is the whale**
- 2024 revenue 约 $38M,其中 **Lilly 历史累积合作占 ABCL 全期 milestone+royalty 的 50%+**(主要因 bamlanivimab COVID royalty 在 2021–2022 贡献 $200M+)。
- 当前 partner book 89+ programs,但 top 5(Lilly, Regeneron, Gilead, Moderna, AbbVie)估占 active program value 的 ~70%。

> - 当前 partner book 89+ programs,但 top 5(Lilly, Regeneron, Gilead, Moderna, AbbVie)估占 active program value 的 ~70%。
- Single-name risk:Lilly 2025 终止 / 减速任一 ABCL 项目 → ABCL 潜在 milestone 池缩 20–30%。

> **ABCL**
- **现在已有 revenue**($38M 2024,$50–60M 2025E),但 99% 是 research fees + 早期 milestones,**royalty 真正放量要等 2027–2030**(89 个 programs 的 5% 假设上市率)。

> 1. **三家中只有 SDGR 有 software-grade 现金流**(2024 $180M ARR);ABCL / RXRX 都是 milestone-binary 模型,任何一年现金流可以 swing $50M+。
2. **ABCL 的真正护城河不是 AI**,是 Trianni mice + Beacon + 89 partner book + 即将上线的 GMP CDMO 一体化 — AI 是 marketing wrapper,核心是 microfluidic single-B-cell 物理资产。

> 1. **三家中只有 SDGR 有 software-grade 现金流**(2024 $180M ARR);ABCL / RXRX 都是 milestone-binary 模型,任何一年现金流可以 swing $50M+。
2. **ABCL 的真正护城河不是 AI**,是 Trianni mice + Beacon + 89 partner book + 即将上线的 GMP CDMO 一体化 — AI 是 marketing wrapper,核心是 microfluidic single-B-cell 物理资产。
3. **RXRX 是 narrative-heavy, milestone-poor**:$12B biobuck 名义巨大,NPV-discounted 后 << market cap implied;真正 cash inflection 在 2027 之后。

> 3. **RXRX 是 narrative-heavy, milestone-poor**:$12B biobuck 名义巨大,NPV-discounted 后 << market cap implied;真正 cash inflection 在 2027 之后。
4. **第一个真正"AI-designed first-in-class antibody IND"在三家中并未发生** — Absci ABS-101 (2024Q1) 仍是行业基准。三家中最接近的是 ABCL(89 个 partner program 中至少 5 个披露含 AI lead-opt),但 attribution 弱。
5. **Customer concentration 排序**:RXRX (Roche 50%) > ABCL (Lilly 30%+) > SDGR (top-1 <10%)。

> 4. **第一个真正"AI-designed first-in-class antibody IND"在三家中并未发生** — Absci ABS-101 (2024Q1) 仍是行业基准。三家中最接近的是 ABCL(89 个 partner program 中至少 5 个披露含 AI lead-opt),但 attribution 弱。
5. **Customer concentration 排序**:RXRX (Roche 50%) > ABCL (Lilly 30%+) > SDGR (top-1 <10%)。

> > Scope: AI 抗体发现链条 vertical 至少 5 层 — compute substrate → wet-lab instrument → consumable/reagent → AI platform → bioprocessing → big pharma integrator。ABCL / RXRX / SDGR 都挤在 platform 这一层,所以本轮把视野放大到上下游各层各取 cleanest pure-play,再回头给三家做 head-to-head ranking。

> - **Layer**: GPU substrate — AlphaFold-Multimer / RFdiffusion / ESMFold / IgLM / Chroma 推理与训练全部跑在 H100/H200/B100/B200 上
- **Specific product**: **DGX BioNeMo + H100/H200 SXM**;BioNeMo 是 NVIDIA 推的 protein/antibody foundation model framework(集成 ESM-2, OpenFold, MoLMIM),被 RXRX BioHive-2(~512 H100s)、ABCL 内部 cluster、ABSI 内部 cluster 直接用。H100 SXM ~$30k/unit,DGX SuperPOD multi-million
- **Scale**: 市值 ~$3.4T (2026Q1),FY2026 revenue ~$200B+,Healthcare vertical ARR <5% 但是 fastest-growing seg

> - **Layer**: Microfluidic single-B-cell screening 硬件(2023 收购 Berkeley Lights ~$57M,改名 Bruker Cellular Analysis)
- **Specific product**: **Beacon Optofluidic platform + Lightning + Culture Station**。ABCL 整个 microfluidic screening pipeline 的核心仍是 Beacon(虽然 ABCL 自研 Celium 部分替代);Genmab、Adimab、AstraZeneca、AbbVie 内部 antibody discovery 也在用。Beacon 单台售价 ~$1.5–2M,reagent consumables ~$30–80k/program
- **Scale**: 市值 ~$8B,2024 revenue ~$3.4B,Cellular Analysis 业务 ~$80M/year(全公司 <3%)

> - **Competitors**: Sphere Fluidics(private UK,droplet microfluidic),Cytek Biosciences (CTKB,spectral flow),10x Genomics (TXG,non-overlap但邻接);antibody-discovery 专用单 B 细胞 + functional screen 上 Beacon 仍是 de facto 标准
- **Vehicle quality**: **Diversified beneficiary, not pure-play**。Bruker 主业 NMR / mass spec / X-ray,Beacon <3% 收入。战略读法是"如果 ABCL 退订,Bruker 短期不痛;但行业新入场者第一台仍买 Beacon"

> - **Layer**: Single-cell + spatial sequencing;antibody 端 = paired heavy/light chain VDJ sequencing
- **Specific product**: **Chromium iX + Next GEM 5' Immune Profiling kit**。ABCL / Adimab / Genmab / Regeneron 内部 NGS-based B-cell repertoire 都跑 10x VDJ。kit ~$5k/sample,每个 antibody discovery program 用 5–20 sample
- **Scale**: 市值 ~$1.3B,2024 revenue ~$640M,Chromium consumables ~70% 收入

> - **Scale**: 市值 ~$300–500M(波动极大),2024 revenue ~$5–10M(partnership early-stage),cash ~$110M,burn ~$70–80M/year,**runway ~14–18 months**
- **Competitors**: ABCL(最大公开市场对手,但 ABCL 有 microfluidic + 89-partner book moat),Generate Biomedicines(私),Xaira(私),Iambic(私),Cradle(私 EU)
- **Vehicle quality**: **Purest-play AI antibody public stock — 高 beta, binary risk**。ABSI 的整个估值就是 ABS-101 Ph1 readout(2026E)是否成功;positive 则 +3–5x,negative 则 -50–70%。**唯一一只你买就是因为"first AI-designed antibody"narrative 的 ticker**

> - **Layer**: End-integrator — 把 AI antibody discovery 接到 development + commercial
- **Specific product into trend**: 历史 = **bamlanivimab / etesevimab**(ABCL 平台,COVID EUA 2020/11);现役 = **donanemab (Kisunla)** Alzheimer mAb(2024 FDA approved,2026 ramp);ABCL 多个 undisclosed partner programs;LLY 内部 AI biology team(累计公开承诺 $700M+ multi-year)
- **Scale**: 市值 ~$700B,2024 revenue $50B(GLP-1 主导),R&D ~$11B/year

> - **Competitors**: NVO(GLP-1 直接对手),REGN(mAb innovation 直接对手),AZN, MRK, RHHBY。在"积极用 external AI 平台"维度 LLY 是 most aggressive of big pharma
- **Vehicle quality**: 完全 diversified — AI 抗体在 LLY $700B 里 <0.5%。**买 LLY 是买 GLP-1 + Alzheimer**,不是 AI antibody。但 LLY 任何一个 ABCL-platform IND 触发的 milestone,LLY 财报不会 notice,ABCL 股价 +15%

> - **Layer**: GMP antibody bioprocessing(filtration, chromatography, single-use bioreactor 模块)
- **Specific product into trend**: 自研 **Protein A resin** + **OPUS pre-packed columns** + **TFF flat-sheet cassettes** + **XCell ATF cell retention**。ABCL Vancouver GMP facility($700M capex)+ Lonza / Catalent / Samsung Biologics 几乎都是 RGEN 客户
- **Scale**: 市值 ~$8B,2024 revenue ~$640M,bioprocessing pure-play(70%+ revenue from filtration + chromatography 模块)

> - 核心资产 = **Chroma generative diffusion** + 已 advance 多个 candidate 进 IND/Ph1 阶段(IL-21 / IL-2 muteins / undisclosed targets)
- **战略意义**: ABSI 的最大 private 对手;IPO 概率 2026–2027 高,IPO 后立刻成为 ABSI / ABCL 的 valuation anchor

> - Built around David Baker(2024 Chemistry Nobel,RFdiffusion 作者)+ ex-Genentech CSO Marc Tessier-Lavigne
- **Critical path**: Baker 实验室 RFdiffusion 是行业最常被引用的 antibody-design 生成模型,Xaira 是 Baker IP 的商业化主体 — 与 ABCL / ABSI / Generate 在 talent pool + IP 上零和竞争
- **Tracking signal**: Xaira 第一个 IND(预计 2027–2028)是 ABSI / ABCL 估值最大外部 disruptor

> - **Critical path**: Baker 实验室 RFdiffusion 是行业最常被引用的 antibody-design 生成模型,Xaira 是 Baker IP 的商业化主体 — 与 ABCL / ABSI / Generate 在 talent pool + IP 上零和竞争
- **Tracking signal**: Xaira 第一个 IND(预计 2027–2028)是 ABSI / ABCL 估值最大外部 disruptor

> - Reagents critical-path: antibody library construction、PCR、cloning enzymes(Q5 polymerase, Gibson Assembly, 限制酶)
- 不可投资,但 ABCL / ABSI / RXRX 的 wet-lab 试剂账单 NEB 占 ~10–20%
- A-share 替代:**Vazyme (688105.SH)** 已上市,但海外 AI antibody 平台基本不用

> | 维度 | ABCL | RXRX | SDGR |
|---|---|---|---|

> 1. **三家中没有一只是 pure-play AI antibody 公开票**;最纯的是 **ABSI**(NASDAQ),它才是用户问题里"first-in-class IND from AI design (antibody)"的实质 ticker。市场上 ABCL 被定位为一线 quality, ABSI 被定位为二线 high-beta — 估值方法不同
2. **ABCL 的真护城河不是 AI**,是 **Bruker Beacon + Trianni mice + 89 partner book + Vancouver GMP** 的物理资产组合。任何 "AI-only" 进入者(ABSI / Generate / Xaira)在 wet-lab throughput 上都还匹配不了 ABCL

> 1. **三家中没有一只是 pure-play AI antibody 公开票**;最纯的是 **ABSI**(NASDAQ),它才是用户问题里"first-in-class IND from AI design (antibody)"的实质 ticker。市场上 ABCL 被定位为一线 quality, ABSI 被定位为二线 high-beta — 估值方法不同
2. **ABCL 的真护城河不是 AI**,是 **Bruker Beacon + Trianni mice + 89 partner book + Vancouver GMP** 的物理资产组合。任何 "AI-only" 进入者(ABSI / Generate / Xaira)在 wet-lab throughput 上都还匹配不了 ABCL
3. **RXRX 在 antibody 维度上是 misclassified** — antibody 在 RXRX 估值里 <10% 权重。如果用户问题焦点是抗体,RXRX 是错误纳入项

> 5. **Picks-and-shovels 安全玩法**: BRKR(Beacon)+ TXG(VDJ)+ RGEN(GMP fill-finish)— 但每个 AI 抗体 narrative 对它们整体股价的影响 <5%
6. **2026–2028 最大外部 disruption 风险**: Xaira + Generate IPO,任一即压制 ABCL / ABSI 估值

> Round 3 完成 — 链条已经铺开:substrate (NVDA) → instrument (BRKR) → consumable (TXG) → AI platform pure-play (ABSI) → bioprocessing (RGEN) → integrator (LLY),加上三家本身。准备好就发 "下一轮" / "round 4" — 进入 **catalyst calendar + position sizing**(2026Q2–2027Q4 readouts / IND / milestone 日历,加上 conviction × time-to-readout 矩阵给 ABCL / ABSI / RXRX / SDGR 排仓位权重)。

> - **What to watch**: Absci 8-K / press release on ABS-101 Ph1a SAD/MAD readout, **expected 2026H2–2027H1**(per Absci 2025 IR disclosures)。两类失败:(a) drug-related SAE / Grade 3+ AE forcing dose halt;(b) PK/PD biomarker(serum TL1A neutralization)未达预期 ≥50% suppression at therapeutic dose
- **Why this falsifies**: ABS-101 是行业唯一公认的 fully de novo AI-designed antibody in clinic。如果它在 first-in-human 阶段就 failure,**整个"generative AI 直接出 IND"的 narrative 退回 pre-2024 状态**,ABCL/Generate/Xaira 的同类项目融资与 partner deal 估值锚下移
- **Verifiable**: ClinicalTrials.gov NCT06127485(ABS-101 Ph1)+ Absci quarterly filings

> ### Trigger 2 — AbCellera 2026 partner-IND count falls below 11 (vs guidance of 14+)
- **What to watch**: ABCL 季度 IR deck 上"partner-initiated INDs cumulative"数字。2025 guidance = 9 by YE2025, 14+ by YE2026
- **Why this falsifies**: ABCL 整个 valuation thesis = 89 partner programs 在未来 5 年线性 IND 化。如果 2026 年实际 IND 数 ≤ 11(即 guidance miss >20%),说明:(a) 平台 productivity 没有 step-up;(b) partner 内部对 AI 平台的相对优先级在下降。**线性 89 → IND 转化曲线断裂,SOTP 估值要 re-derate 30–50%**

> - **What to watch**: ABCL 季度 IR deck 上"partner-initiated INDs cumulative"数字。2025 guidance = 9 by YE2025, 14+ by YE2026
- **Why this falsifies**: ABCL 整个 valuation thesis = 89 partner programs 在未来 5 年线性 IND 化。如果 2026 年实际 IND 数 ≤ 11(即 guidance miss >20%),说明:(a) 平台 productivity 没有 step-up;(b) partner 内部对 AI 平台的相对优先级在下降。**线性 89 → IND 转化曲线断裂,SOTP 估值要 re-derate 30–50%**
- **Verifiable**: ABCL 2026Q4 earnings call(2027/3 前后)的 cumulative IND counter

> - **Why this falsifies**: ABCL 整个 valuation thesis = 89 partner programs 在未来 5 年线性 IND 化。如果 2026 年实际 IND 数 ≤ 11(即 guidance miss >20%),说明:(a) 平台 productivity 没有 step-up;(b) partner 内部对 AI 平台的相对优先级在下降。**线性 89 → IND 转化曲线断裂,SOTP 估值要 re-derate 30–50%**
- **Verifiable**: ABCL 2026Q4 earnings call(2027/3 前后)的 cumulative IND counter
- **Threshold to act**: cumulative number ≤ 11 或者 management 撤回 14+ guidance

> - **What to watch**: Generate Chroma-platform 或 Xaira RFdiffusion-platform 抗体 in 2026–2027 拿到 FDA IND, 且 press release 明确表述 "fully generative" / "no B-cell starting material"
- **Why this falsifies the ABCL/SDGR/RXRX angle**: 如果 private 端 (Generate / Xaira) 比 ABCL 更快做出 cleanly-attributable AI-designed first-in-class IND,则 **ABCL "AI antibody leader" 公开市场标签被 reset 为"microfluidic CRO"**。同时 Generate/Xaira IPO 路径打开,稀释整个 AI antibody pure-play 估值池
- **Verifiable**: FDA orange book、ClinicalTrials.gov、公司 press release;Generate / Xaira IPO S-1 filing 也属同一 trigger

> **Crowded or before-it-20x?** Stage = **early-commercial, narrative-saturated, evidence-thin**。证据:(i) 真正 fully-AI-designed antibody in clinic 仅 ABS-101 一例(2024Q1),(ii) 三家公开票合计市值 ~$8B vs Big Pharma R&D AI 渗透实际 spend <$2B/year — narrative inflated 但 cash flow 远未到。这不是 2017 的 Nvidia data center moment,更像 **2014 的 immunotherapy(Keytruda 已上市但 broad uptake 还需 3–5 年)**。**before-it-20x 已过,但 before-it-3x 仍在窗口** — 前提是 ABS-101 Ph1 & ABCL partner-IND ramp 兑现。

> **90-day single signal to track**: **ABCL Q1 2026 earnings call(2026/5 中下旬)的 partner-initiated IND counter** — 是否从 YE2025 的 9 累进到 11+。这个数字比任何 management commentary 更硬,因为 IND 是公开 FDA 记录,无法粉饰。Counter ≥ 11 = thesis on track; ≤ 9 = 平台 productivity 停滞,re-derate。

> **Cleanest entry now**: **ABCL** — 三家中唯一同时具备(i) AI/microfluidic 平台资产、(ii) 89-program partner book、(iii) ~$700M cash + 3 年 runway、(iv) Lilly 历史 royalty 已实战验证。**ABSI 更纯但 binary 风险过高**(单 trial 决定生死);RXRX 在 antibody 维度是 mis-classified;SDGR 不是 antibody 票。

> **When NOT to own ABCL**: 任一以下:(1) Lilly 或 Regeneron 公告任何形式的 ABCL collab restructuring / scope reduction;(2) Vancouver GMP capex 出现 >$200M cost overrun 或交付延期 12+ 个月;(3) 市值 above ~$1.6B 时(对应 EV/2026E revenue >25x,partner-IND ramp 假设已 fully priced)— 此 level 上没有给 trigger 1/2/4 的 downside 留 margin of safety。

## From tech_dive #50: 技术深挖: Foundation models for protein structure prediction pos...
_2026-05-07T05:01_

> Isomorphic Labs (private) · Recursion (RXRX) · Insilico (private)
        Schrödinger (SDGR — partly here via collaborations) · AbCellera (ABCL)
                       │

> | **Schrödinger (SDGR)** | Top-1 software customer ~7%; **but** drug-discovery collab revenue **highly concentrated** in BMS + Otsuka + Lilly | drug-discovery rev ~**50% one customer**; software more diversified | ~**70%** of drug-discovery rev top-3 |
| **AbCellera (ABCL)** | Lilly historically (bamlanivimab royalty wind-down); now diversified across ~80 partners but bookings still concentrated | ~**30%** | ~**60%** |
| **Isomorphic Labs (private)** | **Lilly + Novartis = ~100%** of 2024 disclosed external revenue | **~50% each** | **100%** |

> - **Insilico:** revenue ~$50M/yr (collab + small services); INS018_055 Phase II readout **~end-2026 / 2027**; first commercial-sales-tier royalty (if approved) **~2030+**.
- **AbCellera (ABCL):** FY24 revenue ~$38M (down sharply from the bamlanivimab COVID royalty peak ~$370M in 2021); ~80 active programs but milestones dribble in unevenly. **Material royalty inflection requires multiple Phase III approvals, ~2027+**.

> Round 3 应该聚焦**公开市场可投标的:股票链 + 估值 + 触发条件 + 风险事件清单**(NVDA / TEM / SDGR / RXRX / 以及 ABCL、TXG、CRL/WuXi 的可投性)。Ready when you say go.

> - **量级 / Scale:** 市值 **~$2–3B**;FY24 合作营收 **~$59M**;**烧现金 ~$400M/yr**,现金 + 等价物 ~$600M (Q4 24),**runway 到 ~2027** 取决于里程碑节奏;员工 ~800(并 Exscientia 后)。
- **竞争 / Competitors:** **Isomorphic Labs**(私有,AF3 母体,见下);**Insilico Medicine**(私有,HK IPO 重提);**AbCellera (ABCL)**;**Relay Therapeutics (RLAY)**(动态结构 + Lilly 合作);**BenevolentAI (BAI.AS, Euronext Amsterdam)**(已大幅减员)。
- **载体质量 / Vehicle quality:** **目前公开市场最纯的 "AI-native pharma" 标的**,但**客户极度集中**(Roche/Genentech ~50%, top-3 ~90%),且**真正现金兑现要到 2026–2028 里程碑窗口**;Phase II 读数双向尾部风险大。**主题表达最直接、风险也最显性的票**。

> ## 5. ABCL / AbCellera Biologics — Nasdaq

> | **现金流"今天就在"的软件 SaaS** | **SDGR**(物理仿真 + AF 互补) | — |
| **2026–2028 里程碑兑现的 Tier-1** | **RXRX**(主题最纯,客户集中风险显性) | ABCL(抗体方向辅助) |
| **2027+ 首批 AI 设计药物 FDA 批文 sentinel** | Insilico Phase II 读数(私有,只看不买)| RXRX REC-xxxx 读数 |
