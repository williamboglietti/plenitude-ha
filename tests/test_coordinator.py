"""Tests for PlenitudeCoordinator."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.plenitude.api.kraken import KrakenAuthError, KrakenSession
from custom_components.plenitude.api.portal import PortalSession
from custom_components.plenitude.coordinator import PlenitudeCoordinator, PlenitudeData
from custom_components.plenitude.models import (
    ConsumptionInterval,
    ConsumptionSnapshot,
    ContractTariffs,
    HalfHourPeriod,
)


def _make_kraken_session() -> KrakenSession:
    return KrakenSession(
        access_token="access_tok",
        access_token_expires_at=datetime.now(tz=UTC) + timedelta(minutes=55),
        refresh_token="rt_tok",
        refresh_token_expires_in_seconds=1209600,
        account_user_id="999999",
    )


def _make_portal_session() -> PortalSession:
    return PortalSession(
        cookie_name="__Secure-better-auth.session_token",
        cookie_value="cookie_val",
        expires_at=datetime.now(tz=UTC) + timedelta(hours=23),
    )


def _make_tariffs() -> ContractTariffs:
    return ContractTariffs(
        hp_eur_per_kwh=0.21114,
        hc_eur_per_kwh=0.16614,
        subscription_eur_per_month=17.66790,
        hp_periods=(HalfHourPeriod("07:30:00", "23:30:00"),),
        hc_periods=(HalfHourPeriod("00:00:00", "07:30:00"),),
        valid_from=datetime(2025, 5, 25, tzinfo=UTC),
        valid_to=None,
    )


def _make_snapshot() -> ConsumptionSnapshot:
    return ConsumptionSnapshot(
        site_id="A-TEST0000",
        intervals=(
            ConsumptionInterval(
                start=datetime(2026, 4, 29, 22, 0, tzinfo=UTC),
                end=datetime(2026, 4, 29, 22, 30, tzinfo=UTC),
                kwh_total=1.5,
                kwh_hp=1.0,
                kwh_hc=0.5,
            ),
        ),
        last_reading_at=datetime(2026, 4, 29, 22, 30, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_coordinator_returns_plenitude_data() -> None:
    """First refresh returns PlenitudeData containing snapshot + tariffs."""
    hass = MagicMock()
    kraken_client = MagicMock()
    portal_client = MagicMock()

    kraken_client.get_consumption = AsyncMock(return_value=_make_snapshot())
    portal_client.fetch_contract = AsyncMock(return_value=_make_tariffs())

    coordinator = PlenitudeCoordinator(
        hass=hass,
        kraken_client=kraken_client,
        portal_client=portal_client,
        kraken_session=_make_kraken_session(),
        portal_session=_make_portal_session(),
        account_number="A-TEST0000",
        scan_interval=timedelta(hours=1),
    )

    data = await coordinator._async_update_data()
    assert isinstance(data, PlenitudeData)
    assert data.consumption.site_id == "A-TEST0000"
    assert data.tariffs.hp_eur_per_kwh == pytest.approx(0.21114)


@pytest.mark.asyncio
async def test_coordinator_refreshes_token_when_expired() -> None:
    """If access_token is near expiry, coordinator refreshes BEFORE fetching."""
    hass = MagicMock()
    kraken_client = MagicMock()
    portal_client = MagicMock()

    expired_session = KrakenSession(
        access_token="expired",
        access_token_expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        refresh_token="rt_tok",
        refresh_token_expires_in_seconds=1209600,
        account_user_id="999999",
    )

    kraken_client.refresh = AsyncMock(return_value=_make_kraken_session())
    kraken_client.get_consumption = AsyncMock(return_value=_make_snapshot())
    portal_client.fetch_contract = AsyncMock(return_value=_make_tariffs())

    coordinator = PlenitudeCoordinator(
        hass=hass,
        kraken_client=kraken_client,
        portal_client=portal_client,
        kraken_session=expired_session,
        portal_session=_make_portal_session(),
        account_number="A-TEST0000",
        scan_interval=timedelta(hours=1),
    )

    data = await coordinator._async_update_data()
    assert isinstance(data, PlenitudeData)
    kraken_client.refresh.assert_awaited_once_with("rt_tok")
    kraken_client.get_consumption.assert_awaited_once()
    assert kraken_client.get_consumption.await_args.kwargs["access_token"] == "access_tok"


@pytest.mark.asyncio
async def test_coordinator_retries_consumption_after_auth_error() -> None:
    """If get_consumption raises KrakenAuthError mid-flight, refresh and retry once."""
    hass = MagicMock()
    kraken_client = MagicMock()
    portal_client = MagicMock()

    snapshot = _make_snapshot()

    kraken_client.refresh = AsyncMock(return_value=_make_kraken_session())
    kraken_client.get_consumption = AsyncMock(
        side_effect=[KrakenAuthError("expired"), snapshot]
    )
    portal_client.fetch_contract = AsyncMock(return_value=_make_tariffs())

    coordinator = PlenitudeCoordinator(
        hass=hass,
        kraken_client=kraken_client,
        portal_client=portal_client,
        kraken_session=_make_kraken_session(),
        portal_session=_make_portal_session(),
        account_number="A-TEST0000",
        scan_interval=timedelta(hours=1),
    )

    data = await coordinator._async_update_data()
    assert data.consumption is snapshot
    assert kraken_client.refresh.await_count == 1
    assert kraken_client.get_consumption.await_count == 2
