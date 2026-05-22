# Changelog

## 0.1.0 — 2026-05-22

- Initial release.
- Polls Plenitude via Kraken Tech BFF tRPC for consumption (kWh, HP/HC).
- Fetches tariffs via the Plenitude portal HTML (RSC payload).
- Publishes 10 sensors via MQTT auto-discovery (consumption, cost, tariffs, last reading).
- Compatible with Home Assistant Energy dashboard.
