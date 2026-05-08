# RXRX -- 综合提取 / All mentions across our research

_Aggregated from 97 mentions across 5 reports. Auto-generated; rerun via `python scripts/compress_dives_to_companies.py`._

---

## From tech_dive #43: 技术深挖: AI antibody discovery commercial inflection: AbCellera...
_2026-05-07T03:10_

> # 技术深挖 / Tech deep-dive: AI antibody discovery commercial inflection: AbCellera (ABCL) + Recursion (RXRX) + Schrödinger (SDGR) -- which platform has the cleanest first-in-class IND from AI design, what's the validation evidence, and how to size the pre-clinical pipeline

> # Round 1 / 第一轮 — Technology Closed Loop / 技术闭环
**Topic:** AI antibody discovery — ABCL + RXRX + SDGR
**Date:** 2026-05-06

> - **Sequence–structure co-design (ABCL 主战场).** 输入抗原结构 (AlphaFold2/3 预测或 cryo-EM),用 inverse-folding 模型 (ESM-IF, ProteinMPNN) 或 diffusion 生成模型 (RFdiffusion, Chroma) 直接输出 CDR 序列;再用 ESM-2/3 这类蛋白语言模型做亲和力 + developability 二次评分。ABCL 的差异化是把生成模型挂到自家 **Beacon 微流控单 B 细胞筛选 + Trianni 人源化小鼠免疫库** 上,即 "AI 排序 → optofluidic 单细胞 readout" 的闭环,而不是纯 in-silico de novo。
- **Phenomics + foundation model (RXRX 主战场).** Cell Painting 染色 → 高内涵成像 → 数百万 perturbation × cell line 矩阵 → 用 MolE / Phenom-Beta 自监督模型把图像嵌入到 ~1024 维表征空间,再用 contrastive learning 找 "这个化合物/基因敲低的表型 = 那个已知药物的表型" 的 map-of-biology。底层算力是 NVIDIA H100 集群 BioHive-2 (~2 EFLOPS FP8)。这条线**不是抗体专属**,而是从表型反推靶点 + 苗头化合物。
- **Physics-first + ML (SDGR 主战场).** FEP+ (free-energy perturbation) 用炼狱级 MD 算配体–靶点结合自由能,误差 ~1 kcal/mol;WaterMap 算结合口袋脱水罚分;近 3 年挂上 active learning + graph NN,把 FEP+ 当作 "ground-truth 标签机" 去训练快速代理模型,使得每周可以打 10⁵ 分子量级而不是 10² 量级。**主战场仍是 small molecule**,2023 起把同一栈延伸到 antibody Fv–antigen 结合面 (LiveDesign Biologics)。

> 所以本 dive 的"老 incumbent"按平台对应是: **ABCL/Generate/Absci → 替代 hybridoma + phage display**;**SDGR → 替代 HTS + 经典 SBDD**;**RXRX → 替代 target-first reductionist drug discovery (本身是个 paradigm shift,不仅是工艺替换)**。

> - **Recursion 临床进展.** REC-994 (CCM, Phase 2 SYCAMORE,2024 年 9 月顶线 — 安全性达标但 efficacy 信号弱);REC-2282 (NF2 meningioma, Phase 2/3 POPLAR);REC-4881 (FAP, Phase 1b/2);REC-617 (CDK7, Phase 1)。**注意:REC-994 是 Recursion 用 phenomics map 重新发现 superoxide scavenger 的指征,不是 de-novo 设计 — 验证的是"老分子新指征"通路,而不是 AI 出新分子的通路。**
- **Recursion × Roche/Genentech.** 2021 年签的 neuroscience + GI oncology phenomic 合作,2024-08 Roche 行权扩展 maps,公开里程碑 ~$300 M 已支付 (RXRX 10-Q, Q3 2024)。
- **Recursion × NVIDIA.** 2023-07 NVIDIA 投资 $50 M;2024-08 Recursion 收购 Exscientia (~$688 M all-stock,2024-11 closed),并入小分子设计能力。BioHive-2 (~63,000 H100-equivalent) 2024 年上线,公开为"top-10 industry HPC"。

> **Round 1 闭合判断:** 技术层面三家差异比"AI drug discovery"这个 umbrella 词暗示的大得多 — ABCL 是 **wet-AI hybrid (binder discovery)**,SDGR 是 **physics + ML (affinity optimization)**,RXRX 是 **phenomics map-of-biology (target ID)**。后续 round 评估"first-in-class IND from AI design"时必须按各自定义打分,不能用同一把尺。**最干净的"AI-designed first-in-class IND"候选应优先看 SDGR 自有管线 (SGR-1505/2921/3515) 和 ABCL 即将进入 IND 的 T20**;RXRX 的临床资产更接近 repurposing,**不是 round 命题想要的"AI 设计的新分子"**。

> # Round 2 / 第二轮 — Commercial Closed Loop / 商业闭环
**Topic:** AI antibody discovery — ABCL + RXRX + SDGR
**Date:** 2026-05-06

> ### RXRX chain (phenomic map + co-development / 表型图谱 + 联合开发)
```

> ▼
Recursion Pharmaceuticals (RXRX)
   │  ⇣ COGS = 表型生产线

> ```
**Key point / 关键点:** RXRX 现金流最依赖 **upfront + map exercise**,没有任何商业化产品收入。FY24 (含 Exscientia 末期) 收入 ~$59 M,**100% 是 collaboration / milestone**,且高度集中于 Roche 这一个客户。

> ### RXRX: Cost-per-actionable-target / 单个可成药靶点发现成本
- **Incumbent (target-first reductionist):** 学术/工业累计估 ~$100 M 才能从 GWAS/CRISPR 筛得到一个进入 lead-finding 阶段的 high-confidence target (含 ~3 年时间)。

> - NVIDIA biopharma vertical revenue (BioNeMo + 直销): 2025E 约 ~$0.8–1.2 B,**仅占 NVDA 数据中心收入的 < 1%**。
- 真正流向 AI drug discovery 平台的 hyperscaler 资金 = NVIDIA $50 M 投 RXRX、Microsoft $100 M 战略合作 Recursion (2025-04 公布) — **量级 < $1 B 累计**,远小于 LLM 赛道。

> ### RXRX
- **Top 3:** Roche/Genentech (~$190 M 累计 milestone + $150 M upfront,占累计 collab 收入 ~50%)、Bayer (~$30 M upfront + later milestones,~15%)、Sanofi (Exscientia 继承,~10%)。

