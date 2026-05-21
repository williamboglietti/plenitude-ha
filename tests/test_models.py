"""Tests for data models."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.plenitude.models import (
    ConsumptionInterval,
    ContractTariffs,
    HalfHourPeriod,
)


def test_consumption_interval_validates_unit() -> None:
    """ConsumptionInterval rejects non-kWh units."""
    with pytest.raises(ValueError):
        ConsumptionInterval(
            start=datetime(2026, 4, 29, 22, 0, tzinfo=UTC),
            end=datetime(2026, 4, 29, 22, 30, tzinfo=UTC),
            kwh_total=1.5,
            kwh_hp=1.0,
            kwh_hc=0.5,
            unit="Wh",
        )


def test_contract_tariffs_helpers() -> None:
    """ContractTariffs exposes convenience methods for hourly tariff lookup."""
    tariffs = ContractTariffs(
        hp_eur_per_kwh=0.21114,
        hc_eur_per_kwh=0.16614,
        subscription_eur_per_month=17.66790,
        hp_periods=(HalfHourPeriod("07:30:00", "23:30:00"),),
        hc_periods=(
            HalfHourPeriod("00:00:00", "07:30:00"),
            HalfHourPeriod("23:30:00", "00:00:00"),  # wraps midnight
        ),
        valid_from=datetime(2025, 5, 25, tzinfo=UTC),
        valid_to=datetime(2027, 5, 25, tzinfo=UTC),
    )

    assert tariffs.is_active_at(datetime(2026, 1, 1, tzinfo=UTC)) is True
    assert tariffs.is_active_at(datetime(2028, 1, 1, tzinfo=UTC)) is False
