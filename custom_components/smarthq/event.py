"""SmartHQ alerts as event entities.

SmartHQ alerts are one-off notifications ("cycle started", "5 minutes left",
"door open"). Most are never followed by a clear message, so the per-alert
binary sensors latch on after the first occurrence and never change again.
An event entity models them as what they are: one entity per device whose
state is the time of the last alert, with the alert type as `event_type`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .service_registry import COMMON_ALERTS

_LOGGER = logging.getLogger(__name__)

ALERT_PREFIX = "cloud.smarthq.alert."
EVENT_SMARTHQ_ALERT = "smarthq_alert"


def _bucket(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return _bucket(hass, entry).get("store") or {}


def _device_info_for(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Dict[str, Any]:
    info = (_store(hass, entry).get(device_id) or {}).get("info") or {}
    return {
        "identifiers": {(DOMAIN, device_id)},
        "name": info.get("nickname") or info.get("model") or device_id[:8],
        "manufacturer": "GE Appliances",
        "model": info.get("model"),
    }


def alert_event_type(token: str) -> str:
    """`cloud.smarthq.alert.endofcycle.minutesleft.5` -> `endofcycle.minutesleft.5`.

    The whole remainder is kept: the last segment alone collides (`5`,
    `disabled` for both `contractormode.disabled` and `enhancedfeature.disabled`).
    """
    return token[len(ALERT_PREFIX) :] if token.startswith(ALERT_PREFIX) else token


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up one alert event entity per device."""
    store = _store(hass, entry)
    entities: List[SmartHQAlertEvent] = []
    for device_id, dev in store.items():
        seen = (dev or {}).get("alerts") or {}
        tokens = set(COMMON_ALERTS) | {t for t in seen if isinstance(t, str) and t.startswith(ALERT_PREFIX)}
        entities.append(SmartHQAlertEvent(hass, entry, device_id, sorted(alert_event_type(t) for t in tokens)))
    if entities:
        async_add_entities(entities)


class SmartHQAlertEvent(EventEntity):
    """Fires once per SmartHQ alert received for a device."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Alert"
    _attr_icon = "mdi:bell-ring-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_id: str, event_types: List[str]) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}:{device_id}:alert_event"
        self._attr_event_types = list(event_types)

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(EVENT_SMARTHQ_ALERT, self._handle_alert))

    @callback
    def _handle_alert(self, event: Event) -> None:
        data = event.data
        if data.get("device_id") != self._device_id or not data.get("active", True):
            return
        token = data.get("alert_type")
        if not isinstance(token, str):
            return

        event_type = alert_event_type(token)
        if event_type not in self._attr_event_types:
            # Alert types are open-ended and model-specific; learn new ones as they arrive.
            self._attr_event_types = [*self._attr_event_types, event_type]

        body = data.get("data") or {}
        attributes: Dict[str, Any] = {"alert_type": token}
        if body.get("lastAlertTime"):
            attributes["alert_time"] = body["lastAlertTime"]
        if body.get("message"):
            attributes["message"] = body["message"]

        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()
