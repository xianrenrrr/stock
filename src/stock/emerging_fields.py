"""stock.emerging_fields -- auto-track new technology fields from discovery themes."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import BaseModel

FIELDS_PATH: str = "data/emerging_fields.yaml"

_FIELD_PATTERNS: tuple[tuple[str, str], ...] = (
    ("space_tech", r"\b(space|satellite|orbital|rocket|launch|lunar|geospatial)\b"),
    ("quantum_tech", r"\b(quantum|qubit|photonic quantum|ion trap)\b"),
    ("robotics_autonomy", r"\b(robotics|robot|humanoid|autonomous|autonomy)\b"),
    ("fusion_energy", r"\b(fusion|tokamak|stellarator|plasma)\b"),
    ("advanced_materials", r"\b(metamaterial|advanced materials|graphene|ceramic)\b"),
    ("synthetic_biology", r"\b(synthetic biology|biofoundry|biomanufacturing)\b"),
)
_AI_RE = re.compile(r"\b(ai|artificial intelligence|machine learning|foundation model)\b", re.I)


class ThemeLike(Protocol):
    theme: str
    summary: str


class EmergingField(BaseModel):
    id: str
    name: str
    status: str = "candidate"
    source: str = "web_discovery"
    rationale: str = ""
    evidence_count: int = 1
    first_seen: str
    last_seen: str
    suggested_queries: list[str] = []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_raw(path: str = FIELDS_PATH) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    rows = raw.get("fields") or []
    return [dict(r) for r in rows if isinstance(r, dict)]


def _save_raw(rows: list[dict], path: str = FIELDS_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump({"fields": rows}, sort_keys=False, allow_unicode=True, width=200),
        encoding="utf-8",
    )


def load_fields(*, path: str = FIELDS_PATH, active_only: bool = False) -> list[EmergingField]:
    fields: list[EmergingField] = []
    for row in _load_raw(path):
        try:
            field = EmergingField(**row)
        except Exception:
            continue
        if active_only and field.status not in {"active", "candidate"}:
            continue
        fields.append(field)
    return fields


def _classify_field(text: str) -> str | None:
    for field_id, pattern in _FIELD_PATTERNS:
        if re.search(pattern, text, re.I):
            return field_id
    return None


def _display_name(field_id: str) -> str:
    return field_id.replace("_", " ").title()


def _queries(field_id: str) -> list[str]:
    label = field_id.replace("_", " ")
    return [
        f"{label} public companies AI technology shift",
        f"{label} hidden gem small cap stocks",
        f"{label} supply chain bottleneck listed companies",
    ]


def update_from_themes(themes: list[ThemeLike], *, path: str = FIELDS_PATH) -> int:
    """Upsert field candidates from discovery themes."""
    rows = _load_raw(path)
    by_id = {str(r.get("id", "")): r for r in rows}
    now = _now_iso()
    changed = 0

    for theme in themes:
        text = f"{theme.theme} {theme.summary}".strip()
        field_id = _classify_field(text)
        if not field_id:
            continue
        is_groundbreaking_non_ai = field_id in {"space_tech", "quantum_tech", "fusion_energy"}
        if not _AI_RE.search(text) and not is_groundbreaking_non_ai:
            continue

        if field_id in by_id:
            row = by_id[field_id]
            row["evidence_count"] = int(row.get("evidence_count") or 0) + 1
            row["last_seen"] = now
            if text[:220] not in str(row.get("rationale", "")):
                row["rationale"] = (
                    str(row.get("rationale", "")).rstrip() + "\n- " + text[:220]
                ).strip()
        else:
            row = {
                "id": field_id,
                "name": _display_name(field_id),
                "status": "candidate",
                "source": "web_discovery.auto_field_detection",
                "rationale": f"- {text[:220]}",
                "evidence_count": 1,
                "first_seen": now,
                "last_seen": now,
                "suggested_queries": _queries(field_id),
            }
            rows.append(row)
            by_id[field_id] = row
        changed += 1

    if changed:
        _save_raw(rows, path)
    return changed


def format_fields_block(fields: list[EmergingField], *, max_fields: int = 8) -> str:
    if not fields:
        return "(no auto-discovered emerging fields yet)"
    lines = [
        "| Field | Status | Evidence | Why it matters | Suggested search |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for field in fields[:max_fields]:
        why = field.rationale.replace("\n", " ")[:120] or "-"
        query = field.suggested_queries[0] if field.suggested_queries else "-"
        lines.append(
            f"| {field.name} | {field.status} | {field.evidence_count} | {why} | {query} |"
        )
    return "\n".join(lines)
