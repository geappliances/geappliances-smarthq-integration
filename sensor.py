# /config/custom_components/smarthq/sensor.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    UnitOfTemperature,
    UnitOfTime,
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    UnitOfVolume,
    UnitOfMass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
import logging

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN, MANUFACTURER, DEFAULT_NAME, sdev_prefix, OPTION_SHOW_ALT_TEMPS
from .dispatcher import SIGNAL_DEVICE_UPDATED
from .service_registry import (
    TEMPERATURE_SERVICE,
    INTEGER_SERVICE,
    METER_SERVICE,
    ENVIRONMENTAL_SERVICE,
    FIRMWARE_SERVICE,
    CYCLETIMER_SERVICE,
    DOUBLE_SERVICE,
    STRING_SERVICE,
    BATTERY_SERVICE,
    COOKING_STATE_SERVICE,
    LAUNDRY_STATE_SERVICE,
    STOPWATCH_SERVICE,
    VOLUME_LIQUID_SERVICE,
    SCALE_SERVICE,
    POWER_USAGE_SERVICE,
    DELAYWINDOW_SERVICE,
    BREW_MODE_SERVICE,
    DISHWASHER_STATE_V1_SERVICE,
    DISHWASHER_RINSE_AGENT_SERVICE,
    DISHDRAWER_STATE_LEGACY_SERVICE,
    DESCALE_V1_SERVICE,
    DRYER_VENT_HEALTH_MODE_SERVICE,
    LAUNDRY_BULKTANK_SERVICE,
    OUTDOORUNIT_INFO_SERVICE,
    SMARTDISPENSE_SERVICE,
    COOKING_OVEN_PROBE_TEMP_SERVICE,
    COOKING_BURNER_STATUS_SERVICE,
    COOKING_ADVANTIUM_SERVICE,
    ESPRESSOMAKER_SERVICE,
    MIXER_SERVICE,
    PIZZAOVEN_STATE_SERVICE,
    SOURDOUGHSTARTER_SERVICE,
    COOKTOP_CLOSEDLOOP_SERVICE,
    COOKTOP_SOUSVIDE_SERVICE,
    OVEN_FLEXTIMER_SERVICE,
    DRYER_CONFIG_CYCLE_V1_SERVICE,
    DRYER_MYCYCLE_SERVICE,
    WASHER_CONFIG_CYCLE_V1_SERVICE,
    WASHER_MYCYCLE_SERVICE,
    DEMANDRESPONSE_STATE_V1_SERVICE,
    OVEN_MENUTREE_SERVICE,
    LAUNDRY_COMMERCIAL_V1_SERVICE,
    LAUNDRY_DOWNLOADABLECYCLE_SERVICE,
    LAUNDRY_PETHAIR_SERVICE,
    DEMANDRESPONSE_EVENT_V1_SERVICE,
    LAUNDRY_PRICEMENU_V1_SERVICE,
    DISHWASHER_STATE_LEGACY_SERVICE,
    CMD_STRING_SET,
    CMD_TEMPERATURE_SET,
    CMD_INTEGER_SET,
    ENVIRONMENTAL_DOMAIN_DEVICE_CLASS,
    METER_DOMAIN_UNIT_CLASS,
    get_device_services,
    make_unique_id,
)


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

def _device_temp_is_f(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> bool:
    """Return True if the device's temperatureunits service is set to Fahrenheit.

    Priority order:
    1. hass.data temp-unit cache (set immediately when user changes Temperatureunits select)
    2. WS snapshot (store) — real-time, populated after first WS update
    3. coordinator.data — initial REST load
    4. HA system unit fallback
    """
    # 1. Immediate cache (updated by SmartHQModeSelect when temperatureunits changes)
    domain_data = hass.data.get(DOMAIN) or {}
    entry_data = domain_data.get(entry.entry_id) or {}
    temp_unit_cache: dict = entry_data.get("temp_unit_cache") or {}
    if device_id in temp_unit_cache:
        return temp_unit_cache[device_id]

    # 2. WS snapshot (store) — real-time
    snap = _snapshot_for(hass, entry, device_id)
    for st in (snap.get("services") or {}).values():
        if isinstance(st, dict):
            dom = str(st.get("domainType") or "")
            if "temperatureunits" in dom.lower():
                mode = str(st.get("mode") or "")
                return "fahrenheit" in mode.lower()

    # 3. coordinator.data — initial REST load
    bucket = _bucket(hass, entry)
    coordinator = bucket.get("coordinator")
    if coordinator and coordinator.data:
        dev_data = coordinator.data.get(device_id) or {}
        services_list = (dev_data.get("item") or {}).get("services") or []
        for svc in services_list:
            if isinstance(svc, dict):
                dom = str(svc.get("domainType") or "")
                if "temperatureunits" in dom.lower():
                    mode = str((svc.get("state") or {}).get("mode") or "")
                    return "fahrenheit" in mode.lower()

    # 4. Fallback: HA system unit
    return hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT


def _allow_key_for_system_unit(hass: HomeAssistant, entry: ConfigEntry, key: str, device_id: str = "") -> bool:
    """Filter temperature keys so only the one matching the device's unit is created.

    When show_alt_temps option is on, both C and F keys are allowed.
    Otherwise only the key matching the device's temperatureunits setting is kept.
    """
    show_alt = entry.options.get(OPTION_SHOW_ALT_TEMPS, False)
    if show_alt:
        return True
    dev_is_f = _device_temp_is_f(hass, entry, device_id) if device_id else (
        hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT
    )
    if key in _C_KEYS:
        return not dev_is_f
    if key in _F_KEYS:
        return dev_is_f
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


# Map domainType tail keyword → human-readable prefix for time sensors
_DOMAIN_TIME_PREFIX: Dict[str, str] = {
    "cooking":    "Cook",
    "laundry":    "Cycle",
    "washer":     "Cycle",
    "dryer":      "Cycle",
    "dishwasher": "Cycle",
    "brew":       "Brew",
    "coffee":     "Brew",
    "bake":       "Cook",
    "roast":      "Cook",
    "oven":       "Cook",
}

_KEY_TIME_SUFFIX: Dict[str, str] = {
    "secondsRemaining": "Time Remaining",
    "secondsElapsed":   "Time Elapsed",
    "cookTimeInitial":  "Time Initial",
}

def _label_for_time_key(key: str, stype: str, dom: str) -> str:
    """Generate a human-readable label for time keys based on serviceType/domainType.

    Examples:
      secondsRemaining + cooking domain  → "Cook Time Remaining"
      secondsRemaining + laundry domain  → "Cycle Time Remaining"
      secondsRemaining + unknown domain  → "Time Remaining"
    """
    suffix = _KEY_TIME_SUFFIX.get(key)
    if not suffix:
        return key.replace("_", " ").title()

    combined = (stype + " " + dom).lower()
    for keyword, prefix in _DOMAIN_TIME_PREFIX.items():
        if keyword in combined:
            return f"{prefix} {suffix}"
    return suffix  # no matching domain → plain "Time Remaining" etc.


# ---- Temperature domain → label prefix ----
_TEMP_DOMAIN_LABEL: Dict[str, str] = {
    "measurement": "Ambient",
    "early":       "Ambient",
    "cooking":     "Cavity",
    "probe":       "Probe",
    "cavity":      "Cavity",
    "smoker":      "Cavity",
}


def _camel_to_words(key: str) -> str:
    """Convert camelCase or snake_case key to Title Case words.

    Examples:
      runStatus           → "Run Status"
      secondsRemaining    → "Seconds Remaining"
      laundryDrynessLevel → "Laundry Dryness Level"
      versionCurrent      → "Version Current"
    """
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", key)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", s)
    return s.replace("_", " ").strip().title()


