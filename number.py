"""Number platform for SmartHQ integration.

Entity registration is driven entirely by coordinator.data[device_id]["item"]["services"].
Live state is read from the WebSocket snapshot store.

Service → entity mapping:
  temperature + CMD_TEMPERATURE_SET → SmartHQTemperatureNumber
  integer     + CMD_INTEGER_SET     → SmartHQIntegerNumber
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_NAME
from .dispatcher import SIGNAL_DEVICE_UPDATED, SIGNAL_COOK_MODE_CHANGED
from .sensor import _snapshot_for, _dev_payload, _device_info_for, _integer_units_to_ha
from .service_registry import (
    TEMPERATURE_SERVICE,
    INTEGER_SERVICE,
    DISHDRAWER_MODE_LEGACY_SERVICE,
    COOKING_MODE_SERVICE,
    is_cooking_mode_domain,
    CMD_TEMPERATURE_SET,
    CMD_INTEGER_SET,
    CMD_DISHDRAWER_MODE_LEGACY_SET,
    make_unique_id,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------

def _bucket(hass, entry):
    return hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SmartHQ number entities from coordinator service definitions."""
    bucket = _bucket(hass, entry)
    coordinator = bucket.get("coordinator")

    if not coordinator or not coordinator.data:
        _LOGGER.warning("[NUMBER] Coordinator data not available yet")
        return

    entities: List[NumberEntity] = []

    for device_id, device_item in coordinator.data.items():
        item = device_item.get("item") or {}
        services_list = item.get("services") or []
        if not isinstance(services_list, list):
            continue

        info = item.get("info") or {}
        dev_name = info.get("nickname") or info.get("name") or DEFAULT_NAME

        # Detect if this device has any startable cooking mode services
        # (Smoker: cooking.food.*, Toaster Oven: cooking.bake/airfry/…, etc.)
        has_cooking_mode = any(
            isinstance(s, dict)
            and s.get("serviceType") == COOKING_MODE_SERVICE
            and is_cooking_mode_domain(s.get("domainType") or "")
            for s in services_list
        )
        if has_cooking_mode:
            entities.extend(_make_cooking_numbers(hass, entry, device_id, dev_name, services_list))

        for svc in services_list:
            if not isinstance(svc, dict):
                continue

            stype = svc.get("serviceType") or ""
            dom = svc.get("domainType") or ""
            service_id = svc.get("id") or svc.get("serviceId") or ""
            cmds = svc.get("supportedCommands") or []
            cfg = svc.get("config") or {}

            # ── temperature number (write) ──────────────────────────────────
            # Skip generic temperature entities on Smoker devices — the dedicated
            # SmartHQSmokerTempNumber covers that role, and the auto/temperature
            # domain services are not meaningful in the Smoker UI.
            if stype == TEMPERATURE_SERVICE and CMD_TEMPERATURE_SET in cmds:
                if has_cooking_mode:
                    continue
                min_f = float(cfg.get("fahrenheitMin", 32))
                max_f = float(cfg.get("fahrenheitMax", 500))
                label = cfg.get("label") or dom.split(".")[-1].replace("_", " ").title()
                entities.append(SmartHQTemperatureNumber(
                    hass=hass, entry=entry,
                    device_id=device_id, service_id=service_id,
                    dev_name=dev_name, label=label,
                    min_f=min_f, max_f=max_f,
                    unique_id=make_unique_id(device_id, service_id, "temp_number"),
                ))

            # ── dishdrawer.mode.legacy delay start number ────────────────
            elif stype == DISHDRAWER_MODE_LEGACY_SERVICE and CMD_DISHDRAWER_MODE_LEGACY_SET in cmds:
                delay_min = float(cfg.get("delayStartMinimum", 0))
                delay_max = float(cfg.get("delayStartMaximum", 0))
                # Only create entity when device actually supports delay start
                if delay_max > delay_min:
                    dom = svc.get("domainType") or ""
                    cycle_label = dom.split(".")[-1].replace("_", " ").title() if dom else "Dishdrawer"
                    entities.append(SmartHQDishdrawerDelayStartNumber(
                        hass=hass, entry=entry,
                        device_id=device_id, service_id=service_id,
                        dev_name=dev_name,
                        label=f"Dishdrawer {cycle_label} Delay Start",
                        min_val=delay_min, max_val=delay_max,
                        unique_id=make_unique_id(device_id, service_id, "dishdrawer_delay_start"),
                    ))

            # ── integer number (write) ──────────────────────────────────────
            elif stype == INTEGER_SERVICE and CMD_INTEGER_SET in cmds:
                int_units = cfg.get("integerUnits") or ""
                min_val = float(cfg.get("minimum", 0))
                max_val = float(cfg.get("maximum", 100))
                label = cfg.get("label") or dom.split(".")[-1].replace("_", " ").title()
                ha_unit, _ = _integer_units_to_ha(int_units)
                entities.append(SmartHQIntegerNumber(
                    hass=hass, entry=entry,
                    device_id=device_id, service_id=service_id,
                    dev_name=dev_name, label=label,
                    min_val=min_val, max_val=max_val, unit=ha_unit,
                    unique_id=make_unique_id(device_id, service_id, "int_number"),
                ))

    _LOGGER.info("[NUMBER] Registering %d number entities", len(entities))
    if entities:
        async_add_entities(entities, update_before_add=False)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------

