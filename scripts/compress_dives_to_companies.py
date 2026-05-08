"""scripts/compress_dives_to_companies.py -- aggregate every tech_dive
mention of a ticker into per-company dense files at pipeline/companies/<TICKER>.md.

Boss directive 2026-05-07: "currently is too many field too repetitive ...
compress them by a dense folder for dive deep companies". Produces one
markdown file per ticker with all surrounding context bullets, deduplicated
across the 17 tech_dive_runs we have.

Pure programmatic -- no LLM cost. Regex finds tickers (US 1-5 letter caps,
A-share \d{6}\.SZ/SS, HK \d{4}\.HK, Star \d{6}\.SH), gathers the line +
2 lines of context, dedupes, groups by ticker.
"""
from __future__ import annotations

import re
import sys
import io
from collections import defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stock.db import get_conn

OUTPUT_DIR = Path("pipeline/companies")

# Match: 1-5 ASCII upper-case (NVDA, COHR, BESI.AS), 6-digit Chinese (300308.SZ,
# 002463.SS, 688012.SH), 4-digit HK (0981.HK), or .AS / .TW suffixes.
TICKER_RE = re.compile(
    r"\b("
    r"[A-Z]{1,5}(?:\.AS|\.TW)?"
    r"|\d{6}\.(?:SS|SZ|SH)"
    r"|\d{4}\.HK"
    r")\b"
)

# Tickers we should ignore (false-positive English words / acronyms)
TICKER_BLACKLIST = {
    "AI", "DC", "PCB", "GPU", "CPU", "HBM", "EUV", "ML", "IP", "OK", "OKAY",
    "OK", "USA", "US", "EU", "UK", "JP", "CN", "FR", "DE", "ASIC", "SOC",
    "OEM", "ODM", "TAM", "SAM", "IRR", "MOIC", "DCF", "LBO", "FCF", "EPS",
    "PE", "PB", "PS", "EV", "EBITDA", "MA", "CEO", "CFO", "COO", "CTO",
    "API", "SDK", "RFP", "MTM", "FY", "QY", "YOY", "QOQ", "IPO", "BPS",
    "BS", "PR", "VC", "LP", "GP", "MOM", "ID", "OK", "RD", "MFG", "SOTA",
    "POC", "MVP", "KPI", "OKR", "ARR", "CAC", "LTV", "GTM", "NPV", "TCO",
    "KYC", "AML", "BD", "PM", "VP", "SVP", "AML", "QA", "QC", "DD", "OS",
    "DB", "UI", "UX", "AR", "VR", "OS", "FA", "AG", "AS", "KO", "HR",
    "II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "OK", "DR",
    "MASH", "SOFC", "PEMFC", "GLP", "SMR", "TFLN", "PAM", "OCS", "CPO",
    "MEMS", "FAU", "EML", "ELS", "DSP", "CWDM", "DWDM", "OFC", "NRC",
    "DOE", "FDA", "EMA", "EPC", "IDM", "OSAT", "WPM", "BOM", "GTM",
    "TKI", "ADC", "ROS", "ALK", "AML", "CMP", "CVD", "ALD", "TCB", "PCB",
    "NVL", "NV", "B", "T", "K", "M", "G", "RD", "QC", "QA",
    "HALEU", "LEU", "MMC", "MDC", "MPO", "MTP", "TGG", "TSAG", "InP", "INP",
    "GAAS", "GE", "GA", "AT", "BE", "OR", "ON", "TO", "WHO", "ALL", "NOR",
    "NCF", "ABF", "MMC", "TCO", "PUE", "AHL", "HALE",
}


def load_whitelist() -> set[str]:
    """Build the set of tickers we actually track from our YAML files.

    Pure programmatic, no LLM. Pulls from watchlist, conviction watchlist,
    smallcap universe, tech trends vehicles, and company dive queue. This
    is the universe of real, intentional tickers -- everything else is
    treated as a false positive (English word, acronym, etc).
    """
    import yaml
    out: set[str] = set()
    files = [
        ("data/watchlist.yaml", "tickers", lambda x: [str(t) for t in x]),
        ("data/conviction_watchlist.yaml", "names", lambda x: [r["ticker"] for r in x]),
        ("data/company_dive_queue.yaml", "companies", lambda x: [r["ticker"] for r in x]),
        ("data/smallcap_universe.yaml", "universe", lambda x: [
            r["ticker"] for sect in x.values() for r in sect
        ]),
    ]
    for path_str, key, extractor in files:
        try:
            data = yaml.safe_load(Path(path_str).read_text(encoding="utf-8")) or {}
            tickers = extractor(data.get(key, []))
            for t in tickers:
                if t:
                    out.add(t.upper())
        except Exception:
            pass
    # Add tech_trends vehicles
    try:
        data = yaml.safe_load(Path("data/tech_trends.yaml").read_text(encoding="utf-8")) or {}
        for trend in data.get("trends", []):
            for t in trend.get("vehicles_pure_play", []) + trend.get("vehicles_diversified", []):
                if t:
                    out.add(t.upper())
    except Exception:
        pass
    # Secular themes beneficiaries
    try:
        data = yaml.safe_load(Path("data/secular_themes.yaml").read_text(encoding="utf-8")) or {}
        for theme in data.get("themes", []):
            for r in theme.get("beneficiaries", []) + theme.get("losers", []):
                if r.get("ticker"):
                    out.add(str(r["ticker"]).upper())
    except Exception:
        pass
    return out


