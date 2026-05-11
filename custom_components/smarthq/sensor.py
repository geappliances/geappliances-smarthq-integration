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
    COFFEEBREWER_V1_SERVICE,
    COFFEEBREWER_V2_SERVICE,
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
    get_service_mapping,
    is_platform_mapped,
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
        # Temperature keys: do NOT return SensorDeviceClass.TEMPERATURE.
        # If TEMPERATURE is returned, HA auto-converts native_value to the HA
        # system unit (e.g. °F → °C on metric systems), overriding the device's
        # own temperatureunits setting. Leaving device_class as None disables
        # that auto-conversion so the unit/value we compute is displayed as-is.
        if self._is_temp_key:
            return None
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

    For devices that don't send WS updates (e.g. Refrigerator), falls back to
    the initial state from coordinator.data.
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

    # device_class is intentionally NOT set to SensorDeviceClass.TEMPERATURE.
    # See SmartHQRawTempSensor for the explanation.

    def _get_state(self) -> dict:
        """Return service state: WS snapshot first, then coordinator.data fallback."""
        # 1. WS snapshot (real-time)
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        ws_st = (snap.get("services") or {}).get(self._service_id) or {}
        if ws_st and "fahrenheit" in ws_st:
            return ws_st
        # 2. coordinator.data fallback (for devices with no WS updates, e.g. Refrigerator)
        bucket = _bucket(self.hass, self._entry)
        coordinator = bucket.get("coordinator")
        if coordinator and coordinator.data:
            dev_data = coordinator.data.get(self._device_id) or {}
            services_list = (dev_data.get("item") or {}).get("services") or []
            for svc in services_list:
                if isinstance(svc, dict):
                    sid = svc.get("id") or svc.get("serviceId") or ""
                    if sid == self._service_id:
                        return svc.get("state") or {}
        return ws_st

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

    # device_class is intentionally NOT set to SensorDeviceClass.TEMPERATURE.
    # If device_class=TEMPERATURE is used, HA auto-converts the value to the
    # HA system unit (e.g. °F → °C on metric systems), which overrides the
    # device's own temperatureunits setting. By leaving device_class as None,
    # HA does not convert the value and the display unit exactly matches the
    # device's own temperature unit setting.

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


# ---------------------------------------------------------------------------
# Phase 5: Data-driven standard sensor dispatch
# ---------------------------------------------------------------------------

@dataclass
class _SF:
    """Specification for a single sensor field within a standard service."""

    key: str                                   # state_key to read from WS snapshot
    uid: str                                   # unique_id suffix
    cls: str                                   # "L"=LaundryStateSensor "S"=ServiceSensor "T"=RawTempSensor
    dev_cls: Any = None                        # SensorDeviceClass.* or None
    unit: Any = None                           # unit string or None
    cat: Optional[EntityCategory] = None       # entity_category
    enabled: bool = True                       # entity_registry_enabled_default
    label: str = ""                            # explicit label; "" → _camel_to_words(key)


