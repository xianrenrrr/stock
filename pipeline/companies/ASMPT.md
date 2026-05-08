# ASMPT -- 综合提取 / All mentions across our research

_Aggregated from 103 mentions across 7 reports. Auto-generated; rerun via `python scripts/compress_dives_to_companies.py`._

---

## From tech_dive #37: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T02:09_

> # 技术深挖 / Tech deep-dive: HBM4 stacking yield bottleneck: who solves it (Micron 1ynm vs SK hynix 1cnm vs Samsung 1c), what's the equipment + materials chain (e.g. ASMPT TCB, Disco SDH grinder, Nagase polishing slurry), and the public-company beneficiaries

> - **SK hynix**: HBM4 12-Hi mass production at M14/M15X Icheon, 2025-Q3. 1bnm/1cnm + Advanced MR-MUF + Hanmi/ASMPT TCB. TSMC N5 base die.
- **Samsung**: 12-Hi qualification samples 2025-Q4, NCF TCB on 1c, Blackwell-Ultra qual still pending per SemiAnalysis (Mar 2026).

> - **Micron**: 36 GB 12-Hi samples 2025-Q2 on 1γ, ~6 months behind SK hynix on volume.
- **Equipment order book**: ASMPT 2024-Q4 call (TCB order ramp); BESI Datacon 8800 TC; Disco DFG8761+DBG+Taiko at Icheon; Hanmi >50% rev from HBM TCB.
- **JEDEC JESD238** ratified April 2025.

> ## 4. Customer concentration / 客户集中度
**NVIDIA 60–65%** of HBM4 cubes, AMD 10–13%, Broadcom 10–13%, Marvell 5–8% → **top-3 = 85%**. Top-4 hyperscalers = 75–80% of pull. Single-customer risk = NVIDIA cadence. Equipment side: **Hanmi >50% from SK hynix** (highest), ASMPT 3-customer, **Resonac NCF ~90%+ share** (industry toll), **Disco ~95% grinder share but spread across all of semis** (lowest concentration, most bond-like).

> ## 5. Time-to-revenue / 收入时间轴
Already booking: SK hynix (2025-Q3), TSMC base die (2025-Q2), ASMPT (2024-Q4), Hanmi (already), Disco (continuous), Resonac (2025-Q2), Advantest (2025-Q4). 2026 ramp: Micron (Q1), Samsung (Q2 conditional on Blackwell-Ultra qual). 2027 call: BESI hybrid bonding. **Samsung qual = biggest 2026 swing factor.**

> | 3 | `2330.TW`/`TSM` | TSMC | Foundry / base die + CoWoS | N5/N4 base die for SK hynix; CoWoS gating whole chain | ~$0.9–1.05T | Owns the bottleneck; HBM <2% of rev — diversified |
| 4 | `0522.HK` | ASMPT | TCB tools | TCB platform shipping to SK hynix + Micron | ~$4–6B | Diversified bonding tools, HBM is highest-growth piece |
| 5 | `042700.KS` | Hanmi Semiconductor | TCB pure-play | Dual TC Bonder Griffin; >50% rev from SK hynix HBM | ~$5–6.5B | **Cleanest TCB pure-play** in public markets |

> The closed loop (tech → business → equity surface) is now complete. The four highest-information events to track for 2026 are SK hynix monthly bit-shipment guidance, ASMPT/Hanmi quarterly book-to-bill, Resonac NCF capacity announcements, and Samsung Blackwell-Ultra qualification.

> - **Where it sits**: cube layer (SK hynix/Micron) NOT pre-discovery — already 4x'd; TCB incumbents (Hanmi, ASMPT) late-mid cycle; **BESI hybrid bonding + Resonac NCF still pricing 2026 not 2027–28** — the residual asymmetry sits there.
- **90-day signal**: **Samsung Q2 2026 earnings (late July) — yes/no on Blackwell-Ultra HBM4 qual.** One binary swings the whole thesis.

## From tech_dive #38: 技术深挖: TSMC CoWoS-L vs Intel EMIB vs Samsung X-Cube: 2.5D adv...
_2026-05-07T02:24_

> 4. **Customer concentration risk** — oligopsony every layer. NVIDIA was ~60–65% of CoWoS in 2024, normalizing to ~50% (NVIDIA+AMD ~70–75% of CoWoS-L 2026); 6 end-buyers (MSFT/META/GOOG/AMZN/ORCL/xAI) dominate; TSMC ~90% of leading-edge packaging; Ibiden+Unimicron+Shinko ~65% of giant substrate; ASMPT+Hanmi ~80% of TCB; **Ajinomoto ~100% on ABF film — single most concentrated chokepoint in the entire chain.** Asymmetric two-way dependency illustrated by the 2024-Q4 → 2025-Q1 CoWoS reallocation episode.

> | 3 | **4062.JP** Ibiden | ABF organic substrate | B+ |
| 4 | **0522.HK** ASMPT | TCB / advanced-packaging equipment | B+ |
| 5 | **CAMT** Camtek | Advanced-packaging inspection | **A — cleanest pure-play** (~50%+ trend, ~80% adv-pkg) |

> Cross-layer read-across notes included so the operator can use one name's signal to pre-trade another (TSMC capacity guide → whole-chain ceiling; Ibiden tightness → "bottleneck moved to substrate"; ASMPT-vs-BESI bookings → TCB-to-hybrid-bonding substitution timing).

## From tech_dive #40: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T02:34_

> # 技术深挖 / Tech deep-dive: HBM4 stacking yield bottleneck: who solves it (Micron 1ynm vs SK hynix 1cnm vs Samsung 1c), what's the equipment + materials chain (e.g. ASMPT TCB, Disco SDH grinder, Nagase polishing slurry), and the public-company beneficiaries

> **Topic:** HBM4 stacking yield bottleneck — Micron 1γ vs SK hynix 1cnm vs Samsung 1c, the equipment + materials chain (ASMPT TCB, Disco SDH grinder, Nagase polishing slurry), and the public-company beneficiaries

> → CMP planarization                  [AMAT Reflexion / Ebara F-REX + Nagase / Fujimi / Cabot slurry]
  → bonding (TCB or hybrid)            [ASMPT / Hanmi / BESI Datacon]
  → underfill (NCF / MR-MUF) or anneal [Resonac NCF film, Nagase polishing media]

> - Mass production declared at M14/M15X Icheon: **2025-Q3** (company IR, September 2025).
- Process: **1bnm/1cnm hybrid + Advanced MR-MUF + TCB** (Hanmi Semiconductor + ASMPT TCB heads).
- **TSMC N5 base die** for HBM4 (publicly confirmed via Reuters / DigiTimes mid-2025).

