# /config/custom_components/smarthq/sensor.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.components.number import NumberEntity
from homeassistant.components.switch import SwitchEntity
import logging

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN, MANUFACTURER, DEFAULT_NAME, OPTION_SHOW_ALT_TEMPS
from .dispatcher import SIGNAL_DEVICE_UPDATED


# -------------------------
# Priority/active key set
# -------------------------

# Representative service priority (actual/state > preset)
_PREFERRED_SERVICE_ORDER = [
    "cloud.smarthq.service.cooking.state.v1",
    "cloud.smarthq.service.cooking.mode.v1",
    "cloud.smarthq.service.progress",
    "cloud.smarthq.service.switch",
    "cloud.smarthq.service.connectivity",
]

# Real-time meaningful keys (skip service if none of these keys exist)
_ACTIVE_KEYS = {
    # Temperature
    "cavityTemperatureCelsiusConverted",
    "cavityTemperatureFahrenheit",
    "probeTemperatureCelsiusConverted",
    "probeTemperatureFahrenheit",
    "celsiusConverted",
    "fahrenheit",
    # Timer/progress
    "secondsRemaining",
    "secondsElapsed",
    "cookTimeInitial",
    "preheatProgress",
    "progress",
    "percentage",
    "value",
    # State/intensity
    "signalStrength",
    "numericOptionValue",
    "runStatus",
    "mode",
}

# Temperature key group
_C_KEYS = {
    "cavityTemperatureCelsiusConverted",
    "probeTemperatureCelsiusConverted",
    "celsiusConverted",
}
_F_KEYS = {
    "cavityTemperatureFahrenheit",
    "probeTemperatureFahrenheit",
    "fahrenheit",
}


# -------------------------
# Helpers
# -------------------------

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

def _allow_key_for_system_unit(hass: HomeAssistant, entry: ConfigEntry, key: str) -> bool:
    """Option (alternative temperature display) + system unit based filter."""
    show_alt = entry.options.get(OPTION_SHOW_ALT_TEMPS, False)
    if show_alt:
        return True
    sys_is_c = hass.config.units.temperature_unit == UnitOfTemperature.CELSIUS
    if key in _C_KEYS:
        return sys_is_c
    if key in _F_KEYS:
        return not sys_is_c
    return True

def _fmt_seconds_to_hms(v: Any) -> Optional[str]:
    try:
        sec = int(v)
    except Exception:
        return None
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def _tail_enum(v: Any) -> Any:
    """For enum like cloud.smarthq.xxx, show only tail nicely."""
    if isinstance(v, str) and v.startswith("cloud.smarthq."):
        return v.split(".")[-1].upper()
    return v

def _preheat_key_from(stype: str, dom: str, state: Dict[str, Any]) -> Optional[Tuple[str, Any]]:
    # 1) Explicit key
    if "preheatProgress" in state:
        return ("preheatProgress", state["preheatProgress"])
    for k in ("percentage", "progress"):
        if k in state and isinstance(state[k], (int, float)):
            return ("preheatProgress", state[k])
    # 2) value(0~100) in preheat/progress domain
    if ("progress" in (stype or "")) or ("progress" in (dom or "")) or ("preheat" in (dom or "")):
        v = state.get("value")
        if isinstance(v, (int, float)) and 0 <= float(v) <= 100:
            return ("preheatProgress", v)
    return None


# -------------------------
# Dynamic sensor crafting
# -------------------------

@dataclass
class _DynKey:
    name: str
    key: str
    device_class: Optional[SensorDeviceClass] = None
    unit: Optional[str] = None
    icon: Optional[str] = None

