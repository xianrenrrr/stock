"""tests.test_prompt_rewriter -- Opus-driven file editor tests."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stock import prompt_rewriter
from stock.models import ChatResponse
from stock.prompt_rewriter import (
    ALLOWED_TARGETS,
    RewriteProposal,
    apply_rewrite,
    parse_patches,
    propose_rewrite,
    revert_rewrite,
)


def _stub_response(content: str, cost: float = 0.001) -> ChatResponse:
    """Build a fake ChatResponse for the rewriter LLM call."""
    return ChatResponse(
        content=content, input_tokens=200, output_tokens=100,
        model="claude-opus-4-7", cost_usd=cost,
    )


def test_parse_patches_basic() -> None:
    """parse_patches extracts target / before / after / rationale fields."""
    text = """
<patch>
  <target>prompts/research.txt</target>
  <before><![CDATA[Keep the whole note under {max_chars} characters total]]></before>
  <after><![CDATA[Keep the whole note under 1500 characters total]]></after>
  <rationale>Boss asked for shorter notes.</rationale>
</patch>
"""
    out = parse_patches(text)
    assert len(out) == 1
    target, before, after, rationale = out[0]
    assert target == "prompts/research.txt"
    assert "1500" in after
    assert "shorter" in rationale.lower()


def test_apply_rewrite_byte_exact_replace(
    mem_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """apply_rewrite replaces the verbatim before_text and stamps applied=1."""
    target = tmp_path / "research.txt"
    target.write_text("hello WORLD bar", encoding="utf-8")

    # Patch ALLOWED_TARGETS to include our test file
    monkeypatch.setattr(
        "stock.prompt_rewriter.ALLOWED_TARGETS",
        (str(target),) + ALLOWED_TARGETS,
    )

    proposal = RewriteProposal(
        target_path=str(target),
        before_text="hello WORLD",
        after_text="hi globe",
        rationale="test",
    )
    rid = apply_rewrite(proposal, mem_db)
    assert rid is not None
    assert "hi globe" in target.read_text(encoding="utf-8")

    row = mem_db.execute(
        "SELECT applied, target_path FROM prompt_rewrites WHERE id = ?",
        (rid,),
    ).fetchone()
    assert row[0] == 1
    assert row[1] == str(target)


def test_apply_rewrite_stages_when_no_match(
    mem_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A before_text that is not present in the file stages applied=0."""
    target = tmp_path / "research.txt"
    target.write_text("foo bar baz", encoding="utf-8")
    monkeypatch.setattr(
        "stock.prompt_rewriter.ALLOWED_TARGETS",
        (str(target),) + ALLOWED_TARGETS,
    )

    proposal = RewriteProposal(
        target_path=str(target),
        before_text="never present",
        after_text="x",
        rationale="t",
    )
    rid = apply_rewrite(proposal, mem_db)
    row = mem_db.execute(
        "SELECT applied FROM prompt_rewrites WHERE id = ?", (rid,)
    ).fetchone()
    assert row[0] == 0


def test_apply_rewrite_rejects_disallowed_path(
    mem_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """A target outside ALLOWED_TARGETS raises ValueError."""
    proposal = RewriteProposal(
        target_path="/etc/passwd",
        before_text="root", after_text="boom",
        rationale="never",
    )
    with pytest.raises(ValueError):
        apply_rewrite(proposal, mem_db)


def test_apply_rewrite_rate_limited(
    mem_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second apply within RATE_LIMIT_HOURS stages applied=0."""
    target = tmp_path / "research.txt"
    target.write_text("foo bar baz", encoding="utf-8")
    monkeypatch.setattr(
        "stock.prompt_rewriter.ALLOWED_TARGETS",
        (str(target),) + ALLOWED_TARGETS,
    )

    proposal_1 = RewriteProposal(
        target_path=str(target), before_text="foo", after_text="zzz",
        rationale="first",
    )
    apply_rewrite(proposal_1, mem_db)

    # Second proposal on the same file should not apply due to rate limit
    proposal_2 = RewriteProposal(
        target_path=str(target), before_text="zzz", after_text="qqq",
        rationale="second",
    )
    rid = apply_rewrite(proposal_2, mem_db)
    row = mem_db.execute(
        "SELECT applied FROM prompt_rewrites WHERE id = ?", (rid,)
    ).fetchone()
    assert row[0] == 0


def test_revert_rewrite_restores_original(
    mem_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """revert_rewrite swaps after_text back to before_text."""
    target = tmp_path / "research.txt"
    target.write_text("alpha bravo", encoding="utf-8")
    monkeypatch.setattr(
        "stock.prompt_rewriter.ALLOWED_TARGETS",
        (str(target),) + ALLOWED_TARGETS,
    )
    proposal = RewriteProposal(
        target_path=str(target), before_text="alpha", after_text="ALPHA",
        rationale="t",
    )
    rid = apply_rewrite(proposal, mem_db)
    assert rid is not None
    assert "ALPHA" in target.read_text(encoding="utf-8")

    ok = revert_rewrite(rid, mem_db)
    assert ok is True
    assert "alpha bravo" == target.read_text(encoding="utf-8")


def test_propose_rewrite_filters_disallowed(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """propose_rewrite drops patches whose target_path is not allowed."""
    # Insert one instruction-typed inbound row to give propose_rewrite content
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO conversations (run_id, recipient, direction, body,"
        " intent, created_at) VALUES ('r', 'boss', 'inbound', 'shorter',"
        " 'instruction', ?)",
        (now,),
    )
    mem_db.commit()
    cid = int(mem_db.execute("SELECT last_insert_rowid()").fetchone()[0])

    bad_response = _stub_response("""
<patch>
  <target>/etc/passwd</target>
  <before><![CDATA[root]]></before>
  <after><![CDATA[boom]]></after>
  <rationale>nope</rationale>
</patch>
""")
    fake_client = MagicMock()
    fake_client.provider = "codex_cli"
    fake_client.chat = MagicMock(return_value=bad_response)
    monkeypatch.setattr("stock.prompt_rewriter.get_core_client", lambda: fake_client)
    monkeypatch.setattr("stock.prompt_rewriter.get_core_model", lambda: "codex-cli-session")

    out = propose_rewrite([cid], mem_db)
    assert out == []


def test_propose_rewrite_diff_size_cap(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """An after_text that is grossly larger than before_text is dropped."""
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO conversations (run_id, recipient, direction, body,"
        " intent, created_at) VALUES ('r', 'boss', 'inbound', 'shorter',"
        " 'instruction', ?)",
        (now,),
    )
    mem_db.commit()
    cid = int(mem_db.execute("SELECT last_insert_rowid()").fetchone()[0])

    huge = "x" * 10_000
    response = _stub_response(f"""
<patch>
  <target>prompts/research.txt</target>
  <before><![CDATA[hi]]></before>
  <after><![CDATA[{huge}]]></after>
  <rationale>boom</rationale>
</patch>
""")
    fake_client = MagicMock()
    fake_client.provider = "codex_cli"
    fake_client.chat = MagicMock(return_value=response)
    monkeypatch.setattr("stock.prompt_rewriter.get_core_client", lambda: fake_client)
    monkeypatch.setattr("stock.prompt_rewriter.get_core_model", lambda: "codex-cli-session")

    out = propose_rewrite([cid], mem_db)
    assert out == []