> **Equipment — order-book confirmations / 订单层面验证**
- **ASMPT** flagged HBM4 TCB order ramp on its **2024-Q4 earnings call**.
- **BESI** Datacon 8800 TC NEXT: HBM4 production tool of record at hyperscaler/foundry level (BESI 2024 annual report). Hybrid-bonding tools shipped to Samsung/TSMC R&D, not yet HBM4 production.

> │  pays for: TSMC/Samsung-Foundry base die wafers (~$15–20k per N5 wafer),
       │            Disco grinders + Hanmi/ASMPT TC bonders + BESI hybrid pilot tools,
       │            Resonac NCF film + Nagase/Cabot CMP slurry + Advantest test heads

> ▼
Equipment + materials   (ASMPT 0522.HK, Hanmi 042700.KS, Disco 6146.T, BESI BESI.AS,
                         Resonac 4004.T, Advantest 6857.T, Camtek CAMT, Entegris ENTG)

> - **Memory maker (SK hynix)**: HBM gross margin **>55%** vs. commodity DRAM 30–35% — HBM is now **>80% of SK hynix's profit pool** despite being <40% of bit shipments (Q3 2025 IR).
- **TCB equipment (Hanmi, ASMPT)**: **35–45% GM** on HBM tools, vs. 20–25% on legacy wirebond.
- **Materials (Resonac NCF, Cabot CMP)**: **40–50% GM**, design-wins sticky by qual cycle (~3 years to displace).

> | --------------------------------- | ------------------ | ----------------------------------------------- |
| **Hanmi Semiconductor (042700.KS)** | **Highest**: >50% revenue from SK hynix HBM TCB | If Samsung passes Blackwell-Ultra qual and shifts orders to ASMPT, Hanmi exposed |
| **ASMPT (0522.HK)**               | 3-customer dependency: SK hynix + Samsung + TSMC CoWoS | Better diversified than Hanmi              |

> | **Hanmi Semiconductor (042700.KS)** | **Highest**: >50% revenue from SK hynix HBM TCB | If Samsung passes Blackwell-Ultra qual and shifts orders to ASMPT, Hanmi exposed |
| **ASMPT (0522.HK)**               | 3-customer dependency: SK hynix + Samsung + TSMC CoWoS | Better diversified than Hanmi              |
| **BESI (BESI.AS)**                | TSMC R&D + Samsung Foundry + Micron pilot     | Pre-volume; concentration follows hybrid-bonding adoption |

> | **TSMC (2330.TW / TSM)** — base die + CoWoS | **2025-Q2 already** (N5 base die wafers booking for SK hynix) | Advanced packaging revenue **+80–100% YoY** continuing |
| **ASMPT (0522.HK)**                        | **2024-Q4 onward** (TCB orders booked through 2025); 2026 = peak | HBM-related revenue **+40–60% YoY**          |
| **Hanmi Semiconductor (042700.KS)**        | **2024 onward** (>50% of revenue already HBM TCB) | 2026 HBM revenue **+30–50% YoY**, 2027 cyclical risk if hybrid bonding pulls in |

> **Cleanest current-quarter beneficiaries (already in revenue):** SK hynix, TSMC, Hanmi, ASMPT, Disco, Resonac, Camtek, Advantest.
**Cleanest 2027 optionality (not yet in revenue):** BESI (hybrid bonding mass-production).

> **中文**:**收入已经在路上,不是 LOI 阶段**。当期已落地受益:SK hynix(已量产)、TSMC(已出货 base die + CoWoS)、Hanmi(2024 起)、ASMPT(2025 订单)、Disco/Resonac/Advantest/Camtek(已贡献收入)。最干净的 **2027 弹性** 是 BESI(混合键合量产)。**2026 最大变量**:三星能否 2026-Q2 拿下 Blackwell-Ultra HBM4 qualification —— 通过则供应格局变化,失败则 SK hynix 维持 50%+ 份额。

> 4. **Concentration is the trade**: NVIDIA = 60–65% of cube demand; top-3 buyers = 85%; top-4 hyperscalers = 75–80% of pull. The chain rises and falls with NVIDIA's quarterly cadence.
5. **Time-to-revenue is now**: SK hynix, TSMC, ASMPT, Hanmi, Disco, Resonac, Advantest, Camtek all booking HBM4-driven revenue in 2025–2026. **BESI is the 2027 call**. **Samsung is the 2026 swing factor**.

> ## 3. ASMPT — `0522.HK` / HKEX

> - **Market cap + scale**: ~**KRW 5–7 T (~USD 3.5–5 B)**. 2025 revenue ~KRW 800 B–1 T (rough). Operating margin 35%+ in 2024–2025 thanks to HBM mix.
- **Top competitors**: ASMPT (`0522.HK`) globally; Hanwha Semitech (Korean private — emerging credible second source for SK hynix); BESI.
- **Vehicle quality**: **Highest-beta single-name on the entire chain.** Pure HBM TCB exposure with single-customer (SK hynix) concentration. Up violently when SK hynix wins; **acutely exposed if Samsung passes Blackwell-Ultra qual** (Samsung uses ASMPT not Hanmi) or if hybrid bonding pulls in faster than 2027.

> - **Top competitors**: ASMPT (`0522.HK`) globally; Hanwha Semitech (Korean private — emerging credible second source for SK hynix); BESI.
- **Vehicle quality**: **Highest-beta single-name on the entire chain.** Pure HBM TCB exposure with single-customer (SK hynix) concentration. Up violently when SK hynix wins; **acutely exposed if Samsung passes Blackwell-Ultra qual** (Samsung uses ASMPT not Hanmi) or if hybrid bonding pulls in faster than 2027.

> - **Market cap + scale**: ~**EUR 10–13 B (~USD 11–14 B)**. 2025 revenue ~EUR 600–700 M. Trading at premium multiple — **the market has already priced 2027** (re-test if PE compresses).
- **Top competitors**: ASMPT (CoWoS hybrid bonding pilot lines); EV Group (Austrian private — wafer-bonding leader, enters HBM via D2W).
- **Vehicle quality**: **The 2027 call**. Pre-revenue on the hybrid-bonding wave, but design-in already happening. Diversified across logic 3D + HBM4E + automotive packaging — multiple shots on goal.

> - **Layer**: TCB equipment (emerging second source).
- **Why critical**: SK hynix has reportedly qualified Hanwha as **second source for HBM TCB bonders**, breaking Hanmi's monopoly grip on that account. If realized at volume, dilutes Hanmi (`042700.KS`) and bleeds into ASMPT pricing.
- **Investability**: Listed within Hanwha Group; cleanest public proxy is **Hanwha Solutions (`009830.KS`)** but the equipment unit is buried under solar/petchem. Watch for a 2026–2027 IPO carve-out — that would be the cleanest direct vehicle.

