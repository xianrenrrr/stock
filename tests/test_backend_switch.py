"""tests.test_backend_switch -- F17 ClaudeCliClient + get_core_client switch."""
from __future__ import annotations

import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock import models as stock_models
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
    FastUtilityClient,
    _codex_circuit_reset,
    _is_codex_circuit_open,
    get_core_client,
    get_core_model,
    get_utility_client,
    get_utility_model,
)


@pytest.fixture(autouse=True)
def _clear_codex_circuit() -> None:
    """Every test starts with a clean circuit-breaker so prior hits don't leak."""
    _codex_circuit_reset()
    yield
    _codex_circuit_reset()


def _fake_codex_subprocess_with_stderr(
    payload: str, stderr: str = "", returncode: int = 0,
):
    """Like _fake_codex_subprocess but with configurable stderr + exit code so
    tests can simulate codex's credit-limit emissions on either channel."""
    def _side_effect(argv, **kwargs):
        out_idx = argv.index("-o") + 1
        Path(argv[out_idx]).write_text(payload, encoding="utf-8")
        return MagicMock(returncode=returncode, stdout="header noise", stderr=stderr)
    return _side_effect


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


def test_get_core_client_defaults_to_claude_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env override -> claude_cli + Opus 4.8 (Fable banned 2026-06-14)."""
    monkeypatch.delenv("CORE_LLM_BACKEND", raising=False)
    _seed_settings(monkeypatch)
    try:
        client = get_core_client()
        assert isinstance(client, ClaudeCliClient)
        assert client.provider == "claude_cli"
        assert get_core_model() == "claude-opus-4-8"
    finally:
        get_settings.cache_clear()


def test_get_core_client_switches_to_codex_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CORE_LLM_BACKEND=codex_cli -> codex with claude fallback (previous default)."""
    _seed_settings(monkeypatch, CORE_LLM_BACKEND="codex_cli")
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
        assert get_core_model() == "claude-opus-4-8"
    finally:
        get_settings.cache_clear()


def test_get_core_client_legacy_minimax_routes_to_codex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CORE_LLM_BACKEND=minimax is legacy and now routes to Codex."""
    _seed_settings(monkeypatch, CORE_LLM_BACKEND="minimax")
    try:
        client = get_core_client()
        assert isinstance(client, CodexWithClaudeFallback)
        assert client.provider == "codex_cli"
        assert get_core_model() == ""
    finally:
        get_settings.cache_clear()


def test_get_core_client_unknown_backend_falls_back_to_codex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Garbage value in env -> get_core_client doesn't crash; returns Codex."""
    _seed_settings(monkeypatch, CORE_LLM_BACKEND="banana")
    try:
        client = get_core_client()
        assert client.provider == "codex_cli"
    finally:
        get_settings.cache_clear()


def test_get_utility_client_defaults_to_fast_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Utility fast lane -> ClaudeCliClient + haiku model, regardless of core backend."""
    _seed_settings(monkeypatch)  # core stays codex_cli default
    try:
        client = get_utility_client()
        assert isinstance(client, FastUtilityClient)
        assert client.provider == "claude_cli"
        assert get_utility_model() == "claude-haiku-4-5-20251001"
    finally:
        get_settings.cache_clear()


def test_utility_fast_lane_falls_back_to_core_when_claude_fails(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the fast haiku call fails, the utility lane drops to the core backend.

    Guarantees the fast lane is never a single point of failure -- a utility
    call always has a backstop, same as the core path.
    """
    _seed_settings(monkeypatch)
    util = FastUtilityClient()
    rescue = MagicMock(content="core rescue", cost_usd=0.0)
    fake_core = MagicMock()
    fake_core.chat.return_value = rescue
    with (
        patch.object(
            util._fast, "chat", side_effect=ClaudeCliUnavailable("haiku down"),
        ),
        patch("stock.models.get_core_client", return_value=fake_core),
        patch("stock.models.get_core_model", return_value=""),
    ):
        msgs: list[ChatMessage] = [{"role": "user", "content": "classify"}]
        resp = util.chat(
            messages=msgs, model="claude-haiku-4-5-20251001", max_tokens=10,
            conn=mem_db, caller="features.extract_single",
        )
    assert resp.content == "core rescue"
    fake_core.chat.assert_called_once()
    assert fake_core.chat.call_args.kwargs["caller"].endswith(".utility_fallback_core")


