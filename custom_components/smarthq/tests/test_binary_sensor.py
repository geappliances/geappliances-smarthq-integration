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


def test_multi_door_open_when_any_door_open():
    """A multi-door service (per-door flags, no doorState) is on while any door is open."""
    entity = _create_door_entity({"topLeftOpen": False, "bottomOpen": True})
    assert entity.is_on is True
    assert entity.extra_state_attributes == {"top_left_open": False, "bottom_open": True}


def test_multi_door_closed_when_all_doors_closed():
    """A multi-door service is off when every per-door flag is false."""
    assert _create_door_entity({"topLeftOpen": False, "bottomOpen": False}).is_on is False


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


PAUSED_ALERT = "cloud.smarthq.alert.pausedcycle"
COMPLETE_ALERT = "cloud.smarthq.alert.endofcycle"


def _cycle_entity(token, state=None, alert=None):
    entity = _create_alert_entity(token, {token: alert} if alert else {})
    entity.hass.data[DOMAIN]["test-entry"]["store"][DEVICE_ID]["snapshot"] = {
        "services": {"cycle": {"serviceType": "cloud.smarthq.service.dishwasher.state.v1", **(state or {})}}
    }
    return entity


def test_idle_dishwasher_clears_stale_pause():
    entity = _cycle_entity(PAUSED_ALERT, {"runStatus": "cloud.smarthq.type.runstatus.off"}, {"active": True})
    assert entity.is_on is False


def test_inactive_cycle_clears_pause():
    entity = _cycle_entity(PAUSED_ALERT, {
        "cycleIndication": "cloud.smarthq.type.dishwasher.cycle.indication.cycle.inactive"
    }, {"active": True})
    assert entity.is_on is False


def test_pause_without_state_or_event_is_unknown():
    assert _cycle_entity(PAUSED_ALERT).is_on is None


def test_active_pause_remains_on():
    assert _cycle_entity(PAUSED_ALERT, alert={"active": True}).is_on is True


def test_cycle_complete_is_informational_and_unknown_until_event():
    entity = _cycle_entity(COMPLETE_ALERT, {"runStatus": "cloud.smarthq.type.runstatus.off"})
    assert entity.is_on is None
    assert entity.device_class is None
    assert entity.name == "Cycle Complete"
    assert entity.unique_id == f"{DOMAIN}:{DEVICE_ID}:alert:{COMPLETE_ALERT}"


def test_cycle_complete_follows_received_event():
    assert _cycle_entity(COMPLETE_ALERT, alert={"active": True}).is_on is True
    assert _cycle_entity(COMPLETE_ALERT, alert={"active": False}).is_on is False


def test_cycle_entities_created_without_prior_event_or_registry():
    import asyncio
    from custom_components.smarthq import binary_sensor

    entity = _cycle_entity(PAUSED_ALERT, {"runStatus": "cloud.smarthq.type.runstatus.off"})
    added = []
    with patch.object(binary_sensor, "_registered_alert_tokens", return_value=[]):
        asyncio.run(binary_sensor.async_setup_entry(
            entity.hass, entity._entry, lambda entities, **kwargs: added.extend(entities)
        ))
    cycle_entities = [sensor for sensor in added if sensor.unique_id.endswith((PAUSED_ALERT, COMPLETE_ALERT))]
    assert len(cycle_entities) == 2
    assert len({sensor.unique_id for sensor in cycle_entities}) == 2


def test_cycle_entities_not_created_for_other_appliances():
    import asyncio
    from custom_components.smarthq import binary_sensor

    entity = _create_alert_entity(COMMON_ALERT, {})
    added = []
    with patch.object(binary_sensor, "_registered_alert_tokens", return_value=[]):
        asyncio.run(binary_sensor.async_setup_entry(
            entity.hass, entity._entry, lambda entities, **kwargs: added.extend(entities)
        ))
    assert not any(sensor.unique_id.endswith((PAUSED_ALERT, COMPLETE_ALERT)) for sensor in added)
