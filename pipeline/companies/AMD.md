# AMD -- 综合提取 / All mentions across our research

_Aggregated from 72 mentions across 13 reports. Auto-generated; rerun via `python scripts/compress_dives_to_companies.py`._

---

## From tech_dive #37: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T02:09_

> ## 1. Revenue flow / 现金流向
**5 tollbooths**: hyperscaler capex ($355–425B 2026E) → GPU/ASIC vendor (NVIDIA/AMD/Broadcom) pays ~$3–4.5k per 8-stack HBM4 set (30–40% of board BOM) → memory maker (SK hynix 50–55%, Micron 20–25%, Samsung 25–30%) → pays for foundry base die + TCB tools + NCF film + slurry + test heads → OSAT (CoWoS) → equipment/materials. **GM rises upstream**: SK hynix HBM GM >55% (now >80% of profit pool), TCB tools 35–45%, materials 40–50%.

> ## 4. Customer concentration / 客户集中度
**NVIDIA 60–65%** of HBM4 cubes, AMD 10–13%, Broadcom 10–13%, Marvell 5–8% → **top-3 = 85%**. Top-4 hyperscalers = 75–80% of pull. Single-customer risk = NVIDIA cadence. Equipment side: **Hanmi >50% from SK hynix** (highest), ASMPT 3-customer, **Resonac NCF ~90%+ share** (industry toll), **Disco ~95% grinder share but spread across all of semis** (lowest concentration, most bond-like).

## From tech_dive #38: 技术深挖: TSMC CoWoS-L vs Intel EMIB vs Samsung X-Cube: 2.5D adv...
_2026-05-07T02:24_

> 5. **Validation** — named deployments by route (CoWoS-S: H100/H200/MI300X/TPU v4-v5p/Trainium 1-2; CoWoS-L: B200/GB200, Rubin, MI350/400, Trainium 3, TPU v7; EMIB: Sapphire Rapids HBM, Ponte Vecchio, Clearwater Forest, IFS for Maia/AWS; X-Cube/I-Cube: 2020 SRAM-on-logic test chip, AMD-evaluated, no marquee AI win) plus industry telemetry (TSMC earnings, NVIDIA CFO commentary, TrendForce quarterly tracking, OCP).

> 1. **Revenue flow** — money path with rough margin/take at each stop: hyperscaler → module vendor (NVIDIA HGX/AMD MI/Broadcom-Marvell ASIC) → foundry+packaging house (TSMC ~90% of leading-edge 2.5D, Intel IFS, Samsung) → parallel split into bridge-die fab + ABF substrate makers + equipment/materials vendors. Pricing power lives at three nodes: TSMC's ~$7k–10k CoWoS-L premium per accelerator, ABF substrate's >10× ASP uplift on AI substrates, and TCB / hybrid-bonder tool concentration.

> 4. **Customer concentration risk** — oligopsony every layer. NVIDIA was ~60–65% of CoWoS in 2024, normalizing to ~50% (NVIDIA+AMD ~70–75% of CoWoS-L 2026); 6 end-buyers (MSFT/META/GOOG/AMZN/ORCL/xAI) dominate; TSMC ~90% of leading-edge packaging; Ibiden+Unimicron+Shinko ~65% of giant substrate; ASMPT+Hanmi ~80% of TCB; **Ajinomoto ~100% on ABF film — single most concentrated chokepoint in the entire chain.** Asymmetric two-way dependency illustrated by the 2024-Q4 → 2025-Q1 CoWoS reallocation episode.

> 3. **HBM ASP/GB drops >25% YoY**, *or* SK Hynix HBM utilization falls below 85% — the bandwidth-scarcity premise gone.
4. **Tier-1 hyperscaler 2027-production design-win on non-CoWoS-L** (glass-core or CoWoS-R) at ≥1 M units (AMD MI500 / MSFT Maia v3 / TPU v8 / Trainium 4 / MTIA v3) — collapses the bridge-die chokepoint two years early.
5. **Inference unit-economics regression** — OpenAI/Anthropic/Google API price floors stop falling for two consecutive quarters *and* inference-revenue growth drops below 50% YoY.

## From tech_dive #40: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T02:34_

> **SK hynix — production / 量产**
- HBM4 12-Hi samples to NVIDIA, AMD: **2025-Q1**.
- Mass production declared at M14/M15X Icheon: **2025-Q3** (company IR, September 2025).

> ▼
GPU / ASIC vendor        (NVIDIA, AMD, Broadcom-for-Google/Meta, Marvell-for-AWS/MSFT)
       │  pays $3,000–4,500 per 8-stack HBM4 cube set (≈30–40% of board BOM)

> GPU servers ≈ 60–70% of that → **~$220–300B flows to NVIDIA + AMD + custom-ASIC** chain in 2026. HBM is 30–40% of GPU board BOM → **HBM TAM consumable: ~$70–100B** (2026E).

> | **NVIDIA**        | **60–65%**                | Blackwell-Ultra + Rubin; single-buyer risk   |
| **AMD**           | 10–13%                    | MI400 / MI500 ramp                           |
| **Broadcom**      | 10–13%                    | TPU v7 (Google), MTIA-2 (Meta) — fastest-growing |

> **中文**:**前三 (NVIDIA + AMD + Broadcom) 拿走 ~85% 的 HBM4 cube 出货,NVIDIA 一家 60–65%** — 整条链最大单点风险。任何 NVIDIA 节奏推迟立即砸 SK hynix 季度收入。设备链中,**Hanmi 集中度最高**(>50% 来自 SK hynix HBM TCB),**Disco 最分散**(~95% 全球市占跨所有半导体客户)。

