# SDGR -- 综合提取 / All mentions across our research

_Aggregated from 91 mentions across 4 reports. Auto-generated; rerun via `python scripts/compress_dives_to_companies.py`._

---

## From tech_dive #43: 技术深挖: AI antibody discovery commercial inflection: AbCellera...
_2026-05-07T03:10_

> # 技术深挖 / Tech deep-dive: AI antibody discovery commercial inflection: AbCellera (ABCL) + Recursion (RXRX) + Schrödinger (SDGR) -- which platform has the cleanest first-in-class IND from AI design, what's the validation evidence, and how to size the pre-clinical pipeline

> # Round 1 / 第一轮 — Technology Closed Loop / 技术闭环
**Topic:** AI antibody discovery — ABCL + RXRX + SDGR
**Date:** 2026-05-06

> - **Phenomics + foundation model (RXRX 主战场).** Cell Painting 染色 → 高内涵成像 → 数百万 perturbation × cell line 矩阵 → 用 MolE / Phenom-Beta 自监督模型把图像嵌入到 ~1024 维表征空间,再用 contrastive learning 找 "这个化合物/基因敲低的表型 = 那个已知药物的表型" 的 map-of-biology。底层算力是 NVIDIA H100 集群 BioHive-2 (~2 EFLOPS FP8)。这条线**不是抗体专属**,而是从表型反推靶点 + 苗头化合物。
- **Physics-first + ML (SDGR 主战场).** FEP+ (free-energy perturbation) 用炼狱级 MD 算配体–靶点结合自由能,误差 ~1 kcal/mol;WaterMap 算结合口袋脱水罚分;近 3 年挂上 active learning + graph NN,把 FEP+ 当作 "ground-truth 标签机" 去训练快速代理模型,使得每周可以打 10⁵ 分子量级而不是 10² 量级。**主战场仍是 small molecule**,2023 起把同一栈延伸到 antibody Fv–antigen 结合面 (LiveDesign Biologics)。

> - **Phage / yeast display (1985–).** 组合文库 (10⁹–10¹¹ 多样性) 显示在噬菌体或酵母表面,生物淘选 (panning) 出 binder。Adimab / MorphoSys / Genmab 是代表。问题是文库偏倚 + epitope coverage 受限 + 需要 4–6 轮淘洗。
- **Brute-force HTS (small molecule 平行物).** 物理筛 10⁶ 化合物库,命中率 0.01–0.1%,贵且低效 — SDGR 的 FEP+/AL 直接打这个范式。

> 所以本 dive 的"老 incumbent"按平台对应是: **ABCL/Generate/Absci → 替代 hybridoma + phage display**;**SDGR → 替代 HTS + 经典 SBDD**;**RXRX → 替代 target-first reductionist drug discovery (本身是个 paradigm shift,不仅是工艺替换)**。

> - **Developability up-front.** 训练好的 liability 预测器 (PTM 位点、聚集、polyspecificity、CMC) 把候选过滤前置,GMP 后期 attrition 报告下降 **~30–50%** (Adimab vs ABCL 公开会议数据,口径不一致需谨慎)。
- **Cost per de-risked lead.** SDGR 在 Nimbus TYK2 项目 (NDI-034858) 公开:用 FEP+ 替代部分湿实验合成,合成–评估化合物数 **~10× 下降**,Takeda 2023 年以 **$4 B 上限** 收购该资产,反向定价了平台节约的开发成本。

> - **数据 moat 假象.** Recursion 宣称 ~50 PB 表型数据,但 Cell Painting 信号 SNR 在跨批次/跨实验室时 effect size 会缩水 ~3–5×;模型在自家数据 work,在外部 OOD 数据集 (JUMP-CP) 上 performance drop 报告 ~20–40%。
- **Regulatory novelty 风险.** FDA 目前没有 "AI-designed therapeutic" 的专门 guidance;CDER 在 2024 RFI 里要求披露训练数据 + model versioning + 性能漂移监控,实操上对 SDGR/ABCL 已商业化的 hybrid 流程影响小,但对纯 de-novo (Generate/Absci) 的 IND 包审稿周期可能 +6–12 个月。

> - **ABCL 合作管线规模.** ABCL 2024 10-K: **>110 partner-initiated 项目**,**13 个 IND-stage 分子在合作方手中**,合作方包括 Lilly、Pfizer、Merck KGaA、Regeneron、Moderna。其中第一个 ABCL 自有共同开发 (T20 program) 2025 年进入 IND-enabling。
- **Schrödinger × Nimbus TYK2.** NDI-034858 (oral allosteric TYK2,后名 zasocitinib) 的 hit-to-lead 由 SDGR FEP+ 主导。**2022-12 Takeda 以 $4 B upfront + earn-outs 收购该资产**;Phase 2b psoriasis 数据 (PASI 75 ~67% at 15 mg) 公布于 2022 EADV。这是迄今 **AI/物理模拟驱动药物发现获得 commercial 验证的最大单笔交易**。
- **Schrödinger 自有管线.** SGR-1505 (MALT1, Phase 1, NHL),SGR-2921 (CDC7, Phase 1, AML),SGR-3515 (Wee1/Myt1, Phase 1, solid tumor) — 三个均为 in-house 用 LiveDesign 设计,2023–2024 进入临床。

> **Round 1 闭合判断:** 技术层面三家差异比"AI drug discovery"这个 umbrella 词暗示的大得多 — ABCL 是 **wet-AI hybrid (binder discovery)**,SDGR 是 **physics + ML (affinity optimization)**,RXRX 是 **phenomics map-of-biology (target ID)**。后续 round 评估"first-in-class IND from AI design"时必须按各自定义打分,不能用同一把尺。**最干净的"AI-designed first-in-class IND"候选应优先看 SDGR 自有管线 (SGR-1505/2921/3515) 和 ABCL 即将进入 IND 的 T20**;RXRX 的临床资产更接近 repurposing,**不是 round 命题想要的"AI 设计的新分子"**。

> # Round 2 / 第二轮 — Commercial Closed Loop / 商业闭环
**Topic:** AI antibody discovery — ABCL + RXRX + SDGR
**Date:** 2026-05-06

