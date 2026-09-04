"""Shared LSA SAF Data Service HTTP client."""
from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlsplit

from aiohttp import BasicAuth, ClientSession, ClientTimeout

ALLOWED_HOST = "datalsasaf.lsasvcs.ipma.pt"
REQUEST_TIMEOUT = ClientTimeout(total=30, connect=10, sock_read=20)


class LsaSafError(Exception):
    """Base LSA SAF error."""

    failure_type = "invalid_response"

    def __init__(
        self, message: str = "", *, retry_after: timedelta | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LsaSafAuthError(LsaSafError):
    """Authentication error."""

    failure_type = "authentication"


class LsaSafRateLimitError(LsaSafError):
    """The LSA SAF service requested slower polling."""

    failure_type = "rate_limit"


class LsaSafServiceUnavailableError(LsaSafError):
    """The LSA SAF service is temporarily unavailable."""

    failure_type = "service_outage"


class LsaSafTimeoutError(LsaSafServiceUnavailableError):
    """The bounded LSA SAF request timed out."""

    failure_type = "timeout"


class LsaSafApi:
    """Shared authenticated client for the LSA SAF Data Service.

    Credentials are kept only in the Home Assistant config entry and in the
    encoded Authorization header used by this runtime client. The plaintext
    password is intentionally not copied to a separate instance attribute.
    """

    def __init__(self, session: ClientSession, username: str, password: str) -> None:
        self._session = session
        self._headers = {"Authorization": BasicAuth(username, password).encode()}


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
