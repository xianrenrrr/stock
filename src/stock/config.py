"""stock.config -- centralized settings loaded from environment."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    anthropic_api_key: str = ""
    # Legacy only. Runtime LLM calls are Codex CLI first; do not set these
    # unless intentionally testing the retired MiniMax client.
    minimax_api_key: str = ""
    minimax_base_url: str = ""
    stock_api_token: str = ""
    daily_cost_ceiling_usd: float = 0.50
    db_path: str = "data/stock.db"

    # WeChat push (the OpenClaw bridge endpoint that delivers daily research)
    wechat_push_url: str = ""
    wechat_push_token: str = ""
    wechat_push_field_to: str = "to"
    wechat_push_field_text: str = "text"

    # Plain SMTP email for daily action reports and automation failure alerts.
    # Gmail works with SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, and an app
    # password in SMTP_PASSWORD.
    daily_report_email_to: str = "2001liqiyangdaily@gmail.com"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "2001liqiyangdaily@gmail.com"
    smtp_starttls: bool = True

    # Daily research output language ("zh" or "en")
    research_language: str = "zh"

    # Web search backends for autonomous discovery (Tavily preferred, free 1000/mo tier)
    tavily_api_key: str = ""
    serper_api_key: str = ""
    brave_api_key: str = ""
    web_search_backend: str = ""  # explicit pin; blank = auto-select first set

    # OpenClaw auto-trigger after each WeChat push. The orchestrator spawns
    # `openclaw agent --agent <OPENCLAW_AGENT> --message ...` so the agent picks up
    # pending outbox tasks and clicks them through WeChat via computer-use.
    openclaw_auto_deliver: bool = True
    openclaw_bin: str = "openclaw"     # binary on PATH; override with full path if needed
    openclaw_agent: str = "main"        # which OpenClaw agent has the delivery skill

    # SEC EDGAR User-Agent header (required by SEC policy, free, no key).
    # Override at install time so SEC can identify the operator if a request misbehaves.
    edgar_user_agent: str = "stock-research 0.1 ops@example.com"

    # Hybrid local + Render-free architecture.
    # `local` (default): full pipeline runs
    #   (scheduler, ingest, predictions, research, GUI delivery).
    # `cloud_proxy`: passive Render-side mode -- no scheduler, no Codex/Tavily calls.
    #   Just serves /channel/* (boss dashboard) and /sync/* (local laptop pushes data here).
    stock_mode: str = "local"

    # Local laptop pushes notes/tokens to this URL every 5 min and pulls boss replies.
    # Empty = sync disabled (laptop-only mode). Set after Render deploy.
    render_sync_url: str = ""

    # Daily self-review backend. Switches who reads the daily packet:
    #   "codex_cli" (default): full autopilot -- spawn `codex exec` to make 1-3 code
    #     changes on a branch, run pytest, auto-merge to main + git push if green.
    #     Falls back to `claude -p` automatically if codex is unavailable / times out.
    #     Requires `codex login` (and `claude login` for the fallback) on this machine.
    #   "claude_cli": same autopilot but skip the codex layer; use claude directly.
    #   "claude_code": only write pipeline/daily_review_*.md, you run /improve manually
    #   "off": skip the daily-review job entirely
    self_review_backend: str = "codex_cli"

    # F17: core "thinking" backend for the user-facing flows (research, reply,
    # grading, deep-dive, health-check). Utility classifiers (intent,
    # prompt_rewriter, thesis, discover, features) also route through this
    # helper so small utility calls do not silently use a different provider.
    #   "codex_cli" (default): every core call spawns `codex exec` locally,
    #                          with claude_cli as automatic fallback on
    #                          timeout / missing binary. $0 metered.
    #   "claude_cli"         : every core call spawns `claude -p` locally only.
    #   "minimax"            : legacy value; ignored and routed to codex_cli.
    core_llm_backend: str = "codex_cli"
    core_claude_model: str = "claude-opus-4-7"
    # Blank lets codex pick its own configured default (currently gpt-5.5).
    # Override in .env if you want to pin a specific codex-supported model.
    core_codex_model: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
