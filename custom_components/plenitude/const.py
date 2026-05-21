"""Constants for the Plenitude integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "plenitude"

# Kraken GraphQL endpoint
KRAKEN_GRAPHQL_URL = "https://api.plenitudefr-kraken.energy/v1/graphql/"

# Plenitude portal
PORTAL_BASE_URL = "https://espace-client.eniplenitude.fr"
PORTAL_CONTRACT_PATH = "/contrat"

# Default polling intervals
DEFAULT_SCAN_INTERVAL = timedelta(hours=1)
MIN_SCAN_INTERVAL = timedelta(minutes=15)
TARIFF_REFRESH_INTERVAL = timedelta(hours=24)

# JWT refresh thresholds
JWT_REFRESH_LEAD_TIME = timedelta(minutes=5)  # refresh access token if exp < now + 5min

# Config flow keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"  # used only at config flow, never stored
CONF_REFRESH_TOKEN = "kraken_refresh_token"
CONF_REFRESH_TOKEN_EXPIRES_AT = "kraken_refresh_token_expires_at"
CONF_PORTAL_COOKIE = "portal_session_cookie"
CONF_PORTAL_COOKIE_EXPIRES_AT = "portal_cookie_expires_at"
CONF_SITE_ID = "site_id"
CONF_PDL = "pdl"
CONF_TARIFF_HP_TTC = "tariff_hp_ttc"  # €/kWh
CONF_TARIFF_HC_TTC = "tariff_hc_ttc"  # €/kWh
CONF_TARIFF_SUBSCRIPTION_TTC = "tariff_subscription_ttc"  # €/month
CONF_HP_PERIODS = "hp_periods"  # list of {start: "HH:MM:SS", end: "HH:MM:SS"}
CONF_HC_PERIODS = "hc_periods"
CONF_SCAN_INTERVAL_HOURS = "scan_interval_hours"

# User-Agent
USER_AGENT = "plenitude-ha/0.1.0 (+https://github.com/williamdupont/plenitude-ha)"
