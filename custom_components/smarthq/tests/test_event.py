"""Tests for the SmartHQ alert event entity."""

from unittest.mock import MagicMock

from custom_components.smarthq.event import SmartHQAlertEvent, alert_event_type

DEVICE_ID = "test-device"
ALERT = "cloud.smarthq.alert.endofcycle.minutesleft.5"


def _create_entity(event_types=("endofcycle.minutesleft.5",)) -> SmartHQAlertEvent:
    entity = SmartHQAlertEvent(MagicMock(), MagicMock(), DEVICE_ID, list(event_types))
    entity.async_write_ha_state = MagicMock()
    return entity


def _alert(**data) -> MagicMock:
    event = MagicMock()
    event.data = {"device_id": DEVICE_ID, "alert_type": ALERT, "active": True, "data": {}, **data}
    return event


def test_event_type_keeps_full_alert_name():
    """The prefix is stripped but the rest is kept, so `...minutesleft.5` is not just `5`."""
    assert alert_event_type(ALERT) == "endofcycle.minutesleft.5"
    assert alert_event_type("cloud.smarthq.alert.contractormode.disabled") == "contractormode.disabled"
    assert alert_event_type("cloud.smarthq.alert.enhancedfeature.disabled") == "enhancedfeature.disabled"


def test_alert_fires_event():
    entity = _create_entity()
    entity._handle_alert(_alert(data={"lastAlertTime": "2026-10-27T13:40:39.574Z", "serial": "secret"}))

    attrs = entity.state_attributes
    assert attrs["event_type"] == "endofcycle.minutesleft.5"
    assert attrs["alert_type"] == ALERT
    assert attrs["alert_time"] == "2026-10-27T13:40:39.574Z"
    assert "serial" not in attrs
    entity.async_write_ha_state.assert_called_once()


def test_repeated_alert_fires_again():
    """A latched binary sensor misses the second occurrence; the event entity must not."""
    entity = _create_entity()
    entity._handle_alert(_alert())
    entity._handle_alert(_alert())
    assert entity.async_write_ha_state.call_count == 2


def test_other_device_ignored():
    entity = _create_entity()
    entity._handle_alert(_alert(device_id="other-device"))
    entity.async_write_ha_state.assert_not_called()


def test_cleared_alert_ignored():
    entity = _create_entity()
    entity._handle_alert(_alert(active=False))
    entity.async_write_ha_state.assert_not_called()


def test_unknown_alert_type_is_learned():
    """Alert types are model-specific; one not seen at setup is added rather than rejected."""
    entity = _create_entity(event_types=["ota.update"])
    entity._handle_alert(_alert(alert_type="cloud.smarthq.alert.startofcycle"))

    assert "startofcycle" in entity.event_types
    assert entity.state_attributes["event_type"] == "startofcycle"
