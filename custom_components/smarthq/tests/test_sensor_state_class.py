"""Tests for the state class of SmartHQ temperature sensors."""

import asyncio
from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfPower, UnitOfTemperature

from custom_components.smarthq.const import DOMAIN, OPTION_SHOW_ALT_TEMPS
from custom_components.smarthq.sensor import (
    SmartHQRawTempSensor,
    SmartHQSnapshotSensor,
    SmartHQTempSensor,
    async_setup_entry,
)
from custom_components.smarthq.service_registry import INTEGER_SERVICE

DEVICE_ID = "test-device"
SERVICE_ID = "test-service"


def _hass_and_entry(coordinator=None) -> tuple[MagicMock, MagicMock]:
    hass = MagicMock()
    hass.data = {DOMAIN: {"test-entry": {"store": {}, "coordinator": coordinator}}}
    entry = MagicMock()
    entry.entry_id = "test-entry"
    return hass, entry


def _integer_sensor(integer_units: str):
    coordinator = MagicMock()
    coordinator.data = {
        DEVICE_ID: {
            "item": {
                "services": [
                    {
                        "id": SERVICE_ID,
                        "serviceType": INTEGER_SERVICE,
                        "domainType": "cloud.smarthq.domain.reading",
                        "config": {"integerUnits": integer_units, "label": "Reading"},
                        "supportedCommands": [],
                    }
                ]
            }
        }
    }
    hass, entry = _hass_and_entry(coordinator)
    added: list = []
    asyncio.run(async_setup_entry(hass, entry, lambda entities, **kwargs: added.extend(entities)))
    sensors = [e for e in added if e.unique_id and e.unique_id.endswith("integer")]
    assert len(sensors) == 1
    return sensors[0]


def test_service_temperature_is_measurement():
    """A temperature service sensor has long-term statistics."""
    hass, entry = _hass_and_entry()
    sensor = SmartHQTempSensor(
        hass, entry, DEVICE_ID, SERVICE_ID, "Refrigerator", "Freezer Temperature", "uid",
    )
    assert sensor.state_class == SensorStateClass.MEASUREMENT


def test_raw_temperature_is_measurement():
    """A raw temperature sensor has long-term statistics."""
    hass, entry = _hass_and_entry()
    sensor = SmartHQRawTempSensor(
        hass, entry, DEVICE_ID, SERVICE_ID, "Oven",
        "Probe Temperature", "probeTemperatureFahrenheit", UnitOfTemperature.FAHRENHEIT, "uid",
    )
    assert sensor.state_class == SensorStateClass.MEASUREMENT


def test_snapshot_temperature_key_is_measurement():
    """A snapshot sensor for a temperature key has long-term statistics."""
    hass, entry = _hass_and_entry()
    sensor = SmartHQSnapshotSensor(
        hass, entry, DEVICE_ID, "Cavity Temperature", "cavityTemperatureFahrenheit",
        None, None, None, SERVICE_ID,
    )
    assert sensor.state_class == SensorStateClass.MEASUREMENT


@pytest.mark.parametrize("show_alt", [False, True])
@pytest.mark.parametrize("initial_fahrenheit", [False, True])
@pytest.mark.parametrize("state_key", ["fahrenheit", "celsiusConverted"])
def test_snapshot_temperature_units_follow_option(show_alt, initial_fahrenheit, state_key):
    """Alternate keys stay fixed while normal sensors follow appliance changes."""
    hass, entry = _hass_and_entry()
    entry.options = {OPTION_SHOW_ALT_TEMPS: show_alt}
    bucket = hass.data[DOMAIN][entry.entry_id]
    bucket["temp_unit_cache"] = {DEVICE_ID: initial_fahrenheit}
    bucket["store"] = {
        DEVICE_ID: {"snapshot": {"services": {
            SERVICE_ID: {"fahrenheit": 37, "celsiusConverted": 2.7777777778},
        }}},
    }
    sensor = SmartHQSnapshotSensor(
        hass, entry, DEVICE_ID, "Temperature", state_key,
        None, None, None, SERVICE_ID,
    )
    original_id = sensor.unique_id
    for appliance_fahrenheit in (initial_fahrenheit, not initial_fahrenheit):
        bucket["temp_unit_cache"][DEVICE_ID] = appliance_fahrenheit
        reports_fahrenheit = state_key == "fahrenheit" if show_alt else appliance_fahrenheit
        expected_unit = (
            UnitOfTemperature.FAHRENHEIT if reports_fahrenheit else UnitOfTemperature.CELSIUS
        )
        assert sensor.native_unit_of_measurement == expected_unit
        assert sensor.native_value == (37 if reports_fahrenheit else 2.8)
        assert sensor.unique_id == original_id
        assert sensor.state_class == SensorStateClass.MEASUREMENT


def test_snapshot_other_key_unchanged():
    """A snapshot sensor for any other key keeps its unit and has no state class."""
    hass, entry = _hass_and_entry()
    sensor = SmartHQSnapshotSensor(
        hass, entry, DEVICE_ID, "Power", "power", None, SensorDeviceClass.POWER, UnitOfPower.WATT, SERVICE_ID,
    )
    assert sensor.state_class is None
    assert sensor.native_unit_of_measurement == UnitOfPower.WATT


def test_integer_temperature_is_measurement():
    """An integer service reporting degrees has long-term statistics."""
    sensor = _integer_sensor("cloud.smarthq.type.integerunits.fahrenheit")
    assert sensor.device_class == SensorDeviceClass.TEMPERATURE
    assert sensor.state_class == SensorStateClass.MEASUREMENT


def test_integer_other_unit_unchanged():
    """An integer service with another unit still has no state class."""
    sensor = _integer_sensor("cloud.smarthq.type.integerunits.watts")
    assert sensor.device_class == SensorDeviceClass.POWER
    assert sensor.state_class is None
