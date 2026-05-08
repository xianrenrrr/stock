# STOCK 工作流总览 / Orchestrator workflow overview

_Last updated: 2026-05-07 EOD. This is the canonical "how does the whole thing work" doc._

---

## 一行话总结

24 小时不间断运行的 AI 股票研究工厂：自动收集数据 → 跑 LLM 深挖 → 识别异常信号 → 把
"在爆发前夜"的隐藏机会推到老板的 APK 上。完全跑在本机笔记本 + Render 云代理上，
零增量 LLM 费用（claude_cli subscription-based）。

---

## 三大数据层

### 1. 数据采集 / Ingest（每 15 分钟，市场时段 14:00-21:45 UTC）

| 来源 | 内容 | 模块 |
|---|---|---|
| Yahoo Finance | 每日 OHLCV + 期权链 | yfinance |
| RSS feeds | 公司新闻头条 | feedparser |
| SEC EDGAR | 8-K, 10-Q, 10-K, **Form 4 (含 XML body)** | F35 insiders.py |
| 用户上传 | 图片/文档（OCR + vision） | F18 vision_extract |

每条新闻自动跑一次 LLM 特征提取（claude_cli, **零费用**），输出结构化 JSON：
情绪 / 新颖度 / 催化剂类型 / 时间敏感度 / 摘要。

### 2. 信号分析 / Analysis（市场收盘后集中跑 21:30-23:30 UTC）

| 任务 | 频率 | 输出 |
|---|---|---|
| Score (F08) | 21:30 daily | predictions_scored + bandit |
| Thesis verify (F16) | 21:40 daily | thesis hits/contradicts/mixed |
| Grade & Reply (F11) | 21:45 daily | grading note + 自动排队下一轮 |
| Tracked events verify (F26) | 21:50 daily | event hit/miss/partial/pending |
| UOA scan (F36) | 21:55 daily | option_anomalies |
| Smallcap scan (F38) | 22:15 daily | smallcap_candidates |
| Discovery engine (F19) | 23:00 daily | FWP composite (insider+8K+reddit+theme velocity) |
| AI loop monitor (F39) | 06:30 Mon | ai_loop_health 面板（15 家 SaaS） |
| Anomaly compute (F12) | 16:00 daily | price_anomalies |

### 3. 输出层 / Output

| 类型 | 频率 | 接收方 |
|---|---|---|
| Daily research note (F00) | 02:30 + 14:30 UTC | APK + dashboard |
| Tech-dive (F43) | _DISABLED 2026-05-07_ | — |
| Company DD checklist (F44) | 5×/day at 03:15/07:45/12:15/16:45/21:15 UTC | APK |
| Weekly QA (F40) | Sat 07:00 UTC | top-5 FWP names |
| Self-review (F18) | 06:00 UTC | pipeline/daily_review_*.md |
| Daily-zh report | 调用即用 | 中文工作汇报 |
| Earnings review / DD checklist / Morning note (F44) | 调用即用 | APK |
| Backup (F33) | 23:30 UTC | data/backups/ |

---

## 25 个 cron jobs（按时间顺序）

```
06:00 UTC  daily_self_review (每日)
06:30 UTC  ai_loop_measure (周一)
07:00 UTC  weekly_qa_dive (周六)
14:00-21:45 UTC  ingest_and_extract (每 15 分钟，工作日)
14:30 UTC  evening_research_push
21:30 UTC  score_daily
21:40 UTC  thesis_verify
21:45 UTC  grade_and_reply
21:50 UTC  verify_tracked_events
21:55 UTC  uoa_scan
22:15 UTC  smallcap_scan
22:30 UTC  morning_research_push
23:00 UTC  discovery_engine
23:30 UTC  backup_db
02:30 UTC  morning_research_push (次日)
03:15 UTC  company_dd_dive (F44)
07:45 UTC  company_dd_dive
12:15 UTC  company_dd_dive
16:45 UTC  company_dd_dive
21:15 UTC  company_dd_dive
*/5s       sync_to_render
```

(原本还有 F43 daily_tech_dive 04:30 UTC，已禁用)

---

## 数据资产（在 data/ 下，可手动编辑）

| 文件 | 内容 |
|---|---|
| `watchlist.yaml` | 39 只主跟踪 + 23 只 boss-directed adds = ~62 只 ingest universe |
| `holdings.yaml` | 当前持仓 (`active=0` 表示已平仓) |
| `secular_themes.yaml` | 5 个长期主题 (china_aging / us_wealth_inequality / ai_displacement / india_demographic / china_semi_value) |
| `tech_trends.yaml` | 13 个具体技术趋势（10 enabled），每个含 why_now + 证伪 + 标的 |
| `conviction_watchlist.yaml` | 25 个深度跟踪股 (含 boss-directed 中际旭创/天孚/云南锗业/工业富联/寒武纪 etc.) |
| `smallcap_universe.yaml` | 33 只小盘股 across 3 板块 |
| `topic_queue.yaml` | F43 主题队列 (10 已完成，cron 已禁用) |
| `company_dive_queue.yaml` | F44 28 家公司队列，priority-tiered |
| `ai_supply_chain.yaml` | AI 供应链层级图 |
| `feedback_rules.yaml` | boss feedback 衍生的响应规则 |