> ### SDGR chain (software + co-discovery hybrid / 软件 + 共研)
```

> ▼
Schrödinger Inc. (SDGR)
   │  ⇣ COGS 主要是工程 + 算力

> ```
**Key point / 关键点:** SDGR 是三家里**唯一软件订阅占大头**的:2024 软件收入 $156 M (FY24, +13% YoY),drug discovery / collab 是脉冲式 ($25–60 M / yr 取决于 Nimbus-类资产卖出年份)。Nimbus TYK2 (zasocitinib) 卖给 Takeda 的 $4 B 上限交易,SDGR 通过 ~3–4% 持股 + 服务费分成,**到手已确认 ~$147 M 现金 (2023 年)**,这是公司至今**单一最大 collateral cash event**。

> ### SDGR: Cost-per-de-risked-clinical-candidate / 单个进 IND 候选成本
- **Incumbent (传统 medchem + DMPK):** 单个 IND-ready 小分子 ~$10–30 M discovery 阶段成本,合成 ~3,000–5,000 化合物。

> - **AI antibody 子赛道:** 全球年开 ~6,000–7,000 个 discovery 项目,其中抗体类 ~25% = ~1,700 个/年。AI 渗透 (含 ABCL/Adimab AI-augmented/Generate/Absci/EvolutionaryScale) ~12% → **~200 个 AI 主导抗体项目/年**,单价 $1.5–3 M → **~$400 M / yr program-fee 池**。**这是 ABCL 真正的"碗"**。
- **AI 软件 (FEP/MD/de-novo design):** Schrödinger + OpenEye + ChemAxon + Cresset 合计 ~$500 M / yr 软件订阅市场,SDGR 占 ~30%。
- **Phenomic / target-ID:** 估值最难,~$200–400 M / yr (Recursion + Insitro + Owkin + Valo 合计)。

> ### SDGR
- **软件 (track A):** 1,700+ commercial customers,top 20 pharma 全在用,前 10 客户约占 software revenue ~40%,**集中度低、续约率 >95%**,这是 SDGR 估值的"年金"部分。

> ### SDGR
- **软件 (track A):** 1,700+ commercial customers,top 20 pharma 全在用,前 10 客户约占 software revenue ~40%,**集中度低、续约率 >95%**,这是 SDGR 估值的"年金"部分。
- **共研 + 自有管线 (track B):** **极高集中**。Nimbus 单笔交易在 2023 年贡献 ~$147 M (~占当年总收入 60%+),没有 Nimbus-类事件的年份会出现 30–50% YoY 收入下滑。**这是 SDGR 营收最大波动源**,sell-side 估值时往往被低估。

> - **软件 (track A):** 1,700+ commercial customers,top 20 pharma 全在用,前 10 客户约占 software revenue ~40%,**集中度低、续约率 >95%**,这是 SDGR 估值的"年金"部分。
- **共研 + 自有管线 (track B):** **极高集中**。Nimbus 单笔交易在 2023 年贡献 ~$147 M (~占当年总收入 60%+),没有 Nimbus-类事件的年份会出现 30–50% YoY 收入下滑。**这是 SDGR 营收最大波动源**,sell-side 估值时往往被低估。
- **Risk:** SDGR 自有管线 (SGR-1505 等) 若 Phase 1/2 失败,既没有"asset value"也没有"validation halo",pure software 估值会被砍到 5–8× revenue (现 ~12×)。

> - **共研 + 自有管线 (track B):** **极高集中**。Nimbus 单笔交易在 2023 年贡献 ~$147 M (~占当年总收入 60%+),没有 Nimbus-类事件的年份会出现 30–50% YoY 收入下滑。**这是 SDGR 营收最大波动源**,sell-side 估值时往往被低估。
- **Risk:** SDGR 自有管线 (SGR-1505 等) 若 Phase 1/2 失败,既没有"asset value"也没有"validation halo",pure software 估值会被砍到 5–8× revenue (现 ~12×)。

> ### SDGR
- **Now (in-pocket):** 软件 $156 M FY24 + collab/milestone $69 M = **$225 M total FY24,YoY +20%**。**唯一一家已经有 stable, growing revenue base 的**。

> - **2025–2026:** Otsuka MALT1 (SGR-1505) 若读出 Phase 1 PoC,触发 ~$30–50 M milestone;Bayer 软件续约 + Lilly 软件扩展,软件部分 conservative +10–15% / yr。
- **2027–2028:** Nimbus TYK2 / zasocitinib FDA approval (Takeda 计划 2026/2027 BLA) 触发 SDGR earn-out 第二级 ~$50–80 M。SGR-2921 / 3515 临床读出。
- **判断:** SDGR 已 **time-to-revenue = 0 (在赚钱)**,问题在 GAAP profitability — 仍在烧钱搞自有管线,2026 前难看到 op profit。**估值 driver 是软件复合增速 + 单一 hit-pipeline event**,不是"等 IND"。

> - **2027–2028:** Nimbus TYK2 / zasocitinib FDA approval (Takeda 计划 2026/2027 BLA) 触发 SDGR earn-out 第二级 ~$50–80 M。SGR-2921 / 3515 临床读出。
- **判断:** SDGR 已 **time-to-revenue = 0 (在赚钱)**,问题在 GAAP profitability — 仍在烧钱搞自有管线,2026 前难看到 op profit。**估值 driver 是软件复合增速 + 单一 hit-pipeline event**,不是"等 IND"。

> - **已闭环且现金流可见:** **SDGR** > ABCL > RXRX。SDGR 是唯一同时具备 (a) recurring software revenue (b) 已变现的 platform-asset event (Nimbus) (c) 自有 IND 管线 三件套的标的。
- **Platform value vs. asset value 拆分 (sell-side 模型常见错误):**

> - ABCL 当前市值 ($1.0–1.2 B 区间) 隐含的 **platform value ~50%、partner royalty NPV ~30%、cash & T20 自有管线 ~20%**。市场对 royalty NPV 给的 discount 偏狠 (~25%/yr),空间在 partner asset Phase 2/3 读出。
  - SDGR 当前市值 ($1.5–1.8 B 区间) 隐含 **software (DCF, ~5–6× sales) ~$900 M + Nimbus tail ~$200 M + 自有管线 option value ~$300–500 M**。下行支撑在软件部分,上行依赖 SGR-1505 读出。
  - RXRX 当前市值 ($1.6–2.0 B,Exscientia 合并后) **几乎全部是 platform option value + cash**,asset NPV 接近 0(因为 REC-994 失败、其他还在 Phase 1/2)。**最高 beta、最大下行**。

