"""Tests for the MQTT publisher."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "addon" / "plenitude2mqtt"))

from service.mqtt_publisher import MqttPublisher, SensorState


def _sensor_state() -> SensorState:
    return SensorState(
        site_id="A-TEST0000",
        conso_totale_kwh=4711.5,
        conso_hp_kwh=2683.2,
        conso_hc_kwh=2028.3,
        cout_total_eur=945.32,
        cout_hp_eur=566.78,
        cout_hc_eur=337.18,
        tarif_hp_eur_kwh=0.21114,
        tarif_hc_eur_kwh=0.16614,
        abonnement_eur_mois=17.66790,
        derniere_releve=datetime(2026, 4, 29, 22, 30, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_publish_discovery_emits_10_configs() -> None:
    """publish_discovery() publishes one discovery config per sensor."""
    mock_client = AsyncMock()
    publisher = MqttPublisher(
        client=mock_client,
        topic_prefix="plenitude",
        discovery_prefix="homeassistant",
        sw_version="0.1.0",
    )

    await publisher.publish_discovery(site_id="A-TEST0000")

    # 10 sensors * 1 publish each + 1 availability publish
    assert mock_client.publish.await_count >= 10
    # Verify one of the discovery payloads is a valid JSON with required fields
    first_call = mock_client.publish.await_args_list[0]
    topic = first_call.args[0] if first_call.args else first_call.kwargs.get("topic")
    payload_raw = (
        first_call.args[1]
        if len(first_call.args) > 1
        else first_call.kwargs.get("payload")
    )
    assert topic.startswith("homeassistant/sensor/plenitude_A_TEST0000_")
    payload = json.loads(payload_raw)
    assert "unique_id" in payload
    assert "state_topic" in payload
    assert payload["state_topic"] == "plenitude/A-TEST0000/state"
    assert "device" in payload


@pytest.mark.asyncio
async def test_publish_state_emits_state_topic() -> None:
    """publish_state() publishes one state payload with all sensor values."""
    mock_client = AsyncMock()
    publisher = MqttPublisher(
        client=mock_client,
        topic_prefix="plenitude",
        discovery_prefix="homeassistant",
        sw_version="0.1.0",
    )

    await publisher.publish_state(_sensor_state())

    mock_client.publish.assert_awaited()
    call = mock_client.publish.await_args
    topic = call.args[0] if call.args else call.kwargs.get("topic")
    payload_raw = call.args[1] if len(call.args) > 1 else call.kwargs.get("payload")
    assert topic == "plenitude/A-TEST0000/state"
    payload = json.loads(payload_raw)
    assert payload["conso_totale_kwh"] == 4711.5
    assert payload["cout_total_eur"] == 945.32
    assert payload["derniere_releve"] == "2026-04-29T22:30:00+00:00"


@pytest.mark.asyncio
async def test_publish_availability_online() -> None:
    """publish_availability() emits online/offline on the status topic."""
    mock_client = AsyncMock()
    publisher = MqttPublisher(
        client=mock_client,
        topic_prefix="plenitude",
        discovery_prefix="homeassistant",
        sw_version="0.1.0",
    )

    await publisher.publish_availability(site_id="A-TEST0000", online=True)

    call = mock_client.publish.await_args
    topic = call.args[0] if call.args else call.kwargs.get("topic")
    payload = call.args[1] if len(call.args) > 1 else call.kwargs.get("payload")
    assert topic == "plenitude/A-TEST0000/status"
    assert payload == "online"
