"""Tests for the add-on main service loop."""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "addon" / "plenitude2mqtt"))

from service.api.kraken import KrakenSession  # noqa: E402
from service.main import (  # noqa: E402
    build_sensor_state,
    ensure_kraken_session,
)
from service.models import (  # noqa: E402
    ConsumptionInterval,
    ConsumptionSnapshot,
    ContractTariffs,
    HalfHourPeriod,
)


@pytest.mark.asyncio
async def test_ensure_kraken_session_uses_refresh_token_when_available() -> None:
    kraken_client = MagicMock()
    fresh = KrakenSession(
        access_token="access",
        access_token_expires_at=datetime.now(tz=UTC) + timedelta(minutes=55),
        refresh_token="rt_new",
        refresh_token_expires_in_seconds=1209600,
        account_user_id="999999",
    )
    kraken_client.refresh = AsyncMock(return_value=fresh)
    kraken_client.login = AsyncMock()

    session = await ensure_kraken_session(
        kraken_client,
        existing_refresh_token="rt_existing",
        email="a@b.c",
        password="pw",
    )

    kraken_client.refresh.assert_awaited_once_with("rt_existing")
    kraken_client.login.assert_not_awaited()
    assert session is fresh


@pytest.mark.asyncio
async def test_ensure_kraken_session_logs_in_when_no_refresh_token() -> None:
    kraken_client = MagicMock()
    fresh = KrakenSession(
        access_token="access",
        access_token_expires_at=datetime.now(tz=UTC) + timedelta(minutes=55),
        refresh_token="rt_new",
        refresh_token_expires_in_seconds=1209600,
        account_user_id="999999",
    )
    kraken_client.login = AsyncMock(return_value=fresh)
    kraken_client.refresh = AsyncMock()

    session = await ensure_kraken_session(
        kraken_client,
        existing_refresh_token=None,
        email="a@b.c",
        password="pw",
    )

    kraken_client.login.assert_awaited_once_with("a@b.c", "pw")
    kraken_client.refresh.assert_not_awaited()
    assert session is fresh


def test_build_sensor_state_computes_cost_correctly() -> None:
    snapshot = ConsumptionSnapshot(
        site_id="A-TEST0000",
        intervals=(
            ConsumptionInterval(
                start=datetime(2026, 4, 29, 22, 0, tzinfo=UTC),
                end=datetime(2026, 4, 29, 22, 30, tzinfo=UTC),
                kwh_total=2.0,
                kwh_hp=1.5,
                kwh_hc=0.5,
            ),
        ),
        last_reading_at=datetime(2026, 4, 29, 22, 30, tzinfo=UTC),
    )
    tariffs = ContractTariffs(
        hp_eur_per_kwh=0.21114,
        hc_eur_per_kwh=0.16614,
        subscription_eur_per_month=17.66790,
        hp_periods=(HalfHourPeriod("07:30:00", "23:30:00"),),
        hc_periods=(HalfHourPeriod("00:00:00", "07:30:00"),),
        valid_from=datetime(2025, 5, 25, tzinfo=UTC),
    )

    state = build_sensor_state(
        site_id="A-TEST0000",
        snapshot=snapshot,
        tariffs=tariffs,
        now=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
    )

    assert state.site_id == "A-TEST0000"
    assert state.conso_totale_kwh == pytest.approx(2.0)
    assert state.conso_hp_kwh == pytest.approx(1.5)
    assert state.conso_hc_kwh == pytest.approx(0.5)
    assert state.tarif_hp_eur_kwh == pytest.approx(0.21114)
    # cost: 1.5 * 0.21114 + 0.5 * 0.16614 + subscription_prorated > 0
    assert state.cout_total_eur > 0