> - **"AI-designed first-in-class IND" 商业兑现的 cleanest path:**
  - **SDGR 自有 SGR-1505 (MALT1 inhibitor)** — 已在 Phase 1 NHL,2026 上半年读出 dose-escalation,**这是三家平台里最接近"AI 设计 → 自有 IND → 商业里程碑"完整闭环的资产**。
  - **ABCL T20** — 仍在 IND-enabling,验证窗口 2027+。

> **Round 3 应聚焦:** 把上述 platform value vs. asset value 拆分映射到三家具体的可投资 catalyst calendar (2026–2028),并明确 sizing logic — 即在 pre-clinical pipeline 这一资产类别里,如何设定 ABCL : SDGR : RXRX 的相对权重 (含失败概率加权与单个 clinical readout 的 binary risk)。同时回答最初命题:**哪个平台的"first-in-class IND from AI design"最干净 + 有最强 validation evidence**。

> # Round 3 / 第三轮 — Public companies in the chain / 链条上的上市公司
**Topic:** AI antibody discovery — ABCL + RXRX + SDGR
**Date:** 2026-05-06

> ABCL/RXRX/SDGR 本身是 "integrator / platform" 层。**它们的上游不是一条链,而是三条几乎不重叠的链** (round 1/2 已建立),因此 round 3 的链条公司必须按 "为哪一家平台供货" 分别列。下表的颜色编码:🅰 = 主要供 ABCL 链,🅡 = RXRX 链,🅢 = SDGR 链,⚪ = 三家通吃。

> - **Specific SKU into this trend / 具体打入该趋势的产品:**
  - H100 / H200 / B200 GPUs — 用于 BioHive-2 (RXRX, ~63 K H100-equiv,公开为业界 top-10 industry HPC) 以及 SDGR 在 Google Cloud / AWS 上租用的 FEP+ 算力 (单 ligand-pair ~4–8 GPU-hour)。
  - **BioNeMo platform** — 把 ESM-2/3, AlphaFold-Multimer, RFdiffusion, MolMIM, DiffDock 打包成 inference microservices,通过 NIM 卖给 pharma + biotech AI team。NVDA 自报 BioNeMo 客户 >100 家 (2025 GTC),含 Recursion (战略持股)、Genentech、Insilico Medicine、Iambic Therapeutics。

> - **Market cap + scale / 市值 + 规模:** ~$3.5 T (2026Q1),FY25 (Jan 2026 财年结) revenue ~$170 B,**biopharma vertical revenue 估 ~$0.8–1.2 B / yr,< DC 收入的 1%**。
- **Top competitors / 主要竞争者:** AMD (AMD, MI300X — Meta + Microsoft 已采用,但 biopharma vertical 渗透极低)、Google TPU (内部自用,via GCP 租给 SDGR)、Intel Gaudi3 (INTC,几乎不在 biopharma 出现)。**实际意义上的"竞争对手"接近于零 — biopharma AI 已经 90%+ 锁在 CUDA + cuDNN + cuBLAS 栈**。
- **Vehicle quality / 标的质量:** **极度 diversified — 不是 AI antibody 的纯 play**。任何把 NVDA 当作 "AI 制药"敞口的论点都被 LLM/data-center cycle 稀释 ~99×。**Round 2 已警告: 把这条赛道挂到 hyperscaler capex 是 sell-side 叙事拉伸**。NVDA 在本 dive 中只能算 "macro tide,不是 alpha"。

> - **Cytiva ÄKTA chromatography systems + Xcellerex single-use bioreactors** — DSP / USP 平台,ABCL partner 项目从 IND-enabling 起开始消耗。
  - **Beckman Coulter Echo 525 acoustic dispensers + Biomek FX** — 高通量化合物 / antibody 处理,SDGR FEP+ "design–make–test" 循环里 "make" 环节的标准设备。
  - **Leica Mica / SP8 X confocal** — 在 RXRX 类 phenomics 客户中做 secondary 验证。

> - **HK + 无锡 + 爱尔兰 Dundalk + 美国 MA + 新加坡 GMP 产能** — 总产能 ~430 KL (2025 末),全球前三大生物药 CDMO。
  - 直接已知合作:ABCL 的 LY-CoV555 (bamlanivimab) 部分供应、多个 Lilly/Pfizer ABCL-derived programs。SDGR 暂无直接合作 (其 antibody 工作刚起步)。RXRX 部分小分子项目走 WuXi STA (兄弟公司)。
- **Market cap + scale / 市值 + 规模:** ~HKD 60–80 B (~$8–10 B USD,2026Q1)。FY24 revenue ~RMB 18.7 B (~$2.6 B USD)。员工 ~11,000+。**估值长期被 Biosecure Act + 美中地缘政治 overhang 压制 — P/E 一度从 80× 跌到 15×**。

> | System — CDMO | 2269.HK | $9 B | 强 (ABCL 兑现物理路径) | 7/10 ⚠ geo risk |
| Integrator — platform | ABCL/SDGR/RXRX | $1.0–1.8 B 各 | 100% (本 dive 主体) | 10/10 |

> **2. 与 round 1/2 一致性确认:**
- Round 1 已确立三家平台技术异质性,链条公司也据此分化:Beacon 卖 ABCL,Opera 卖 RXRX,**SDGR 几乎没有专属硬件供应商** (因为 SDGR 本身是软件 + cloud GPU stack — 这正是 round 2 强调 SDGR 唯一具备 "现金流可见性" 的另一面解释:**它不依赖资本品 capex 周期**)。
- Round 2 警示的 "把这赛道挂到 hyperscaler capex 是叙事拉伸" 在 round 3 得到量化:NVDA biopharma 收入 < 数据中心 1%,**用 NVDA 押注 AI antibody = 用航母赌一个游艇泊位的潮汐**。

