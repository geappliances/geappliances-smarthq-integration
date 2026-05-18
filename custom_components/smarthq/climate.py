"""Climate platform for SmartHQ integration — thermostat.v1.

Provides full climate entity support for AC/thermostat devices using the
SmartHQ thermostat.v1 service. Supports mode control, temperature setpoints,
fan speed, eco mode, and on/off control.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_OFF,
    FAN_ON,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_NAME
from .dispatcher import SIGNAL_DEVICE_UPDATED
from .service_registry import (
    THERMOSTAT_SERVICE,
    get_device_services,
    make_unique_id,
    get_service_mapping,
    is_platform_mapped,
)

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SmartHQ → HA HVAC mode mapping
# ---------------------------------------------------------------------------
_THERMOSTAT_MODE_MAP: Dict[str, HVACMode] = {
    "cloud.smarthq.type.thermostatmode.cool":              HVACMode.COOL,
    "cloud.smarthq.type.thermostatmode.cool.energysaver":  HVACMode.COOL,
    "cloud.smarthq.type.thermostatmode.cool.quiet":        HVACMode.COOL,
    "cloud.smarthq.type.thermostatmode.cool.turbo":        HVACMode.COOL,
    "cloud.smarthq.type.thermostatmode.heat":              HVACMode.HEAT,
    "cloud.smarthq.type.thermostatmode.auto":              HVACMode.AUTO,
    "cloud.smarthq.type.thermostatmode.auto.twotemperature": HVACMode.AUTO,
    "cloud.smarthq.type.thermostatmode.dry":               HVACMode.DRY,
    "cloud.smarthq.type.thermostatmode.fanonly":           HVACMode.FAN_ONLY,
    "cloud.smarthq.type.thermostatmode.off":               HVACMode.OFF,
    "cloud.smarthq.type.thermostatmode.on":                HVACMode.AUTO,
    "cloud.smarthq.type.thermostatmode.continuous":        HVACMode.AUTO,
}

# Reverse map: HA HVACMode → SmartHQ thermostatmode token
_HA_MODE_TO_SMARTHQ: Dict[HVACMode, str] = {
    HVACMode.COOL:     "cloud.smarthq.type.thermostatmode.cool",
    HVACMode.HEAT:     "cloud.smarthq.type.thermostatmode.heat",
    HVACMode.AUTO:     "cloud.smarthq.type.thermostatmode.auto",
    HVACMode.DRY:      "cloud.smarthq.type.thermostatmode.dry",
    HVACMode.FAN_ONLY: "cloud.smarthq.type.thermostatmode.fanonly",
    HVACMode.OFF:      "cloud.smarthq.type.thermostatmode.off",
}

# SmartHQ fan speed → HA fan mode
_FANSPEED_MAP: Dict[str, str] = {
    "cloud.smarthq.type.fanspeed.auto":      FAN_AUTO,
    "cloud.smarthq.type.fanspeed.high":      FAN_HIGH,
    "cloud.smarthq.type.fanspeed.medium":    FAN_MEDIUM,
    "cloud.smarthq.type.fanspeed.low":       FAN_LOW,
    "cloud.smarthq.type.fanspeed.off":       FAN_OFF,
    "cloud.smarthq.type.fanspeed.on":        FAN_ON,
    "cloud.smarthq.type.fanspeed.smart.dry": "smart_dry",
    "cloud.smarthq.type.fanspeed.circulate": "circulate",
}

# Reverse fan speed map
_HA_FAN_TO_SMARTHQ: Dict[str, str] = {v: k for k, v in _FANSPEED_MAP.items()}


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------

def _bucket(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return _bucket(hass, entry).get("store") or {}


def _device_info_for(hass, entry, device_id):
    dev_data = (_store(hass, entry).get(device_id) or {})
    info = dev_data.get("info") or {}
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


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartHQ climate entities from coordinator service definitions."""
    bucket = _bucket(hass, entry)
    coordinator = bucket.get("coordinator")
    client = bucket.get("client")

    if not coordinator or not coordinator.data:
        return

    entities: List[ClimateEntity] = []
    existing_uids: set = set()

    for device_id, dev_data in coordinator.data.items():
        dev_name = (dev_data.get("info") or {}).get("nickname") or DEFAULT_NAME
        item = dev_data.get("item") or {}
        for svc in (item.get("services") or []):
            stype = svc.get("serviceType") or ""
            service_id = svc.get("serviceId") or ""
            if not service_id:
                continue

            # ── Allowlist check ──
            if get_service_mapping(stype) is None:
                _LOGGER.debug("[CLIMATE] Skipping unmapped serviceType=%s", stype)
                continue
            if not is_platform_mapped(stype, "climate"):
                continue

            if stype == THERMOSTAT_SERVICE:
                uid = make_unique_id(device_id, service_id, "thermostat")
                if uid not in existing_uids:
                    existing_uids.add(uid)
                    entities.append(SmartHQThermostatClimate(
                        hass=hass,
                        entry=entry,
                        client=client,
                        device_id=device_id,
                        service_id=service_id,
                        dev_name=dev_name,
                        svc_config=svc.get("config") or {},
                        unique_id=uid,
                    ))

    _LOGGER.info("[CLIMATE] Registering %d climate entities", len(entities))
    if entities:
        async_add_entities(entities, update_before_add=False)


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------

