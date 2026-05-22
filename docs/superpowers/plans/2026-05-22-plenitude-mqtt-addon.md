# Plenitude MQTT add-on — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Home Assistant **Supervisor add-on** (`plenitude2mqtt`) that polls the Plenitude APIs and publishes consumption + cost + tariff data to MQTT with auto-discovery, so HA users on HAOS/Supervised can install the integration **natively from the add-on store** by adding the repo URL (no HACS, no `custom_components/` manipulation). The existing custom integration remains for HA Container / Core users.

**Architecture:**
- Two distribution channels in the **same** repo (`plenitude-ha`):
  1. **`custom_components/plenitude/`** — existing HA custom integration (already shipped in v0.1.0)
  2. **`addon/plenitude2mqtt/`** — new Supervisor add-on (Docker container) that publishes to MQTT
- A shared Python library (`plenitude_core/`) is **NOT** introduced — adding it would create import-path complications for the custom integration. Instead, the add-on **copies** the API client code from `custom_components/plenitude/api/` into `addon/plenitude2mqtt/service/api/`, and a `make sync` / GitHub Actions step verifies the two copies stay byte-identical. Pragmatic over architecturally pure.
- The add-on uses **Supervisor MQTT service discovery** to auto-receive broker credentials (no manual MQTT config from the user) when an MQTT add-on (Mosquitto, EMQX, etc.) is installed.
- Publishes via MQTT auto-discovery so HA creates the 10 sensors automatically (same as the custom integration produces). HA accepts MQTT-discovered entities in the Energy dashboard.

**Tech Stack:** Python 3.12, `aiohttp`, `paho-mqtt` (async wrapper or `asyncio-mqtt`), Docker, Home Assistant Supervisor add-on framework, MQTT discovery spec.

**Existing state to be aware of:**
- Repo: `https://github.com/williamboglietti/plenitude-ha`
- v0.1.0 tag published, CI green
- Existing `custom_components/plenitude/` contains 4 API client modules already tested:
  - `api/kraken.py` — login, refresh, get_viewer, get_consumption (BFF tRPC), invalidate_refresh_token
  - `api/portal.py` — login via Server Action with hash scrape, fetch_contract
  - `api/rsc_parser.py` — parse_rsc_tariffs() regex over HTML
  - `cost.py` — calculate_cost() pure function
  - `models.py` — ConsumptionInterval, ContractTariffs, etc.
- 28 unit tests passing
- Test fixtures in `tests/fixtures/` (kraken JSON responses, portal HTML)

**Source spec:** `docs/superpowers/specs/2026-05-21-plenitude-ha-design.md` (read for design rationale; the MQTT add-on extends this — no spec changes are required for the existing integration)

---

## Background — Home Assistant add-ons in 30 seconds

A Home Assistant **add-on** is a Docker container managed by the Supervisor (the orchestrator that runs alongside HA Core in HAOS / Supervised installs). When a user installs an add-on:

1. Supervisor reads the add-on's `config.yaml` (which declares ports, environment variables, options schema, services needed)
2. It builds the Docker image from the add-on's `Dockerfile` (or pulls a pre-built one)
3. It runs the container with options + service credentials injected as environment variables

Add-ons can be discovered from **add-on repositories** — Git repos with a specific structure:

```
my-addon-repo/
├── repository.yaml           # repo metadata
├── README.md
├── my-first-addon/
│   ├── config.yaml           # add-on metadata + options schema
│   ├── Dockerfile            # how to build the container
│   ├── run.sh                # entrypoint
│   └── ...
└── my-second-addon/
    └── ...
```

The user adds the repo URL via **Settings → Add-ons → Add-on Store → ⋮ → Repositories → Add**. Then the add-ons appear in the store, ready to install.

For our case, the **repository root** = `addon/` subfolder of the existing `plenitude-ha` repo. We point HA at `https://github.com/williamboglietti/plenitude-ha` with the path `/addon`, and the Supervisor picks up the `repository.yaml` and the add-on inside.

Actually — a cleaner pattern is to put `repository.yaml` at the **root of the repo**, and the add-on under a subfolder. HA accepts both. We'll go with `repository.yaml` at the root for simplicity, and `addon/plenitude2mqtt/` for the add-on contents.

---

## Background — Supervisor MQTT service discovery

When an add-on declares `services: ["mqtt:need"]` in its `config.yaml`, the Supervisor injects these env vars into the container at startup if an MQTT broker (Mosquitto add-on, etc.) is installed:

- `MQTT_HOST` — broker hostname (typically `core-mosquitto`)
- `MQTT_PORT` — broker port (1883)
- `MQTT_USER` — auto-provisioned MQTT user for this add-on
- `MQTT_PASSWORD` — auto-provisioned password
- `MQTT_SSL` — `"true"` or `"false"`

**No manual MQTT config from the user.** This is the standard, hands-off pattern. If the user has no MQTT broker, the add-on falls back to options-file-provided credentials (escape hatch).

---

## Background — MQTT auto-discovery for HA

HA listens to `homeassistant/sensor/<unique_id>/config` topics for entity config payloads. When we publish:

```json
POST homeassistant/sensor/plenitude_A_TEST0000_conso_totale_kwh/config
{
  "name": "Consommation totale",
  "unique_id": "plenitude_A_TEST0000_conso_totale_kwh",
  "object_id": "plenitude_A_TEST0000_conso_totale_kwh",
  "state_topic": "plenitude/A-TEST0000/state",
  "value_template": "{{ value_json.conso_totale_kwh }}",
  "unit_of_measurement": "kWh",
  "device_class": "energy",
  "state_class": "total_increasing",
  "availability_topic": "plenitude/A-TEST0000/status",
  "payload_available": "online",
  "payload_not_available": "offline",
  "device": {
    "identifiers": ["plenitude_A_TEST0000"],
    "name": "Plenitude — A-TEST0000",
    "manufacturer": "Plenitude (Kraken Tech)",
    "model": "Electricity contract",
    "sw_version": "0.1.0"
  }
}
```