> | Foundry base die + CoWoS | (none)              | TSMC `2330.TW / TSM`     | TSMC                   |
| TCB equipment            | Hanmi `042700.KS`    | ASMPT `0522.HK`         | Hanmi (single-customer) |
| Hybrid bonding (2027)    | BESI `BESI.AS`       | BESI                    | BESI (pre-revenue)     |

> - **Observable signal**: BESI flags **HBM4E hybrid-bonding production tool revenue** in 2026-H1 (not 2027-H1 as currently telegraphed), OR TSMC announces a hybrid-bonding HBM customer in a 2026 earnings call. Specifically: *"first HBM hybrid-bonding production tools shipping"* on a BESI quarterly.
- **Why it falsifies (in a specific direction)**: The current chain narrative gives TCB/NCF a clean run through 2027–2028 before hybrid bonding takes share. An early hybrid-bonding pull-in **destroys Hanmi's 2027–2028 cash flow** (TCB-only exposure) and **front-loads BESI's revenue curve by ~12 months**. The trade thesis isn't broken — it *rotates* violently from Hanmi/ASMPT to BESI inside 90 days.
- **Sub-signal**: D2W (die-to-wafer) hybrid bonding KGSD yield breaking 70% in any public disclosure (currently <50% per industry triangulation).

> **Zone read**: This trend is **past the "before-it-20x" zone but not yet crowded**. Evidence: SK hynix HBM is already >80% of profit pool; HBM TAM has tripled since 2023; the names in Round 3 (Hanmi, ASMPT, Camtek, Disco) have already re-rated 2–4× in 18 months. But CoWoS-L is still oversold through 2026, single-die yield at 1c is the binding constraint, and 2027 hybrid-bonding optionality is unpriced at most names. **Mid-cycle, not late-cycle.**

## From tech_dive #41: 技术深挖: TSMC CoWoS-L vs Intel EMIB vs Samsung X-Cube: 2.5D adv...
_2026-05-07T02:44_

> **(c) HBM stacking and TCB throughput / HBM 堆叠与 TCB 节拍.** HBM4 moves to 16-Hi stacks with hybrid bonding (Cu-Cu) inside the cube. Hybrid-bonding tools (BESI/ASMPT) are still ramping; thermo-compression bonding (TCB) cycle times of **~10–15 s/die** vs. mass-reflow's **~0.5 s/die** structurally cap line throughput. Hanmi, ASMPT, Shinkawa supply is concentrated in 3 vendors.

> Tool / consumable suppliers (ASML, AMAT, TEL, LRCX for TSV/CMP; Disco for grinding/dicing;
    BESI + ASMPT for hybrid bonding; Hanmi + Shinkawa for TCB; Camtek + Onto for inspection;
    Shin-Etsu / Sumitomo Bakelite for EMC + dielectric)

> **中文.** 链条 7 段:**云厂/OEM(MSFT/META/GOOG/AMZN/Oracle/xAI/Tesla/主权云)→ 加速器设计公司(NVDA/AMD/Broadcom-定制 ASIC/Marvell-定制 ASIC)→ 晶圆 + 封装代工(TSMC、Intel Foundry、Samsung Foundry)→ OSAT 组装与最终测试(Amkor、ASE/SPIL、KYEC)→ HBM 供应商(SK 海力士第一、Micron 第二、三星追赶)→ ABF 有机基板(Ibiden ~30%、Unimicron ~20%、Nan Ya PCB、Shinko、AT&S、Kinsus)→ 工具/耗材(ASML、AMAT、TEL、LRCX、Disco、BESI、ASMPT、Hanmi、Camtek、Onto、信越/住友 Bakelite)。**

> - **Tooling:** ASML EUV (single source); Disco grinding/dicing (~80%+ of advanced thin-wafer dicing market); BESI + ASMPT split hybrid bonding ~50/50 with no third entrant; Hanmi + Shinkawa dominate TCB.

> - **ABF 基板** — Ibiden ~30%、Unimicron ~20%、Shinko ~15%、Nan Ya ~10%、AT&S/Kinsus 其他;**前 2 ≈ 50%、前 3 ≈ 65%**。Ibiden 大垣一期是若干 NVDA SKU 的单源。
- **工具** — ASML EUV 单源;Disco 在先进薄圆片切割 >80%;BESI + ASMPT 平分 hybrid bonding;Hanmi + Shinkawa 占 TCB。
- **需求端** — 前五云厂(MSFT/META/GOOG/AMZN/ORCL)买走 **~70-75%** NVDA 数据中心收入;加 xAI/Tesla/Apple/主权云,前 15 占 ~95%。**5 家中有 3 家暂停 AI capex,2 季度内整条 2.5D 链子收入塌方。**

> - **Equipment** — BESI / ASMPT / Hanmi / Disco / Camtek / Onto / AMAT / TEL / LRCX → tool revenue is **leading** the package revenue by ~**4-6 quarters** (tools install, then qualify, then ramp). 2025 is peak tool order intake; 2026-2027 is when the ordered tools translate into hyperscaler accelerator deliveries.

> **Bottom line on timing:**
- **Live now (2025):** TSMC CoWoS, NVDA Blackwell, AMD MI300X/MI325X, AWS Trainium2, Google TPU v5p/v6, SK hynix HBM3e, Ibiden ABF, BESI/ASMPT/Hanmi tools, Amkor/ASE outsourced WoS.
- **Inflection 2026:** CoWoS-L mix dominates, MI350 ramps, Maia v2 / MTIA v2 / TPU v6 step up, HBM4 starts, Rubin samples, Ibiden Phase-1 fully online, EMIB-T external.

> - **OSAT 外包 WoS(Amkor / ASE)** — 2025H2 起有量,**2026 显著放大**(Amkor 越南二期、ASE 高雄 K28)。
- **设备** — BESI / ASMPT / Hanmi / Disco / Camtek / Onto / AMAT / TEL / LRCX 的设备收入**比封装收入领先 4-6 个季度**;**2025 是设备订单峰值,2026-2027 是订单转化为出货的兑现年**。

> **时间线 TL;DR:**
- **2025 已实收入:** TSMC CoWoS、NVDA Blackwell、AMD MI300X/MI325X、Trainium2、TPU v5p/v6、SK 海力士 HBM3e、Ibiden ABF、BESI/ASMPT/Hanmi 设备、Amkor/ASE 外包 WoS。
- **2026 拐点:** CoWoS-L 占比反客为主、MI350 起量、Maia v2/MTIA v2/TPU v6 抬量、HBM4 开始、Rubin 送样、Ibiden 一期满产、EMIB-T 外部首单。

> ## 4. ASMPT — 0522.HK (HKEX)

> - **Layer / 链条位置:** Advanced-packaging equipment — TCB (thermo-compression bonder) for HBM stacking + chiplet placement; flip-chip bonders; co-development partner with TSMC on hybrid bonding. ASMPT + Hanmi ≈ ~80% of TCB market.
- **Specific SKU / 直接 SKU:**