# Default label candidates (labels partially overridden by domain below)
_DYN_KEYS: List[_DynKey] = [
    # Temperature
    _DynKey("Ambient Temperature", "celsiusConverted", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, "mdi:thermometer"),
    _DynKey("Ambient Temperature (°F)", "fahrenheit", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT, "mdi:thermometer"),
    _DynKey("Cavity Temperature", "cavityTemperatureCelsiusConverted", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, "mdi:thermometer"),
    _DynKey("Cavity Temperature (°F)", "cavityTemperatureFahrenheit", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT, "mdi:thermometer"),
    _DynKey("Probe Temperature", "probeTemperatureCelsiusConverted", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, "mdi:thermometer"),
    _DynKey("Probe Temperature (°F)", "probeTemperatureFahrenheit", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT, "mdi:thermometer"),
    # Timer/progress
    _DynKey("Cook Time Initial", "cookTimeInitial", None, None, "mdi:timer"),
    _DynKey("Cook Time Remaining", "secondsRemaining", None, None, "mdi:timer-outline"),
    _DynKey("Cook Time Elapsed", "secondsElapsed", None, None, "mdi:timer-sand"),
    _DynKey("Preheat Progress", "preheatProgress", None, PERCENTAGE, "mdi:progress-clock"),
    # Others
    _DynKey("Signal Strength", "signalStrength", None, None, "mdi:wifi-strength-2"),
    _DynKey("Smoke Level", "numericOptionValue", None, None, "mdi:fire"),
    _DynKey("Run Status", "runStatus", None, None, "mdi:information"),
    _DynKey("Mode", "mode", None, None, "mdi:tune"),
    _DynKey("Value", "value"),
]


class SmartHQSnapshotSensor(SensorEntity):
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        label: str,
        state_key: str,
        icon: Optional[str],
        device_class: Optional[SensorDeviceClass],
        unit: Optional[str],
        service_id: str,
    ):
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._label = label
        self._state_key = state_key
        self._service_id = service_id
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit

        info = _dev_payload(hass, entry, device_id).get("info") or {}
        dev_name = info.get("nickname") or info.get("name") or DEFAULT_NAME
        self._attr_name = f"{dev_name} {label}"
        self._attr_unique_id = f"{DOMAIN}:{device_id}:sensor:{service_id}:{state_key}"
        self._attr_has_entity_name = True

    def _get_service_meta(self):
        """Return (service_state, service_type, domain_type)."""
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        services = snap.get("services") or {}
        st = services.get(self._service_id) or {}
        rev = {sid: pair for pair, sid in (snap.get("index") or {}).items()}
        stype, dom = rev.get(self._service_id, (None, None))
        return st, (stype or ""), (dom or "")

    def _resolve_preheat_value(self, st: dict, stype: str, dom: str):
        """Resolve progress (%) from various keys for preheat/progress domains."""
        # Explicit keys first
        if "preheatProgress" in st:
            return st.get("preheatProgress")
        for k in ("percentage", "progress"):
            if k in st:
                return st.get(k)
        # When domain is preheat/progress but only has value(0~100)
        doms = f"{stype}.{dom}".lower()
        if ("preheat" in doms or "progress" in doms) and "value" in st:
            v = st.get("value")
            try:
                f = float(v)
                if 0 <= f <= 100:
                    return f
            except Exception:
                pass
        return None

    @property
    def available(self) -> bool:
        st, stype, dom = self._get_service_meta()
        if self._state_key == "preheatProgress":
            # Temporarily unavailable if no value
            return self._resolve_preheat_value(st, stype, dom) is not None
        return self._state_key in st

    @property
    def native_value(self):
        st, stype, dom = self._get_service_meta()
        if self._state_key == "preheatProgress":
            return self._resolve_preheat_value(st, stype, dom)
        val = st.get(self._state_key)
        if self._state_key in ("secondsRemaining", "secondsElapsed", "cookTimeInitial"):
            hv = _fmt_seconds_to_hms(val)
            return hv if hv is not None else val
        if self._state_key in ("runStatus", "mode"):
            return _tail_enum(val)
        return val

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_added_to_hass(self) -> None:
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
        self.schedule_update_ha_state()


