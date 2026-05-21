"""GraphQL client for the Kraken Tech API (Plenitude France)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import aiohttp

from ..const import KRAKEN_GRAPHQL_URL, USER_AGENT
from ..models import ConsumptionInterval, ConsumptionSnapshot

_BFF_CONSUMPTION_URL = (
    "https://portal-api.eniplenitude.fr/api/trpc/b2c.consumptions.getBySiteIds"
)


class KrakenError(Exception):
    """Base error for Kraken API failures."""


class KrakenAuthError(KrakenError):
    """Authentication-related Kraken error (invalid credentials, refresh failed, etc.)."""


@dataclass(slots=True, frozen=True)
class KrakenSession:
    """Represents the tokens returned by obtainKrakenToken."""

    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_in_seconds: int
    account_user_id: str | None = None  # extracted from JWT.sub when available


@dataclass(slots=True, frozen=True)
class AccountRef:
    """A Kraken account reference."""

    number: str
    status: str


@dataclass(slots=True, frozen=True)
class ViewerInfo:
    """The authenticated user's basic profile."""

    user_id: str
    email: str
    given_name: str | None
    accounts: tuple[AccountRef, ...]


_OBTAIN_TOKEN_MUTATION = """
mutation ObtainKrakenToken($input: ObtainJSONWebTokenInput!) {
  obtainKrakenToken(input: $input) {
    token
    refreshToken
    refreshExpiresIn
    payload
  }
}
""".strip()

_INVALIDATE_REFRESH_MUTATION = """
mutation InvalidateRefreshToken($input: InvalidateRefreshTokenInput!) {
  invalidateRefreshToken(input: $input) { success }
}
""".strip()

_VIEWER_QUERY = """
query ViewerWithAccounts {
  viewer {
    id
    email
    givenName
    accounts { number status }
  }
}
""".strip()


