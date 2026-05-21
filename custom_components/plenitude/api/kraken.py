"""GraphQL client for the Kraken Tech API (Plenitude France)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiohttp

from ..const import KRAKEN_GRAPHQL_URL, USER_AGENT


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
                return await resp.json()
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