> 中文:**TCB 是 HBM 堆叠 + chiplet 放置必经设备,2.5D 产能扩张 = TCB 订单。** 风险:hybrid bonding 替代 TCB 节奏 — 若 BESI 节奏快于预期,2027+ ASMPT 必须把 hybrid bonder 跑到位才能续命。Hanmi 在 Hynix 那边有 captive 优势,所以 ASMPT 更靠 TSMC 一侧。

> | 3 | 4062.T | Ibiden | ABF substrate (giant body) | ~$10B | ~30–35% | B+ |
| 4 | 0522.HK | ASMPT | TCB / AP equipment | ~$6.5B | ~25–30% rev / 50%+ op profit | B+ |
| 5 | CAMT | Camtek | AP inspection / metrology | ~$6B | ~50%+ | **A (cleanest pure-play)** |

> - **Ibiden is the read-across for "is the bottleneck moving from interposer to substrate"** — multi-quarter Ibiden capacity-tight signal would say yes, dragging Unimicron + Nan Ya PCB up with it.
- **ASMPT vs. BESI** — TCB-vs-hybrid-bonding is the substitution debate; if BESI bookings re-accelerate faster than ASMPT, 2027+ tool-mix is shifting and ASMPT terminal value should be marked down.
- **Camtek + Advantest are pick-and-shovel cleanest reads** — both grow with packaging volume regardless of which architecture wins. Less optionality than integrator/memory but lower architectural risk.

> **EN.** This is **a late-mid-cycle thesis, not "before-it-20x."** Evidence: TSMC AP segment already ~$8–10B FY2025 with consensus ~$15–20B FY2026; Hynix HBM ~40% of revenue; NVDA datacenter run-rate $140–170B in 2025; Camtek/ASMPT/Advantest have already moved 3–5× off 2023 lows. The 20× window was 2022–2024 (when CoWoS demand was first being recognized). What remains is a 2–3× compounder if 2026 hyperscaler capex prints as guided and CoWoS supply stays binding through end-2026. **Single 90-day signal to watch:** the next TrendForce CoWoS supply/demand update plus TSMC's Q2-2026 earnings (~July 17) — specifically whether the *2027* CoWoS wpm number is raised, held, or cut versus prior commentary. That single data-point reprices the entire chain. **Cleanest entry today: Camtek (CAMT)** — ~50%+ trend-attributable, ~80% advanced-packaging revenue, lowest architectural-risk pick-and-shovel. **Do not own** if (i) any falsifier 1–3 fires, or (ii) CAMT trades >35× forward earnings on an unchanged TSMC capex print — the multiple-expansion is then doing the work, not the thesis.

> **中文.** 这是**中后段命题,不是"20× 起跑前"。** 证据:TSMC 先进封装 2025 已 $80-100 亿、2026 共识 $150-200 亿;海力士 HBM 占营收 40%;NVDA 数据中心 2025 跑率 $1,400-1,700 亿;Camtek/ASMPT/Advantest 较 2023 低点已上行 3-5×。**20× 窗口是 2022-2024**(CoWoS 需求被首次认知时)。剩下是一个 2-3× 复合机会 — 前提是 2026 云厂 capex 兑现指引、CoWoS 紧张延续到 2026 末。**90 天唯一观察信号:** 下一份 TrendForce CoWoS 供需更新 + TSMC 2026Q2 法说会(~7 月 17 日),具体看 **2027** CoWoS wpm 数字相对此前是抬、平、还是降。这一个数据点重定价整条链。**当下最干净入口:Camtek (CAMT)** — 趋势归因 50%+、先进封装收入 80%、架构风险最低的"卖铲人"。**不应持有** 的情形:(i) 证伪 1–3 任一触发,或 (ii) TSMC capex 不变的前提下 CAMT forward PE >35× — 此时驱动是估值扩张而非命题本身。

## From tech_dive #45: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T04:29_

> # 技术深挖 / Tech deep-dive: HBM4 stacking yield bottleneck: who solves it (Micron 1ynm vs SK hynix 1cnm vs Samsung 1c), what's the equipment + materials chain (e.g. ASMPT TCB, Disco SDH grinder, Nagase polishing slurry), and the public-company beneficiaries

> - **JEDEC JESD238 (HBM4)** ratified **April 2025**: 2048-bit IO, up to 8 Gbps/pin, 12-Hi/16-Hi stacking, RAS extensions codified.
- **SK hynix HBM4 12-Hi**: samples to NVIDIA / AMD **2025-Q1**; mass production declared at **M14/M15X Icheon, 2025-Q3** (company IR briefing September 2025). Process: 1bnm/1cnm DRAM + Advanced MR-MUF + TCB (Hanmi dual-head + ASMPT) + **TSMC N5 base die** (publicly confirmed mid-2025 — first commercial logic-foundry HBM base die at scale).
- **Micron HBM4 12-Hi 36 GB**: samples to "lead AI customers" **2025-Q2** (June 2025 earnings call); volume ramp 2026-Q1 into Rubin / MI400. Process: 1γ DRAM + MR-MUF-equivalent. Idaho + Hiroshima fabs.

> - **Hybrid bonding readiness (HBM4E)**: BESI Datacon hybrid bonders shipped to TSMC SoIC R&D, Samsung Foundry R&D, and SK hynix HBM4E pilot lines; Tokyo Electron, Applied Materials, EVG demonstrated D2W tools at SEMICON Japan 2024 and SEMICON West 2025. **Not yet at HBM production yield in 2026.**
- **Equipment / materials install base** validated in 2024–2025 order books: ASMPT TCB ramp flagged on 2024-Q4 earnings; Hanmi Semiconductor reports >50% revenue from HBM TCB; Disco DFG8761 grinder + DBG + Taiko in production at SK hynix Icheon; Resonac NCF capacity expansion at Yokohama (2025) called out specifically for HBM.

> 中文要点:HBM4 标准 2025-04 批准 (JESD238)。**SK hynix 2025-Q3 已量产** (M14/M15X)、**Micron 2026-Q1 起量产**、**三星仍未通过 NVIDIA Blackwell-Ultra qual**。混合键合用于 HBM4E,2026 仍在试产。ASMPT、Hanmi、Disco、Resonac 在 2024–2025 已实际确认 HBM4 收入。

> Equipment + materials rent layer:
   - ASMPT TCB + Hanmi dual-head TCB (~$3–4 M per tool, ~600+ tools 2025–2027 cumulative)
   - BESI Datacon hybrid bonders (~$10–12 M per tool, HBM4E ramp 2027+)

> **Equipment-tier concentration (the rent layer):**
- TCB: ASMPT + Hanmi Semiconductor ≈ 90% combined share
- Hybrid bonding D2W: BESI + AMAT-led joint ≈ ~80% (BESI alone ~60%)