> **3. Round 4 (若继续) 应聚焦:** 把 catalyst calendar (2026 SGR-1505 dose-escalation, 2026/2027 REC-2282 POPLAR 顶线, 2027 ABCL T20 IND) 与本 round 列出的链条公司财报节奏 (BRKR Q2 BSI 部门、RVTY Imaging guidance、2269.HK Biosecure 立法窗口) 对齐,产出 **可触发的 catalyst-by-catalyst 仓位调整 playbook**。同时给出对最初命题的最终 sizing 答案:**"AI-designed first-in-class IND" 最干净的 vehicle 仍是 SDGR 自有 SGR-1505 (per round 2 闭合),链条 sympathy 标的优先级 BRKR > RVTY > 2269.HK (如果地缘可控)**。

> # Round 4 / 第四轮 — Falsification + Synthesis / 证伪 + 综合判断
**Topic:** AI antibody discovery — ABCL + RXRX + SDGR
**Date:** 2026-05-06

> ### Trigger 1 — **SGR-1505 (MALT1, SDGR 自有) Phase 1 dose-escalation 在 2026H1 读出 (a) DLT 截断在 ≤ 3 dose level 或 (b) 客观应答率 ORR ≤ 5% 在 r/r NHL**

> - **可验证位置:** Schrödinger 8-K + ASH 2026 (Dec) / EHA 2026 (Jun) abstract,以及 ClinicalTrials.gov NCT05544929 进度更新。
- **为何能证伪:** Round 2 闭合判断把 "AI-designed first-in-class IND 最干净的 vehicle" 锚在 SGR-1505。如果 in-house FEP+/active-learning 设计的第一颗自有分子在最早的人体读出就显示**狭窄治疗窗 + 无 efficacy 信号**,那么 "SDGR = 唯一已闭环的 AI-designed asset" 这条 thesis 直接断。SDGR 估值的 platform-halo (~$300–500 M option value, round 3) 会被快速折掉。
- **校准注意:** SGR-1505 是 first-in-class 但 MALT1 靶点本身在 NHL 已有 multiple competitors (JNJ-67856633, MPT-0118),所以**靶点失败 ≠ 平台失败**,需要看 PK/PD 是否符合 SDGR 自报的 FEP+ 预测。如果 PK 偏差 > 3× predicted,**这才是技术证伪**;如果只是临床 efficacy 不足,**只是单分子证伪**。两者要分清。

> - **为何能证伪:** Round 2 闭合判断把 "AI-designed first-in-class IND 最干净的 vehicle" 锚在 SGR-1505。如果 in-house FEP+/active-learning 设计的第一颗自有分子在最早的人体读出就显示**狭窄治疗窗 + 无 efficacy 信号**,那么 "SDGR = 唯一已闭环的 AI-designed asset" 这条 thesis 直接断。SDGR 估值的 platform-halo (~$300–500 M option value, round 3) 会被快速折掉。
- **校准注意:** SGR-1505 是 first-in-class 但 MALT1 靶点本身在 NHL 已有 multiple competitors (JNJ-67856633, MPT-0118),所以**靶点失败 ≠ 平台失败**,需要看 PK/PD 是否符合 SDGR 自报的 FEP+ 预测。如果 PK 偏差 > 3× predicted,**这才是技术证伪**;如果只是临床 efficacy 不足,**只是单分子证伪**。两者要分清。

> - **可验证位置:** FDA Federal Register + CDER GfPs (Guidance for Industry) 列表;BIO/PhRMA 公开提交的 comment 文件。
- **为何能证伪 / 反向重估:** Round 1 已点出 "regulatory novelty 风险" (de-novo 流程审稿周期可能 +6–12 个月)。如果 FDA 把要求落地到具体审评流程,**ABCL/SDGR 这种 hybrid wet-AI 流程问题不大** (训练数据有湿实验 ground truth + 标准 process dev) — **反而对 RXRX/Generate/Absci 的纯 in-silico 路径冲击大**。这个 trigger 命中会**重新分配三家估值**:ABCL/SDGR 得益 (regulatory moat),RXRX/纯 de-novo player 受损。
- **重要:** 这条不是单向证伪,是 **path-dependent re-rating**。如果 guidance 偏松 (只要求披露,不要求强制 re-validation),则全行业受益,反而加速 inflection。

> **90 天 watch:** 跟踪 **SGR-1505 ASCO 2026 (5 月底–6 月初) abstract 是否披露 dose-escalation 期 expansion cohort 启动 + PK/PD 是否落在 SDGR FEP+ 自报预测的 ±20% 区间内**。这是 Trigger 1 的早期信号,远早于正式 Phase 1 顶线。

> **Cleanest entry:** **SDGR 本身**。Round 2 论证 SDGR 是唯一同时拥有 software ARR (~$156 M 复合 +13%) + 已变现 platform event (Nimbus $147 M 已到账) + 自有 IND 的标的;链条 sympathy (BRKR/RVTY/2269.HK) 都被稀释到 second-derivative。**不愿持有的情境:** SGR-1505 PK 偏离 FEP+ 预测 > 3×,或 SDGR software 续约率从 95%+ 跌破 90%(意味着 LiveDesign 商业化已被竞品蚕食)。

## From tech_dive #44: 技术深挖: Foundation models for protein structure prediction pos...
_2026-05-07T03:17_

> - **Pfizer** — AF2 in target triage, JPM Jan 2023.
- **Schrödinger (SDGR)** — AF2 structures into LiveDesign / FEP+; 10-K (2022, 2023).
- **Insilico Medicine** — **INS018_055 (TNIK / IPF)** is the **first fully AI-generated drug to reach Phase II**: Phase IIa initiated June 2023, full enrollment Feb 2024.

## From tech_dive #49: 技术深挖: AI antibody discovery commercial inflection: AbCellera...
_2026-05-07T04:52_

> # 技术深挖 / Tech deep-dive: AI antibody discovery commercial inflection: AbCellera (ABCL) + Recursion (RXRX) + Schrödinger (SDGR) -- which platform has the cleanest first-in-class IND from AI design, what's the validation evidence, and how to size the pre-clinical pipeline

> > Scope note: 用户问题聚焦三家 — ABCL / RXRX / SDGR。但严格来说,只有 **AbCellera (ABCL)** 是 antibody-native 平台;RXRX 是 phenomic / small molecule 为主,SDGR 是 physics-based small molecule(近年在向 biologics 拓展)。本轮按"AI 抗体发现"通用技术栈写,后续轮次会拆分到具体公司。