class _SmartHQNumberBase(NumberEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass, entry, device_id, service_id, dev_name, label, unique_id):
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._attr_name = f"{dev_name} {label}"
        self._attr_unique_id = unique_id

    def _get_state(self) -> dict:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def available(self) -> bool:
        st = self._get_state()
        return bool(st) and not st.get("disabled", False)

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

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


class SmartHQTemperatureNumber(_SmartHQNumberBase):
    """Writable temperature service number entity."""

    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_device_class = "temperature"
    _attr_native_step = 1.0

    def __init__(self, hass, entry, device_id, service_id,
                 dev_name, label, min_f, max_f, unique_id):
        super().__init__(hass, entry, device_id, service_id, dev_name, label, unique_id)
        self._attr_native_min_value = min_f
        self._attr_native_max_value = max_f

    @property
    def native_value(self) -> float | None:
        return self._get_state().get("fahrenheit")

    async def async_set_native_value(self, value: float) -> None:
        client = _bucket(self.hass, self._entry).get("client")
        if client:
            snap = _snapshot_for(self.hass, self._entry, self._device_id)
            svc_dict = (snap.get("services") or {}).get(self._service_id) or {}
            await client.async_send_service_command(
                device_id=self._device_id,
                service=svc_dict,
                command_type=CMD_TEMPERATURE_SET,
                command_params={"fahrenheit": value},
            )
        self.async_write_ha_state()