> ### RXRX
- **Now (in-pocket):** FY24 ~$59 M,80%+ 是 Roche/Bayer collaboration recognition。**没有任何商业化产品收入**。

> - **2025–2026:** Roche 后续 map exercise (option fee per map ~$10–30 M,频率 2–4 / yr),Bayer milestone trickle。Recursion + Exscientia 合并后,Sanofi/BMS 旧合约可能贡献 ~$30–50 M。**全年 $60–100 M 的 ceiling,且 lumpy**。
- **2027–2028 (binary catalyst):** REC-2282 (NF2 meningioma Phase 2/3 POPLAR 顶线 2026/2027)、REC-4881 (FAP Phase 2)、REC-617 (CDK7 Phase 1) — 若 ≥1 个出阳性,**重估上升空间显著**;若全失败,RXRX 将和 BenevolentAI、Exscientia (前事) 一样进入"再融资 / 被吞并"叙事。
- **判断:** **2027 之前 RXRX 没有真实的产品 revenue**,collab milestone 是唯一的"血"。**这是三家里 funding-risk 最高的**,Q4 2024 cash ~$600 M (含 Exscientia 注入),按现 burn rate 仅够撑到 2026 中末。

> - **2027–2028 (binary catalyst):** REC-2282 (NF2 meningioma Phase 2/3 POPLAR 顶线 2026/2027)、REC-4881 (FAP Phase 2)、REC-617 (CDK7 Phase 1) — 若 ≥1 个出阳性,**重估上升空间显著**;若全失败,RXRX 将和 BenevolentAI、Exscientia (前事) 一样进入"再融资 / 被吞并"叙事。
- **判断:** **2027 之前 RXRX 没有真实的产品 revenue**,collab milestone 是唯一的"血"。**这是三家里 funding-risk 最高的**,Q4 2024 cash ~$600 M (含 Exscientia 注入),按现 burn rate 仅够撑到 2026 中末。

> - **已闭环且现金流可见:** **SDGR** > ABCL > RXRX。SDGR 是唯一同时具备 (a) recurring software revenue (b) 已变现的 platform-asset event (Nimbus) (c) 自有 IND 管线 三件套的标的。
- **Platform value vs. asset value 拆分 (sell-side 模型常见错误):**

> - SDGR 当前市值 ($1.5–1.8 B 区间) 隐含 **software (DCF, ~5–6× sales) ~$900 M + Nimbus tail ~$200 M + 自有管线 option value ~$300–500 M**。下行支撑在软件部分,上行依赖 SGR-1505 读出。
  - RXRX 当前市值 ($1.6–2.0 B,Exscientia 合并后) **几乎全部是 platform option value + cash**,asset NPV 接近 0(因为 REC-994 失败、其他还在 Phase 1/2)。**最高 beta、最大下行**。
- **"AI-designed first-in-class IND" 商业兑现的 cleanest path:**

> - **ABCL T20** — 仍在 IND-enabling,验证窗口 2027+。
  - **RXRX REC-2282 / REC-617** — 不是新分子设计,**不符合 round 命题"AI-designed first-in-class"严格定义**。

> **Round 3 应聚焦:** 把上述 platform value vs. asset value 拆分映射到三家具体的可投资 catalyst calendar (2026–2028),并明确 sizing logic — 即在 pre-clinical pipeline 这一资产类别里,如何设定 ABCL : SDGR : RXRX 的相对权重 (含失败概率加权与单个 clinical readout 的 binary risk)。同时回答最初命题:**哪个平台的"first-in-class IND from AI design"最干净 + 有最强 validation evidence**。

> # Round 3 / 第三轮 — Public companies in the chain / 链条上的上市公司
**Topic:** AI antibody discovery — ABCL + RXRX + SDGR
**Date:** 2026-05-06

> ABCL/RXRX/SDGR 本身是 "integrator / platform" 层。**它们的上游不是一条链,而是三条几乎不重叠的链** (round 1/2 已建立),因此 round 3 的链条公司必须按 "为哪一家平台供货" 分别列。下表的颜色编码:🅰 = 主要供 ABCL 链,🅡 = RXRX 链,🅢 = SDGR 链,⚪ = 三家通吃。

> - **Specific SKU into this trend / 具体打入该趋势的产品:**
  - H100 / H200 / B200 GPUs — 用于 BioHive-2 (RXRX, ~63 K H100-equiv,公开为业界 top-10 industry HPC) 以及 SDGR 在 Google Cloud / AWS 上租用的 FEP+ 算力 (单 ligand-pair ~4–8 GPU-hour)。
  - **BioNeMo platform** — 把 ESM-2/3, AlphaFold-Multimer, RFdiffusion, MolMIM, DiffDock 打包成 inference microservices,通过 NIM 卖给 pharma + biotech AI team。NVDA 自报 BioNeMo 客户 >100 家 (2025 GTC),含 Recursion (战略持股)、Genentech、Insilico Medicine、Iambic Therapeutics。

> - **BioNeMo platform** — 把 ESM-2/3, AlphaFold-Multimer, RFdiffusion, MolMIM, DiffDock 打包成 inference microservices,通过 NIM 卖给 pharma + biotech AI team。NVDA 自报 BioNeMo 客户 >100 家 (2025 GTC),含 Recursion (战略持股)、Genentech、Insilico Medicine、Iambic Therapeutics。
  - 直接战略股权:RXRX $50 M 一级投资 (2023-07);Recursion 后续披露 ~$200 M+ GPU 采购承诺 (10-Q, 2024)。
- **Market cap + scale / 市值 + 规模:** ~$3.5 T (2026Q1),FY25 (Jan 2026 财年结) revenue ~$170 B,**biopharma vertical revenue 估 ~$0.8–1.2 B / yr,< DC 收入的 1%**。

> ### 3. **RVTY Revvity Inc / NYSE** 🅡 (主供 RXRX 链)

> - **Specific SKU into this trend / 具体打入该趋势的产品:**
  - **Opera Phenix Plus / Operetta CLS high-content imager** — 共聚焦自动化显微镜,**Recursion 装机超过 100 台** (RXRX 2023 投资者日披露),**单台 list price ~$700 K–1 M + 年服务费 ~$80 K**。是全球 phenomic / Cell Painting screening 最大装机基础。
  - **Harmony Imaging Software** + **Signals Lead Discovery informatics** — 把 image well → numeric feature 量化的 pipeline,RXRX 早期管线大量基于此再转入 in-house 模型。

