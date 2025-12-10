from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .dispatcher import SIGNAL_DEVICE_UPDATED

_LOGGER = logging.getLogger(__name__)

def _bucket(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}

def _store(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return _bucket(hass, entry).get("store") or {}

def _dev(hass: HomeAssistant, entry: ConfigEntry, did: str) -> Dict[str, Any]:
    return _store(hass, entry).get(did) or {}

def _snap(hass: HomeAssistant, entry: ConfigEntry, did: str) -> Dict[str, Any]:
    return _dev(hass, entry, did).get("snapshot") or {}

def _client(hass: HomeAssistant, entry: ConfigEntry):
    return _bucket(hass, entry).get("client")

def _title(hass: HomeAssistant, entry: ConfigEntry, did: str) -> str:
    info = _dev(hass, entry, did).get("info") or {}
    return info.get("nickname") or info.get("name") or "SmartHQ"

def _iter_mode_services(hass: HomeAssistant, entry: ConfigEntry, did: str):
    snap = _snap(hass, entry, did) or {}
    services: Dict[str, Any] = snap.get("services") or {}
    
    # Find mode-type services
    for sid, svc in services.items():
        if not isinstance(svc, dict):
            continue
        
        stype = str(svc.get("serviceType") or "")
        dom = str(svc.get("domainType") or "").lower()
        label = str(svc.get("label") or svc.get("name") or "").lower()
        
        if stype != "cloud.smarthq.service.mode":
            continue
        
        # brightness and light handled in switch
        if "brightness" in dom or "light" in dom or "light" in label:
            continue
        
        # Only allow temperatureunits (Celsius/Fahrenheit)
        if "temperatureunits" not in dom:
            continue
        
        yield sid, svc

def _iter_cooking_mode_services(hass: HomeAssistant, entry: ConfigEntry, did: str):
    """Collect cooking mode services and create virtual select
    
    Each cooking.food.* domain is an individual service,
    supportedModes is empty, so collect all cooking.food.* domains
    and return as a virtual service
    """
    snap = _snap(hass, entry, did) or {}
    services: Dict[str, Any] = snap.get("services") or {}
    
    # Collect all cooking.mode.v1 services
    cooking_services = {}
    for sid, svc in services.items():
        if not isinstance(svc, dict):
            continue
        
        stype = str(svc.get("serviceType") or "")
        dom = str(svc.get("domainType") or "")
        
        if stype == "cloud.smarthq.service.cooking.mode.v1":
            # Collect only cooking.food.* domains (includes Auto Warm)
            if "cooking.food." in dom or dom == "cloud.smarthq.domain.cooking.custom" or dom == "cloud.smarthq.domain.cooking.warm.auto":
                cooking_services[sid] = {
                    "service": svc,
                    "domain": dom,
                    "service_id": sid
                }
                _LOGGER.info(
                    "[COOKING_MODE_FILTER] Found cooking service: %s domain=%s",
                    sid[:8], dom
                )
    
    if cooking_services:
        # Use first service as representative, add all domains to supportedModes
        first_sid = list(cooking_services.keys())[0]
        first_svc = cooking_services[first_sid]["service"].copy()
        
        # Set all domains as supportedModes
        all_domains = [info["domain"] for info in cooking_services.values()]
        
        if "config" not in first_svc:
            first_svc["config"] = {}
        first_svc["config"]["supportedModes"] = all_domains
        
        # Save service ID mapping for later command sending
        first_svc["_cooking_service_map"] = cooking_services
        
        _LOGGER.info(
            "[COOKING_MODE_FILTER] ✓ Created virtual cooking mode service with %d modes: %s",
            len(all_domains), all_domains
        )
        
        yield first_sid, first_svc

class SmartHQModeSelect(SelectEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, did: str, sid: str):
        self.hass = hass
        self._entry = entry
        self._device_id = did
        self._service_id = sid

        dn = _title(hass, entry, did)
        
        # Determine entity name based on domain type
        snap = _snap(hass, entry, did)
        svc = (snap.get("services") or {}).get(sid) or {}
        dom = str(svc.get("domainType") or "").lower()
        
        if "brightness" in dom:
            self._attr_name = f"{dn} Cavity Light"
            self._attr_icon = "mdi:lightbulb"
        else:
            self._attr_name = f"{dn} Mode"
            self._attr_icon = None
        
        self._attr_unique_id = f"{DOMAIN}:{did}:select:{sid}:mode"

        self._token_to_name: Dict[str, str] = {}
        self._name_to_token: Dict[str, str] = {}
        self._refresh_options_from_snapshot()

    def _refresh_options_from_snapshot(self) -> None:
        snap = _snap(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        cfg = svc.get("config") or {}
        modes = cfg.get("supportedModes") or []

        tokens: List[str] = []
        for m in modes:
            if isinstance(m, str):
                tokens.append(m)
            elif isinstance(m, dict) and "token" in m:
                tokens.append(str(m["token"]))

        def pretty(tok: str) -> str:
            name = tok.split(".")[-1].replace("_", " ").replace("-", " ")
            return name.capitalize()

        self._token_to_name = {t: pretty(t) for t in tokens}
        self._name_to_token = {v: k for k, v in self._token_to_name.items()}
        self._attr_options = list(self._name_to_token.keys()) or []

    def _current_token(self) -> Optional[str]:
        snap = _snap(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        cur = svc.get("mode")
        return str(cur) if cur is not None else None

    @property
    def current_option(self) -> Optional[str]:
        token = self._current_token()
        if token and token in self._token_to_name:
            return self._token_to_name[token]
        return (token.split(".")[-1].capitalize() if token else None)

    @property
    def device_info(self):
        """Return device information."""
        info = _dev(self.hass, self._entry, self._device_id).get("info") or {}
        from .const import MANUFACTURER
        name = info.get("nickname") or info.get("name") or "SmartHQ"
        model = info.get("model") or info.get("deviceType") or ""
        sw_version = info.get("firmwareRevision") or ""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "manufacturer": MANUFACTURER,
            "name": name,
            "model": model,
            "sw_version": sw_version,
        }

    async def async_select_option(self, option: str) -> None:
        token = self._name_to_token.get(option) or (option if "." in option else None)
        client = _client(self.hass, self._entry)
        if client and token:
            await client.async_set_mode(self._device_id, self._service_id, token)
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    def _signal_update(self) -> None:
        self._refresh_options_from_snapshot()
        self.schedule_update_ha_state()


class SmartHQCookingModeSelect(SelectEntity):
    """Cooking Mode select entity (Brisket, Chicken, etc.)"""
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, did: str, sid: str):
        self.hass = hass
        self._entry = entry
        self._device_id = did
        self._service_id = sid

        dn = _title(hass, entry, did)
        self._attr_name = f"{dn} Cook Mode"
        self._attr_icon = "mdi:chef-hat"
        self._attr_unique_id = f"{DOMAIN}:{did}:select:{sid}:cook_mode"

        self._token_to_name: Dict[str, str] = {}
        self._name_to_token: Dict[str, str] = {}
        self._refresh_options_from_snapshot()

    def _refresh_options_from_snapshot(self) -> None:
        snap = _snap(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        cfg = svc.get("config") or {}
        modes = cfg.get("supportedModes") or []
        
        _LOGGER.info(
            "[COOKING_MODE] Parsing modes for service %s: config=%s",
            self._service_id[:8], cfg
        )

        tokens: List[str] = []
        for m in modes:
            if isinstance(m, str):
                tokens.append(m)
                _LOGGER.debug("[COOKING_MODE] Added mode string: %s", m)
            elif isinstance(m, dict):
                if "token" in m:
                    tokens.append(str(m["token"]))
                    _LOGGER.debug("[COOKING_MODE] Added mode from dict token: %s", m["token"])
                elif "domainType" in m:
                    # If domainType is directly available
                    tokens.append(str(m["domainType"]))
                    _LOGGER.debug("[COOKING_MODE] Added mode from dict domainType: %s", m["domainType"])

        _LOGGER.info(
            "[COOKING_MODE] Total modes found: %d - %s",
            len(tokens), tokens
        )

        def pretty(tok: str) -> str:
            # Extract friendly name from domain type
            # e.g., cloud.smarthq.domain.cooking.food.brisket -> Brisket
            parts = tok.split(".")
            if len(parts) > 0:
                name = parts[-1].replace("_", " ").replace("-", " ")
                return name.title()
            return tok

        self._token_to_name = {t: pretty(t) for t in tokens}
        self._name_to_token = {v: k for k, v in self._token_to_name.items()}
        self._attr_options = list(self._name_to_token.keys()) or []
        
        _LOGGER.info(
            "[COOKING_MODE] Final options: %s",
            self._attr_options
        )

    def _current_token(self) -> Optional[str]:
        # Current cooking mode from device
        # Read current mode from cooking.state.v1 service
        snap = _snap(self.hass, self._entry, self._device_id)
        services = snap.get("services") or {}
        
        # Find cooking.state.v1 service
        for sid, svc in services.items():
            if not isinstance(svc, dict):
                continue
            stype = str(svc.get("serviceType") or "")
            if stype == "cloud.smarthq.service.cooking.state.v1":
                cur = svc.get("mode")
                if cur:
                    _LOGGER.debug(
                        "[COOK_MODE] Current mode from cooking.state: %s",
                        cur
                    )
                    return str(cur)
        
        # Fallback: current service mode
        svc = services.get(self._service_id) or {}
        cur = svc.get("mode")
        return str(cur) if cur is not None else None

    @property
    def current_option(self) -> Optional[str]:
        token = self._current_token()
        if token and token in self._token_to_name:
            return self._token_to_name[token]
        return (token.split(".")[-1].title() if token else None)

    @property
    def available(self) -> bool:
        """Cook Mode is only available when device is powered on."""
        snap = _snap(self.hass, self._entry, self._device_id)
        services = snap.get("services") or {}
        
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

    @property
    def device_info(self):
        info = _dev(self.hass, self._entry, self._device_id).get("info") or {}
        from .const import MANUFACTURER
        name = info.get("nickname") or info.get("name") or "SmartHQ"
        model = info.get("model") or info.get("deviceType") or ""
        sw_version = info.get("firmwareRevision") or ""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "manufacturer": MANUFACTURER,
            "name": name,
            "model": model,
            "sw_version": sw_version,
        }

    async def async_select_option(self, option: str) -> None:
        """Store cooking mode selection (not sent until button press)"""
        token = self._name_to_token.get(option) or (option if "." in option else None)
        if token:
            # Store selected cook mode
            bucket = _bucket(self.hass, self._entry)
            if "pending_cook_modes" not in bucket:
                bucket["pending_cook_modes"] = {}
            bucket["pending_cook_modes"][self._device_id] = {
                "mode_token": token
            }
            _LOGGER.info(
                "[COOK_MODE] Selected for device %s: %s (domain: %s)",
                self._device_id[:8], option, token
            )
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    def _signal_update(self) -> None:
        self._refresh_options_from_snapshot()
        self.schedule_update_ha_state()


class SmartHQCookTargetMethodSelect(SelectEntity):
    """Cook Target Method select entity (Cook Time / Probe Target)"""
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:target"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_id: str):
        self.hass = hass
        self._entry = entry
        self._device_id = device_id

        dn = _title(hass, entry, device_id)
        self._attr_name = f"{dn} Cook Target Method"
        self._attr_unique_id = f"{DOMAIN}:{device_id}:select:cook_target_method"
        self._attr_options = ["Cook Time", "Probe Target"]

    @property
    def current_option(self) -> str:
        """Get current selection from pending_cook_params."""
        bucket = _bucket(self.hass, self._entry)
        pending_params = bucket.get("pending_cook_params", {})
        device_params = pending_params.get(self._device_id, {})
        is_probe_based = device_params.get("is_probe_based", True)
        return "Probe Target" if is_probe_based else "Cook Time"

    @property
    def available(self) -> bool:
        """Cook Target Method is only available when device is powered on."""
        snap = _snap(self.hass, self._entry, self._device_id)
        services = snap.get("services") or {}
        
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

    @property
    def device_info(self):
        info = _dev(self.hass, self._entry, self._device_id).get("info") or {}
        from .const import MANUFACTURER
        name = info.get("nickname") or info.get("name") or "SmartHQ"
        model = info.get("model") or info.get("deviceType") or ""
        sw_version = info.get("firmwareRevision") or ""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "manufacturer": MANUFACTURER,
            "name": name,
            "model": model,
            "sw_version": sw_version,
        }

    async def async_select_option(self, option: str) -> None:
        """Store Cook Time / Probe Target selection."""
        is_probe_based = (option == "Probe Target")
        
        bucket = _bucket(self.hass, self._entry)
        if "pending_cook_params" not in bucket:
            bucket["pending_cook_params"] = {}
        if self._device_id not in bucket["pending_cook_params"]:
            bucket["pending_cook_params"][self._device_id] = {}
        
        bucket["pending_cook_params"][self._device_id]["is_probe_based"] = is_probe_based
        
        _LOGGER.info(
            "[COOK_TARGET_METHOD] Device %s: Set to %s (is_probe_based=%s)",
            self._device_id[:8], option, is_probe_based
        )
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    def _signal_update(self) -> None:
        self.schedule_update_ha_state()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    entities: List[SelectEntity] = []
    store = _store(hass, entry)
    _LOGGER.info("[SELECT_SETUP] Setting up select entities for %d devices", len(store))
    
    for did in list(store.keys()):
        snap = _snap(hass, entry, did)
        services = snap.get("services") or {}
        index = snap.get("index") or {}
        
        _LOGGER.info("[SELECT_SETUP] Device %s: %d services, %d index entries", did[:8], len(services), len(index))
        
        # Dump all service types
        import json
        for sid, svc in list(services.items())[:10]:  # First 10 only
            if isinstance(svc, dict):
                stype = svc.get("serviceType", "")
                dom = svc.get("domainType", "")
                _LOGGER.info(
                    "[SELECT_SETUP] Service %s: type=%s domain=%s",
                    sid[:8], stype, dom
                )
        
        # Temperature units mode (Celsius/Fahrenheit)
        for sid, svc in _iter_mode_services(hass, entry, did):
            dom = svc.get("domainType") or ""
            _LOGGER.info("[SELECT] Creating temp unit select: device=%s service=%s domain=%s", did[:8], sid[:8] if sid else "none", dom)
            entities.append(SmartHQModeSelect(hass, entry, did, sid))
        
        # Cooking mode selection (Brisket, Chicken, etc.)
        for sid, svc in _iter_cooking_mode_services(hass, entry, did):
            dom = svc.get("domainType") or ""
            _LOGGER.info("[SELECT] Creating cooking mode select: device=%s service=%s domain=%s", did[:8], sid[:8] if sid else "none", dom)
            entities.append(SmartHQCookingModeSelect(hass, entry, did, sid))
        
        # Cook Target Method select for smoker devices
        device_type = str(snap.get("deviceType") or "").lower()
        if "smoker" in device_type:
            _LOGGER.info("[SELECT] Creating Cook Target Method select: device=%s", did[:8])
            entities.append(SmartHQCookTargetMethodSelect(hass, entry, did))
    
    _LOGGER.info("[SELECT] Adding %d select entities", len(entities))
    async_add_entities(entities, update_before_add=False)
