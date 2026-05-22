# Plenitude2MQTT

Polls Plenitude France APIs and publishes electricity consumption + tariffs to MQTT
with Home Assistant auto-discovery.

## Requirements

- Home Assistant OS or Supervised
- An MQTT broker add-on (Mosquitto, EMQX, etc.)
- A Plenitude France account with Linky communicating meter

## Installation

1. Add this add-on repository to HA: Settings → Add-ons → Add-on Store → ⋮ → Repositories
   → paste `https://github.com/williamboglietti/plenitude-ha` → Add
2. Find "Plenitude2MQTT" in the store, click → Install
3. Configure: enter your Plenitude email + password, click Save
4. Start the add-on
5. Open Settings → Devices & services. After ~1 minute, 10 sensors appear under a
   device named "Plenitude — A-XXXXXXXX". They are Energy-dashboard ready.

## What gets stored

- Your password is used at first login to obtain Kraken refresh tokens. After that,
  only the refresh tokens persist in `/data/state.json` (inside the add-on container).
  If you change your Plenitude password, you must update the option here and restart.

## Configuration options

| Option | Description | Default |
|---|---|---|
| `email` | Plenitude account email | (required) |
| `password` | Plenitude account password | (required) |
| `scan_interval_hours` | How often to poll Plenitude (1–24h) | 1 |
| `mqtt_topic_prefix` | Topic root for state messages | `plenitude` |
| `mqtt_discovery_prefix` | HA discovery prefix (rarely needs changing) | `homeassistant` |
| `log_level` | Add-on log verbosity | `info` |
