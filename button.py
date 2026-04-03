from __future__ import annotations
from typing import Any, Dict, List, Set
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, MANUFACTURER, DEFAULT_NAME

_LOGGER = logging.getLogger(__name__)

def _bucket(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}

def _store(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return _bucket(hass, entry).get("store") or {}

def _dev(hass: HomeAssistant, entry: ConfigEntry, did: str) -> Dict[str, Any]:
    return _store(hass, entry).get(did) or {}

class SmartHQSendToSmoker(ButtonEntity):
    """Send pending cooking settings to smoker."""

    _attr_icon = "mdi:upload"
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, did: str):
        self.hass = hass
        self._entry = entry
        self._device_id = did

        info = _dev(hass, entry, did).get("info") or {}
        dn = info.get("nickname") or info.get("name") or DEFAULT_NAME

        # Include entry_id to prevent UID conflicts
        self._attr_unique_id = f"{DOMAIN}:{entry.entry_id}:{did}:button:send_to_smoker"
        self._attr_name = f"{dn} SEND TO SMOKER"
        self._attr_has_entity_name = True

    @property
    def device_info(self):
        info = _dev(self.hass, self._entry, self._device_id).get("info") or {}
        name = info.get("nickname") or info.get("name") or DEFAULT_NAME
        model = info.get("model") or info.get("deviceType") or ""
        sw = info.get("firmwareRevision") or ""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "manufacturer": MANUFACTURER,
            "name": name,
            "model": model,
            "sw_version": sw,
        }

    @property
    def available(self) -> bool:
        """SEND TO SMOKER is only available when device is powered on."""
        store = _store(self.hass, self._entry)
        device_data = store.get(self._device_id, {})
        snapshot = device_data.get("snapshot", {})
        services = snapshot.get("services", {})
        
        # Check if device is powered on
        for sid, svc in services.items():
            if not isinstance(svc, dict):
                continue
            stype = str(svc.get("serviceType") or "")
            if "cooking.state" in stype:
                state_data = svc.get("state") or {}
                cooking_status = state_data.get("cookingStatus", "")
                run_status = state_data.get("runStatus", "")
                
                # If not OFF, device is powered on
                if not ("off" in cooking_status.lower() and "off" in run_status.lower()):
                    return True
                return False
        
        return False

    async def async_press(self) -> None:
        """Send all pending cooking parameters to smoker."""
        bucket = _bucket(self.hass, self._entry)
        client = bucket.get("client")
        
        if not client:
            _LOGGER.error("[SEND_TO_SMOKER] WebSocket client not available")
            return
        
        # Get pending cook mode
        pending_modes = bucket.get("pending_cook_modes", {})
        mode_info = pending_modes.get(self._device_id)
        
        # Get pending cook parameters (temperature, timer, smoke_level)
        pending_params = bucket.get("pending_cook_params", {})
        device_params = pending_params.get(self._device_id, {})
        
        # Check if there's anything to send
        if not mode_info and not device_params:
            _LOGGER.warning(
                "[SEND_TO_SMOKER] No pending settings for device %s",
                self._device_id[:8]
            )
            return
        
        # Extract parameters
        mode_token = mode_info.get("mode_token") if mode_info else None
        temp_value = device_params.get("target_temperature")
        timer_value = device_params.get("cook_timer")
        probe_target = device_params.get("probe_target")
        smoke_level = device_params.get("smoke_level")
        is_probe_based = device_params.get("is_probe_based", True)
        
        _LOGGER.info(
            "[SEND_TO_SMOKER] Sending settings to device %s: mode=%s, temp=%s°F, timer=%smin, probe=%s°F, smoke=%s, probe_based=%s",
            self._device_id[:8], 
            mode_token,
            temp_value,
            timer_value,
            probe_target,
            smoke_level,
            is_probe_based
        )
        
        try:
            # If we have mode or parameters, send via cooking mode command
            if mode_token or temp_value or timer_value or probe_target or smoke_level is not None:
                # Use current mode if no new mode selected
                if not mode_token:
                    # First check if there's a previously sent mode in pending (from last send)
                    if self._device_id in pending_modes and "last_sent_mode" in pending_modes[self._device_id]:
                        mode_token = pending_modes[self._device_id]["last_sent_mode"]
                        _LOGGER.info("[SEND_TO_SMOKER] Using last sent mode: %s", mode_token)
                    else:
                        # Get current cooking mode from device state as fallback
                        store = bucket.get("store", {})
                        device_data = store.get(self._device_id, {})
                        snap = device_data.get("snapshot", {})
                        services = snap.get("services", {})
                        
                        # Find cooking.mode.v1 service
                        for sid, svc in services.items():
                            if svc.get("serviceType") == "cloud.smarthq.service.cooking.mode.v1":
                                mode_token = svc.get("domainType")
                                _LOGGER.info("[SEND_TO_SMOKER] Using current device mode: %s", mode_token)
                                break
                    
                    if not mode_token:
                        _LOGGER.error("[SEND_TO_SMOKER] No mode token available")
                        return
                
                # Send all parameters in one cooking mode command
                await client.async_set_cooking_mode(
                    self._device_id, 
                    None, 
                    mode_token,
                    cavity_temp_f=temp_value,
                    cook_time_minutes=timer_value if not is_probe_based else None,
                    probe_temp_f=probe_target if is_probe_based else None,
                    smoke_level=smoke_level
                )
                
                _LOGGER.info("[SEND_TO_SMOKER] ✓ All settings sent successfully")
                
                # Save the sent mode for future use
                if mode_token:
                    if "pending_cook_modes" not in bucket:
                        bucket["pending_cook_modes"] = {}
                    if self._device_id not in bucket["pending_cook_modes"]:
                        bucket["pending_cook_modes"][self._device_id] = {}
                    bucket["pending_cook_modes"][self._device_id]["last_sent_mode"] = mode_token
                    _LOGGER.debug("[SEND_TO_SMOKER] Saved last sent mode: %s", mode_token)
                
                # Clear pending values after successful send
                if mode_info and "mode_token" in pending_modes.get(self._device_id, {}):
                    # Only clear mode_token, keep last_sent_mode
                    pending_modes[self._device_id].pop("mode_token", None)
                if device_params:
                    pending_params.pop(self._device_id, None)
            
        except Exception as e:
            _LOGGER.error(
                "[SEND_TO_SMOKER] ✗ Failed to send settings to device %s: %s",
                self._device_id[:8], e, exc_info=True
            )

