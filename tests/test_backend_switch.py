"""tests.test_backend_switch -- F17 ClaudeCliClient + get_core_client switch."""
from __future__ import annotations

import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock.config import get_settings
from stock.models import (
    CLAUDE_CLI_CORE_MODEL_NAME,
    CODEX_CLI_CORE_MODEL_NAME,
    ChatMessage,
    ClaudeCliClient,
    ClaudeCliUnavailable,
    CodexCliClient,
    CodexCliUnavailable,
    CodexWithClaudeFallback,
    LLMClient,
    get_core_client,
    get_core_model,
)


def _fake_codex_subprocess(payload: str):
    """Build a subprocess.run side_effect that writes `payload` to the -o file
    referenced in argv and returns a 0-exit MagicMock. Mirrors how the real
    codex CLI emits its final-assistant message into the `-o` file.
    """
    def _side_effect(argv, **kwargs):
        out_idx = argv.index("-o") + 1
        Path(argv[out_idx]).write_text(payload, encoding="utf-8")
        return MagicMock(returncode=0, stdout="header noise", stderr="")
    return _side_effect


def _seed_settings(monkeypatch: pytest.MonkeyPatch, **kw: str) -> None:
    """Set env + force-reload Settings ignoring the on-disk .env file.

    Pydantic-settings reads .env BEFORE env vars; on a real laptop .env may
    contain CORE_LLM_BACKEND=claude_cli already (we shipped that). To make
    tests reproducible, build a fresh Settings via constructor with _env_file=None
    so on-disk .env is bypassed entirely.
    """
    monkeypatch.setenv("MINIMAX_API_KEY", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    for k, v in kw.items():
        monkeypatch.setenv(k, v)
    from stock.config import Settings

    def _fake_get_settings():
        return Settings(_env_file=None)

    monkeypatch.setattr("stock.config.get_settings", _fake_get_settings)
    monkeypatch.setattr("stock.models.get_settings", _fake_get_settings)
    get_settings.cache_clear()


def test_get_core_client_defaults_to_codex_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env override -> get_core_client returns CodexWithClaudeFallback (new default)."""
    monkeypatch.delenv("CORE_LLM_BACKEND", raising=False)
    _seed_settings(monkeypatch)
    try:
        client = get_core_client()
        assert isinstance(client, CodexWithClaudeFallback)
        assert client.provider == "codex_cli"
        # codex picks its own model by default -> get_core_model returns ""
        assert get_core_model() == ""
    finally:
        get_settings.cache_clear()


def test_get_core_client_switches_to_claude_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CORE_LLM_BACKEND=claude_cli -> get_core_client returns a pure ClaudeCliClient."""
    _seed_settings(monkeypatch, CORE_LLM_BACKEND="claude_cli")
    try:
        client = get_core_client()
        assert isinstance(client, ClaudeCliClient)
        assert client.provider == "claude_cli"
        assert get_core_model() == "claude-opus-4-7"
    finally:
        get_settings.cache_clear()


def test_get_core_client_explicit_minimax(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CORE_LLM_BACKEND=minimax -> get_core_client returns a MiniMax LLMClient."""
    _seed_settings(monkeypatch, CORE_LLM_BACKEND="minimax")
    try:
        client = get_core_client()
        assert isinstance(client, LLMClient)
        assert client.provider == "minimax"
        assert get_core_model() == "MiniMax-M2.5-highspeed"
    finally:
        get_settings.cache_clear()


def test_get_core_client_unknown_backend_falls_back_to_minimax(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Garbage value in env -> get_core_client doesn't crash; returns MiniMax."""
    _seed_settings(monkeypatch, CORE_LLM_BACKEND="banana")
    try:
        client = get_core_client()
        assert client.provider == "minimax"
    finally:
        get_settings.cache_clear()


def test_codex_cli_client_chat_happy_path(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codex exec writes final message to -o file -> chat() reads it back + logs."""
    _seed_settings(monkeypatch)
    with patch("subprocess.run", side_effect=_fake_codex_subprocess("PONG")) as mock_run:
        client = CodexCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "ping"}]
        response = client.chat(
            messages=msgs,
            model="",
            max_tokens=128,
            conn=mem_db,
            caller="test.codex_cli",
            cached_system="System block",
        )

    args, kwargs = mock_run.call_args
    argv = args[0]
    assert argv[0].lower().endswith("codex") or argv[0].lower().endswith("codex.cmd")
    assert argv[1] == "exec"
    assert "--dangerously-bypass-approvals-and-sandbox" in argv
    assert "-o" in argv  # output file flag
    # Prompt goes via stdin, not argv
    stdin_text = kwargs.get("input", "")
    assert "System block" in stdin_text and "ping" in stdin_text

    assert response.content == "PONG"
    assert response.cost_usd == 0.0
    assert response.model == CODEX_CLI_CORE_MODEL_NAME
    row = mem_db.execute(
        "SELECT provider, cost_usd FROM llm_calls WHERE caller = 'test.codex_cli'"
    ).fetchone()
    assert row == ("codex_cli", 0.0)


def test_codex_cli_client_missing_binary_raises_unavailable(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FileNotFoundError on subprocess.run -> CodexCliUnavailable."""
    _seed_settings(monkeypatch)
    with patch("subprocess.run", side_effect=FileNotFoundError("no codex")):
        client = CodexCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "x"}]
        with pytest.raises(CodexCliUnavailable):
            client.chat(
                messages=msgs, model="", max_tokens=10,
                conn=mem_db, caller="test.missing_codex",
            )


def test_codex_cli_client_timeout_raises_unavailable(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subprocess timeout -> CodexCliUnavailable so the wrapper can fall back."""
    _seed_settings(monkeypatch)
    err = subprocess.TimeoutExpired(cmd=["codex"], timeout=600)
    with patch("subprocess.run", side_effect=err):
        client = CodexCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "x"}]
        with pytest.raises(CodexCliUnavailable):
            client.chat(
                messages=msgs, model="", max_tokens=10,
                conn=mem_db, caller="test.codex_timeout",
            )


def test_codex_cli_client_nonzero_exit_raises_unavailable(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codex non-zero exit -> CodexCliUnavailable with stderr in message."""
    _seed_settings(monkeypatch)

    def _bad_run(argv, **kwargs):
        # Write empty content to the -o file so the read path doesn't fail
        # before we check returncode
        out_idx = argv.index("-o") + 1
        Path(argv[out_idx]).write_text("", encoding="utf-8")
        return MagicMock(returncode=3, stdout="", stderr="auth required")

    with patch("subprocess.run", side_effect=_bad_run):
        client = CodexCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "x"}]
        with pytest.raises(CodexCliUnavailable) as excinfo:
            client.chat(
                messages=msgs, model="", max_tokens=10,
                conn=mem_db, caller="test.codex_exit",
            )
        assert "auth required" in str(excinfo.value)


