"""stock.pdf_export -- markdown to PDF via weasyprint.

Boss directive 2026-05-06: "PDF or PPT" (NotebookLM-style). PDF is the
cheap path -- weasyprint is pure-Python (no LaTeX/pandoc), reads markdown
through python-markdown, renders via CSS print stylesheet.

Usage:
  stock pdf-export research <id>          # one research_reports row -> PDF
  stock pdf-export file <path.md>         # any markdown file -> PDF
  stock pdf-export tech-dive <topic>      # most recent dive matching topic
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import markdown as md_lib

logger = logging.getLogger(__name__)

OUTPUT_DIR: str = "pipeline/pdf"

# CSS designed for boss-style reading: serif headers + monospace tables,
# Chinese-friendly font fallback (Microsoft YaHei + Noto Sans CJK + sans-serif).
_BASE_CSS: str = """
@page { size: A4; margin: 1.6cm 1.4cm 1.6cm 1.4cm; }

body {
  font-family: "Microsoft YaHei", "Noto Sans CJK SC", "PingFang SC", sans-serif;
  font-size: 10.5pt;
  line-height: 1.55;
  color: #1a1a1a;
}

h1 { font-size: 22pt; border-bottom: 2px solid #2c3e50; padding-bottom: 6px;
     margin-top: 0; color: #2c3e50; }
h2 { font-size: 15pt; color: #34495e; margin-top: 20px;
     border-bottom: 1px solid #bdc3c7; padding-bottom: 3px; }
h3 { font-size: 12pt; color: #2c3e50; margin-top: 14px; }
h4 { font-size: 11pt; color: #34495e; }

p { margin: 6px 0; }
ul, ol { margin: 6px 0; padding-left: 22px; }
li { margin: 2px 0; }

code {
  font-family: "Consolas", "Cascadia Code", "Courier New", monospace;
  font-size: 9.5pt;
  background-color: #f4f4f4;
  padding: 1px 4px;
  border-radius: 2px;
}

pre {
  background-color: #f4f4f4;
  padding: 8px;
  border-left: 3px solid #3498db;
  border-radius: 3px;
  overflow-wrap: break-word;
  white-space: pre-wrap;
  font-size: 9pt;
}

table {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
  font-size: 9.5pt;
}
th, td { border: 1px solid #bdc3c7; padding: 4px 8px; text-align: left;
         vertical-align: top; }
th { background-color: #ecf0f1; font-weight: bold; }
tr:nth-child(even) td { background-color: #fafafa; }

blockquote {
  border-left: 3px solid #95a5a6;
  margin-left: 0;
  padding-left: 12px;
  color: #555;
  font-style: italic;
}

hr { border: 0; border-top: 1px solid #bdc3c7; margin: 18px 0; }

strong { color: #2c3e50; }
"""


def _markdown_to_html(md_text: str) -> str:
    """Convert markdown to HTML with table + fenced-code support."""
    return md_lib.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
        output_format="html5",
    )


def render_pdf(md_text: str, *, title: str | None = None, out_path: str | Path) -> Path:
    """Render markdown to a PDF file at out_path.

    Tries weasyprint first (better CSS support, requires GTK/Pango); falls
    back to xhtml2pdf (pure Python, more limited CSS but works on Windows
    without external deps). HTML is also written next to the PDF as a
    side-effect so the operator can debug rendering.
    """
    html_body = _markdown_to_html(md_text)
    title_html = f"<title>{title}</title>" if title else ""
    style_block = f"<style>{_BASE_CSS}</style>"
    full_html = (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'{title_html}{style_block}</head>'
        f'<body>{html_body}</body></html>'
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Always write the HTML alongside -- useful as a fallback artifact and
    # helpful when boss wants to view in a browser.
    html_out = out.with_suffix(".html")
    html_out.write_text(full_html, encoding="utf-8")

    # Try weasyprint (best output) -> xhtml2pdf (pure Python fallback)
    try:
        from weasyprint import CSS, HTML
        HTML(string=full_html).write_pdf(str(out), stylesheets=[CSS(string=_BASE_CSS)])
        return out
    except (OSError, ImportError) as exc:
        logger.warning("weasyprint unavailable (%s); falling back to xhtml2pdf", exc)

    try:
        from xhtml2pdf import pisa
        with open(out, "wb") as fh:
            result = pisa.CreatePDF(src=full_html, dest=fh, encoding="utf-8")
        if result.err:
            raise RuntimeError(f"xhtml2pdf reported {result.err} errors")
        return out
    except Exception:
        logger.exception("PDF render failed; HTML preserved at %s", html_out)
        raise


def export_research_report(
    conn: sqlite3.Connection, research_id: int, *,
    out_dir: str | Path = OUTPUT_DIR,
) -> Path:
    """Export one research_reports row as PDF; returns the output path."""
    row = conn.execute(
        "SELECT topic, kind, body, created_at FROM research_reports WHERE id = ?",
        (research_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"research_id {research_id} not found")
    topic, kind, body, created_at = row
    safe_topic = "".join(c if c.isalnum() or c in "-_" else "_" for c in (topic or "report")[:60])
    date_part = (created_at or datetime.now(timezone.utc).isoformat())[:10]
    fname = f"{kind}_{date_part}_{research_id}_{safe_topic}.pdf"
    return render_pdf(body or "", title=topic or "report", out_path=Path(out_dir) / fname)


def export_markdown_file(path: str | Path, *, out_dir: str | Path = OUTPUT_DIR) -> Path:
    """Export an arbitrary .md file as PDF."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(str(src))
    body = src.read_text(encoding="utf-8")
    out = Path(out_dir) / (src.stem + ".pdf")
    return render_pdf(body, title=src.stem, out_path=out)


def export_recent_tech_dives(
    conn: sqlite3.Connection, *, days: int = 1, out_dir: str | Path = OUTPUT_DIR,
) -> list[Path]:
    """Export every tech_dive_run from the last N days. Returns paths written."""
    rows = conn.execute(
        "SELECT research_id FROM tech_dive_runs"
        " WHERE created_at >= datetime('now', ?)"
        " ORDER BY created_at DESC",
        (f"-{int(days)} days",),
    ).fetchall()
    out: list[Path] = []
    for (rid,) in rows:
        try:
            out.append(export_research_report(conn, int(rid), out_dir=out_dir))
        except Exception:  # noqa: BLE001 -- one failure shouldn't kill the batch
            logger.exception("PDF export failed for research_id=%s", rid)
    return out
