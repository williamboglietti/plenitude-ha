"""Plenitude2MQTT service entrypoint.

Polls Plenitude APIs every `scan_interval_hours` and publishes consumption,
cost, and tariff data to MQTT with Home Assistant auto-discovery.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta

import aiohttp
import aiomqtt

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
            _LOGGER.warning(
                "Stored refresh token rejected; falling back to password login"
            )
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


def _start_of_month(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def build_sensor_state(
    *,
    site_id: str,
    snapshot: ConsumptionSnapshot,
    tariffs: ContractTariffs,
    now: datetime,
) -> SensorState:
    """Assemble the SensorState from a fresh snapshot + tariffs.

    Consumption and cost are aggregated **from the 1st of the current month**.
    HA's `total_increasing` state class then sees a monotonically growing value
    that resets on the 1st (the Energy dashboard handles this as a normal meter
    cycle). The caller must fetch a snapshot covering at least from the 1st of
    the month to `now`.
    """
    month_start = _start_of_month(now)
    monthly = ConsumptionSnapshot(
        site_id=snapshot.site_id,
        intervals=tuple(i for i in snapshot.intervals if i.start >= month_start),
        last_reading_at=snapshot.last_reading_at,
    )
    cost = calculate_cost(monthly, tariffs, now=now)
    return SensorState(
        site_id=site_id,
        conso_totale_kwh=round(monthly.total_kwh, 3),
        conso_hp_kwh=round(monthly.total_hp_kwh, 3),
        conso_hc_kwh=round(monthly.total_hc_kwh, 3),
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
        save_state(
            PersistedState(
                kraken_refresh_token=kraken_session.refresh_token,
                kraken_refresh_token_expires_at=(
                    datetime.now(tz=UTC)
                    + timedelta(
                        seconds=kraken_session.refresh_token_expires_in_seconds
                    )
                ),
                portal_cookie_name=portal_session.cookie_name,
                portal_cookie_value=portal_session.cookie_value,
                portal_cookie_expires_at=portal_session.expires_at,
                site_id=site_id,
            )
        )

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

                    # Fetch consumption. Window must cover the 1st of the
                    # current month (build_sensor_state aggregates from there),
                    # plus a 2-day cushion for Enedis' publication delay. On the
                    # first days of a new month, fall back to a 14-day window so
                    # we still have something to publish.
                    now = datetime.now(tz=UTC)
                    fetch_start = min(
                        _start_of_month(now) - timedelta(days=2),
                        now - timedelta(days=14),
                    )
                    snapshot = await kraken_client.get_consumption(
                        access_token=kraken_session.access_token,
                        site_id=site_id,
                        start=fetch_start,
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
                            cached_tariffs = await portal_client.fetch_contract(
                                portal_session
                            )
                            last_tariff_fetch = now
                        except PortalAuthError:
                            _LOGGER.warning(
                                "Portal session expired; re-logging in"
                            )
                            portal_session = await portal_client.login(
                                options.email, options.password
                            )
                            cached_tariffs = await portal_client.fetch_contract(
                                portal_session
                            )
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
                    save_state(
                        PersistedState(
                            kraken_refresh_token=kraken_session.refresh_token,
                            kraken_refresh_token_expires_at=(
                                datetime.now(tz=UTC)
                                + timedelta(
                                    seconds=kraken_session.refresh_token_expires_in_seconds
                                )
                            ),
                            portal_cookie_name=portal_session.cookie_name,
                            portal_cookie_value=portal_session.cookie_value,
                            portal_cookie_expires_at=portal_session.expires_at,
                            site_id=site_id,
                        )
                    )

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
