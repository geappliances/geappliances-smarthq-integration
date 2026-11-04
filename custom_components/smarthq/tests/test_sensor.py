"""Tests for SmartHQ sensor discovery."""

import asyncio
from unittest.mock import MagicMock

import pytest
from homeassistant.const import UnitOfTemperature

from custom_components.smarthq.const import DOMAIN, OPTION_SHOW_ALT_TEMPS
from custom_components.smarthq.sensor import SmartHQTempSensor, async_setup_entry
from custom_components.smarthq.service_registry import TEMPERATURE_SERVICE


def _discover_temperature_entities(
    device_is_fahrenheit: bool, show_alt_temps: bool, services=None,
) -> tuple[list, MagicMock, MagicMock]:
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
    if services is not None:
        bucket = hass.data[DOMAIN][entry_id]
        bucket["coordinator"].data[device_id]["item"]["services"] = services
        bucket["store"][device_id]["snapshot"]["services"] = {
            service["serviceId"]: {**service, **service["state"]}
            for service in services
        }
    added_entities = []

    def add_entities(entities, **kwargs):
        added_entities.extend(entities)

    asyncio.run(async_setup_entry(hass, entry, add_entities))
    return added_entities, hass, entry


@pytest.mark.parametrize("device_is_fahrenheit", [False, True])
def test_temperature_service_creates_one_entity_for_both_unit_keys(device_is_fahrenheit) -> None:
    """The unit-following entity replaces dynamic entities for the same unit."""
    added_entities, _, _ = _discover_temperature_entities(device_is_fahrenheit, False)

    assert len(added_entities) == 1
    assert isinstance(added_entities[0], SmartHQTempSensor)


@pytest.mark.parametrize("device_is_fahrenheit", [False, True])
def test_alternate_temperature_entity_is_kept_and_labeled_by_unit(device_is_fahrenheit) -> None:
    added_entities, _, _ = _discover_temperature_entities(device_is_fahrenheit, True)

    assert len(added_entities) == 2
    assert all(isinstance(entity, SmartHQTempSensor) for entity in added_entities)
    assert {entity.entity_description.name for entity in added_entities} == {
        "Indoor Ambient Temperature (°F)",
        "Indoor Ambient Temperature (°C)",
    }
    assert {entity.native_unit_of_measurement for entity in added_entities} == {
        UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT,
    }
    assert {entity.native_value for entity in added_entities} == {22.8, 73}


@pytest.mark.parametrize("device_is_fahrenheit", [False, True])
@pytest.mark.parametrize("show_alt", [False, True])
def test_all_hvac_temperature_services_are_discovered(device_is_fahrenheit, show_alt):
    services = [
        {
            "serviceId": service_id,
            "serviceType": TEMPERATURE_SERVICE,
            "domainType": domain,
            "serviceDeviceType": component,
            "state": {"fahrenheit": value, "celsiusConverted": (value - 32) * 5 / 9},
        }
        for service_id, domain, component, value in (
            ("indoor", "cloud.smarthq.domain.indoor.ambient", "cloud.smarthq.device.appliance", 73),
            ("outdoor", "cloud.smarthq.domain.outdoor.ambient", "cloud.smarthq.device.appliance", 58),
            ("target", "cloud.smarthq.domain.indoor", "cloud.smarthq.device.outlet", 72),
        )
    ]
    entities, _, _ = _discover_temperature_entities(device_is_fahrenheit, show_alt, services)
    assert len(entities) == (6 if show_alt else 3)
    assert len({entity.unique_id for entity in entities}) == len(entities)
    for label, fahrenheit in (
        ("Indoor Ambient Temperature", 73),
        ("Outdoor Ambient Temperature", 58),
        ("Indoor Target Temperature", 72),
    ):
        matching = [entity for entity in entities if label in entity.entity_description.name]
        assert len(matching) == (2 if show_alt else 1)
        for entity in matching:
            reports_fahrenheit = entity.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT
            expected_value = fahrenheit if reports_fahrenheit else round((fahrenheit - 32) * 5 / 9, 1)
            assert entity.native_value == expected_value


@pytest.mark.parametrize("device_is_fahrenheit", [False, True])
def test_alternate_pair_keeps_both_units_when_appliance_unit_changes(device_is_fahrenheit):
    entities, hass, entry = _discover_temperature_entities(device_is_fahrenheit, True)
    original_ids = {entity.unique_id for entity in entities}
    bucket = hass.data[DOMAIN][entry.entry_id]
    for appliance_fahrenheit in (device_is_fahrenheit, not device_is_fahrenheit):
        bucket["temp_unit_cache"]["test-device"] = appliance_fahrenheit
        assert {entity.native_unit_of_measurement for entity in entities} == {
            UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT,
        }
        assert {entity.native_value for entity in entities} == {22.8, 73}
        assert {entity.unique_id for entity in entities} == original_ids
    reloaded, _, _ = _discover_temperature_entities(not device_is_fahrenheit, True)
    assert {entity.unique_id for entity in reloaded} == original_ids


@pytest.mark.parametrize("device_is_fahrenheit", [False, True])
def test_single_temperature_follows_unit_changes_without_changing_id(device_is_fahrenheit):
    entities, hass, entry = _discover_temperature_entities(device_is_fahrenheit, False)
    sensor = entities[0]
    original_id = sensor.unique_id
    bucket = hass.data[DOMAIN][entry.entry_id]
    for appliance_fahrenheit in (device_is_fahrenheit, not device_is_fahrenheit):
        bucket["temp_unit_cache"]["test-device"] = appliance_fahrenheit
        expected_unit = UnitOfTemperature.FAHRENHEIT if appliance_fahrenheit else UnitOfTemperature.CELSIUS
        assert sensor.native_unit_of_measurement == expected_unit
        assert sensor.native_value == (73 if appliance_fahrenheit else 22.8)
        assert sensor.unique_id == original_id
    reloaded, _, _ = _discover_temperature_entities(not device_is_fahrenheit, False)
    assert [entity.unique_id for entity in reloaded] == [original_id]
    alternate_pair, _, _ = _discover_temperature_entities(not device_is_fahrenheit, True)
    assert original_id in {entity.unique_id for entity in alternate_pair}


@pytest.mark.parametrize("device_is_fahrenheit", [False, True])
@pytest.mark.parametrize("show_alt", [False, True])
def test_temperature_services_fall_back_to_rest_state(device_is_fahrenheit, show_alt):
    entities, hass, entry = _discover_temperature_entities(device_is_fahrenheit, show_alt)
    hass.data[DOMAIN][entry.entry_id]["store"] = {}
    assert all(entity.available for entity in entities)
    for entity in entities:
        reports_fahrenheit = entity.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT
        assert entity.native_value == (73 if reports_fahrenheit else 22.8)