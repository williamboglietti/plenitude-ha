"""Tests for the persistent state store."""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "addon" / "plenitude2mqtt"))

from service.state_store import PersistedState, load_state, save_state


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    original = PersistedState(
        kraken_refresh_token="rt_abc",
        kraken_refresh_token_expires_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        portal_cookie_name="__Secure-better-auth.session_token",
        portal_cookie_value="cookie_xyz",
        portal_cookie_expires_at=datetime(2026, 5, 23, 0, 0, tzinfo=UTC),
        site_id="A-TEST0000",
    )

    save_state(original, state_file)
    loaded = load_state(state_file)

    assert loaded == original


def test_load_state_returns_none_when_file_missing(tmp_path: Path) -> None:
    state_file = tmp_path / "nonexistent.json"
    assert load_state(state_file) is None