def _label_for_key(key: str, stype: str = "", dom: str = "") -> str:
    """Generate a human-readable label for any state_key with optional context.

    Dispatch order:
      1. Time keys  → _label_for_time_key (domain-aware)
      2. Temperature keys → domain-aware prefix + "Temperature [°F]"
      3. Everything else → _camel_to_words(key)
    """
    # 1. Time keys
    if key in _KEY_TIME_SUFFIX:
        return _label_for_time_key(key, stype, dom)

    # 2. Temperature keys: derive prefix from domainType / serviceType
    if key in _C_KEYS or key in _F_KEYS:
        unit_sfx = "" if key in _C_KEYS else " (°F)"
        combined_low = (stype + " " + dom).lower()
        for kw, prefix in _TEMP_DOMAIN_LABEL.items():
            if kw in combined_low:
                return f"{prefix} Temperature{unit_sfx}"
        # Fallback: domain tail
        dom_tail = dom.split(".")[-1].replace("_", " ").title() if dom else ""
        prefix = dom_tail if dom_tail else "Ambient"
        return f"{prefix} Temperature{unit_sfx}"

    # 3. Generic camelCase conversion
    return _camel_to_words(key)


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

# Labels are generated dynamically via _label_for_key(key, stype, dom).
# name="" means "derive from key+context at runtime".
_DYN_KEYS: List[_DynKey] = [
    # Temperature — label generated by _label_for_key (domain-aware prefix)
    _DynKey("", "celsiusConverted", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, "mdi:thermometer"),
    _DynKey("", "fahrenheit", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT, "mdi:thermometer"),
    _DynKey("", "cavityTemperatureCelsiusConverted", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, "mdi:thermometer"),
    _DynKey("", "cavityTemperatureFahrenheit", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT, "mdi:thermometer"),
    _DynKey("", "probeTemperatureCelsiusConverted", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, "mdi:thermometer"),
    _DynKey("", "probeTemperatureFahrenheit", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT, "mdi:thermometer"),
    # Timer/progress — label generated by _label_for_key (time/domain-aware)
    _DynKey("", "cookTimeInitial", None, None, "mdi:timer"),
    _DynKey("", "secondsRemaining", None, None, "mdi:timer-outline"),
    _DynKey("", "secondsElapsed", None, None, "mdi:timer-sand"),
    _DynKey("", "preheatProgress", None, PERCENTAGE, "mdi:progress-clock"),
    # Others — label = _camel_to_words(key)
    _DynKey("", "signalStrength", None, None, "mdi:wifi-strength-2"),
    _DynKey("", "numericOptionValue", None, None, "mdi:fire"),
    _DynKey("", "runStatus", None, None, "mdi:information"),
    _DynKey("", "mode", None, None, "mdi:tune"),
    _DynKey("", "value"),
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
        self._fixed_unit = unit  # used only for non-temp keys
        self._fixed_device_class = device_class
        # For temperature keys we compute unit/device_class dynamically.
        # Do NOT set _attr_native_unit_of_measurement or _attr_device_class for
        # temp keys — HA caches _attr_ values and they take priority over properties.
        self._is_temp_key = state_key in _C_KEYS or state_key in _F_KEYS
        if not self._is_temp_key:
            self._attr_native_unit_of_measurement = unit
            self._attr_device_class = device_class

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
        # Read stype/dom directly from the stored service state to avoid lossy
        # index_map dedup (index_map only keeps the last sid per (stype,dom) pair).
        stype = st.get("serviceType") or ""
        dom = st.get("domainType") or ""
        return st, stype, dom

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
        if self._is_temp_key:
            # Check the F-key (always present in snapshot regardless of unit setting)
            return self._f_key_for(self._state_key) in st
        return self._state_key in st

    @property
    def device_class(self) -> Optional[SensorDeviceClass]:
        if self._is_temp_key:
            return SensorDeviceClass.TEMPERATURE
        return self._fixed_device_class

    @property
    def native_unit_of_measurement(self) -> Optional[str]:
        if not self._is_temp_key:
            return self._fixed_unit
        return (
            UnitOfTemperature.FAHRENHEIT
            if _device_temp_is_f(self.hass, self._entry, self._device_id)
            else UnitOfTemperature.CELSIUS
        )

    def _f_key_for(self, key: str) -> str:
        """Return the °F sibling key so we always read from the F key and convert."""
        _to_f = {
            "celsiusConverted": "fahrenheit",
            "cavityTemperatureCelsiusConverted": "cavityTemperatureFahrenheit",
            "probeTemperatureCelsiusConverted": "probeTemperatureFahrenheit",
        }
        return _to_f.get(key, key)  # already an F key → return as-is

    @property
    def native_value(self):
        st, stype, dom = self._get_service_meta()
        if self._state_key == "preheatProgress":
            return self._resolve_preheat_value(st, stype, dom)

        if self._is_temp_key:
            # Always read from the Fahrenheit key; convert to °C when needed
            f_key = self._f_key_for(self._state_key)
            raw = st.get(f_key)
            if raw is None:
                return None
            try:
                f_val = float(raw)
            except (TypeError, ValueError):
                return raw
            if _device_temp_is_f(self.hass, self._entry, self._device_id):
                return round(f_val, 1)
            return round((f_val - 32) * 5 / 9, 1)

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
        self.async_write_ha_state()



# -------------------------
# Discovery
# -------------------------

# ---------------------------------------------------------------------------
# Helpers: map SmartHQ units → HA units / device class
# ---------------------------------------------------------------------------

def _integer_units_to_ha(int_units: str) -> tuple:
    """Map INTEGER_UNITS string to (ha_unit, SensorDeviceClass | None)."""
    _map = {
        "percentage":           (PERCENTAGE, SensorDeviceClass.BATTERY),
        "kwh":                  (UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY),
        "watts":                (UnitOfPower.WATT, SensorDeviceClass.POWER),
        "dbm":                  ("dBm", SensorDeviceClass.SIGNAL_STRENGTH),
        "temperature.fahrenheit": (UnitOfTemperature.FAHRENHEIT, SensorDeviceClass.TEMPERATURE),
        "rpm":                  ("rpm", None),
        "cfm":                  ("ft³/min", None),
        "minutes":              ("min", None),
        "seconds":              ("s", None),
        "hours":                ("h", None),
        "days":                 ("d", None),
        "count":                (None, None),
        "level":                (None, None),
        "unitless":             (None, None),
    }
    return _map.get(int_units, (None, None))


def _meter_units_to_ha(meter_units: str, dom: str) -> tuple:
    """Map METER_UNITS string (+ domainType fallback) to (ha_unit, SensorDeviceClass)."""
    _map = {
        "kwh":        (UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY),
        "kw":         (UnitOfPower.KILO_WATT, SensorDeviceClass.POWER),
        "volts":      (UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
        "amps":       (UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
        "liters":     (UnitOfVolume.LITERS, SensorDeviceClass.WATER),
        "milileters": (UnitOfVolume.MILLILITERS, SensorDeviceClass.WATER),
        "cubicfeet":  (UnitOfVolume.CUBIC_FEET, SensorDeviceClass.WATER),
    }
    if meter_units in _map:
        return _map[meter_units]
    # Fallback via domain
    if dom in METER_DOMAIN_UNIT_CLASS:
        unit_str, cls_str = METER_DOMAIN_UNIT_CLASS[dom]
        cls_map = {
            "energy": SensorDeviceClass.ENERGY,
            "voltage": SensorDeviceClass.VOLTAGE,
            "water": SensorDeviceClass.WATER,
        }
        return unit_str, cls_map.get(cls_str)
    return (None, None)


# ---------------------------------------------------------------------------
# Sensor classes (coordinator / service-based)
# ---------------------------------------------------------------------------

class SmartHQServiceSensor(SensorEntity):
    """Generic sensor that reads a single state key from the WS snapshot.

    Created from coordinator.data service definitions; state values come from
    the live WebSocket snapshot store (same as SmartHQSnapshotSensor).
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        service_id: str,
        dev_name: str,
        label: str,
        state_key: str,
        device_class,
        unit,
        unique_id: str,
        entity_category=None,
        enabled_default: bool = True,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._state_key = state_key
        self._attr_name = f"{dev_name} {label}"
        # Only set _attr_ when a value is given; None would shadow subclass properties.
        if device_class is not None:
            self._attr_device_class = device_class
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = unique_id
        if entity_category is not None:
            self._attr_entity_category = entity_category
        self._attr_entity_registry_enabled_default = enabled_default

    def _get_state(self) -> dict:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        services = snap.get("services") or {}
        return services.get(self._service_id) or {}

    @property
    def native_value(self):
        st = self._get_state()
        return st.get(self._state_key)

    @property
    def available(self) -> bool:
        st = self._get_state()
        if not st:
            return False
        if st.get("disabled"):
            return False
        return self._state_key in st

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
        self.async_write_ha_state()


class SmartHQTempSensor(SmartHQServiceSensor):
    """Temperature sensor whose unit follows the device's temperatureunits setting.

    A single entity is created per temperature service (replacing the old
    separate °C / °F pair).  The sensor always reads the Fahrenheit snapshot
    key and converts the value on-the-fly when the device is in Celsius mode.
    """

    def __init__(
        self,
        hass, entry, device_id, service_id, dev_name,
        label: str, unique_id: str,
    ) -> None:
        # Pass unit=None so SmartHQServiceSensor.__init__ does NOT set
        # _attr_native_unit_of_measurement — our property must take priority.
        super().__init__(
            hass, entry, device_id, service_id, dev_name,
            label, "fahrenheit",
            None, None,  # device_class and unit: do NOT fix via _attr_
            unique_id,
        )

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.TEMPERATURE

    @property
    def native_unit_of_measurement(self) -> str:
        return (
            UnitOfTemperature.FAHRENHEIT
            if _device_temp_is_f(self.hass, self._entry, self._device_id)
            else UnitOfTemperature.CELSIUS
        )

    @property
    def native_value(self):
        st = self._get_state()
        raw = st.get("fahrenheit")
        if raw is None:
            return None
        try:
            f_val = float(raw)
        except (TypeError, ValueError):
            return raw
        if _device_temp_is_f(self.hass, self._entry, self._device_id):
            return round(f_val, 1)
        return round((f_val - 32) * 5 / 9, 1)

    @property
    def available(self) -> bool:
        st = self._get_state()
        return bool(st) and not st.get("disabled") and "fahrenheit" in st


class SmartHQRawTempSensor(SmartHQServiceSensor):
    """Temperature sensor that reads a named key (raw °F or °C) and converts dynamically.

    Unlike SmartHQTempSensor (which always reads the 'fahrenheit' key),
    this class accepts any state_key and a raw_unit to handle services
    that expose temperature under arbitrary key names (e.g. domeFrontTemperature,
    targetTemperatureFahrenheit, brewTemperature).

    Conversion follows the device's own temperatureunits setting via
    _device_temp_is_f(), which checks the cache, WS snapshot, coordinator data,
    and HA system unit in that priority order.
    """

    def __init__(
        self,
        hass, entry, device_id, service_id, dev_name,
        label: str, state_key: str, raw_unit: str, unique_id: str,
    ) -> None:
        # Pass unit=None so _attr_ does not fix the unit — our property overrides it.
        super().__init__(
            hass, entry, device_id, service_id, dev_name,
            label, state_key,
            None, None,
            unique_id,
        )
        self._raw_unit = raw_unit  # UnitOfTemperature.FAHRENHEIT or CELSIUS

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.TEMPERATURE

    @property
    def native_unit_of_measurement(self) -> str:
        return (
            UnitOfTemperature.FAHRENHEIT
            if _device_temp_is_f(self.hass, self._entry, self._device_id)
            else UnitOfTemperature.CELSIUS
        )

    @property
    def native_value(self):
        st = self._get_state()
        raw = st.get(self._state_key)
        if raw is None:
            return None
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return raw
        is_f = _device_temp_is_f(self.hass, self._entry, self._device_id)
        if self._raw_unit == UnitOfTemperature.FAHRENHEIT:
            return round(val, 1) if is_f else round((val - 32) * 5 / 9, 1)
        else:  # raw is °C
            return round(val * 9 / 5 + 32, 1) if is_f else round(val, 1)

    @property
    def available(self) -> bool:
        st = self._get_state()
        return bool(st) and not st.get("disabled") and self._state_key in st


class SmartHQMeterSensor(SmartHQServiceSensor):
    """Sensor for meter services (cumulative energy, water, etc.)."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        hass, entry, device_id, service_id, dev_name,
        label, unit, device_class, unique_id,
    ) -> None:
        super().__init__(
            hass, entry, device_id, service_id, dev_name,
            label, "meterValue", device_class, unit, unique_id,
        )

    @property
    def extra_state_attributes(self) -> dict:
        st = self._get_state()
        return {
            "meter_value_delta": st.get("meterValueDelta"),
            "update_frequency_seconds": st.get("updateFrequencySeconds"),
        }


class SmartHQEnvironmentalSensor(SmartHQServiceSensor):
    """Sensor for environmental.sensor services (air quality, humidity, etc.)."""

    def __init__(
        self,
        hass, entry, device_id, service_id, dev_name,
        label, env_class_str: str, unique_id,
    ) -> None:
        # Map device class string to HA device class enum
        _cls_map = {
            "temperature":               SensorDeviceClass.TEMPERATURE,
            "humidity":                  SensorDeviceClass.HUMIDITY,
            "volatile_organic_compounds": SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
            "pm25":                      SensorDeviceClass.PM25,
            "pm10":                      SensorDeviceClass.PM10,
            "pm1":                       SensorDeviceClass.PM1,
            "aqi":                       SensorDeviceClass.AQI,
        }
        dev_class = _cls_map.get(env_class_str)
        # stateValue is the primary measurement
        super().__init__(
            hass, entry, device_id, service_id, dev_name,
            label, "stateValue", dev_class, None, unique_id,
        )

    @property
    def extra_state_attributes(self) -> dict:
        st = self._get_state()
        return {
            "index_value": st.get("indexValue"),
            "air_quality_value": st.get("airQualityValue"),
            "update_period_value": st.get("updatePeriodValue"),
        }


class SmartHQLaundryStateSensor(SmartHQServiceSensor):
    """Sensor for laundry.state.v1 services.

    Enum values (e.g. cloud.smarthq.type.laundry.cycle.cottons) are
    rendered as the tail token in UPPER_CASE for a tidy HA display.
    """

    def __init__(
        self,
        hass, entry, device_id, service_id, dev_name,
        label, state_key, unique_id,
    ) -> None:
        super().__init__(
            hass, entry, device_id, service_id, dev_name,
            label, state_key, None, None, unique_id,
        )
        self._attr_icon = _LAUNDRY_STATE_ICONS.get(state_key, "mdi:washing-machine")

    @property
    def native_value(self):
        st = self._get_state()
        val = st.get(self._state_key)
        return _tail_enum(val)

    @property
    def extra_state_attributes(self) -> dict:
        """Expose raw enum value alongside the human-friendly tail."""
        st = self._get_state()
        raw = st.get(self._state_key)
        return {"raw": raw} if raw is not None else {}


# Icon map for laundry state fields
_LAUNDRY_STATE_ICONS: dict[str, str] = {
    "runStatus":           "mdi:washing-machine",
    "cycle":               "mdi:refresh-circle",
    "subCycle":            "mdi:progress-clock",
    "laundrySpin":         "mdi:rotate-3d-variant",
    "laundryTemperature":  "mdi:thermometer-water",
    "laundryRinse":        "mdi:water",
    "laundrySoil":         "mdi:blur",
    "laundryDrynessLevel": "mdi:air-humidifier-off",
    "stain":               "mdi:sticker-remove-outline",
}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _iter_dynamic_sensors(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Iterable[SmartHQSnapshotSensor]:
    snap = _snapshot_for(hass, entry, device_id)
    services: Dict[str, Dict[str, Any]] = snap.get("services") or {}
    if not services:
        return []

    # Build sid -> (serviceType, domainType) directly from services_map so that
    # services sharing the same (stype, domain) but different serviceDeviceType
    # (e.g. two temperature/measurement services: probe vs smoker cavity) are
    # ALL included.  The index_map only stores the last sid per (stype,dom) key
    # which would silently drop duplicates.
    rev: Dict[str, Tuple[str, str]] = {
        sid: (str(st.get("serviceType") or ""), str(st.get("domainType") or ""))
        for sid, st in services.items()
    }

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
            if not _allow_key_for_system_unit(hass, entry, key, device_id):
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
            if k not in chosen_sid_for_key and _allow_key_for_system_unit(hass, entry, k, device_id):
                chosen_sid_for_key[k] = sid

    # 1) Pretty labels first (icons / units from _DYN_KEYS)
    for dyn in _DYN_KEYS:
        key = dyn.key
        sid = chosen_sid_for_key.get(key)
        if not sid:
            continue
        st = services.get(sid) or {}

        # 🔸 Allow creating entity for Preheat Progress even without key
        if key != "preheatProgress" and key not in st:
            continue

        stype, dom = rev.get(sid, (None, ""))
        # cooking.mode.v1 temperature keys → "Target" prefix
        if stype == "cloud.smarthq.service.cooking.mode.v1" and key in _C_KEYS | _F_KEYS:
            unit_sfx = "" if key in _C_KEYS else " (°F)"
            if "cavity" in key.lower():
                label = f"Cavity Target Temperature{unit_sfx}"
            elif "probe" in key.lower():
                label = f"Probe Target Temperature{unit_sfx}"
            else:
                label = f"Target Temperature{unit_sfx}"
        else:
            label = _label_for_key(key, stype or "", dom or "")

        unit = dyn.unit
        dev_class = dyn.device_class
        icon = dyn.icon

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

    # 2) Fallback labels for remaining keys not covered by _DYN_KEYS
    for key, sid in chosen_sid_for_key.items():
        stype, dom = rev.get(sid, (None, ""))
        dev_class = None
        unit = None

        # cooking.mode.v1 temperature keys → "Target" prefix
        if stype == "cloud.smarthq.service.cooking.mode.v1" and key in _C_KEYS | _F_KEYS:
            unit_sfx = "" if key in _C_KEYS else " (°F)"
            if "cavity" in key.lower():
                label = f"Cavity Target Temperature{unit_sfx}"
            elif "probe" in key.lower():
                label = f"Probe Target Temperature{unit_sfx}"
            else:
                label = f"Target Temperature{unit_sfx}"
        else:
            label = _label_for_key(key, stype or "", dom or "")

        if key in _C_KEYS:
            dev_class = SensorDeviceClass.TEMPERATURE
            unit = UnitOfTemperature.CELSIUS
        elif key in _F_KEYS:
            dev_class = SensorDeviceClass.TEMPERATURE
            unit = UnitOfTemperature.FAHRENHEIT
        elif key == "preheatProgress":
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
    """Set up SmartHQ sensor entities.

    Two complementary sources:
    1. coordinator.data[device_id]["item"]["services"] — generic service sensors
       (temperature/integer/meter/environmental/firmware).
    2. WS snapshot _iter_dynamic_sensors — cooking-state sensors (Smoker, Oven…)
       that use device-specific state keys outside the generic service schema.
    """
    entities: List[SensorEntity] = []

    # ── Source 1: coordinator service-based sensors ───────────────────────────
    bucket = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    coordinator = bucket.get("coordinator")
    if coordinator and coordinator.data:
        existing_uids: set[str] = {e.unique_id for e in entities if e.unique_id}

        for device_id, device_item in coordinator.data.items():
            item = device_item.get("item") or {}
            services_list: list = item.get("services") or []
            if not isinstance(services_list, list):
                continue

            info = device_item.get("info") or {}  # coordinator stores info at top level
            # Fallback: item itself may contain nickname directly (API response)
            dev_name = (info.get("nickname") or info.get("name")
                        or item.get("nickname") or item.get("name")
                        or DEFAULT_NAME)

            for svc in services_list:
                if not isinstance(svc, dict):
                    continue

                stype = svc.get("serviceType") or ""
                dom = svc.get("domainType") or ""
                service_id = svc.get("id") or svc.get("serviceId") or ""
                cmds: list = svc.get("supportedCommands") or []
                cfg = svc.get("config") or {}

                # ── temperature sensor (read-only) ──────────────────────────
                if stype == TEMPERATURE_SERVICE and CMD_TEMPERATURE_SET not in cmds:
                    sdev = svc.get("serviceDeviceType") or ""
                    # For measurement domain with two serviceDeviceType instances
                    # (Smoker: device.smoker=Cavity, device.probe=Ambient)
                    if "measurement" in dom.lower() and "smoker" in sdev.lower():
                        label = "Cavity Temperature"
                    else:
                        _base = _label_for_key("fahrenheit", stype, dom)
                        _prefix = sdev_prefix(sdev)
                        label = f"{_prefix} {_base}".strip() if _prefix else _base

                    # Single entity whose unit follows the device's temperatureunits
                    # setting at runtime.  Use the legacy °F uid for continuity.
                    uid = make_unique_id(device_id, service_id, "fahrenheit")
                    if uid not in existing_uids:
                        entities.append(SmartHQTempSensor(
                            hass, entry, device_id, service_id, dev_name,
                            label, uid,
                        ))
                        existing_uids.add(uid)

                # ── integer sensor (read-only) ──────────────────────────────
                elif stype == INTEGER_SERVICE and CMD_INTEGER_SET not in cmds:
                    int_units = cfg.get("integerUnits") or ""
                    label_base = cfg.get("label") or _camel_to_words(dom.split(".")[-1])
                    ha_unit, dev_class = _integer_units_to_ha(int_units)
                    uid = make_unique_id(device_id, service_id, "integer")
                    if uid not in existing_uids:
                        entities.append(SmartHQServiceSensor(
                            hass, entry, device_id, service_id, dev_name,
                            label_base, "value",
                            dev_class, ha_unit, uid,
                        ))
                        existing_uids.add(uid)

                # ── meter sensor ────────────────────────────────────────────
                elif stype == METER_SERVICE:
                    meter_units = cfg.get("meterUnits") or ""
                    ha_unit, dev_class = _meter_units_to_ha(meter_units, dom)
                    label_base = _camel_to_words(dom.split(".")[-1]) + " Meter"
                    uid = make_unique_id(device_id, service_id, "meter")
                    if uid not in existing_uids:
                        entities.append(SmartHQMeterSensor(
                            hass, entry, device_id, service_id, dev_name,
                            label_base, ha_unit, dev_class, uid,
                        ))
                        existing_uids.add(uid)

                # ── environmental sensor ────────────────────────────────────
                elif stype == ENVIRONMENTAL_SERVICE:
                    env_class = ENVIRONMENTAL_DOMAIN_DEVICE_CLASS.get(dom, "")
                    uid = make_unique_id(device_id, service_id, "env")
                    label_base = _camel_to_words(dom.split(".")[-1])
                    if uid not in existing_uids:
                        entities.append(SmartHQEnvironmentalSensor(
                            hass, entry, device_id, service_id, dev_name,
                            label_base, env_class, uid,
                        ))
                        existing_uids.add(uid)

                # ── firmware version sensors (hidden by default — diagnostic only) ──
                elif stype == FIRMWARE_SERVICE:
                    for state_key, uid_sfx in [
                        ("versionCurrent",   "fw_current"),
                        ("versionAvailable", "fw_available"),
                        ("upgradeStatus",    "fw_status"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQServiceSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key,
                                None, None, uid,
                                entity_category=EntityCategory.DIAGNOSTIC,
                                enabled_default=False,
                            ))
                            existing_uids.add(uid)

                # ── cycletimer sensor ───────────────────────────────────────
                elif stype == CYCLETIMER_SERVICE:
                    for state_key, uid_sfx in [
                        ("timeRemaining", "timer_remaining"),
                        ("timeElapsed",   "timer_elapsed"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQServiceSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _label_for_key(state_key, stype, dom), state_key,
                                SensorDeviceClass.DURATION, "s", uid,
                            ))
                            existing_uids.add(uid)

                # ── double sensor (float value) ─────────────────────────────
                elif stype == DOUBLE_SERVICE:
                    label_base = cfg.get("label") or _camel_to_words(dom.split(".")[-1])
                    uid = make_unique_id(device_id, service_id, "double")
                    if uid not in existing_uids:
                        entities.append(SmartHQServiceSensor(
                            hass, entry, device_id, service_id, dev_name,
                            label_base, "value",
                            None, None, uid,
                        ))
                        existing_uids.add(uid)

                # ── string sensor ───────────────────────────────────────────
                elif stype == STRING_SERVICE and CMD_STRING_SET not in cmds:
                    # Read-only: expose as sensor. Writable case → text.py
                    label_base = cfg.get("label") or _camel_to_words(dom.split(".")[-1])
                    uid = make_unique_id(device_id, service_id, "string")
                    if uid not in existing_uids:
                        entities.append(SmartHQServiceSensor(
                            hass, entry, device_id, service_id, dev_name,
                            label_base, "stringValue",
                            None, None, uid,
                        ))
                        existing_uids.add(uid)

                # ── battery sensor ──────────────────────────────────────────
                elif stype == BATTERY_SERVICE:
                    uid = make_unique_id(device_id, service_id, "battery")
                    if uid not in existing_uids:
                        entities.append(SmartHQServiceSensor(
                            hass, entry, device_id, service_id, dev_name,
                            _camel_to_words("batteryLevel"), "level",
                            SensorDeviceClass.BATTERY, PERCENTAGE, uid,
                        ))
                        existing_uids.add(uid)

                # ── cooking state sensor (read-only status) ─────────────────
                elif stype == COOKING_STATE_SERVICE:
                    for state_key, uid_sfx in [
                        ("cookingStatus", "cook_status"),
                        ("runStatus",     "run_status"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQServiceSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key,
                                None, None, uid,
                            ))
                            existing_uids.add(uid)

                # ── stopwatch sensor ───────────────────────────────────────
                elif stype == STOPWATCH_SERVICE:
                    uid = make_unique_id(device_id, service_id, "stopwatch_elapsed")
                    if uid not in existing_uids:
                        entities.append(SmartHQServiceSensor(
                            hass, entry, device_id, service_id, dev_name,
                            _camel_to_words("secondsElapsed"), "secondsElapsed",
                            SensorDeviceClass.DURATION, "s", uid,
                        ))
                        existing_uids.add(uid)

                # ── volume.liquid.v1 sensor ─────────────────────────────────
                elif stype == VOLUME_LIQUID_SERVICE:
                    uid = make_unique_id(device_id, service_id, "volume_liters")
                    if uid not in existing_uids:
                        entities.append(SmartHQServiceSensor(
                            hass, entry, device_id, service_id, dev_name,
                            _camel_to_words("liters"), "liters",
                            SensorDeviceClass.WATER, UnitOfVolume.LITERS, uid,
                        ))
                        existing_uids.add(uid)

                # ── scale.v1 sensors ────────────────────────────────────────
                elif stype == SCALE_SERVICE:
                    for state_key, uid_sfx in [
                        ("weightCurrent", "scale_current"),
                        ("weightTarget",  "scale_target"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQServiceSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key,
                                SensorDeviceClass.WEIGHT, UnitOfMass.GRAMS, uid,
                            ))
                            existing_uids.add(uid)

                # ── power.usage sensors ─────────────────────────────────────
                elif stype == POWER_USAGE_SERVICE:
                    for state_key, uid_sfx, dev_cls, unit in [
                        ("instantaneousPower",    "power_instant", SensorDeviceClass.POWER, UnitOfPower.WATT),
                        ("wattSecondsSinceClear", "power_energy",  None,                    "Ws"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQServiceSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key,
                                dev_cls, unit, uid,
                            ))
                            existing_uids.add(uid)

                # ── laundry state sensor ────────────────────────────────────
                elif stype == LAUNDRY_STATE_SERVICE:
                    _LOGGER.debug(
                        "[LAUNDRY_SENSOR] device=%s dev_name=%r service_id=%s creating sensors",
                        device_id[:8], dev_name, service_id[:8],
                    )
                    for state_key, uid_sfx in [
                        ("runStatus",          "laundry_run_status"),
                        ("cycle",              "laundry_cycle"),
                        ("subCycle",           "laundry_subcycle"),
                        ("laundrySpin",        "laundry_spin"),
                        ("laundryTemperature", "laundry_temperature"),
                        ("laundryRinse",       "laundry_rinse"),
                        ("laundrySoil",        "laundry_soil"),
                        ("laundryDrynessLevel","laundry_dryness"),
                        ("stain",              "laundry_stain"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── delaywindow sensors ─────────────────────────────────────
                elif stype == DELAYWINDOW_SERVICE:
                    for state_key, uid_sfx in [
                        ("startTime", "delay_start"),
                        ("endTime",   "delay_end"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQServiceSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key,
                                None, None, uid,
                            ))
                            existing_uids.add(uid)

                # ── brew.mode.v1 sensors ────────────────────────────────────
                elif stype == BREW_MODE_SERVICE:
                    for state_key, uid_sfx, dev_cls, unit in [
                        ("volume",          "brew_volume",      None,                          None),
                        ("grindTime",       "brew_grind_time",  SensorDeviceClass.DURATION,    "s"),
                        ("brewTemperature", "brew_temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            if dev_cls == SensorDeviceClass.TEMPERATURE:
                                entities.append(SmartHQRawTempSensor(
                                    hass, entry, device_id, service_id, dev_name,
                                    _label_for_key(state_key, stype, dom), state_key,
                                    unit, uid,
                                ))
                            else:
                                entities.append(SmartHQServiceSensor(
                                    hass, entry, device_id, service_id, dev_name,
                                    _label_for_key(state_key, stype, dom), state_key,
                                    dev_cls, unit, uid,
                                ))
                            existing_uids.add(uid)

                # ── dishwasher.state.v1 sensors ─────────────────────────────
                elif stype == DISHWASHER_STATE_V1_SERVICE:
                    for state_key, uid_sfx in [
                        ("runStatus",       "dw_run_status"),
                        ("mode",            "dw_mode"),
                        ("cycleIndication", "dw_cycle"),
                        ("delayStart",      "dw_delay_start"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── dishdrawer.state.legacy sensors ──────────────────────────
                elif stype == DISHDRAWER_STATE_LEGACY_SERVICE:
                    for state_key, uid_sfx in [
                        ("runStatus",                  "ddr_run_status"),
                        ("mode",                       "ddr_mode"),
                        ("cycleIndication",            "ddr_cycle"),
                        ("delayStart",                 "ddr_delay_start"),
                        ("dishdrawerModeLegacyOption", "ddr_option"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── dishwasher.rinse.agent sensor ────────────────────────────
                elif stype == DISHWASHER_RINSE_AGENT_SERVICE:
                    uid = make_unique_id(device_id, service_id, "rinse_agent_status")
                    if uid not in existing_uids:
                        entities.append(SmartHQLaundryStateSensor(
                            hass, entry, device_id, service_id, dev_name,
                            _camel_to_words("rinseAgentStatus"), "rinseAgentStatus", uid,
                        ))
                        existing_uids.add(uid)

                # ── dishwasher.state.legacy sensors ──────────────────────────
                elif stype == DISHWASHER_STATE_LEGACY_SERVICE:
                    for state_key, uid_sfx in [
                        ("runStatus",       "dws_lg_run_status"),
                        ("shortNameMode",   "dws_lg_mode"),
                        ("cycleIndication", "dws_lg_cycle"),
                        ("delayStart",      "dws_lg_delay"),
                        ("heatedDry",       "dws_lg_heated_dry"),
                        ("washTemp",        "dws_lg_wash_temp"),
                        ("washZone",        "dws_lg_wash_zone"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── descale.v1 sensors ───────────────────────────────────────
                elif stype == DESCALE_V1_SERVICE:
                    for state_key, uid_sfx, dev_cls, unit in [
                        ("runStatus",         "descale_status", None, None),
                        ("volumeUntilNeeded", "descale_volume", None, "mL"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQServiceSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key,
                                dev_cls, unit, uid,
                            ))
                            existing_uids.add(uid)

                # ── dryer.vent.health.mode sensors ───────────────────────────
                elif stype == DRYER_VENT_HEALTH_MODE_SERVICE:
                    uid = make_unique_id(device_id, service_id, "vent_health_mode")
                    if uid not in existing_uids:
                        entities.append(SmartHQLaundryStateSensor(
                            hass, entry, device_id, service_id, dev_name,
                            _label_for_key("mode", stype, dom), "mode", uid,
                        ))
                        existing_uids.add(uid)

                # ── laundry.bulktank sensors ─────────────────────────────────
                elif stype == LAUNDRY_BULKTANK_SERVICE:
                    for state_key, uid_sfx, dev_cls, unit in [
                        ("tank1usagePercent", "bulktank1_pct", None, PERCENTAGE),
                        ("tank2usagePercent", "bulktank2_pct", None, PERCENTAGE),
                        ("tank1substance",    "bulktank1_sub", None, None),
                        ("tank2substance",    "bulktank2_sub", None, None),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ) if dev_cls is None and unit is None else SmartHQServiceSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, dev_cls, unit, uid,
                            ))
                            existing_uids.add(uid)

                # ── outdoorunit.info sensors ─────────────────────────────────
                elif stype == OUTDOORUNIT_INFO_SERVICE:
                    for state_key, uid_sfx in [
                        ("modelNumber",  "outdoor_model"),
                        ("serialNumber", "outdoor_serial"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQServiceSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key,
                                None, None, uid,
                                entity_category=EntityCategory.DIAGNOSTIC,
                            ))
                            existing_uids.add(uid)

                # ── smartdispense sensors ─────────────────────────────────────
                elif stype == SMARTDISPENSE_SERVICE:
                    for state_key, uid_sfx in [
                        ("level",           "smartdisp_level"),
                        ("substance",       "smartdisp_substance"),
                        ("cyclesRemaining", "smartdisp_cycles"),
                        ("dosing",          "smartdisp_dosing"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── cooking.oven.probe.temperature sensors ────────────────────
                elif stype == COOKING_OVEN_PROBE_TEMP_SERVICE:
                    for state_key, uid_sfx in [
                        ("probeUpperDisplayTemperature", "probe_upper_temp"),
                        ("probeLowerDisplayTemperature", "probe_lower_temp"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQRawTempSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key,
                                UnitOfTemperature.FAHRENHEIT, uid,
                            ))
                            existing_uids.add(uid)

                # ── cooking.burner.status.v1 sensors ─────────────────────────
                elif stype == COOKING_BURNER_STATUS_SERVICE:
                    for state_key, uid_sfx in [
                        ("cooktopStatus", "burner_status"),
                        ("energySource",  "burner_energy_src"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── cooking.advantium sensors ─────────────────────────────────
                elif stype == COOKING_ADVANTIUM_SERVICE:
                    for state_key, uid_sfx, dev_cls, unit in [
                        ("advantiumCookMode",           "adv_cook_mode",   None,                          None),
                        ("cookAction",                  "adv_cook_action", None,                          None),
                        ("preheatStatus",               "adv_preheat",     None,                          None),
                        ("targetTemperatureFahrenheit", "adv_target_temp", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            if dev_cls == SensorDeviceClass.TEMPERATURE:
                                entities.append(SmartHQRawTempSensor(
                                    hass, entry, device_id, service_id, dev_name,
                                    _camel_to_words(state_key), state_key,
                                    unit, uid,
                                ))
                            elif dev_cls is None:
                                entities.append(SmartHQLaundryStateSensor(
                                    hass, entry, device_id, service_id, dev_name,
                                    _camel_to_words(state_key), state_key, uid,
                                ))
                            else:
                                entities.append(SmartHQServiceSensor(
                                    hass, entry, device_id, service_id, dev_name,
                                    _camel_to_words(state_key), state_key, dev_cls, unit, uid,
                                ))
                            existing_uids.add(uid)

                # ── espressomaker.v1 sensors ──────────────────────────────────
                elif stype == ESPRESSOMAKER_SERVICE:
                    for state_key, uid_sfx, dev_cls, unit in [
                        ("runStatus",            "espresso_status",   None,                          None),
                        ("brewType",             "espresso_brew_type",None,                          None),
                        ("brewTemperature",      "espresso_brew_temp",SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
                        ("volume",               "espresso_volume",   None,                          None),
                        ("grindTime",            "espresso_grind",    None,                          None),
                        ("lifetimeCoffeeGround", "espresso_lifetime", None,                          None),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            if dev_cls == SensorDeviceClass.TEMPERATURE:
                                entities.append(SmartHQRawTempSensor(
                                    hass, entry, device_id, service_id, dev_name,
                                    _camel_to_words(state_key), state_key,
                                    unit, uid,
                                ))
                            elif dev_cls is None:
                                entities.append(SmartHQLaundryStateSensor(
                                    hass, entry, device_id, service_id, dev_name,
                                    _camel_to_words(state_key), state_key, uid,
                                ))
                            else:
                                entities.append(SmartHQServiceSensor(
                                    hass, entry, device_id, service_id, dev_name,
                                    _camel_to_words(state_key), state_key, dev_cls, unit, uid,
                                ))
                            existing_uids.add(uid)

                # ── mixer.v1 sensors ──────────────────────────────────────────
                elif stype == MIXER_SERVICE:
                    for state_key, uid_sfx in [
                        ("runStatus",  "mixer_status"),
                        ("speed",      "mixer_speed"),
                        ("direction",  "mixer_direction"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── pizzaoven.state sensors ───────────────────────────────────
                elif stype == PIZZAOVEN_STATE_SERVICE:
                    for state_key, uid_sfx, dev_cls, unit in [
                        ("operatingState",       "pzo_op_state",       None,                          None),
                        ("menuSelection",        "pzo_menu",           None,                          None),
                        ("timerState",           "pzo_timer_state",    None,                          None),
                        ("currentTimeRemaining", "pzo_time_remaining", None,                          None),
                        ("domeFrontTemperature", "pzo_dome_front",     SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT),
                        ("domeRearTemperature",  "pzo_dome_rear",      SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT),
                        ("stoneFrontTemperature","pzo_stone_front",    SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT),
                        ("stoneRearTemperature", "pzo_stone_rear",     SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            if dev_cls == SensorDeviceClass.TEMPERATURE:
                                entities.append(SmartHQRawTempSensor(
                                    hass, entry, device_id, service_id, dev_name,
                                    _camel_to_words(state_key), state_key,
                                    unit, uid,
                                ))
                            else:
                                entities.append(SmartHQLaundryStateSensor(
                                    hass, entry, device_id, service_id, dev_name,
                                    _camel_to_words(state_key), state_key, uid,
                                ))
                            existing_uids.add(uid)

                # ── sourdoughstarter.v1 sensors ───────────────────────────────
                elif stype == SOURDOUGHSTARTER_SERVICE:
                    for state_key, uid_sfx in [
                        ("state",          "sourdough_state"),
                        ("mode",           "sourdough_mode"),
                        ("goalTimeHours",  "sourdough_goal_h"),
                        ("goalTimeMinutes","sourdough_goal_m"),
                        ("flourRatio",     "sourdough_flour"),
                        ("waterRatio",     "sourdough_water"),
                        ("starterRatio",   "sourdough_starter"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── cooktop.closedloop sensors ────────────────────────────────
                elif stype == COOKTOP_CLOSEDLOOP_SERVICE:
                    for state_key, uid_sfx in [
                        ("primaryDeviceStatus",   "cl_primary_status"),
                        ("primaryDeviceType",     "cl_primary_type"),
                        ("primaryDeviceFamily",   "cl_primary_family"),
                        ("primaryShortId",        "cl_primary_id"),
                        ("secondaryDeviceStatus", "cl_secondary_status"),
                        ("secondaryDeviceFamily", "cl_secondary_family"),
                        ("secondaryShortId",      "cl_secondary_id"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── cooktop.sousvide sensors ──────────────────────────────────
                elif stype == COOKTOP_SOUSVIDE_SERVICE:
                    for state_key, uid_sfx in [
                        ("clcCurrentTemperature",          "sv_current_temp"),
                        ("clcTargetTemperature",           "sv_target_temp"),
                        ("closedLoopCookingDeviceBattery", "sv_battery"),
                        ("bluetoothConnectionStatus",      "sv_bt_conn"),
                        ("bluetoothPairedStatus",          "sv_bt_paired"),
                        ("elapsedClosedLoopCookingTime",   "sv_elapsed_time"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── oven.flextimer sensors ────────────────────────────────────
                elif stype == OVEN_FLEXTIMER_SERVICE:
                    for state_key, uid_sfx in [
                        ("cookTimeTotalDuration", "flextimer_duration"),
                        ("addSubtractStatus",     "flextimer_addsubtract"),
                        ("expirationStatus",      "flextimer_expiry"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── laundry.pethair sensor ────────────────────────────────────
                elif stype == LAUNDRY_PETHAIR_SERVICE:
                    uid = make_unique_id(device_id, service_id, "pethair_disabled")
                    if uid not in existing_uids:
                        entities.append(SmartHQLaundryStateSensor(
                            hass, entry, device_id, service_id, dev_name,
                            _camel_to_words("disabled"), "disabled", uid,
                        ))
                        existing_uids.add(uid)

                # ── dryer.config.cycle.v1 sensors ────────────────────────────
                elif stype == DRYER_CONFIG_CYCLE_V1_SERVICE:
                    for state_key, uid_sfx in [
                        ("optionHeatHighMinutes",          "dryercfg_heat_high_min"),
                        ("optionHeatMediumMinutes",        "dryercfg_heat_med_min"),
                        ("optionHeatLowMinutes",           "dryercfg_heat_low_min"),
                        ("optionHeatNoneMinutes",          "dryercfg_heat_none_min"),
                        ("optionHeatHighCelsiusConverted", "dryercfg_heat_high_c"),
                        ("optionHeatLowCelsiusConverted",  "dryercfg_heat_low_c"),
                        ("disabled",                      "dryercfg_disabled"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── dryer.mycycle sensor ──────────────────────────────────────
                elif stype == DRYER_MYCYCLE_SERVICE:
                    uid = make_unique_id(device_id, service_id, "dryer_mycycles")
                    if uid not in existing_uids:
                        entities.append(SmartHQLaundryStateSensor(
                            hass, entry, device_id, service_id, dev_name,
                            _camel_to_words("myCycles"), "myCycles", uid,
                        ))
                        existing_uids.add(uid)

                # ── washer.config.cycle.v1 sensors ───────────────────────────
                elif stype == WASHER_CONFIG_CYCLE_V1_SERVICE:
                    for state_key, uid_sfx in [
                        ("cycleWashColors",    "washercfg_colors"),
                        ("cycleWashWhites",    "washercfg_whites"),
                        ("cycleWashTowels",    "washercfg_towels"),
                        ("cycleWashDelicates", "washercfg_delicates"),
                        ("cycleWashDeepClean", "washercfg_deepclean"),
                        ("cycleWashSpeed",     "washercfg_speed"),
                        ("cycleWashCold",      "washercfg_spin_cold"),
                        ("cycleWashWarm",      "washercfg_spin_warm"),
                        ("cycleWashHot",       "washercfg_spin_hot"),
                        ("disabled",           "washercfg_disabled"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── washer.mycycle sensor ─────────────────────────────────────
                elif stype == WASHER_MYCYCLE_SERVICE:
                    uid = make_unique_id(device_id, service_id, "washer_mycycles")
                    if uid not in existing_uids:
                        entities.append(SmartHQLaundryStateSensor(
                            hass, entry, device_id, service_id, dev_name,
                            _camel_to_words("storedCycles"), "storedCycles", uid,
                        ))
                        existing_uids.add(uid)

                # ── demandresponse.state.v1 sensors ──────────────────────────
                elif stype == DEMANDRESPONSE_STATE_V1_SERVICE:
                    for state_key, uid_sfx in [
                        ("systemStatus", "dr_system_status"),
                        ("energyState",  "dr_energy_state"),
                        ("eventId",      "dr_event_id"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── oven.menutree sensors ─────────────────────────────────────
                elif stype == OVEN_MENUTREE_SERVICE:
                    for state_key, uid_sfx in [
                        ("sequence1",        "menutree_seq1"),
                        ("sequence2",        "menutree_seq2"),
                        ("uuidSelection1",   "menutree_uuid1"),
                        ("uuidSelection2",   "menutree_uuid2"),
                        ("shortnameCavity1", "menutree_short1"),
                        ("shortnameCavity2", "menutree_short2"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── laundry.commercial.v1 sensors ────────────────────────────
                elif stype == LAUNDRY_COMMERCIAL_V1_SERVICE:
                    for state_key, uid_sfx in [
                        ("machineStatus",    "commercial_machine_status"),
                        ("phaseCloud",       "commercial_phase_cloud"),
                        ("phaseDevice",      "commercial_phase_device"),
                        ("selectedCycle",    "commercial_selected_cycle"),
                        ("heatOption",       "commercial_heat_option"),
                        ("soilOption",       "commercial_soil_option"),
                        ("temperatureOption","commercial_temp_option"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                # ── laundry.downloadablecycle sensors ────────────────────────
                elif stype == LAUNDRY_DOWNLOADABLECYCLE_SERVICE:
                    for state_key, uid_sfx in [
                        ("downloadableCycleSelected", "dlcycle_selected"),
                        ("featureVersion",            "dlcycle_version"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                elif stype == DEMANDRESPONSE_EVENT_V1_SERVICE:
                    for state_key, uid_sfx in [
                        ("eventId",           "dr_event_id"),
                        ("curtailmentLevel",  "dr_curtailment"),
                        ("temperatureOffset", "dr_temp_offset"),
                        ("eventStatus",       "dr_event_status"),
                        ("userOption",        "dr_user_option"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)

                elif stype == LAUNDRY_PRICEMENU_V1_SERVICE:
                    for state_key, uid_sfx in [
                        ("cycleWashCold",        "pm_wash_cold"),
                        ("cycleWashWarm",        "pm_wash_warm"),
                        ("cycleWashHot",         "pm_wash_hot"),
                        ("cycleWashDelicates",   "pm_wash_delicates"),
                        ("optionExtraRinse",     "pm_opt_extra_rinse"),
                        ("optionSoilLight",      "pm_opt_soil_light"),
                        ("optionSoilMedium",     "pm_opt_soil_medium"),
                        ("optionSoilHeavy",      "pm_opt_soil_heavy"),
                        ("optionHeatNone",       "pm_heat_none"),
                        ("optionHeatLow",        "pm_heat_low"),
                        ("optionHeatMedium",     "pm_heat_medium"),
                        ("optionHeatHigh",       "pm_heat_high"),
                        ("adjustmentHeatNone",   "pm_adj_heat_none"),
                        ("adjustmentHeatLow",    "pm_adj_heat_low"),
                        ("adjustmentHeatMedium", "pm_adj_heat_med"),
                        ("adjustmentHeatHigh",   "pm_adj_heat_high"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in existing_uids:
                            entities.append(SmartHQLaundryStateSensor(
                                hass, entry, device_id, service_id, dev_name,
                                _camel_to_words(state_key), state_key, uid,
                            ))
                            existing_uids.add(uid)


    # ── Source 2: WS snapshot cooking-state sensors ───────────────────────────
    # These cover cooking-specific sensors (temperatures, timers, preheat
    # progress) for devices like Smoker and Oven that use device-specific
    # state keys not represented by the generic service schema.
    snapshot_entities: List[SensorEntity] = []
    for did in list(_store(hass, entry).keys()):
        snapshot_entities.extend(list(_iter_dynamic_sensors(hass, entry, did)))

    all_entities = entities + snapshot_entities
    if all_entities:
        _LOGGER.debug(
            "[SENSOR_SETUP] Registering %d entities (%d source1 + %d snapshot)",
            len(all_entities), len(entities), len(snapshot_entities),
        )
        async_add_entities(all_entities, update_before_add=False)
