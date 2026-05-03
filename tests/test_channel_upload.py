"""tests.test_channel_upload -- F18 POST /channel/api/upload_image endpoint."""
from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock import channel
from stock.config import get_settings
from stock.db import _ensure_schema


@pytest.fixture
def thread_safe_db() -> Generator[sqlite3.Connection, None, None]:
    """In-memory DB connection that TestClient's worker thread can also use."""
    import sqlite_vec

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    _ensure_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


def _make_test_app(conn: sqlite3.Connection) -> FastAPI:
    """Build a FastAPI app with channel router + DB override yielding the test conn."""
    app = FastAPI()
    app.add_exception_handler(channel.ChannelHTTPError, channel.channel_exception_handler)
    app.include_router(channel.create_router())

    def _override_conn() -> Generator[sqlite3.Connection, None, None]:
        yield conn

    app.dependency_overrides[channel.get_db_conn] = _override_conn
    return app


def _mint_token(thread_safe_db: sqlite3.Connection, recipient: str = "richard") -> str:
    return channel.mint_token(thread_safe_db, recipient)


def _png_bytes() -> bytes:
    """Tiny valid 1x1 PNG."""
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect channel upload + feedback paths to tmp_path so tests don't pollute data/."""
    uploads = tmp_path / "uploads"
    feedback = tmp_path / "wechat_feedback.md"
    monkeypatch.setattr(channel, "UPLOAD_DIR", str(uploads))
    monkeypatch.setattr(channel, "FEEDBACK_PATH", str(feedback))
    return tmp_path


def test_upload_requires_auth(thread_safe_db: sqlite3.Connection, upload_dir: Path) -> None:
    """No bearer token -> 401."""
    client = TestClient(_make_test_app(thread_safe_db))
    r = client.post(
        "/channel/api/upload_image",
        files={"image": ("x.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 401


def test_upload_rejects_unsupported_extension(
    thread_safe_db: sqlite3.Connection, upload_dir: Path,
) -> None:
    """`.bmp` -> 400 unsupported_extension."""
    token = _mint_token(thread_safe_db)
    client = TestClient(_make_test_app(thread_safe_db))
    r = client.post(
        "/channel/api/upload_image",
        files={"image": ("x.bmp", b"BM", "image/bmp")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_extension"


def test_upload_rejects_oversize(
    thread_safe_db: sqlite3.Connection, upload_dir: Path,
) -> None:
    """> 8MB upload -> 413 image_too_large."""
    token = _mint_token(thread_safe_db)
    huge = b"\x89PNG\r\n\x1a\n" + b"x" * (9 * 1024 * 1024)
    client = TestClient(_make_test_app(thread_safe_db))
    r = client.post(
        "/channel/api/upload_image",
        files={"image": ("big.png", huge, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 413
    assert r.json()["error"] == "image_too_large"


def test_upload_rejects_empty_file(
    thread_safe_db: sqlite3.Connection, upload_dir: Path,
) -> None:
    """Zero-byte upload -> 400 empty_image."""
    token = _mint_token(thread_safe_db)
    client = TestClient(_make_test_app(thread_safe_db))
    r = client.post(
        "/channel/api/upload_image",
        files={"image": ("empty.png", b"", "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "empty_image"


def test_upload_happy_path_persists_file_and_feedback(
    thread_safe_db: sqlite3.Connection, upload_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid PNG -> file saved, vision extraction inlined, feedback file appended."""
    token = _mint_token(thread_safe_db, recipient="richard")
    fake_extraction = MagicMock(
        description="A chart of NVDA showing breakout.",
        extracted_text="NVDA 152.45",
        ticker_mentions=["NVDA"],
        suspected_topic="NVDA breakout",
        user_intent="question",
        backend="anthropic",
        cost_usd=0.012,
        duration_ms=1200,
    )

    with (
        patch("stock.vision.extract_image_info", return_value=fake_extraction),
        patch("stock.vision.format_extraction_as_feedback",
              return_value="[image] x.png\n[summary] A chart of NVDA showing breakout."),
    ):
        client = TestClient(_make_test_app(thread_safe_db))
        r = client.post(
            "/channel/api/upload_image",
            files={"image": ("test.png", _png_bytes(), "image/png")},
            data={"caption": "what do you think"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["backend"] == "anthropic"
    assert body["ticker_mentions"] == ["NVDA"]
    assert body["user_intent"] == "question"
    assert body["filename"].endswith("_richard.png")

    # File on disk
    saved = list((upload_dir / "uploads").iterdir())
    assert len(saved) == 1
    assert saved[0].read_bytes() == _png_bytes()

    # Feedback markdown appended with channel_image source marker
    fb = (upload_dir / "wechat_feedback.md").read_text(encoding="utf-8")
    assert "**source**: channel_image" in fb
    assert "**vision_backend**: anthropic" in fb
    assert "richard" in fb

    # Conversations table row written
    convs = thread_safe_db.execute(
        "SELECT recipient, direction FROM conversations WHERE recipient = 'richard'"
    ).fetchall()
    assert len(convs) >= 1
    assert convs[0][1] == "inbound"


def test_upload_safe_filename_strips_dangerous_chars(
    thread_safe_db: sqlite3.Connection, upload_dir: Path,
) -> None:
    """Recipient with slashes / spaces -> sanitized in saved filename."""
    token = _mint_token(thread_safe_db, recipient="../bad name")
    fake_extraction = MagicMock(
        description="x", extracted_text="", ticker_mentions=[],
        suspected_topic="", user_intent="unknown",
        backend="stub", cost_usd=0.0, duration_ms=0,
    )
    with patch("stock.vision.extract_image_info", return_value=fake_extraction), \
         patch("stock.vision.format_extraction_as_feedback", return_value="[image] x"):
        client = TestClient(_make_test_app(thread_safe_db))
        r = client.post(
            "/channel/api/upload_image",
            files={"image": ("x.png", _png_bytes(), "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert r.status_code == 200
    saved = list((upload_dir / "uploads").iterdir())
    name = saved[0].name
    assert ".." not in name
    assert "/" not in name and "\\" not in name
    assert " " not in name
