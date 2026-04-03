from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, MANUFACTURER
from .dispatcher import SIGNAL_DEVICE_UPDATED

_LOGGER = logging.getLogger(__name__)


def _bucket(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return _bucket(hass, entry).get("store") or {}


def _known_devices(hass: HomeAssistant, entry: ConfigEntry) -> List[str]:
    return list(_store(hass, entry).keys())


def _iter_alert_tokens(hass: HomeAssistant, entry: ConfigEntry, did: str) -> Iterable[str]:
    alerts = (_store(hass, entry).get(did) or {}).get("alerts") or {}
    for token in alerts.keys():
        if isinstance(token, str) and token.startswith("cloud.smarthq.alert."):
            yield token


def _dev_payload(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Dict[str, Any]:
    """Get device payload from store."""
    return _store(hass, entry).get(device_id) or {}


def _device_info_for(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Dict[str, Any]:
    """Build device_info for a given deviceId."""
    info = _dev_payload(hass, entry, device_id).get("info") or {}
    return {
        "identifiers": {(DOMAIN, device_id)},
        "name": info.get("nickname") or info.get("model") or device_id[:8],
        "manufacturer": MANUFACTURER,
        "model": info.get("model"),
    }


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SmartHQ binary sensors (alerts and settings)."""
    store = _store(hass, entry)
    if not store:
        return

    created: set[str] = set()
    entities: List[BinarySensorEntity] = []

    # 1) Alert sensors
    for did in _known_devices(hass, entry):
        for token in _iter_alert_tokens(hass, entry, did):
            uid = f"{DOMAIN}:{did}:alert:{token}"
            if uid in created:
                continue
            created.add(uid)
            entities.append(SmartHQAlertBinarySensor(hass, entry, did, token))
    
    # 2) Settings sensors (read-only)
    for device_id in _known_devices(hass, entry):
        dev_payload = _dev_payload(hass, entry, device_id)
        settings = dev_payload.get("settings", [])
        
        for setting in settings:
            if not isinstance(setting, dict):
                continue
            
            setting_id = setting.get("id")
            setting_type = setting.get("type")
            

            if setting_type != "BOOLEAN" or not setting_id:
                continue
            
            title = setting.get("title", "Unknown Setting")
            description = setting.get("description", "")
            
            uid = f"{DOMAIN}:{device_id}:setting:{setting_id}"
            if uid in created:
                continue
            created.add(uid)
            
            entities.append(
                SmartHQSettingBinarySensor(
                    hass=hass,
                    entry=entry,
                    device_id=device_id,
                    setting_id=setting_id,
                    name=title,
                    description=description,
                )
            )

    if entities:
        async_add_entities(entities, update_before_add=True)


    @callback
    def _on_device_update() -> None:
        """Handle device update signal to discover new alerts."""
        for device_id in _known_devices(hass, entry):
            new_list: List[SmartHQAlertBinarySensor] = []
            for token in _iter_alert_tokens(hass, entry, device_id):
                uid = f"{DOMAIN}:{device_id}:alert:{token}"
                if uid in created:
                    continue
                created.add(uid)
                new_list.append(SmartHQAlertBinarySensor(hass, entry, device_id, token))
            if new_list:
                _LOGGER.debug("[ALERT_ENTITIES] add %d for %s", len(new_list), device_id[:8])
                async_add_entities(new_list)


    for device_id in _known_devices(hass, entry):
        async_dispatcher_connect(
            hass,
            SIGNAL_DEVICE_UPDATED.format(device_id=device_id),
            _on_device_update,
        )


class SmartHQAlertBinarySensor(BinarySensorEntity):
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_id: str, token: str) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._token = token
        nice = token.split(".")[-1].replace("_", " ").title()
        self._attr_name = f"Alert: {nice}"
        self._attr_unique_id = f"{DOMAIN}:{device_id}:alert:{token}"

    @property
    def is_on(self) -> bool:
        a = (_store(self.hass, self._entry).get(self._device_id) or {}).get("alerts", {}).get(self._token) or {}
        if "active" in a:
            return bool(a["active"])
        return True if a else False

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        a = (_store(self.hass, self._entry).get(self._device_id) or {}).get("alerts", {}).get(self._token) or {}
        return {
            "token": self._token,
            "last_ts": a.get("last_ts"),
            "message": a.get("message"),
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self.async_write_ha_state()

    @callback
    def _signal_update(self) -> None:
        """Handle device update signal."""
        self.async_write_ha_state()


class SmartHQSettingBinarySensor(BinarySensorEntity):
    """Representation of a SmartHQ Setting (read-only)."""
    
    _attr_should_poll = False
    _attr_device_class = None  # Generic binary sensor
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        setting_id: str,
        name: str,
        description: str,
    ) -> None:
        """Initialize the setting binary sensor."""
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._setting_id = setting_id
        self._attr_name = name
        self._description = description
        self._attr_unique_id = f"{DOMAIN}:{device_id}:setting:{setting_id}"
        self._attr_icon = "mdi:bell-outline"

    def _get_setting_value(self) -> Optional[bool]:
        """Get current setting value from store."""
        dev_payload = _dev_payload(self.hass, self._entry, self._device_id)
        settings = dev_payload.get("settings", [])
        
        for setting in settings:
            if isinstance(setting, dict) and setting.get("id") == self._setting_id:
                return setting.get("current")
        
        return None

    @property
    def is_on(self) -> Optional[bool]:
        """Return True if the setting is enabled."""
        return self._get_setting_value()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional attributes."""
        return {
            "description": self._description,
            "setting_id": self._setting_id,
            "read_only": True,
        }

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._get_setting_value() is not None

    @property
    def device_info(self):
        """Return device information."""
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self) -> None:
        """Handle updated data."""
        self.async_write_ha_state()