> - **Top competitors**: Samsung Foundry (captive 4LPP for Samsung HBM4 only); Intel Foundry (no HBM4 base die win to date). For 2.5D packaging — none at HBM4 volumes; Amkor + ASE chase fan-out variants.
- **Vehicle quality**: 双重收费站 — HBM4 base die wafer + CoWoS-L 封装。Diversified across HBM3E/4/4E generations and NVIDIA/AMD/Broadcom/Marvell customers. **Lower beta than HBM-pure plays but larger absolute dollar haul.**

## From tech_dive #41: 技术深挖: TSMC CoWoS-L vs Intel EMIB vs Samsung X-Cube: 2.5D adv...
_2026-05-07T02:44_

> - **Die-to-HBM bandwidth / 带宽**: HBM3e single stack via interposer ≈ **1.2 TB/s**; an 8-stack package ≈ **~9.6 TB/s**; HBM4 16-stack roadmap pushes past **~16 TB/s**. PCB-routed DDR5 tops at **~100 GB/s** per channel → bandwidth advantage ≈ **100×**.
- **Reticle-busting / 突破光罩**: monolithic exposure capped at **858 mm²**. CoWoS-L stitched interposer ships today at **~2,800–3,300 mm² (~3.3× reticle)**; TSMC's roadmap targets **~5.5× reticle (~4,700 mm²)** for 2026-2027 (NVIDIA Rubin Ultra, AMD MI400 class). NVIDIA Blackwell B200 = 2× ~800 mm² compute dies + 8 HBM3e on one package ≈ **~3,000 mm² silicon**.
- **Bump pitch / 凸点密度**: micro-bumps on Si interposer at **40–55 µm pitch** vs. C4 bumps on substrate at **150–200 µm** — areal density ~**10×**. RDL pitch **0.4–1.0 µm** on Si interposer vs. **8–15 µm** on organic substrate — another ~**10×** at the trace level.

> - **TSMC CoWoS-L** — **NVIDIA Blackwell B100 / B200 / GB200** (2024-Q4 ramp, 2025 production); **NVIDIA Rubin / Rubin Ultra** announced for 2026 (TSMC Tech Symposium 2024 keynote, NVIDIA GTC 2024). **AMD MI300X / MI325X** ship on CoWoS-S today; **MI350 / MI400 (2025-2026)** moving to CoWoS-L per AMD investor day. **AWS Trainium2** (re:Invent 2024) and **Google TPU v5p / v6** also use TSMC CoWoS class. **Broadcom** custom ASICs for Meta MTIA + Google TPU run CoWoS-S/L.
- **Intel EMIB** — **Sapphire Rapids HBM (Xeon Max, 2023)**, **Ponte Vecchio / Data Center Max GPU 1550 (Aurora supercomputer at Argonne, 2023-2024)** — 47 active tiles with EMIB + Foveros; **Granite Rapids-AP (2024)**; **Clearwater Forest (E-core Xeon, 2025)** uses Foveros Direct + EMIB-T. **Intel 18A "Panther Lake"** announced EMIB roadmap for foundry customers (IFS Direct Connect 2024).

> **中文.** 已经在跑量的"现役 2.5D 客户":
- **CoWoS-L** — NVIDIA Blackwell B100/B200/GB200(2024Q4 量产)、Rubin/Rubin Ultra(2026 路线图)、AMD MI350/MI400(2025-2026)、AWS Trainium2、Google TPU v5p/v6、Broadcom 给 Meta MTIA + Google TPU 的定制 ASIC。
- **EMIB** — Intel Sapphire Rapids HBM(Xeon Max,2023)、Ponte Vecchio(Aurora 超算,Argonne)、Granite Rapids-AP、Clearwater Forest(EMIB-T + Foveros Direct)、18A Panther Lake 路线图。

> **Round 1 done.** Tech is **live in production** at NVIDIA/AMD/Intel/Google/AWS scale, with the binding 2026-2027 constraints being **CoWoS capacity (TSMC), bridge-die alignment yield, ABF substrate supply, and HBM4/hybrid-bonding ramp** — not the compute die. Ready for Round 2 (business chain) when you call it.

> ▼
Compute-IP / merchant accelerator vendor (NVDA, AMD, Broadcom-as-ASIC-designer, Marvell-as-ASIC-designer)
   │  ~70-78% gross margin on NVDA datacenter; ~55-60% on AMD MI300/MI350

> Compute-IP / merchant accelerator vendor (NVDA, AMD, Broadcom-as-ASIC-designer, Marvell-as-ASIC-designer)
   │  ~70-78% gross margin on NVDA datacenter; ~55-60% on AMD MI300/MI350
   ▼

> **中文.** 链条 7 段:**云厂/OEM(MSFT/META/GOOG/AMZN/Oracle/xAI/Tesla/主权云)→ 加速器设计公司(NVDA/AMD/Broadcom-定制 ASIC/Marvell-定制 ASIC)→ 晶圆 + 封装代工(TSMC、Intel Foundry、Samsung Foundry)→ OSAT 组装与最终测试(Amkor、ASE/SPIL、KYEC)→ HBM 供应商(SK 海力士第一、Micron 第二、三星追赶)→ ABF 有机基板(Ibiden ~30%、Unimicron ~20%、Nan Ya PCB、Shinko、AT&S、Kinsus)→ 工具/耗材(ASML、AMAT、TEL、LRCX、Disco、BESI、ASMPT、Hanmi、Camtek、Onto、信越/住友 Bakelite)。**

