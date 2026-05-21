# Plenitude — Home Assistant integration

Unofficial Home Assistant integration for [Plenitude France](https://www.eniplenitude.fr) (formerly Eni Gas e Luce France, now operated on the [Kraken Tech](https://www.kraken.tech) SaaS platform).

Retrieves half-hourly electricity consumption (kWh, HP/HC breakdown) from the Kraken GraphQL API and electricity tariffs (€/kWh HP/HC, monthly subscription) from the customer portal, exposing them as native HA sensors compatible with the **Energy dashboard**.

## Status

**Unofficial.** This is a personal-use integration. Not affiliated with, endorsed by, or supported by Plenitude or Kraken Tech. Plenitude may change its API at any time, breaking this integration.

## Requirements

- Home Assistant 2024.10.0+
- Plenitude France account with online portal access
- Linky communicating smart meter (for half-hourly granularity)

## Installation via HACS

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/williamdupont/plenitude-ha` as type **Integration**
3. Install **Plenitude**
4. Restart Home Assistant
5. Settings → Devices & services → Add integration → **Plenitude**
6. Enter your email and password

## What gets stored

After the config flow:
- **Stored:** Kraken refresh token (revocable, scoped), portal session cookie, auto-detected tariffs.
- **NOT stored:** your password (used once to obtain tokens, then discarded).

## Sensors

| Entity | Unit | Energy dashboard |
|---|---|---|
| `sensor.plenitude_consommation_totale` | kWh | ✅ consumption |
| `sensor.plenitude_consommation_heures_pleines` | kWh | ✅ consumption |
| `sensor.plenitude_consommation_heures_creuses` | kWh | ✅ consumption |
| `sensor.plenitude_derniere_releve` | timestamp | — |
| `sensor.plenitude_cout_total` | EUR | ✅ cost |
| `sensor.plenitude_cout_heures_pleines` | EUR | — |
| `sensor.plenitude_cout_heures_creuses` | EUR | — |
| `sensor.plenitude_tarif_heures_pleines` | EUR/kWh | — |
| `sensor.plenitude_tarif_heures_creuses` | EUR/kWh | — |
| `sensor.plenitude_abonnement_mensuel` | EUR | — |

## Limitations

- Electricity only (no gas yet)
- One account per HA instance (multi-account support planned)
- If your password changes on the Plenitude portal, you must re-authenticate via the integration's Configure button (Options flow)

## License

MIT
