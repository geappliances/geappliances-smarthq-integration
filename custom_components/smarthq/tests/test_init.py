"""Test setting up and unloading the SmartHQ integration."""

from collections.abc import Generator
from unittest.mock import create_autospec, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthq.api import SmartHQApi
from custom_components.smarthq.const import DEFAULT_OPTIONS, DOMAIN
from custom_components.smarthq.service_registry import CMD_TOGGLE_SET, TOGGLE_SERVICE
from custom_components.smarthq.ws_client import SmartHQWebsocket

from .const import MOCK_CONFIG

DEVICE_ID = "test-device"
SERVICE_ID = "svc-turbo"

DEVICE = {
    "deviceId": DEVICE_ID,
    "deviceType": "cloud.smarthq.device.refrigerator",
    "nickname": "Kitchen Fridge",
    "model": "TEST-MODEL",
    "firmwareRevision": "1.0.0",
}

DEVICE_ITEM = {
    "deviceId": DEVICE_ID,
    "deviceType": "cloud.smarthq.device.refrigerator",
    "services": [
        {
            "serviceId": SERVICE_ID,
            "serviceType": TOGGLE_SERVICE,
            "domainType": "cloud.smarthq.domain.turbo",
            "serviceDeviceType": "cloud.smarthq.device.refrigerator.freezer",
            "supportedCommands": [CMD_TOGGLE_SET],
            "state": {"on": True},
        }
    ],
}


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Add a SmartHQ config entry to Home Assistant."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="SmartHQ",
        data={
            **MOCK_CONFIG,
            "token": {
                "access_token": "mock-access-token",
                "refresh_token": "mock-refresh-token",
                "expires_at": 9999999999,
                "token_type": "Bearer",
            },
        },
        options=DEFAULT_OPTIONS,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_api() -> Generator[SmartHQApi]:
    """Replace the SmartHQ REST client with one that returns a single refrigerator."""
    api = create_autospec(SmartHQApi, instance=True)
    api.async_list_devices.return_value = [DEVICE]
    api.async_get_device_item.return_value = DEVICE_ITEM
    api.get_device_settings.return_value = []
    api.async_get_presence.return_value = {"presence": "ONLINE"}
    with patch("custom_components.smarthq.api.SmartHQApi", return_value=api):
        yield api


@pytest.fixture
def mock_ws() -> Generator[SmartHQWebsocket]:
    """Replace the SmartHQ WebSocket client so no connection is opened."""
    ws = create_autospec(SmartHQWebsocket, instance=True)
    with patch("custom_components.smarthq.ws_client.SmartHQWebsocket", return_value=ws):
        yield ws


async def test_setup_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: SmartHQApi,
    mock_ws: SmartHQWebsocket,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Setting up an entry loads devices, starts the WebSocket and creates entities."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    mock_api.async_list_devices.assert_awaited_once()
    mock_ws.start.assert_awaited_once()

    bucket = hass.data[DOMAIN][config_entry.entry_id]
    assert bucket["client"] is mock_ws
    snapshot = bucket["store"][DEVICE_ID]["snapshot"]
    assert snapshot["services"][SERVICE_ID]["on"] is True

    devices = dr.async_entries_for_config_entry(device_registry, config_entry.entry_id)
    assert [(d.identifiers, d.name) for d in devices] == [({(DOMAIN, DEVICE_ID)}, "Kitchen Fridge")]

    entity_id = entity_registry.async_get_entity_id("switch", DOMAIN, f"{DEVICE_ID}_{SERVICE_ID}_toggle")
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"

    for service in ("dump", "diagnose", "alert_snapshot", "set_cavity_light_mode"):
        assert hass.services.has_service(DOMAIN, service)


async def test_unload_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: SmartHQApi,
    mock_ws: SmartHQWebsocket,
) -> None:
    """Unloading an entry stops the WebSocket and drops the entry's data."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    polling_task = hass.data[DOMAIN][config_entry.entry_id]["settings_polling_task"]

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    mock_ws.stop.assert_awaited_once()
    assert polling_task.done()
    assert config_entry.entry_id not in hass.data[DOMAIN]


async def test_setup_auth_failure_starts_reauth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: SmartHQApi,
    mock_ws: SmartHQWebsocket,
) -> None:
    """An authentication error while listing devices asks the user to sign in again."""
    mock_api.async_list_devices.side_effect = Exception("401 Unauthorized")

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    mock_ws.start.assert_not_called()


async def test_setup_retries_when_api_unavailable(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: SmartHQApi,
    mock_ws: SmartHQWebsocket,
) -> None:
    """A non-auth error while listing devices schedules a retry."""
    mock_api.async_list_devices.side_effect = Exception("503 Service Unavailable")

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_ws.start.assert_not_called()
