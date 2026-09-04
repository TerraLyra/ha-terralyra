"""Interface implemented by active-fire data providers."""
from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from ..models import ProviderSnapshot


class ActiveFireProviderError(Exception):
    """Base error raised by a normalized active-fire provider."""

    failure_type = "unknown"

    def __init__(
        self, message: str = "", *, retry_after: timedelta | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderAuthenticationError(ActiveFireProviderError):
    """Provider credentials are invalid or expired."""

    failure_type = "authentication"


class ProviderNoDataError(ActiveFireProviderError):
    """No recent provider product is currently available."""

    failure_type = "no_product"


class ProviderUnavailableError(ActiveFireProviderError):
    """The provider could not return a safe, valid product."""

    failure_type = "service_outage"


class ProviderRateLimitError(ProviderUnavailableError):
    """The provider temporarily rejected requests due to rate limiting."""

    failure_type = "rate_limit"


class ProviderTimeoutError(ProviderUnavailableError):
    """The provider request exceeded its bounded timeout."""

    failure_type = "timeout"


class ProviderInvalidResponseError(ProviderUnavailableError):
    """The provider returned data that failed safe validation."""

    failure_type = "invalid_response"


class ActiveFireProvider(Protocol):
    """Return provider data in the common active-fire model."""

    async def async_fetch_latest(self) -> ProviderSnapshot:
        """Fetch and normalize the latest provider product."""
        ...