> - **Opera Phenix Plus / Operetta CLS high-content imager** — 共聚焦自动化显微镜,**Recursion 装机超过 100 台** (RXRX 2023 投资者日披露),**单台 list price ~$700 K–1 M + 年服务费 ~$80 K**。是全球 phenomic / Cell Painting screening 最大装机基础。
  - **Harmony Imaging Software** + **Signals Lead Discovery informatics** — 把 image well → numeric feature 量化的 pipeline,RXRX 早期管线大量基于此再转入 in-house 模型。
  - **PhenoLogic / PhenoVue** Cell Painting 试剂套装 — 标准化的 6-color staining kit,直接对接 JUMP-CP (JUMP Cell Painting Consortium) 标准。

> - **Top competitors / 主要竞争者:** Molecular Devices (Brooks Automation BRKS 子公司,~$2.5 B market cap parent);Yokogawa Electric (**6841.T**,~$10 B 市值,CV8000 / CV7000 confocal HCI 系统,Recursion 也有部分 fleet 用 Yokogawa);Olympus / Evident Scientific (8088.T 母,Olympus 母;Evident 已私有化 Bain Capital 持股);Nikon (7731.T,BioPipeline)。
- **Vehicle quality / 标的质量:** **半 pure-play (HCI 板块) + diagnostics 拖累**。Revvity 2023 拆分自 PerkinElmer 后核心是 life sciences + diagnostics 双轮,Diagnostics 在 Q4 2024 拖累整体 (中国 IVD market 疲软)。**Imaging 是 RXRX 平台扩张的硬约束 — Recursion 每多收一个 Roche map option,就要扩 Opera Phenix fleet**,这条供需链在 RVTY 业绩上能看到 ~6 个月滞后的 lift。

> - **Beckman Coulter Echo 525 acoustic dispensers + Biomek FX** — 高通量化合物 / antibody 处理,SDGR FEP+ "design–make–test" 循环里 "make" 环节的标准设备。
  - **Leica Mica / SP8 X confocal** — 在 RXRX 类 phenomics 客户中做 secondary 验证。
- **Market cap + scale / 市值 + 规模:** ~$165–175 B (2026Q1)。FY24 revenue ~$23.9 B,Bioprocessing (~$8 B) + Diagnostics + Life Sciences。员工 ~63,000。**bioprocessing 板块 2024H2 触底反弹,2025–2026 是上升周期**。

> - **HK + 无锡 + 爱尔兰 Dundalk + 美国 MA + 新加坡 GMP 产能** — 总产能 ~430 KL (2025 末),全球前三大生物药 CDMO。
  - 直接已知合作:ABCL 的 LY-CoV555 (bamlanivimab) 部分供应、多个 Lilly/Pfizer ABCL-derived programs。SDGR 暂无直接合作 (其 antibody 工作刚起步)。RXRX 部分小分子项目走 WuXi STA (兄弟公司)。
- **Market cap + scale / 市值 + 规模:** ~HKD 60–80 B (~$8–10 B USD,2026Q1)。FY24 revenue ~RMB 18.7 B (~$2.6 B USD)。员工 ~11,000+。**估值长期被 Biosecure Act + 美中地缘政治 overhang 压制 — P/E 一度从 80× 跌到 15×**。

> | Device — optofluidic | BRKR | $8 B | 中强 (Beacon = ABCL 必需) | 4/10 |
| Device — HCI imaging | RVTY | $13 B | 中强 (Opera = RXRX 必需) | 4/10 |
| Module — bioprocess | DHR | $170 B | 弱-中 (Cytiva 7% diluted) | 2/10 |

> | System — CDMO | 2269.HK | $9 B | 强 (ABCL 兑现物理路径) | 7/10 ⚠ geo risk |
| Integrator — platform | ABCL/SDGR/RXRX | $1.0–1.8 B 各 | 100% (本 dive 主体) | 10/10 |

> - NVDA / DHR / TMO 都是"sympathy beneficiary",AI antibody 故事在它们的 P&L 上稀释到几乎不可见 → **不应该用它们押注本 dive 的 thesis**。
- BRKR (Beacon → ABCL) 和 RVTY (Opera Phenix → RXRX) 是有意义的 second-derivative,但仍非 pure play。
- **2269.HK / 207940.KS 是物理路径瓶颈** — ABCL 13 个 IND-stage 分子兑现到 commercial 一定经手生物药 CDMO,这是 round 2 缺失的"下游隐含 lever"。

> **2. 与 round 1/2 一致性确认:**
- Round 1 已确立三家平台技术异质性,链条公司也据此分化:Beacon 卖 ABCL,Opera 卖 RXRX,**SDGR 几乎没有专属硬件供应商** (因为 SDGR 本身是软件 + cloud GPU stack — 这正是 round 2 强调 SDGR 唯一具备 "现金流可见性" 的另一面解释:**它不依赖资本品 capex 周期**)。
- Round 2 警示的 "把这赛道挂到 hyperscaler capex 是叙事拉伸" 在 round 3 得到量化:NVDA biopharma 收入 < 数据中心 1%,**用 NVDA 押注 AI antibody = 用航母赌一个游艇泊位的潮汐**。

> # Round 4 / 第四轮 — Falsification + Synthesis / 证伪 + 综合判断
**Topic:** AI antibody discovery — ABCL + RXRX + SDGR
**Date:** 2026-05-06

> - **可验证位置:** RXRX 8-K + Roche Pharma Day 投资者材料 (通常 9 月);Roche 历年披露的 deal 表里有 "Recursion collaboration status"。
- **为何能证伪:** Round 2 已识别 RXRX 的客户集中度风险 — Roche/Genentech 占累计 collab revenue 50%+,且 2024-08 的扩展行权是 "platform 验证最强信号"。**Roche 是全球唯一一个对 phenomic 平台**真金**下注超过 $300 M 的大客户**。如果这个客户开始减速行权,等于市场上**唯一 informed buyer 用脚投票**,RXRX 平台 thesis 失血最快的伤口。