HA creates `sensor.plenitude_a_test0000_conso_totale_kwh` automatically and groups it with the other 9 sensors under one device.

Then each polling tick we publish ONE state payload that updates all 10 sensors via `value_template`:

```
POST plenitude/A-TEST0000/state
{
  "conso_totale_kwh": 4711.5,
  "conso_hp_kwh": 2683.2,
  "conso_hc_kwh": 2028.3,
  "cout_total_eur": 945.32,
  "cout_hp_eur": 566.78,
  "cout_hc_eur": 337.18,
  "tarif_hp_eur_kwh": 0.21114,
  "tarif_hc_eur_kwh": 0.16614,
  "abonnement_eur_mois": 17.66790,
  "derniere_releve": "2026-04-29T22:30:00Z"
}
```

And the availability topic when starting/stopping:

```
plenitude/A-TEST0000/status  →  "online" | "offline"
```

(With MQTT LWT for graceful "offline" if the container dies.)

---

## File Structure

After this plan completes, the repo will look like:

```
plenitude-ha/
├── custom_components/plenitude/          # UNCHANGED — existing v0.1.0 integration
│   ├── api/{kraken,portal,rsc_parser}.py
│   ├── coordinator.py
│   ├── sensor.py
│   ├── config_flow.py
│   ├── cost.py
│   ├── models.py
│   ├── const.py
│   ├── manifest.json
│   └── ...
├── addon/                                # NEW
│   └── plenitude2mqtt/
│       ├── config.yaml                   # add-on manifest
│       ├── Dockerfile
│       ├── run.sh                        # entrypoint
│       ├── icon.png                      # optional 128×128 icon
│       ├── README.md
│       ├── CHANGELOG.md
│       └── service/                      # Python service code
│           ├── __init__.py
│           ├── main.py                   # async main loop
│           ├── mqtt_publisher.py         # discovery + state publishing
│           ├── options_loader.py         # read /data/options.json
│           ├── state_store.py            # persist refresh tokens to /data/state.json
│           └── api/                      # COPIED from custom_components/plenitude/api/
│               ├── __init__.py
│               ├── kraken.py             # synced via scripts/sync_api.sh
│               ├── portal.py             # synced via scripts/sync_api.sh
│               └── rsc_parser.py         # synced via scripts/sync_api.sh
│           # Also copied: cost.py, models.py (see sync script)
├── repository.yaml                       # NEW — HAOS add-on repo metadata
├── scripts/
│   ├── sync_api.sh                       # NEW — sync api/ + cost.py + models.py into the add-on
│   └── check_sync.sh                     # NEW — CI check that sync is up-to-date
├── tests/
│   ├── test_addon_mqtt_publisher.py      # NEW
│   ├── test_addon_options_loader.py      # NEW
│   ├── test_addon_state_store.py         # NEW
│   ├── test_addon_main.py                # NEW
│   └── ...                               # existing tests stay
├── .github/workflows/
│   ├── test.yml                          # UNCHANGED + add sync check job
│   └── addon-build.yml                   # NEW — build add-on image on PRs
├── README.md                             # UPDATED — explain both install paths
└── hacs.json                             # UNCHANGED
```

---

## Task 1: Add repository.yaml + sync_api.sh + add-on skeleton

**Files:**
- Create: `repository.yaml`
- Create: `addon/plenitude2mqtt/config.yaml`
- Create: `addon/plenitude2mqtt/README.md`
- Create: `addon/plenitude2mqtt/CHANGELOG.md`
- Create: `addon/plenitude2mqtt/Dockerfile`
- Create: `addon/plenitude2mqtt/run.sh`
- Create: `scripts/sync_api.sh`
- Create: `scripts/check_sync.sh`

- [ ] **Step 1: Create repository.yaml at repo root**

```yaml
name: "Plenitude Home Assistant add-ons"
url: "https://github.com/williamboglietti/plenitude-ha"
maintainer: "William BOGLIETTI <williamboglietti@users.noreply.github.com>"
```

- [ ] **Step 2: Create the add-on directory tree**

```bash
mkdir -p addon/plenitude2mqtt/service/api
mkdir -p scripts
```

- [ ] **Step 3: Create addon/plenitude2mqtt/config.yaml**

```yaml
name: Plenitude2MQTT
version: "0.1.0"
slug: plenitude2mqtt
description: >
  Polls Plenitude France (Eni Plenitude / Kraken Tech) consumption + tariffs
  and publishes to MQTT with auto-discovery for Home Assistant.
url: "https://github.com/williamboglietti/plenitude-ha"
arch:
  - amd64
  - aarch64
  - armv7
  - armhf
  - i386
startup: services
boot: auto
init: false
services:
  - mqtt:need
options:
  email: ""
  password: ""
  scan_interval_hours: 1
  mqtt_topic_prefix: "plenitude"
  mqtt_discovery_prefix: "homeassistant"
  log_level: "info"
schema:
  email: email
  password: password
  scan_interval_hours: int(1,24)
  mqtt_topic_prefix: str
  mqtt_discovery_prefix: str
  log_level: list(trace|debug|info|notice|warning|error|fatal)
image: ""
```

Notes on the schema:
- `services: ["mqtt:need"]` — Supervisor will refuse to start the add-on unless an MQTT broker add-on is installed
- `password` type masks the field in the UI
- `int(1,24)` constrains the polling interval to a sane range
- `image: ""` means "build locally from Dockerfile" (no pre-built image)

- [ ] **Step 4: Create addon/plenitude2mqtt/Dockerfile**

```dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python 3.12+ and dependencies
RUN apk add --no-cache python3 py3-pip

# Install runtime Python deps
COPY service/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# Copy service code
COPY service /opt/plenitude2mqtt/service
COPY run.sh /

RUN chmod a+x /run.sh

CMD ["/run.sh"]
```

