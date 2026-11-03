"""Alert event entity through a real config entry: setup, reload, restart, unload, automations."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_restore_state_shutdown_restart,
    async_mock_service,
    mock_restore_cache_with_extra_data,
)

import custom_components.smarthq as smarthq
from custom_components.smarthq.const import DOMAIN
from custom_components.smarthq.event import EVENT_SMARTHQ_ALERT

DEVICE_ID = "0123456789abcdef"
ENTITY_ID = "event.combo_alert"
END = "cloud.smarthq.alert.endofcycle"
START = "cloud.smarthq.alert.startofcycle"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """A loaded entry with one device and only the event platform.

    The real setup needs the GE cloud; this one fills the store the way it
    does and forwards only the platform under test.
    """

    async def setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
            "store": {DEVICE_ID: {"info": {"nickname": "Combo"}, "alerts": {}}}
        }
        await hass.config_entries.async_forward_entry_setups(entry, ["event"])
        return True

    async def unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        ok = await hass.config_entries.async_unload_platforms(entry, ["event"])
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return ok

    config_entry = MockConfigEntry(domain=DOMAIN, data={"auth_implementation": DOMAIN})
    config_entry.add_to_hass(hass)
    with (
        patch.object(smarthq, "async_setup_entry", setup_entry),
        patch.object(smarthq, "async_unload_entry", unload_entry),
    ):
        yield config_entry


def _fire(hass: HomeAssistant, alert_type: str, alert_time: str, **data) -> None:
    hass.bus.async_fire(
        EVENT_SMARTHQ_ALERT,
        {
            "device_id": DEVICE_ID,
            "alert_type": alert_type,
            "active": True,
            "data": {"lastAlertTime": alert_time, "serial": "ZA341441N", "userId": "u-123", **data},
        },
    )


def _alert_listeners(hass: HomeAssistant) -> int:
    return hass.bus.async_listeners().get(EVENT_SMARTHQ_ALERT, 0)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_second_cycle_fires_again(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await _setup(hass, entry)
    assert hass.states.get(ENTITY_ID).state == STATE_UNKNOWN

    _fire(hass, END, "2026-10-27T13:45:51.000Z", message="Cycle complete")
    await hass.async_block_till_done()
    first = hass.states.get(ENTITY_ID)
    assert first.attributes["event_type"] == "endofcycle"
    assert first.attributes["alert_time"] == "2026-10-27T13:45:51.000Z"
    assert first.attributes["message"] == "Cycle complete"
    # Only the type, time and message; the alert body's serial and user ID stay out.
    assert "ZA341441N" not in str(first.attributes)
    assert "u-123" not in str(first.attributes)

    _fire(hass, END, "2026-10-28T09:45:51.000Z")
    await hass.async_block_till_done()
    second = hass.states.get(ENTITY_ID)
    assert second.state != first.state
    assert second.attributes["alert_time"] == "2026-10-28T09:45:51.000Z"


async def test_reload_keeps_one_listener(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await _setup(hass, entry)
    baseline = _alert_listeners(hass)

    for _ in range(3):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert _alert_listeners(hass) == baseline

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert _alert_listeners(hass) == baseline - 1
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


async def test_restart_does_not_replay(hass: HomeAssistant, entry: MockConfigEntry, hass_storage) -> None:
    """An alert resent after a restart with its old lastAlertTime is not a new occurrence."""
    await _setup(hass, entry)
    _fire(hass, END, "2026-10-27T13:45:51.000Z")
    await hass.async_block_till_done()
    before = hass.states.get(ENTITY_ID).state

    await async_mock_restore_state_shutdown_restart(hass)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == before

    _fire(hass, END, "2026-10-27T13:45:51.000Z")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == before

    _fire(hass, END, "2026-10-28T09:45:51.000Z")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state != before


async def test_restores_alert_times_from_older_state(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Restored data from before this guard existed has no alert times; nothing breaks."""
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(ENTITY_ID, "2026-10-27T13:45:51.100+00:00", {"event_type": "endofcycle"}),
                {"last_event_type": "endofcycle", "last_event_attributes": {"alert_type": END}},
            )
        ],
    )
    await _setup(hass, entry)
    assert hass.states.get(ENTITY_ID).state == "2026-10-27T13:45:51.100+00:00"

    _fire(hass, START, "2026-10-28T07:46:44.000Z")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).attributes["event_type"] == "startofcycle"


async def test_automation_on_event_entity(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """An automation triggered by the entity, filtered on event_type, runs once per occurrence."""
    calls = async_mock_service(hass, "test", "automation")
    await _setup(hass, entry)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "triggers": {"trigger": "state", "entity_id": ENTITY_ID, "not_from": STATE_UNAVAILABLE},
                "conditions": {
                    "condition": "template",
                    "value_template": "{{ trigger.to_state.attributes.event_type == 'endofcycle' }}",
                },
                "actions": {"action": "test.automation"},
            }
        },
    )
    await hass.async_block_till_done()

    _fire(hass, START, "2026-10-27T11:46:44.000Z")
    _fire(hass, END, "2026-10-27T13:45:51.000Z")
    _fire(hass, END, "2026-10-27T13:45:51.000Z")
    _fire(hass, END, "2026-10-28T09:45:51.000Z")
    await hass.async_block_till_done()
    assert len(calls) == 2