> 每张 B200 卖 ~$30-45k、GB200 NVL72 整柜单卡位 ~$60-80k;NVDA 数据中心毛利 ~70-78%、AMD MI 系列 ~55-60%;CoWoS 包装 ASP ~$7-12k/套(L 类);ABF 90 层基板 ASP $300-700,较上一代翻倍。

> - Each B200/GB200 = 1 CoWoS-L package; each Rubin = 1 CoWoS-L (larger interposer, ~5.5× reticle).
- AMD MI350/MI400 contributes another **~500k-1M packages** in 2026.
- Custom ASICs (Google TPU v6, AWS Trainium2/3, Meta MTIA v2, Microsoft Maia v2, Broadcom-designed silicon) **~1.5-2M CoWoS-class packages** in 2026.

> **封装单位换算:** NVDA 2025 数据中心 ~$1400-1700 亿收入 → ~4-5M Blackwell 等效 GPU,各对应 1 个 CoWoS-L 套件;AMD MI350/MI400 加 ~50万-100万套;TPU v6/Trainium2-3/MTIA v2/Maia v2/Broadcom 定制 ASIC 加 ~150-200万套。**2026 CoWoS 级封装总需求 ~7-800 万套**,TSMC 端 2026 ~13.5-15万 wpm,**面积口径仍紧,2027 才有望转松(取决于嘉义 AP8 准时投产)。**

> - **Compute-die layer:** NVIDIA ~**85-90% of merchant AI accelerator revenue** in 2025 (consensus). AMD ~5-10%, custom ASICs combined ~5-10%. **NVIDIA alone is >50% of TSMC's CoWoS allocation** (TrendForce, SemiAnalysis). One customer dominance unlike anything in semis history.

> **中文.** 整条链子**两端各有一个单点**:
- **计算 die 层** — NVDA 约占 2025 商用 AI 加速器收入 **85-90%**,AMD 5-10%,定制 ASIC 合计 5-10%。NVDA 一家独占 TSMC CoWoS 分配 **>50%**。
- **CoWoS/2.5D 产能** — TSMC AI 端 2.5D 实际**份额 >90%**,Intel EMIB 主要服务 Intel 自家 + 少量代工试点,Samsung I-Cube 仅 Naver-Tenstorrent 等小批客户。**未来 18 个月就是 TSMC 单家垄断**。

> - **AMD MI350 (CoWoS-L)** — sampling Q4 2025, production ramp **Q1-Q2 2026**, revenue mid-2026; MI400 follows in 2027.

> **Bottom line on timing:**
- **Live now (2025):** TSMC CoWoS, NVDA Blackwell, AMD MI300X/MI325X, AWS Trainium2, Google TPU v5p/v6, SK hynix HBM3e, Ibiden ABF, BESI/ASMPT/Hanmi tools, Amkor/ASE outsourced WoS.
- **Inflection 2026:** CoWoS-L mix dominates, MI350 ramps, Maia v2 / MTIA v2 / TPU v6 step up, HBM4 starts, Rubin samples, Ibiden Phase-1 fully online, EMIB-T external.

> - **NVDA Blackwell** — B100/B200 2024Q4 起量,2025Q1-Q2 全速;GB200 NVL72 整柜 2025Q2 起规模出货。Rubin 2025 GTC 揭幕,2026H2 量产,**收入拐点在 2026 末 / 2027**。
- **AMD MI350(CoWoS-L)** — 2025Q4 送样,2026Q1-Q2 量产爬坡,2026 中确认收入;MI400 在 2027。
- **定制 ASIC** — Trainium2 已出货(re:Invent 2024)、Trainium3 2025H2、TPU v6 (Trillium) 2025、MTIA v2 2025-2026、Maia v2 2026。Broadcom AI 业务 FY2024 $120 亿 → FY2025 指引 $200-250 亿+ — **现在就是收入**。

> **时间线 TL;DR:**
- **2025 已实收入:** TSMC CoWoS、NVDA Blackwell、AMD MI300X/MI325X、Trainium2、TPU v5p/v6、SK 海力士 HBM3e、Ibiden ABF、BESI/ASMPT/Hanmi 设备、Amkor/ASE 外包 WoS。
- **2026 拐点:** CoWoS-L 占比反客为主、MI350 起量、Maia v2/MTIA v2/TPU v6 抬量、HBM4 开始、Rubin 送样、Ibiden 一期满产、EMIB-T 外部首单。

> - **Specific SKU / 直接 SKU:**
  - **HBM3e 12-Hi 36 GB stack** — primary supplier to NVDA B200/B300 since 2024-Q3, broadening to AMD MI350.
  - HBM4 12-Hi/16-Hi sampling 2025-Q4, volume 2026-H2 for Rubin.

> - **Specific SKU / 直接 SKU:**
  - High-layer-count (90+) FCBGA substrate for NVDA B200/GB200, Intel Sapphire Rapids/Ponte Vecchio/Clearwater Forest, AMD MI300/350, Google TPU v5p/v6+. Substrate ASP **$400–800 per piece** on AI accelerators (vs. $20–40 on server CPUs).
  - **Ogaki North plant** — ¥180B (~$1.2B) AI-substrate-dedicated capex; ramp 2024-Q4 → full run 2026.

> - **Top competitors / 主要对手:**
  - **Teradyne (TER, NASDAQ)** — main SoC tester rival; weaker on HBM, stronger on traditional SoC and AMD.
  - **Chroma ATE (2360.TW, TPE)** — system-level (rack-level burn-in for GB200), an *adjacent* layer rather than direct competitor.