class SmartHQSmokerNumber(NumberEntity):
    """Representation of a SmartHQ Smoker temperature/timer control with pending state."""

    def __init__(self, api, hass: HomeAssistant, coordinator, entry: ConfigEntry, appliance_id: str, name: str, erd_code: str, min_value: float = 0, max_value: float = 500, step: float = 1):
        """Initialize the number entity."""
        self._api = api
        self.hass = hass
        self.coordinator = coordinator
        self._entry = entry
        self._appliance_id = appliance_id
        self._attr_name = name
        self._erd_code = erd_code
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_unique_id = f"{appliance_id}_{erd_code}"
        
        # Set unit of measurement based on ERD code
        if "temperature" in erd_code or "probe" in erd_code:
            self._attr_native_unit_of_measurement = "°F"  # Temperature
        elif "timer" in erd_code or "time" in erd_code.lower():
            self._attr_native_unit_of_measurement = "min"  # Minutes
        else:
            self._attr_native_unit_of_measurement = None  # No unit (like smoke level)

    @property
    def available(self) -> bool:
        """Return True if entity should be available based on Power ON state and Cook Target Method."""
        bucket = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id) or {}
        store = bucket.get("store", {})
        device_data = store.get(self._appliance_id, {})
        snapshot = device_data.get("snapshot", {})
        services = snapshot.get("services", {})
        
        # Check if device is powered on (Ready or Cooking state)
        is_powered_on = False
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
                    is_powered_on = True
                break
        
        # Cook Time: only available when Time Based mode AND powered on
        if self._erd_code == "cook_timer":
            pending_params = bucket.get("pending_cook_params", {})
            device_params = pending_params.get(self._appliance_id, {})
            is_probe_based = device_params.get("is_probe_based", True)
            return is_powered_on and not is_probe_based
        
        # Probe Target: only available when Probe Temp mode AND powered on
        if self._erd_code == "probe_target":
            pending_params = bucket.get("pending_cook_params", {})
            device_params = pending_params.get(self._appliance_id, {})
            is_probe_based = device_params.get("is_probe_based", True)
            return is_powered_on and is_probe_based
        
        # Other entities (target_temperature, smoke_level): available when powered on
        return is_powered_on

    @property
    def native_value(self) -> float | None:
        """Return pending value if exists, otherwise actual value."""
        bucket = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id) or {}
        pending = bucket.get("pending_cook_params", {})
        
        # Check if there's a pending value
        device_pending = pending.get(self._appliance_id, {})
        if self._erd_code in device_pending:
            return device_pending[self._erd_code]
        
        # Return actual value from device state
        store = bucket.get("store", {})
        device_data = store.get(self._appliance_id, {})
        snapshot = device_data.get("snapshot", {})
        services = snapshot.get("services", {})
        
        # For smoke_level, find the integer service with numericOptionValue
        if self._erd_code == "smoke_level":
            for sid, svc in services.items():
                if not isinstance(svc, dict):
                    continue
                stype = str(svc.get("serviceType") or "")
                if stype == "cloud.smarthq.service.integer":
                    value = svc.get("numericOptionValue")
                    if value is not None:
                        return int(value)
            return 0  # Default smoke level
        
        # For target_temperature and cook_timer, use coordinator data
        appliance = self.coordinator.data.get(self._appliance_id, {})
        return appliance.get(self._erd_code)

    async def async_set_native_value(self, value: float) -> None:
        """Store value in pending state instead of sending immediately."""
        bucket = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id) or {}
        
        # Initialize pending_cook_params if not exists
        if "pending_cook_params" not in bucket:
            bucket["pending_cook_params"] = {}
        
        # Store pending value
        if self._appliance_id not in bucket["pending_cook_params"]:
            bucket["pending_cook_params"][self._appliance_id] = {}
        
        bucket["pending_cook_params"][self._appliance_id][self._erd_code] = int(value)
        
        _LOGGER.info(
            "[NUMBER_PENDING] %s set to %s (pending, not sent yet)",
            self._erd_code, value
        )
        
        # Trigger state update to show pending value
        self.async_write_ha_state()

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._appliance_id)},
        }


class SmartHQSmokerSwitch(SwitchEntity):
    """Representation of a SmartHQ Smoker switch."""

    def __init__(self, api, hass: HomeAssistant, coordinator, appliance_id: str, name: str, erd_code: str):
        """Initialize the switch entity."""
        self._api = api
        self.hass = hass
        self.coordinator = coordinator
        self._appliance_id = appliance_id
        self._attr_name = name
        self._erd_code = erd_code
        self._attr_unique_id = f"{appliance_id}_{erd_code}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        appliance = self.coordinator.data.get(self._appliance_id, {})
        value = appliance.get(self._erd_code)
        return value == 1 or value is True

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        success = await self._api.set_erd_value(self._appliance_id, self._erd_code, 1)
        if success:
            _LOGGER.info(f"Successfully turned on {self._erd_code}")

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        success = await self._api.set_erd_value(self._appliance_id, self._erd_code, 0)
        if success:
            _LOGGER.info(f"Successfully turned off {self._erd_code}")

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._appliance_id)},
        }


# -------------------------
# Discovery
# -------------------------

