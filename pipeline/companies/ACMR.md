# ACMR -- 综合提取 / All mentions across our research

_Aggregated from 47 mentions across 4 reports. Auto-generated; rerun via `python scripts/compress_dives_to_companies.py`._

---

## From deep_qa #30: ACMR 深度问答...
_2026-05-06T02:08_

> # ACMR 深度问答 / Q&A deep-dive

> ## Q1: For ACMR, the operator is considering this thesis: 'ACM Research US ADR: A-share parent 盛美上海 (688082) is the SAPS clean wet-bench monopoly at SMIC/YMTC; -65% from 2024 entity-list panic; Big Fund Phase III + China semi-domesticization is the structural backwind. Why now, what's the catalyst window, and what would falsify this?'. Why is this investable RIGHT NOW, not 6 months ago or 6 months from now? What is the specific catalyst window, and which observable evidence makes the timing tight?

> **Why not 6 months ago:** Through late 2025 the BIS Entity List overhang was unresolved — ACMR was discussed in draft scenarios around the December 2024 export-control package. Until that risk was either confirmed (catastrophic) or formally bypassed, the discount was rationally pricing a binary tail, not opportunity. You couldn't size the position because you couldn't size the downside.

> **The tight window:** Q1 2026 results (688082 typically reports late April; ACMR ADR reports early May — likely just released) are the *first* quarter where Big Fund III + SMIC's N+2 capex + CXMT's DRAM ramp overlap on the order book. This is the "show me" print.

> - SMIC 2026 capex guide (~$7.5B last) sustained or raised
- ACMR absence from any April 2026 BIS publication

> **Why "flat capex" does not falsify the ACMR thesis even if literally true:**
1. **Wet-clean intensity rises with node** — each advanced-node generation (N+1 → N+2) adds more cleaning steps per wafer (roughly 30-50% step-count increase moving from 14nm to 7nm-equivalent, though I am uncertain on the exact figure). Flat aggregate capex with mix shift *to* advanced still means rising SAPS tool orders.

> 1. **Wet-clean intensity rises with node** — each advanced-node generation (N+1 → N+2) adds more cleaning steps per wafer (roughly 30-50% step-count increase moving from 14nm to 7nm-equivalent, though I am uncertain on the exact figure). Flat aggregate capex with mix shift *to* advanced still means rising SAPS tool orders.
2. **Memory offset** — even if SMIC is flat, CXMT's DRAM ramp and YMTC's Xtacking restart are independent capex pools. ACMR's 合同负债 has plausibly become *more* memory-weighted in 2025-2026 vs 2023.

> ## Q5: What is the documented wet-clean step count for SMIC's N+1 (7nm-equivalent) versus 14nm process — because the entire "flat capex still bullish for ACMR" argument rests on a 30-50% step-count increase I cited from memory without a source, and if the actual increase is closer to 10-15% then mix shift cannot offset volume softness?

> **What this means operationally:** If SMIC guides flat capex with ~15% step-count uplift, the ACMR mix-shift argument needs ~10% wet-clean $/wafer growth to hold — tighter than I implied but not impossible. The cleaner falsification is reading ACM's own 10-K SAPS unit ASP trend, not arguing about SMIC step counts I can't source.

## From tech_dive #42: 技术深挖: China semi domesticization deep-dive: 盛美 ACMR + 中微 AME...
_2026-05-07T03:00_

> # 技术深挖 / Tech deep-dive: China semi domesticization deep-dive: 盛美 ACMR + 中微 AMEC + 北方华创 NAURA + 长电 JCET -- which equipment vendor is closest to non-Pluggable parity at SMIC's 5nm-class node, and what's the realistic 2027 revenue path

> - **ACMR (盛美 / 688082.SH + ACMR NASDAQ)** — wet processing: SAPS / TEBO single-wafer megasonic clean, Ultra ECP map Cu plating, Tahoe sulfuric-acid recycle wet bench, vertical furnace.
- **AMEC (中微 / 688012.SH)** — plasma etch: Primo D-RIE CCP (3D NAND high-AR channel), Primo Twin SE-CCP (dielectric/contact), Primo TSV, Primo Nanova ICP (still maturing). Plus MOCVD (non-logic).

