"""DataUpdateCoordinator orchestrating Kraken + Portal clients."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.kraken import (
    KrakenAuthError,
    KrakenError,
    KrakenSession,
    PlenitudeKrakenClient,
)
from .api.portal import (
    PlenitudePortalClient,
    PortalAuthError,
    PortalError,
    PortalSession,
)
from .const import DOMAIN, JWT_REFRESH_LEAD_TIME, TARIFF_REFRESH_INTERVAL
from .models import ConsumptionSnapshot, ContractTariffs

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class PlenitudeData:
    """Snapshot of all data refreshed each tick."""

    consumption: ConsumptionSnapshot
    tariffs: ContractTariffs


class PlenitudeCoordinator(DataUpdateCoordinator[PlenitudeData]):
    """Coordinator that pulls consumption from Kraken BFF and tariffs from the portal."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        kraken_client: PlenitudeKrakenClient,
        portal_client: PlenitudePortalClient,
        kraken_session: KrakenSession,
        portal_session: PortalSession,
        account_number: str,
        scan_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=DOMAIN,
            update_interval=scan_interval,
        )
        self._kraken_client = kraken_client
        self._portal_client = portal_client
        self._kraken_session = kraken_session
        self._portal_session = portal_session
        self._account_number = account_number
        self._cached_tariffs: ContractTariffs | None = None
        self._tariffs_fetched_at: datetime | None = None

    @property
    def kraken_session(self) -> KrakenSession:
        return self._kraken_session

    @property
    def portal_session(self) -> PortalSession:
        return self._portal_session

    async def _async_update_data(self) -> PlenitudeData:
        """Refresh consumption every tick and tariffs once per day."""
        await self._ensure_fresh_kraken_token()
        snapshot = await self._fetch_consumption_with_retry()
        tariffs = await self._ensure_tariffs_loaded()
        return PlenitudeData(consumption=snapshot, tariffs=tariffs)

    async def _ensure_fresh_kraken_token(self) -> None:
        """Refresh the access token proactively if near expiry."""
        now = datetime.now(tz=UTC)
        if self._kraken_session.access_token_expires_at - now > JWT_REFRESH_LEAD_TIME:
            return
        try:
            self._kraken_session = await self._kraken_client.refresh(
                self._kraken_session.refresh_token
            )
        except KrakenAuthError as err:
            raise UpdateFailed(f"Kraken refresh failed: {err}") from err

    async def _fetch_consumption_with_retry(self) -> ConsumptionSnapshot:
        """Fetch consumption; if KrakenAuthError, refresh tokens and retry once."""
        now = datetime.now(tz=UTC)
        start = now - timedelta(days=2)
        try:
            return await self._kraken_client.get_consumption(
                access_token=self._kraken_session.access_token,
                site_id=self._account_number,
                start=start,
                end=now,
                group_by="HALF_HOUR",
            )
        except KrakenAuthError as err:
            _LOGGER.info(
                "Kraken access token rejected mid-flight: %s; refreshing", err
            )
        except KrakenError as err:
            raise UpdateFailed(f"Kraken error: {err}") from err

        try:
            self._kraken_session = await self._kraken_client.refresh(
                self._kraken_session.refresh_token
            )
        except KrakenAuthError as err:
            raise UpdateFailed(
                f"Kraken refresh failed after mid-flight auth error: {err}"
            ) from err

        try:
            return await self._kraken_client.get_consumption(
                access_token=self._kraken_session.access_token,
                site_id=self._account_number,
                start=start,
                end=now,
                group_by="HALF_HOUR",
            )
        except KrakenAuthError as err:
            raise UpdateFailed(f"Kraken still rejects after refresh: {err}") from err
        except KrakenError as err:
            raise UpdateFailed(f"Kraken error after refresh: {err}") from err

    async def _ensure_tariffs_loaded(self) -> ContractTariffs:
        """Fetch tariffs once per day, cache between fetches."""
        now = datetime.now(tz=UTC)
        if (
            self._cached_tariffs is not None
            and self._tariffs_fetched_at is not None
            and now - self._tariffs_fetched_at < TARIFF_REFRESH_INTERVAL
        ):
            return self._cached_tariffs
        try:
            tariffs = await self._portal_client.fetch_contract(self._portal_session)
        except PortalAuthError:
            _LOGGER.warning(
                "Portal session expired; using cached tariffs. Re-auth required."
            )
            if self._cached_tariffs is None:
                raise
            return self._cached_tariffs
        except PortalError as err:
            _LOGGER.warning(
                "Portal error: %s; using cached tariffs if available", err
            )
            if self._cached_tariffs is None:
                raise UpdateFailed(f"Portal error: {err}") from err
            return self._cached_tariffs
        self._cached_tariffs = tariffs
        self._tariffs_fetched_at = now
        return tariffs

    def replace_kraken_session(self, session: KrakenSession) -> None:
        """Inject a fresh KrakenSession (e.g. after manual re-auth)."""
        self._kraken_session = session

    def replace_portal_session(self, session: PortalSession) -> None:
        """Inject a fresh PortalSession (e.g. after manual re-auth)."""
        self._portal_session = session