> - **可验证位置:** RXRX 8-K + Roche Pharma Day 投资者材料 (通常 9 月);Roche 历年披露的 deal 表里有 "Recursion collaboration status"。
- **为何能证伪:** Round 2 已识别 RXRX 的客户集中度风险 — Roche/Genentech 占累计 collab revenue 50%+,且 2024-08 的扩展行权是 "platform 验证最强信号"。**Roche 是全球唯一一个对 phenomic 平台**真金**下注超过 $300 M 的大客户**。如果这个客户开始减速行权,等于市场上**唯一 informed buyer 用脚投票**,RXRX 平台 thesis 失血最快的伤口。
- **细节:** Roche 行权频率 2022–2024 平均 2–3 次/年,2025 至今 (2026-05-06) 已知 1 次。**全年 ≤ 1 次会显著低于历史 cadence**,即使没有正式 "终止" 表述。

> - **可验证位置:** JUMP-CP GitHub + Nature Methods / Nature Biotech 论文 (2025–2026 预期发表);Broad Institute Carpenter Lab 主页 publication list。
- **为何能证伪:** Round 1 已警示 Recursion 自报数据 vs. 外部 OOD 数据集的 ~20–40% performance drop 风险,但**目前没有第三方权威基准**让买方能打假。一旦 JUMP-CP 出官方 benchmark 且 RXRX/Insitro 模型在跨批次 reproducibility 上**显著落后于纯 self-supervised baselines (DINO-v2, MAE)**,"phenomic moat" 叙事 (50 PB 数据 = 不可复制) 立即失去技术支撑 — 这正是 round 2 提到的 "RXRX 几乎全部市值是 platform option value" 的核心。
- **校准:** 此 trigger 是 **round 1 的技术弱点 round 4 量化版**。如果 benchmark 显示 RXRX 模型 F1 > 0.5 且优于 baseline,反而是 strong 反向 confirmation,需要把 RXRX 估值上调。

> - **为何能证伪:** Round 1 已警示 Recursion 自报数据 vs. 外部 OOD 数据集的 ~20–40% performance drop 风险,但**目前没有第三方权威基准**让买方能打假。一旦 JUMP-CP 出官方 benchmark 且 RXRX/Insitro 模型在跨批次 reproducibility 上**显著落后于纯 self-supervised baselines (DINO-v2, MAE)**,"phenomic moat" 叙事 (50 PB 数据 = 不可复制) 立即失去技术支撑 — 这正是 round 2 提到的 "RXRX 几乎全部市值是 platform option value" 的核心。
- **校准:** 此 trigger 是 **round 1 的技术弱点 round 4 量化版**。如果 benchmark 显示 RXRX 模型 F1 > 0.5 且优于 baseline,反而是 strong 反向 confirmation,需要把 RXRX 估值上调。

> - **可验证位置:** FDA Federal Register + CDER GfPs (Guidance for Industry) 列表;BIO/PhRMA 公开提交的 comment 文件。
- **为何能证伪 / 反向重估:** Round 1 已点出 "regulatory novelty 风险" (de-novo 流程审稿周期可能 +6–12 个月)。如果 FDA 把要求落地到具体审评流程,**ABCL/SDGR 这种 hybrid wet-AI 流程问题不大** (训练数据有湿实验 ground truth + 标准 process dev) — **反而对 RXRX/Generate/Absci 的纯 in-silico 路径冲击大**。这个 trigger 命中会**重新分配三家估值**:ABCL/SDGR 得益 (regulatory moat),RXRX/纯 de-novo player 受损。
- **重要:** 这条不是单向证伪,是 **path-dependent re-rating**。如果 guidance 偏松 (只要求披露,不要求强制 re-validation),则全行业受益,反而加速 inflection。

## From tech_dive #44: 技术深挖: Foundation models for protein structure prediction pos...
_2026-05-07T03:17_

> - **Insilico Medicine** — **INS018_055 (TNIK / IPF)** is the **first fully AI-generated drug to reach Phase II**: Phase IIa initiated June 2023, full enrollment Feb 2024.
- **Recursion (RXRX)** — **NVIDIA $50M July 2023** for **BioHive-2** (first DGX H100 SuperPOD in pharma); Roche/Genentech $150M Dec 2021; Tempus data deal Nov 2023.
- **Isomorphic Labs (DeepMind spinout)** — Jan 2024: **Lilly $45M upfront / up to $1.7B** + **Novartis $37.5M / up to $1.2B**, both gated on AF3-class platform.

## From tech_dive #49: 技术深挖: AI antibody discovery commercial inflection: AbCellera...
_2026-05-07T04:52_

> # 技术深挖 / Tech deep-dive: AI antibody discovery commercial inflection: AbCellera (ABCL) + Recursion (RXRX) + Schrödinger (SDGR) -- which platform has the cleanest first-in-class IND from AI design, what's the validation evidence, and how to size the pre-clinical pipeline

> > Scope note: 用户问题聚焦三家 — ABCL / RXRX / SDGR。但严格来说,只有 **AbCellera (ABCL)** 是 antibody-native 平台;RXRX 是 phenomic / small molecule 为主,SDGR 是 physics-based small molecule(近年在向 biologics 拓展)。本轮按"AI 抗体发现"通用技术栈写,后续轮次会拆分到具体公司。

> **关键事实(下一轮要用)**:在 ABCL / RXRX / SDGR 三家中,只有 **ABCL 有 AI-platform–attributable 的临床抗体**(bamlanivimab,2020),而真正的"first-in-class IND from AI design (antibody)"行业基准点是 **Absci ABS-101 (2024Q1)** — 不是这三家。这个对比将决定 round 2 (business closed loop) 的估值锚定方式。

> > 三家公司商业模式差异极大,不能用同一把尺子测量。本轮先按 ABCL / RXRX / SDGR 各自拆解,再合并到 customer / time-to-revenue 维度对比。

> **RXRX (subscription-flavored R&D + 合并后的 dual-engine)**
- 钱链:**Roche/Genentech (2021, $150M upfront, $300M+ extension 2025),Bayer (2020, $30M upfront),Sanofi (post-Exscientia legacy, $150M upfront 2022),BMS (Exscientia legacy, $50M+),Merck KGaA → RXRX**,形式 = upfront + research funding (FTE-based) + milestones + royalty。

