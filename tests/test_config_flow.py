"""Tests for the Plenitude config flow."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant

from custom_components.plenitude.api.kraken import (
    AccountRef,
    KrakenAuthError,
    KrakenSession,
    ViewerInfo,
)
from custom_components.plenitude.api.portal import PortalSession
from custom_components.plenitude.const import DOMAIN
from custom_components.plenitude.models import ContractTariffs, HalfHourPeriod


def _kraken_session() -> KrakenSession:
    return KrakenSession(
        access_token="tok",
        access_token_expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        refresh_token="rt",
        refresh_token_expires_in_seconds=1209600,
        account_user_id="999999",
    )


def _portal_session() -> PortalSession:
    return PortalSession(
        cookie_name="__Secure-better-auth.session_token",
        cookie_value="c",
        expires_at=datetime.now(tz=UTC) + timedelta(hours=23),
    )


def _viewer() -> ViewerInfo:
    return ViewerInfo(
        user_id="999999",
        email="test@example.com",
        given_name="Test",
        accounts=(AccountRef(number="A-TEST0000", status="ACTIVE"),),
    )


def _tariffs() -> ContractTariffs:
    return ContractTariffs(
        hp_eur_per_kwh=0.21114,
        hc_eur_per_kwh=0.16614,
        subscription_eur_per_month=17.66790,
        hp_periods=(HalfHourPeriod("07:30:00", "23:30:00"),),
        hc_periods=(HalfHourPeriod("00:00:00", "07:30:00"),),
        valid_from=datetime(2025, 5, 25, tzinfo=UTC),
        valid_to=None,
    )


@pytest.mark.asyncio
async def test_config_flow_user_step_proceeds_to_tariffs(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """User step with valid credentials moves to the tariffs preview step."""
    with (
        patch(
            "custom_components.plenitude.config_flow.PlenitudeKrakenClient.login",
            new=AsyncMock(return_value=_kraken_session()),
        ),
        patch(
            "custom_components.plenitude.config_flow.PlenitudeKrakenClient.get_viewer",
            new=AsyncMock(return_value=_viewer()),
        ),
        patch(
            "custom_components.plenitude.config_flow.PlenitudePortalClient.login",
            new=AsyncMock(return_value=_portal_session()),
        ),
        patch(
            "custom_components.plenitude.config_flow.PlenitudePortalClient.fetch_contract",
            new=AsyncMock(return_value=_tariffs()),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"email": "test@example.com", "password": "secret"},
        )
        assert result2["type"] == data_entry_flow.FlowResultType.FORM
        assert result2["step_id"] == "tariffs"


@pytest.mark.asyncio
async def test_config_flow_user_step_shows_invalid_auth_error(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """KrakenAuthError on login surfaces as invalid_auth error."""
    with patch(
        "custom_components.plenitude.config_flow.PlenitudeKrakenClient.login",
        new=AsyncMock(side_effect=KrakenAuthError("bad")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"email": "test@example.com", "password": "wrong"},
        )

    assert result2["type"] == data_entry_flow.FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}