class SmartHQIntegerNumber(_SmartHQNumberBase):
    """Writable integer service number entity."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1.0

    def __init__(self, hass, entry, device_id, service_id,
                 dev_name, label, min_val, max_val, unit, unique_id):
        super().__init__(hass, entry, device_id, service_id, dev_name, label, unique_id)
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> float | None:
        val = self._get_state().get("value")
        return float(val) if val is not None else None

    async def async_set_native_value(self, value: float) -> None:
        client = _bucket(self.hass, self._entry).get("client")
        if client:
            snap = _snapshot_for(self.hass, self._entry, self._device_id)
            svc_dict = (snap.get("services") or {}).get(self._service_id) or {}
            await client.async_send_service_command(
                device_id=self._device_id,
                service=svc_dict,
                command_type=CMD_INTEGER_SET,
                command_params={"value": value},
            )
        self.async_write_ha_state()


class SmartHQDishdrawerDelayStartNumber(_SmartHQNumberBase):
    """Number entity for dishdrawer.mode.legacy delay start (minutes).

    Stores the delay value in the HA bucket. When the cycle command is sent
    by SmartHQDishdrawerModeLegacyCycleSelect the delayStartValue is included.
    """

    _attr_mode = NumberMode.BOX
    _attr_native_step = 1.0
    _attr_icon = "mdi:timer-outline"

    def __init__(self, hass, entry, device_id, service_id,
                 dev_name, label, min_val, max_val, unique_id):
        super().__init__(hass, entry, device_id, service_id, dev_name, label, unique_id)
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_unit_of_measurement = "min"

    def _pending(self) -> dict:
        bucket = _bucket(self.hass, self._entry)
        return bucket.setdefault("dishdrawer_pending", {}).setdefault(self._device_id, {
            "delay_start": self._attr_native_min_value
        })

    @property
    def native_value(self) -> float:
        return float(self._pending().get("delay_start", self._attr_native_min_value))

    async def async_set_native_value(self, value: float) -> None:
        self._pending()["delay_start"] = value
        _LOGGER.info("[DISHDRAWER_DELAY] Delay start set to %s min", value)
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Cooking Number entities (Smoker + Toaster Oven + Oven, etc.)
# ---------------------------------------------------------------------------

def _make_cooking_numbers(hass, entry, device_id: str, dev_name: str, services_list: list) -> list:
    """Create cooking-control number entities based on what the device supports.

    Common entities (all devices with cooking.mode.v1):
      • Cavity Temperature  (when any mode has cavityTemperatureSupported)
      • Cook Time           (when any mode has cookTimeSupported)

    Smoker-only extras:
      • Probe Target Temperature (when any mode has probeTemperatureSupported)
      • Smoke Level              (when any mode has numericOptionSupported with smoke units)
    """
    from .service_registry import COOKING_PARAM_SUPPORTED, COOKING_MODE_SERVICE, is_cooking_mode_domain

    # Scan all cooking mode services to determine which parameters are supported
    has_cavity_temp = False
    has_cook_time = False
    has_probe_temp = False
    has_smoke_level = False

    for svc in services_list:
        if not isinstance(svc, dict):
            continue
        if svc.get("serviceType") != COOKING_MODE_SERVICE:
            continue
        if not is_cooking_mode_domain(svc.get("domainType") or ""):
            continue
        cfg = svc.get("config") or {}
        if cfg.get("cavityTemperatureSupported") in COOKING_PARAM_SUPPORTED:
            has_cavity_temp = True
        if cfg.get("cookTimeSupported") in COOKING_PARAM_SUPPORTED:
            has_cook_time = True
        if cfg.get("probeTemperatureSupported") in COOKING_PARAM_SUPPORTED:
            has_probe_temp = True
        numeric_units = cfg.get("numericOptionUnits") or ""
        if (cfg.get("numericOptionSupported") in COOKING_PARAM_SUPPORTED
                and "smoke" in numeric_units.lower()):
            has_smoke_level = True

    entities = []

    if has_cavity_temp:
        entities.append(SmartHQSmokerTempNumber(
            hass=hass, entry=entry, device_id=device_id, dev_name=dev_name,
            unique_id=make_unique_id(device_id, device_id, "smoker_temp"),
        ))
    if has_probe_temp:
        entities.append(SmartHQProbeTargetNumber(
            hass=hass, entry=entry, device_id=device_id, dev_name=dev_name,
            unique_id=make_unique_id(device_id, device_id, "probe_target"),
        ))
    if has_cook_time:
        entities.append(SmartHQCookTimeNumber(
            hass=hass, entry=entry, device_id=device_id, dev_name=dev_name,
            unique_id=make_unique_id(device_id, device_id, "cook_time"),
            has_probe=has_probe_temp,
        ))
    if has_smoke_level:
        entities.append(SmartHQSmokeLevelNumber(
            hass=hass, entry=entry, device_id=device_id, dev_name=dev_name,
            unique_id=make_unique_id(device_id, device_id, "smoke_level"),
        ))

    _LOGGER.info(
        "[COOKING_NUMBERS] device=%s  cavity=%s cook_time=%s probe=%s smoke=%s → %d entities",
        device_id[:8], has_cavity_temp, has_cook_time, has_probe_temp, has_smoke_level, len(entities),
    )

    # If config scanning found no supported parameters, return nothing.
    # This prevents Smoker-style entities appearing on non-Smoker cooking devices.
    return entities


class _SmartHQSmokerBase(NumberEntity):
    """Base class for Smoker-specific number controls.

    Values are stored in ``pending_cook_params[device_id]`` and sent to the
    device as a batch when the user presses the *Send To Smoker* button.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(self, hass, entry, device_id: str, dev_name: str, unique_id: str) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._attr_unique_id = unique_id

    def _pending(self) -> dict:
        bucket = _bucket(self.hass, self._entry)
        return bucket.setdefault("pending_cook_params", {}).setdefault(
            self._device_id, {"is_probe_based": True}
        )

    def _is_probe_based(self) -> bool:
        return self._pending().get("is_probe_based", True)

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
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_COOK_MODE_CHANGED.format(device_id=self._device_id),
                self._signal_update,
            )
        )

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()

    def _device_is_f(self) -> bool:
        """Return True if the device's temperatureunits service is set to Fahrenheit.

        Falls back to the HA system unit when the service is not present.
        """
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        for st in (snap.get("services") or {}).values():
            if isinstance(st, dict):
                dom = str(st.get("domainType") or "")
                if "temperatureunits" in dom.lower():
                    mode = str(st.get("mode") or "")
                    return "fahrenheit" in mode.lower()
        # Fallback: use HA system unit
        return self.hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT


