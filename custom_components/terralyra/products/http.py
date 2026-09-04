"""Small shared helpers for safe upstream HTTP retry handling."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime


def parse_retry_after(value: str | None) -> timedelta | None:
    """Parse a Retry-After delay or HTTP date without raising."""
    if not value or len(value) > 128:
        return None
    try:
        seconds = int(value.strip())
    except ValueError:
        seconds = None
    else:
        if seconds < 0:
            return None
        try:
            return timedelta(seconds=seconds)
        except OverflowError:
            return None

    try:
        retry_at = parsedate_to_datetime(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    delay = retry_at - datetime.now(UTC)
    return max(delay, timedelta(0))