def _iter_dynamic_sensors(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Iterable[SmartHQSnapshotSensor]:
    snap = _snapshot_for(hass, entry, device_id)
    services: Dict[str, Dict[str, Any]] = snap.get("services") or {}
    index: Dict[tuple, str] = snap.get("index") or {}
    if not services:
        return []

    # Reverse mapping: serviceId -> (serviceType, domainType)
    rev: Dict[str, Tuple[str, str]] = {sid: pair for pair, sid in index.items()}

    made_labels: set[str] = set()
    added_pairs: set[tuple[str, str]] = set()   # (service_id, state_key)
    result: list[SmartHQSnapshotSensor] = []

    # Candidate services (exclude inactive + active keys exist)
    def _is_dynamic_state(st: Dict[str, Any]) -> bool:
        if not isinstance(st, dict):
            return False
        if st.get("disabled") is True:
            return False
        return any(k in st for k in _ACTIVE_KEYS)

    candidates: list[tuple[str, Dict[str, Any]]] = [
        (sid, st) for sid, st in services.items() if _is_dynamic_state(st)
    ]
    if not candidates:
        return []

    # Initialize sid at the beginning of the function
    sid = None

    # Identify currently active cooking mode (preset) → use only that preset as representative
    active_mode: str = ""
    for _sid, _st in services.items():
        if sid is None:
            sid = _sid
        if _sid == sid:
            continue
        if rev.get(_sid, (None, None))[0] == "cloud.smarthq.service.cooking.state.v1":
            active_mode = str(_st.get("mode") or "").lower()
            break

    # Representative service score
    def _score(sid: str, st: Dict[str, Any]) -> int:
        stype, _dom = rev.get(sid, (None, None))
        sc = 0
        if any(x in st for x in ("preheatProgress", "secondsRemaining", "secondsElapsed", "progress", "percentage", "value")):
            sc += 20
        if stype in _PREFERRED_SERVICE_ORDER:
            sc += (1000 - _PREFERRED_SERVICE_ORDER.index(stype) * 100)
        return sc

    # key -> representative sid (includes system unit/option filter)
    chosen_sid_for_key: dict[str, str] = {}
    for sid, st in candidates:
        stype, dom = rev.get(sid, ("", ""))

        # For cooking.mode.v1, use only those matching current active preset
        if stype == "cloud.smarthq.service.cooking.mode.v1" and active_mode:
            dom_l = (dom or "").lower()
            if ".food." in dom_l and (("." + active_mode) not in dom_l):
                continue

        for key in list(st.keys()):
            if key == "disabled" or "Default" in key:
                continue
            if key not in _ACTIVE_KEYS:
                continue
            if not _allow_key_for_system_unit(hass, entry, key):
                continue

            # ✅ Exclude fake 24h(86400) remaining time during preheat
            if key == "secondsRemaining":
                cooking_state = None
                for _sid, _st in services.items():
                    if _sid == sid:
                        continue
                    if rev.get(_sid, (None, None))[0] == "cloud.smarthq.service.cooking.state.v1":
                        cooking_state = _st
                        break
                if cooking_state and str(cooking_state.get("cookingStatus", "")).upper() == "PREHEAT" and int(st.get("secondsRemaining", 0)) == 86400:
                    continue

            # ✅ Select Smoke Level only from cooking series
            if key == "numericOptionValue":
                if "cooking" not in (stype or "") and "cooking" not in (dom or ""):
                    continue

            cur = chosen_sid_for_key.get(key)
            if cur is None or _score(sid, st) > _score(cur, services[cur]):
                chosen_sid_for_key[key] = sid

    # ★ Enhancement: force map percent value (value/percentage/progress) in progress/preheat domain
    for sid, st in candidates:
        stype, dom = rev.get(sid, (None, None))
        pair = _preheat_key_from(stype or "", dom or "", st)
        if pair:
            k, _ = pair
            if k not in chosen_sid_for_key and _allow_key_for_system_unit(hass, entry, k):
                chosen_sid_for_key[k] = sid

    # 1) Pretty labels first
    for dyn in _DYN_KEYS:
        key = dyn.key
        sid = chosen_sid_for_key.get(key)
        if not sid:
            continue
        st = services.get(sid) or {}

        # 🔸 Allow creating entity for Preheat Progress even without key
        if key != "preheatProgress" and key not in st:
            continue

        # ---- Temperature label routing (distinguish Ambient/Cavity by domain) ----
        stype, dom = rev.get(sid, (None, ""))
        label = dyn.name
        unit = dyn.unit
        dev_class = dyn.device_class
        icon = dyn.icon

        if stype == "cloud.smarthq.service.cooking.mode.v1":
            if key in ("cavityTemperatureCelsiusConverted", "cavityTemperatureFahrenheit"):
                label = "Cavity Target Temperature" if "Celsius" in key or key == "cavityTemperatureCelsiusConverted" \
                    else "Cavity Target Temperature (°F)"
            if key in ("probeTemperatureCelsiusConverted", "probeTemperatureFahrenheit"):
                label = "Probe Target Temperature" if "Celsius" in key or key == "probeTemperatureCelsiusConverted" \
                    else "Probe Target Temperature (°F)"

        if key in ("celsiusConverted", "fahrenheit") and stype == "cloud.smarthq.service.temperature":
            dom_low = (dom or "").lower()
            if ("measurement" in dom_low) or ("early.temperature" in dom_low):
                label = "Ambient Temperature" if key == "celsiusConverted" else "Ambient Temperature (°F)"
            elif "cooking" in dom_low:
                # cooking.* → consider as Cavity
                label = "Cavity Temperature" if key == "celsiusConverted" else "Cavity Temperature (°F)"

        if label in made_labels:
            continue

        pair = (sid, key)
        if pair in added_pairs:
            continue
        result.append(
            SmartHQSnapshotSensor(
                hass, entry, device_id,
                label=label, state_key=key, icon=icon,
                device_class=dev_class, unit=unit, service_id=sid,
            )
        )
        added_pairs.add(pair)
        made_labels.add(label)

    # 2) Simple labels for remaining keys
    for key, sid in chosen_sid_for_key.items():
        # Skip labels already created in 1)
        stype, dom = rev.get(sid, (None, ""))
        label = key.replace("_", " ").title()
        dev_class = None
        unit = None

        if stype == "cloud.smarthq.service.cooking.mode.v1":
            if key in ("cavityTemperatureCelsiusConverted", "cavityTemperatureFahrenheit"):
                label = "Cavity Target Temperature" if "Celsius" in key or key == "cavityTemperatureCelsiusConverted" \
                    else "Cavity Target Temperature (°F)"
            if key in ("probeTemperatureCelsiusConverted", "probeTemperatureFahrenheit"):
                label = "Probe Target Temperature" if "Celsius" in key or key == "probeTemperatureCelsiusConverted" \
                    else "Probe Target Temperature (°F)"

        if key in ("cavityTemperatureCelsiusConverted", "probeTemperatureCelsiusConverted", "celsiusConverted"):
            dev_class = SensorDeviceClass.TEMPERATURE
            unit = UnitOfTemperature.CELSIUS
        if key in ("cavityTemperatureFahrenheit", "probeTemperatureFahrenheit", "fahrenheit"):
            dev_class = SensorDeviceClass.TEMPERATURE
            unit = UnitOfTemperature.FAHRENHEIT

        # Temperature label routing
        if key in ("celsiusConverted", "fahrenheit") and stype == "cloud.smarthq.service.temperature":
            dom_low = (dom or "").lower()
            if ("measurement" in dom_low) or ("early.temperature" in dom_low):
                label = "Ambient Temperature" if key == "celsiusConverted" else "Ambient Temperature (°F)"
            elif "cooking" in dom_low:
                label = "Cavity Temperature" if key == "celsiusConverted" else "Cavity Temperature (°F)"

        # Unify progress labels
        if key == "preheatProgress":
            label = "Preheat Progress"
            dev_class = None
            unit = PERCENTAGE

        if label in made_labels:
            continue
        st = services.get(sid) or {}

        # 🔸 Allow creating entity for Preheat Progress even without key
        if key != "preheatProgress" and key not in st:
            continue

        pair = (sid, key)
        if pair in added_pairs:
            continue
        result.append(
            SmartHQSnapshotSensor(
                hass, entry, device_id,
                label=label, state_key=key, icon=None,
                device_class=dev_class, unit=unit, service_id=sid,
            )
        )
        added_pairs.add(pair)
        made_labels.add(label)

    return result


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    entities: List[SensorEntity] = []
    for did in list(_store(hass, entry).keys()):
        entities.extend(list(_iter_dynamic_sensors(hass, entry, did)))
    async_add_entities(entities, update_before_add=False)
