"""Tests for the SmartHQ climate platform."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.climate import ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import setup_test_component_platform

from custom_components.smarthq.climate import SmartHQThermostatClimate
from custom_components.smarthq.const import DOMAIN
from custom_components.smarthq.sensor import _label_for_key
from custom_components.smarthq.service_registry import POWER_USAGE_SERVICE, TEMPERATURE_SERVICE

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


def test_current_temperature_prefers_indoor_ambient_regardless_of_service_order() -> None:
    """Prefer measured indoor air over outdoor ambient and setpoint services."""
    entity, _ = _create_entity()
    entity.hass.data[DOMAIN]["test-entry"]["store"] = {
        "test-device": {
            "snapshot": {
                "services": {
                    "thermostat": {"serviceType": "thermostat"},
                    "outdoor": {
                        "serviceType": TEMPERATURE_SERVICE,
                        "domainType": "cloud.smarthq.domain.outdoor.ambient",
                        "fahrenheit": 58,
                    },
                    "setpoint": {
                        "serviceType": TEMPERATURE_SERVICE,
                        "domainType": "cloud.smarthq.domain.indoor",
                        "serviceDeviceType": "cloud.smarthq.device.outlet",
                        "fahrenheit": 72,
                    },
                    "indoor": {
                        "serviceType": TEMPERATURE_SERVICE,
                        "domainType": "cloud.smarthq.domain.indoor.ambient",
                        "fahrenheit": 73,
                    },
                }
            }
        }
    }

    assert round(entity.current_temperature, 1) == 73

    services = entity.hass.data[DOMAIN]["test-entry"]["store"]["test-device"]["snapshot"]["services"]
    services = dict(reversed(list(services.items())))
    entity.hass.data[DOMAIN]["test-entry"]["store"]["test-device"]["snapshot"]["services"] = services
    assert round(entity.current_temperature, 1) == 73


def test_current_temperature_ignores_indoor_target_without_measured_ambient() -> None:
    """A setpoint-only temperature service is not a measured room temperature."""
    entity, _ = _create_entity()
    entity.hass.data[DOMAIN]["test-entry"]["store"] = {
        "test-device": {
            "snapshot": {
                "services": {
                    "thermostat": {"serviceType": "thermostat"},
                    "setpoint": {
                        "serviceType": TEMPERATURE_SERVICE,
                        "domainType": "cloud.smarthq.domain.indoor",
                        "serviceDeviceType": "cloud.smarthq.device.outlet",
                        "fahrenheit": 72,
                    },
                }
            }
        }
    }

    assert entity.current_temperature is None


def test_current_temperature_converts_celsius_when_fahrenheit_is_missing() -> None:
    entity, _ = _create_entity()
    entity.hass.data[DOMAIN]["test-entry"]["store"] = {
        "test-device": {
            "snapshot": {
                "services": {
                    "thermostat": {"serviceType": "thermostat"},
                    "indoor": {
                        "serviceType": TEMPERATURE_SERVICE,
                        "domainType": "cloud.smarthq.domain.indoor.ambient",
                        "celsiusConverted": 22.7777777778,
                    },
                }
            }
        }
    }

    assert round(entity.current_temperature, 1) == 73


def test_temperature_labels_distinguish_indoor_outdoor_and_setpoint() -> None:
    temp = TEMPERATURE_SERVICE
    assert _label_for_key(
        "fahrenheit", temp, "cloud.smarthq.domain.indoor.ambient"
    ) == "Indoor Ambient Temperature"
    assert _label_for_key(
        "fahrenheit", temp, "cloud.smarthq.domain.outdoor.ambient"
    ) == "Outdoor Ambient Temperature"
    assert _label_for_key(
        "fahrenheit",
        temp,
        "cloud.smarthq.domain.indoor",
        service_device_type="cloud.smarthq.device.outlet",
    ) == "Indoor Target Temperature"


@pytest.mark.parametrize("domain,expected", [
    ("cloud.smarthq.domain.ambient", 71),
    ("cloud.smarthq.domain.measurement", 71),
    ("cloud.smarthq.domain.outdoor.ambient", None),
    ("cloud.smarthq.domain.indoor", None),
])
def test_current_temperature_only_uses_measured_ambient_fallback(domain, expected):
    entity, _ = _create_entity()
    entity.hass.data[DOMAIN]["test-entry"]["store"] = {
        "test-device": {"snapshot": {"services": {
            "temperature": {
                "serviceType": TEMPERATURE_SERVICE,
                "domainType": domain,
                "fahrenheit": 71,
            },
        }}},
    }
    assert entity.current_temperature == expected


def test_supported_features_include_turn_on_and_turn_off() -> None:
    entity, _ = _create_entity()
    assert ClimateEntityFeature.TURN_ON in entity.supported_features
    assert ClimateEntityFeature.TURN_OFF in entity.supported_features
    assert ClimateEntityFeature.TARGET_TEMPERATURE in entity.supported_features


@pytest.mark.parametrize(
    "service,on,expected_on",
    [
        ("toggle", True, False),
        ("toggle", False, True),
        ("turn_off", True, False),
        ("turn_on", False, True),
    ],
)
async def test_power_services_through_home_assistant(hass, service, on, expected_on) -> None:
    """Call the real climate services; HA gates them on TURN_ON / TURN_OFF."""
    entry = MagicMock()
    entry.entry_id = "test-entry"
    client = AsyncMock()
    hass.data[DOMAIN] = {"test-entry": {"store": {"test-device": {"snapshot": {"services": {
        "test-thermostat": {"on": on, "mode": "cloud.smarthq.type.thermostatmode.cool"},
    }}}}}}
    entity = SmartHQThermostatClimate(
        hass=hass,
        entry=entry,
        client=client,
        device_id="test-device",
        service_id="test-thermostat",
        dev_name="Test AC",
        svc_config={"supportedModes": ["cloud.smarthq.type.thermostatmode.cool"]},
        unique_id="test-climate",
    )
    setup_test_component_platform(hass, "climate", [entity])
    assert await async_setup_component(hass, "climate", {"climate": {"platform": "test"}})
    await hass.async_block_till_done()
    assert hass.states.get(entity.entity_id) is not None

    await hass.services.async_call(
        "climate", service, {"entity_id": entity.entity_id}, blocking=True
    )

    client.async_set_thermostat.assert_awaited_once_with(
        "test-device", "test-thermostat", on=expected_on
    )
