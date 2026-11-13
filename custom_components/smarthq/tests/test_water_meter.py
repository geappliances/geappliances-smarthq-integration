"""Tests for the SmartHQ water meter sensor."""

import asyncio
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy, UnitOfVolume

from custom_components.smarthq.const import DOMAIN
from custom_components.smarthq.sensor import (
    SmartHQWaterMeterSensor,
    _integer_units_to_ha,
    async_setup_entry,
)
from custom_components.smarthq.service_registry import INTEGER_SERVICE, make_unique_id

DEVICE_ID = "test-device"
SERVICE_ID = "test-water"
FLUID_OUNCES = "cloud.smarthq.type.integerunits.ounces.fluid"
METER_DEVICE = "cloud.smarthq.device.refrigerator.meter"


def _water_meter(state: dict) -> SmartHQWaterMeterSensor:
    hass = MagicMock()
    hass.data = {DOMAIN: {"test-entry": {"store": {DEVICE_ID: {"snapshot": {"services": {SERVICE_ID: state}}}}}}}
    entry = MagicMock()
    entry.entry_id = "test-entry"
    return SmartHQWaterMeterSensor(hass, entry, DEVICE_ID, SERVICE_ID, "Refrigerator", "Water", "test-water-uid")


def _discover(service_device_type: str) -> list:
    coordinator = MagicMock()
    coordinator.data = {
        DEVICE_ID: {
            "item": {
                "services": [
                    {
                        "id": SERVICE_ID,
                        "serviceType": INTEGER_SERVICE,
                        "serviceDeviceType": service_device_type,
                        "domainType": "cloud.smarthq.domain.water",
                        "config": {"integerUnits": FLUID_OUNCES, "label": "Water"},
                        "supportedCommands": [],
                    }
                ]
            }
        }
    }
    hass = MagicMock()
    hass.data = {DOMAIN: {"test-entry": {"store": {}, "coordinator": coordinator}}}
    entry = MagicMock()
    entry.entry_id = "test-entry"
    added: list = []
    asyncio.run(async_setup_entry(hass, entry, lambda entities, **kwargs: added.extend(entities)))
    return [e for e in added if e.unique_id == make_unique_id(DEVICE_ID, SERVICE_ID, "integer")]


def test_fluid_ounces_converted_to_gallons():
    """128 fl oz is exactly one US gallon."""
    assert _water_meter({"value": 128}).native_value == 1.0


def test_missing_value_is_none():
    """No reading yet reports unknown."""
    assert _water_meter({}).native_value is None


def test_non_numeric_value_is_none():
    """A value that is not a number reports unknown instead of raising."""
    assert _water_meter({"value": "n/a"}).native_value is None


def test_water_meter_classes():
    """The meter is a cumulative water total in gallons."""
    sensor = _water_meter({"value": 128})
    assert sensor.device_class == SensorDeviceClass.WATER
    assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
    assert sensor.native_unit_of_measurement == UnitOfVolume.GALLONS


def test_fluid_ounce_units():
    """The dotted unit name maps to fluid ounces; single-word units still map."""
    assert _integer_units_to_ha(FLUID_OUNCES) == (UnitOfVolume.FLUID_OUNCES, SensorDeviceClass.VOLUME)
    assert _integer_units_to_ha("cloud.smarthq.type.integerunits.kwh") == (
        UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY,
    )


def test_meter_discovered_as_water_meter_with_same_unique_id():
    """A fluid-ounce integer on a meter sub-device becomes the water meter, keeping its unique ID."""
    sensors = _discover(METER_DEVICE)
    assert len(sensors) == 1
    assert isinstance(sensors[0], SmartHQWaterMeterSensor)


def test_fluid_ounces_off_meter_stay_plain():
    """Fluid ounces on any other sub-device are not treated as a water meter."""
    sensors = _discover("cloud.smarthq.device.refrigerator")
    assert len(sensors) == 1
    assert not isinstance(sensors[0], SmartHQWaterMeterSensor)
    assert sensors[0].native_unit_of_measurement == UnitOfVolume.FLUID_OUNCES
