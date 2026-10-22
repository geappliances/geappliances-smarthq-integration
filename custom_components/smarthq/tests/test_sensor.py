"""Tests for SmartHQ sensor discovery."""

import asyncio
from unittest.mock import MagicMock

import pytest
from homeassistant.const import UnitOfTemperature

from custom_components.smarthq.const import DOMAIN, OPTION_SHOW_ALT_TEMPS
from custom_components.smarthq.sensor import SmartHQSnapshotSensor, SmartHQTempSensor, async_setup_entry
from custom_components.smarthq.service_registry import TEMPERATURE_SERVICE


def _discover_temperature_entities(device_is_fahrenheit: bool, show_alt_temps: bool) -> list:
    device_id = "test-device"
    service_id = "indoor-ambient"
    entry_id = "test-entry"
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            entry_id: {
                "temp_unit_cache": {device_id: device_is_fahrenheit},
                "coordinator": MagicMock(
                    data={
                        device_id: {
                            "info": {"nickname": "Test HVAC"},
                            "item": {
                                "services": [
                                    {
                                        "serviceId": service_id,
                                        "serviceType": TEMPERATURE_SERVICE,
                                        "domainType": "cloud.smarthq.domain.indoor.ambient",
                                        "serviceDeviceType": "cloud.smarthq.device.appliance",
                                        "state": {
                                            "fahrenheit": 73,
                                            "celsiusConverted": 22.7777777778,
                                        },
                                    }
                                ]
                            },
                        }
                    }
                ),
                "store": {
                    device_id: {
                        "snapshot": {
                            "services": {
                                service_id: {
                                    "serviceType": TEMPERATURE_SERVICE,
                                    "domainType": "cloud.smarthq.domain.indoor.ambient",
                                    "serviceDeviceType": "cloud.smarthq.device.appliance",
                                    "fahrenheit": 73,
                                    "celsiusConverted": 22.7777777778,
                                }
                            }
                        }
                    }
                },
            }
        }
    }
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.options = {OPTION_SHOW_ALT_TEMPS: show_alt_temps}
    added_entities = []

    def add_entities(entities, **kwargs):
        added_entities.extend(entities)

    asyncio.run(async_setup_entry(hass, entry, add_entities))
    return added_entities


@pytest.mark.parametrize("device_is_fahrenheit", [False, True])
def test_temperature_service_creates_one_entity_for_both_unit_keys(device_is_fahrenheit) -> None:
    """The unit-following entity replaces dynamic entities for the same unit."""
    added_entities = _discover_temperature_entities(device_is_fahrenheit, False)

    assert len(added_entities) == 1
    assert isinstance(added_entities[0], SmartHQTempSensor)


@pytest.mark.parametrize("device_is_fahrenheit", [False, True])
def test_alternate_temperature_entity_is_kept_and_labeled_by_unit(device_is_fahrenheit) -> None:
    added_entities = _discover_temperature_entities(device_is_fahrenheit, True)

    assert len(added_entities) == 2
    assert sum(isinstance(entity, SmartHQTempSensor) for entity in added_entities) == 1
    assert sum(isinstance(entity, SmartHQSnapshotSensor) for entity in added_entities) == 1
    assert {entity.entity_description.name for entity in added_entities} == {
        "Indoor Ambient Temperature",
        "Indoor Ambient Temperature (°C)" if device_is_fahrenheit else "Indoor Ambient Temperature (°F)",
    }
    alternate = next(entity for entity in added_entities if isinstance(entity, SmartHQSnapshotSensor))
    assert alternate.native_unit_of_measurement == (
        UnitOfTemperature.CELSIUS if device_is_fahrenheit else UnitOfTemperature.FAHRENHEIT
    )
    assert alternate.native_value == (22.8 if device_is_fahrenheit else 73)