- [ ] **Step 5: Create addon/plenitude2mqtt/service/requirements.txt**

```
aiohttp>=3.9
asyncio-mqtt>=0.16
```

- [ ] **Step 6: Create addon/plenitude2mqtt/run.sh**

```bash
#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Plenitude2MQTT…"

# Export options for the Python service
export PLENITUDE_EMAIL="$(bashio::config 'email')"
export PLENITUDE_PASSWORD="$(bashio::config 'password')"
export PLENITUDE_SCAN_INTERVAL_HOURS="$(bashio::config 'scan_interval_hours')"
export PLENITUDE_MQTT_TOPIC_PREFIX="$(bashio::config 'mqtt_topic_prefix')"
export PLENITUDE_MQTT_DISCOVERY_PREFIX="$(bashio::config 'mqtt_discovery_prefix')"
export PLENITUDE_LOG_LEVEL="$(bashio::config 'log_level')"

# Supervisor injects MQTT_* env vars when services: ["mqtt:need"] is declared
bashio::log.info "MQTT broker: ${MQTT_HOST}:${MQTT_PORT} (user=${MQTT_USER})"

cd /opt/plenitude2mqtt
exec python3 -m service.main
```

Notes:
- `bashio` is the standard add-on shell helper (lives at `/usr/bin/with-contenv bashio` in the base image)
- `bashio::config 'email'` reads the option from `/data/options.json`
- All env vars are prefixed `PLENITUDE_` to avoid collision with Supervisor's MQTT_*

- [ ] **Step 7: Create addon/plenitude2mqtt/README.md**

```markdown
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
```

- [ ] **Step 8: Create addon/plenitude2mqtt/CHANGELOG.md**

```markdown
# Changelog

## 0.1.0 — 2026-05-22

- Initial release.
- Polls Plenitude via Kraken Tech BFF tRPC for consumption (kWh, HP/HC).
- Fetches tariffs via the Plenitude portal HTML (RSC payload).
- Publishes 10 sensors via MQTT auto-discovery (consumption, cost, tariffs, last reading).
- Compatible with Home Assistant Energy dashboard.
```

- [ ] **Step 9: Create scripts/sync_api.sh**

This script keeps the API client code in sync between the custom integration and the add-on. It must be run after any edit to `custom_components/plenitude/api/` or to `cost.py` / `models.py`.

```bash
#!/usr/bin/env bash
# Sync the API client + shared models from the custom integration into the add-on.
# Run after any edit to custom_components/plenitude/api/, cost.py, or models.py.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${REPO_ROOT}/custom_components/plenitude"
DST="${REPO_ROOT}/addon/plenitude2mqtt/service"

# Copy api/ verbatim
rm -rf "${DST}/api"
mkdir -p "${DST}/api"
cp "${SRC}/api/"*.py "${DST}/api/"

# Copy cost.py and models.py verbatim
cp "${SRC}/cost.py" "${DST}/cost.py"
cp "${SRC}/models.py" "${DST}/models.py"

# Strip HA-specific imports if any sneak in
# (the api modules and cost/models are pure Python, no HA imports — verified at design)

# Note: api/kraken.py imports from `..const`. The add-on side needs its own const
# substitution. We auto-generate a minimal const.py in the add-on:
cat > "${DST}/const.py" <<'EOF'
"""Constants for the Plenitude add-on service.

Auto-generated by scripts/sync_api.sh — DO NOT EDIT.
Mirror of the keys needed by the api/ modules, without HA-specific config keys.
"""
from __future__ import annotations

KRAKEN_GRAPHQL_URL = "https://api.plenitudefr-kraken.energy/v1/graphql/"
PORTAL_BASE_URL = "https://espace-client.eniplenitude.fr"
PORTAL_CONTRACT_PATH = "/contrat"
USER_AGENT = "plenitude2mqtt/0.1.0 (+https://github.com/williamboglietti/plenitude-ha)"
EOF

echo "✓ Synced api/, cost.py, models.py from custom_components/plenitude/ to addon/plenitude2mqtt/service/"
```

Make it executable: `chmod +x scripts/sync_api.sh`

- [ ] **Step 10: Create scripts/check_sync.sh (CI guard)**

```bash
#!/usr/bin/env bash
# Verify the add-on's API client copy is byte-identical to the custom integration's.
# Used by CI to prevent drift.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${REPO_ROOT}/custom_components/plenitude"
DST="${REPO_ROOT}/addon/plenitude2mqtt/service"

fail=0

for f in api/kraken.py api/portal.py api/rsc_parser.py api/__init__.py cost.py models.py; do
    if ! diff -q "${SRC}/${f}" "${DST}/${f}" > /dev/null; then
        echo "✗ ${f} differs between custom_components/ and addon/"
        diff "${SRC}/${f}" "${DST}/${f}" || true
        fail=1
    fi
done

if [ ${fail} -eq 0 ]; then
    echo "✓ All shared files are in sync."
else
    echo ""
    echo "Run: scripts/sync_api.sh"
    exit 1
fi
```

Make it executable: `chmod +x scripts/check_sync.sh`

- [ ] **Step 11: Run sync_api.sh to populate the add-on service code**

```bash
./scripts/sync_api.sh
ls -la addon/plenitude2mqtt/service/
```

Expected: `api/`, `cost.py`, `models.py`, `const.py` present.

- [ ] **Step 12: Verify the imports work standalone**

```bash
cd addon/plenitude2mqtt/service
python3 -c "from api.kraken import PlenitudeKrakenClient; print('OK')"
python3 -c "from api.portal import PlenitudePortalClient; print('OK')"
python3 -c "from api.rsc_parser import parse_rsc_tariffs; print('OK')"
python3 -c "from cost import calculate_cost; print('OK')"
python3 -c "from models import ConsumptionSnapshot; print('OK')"
```

