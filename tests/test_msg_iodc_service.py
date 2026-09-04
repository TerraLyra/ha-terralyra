"""Tests for the explicit MSG-IODC compatibility action."""
from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terralyra import async_setup
from custom_components.terralyra.const import (
    ATTR_CONFIG_ENTRY_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    SERVICE_PROBE_MSG_IODC,
)
from custom_components.terralyra.products.msg_iodc import (
    MsgIodcAuthenticationError,
    async_fetch_latest_list_product,
)


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def iter_chunked(self, chunk_size: int):
        for offset in range(0, len(self._payload), chunk_size):
            yield self._payload[offset : offset + chunk_size]


class _Response:
    def __init__(self, status: int, payload: bytes = b"") -> None:
        self.status = status
        self.content = _Body(payload)
        self.content_length = len(payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
        return None


class _Session:
    def __init__(self, *responses: _Response) -> None:
        self.responses = deque(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs) -> _Response:
        self.calls.append((url, kwargs))
        return self.responses.popleft()


@pytest.mark.asyncio
async def test_fetch_skips_missing_slot_and_returns_bounded_payload() -> None:
    session = _Session(_Response(404), _Response(200, b"hdf5-metadata"))

    filename, payload = await async_fetch_latest_list_product(
        session,
        "account",
        "-".join(("test", "credential")),
        now=datetime(2026, 9, 4, 18, 46, tzinfo=UTC),
        lookback_slots=2,
    )

    assert filename.endswith("202609041815")
    assert payload == b"hdf5-metadata"
    assert len(session.calls) == 2
    assert session.calls[0][1]["allow_redirects"] is False


@pytest.mark.asyncio
async def test_fetch_maps_rejected_credentials_without_response_body() -> None:
    session = _Session(_Response(401, b"upstream details must not escape"))

    with pytest.raises(MsgIodcAuthenticationError):
        await async_fetch_latest_list_product(
            session,
            "account",
            "-".join(("test", "credential")),
            now=datetime(2026, 9, 4, 18, 46, tzinfo=UTC),
            lookback_slots=1,
        )


@pytest.mark.asyncio
async def test_home_assistant_action_returns_only_sanitized_schema(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "account",
            CONF_PASSWORD: "-".join(("test", "credential")),
        },
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    await async_setup(hass, {})
    schema = {
        "format": "terralyra-msg-iodc-schema-v1",
        "payload_bytes": 512,
        "objects": [],
    }

    with (
        patch(
            "custom_components.terralyra.async_fetch_latest_list_product",
            new=AsyncMock(return_value=("safe-product", b"payload")),
        ),
        patch(
            "custom_components.terralyra.inspect_list_product_schema",
            return_value=schema,
        ),
    ):
        response = await hass.services.async_call(
            DOMAIN,
            SERVICE_PROBE_MSG_IODC,
            {ATTR_CONFIG_ENTRY_ID: entry.entry_id},
            blocking=True,
            return_response=True,
        )

    assert response == {
        "status": "compatible",
        "provider": "EUMETSAT LSA SAF",
        "satellite": "Meteosat-9",
        "product": "MSG-IODC FRP-PIXEL List Product",
        "schema": schema,
    }
    assert CONF_USERNAME not in repr(response)
    assert CONF_PASSWORD not in repr(response)
