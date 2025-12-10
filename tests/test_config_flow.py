"""Test the SmartHQ config flow."""
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.smarthq.const import DOMAIN


@pytest.fixture
def mock_setup_entry():
    """Mock setting up a config entry."""
    with patch(
        "custom_components.smarthq.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup


async def test_config_flow_oauth(hass: HomeAssistant, mock_setup_entry):
    """Test the OAuth config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "pick_implementation"

    # This would normally continue with OAuth flow
    # For now, we just verify the initial step works


async def test_config_flow_abort_if_already_setup(hass: HomeAssistant):
    """Test we abort if SmartHQ is already setup."""
    # Create a mock config entry
    config_entry = config_entries.ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="SmartHQ",
        data={},
        source=config_entries.SOURCE_USER,
        unique_id="smarthq_oauth",
    )
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
