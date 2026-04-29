"""tests.test_config -- verify Settings loads correctly from environment."""
from __future__ import annotations

import pytest

from stock.config import Settings, get_settings


class TestSettings:
    def test_settings_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings picks up values from environment variables."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("MINIMAX_API_KEY", "mm-test")
        monkeypatch.setenv("STOCK_API_TOKEN", "tok-test")
        monkeypatch.setenv("DAILY_COST_CEILING_USD", "2.50")
        monkeypatch.setenv("DB_PATH", "/tmp/test.db")

        s = Settings()
        assert s.anthropic_api_key == "sk-ant-test"
        assert s.minimax_api_key == "mm-test"
        assert s.stock_api_token == "tok-test"
        assert s.daily_cost_ceiling_usd == 2.50
        assert s.db_path == "/tmp/test.db"

    def test_settings_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings uses correct defaults when env vars and .env are absent."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        monkeypatch.delenv("STOCK_API_TOKEN", raising=False)
        monkeypatch.delenv("DAILY_COST_CEILING_USD", raising=False)
        monkeypatch.delenv("DB_PATH", raising=False)

        # Disable .env loading so the project's real .env doesn't leak into the test
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.anthropic_api_key == ""
        assert s.minimax_api_key == ""
        assert s.stock_api_token == ""
        assert s.daily_cost_ceiling_usd == 0.50
        assert s.db_path == "data/stock.db"

    def test_get_settings_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_settings returns the same cached instance on repeated calls."""
        get_settings.cache_clear()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "cached-test")
        first = get_settings()
        second = get_settings()
        assert first is second
        get_settings.cache_clear()
