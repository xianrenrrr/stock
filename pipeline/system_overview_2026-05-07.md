# 系统全景说明 / How the whole STOCK system works

_2026-05-07 end-of-day summary, 老板要求的中文版本_

---

## 一句话总结

每天 24 小时不间断运行的 AI 股票研究工厂：自动收集数据、跑 LLM 深挖、识别异常信号、把"在爆发前夜"的隐藏机会推到老板的 APK 上。完全跑在本机笔记本 + Render 云代理上，零外部 API 月费（除 yfinance / SEC EDGAR / RSS 这些免费源）。

---

## 三大数据层

### 1. 数据采集层 (Ingest)
**每 15 分钟自动跑** during US market hours (14:00-21:45 UTC):
- **新闻**: Yahoo + RSS + SEC EDGAR (10-Q, 10-K, 8-K, Form 4)
- **价格**: yfinance daily OHLCV (端 = 明天日期，避免昨晚 fix 过的 1 天滞后 bug)
- **特征提取**: 每条新闻跑一次 LLM (claude_cli, 免费), 输出结构化 JSON (情绪 / 新颖度 / 催化剂类型 / 时间敏感度 / 摘要)
- **内幕交易**: SEC EDGAR Form 4 ATOM + XML body (F35 fix)
- **期权异常 (F36)**: yfinance 期权链, 标记 vol/OI ≥ 5 + 距现价 12% 以内的 EXTREME 信号

### 2. 信号分析层 (Analysis)
**每天 21:30-23:30 UTC 集中跑** (美股收盘后):
- **Score (F08)**: 给昨天的预测打分, 更新 bandit + 校准
- **Thesis verify (F16)**: 论点核验 -- 把昨天的"催化剂"主张去新闻里找证据
- **Grade & Reply (F11)**: 评分备忘录 + 自动排队下一轮深挖话题
- **Tracked events (F26)**: 验证之前预测的事件是否兑现 (hit/miss/partial/pending)
- **UOA scan (F36)**: 期权异常扫描
- **Smallcap scan (F38)**: 33 只小盘股 (3 板块 × ~10 只) 重新打分
- **Discovery (F19)**: FWP 综合评分 (insider + 8K novelty + reddit 加速 + theme velocity)
- **AI loop (F39)**: 每周一 AI-using SaaS 公司毛利+收入趋势监控

### 3. 输出层 (Output)
- **Daily research (F00)**: 早 02:30 / 晚 14:30 UTC, 长篇研究报告
- **Tech dive (F43)**: 每天 04:30 UTC 一次, 4 轮结构化技术深挖 (技术闭环 + 商业闭环 + 公司链条 + 证伪综合), 板块轮换 (信息 / 生物医药×AI / 能源)
- **Company DD dive (F44)**: 每天 5 次 (3,7,12,16,21:15 UTC), 每次 1 个公司 12 项尽调清单
- **Weekly QA (F40)**: 周六 07:00 UTC, top-5 FWP 候选股 5 轮 Q&A
- **Self review (F18)**: 每天 06:00 UTC, 自动写 daily_review_*.md 操作复盘
- **Daily zh (F-) **: `stock daily-zh` 中文日报
- **Earnings review / DD checklist / Morning note (F44)**: 调用即用

---

## 现在每天具体做什么

| 时间 (UTC) | 任务 | 输出 |
|---|---|---|
| 02:30 | 早晨研究推送 | research_reports kind='daily' |
| 03:15 | 公司 DD 深挖 #1 | dd_checklist (1 公司) |
| 04:30 | 当日技术趋势深挖 | tech_dive (1 主题) |
| 06:00 | 自我复盘包 | daily_review_*.md |
| 06:30 (周一) | AI 商业闭环面板 | ai_loop_health |
| 07:00 (周六) | top-5 FWP Q&A 深挖 | deep_qa × 5 |
| 07:45 | 公司 DD 深挖 #2 | dd_checklist |
| 12:15 | 公司 DD 深挖 #3 | dd_checklist |
| 14:00-21:45 (每 15 分钟) | 新闻+价格+特征 ingest | features, prices, news |
| 14:30 | 晚间研究推送 | research_reports kind='daily' |
| 16:45 | 公司 DD 深挖 #4 | dd_checklist |
| 21:15 | 公司 DD 深挖 #5 | dd_checklist |
| 21:30 | 评分日 | predictions_scored, bandit_state |
| 21:45 | 评分备忘 + 后续排队 | grading note + action_queue |
| 21:50 | 跟踪事件验证 | tracked_events 状态 |
| 21:55 | UOA 扫描 | option_anomalies |
| 22:15 | 小盘股扫描 | smallcap_candidates |
| 23:00 | 前瞻发现引擎 | discovery_candidates |
| 23:30 | SQLite 在线备份 | data/backups/ |
| _/5s_ | Render 同步 | 推送 research_reports + 拉取 boss 回复 |

