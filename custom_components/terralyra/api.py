"""Shared LSA SAF Data Service HTTP client."""
from __future__ import annotations

from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout, encode_basic_auth

ALLOWED_HOST = "datalsasaf.lsasvcs.ipma.pt"
REQUEST_TIMEOUT = ClientTimeout(total=30, connect=10, sock_read=20)


class LsaSafError(Exception):
    """Base LSA SAF error."""


class LsaSafAuthError(LsaSafError):
    """Authentication error."""


class LsaSafApi:
    """Shared authenticated client for the LSA SAF Data Service.

    Credentials are kept only in the Home Assistant config entry and in the
    encoded Authorization header used by this runtime client. The plaintext
    password is intentionally not copied to a separate instance attribute.
    """

    def __init__(self, session: ClientSession, username: str, password: str) -> None:
        self._session = session
        self._headers = {"Authorization": encode_basic_auth(username, password)}


def validate_service_url(url: str) -> None:
    """Reject non-HTTPS and non-LSA SAF destinations before credentials are sent."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != ALLOWED_HOST
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise LsaSafError("Refusing an untrusted LSA SAF service URL")