## From tech_dive #42: 技术深挖: China semi domesticization deep-dive: 盛美 ACMR + 中微 AME...
_2026-05-07T03:00_

> - **NAURA**: SMIC (broadest single-vendor footprint), YMTC, CXMT, all major domestic mature-node fabs. **FY2024 ~RMB 28–32B — largest Chinese WFE company by revenue, ~3× ACMR or AMEC.**
- **JCET**: Qualcomm, MediaTek, Apple-via-STATS, AMD, Marvell, NXP, STMicro + domestic AI accelerator XDFOI insertions. FY2024 ~RMB 33B — #3 OSAT globally.

> | 5 | **688019.SH** | 安集科技 Anji Micro | **Materials** — CMP slurry / strippers | Highest GM on list (~55–60%), recipe-IP moat. Long-standing TSMC qualification — credentialing data point nothing else here matches. |
| 6 | **002156.SZ** | 通富微电 TFME | **OSAT** | The closest pair-trade / hedge to JCET. **Packages all of AMD's MI300/MI325/MI350** via the Suzhou + Penang JV — only non-Nvidia AI accelerator at hyperscale volume. |

> 4. **SkyVerse (688361.SH)** — KLA gap-fill; biggest narrative torque, slowest tangible ramp.
5. **TFME (002156.SZ)** — JCET pair / AMD-MI exposure; not additive to the China-domestic AI story.
6. **NSIG (688126.SH)** — base-layer beneficiary, lowest-multiple, lowest-volatility.

## From tech_dive #43: 技术深挖: AI antibody discovery commercial inflection: AbCellera...
_2026-05-07T03:10_

> - **Market cap + scale / 市值 + 规模:** ~$3.5 T (2026Q1),FY25 (Jan 2026 财年结) revenue ~$170 B,**biopharma vertical revenue 估 ~$0.8–1.2 B / yr,< DC 收入的 1%**。
- **Top competitors / 主要竞争者:** AMD (AMD, MI300X — Meta + Microsoft 已采用,但 biopharma vertical 渗透极低)、Google TPU (内部自用,via GCP 租给 SDGR)、Intel Gaudi3 (INTC,几乎不在 biopharma 出现)。**实际意义上的"竞争对手"接近于零 — biopharma AI 已经 90%+ 锁在 CUDA + cuDNN + cuBLAS 栈**。
- **Vehicle quality / 标的质量:** **极度 diversified — 不是 AI antibody 的纯 play**。任何把 NVDA 当作 "AI 制药"敞口的论点都被 LLM/data-center cycle 稀释 ~99×。**Round 2 已警告: 把这条赛道挂到 hyperscaler capex 是 sell-side 叙事拉伸**。NVDA 在本 dive 中只能算 "macro tide,不是 alpha"。

## From tech_dive #45: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T04:29_

> - **JEDEC JESD238 (HBM4)** ratified **April 2025**: 2048-bit IO, up to 8 Gbps/pin, 12-Hi/16-Hi stacking, RAS extensions codified.
- **SK hynix HBM4 12-Hi**: samples to NVIDIA / AMD **2025-Q1**; mass production declared at **M14/M15X Icheon, 2025-Q3** (company IR briefing September 2025). Process: 1bnm/1cnm DRAM + Advanced MR-MUF + TCB (Hanmi dual-head + ASMPT) + **TSMC N5 base die** (publicly confirmed mid-2025 — first commercial logic-foundry HBM base die at scale).
- **Micron HBM4 12-Hi 36 GB**: samples to "lead AI customers" **2025-Q2** (June 2025 earnings call); volume ramp 2026-Q1 into Rubin / MI400. Process: 1γ DRAM + MR-MUF-equivalent. Idaho + Hiroshima fabs.

> NVIDIA  (Blackwell-Ultra, Rubin)  ~ 55–60% of HBM4 demand
AMD     (MI400 series)            ~ 12–15%
Broadcom/Marvell-designed ASICs   ~ 18–22% (Google TPU v7, AWS Trainium 3, Meta MTIA, MSFT Maia)

> - NVIDIA: ~55–60% of all HBM4 demand 2026
- AMD: ~12–15%
- Broadcom + Marvell-fronted ASICs (Google TPU v7, AWS Trainium 3, Meta MTIA, Microsoft Maia): combined ~18–22%

> 1. **钱流**:超大规模数据中心 → NVIDIA/AMD/ASIC → SK hynix/美光/三星 → 台积电 CoWoS → 设备 + 材料层。一颗 Blackwell-Ultra GPU 含 HBM ~$2.6–3.4K,**HBM 占 AI 服务器 BOM 已从 3% 升至 9%**。
2. **拐点**:HBM4 vs HBM3E 单 GB 贵 25%,但单 GB/s 便宜 30% — 已经发生。混合键合 vs TCB 的拐点在 16-Hi、~2027-H2,**真正驱动是 NVIDIA Rubin-Ultra 的 2.0 kW 功耗墙,不是单价**。

> 3. **总量**:2026 HBM TAM ~$45–55 B,2026 出货 ~50 M cubes,**供给受限,不是需求受限**。
4. **客户集中**:NVIDIA + AMD + 三大 ASIC = 85–95% 需求;三家 HBM 厂垄断供给;BESI、ASMPT、Hanmi、Disco、Resonac 在各自工序近垄断。任一玩家失误立即收紧 20%+ 供给。
5. **真实收入时间**:SK hynix、ASMPT、Hanmi、Disco、Resonac、TSMC **已经入账**;美光 2026-Q1 起量;三星 2026-Q2/Q3 视 NVIDIA qual;**BESI 是 2027 才看得见的真钱**。

