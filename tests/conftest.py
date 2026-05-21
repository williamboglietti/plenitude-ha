"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def load_fixture(fixtures_dir: Path):
    """Return a function to load a fixture file as text."""

    def _load(name: str) -> str:
        return (fixtures_dir / name).read_text(encoding="utf-8")

    return _load