_WHITELIST_CACHE: set[str] | None = None


def is_real_ticker(t: str) -> bool:
    """Whitelist-only + minimum length filter (1-letter tickers like M are
    indistinguishable from natural-language tokens, so we drop them from
    aggregation even if they're tracked)."""
    global _WHITELIST_CACHE
    if _WHITELIST_CACHE is None:
        _WHITELIST_CACHE = load_whitelist()
    # 1-letter tickers (M Macy's, F Ford, etc.) generate too many false-positive
    # matches in narrative text; require >=2 chars OR an exchange suffix.
    if len(t) <= 1 and "." not in t:
        return False
    return t.upper() in _WHITELIST_CACHE


def extract_mentions(body: str, topic: str) -> dict[str, list[str]]:
    """Find every ticker mention; return {ticker: [context_lines]}."""
    out: dict[str, list[str]] = defaultdict(list)
    lines = body.split("\n")
    for i, line in enumerate(lines):
        for m in TICKER_RE.finditer(line):
            t = m.group(1)
            if not is_real_ticker(t):
                continue
            # Capture this line + previous 1 line for context
            ctx_start = max(0, i - 1)
            ctx_end = min(len(lines), i + 2)
            context = "\n".join(lines[ctx_start:ctx_end]).strip()
            if context and context not in out[t]:
                out[t].append(context)
    return out


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, kind, topic, body, created_at FROM research_reports"
        " WHERE kind IN ('tech_dive', 'deep_qa', 'morning_note', 'earnings_review',"
        "                'dd_checklist')"
        " ORDER BY created_at"
    ).fetchall()

    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for rid, kind, topic, body, created_at in rows:
        body_str = body or ""
        topic_str = topic or ""
        mentions = extract_mentions(body_str, topic_str)
        for ticker, contexts in mentions.items():
            for ctx in contexts:
                by_ticker[ticker].append({
                    "rid": rid, "kind": kind, "topic": topic_str[:60],
                    "created_at": created_at, "context": ctx,
                })

    print(f"Companies surfaced across {len(rows)} reports: {len(by_ticker)}")

    # Render per-company files
    for ticker, entries in sorted(by_ticker.items()):
        if len(entries) < 2:  # skip drive-by single mentions
            continue
        path = OUTPUT_DIR / f"{ticker.replace('.', '_')}.md"
        lines = [
            f"# {ticker} -- 综合提取 / All mentions across our research",
            "",
            f"_Aggregated from {len(entries)} mentions across "
            f"{len({e['rid'] for e in entries})} reports. "
            f"Auto-generated; rerun via "
            f"`python scripts/compress_dives_to_companies.py`._",
            "",
            "---",
            "",
        ]
        # Group by source rid
        by_rid: dict[int, list[dict]] = defaultdict(list)
        for e in entries:
            by_rid[e["rid"]].append(e)
        for rid in sorted(by_rid.keys()):
            sample = by_rid[rid][0]
            lines.append(f"## From {sample['kind']} #{rid}: {sample['topic']}...")
            lines.append(f"_{sample['created_at'][:16]}_")
            lines.append("")
            seen = set()
            for e in by_rid[rid]:
                if e["context"] in seen:
                    continue
                seen.add(e["context"])
                lines.append(f"> {e['context']}")
                lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")

    # Index file
    index = OUTPUT_DIR / "INDEX.md"
    idx_lines = [
        "# 公司索引 / Per-company dense reference index",
        "",
        f"_Total tickers with 2+ mentions: "
        f"{sum(1 for v in by_ticker.values() if len(v) >= 2)}_",
        "",
        "Sorted by mention count (most-mentioned first):",
        "",
    ]
    sorted_t = sorted(by_ticker.items(), key=lambda kv: -len(kv[1]))
    for ticker, entries in sorted_t:
        if len(entries) < 2:
            continue
        path_name = f"{ticker.replace('.', '_')}.md"
        idx_lines.append(f"- **{ticker}** ({len(entries)} mentions) -- [{path_name}]({path_name})")
    index.write_text("\n".join(idx_lines), encoding="utf-8")

    print(f"Wrote {OUTPUT_DIR}/ -- "
          f"{sum(1 for v in by_ticker.values() if len(v) >= 2)} per-company files + INDEX.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
