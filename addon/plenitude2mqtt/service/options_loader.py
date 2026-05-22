"""Load add-on options from /data/options.json + Supervisor-injected MQTT env vars."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_OPTIONS_PATH = Path("/data/options.json")


@dataclass(slots=True, frozen=True)
class AddonOptions:
    """Combined user options + Supervisor MQTT credentials."""

    email: str
    password: str
    scan_interval_hours: int
    mqtt_topic_prefix: str
    mqtt_discovery_prefix: str
    log_level: str
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_password: str
    mqtt_ssl: bool


def load_options(options_path: Path = DEFAULT_OPTIONS_PATH) -> AddonOptions:
    """Read user options from disk and MQTT credentials from env."""
    if not options_path.exists():
        raise FileNotFoundError(f"Options file not found: {options_path}")
    raw = json.loads(options_path.read_text())

    email = raw.get("email") or ""
    if not email:
        raise ValueError("email option is required")
    password = raw.get("password") or ""
    if not password:
        raise ValueError("password option is required")

    mqtt_host = os.environ.get("MQTT_HOST", "")
    if not mqtt_host:
        raise ValueError(
            "MQTT_HOST env var missing. Did you install an MQTT broker add-on "
            "(e.g. Mosquitto)? The add-on declares services: ['mqtt:need']."
        )

    return AddonOptions(
        email=email,
        password=password,
        scan_interval_hours=int(raw.get("scan_interval_hours") or 1),
        mqtt_topic_prefix=raw.get("mqtt_topic_prefix") or "plenitude",
        mqtt_discovery_prefix=raw.get("mqtt_discovery_prefix") or "homeassistant",
        log_level=raw.get("log_level") or "info",
        mqtt_host=mqtt_host,
        mqtt_port=int(os.environ.get("MQTT_PORT") or 1883),
        mqtt_user=os.environ.get("MQTT_USER") or "",
        mqtt_password=os.environ.get("MQTT_PASSWORD") or "",
        mqtt_ssl=(os.environ.get("MQTT_SSL") or "false").lower() == "true",
    )
