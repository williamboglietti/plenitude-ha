"""Shared pytest fixtures."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the fixtures directory."""
    return _FIXTURES_DIR


@pytest.fixture
def load_fixture(fixtures_dir: Path) -> Callable[[str], str]:
    """Return a function to load a fixture file as text."""

    def _load(name: str) -> str:
        return (fixtures_dir / name).read_text(encoding="utf-8")

    return _load


from custom_components.plenitude.api.portal import PortalSession  # noqa: E402


@pytest.fixture
def portal_session() -> PortalSession:
    """A valid PortalSession for tests."""
    return PortalSession(
        cookie_name="__Secure-better-auth.session_token",
        cookie_value="test-cookie-value",
        expires_at=datetime.now(tz=UTC) + timedelta(hours=23),
    )
