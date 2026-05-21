"""Tests for the Plenitude portal HTTP client."""
from __future__ import annotations

from pathlib import Path

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.plenitude.api.portal import (
    PlenitudePortalClient,
    PortalAuthError,
    PortalSession,
)
from custom_components.plenitude.const import PORTAL_BASE_URL
from custom_components.plenitude.models import ContractTariffs


@pytest.mark.asyncio
async def test_login_scrapes_hash_and_captures_session_cookie(fixtures_dir: Path) -> None:
    """login() scrapes next-action hash from /auth/connexion then POSTs the Server Action."""
    login_page_html = (fixtures_dir / "portal_login_page.html").read_text(encoding="utf-8")

    with aioresponses() as mocked:
        # First: GET /auth/connexion -> returns the login page with hashes
        mocked.get(f"{PORTAL_BASE_URL}/auth/connexion", status=200, body=login_page_html)

        # Then: POST /auth/connexion -> returns Set-Cookie
        # (aioresponses matches on URL only, it doesn't inspect the body)
        mocked.post(
            f"{PORTAL_BASE_URL}/auth/connexion",
            status=200,
            headers={
                "Set-Cookie": (
                    "__Secure-better-auth.session_token=WRWq8m2muz8T0rUF3mtIFkV7Y; "
                    "Path=/; Expires=Fri, 22 May 2026 01:42:59 GMT; "
                    "Max-Age=86400; Secure; HttpOnly; SameSite=lax"
                )
            },
            body="0:[{\"status\":\"complete\"},\"$K1\"]",
        )

        async with aiohttp.ClientSession() as http:
            client = PlenitudePortalClient(http)
            session = await client.login("test@example.com", "secret")

    assert isinstance(session, PortalSession)
    assert session.cookie_name == "__Secure-better-auth.session_token"
    assert session.cookie_value == "WRWq8m2muz8T0rUF3mtIFkV7Y"


@pytest.mark.asyncio
async def test_login_raises_if_action_hash_not_in_page(fixtures_dir: Path) -> None:
    """login() raises PortalAuthError if scraping the action hash fails."""
    with aioresponses() as mocked:
        mocked.get(
            f"{PORTAL_BASE_URL}/auth/connexion",
            status=200,
            body="<html><body>unrelated</body></html>",
        )

        async with aiohttp.ClientSession() as http:
            client = PlenitudePortalClient(http)
            with pytest.raises(PortalAuthError):
                await client.login("test@example.com", "secret")


@pytest.mark.asyncio
async def test_login_raises_when_no_session_cookie_set(fixtures_dir: Path) -> None:
    """login() raises PortalAuthError when the POST response sets no session cookie."""
    login_page_html = (fixtures_dir / "portal_login_page.html").read_text(encoding="utf-8")

    with aioresponses() as mocked:
        mocked.get(f"{PORTAL_BASE_URL}/auth/connexion", status=200, body=login_page_html)
        mocked.post(
            f"{PORTAL_BASE_URL}/auth/connexion",
            status=200,
            headers={},  # no Set-Cookie -> invalid credentials inferred
            body="error",
        )

        async with aiohttp.ClientSession() as http:
            client = PlenitudePortalClient(http)
            with pytest.raises(PortalAuthError):
                await client.login("test@example.com", "wrong")


@pytest.mark.asyncio
async def test_fetch_contract_returns_tariffs(
    fixtures_dir: Path, portal_session: PortalSession
) -> None:
    """fetch_contract() returns parsed ContractTariffs from the /contrat page."""
    html_text = (fixtures_dir / "portal_contract_page.html").read_text(encoding="utf-8")

    with aioresponses() as mocked:
        mocked.get(f"{PORTAL_BASE_URL}/contrat", status=200, body=html_text)

        async with aiohttp.ClientSession() as http:
            client = PlenitudePortalClient(http)
            tariffs = await client.fetch_contract(portal_session)

    assert isinstance(tariffs, ContractTariffs)
    assert tariffs.hp_eur_per_kwh > 0.0
    assert tariffs.hc_eur_per_kwh > 0.0
    assert tariffs.subscription_eur_per_month > 0.0


@pytest.mark.asyncio
async def test_fetch_contract_raises_on_redirect(portal_session: PortalSession) -> None:
    """fetch_contract() raises PortalAuthError if the page redirects to login."""
    with aioresponses() as mocked:
        mocked.get(
            f"{PORTAL_BASE_URL}/contrat",
            status=307,
            headers={"Location": "/auth/connexion"},
        )

        async with aiohttp.ClientSession() as http:
            client = PlenitudePortalClient(http)
            with pytest.raises(PortalAuthError):
                await client.fetch_contract(portal_session)
