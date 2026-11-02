"""Tests for the SmartHQ entity naming helpers."""

from custom_components.smarthq.const import entity_label, sdev_prefix, strip_device_name

FRIDGE = "cloud.smarthq.device.refrigerator"


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