# Maps serviceType → list[_SF].  async_setup_entry delegates to _build_standard_sensors().
_STANDARD_SENSOR_SPECS: dict[str, list[_SF]] = {
    # ── firmware.v1 ────────────────────────────────────────────────────────
    FIRMWARE_SERVICE: [
        _SF("versionCurrent",   "fw_current",   "S", cat=EntityCategory.DIAGNOSTIC, enabled=False),
        _SF("versionAvailable", "fw_available", "S", cat=EntityCategory.DIAGNOSTIC, enabled=False),
        _SF("upgradeStatus",    "fw_status",    "S", cat=EntityCategory.DIAGNOSTIC, enabled=False),
    ],
    # ── cycletimer ─────────────────────────────────────────────────────────
    CYCLETIMER_SERVICE: [
        _SF("timeRemaining", "timer_remaining", "S", dev_cls=SensorDeviceClass.DURATION, unit="s"),
        _SF("timeElapsed",   "timer_elapsed",   "S", dev_cls=SensorDeviceClass.DURATION, unit="s"),
    ],
    # ── battery ────────────────────────────────────────────────────────────
    BATTERY_SERVICE: [
        _SF("level", "battery", "S", dev_cls=SensorDeviceClass.BATTERY, unit=PERCENTAGE, label="Battery Level"),
    ],
    # ── cooking.state.v1 ───────────────────────────────────────────────────
    COOKING_STATE_SERVICE: [
        _SF("cookingStatus", "cook_status", "S"),
        _SF("runStatus",     "run_status",  "S"),
    ],
    # ── stopwatch ──────────────────────────────────────────────────────────
    STOPWATCH_SERVICE: [
        _SF("secondsElapsed", "stopwatch_elapsed", "S", dev_cls=SensorDeviceClass.DURATION, unit="s"),
    ],
    # ── volume.liquid.v1 ───────────────────────────────────────────────────
    VOLUME_LIQUID_SERVICE: [
        _SF("liters", "volume_liters", "S", dev_cls=SensorDeviceClass.WATER, unit=UnitOfVolume.LITERS),
    ],
    # ── scale.v1 ───────────────────────────────────────────────────────────
    SCALE_SERVICE: [
        _SF("weightCurrent", "scale_current", "S", dev_cls=SensorDeviceClass.WEIGHT, unit=UnitOfMass.GRAMS),
        _SF("weightTarget",  "scale_target",  "S", dev_cls=SensorDeviceClass.WEIGHT, unit=UnitOfMass.GRAMS),
    ],
    # ── power.usage ────────────────────────────────────────────────────────
    POWER_USAGE_SERVICE: [
        _SF("instantaneousPower",    "power_instant", "S", dev_cls=SensorDeviceClass.POWER, unit=UnitOfPower.WATT),
        _SF("wattSecondsSinceClear", "power_energy",  "S", unit="Ws"),
    ],
    # ── laundry.state.v1 ───────────────────────────────────────────────────
    LAUNDRY_STATE_SERVICE: [
        _SF("runStatus",           "laundry_run_status",  "L"),
        _SF("cycle",               "laundry_cycle",       "L"),
        _SF("subCycle",            "laundry_subcycle",    "L"),
        _SF("laundrySpin",         "laundry_spin",        "L"),
        _SF("laundryTemperature",  "laundry_temperature", "L"),
        _SF("laundryRinse",        "laundry_rinse",       "L"),
        _SF("laundrySoil",         "laundry_soil",        "L"),
        _SF("laundryDrynessLevel", "laundry_dryness",     "L"),
        _SF("stain",               "laundry_stain",       "L"),
    ],
    # ── delaywindow ────────────────────────────────────────────────────────
    DELAYWINDOW_SERVICE: [
        _SF("startTime", "delay_start", "S"),
        _SF("endTime",   "delay_end",   "S"),
    ],
    # ── brew.mode.v1 ───────────────────────────────────────────────────────
    BREW_MODE_SERVICE: [
        _SF("volume",          "brew_volume",      "S"),
        _SF("grindTime",       "brew_grind_time",  "S", dev_cls=SensorDeviceClass.DURATION, unit="s"),
        _SF("brewTemperature", "brew_temperature", "T", unit=UnitOfTemperature.CELSIUS),
    ],
    # ── coffeebrewer.v1 ────────────────────────────────────────────────────
    COFFEEBREWER_V1_SERVICE: [
        _SF("temperatureFahrenheit", "brew_current_temp", "T", unit=UnitOfTemperature.FAHRENHEIT, label="Brew Temperature"),
    ],
    # ── coffeebrewer.v2 ────────────────────────────────────────────────────
    COFFEEBREWER_V2_SERVICE: [
        _SF("temperatureFahrenheit", "brew_current_temp", "T", unit=UnitOfTemperature.FAHRENHEIT, label="Brew Temperature"),
    ],
    # ── dishwasher.state.v1 ────────────────────────────────────────────────
    DISHWASHER_STATE_V1_SERVICE: [
        _SF("runStatus",       "dw_run_status",  "L"),
        _SF("mode",            "dw_mode",        "L"),
        _SF("cycleIndication", "dw_cycle",       "L"),
        _SF("delayStart",      "dw_delay_start", "L"),
    ],
    # ── dishdrawer.state.legacy ────────────────────────────────────────────
    DISHDRAWER_STATE_LEGACY_SERVICE: [
        _SF("runStatus",                  "ddr_run_status", "L"),
        _SF("mode",                       "ddr_mode",       "L"),
        _SF("cycleIndication",            "ddr_cycle",      "L"),
        _SF("delayStart",                 "ddr_delay_start","L"),
        _SF("dishdrawerModeLegacyOption", "ddr_option",     "L"),
    ],
    # ── dishwasher.rinse.agent ─────────────────────────────────────────────
    DISHWASHER_RINSE_AGENT_SERVICE: [
        _SF("rinseAgentStatus", "rinse_agent_status", "L"),
    ],
    # ── dishwasher.state.legacy ────────────────────────────────────────────
    DISHWASHER_STATE_LEGACY_SERVICE: [
        _SF("runStatus",       "dws_lg_run_status", "L"),
        _SF("shortNameMode",   "dws_lg_mode",       "L"),
        _SF("cycleIndication", "dws_lg_cycle",      "L"),
        _SF("delayStart",      "dws_lg_delay",      "L"),
        _SF("heatedDry",       "dws_lg_heated_dry", "L"),
        _SF("washTemp",        "dws_lg_wash_temp",  "L"),
        _SF("washZone",        "dws_lg_wash_zone",  "L"),
    ],
    # ── descale.v1 ─────────────────────────────────────────────────────────
    DESCALE_V1_SERVICE: [
        _SF("runStatus",         "descale_status", "S"),
        _SF("volumeUntilNeeded", "descale_volume", "S", unit="mL"),
    ],
    # ── dryer.vent.health.mode ─────────────────────────────────────────────
    DRYER_VENT_HEALTH_MODE_SERVICE: [
        _SF("mode", "vent_health_mode", "L"),
    ],
    # ── laundry.bulktank ───────────────────────────────────────────────────
    LAUNDRY_BULKTANK_SERVICE: [
        _SF("tank1usagePercent", "bulktank1_pct", "S", unit=PERCENTAGE),
        _SF("tank2usagePercent", "bulktank2_pct", "S", unit=PERCENTAGE),
        _SF("tank1substance",    "bulktank1_sub", "L"),
        _SF("tank2substance",    "bulktank2_sub", "L"),
    ],
    # ── outdoorunit.info ───────────────────────────────────────────────────
    OUTDOORUNIT_INFO_SERVICE: [
        _SF("modelNumber",  "outdoor_model",  "S", cat=EntityCategory.DIAGNOSTIC),
        _SF("serialNumber", "outdoor_serial", "S", cat=EntityCategory.DIAGNOSTIC),
    ],
    # ── smartdispense ──────────────────────────────────────────────────────
    SMARTDISPENSE_SERVICE: [
        _SF("level",           "smartdisp_level",     "L"),
        _SF("substance",       "smartdisp_substance", "L"),
        _SF("cyclesRemaining", "smartdisp_cycles",    "L"),
        _SF("dosing",          "smartdisp_dosing",    "L"),
    ],
    # ── cooking.oven.probe.temperature ─────────────────────────────────────
    COOKING_OVEN_PROBE_TEMP_SERVICE: [
        _SF("probeUpperDisplayTemperature", "probe_upper_temp", "T", unit=UnitOfTemperature.FAHRENHEIT),
        _SF("probeLowerDisplayTemperature", "probe_lower_temp", "T", unit=UnitOfTemperature.FAHRENHEIT),
    ],
    # ── cooking.burner.status.v1 ───────────────────────────────────────────
    COOKING_BURNER_STATUS_SERVICE: [
        _SF("cooktopStatus", "burner_status",     "L"),
        _SF("energySource",  "burner_energy_src", "L"),
    ],
    # ── cooking.advantium ─────────────────────────────────────────────────
    COOKING_ADVANTIUM_SERVICE: [
        _SF("advantiumCookMode",           "adv_cook_mode",   "L"),
        _SF("cookAction",                  "adv_cook_action", "L"),
        _SF("preheatStatus",               "adv_preheat",     "L"),
        _SF("targetTemperatureFahrenheit", "adv_target_temp", "T", unit=UnitOfTemperature.FAHRENHEIT),
    ],
    # ── espressomaker.v1 ───────────────────────────────────────────────────
    ESPRESSOMAKER_SERVICE: [
        _SF("runStatus",            "espresso_status",    "L"),
        _SF("brewType",             "espresso_brew_type", "L"),
        _SF("brewTemperature",      "espresso_brew_temp", "T", unit=UnitOfTemperature.CELSIUS),
        _SF("volume",               "espresso_volume",    "L"),
        _SF("grindTime",            "espresso_grind",     "L"),
        _SF("lifetimeCoffeeGround", "espresso_lifetime",  "L"),
    ],
    # ── mixer.v1 ──────────────────────────────────────────────────────────
    MIXER_SERVICE: [
        _SF("runStatus", "mixer_status",    "L"),
        _SF("speed",     "mixer_speed",     "L"),
        _SF("direction", "mixer_direction", "L"),
    ],
    # ── pizzaoven.state ────────────────────────────────────────────────────
    PIZZAOVEN_STATE_SERVICE: [
        _SF("operatingState",        "pzo_op_state",       "L"),
        _SF("menuSelection",         "pzo_menu",           "L"),
        _SF("timerState",            "pzo_timer_state",    "L"),
        _SF("currentTimeRemaining",  "pzo_time_remaining", "L"),
        _SF("domeFrontTemperature",  "pzo_dome_front",     "T", unit=UnitOfTemperature.FAHRENHEIT),
        _SF("domeRearTemperature",   "pzo_dome_rear",      "T", unit=UnitOfTemperature.FAHRENHEIT),
        _SF("stoneFrontTemperature", "pzo_stone_front",    "T", unit=UnitOfTemperature.FAHRENHEIT),
        _SF("stoneRearTemperature",  "pzo_stone_rear",     "T", unit=UnitOfTemperature.FAHRENHEIT),
    ],
    # ── sourdoughstarter.v1 ────────────────────────────────────────────────
    SOURDOUGHSTARTER_SERVICE: [
        _SF("state",           "sourdough_state",   "L"),
        _SF("mode",            "sourdough_mode",    "L"),
        _SF("goalTimeHours",   "sourdough_goal_h",  "L"),
        _SF("goalTimeMinutes", "sourdough_goal_m",  "L"),
        _SF("flourRatio",      "sourdough_flour",   "L"),
        _SF("waterRatio",      "sourdough_water",   "L"),
        _SF("starterRatio",    "sourdough_starter", "L"),
    ],
    # ── cooktop.closedloop ─────────────────────────────────────────────────
    COOKTOP_CLOSEDLOOP_SERVICE: [
        _SF("primaryDeviceStatus",   "cl_primary_status",   "L"),
        _SF("primaryDeviceType",     "cl_primary_type",     "L"),
        _SF("primaryDeviceFamily",   "cl_primary_family",   "L"),
        _SF("primaryShortId",        "cl_primary_id",       "L"),
        _SF("secondaryDeviceStatus", "cl_secondary_status", "L"),
        _SF("secondaryDeviceFamily", "cl_secondary_family", "L"),
        _SF("secondaryShortId",      "cl_secondary_id",     "L"),
    ],
    # ── cooktop.sousvide ───────────────────────────────────────────────────
    COOKTOP_SOUSVIDE_SERVICE: [
        _SF("clcCurrentTemperature",          "sv_current_temp", "L"),
        _SF("clcTargetTemperature",           "sv_target_temp",  "L"),
        _SF("closedLoopCookingDeviceBattery", "sv_battery",      "L"),
        _SF("bluetoothConnectionStatus",      "sv_bt_conn",      "L"),
        _SF("bluetoothPairedStatus",          "sv_bt_paired",    "L"),
        _SF("elapsedClosedLoopCookingTime",   "sv_elapsed_time", "L"),
    ],
    # ── oven.flextimer ─────────────────────────────────────────────────────
    OVEN_FLEXTIMER_SERVICE: [
        _SF("cookTimeTotalDuration", "flextimer_duration",    "L"),
        _SF("addSubtractStatus",     "flextimer_addsubtract", "L"),
        _SF("expirationStatus",      "flextimer_expiry",      "L"),
    ],
    # ── laundry.pethair ────────────────────────────────────────────────────
    LAUNDRY_PETHAIR_SERVICE: [
        _SF("disabled", "pethair_disabled", "L"),
    ],
    # ── dryer.config.cycle.v1 ─────────────────────────────────────────────
    DRYER_CONFIG_CYCLE_V1_SERVICE: [
        _SF("optionHeatHighMinutes",          "dryercfg_heat_high_min", "L"),
        _SF("optionHeatMediumMinutes",        "dryercfg_heat_med_min",  "L"),
        _SF("optionHeatLowMinutes",           "dryercfg_heat_low_min",  "L"),
        _SF("optionHeatNoneMinutes",          "dryercfg_heat_none_min", "L"),
        _SF("optionHeatHighCelsiusConverted", "dryercfg_heat_high_c",   "L"),
        _SF("optionHeatLowCelsiusConverted",  "dryercfg_heat_low_c",    "L"),
        _SF("disabled",                       "dryercfg_disabled",      "L"),
    ],
    # ── dryer.mycycle ──────────────────────────────────────────────────────
    DRYER_MYCYCLE_SERVICE: [
        _SF("myCycles", "dryer_mycycles", "L"),
    ],
    # ── washer.config.cycle.v1 ────────────────────────────────────────────
    WASHER_CONFIG_CYCLE_V1_SERVICE: [
        _SF("cycleWashColors",    "washercfg_colors",    "L"),
        _SF("cycleWashWhites",    "washercfg_whites",    "L"),
        _SF("cycleWashTowels",    "washercfg_towels",    "L"),
        _SF("cycleWashDelicates", "washercfg_delicates", "L"),
        _SF("cycleWashDeepClean", "washercfg_deepclean", "L"),
        _SF("cycleWashSpeed",     "washercfg_speed",     "L"),
        _SF("cycleWashCold",      "washercfg_spin_cold", "L"),
        _SF("cycleWashWarm",      "washercfg_spin_warm", "L"),
        _SF("cycleWashHot",       "washercfg_spin_hot",  "L"),
        _SF("disabled",           "washercfg_disabled",  "L"),
    ],
    # ── washer.mycycle ────────────────────────────────────────────────────
    WASHER_MYCYCLE_SERVICE: [
        _SF("storedCycles", "washer_mycycles", "L"),
    ],
    # ── demandresponse.state.v1 ───────────────────────────────────────────
    DEMANDRESPONSE_STATE_V1_SERVICE: [
        _SF("systemStatus", "dr_system_status", "L"),
        _SF("energyState",  "dr_energy_state",  "L"),
        _SF("eventId",      "dr_event_id",      "L"),
    ],
    # ── oven.menutree ─────────────────────────────────────────────────────
    OVEN_MENUTREE_SERVICE: [
        _SF("sequence1",        "menutree_seq1",   "L"),
        _SF("sequence2",        "menutree_seq2",   "L"),
        _SF("uuidSelection1",   "menutree_uuid1",  "L"),
        _SF("uuidSelection2",   "menutree_uuid2",  "L"),
        _SF("shortnameCavity1", "menutree_short1", "L"),
        _SF("shortnameCavity2", "menutree_short2", "L"),
    ],
    # ── laundry.commercial.v1 ─────────────────────────────────────────────
    LAUNDRY_COMMERCIAL_V1_SERVICE: [
        _SF("machineStatus",     "commercial_machine_status", "L"),
        _SF("phaseCloud",        "commercial_phase_cloud",    "L"),
        _SF("phaseDevice",       "commercial_phase_device",   "L"),
        _SF("selectedCycle",     "commercial_selected_cycle", "L"),
        _SF("heatOption",        "commercial_heat_option",    "L"),
        _SF("soilOption",        "commercial_soil_option",    "L"),
        _SF("temperatureOption", "commercial_temp_option",    "L"),
    ],
    # ── laundry.downloadablecycle ─────────────────────────────────────────
    LAUNDRY_DOWNLOADABLECYCLE_SERVICE: [
        _SF("downloadableCycleSelected", "dlcycle_selected", "L"),
        _SF("featureVersion",            "dlcycle_version",  "L"),
    ],
    # ── demandresponse.event.v1 ───────────────────────────────────────────
    DEMANDRESPONSE_EVENT_V1_SERVICE: [
        _SF("eventId",           "dr_event_id",     "L"),
        _SF("curtailmentLevel",  "dr_curtailment",  "L"),
        _SF("temperatureOffset", "dr_temp_offset",  "L"),
        _SF("eventStatus",       "dr_event_status", "L"),
        _SF("userOption",        "dr_user_option",  "L"),
    ],
    # ── laundry.pricemenu.v1 ──────────────────────────────────────────────
    LAUNDRY_PRICEMENU_V1_SERVICE: [
        _SF("cycleWashCold",        "pm_wash_cold",       "L"),
        _SF("cycleWashWarm",        "pm_wash_warm",       "L"),
        _SF("cycleWashHot",         "pm_wash_hot",        "L"),
        _SF("cycleWashDelicates",   "pm_wash_delicates",  "L"),
        _SF("optionExtraRinse",     "pm_opt_extra_rinse", "L"),
        _SF("optionSoilLight",      "pm_opt_soil_light",  "L"),
        _SF("optionSoilMedium",     "pm_opt_soil_medium", "L"),
        _SF("optionSoilHeavy",      "pm_opt_soil_heavy",  "L"),
        _SF("optionHeatNone",       "pm_heat_none",       "L"),
        _SF("optionHeatLow",        "pm_heat_low",        "L"),
        _SF("optionHeatMedium",     "pm_heat_medium",     "L"),
        _SF("optionHeatHigh",       "pm_heat_high",       "L"),
        _SF("adjustmentHeatNone",   "pm_adj_heat_none",   "L"),
        _SF("adjustmentHeatLow",    "pm_adj_heat_low",    "L"),
        _SF("adjustmentHeatMedium", "pm_adj_heat_med",    "L"),
        _SF("adjustmentHeatHigh",   "pm_adj_heat_high",   "L"),
    ],
}


