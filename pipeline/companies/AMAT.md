# AMAT -- 综合提取 / All mentions across our research

_Aggregated from 40 mentions across 8 reports. Auto-generated; rerun via `python scripts/compress_dives_to_companies.py`._

---

## From deep_qa #30: ACMR 深度问答...
_2026-05-06T02:08_

> **The honest industry-analyst range** (from memory of Lam/AMAT investor commentary, must verify):
- Mask-layer count: 14nm ~60 layers, 7nm ~80 layers (~30% more masks)

## From tech_dive #40: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T02:34_

> → backside thinning to 30–50 µm     [Disco DBG / SDH grinder, Taiko process]
  → TSV reveal etch                    [Lam, AMAT etchers]
  → CMP planarization                  [AMAT Reflexion / Ebara F-REX + Nagase / Fujimi / Cabot slurry]

> → TSV reveal etch                    [Lam, AMAT etchers]
  → CMP planarization                  [AMAT Reflexion / Ebara F-REX + Nagase / Fujimi / Cabot slurry]
  → bonding (TCB or hybrid)            [ASMPT / Hanmi / BESI Datacon]

## From tech_dive #41: 技术深挖: TSMC CoWoS-L vs Intel EMIB vs Samsung X-Cube: 2.5D adv...
_2026-05-07T02:44_