> **RXRX (subscription-flavored R&D + 合并后的 dual-engine)**
- 钱链:**Roche/Genentech (2021, $150M upfront, $300M+ extension 2025),Bayer (2020, $30M upfront),Sanofi (post-Exscientia legacy, $150M upfront 2022),BMS (Exscientia legacy, $50M+),Merck KGaA → RXRX**,形式 = upfront + research funding (FTE-based) + milestones + royalty。
- Roche deal 是行业最大 biobuck:**up to $12B in milestones across 40 programs**(neuroscience + GI oncology),已 trigger 一笔 $30M operational milestone(2024)。

> - Roche deal 是行业最大 biobuck:**up to $12B in milestones across 40 programs**(neuroscience + GI oncology),已 trigger 一笔 $30M operational milestone(2024)。
- RXRX → 上游:NVIDIA H100/H200 (BioHive-2 supercomputer, ~512 H100s,2024 上线)+ Tempus 临床数据 + Helix LLM partnership(genome-scale foundation model)。Compute 是最大单项 OPEX。
- **2024 全年 revenue $59M**(80% 来自 collaborations,主要是 Roche + Bayer FTE 支付),**无 royalty 现金到账**(全部 milestone 都是 pre-clinical / Ph1 阶段)。

> - SDGR → 上游:GCP / AWS compute(physics-based FEP+ 计算密集)+ in-house wet lab(自 2020 建于 Framingham, MA),用于实验回灌 ML training。
- **现金流逻辑独特**:software 收入支付绝大部分 OPEX,drug-discovery royalty 是 free option;ABCL/RXRX 没有这个 software cushion。

> **RXRX inflection 更远**
- Roche/Bayer 体系下,milestone $300M+ realized 才能覆盖 $300–400M/year burn。这要 **3–5 个 IND + 至少一个 Ph2 readout** — 最早 2027–2028。

> - Pfizer "Charlie" — internal AI infra,$500M+ accumulated。
  - Roche/Genentech — $150M+ upfront to RXRX,$200M+ Recursion equity stake。
  - Lilly — $700M+ multi-year commitment to ABCL platform deals(累计公开数额);自建 OpenAgentic 类内部 AI biology team。

> **RXRX — 双 anchor, post-Exscientia 适度分散**
- Roche/Genentech 单家在 RXRX collab 收入占比 **~50%**(2024)。Bayer ~20%。Sanofi(Exscientia legacy)~15%。

> **RXRX — 双 anchor, post-Exscientia 适度分散**
- Roche/Genentech 单家在 RXRX collab 收入占比 **~50%**(2024)。Bayer ~20%。Sanofi(Exscientia legacy)~15%。
- 12B Roche biobuck 是支撑 RXRX market cap 的核心 narrative,**Roche 单边退出 → RXRX 估值切半 not impossible**(参考 2023 Pfizer 终止部分 RXRX collab 时的 -25% 单日反应)。

> - Roche/Genentech 单家在 RXRX collab 收入占比 **~50%**(2024)。Bayer ~20%。Sanofi(Exscientia legacy)~15%。
- 12B Roche biobuck 是支撑 RXRX market cap 的核心 narrative,**Roche 单边退出 → RXRX 估值切半 not impossible**(参考 2023 Pfizer 终止部分 RXRX collab 时的 -25% 单日反应)。
- Exscientia 合并稀释了一些集中度,但 BMS / Sanofi / Merck KGaA 三家也都 Big-3 风险敞口。

> **RXRX**
- 当前 revenue ~$60M(2024),全部是 collab funding,**真正第一笔有意义 development milestone 在 2025–2026**(Roche neuroscience programs 进 IND)。

> 1. **三家中只有 SDGR 有 software-grade 现金流**(2024 $180M ARR);ABCL / RXRX 都是 milestone-binary 模型,任何一年现金流可以 swing $50M+。
2. **ABCL 的真正护城河不是 AI**,是 Trianni mice + Beacon + 89 partner book + 即将上线的 GMP CDMO 一体化 — AI 是 marketing wrapper,核心是 microfluidic single-B-cell 物理资产。

> 2. **ABCL 的真正护城河不是 AI**,是 Trianni mice + Beacon + 89 partner book + 即将上线的 GMP CDMO 一体化 — AI 是 marketing wrapper,核心是 microfluidic single-B-cell 物理资产。
3. **RXRX 是 narrative-heavy, milestone-poor**:$12B biobuck 名义巨大,NPV-discounted 后 << market cap implied;真正 cash inflection 在 2027 之后。
4. **第一个真正"AI-designed first-in-class antibody IND"在三家中并未发生** — Absci ABS-101 (2024Q1) 仍是行业基准。三家中最接近的是 ABCL(89 个 partner program 中至少 5 个披露含 AI lead-opt),但 attribution 弱。

> 4. **第一个真正"AI-designed first-in-class antibody IND"在三家中并未发生** — Absci ABS-101 (2024Q1) 仍是行业基准。三家中最接近的是 ABCL(89 个 partner program 中至少 5 个披露含 AI lead-opt),但 attribution 弱。
5. **Customer concentration 排序**:RXRX (Roche 50%) > ABCL (Lilly 30%+) > SDGR (top-1 <10%)。

> > Scope: AI 抗体发现链条 vertical 至少 5 层 — compute substrate → wet-lab instrument → consumable/reagent → AI platform → bioprocessing → big pharma integrator。ABCL / RXRX / SDGR 都挤在 platform 这一层,所以本轮把视野放大到上下游各层各取 cleanest pure-play,再回头给三家做 head-to-head ranking。

> - **Layer**: GPU substrate — AlphaFold-Multimer / RFdiffusion / ESMFold / IgLM / Chroma 推理与训练全部跑在 H100/H200/B100/B200 上
- **Specific product**: **DGX BioNeMo + H100/H200 SXM**;BioNeMo 是 NVIDIA 推的 protein/antibody foundation model framework(集成 ESM-2, OpenFold, MoLMIM),被 RXRX BioHive-2(~512 H100s)、ABCL 内部 cluster、ABSI 内部 cluster 直接用。H100 SXM ~$30k/unit,DGX SuperPOD multi-million
- **Scale**: 市值 ~$3.4T (2026Q1),FY2026 revenue ~$200B+,Healthcare vertical ARR <5% 但是 fastest-growing seg

> - Reagents critical-path: antibody library construction、PCR、cloning enzymes(Q5 polymerase, Gibson Assembly, 限制酶)
- 不可投资,但 ABCL / ABSI / RXRX 的 wet-lab 试剂账单 NEB 占 ~10–20%
- A-share 替代:**Vazyme (688105.SH)** 已上市,但海外 AI antibody 平台基本不用

