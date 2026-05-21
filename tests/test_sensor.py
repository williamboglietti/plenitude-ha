"""Tests for Plenitude sensors."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.plenitude.coordinator import PlenitudeCoordinator, PlenitudeData
from custom_components.plenitude.models import (
    ConsumptionInterval,
    ConsumptionSnapshot,
    ContractTariffs,
    HalfHourPeriod,
)
from custom_components.plenitude.sensor import (
    PlenitudeConsumptionHCSensor,
    PlenitudeConsumptionHPSensor,
    PlenitudeConsumptionTotalSensor,
    PlenitudeLastReadingSensor,
)


def _data() -> PlenitudeData:
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
    return PlenitudeData(consumption=snapshot, tariffs=tariffs)


def _coordinator(data: PlenitudeData) -> PlenitudeCoordinator:
    c = MagicMock(spec=PlenitudeCoordinator)
    c.data = data
    c.last_update_success = True
    return c


def test_consumption_total_sensor() -> None:
    sensor = PlenitudeConsumptionTotalSensor(_coordinator(_data()), site_id="A-TEST0000")
    assert sensor.native_value == pytest.approx(2.0)
    assert sensor.native_unit_of_measurement == "kWh"
    assert sensor.device_class == SensorDeviceClass.ENERGY
    assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
    assert sensor.unique_id == "plenitude_A-TEST0000_conso_totale_kwh"


def test_consumption_hp_sensor() -> None:
    sensor = PlenitudeConsumptionHPSensor(_coordinator(_data()), site_id="A-TEST0000")
    assert sensor.native_value == pytest.approx(1.5)


def test_consumption_hc_sensor() -> None:
    sensor = PlenitudeConsumptionHCSensor(_coordinator(_data()), site_id="A-TEST0000")
    assert sensor.native_value == pytest.approx(0.5)


def test_last_reading_sensor() -> None:
    sensor = PlenitudeLastReadingSensor(_coordinator(_data()), site_id="A-TEST0000")
    assert sensor.native_value == datetime(2026, 4, 29, 22, 30, tzinfo=UTC)
    assert sensor.device_class == SensorDeviceClass.TIMESTAMP
