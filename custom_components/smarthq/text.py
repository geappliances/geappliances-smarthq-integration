"""Text platform for SmartHQ integration.

Handles string services that support the cloud.smarthq.command.string.set command.
Examples: Appliance Set Model Number (domain.model), custom label strings, etc.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_NAME
from .dispatcher import SIGNAL_DEVICE_UPDATED
from .service_registry import (
    STRING_SERVICE,
    CMD_STRING_SET,
    make_unique_id,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------

def _bucket(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}

def _store(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return _bucket(hass, entry).get("store") or {}

def _known_devices(hass: HomeAssistant, entry: ConfigEntry) -> List[str]:
    return list(_store(hass, entry).keys())

def _dev_payload(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Dict[str, Any]:
    return _store(hass, entry).get(device_id) or {}

def _device_info_for(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Dict[str, Any]:
    info = _dev_payload(hass, entry, device_id).get("info") or {}
    return {
        "identifiers": {(DOMAIN, device_id)},
        "name": info.get("nickname") or info.get("model") or device_id[:8],
        "manufacturer": MANUFACTURER,
        "model": info.get("model"),
    }

def _snapshot_for(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Dict[str, Any]:
    return _dev_payload(hass, entry, device_id).get("snapshot") or {}

def _get_services(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> List[dict]:
    item = _dev_payload(hass, entry, device_id).get("item") or {}
    svcs = item.get("services") or []
    return svcs if isinstance(svcs, list) else []


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartHQ text entities."""
    coordinator = _bucket(hass, entry).get("coordinator")
    if not coordinator or not coordinator.data:
        _LOGGER.warning("[TEXT] No coordinator data available")
        return

    created: set[str] = set()

    def _discover() -> None:
        entities: List[SmartHQStringTextEntity] = []

        for device_id, device_item in coordinator.data.items():
            item = device_item.get("item") or {}
            services_list = item.get("services") or []
            if not isinstance(services_list, list):
                continue

            info = device_item.get("info") or {}
            dev_name = info.get("nickname") or info.get("name") or DEFAULT_NAME

            for svc in services_list:
                if not isinstance(svc, dict):
                    continue

                stype = svc.get("serviceType") or ""
                service_id = svc.get("id") or svc.get("serviceId") or ""
                cfg = svc.get("config") or {}
                dom = svc.get("domainType") or ""
                cmds = svc.get("supportedCommands") or []

                if stype != STRING_SERVICE:
                    continue
                if CMD_STRING_SET not in cmds:
                    continue

                uid = make_unique_id(device_id, service_id, "string_text")
                if uid in created:
                    continue
                created.add(uid)

                label = cfg.get("label") or dom.split(".")[-1].replace("_", " ").title()
                entities.append(SmartHQStringTextEntity(
                    hass=hass,
                    entry=entry,
                    device_id=device_id,
                    service_id=service_id,
                    dev_name=dev_name,
                    label=label,
                    unique_id=uid,
                ))

        if entities:
            _LOGGER.debug("[TEXT] Adding %d text entities", len(entities))
            async_add_entities(entities, update_before_add=True)

    _discover()

    @callback
    def _on_coordinator_update() -> None:
        _discover()

    entry.async_on_unload(
        coordinator.async_add_listener(_on_coordinator_update)
    )


# ---------------------------------------------------------------------------
# SmartHQStringTextEntity
# ---------------------------------------------------------------------------

class SmartHQStringTextEntity(TextEntity):
    """Text entity for string services that support cloud.smarthq.command.string.set."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_mode = TextMode.TEXT

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        service_id: str,
        dev_name: str,
        label: str,
        unique_id: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._attr_unique_id = unique_id
        self._attr_name = f"{dev_name} {label}"
        self._attr_native_value: Optional[str] = None

    def _get_state(self) -> Dict[str, Any]:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def native_value(self) -> Optional[str]:
        return self._get_state().get("stringValue")

    @property
    def available(self) -> bool:
        st = self._get_state()
        return bool(st) and not st.get("disabled", False)

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_set_value(self, value: str) -> None:
        client = _bucket(self.hass, self._entry).get("client")
        if client:
            await client.async_send_service_command(
                device_id=self._device_id,
                service_id=self._service_id,
                command_type=CMD_STRING_SET,
                params={"stringValue": value},
            )
        self.async_write_ha_state()

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