> Mapped block-by-block in the file. Headlines: **ACMR ↔ TEL UW-300 / SCREEN FC-3300 / Lam Da Vinci** (clean) + **Lam Sabre** (ECP) | **AMEC ↔ Lam Vector / Flex / Vantex + TEL Tactras** (CCP etch, 3D NAND) | **NAURA ↔ AMAT Endura (PVD) / TEL Alpha furnace / ASMI Pulsar (ALD) / AMAT Centura EPI** | **JCET ↔ ASE + Amkor + TSMC InFO/CoWoS**.

> Per vendor: ACMR Tahoe ~80% H2SO4-volume reduction; SAPS sub-65nm particle removal benchmarked at ~99% with <0.05% fin-collapse. AMEC Primo D-RIE in **YMTC 192-layer 3D NAND production** (the hardest non-EUV etch on earth) and Twin SE-CCP **40–60 wph dual-station throughput** vs Lam Vector ~25–35 wph. NAURA dominant domestic share (≈30%+ of CSIA WFE shipments) with PVD Cu-seed defect counts within ~5% of AMAT Endura at 28nm. JCET XDFOI claims ~4× InFO interconnect density at sub-1µm RDL; 40 µm Cu pillar in volume; **largest OSAT capacity in China + STATS ChipPAC overseas hedge**.

> - **ACMR**: backside contamination at <10nm trails TEL/Lam by ~2–3× particle count (the reason SMIC still imports for the most critical metal-layer cleans); megasonic fin damage at AR>30:1; advanced-packaging RDL ECP gap.
- **AMEC**: **conductor etch (Si gate / metal gate) at FinFET not in N+2 production** — Lam Kiyo / AMAT Sym3 dominate. **ALE for GAA 3nm not yet at production**. ICP source uniformity at AR>60:1. Recipe library 3× shallower than incumbents.

> - **ACMR**: SMIC (28nm + 14nm + N+1 limited), YMTC (Tahoe + Ultra ECP at 128/192-layer), CXMT, Hua Hong, SK Hynix Wuxi (historical). FY2024 ~RMB 5–6B shipped.
- **AMEC**: SMIC (Primo D-RIE / Twin SE-CCP at 14nm and N+1), **YMTC 128-layer + 192-layer 3D NAND channel etch — single highest-difficulty publicly-disclosed Chinese etch deployment**, CXMT, TSMC (legacy 65/40nm), ASE/JCET/Amkor (TSV).

> - **AMEC**: SMIC (Primo D-RIE / Twin SE-CCP at 14nm and N+1), **YMTC 128-layer + 192-layer 3D NAND channel etch — single highest-difficulty publicly-disclosed Chinese etch deployment**, CXMT, TSMC (legacy 65/40nm), ASE/JCET/Amkor (TSV).
- **NAURA**: SMIC (broadest single-vendor footprint), YMTC, CXMT, all major domestic mature-node fabs. **FY2024 ~RMB 28–32B — largest Chinese WFE company by revenue, ~3× ACMR or AMEC.**
- **JCET**: Qualcomm, MediaTek, Apple-via-STATS, AMD, Marvell, NXP, STMicro + domestic AI accelerator XDFOI insertions. FY2024 ~RMB 33B — #3 OSAT globally.

> **Negative validation list** (the gating list for the parity question): no AMEC FinFET gate etch in volume; no JCET HBM3+ 8-high in volume; no NAURA FinFET S/D EPI in volume; no NAURA HKMG ALD in volume; no ACMR backside-clean parity at 5nm critical metal layers.