> | 维度 | ABCL | RXRX | SDGR |
|---|---|---|---|

> | Direct AI-antibody comp | **ABSI 是真正头对头** | n/a | n/a |
| Vehicle quality for "AI antibody" thesis | **best of three(但 ABSI purer)** | **worst of three** — 买 RXRX 是买 phenomic + Roche option | **不是 antibody 票** — 买 SDGR 是买 software ARR + MALT1 binary |

> 2. **ABCL 的真护城河不是 AI**,是 **Bruker Beacon + Trianni mice + 89 partner book + Vancouver GMP** 的物理资产组合。任何 "AI-only" 进入者(ABSI / Generate / Xaira)在 wet-lab throughput 上都还匹配不了 ABCL
3. **RXRX 在 antibody 维度上是 misclassified** — antibody 在 RXRX 估值里 <10% 权重。如果用户问题焦点是抗体,RXRX 是错误纳入项
4. **SDGR 在 antibody 上几乎为零** — 2026–2027 内不会有 SDGR-attributed antibody IND。SDGR 的真实 thesis 是 software ARR + small molecule MALT1

> Round 3 完成 — 链条已经铺开:substrate (NVDA) → instrument (BRKR) → consumable (TXG) → AI platform pure-play (ABSI) → bioprocessing (RGEN) → integrator (LLY),加上三家本身。准备好就发 "下一轮" / "round 4" — 进入 **catalyst calendar + position sizing**(2026Q2–2027Q4 readouts / IND / milestone 日历,加上 conviction × time-to-readout 矩阵给 ABCL / ABSI / RXRX / SDGR 排仓位权重)。

> ### Trigger 3 — Roche reduces / restructures the RXRX $12B Recursion deal
- **What to watch**: Roche / RXRX 联合声明,任何形式的 "program scope reduction" / "milestone restructuring" / "termination of N programs out of 40"。也包括 Roche pharma R&D head(Hans Clevers / successor)在 JPM 或 R&D Day 上 explicitly downgrade Recursion 优先级

> ### Trigger 3 — Roche reduces / restructures the RXRX $12B Recursion deal
- **What to watch**: Roche / RXRX 联合声明,任何形式的 "program scope reduction" / "milestone restructuring" / "termination of N programs out of 40"。也包括 Roche pharma R&D head(Hans Clevers / successor)在 JPM 或 R&D Day 上 explicitly downgrade Recursion 优先级
- **Why this falsifies**: $12B biobuck 是 RXRX 当前 ~$2–3B 市值核心 narrative pillar。Roche 任何形式的 walk-back 都会 NPV-discount RXRX 估值至 cash + 残余 platform value(~$600M cash + $300–500M platform = $900M–1.1B)

> - **What to watch**: Roche / RXRX 联合声明,任何形式的 "program scope reduction" / "milestone restructuring" / "termination of N programs out of 40"。也包括 Roche pharma R&D head(Hans Clevers / successor)在 JPM 或 R&D Day 上 explicitly downgrade Recursion 优先级
- **Why this falsifies**: $12B biobuck 是 RXRX 当前 ~$2–3B 市值核心 narrative pillar。Roche 任何形式的 walk-back 都会 NPV-discount RXRX 估值至 cash + 残余 platform value(~$600M cash + $300–500M platform = $900M–1.1B)
- **Verifiable**: 8-K / Roche IR / 行业新闻(STAT, Endpoints)。**Pfizer 2023 部分终止 RXRX 合作时单日股价 -25% 是先例**

> - **Why this falsifies**: $12B biobuck 是 RXRX 当前 ~$2–3B 市值核心 narrative pillar。Roche 任何形式的 walk-back 都会 NPV-discount RXRX 估值至 cash + 残余 platform value(~$600M cash + $300–500M platform = $900M–1.1B)
- **Verifiable**: 8-K / Roche IR / 行业新闻(STAT, Endpoints)。**Pfizer 2023 部分终止 RXRX 合作时单日股价 -25% 是先例**
- **Threshold to act**: 任何 "deprioritize" / "wind-down" / 移除 program 数字披露

> - **What to watch**: Generate Chroma-platform 或 Xaira RFdiffusion-platform 抗体 in 2026–2027 拿到 FDA IND, 且 press release 明确表述 "fully generative" / "no B-cell starting material"
- **Why this falsifies the ABCL/SDGR/RXRX angle**: 如果 private 端 (Generate / Xaira) 比 ABCL 更快做出 cleanly-attributable AI-designed first-in-class IND,则 **ABCL "AI antibody leader" 公开市场标签被 reset 为"microfluidic CRO"**。同时 Generate/Xaira IPO 路径打开,稀释整个 AI antibody pure-play 估值池
- **Verifiable**: FDA orange book、ClinicalTrials.gov、公司 press release;Generate / Xaira IPO S-1 filing 也属同一 trigger

> **Cleanest entry now**: **ABCL** — 三家中唯一同时具备(i) AI/microfluidic 平台资产、(ii) 89-program partner book、(iii) ~$700M cash + 3 年 runway、(iv) Lilly 历史 royalty 已实战验证。**ABSI 更纯但 binary 风险过高**(单 trial 决定生死);RXRX 在 antibody 维度是 mis-classified;SDGR 不是 antibody 票。

## From tech_dive #50: 技术深挖: Foundation models for protein structure prediction pos...
_2026-05-07T05:01_

> - **Insilico Medicine (private; HK IPO refiled)** — PandaOmics target ID + Chemistry42 generative chemistry; **INS018_055** (TNIK inhibitor for IPF) is the **first fully AI-generated drug to reach Phase II** — Phase IIa initiated **June 2023**, full enrollment **Feb 2024**.
- **Recursion (RXRX)** — AF2 fused with phenomics; **NVIDIA $50M investment July 2023** for the **BioHive-2** DGX H100 SuperPOD (first hyperscale-class DGX in pharma); Roche/Genentech $150M upfront Dec 2021; Bayer ~$50M; Tempus data-licensing deal Nov 2023; **Exscientia merger closed Aug 2024**.
- **Isomorphic Labs (DeepMind spinout)** — announced Jan 2024 with two simultaneous deals: **Eli Lilly $45M upfront + up to $1.7B milestones** and **Novartis $37.5M upfront + up to $1.2B milestones**, both explicitly gated on **AF3-class** platform delivery.