> - **Competitors**: `TER` Teradyne (~30–35% share, Magnum platform). Effective two-vendor market.
- **Vehicle quality**: **diversified beneficiary** — Advantest's SoC test business (NVIDIA, AMD) is also booming, so HBM is one of two co-incident tailwinds. Best risk-adjusted way to own "complexity is going up everywhere in AI silicon" without picking the bonding-route winner.

## From tech_dive #46: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T04:35_

> 直接挑战 **HBM3E（12-Hi, 1024-bit, ~1.2 TB/s）**——目前 Nvidia H200 / B200 / B300、AMD MI300X / MI325X 在用的版本。次级挑战：**GDDR7**（消费/边缘 AI 推理卡，~32 Gbps/pin 但点对点带宽远低于 HBM4 stack）。在封装路线上，HBM4 强迫 **TCB / hybrid bonding 取代 MR + capillary underfill** 作为主流堆叠方法——这是 advanced packaging 的范式切换。

> - **Logic base die customization**: HBM4 的 base die 用 **foundry advanced node**（TSMC N5/N4，SK 海力士已宣布）做，可塞入控制器/ECC/缓冲，减轻 GPU 端逻辑负担——HBM3E 的 base die 仍是 DRAM fab process
- **System-level memory bandwidth × 8 stacks = 16 TB/s** per accelerator，对应 Nvidia Rubin / AMD MI400 的训练算力刚好够喂

> - **Nvidia Rubin**：CES 2025 公布配置 **8 stacks HBM4 = 288 GB / 13 TB/s**；Rubin Ultra（2027）规划 **12 stacks HBM4E**
- **AMD MI400**: 2025 advanced AI event 公开规划，预计 12 stacks HBM4

> ▼
Nvidia / AMD (Rubin / MI400 board)
        │  HBM stacks: 8–12 per GPU @ ~$5k each = $40–60k of BOM

> - **HBM buyers**: **Nvidia ~70%**, **AMD ~15%**, **Broadcom/Marvell ASIC ~10%**, others (Intel Gaudi, custom) ~5%. **Top 3 = 95%+** — extreme.
- **Within Nvidia**: Microsoft + Meta + Google + Amazon + Oracle = **~75% of Nvidia data-center revenue**. If any one cuts capex 30% (e.g., AI ROI disappointment in 1H2026), HBM4 ramp slips a quarter.

> - **Layer**: HBM stack maker (TCB-NCF route, no MR-MUF) + DRAM die (1β) + Hiroshima/Taichung packaging
- **Specific SKU into trend**: **HBM4 12-Hi 36 GB** sampled June 2025 to Nvidia / AMD; targeting **20–25% Rubin allocation by Q3 2026**. FY2026 (Aug-26) HBM revenue guided **>$8B**, of which HBM4 likely $1–2B exiting.
- **Market cap / scale**: ~**$135B USD** (2026-04); FY2025 revenue $25B; ~48k employees; DRAM segment op-margin recovered to 35%+

## From tech_dive #47: 技术深挖: TSMC CoWoS-L vs Intel EMIB vs Samsung X-Cube: 2.5D adv...
_2026-05-07T04:37_

> - **NVIDIA B100 / B200 / GB200 (Blackwell) — CoWoS-L, TSMC, ramp 2024H2–2025**, dual-die reticle (2 × ~800 mm² stitched), 8×HBM3E. **First high-volume CoWoS-L deployment.** / Blackwell 是 CoWoS-L 首个大批量出货。
- **AMD MI300X / MI300A — CoWoS-S + 3.5D hybrid bonding, TSMC, shipping since 2023Q4**; 3D-stacked CCDs on IODs + 8×HBM3 via interposer. / 2023Q4 起出货。
- **Intel Sapphire Rapids (Xeon Max) — EMIB, since 2023Q1**; 4-tile CPU, also Ponte Vecchio GPU in **Aurora supercomputer at Argonne (validated 2024 exascale)** uses 47 tiles with EMIB + Foveros 3D. / Sapphire Rapids 2023Q1;Ponte Vecchio 用于 Argonne Aurora 超算。

> 1. **Hyperscaler → Accelerator vendor.** Microsoft / Meta / Google / Amazon / Oracle / xAI buy GPUs or place ASIC build orders. NVIDIA H100 SXM ASP ~$25–30k; B200 ~$30–40k; GB200 NVL72 rack ~$3.0–3.5M (72×B200 + 36×Grace + NVLink switch).
2. **Accelerator vendor → TSMC (and HBM makers in parallel).** NVIDIA / AMD / Broadcom (for Google TPU) / AWS (for Trainium) pay TSMC a **bundled wafer + CoWoS packaging price** (~$25–35k per Blackwell package, of which packaging+HBM assembly is ~$5–8k; HBM stacks themselves ~$8–15k for 8×HBM3E **paid directly to SK Hynix / Micron / Samsung**, not through TSMC).
3. **TSMC → OSAT overflow + substrate + materials.** TSMC subcontracts CoWoS back-end (chip-attach, mold, ball-drop) to **ASE / SPIL / Amkor** when AP6 is full (~10–15% overflow in 2025, dropping in 2026 as AP7/AP8 ramp). Substrate (ABF FCBGA carrier ~$300–600/unit) goes to **Ibiden / Unimicron / Shinko / Nan Ya PCB / Kinsus / AT&S**. Ajinomoto sells ABF film into all of them (~$5–10/unit attributable).