> - NCF: Resonac (formerly Showa Denko) ≈ 80%+
- TC bonder + advanced reflow ovens: ASMPT, Shinkawa (Hakuto), Toray
- Test cells (KGSD HBM4 head): Advantest ≈ 60–65%, Teradyne ≈ 30–35%

> **Concentration risk reads both ways**: equipment vendors enjoy near-monopoly economics today, but **a single customer cancellation (e.g. Samsung HBM4 program halt) materially impacts ASMPT/Hanmi 2026 revenue by 8–12%**.

> | **Samsung** HBM4 12-Hi | **2026-Q2 at earliest, 2026-Q3 base case** | NVIDIA Blackwell-Ultra qual still pending per Reuters Feb 2026; revenue contingent on this qualification |
| **ASMPT** (TCB) | **Already booked 2024-Q4 onward** | Q4 2024 earnings flagged "step-up in HBM4 TCB orders"; FY25 HBM-related revenue guided ~30% of bonding segment |
| **Hanmi Semiconductor** | **Already booked** | Reported >50% of total revenue from HBM TCB through 2025; FY25 revenue +60% YoY |

> **Critical insight on the ordering**: the equipment + materials layer is **pre-paid against future cube revenue** — Disco, ASMPT, Hanmi, Resonac all booked HBM4 revenue in 2024–2025 *before* Micron and Samsung shipped a single qualified HBM4 cube. **The picks-and-shovels theory has already been validated in the income statements.** What is *not* yet validated is the BESI / hybrid-bonding hypothesis — that's the 2027 trade.

> 3. **总量**:2026 HBM TAM ~$45–55 B,2026 出货 ~50 M cubes,**供给受限,不是需求受限**。
4. **客户集中**:NVIDIA + AMD + 三大 ASIC = 85–95% 需求;三家 HBM 厂垄断供给;BESI、ASMPT、Hanmi、Disco、Resonac 在各自工序近垄断。任一玩家失误立即收紧 20%+ 供给。
5. **真实收入时间**:SK hynix、ASMPT、Hanmi、Disco、Resonac、TSMC **已经入账**;美光 2026-Q1 起量;三星 2026-Q2/Q3 视 NVIDIA qual;**BESI 是 2027 才看得见的真钱**。

> 4. **客户集中**:NVIDIA + AMD + 三大 ASIC = 85–95% 需求;三家 HBM 厂垄断供给;BESI、ASMPT、Hanmi、Disco、Resonac 在各自工序近垄断。任一玩家失误立即收紧 20%+ 供给。
5. **真实收入时间**:SK hynix、ASMPT、Hanmi、Disco、Resonac、TSMC **已经入账**;美光 2026-Q1 起量;三星 2026-Q2/Q3 视 NVIDIA qual;**BESI 是 2027 才看得见的真钱**。

> - **Market cap**: ~KRW 5 T (~$3.5–4 B USD). FY2025 revenue ~KRW 600 B (~$430 M). ~700 employees. KOSDAQ-listed mid-cap.
- **Competitors**: `0522.HK` ASMPT (TCB on Micron / Samsung lines), Shinkawa (Yamaha-affiliated, Japanese). Hanmi's moat is its incumbency at the SK hynix line and the dual-head throughput edge.
- **Vehicle quality**: **the cleanest TCB pure-play on the board** — almost the entire equity is a function of HBM stacking volume × TCB tool intensity. Stock has 5×'d off late-2023; the multiple is now full and the upgrade cycle to 16-Hi is the next leg, but **a hybrid-bonding-earlier-than-2027 outcome compresses this name fastest**.

> ### B2 — `0522.HK` ASMPT / Hong Kong Stock Exchange
- **Layer**: TCB + advanced packaging equipment (also wire bonders, surface-mount, semi-conductor solutions).

