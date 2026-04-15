"""Water heater platform for SmartHQ integration — waterheater.v1.

Provides WaterHeaterEntity support for SmartHQ water heater devices.
Supports mode (operation mode) selection and temperature setpoint.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_NAME
from .dispatcher import SIGNAL_DEVICE_UPDATED
from .service_registry import (
    WATERHEATER_SERVICE,
    get_device_services,
    make_unique_id,
)

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SmartHQ WATERHEATERMODE → HA operation mode label
# ---------------------------------------------------------------------------
_MODE_MAP: Dict[str, str] = {
    "cloud.smarthq.type.waterheatermode.electric":    "electric",
    "cloud.smarthq.type.waterheatermode.hybrid":      "hybrid",
    "cloud.smarthq.type.waterheatermode.heatpump":    "heat_pump",
    "cloud.smarthq.type.waterheatermode.highdemand":  "high_demand",
    "cloud.smarthq.type.waterheatermode.eheat":       "e_heat",
    "cloud.smarthq.type.waterheatermode.vacation":    "vacation",
    "cloud.smarthq.type.waterheatermode.unknown":     "unknown",
}
_HA_MODE_TO_SMARTHQ: Dict[str, str] = {v: k for k, v in _MODE_MAP.items()}


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
    """Set up SmartHQ water heater entities from coordinator service definitions."""
    bucket = _bucket(hass, entry)
    coordinator = bucket.get("coordinator")
    client = bucket.get("client")

    if not coordinator or not coordinator.data:
        return

    entities: List[WaterHeaterEntity] = []
    existing_uids: set = set()

    for device_id, dev_data in coordinator.data.items():
        dev_name = (dev_data.get("info") or {}).get("nickname") or DEFAULT_NAME
        item = dev_data.get("item") or {}
        for svc in (item.get("services") or []):
            stype = svc.get("serviceType") or ""
            service_id = svc.get("serviceId") or ""
            if not service_id:
                continue

            if stype == WATERHEATER_SERVICE:
                uid = make_unique_id(device_id, service_id, "water_heater")
                if uid not in existing_uids:
                    existing_uids.add(uid)
                    entities.append(SmartHQWaterHeater(
                        hass=hass,
                        entry=entry,
                        client=client,
                        device_id=device_id,
                        service_id=service_id,
                        dev_name=dev_name,
                        svc_config=svc.get("config") or {},
                        unique_id=uid,
                    ))

    _LOGGER.info("[WATER_HEATER] Registering %d water heater entities", len(entities))
    if entities:
        async_add_entities(entities, update_before_add=False)


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------

class SmartHQWaterHeater(WaterHeaterEntity):
    """Water heater entity backed by waterheater.v1 service."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )

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
        self._attr_name = f"{dev_name} Water Heater"
        self._attr_unique_id = unique_id

        # Build supported operation modes from config
        mode_tokens = svc_config.get("supportedModes") or []
        self._attr_operation_list = [
            _MODE_MAP[t] for t in mode_tokens if t in _MODE_MAP
        ] or list(_MODE_MAP.values())

        # Temperature range from config
        self._attr_min_temp = svc_config.get("setpointFahrenheitMinimum") or 100.0
        self._attr_max_temp = svc_config.get("setpointFahrenheitMaximum") or 140.0
        self._attr_target_temperature_step = 1.0

    def _get_state(self) -> dict:
        store = _store(self.hass, self._entry)
        snap = (store.get(self._device_id) or {}).get("snapshot") or {}
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def current_operation(self) -> str | None:
        token = self._get_state().get("mode") or ""
        return _MODE_MAP.get(token)

    @property
    def current_temperature(self) -> float | None:
        return None  # waterheater.v1 doesn't expose measured temp

    @property
    def target_temperature(self) -> float | None:
        st = self._get_state()
        return st.get("setpointFahrenheit") or st.get("setpointFahrenheitConverted")

    @property
    def available(self) -> bool:
        st = self._get_state()
        return "mode" in st or "setpointFahrenheit" in st

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        client = self._client or _bucket(self.hass, self._entry).get("client")
        if not client:
            return
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await client.async_set_waterheater(
                self._device_id, self._service_id, setpointFahrenheit=float(temp)
            )

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        client = self._client or _bucket(self.hass, self._entry).get("client")
        if not client:
            return
        token = _HA_MODE_TO_SMARTHQ.get(operation_mode)
        if token:
            await client.async_set_waterheater(
                self._device_id, self._service_id, mode=token
            )

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
