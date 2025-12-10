from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_NAME
from .dispatcher import SIGNAL_DEVICE_UPDATED

_LOGGER = logging.getLogger(__name__)


def _bucket(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return _bucket(hass, entry).get("store") or {}


def _dev_payload(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Dict[str, Any]:
    return _store(hass, entry).get(device_id) or {}


def _snapshot_for(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Dict[str, Any]:
    return _dev_payload(hass, entry, device_id).get("snapshot") or {}


def _device_info_for(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Dict[str, Any]:
    info = _dev_payload(hass, entry, device_id).get("info") or {}
    name = info.get("nickname") or info.get("name") or DEFAULT_NAME
    model = info.get("model") or info.get("deviceType") or ""
    sw_version = info.get("firmwareRevision") or ""
    return {
        "identifiers": {(DOMAIN, device_id)},
        "manufacturer": MANUFACTURER,
        "name": name,
        "model": model,
        "sw_version": sw_version,
    }


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SmartHQ switches."""
    bucket = _bucket(hass, entry)
    ws = bucket.get("client") or bucket.get("ws")
    api = bucket.get("api")
    
    if not ws:
        _LOGGER.error("WS not found in bucket")
        return

    entities: List[SwitchEntity] = []
    
    for device_id in list(_store(hass, entry).keys()):
        snap = _snapshot_for(hass, entry, device_id)
        services = snap.get("services") or {}
        index = snap.get("index") or {}
        
        # Toggle services (Control Lock, Auto Warm, etc.)
        for (stype, dom), service_id in index.items():
            if stype != "cloud.smarthq.service.toggle":
                continue
                
            state = services.get(service_id) or {}
            if state.get("disabled"):
                continue
            
            dom_lower = (dom or "").lower()
            
            # Set name and icon per domain
            if "warm.auto" in dom_lower:
                name = "Auto Warm"
                icon = "mdi:fire-alert"
            elif "lock" in dom_lower:
                name = "Control Lock"
                icon = "mdi:lock"
            elif "light" in dom_lower or "cavity" in dom_lower:
                name = "Cavity Light"
                icon = "mdi:lightbulb"
            elif "smoke" in dom_lower:
                name = "Clear Smoke"
                icon = "mdi:smoke"
            else:
                name = dom.split(".")[-1].replace("_", " ").title() if dom else "Toggle"
                icon = "mdi:toggle-switch"
            
            entities.append(
                SmartHQToggleSwitch(
                    hass=hass,
                    entry=entry,
                    ws=ws,
                    api=api,
                    device_id=device_id,
                    service_id=service_id,
                    name=name,
                    icon=icon,
                )
            )
        
        # Process mode services - handle brightness/light domains as switches
        for sid, svc in services.items():
            if not isinstance(svc, dict):
                continue
            
            stype = str(svc.get("serviceType") or "")
            if stype != "cloud.smarthq.service.mode":
                continue
            
            if svc.get("disabled"):
                continue
            
            dom_lower = str(svc.get("domainType") or "").lower()
            device_type_lower = str(svc.get("serviceDeviceType") or "").lower()
            
            # brightness domain + light device = Cavity Light
            if "brightness" in dom_lower and "light" in device_type_lower:
                name = "Cavity Light"
                icon = "mdi:lightbulb"
                
                entities.append(
                    SmartHQModeSwitch(
                        hass=hass,
                        entry=entry,
                        ws=ws,
                        device_id=device_id,
                        service_id=sid,
                        name=name,
                        icon=icon,
                    )
                )
                continue
            
            # General light domain (exclude display)
            if "light" in dom_lower or "cavity" in dom_lower:
                # Exclude display brightness
                if "display" in device_type_lower:
                    continue
                    
                name = "Cavity Light"
                icon = "mdi:lightbulb"
                
                entities.append(
                    SmartHQModeSwitch(
                        hass=hass,
                        entry=entry,
                        ws=ws,
                        device_id=device_id,
                        service_id=sid,
                        name=name,
                        icon=icon,
                    )
                )

    
    if entities:
        _LOGGER.info("[SWITCH] Registering %d switch entities", len(entities))
        async_add_entities(entities, update_before_add=True)
    else:
        _LOGGER.warning("[SWITCH] No switch entities found")


class SmartHQToggleSwitch(SwitchEntity):
    """Representation of a SmartHQ Toggle Switch (via WebSocket)."""
    
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        ws: Any,
        api: Any,
        device_id: str,
        service_id: str,
        name: str,
        icon: str,
    ):
        """Initialize the switch."""
        self.hass = hass
        self._entry = entry
        self._ws = ws
        self._api = api
        self._device_id = device_id
        self._service_id = service_id
        
        info = _dev_payload(hass, entry, device_id).get("info") or {}
        dev_name = info.get("nickname") or info.get("name") or DEFAULT_NAME
        
        self._attr_name = f"{dev_name} {name}"
        self._attr_icon = icon
        self._attr_unique_id = f"{DOMAIN}:{entry.entry_id}:{device_id}:toggle:{service_id}"
        self._attr_has_entity_name = True
        
        _LOGGER.debug(
            "[TOGGLE_SWITCH] Created: %s (device=%s, service=%s)",
            self._attr_name, device_id[:8], service_id[:8]
        )

    def _get_service_state(self) -> Dict[str, Any]:
        """Get the current service state."""
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        services = snap.get("services") or {}
        return services.get(self._service_id) or {}

    def _get_cooking_state(self) -> Dict[str, Any]:
        """Get device cooking state."""
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        index = snap.get("index") or {}
        services = snap.get("services") or {}
        
        cooking_key = ("cloud.smarthq.service.cooking", "cloud.smarthq.domain.cooking")
        cooking_id = index.get(cooking_key)
        if cooking_id:
            return services.get(cooking_id) or {}
        return {}

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        state = self._get_service_state()
        value = state.get("on")
        
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value == 1
        if isinstance(value, str):
            return value.lower() in ("on", "true", "1")
        
        return False

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        state = self._get_service_state()
        if not state:
            return False
        if state.get("disabled", False):
            return False
        
        # Check device presence
        dev_data = _dev_payload(self.hass, self._entry, self._device_id)
        presence = dev_data.get("presence", {})
        if presence.get("presence") != "ONLINE":
            return False
        
        # Light services require device to be active (not in standby)
        # This is a firmware limitation - lights won't respond in standby mode
        state_data = self._get_service_state()
        service_type = state_data.get("serviceType", "")
        domain_type = state_data.get("domainType", "")
        
        is_light = ("light" in domain_type.lower() or 
                    "brightness" in domain_type.lower() or
                    "cavity" in self._attr_name.lower())
        
        if is_light:
            cooking_state = self._get_cooking_state()
            run_status = cooking_state.get("runStatus", "")
            # Device must be active for light control
            if "off" in run_status.lower():
                return False
        
        return True

    @property
    def device_info(self):
        """Return device information."""
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        _LOGGER.info("[SWITCH] Turning ON: %s (service_id=%s)", self.name, self._service_id[:8])
        
        # Send via WebSocket only
        await self._ws.async_set_toggle(
            device_id=self._device_id,
            service_id=self._service_id,
            on=True,
        )
        
        # Optimistic update
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        _LOGGER.info("[SWITCH] Turning OFF: %s (service_id=%s)", self.name, self._service_id[:8])
        
        # Send via WebSocket only
        await self._ws.async_set_toggle(
            device_id=self._device_id,
            service_id=self._service_id,
            on=False,
        )
        
        # Optimistic update
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
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
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class SmartHQModeSwitch(SwitchEntity):
    """Representation of a SmartHQ Mode Switch (Cavity Light)."""
    
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        ws: Any,
        device_id: str,
        service_id: str,
        name: str,
        icon: str,
    ):
        """Initialize the switch."""
        self.hass = hass
        self._entry = entry
        self._ws = ws
        self._device_id = device_id
        self._service_id = service_id
        
        info = _dev_payload(hass, entry, device_id).get("info") or {}
        dev_name = info.get("nickname") or info.get("name") or DEFAULT_NAME
        
        self._attr_name = f"{dev_name} {name}"
        self._attr_icon = icon
        self._attr_unique_id = f"{DOMAIN}:{entry.entry_id}:{device_id}:mode:{service_id}"
        self._attr_has_entity_name = True
        
        _LOGGER.debug(
            "[MODE_SWITCH] Created: %s (device=%s, service=%s)",
            self._attr_name, device_id[:8], service_id[:8]
        )

    def _get_service_state(self) -> Dict[str, Any]:
        """Get the current service state."""
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        services = snap.get("services") or {}
        return services.get(self._service_id) or {}

    def _get_cooking_state(self) -> Dict[str, Any]:
        """Get device cooking state."""
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        index = snap.get("index") or {}
        services = snap.get("services") or {}
        
        cooking_key = ("cloud.smarthq.service.cooking", "cloud.smarthq.domain.cooking")
        cooking_id = index.get(cooking_key)
        if cooking_id:
            return services.get(cooking_id) or {}
        return {}

    @property
    def is_on(self) -> bool | None:
        """Return true if the light is on."""
        state = self._get_service_state()
        
        if "on" in state:
            return bool(state["on"])
        
        mode = state.get("mode")
        if not mode:
            return False
        
        mode_str = str(mode).lower()
        return mode_str.endswith(".on") or "on" in mode_str

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        state = self._get_service_state()
        if not state:
            return False
        if state.get("disabled", False):
            return False
        
        # Check device presence
        dev_data = _dev_payload(self.hass, self._entry, self._device_id)
        presence = dev_data.get("presence", {})
        if presence.get("presence") != "ONLINE":
            return False
        
        # Light services require device to be active (not in standby)
        # This is a firmware limitation - lights won't respond in standby mode
        state_data = self._get_service_state()
        service_type = state_data.get("serviceType", "")
        domain_type = state_data.get("domainType", "")
        
        is_light = ("light" in domain_type.lower() or 
                    "brightness" in domain_type.lower() or
                    "cavity" in self._attr_name.lower())
        
        if is_light:
            cooking_state = self._get_cooking_state()
            run_status = cooking_state.get("runStatus", "")
            # Device must be active for light control
            if "off" in run_status.lower():
                return False
        
        return True

    @property
    def device_info(self):
        """Return device information."""
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the light on."""
        _LOGGER.info("[SWITCH] Turning ON: %s (service_id=%s)", self._attr_name, self._service_id[:8])
        try:
            await self._ws.async_set_mode(
                self._device_id,
                self._service_id,
                "cloud.smarthq.type.mode.on"
            )
            _LOGGER.info("[SWITCH] ✓ Command sent successfully for %s", self._attr_name)
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error("[SWITCH] ✗ Error turning on %s: %s", self._attr_name, e, exc_info=True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        _LOGGER.info("[SWITCH] Turning OFF: %s (service_id=%s)", self._attr_name, self._service_id[:8])
        try:
            await self._ws.async_set_mode(
                self._device_id,
                self._service_id,
                "cloud.smarthq.type.mode.off"
            )
            _LOGGER.info("[SWITCH] ✓ Command sent successfully for %s", self._attr_name)
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error("[SWITCH] ✗ Error turning off %s: %s", self._attr_name, e, exc_info=True)

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
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
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
