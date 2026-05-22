# Plenitude — Home Assistant integration

Unofficial Home Assistant integration for [Plenitude France](https://www.eniplenitude.fr) (formerly Eni Gas e Luce France, now operated on the [Kraken Tech](https://www.kraken.tech) SaaS platform).

Retrieves half-hourly electricity consumption (kWh, HP/HC breakdown) from the Kraken GraphQL API and electricity tariffs (€/kWh HP/HC, monthly subscription) from the customer portal, exposing them as native HA sensors compatible with the **Energy dashboard**.

## Status

**Unofficial.** This is a personal-use integration. Not affiliated with, endorsed by, or supported by Plenitude or Kraken Tech. Plenitude may change its API at any time, breaking this integration.

## Requirements

- Home Assistant 2024.10.0+
- Plenitude France account with online portal access
- Linky communicating smart meter (for half-hourly granularity)

## Installation

You have **two install paths** depending on your Home Assistant setup.

### Path A — Supervisor add-on (HAOS / Supervised, recommended)

The simplest setup — no HACS required.

1. In HA, go to Settings → Add-ons → Add-on Store → **⋮ (top right) → Repositories**.
2. Paste: `https://github.com/williamboglietti/plenitude-ha` → Add.
3. Refresh the store. Find **Plenitude2MQTT** → Install.
4. In the add-on Configuration tab, enter:
   - **email**: your Plenitude account email
   - **password**: your Plenitude account password
   - (optional) **scan_interval_hours**: how often to poll (default 1h, min 15 min effectively per Kraken rate limit)
5. **Save** then **Start** the add-on.
6. Within ~1 minute, 10 sensors appear under a device named "Plenitude — A-XXXXXXXX".
7. Sensors are **Energy dashboard ready**: Settings → Dashboards → Energy → Add `sensor.plenitude_<id>_conso_totale_kwh` (consumption) and `sensor.plenitude_<id>_cout_total_eur` (cost).

**Requires an MQTT broker add-on** (Mosquitto, EMQX, etc.). The Supervisor auto-provisions a per-add-on MQTT user — no manual credentials.

### Path B — Custom integration via HACS (HA Container / Core / Supervised)

1. Open HACS → Integrations → **⋮ → Custom repositories**.
2. URL: `https://github.com/williamboglietti/plenitude-ha`, Type: **Integration**, Add.
3. Find **Plenitude** in the list → Download → choose version → Restart HA.
4. Settings → Devices & services → **+ Add integration → Plenitude**.
5. Enter email + password; the config flow auto-detects your tariffs.

### Path C — Manual integration (no HACS)

```bash
HA_CONFIG=/path/to/your/config
git clone https://github.com/williamboglietti/plenitude-ha.git /tmp/plenitude
mkdir -p "$HA_CONFIG/custom_components"
cp -r /tmp/plenitude/custom_components/plenitude "$HA_CONFIG/custom_components/"
# Restart HA
```

### Which path is right for me?

| Setup | Best path |
|---|---|
| HAOS / Supervised | **Path A** (add-on, simplest) |
| HA Container (Docker) | Path B (HACS) or Path C (manual) |
| HA Core (venv) | Path B or Path C |

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