> - **Developability shift-left**:IgLM / AbLang2 把 "humanness score" 算进 lead selection,可把 humanization rounds 从 2–3 轮压到 0–1 轮(ABCL Trianni / OrthoMab data 暗示约 **30–50% 时间节省**)。
- **Multi-specifics**:bispecific / Fab-Fc 几何在传统平台需逐个工程化,生成模型可一次性给出 backbone + linker(SDGR PLD 在 IL-13 × IL-4Rα 案例做过 retrospective benchmark)。

> - **Generate Biomedicines GB-0669 / Chroma platform** — 2024 进入 Ph1,首批 generative-diffusion–designed mAb 之一。
- **Schrödinger PLD (Predictive Ligand Design)** 在 biologics 上仍以 retrospective benchmarks 为主,**尚无 SDGR 自研 antibody-IND**;SDGR 商业化仍以 small molecule 为主(MALT1 SGR-1505, CDC7 SGR-2921, Wee1 SGR-3515 均为小分子)。
- **Recursion** 的 antibody 工作主要通过 2023 Cyclica 收购 + 2024 Exscientia 合并后整合 — 仍处 platform-buildout 阶段,**无 AI-designed antibody IND 在手**;Recursion 的 IND(REC-994 CCM, REC-2282 NF2, REC-4881 FAP)均为 small molecule,且 AI 角色是 indication / repurposing,不是 de novo design。

> **关键事实(下一轮要用)**:在 ABCL / RXRX / SDGR 三家中,只有 **ABCL 有 AI-platform–attributable 的临床抗体**(bamlanivimab,2020),而真正的"first-in-class IND from AI design (antibody)"行业基准点是 **Absci ABS-101 (2024Q1)** — 不是这三家。这个对比将决定 round 2 (business closed loop) 的估值锚定方式。

> > 三家公司商业模式差异极大,不能用同一把尺子测量。本轮先按 ABCL / RXRX / SDGR 各自拆解,再合并到 customer / time-to-revenue 维度对比。

> **SDGR (software ARR + drug-discovery option value)**
- 钱链分两段:

> - 钱链分两段:
  - (A) **Software**:Pfizer, Merck, BMS, Lilly, AstraZeneca, Bayer, Novartis, Sanofi → SDGR,license + maintenance,multi-year ARR 模式。**2024 software revenue $180M, ~13% YoY,ACV/customer $1.6M, top-customer ACV >$5M**。这条是真现金流。
  - (B) **Drug discovery (collab + internal)**:Nimbus / BMS / Otsuka / Eli Lilly (CDC7) / Novartis 等,upfront + milestone + royalty;**Nimbus-Takeda TYK2 deal (2022, $4B upfront + $2B milestones)** 让 SDGR 拿到 ~$300M cash + equity payout(SDGR 持股 Nimbus),是 SDGR 历史最大单笔 milestone realization。

> - (A) **Software**:Pfizer, Merck, BMS, Lilly, AstraZeneca, Bayer, Novartis, Sanofi → SDGR,license + maintenance,multi-year ARR 模式。**2024 software revenue $180M, ~13% YoY,ACV/customer $1.6M, top-customer ACV >$5M**。这条是真现金流。
  - (B) **Drug discovery (collab + internal)**:Nimbus / BMS / Otsuka / Eli Lilly (CDC7) / Novartis 等,upfront + milestone + royalty;**Nimbus-Takeda TYK2 deal (2022, $4B upfront + $2B milestones)** 让 SDGR 拿到 ~$300M cash + equity payout(SDGR 持股 Nimbus),是 SDGR 历史最大单笔 milestone realization。
- SDGR → 上游:GCP / AWS compute(physics-based FEP+ 计算密集)+ in-house wet lab(自 2020 建于 Framingham, MA),用于实验回灌 ML training。

> - (B) **Drug discovery (collab + internal)**:Nimbus / BMS / Otsuka / Eli Lilly (CDC7) / Novartis 等,upfront + milestone + royalty;**Nimbus-Takeda TYK2 deal (2022, $4B upfront + $2B milestones)** 让 SDGR 拿到 ~$300M cash + equity payout(SDGR 持股 Nimbus),是 SDGR 历史最大单笔 milestone realization。
- SDGR → 上游:GCP / AWS compute(physics-based FEP+ 计算密集)+ in-house wet lab(自 2020 建于 Framingham, MA),用于实验回灌 ML training。
- **现金流逻辑独特**:software 收入支付绝大部分 OPEX,drug-discovery royalty 是 free option;ABCL/RXRX 没有这个 software cushion。

> **SDGR inflection 已部分发生**
- Software 业务 **gross margin ~75–80%**,2024 已贡献 $135M+ gross profit,接近覆盖 R&D ~$170M。**software 收入 break-even 估在 2027–2028**(按 ~13% growth + FX 中性测算)。

> - Software 业务 **gross margin ~75–80%**,2024 已贡献 $135M+ gross profit,接近覆盖 R&D ~$170M。**software 收入 break-even 估在 2027–2028**(按 ~13% growth + FX 中性测算)。
- Drug discovery 业务的 break-even 取决于 SGR-1505 MALT1 Ph2 数据(预计 2026H2)— 若 positive,SDGR 持有的 ~$100M+ 全经济权益是单笔可触发的 inflection。

> **SDGR — software 端最分散,drug-discovery 端集中**
- Software:**top 20 customers 占 software revenue ~60%**,但 top-1 (Pfizer) 估 <10%。客户多样,churn risk 低 — 这是 SDGR 估值最稳的护城河。

> **SDGR — software 端最分散,drug-discovery 端集中**
- Software:**top 20 customers 占 software revenue ~60%**,但 top-1 (Pfizer) 估 <10%。客户多样,churn risk 低 — 这是 SDGR 估值最稳的护城河。
- Drug discovery:Nimbus(SDGR 持股 ~5–7%)是历史最大单笔 realized,未来核心是 internal pipeline(SGR-1505 / 2921 / 3515)+ Otsuka MALT1 collab。**single-asset risk highest** 在 SDGR,因为 internal pipeline 是 binary readout。