> ▼
Tool / consumable suppliers (ASML, AMAT, TEL, LRCX for TSV/CMP; Disco for grinding/dicing;
    BESI + ASMPT for hybrid bonding; Hanmi + Shinkawa for TCB; Camtek + Onto for inspection;

> **中文.** 链条 7 段:**云厂/OEM(MSFT/META/GOOG/AMZN/Oracle/xAI/Tesla/主权云)→ 加速器设计公司(NVDA/AMD/Broadcom-定制 ASIC/Marvell-定制 ASIC)→ 晶圆 + 封装代工(TSMC、Intel Foundry、Samsung Foundry)→ OSAT 组装与最终测试(Amkor、ASE/SPIL、KYEC)→ HBM 供应商(SK 海力士第一、Micron 第二、三星追赶)→ ABF 有机基板(Ibiden ~30%、Unimicron ~20%、Nan Ya PCB、Shinko、AT&S、Kinsus)→ 工具/耗材(ASML、AMAT、TEL、LRCX、Disco、BESI、ASMPT、Hanmi、Camtek、Onto、信越/住友 Bakelite)。**

> - **Equipment** — BESI / ASMPT / Hanmi / Disco / Camtek / Onto / AMAT / TEL / LRCX → tool revenue is **leading** the package revenue by ~**4-6 quarters** (tools install, then qualify, then ramp). 2025 is peak tool order intake; 2026-2027 is when the ordered tools translate into hyperscaler accelerator deliveries.

> - **OSAT 外包 WoS(Amkor / ASE)** — 2025H2 起有量,**2026 显著放大**(Amkor 越南二期、ASE 高雄 K28)。
- **设备** — BESI / ASMPT / Hanmi / Disco / Camtek / Onto / AMAT / TEL / LRCX 的设备收入**比封装收入领先 4-6 个季度**;**2025 是设备订单峰值,2026-2027 是订单转化为出货的兑现年**。

> **EN.** The thesis assumes TSMC ramps **CoWoS aggregate ~75k wpm (end-2025) → 135–150k wpm (end-2026)**. **Falsifier:** at any TSMC quarterly earnings call (next one ~2026-07-17), or at the TSMC North America Technology Symposium (next: April 2026 cycle), the CoWoS end-2026 number is officially **revised down by ≥15%** — i.e., to <115k wpm — citing demand softness rather than tooling delays. A demand-driven cut (not a supply slip) means hyperscalers stopped pulling, and the entire chain re-rates downward at once. **Counter-signal to watch:** if the cut is explicitly attributed to ASML/Disco/AMAT tool delays with end-customer orders intact, the bottleneck thesis actually *strengthens* (longer scarcity).

> **中文.** 命题假设 TSMC CoWoS 总产能 ~7.5万 wpm(2025末)→ 13.5–15万 wpm(2026末)。**证伪:** 任何一次 TSMC 法说会(下次 ~2026-07-17)或北美技术论坛(2026 年 4 月一轮)上,CoWoS 2026 年末数字**官方下修 ≥15%**(降至 <11.5万 wpm),且口径归因为"需求疲软"而非工具延迟。需求侧砍单 = 云厂不拉了,整链同步下修。**反向信号:** 如果归因明确为 ASML/Disco/AMAT 工具延迟、终端订单未变,瓶颈论反而**更紧**(稀缺时间更长)。

## From tech_dive #42: 技术深挖: China semi domesticization deep-dive: 盛美 ACMR + 中微 AME...
_2026-05-07T03:00_

> Saved to `pipeline/tech_dive_china_semi_2026-05-07.md`. Topic-wording note up top: I read "non-Pluggable parity" as context-bleed from the prior OCS dive — substantive question is parity vs **foreign WFE/OSAT incumbents** (AMAT, Lam, TEL, SCREEN, ASMI; ASE/Amkor for OSAT) at SMIC's N+2 (~5nm-class FinFET, SAQP DUV, no EUV). Flag that interpretation in Round 2 if wrong.

> Together they cover ~40–55% of WFE BOM by tool count + the OSAT back-end. **Critical gaps not addressed by any of these four**: lithography (ASML / SMEE), ion implantation (AMAT/Axcelis → 凯世通), CMP (AMAT/Ebara → 华海清科), high-end metrology (KLA → 精测/中科飞测).

> Mapped block-by-block in the file. Headlines: **ACMR ↔ TEL UW-300 / SCREEN FC-3300 / Lam Da Vinci** (clean) + **Lam Sabre** (ECP) | **AMEC ↔ Lam Vector / Flex / Vantex + TEL Tactras** (CCP etch, 3D NAND) | **NAURA ↔ AMAT Endura (PVD) / TEL Alpha furnace / ASMI Pulsar (ALD) / AMAT Centura EPI** | **JCET ↔ ASE + Amkor + TSMC InFO/CoWoS**.

> Per vendor: ACMR Tahoe ~80% H2SO4-volume reduction; SAPS sub-65nm particle removal benchmarked at ~99% with <0.05% fin-collapse. AMEC Primo D-RIE in **YMTC 192-layer 3D NAND production** (the hardest non-EUV etch on earth) and Twin SE-CCP **40–60 wph dual-station throughput** vs Lam Vector ~25–35 wph. NAURA dominant domestic share (≈30%+ of CSIA WFE shipments) with PVD Cu-seed defect counts within ~5% of AMAT Endura at 28nm. JCET XDFOI claims ~4× InFO interconnect density at sub-1µm RDL; 40 µm Cu pillar in volume; **largest OSAT capacity in China + STATS ChipPAC overseas hedge**.

> - **ACMR**: backside contamination at <10nm trails TEL/Lam by ~2–3× particle count (the reason SMIC still imports for the most critical metal-layer cleans); megasonic fin damage at AR>30:1; advanced-packaging RDL ECP gap.
- **AMEC**: **conductor etch (Si gate / metal gate) at FinFET not in N+2 production** — Lam Kiyo / AMAT Sym3 dominate. **ALE for GAA 3nm not yet at production**. ICP source uniformity at AR>60:1. Recipe library 3× shallower than incumbents.
- **NAURA**: **EPI for SiGe / Si:P S/D — material gap** (AMAT Centura imported); **HKMG HfO2 ALD — material gap** (ASMI Pulsar imported); "broad but shallow" — rarely best at 5nm-critical steps; R&D split across 8+ lines.

> - **AMEC**: **conductor etch (Si gate / metal gate) at FinFET not in N+2 production** — Lam Kiyo / AMAT Sym3 dominate. **ALE for GAA 3nm not yet at production**. ICP source uniformity at AR>60:1. Recipe library 3× shallower than incumbents.
- **NAURA**: **EPI for SiGe / Si:P S/D — material gap** (AMAT Centura imported); **HKMG HfO2 ALD — material gap** (ASMI Pulsar imported); "broad but shallow" — rarely best at 5nm-critical steps; R&D split across 8+ lines.
- **JCET**: **HBM3+ TSV stacking < 8-high in volume** — the elephant; CoWoS-class 2.5D with Si interposer trails TSMC materially; hybrid-bond Cu-Cu sub-1µm pitch behind TSMC SoIC; >600 mm² die test yield trails ASE/Amkor.

> Full system parity at N+2 still gated by **ASML ArFi + AMAT Centura + ASMI Pulsar + KLA**, none of which these four address.

> |---|---|---|---|---|
| 1 | **688120.SH** | 华海清科 Hwatsing | Equipment — **CMP** | Cleanest pure-play, fills R1 CMP gap. ~RMB 50B mcap, FY24 ~RMB 3.5–4B revenue, ~45% GM. Competitor: AMAT, Ebara. |
| 2 | **688072.SH** | 拓荆 Piotech | Equipment — **CVD/ALD** | R1 named-explicitly fill for NAURA's HKMG ALD / S/D EPI gaps. FY24 ~RMB 4.0–4.5B. Tension: PECVD overlap with NAURA itself. |

> 1. **AMEC FY26 / 1H27 disclosed FinFET-conductor-etch revenue stays <8% of total etch revenue** → falsifies the "AMEC closest single-tool parity at SMIC N+2" call. Today's parity is dielectric/high-AR; conductor etch (Lam Kiyo / AMAT Sym3 turf) is the binding gap.

> **When NOT to own it:** at >12x FY27E EV/Sales, OR if AMAT/Ebara secure a CMP carve-out in any new export-control package — either turns it into a multiple-compression trade.

## From tech_dive #45: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T04:29_

> - TCB: ASMPT + Hanmi Semiconductor ≈ 90% combined share
- Hybrid bonding D2W: BESI + AMAT-led joint ≈ ~80% (BESI alone ~60%)
- Wafer thinning/grinding: Disco ≈ 70%+ on DFG/DBG/Taiko

## From tech_dive #46: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T04:35_

> | **Resonac (4004.JP)**           | **2026 H1** (NCF for Micron/SKH HBM4) | Electronics seg margin lift 200–300 bps |
| **BESI (BESI.AS)** + **Applied (AMAT)** | **HBM4E 2027–2028** (hybrid bonding) | Optionality, not 2026 |
| **Nagase / CMC Materials**      | **2027+** (slurry for hybrid bonding) | Pre-revenue today |

> | **16-Hi inline inspection**             | Camtek / Onto duopoly                  | **CAMT / ONTO**                                            |
| **Hybrid bonding (HBM4E 2027+)**        | BESI + Applied "BE 8800"; EVG; SUSS    | **BESI.AS / AMAT / 8208.DE** (optionality, not 2026 driver) |

> - **观测点**: SK hynix 或 Micron 在 **2026 H2 之前**公开声明 16-Hi 量产路线切换到 **hybrid bonding (Cu-Cu)** 或 **single-pass mass reflow with new MUF**（即不再每层 5–15 秒 TCB），或 ASMPT 季报 **TCB orders QoQ -20% 以上连续两季**。
- **为什么是证伪**: TCB 瓶颈是 ASMPT / Hanmi 估值的全部基础；如果 hybrid bonding 提前两年（原计划 HBM4E 2027–28）攻入 HBM4，BESI / AMAT / EVG / SUSS 替代 ASMPT，0522.HK 与 042700.KS 的 conviction 解构。
- **如何验证**: ASMPT / Hanmi 季报 book-to-bill < 0.9；BESI / AMAT 财报里 "hybrid bonding tools shipped to DRAM" 出现。

> - **为什么是证伪**: TCB 瓶颈是 ASMPT / Hanmi 估值的全部基础；如果 hybrid bonding 提前两年（原计划 HBM4E 2027–28）攻入 HBM4，BESI / AMAT / EVG / SUSS 替代 ASMPT，0522.HK 与 042700.KS 的 conviction 解构。
- **如何验证**: ASMPT / Hanmi 季报 book-to-bill < 0.9；BESI / AMAT 财报里 "hybrid bonding tools shipped to DRAM" 出现。

## From tech_dive #47: 技术深挖: TSMC CoWoS-L vs Intel EMIB vs Samsung X-Cube: 2.5D adv...
_2026-05-07T04:37_

> - **ABF substrate / glass substrate transition / ABF 基板与玻璃基板过渡:** Ajinomoto ABF film for ultra-large packages (>100×100 mm carriers) is supply-constrained; glass-core substrate (Intel/Samsung roadmap 2026–2027) needed for next-gen warpage control but TGV (through-glass-via) tooling immature. / 超大封装(载板 >100×100 mm)的 ABF film 供给紧;玻璃基板(Intel/三星 2026–2027 路线图)对解决翘曲是必需,但 TGV 设备尚未成熟。
- **Hybrid-bonding (no-bump) handoff / 混合键合(无凸点)切换:** Below ~25 µm pitch, μ-bumps fail and **hybrid bonding (Cu-Cu direct + SiO₂-SiO₂)** is required; this needs ultra-clean fab-grade environment and equipment from BESI/AMAT/ASMPT — **the single biggest equipment-side risk for HBM4 (2026) and CoWoS-L generation 2.** / pitch <25 µm 时微凸点失效,需切到混合键合(Cu-Cu + SiO₂-SiO₂),要求 fab 级洁净环境和 BESI / AMAT / ASMPT 设备——**HBM4 (2026) 和二代 CoWoS-L 最大的设备侧风险点**。

> 3. **TSMC → OSAT overflow + substrate + materials.** TSMC subcontracts CoWoS back-end (chip-attach, mold, ball-drop) to **ASE / SPIL / Amkor** when AP6 is full (~10–15% overflow in 2025, dropping in 2026 as AP7/AP8 ramp). Substrate (ABF FCBGA carrier ~$300–600/unit) goes to **Ibiden / Unimicron / Shinko / Nan Ya PCB / Kinsus / AT&S**. Ajinomoto sells ABF film into all of them (~$5–10/unit attributable).
4. **TSMC → Equipment makers (capex, not COGS).** ASML (advanced litho for RDL stitching), AMAT / TEL / Lam (deposition, etch for TSV/RDL), **BE Semiconductor (BESI) and ASMPT for hybrid-bonding tools** (~$5–8M per tool, TSMC ordered 50+ for AP6/AP7/AP8 by 2025), Disco / Tokyo Seimitsu (dicing/grinding), Onto / KLA (metrology).

> 3. **台积电 → OSAT 溢出 + 基板 + 材料。** TSMC 在 AP6 满载时把 CoWoS 后段(贴片、塑封、植球)外包给 **日月光 / 力成 / Amkor**(2025 年外溢约 10–15%,随 AP7/AP8 投产 2026 年回落)。ABF FCBGA 载板单价 ~$300–600 由 **欣兴 / Ibiden / Shinko / 南亚电路 / 景硕 / AT&S** 提供;Ajinomoto ABF 膜可分摊 ~$5–10/封装。
4. **台积电 → 设备厂(资本开支,不入 COGS)。** ASML(RDL 拼接用先进光刻)、AMAT / TEL / Lam(TSV/RDL 沉积、刻蚀)、**BE Semiconductor (BESI) 与 ASMPT 提供混合键合机**(单台 ~$500–800 万美元,TSMC 在 AP6/AP7/AP8 到 2025 年累计下单 50+ 台)、Disco / Tokyo Seimitsu(切割/研磨)、Onto / KLA(量测)。

> **Cap & scale / 市值与体量:** 市值 ~$10B,FY2025 营收 ~$0.7B,员工 ~2k。
**Competitors / 竞争对手:** **ASMPT (0522.HK)**(港股,混合键合 + TCB 双产品线)、AMAT 应用材料 (AMAT.US,刚做大并购布局混合键合)、EV Group(私人,奥地利)。
**Vehicle quality / 标的成色:** **链条上最纯 2.5D/3D 设备多头**——估值贵但属于"合理贵"。小盘子 + 高弹性 + 双寡头格局,是教科书级 picks-and-shovels。

## From tech_dive #48: 技术深挖: China semi domesticization deep-dive: 盛美 ACMR + 中微 AME...
_2026-05-07T04:45_

> | Dielectric etch (CCP) | **Lam Research (US)**, TEL (JP) |
| Conductor etch (ICP) | **Lam (US)**, AMAT (US) |
| ALE / ALD | Lam, AMAT, ASM International (NL), TEL |

> | Conductor etch (ICP) | **Lam (US)**, AMAT (US) |
| ALE / ALD | Lam, AMAT, ASM International (NL), TEL |
| PVD / Cu plating | **AMAT (US)** |

> | ALE / ALD | Lam, AMAT, ASM International (NL), TEL |
| PVD / Cu plating | **AMAT (US)** |
| Furnace / oxidation | **TEL (JP)**, Kokusai (JP, Hitachi Kokusai) |

> | Optical/e-beam metrology | **KLA (US)** ~85% share |
| Ion implant (high-current) | **AMAT (US)** |
| 2.5D / FOWLP packaging | **TSMC InFO/CoWoS**, ASE (TW), Amkor (US/KR) |

> The *core* incumbents being directly attacked at the 5nm-class node by domestic vendors are: **Lam (etch)**, **AMAT (PVD/CMP)**, **SCREEN/TEL (clean & furnace)**, and **ASE/Amkor (advanced packaging)**. ASML and KLA are NOT credibly being challenged in this cycle.

> - **Tool MTBF / 平均无故障时间:** field MTBF for domestic 单片清洗 in early SMIC deployments was **~600–900 hours** vs. SCREEN benchmark of **2,000+ hours**; gap is closing but still ~**2–3×** worse, which directly hits fab utilization. Same pattern in CCP etch.
- **No domestic high-current ion implant** for source/drain doping at <5keV: Beijing-based attempts have not crossed the **1.0E15 atoms/cm² @ <±1% across-wafer uniformity** bar that AMAT VIISta meets routinely. SMIC currently substitutes JP/US tools here.

> | CCP 介质刻蚀 (5nm HAR) | Lam: defectivity 0.03/cm² @ 60:1 | AMEC: ~0.08/cm² @ 60:1 | **Not yet — 12–18 months away** |
| ICP 金属刻蚀 | Lam/AMAT | NAURA | Crossed for non-critical, parity gap closing |
| PVD/ALD | AMAT Endura, ASMI Pulsar | NAURA | **12–24 months away** |

> | ICP 金属刻蚀 | Lam/AMAT | NAURA | Crossed for non-critical, parity gap closing |
| PVD/ALD | AMAT Endura, ASMI Pulsar | NAURA | **12–24 months away** |
| 2.5D Si interposer + FCBGA | TSMC CoWoS $0.40/mm² interposer | JCET XDFOI: $0.25–0.30/mm² | Crossed on cost; **not yet on >2000mm² interposer area or HBM3E stack count** |

> - **Top 1–2 competitors:**
  - Foreign: **Lam Research (LRCX, etch + dep)**, **Applied Materials (AMAT, dep + ion implant)**
  - Domestic: **AMEC (688012.SH)** in CCP etch overlap

> - **Top 1–2 competitors:**
  - Foreign: **Applied Materials (AMAT)**, **ASM International (ASMI.AS)**, **Lam (LRCX)**
  - Domestic: NAURA (688012.SH 内的 dep 部分)

> - Foreign: **KLA Corp (KLAC)** ~85% global metrology — 没有真正对手
  - Foreign: **Applied Materials (AMAT)** e-beam inspection
  - Domestic: 上海精测 (688213.SH 上市子,精测电子 300567.SZ 母)

> This trend sits in the **late-early-innings** zone — past the "is it real" phase (R2: ACMR/AMEC/NAURA/JCET 已计入真实 P&L since 2022–2024,not LOI),but **not yet crowded**:消费级南向资金仍主要持有 SMIC + Huawei concept basket,而 WFE 设备厂 sell-side 覆盖 <12 家(vs Lam/AMAT 的 ~30 家),公募基金在 NAURA/AMEC 的合计仓位 <8% of free float.SMIC 5nm-class wpm 50K → 80K 的过渡 + Ascend 910D 流片是双重催化,向 20x 的赔率仍开放(NAURA + ACMR 2027E 收入翻倍可见,multiple 离 sector peak ~30–40%).
