"""Interface implemented by active-fire data providers."""
from __future__ import annotations

from typing import Protocol

from ..models import ProviderSnapshot


class ActiveFireProviderError(Exception):
    """Base error raised by a normalized active-fire provider."""


class ProviderAuthenticationError(ActiveFireProviderError):
    """Provider credentials are invalid or expired."""


class ProviderNoDataError(ActiveFireProviderError):
    """No recent provider product is currently available."""


class ProviderUnavailableError(ActiveFireProviderError):
    """The provider could not return a safe, valid product."""


class ActiveFireProvider(Protocol):
    """Return provider data in the common active-fire model."""

    async def async_fetch_latest(self) -> ProviderSnapshot:
        """Fetch and normalize the latest provider product."""
        ...