def test_get_utility_client_blank_falls_back_to_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank utility_claude_model -> utility lane reuses the active core backend."""
    _seed_settings(monkeypatch, UTILITY_CLAUDE_MODEL="", CORE_LLM_BACKEND="claude_cli")
    try:
        client = get_utility_client()
        # Falls back to core, which is claude_cli here -> a pure ClaudeCliClient.
        assert isinstance(client, ClaudeCliClient)
        assert get_utility_model() == "claude-opus-4-8"  # core model, not haiku
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
    args, _kwargs = mock_run.call_args
    cmd = args[0]
    effort_idx = cmd.index("-c") + 1
    assert cmd[effort_idx] == 'model_reasoning_effort="high"'
    row = mem_db.execute(
        "SELECT provider, cost_usd FROM llm_calls WHERE caller = 'test.codex_cli'"
    ).fetchone()
    assert row == ("codex_cli", 0.0)


def test_codex_cli_prediction_uses_prediction_reasoning_effort(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prediction callers use the max reasoning lane for Codex."""
    _seed_settings(monkeypatch)
    with patch("subprocess.run", side_effect=_fake_codex_subprocess("PONG")) as mock_run:
        client = CodexCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "predict"}]
        client.chat(
            messages=msgs,
            model="",
            max_tokens=128,
            conn=mem_db,
            caller="predict.predict_ticker",
        )

    args, _kwargs = mock_run.call_args
    cmd = args[0]
    effort_idx = cmd.index("-c") + 1
    assert cmd[effort_idx] == 'model_reasoning_effort="max"'


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
    effort_idx = cmd.index("--effort") + 1
    assert cmd[effort_idx] == "high"
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


