"""Tests for the SmartHQ binary_sensor platform."""

from unittest.mock import MagicMock, patch

from custom_components.smarthq.binary_sensor import (
    SmartHQAlertBinarySensor,
    SmartHQDoorBinarySensor,
    _registered_alert_tokens,
)
from custom_components.smarthq.const import DOMAIN

DEVICE_ID = "test-device"
SERVICE_ID = "test-door"


def _create_door_entity(state: dict) -> SmartHQDoorBinarySensor:
    hass = MagicMock()
    hass.data = {DOMAIN: {"test-entry": {"store": {DEVICE_ID: {"snapshot": {"services": {SERVICE_ID: state}}}}}}}
    entry = MagicMock()
    entry.entry_id = "test-entry"
    return SmartHQDoorBinarySensor(hass, entry, DEVICE_ID, SERVICE_ID, "Door", "test-door-uid")


def test_door_state_string_open():
    """A DOOR_SERVICE reporting doorState="open" is on."""
    assert _create_door_entity({"doorState": "open"}).is_on is True


def test_door_state_string_closed():
    """A DOOR_SERVICE reporting doorState="closed" is off."""
    assert _create_door_entity({"doorState": "closed"}).is_on is False


def test_toggle_shaped_door_open():
    """A read-only toggle door service reporting {"on": True} is on."""
    assert _create_door_entity({"on": True}).is_on is True


def test_toggle_shaped_door_closed():
    """A read-only toggle door service reporting {"on": False} is off.

    Regression guard: `on` must be read explicitly. Falling through to the
    string branch would coerce False to "" and report the door closed for
    both states, which is indistinguishable from a working sensor.
    """
    assert _create_door_entity({"on": False}).is_on is False


def test_door_state_wins_over_normalised_on():
    """An explicit doorState takes precedence over a normalised `on` flag.

    ws_client normalises `enabled`/`mode` into `on` for every service, so `on`
    may be present on a DOOR_SERVICE without describing the door.
    """
    assert _create_door_entity({"doorState": "open", "on": False}).is_on is True


def test_unavailable_when_service_missing():
    """An entity with no service state in the store is unavailable."""
    entity = _create_door_entity({})
    assert entity.available is False


def _create_alert_entity(token: str, alerts: dict) -> SmartHQAlertBinarySensor:
    hass = MagicMock()
    hass.data = {DOMAIN: {"test-entry": {"store": {DEVICE_ID: {"alerts": alerts}}}}}
    entry = MagicMock()
    entry.entry_id = "test-entry"
    return SmartHQAlertBinarySensor(hass, entry, DEVICE_ID, token)


DOOR_ALERT = "cloud.smarthq.alert.door.open.freezer"
COMMON_ALERT = "cloud.smarthq.alert.ota.update"


def test_unseen_dynamic_alert_is_unknown():
    """A restored alert with no message since restart is unknown, not cleared."""
    assert _create_alert_entity(DOOR_ALERT, {}).is_on is None


def test_unseen_common_alert_is_off():
    """Common alerts keep their pre-registered off state."""
    assert _create_alert_entity(COMMON_ALERT, {}).is_on is False


def test_received_alert_follows_active_flag():
    assert _create_alert_entity(DOOR_ALERT, {DOOR_ALERT: {"active": True}}).is_on is True
    assert _create_alert_entity(DOOR_ALERT, {DOOR_ALERT: {"active": False}}).is_on is False


def test_registered_alert_tokens_filters_by_device_and_platform():
    """Only this device's registered alert entities yield tokens."""
    def reg(domain: str, unique_id: str) -> MagicMock:
        return MagicMock(domain=domain, unique_id=unique_id)

    entries = [
        reg("binary_sensor", f"{DOMAIN}:{DEVICE_ID}:alert:{DOOR_ALERT}"),
        reg("binary_sensor", f"{DOMAIN}:other-device:alert:{COMMON_ALERT}"),
        reg("sensor", f"{DOMAIN}:{DEVICE_ID}:alert:{COMMON_ALERT}"),
        reg("binary_sensor", f"{DOMAIN}:{DEVICE_ID}:door"),
    ]
    entry = MagicMock()
    entry.entry_id = "test-entry"
    with patch("custom_components.smarthq.binary_sensor.er") as er:
        er.async_entries_for_config_entry.return_value = entries
        assert list(_registered_alert_tokens(MagicMock(), entry, DEVICE_ID)) == [DOOR_ALERT]