class SmartHQSmokerTempNumber(_SmartHQSmokerBase):
    """Smoker cavity temperature — unit follows HA system setting (°C or °F)."""

    _attr_native_step = 1.0
    _attr_icon = "mdi:thermometer"

    # Internal storage is always °F
    _MIN_F = 100.0
    _MAX_F = 325.0

    def __init__(self, hass, entry, device_id, dev_name, unique_id):
        super().__init__(hass, entry, device_id, dev_name, unique_id)
        self._attr_name = f"{dev_name} Smoker Temp"

    def _f_to_display(self, f: float) -> float:
        if self._device_is_f():
            return round(f, 1)
        return round((f - 32) * 5 / 9, 1)

    def _display_to_f(self, v: float) -> float:
        if self._device_is_f():
            return v
        return v * 9 / 5 + 32

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTemperature.FAHRENHEIT if self._device_is_f() else UnitOfTemperature.CELSIUS

    @property
    def native_min_value(self) -> float:
        # Use config from the currently pending mode's service, or class default
        svc = self._svc_for_pending_mode()
        cfg = (svc.get("config") or {}) if svc else {}
        min_f = cfg.get("cavityTemperatureFahrenheitMinimum") or self._MIN_F
        return self._f_to_display(float(min_f))

    @property
    def native_max_value(self) -> float:
        svc = self._svc_for_pending_mode()
        cfg = (svc.get("config") or {}) if svc else {}
        max_f = cfg.get("cavityTemperatureFahrenheitMaximum") or self._MAX_F
        return self._f_to_display(float(max_f))

    def _svc_for_pending_mode(self) -> dict | None:
        """Return coordinator svc dict matching the pending cook mode domain, if any."""
        bucket = _bucket(self.hass, self._entry)
        token = (bucket.get("pending_cook_modes") or {}).get(self._device_id, {}).get("mode_token")
        if not token:
            return None
        coord = bucket.get("coordinator")
        if not coord or not coord.data:
            return None
        item = (coord.data.get(self._device_id) or {}).get("item") or {}
        for svc in item.get("services") or []:
            if isinstance(svc, dict) and svc.get("domainType") == token:
                return svc
        return None

    @property
    def native_value(self) -> Optional[float]:
        p = self._pending()
        if "smoker_temp_f" in p:
            return self._f_to_display(float(p["smoker_temp_f"]))
        # Fallback: default from coordinator state for the current pending mode
        svc = self._svc_for_pending_mode()
        if svc:
            state = svc.get("state") or {}
            temp_f = state.get("cavityTemperatureFahrenheitDefault") or state.get("cavityTemperatureFahrenheit")
            if temp_f is not None:
                return self._f_to_display(float(temp_f))
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        for st in (snap.get("services") or {}).values():
            if isinstance(st, dict) and "cavityFahrenheit" in st:
                return self._f_to_display(float(st["cavityFahrenheit"]))
        return None

    @property
    def available(self) -> bool:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        return bool(snap)

    async def async_set_native_value(self, value: float) -> None:
        f_val = int(self._display_to_f(value))
        self._pending()["smoker_temp_f"] = f_val
        _LOGGER.info("[SMOKER_TEMP] Set to %s°F (display: %s)", f_val, value)
        self.async_write_ha_state()


class SmartHQProbeTargetNumber(_SmartHQSmokerBase):
    """Probe target temperature — unit follows the device's temperatureunits setting.
    Only available when Cook Target Method = Probe Temp.
    """

    _attr_native_step = 1.0
    _attr_icon = "mdi:thermometer-probe"

    _MIN_F = 100.0
    _MAX_F = 210.0

    def __init__(self, hass, entry, device_id, dev_name, unique_id):
        super().__init__(hass, entry, device_id, dev_name, unique_id)
        self._attr_name = f"{dev_name} Probe Target"

    def _f_to_display(self, f: float) -> float:
        if self._device_is_f():
            return round(f, 1)
        return round((f - 32) * 5 / 9, 1)

    def _display_to_f(self, v: float) -> float:
        if self._device_is_f():
            return v
        return v * 9 / 5 + 32

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTemperature.FAHRENHEIT if self._device_is_f() else UnitOfTemperature.CELSIUS

    @property
    def native_min_value(self) -> float:
        return self._f_to_display(self._MIN_F)

    @property
    def native_max_value(self) -> float:
        return self._f_to_display(self._MAX_F)

    @property
    def native_value(self) -> Optional[float]:
        p = self._pending()
        if "probe_target_f" in p:
            return self._f_to_display(float(p["probe_target_f"]))
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        for st in (snap.get("services") or {}).values():
            if isinstance(st, dict) and "probeFahrenheit" in st:
                return self._f_to_display(float(st["probeFahrenheit"]))
        return None

    @property
    def available(self) -> bool:
        """Only available when Cook Target Method = Probe Temp."""
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        return bool(snap) and self._is_probe_based()

    async def async_set_native_value(self, value: float) -> None:
        f_val = int(self._display_to_f(value))
        self._pending()["probe_target_f"] = f_val
        _LOGGER.info("[PROBE_TARGET] Set to %s°F (display: %s)", f_val, value)
        self.async_write_ha_state()