class SmartHQThermostatClimate(ClimateEntity):
    """Climate entity backed by thermostat.v1 service."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: Any,
        device_id: str,
        service_id: str,
        dev_name: str,
        svc_config: dict,
        unique_id: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._client = client
        self._device_id = device_id
        self._service_id = service_id
        self._svc_config = svc_config
        self._attr_name = f"{dev_name} Thermostat"
        self._attr_unique_id = unique_id

        # Build supported HVAC modes from config
        supported_modes_tokens = svc_config.get("supportedModes") or []
        hvac_modes = {HVACMode.OFF}
        for token in supported_modes_tokens:
            ha_mode = _THERMOSTAT_MODE_MAP.get(token)
            if ha_mode:
                hvac_modes.add(ha_mode)
        self._attr_hvac_modes = list(hvac_modes) if hvac_modes else [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT, HVACMode.AUTO, HVACMode.FAN_ONLY, HVACMode.DRY]

        # Build supported fan modes
        fan_speed_tokens = svc_config.get("supportedFanSpeeds") or []
        fan_modes = [_FANSPEED_MAP[t] for t in fan_speed_tokens if t in _FANSPEED_MAP]
        self._attr_fan_modes = fan_modes or None

        # Temperature range
        self._attr_min_temp = svc_config.get("coolFahrenheitMinimum") or svc_config.get("heatFahrenheitMinimum") or 60.0
        self._attr_max_temp = svc_config.get("coolFahrenheitMaximum") or svc_config.get("heatFahrenheitMaximum") or 86.0
        self._attr_target_temperature_step = 1.0

        # Build supported features
        features = ClimateEntityFeature.TARGET_TEMPERATURE
        if fan_modes:
            features |= ClimateEntityFeature.FAN_MODE
        if svc_config.get("supportsSwing"):
            features |= ClimateEntityFeature.SWING_MODE
        self._attr_supported_features = features

    def _get_state(self) -> dict:
        store = _store(self.hass, self._entry)
        snap = (store.get(self._device_id) or {}).get("snapshot") or {}
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def hvac_mode(self) -> HVACMode | None:
        st = self._get_state()
        on = st.get("on", True)
        if on is False:
            return HVACMode.OFF
        mode_token = st.get("mode") or ""
        return _THERMOSTAT_MODE_MAP.get(mode_token, HVACMode.OFF)

    @property
    def current_temperature(self) -> float | None:
        # thermostat.v1 doesn't expose a measured temperature field in state
        return None

    @property
    def target_temperature(self) -> float | None:
        st = self._get_state()
        mode = self.hvac_mode
        if mode == HVACMode.COOL:
            return st.get("coolFahrenheit") or st.get("coolFahrenheitConverted")
        if mode == HVACMode.HEAT:
            return st.get("heatFahrenheit") or st.get("heatFahrenheitConverted")
        # fallback: try cool then heat
        return st.get("coolFahrenheit") or st.get("heatFahrenheit")

    @property
    def fan_mode(self) -> str | None:
        st = self._get_state()
        token = st.get("fanSpeed") or ""
        return _FANSPEED_MAP.get(token)

    @property
    def swing_mode(self) -> str | None:
        st = self._get_state()
        return "on" if st.get("swing") else "off"

    @property
    def available(self) -> bool:
        st = self._get_state()
        return "on" in st or "mode" in st

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        client = self._client or _bucket(self.hass, self._entry).get("client")
        if not client:
            return
        if hvac_mode == HVACMode.OFF:
            await client.async_set_thermostat(self._device_id, self._service_id, on=False)
        else:
            smarthq_mode = _HA_MODE_TO_SMARTHQ.get(hvac_mode)
            if smarthq_mode:
                await client.async_set_thermostat(
                    self._device_id, self._service_id,
                    on=True, mode=smarthq_mode,
                )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        client = self._client or _bucket(self.hass, self._entry).get("client")
        if not client:
            return
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        mode = self.hvac_mode
        params: dict = {}
        if mode == HVACMode.HEAT:
            params["heatFahrenheit"] = temp
        else:
            params["coolFahrenheit"] = temp
        await client.async_set_thermostat(self._device_id, self._service_id, **params)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        client = self._client or _bucket(self.hass, self._entry).get("client")
        if not client:
            return
        token = _HA_FAN_TO_SMARTHQ.get(fan_mode)
        if token:
            await client.async_set_thermostat(self._device_id, self._service_id, fanSpeed=token)

    async def async_turn_on(self) -> None:
        client = self._client or _bucket(self.hass, self._entry).get("client")
        if client:
            await client.async_set_thermostat(self._device_id, self._service_id, on=True)

    async def async_turn_off(self) -> None:
        client = self._client or _bucket(self.hass, self._entry).get("client")
        if client:
            await client.async_set_thermostat(self._device_id, self._service_id, on=False)

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
        self.async_write_ha_state()
