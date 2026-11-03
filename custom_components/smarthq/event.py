"""SmartHQ alerts as event entities.

SmartHQ alerts are one-off notifications ("cycle started", "5 minutes left",
"door open"). Most are never followed by a clear message, so the per-alert
binary sensors latch on after the first occurrence and never change again.
An event entity models them as what they are: one entity per device whose
state is the time of the last alert, with the alert type as `event_type`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

from homeassistant.components.event import EventEntity, EventExtraStoredData
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

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


@dataclass
class AlertEventStoredData(EventExtraStoredData):
    """The base event data, plus the last `lastAlertTime` seen per alert type.

    `as_dict` is `asdict`, so the extra field is stored alongside the base
    ones, and the base `from_dict` ignores it.
    """

    last_alert_times: Dict[str, str] = field(default_factory=dict)


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
        # Alert type -> lastAlertTime of the last occurrence fired, kept across restarts.
        self._last_alert_times: Dict[str, datetime] = {}

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    @property
    def extra_restore_state_data(self) -> AlertEventStoredData:
        base = super().extra_restore_state_data
        return AlertEventStoredData(
            base.last_event_type,
            base.last_event_attributes,
            {token: t.isoformat() for token, t in self._last_alert_times.items()},
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (stored := await self.async_get_last_extra_data()) is not None:
            for token, value in (stored.as_dict().get("last_alert_times") or {}).items():
                if (parsed := dt_util.parse_datetime(value)) is not None:
                    self._last_alert_times[token] = parsed
        self.async_on_remove(self.hass.bus.async_listen(EVENT_SMARTHQ_ALERT, self._handle_alert))

    @callback
    def _handle_alert(self, event: Event) -> None:
        data = event.data
        if data.get("device_id") != self._device_id or not data.get("active", True):
            return
        token = data.get("alert_type")
        if not isinstance(token, str):
            return

        body = data.get("data") or {}
        # The same occurrence can arrive again (e.g. resent after a reconnect).
        # It carries the same lastAlertTime, so only a newer one counts. An alert
        # without a parseable time can't be told apart and always fires.
        raw_time = body.get("lastAlertTime")
        alert_time = dt_util.parse_datetime(raw_time) if isinstance(raw_time, str) else None
        if alert_time is not None:
            last = self._last_alert_times.get(token)
            if last is not None and alert_time <= last:
                _LOGGER.debug("[ALERT_EVENT] %s: %s at %s already fired", self._device_id[:8], token, raw_time)
                return
            self._last_alert_times[token] = alert_time

        event_type = alert_event_type(token)
        if event_type not in self._attr_event_types:
            # Alert types are open-ended and model-specific; learn new ones as they arrive.
            self._attr_event_types = [*self._attr_event_types, event_type]

        attributes: Dict[str, Any] = {"alert_type": token}
        if body.get("lastAlertTime"):
            attributes["alert_time"] = body["lastAlertTime"]
        if body.get("message"):
            attributes["message"] = body["message"]

        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()