def _build_standard_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_id: str,
    service_id: str,
    dev_name: str,
    stype: str,
    existing_uids: set[str],
) -> list[SensorEntity]:
    """Create sensor entities for a standard (data-driven) serviceType."""
    result: list[SensorEntity] = []
    for f in _STANDARD_SENSOR_SPECS.get(stype, []):
        uid = make_unique_id(device_id, service_id, f.uid)
        if uid in existing_uids:
            continue
        label = f.label if f.label else _camel_to_words(f.key)
        if f.cls == "L":
            entity: SensorEntity = SmartHQLaundryStateSensor(
                hass, entry, device_id, service_id, dev_name, label, f.key, uid,
            )
        elif f.cls == "T":
            entity = SmartHQRawTempSensor(
                hass, entry, device_id, service_id, dev_name, label, f.key, f.unit, uid,
            )
        else:  # "S"
            kwargs: dict = {}
            if f.cat is not None:
                kwargs["entity_category"] = f.cat
            if not f.enabled:
                kwargs["enabled_default"] = False
            entity = SmartHQServiceSensor(
                hass, entry, device_id, service_id, dev_name,
                label, f.key, f.dev_cls, f.unit, uid, **kwargs,
            )
        result.append(entity)
        existing_uids.add(uid)
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

                # ── Allowlist check ──
                if get_service_mapping(stype) is None:
                    _LOGGER.debug("[SENSOR] Skipping unmapped serviceType=%s", stype)
                    continue
                if not is_platform_mapped(stype, "sensor"):
                    continue

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

                # ── standard (data-driven) sensors ─────────────────────────
                elif stype in _STANDARD_SENSOR_SPECS:
                    entities.extend(_build_standard_sensors(
                        hass, entry, device_id, service_id, dev_name, stype, existing_uids,
                    ))


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