> - Software:**top 20 customers 占 software revenue ~60%**,但 top-1 (Pfizer) 估 <10%。客户多样,churn risk 低 — 这是 SDGR 估值最稳的护城河。
- Drug discovery:Nimbus(SDGR 持股 ~5–7%)是历史最大单笔 realized,未来核心是 internal pipeline(SGR-1505 / 2921 / 3515)+ Otsuka MALT1 collab。**single-asset risk highest** 在 SDGR,因为 internal pipeline 是 binary readout。

> **SDGR**
- Software 是即时现金流,$180M 2024 → $215–230M 2026E。

> - Drug discovery 第一笔 transformational event = **SGR-1505 MALT1 Ph2 readout 2026H2**;若 positive,partnership/royalty 现金 ~$100–300M realizable in 2027–2028。
- Nimbus-Takeda TYK2 类似的"hidden royalty"在 SDGR equity-stake portfolio 还有 ~6–8 个未披露持股公司,2026–2028 可能有 1–2 笔 $50–200M 退出。

> 1. **三家中只有 SDGR 有 software-grade 现金流**(2024 $180M ARR);ABCL / RXRX 都是 milestone-binary 模型,任何一年现金流可以 swing $50M+。
2. **ABCL 的真正护城河不是 AI**,是 Trianni mice + Beacon + 89 partner book + 即将上线的 GMP CDMO 一体化 — AI 是 marketing wrapper,核心是 microfluidic single-B-cell 物理资产。

> 4. **第一个真正"AI-designed first-in-class antibody IND"在三家中并未发生** — Absci ABS-101 (2024Q1) 仍是行业基准。三家中最接近的是 ABCL(89 个 partner program 中至少 5 个披露含 AI lead-opt),但 attribution 弱。
5. **Customer concentration 排序**:RXRX (Roche 50%) > ABCL (Lilly 30%+) > SDGR (top-1 <10%)。

> > Scope: AI 抗体发现链条 vertical 至少 5 层 — compute substrate → wet-lab instrument → consumable/reagent → AI platform → bioprocessing → big pharma integrator。ABCL / RXRX / SDGR 都挤在 platform 这一层,所以本轮把视野放大到上下游各层各取 cleanest pure-play,再回头给三家做 head-to-head ranking。

> | 维度 | ABCL | RXRX | SDGR |
|---|---|---|---|

> | Direct AI-antibody comp | **ABSI 是真正头对头** | n/a | n/a |
| Vehicle quality for "AI antibody" thesis | **best of three(但 ABSI purer)** | **worst of three** — 买 RXRX 是买 phenomic + Roche option | **不是 antibody 票** — 买 SDGR 是买 software ARR + MALT1 binary |

> 3. **RXRX 在 antibody 维度上是 misclassified** — antibody 在 RXRX 估值里 <10% 权重。如果用户问题焦点是抗体,RXRX 是错误纳入项
4. **SDGR 在 antibody 上几乎为零** — 2026–2027 内不会有 SDGR-attributed antibody IND。SDGR 的真实 thesis 是 software ARR + small molecule MALT1
5. **Picks-and-shovels 安全玩法**: BRKR(Beacon)+ TXG(VDJ)+ RGEN(GMP fill-finish)— 但每个 AI 抗体 narrative 对它们整体股价的影响 <5%

> Round 3 完成 — 链条已经铺开:substrate (NVDA) → instrument (BRKR) → consumable (TXG) → AI platform pure-play (ABSI) → bioprocessing (RGEN) → integrator (LLY),加上三家本身。准备好就发 "下一轮" / "round 4" — 进入 **catalyst calendar + position sizing**(2026Q2–2027Q4 readouts / IND / milestone 日历,加上 conviction × time-to-readout 矩阵给 ABCL / ABSI / RXRX / SDGR 排仓位权重)。

> - **What to watch**: Generate Chroma-platform 或 Xaira RFdiffusion-platform 抗体 in 2026–2027 拿到 FDA IND, 且 press release 明确表述 "fully generative" / "no B-cell starting material"
- **Why this falsifies the ABCL/SDGR/RXRX angle**: 如果 private 端 (Generate / Xaira) 比 ABCL 更快做出 cleanly-attributable AI-designed first-in-class IND,则 **ABCL "AI antibody leader" 公开市场标签被 reset 为"microfluidic CRO"**。同时 Generate/Xaira IPO 路径打开,稀释整个 AI antibody pure-play 估值池
- **Verifiable**: FDA orange book、ClinicalTrials.gov、公司 press release;Generate / Xaira IPO S-1 filing 也属同一 trigger

> - (a) **SGR-1505 (MALT1) Ph2 readout 2026H2 / 2027H1** — primary endpoint(B-cell lymphoma ORR / CR rate)未达预设阈值,或 dose-limiting toxicity;
  - (b) SDGR software revenue YoY growth dropping below 8% in any 2 consecutive quarters(2024 ~13%,2025 guidance 10–12%)
- **Why this falsifies**: SDGR 是三家中唯一不是 antibody-led 的; 它的存在依赖 (i) software ARR 是真现金流 cushion、(ii) MALT1 是 free option 上的 hidden value。**(a) 摧毁 drug discovery option,(b) 摧毁 software moat narrative**。两者同时坏,SDGR 估值压回 software P/S 6–8x 区间(对应市值 ~$1.2–1.7B vs 当前 ~$2.5–3B)

> - (b) SDGR software revenue YoY growth dropping below 8% in any 2 consecutive quarters(2024 ~13%,2025 guidance 10–12%)
- **Why this falsifies**: SDGR 是三家中唯一不是 antibody-led 的; 它的存在依赖 (i) software ARR 是真现金流 cushion、(ii) MALT1 是 free option 上的 hidden value。**(a) 摧毁 drug discovery option,(b) 摧毁 software moat narrative**。两者同时坏,SDGR 估值压回 software P/S 6–8x 区间(对应市值 ~$1.2–1.7B vs 当前 ~$2.5–3B)
- **Verifiable**: SDGR 8-K 财报 + clinicaltrials.gov NCT05544019 (SGR-1505 Ph1/2)

