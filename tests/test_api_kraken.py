"""Tests for the Kraken GraphQL client."""
from __future__ import annotations

import json
from pathlib import Path

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.plenitude.api.kraken import (
    KrakenAuthError,
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


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(fixtures_dir: Path) -> None:
    """refresh() should call obtainKrakenToken with refreshToken input and return a new session."""
    response = json.loads((fixtures_dir / "kraken_refresh_response.json").read_text())

    with aioresponses() as mocked:
        mocked.post(KRAKEN_GRAPHQL_URL, payload=response)

        async with aiohttp.ClientSession() as http:
            client = PlenitudeKrakenClient(http)
            new_session = await client.refresh("rt_old_token")

    assert new_session.access_token != ""
    assert new_session.refresh_token == "rt_test_xyz789uvw321"  # rotation
    assert new_session.access_token_expires_at.timestamp() == 1779340000


@pytest.mark.asyncio
async def test_refresh_raises_on_invalid_token() -> None:
    """refresh() should raise KrakenAuthError on an invalid refresh token."""
    error_response = {
        "errors": [
            {
                "message": "Invalid refresh token.",
                "extensions": {"errorCode": "KT-CT-1134", "errorType": "VALIDATION"},
            }
        ],
        "data": {"obtainKrakenToken": None},
    }

    with aioresponses() as mocked:
        mocked.post(KRAKEN_GRAPHQL_URL, payload=error_response)

        async with aiohttp.ClientSession() as http:
            client = PlenitudeKrakenClient(http)
            with pytest.raises(KrakenAuthError):
                await client.refresh("rt_bad")
