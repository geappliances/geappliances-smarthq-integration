"""Tests for the SmartHQ switch platform."""

import asyncio
from unittest.mock import MagicMock

from custom_components.smarthq.const import DOMAIN
from custom_components.smarthq.service_registry import CMD_TOGGLE_SET, TOGGLE_SERVICE
from custom_components.smarthq.switch import async_setup_entry

FREEZER = "cloud.smarthq.device.refrigerator.freezer"
FRESH_FOOD = "cloud.smarthq.device.refrigerator.freshfood"
TURBO = "cloud.smarthq.domain.turbo"
LOCK = "cloud.smarthq.domain.controls.lock"
OVERRIDE = "cloud.smarthq.domain.override"


def _toggle(service_id: str, domain: str, device_type: str) -> dict:
    return {
        "id": service_id,
        "serviceType": TOGGLE_SERVICE,
        "domainType": domain,
        "serviceDeviceType": device_type,
        "supportedCommands": [CMD_TOGGLE_SET],
    }


def _setup_switches(*services: dict) -> list:
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test-entry"
    coordinator = MagicMock()
    coordinator.data = {"test-device": {"item": {"services": list(services)}}}
    hass.data = {DOMAIN: {"test-entry": {"client": MagicMock(), "coordinator": coordinator, "store": {}}}}
    added: list = []
    asyncio.run(async_setup_entry(hass, entry, lambda entities, **kwargs: added.extend(entities)))
    return added


def test_same_domain_different_labels_keeps_both():
    """A refrigerator's freezer and fresh food turbo toggles share a domain and both become switches."""
    switches = _setup_switches(_toggle("svc-1", TURBO, FREEZER), _toggle("svc-2", TURBO, FRESH_FOOD))
    assert len(switches) == 2
    assert any(s._attr_name.endswith("Freezer Turbo") for s in switches)
    assert any(s._attr_name.endswith("Fresh Food Turbo") for s in switches)


def test_same_domain_same_label_creates_one():
    """The same toggle exposed once per sub-device with the same label creates one switch."""
    switches = _setup_switches(_toggle("svc-1", LOCK, FREEZER), _toggle("svc-2", LOCK, FRESH_FOOD))
    assert len(switches) == 1
    assert switches[0]._attr_name.endswith("Control Lock")


def test_same_label_different_domains_keeps_both():
    """Two domains that both read "Control Lock" do not hide each other."""
    switches = _setup_switches(_toggle("svc-1", LOCK, FREEZER), _toggle("svc-2", OVERRIDE, FREEZER))
    assert len(switches) == 2
