"""MQTT publisher: discovery configs + state payloads."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

_LOGGER = logging.getLogger(__name__)


class _MqttClient(Protocol):
    """Minimal MQTT client interface (asyncio-mqtt-like)."""

    async def publish(
        self, topic: str, payload: str | bytes, *, retain: bool = False
    ) -> Any: ...


@dataclass(slots=True, frozen=True)
class SensorState:
    """All sensor values in one payload."""

    site_id: str
    conso_totale_kwh: float
    conso_hp_kwh: float
    conso_hc_kwh: float
    cout_total_eur: float
    cout_hp_eur: float
    cout_hc_eur: float
    tarif_hp_eur_kwh: float
    tarif_hc_eur_kwh: float
    abonnement_eur_mois: float
    derniere_releve: datetime | None


# Sensor catalog. Each entry produces one MQTT discovery config.
_SENSOR_CATALOG: list[dict[str, Any]] = [
    {"key": "conso_totale_kwh", "name": "Consommation totale", "unit": "kWh",
     "device_class": "energy", "state_class": "total_increasing"},
    {"key": "conso_hp_kwh", "name": "Consommation Heures Pleines", "unit": "kWh",
     "device_class": "energy", "state_class": "total_increasing"},
    {"key": "conso_hc_kwh", "name": "Consommation Heures Creuses", "unit": "kWh",
     "device_class": "energy", "state_class": "total_increasing"},
    {"key": "cout_total_eur", "name": "Coût total", "unit": "EUR",
     "device_class": "monetary", "state_class": "total_increasing"},
    {"key": "cout_hp_eur", "name": "Coût Heures Pleines", "unit": "EUR",
     "device_class": "monetary", "state_class": "total_increasing"},
    {"key": "cout_hc_eur", "name": "Coût Heures Creuses", "unit": "EUR",
     "device_class": "monetary", "state_class": "total_increasing"},
    {"key": "tarif_hp_eur_kwh", "name": "Tarif Heures Pleines", "unit": "EUR/kWh",
     "device_class": None, "state_class": None},
    {"key": "tarif_hc_eur_kwh", "name": "Tarif Heures Creuses", "unit": "EUR/kWh",
     "device_class": None, "state_class": None},
    {"key": "abonnement_eur_mois", "name": "Abonnement mensuel", "unit": "EUR",
     "device_class": "monetary", "state_class": None},
    {"key": "derniere_releve", "name": "Dernière relève", "unit": None,
     "device_class": "timestamp", "state_class": None},
]


class MqttPublisher:
    """Publishes discovery configs and state payloads via MQTT."""

    def __init__(
        self,
        client: _MqttClient,
        *,
        topic_prefix: str = "plenitude",
        discovery_prefix: str = "homeassistant",
        sw_version: str = "0.1.0",
    ) -> None:
        self._client = client
        self._topic_prefix = topic_prefix
        self._discovery_prefix = discovery_prefix
        self._sw_version = sw_version

    def state_topic(self, site_id: str) -> str:
        return f"{self._topic_prefix}/{site_id}/state"

    def availability_topic(self, site_id: str) -> str:
        return f"{self._topic_prefix}/{site_id}/status"

    async def publish_discovery(self, site_id: str) -> None:
        """Publish one discovery config per sensor."""
        device = {
            "identifiers": [f"plenitude_{site_id.replace('-', '_')}"],
            "name": f"Plenitude — {site_id}",
            "manufacturer": "Plenitude (Kraken Tech)",
            "model": "Electricity contract",
            "sw_version": self._sw_version,
        }

        for sensor in _SENSOR_CATALOG:
            unique_id = f"plenitude_{site_id.replace('-', '_')}_{sensor['key']}"
            config_topic = (
                f"{self._discovery_prefix}/sensor/{unique_id}/config"
            )
            payload: dict[str, Any] = {
                "name": sensor["name"],
                "unique_id": unique_id,
                "object_id": unique_id,
                "state_topic": self.state_topic(site_id),
                "value_template": (
                    "{{ none if value_json."
                    f"{sensor['key']} is none else value_json.{sensor['key']}"
                    " }}"
                ),
                "availability_topic": self.availability_topic(site_id),
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device,
            }
            if sensor["unit"]:
                payload["unit_of_measurement"] = sensor["unit"]
            if sensor["device_class"]:
                payload["device_class"] = sensor["device_class"]
            if sensor["state_class"]:
                payload["state_class"] = sensor["state_class"]

            _LOGGER.debug("publish discovery -> %s", config_topic)
            await self._client.publish(
                config_topic, json.dumps(payload), retain=True
            )

    async def publish_state(self, state: SensorState) -> None:
        """Publish one state payload (all sensor values)."""
        payload = {
            "conso_totale_kwh": state.conso_totale_kwh,
            "conso_hp_kwh": state.conso_hp_kwh,
            "conso_hc_kwh": state.conso_hc_kwh,
            "cout_total_eur": state.cout_total_eur,
            "cout_hp_eur": state.cout_hp_eur,
            "cout_hc_eur": state.cout_hc_eur,
            "tarif_hp_eur_kwh": state.tarif_hp_eur_kwh,
            "tarif_hc_eur_kwh": state.tarif_hc_eur_kwh,
            "abonnement_eur_mois": state.abonnement_eur_mois,
            "derniere_releve": (
                state.derniere_releve.isoformat() if state.derniere_releve else None
            ),
        }
        _LOGGER.debug("publish state -> %s", self.state_topic(state.site_id))
        await self._client.publish(
            self.state_topic(state.site_id), json.dumps(payload), retain=True
        )

    async def publish_availability(self, site_id: str, *, online: bool) -> None:
        """Publish online/offline to the availability topic."""
        payload = "online" if online else "offline"
        await self._client.publish(
            self.availability_topic(site_id), payload, retain=True
        )