> 1. **AMEC** — closest single-tool-class parity (dielectric / high-AR etch in 192-layer NAND). Open: conductor etch, GAA ALE.
2. **ACMR** — cleanest narrow-product parity at sub-FinFET clean + ECP. Open: backside clean, scrubber.
3. **JCET** — architectural parity at fine-pitch flip-chip + fan-out; **HBM and CoWoS-class are binding gaps** — and 2026's AI capex is precisely those gaps.

> 1. **Two parallel revenue chains, one cross-link** — Chain A (WFE: ACMR/AMEC/NAURA paid by SMIC/YMTC/CXMT capex) lags wafer demand by 6–12 mo; Chain B (OSAT: JCET paid by fabless directly *and* via OSAT-margin uplift on advanced packaging). Cross-link: ACMR Ultra ECP, AMEC Primo TSV, NAURA PVD all sell into JCET's bumping/RDL/TSV lines — **the only "all four win together" scenario is a domestic AI accelerator on SMIC N+2 + JCET XDFOI**.

> 2. **Inflection** — at mature nodes (≥28nm) all four are already past TCO inflection. At 5nm-class: **AMEC dielectric etch is across the line today** (YMTC 192-layer NAND in production); **JCET XDFOI is at the threshold contingent on >600 mm² yield**; **ACMR is 2026 H2 → 2027 H1 on backside-clean parity**; **NAURA HKMG ALD / S/D EPI is 2028+**.

> 4. **Concentration** — ACMR/AMEC/NAURA all live on the same triumvirate (SMIC + YMTC + CXMT ≈ 60–75% revenue); customer concentration ≈ policy-stack concentration. JCET's deepest single dependency is Qualcomm (likely 15–25%).

> 5. **2027 revenue path (base case)** — ACMR RMB 9–13B (~1.6–2.2× FY24) | AMEC RMB 13–18B (~2× FY24, the cleanest "parity revenue now" story) | NAURA RMB 48–60B (~1.7× FY24, biggest absolute, weakest parity premium) | JCET RMB 42–52B (~1.4× FY24, slowest near-term but largest 2028–2030 optionality from AI/HBM mix).

> **Combined parity-rev ranking**: AMEC (parity revenue today) > ACMR (cleanest narrative if SMIC capex pacing holds) > NAURA (lowest risk, lowest parity torque) > JCET (widest TAM, slowest translation).

> I picked **6 public + 2 private bonus**, deliberately mapping the layers the four anchor names (ACMR / AMEC / NAURA / JCET) do **not** cover, and prioritizing the gap-fills Round 1 named explicitly (CMP, CVD/ALD, metrology, lithography).

> - **SMEE / 上海微电子装备** — China's only stepper/scanner maker. R1's **single binding constraint**: ArFi (193 nm immersion) at <28nm logic still in development. Until SMEE delivers ArFi, the parity thesis is a half-thesis. State-owned, IPO repeatedly rumored, never executed.
- **YMTC + CXMT** — the demand-side anchors nobody can buy. Their capex pacing is **the single most important variable** in the 2027-revenue model for ACMR / AMEC / NAURA — and it is set by policy, not market signal. SMIC (688981.SH / 0981.HK) is the only listed demand-side proxy and does not capture the NAND or DRAM streams.

> 2. **SMEE ArFi (193 nm immersion) tape-out / first-fab-shipment slips past 2027-Q4** → falsifies the entire 2027 revenue path for ACMR/AMEC/NAURA. Without domestic ArFi, China-domestic-share target collapses from 35–45% to 25–30%.

## From tech_dive #48: 技术深挖: China semi domesticization deep-dive: 盛美 ACMR + 中微 AME...
_2026-05-07T04:45_

> # 技术深挖 / Tech deep-dive: China semi domesticization deep-dive: 盛美 ACMR + 中微 AMEC + 北方华创 NAURA + 长电 JCET -- which equipment vendor is closest to non-Pluggable parity at SMIC's 5nm-class node, and what's the realistic 2027 revenue path