**总计 26 个 cron jobs**, 全部跑 claude_cli 后端 (零增量费用).

---

## 收集的关键信息

### 价格 + 成交 (prices)
- 美股 watchlist 26 只 + A 股+港股 13 只 + 小盘宇宙 33 只 = 共 ~70 只 ticker
- 每天收盘后自动入库

### 新闻 (news)
- 每 ticker 多源 (Yahoo RSS + EDGAR + 自动 web 搜索)
- 提取后挂上 features (情绪 / 新颖度 / 催化剂)

### 内幕交易 (insider_filings)
- SEC Form 4 ATOM feed + XML body 解析
- transaction_type / shares / price / 角色 全字段填充 (F35 fix 后)

### 期权异常 (option_anomalies)
- 每 ticker 每天扫一次
- 标记 vol/OI ≥ 5 + 接近 ATM 的"smart money positioning"

### 论点核验 (theses)
- 每个预测被分解成多个原子主张
- 验证后打 supports / contradicts / mixed / no_evidence 标签

### 跟踪事件 (tracked_events)
- 用户/系统预测的具体催化剂事件 (e.g. "NVDA 5月底前发布 Blackwell-Ultra")
- 自动验证窗口结束后的命中率

### 技术趋势 (tech_trends.yaml)
- 13 个具体技术趋势 (10 enabled + 3 swappable)
- 每个有时间窗口 + why_now 证据 + 证伪触发器 + pure-play + diversified vehicles

### 重仓股 (conviction_watchlist.yaml)
- 17 只 enabled + 10 个新增 boss-directed adds
- 每只挂上对应的 trend_id

### 板块前瞻 (smallcap_universe.yaml)
- 33 只小盘股 across 3 板块 (AI 算力 / 生物医药 / 能源)

---

## 老板的 APK 看到什么

**通过 Render /channel/api/notes 自动拉取**, 全部按 kind 分类:
- `daily` -- 每天早晚研究推送
- `tech_dive` -- 4 轮结构化技术深挖
- `dd_checklist` -- 12 项尽调清单
- `earnings_review` -- 业绩复盘
- `morning_note` -- 1 页晨会笔记
- `deep_qa` -- 5 轮 Q&A 深挖
- `alert` -- 持仓警报 (e.g. SMCI fraud_legal)
- `trade_log` -- 交易记录
- `grading` -- 评分备忘录

每个都带时间戳 + topic + body, 老板手机一打开就能看, 不用跳来跳去.

---

## Claude Code 集成

新增的 4 个 slash 命令 (boss 直接打 `/...` 就能用):
- `/tech-dive <topic>` -- 4 轮技术深挖
- `/earnings <ticker>` -- 业绩复盘
- `/dd-checklist <ticker>` -- 12 项尽调
- `/morning-note` -- 隔夜要闻摘要

加上 `/improve` (代码改进建议) -- 共 5 个 STOCK-specific 命令.

---

## 已知问题

1. **PDF 中文字体**: xhtml2pdf 不带 CJK 字体 → 中文显示为方块. **解决方案**: HTML 同步生成, boss 用 Chrome 打开 HTML 后"另存为 PDF"即可正确渲染中文.
2. **MiniMax 余额**: 已迁移所有调用到 claude_cli, MiniMax 仅作 fallback. 如需切回: `stock backend set minimax`.
3. **盛合晶微**: 私募 SMIC 封装 JV, 暂无公开 ticker, 仅定性跟踪.
4. **腿冷概念股**: 英维克 Q1 不及预期, 暂时观望 (per 老板 article)

---

## 今晚已完成

- 11 个 tech_dive 跑通 (OCS + HBM4 + CoWoS + 中国半导体 + AI 抗体发现 + AlphaFold 后续 + 4 个 retry 失败的能源/临床), PDF + Render 同步
- 10 个新 conviction 添加 (含 boss-directed 中际旭创, 天孚, 云南锗业, 工业富联, 寒武纪, 海光, 拓荆, 沪电 etc.)
- F44 analyst skills (earnings/dd-checklist/morning-note) 上线, 含 4 测试
- F44 company_dd_dive cron (每 4.5h 一次) 注册
- BE entry zone 计算: $234-$265 推荐回踩区间 (当前 $285)
- IDM PPT 全文提取存档 → 验证 TFLN/TSAG 论点 + 客户清单
- 自动 4.5h 续接 cron 已注册 (会议结束后保持工作流推进)
- code_structure.md 同步更新

**今天 git commits**: ~5 个 (含 F44, 公司 DD queue, entry-zone, BE prices fix, 各种小补丁)
**今天 LLM calls**: ~31 (claude_cli 全部 $0)
**APK 上新内容**: 8+ 篇 tech_dive 报告

---

_Not financial advice. 不构成投资建议._