class PlenitudeKrakenClient:
    """Async client for the Plenitude / Kraken Tech GraphQL endpoint."""

    def __init__(self, http: aiohttp.ClientSession, *, endpoint: str = KRAKEN_GRAPHQL_URL) -> None:
        self._http = http
        self._endpoint = endpoint

    async def login(self, email: str, password: str) -> KrakenSession:
        """Authenticate with email/password and return a KrakenSession."""
        return await self._obtain_token({"email": email, "password": password})

    async def refresh(self, refresh_token: str) -> KrakenSession:
        """Exchange a refresh token for a new KrakenSession."""
        return await self._obtain_token({"refreshToken": refresh_token})

    async def get_viewer(self, access_token: str) -> ViewerInfo:
        """Fetch the authenticated user and their accounts."""
        resp = await self._post({"query": _VIEWER_QUERY}, access_token=access_token)
        errors = resp.get("errors")
        if errors:
            raise _classify_errors(errors)
        data = (resp.get("data") or {}).get("viewer")
        if not data:
            raise KrakenError("viewer query returned no data")
        accounts = tuple(
            AccountRef(number=a["number"], status=a["status"])
            for a in data.get("accounts") or []
        )
        return ViewerInfo(
            user_id=str(data["id"]),
            email=str(data["email"]),
            given_name=data.get("givenName"),
            accounts=accounts,
        )

    async def invalidate_refresh_token(self, refresh_token: str) -> None:
        """Best-effort cleanup: invalidate a refresh token. Never raises."""
        body = {
            "query": _INVALIDATE_REFRESH_MUTATION,
            "variables": {"input": {"refreshToken": refresh_token}},
        }
        try:
            await self._post(body)
        except KrakenError:
            # Swallowed: this is a cleanup-on-unload path; failure shouldn't bubble.
            return

    async def get_consumption(
        self,
        *,
        access_token: str,
        site_id: str,
        start: datetime,
        end: datetime,
        group_by: str = "HALF_HOUR",
    ) -> ConsumptionSnapshot:
        """Fetch a consumption snapshot for the given range.

        Routes through the Plenitude BFF tRPC endpoint
        (portal-api.eniplenitude.fr/api/trpc/b2c.consumptions.getBySiteIds), which
        wraps the Kraken Tech detailedMeasures query and exposes a friendlier
        JSON shape with HP/HC breakdown already separated.

        The BFF accepts the same Kraken JWT as the direct GraphQL endpoint.
        """
        input_payload = {
            "json": {
                "startAt": start.isoformat().replace("+00:00", "Z"),
                "endAt": end.isoformat().replace("+00:00", "Z"),
                "sites": [{"id": site_id, "type": "ELECTRICITY"}],
                "groupBy": group_by,
            },
            "meta": {
                "values": {
                    "startAt": ["Date"],
                    "endAt": ["Date"],
                }
            },
        }
        url = f"{_BFF_CONSUMPTION_URL}?input={quote(json.dumps(input_payload), safe='')}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "x-portal-app-version": "3.23.1+8da6e0c4",
            "x-trpc-source": "nextjs-react",
            "Origin": "https://espace-client.eniplenitude.fr",
            "Referer": "https://espace-client.eniplenitude.fr/",
        }
        try:
            async with self._http.get(url, headers=headers) as resp:
                if resp.status in (401, 403):
                    raise KrakenAuthError(f"BFF tRPC rejected token: HTTP {resp.status}")
                if resp.status >= 500:
                    raise KrakenError(f"BFF tRPC returned HTTP {resp.status}")
                body: dict[str, Any] = await resp.json()
        except aiohttp.ClientError as err:
            raise KrakenError(f"BFF tRPC HTTP error: {err}") from err

        return self._parse_bff_consumption(body, site_id)

    @staticmethod
    def _parse_bff_consumption(body: dict[str, Any], site_id: str) -> ConsumptionSnapshot:
        """Parse the BFF tRPC consumption response into a ConsumptionSnapshot."""
        sites = (((body.get("result") or {}).get("data") or {}).get("json")) or []
        site_data = next((s for s in sites if s.get("siteId") == site_id), None)
        if site_data is None:
            return ConsumptionSnapshot(site_id=site_id)

        electricity = site_data.get("electricity") or {}
        raw_intervals = electricity.get("consumptions") or []

        intervals: list[ConsumptionInterval] = []
        last_reading: datetime | None = None
        for raw in raw_intervals:
            read_at_str = raw.get("readAt")
            if not read_at_str:
                continue
            interval_start = datetime.fromisoformat(read_at_str.replace("Z", "+00:00"))
            if last_reading is None or interval_start > last_reading:
                last_reading = interval_start

            kwh_total = float(raw.get("value") or 0)
            details = raw.get("details") or []
            kwh_hp = next(
                (float(d.get("value") or 0) for d in details if d.get("type") == "HP"),
                0.0,
            )
            kwh_hc = next(
                (float(d.get("value") or 0) for d in details if d.get("type") == "HC"),
                0.0,
            )

            intervals.append(
                ConsumptionInterval(
                    start=interval_start,
                    end=interval_start,
                    kwh_total=kwh_total,
                    kwh_hp=kwh_hp,
                    kwh_hc=kwh_hc,
                    unit="kWh",
                )
            )

        return ConsumptionSnapshot(
            site_id=site_id,
            intervals=tuple(intervals),
            last_reading_at=last_reading,
        )

    async def _obtain_token(self, input_payload: dict[str, Any]) -> KrakenSession:
        body = {
            "query": _OBTAIN_TOKEN_MUTATION,
            "variables": {"input": input_payload},
        }
        resp = await self._post(body)
        errors = resp.get("errors")
        if errors:
            raise _classify_errors(errors)
        data = (resp.get("data") or {}).get("obtainKrakenToken")
        if not data or not data.get("token"):
            raise KrakenAuthError("obtainKrakenToken returned no token")
        payload = data.get("payload") or {}
        exp = payload.get("exp")
        if not isinstance(exp, int):
            raise KrakenAuthError("obtainKrakenToken payload missing exp")
        refresh_expires_in = data.get("refreshExpiresIn")
        if not isinstance(refresh_expires_in, int):
            raise KrakenAuthError("obtainKrakenToken response missing refreshExpiresIn")
        return KrakenSession(
            access_token=data["token"],
            access_token_expires_at=datetime.fromtimestamp(exp, tz=UTC),
            refresh_token=data["refreshToken"],
            refresh_token_expires_in_seconds=refresh_expires_in,
            account_user_id=_account_user_id_from_sub(payload.get("sub")),
        )

    async def _post(
        self, body: dict[str, Any], *, access_token: str | None = None
    ) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            async with self._http.post(self._endpoint, json=body, headers=headers) as resp:
                if resp.status >= 500:
                    raise KrakenError(f"Kraken returned HTTP {resp.status}")
                data: dict[str, Any] = await resp.json()
                return data
        except aiohttp.ClientError as err:
            raise KrakenError(f"Kraken HTTP error: {err}") from err


_AUTH_ERROR_CODES = frozenset({
    "KT-CT-1111",  # unauthorized
    "KT-CT-1124",  # JWT signature expired
    "KT-CT-1134",  # invalid refresh token (best-effort guess; treat as auth)
    "KT-CT-1138",  # invalid credentials
})


def _classify_errors(errors: list[dict[str, Any]]) -> KrakenError:
    """Return KrakenAuthError for auth-related codes, KrakenError otherwise."""
    for err in errors:
        code = (err.get("extensions") or {}).get("errorCode")
        if code in _AUTH_ERROR_CODES:
            return KrakenAuthError(_format_errors(errors))
    return KrakenError(_format_errors(errors))


def _format_errors(errors: list[dict[str, Any]]) -> str:
    parts = []
    for e in errors:
        code = (e.get("extensions") or {}).get("errorCode") or ""
        msg = e.get("message") or ""
        formatted = f"[{code}] {msg}".strip() if code else msg.strip()
        parts.append(formatted)
    return "; ".join(parts) or "unknown Kraken error"


def _account_user_id_from_sub(sub: str | None) -> str | None:
    """Extract numeric ID from sub like 'krakenaccount-user:999999'."""
    if not isinstance(sub, str):
        return None
    if ":" not in sub:
        return None
    return sub.split(":", 1)[1]