If `from ..const import ...` (relative) breaks, edit the synced api files to use `from const import ...` (absolute, since `service/` is the root in the add-on container). The `sync_api.sh` script can include a `sed` step to do this rewrite, but **first verify whether it's actually needed**. If `service/` is on PYTHONPATH and `service/__init__.py` exists, relative imports inside `service/api/` may still need adjustment. Test, then patch sync_api.sh if necessary.

If the sync needs to rewrite relative imports, append to `scripts/sync_api.sh` (before the final echo):

```bash
# Rewrite the api files' relative imports for the add-on context (no parent package)
sed -i.bak \
    -e 's/from \.\.const import/from ..const import/g' \
    -e 's/from \.\.models import/from ..models import/g' \
    "${DST}/api/"*.py
rm -f "${DST}/api/"*.bak
```

(`from ..const` and `from ..models` work if `service/__init__.py` exists and `service/api/__init__.py` exists. Verify both are present after `sync_api.sh`.)

Create `addon/plenitude2mqtt/service/__init__.py` and `addon/plenitude2mqtt/service/api/__init__.py` if missing:

```bash
touch addon/plenitude2mqtt/service/__init__.py
# api/__init__.py is already synced from custom_components/plenitude/api/__init__.py
```

- [ ] **Step 13: Commit**

```bash
git add repository.yaml addon/ scripts/
git commit -m "feat(addon): scaffold plenitude2mqtt add-on + sync infrastructure

- repository.yaml at repo root (HAOS add-on repo manifest)
- addon/plenitude2mqtt/config.yaml + Dockerfile + run.sh + README + CHANGELOG
- scripts/sync_api.sh + check_sync.sh keep API client in sync between
  custom_components/plenitude/ (integration) and addon/plenitude2mqtt/service/
  (add-on). Pragmatic dual-channel approach without introducing a separate
  package.
- service/api/, cost.py, models.py copied from the custom integration.
- Add-on declares services: ['mqtt:need'] so Supervisor auto-provisions MQTT
  broker credentials."
```

---

## Task 2: Options loader (read /data/options.json)

**Files:**
- Create: `addon/plenitude2mqtt/service/options_loader.py`
- Create: `tests/test_addon_options_loader.py`

In Supervisor add-ons, options the user sets in the UI are written to `/data/options.json` inside the container. The add-on reads them at startup. Additionally, the Supervisor injects MQTT credentials as `MQTT_*` env vars.

We wrap both into one `AddonOptions` dataclass.

- [ ] **Step 1: Write the failing test**

`tests/test_addon_options_loader.py`:

```python
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
```

- [ ] **Step 2: Run tests — must FAIL**

```bash
source .venv/bin/activate
pytest tests/test_addon_options_loader.py -v
```

Expected: `ModuleNotFoundError: No module named 'service.options_loader'`.

- [ ] **Step 3: Implement options_loader.py**

`addon/plenitude2mqtt/service/options_loader.py`:

```python
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
```

- [ ] **Step 4: Run tests — must PASS**

```bash
pytest tests/test_addon_options_loader.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add addon/plenitude2mqtt/service/options_loader.py tests/test_addon_options_loader.py
git commit -m "feat(addon): AddonOptions loader reads /data/options.json + MQTT env vars

Combines user-configured options (email, password, intervals) with Supervisor-
injected MQTT broker credentials. Raises ValueError if required fields missing."
```

---

## Task 3: State store (persist refresh tokens between restarts)

**Files:**
- Create: `addon/plenitude2mqtt/service/state_store.py`
- Create: `tests/test_addon_state_store.py`

When the add-on restarts (HA reboot, add-on update, etc.), we don't want to re-login from scratch. We persist:
- The Kraken refresh token + its expiry
- The portal session cookie + its expiry

In `/data/state.json` (the `/data/` dir persists across add-on restarts).

- [ ] **Step 1: Write the failing test**

`tests/test_addon_state_store.py`:

```python
"""Tests for the persistent state store."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, UTC
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "addon" / "plenitude2mqtt"))

from service.state_store import PersistedState, load_state, save_state


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    original = PersistedState(
        kraken_refresh_token="rt_abc",
        kraken_refresh_token_expires_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        portal_cookie_name="__Secure-better-auth.session_token",
        portal_cookie_value="cookie_xyz",
        portal_cookie_expires_at=datetime(2026, 5, 23, 0, 0, tzinfo=UTC),
        site_id="A-TEST0000",
    )

    save_state(original, state_file)
    loaded = load_state(state_file)

    assert loaded == original


def test_load_state_returns_none_when_file_missing(tmp_path: Path) -> None:
    state_file = tmp_path / "nonexistent.json"
    assert load_state(state_file) is None
```

- [ ] **Step 2: Run tests — must FAIL**

```bash
pytest tests/test_addon_state_store.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement state_store.py**

`addon/plenitude2mqtt/service/state_store.py`:

```python
"""Persistent state for the add-on (refresh tokens, cookies)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_STATE_PATH = Path("/data/state.json")


@dataclass(slots=True, frozen=True)
class PersistedState:
    """State that survives add-on restarts. Stored in /data/state.json."""

    kraken_refresh_token: str
    kraken_refresh_token_expires_at: datetime
    portal_cookie_name: str
    portal_cookie_value: str
    portal_cookie_expires_at: datetime
    site_id: str


def load_state(state_path: Path = DEFAULT_STATE_PATH) -> PersistedState | None:
    """Read persisted state, or return None if the file doesn't exist."""
    if not state_path.exists():
        return None
    raw = json.loads(state_path.read_text())
    return PersistedState(
        kraken_refresh_token=raw["kraken_refresh_token"],
        kraken_refresh_token_expires_at=datetime.fromisoformat(
            raw["kraken_refresh_token_expires_at"]
        ),
        portal_cookie_name=raw["portal_cookie_name"],
        portal_cookie_value=raw["portal_cookie_value"],
        portal_cookie_expires_at=datetime.fromisoformat(
            raw["portal_cookie_expires_at"]
        ),
        site_id=raw["site_id"],
    )


