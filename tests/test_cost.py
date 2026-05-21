"""Tests for cost calculation."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.plenitude.cost import CostBreakdown, calculate_cost
from custom_components.plenitude.models import (
    ConsumptionInterval,
    ConsumptionSnapshot,
    ContractTariffs,
    HalfHourPeriod,
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


def test_calculate_cost_multiplies_kwh_by_tariff() -> None:
    snapshot = ConsumptionSnapshot(
        site_id="A-X",
        intervals=(
            ConsumptionInterval(
                start=datetime(2026, 4, 29, 10, 0, tzinfo=UTC),
                end=datetime(2026, 4, 29, 10, 30, tzinfo=UTC),
                kwh_total=1.0,
                kwh_hp=1.0,
                kwh_hc=0.0,
            ),
            ConsumptionInterval(
                start=datetime(2026, 4, 29, 3, 0, tzinfo=UTC),
                end=datetime(2026, 4, 29, 3, 30, tzinfo=UTC),
                kwh_total=2.0,
                kwh_hp=0.0,
                kwh_hc=2.0,
            ),
        ),
    )

    cost = calculate_cost(snapshot, _tariffs(), now=datetime(2026, 4, 29, 12, 0, tzinfo=UTC))

    assert isinstance(cost, CostBreakdown)
    # 1.0 kWh HP at 0.21114 + 2.0 kWh HC at 0.16614 = 0.54342
    assert cost.energy_eur == pytest.approx(0.21114 + 2 * 0.16614, abs=1e-5)
    assert cost.hp_eur == pytest.approx(0.21114, abs=1e-5)
    assert cost.hc_eur == pytest.approx(2 * 0.16614, abs=1e-5)
    # Subscription prorated: April 29 at 12:00 → 28.5 / 30 days elapsed in April
    assert 0.0 < cost.subscription_eur_prorated <= 17.66790


def test_calculate_cost_handles_empty_snapshot() -> None:
    snapshot = ConsumptionSnapshot(site_id="A-X", intervals=())
    cost = calculate_cost(snapshot, _tariffs(), now=datetime(2026, 4, 29, 12, 0, tzinfo=UTC))
    assert cost.energy_eur == 0.0
    assert cost.hp_eur == 0.0
    assert cost.hc_eur == 0.0