> Tier 1  AI-NATIVE DRUG DISCOVERY CO  (the asset-licensing layer — most margin)
        Isomorphic Labs (private) · Recursion (RXRX) · Insilico (private)
        Schrödinger (SDGR — partly here via collaborations) · AbCellera (ABCL)

> NVIDIA (GPUs + BioNeMo) · AWS/Azure/GCP (cloud) · Tempus (TEM, clinical-genomic data)
        10x Genomics (RXRX/TXG, single-cell data) · Veeva (CRM/eTMF rails)
                       │

> | **Sanofi → Insilico** | $21.5M upfront + up to **$1.2B** in milestones (USP1 etc.) | Aug 2022 |
| **Sanofi → Exscientia** (now part of RXRX) | $100M upfront + up to **$5.2B** milestones (15 programs) | Jan 2022 |
| **NVIDIA → Recursion** | **$50M** equity + GPU allocation (BioHive-2 H100 SuperPOD) | Jul 2023 |

> |---|---|---|---|
| **Recursion (RXRX)** | Roche/Genentech | ~**50%** of 2023 collab revenue | ~**90%** (Roche + Bayer + Tempus collab) |
| **Schrödinger (SDGR)** | Top-1 software customer ~7%; **but** drug-discovery collab revenue **highly concentrated** in BMS + Otsuka + Lilly | drug-discovery rev ~**50% one customer**; software more diversified | ~**70%** of drug-discovery rev top-3 |

> **(b) Tier 1 — AI-native drug discovery: UPFRONT NOW, MILESTONES BACK-LOADED**
- **Recursion (RXRX):** FY24 revenue **~$59M** (mostly Roche/Bayer collaboration recognition + Exscientia legacy Sanofi); cash burn ~$400M/yr; runway through ~2027. **Real Phase II/III milestone revenue is a 2027–2030 event**, not 2025–2026. Largest near-term inflection: REC-994 / REC-2282 / REC-4881 Phase II readouts in 2025.
- **Isomorphic Labs:** $82.5M total upfront recognized 2024 from Lilly + Novartis; **first $50–150M tranche of milestones plausibly 2026–2027** if AF3-class platform delivers IND-enabling structures on schedule.

> │        │        │        │        │        │        │
NVDA      TEM     RXRX     INSILICO   FIRST    AI-DRUG  
HEALTH    DATA    PH-II    PH-II      AI-DRUG  $1B/YR

> 中文:三层落账速度差异极大 —— **基础设施层(Tier 2)正在落账**:NVIDIA 医疗 ~$1B/yr、Tempus 数据授权 ~$140M/yr、Schrödinger 软件 ~$170M/yr;**AI 药企层(Tier 1)上游已落、里程碑后置**:Recursion FY24 营收仅 $59M、Isomorphic 2024 确认 $82.5M 上游、Insilico ~$50M/yr,**真正的 Phase II/III 里程碑现金窗口在 2026–2028**;**大药企卖药层(Tier 0)需到 2028–2032**:Insilico INS018_055 与 Recursion 几条 REC-资产可能在 2027–2028 出第一张"完全 AI 设计药物"FDA 批文,但要做到 $1B/yr 单品级别还要再 5–7 年(大概 2030+)。**所以"今天能买的现金流"在 NVIDIA、TEM、SDGR;"2026–2028 兑现的"是 RXRX 与 Isomorphic 的里程碑;"2030+ 才会出现的"是真正的 AI 药销售收入** —— 三个时间窗口对应三种估值范式。

> **Round 2 close.** 商业图景的关键点 —— **(1) 模型本身没钱**(全免费或 CC BY-NC),**钱在用模型产出的"减风险药物资产"**(Tier 1 上游 + 里程碑 + 销售提成);**(2) 单位经济拐点已在发生但只压到了 IND 阶段**,真正的胜负看 AI 是否能提升 Phase II→III 成功率,目前数据不支持;**(3) TAM 看似巨大但落到 AI 制药本身只有 ~$10B/yr 到 2030**,远小于 NVIDIA 数据中心 ~$115B/yr;**(4) Tier-1 AI 药企客户极度集中**,Lilly + Roche/Genentech 任一家策略转向都会撼动行业;**(5) 时间窗口三段** —— NVIDIA / TEM / SDGR 现金流今天就在,RXRX / Isomorphic 里程碑窗口 2026–2028,真正的 AI 药销售要到 2030+。

> Round 3 应该聚焦**公开市场可投标的:股票链 + 估值 + 触发条件 + 风险事件清单**(NVDA / TEM / SDGR / RXRX / 以及 ABCL、TXG、CRL/WuXi 的可投性)。Ready when you say go.

> ## 4. RXRX / Recursion Pharmaceuticals — Nasdaq

> - **竞争 / Competitors:** **Adagene**(私有 / 退市)、**Twist Bioscience (TWST)**(基因合成端)、**Absci (ABSI)**(生成式抗体设计 + AstraZeneca 合作)、**Genmab (GMAB)**(成熟抗体平台)、中国侧 **百济神州 (BGNE)** 部分。
- **载体质量 / Vehicle quality:** **抗体方向最纯的 "AI + 实验" 整合票**,补 AF 系软肋;但里程碑回款节奏比 RXRX 更碎片化、单笔小。**作为 protein-design 主题的次要 vehicle 还可,作主仓不够厚**。

> - **量级 / Scale:** 市值 **~HK$10–15B(~$1.3–2B USD)区间**;FY23 营收 ~¥175M(USD ~$24M),亏损;员工 ~900;客户包括辉瑞、礼来、强生及 ~150 家中小 biotech。
- **竞争 / Competitors:** **Schrödinger (SDGR)**(直接对位)、**Recursion (RXRX)**、**英矽智能 Insilico**(私有)、**成都先导 688222.SH**(DEL 库 + AI)、**药石科技 300725.SZ**(化学库 + AI)。
- **载体质量 / Vehicle quality:** **港股侧最纯的 "AI 药物发现 + 平台 SaaS" 票**,且按中国制造业成本结构跑;但**营收尚小、盈利路径未验证、国际化客户结构受中美关系扰动**。**作为 A/H 投资人表达 AF 主题的可选载体,但厚度不够,更适合作为 RXRX/SDGR 的对照仓位**。

