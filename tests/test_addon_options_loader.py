"""Tests for the add-on options loader."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Add the add-on service path to sys.path so we can import it directly in tests
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "addon" / "plenitude2mqtt"))

from service.options_loader import AddonOptions, load_options


def test_load_options_reads_user_config_and_mqtt_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load_options() reads /data/options.json + MQTT_* env vars."""
    options_file = tmp_path / "options.json"
    options_file.write_text(json.dumps({
        "email": "user@example.com",
        "password": "secret",
        "scan_interval_hours": 2,
        "mqtt_topic_prefix": "plenitude",
        "mqtt_discovery_prefix": "homeassistant",
        "log_level": "info",
    }))

    monkeypatch.setenv("MQTT_HOST", "core-mosquitto")
    monkeypatch.setenv("MQTT_PORT", "1883")
    monkeypatch.setenv("MQTT_USER", "addons")
    monkeypatch.setenv("MQTT_PASSWORD", "broker-pass")
    monkeypatch.setenv("MQTT_SSL", "false")

    opts = load_options(options_path=options_file)

    assert isinstance(opts, AddonOptions)
    assert opts.email == "user@example.com"
    assert opts.password == "secret"
    assert opts.scan_interval_hours == 2
    assert opts.mqtt_host == "core-mosquitto"
    assert opts.mqtt_port == 1883
    assert opts.mqtt_user == "addons"
    assert opts.mqtt_password == "broker-pass"
    assert opts.mqtt_ssl is False


def test_load_options_missing_email_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options_file = tmp_path / "options.json"
    options_file.write_text(json.dumps({"password": "x"}))
    monkeypatch.setenv("MQTT_HOST", "host")
    monkeypatch.setenv("MQTT_PORT", "1883")
    with pytest.raises(ValueError, match="email"):
        load_options(options_path=options_file)


def test_load_options_missing_mqtt_creds_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options_file = tmp_path / "options.json"
    options_file.write_text(json.dumps({
        "email": "a@b.c", "password": "x", "scan_interval_hours": 1,
        "mqtt_topic_prefix": "p", "mqtt_discovery_prefix": "h", "log_level": "info"
    }))
    monkeypatch.delenv("MQTT_HOST", raising=False)
    with pytest.raises(ValueError, match="MQTT_HOST"):
        load_options(options_path=options_file)