> ↓ 资本支出 (capex) — 单 chamber $3–5M
设备厂 (NAURA, AMEC, ACMR) ←—— foundry 还另外付封装代工费 ——→ 封装 (JCET, 通富微电, 华天)
                                                                   ↓

> | 晶圆代工 (SMIC) | $20–25 | of which ~$8–10 是设备折旧 |
| 设备折旧 → WFE 厂收入轮 | $8–10 | NAURA/AMEC/ACMR 分账 |
| 先进封装 (JCET, 2.5D + HBM 集成) | $8–12 | HBM stack 集成是利润来源 |

> |---|---|---|---|
| Single-wafer wet clean | SCREEN: $5M, MTBF 2000h, 150 wph → ~$0.15/wafer-pass | ACMR: $2.5M, MTBF ~1400h (up from 900h in 2023), 120 wph → ~$0.12/wafer-pass | **Crossed** — ACMR cheaper net of downtime |
| Furnace / 氧化/扩散 | TEL/Kokusai | NAURA | **Crossed at ≤14nm**, near-crossing at 7nm |

> - 刻蚀 (etch): $5–6B → AMEC + NAURA 主战场
- 清洗 (clean): $2.0–2.5B → ACMR 主导
- ALD/CVD/PVD: $3–4B → NAURA 主导

> |---|---|---|---|---|
| ACMR (盛美) | ~$770M | ~$1.4–1.7B | ~22–28% | 清洗扩品类 (CMP, ECP, furnace add-on) + SMIC/CXMT 5nm/DRAM |
| AMEC (中微) | ~RMB 9B (~$1.25B) | ~RMB 18–22B (~$2.5–3B) | ~25–30% | CCP etch 5nm-class breakthrough + MOCVD 国际份额 |

> |---|---|---|---|
| ACMR (盛美) | ~60–65% (SMIC+YMTC+CXMT) | ~12–15% (美国上市,有 SK Hynix + Micron 历史关系) | **最分散** 的 WFE 厂 |
| AMEC (中微) | ~70–75% | ~10% (历史上有 TSMC,正在流失) | 中等 |

> **关键 tail risk:** 如果 Huawei Ascend 销量低于预期(例如 2027 出货 <1.2M 颗 vs 当前预期 1.5–2M),或美国对 2nd-tier 设备零部件供应商执法收紧(光刻气体、特种化学品、压电陶瓷晶振),NAURA / AMEC / ACMR 三家管道里 ~50%+ 收入将依赖反周期对冲(CXMT DRAM 替代逻辑订单)。**JCET 因全球 OSAT mix 受冲击最小**。

> |---|---|---|
| ACMR | 2023 起 SMIC 7nm 清洗实计入营收;2024 SMIC 5nm-class 验证机首批入账 | 2026 H2:CMP 独立产品线 (公司目标 $100M+ in 2027 vs 2024 ~$20M);ECP 铜电镀 2025 首单 |
| AMEC | 2022 起 5nm CCP etch 在 SMIC 入账;2024 H2 关键介质 etch 量产 | 2026 H1:5nm HAR 关键层 defectivity 缺陷率 是否进入 Lam 1.5x 以内 — 这决定是否吃到 5nm 关键层订单 |

> - 2027 H1 — Huawei Ascend 910D 流片节点;若验证 SMIC 3nm-class 良率,JCET 2.5D 中介层扩产板上钉钉
- 2027 H2 — ACMR/AMEC 是否能交出 5nm 关键层 (HAR, fin etch) 量产数据 — 这是 "non-Pluggable parity" 论题真正成立的最终证据

> |---|---|
| **5nm-class non-Pluggable parity 最近** | **AMEC** (CCP etch, 关键 IP + node coverage) + **ACMR** (clean,已交叉) |
| **2027 收入复合最快 (绝对增量 TAM 最大)** | **NAURA** (~27–34% CAGR,最广产品线;最大金额受益方) |

