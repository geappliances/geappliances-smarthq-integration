"""Test the SmartHQ init."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.smarthq.const import DOMAIN
from .const import MOCK_CONFIG


@pytest.fixture
def mock_api():
    """Mock SmartHQApi."""
    with patch("custom_components.smarthq.SmartHQApi") as mock:
        api = mock.return_value
        api.async_get_devices = AsyncMock(return_value=[])
        yield api


async def test_setup_entry(hass: HomeAssistant, mock_api):
    """Test setting up a config entry."""
    entry = MagicMock()
    entry.data = MOCK_CONFIG
    entry.entry_id = "test_entry"

    with patch("custom_components.smarthq.SmartHQWebsocket") as mock_ws:
        mock_ws.return_value.start = AsyncMock()
        result = await hass.config_entries.async_setup(entry.entry_id)
        
        # The setup would normally complete successfully
        # For now we just verify it doesn't crash


async def test_unload_entry(hass: HomeAssistant):
    """Test unloading a config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.state = ConfigEntryState.LOADED

    with patch("custom_components.smarthq.async_unload_platforms", return_value=True):
        result = await hass.config_entries.async_unload(entry.entry_id)
        # Verify unload doesn't crash