def test_claude_cli_prediction_uses_prediction_reasoning_effort(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prediction callers use the max reasoning lane for Claude."""
    _seed_settings(monkeypatch)
    fake_proc = MagicMock(returncode=0, stdout="OK\n", stderr="")
    with patch("subprocess.run", return_value=fake_proc) as mock_run:
        client = ClaudeCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "predict"}]
        client.chat(
            messages=msgs,
            model="claude-opus-4-8",
            max_tokens=128,
            conn=mem_db,
            caller="predict.predict_ticker",
        )

    args, _kwargs = mock_run.call_args
    cmd = args[0]
    effort_idx = cmd.index("--effort") + 1
    assert cmd[effort_idx] == "max"


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


def test_grading_fails_closed_when_claude_cli_unavailable(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When claude_cli is unreachable, grading does not fall back to MiniMax."""
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

    cli_client = MagicMock(spec=ClaudeCliClient)
    cli_client.chat.side_effect = ClaudeCliUnavailable("no binary")

    try:
        with (
            patch("stock.grading.refresh_prices_for_all") as mock_refresh,
            patch("stock.grading.score_due"),
            patch("stock.grading.check_cost_ceiling"),
            patch("stock.grading.get_core_client", return_value=cli_client),
        ):
            from stock.grading import (
                PriceRefreshResult,
                generate_grading_note,
            )

            mock_refresh.return_value = PriceRefreshResult(
                tickers=["NVDA"], inserted_total=1, failed=[],
            )
            with pytest.raises(ClaudeCliUnavailable):
                generate_grading_note(mem_db, lookback_hours=36)
    finally:
        get_settings.cache_clear()

    cli_client.chat.assert_called_once()


def test_research_core_chat_helper_fails_closed(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """research._core_chat does not fall back to MiniMax."""
    _seed_settings(monkeypatch, CORE_LLM_BACKEND="claude_cli")

    cli_client = MagicMock(spec=ClaudeCliClient)
    cli_client.chat.side_effect = ClaudeCliUnavailable("no binary")

    try:
        with (
            patch("stock.research.get_core_client", return_value=cli_client),
            patch("stock.research.get_core_model", return_value="claude-opus-4-7"),
        ):
            from stock.research import _core_chat

            with pytest.raises(ClaudeCliUnavailable):
                _core_chat(
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=64,
                    conn=mem_db,
                    caller="test.research_core",
                )
    finally:
        get_settings.cache_clear()

    cli_client.chat.assert_called_once()


# ---------------------------------------------------------------------------
# F17c: credit-limit detection + circuit breaker
# ---------------------------------------------------------------------------


def test_codex_credit_limit_in_stderr_raises_unavailable(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codex exits non-zero with 'rate limit' in stderr -> CodexCliUnavailable
    AND the breaker records a hit."""
    _seed_settings(monkeypatch)
    side = _fake_codex_subprocess_with_stderr(
        payload="",
        stderr="Error: rate limit reached on your ChatGPT plan",
        returncode=1,
    )
    with patch("subprocess.run", side_effect=side):
        client = CodexCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "x"}]
        with pytest.raises(CodexCliUnavailable) as excinfo:
            client.chat(
                messages=msgs, model="", max_tokens=10,
                conn=mem_db, caller="test.credit_stderr",
            )
        assert "credit/usage limit" in str(excinfo.value)
    # One hit recorded -> breaker stays closed (threshold is 2)
    assert _is_codex_circuit_open() is False


def test_codex_credit_limit_in_content_raises_unavailable(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codex exits 0 but writes a rate-limit apology to the -o file ->
    still detected as credit-limit, raises CodexCliUnavailable."""
    _seed_settings(monkeypatch)
    side = _fake_codex_subprocess_with_stderr(
        payload="I'm sorry, you have exceeded your weekly limit on this plan.",
        stderr="",
        returncode=0,
    )
    with patch("subprocess.run", side_effect=side):
        client = CodexCliClient()
        msgs: list[ChatMessage] = [{"role": "user", "content": "x"}]
        with pytest.raises(CodexCliUnavailable) as excinfo:
            client.chat(
                messages=msgs, model="", max_tokens=10,
                conn=mem_db, caller="test.credit_content",
            )
        assert "credit/usage limit" in str(excinfo.value)


def test_codex_circuit_opens_after_threshold_hits(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two credit-limit hits within the window open the breaker."""
    _seed_settings(monkeypatch)
    side = _fake_codex_subprocess_with_stderr(
        payload="", stderr="rate limit exceeded", returncode=1,
    )
    client = CodexCliClient()
    msgs: list[ChatMessage] = [{"role": "user", "content": "x"}]
    with patch("subprocess.run", side_effect=side):
        for i in range(stock_models.CODEX_CIRCUIT_HITS_THRESHOLD):
            with pytest.raises(CodexCliUnavailable):
                client.chat(
                    messages=msgs, model="", max_tokens=10,
                    conn=mem_db, caller=f"test.threshold_{i}",
                )
    assert _is_codex_circuit_open() is True


def test_codex_circuit_open_routes_directly_to_claude(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the breaker is open, the wrapper bypasses codex entirely and goes
    straight to claude_cli with a distinguishable caller suffix."""
    _seed_settings(monkeypatch)
    # Force the circuit open by setting the deadline in the future
    stock_models._codex_circuit_open_until = time.time() + 60.0

    wrapper = CodexWithClaudeFallback()
    claude_resp = MagicMock(content="claude rescue", cost_usd=0.0)
    with (
        patch.object(wrapper._codex, "chat") as codex_chat,
        patch.object(wrapper._claude, "chat", return_value=claude_resp) as claude_chat,
    ):
        msgs: list[ChatMessage] = [{"role": "user", "content": "hi"}]
        response = wrapper.chat(
            messages=msgs, model="", max_tokens=10,
            conn=mem_db, caller="test.circuit_open",
        )
    codex_chat.assert_not_called()
    claude_chat.assert_called_once()
    assert claude_chat.call_args.kwargs["caller"].endswith(".codex_circuit_open_claude")
    assert response.content == "claude rescue"


def test_codex_circuit_closes_after_cooldown(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the cooldown elapses, the wrapper attempts codex again."""
    _seed_settings(monkeypatch)
    # Open the circuit, then advance time past the cooldown
    stock_models._codex_circuit_open_until = time.time() + 0.001
    time.sleep(0.005)
    assert _is_codex_circuit_open() is False

    wrapper = CodexWithClaudeFallback()
    codex_resp = MagicMock(content="codex back online", cost_usd=0.0)
    with (
        patch.object(wrapper._codex, "chat", return_value=codex_resp) as codex_chat,
        patch.object(wrapper._claude, "chat") as claude_chat,
    ):
        msgs: list[ChatMessage] = [{"role": "user", "content": "hi"}]
        response = wrapper.chat(
            messages=msgs, model="", max_tokens=10,
            conn=mem_db, caller="test.circuit_closed",
        )
    codex_chat.assert_called_once()
    claude_chat.assert_not_called()
    assert response.content == "codex back online"
