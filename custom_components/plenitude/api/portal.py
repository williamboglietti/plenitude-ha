"""HTTP client for the Plenitude espace-client portal.

Used for tariff retrieval — fetches the /contrat HTML and parses the
embedded RSC JSON. Login goes through a Next.js Server Action because
better-auth's email/password endpoint is disabled on this deployment.
"""
from __future__ import annotations

import html
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import aiohttp

from ..const import PORTAL_BASE_URL, USER_AGENT


class PortalError(Exception):
    """Base error for portal HTTP failures."""


class PortalAuthError(PortalError):
    """Authentication failure on the portal."""


@dataclass(slots=True, frozen=True)
class PortalSession:
    """The portal session cookie captured at login."""

    cookie_name: str
    cookie_value: str
    expires_at: datetime  # UTC

    @property
    def cookie_header(self) -> str:
        return f"{self.cookie_name}={self.cookie_value}"


_LOGIN_PATH = "/auth/connexion"
_SESSION_COOKIE_NAME = "__Secure-better-auth.session_token"

# Captured at design time from a real /consommation POST. The router state tree
# only depends on the route structure (not the user), so a static value is fine.
_DEFAULT_ROUTER_STATE_TREE = (
    "%5B%22%22%2C%7B%22children%22%3A%5B%5B%22locale%22%2C%22fr-FR%22%2C%22d%22%2C"
    "null%5D%2C%7B%22children%22%3A%5B%22auth%22%2C%7B%22children%22%3A%5B%22signin%22%2C"
    "%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2Cnull%2Cnull%2C0%5D%7D%2Cnull%2Cnull%2C0%5D%7D%2C"
    "null%2Cnull%2C0%5D%7D%2Cnull%2Cnull%2C16%5D"
)

# Regex to extract the Server Action hash from the form's $ACTION_1:0 hidden input
# Example match: value="{&quot;id&quot;:&quot;<hash>&quot;,&quot;bound&quot;:&quot;$@1&quot;}"
_ACTION_HASH_RE = re.compile(
    r'name="\$ACTION_1:0"\s+value="([^"]+)"',
    re.IGNORECASE,
)
_ACTION_KEY_RE = re.compile(
    r'name="\$ACTION_KEY"\s+value="([^"]+)"',
    re.IGNORECASE,
)


class PlenitudePortalClient:
    """Async client for the Plenitude portal."""

    def __init__(self, http: aiohttp.ClientSession, *, base_url: str = PORTAL_BASE_URL) -> None:
        self._http = http
        self._base_url = base_url

    async def login(self, email: str, password: str) -> PortalSession:
        """Authenticate via Next.js Server Action and return a PortalSession."""
        action_id, action_key = await self._scrape_action_credentials()
        return await self._post_login(email, password, action_id, action_key)

    async def _scrape_action_credentials(self) -> tuple[str, str]:
        """Fetch /auth/connexion HTML and extract the Server Action hash + key."""
        url = f"{self._base_url}{_LOGIN_PATH}"
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
        }
        try:
            async with self._http.get(url, headers=headers) as resp:
                if resp.status >= 400:
                    raise PortalError(f"portal login page HTTP {resp.status}")
                html_text = await resp.text()
        except aiohttp.ClientError as err:
            raise PortalError(f"portal login page HTTP error: {err}") from err

        action_match = _ACTION_HASH_RE.search(html_text)
        key_match = _ACTION_KEY_RE.search(html_text)
        if not action_match or not key_match:
            raise PortalAuthError(
                "could not scrape Next.js Server Action credentials from the login page; "
                "Plenitude may have changed the page structure"
            )
        # The value attribute is HTML-escaped. Decode &quot; -> ", etc.
        action_value_decoded = html.unescape(action_match.group(1))
        # action_value_decoded is JSON like {"id":"<hash>","bound":"$@1"}
        id_match = re.search(r'"id"\s*:\s*"([0-9a-f]+)"', action_value_decoded)
        if not id_match:
            raise PortalAuthError("could not extract action id from scraped value")
        return id_match.group(1), html.unescape(key_match.group(1))

    async def _post_login(
        self, email: str, password: str, action_id: str, action_key: str
    ) -> PortalSession:
        """POST the Next.js Server Action form to /auth/connexion."""
        url = f"{self._base_url}{_LOGIN_PATH}"
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        body = _build_login_body(boundary, action_id, action_key, email, password)
        headers = {
            "Accept": "text/x-component",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": USER_AGENT,
            "next-action": action_id,
            "next-router-state-tree": _DEFAULT_ROUTER_STATE_TREE,
            "Origin": self._base_url,
            "Referer": f"{self._base_url}{_LOGIN_PATH}",
        }
        try:
            async with self._http.post(
                url, data=body, headers=headers, allow_redirects=False
            ) as resp:
                if resp.status in (401, 403):
                    raise PortalAuthError(f"portal login rejected: HTTP {resp.status}")
                if resp.status >= 400:
                    raise PortalError(f"portal login HTTP {resp.status}")
                # Get all Set-Cookie headers
                set_cookies = resp.headers.getall("Set-Cookie", [])
        except aiohttp.ClientError as err:
            raise PortalError(f"portal login HTTP error: {err}") from err

        cookie_value, max_age = _find_session_cookie(set_cookies, _SESSION_COOKIE_NAME)
        if not cookie_value:
            raise PortalAuthError(
                "login response did not set the session cookie — credentials likely invalid"
            )
        expires_at = datetime.now(tz=UTC) + timedelta(seconds=max_age or 86400)
        return PortalSession(
            cookie_name=_SESSION_COOKIE_NAME,
            cookie_value=cookie_value,
            expires_at=expires_at,
        )


def _build_login_body(
    boundary: str, action_id: str, action_key: str, email: str, password: str
) -> bytes:
    """Build the multipart body for the Server Action POST."""
    crlf = "\r\n"
    parts = [
        ("_1_$ACTION_REF_1", ""),
        ("_1_$ACTION_1:0", f'{{"id":"{action_id}","bound":"$@1"}}'),
        ("_1_$ACTION_1:1", '[{"status":"idle"}]'),
        ("_1_$ACTION_KEY", action_key),
        ("_1_email", email),
        ("_1_password", password),
        ("0", '[{"status":"idle"},"$K1"]'),
    ]
    lines: list[str] = []
    for name, value in parts:
        lines.append(f"--{boundary}")
        lines.append(f'Content-Disposition: form-data; name="{name}"')
        lines.append("")
        lines.append(value)
    lines.append(f"--{boundary}--")
    lines.append("")
    return crlf.join(lines).encode("utf-8")


def _find_session_cookie(
    set_cookies: list[str], name: str
) -> tuple[str | None, int | None]:
    """Return (value, max_age) for the named cookie from a list of Set-Cookie headers."""
    for header in set_cookies:
        for cookie_part in re.split(r",(?=[^,]+?=)", header):
            cookie_part = cookie_part.strip()
            if cookie_part.startswith(f"{name}="):
                value = cookie_part.split("=", 1)[1].split(";", 1)[0]
                max_age_match = re.search(r"Max-Age=(\d+)", cookie_part, re.IGNORECASE)
                max_age = int(max_age_match.group(1)) if max_age_match else None
                return value, max_age
    return None, None
