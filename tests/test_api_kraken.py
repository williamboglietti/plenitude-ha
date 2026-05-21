"""Tests for the Kraken GraphQL client."""
from __future__ import annotations

import json
from pathlib import Path

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.plenitude.api.kraken import (
    KrakenAuthError,
    KrakenError,
    KrakenSession,
    PlenitudeKrakenClient,
)
from custom_components.plenitude.const import KRAKEN_GRAPHQL_URL


@pytest.mark.asyncio
async def test_login_returns_session(fixtures_dir: Path) -> None:
    """login() should call obtainKrakenToken and return a KrakenSession."""
    response = json.loads((fixtures_dir / "kraken_login_response.json").read_text())

    with aioresponses() as mocked:
        mocked.post(KRAKEN_GRAPHQL_URL, payload=response)

        async with aiohttp.ClientSession() as http:
            client = PlenitudeKrakenClient(http)
            session = await client.login("test@example.com", "secret-password")

    assert isinstance(session, KrakenSession)
    assert session.access_token.startswith("eyJ")
    assert session.refresh_token == "rt_test_abc123def456"
    assert session.access_token_expires_at.timestamp() == 1779335505
    assert session.refresh_token_expires_in_seconds == 1209600