> - **Market cap**: ~HK$45–55 B (~$5.5–7 B USD). FY2025 revenue ~HK$15 B. ~17 K employees. HK-listed but with substantial European (Switzerland Datacon roots) operating structure.
- **Competitors**: `042700.KQ` Hanmi, BESI (in advanced packaging at the high end), Shinkawa. ASMPT has the broader product surface; Hanmi has the SK hynix incumbency.
- **Vehicle quality**: **diversified beneficiary** — HBM is real and growing but not majority of revenue (vs Hanmi's purity). Pays a dividend, lower beta, slower upside but lower drawdown risk than Hanmi.

> - **Layer**: TCB + dispense systems supplied into Korean memory (specifically TCB tooling for Samsung HBM and SK hynix line additions).
- **Why it matters**: As Samsung pushes HBM4 yield in 2026, Hanwha Semitech is the back-up TCB vendor inside the Korean ecosystem — ASMPT's effective challenger from inside the country. **The Korean "domestic substitution" play**. The Hanwha parent ticker `000880.KS` is an industrial conglomerate where Semitech is too small to move the SOTP — so this is a watch-the-orderbook signal, not an investment vehicle. Watch it via Samsung CapEx Day disclosures.

> | TCB pure-play | `042700.KQ` Hanmi | **Pure-play** | Highest beta to 2025–2027 TCB cycle, highest hybrid-bonding-arrival risk |
| TCB diversified | `0522.HK` ASMPT | Diversified | Lower-beta TCB exposure, dividend-paying |
| Hybrid bonding | `BESI.AS` BESI | **Pure-play** | The only public way to own the 2027–2028 HBM4E inflection |

> | Private (watch) | EV Group | n/a | Structural BESI competitor — gates the BESI monopoly thesis |
| Private (watch) | Hanwha Semitech | n/a | Korean TCB substitution into Samsung — gates ASMPT/Hanmi share |

> **中文小结:** 链条上至少 **8 个公开标的横跨 5 层** — 立方体厂(SK hynix、Micron)、TCB 设备(Hanmi、ASMPT)、混合键合(BESI)、减薄(Disco)、材料(Resonac)、测试(Advantest)、代工底片/封装(TSMC)。**最纯标**:Hanmi(TCB 当下)、BESI(混合键合 2027)。**最被低估**:Resonac(NCF 垄断卡在化工集团估值里)、Disco(收过路费,与键合路线无关,不会被证伪)。**关键私营**:EVG(奥地利,BESI 唯一对手)、Hanwha Semitech(韩国本土 TCB 替代,看 Samsung CapEx 拿单)。

> If hybrid bonding lands a year early, **TCB pure-plays — Hanmi above all — re-rate down sharply**. Hybrid bonding does not need to be cheaper to win; it needs to be cooler (Round 2 argument). Once HBM4E pilot yield clears 70%, hyperscalers fund the migration to recover power headroom. Watch: BESI quarterly transcripts ("HBM4E pilot yield," "qualification with [redacted customer]"); Imec ITF papers; SK hynix M15X tool-vendor split disclosures.
中文:**BESI/EVG 在 2026-Q4 前混合键合 D2W 试产良率 >70%** — Hanmi、ASMPT 估值塌陷。

## From tech_dive #46: 技术深挖: HBM4 stacking yield bottleneck: who solves it (Micron ...
_2026-05-07T04:35_

> # 技术深挖 / Tech deep-dive: HBM4 stacking yield bottleneck: who solves it (Micron 1ynm vs SK hynix 1cnm vs Samsung 1c), what's the equipment + materials chain (e.g. ASMPT TCB, Disco SDH grinder, Nagase polishing slurry), and the public-company beneficiaries

> - **16-Hi stack-level yield 坍塌**：单层 die yield 即便 99%，16 层串联后理论上限 ~85%，加上 bonding/warpage 缺陷实际 30–40%——直接决定 HBM4 单价
- **TCB throughput 瓶颈**：TCB 每个 bond cycle 5–15 秒，相比 MR（mass reflow 一次过炉）慢 **~10×**。要做 16-Hi 等于一个 stack 占用 TCB 机台 2–4 分钟，**ASMPT / Shinkawa 的 TCB 机台产能成为全行业瓶颈**
- **Die thinning <30 μm 导致 wafer handling 脆弱**：DAF（die attach film）+ backgrinding 工序中破片率上升；**Disco DBG (Dicing Before Grinding) + SDH 系列研磨机** 是少数能稳定做到 25–20 μm 的设备

> ▼                             ▼
TCB equipment (ASMPT, Shinkawa/Hanmi) -- $1.5–2.5M/tool
Thinning/dicing (Disco SDH, DAS300/8800)

> - **Break-even for hyperscaler**: a Rubin GPU at $40k with 8 HBM4 stacks delivers 13 TB/s vs B200 at $30–35k with 8 HBM3E delivering 8 TB/s. **$/TB/s drops ~25–30%**, which is the sole reason hyperscalers absorb the $5k stack price
- **Equipment payback**: an ASMPT TCB tool at $2M doing 16-Hi stacks @ 3 min/stack × 24/7 × 70% utilization = **~110k stacks/yr**; at $200 bonding service revenue per stack ≈ $22M/tool/yr → **payback < 12 months** for OSAT — explains why TCB capacity is being booked through 2027

> - **Equipment TAM lift**:
  - **TCB tools**: ~600 installed base (HBM3E era) → **needs 1,500+ by 2027**, ~$2B incremental tool revenue (ASMPT 50%+ share, Hanmi 25%, Shinkawa 15%)
  - **Disco SDH/DAS**: ~$800M HBM-attributable revenue 2025 → ~$1.5B 2027

> - **Equipment-chain concentration**:
  - TCB: **ASMPT alone holds Nvidia/SKH-aligned spec** for 16-Hi — single point of failure
  - Thinning: Disco **>90% global share** in precision wafer grinding

> | **TSMC (2330.TW / TSM)**        | **Booked in CoWoS-L revenue from 2H2025**, HBM4 base die spike **2026 H2** | Already material; HBM4 base die adds ~$2B 2026 |
| **ASMPT (0522.HK)**             | **Order book inflection 2H2025** → **revenue 2026 H1** | Semi-solutions seg: HBM4 TCB orders ~$500–700M of incremental backlog disclosed Mar-2025 |
| **Disco (6146.JP)**             | **Already in revenue** (HBM3E ramp); HBM4 step-up **2026 Q2** | Op margin 38–40%; HBM mix ~25% of revenue and growing |

> - **SK hynix** — sole-source HBM4 launch supplier, structural monopoly Q4 2025–Q3 2026
- **ASMPT** — TCB monopoly through 2027, equipment-bookings leading indicator
- **Disco** — pricing power from <30 μm thinning capability, no credible competitor

> ### 3. **0522.HK — ASMPT / HKEX** —— `equipment — TCB monopoly`
- **Layer**: Back-end packaging tools — **TCB bonders** (Thermal Compression Bonding), die attach, hybrid bonding pilot

> - **Market cap / scale**: ~**KRW 12T (~$8.5B USD)**; 2025 revenue ~KRW 550B (~$400M); ~700 employees; op-margin 40%+
- **Top competitors**: ASMPT (0522.HK) globally; **Shinkawa** (under 7272.JP) at Samsung
- **Vehicle quality**: **Cleanest Korean pure-play on HBM stacking equipment.** Single-customer concentration risk — SK hynix is >50% of revenue. If SK hynix shifts a TCB share to ASMPT, hits hard. Local-listing access friction for non-Korean investors.

> - **Top competitors**: ASMPT (0522.HK) globally; **Shinkawa** (under 7272.JP) at Samsung
- **Vehicle quality**: **Cleanest Korean pure-play on HBM stacking equipment.** Single-customer concentration risk — SK hynix is >50% of revenue. If SK hynix shifts a TCB share to ASMPT, hits hard. Local-listing access friction for non-Korean investors.

> ### P2. **Shinkawa** (Tokyo; subsidiary of **7272.JP Yamaha Motor**)
- Legacy TCB pioneer, aligned with Samsung HBM TCB lines. Indirect listing via Yamaha Motor — Shinkawa ~1% of group revenue. **Effectively non-investable** as a pure-play but IS the third leg of the TCB supply triangle (ASMPT-Hanmi-Shinkawa).

> | **Die thinning <30 μm**                 | Disco grinders                         | **6146.JP**                                                |
| **TCB stacking (5–15s/cycle)**          | ASMPT (Nvidia/SKH spec), Hanmi (SKH 2nd) | **0522.HK / 042700.KS**                                  |
| **NCF underfill film**                  | Resonac (>80% share)                   | **4004.JP**                                                |

> **Conviction stack (highest to lowest pure-play purity for 2026 ramp)**:
1. **0522.HK ASMPT** — TCB monopoly, ~40% segment lift
2. **042700.KS Hanmi** — 2nd TCB, leveraged but Korean-listing access

> **Closure / 闭环判断**: 16-Hi stack yield 是定价权源头 → 良率提升的速度由 **TCB 节拍 (ASMPT/Hanmi) + 减薄能力 (Disco) + NCF 一致性 (Resonac) + 16-Hi 检测 (Camtek/Onto)** 四把钥匙共同决定。**SK hynix 的窗口期 (Q4 2025 – mid 2026) 即将关闭**——Micron 量产即标志结构性溢价的削弱。装备链是更长久的票，IDM 是窗口期的票。Hybrid bonding 是 HBM4E (2027–28) 才解锁的下一段链条故事。

> ### 2. **TCB 节拍突破或被替代：MR / hybrid bonding 提前在 HBM4 量产**
- **观测点**: SK hynix 或 Micron 在 **2026 H2 之前**公开声明 16-Hi 量产路线切换到 **hybrid bonding (Cu-Cu)** 或 **single-pass mass reflow with new MUF**（即不再每层 5–15 秒 TCB），或 ASMPT 季报 **TCB orders QoQ -20% 以上连续两季**。
- **为什么是证伪**: TCB 瓶颈是 ASMPT / Hanmi 估值的全部基础；如果 hybrid bonding 提前两年（原计划 HBM4E 2027–28）攻入 HBM4，BESI / AMAT / EVG / SUSS 替代 ASMPT，0522.HK 与 042700.KS 的 conviction 解构。

> - **观测点**: SK hynix 或 Micron 在 **2026 H2 之前**公开声明 16-Hi 量产路线切换到 **hybrid bonding (Cu-Cu)** 或 **single-pass mass reflow with new MUF**（即不再每层 5–15 秒 TCB），或 ASMPT 季报 **TCB orders QoQ -20% 以上连续两季**。
- **为什么是证伪**: TCB 瓶颈是 ASMPT / Hanmi 估值的全部基础；如果 hybrid bonding 提前两年（原计划 HBM4E 2027–28）攻入 HBM4，BESI / AMAT / EVG / SUSS 替代 ASMPT，0522.HK 与 042700.KS 的 conviction 解构。
- **如何验证**: ASMPT / Hanmi 季报 book-to-bill < 0.9；BESI / AMAT 财报里 "hybrid bonding tools shipped to DRAM" 出现。

> - **为什么是证伪**: TCB 瓶颈是 ASMPT / Hanmi 估值的全部基础；如果 hybrid bonding 提前两年（原计划 HBM4E 2027–28）攻入 HBM4，BESI / AMAT / EVG / SUSS 替代 ASMPT，0522.HK 与 042700.KS 的 conviction 解构。
- **如何验证**: ASMPT / Hanmi 季报 book-to-bill < 0.9；BESI / AMAT 财报里 "hybrid bonding tools shipped to DRAM" 出现。

> **Crowded vs. before-20×?** 这条 trend 已经从 "before-20×" 走入 **"mid-cycle, crowded but not exhausted"**。证据：(a) SK hynix YTD 已涨 +60%（2026 H1），相对 PE 从历史均值 8× 抬到 14×；(b) ASMPT 0522.HK 在 2025 Q4 起的 TCB-backlog 披露后从 HK$70 涨到 HK$130（已 2× 反映瓶颈）；(c) Disco 6146.JP 估值跑到 35× forward PE，远超半导体设备中位数 22×。**仍未充分定价**的部分是 **Resonac NCF 份额 + Camtek 16-Hi 检测 step-up**（小盘漏网）。

> **Cleanest entry now**：**0522.HK ASMPT** —— TCB 几乎全部市场份额、book-to-bill 仍在 1.3–1.5、估值未透支 hybrid bonding 替代风险。**Do-not-own scenario**：若 SK hynix 或 Micron 公开宣布 HBM4 量产切换 hybrid bonding（参见证伪 #2），或 ASMPT 连续两季 TCB orders QoQ 负成长 → 立即出场。

## From tech_dive #47: 技术深挖: TSMC CoWoS-L vs Intel EMIB vs Samsung X-Cube: 2.5D adv...
_2026-05-07T04:37_

> - **ABF substrate / glass substrate transition / ABF 基板与玻璃基板过渡:** Ajinomoto ABF film for ultra-large packages (>100×100 mm carriers) is supply-constrained; glass-core substrate (Intel/Samsung roadmap 2026–2027) needed for next-gen warpage control but TGV (through-glass-via) tooling immature. / 超大封装(载板 >100×100 mm)的 ABF film 供给紧;玻璃基板(Intel/三星 2026–2027 路线图)对解决翘曲是必需,但 TGV 设备尚未成熟。
- **Hybrid-bonding (no-bump) handoff / 混合键合(无凸点)切换:** Below ~25 µm pitch, μ-bumps fail and **hybrid bonding (Cu-Cu direct + SiO₂-SiO₂)** is required; this needs ultra-clean fab-grade environment and equipment from BESI/AMAT/ASMPT — **the single biggest equipment-side risk for HBM4 (2026) and CoWoS-L generation 2.** / pitch <25 µm 时微凸点失效,需切到混合键合(Cu-Cu + SiO₂-SiO₂),要求 fab 级洁净环境和 BESI / AMAT / ASMPT 设备——**HBM4 (2026) 和二代 CoWoS-L 最大的设备侧风险点**。

> 3. **TSMC → OSAT overflow + substrate + materials.** TSMC subcontracts CoWoS back-end (chip-attach, mold, ball-drop) to **ASE / SPIL / Amkor** when AP6 is full (~10–15% overflow in 2025, dropping in 2026 as AP7/AP8 ramp). Substrate (ABF FCBGA carrier ~$300–600/unit) goes to **Ibiden / Unimicron / Shinko / Nan Ya PCB / Kinsus / AT&S**. Ajinomoto sells ABF film into all of them (~$5–10/unit attributable).
4. **TSMC → Equipment makers (capex, not COGS).** ASML (advanced litho for RDL stitching), AMAT / TEL / Lam (deposition, etch for TSV/RDL), **BE Semiconductor (BESI) and ASMPT for hybrid-bonding tools** (~$5–8M per tool, TSMC ordered 50+ for AP6/AP7/AP8 by 2025), Disco / Tokyo Seimitsu (dicing/grinding), Onto / KLA (metrology).

> 3. **台积电 → OSAT 溢出 + 基板 + 材料。** TSMC 在 AP6 满载时把 CoWoS 后段(贴片、塑封、植球)外包给 **日月光 / 力成 / Amkor**(2025 年外溢约 10–15%,随 AP7/AP8 投产 2026 年回落)。ABF FCBGA 载板单价 ~$300–600 由 **欣兴 / Ibiden / Shinko / 南亚电路 / 景硕 / AT&S** 提供;Ajinomoto ABF 膜可分摊 ~$5–10/封装。
4. **台积电 → 设备厂(资本开支,不入 COGS)。** ASML(RDL 拼接用先进光刻)、AMAT / TEL / Lam(TSV/RDL 沉积、刻蚀)、**BE Semiconductor (BESI) 与 ASMPT 提供混合键合机**(单台 ~$500–800 万美元,TSMC 在 AP6/AP7/AP8 到 2025 年累计下单 50+ 台)、Disco / Tokyo Seimitsu(切割/研磨)、Onto / KLA(量测)。

> - **Substrate — concentrated on Ibiden + Unimicron.** Ibiden ~40%, Unimicron ~25%, Shinko ~15%, Nan Ya PCB / Kinsus / AT&S splitting the rest of high-end ABF FCBGA. AI is ~50% of Ibiden's ABF revenue and rising.
- **Equipment — duopolies / monopolies in choke points.** Hybrid bonding: BESI + ASMPT (~80% of installed base). EUV: ASML monopoly. ABF film: **Ajinomoto monopoly (~95%)**. Disco monopoly on dicing tools used at HBM/Si-bridge thicknesses. **The Ajinomoto and Disco bottlenecks are hard-to-substitute single-vendor risks for the entire AI supply chain.**
- **Hyperscaler concentration on the demand side.** ~75–80% of 2026 accelerator TAM is consumed by the **Top-5: Microsoft + Meta + Google + Amazon + Oracle**. A capex pause from any two of those would visibly slow CoWoS utilization — hyperscaler capex digestion is the #1 macro risk factor for the chain.

> - **基板——集中在 Ibiden + 欣兴。** Ibiden ~40%、欣兴 ~25%、Shinko ~15%,南亚电路/景硕/AT&S 共享其余高端 ABF FCBGA 份额。Ibiden 收入中 AI 占比已 ~50% 并继续提升。
- **设备——卡脖子位置全是双寡头/独家。** 混合键合:BESI + ASMPT(装机量 ~80%);EUV:ASML 独家;ABF 膜:**Ajinomoto 独家(~95%)**;HBM/硅桥级薄片切割机:Disco 独家。**Ajinomoto 与 Disco 是整条 AI 供应链最难替代的单一供应商风险。**
- **需求端——超大规模云厂集中度。** 2026 年加速卡 TAM 中 ~75–80% 由 **Top-5(微软 + Meta + Google + 亚马逊 + Oracle)** 消化。其中任意两家暂停资本开支,CoWoS 稼动率立刻下滑——**超大规模云厂的资本开支消化节奏是整条链的第一宏观风险因子**。

> **EN:**
- **Already booking real revenue (2024–2025):** TSMC CoWoS-S/L (NVIDIA Hopper + Blackwell), HBM3 + HBM3E (SK Hynix + Micron), ABF substrates (Ibiden + Unimicron), BESI/ASMPT hybrid bonding (Q3-2024 onwards), Ajinomoto ABF film, Disco. **TSMC's advanced-packaging revenue grew from ~$2B (2023) to ~$5–6B (2024) to estimated $10–12B (2025).** SK Hynix HBM revenue: $4B (2023) → $13B (2024) → ~$25B (2025).
- **Ramping into revenue 2026:** CoWoS-L gen 2 (3× reticle, AP7/AP8 fabs at TSMC come online H1-2026), HBM4 from SK Hynix (Q3-Q4 2026 mass production for Rubin), glass-core substrates (Intel pilot 2026, merchant 2027), ABF supply expansion (Ibiden Hokuriku N3 plant 2026 start). Revenue ramp **back-loaded into H2-2026** as Rubin sampling ships.

> **ZH:**
- **已在确认真实收入(2024–2025):** TSMC CoWoS-S/L(NVIDIA Hopper + Blackwell)、HBM3 + HBM3E(SK 海力士 + 美光)、ABF 基板(Ibiden + 欣兴)、BESI/ASMPT 混合键合机(2024 Q3 起)、Ajinomoto ABF 膜、Disco。**TSMC 先进封装收入从 ~$2B (2023) → ~$5–6B (2024) → 估算 $10–12B (2025)**。SK 海力士 HBM 收入:$4B (2023) → $13B (2024) → ~$25B (2025)。
- **2026 进入收入兑现期:** CoWoS-L 二代(3× 光罩,TSMC AP7/AP8 在 2026 H1 投产)、SK 海力士 HBM4(2026 Q3–Q4 量产供 Rubin)、玻璃基板(Intel 2026 pilot,商用 2027)、ABF 扩产(Ibiden 北陆 N3 厂 2026 开工)。收入放量**集中在 2026 H2** 随 Rubin 送样出货。

> **Layer / 层位:** 设备——混合键合机(Hybrid bonding tool)
**Specific product / 具体产品:** **Datacon 8800 系列混合键合机**——单台 ~$5–8M;TSMC AP6/AP7/AP8 至 2025 年累计下单 50+ 台用于 CoWoS-L gen 2 + HBM4 die 堆叠。与 ASMPT 共占混合键合装机量 ~80%。HBM4(2026 Q3 起)正式从微凸点切到混合键合,是 BESI 收入二阶导上拐的关键。
**Cap & scale / 市值与体量:** 市值 ~$10B,FY2025 营收 ~$0.7B,员工 ~2k。

> **Cap & scale / 市值与体量:** 市值 ~$10B,FY2025 营收 ~$0.7B,员工 ~2k。
**Competitors / 竞争对手:** **ASMPT (0522.HK)**(港股,混合键合 + TCB 双产品线)、AMAT 应用材料 (AMAT.US,刚做大并购布局混合键合)、EV Group(私人,奥地利)。
**Vehicle quality / 标的成色:** **链条上最纯 2.5D/3D 设备多头**——估值贵但属于"合理贵"。小盘子 + 高弹性 + 双寡头格局,是教科书级 picks-and-shovels。

> ## 10. ASMPT — 0522.HK / 港交所
**Layer / 层位:** 设备——混合键合 + TCB(港股口径)

> **Cap & scale / 市值与体量:** 市值 ~$3.5B,FY2025 营收 ~$1.7B,员工 ~14k。
**Competitors / 竞争对手:** BESI(混合键合主对手)、新川 Shinkawa(已并入 ASMPT)、Kulicke & Soffa (KLIC.US)。
**Vehicle quality / 标的成色:** **港股链条最纯封装设备多头**,但 SMT(电子组装)分部稀释半导体故事约一半;弹性高于 BESI 但纯度不如。**适合做"BESI 的港股替代+SMT beta 对冲"**。

> - **EV Group (EVG) — 奥地利** / Hybrid bonding 设备的第三家(BESI、ASMPT 之外),晶圆-晶圆混合键合(SmartView 平台)在某些 fab 是首选;TSMC SoIC 产线深度使用其设备。**完全私人持股**——若 IPO 将是直接对标 BESI 的玩家。
- **JX Advanced Metals — 日本(2024 年 12 月已 IPO,5016.JP)**——半导体级铜箔、键合材料、靶材,占 die-to-die 互连铜柱 / 凸点 / TSV 镀层市场极高份额。**已上市但流动性极低,机构覆盖少**;严格说是"准私人"标的。

> | AI 服务器 PCB | 002463.SZ 沪电股份 | 板级 AI 杠杆,A 股最易上手 |
| Hybrid-bonding(港股)| 0522.HK ASMPT | BESI 的港股替代 |
| Accelerator demand sink | NVDA | 整条链宏观分母 |

> **链条多头优先级(纯度排序):BESI ≈ Ibiden > Disco > ASE / SK Hynix > 通富微电 / ASMPT > TSMC > 沪电股份 > Ajinomoto > NVDA**(纯度,不等于回报排序;回报还需叠加估值与拥挤度)。