> 1. **超大规模云厂 → 加速卡厂商。** 微软 / Meta / Google / 亚马逊 / Oracle / xAI 买 GPU 或下 ASIC 订单。NVIDIA H100 SXM 单价 ~$25–30k;B200 ~$30–40k;GB200 NVL72 整柜 ~$300–350 万美元(72 颗 B200 + 36 颗 Grace + NVLink 交换机)。
2. **加速卡厂商 → 台积电(并行支付 HBM 厂)。** NVIDIA / AMD / Broadcom(代设计 Google TPU)/ AWS(代设计 Trainium)向台积电支付**晶圆 + CoWoS 封装打包价**(Blackwell 单封装 ~$25–35k,其中封装+HBM 组装 ~$5–8k);HBM 堆栈本身 8 颗 HBM3E ~$8–15k **直接付给 SK 海力士 / 美光 / 三星**,不走 TSMC。
3. **台积电 → OSAT 溢出 + 基板 + 材料。** TSMC 在 AP6 满载时把 CoWoS 后段(贴片、塑封、植球)外包给 **日月光 / 力成 / Amkor**(2025 年外溢约 10–15%,随 AP7/AP8 投产 2026 年回落)。ABF FCBGA 载板单价 ~$300–600 由 **欣兴 / Ibiden / Shinko / 南亚电路 / 景硕 / AT&S** 提供;Ajinomoto ABF 膜可分摊 ~$5–10/封装。

> - **CoWoS-L vs CoWoS-S crossover at ~2.5× reticle.** CoWoS-S yield drops below ~50% above 2.5× reticle (because a single defect on a 2,000+ mm² Si interposer kills the whole unit). CoWoS-L's RDL+bridge architecture means a single bridge defect (~5 mm²) only loses a bridge, not the carrier. Effective $/good-die crosses below CoWoS-S at **≥2.5× reticle area**, and CoWoS-L is the **only viable path above 3× reticle**. Blackwell B200 is 2× reticle stitched ≈ ~1,600 mm² compute footprint + 8 HBM — already in CoWoS-L territory. Rubin (R200) and Rubin Ultra are guided at 3.3× and 4× reticle respectively → CoWoS-S impossible.
- **EMIB vs CoWoS on cost.** EMIB strips out the silicon interposer and the costly TSV step → **package BOM is ~30–50% cheaper than CoWoS-L** (Intel public claim, plus reverse-engineering teardowns of Sapphire Rapids vs Sapphire-with-HBM CoWoS-S parts). Intel's problem is not cost — it's that NVIDIA/AMD don't certify EMIB and Intel has no merchant-AI flagship customer.
- **2.5D vs monolithic die — break-even by die area.** Below ~600 mm² compute, monolithic + GDDR is still cheaper. Above ~700 mm² **and** when HBM is required (training, large-batch inference), CoWoS-L is unambiguously cheaper per FLOP delivered, because monolithic > 858 mm² is reticle-prohibited and GDDR cannot saturate ≥1 TB/s memory demand. The crossover is set by **memory-bandwidth per dollar**, not die-area cost — every >600 W AI training accelerator from 2024 onward is on 2.5D.

> - **CoWoS-L 与 CoWoS-S 在 ~2.5× 光罩处交叉。** CoWoS-S 在 >2.5× 光罩(>2,000 mm² Si interposer)良率跌破 ~50%——一个缺陷直接报废整封装。CoWoS-L 用 RDL+小硅桥后,桥(~5 mm²)单缺陷只丢一颗桥不丢载板。等效 $/良品在 **≥2.5× 光罩面积** 处反超 CoWoS-S,**>3× 光罩则只剩 CoWoS-L 可走**。B200 2× 光罩拼接 ~1,600 mm² + 8 HBM——已在 CoWoS-L 区间;Rubin (R200) 3.3×、Rubin Ultra 4× 光罩——CoWoS-S 完全做不了。
- **EMIB vs CoWoS 成本。** EMIB 砍掉 Si interposer 和 TSV 步骤,**封装 BOM 比 CoWoS-L 低 30–50%**(Intel 公开口径 + Sapphire Rapids 与 HBM 版 CoWoS-S 拆解推算)。Intel 的问题不在成本,而在 NVIDIA / AMD 不认证 EMIB 产线,且本身没有商用 AI 旗舰客户。
- **2.5D vs 单 die — 按面积找平衡。** <600 mm² 单 die + GDDR 仍最便宜;>700 mm² **且需 HBM**(训练、大 batch 推理)时,CoWoS-L 单位 FLOP 成本明确占优——因为 >858 mm² 单 die 受光罩限制造不出,GDDR 也喂不饱 ≥1 TB/s 带宽。**真正的拐点由"每美元内存带宽"驱动**,不是 die 面积成本。2024 年起所有 >600 W AI 训练卡都已走 2.5D。

> **EN:**
- **TSMC CoWoS — exposed to NVIDIA.** Estimated 2025 split: **NVIDIA ~60–65%**, AMD ~10–12%, Broadcom (Google TPU v5p / v6 + Meta MTIA) ~10–12%, AWS (Trainium2/3) ~5–8%, Apple ~3–5% (M-series Ultra is on InFO_LSI, not CoWoS), Marvell + others ~3–5%. **Single point of failure: NVIDIA orders.** A 20% miss on Blackwell/Rubin demand drops TSMC packaging utilization ~12–13 pts.
- **HBM — even more concentrated.** SK Hynix ~50% share, Samsung ~30%, Micron ~20% in 2025; **NVIDIA absorbs ~70% of HBM3E output** (B200 + B300 + GB300 each take 8×HBM3E). SK Hynix is essentially a single-customer story for HBM3E in 2025–2026.

