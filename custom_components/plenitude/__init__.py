"""The Plenitude integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.kraken import PlenitudeKrakenClient
from .api.portal import PlenitudePortalClient, PortalSession
from .const import (
    CONF_PORTAL_COOKIE,
    CONF_PORTAL_COOKIE_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL_HOURS,
    CONF_SITE_ID,
    DOMAIN,
)
from .coordinator import PlenitudeCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Plenitude from a config entry."""
    http = async_get_clientsession(hass)
    kraken_client = PlenitudeKrakenClient(http)
    portal_client = PlenitudePortalClient(http)

    # Refresh JWT immediately on setup using the stored refresh token
    refresh_token = entry.data[CONF_REFRESH_TOKEN]
    kraken_session = await kraken_client.refresh(refresh_token)

    cookie_data = entry.data[CONF_PORTAL_COOKIE]
    portal_session = PortalSession(
        cookie_name=cookie_data["name"],
        cookie_value=cookie_data["value"],
        expires_at=datetime.fromisoformat(entry.data[CONF_PORTAL_COOKIE_EXPIRES_AT]),
    )

    scan_interval = timedelta(hours=entry.data.get(CONF_SCAN_INTERVAL_HOURS, 1))

    coordinator = PlenitudeCoordinator(
        hass=hass,
        kraken_client=kraken_client,
        portal_client=portal_client,
        kraken_session=kraken_session,
        portal_session=portal_session,
        account_number=entry.data[CONF_SITE_ID],
        scan_interval=scan_interval,
    )

    # Persist the rotated refresh token (Kraken issues a new one on each refresh)
    if kraken_session.refresh_token != refresh_token:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_REFRESH_TOKEN: kraken_session.refresh_token},
        )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "kraken_client": kraken_client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Plenitude config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False

    stored = hass.data[DOMAIN].pop(entry.entry_id, None)
    if stored is not None:
        kraken_client: PlenitudeKrakenClient = stored["kraken_client"]
        # Best-effort: revoke the stored refresh token server-side
        try:
            await kraken_client.invalidate_refresh_token(entry.data[CONF_REFRESH_TOKEN])
        except Exception:  # noqa: BLE001 — never block unload on cleanup
            _LOGGER.debug("invalidate_refresh_token failed on unload", exc_info=True)

    return True
