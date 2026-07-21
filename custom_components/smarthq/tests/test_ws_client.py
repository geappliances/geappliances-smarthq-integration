"""Tests for SmartHQ WebSocket state handling."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.smarthq.service_registry import POWER_USAGE_SERVICE, THERMOSTAT_SERVICE
from custom_components.smarthq.ws_client import SmartHQWebsocket


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