class SmartHQCookTimeNumber(_SmartHQSmokerBase):
    """Cook time (minutes) — active only when Cook Target Method = Time Based."""

    _attr_native_min_value = 1.0
    _attr_native_max_value = 720.0   # 12 hours
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "min"
    _attr_icon = "mdi:timer-outline"

    def __init__(self, hass, entry, device_id, dev_name, unique_id, has_probe: bool = False):
        super().__init__(hass, entry, device_id, dev_name, unique_id)
        self._attr_name = f"{dev_name} Cook Time"
        self._has_probe = has_probe

    async def async_added_to_hass(self) -> None:
        # For devices without a probe (Toaster Oven, Oven), time-based cooking
        # is always the method — set default so entity is available immediately
        # without needing a CookTargetMethod select.
        if not self._has_probe:
            bucket = _bucket(self.hass, self._entry)
            bucket.setdefault("pending_cook_params", {}).setdefault(
                self._device_id, {}
            ).setdefault("is_probe_based", False)
        await super().async_added_to_hass()

    def _svc_for_pending_mode(self) -> dict | None:
        """Return coordinator svc dict matching the pending cook mode domain."""
        bucket = _bucket(self.hass, self._entry)
        token = (bucket.get("pending_cook_modes") or {}).get(self._device_id, {}).get("mode_token")
        if not token:
            return None
        coord = bucket.get("coordinator")
        if not coord or not coord.data:
            return None
        item = (coord.data.get(self._device_id) or {}).get("item") or {}
        for svc in item.get("services") or []:
            if isinstance(svc, dict) and svc.get("domainType") == token:
                return svc
        return None

    @property
    def native_min_value(self) -> float:
        svc = self._svc_for_pending_mode()
        cfg = (svc.get("config") or {}) if svc else {}
        min_s = cfg.get("cookTimeMinimum") or 60
        return max(1.0, int(min_s) / 60)

    @property
    def native_max_value(self) -> float:
        svc = self._svc_for_pending_mode()
        cfg = (svc.get("config") or {}) if svc else {}
        max_s = cfg.get("cookTimeMaximum") or 43200
        return int(max_s) / 60

    @property
    def native_value(self) -> Optional[float]:
        p = self._pending()
        if "cook_time_min" in p:
            return float(p["cook_time_min"])
        # Fallback: default from coordinator state for the current pending mode
        svc = self._svc_for_pending_mode()
        if svc:
            state = svc.get("state") or {}
            time_s = state.get("cookTimeInitialDefault") or state.get("cookTimeInitial")
            if time_s:
                return max(1.0, int(time_s) / 60)
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        for st in (snap.get("services") or {}).values():
            if isinstance(st, dict) and "cookTimeSeconds" in st:
                secs = st["cookTimeSeconds"]
                if secs:
                    return round(float(secs) / 60, 1)
        return None

    @property
    def available(self) -> bool:
        """Only available when Cook Target Method = Time Based."""
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        return bool(snap) and not self._is_probe_based()

    async def async_set_native_value(self, value: float) -> None:
        self._pending()["cook_time_min"] = int(value)
        _LOGGER.info("[COOK_TIME] Set to %s min", int(value))
        self.async_write_ha_state()


class SmartHQSmokeLevelNumber(_SmartHQSmokerBase):
    """Smoke level (0–5) — always active when a cook mode is selected."""

    _attr_native_min_value = 0.0
    _attr_native_max_value = 5.0
    _attr_native_step = 1.0
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:smoke"

    def __init__(self, hass, entry, device_id, dev_name, unique_id):
        super().__init__(hass, entry, device_id, dev_name, unique_id)
        self._attr_name = f"{dev_name} Smoke Level"

    @property
    def native_value(self) -> Optional[float]:
        p = self._pending()
        if "smoke_level" in p:
            return float(p["smoke_level"])
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        for st in (snap.get("services") or {}).values():
            if isinstance(st, dict) and "numericOptionValue" in st:
                return float(st["numericOptionValue"])
        return 3.0  # default mid-level

    @property
    def available(self) -> bool:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        return bool(snap)

    async def async_set_native_value(self, value: float) -> None:
        self._pending()["smoke_level"] = int(value)
        _LOGGER.info("[SMOKE_LEVEL] Set to %s", int(value))
        self.async_write_ha_state()