def test_codex_cli_client_empty_output_raises_unavailable(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty output from codex -> CodexCliUnavailable so we fall back rather than
    return a useless empty response to callers."""
    _seed_settings(monkeypatch)
    with patch("subprocess.run", side_effect=_fake_codex_subprocess("")):
        client = CodexCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "x"}]
        with pytest.raises(CodexCliUnavailable):
            client.chat(
                messages=msgs, model="", max_tokens=10,
                conn=mem_db, caller="test.codex_empty",
            )


def test_codex_fallback_wrapper_uses_codex_on_success(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When codex succeeds, the wrapper never invokes claude_cli."""
    _seed_settings(monkeypatch)
    wrapper = CodexWithClaudeFallback()
    codex_resp = MagicMock(content="codex ok", cost_usd=0.0, model=CODEX_CLI_CORE_MODEL_NAME)
    claude_chat = MagicMock()
    with (
        patch.object(wrapper._codex, "chat", return_value=codex_resp) as codex_chat,
        patch.object(wrapper._claude, "chat", side_effect=claude_chat),
    ):
        msgs: list[ChatMessage] = [{"role": "user", "content": "hi"}]
        response = wrapper.chat(
            messages=msgs, model="", max_tokens=10,
            conn=mem_db, caller="test.wrap_success",
        )
    codex_chat.assert_called_once()
    claude_chat.assert_not_called()
    assert response.content == "codex ok"


def test_codex_fallback_wrapper_falls_back_to_claude(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codex raising CodexCliUnavailable -> wrapper calls claude_cli, tagged caller."""
    _seed_settings(monkeypatch)
    wrapper = CodexWithClaudeFallback()
    claude_resp = MagicMock(content="claude rescue", cost_usd=0.0)
    with (
        patch.object(
            wrapper._codex, "chat", side_effect=CodexCliUnavailable("timeout"),
        ) as codex_chat,
        patch.object(wrapper._claude, "chat", return_value=claude_resp) as claude_chat,
    ):
        msgs: list[ChatMessage] = [{"role": "user", "content": "hi"}]
        response = wrapper.chat(
            messages=msgs, model="",  max_tokens=10,
            conn=mem_db, caller="test.wrap_fallback",
        )
    codex_chat.assert_called_once()
    claude_chat.assert_called_once()
    # Caller string is re-tagged so llm_calls rows show the fallback path
    assert claude_chat.call_args.kwargs["caller"].endswith(".codex_fallback_claude")
    assert response.content == "claude rescue"


def test_codex_fallback_wrapper_both_fail_propagates_claude_error(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both codex AND claude fail, the wrapper raises ClaudeCliUnavailable.

    Existing call sites already catch that and drop to MiniMax, preserving the
    final safety tier.
    """
    _seed_settings(monkeypatch)
    wrapper = CodexWithClaudeFallback()
    with (
        patch.object(
            wrapper._codex, "chat", side_effect=CodexCliUnavailable("no codex"),
        ),
        patch.object(
            wrapper._claude, "chat", side_effect=ClaudeCliUnavailable("no claude"),
        ),
    ):
        msgs: list[ChatMessage] = [{"role": "user", "content": "hi"}]
        with pytest.raises(ClaudeCliUnavailable):
            wrapper.chat(
                messages=msgs, model="", max_tokens=10,
                conn=mem_db, caller="test.wrap_both_fail",
            )


def test_claude_cli_client_chat_happy_path(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subprocess returns text on stdout -> chat() returns ChatResponse + logs to llm_calls."""
    _seed_settings(monkeypatch)
    fake_proc = MagicMock(returncode=0, stdout="OK\n", stderr="")
    with patch("subprocess.run", return_value=fake_proc) as mock_run:
        client = ClaudeCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "Say OK"}]
        response = client.chat(
            messages=msgs,
            model="claude-opus-4-7",
            max_tokens=128,
            conn=mem_db,
            caller="test.claude_cli",
            cached_system="System block",
        )

    args, kwargs = mock_run.call_args
    cmd = args[0]
    # subprocess invoked with the right shape -- bin can be 'claude' or
    # the resolved absolute path returned by shutil.which (Windows resolves
    # to .CMD); the trailing "-p" is the headless-mode flag.
    assert cmd[0].lower().endswith("claude") or cmd[0].lower().endswith("claude.cmd")
    assert cmd[1] == "-p"
    # Prompt now goes via stdin (`input=`), NOT argv -- avoids the 32 KB
    # Windows command-line cap that broke the daily-research push.
    stdin_text = kwargs.get("input", "")
    assert "System block" in stdin_text and "Say OK" in stdin_text
    # Response well-formed
    assert response.content == "OK"
    assert response.cost_usd == 0.0
    assert response.model == CLAUDE_CLI_CORE_MODEL_NAME
    # Logged to llm_calls with cost=0 and provider=claude_cli
    row = mem_db.execute(
        "SELECT provider, cost_usd FROM llm_calls WHERE caller = 'test.claude_cli'"
    ).fetchone()
    assert row == ("claude_cli", 0.0)


def test_claude_cli_client_missing_binary_raises_unavailable(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FileNotFoundError on subprocess.run -> ClaudeCliUnavailable, not raw OSError."""
    _seed_settings(monkeypatch)
    with patch("subprocess.run", side_effect=FileNotFoundError("no claude")):
        client = ClaudeCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "x"}]
        with pytest.raises(ClaudeCliUnavailable):
            client.chat(
                messages=msgs, model="claude-opus-4-7", max_tokens=10,
                conn=mem_db, caller="test.missing",
            )


def test_claude_cli_client_timeout_raises_unavailable(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subprocess timeout -> ClaudeCliUnavailable so callers can fall back cleanly."""
    _seed_settings(monkeypatch)
    err = subprocess.TimeoutExpired(cmd=["claude"], timeout=600)
    with patch("subprocess.run", side_effect=err):
        client = ClaudeCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "x"}]
        with pytest.raises(ClaudeCliUnavailable):
            client.chat(
                messages=msgs, model="claude-opus-4-7", max_tokens=10,
                conn=mem_db, caller="test.timeout",
            )


def test_claude_cli_client_nonzero_exit_raises_unavailable(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`claude -p` returning non-zero exit -> ClaudeCliUnavailable with stderr in message."""
    _seed_settings(monkeypatch)
    fake_proc = MagicMock(returncode=2, stdout="", stderr="auth error")
    with patch("subprocess.run", return_value=fake_proc):
        client = ClaudeCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "x"}]
        with pytest.raises(ClaudeCliUnavailable) as excinfo:
            client.chat(
                messages=msgs, model="claude-opus-4-7", max_tokens=10,
                conn=mem_db, caller="test.exit",
            )
        assert "auth error" in str(excinfo.value)


