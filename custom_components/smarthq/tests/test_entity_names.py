"""Tests for the SmartHQ entity naming helpers and the names discovery gives entities."""

import asyncio
from unittest.mock import MagicMock

from custom_components.smarthq.const import DOMAIN, entity_label, sdev_prefix, strip_device_name
from custom_components.smarthq.sensor import async_setup_entry as sensor_setup
from custom_components.smarthq.service_registry import (
    CMD_TOGGLE_SET,
    STRING_SERVICE,
    TOGGLE_SERVICE,
    make_unique_id,
)
from custom_components.smarthq.switch import async_setup_entry as switch_setup

FRIDGE = "cloud.smarthq.device.refrigerator"
DEVICE_ID = "test-device"


def test_strip_device_name_drops_leading_device_name():
    """A label starting with the device name loses it; Home Assistant adds it back."""
    assert strip_device_name("Refrigerator", "Refrigerator Light Wall") == "Light Wall"


def test_strip_device_name_ignores_case():
    assert strip_device_name("Refrigerator", "refrigerator Model") == "Model"


def test_strip_device_name_keeps_exact_match():
    """A label that is only the device name is left for the caller."""
    assert strip_device_name("Refrigerator", "Refrigerator") == "Refrigerator"


def test_strip_device_name_needs_a_whole_word():
    """A label that merely begins with the same letters keeps them."""
    assert strip_device_name("Oven", "Ovenlight") == "Ovenlight"


def test_strip_device_name_without_device_name():
    assert strip_device_name("", "Light Wall") == "Light Wall"


def test_sdev_prefix_components():
    assert sdev_prefix(f"{FRIDGE}.freshfood") == "Fresh Food"
    assert sdev_prefix(f"{FRIDGE}.freezer") == "Freezer"
    assert sdev_prefix(f"{FRIDGE}.convertibledrawer.mode2") == "Convertible Drawer Mode 2"


def test_sdev_prefix_appliance_itself_has_none():
    assert sdev_prefix(FRIDGE) == ""
    assert sdev_prefix("cloud.smarthq.device.washer") == ""
    assert sdev_prefix("") == ""


def test_sdev_prefix_instance_numbers():
    """A trailing .1 is the only instance and is omitted; any other number is kept."""
    assert sdev_prefix("cloud.smarthq.device.icemaker.1") == "Ice Maker"
    assert sdev_prefix("cloud.smarthq.device.icemaker.2") == "Ice Maker 2"
    assert sdev_prefix("cloud.smarthq.device.icemaker.0") == "Ice Maker 0"


def test_entity_label_adds_sub_device_once():
    assert entity_label("Refrigerator", f"{FRIDGE}.waterfilter", "Refrigerator Model") == "Water Filter Model"
    assert entity_label("Refrigerator", f"{FRIDGE}.freezer", "Freezer Turbo") == "Freezer Turbo"
    assert entity_label("Refrigerator", f"{FRIDGE}.freezer", "Freezer") == "Freezer"


def test_entity_label_without_sub_device():
    assert entity_label("Refrigerator", FRIDGE, "Refrigerator Light Wall") == "Light Wall"


def _discover(platform, *services: dict) -> list:
    """Run a platform's discovery for one refrigerator with the given services."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test-entry"
    entry.options = {}
    coordinator = MagicMock()
    coordinator.data = {
        DEVICE_ID: {"info": {"nickname": "Refrigerator"}, "item": {"services": list(services)}},
    }
    hass.data = {DOMAIN: {"test-entry": {"client": MagicMock(), "coordinator": coordinator, "store": {}}}}
    added: list = []
    asyncio.run(platform(hass, entry, lambda entities, **kwargs: added.extend(entities)))
    return added


def _service(service_id: str, service_type: str, domain: str, device_type: str) -> dict:
    return {
        "id": service_id,
        "serviceType": service_type,
        "domainType": domain,
        "serviceDeviceType": device_type,
        "supportedCommands": [CMD_TOGGLE_SET] if service_type == TOGGLE_SERVICE else [],
    }


def test_switch_discovery_keeps_unique_ids_and_count():
    """Refrigerator toggles get readable names; unique IDs and the entity count are unchanged."""
    switches = _discover(
        switch_setup,
        _service("svc-lock", TOGGLE_SERVICE, "cloud.smarthq.domain.controls.lock", "cloud.smarthq.device.appliance"),
        _service("svc-power", TOGGLE_SERVICE, "cloud.smarthq.domain.power", "cloud.smarthq.device.icemaker.1"),
    )
    assert sorted(s.unique_id for s in switches) == [
        make_unique_id(DEVICE_ID, "svc-lock", "toggle"),
        make_unique_id(DEVICE_ID, "svc-power", "toggle"),
    ]
    assert sorted(s._attr_name for s in switches) == ["Control Lock", "Ice Maker Power"]


def test_sensor_discovery_keeps_unique_ids_and_count():
    """Sub-device string readings get the component name; unique IDs and the entity count are unchanged."""
    sensors = _discover(
        sensor_setup,
        _service("svc-model", STRING_SERVICE, "cloud.smarthq.domain.model", "cloud.smarthq.device.waterfilter"),
        _service("svc-location", STRING_SERVICE, "cloud.smarthq.domain.location", "cloud.smarthq.device.icemaker.1"),
    )
    assert sorted(s.unique_id for s in sensors) == [
        make_unique_id(DEVICE_ID, "svc-location", "string"),
        make_unique_id(DEVICE_ID, "svc-model", "string"),
    ]
    assert sorted(s.entity_description.name for s in sensors) == ["Ice Maker Location", "Water Filter Model"]