> - **Furnace / 炉管:** 氧化/扩散/退火炉 (国内 ~50%+ 占有率)
  - **Wet/clean** (与 ACMR 在低端有重叠)
  - 2024A 营收 ~RMB 22B,设备贡献 ~RMB 18–19B,**几乎是国产 WFE 单家最广的产品矩阵**

> ### 3. `ACMR` (NASDAQ) + `688082.SH` 盛美上海 / ACM Research — 双重上市
- **Layer:** **System — 湿法清洗 OEM** + 周边 (CMP, ECP, furnace add-on)

> - 2024A 营收 ~$770M;盛美上海 (688082) 营收 ~RMB 5B
- **Market cap + scale:** ACMR (NASDAQ) ~$1.5–2B; 盛美上海 (688082) ~RMB 50–70B (~USD 7–10B);员工 >2,000;**两个壳同一资产 — 注意 holdco 折价**
- **Top 1–2 competitors:**

> - 域内对标:**南大光电 (300346.SZ)** + **彤程新材 (603650.SH)**,但 ArF/EUV 级仍处于 14nm 验证阶段.
- **Why critical-path:** 没有光刻胶 = 没有 5nm wafer.即使 NAURA/AMEC/ACMR/JCET 全链条国产化,这一块仍是 chokepoint.

> - 域内对标:**上海微电子 SMEE** (未上市) — 28nm DUV 工程机 2024 出货,**14nm DUV 仍在 2026–2027 路上**;5nm 级 DUV immersion **目前国产 0%**.
- **Why critical-path:** 整个 thesis 的最大 unsolved physics gap.NAURA/AMEC/ACMR/JCET 全部强,也无法弥补这一节阶梯.**是论题失败的最大单一外生风险.**

> | **5nm 关键工艺单点弹性** | AMEC `688012.SH` | HIGH (但 tail risk 大) | 战术仓 |
| **清洗 pure-play + 海外护城河** | ACMR `ACMR / 688082.SH` | HIGH | 核心仓 (注意双壳) |
| **OSAT 防御 + AI 封装弹性** | JCET `600584.SH` | MED-HIGH | 防御核心 |

> This trend sits in the **late-early-innings** zone — past the "is it real" phase (R2: ACMR/AMEC/NAURA/JCET 已计入真实 P&L since 2022–2024,not LOI),but **not yet crowded**:消费级南向资金仍主要持有 SMIC + Huawei concept basket,而 WFE 设备厂 sell-side 覆盖 <12 家(vs Lam/AMAT 的 ~30 家),公募基金在 NAURA/AMEC 的合计仓位 <8% of free float.SMIC 5nm-class wpm 50K → 80K 的过渡 + Ascend 910D 流片是双重催化,向 20x 的赔率仍开放(NAURA + ACMR 2027E 收入翻倍可见,multiple 离 sector peak ~30–40%).

> 下一步建议:把 R1+R2+R3+R4 合并写入 `pipeline/tech_dive_china_semi_2026-05-07.md`(已在你的 untracked 树中),并把 `NAURA / AMEC / ACMR / JCET` 加入 `data/topic_queue.yaml` 的 conviction watchlist,设置 90-day 触发器 review 上述 4 个 falsification signals.是否继续?

## From morning_note #53: 晨会笔记 2026-05-07...
_2026-05-07T05:39_

> - **SMCI** 持仓警报触发：fraud_legal 关键词命中 3 条头条 + 当日 +17.21% 放巨量（vol 2.6x）。这是经典"冲高出货 + 法律风险"组合，**不在核心 conviction 但若有持仓必须处理**。
- **半导体大盘强势**：ASML +7.06%、LRCX +6.66%、MU +11.06%——利好 TSM、ACMR、AXTI、002428.SZ 这条产业链。

> ---
**Bias 总结:** AI 数据中心需求侧基本面继续 confirm（AMD/COHR/MU 共振），但价格层面机构开始用 PUT 表达短期谨慎——**节奏比方向更重要**。半导体设备/材料链（TSM/ACMR/AXTI）相对受益且无极端期权信号，可作为多头敞口的较稳载体。