class SmartHQCoffeeBrewerButton(ButtonEntity):
    """Coffee Brewer Start/Stop button."""

    _attr_should_poll = False
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_id: str, service_id: str, command_type: str, button_type: str):
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._command_type = command_type  # v1.start, v1.stop, v2.start, v2.stop
        self._button_type = button_type  # "start" or "stop"

        info = _dev(hass, entry, device_id).get("info") or {}
        device_name = info.get("nickname") or info.get("name") or DEFAULT_NAME

        self._attr_unique_id = f"{DOMAIN}:{entry.entry_id}:{device_id}:button:brew_{self._button_type}"
        self._attr_name = f"{device_name} Brew {button_type.title()}"
        self._attr_icon = "mdi:coffee" if button_type == "start" else "mdi:stop"
        self._attr_has_entity_name = True

    @property
    def device_info(self):
        info = _dev(self.hass, self._entry, self._device_id).get("info") or {}
        name = info.get("nickname") or info.get("name") or DEFAULT_NAME
        model = info.get("model") or info.get("deviceType") or ""
        sw = info.get("firmwareRevision") or ""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "manufacturer": MANUFACTURER,
            "name": name,
            "model": model,
            "sw_version": sw,
        }

    async def async_press(self) -> None:
        """Send brew start/stop command"""
        bucket = _bucket(self.hass, self._entry)
        client = bucket.get("client")
        
        if not client:
            _LOGGER.error("[COFFEE_BREW] WebSocket client not available")
            return
        
        _LOGGER.info(
            "[COFFEE_BREW] Sending %s command to device %s (command=%s)",
            self._button_type.upper(), self._device_id[:8], self._command_type
        )
        
        try:
            # Get service metadata
            store = _store(self.hass, self._entry)
            device_data = store.get(self._device_id, {})
            snap = device_data.get("snapshot", {})
            services = snap.get("services", {})
            service = services.get(self._service_id, {})
            
            service_type = service.get("serviceType", "")
            domain_type = service.get("domainType", "")
            service_device_type = service.get("serviceDeviceType", "")
            
            # Build command
            command = {
                "commandType": self._command_type
            }
            
            # For START command, add brewing parameters
            if self._button_type == "start":
                # Get settings from bucket storage
                settings = bucket.get("coffee_brewer_settings", {}).get(self._device_id, {})
                strength_str = settings.get("strength", "Medium")
                size_str = settings.get("size", "12 Oz")
                temp_str = settings.get("temperature", "90°C")
                
                # Convert strength to integer (0=Light, 1=Medium, 2=Bold)
                strength_map = {"Light": 0, "Medium": 1, "Bold": 2}
                strength_value = strength_map.get(strength_str, 1)
                
                # Extract volume in oz (e.g., "12 Oz" -> 12.0)
                volume_value = 12.0
                if size_str != "Carafe":
                    try:
                        volume_value = float(size_str.split()[0])
                    except (ValueError, IndexError):
                        volume_value = 12.0
                else:
                    volume_value = 14.0  # Carafe size
                
                # Extract temperature (e.g., "90°C" -> 90.0)
                try:
                    temp_value = float(temp_str.replace("°C", ""))
                except ValueError:
                    temp_value = 90.0
                
                # Add parameters to command
                command["strength"] = strength_value
                command["volumeSingle"] = volume_value
                command["volumeUnits"] = "cloud.smarthq.type.volumeunits.fluidounces"
                command["temperatureCelsius"] = temp_value
                
                _LOGGER.info(
                    "[COFFEE_BREW] Brewing with: strength=%s(%d), size=%s(%.1f oz), temp=%s(%.1f°C)",
                    strength_str, strength_value, size_str, volume_value, temp_str, temp_value
                )
            
            # Send via REST API
            api = bucket.get("api")
            if api:
                await api.async_send_command(
                    device_id=self._device_id,
                    service_type=service_type,
                    domain_type=domain_type,
                    service_device_type=service_device_type,
                    command=command,
                )
                _LOGGER.info("[COFFEE_BREW] ✓ %s command sent successfully", self._button_type.upper())
                # Force state update after command
                self.async_schedule_update_ha_state(force_refresh=True)
            else:
                _LOGGER.error("[COFFEE_BREW] API client not available")
                
        except Exception as e:
            _LOGGER.error(
                "[COFFEE_BREW] ✗ Failed to send %s command: %s",
                self._button_type, e, exc_info=True
            )

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added to hass."""
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .dispatcher import SIGNAL_DEVICE_UPDATED
        
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    def _signal_update(self) -> None:
        """Update button state when device state changes."""
        self.async_schedule_update_ha_state(force_refresh=True)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    """Create device-specific buttons."""
    bucket = _bucket(hass, entry)
    dids: Set[str] = set()

    dids.update(_store(hass, entry).keys())
    if isinstance(bucket.get("device_ids"), (list, set, tuple)):
        dids.update(bucket["device_ids"])

    _LOGGER.debug("[BUTTON_SETUP] device_ids=%s", sorted(dids))

    entities: List[ButtonEntity] = []
    
    for did in sorted(dids):
        # Get device snapshot
        device_data = _store(hass, entry).get(did, {})
        snap = device_data.get("snapshot", {})
        device_type = str(snap.get("deviceType") or "").lower()
        services = snap.get("services", {})
        
        # Smoker devices: SEND TO SMOKER button
        if "smoker" in device_type:
            entities.append(SmartHQSendToSmoker(hass, entry, did))
        
        # Coffee Brewer devices: Start/Stop buttons
        if "coffeebrewer" in device_type:
            # Find coffee brewer service (v1 or v2)
            for sid, svc in services.items():
                if not isinstance(svc, dict):
                    continue
                stype = str(svc.get("serviceType") or "")
                
                if "coffeebrewer.v1" in stype:
                    entities.append(SmartHQCoffeeBrewerButton(
                        hass, entry, did, sid,
                        "cloud.smarthq.command.coffeebrewer.v1.start",
                        "start"
                    ))
                    entities.append(SmartHQCoffeeBrewerButton(
                        hass, entry, did, sid,
                        "cloud.smarthq.command.coffeebrewer.v1.stop",
                        "stop"
                    ))
                    break
                elif "coffeebrewer.v2" in stype:
                    entities.append(SmartHQCoffeeBrewerButton(
                        hass, entry, did, sid,
                        "cloud.smarthq.command.coffeebrewer.v2.start",
                        "start"
                    ))
                    entities.append(SmartHQCoffeeBrewerButton(
                        hass, entry, did, sid,
                        "cloud.smarthq.command.coffeebrewer.v2.stop",
                        "stop"
                    ))
                    break
    
    async_add_entities(entities, update_before_add=False)

    _LOGGER.debug("[BUTTON_SETUP] created=%d", len(entities))
