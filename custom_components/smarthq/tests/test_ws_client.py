"""Tests for SmartHQ WebSocket state handling."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
import yarl
from aiohttp.client_reqrep import RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy

from custom_components.smarthq.service_registry import POWER_USAGE_SERVICE, THERMOSTAT_SERVICE
from custom_components.smarthq.ws_client import SmartHQWebsocket, _redact


@pytest.mark.parametrize(("thermostat_on", "expected_power"), [(False, 0), (True, 708)])
async def test_thermostat_update_reconciles_instantaneous_power(thermostat_on: bool, expected_power: int) -> None:
    """Clear stale power only when the thermostat explicitly turns off."""
    device_id = "test-device"
    store = {
        device_id: {
            "snapshot": {
                "services": {
                    "power": {
                        "serviceType": POWER_USAGE_SERVICE,
                        "instantaneousPower": 708,
                    }
                }
            }
        }
    }
    websocket = SmartHQWebsocket(MagicMock(), api=MagicMock(), device_ids=[device_id], store=store)
    payload = {
        "kind": "pubsub#service",
        "deviceId": device_id,
        "serviceId": "thermostat",
        "serviceType": THERMOSTAT_SERVICE,
        "domainType": "cloud.smarthq.domain.thermostat",
        "state": {"on": thermostat_on},
    }

    with patch("custom_components.smarthq.ws_client.async_dispatcher_send"):
        await websocket._on_message(payload)

    assert store[device_id]["snapshot"]["services"]["power"]["instantaneousPower"] == expected_power


TOKEN = "uw2cpSECRETTOKEN"
ENDPOINT = f"wss://ws-us-west-2.mysmarthq.com?access_token={TOKEN}"


def _handshake_error(status: int) -> aiohttp.WSServerHandshakeError:
    """Build the error aiohttp raises when the server rejects the upgrade."""
    url = yarl.URL(ENDPOINT)
    request_info = RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict()), url)
    return aiohttp.WSServerHandshakeError(request_info, (), status=status, message="Invalid response status")


def test_redact_masks_the_access_token() -> None:
    """The raw endpoint and aiohttp's normalized error text both lose the token."""
    assert _redact(ENDPOINT) == "wss://ws-us-west-2.mysmarthq.com?access_token=**REDACTED**"
    assert TOKEN in str(_handshake_error(401))
    assert TOKEN not in _redact(_handshake_error(401))
    assert _redact("wss://host/?a=1&access_token=x&b=2") == "wss://host/?a=1&access_token=**REDACTED**&b=2"


async def test_reconnect_loop_never_exposes_the_access_token(caplog: pytest.LogCaptureFixture) -> None:
    """Rejected handshakes (an expired token) log and notify without the token."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    api = MagicMock()
    api.async_get_websocket_endpoint = AsyncMock(return_value=ENDPOINT)
    websocket = SmartHQWebsocket(hass, api=api, device_ids=[], store={})
    websocket._session = MagicMock()
    websocket._session.ws_connect.side_effect = _handshake_error(401)

    async def stop_after_three(_delay: float) -> None:
        if websocket._session.ws_connect.call_count >= 3:
            websocket._stopped.set()

    caplog.set_level(logging.INFO, logger="custom_components.smarthq.ws_client")
    with patch("custom_components.smarthq.ws_client.asyncio.sleep", side_effect=stop_after_three):
        await websocket._runner()

    assert websocket._session.ws_connect.call_args.args[0] == ENDPOINT
    assert "access_token=**REDACTED**" in caplog.text
    assert "401" in caplog.text
    assert TOKEN not in caplog.text
    notifications = [
        call.args[2]["message"]
        for call in hass.services.async_call.call_args_list
        if call.args[:2] == ("persistent_notification", "create")
    ]
    assert len(notifications) == 1
    assert "401" in notifications[0]
    assert TOKEN not in notifications[0]
