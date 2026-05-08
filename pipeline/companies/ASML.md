# ASML -- 综合提取 / All mentions across our research

_Aggregated from 17 mentions across 5 reports. Auto-generated; rerun via `python scripts/compress_dives_to_companies.py`._

---

## From tech_dive #41: 技术深挖: TSMC CoWoS-L vs Intel EMIB vs Samsung X-Cube: 2.5D adv...
_2026-05-07T02:44_

> **(f) Single-source on key tools / 单源依赖.** ASML EUV (no alternative), Disco grinder/dicing for interposer thinning, Applied Materials / TEL for TSV reveal-etch + CMP, Camtek/Onto for bridge inspection. Any one tool slip cascades into months of CoWoS slip.

> ▼
Tool / consumable suppliers (ASML, AMAT, TEL, LRCX for TSV/CMP; Disco for grinding/dicing;
    BESI + ASMPT for hybrid bonding; Hanmi + Shinkawa for TCB; Camtek + Onto for inspection;

> **中文.** 链条 7 段:**云厂/OEM(MSFT/META/GOOG/AMZN/Oracle/xAI/Tesla/主权云)→ 加速器设计公司(NVDA/AMD/Broadcom-定制 ASIC/Marvell-定制 ASIC)→ 晶圆 + 封装代工(TSMC、Intel Foundry、Samsung Foundry)→ OSAT 组装与最终测试(Amkor、ASE/SPIL、KYEC)→ HBM 供应商(SK 海力士第一、Micron 第二、三星追赶)→ ABF 有机基板(Ibiden ~30%、Unimicron ~20%、Nan Ya PCB、Shinko、AT&S、Kinsus)→ 工具/耗材(ASML、AMAT、TEL、LRCX、Disco、BESI、ASMPT、Hanmi、Camtek、Onto、信越/住友 Bakelite)。**

> - **Tooling:** ASML EUV (single source); Disco grinding/dicing (~80%+ of advanced thin-wafer dicing market); BESI + ASMPT split hybrid bonding ~50/50 with no third entrant; Hanmi + Shinkawa dominate TCB.

> - **ABF 基板** — Ibiden ~30%、Unimicron ~20%、Shinko ~15%、Nan Ya ~10%、AT&S/Kinsus 其他;**前 2 ≈ 50%、前 3 ≈ 65%**。Ibiden 大垣一期是若干 NVDA SKU 的单源。
- **工具** — ASML EUV 单源;Disco 在先进薄圆片切割 >80%;BESI + ASMPT 平分 hybrid bonding;Hanmi + Shinkawa 占 TCB。
- **需求端** — 前五云厂(MSFT/META/GOOG/AMZN/ORCL)买走 **~70-75%** NVDA 数据中心收入;加 xAI/Tesla/Apple/主权云,前 15 占 ~95%。**5 家中有 3 家暂停 AI capex,2 季度内整条 2.5D 链子收入塌方。**

> **EN.** The thesis assumes TSMC ramps **CoWoS aggregate ~75k wpm (end-2025) → 135–150k wpm (end-2026)**. **Falsifier:** at any TSMC quarterly earnings call (next one ~2026-07-17), or at the TSMC North America Technology Symposium (next: April 2026 cycle), the CoWoS end-2026 number is officially **revised down by ≥15%** — i.e., to <115k wpm — citing demand softness rather than tooling delays. A demand-driven cut (not a supply slip) means hyperscalers stopped pulling, and the entire chain re-rates downward at once. **Counter-signal to watch:** if the cut is explicitly attributed to ASML/Disco/AMAT tool delays with end-customer orders intact, the bottleneck thesis actually *strengthens* (longer scarcity).

> **中文.** 命题假设 TSMC CoWoS 总产能 ~7.5万 wpm(2025末)→ 13.5–15万 wpm(2026末)。**证伪:** 任何一次 TSMC 法说会(下次 ~2026-07-17)或北美技术论坛(2026 年 4 月一轮)上,CoWoS 2026 年末数字**官方下修 ≥15%**(降至 <11.5万 wpm),且口径归因为"需求疲软"而非工具延迟。需求侧砍单 = 云厂不拉了,整链同步下修。**反向信号:** 如果归因明确为 ASML/Disco/AMAT 工具延迟、终端订单未变,瓶颈论反而**更紧**(稀缺时间更长)。

## From tech_dive #42: 技术深挖: China semi domesticization deep-dive: 盛美 ACMR + 中微 AME...
_2026-05-07T03:00_

> Together they cover ~40–55% of WFE BOM by tool count + the OSAT back-end. **Critical gaps not addressed by any of these four**: lithography (ASML / SMEE), ion implantation (AMAT/Axcelis → 凯世通), CMP (AMAT/Ebara → 华海清科), high-end metrology (KLA → 精测/中科飞测).

> Full system parity at N+2 still gated by **ASML ArFi + AMAT Centura + ASMI Pulsar + KLA**, none of which these four address.

## From tech_dive #47: 技术深挖: TSMC CoWoS-L vs Intel EMIB vs Samsung X-Cube: 2.5D adv...
_2026-05-07T04:37_

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

## From tech_dive #48: 技术深挖: China semi domesticization deep-dive: 盛美 ACMR + 中微 AME...
_2026-05-07T04:45_

> | Furnace / oxidation | **TEL (JP)**, Kokusai (JP, Hitachi Kokusai) |
| Lithography (DUV/EUV) | **ASML (NL) — banned for 5nm-class to China** |
| Optical/e-beam metrology | **KLA (US)** ~85% share |

> The *core* incumbents being directly attacked at the 5nm-class node by domestic vendors are: **Lam (etch)**, **AMAT (PVD/CMP)**, **SCREEN/TEL (clean & furnace)**, and **ASE/Amkor (advanced packaging)**. ASML and KLA are NOT credibly being challenged in this cycle.

> ### 4. **ASML (ASML.AS) — 光刻 (DUV immersion + EUV)**
- R1 §4 已说明:**EUV 完全无法获得**,DUV ArFi 已自 2024 H1 起 BIS + 荷兰 NL 双重许可证管控.

## From morning_note #53: 晨会笔记 2026-05-07...
_2026-05-07T05:39_

> - **SMCI** 持仓警报触发：fraud_legal 关键词命中 3 条头条 + 当日 +17.21% 放巨量（vol 2.6x）。这是经典"冲高出货 + 法律风险"组合，**不在核心 conviction 但若有持仓必须处理**。
- **半导体大盘强势**：ASML +7.06%、LRCX +6.66%、MU +11.06%——利好 TSM、ACMR、AXTI、002428.SZ 这条产业链。
