"""Tests for the SmartHQ climate platform."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.climate import HVACAction, HVACMode

from custom_components.smarthq.climate import SmartHQThermostatClimate
from custom_components.smarthq.const import DOMAIN
from custom_components.smarthq.service_registry import POWER_USAGE_SERVICE

ENERGY_SAVER_MODE = "cloud.smarthq.type.thermostatmode.cool.energysaver"
NATIVE_AUTO_MODE = "cloud.smarthq.type.thermostatmode.auto"


def _create_entity(*supported_modes: str) -> tuple[SmartHQThermostatClimate, AsyncMock]:
    hass = MagicMock()
    hass.data = {DOMAIN: {"test-entry": {"store": {}}}}
    entry = MagicMock()
    entry.entry_id = "test-entry"
    client = AsyncMock()
    entity = SmartHQThermostatClimate(
        hass=hass,
        entry=entry,
        client=client,
        device_id="test-device",
        service_id="test-thermostat",
        dev_name="Test AC",
        svc_config={"supportedModes": list(supported_modes)},
        unique_id="test-climate",
    )
    return entity, client


def _set_thermostat_state(
    entity: SmartHQThermostatClimate,
    *,
    on: bool = True,
    mode: str,
    power: float | None = None,
) -> None:
    services = {"test-thermostat": {"on": on, "mode": mode}}
    if power is not None:
        services["power"] = {
            "serviceType": POWER_USAGE_SERVICE,
            "instantaneousPower": power,
        }
    entity.hass.data[DOMAIN]["test-entry"]["store"] = {
        "test-device": {"snapshot": {"services": services}}
    }


def test_energy_saver_is_exposed_and_set_as_auto() -> None:
    """Expose an eco-only appliance as AUTO and send its supported token."""
    entity, client = _create_entity(ENERGY_SAVER_MODE)
    entity.hass.data[DOMAIN]["test-entry"]["store"] = {
        "test-device": {
            "snapshot": {
                "services": {
                    "test-thermostat": {"on": True, "mode": ENERGY_SAVER_MODE}
                }
            }
        }
    }

    assert set(entity.hvac_modes) == {HVACMode.OFF, HVACMode.AUTO}
    assert entity.hvac_mode == HVACMode.AUTO

    asyncio.run(entity.async_set_hvac_mode(HVACMode.AUTO))

    client.async_set_thermostat.assert_awaited_once_with(
        "test-device",
        "test-thermostat",
        on=True,
        mode=ENERGY_SAVER_MODE,
    )


def test_native_auto_token_takes_precedence() -> None:
    """Keep using native AUTO when the appliance supports both modes."""
    entity, client = _create_entity(ENERGY_SAVER_MODE, NATIVE_AUTO_MODE)

    asyncio.run(entity.async_set_hvac_mode(HVACMode.AUTO))

    client.async_set_thermostat.assert_awaited_once_with(
        "test-device",
        "test-thermostat",
        on=True,
        mode=NATIVE_AUTO_MODE,
    )


def test_hvac_action_uses_power_draw_for_compressor_activity() -> None:
    """Report cooling only while power draw indicates compressor activity."""
    cool_mode = "cloud.smarthq.type.thermostatmode.cool"
    entity, _ = _create_entity(cool_mode)

    _set_thermostat_state(entity, mode=cool_mode, power=500)
    assert entity.hvac_action == HVACAction.COOLING

    _set_thermostat_state(entity, mode=cool_mode, power=50)
    assert entity.hvac_action == HVACAction.IDLE


def test_hvac_action_reports_off_and_fan_only() -> None:
    """Report direct activity states without compressor inference."""
    fan_mode = "cloud.smarthq.type.thermostatmode.fanonly"
    entity, _ = _create_entity(fan_mode)

    _set_thermostat_state(entity, mode=fan_mode)
    assert entity.hvac_action == HVACAction.FAN

    _set_thermostat_state(entity, on=False, mode=fan_mode)
    assert entity.hvac_action == HVACAction.OFF