def save_state(state: PersistedState, state_path: Path = DEFAULT_STATE_PATH) -> None:
    """Persist state atomically (write to temp file, then rename)."""
    payload = {
        **asdict(state),
        "kraken_refresh_token_expires_at": (
            state.kraken_refresh_token_expires_at.isoformat()
        ),
        "portal_cookie_expires_at": state.portal_cookie_expires_at.isoformat(),
    }
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(state_path)
```

- [ ] **Step 4: Run tests — must PASS**

```bash
pytest tests/test_addon_state_store.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add addon/plenitude2mqtt/service/state_store.py tests/test_addon_state_store.py
git commit -m "feat(addon): PersistedState + load_state/save_state for /data/state.json

Refresh tokens and portal cookies persist across add-on restarts, so we don't
have to re-prompt the user for their password. Atomic write via tmp + rename."
```

---

## Task 4: MQTT publisher (discovery configs + state publishing)

**Files:**
- Create: `addon/plenitude2mqtt/service/mqtt_publisher.py`
- Create: `tests/test_addon_mqtt_publisher.py`

The publisher knows the 10 sensor configs (mirror of the existing custom integration's sensors), publishes them as discovery configs on startup, then publishes one state payload per polling tick.

- [ ] **Step 1: Write the failing tests**

`tests/test_addon_mqtt_publisher.py`:

```python
"""Tests for the MQTT publisher."""
from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import sys
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
    payload_raw = first_call.args[1] if len(first_call.args) > 1 else first_call.kwargs.get("payload")
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
```

- [ ] **Step 2: Run tests — must FAIL**

```bash
pytest tests/test_addon_mqtt_publisher.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement mqtt_publisher.py**

`addon/plenitude2mqtt/service/mqtt_publisher.py`:

```python
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

    async def publish(self, topic: str, payload: str | bytes, *, retain: bool = False) -> Any: ...


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
# Field name -> (human name, unit, device_class, state_class)
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
```

- [ ] **Step 4: Run tests — must PASS**

```bash
pytest tests/test_addon_mqtt_publisher.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add addon/plenitude2mqtt/service/mqtt_publisher.py tests/test_addon_mqtt_publisher.py
git commit -m "feat(addon): MqttPublisher emits discovery configs + state payloads

10 sensors mirrored from custom_components/plenitude/sensor.py. Discovery
configs are retained so HA picks them up even if it restarts after the
add-on. Availability topic for graceful offline notification."
```

---

## Task 5: Main service loop (orchestrate everything)

**Files:**
- Create: `addon/plenitude2mqtt/service/main.py`
- Create: `tests/test_addon_main.py`

The main loop:
1. Load options + state
2. Connect to MQTT (with LWT for offline)
3. Refresh Kraken token (from persisted refresh_token if exists, else password login)
4. Refresh portal session (from persisted cookie if not expired, else password login)
5. Publish discovery configs once
6. Loop: fetch consumption + tariffs → compute cost → publish state → sleep `scan_interval_hours`

- [ ] **Step 1: Write the failing tests**

This task is the most integration-flavored. Test the core orchestration logic with all the API clients mocked.

`tests/test_addon_main.py`:

```python
"""Tests for the add-on main service loop."""
from __future__ import annotations

from datetime import datetime, timedelta, UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "addon" / "plenitude2mqtt"))

from service.api.kraken import KrakenSession, ViewerInfo, AccountRef
from service.api.portal import PortalSession
from service.main import build_sensor_state, ensure_kraken_session, ensure_portal_session
from service.models import (
    ConsumptionInterval,
    ConsumptionSnapshot,
    ContractTariffs,
    HalfHourPeriod,
)


@pytest.mark.asyncio
async def test_ensure_kraken_session_uses_refresh_token_when_available() -> None:
    kraken_client = MagicMock()
    fresh = KrakenSession(
        access_token="access",
        access_token_expires_at=datetime.now(tz=UTC) + timedelta(minutes=55),
        refresh_token="rt_new",
        refresh_token_expires_in_seconds=1209600,
        account_user_id="999999",
    )
    kraken_client.refresh = AsyncMock(return_value=fresh)
    kraken_client.login = AsyncMock()

    session = await ensure_kraken_session(
        kraken_client,
        existing_refresh_token="rt_existing",
        email="a@b.c",
        password="pw",
    )

    kraken_client.refresh.assert_awaited_once_with("rt_existing")
    kraken_client.login.assert_not_awaited()
    assert session is fresh


@pytest.mark.asyncio
async def test_ensure_kraken_session_logs_in_when_no_refresh_token() -> None:
    kraken_client = MagicMock()
    fresh = KrakenSession(
        access_token="access",
        access_token_expires_at=datetime.now(tz=UTC) + timedelta(minutes=55),
        refresh_token="rt_new",
        refresh_token_expires_in_seconds=1209600,
        account_user_id="999999",
    )
    kraken_client.login = AsyncMock(return_value=fresh)
    kraken_client.refresh = AsyncMock()

    session = await ensure_kraken_session(
        kraken_client,
        existing_refresh_token=None,
        email="a@b.c",
        password="pw",
    )

    kraken_client.login.assert_awaited_once_with("a@b.c", "pw")
    kraken_client.refresh.assert_not_awaited()
    assert session is fresh


def test_build_sensor_state_computes_cost_correctly() -> None:
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

    state = build_sensor_state(
        site_id="A-TEST0000",
        snapshot=snapshot,
        tariffs=tariffs,
        now=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
    )

    assert state.site_id == "A-TEST0000"
    assert state.conso_totale_kwh == pytest.approx(2.0)
    assert state.conso_hp_kwh == pytest.approx(1.5)
    assert state.conso_hc_kwh == pytest.approx(0.5)
    assert state.tarif_hp_eur_kwh == pytest.approx(0.21114)
    # cost: 1.5 * 0.21114 + 0.5 * 0.16614 + subscription_prorated > 0
    assert state.cout_total_eur > 0
```

