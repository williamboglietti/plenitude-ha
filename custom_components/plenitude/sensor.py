"""Plenitude sensor entities."""
from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SITE_ID, DOMAIN
from .coordinator import PlenitudeCoordinator
from .cost import calculate_cost


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    stored = hass.data[DOMAIN][entry.entry_id]
    coordinator: PlenitudeCoordinator = stored["coordinator"]
    site_id: str = entry.data[CONF_SITE_ID]
    async_add_entities(
        [
            PlenitudeConsumptionTotalSensor(coordinator, site_id=site_id),
            PlenitudeConsumptionHPSensor(coordinator, site_id=site_id),
            PlenitudeConsumptionHCSensor(coordinator, site_id=site_id),
            PlenitudeLastReadingSensor(coordinator, site_id=site_id),
            PlenitudeCostTotalSensor(coordinator, site_id=site_id),
            PlenitudeCostHPSensor(coordinator, site_id=site_id),
            PlenitudeCostHCSensor(coordinator, site_id=site_id),
            PlenitudeTariffHPSensor(coordinator, site_id=site_id),
            PlenitudeTariffHCSensor(coordinator, site_id=site_id),
            PlenitudeSubscriptionSensor(coordinator, site_id=site_id),
        ]
    )


class _PlenitudeSensorBase(CoordinatorEntity[PlenitudeCoordinator], SensorEntity):
    """Common base for Plenitude sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PlenitudeCoordinator, *, site_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._site_id = site_id
        self._attr_unique_id = f"plenitude_{site_id}_{key}"


class PlenitudeConsumptionTotalSensor(_PlenitudeSensorBase):
    """Total energy consumed (kWh) — feeds Energy dashboard."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_name = "Consommation totale"

    def __init__(self, coordinator: PlenitudeCoordinator, *, site_id: str) -> None:
        super().__init__(coordinator, site_id=site_id, key="conso_totale_kwh")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.consumption.total_kwh


class PlenitudeConsumptionHPSensor(_PlenitudeSensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_name = "Consommation Heures Pleines"

    def __init__(self, coordinator: PlenitudeCoordinator, *, site_id: str) -> None:
        super().__init__(coordinator, site_id=site_id, key="conso_hp_kwh")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.consumption.total_hp_kwh


class PlenitudeConsumptionHCSensor(_PlenitudeSensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_name = "Consommation Heures Creuses"

    def __init__(self, coordinator: PlenitudeCoordinator, *, site_id: str) -> None:
        super().__init__(coordinator, site_id=site_id, key="conso_hc_kwh")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.consumption.total_hc_kwh


class PlenitudeLastReadingSensor(_PlenitudeSensorBase):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_name = "Dernière relève"

    def __init__(self, coordinator: PlenitudeCoordinator, *, site_id: str) -> None:
        super().__init__(coordinator, site_id=site_id, key="derniere_releve")

    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.consumption.last_reading_at


class _CostSensorBase(_PlenitudeSensorBase):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "EUR"


class PlenitudeCostTotalSensor(_CostSensorBase):
    _attr_name = "Coût total"

    def __init__(self, coordinator: PlenitudeCoordinator, *, site_id: str) -> None:
        super().__init__(coordinator, site_id=site_id, key="cout_total_eur")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None:
            return None
        cost = calculate_cost(data.consumption, data.tariffs, now=datetime.now(tz=UTC))
        return round(cost.total_eur, 4)


class PlenitudeCostHPSensor(_CostSensorBase):
    _attr_name = "Coût Heures Pleines"

    def __init__(self, coordinator: PlenitudeCoordinator, *, site_id: str) -> None:
        super().__init__(coordinator, site_id=site_id, key="cout_hp_eur")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None:
            return None
        cost = calculate_cost(data.consumption, data.tariffs, now=datetime.now(tz=UTC))
        return round(cost.hp_eur, 4)


class PlenitudeCostHCSensor(_CostSensorBase):
    _attr_name = "Coût Heures Creuses"

    def __init__(self, coordinator: PlenitudeCoordinator, *, site_id: str) -> None:
        super().__init__(coordinator, site_id=site_id, key="cout_hc_eur")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None:
            return None
        cost = calculate_cost(data.consumption, data.tariffs, now=datetime.now(tz=UTC))
        return round(cost.hc_eur, 4)


class PlenitudeTariffHPSensor(_PlenitudeSensorBase):
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_name = "Tarif Heures Pleines"

    def __init__(self, coordinator: PlenitudeCoordinator, *, site_id: str) -> None:
        super().__init__(coordinator, site_id=site_id, key="tarif_hp_eur_kwh")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        return None if data is None else data.tariffs.hp_eur_per_kwh


class PlenitudeTariffHCSensor(_PlenitudeSensorBase):
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_name = "Tarif Heures Creuses"

    def __init__(self, coordinator: PlenitudeCoordinator, *, site_id: str) -> None:
        super().__init__(coordinator, site_id=site_id, key="tarif_hc_eur_kwh")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        return None if data is None else data.tariffs.hc_eur_per_kwh


class PlenitudeSubscriptionSensor(_PlenitudeSensorBase):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_name = "Abonnement mensuel"

    def __init__(self, coordinator: PlenitudeCoordinator, *, site_id: str) -> None:
        super().__init__(coordinator, site_id=site_id, key="abonnement_eur_mois")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        return None if data is None else data.tariffs.subscription_eur_per_month