> **ZH:**
- **TSMC CoWoS——NVIDIA 风险敞口大。** 2025 年估计份额:**NVIDIA ~60–65%**,AMD ~10–12%,Broadcom(Google TPU v5p/v6 + Meta MTIA)~10–12%,AWS(Trainium2/3)~5–8%,Apple ~3–5%(M-Ultra 走 InFO_LSI 不走 CoWoS),Marvell 等 ~3–5%。**单点风险即 NVIDIA 订单**——Blackwell/Rubin 需求若不及预期 20%,TSMC 封装稼动率下滑 12–13 个百分点。
- **HBM——集中度更高。** 2025 年 SK 海力士 ~50%、三星 ~30%、美光 ~20%;**NVIDIA 吃掉 ~70% HBM3E 产出**(B200 + B300 + GB300 每颗 8×HBM3E)。SK 海力士的 HBM3E 业务 2025–2026 年本质是单客户故事。

> **Cap & scale / 市值与体量:** 市值 ~$1.05T(2026 Q1),FY2025 营收 ~$120B,员工 ~80k。
**Competitors / 竞争对手:** Intel Foundry(EMIB / Foveros,公开未拿到 NVIDIA / AMD 旗舰订单);Samsung Foundry(I-Cube / X-Cube,目前几无外部 AI 旗舰客户)。
**Vehicle quality / 标的成色:** **链条最干净的核心多头,但不纯 2.5D 标的**——CoWoS 占整体收入仍小,2.5D 故事被晶圆代工总盘子稀释,beta 大于 alpha。

> ## 3. 通富微电 Tongfu Microelectronics — 002156.SZ / 深圳主板
**Layer / 层位:** OSAT(A 股,AMD 后段独家合作)
**Specific product / 具体产品:** AMD MI300 / MI325X / MI350X 系列的**主力后段封装合作伙伴**(苏州厂 + 槟城厂),自研 2.5D / 3D 封装(Multi-Die-Integration MDI)。AMD 占总收入估算 ~50%+,AI GPU 后段封装是其最大增量。

> **Layer / 层位:** OSAT(A 股,AMD 后段独家合作)
**Specific product / 具体产品:** AMD MI300 / MI325X / MI350X 系列的**主力后段封装合作伙伴**(苏州厂 + 槟城厂),自研 2.5D / 3D 封装(Multi-Die-Integration MDI)。AMD 占总收入估算 ~50%+,AI GPU 后段封装是其最大增量。
**Cap & scale / 市值与体量:** 市值 ~RMB 350–400 亿,FY2024 营收 ~RMB 240 亿,员工 ~14k。

> **Competitors / 竞争对手:** 长电科技 JCET (600584.SH)、华天科技 (002185.SZ)、甬矽电子 (688362.SH);海外为 ASE / Amkor。
**Vehicle quality / 标的成色:** **A 股链条最直接受益标的之一,但纯度是"AMD 先进封装代工"而非真 2.5D 桥封装设计——客户集中度高(单一客户 AMD)是双刃**。MI 系列若放量则 EPS 弹性大,反之亦然。
**EN one-liner:** Most direct A-share advanced-packaging name via AMD backend, but earnings are a single-customer leverage on MI300-series success.

> **Vehicle quality / 标的成色:** **A 股链条最直接受益标的之一,但纯度是"AMD 先进封装代工"而非真 2.5D 桥封装设计——客户集中度高(单一客户 AMD)是双刃**。MI 系列若放量则 EPS 弹性大,反之亦然。
**EN one-liner:** Most direct A-share advanced-packaging name via AMD backend, but earnings are a single-customer leverage on MI300-series success.

> **Layer / 层位:** ABF FCBGA 载板(高端有机基板)
**Specific product / 具体产品:** **NVIDIA B200 / B300 / Rubin 用大尺寸 ABF FCBGA 载板**(>100×100 mm 级别,单价 $300–600)。AI 占 ABF 收入 ~50% 并继续提升;北陆 N3 厂 2026 投产专为 AI 大封装。市占率 ~40%,长期 NVIDIA / Intel / AMD 高端基板独家或主供。
**Cap & scale / 市值与体量:** 市值 ~$8.5B,FY2025 营收 ~$5.5B,员工 ~12k。

> **Cap & scale / 市值与体量:** 市值 ~$3.4T,FY2026 (Apr-end) 营收预期 ~$220B,员工 ~30k。
**Competitors / 竞争对手:** AMD (AMD)、Broadcom (AVGO,代设计 Google TPU + Meta MTIA)、Marvell (MRVL,代设计 AWS Trainium2)、Intel Gaudi 3。
**Vehicle quality / 标的成色:** **不是 2.5D 标的而是整条链最大单一多头**——估值 / 仓位讨论已是宏观主线;放在这里仅为完整性。

> | OSAT(US/TW)| 3711.TW / ASX(+ AMKR) | Overflow 受益,2026 H2 后转弱 |
| OSAT(A 股)| 002156.SZ 通富微电 | 单一客户 AMD 杠杆 |
| HBM | 000660.KS SK Hynix | HBM 暴露最高 |