def test_claude_cli_client_strips_thinking_blocks(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subprocess that emits <think>...</think> still returns clean content."""
    _seed_settings(monkeypatch)
    fake_proc = MagicMock(
        returncode=0,
        stdout="<think>internal reasoning</think>\nfinal answer here",
        stderr="",
    )
    with patch("subprocess.run", return_value=fake_proc):
        client = ClaudeCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "x"}]
        response = client.chat(
            messages=msgs, model="claude-opus-4-7", max_tokens=10,
            conn=mem_db, caller="test.thinking",
        )
    assert "<think>" not in response.content
    assert "final answer here" in response.content


def test_grading_falls_back_to_minimax_when_claude_cli_unavailable(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When claude_cli backend is selected but unreachable, grading.generate_grading_note falls back to MiniMax."""
    _seed_settings(monkeypatch, CORE_LLM_BACKEND="claude_cli")

    # Seed a scored prediction so the grading window isn't empty
    cursor = mem_db.execute(
        "INSERT INTO predictions ("
        "  ticker, horizon_minutes, direction, prob_up, confidence,"
        "  rationale, key_factors_json, model_used, created_at, due_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("NVDA", 390, "up", 0.7, 0.7, "rationale", "[]", "test",
         "2026-04-29T14:00:00+00:00", "2026-04-30T21:00:00+00:00"),
    )
    pid = cursor.lastrowid
    now_iso = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (pid, 0.04, 1, 0.04, now_iso),
    )
    mem_db.commit()

    # claude_cli raises -> grading falls back to MiniMax
    cli_client = MagicMock(spec=ClaudeCliClient)
    cli_client.chat.side_effect = ClaudeCliUnavailable("no binary")

    minimax_client = MagicMock()
    minimax_client.chat.return_value = MagicMock(
        content="grading body\n\nNot financial advice.", cost_usd=0.0003,
    )

    try:
        with (
            patch("stock.grading.refresh_prices_for_all") as mock_refresh,
            patch("stock.grading.score_due"),
            patch("stock.grading.check_cost_ceiling"),
            patch("stock.grading.get_core_client", return_value=cli_client),
            patch("stock.grading.get_client", return_value=minimax_client),
        ):
            from stock.grading import (
                PriceRefreshResult,
                generate_grading_note,
            )

            mock_refresh.return_value = PriceRefreshResult(
                tickers=["NVDA"], inserted_total=1, failed=[],
            )
            note = generate_grading_note(mem_db, lookback_hours=36)
    finally:
        get_settings.cache_clear()

    cli_client.chat.assert_called_once()
    minimax_client.chat.assert_called_once()
    # Fallback caller string is logged
    assert "fallback" in minimax_client.chat.call_args.kwargs["caller"]
    assert note.cost_usd == pytest.approx(0.0003)


def test_research_core_chat_helper_falls_back(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """research._core_chat falls back to MiniMax when the primary raises ClaudeCliUnavailable."""
    _seed_settings(monkeypatch, CORE_LLM_BACKEND="claude_cli")

    cli_client = MagicMock(spec=ClaudeCliClient)
    cli_client.chat.side_effect = ClaudeCliUnavailable("no binary")
    minimax_client = MagicMock()
    minimax_client.chat.return_value = MagicMock(
        content="ok", cost_usd=0.0001, model="MiniMax-M2.5-highspeed",
        input_tokens=10, output_tokens=2,
    )

    try:
        with (
            patch("stock.research.get_core_client", return_value=cli_client),
            patch("stock.research.get_client", return_value=minimax_client),
            patch("stock.research.get_core_model", return_value="claude-opus-4-7"),
        ):
            from stock.research import _core_chat

            response = _core_chat(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=64,
                conn=mem_db,
                caller="test.research_core",
            )
    finally:
        get_settings.cache_clear()

    assert response.content == "ok"
    cli_client.chat.assert_called_once()
    minimax_client.chat.assert_called_once()
    assert "fallback" in minimax_client.chat.call_args.kwargs["caller"]
