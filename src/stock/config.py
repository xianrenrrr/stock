"""stock.config -- centralized settings loaded from environment."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    anthropic_api_key: str = ""
    minimax_api_key: str = ""
    minimax_base_url: str = ""  # override if api.minimaxi.com is blocked / failing
    stock_api_token: str = ""
    daily_cost_ceiling_usd: float = 0.50
    db_path: str = "data/stock.db"

    # WeChat push (the OpenClaw bridge endpoint that delivers daily research)
    wechat_push_url: str = ""
    wechat_push_token: str = ""
    wechat_push_field_to: str = "to"
    wechat_push_field_text: str = "text"

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