## From tech_dive #48: 技术深挖: China semi domesticization deep-dive: 盛美 ACMR + 中微 AME...
_2026-05-07T04:45_

> - Foreign 高端: **TSMC InFO/CoWoS** (内部封装,但抢 OSAT TAM)
  - Domestic: **通富微电 (002156.SZ)** AMD MI300 主力封装合作伙伴
- **Vehicle quality:** **最分散最防御** — 客户结构全球化,β 最低;但因此弹性最小,5nm 国产化进度对其 ASP/利润是 +5–10pp,而非 multiple re-rate.**Diversified beneficiary with downside protection**.

## From tech_dive #49: 技术深挖: AI antibody discovery commercial inflection: AbCellera...
_2026-05-07T04:52_

> - **Scale**: 市值 ~$3.4T (2026Q1),FY2026 revenue ~$200B+,Healthcare vertical ARR <5% 但是 fastest-growing seg
- **Competitors**: AMD MI300X/MI400,Intel Gaudi 3,Google TPU(internal-only),Cerebras WSE-3(私)。Healthcare inference share NVDA ~95%+
- **Vehicle quality**: 高度 diversified;AI 抗体即使 10 年内做到 100% pharma 渗透也只是 NVDA $1B/year 量级,对 NVDA 估值几乎无影响。**Buy NVDA for AI generally, not for antibody**

## From tech_dive #50: 技术深挖: Foundation models for protein structure prediction pos...
_2026-05-07T05:01_

> - Cloud: ~**60% AWS** in pharma life-sciences (HHS/Veeva/IQVIA all AWS-heavy); Azure dominant inside Roche & Novartis; GCP minor.
- GPU: **>95% NVIDIA** for foundation-model training/inference in pharma; AMD MI300 just starting in 2025 (Recursion BioHive-2 is all-NVIDIA H100).
- Wet-lab validation: **WuXi AppTec / WuXi Biologics** alone ~25–30% of global preclinical CRO capacity — single point of geopolitical (BIOSECURE Act) failure.

> - **量级 / Scale:** 市值 **~$3T+** 区间(2026-Q1 GTC 前后);FY25 数据中心收入 ~**$115B**;**Healthcare 业务披露年化 ~$1B**(BioNeMo + Parabricks + Clara 合并),~50% YoY,**占数据中心 < 1%**。
- **竞争 / Competitors:** **AMD (AMD)** MI300X / MI325 — 进入 pharma 慢,Recursion 仍全 H100;**Google TPU v5p** — 内部 Isomorphic / DeepMind 训 AF3 用,但不外卖 pharma;中国侧 **华为昇腾 910B**(私有)+ **寒武纪 688256.SH**(微量进入药企科研云)。
- **载体质量 / Vehicle quality:** 重度稀释 — 蛋白结构这个主题对 NVDA 是**< 1% 收入边际催化**,股价由通用 AI capex 驱动;若想表达 "AI 制药" 主题,NVDA 是错的票。**只在"通用 AI 算力"框下持有,不要把它当作 protein-AF3 的 vehicle**。

## From morning_note #53: 晨会笔记 2026-05-07...
_2026-05-07T05:39_

> ### 1. 头条 / Top call
**AMD** — Q1 数据中心营收 +57% YoY 推动股价 +17.48%（vol 1.6x），但同日 PUT 期权异常爆量：$422/$410/$408/$400 行权价 V/OI 比飙至 600x–3246x（多个 size whale）。
**Implication:** 不要追涨。盘后大涨叠加 ATM PUT 砸单 = 机构在用 PUT 锁定利润或押注回测，二者都偏空。等回踩 $400 附近放量止跌再考虑加仓。

> - **COHR** Q3 收入超预期（AI 数据中心需求强劲），但股价反跌——市场担心 48x EPS 估值；CPO（共封装光学）+ systems optionality 长线逻辑未变。
- **AMD** 财报 DC +57%，验证 MI300 产能爬坡逻辑；但市场用极端 PUT 表态——背离信号要重视。
- **SMCI** 持仓警报触发：fraud_legal 关键词命中 3 条头条 + 当日 +17.21% 放巨量（vol 2.6x）。这是经典"冲高出货 + 法律风险"组合，**不在核心 conviction 但若有持仓必须处理**。

> ### 3. 异常信号 / Anomalies
- **AMD UOA 史诗级**：$422 PUT V/OI=3246x、$410 PUT 2024x（含 size whale）。这种 ATM 大额 PUT 罕见，警惕未来 1–2 周回撤。
- **LRCX PUT $285 V/OI=684x**——半导体设备链同步出现保护性买盘。

> 今日 DB 未标记 conviction list 上的财报/分析师日。重点关注：
- AMD 电话会议复盘（cadence guide for Q2 hyperscaler ramp）。
- COHR 业绩会要点：CPO 客户名单、systems 业务拆分。

> |--------|--------|---------|-------------|
| **AMD** | TRIM (if held >5%) | PUT wall $400–422 形成阻力 + 高位 ATM PUT V/OI 极端 | 放量站稳 $430 且 PUT IV 回落 |
| **COHR** | HOLD, ADD on dip | 回踩 50-DMA 不破 + CPO 客户公告 | AI capex 放缓信号或毛利率指引下修 |

> ---
**Bias 总结:** AI 数据中心需求侧基本面继续 confirm（AMD/COHR/MU 共振），但价格层面机构开始用 PUT 表达短期谨慎——**节奏比方向更重要**。半导体设备/材料链（TSM/ACMR/AXTI）相对受益且无极端期权信号，可作为多头敞口的较稳载体。
