"""Persistent state for the add-on (refresh tokens, cookies)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_STATE_PATH = Path("/data/state.json")


@dataclass(slots=True, frozen=True)
class PersistedState:
    """State that survives add-on restarts. Stored in /data/state.json."""

    kraken_refresh_token: str
    kraken_refresh_token_expires_at: datetime
    portal_cookie_name: str
    portal_cookie_value: str
    portal_cookie_expires_at: datetime
    site_id: str


def load_state(state_path: Path = DEFAULT_STATE_PATH) -> PersistedState | None:
    """Read persisted state, or return None if the file doesn't exist."""
    if not state_path.exists():
        return None
    raw = json.loads(state_path.read_text())
    return PersistedState(
        kraken_refresh_token=raw["kraken_refresh_token"],
        kraken_refresh_token_expires_at=datetime.fromisoformat(
            raw["kraken_refresh_token_expires_at"]
        ),
        portal_cookie_name=raw["portal_cookie_name"],
        portal_cookie_value=raw["portal_cookie_value"],
        portal_cookie_expires_at=datetime.fromisoformat(
            raw["portal_cookie_expires_at"]
        ),
        site_id=raw["site_id"],
    )


def save_state(state: PersistedState, state_path: Path = DEFAULT_STATE_PATH) -> None:
    """Persist state atomically (write to temp file, then rename)."""
    payload = {
        **asdict(state),
        "kraken_refresh_token_expires_at": (
            state.kraken_refresh_token_expires_at.isoformat()
        ),
        "portal_cookie_expires_at": state.portal_cookie_expires_at.isoformat(),
    }
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(state_path)