- [ ] **Step 2: Run tests — must FAIL**

```bash
pytest tests/test_addon_main.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement main.py**

`addon/plenitude2mqtt/service/main.py`:

```python
"""Plenitude2MQTT service entrypoint.

Polls Plenitude APIs every `scan_interval_hours` and publishes consumption,
cost, and tariff data to MQTT with Home Assistant auto-discovery.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta, UTC
from pathlib import Path

import aiohttp
import asyncio_mqtt as aiomqtt

from .api.kraken import (
    KrakenAuthError,
    KrakenError,
    KrakenSession,
    PlenitudeKrakenClient,
    ViewerInfo,
)
from .api.portal import (
    PlenitudePortalClient,
    PortalAuthError,
    PortalError,
    PortalSession,
)
from .cost import calculate_cost
from .models import ConsumptionSnapshot, ContractTariffs
from .mqtt_publisher import MqttPublisher, SensorState
from .options_loader import AddonOptions, load_options
from .state_store import PersistedState, load_state, save_state


_LOGGER = logging.getLogger("plenitude2mqtt")


SW_VERSION = "0.1.0"


def configure_logging(level: str) -> None:
    """Map add-on log levels to Python logging levels."""
    mapping = {
        "trace": logging.DEBUG,
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "notice": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "fatal": logging.CRITICAL,
    }
    logging.basicConfig(
        level=mapping.get(level.lower(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def ensure_kraken_session(
    kraken_client: PlenitudeKrakenClient,
    *,
    existing_refresh_token: str | None,
    email: str,
    password: str,
) -> KrakenSession:
    """Refresh JWT from existing refresh token, or login if none."""
    if existing_refresh_token:
        try:
            return await kraken_client.refresh(existing_refresh_token)
        except KrakenAuthError:
            _LOGGER.warning("Stored refresh token rejected; falling back to password login")
    return await kraken_client.login(email, password)


async def ensure_portal_session(
    portal_client: PlenitudePortalClient,
    *,
    existing_cookie: tuple[str, str] | None,
    existing_expires_at: datetime | None,
    email: str,
    password: str,
) -> PortalSession:
    """Use existing portal cookie if not expired, else login."""
    if existing_cookie and existing_expires_at:
        # Allow a 1-hour buffer before expiry
        if existing_expires_at - datetime.now(tz=UTC) > timedelta(hours=1):
            cookie_name, cookie_value = existing_cookie
            return PortalSession(
                cookie_name=cookie_name,
                cookie_value=cookie_value,
                expires_at=existing_expires_at,
            )
    return await portal_client.login(email, password)


def build_sensor_state(
    *,
    site_id: str,
    snapshot: ConsumptionSnapshot,
    tariffs: ContractTariffs,
    now: datetime,
) -> SensorState:
    """Assemble the SensorState from a fresh snapshot + tariffs."""
    cost = calculate_cost(snapshot, tariffs, now=now)
    return SensorState(
        site_id=site_id,
        conso_totale_kwh=snapshot.total_kwh,
        conso_hp_kwh=snapshot.total_hp_kwh,
        conso_hc_kwh=snapshot.total_hc_kwh,
        cout_total_eur=round(cost.total_eur, 4),
        cout_hp_eur=round(cost.hp_eur, 4),
        cout_hc_eur=round(cost.hc_eur, 4),
        tarif_hp_eur_kwh=tariffs.hp_eur_per_kwh,
        tarif_hc_eur_kwh=tariffs.hc_eur_per_kwh,
        abonnement_eur_mois=tariffs.subscription_eur_per_month,
        derniere_releve=snapshot.last_reading_at,
    )


async def run(options: AddonOptions) -> None:
    """Main async loop."""
    state = load_state()
    kraken_refresh_token = state.kraken_refresh_token if state else None
    portal_cookie = (
        (state.portal_cookie_name, state.portal_cookie_value) if state else None
    )
    portal_expires_at = state.portal_cookie_expires_at if state else None

    async with aiohttp.ClientSession() as http:
        kraken_client = PlenitudeKrakenClient(http)
        portal_client = PlenitudePortalClient(http)

        # Login / refresh
        kraken_session = await ensure_kraken_session(
            kraken_client,
            existing_refresh_token=kraken_refresh_token,
            email=options.email,
            password=options.password,
        )

        portal_session = await ensure_portal_session(
            portal_client,
            existing_cookie=portal_cookie,
            existing_expires_at=portal_expires_at,
            email=options.email,
            password=options.password,
        )

        # Discover account number
        viewer = await kraken_client.get_viewer(kraken_session.access_token)
        if not viewer.accounts:
            _LOGGER.error("No Plenitude accounts found for this user")
            return
        site_id = viewer.accounts[0].number

        # Persist initial state
        save_state(PersistedState(
            kraken_refresh_token=kraken_session.refresh_token,
            kraken_refresh_token_expires_at=(
                datetime.now(tz=UTC)
                + timedelta(seconds=kraken_session.refresh_token_expires_in_seconds)
            ),
            portal_cookie_name=portal_session.cookie_name,
            portal_cookie_value=portal_session.cookie_value,
            portal_cookie_expires_at=portal_session.expires_at,
            site_id=site_id,
        ))

        # Connect to MQTT
        async with aiomqtt.Client(
            hostname=options.mqtt_host,
            port=options.mqtt_port,
            username=options.mqtt_user or None,
            password=options.mqtt_password or None,
            tls_context=None if not options.mqtt_ssl else None,  # adjust if SSL needed
            will=aiomqtt.Will(
                topic=f"{options.mqtt_topic_prefix}/{site_id}/status",
                payload=b"offline",
                qos=1,
                retain=True,
            ),
        ) as mqtt_client:
            publisher = MqttPublisher(
                client=mqtt_client,
                topic_prefix=options.mqtt_topic_prefix,
                discovery_prefix=options.mqtt_discovery_prefix,
                sw_version=SW_VERSION,
            )

            # Publish discovery once
            await publisher.publish_discovery(site_id=site_id)
            await publisher.publish_availability(site_id=site_id, online=True)
            _LOGGER.info("Discovery published for site %s", site_id)

            # Main polling loop
            cached_tariffs: ContractTariffs | None = None
            last_tariff_fetch: datetime | None = None

            while True:
                try:
                    # Refresh access token proactively (5 min before expiry)
                    if (
                        kraken_session.access_token_expires_at
                        - datetime.now(tz=UTC)
                        < timedelta(minutes=5)
                    ):
                        kraken_session = await kraken_client.refresh(
                            kraken_session.refresh_token
                        )

                    # Fetch consumption
                    now = datetime.now(tz=UTC)
                    snapshot = await kraken_client.get_consumption(
                        access_token=kraken_session.access_token,
                        site_id=site_id,
                        start=now - timedelta(days=2),
                        end=now,
                        group_by="HALF_HOUR",
                    )

                    # Refresh tariffs once per day
                    if (
                        cached_tariffs is None
                        or last_tariff_fetch is None
                        or now - last_tariff_fetch > timedelta(hours=24)
                    ):
                        try:
                            cached_tariffs = await portal_client.fetch_contract(portal_session)
                            last_tariff_fetch = now
                        except PortalAuthError:
                            _LOGGER.warning(
                                "Portal session expired; re-logging in"
                            )
                            portal_session = await portal_client.login(
                                options.email, options.password
                            )
                            cached_tariffs = await portal_client.fetch_contract(portal_session)
                            last_tariff_fetch = now

                    assert cached_tariffs is not None  # appease type checker
                    state_payload = build_sensor_state(
                        site_id=site_id,
                        snapshot=snapshot,
                        tariffs=cached_tariffs,
                        now=now,
                    )
                    await publisher.publish_state(state_payload)
                    _LOGGER.info(
                        "Published: conso=%.1f kWh, coût=%.2f €",
                        state_payload.conso_totale_kwh,
                        state_payload.cout_total_eur,
                    )

                    # Save updated session state
                    save_state(PersistedState(
                        kraken_refresh_token=kraken_session.refresh_token,
                        kraken_refresh_token_expires_at=(
                            datetime.now(tz=UTC)
                            + timedelta(seconds=kraken_session.refresh_token_expires_in_seconds)
                        ),
                        portal_cookie_name=portal_session.cookie_name,
                        portal_cookie_value=portal_session.cookie_value,
                        portal_cookie_expires_at=portal_session.expires_at,
                        site_id=site_id,
                    ))

                except (KrakenError, PortalError) as err:
                    _LOGGER.error("Poll failed: %s", err)

                await asyncio.sleep(options.scan_interval_hours * 3600)


def main() -> int:
    try:
        options = load_options()
    except (FileNotFoundError, ValueError) as err:
        print(f"Configuration error: {err}", file=sys.stderr)
        return 2

    configure_logging(options.log_level)
    _LOGGER.info("Plenitude2MQTT %s starting", SW_VERSION)

    try:
        asyncio.run(run(options))
    except KeyboardInterrupt:
        _LOGGER.info("Received SIGINT, shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests — must PASS**

```bash
pytest tests/test_addon_main.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Run all tests + ruff**

```bash
pytest -v
ruff check custom_components/ addon/plenitude2mqtt/service/ tests/
```

Expected: all PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add addon/plenitude2mqtt/service/main.py tests/test_addon_main.py
git commit -m "feat(addon): main service loop — login, poll, publish, persist

- ensure_kraken_session: refresh from stored RT, fallback to password login
- ensure_portal_session: reuse cookie if not expired, else login
- build_sensor_state: assemble state from snapshot + tariffs + cost calc
- run(): connect MQTT (with LWT), publish discovery once, poll-publish loop
  every scan_interval_hours, persist session state to /data/state.json"
```

---

## Task 6: GitHub Actions — add-on build + sync check

**Files:**
- Modify: `.github/workflows/test.yml`
- Create: `.github/workflows/addon-build.yml`

- [ ] **Step 1: Add a sync-check step to test.yml**

Insert this step in `.github/workflows/test.yml` after the existing "Install dependencies" step:

```yaml
      - name: Verify add-on API client is in sync
        run: ./scripts/check_sync.sh
```

- [ ] **Step 2: Create addon-build.yml**

`.github/workflows/addon-build.yml`:

```yaml
name: Add-on build

on:
  push:
    branches: [main]
    paths:
      - 'addon/**'
      - '.github/workflows/addon-build.yml'
  pull_request:
    branches: [main]
    paths:
      - 'addon/**'

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        arch: [amd64, aarch64]
    steps:
      - uses: actions/checkout@v4

      - name: Build add-on
        uses: home-assistant/builder@2024.03.5
        with:
          args: |
            --${{ matrix.arch }} \
            --target /data/addon/plenitude2mqtt \
            --image plenitude2mqtt-{arch} \
            --version 0.1.0 \
            --test
```

Notes:
- `home-assistant/builder` action handles the multi-arch Docker build using the BUILD_FROM args declared in the Dockerfile
- `--test` means "don't push to a registry" — just build to verify it works
- Multi-arch matrix ensures the add-on builds for both x86_64 (most users) and aarch64 (Raspberry Pi 4/5)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/test.yml .github/workflows/addon-build.yml
git commit -m "ci: add sync-check + multi-arch add-on Docker build

- test.yml: verify scripts/check_sync.sh passes before running tests
- addon-build.yml: build amd64 + aarch64 images via home-assistant/builder
  on every push touching addon/"
```

---

## Task 7: Update root README to document both install paths

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README.md**

Replace the existing `## Installation via HACS` section with:

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README explains both install paths (add-on vs custom integration)

Path A (add-on, HAOS/Supervised): the native install via add-on store URL.
Path B (HACS custom repo, all setups): the existing v0.1.0 flow.
Path C (manual): for users who prefer not using HACS."
```

---

## Task 8: Tag v0.2.0 release

- [ ] **Step 1: Verify everything is committed and tests pass**

```bash
source .venv/bin/activate
pytest -v
ruff check custom_components/ addon/plenitude2mqtt/service/ tests/
./scripts/check_sync.sh
git status
```

Expected: all tests pass, ruff clean, sync OK, working tree clean.

- [ ] **Step 2: Tag the release**

```bash
git tag -a v0.2.0 -m "Release v0.2.0 — plenitude2mqtt add-on

This release adds the Supervisor add-on track. Two install paths now exist:

1. Add-on (HAOS/Supervised): adds the repo URL in Settings → Add-ons → Repositories,
   then installs Plenitude2MQTT from the store. Publishes data to MQTT with
   HA auto-discovery. Same 10 sensors as the custom integration. Native HA
   install — no HACS required.

2. Custom integration (any HA setup): unchanged from v0.1.0. Install via HACS
   or manually into custom_components/. Direct Python integration.

Both paths share the same API client code (synced via scripts/sync_api.sh and
verified by CI). Pick the one that fits your setup."

git push --tags
```

- [ ] **Step 3: Confirm the release is visible**

```bash
gh release list --limit 5
gh release view v0.2.0
```

---

## Task 9: Manual end-to-end verification (user)

This is not automatable in CI — you must validate the add-on on a real HAOS / Supervised install.

- [ ] **Step 1: Install the add-on on a HAOS test instance**

If you don't have one, the easiest is a HAOS VM via QEMU or VirtualBox. Otherwise use your real HA if you accept some risk.

1. Settings → Add-ons → Add-on Store → ⋮ → Repositories
2. Paste `https://github.com/williamboglietti/plenitude-ha` → Add
3. Find Plenitude2MQTT → Install
4. Verify the Mosquitto broker add-on is installed and running
5. Configuration tab: enter email + password → Save
6. Click **Start**

- [ ] **Step 2: Read the add-on log**

In the add-on's Log tab, expect within ~30 seconds:
```
INFO ... Plenitude2MQTT 0.1.0 starting
INFO ... MQTT broker: core-mosquitto:1883 (user=addons)
INFO ... Discovery published for site A-XXXXXXXX
INFO ... Published: conso=XXXX.X kWh, coût=XX.XX €
```

If you see an error:
- `Configuration error: email option is required` → fill the email field in Configuration
- `MQTT_HOST env var missing` → install an MQTT broker add-on (Mosquitto)
- `KrakenAuthError` → wrong Plenitude credentials
- `failed to parse tariffs from /contrat` → Plenitude has changed their page (open an issue)
- `could not scrape Next.js Server Action credentials` → Plenitude has changed the login form (open an issue)

- [ ] **Step 3: Verify the sensors appeared in HA**

Settings → Devices & services → MQTT → look for the **Plenitude — A-XXXXXXXX** device with 10 entities. All should have a value (not "Unavailable").

- [ ] **Step 4: Verify Energy dashboard integration**

Settings → Dashboards → Energy:
- Electricity grid consumption: add `sensor.plenitude_<id>_conso_totale_kwh`
- Energy cost: add `sensor.plenitude_<id>_cout_total_eur`
- Save and open the Energy dashboard — values should appear within a few hours.

- [ ] **Step 5: Verify restart resilience**

1. Restart the add-on (Stop, then Start).
2. Check the log: should resume polling without re-prompting password (refresh token reused from `/data/state.json`).
3. Restart HA itself.
4. After HA comes back up, the sensors should still have their values (MQTT retain) and resume updating once the add-on restarts automatically.

- [ ] **Step 6: Verify password rotation handling**

1. Change your Plenitude password on the customer portal.
2. Watch the add-on log: at next refresh tick, you should see `Stored refresh token rejected; falling back to password login`. With the OLD password in the add-on options, this will then fail with `KrakenAuthError`.
3. Update the password in the add-on's Configuration tab, click **Save**, then **Restart** the add-on.
4. Verify polling resumes.

- [ ] **Step 7: Document any deviations in `docs/superpowers/verification-log.md`**

Note anything that didn't work as expected — bugs to fix in v0.2.1.

---

## Self-review checklist (run BEFORE marking the plan complete)

- [ ] All tasks committed
- [ ] All tests passing (existing + new add-on tests, ~38 tests total)
- [ ] `ruff check custom_components/ addon/plenitude2mqtt/service/ tests/` clean
- [ ] `scripts/check_sync.sh` passes (API client copies are byte-identical)
- [ ] `home-assistant/builder` GitHub Actions job passes on at least amd64
- [ ] `docs/superpowers/specs/2026-05-21-plenitude-ha-design.md` not modified (the spec stands; the MQTT add-on extends the implementation without changing the design)
- [ ] No personal data leaked (check `git grep -n "Boglietti\|jacques bingen\|04574240211451"` returns nothing)
- [ ] Tag v0.2.0 pushed to remote

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-22-plenitude-mqtt-addon.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Use **superpowers:subagent-driven-development**.

**2. Inline Execution** — Execute tasks in this session using **superpowers:executing-plans**, batch execution with checkpoints.

Either way: read the related spec first (`docs/superpowers/specs/2026-05-21-plenitude-ha-design.md`) and skim the existing `custom_components/plenitude/api/*.py` to understand what's being reused. Then start with Task 1.