> - **Why this falsifies**: SDGR 是三家中唯一不是 antibody-led 的; 它的存在依赖 (i) software ARR 是真现金流 cushion、(ii) MALT1 是 free option 上的 hidden value。**(a) 摧毁 drug discovery option,(b) 摧毁 software moat narrative**。两者同时坏,SDGR 估值压回 software P/S 6–8x 区间(对应市值 ~$1.2–1.7B vs 当前 ~$2.5–3B)
- **Verifiable**: SDGR 8-K 财报 + clinicaltrials.gov NCT05544019 (SGR-1505 Ph1/2)
- **Threshold to act**: Ph2 ORR <30% 或 software growth 连续两季 <8%

> **Cleanest entry now**: **ABCL** — 三家中唯一同时具备(i) AI/microfluidic 平台资产、(ii) 89-program partner book、(iii) ~$700M cash + 3 年 runway、(iv) Lilly 历史 royalty 已实战验证。**ABSI 更纯但 binary 风险过高**(单 trial 决定生死);RXRX 在 antibody 维度是 mis-classified;SDGR 不是 antibody 票。

## From tech_dive #50: 技术深挖: Foundation models for protein structure prediction pos...
_2026-05-07T05:01_

> - **Pfizer** — disclosed AF2 in target triage at **JPM Jan 2023**; ~50 structure-enabled programs cited.
- **Schrödinger (SDGR)** — AF2-derived structures fed into LiveDesign / FEP+; FY2022 and FY2023 10-Ks explicitly cite AlphaFold integration as platform input.
- **Insilico Medicine (private; HK IPO refiled)** — PandaOmics target ID + Chemistry42 generative chemistry; **INS018_055** (TNIK inhibitor for IPF) is the **first fully AI-generated drug to reach Phase II** — Phase IIa initiated **June 2023**, full enrollment **Feb 2024**.

> Isomorphic Labs (private) · Recursion (RXRX) · Insilico (private)
        Schrödinger (SDGR — partly here via collaborations) · AbCellera (ABCL)
                       │

> | **Recursion (RXRX)** | Roche/Genentech | ~**50%** of 2023 collab revenue | ~**90%** (Roche + Bayer + Tempus collab) |
| **Schrödinger (SDGR)** | Top-1 software customer ~7%; **but** drug-discovery collab revenue **highly concentrated** in BMS + Otsuka + Lilly | drug-discovery rev ~**50% one customer**; software more diversified | ~**70%** of drug-discovery rev top-3 |
| **AbCellera (ABCL)** | Lilly historically (bamlanivimab royalty wind-down); now diversified across ~80 partners but bookings still concentrated | ~**30%** | ~**60%** |

> - **Tempus AI (TEM):** IPO'd Jun 2024 at ~$8B FDV; FY24 revenue **~$700M** (genomics + data licensing combined); ~80% from genomics testing today, ~20% from data licensing including AI partners. The data-licensing line is the AF-adjacent one — **booking now, ~$140M run-rate**, growing >35% YoY.
- **Schrödinger (SDGR):** FY24 revenue **~$210M** (software ~$170M + drug-discovery ~$40M); **software is recurring SaaS, booking now**. Drug-discovery revenue is milestone-lumpy.
- **10x Genomics (TXG):** FY24 ~$615M, mostly Chromium consumables; AI-discovery is upstream demand pull, indirect.

> 中文:三层落账速度差异极大 —— **基础设施层(Tier 2)正在落账**:NVIDIA 医疗 ~$1B/yr、Tempus 数据授权 ~$140M/yr、Schrödinger 软件 ~$170M/yr;**AI 药企层(Tier 1)上游已落、里程碑后置**:Recursion FY24 营收仅 $59M、Isomorphic 2024 确认 $82.5M 上游、Insilico ~$50M/yr,**真正的 Phase II/III 里程碑现金窗口在 2026–2028**;**大药企卖药层(Tier 0)需到 2028–2032**:Insilico INS018_055 与 Recursion 几条 REC-资产可能在 2027–2028 出第一张"完全 AI 设计药物"FDA 批文,但要做到 $1B/yr 单品级别还要再 5–7 年(大概 2030+)。**所以"今天能买的现金流"在 NVIDIA、TEM、SDGR;"2026–2028 兑现的"是 RXRX 与 Isomorphic 的里程碑;"2030+ 才会出现的"是真正的 AI 药销售收入** —— 三个时间窗口对应三种估值范式。

> **Round 2 close.** 商业图景的关键点 —— **(1) 模型本身没钱**(全免费或 CC BY-NC),**钱在用模型产出的"减风险药物资产"**(Tier 1 上游 + 里程碑 + 销售提成);**(2) 单位经济拐点已在发生但只压到了 IND 阶段**,真正的胜负看 AI 是否能提升 Phase II→III 成功率,目前数据不支持;**(3) TAM 看似巨大但落到 AI 制药本身只有 ~$10B/yr 到 2030**,远小于 NVIDIA 数据中心 ~$115B/yr;**(4) Tier-1 AI 药企客户极度集中**,Lilly + Roche/Genentech 任一家策略转向都会撼动行业;**(5) 时间窗口三段** —— NVIDIA / TEM / SDGR 现金流今天就在,RXRX / Isomorphic 里程碑窗口 2026–2028,真正的 AI 药销售要到 2030+。

> Round 3 应该聚焦**公开市场可投标的:股票链 + 估值 + 触发条件 + 风险事件清单**(NVDA / TEM / SDGR / RXRX / 以及 ABCL、TXG、CRL/WuXi 的可投性)。Ready when you say go.

> ## 3. SDGR / Schrödinger — Nasdaq

> - **链条层级 / Layer:** Tier 1/2 交界,**物理基础的分子模拟软件 + 自有药物管线**。它是 AF / 结构预测的**互补品**,不是替代品 — AF 给静态结构,SDGR 的 FEP+ / WaterMap 给**结合自由能与动态**(参见 Round 1 短板第 1 条)。10-K 多年明确写"AlphaFold structures fed into LiveDesign"。
- **具体 SKU / Priced product into trend:** **LiveDesign + Maestro** 桌面 + 云,~**1,800+ 客户、订阅 SaaS**;**FEP+** 自由能扰动模块(行业金标);**OurEXP / WaveLM** — AF/PLM-bolt-on;**药物合作管线**(BMS、Otsuka、Lilly、自有早期资产)。