---

## 数据库表（SQLite, ~25 张表）

核心：news / prices / features / predictions / predictions_scored / research_reports / watchlist /
holdings / **insider_filings (F35)** / **discovery_candidates (F19)** / **tracked_events (F26)** /
**option_anomalies (F36)** / **smallcap_candidates (F38)** / **ai_loop_health (F39)** /
**tech_dive_runs (F43)** / price_anomalies / action_queue / llm_calls / recipient_tokens /
conversations / wechat_log (legacy) / prompt_rewrites

每天 23:30 UTC 自动备份到 `data/backups/stock.db.YYYY-MM-DD.bak`，保留最近 7 份。

---

## CLI 命令一览

### 日常操作
- `stock summary` -- F34 早晨视图
- `stock check <ticker>` -- F30 9-section 实时快照
- `stock research` -- 立即生成 daily note
- `stock daily-zh` -- 中文工作汇报

### 数据管理
- `stock watchlist add/remove/list` -- ingest universe
- `stock holding add/remove/list/note` -- 持仓
- `stock trend list/show/toggle/swap/add/remove` -- F41 技术趋势
- `stock conviction list/toggle/swap/add/remove` -- F42 重仓股
- `stock event add/list/edit/delete/verify/calibration` -- F26 跟踪事件
- `stock thesis extract/verify/stats/show` -- F16 论点核验
- `stock forward-discover run/list/dismiss/promote` -- F19 前瞻发现

### 按需扫描
- `stock smallcap-scan` -- F38 小盘扫描
- `stock uoa-scan` -- F36 期权异常
- `stock ai-loop-measure` -- F39 AI 闭环面板
- `stock weekly-qa-dive` -- F40 周度 Q&A
- `stock qa-dive <ticker>` -- F37 单股 Q&A
- `stock tech-dive <topic>` -- F43 4 轮技术深挖
- `stock anomaly-run` -- F12 异常重算

### 分析师技能（F44, 借鉴 Anthropic FSI）
- `stock earnings-review <ticker>` -- 业绩复盘 3 轮
- `stock dd-checklist <ticker>` -- 12 项尽调
- `stock morning-note` -- 隔夜要闻摘要

### 工具
- `stock entry-zone <ticker>` -- 回踩入场区间
- `stock pdf-export research:<id> | file:<path> | recent-dives` -- PDF 导出
- `stock backup-db` -- 手动备份
- `stock backend show/set` -- claude_cli vs minimax 切换

### Claude Code slash 命令
- `/tech-dive <topic>` -- F43 风格深挖
- `/earnings <ticker>` -- 业绩复盘
- `/dd-checklist <ticker>` -- 尽调清单
- `/morning-note` -- 晨会笔记
- `/improve` -- 自动代码改进建议

---

## 后端路由

所有 LLM 调用走 `get_core_client()` -- 一个 env var 切换全部:

```bash
stock backend set claude_cli   # 默认，订阅免费
stock backend set minimax       # 切回 MiniMax (按量计费)
```

**当前**: claude_cli (Opus 4.7), 零增量费用。

---

## APK + Render

老板的 Android APK 通过 Render 云代理拉取数据：

- 本机每 5 秒推送 research_reports 到 Render `/sync/notes`
- APK 每 N 秒拉 `/channel/api/notes` 显示
- recipient token 鉴权
- 支持: daily / tech_dive / dd_checklist / earnings_review / morning_note / deep_qa / alert / trade_log / grading / reply

---

## 已知 issues

1. **PDF 中文字体**: xhtml2pdf 不带 CJK 字体 → 中文显示为方块。**解决**: HTML 同步生成，
   Chrome 打开后"另存为 PDF"即可。
2. **MiniMax 余额**: 已迁移所有调用到 claude_cli。如要切回需要先 `stock backend set minimax`。
3. **盛合晶微**: 私募 SMIC 封装 JV，无公开 ticker，仅定性跟踪。
4. **MCP connectors** (Aiera/S&P Kensho 等): 均需付费订阅，暂未集成。
5. **F44 21:15 UTC cron**: 触发了但 claude_cli 返回空 body（rate limit 嫌疑），未持久化。
   下次自然 fire 应正常工作。

---

## 公司密集索引 / Per-company dense files

`pipeline/companies/<TICKER>.md` -- 每家被研究覆盖过的公司（≥2 次提及）的全部上下文聚合。
覆盖 44 家公司，含中际旭创、天孚通信、寒武纪、云南锗业、ACMR、BESI、CAMT 等。
索引文件: `pipeline/companies/INDEX.md`，按提及次数排序。

刷新方法: `python scripts/compress_dives_to_companies.py`（无 LLM 费用）。

---

_Not financial advice. 不构成投资建议._
