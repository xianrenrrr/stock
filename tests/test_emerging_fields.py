"""tests.test_emerging_fields -- auto field tracking from discovery themes."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from stock.emerging_fields import format_fields_block, load_fields, update_from_themes


class Theme(BaseModel):
    theme: str
    summary: str


def test_update_from_themes_adds_space_field(tmp_path: Path) -> None:
    path = tmp_path / "emerging_fields.yaml"

    changed = update_from_themes(
        [
            Theme(
                theme="AI geospatial intelligence",
                summary="Satellite imagery is becoming a queryable AI data layer.",
            )
        ],
        path=str(path),
    )

    assert changed == 1
    fields = load_fields(path=str(path))
    assert fields[0].id == "space_tech"
    assert fields[0].evidence_count == 1
    assert "satellite" in fields[0].rationale.lower()


def test_update_from_themes_increments_existing(tmp_path: Path) -> None:
    path = tmp_path / "emerging_fields.yaml"
    theme = Theme(
        theme="Quantum AI",
        summary="AI control software improves qubit calibration.",
    )

    update_from_themes([theme], path=str(path))
    update_from_themes([theme], path=str(path))

    fields = load_fields(path=str(path))
    assert fields[0].id == "quantum_tech"
    assert fields[0].evidence_count == 2


def test_format_fields_block_handles_empty() -> None:
    assert "no auto-discovered" in format_fields_block([]).lower()