> - **竞争 / Competitors:** **Schrödinger (SDGR)**(直接对位)、**Recursion (RXRX)**、**英矽智能 Insilico**(私有)、**成都先导 688222.SH**(DEL 库 + AI)、**药石科技 300725.SZ**(化学库 + AI)。
- **载体质量 / Vehicle quality:** **港股侧最纯的 "AI 药物发现 + 平台 SaaS" 票**,且按中国制造业成本结构跑;但**营收尚小、盈利路径未验证、国际化客户结构受中美关系扰动**。**作为 A/H 投资人表达 AF 主题的可选载体,但厚度不够,更适合作为 RXRX/SDGR 的对照仓位**。

> - **竞争 / Competitors:** **Roche RHHBY**(Recursion $12B 单笔最大签字方);**Novo Nordisk (NVO)** GLP-1 直接对手;**Pfizer (PFE)、Merck (MRK)、BMS、Sanofi (SNY)、Novartis (NVS)** AI 合作活跃但规模 / 频率低于 Lilly。
- **载体质量 / Vehicle quality:** **绝对不是 AF 主题 vehicle** — Lilly 股价由 GLP-1 销售曲线、专利悬崖、价格谈判主导;**但作为 "理解 AI-pharma 需求侧" 的必读公司**,任何 RXRX/SDGR/Isomorphic 估值都隐含 Lilly 持续买入的假设。**作为 sentinel signal 持有,而非 vehicle**。

> - **不可投性:** Alphabet 全资,无独立股权;**间接 vehicle = GOOG / GOOGL**,但 Isomorphic 在 GOOG 万亿级营收中是隐藏单元(<<1%),稀释到失效。
- **为什么重要:** AF3 平台进展决定 Tier-1 整体节奏 — Isomorphic 若在 2026–2027 兑现首批 Lilly/Novartis IND,会**直接重定价 RXRX 与 SDGR**(平台估值上调或下调 — 取决于"是 Isomorphic 独家"还是"AF3 同类成果泛在")。

> - **不可投性:** 港股 IPO 2023、2024 两度撤回,2025 重新提交但市况未明。
- **为什么重要:** **如 INS018_055 在 2026–2027 Phase IIb 读数为正,是整个 AI-pharma 主题的概念性催化** — 可能比 RXRX 任何一项 REC-xxxx 读数更具市场说服力(因其叙事更纯)。**应建仓位列入 watchlist 的 Phase II 读数日历最前**。

> - **不可投性:** 早期私有公司。
- **为什么重要:** 与 **Boltz-1**(MIT,2024-10)+ **HelixFold3**(Baidu BIDU,中国侧)一起,**让"AF3 类能力"在 2024-Q4 之后变成商品** — 这是 Round 1 / Round 2 预测过的"模型层无溢价"在 2025 年的进一步确证。**含义:Tier-2 模型层利润趋零 → 价值更确定地落到 Tier-1(资产)与 Tier-2(基础设施 + 数据)** — 这反过来强化 NVDA / TEM / RXRX / SDGR 论点。

> | **现金流"今天就在"的软件 SaaS** | **SDGR**(物理仿真 + AF 互补) | — |
| **2026–2028 里程碑兑现的 Tier-1** | **RXRX**(主题最纯,客户集中风险显性) | ABCL(抗体方向辅助) |
| **2027+ 首批 AI 设计药物 FDA 批文 sentinel** | Insilico Phase II 读数(私有,只看不买)| RXRX REC-xxxx 读数 |

> | **2026–2028 里程碑兑现的 Tier-1** | **RXRX**(主题最纯,客户集中风险显性) | ABCL(抗体方向辅助) |
| **2027+ 首批 AI 设计药物 FDA 批文 sentinel** | Insilico Phase II 读数(私有,只看不买)| RXRX REC-xxxx 读数 |
| **A/H 侧表达** | **2228.HK 晶泰科技** | 688222.SH 成都先导(辅助) |

> **最干净的三票组合(若必须选三):TEM + SDGR + RXRX** — 分别覆盖"数据"+"软件"+"资产",时间窗口梯度配置。**NVDA 不在此组合里 —— 它对此主题是稀释票。**

> Round 4(若继续)应聚焦 **公司 × 触发条件 × 风险事件日历**:具体到 RXRX 哪几个 Phase II 读数日、Isomorphic 首批 IND guidance、BIOSECURE 立法节奏、Insilico HK IPO 时间窗、Lilly AI 资本配置披露口径。Ready when you say go.

> **Where in the cycle / 周期位置:** Not in the "before-it-20x" zone for the platform-software layer — that already 5–10×'d in 2020–2023 (RXRX peak ~$11B FDV, SDGR peak ~$7B); model layer commoditization confirmed Q4 2024 by Chai-1 / Boltz-1 / HelixFold3 (Round 1 §4). **Still pre-inflection at the asset layer:** zero AI-designed drugs FDA-approved as of session date; first plausible approval 2027–2028; first $1B/yr "AI drug" 2030+. So the trade is **buying through the pre-revenue valley** at depressed Tier-1 multiples — it is *unloved*, not crowded.

> **Cleanest entry / 最干净敞口:** **TEM (Tempus AI)** — Tier-2 data layer, ~$140M/yr data-licensing run-rate growing >35% YoY, the only book-now revenue with low milestone dependency. **Would NOT own:** at >$15–18B market cap (>~25× data-licensing run-rate), or if oncology NGS reimbursement headlines (CMS LCD changes) hit the ~80% testing-revenue base. The investable bet on the *thesis* is TEM + SDGR + RXRX (data + software + asset), not NVDA.

## From tech_dive #51: 技术深挖: AI clinical trials operations: Tempus AI (TEM) + Veeva...
_2026-05-07T05:17_

> [Data + AI]       TEM   RHHBY (Flatiron + FMI)  GH  EXAS
[Customer]        RXRX  AZN  GSK  PFE  MRK
[Cloud host]      MSFT  AMZN  GOOGL

> | 6 | **300347.SZ** Tigermed / SZSE | China clinical CRO | ~$0.9–1B rev / ~$5–6B mcap | Cheap call option on China trial-volume normalization |
| 7 | **RXRX** Recursion / NASDAQ | Demand-side validator | ~$60M rev / ~$1.5–2.5B mcap | Not a vehicle — signal that AI biotechs use the stack |
| 8 | **RHHBY** Roche / OTC | Owns Flatiron + FMI | ~$220–250B mcap | TEM short-hedge only; otherwise too diluted |
