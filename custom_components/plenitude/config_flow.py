"""Config flow for the Plenitude integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from .api.kraken import KrakenAuthError, KrakenError, PlenitudeKrakenClient
from .api.portal import PlenitudePortalClient, PortalAuthError, PortalError
from .const import (
    CONF_EMAIL,
    CONF_HC_PERIODS,
    CONF_HP_PERIODS,
    CONF_PASSWORD,
    CONF_PORTAL_COOKIE,
    CONF_PORTAL_COOKIE_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_REFRESH_TOKEN_EXPIRES_AT,
    CONF_SCAN_INTERVAL_HOURS,
    CONF_SITE_ID,
    CONF_TARIFF_HC_TTC,
    CONF_TARIFF_HP_TTC,
    CONF_TARIFF_SUBSCRIPTION_TTC,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .models import ContractTariffs

_LOGGER = logging.getLogger(__name__)

_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
        ),
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


class PlenitudeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Plenitude config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._kraken_refresh_token: str | None = None
        self._kraken_refresh_expires_in: int | None = None
        self._portal_cookie_name: str | None = None
        self._portal_cookie_value: str | None = None
        self._portal_cookie_expires_at: str | None = None
        self._account_number: str | None = None
        self._detected_tariffs: ContractTariffs | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect credentials, test both logins, fetch tariffs."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            try:
                async with aiohttp.ClientSession() as http:
                    kraken_client = PlenitudeKrakenClient(http)
                    portal_client = PlenitudePortalClient(http)

                    try:
                        k_session = await kraken_client.login(email, password)
                    except KrakenAuthError:
                        errors["base"] = "invalid_auth"
                    except KrakenError:
                        errors["base"] = "cannot_connect"
                    else:
                        try:
                            viewer = await kraken_client.get_viewer(k_session.access_token)
                        except KrakenError:
                            errors["base"] = "cannot_connect"
                        else:
                            if not viewer.accounts:
                                errors["base"] = "cannot_connect"
                            else:
                                self._account_number = viewer.accounts[0].number

                                try:
                                    p_session = await portal_client.login(email, password)
                                except PortalAuthError:
                                    errors["base"] = "invalid_auth"
                                except PortalError:
                                    errors["base"] = "cannot_connect"
                                else:
                                    try:
                                        tariffs = await portal_client.fetch_contract(
                                            p_session
                                        )
                                    except (PortalAuthError, PortalError) as err:
                                        _LOGGER.warning(
                                            "Could not auto-detect tariffs: %s; "
                                            "user will enter manually",
                                            err,
                                        )
                                        tariffs = None

                                    self._email = email
                                    self._kraken_refresh_token = k_session.refresh_token
                                    self._kraken_refresh_expires_in = (
                                        k_session.refresh_token_expires_in_seconds
                                    )
                                    self._portal_cookie_name = p_session.cookie_name
                                    self._portal_cookie_value = p_session.cookie_value
                                    self._portal_cookie_expires_at = (
                                        p_session.expires_at.isoformat()
                                    )
                                    self._detected_tariffs = tariffs

                                    await self.async_set_unique_id(self._account_number)
                                    self._abort_if_unique_id_configured()
                                    return await self.async_step_tariffs()
            except aiohttp.ClientError as err:
                _LOGGER.error("Network error during config flow: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user", data_schema=_USER_SCHEMA, errors=errors
        )

    async def async_step_tariffs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show detected tariffs, allow editing, then create the entry."""
        detected = self._detected_tariffs
        defaults = {
            CONF_TARIFF_HP_TTC: detected.hp_eur_per_kwh if detected else 0.0,
            CONF_TARIFF_HC_TTC: detected.hc_eur_per_kwh if detected else 0.0,
            CONF_TARIFF_SUBSCRIPTION_TTC: (
                detected.subscription_eur_per_month if detected else 0.0
            ),
            CONF_SCAN_INTERVAL_HOURS: int(DEFAULT_SCAN_INTERVAL.total_seconds() // 3600),
        }
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TARIFF_HP_TTC, default=defaults[CONF_TARIFF_HP_TTC]
                ): vol.Coerce(float),
                vol.Required(
                    CONF_TARIFF_HC_TTC, default=defaults[CONF_TARIFF_HC_TTC]
                ): vol.Coerce(float),
                vol.Required(
                    CONF_TARIFF_SUBSCRIPTION_TTC,
                    default=defaults[CONF_TARIFF_SUBSCRIPTION_TTC],
                ): vol.Coerce(float),
                vol.Required(
                    CONF_SCAN_INTERVAL_HOURS,
                    default=defaults[CONF_SCAN_INTERVAL_HOURS],
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=int(MIN_SCAN_INTERVAL.total_seconds() // 3600)),
                ),
            }
        )

        if user_input is None:
            return self.async_show_form(step_id="tariffs", data_schema=schema)

        hp_periods = [
            {"start": p.start, "end": p.end}
            for p in (detected.hp_periods if detected else ())
        ]
        hc_periods = [
            {"start": p.start, "end": p.end}
            for p in (detected.hc_periods if detected else ())
        ]

        return self.async_create_entry(
            title=f"Plenitude — {self._account_number}",
            data={
                CONF_EMAIL: self._email,
                CONF_REFRESH_TOKEN: self._kraken_refresh_token,
                CONF_REFRESH_TOKEN_EXPIRES_AT: self._kraken_refresh_expires_in,
                CONF_PORTAL_COOKIE: {
                    "name": self._portal_cookie_name,
                    "value": self._portal_cookie_value,
                },
                CONF_PORTAL_COOKIE_EXPIRES_AT: self._portal_cookie_expires_at,
                CONF_SITE_ID: self._account_number,
                CONF_TARIFF_HP_TTC: user_input[CONF_TARIFF_HP_TTC],
                CONF_TARIFF_HC_TTC: user_input[CONF_TARIFF_HC_TTC],
                CONF_TARIFF_SUBSCRIPTION_TTC: user_input[CONF_TARIFF_SUBSCRIPTION_TTC],
                CONF_HP_PERIODS: hp_periods,
                CONF_HC_PERIODS: hc_periods,
                CONF_SCAN_INTERVAL_HOURS: user_input[CONF_SCAN_INTERVAL_HOURS],
            },
        )