> - **量级 / Scale:** 市值 **~$1.5–2B**;FY24 营收 **~$210M**(软件 ~$170M 订阅 + 药物合作 ~$40M 里程碑);软件订阅毛利 ~80%,药物合作收入大块且 lumpy。
- **竞争 / Competitors:** **Certara (CERT)** PBPK / QSP 仿真(临床端,与 SDGR 临床前互补);**Simulations Plus (SLP)**;**OpenEye (private,Cadence 旗下)**;**Cresset / Cadence Molecular Sciences**;中国侧 **晶泰科技 2228.HK**。
- **载体质量 / Vehicle quality:** **软件订阅是 AF 时代少有"现在就在落账"的 SaaS**,质量高;但药物合作收入 lumpy + 自有管线烧现金 ~$200M/yr,股价波动来自管线读数而非 SaaS。**纯主题敞口最干净的 ~$2B 量级标的之一**。

> - **量级 / Scale:** 市值 **~HK$10–15B(~$1.3–2B USD)区间**;FY23 营收 ~¥175M(USD ~$24M),亏损;员工 ~900;客户包括辉瑞、礼来、强生及 ~150 家中小 biotech。
- **竞争 / Competitors:** **Schrödinger (SDGR)**(直接对位)、**Recursion (RXRX)**、**英矽智能 Insilico**(私有)、**成都先导 688222.SH**(DEL 库 + AI)、**药石科技 300725.SZ**(化学库 + AI)。
- **载体质量 / Vehicle quality:** **港股侧最纯的 "AI 药物发现 + 平台 SaaS" 票**,且按中国制造业成本结构跑;但**营收尚小、盈利路径未验证、国际化客户结构受中美关系扰动**。**作为 A/H 投资人表达 AF 主题的可选载体,但厚度不够,更适合作为 RXRX/SDGR 的对照仓位**。

> - **竞争 / Competitors:** **Schrödinger (SDGR)**(直接对位)、**Recursion (RXRX)**、**英矽智能 Insilico**(私有)、**成都先导 688222.SH**(DEL 库 + AI)、**药石科技 300725.SZ**(化学库 + AI)。
- **载体质量 / Vehicle quality:** **港股侧最纯的 "AI 药物发现 + 平台 SaaS" 票**,且按中国制造业成本结构跑;但**营收尚小、盈利路径未验证、国际化客户结构受中美关系扰动**。**作为 A/H 投资人表达 AF 主题的可选载体,但厚度不够,更适合作为 RXRX/SDGR 的对照仓位**。

> - **竞争 / Competitors:** **Roche RHHBY**(Recursion $12B 单笔最大签字方);**Novo Nordisk (NVO)** GLP-1 直接对手;**Pfizer (PFE)、Merck (MRK)、BMS、Sanofi (SNY)、Novartis (NVS)** AI 合作活跃但规模 / 频率低于 Lilly。
- **载体质量 / Vehicle quality:** **绝对不是 AF 主题 vehicle** — Lilly 股价由 GLP-1 销售曲线、专利悬崖、价格谈判主导;**但作为 "理解 AI-pharma 需求侧" 的必读公司**,任何 RXRX/SDGR/Isomorphic 估值都隐含 Lilly 持续买入的假设。**作为 sentinel signal 持有,而非 vehicle**。

> - **不可投性:** Alphabet 全资,无独立股权;**间接 vehicle = GOOG / GOOGL**,但 Isomorphic 在 GOOG 万亿级营收中是隐藏单元(<<1%),稀释到失效。
- **为什么重要:** AF3 平台进展决定 Tier-1 整体节奏 — Isomorphic 若在 2026–2027 兑现首批 Lilly/Novartis IND,会**直接重定价 RXRX 与 SDGR**(平台估值上调或下调 — 取决于"是 Isomorphic 独家"还是"AF3 同类成果泛在")。

> - **不可投性:** 早期私有公司。
- **为什么重要:** 与 **Boltz-1**(MIT,2024-10)+ **HelixFold3**(Baidu BIDU,中国侧)一起,**让"AF3 类能力"在 2024-Q4 之后变成商品** — 这是 Round 1 / Round 2 预测过的"模型层无溢价"在 2025 年的进一步确证。**含义:Tier-2 模型层利润趋零 → 价值更确定地落到 Tier-1(资产)与 Tier-2(基础设施 + 数据)** — 这反过来强化 NVDA / TEM / RXRX / SDGR 论点。

> | **现金流"今天就在"的基础设施** | **TEM**(数据,纯) | NVDA(稀释) |
| **现金流"今天就在"的软件 SaaS** | **SDGR**(物理仿真 + AF 互补) | — |
| **2026–2028 里程碑兑现的 Tier-1** | **RXRX**(主题最纯,客户集中风险显性) | ABCL(抗体方向辅助) |

> **最干净的三票组合(若必须选三):TEM + SDGR + RXRX** — 分别覆盖"数据"+"软件"+"资产",时间窗口梯度配置。**NVDA 不在此组合里 —— 它对此主题是稀释票。**

> **Where in the cycle / 周期位置:** Not in the "before-it-20x" zone for the platform-software layer — that already 5–10×'d in 2020–2023 (RXRX peak ~$11B FDV, SDGR peak ~$7B); model layer commoditization confirmed Q4 2024 by Chai-1 / Boltz-1 / HelixFold3 (Round 1 §4). **Still pre-inflection at the asset layer:** zero AI-designed drugs FDA-approved as of session date; first plausible approval 2027–2028; first $1B/yr "AI drug" 2030+. So the trade is **buying through the pre-revenue valley** at depressed Tier-1 multiples — it is *unloved*, not crowded.

> **Cleanest entry / 最干净敞口:** **TEM (Tempus AI)** — Tier-2 data layer, ~$140M/yr data-licensing run-rate growing >35% YoY, the only book-now revenue with low milestone dependency. **Would NOT own:** at >$15–18B market cap (>~25× data-licensing run-rate), or if oncology NGS reimbursement headlines (CMS LCD changes) hit the ~80% testing-revenue base. The investable bet on the *thesis* is TEM + SDGR + RXRX (data + software + asset), not NVDA.
