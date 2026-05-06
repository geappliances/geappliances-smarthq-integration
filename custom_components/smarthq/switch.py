"""Switch platform for SmartHQ integration.

Entity registration is driven by:
  1. coordinator.data[device_id]["item"]["services"]  (WS-based service switches)
  2. coordinator.data[device_id]["settings"]           (REST-based notification/alert toggles)

Service → entity mapping:
  toggle  + CMD_TOGGLE_SET                               → SmartHQToggleSwitch
  mode    + CMD_MODE_SET + domain in SWITCH_MODE_DOMAINS → SmartHQModeSwitch
  settings (type=BOOLEAN)                                → SmartHQSettingSwitch
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_NAME, sdev_prefix
from .dispatcher import SIGNAL_DEVICE_UPDATED
from .service_registry import (
    TOGGLE_SERVICE,
    MODE_SERVICE,
    LAUNDRY_TOGGLE_V2_SERVICE,
    CMD_TOGGLE_SET,
    CMD_MODE_SET,
    CMD_LAUNDRY_TOGGLE_V2_SET,
    SWITCH_MODE_DOMAINS,
    make_unique_id,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------

def _bucket(hass, entry):
    return hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}

def _store(hass, entry):
    return _bucket(hass, entry).get("store") or {}

def _dev_payload(hass, entry, device_id):
    return _store(hass, entry).get(device_id) or {}

def _snapshot_for(hass, entry, device_id):
    return _dev_payload(hass, entry, device_id).get("snapshot") or {}

def _device_info_for(hass, entry, device_id):
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

def _label_for_toggle(dom, sdev: str = ""):
    d = dom.lower()
    if "warm.auto" in d:
        return "Auto Warm", "mdi:fire-alert"
    if "lock" in d or "override" in d:
        return "Control Lock", "mdi:lock"
    if "light" in d or "cavity" in d:
        return "Cavity Light", "mdi:lightbulb"
    if "smoke" in d:
        return "Clear Smoke", "mdi:smoke"
    base = dom.split(".")[-1].replace("_", " ").title() if dom else "Toggle"
    prefix = sdev_prefix(sdev)
    return (f"{prefix} {base}".strip() if prefix else base), "mdi:toggle-switch"

def _label_for_mode_switch(dom, sdev: str = ""):
    d = dom.lower()
    if "brightness" in d or "light" in d:
        return "Cavity Light", "mdi:lightbulb"
    if "lock" in d or "override" in d:
        return "Control Lock", "mdi:lock"
    base = dom.split(".")[-1].replace("_", " ").title() if dom else "Mode"
    prefix = sdev_prefix(sdev)
    return (f"{prefix} {base}".strip() if prefix else base), "mdi:toggle-switch"


def _pretty_dom(dom: str) -> str:
    """Return human-readable name from domain tail."""
    return dom.split(".")[-1].replace("_", " ").title() if dom else ""


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SmartHQ switches from coordinator service definitions."""
    bucket = _bucket(hass, entry)
    ws = bucket.get("client") or bucket.get("ws")
    coordinator = bucket.get("coordinator")

    if not ws:
        _LOGGER.error("[SWITCH] WebSocket client not found in bucket")
        return
    if not coordinator or not coordinator.data:
        _LOGGER.warning("[SWITCH] Coordinator data not available yet")
        return

    entities = []

    for device_id, device_item in coordinator.data.items():
        item = device_item.get("item") or {}
        services_list = item.get("services") or []
        if not isinstance(services_list, list):
            continue

        # Per-device dedup: track (serviceType, domainType) pairs already handled.
        # This prevents duplicate switch entities when the same domain appears in
        # multiple service instances (e.g. Smoker Light State Service appears once
        # for the smoker serviceDeviceType and once for the light serviceDeviceType).
        seen_switch_domains: set[tuple[str, str]] = set()

        for svc in services_list:
            if not isinstance(svc, dict):
                continue

            stype = svc.get("serviceType") or ""
            dom = svc.get("domainType") or ""
            service_id = svc.get("id") or svc.get("serviceId") or ""
            cmds = svc.get("supportedCommands") or []

            if stype == TOGGLE_SERVICE and CMD_TOGGLE_SET in cmds:
                label, icon = _label_for_toggle(dom, svc.get("serviceDeviceType") or "")
                entities.append(SmartHQToggleSwitch(
                    hass=hass, entry=entry, ws=ws,
                    device_id=device_id, service_id=service_id,
                    label=label, icon=icon,
                    unique_id=make_unique_id(device_id, service_id, "toggle"),
                ))

            elif stype == MODE_SERVICE and CMD_MODE_SET in cmds and dom in SWITCH_MODE_DOMAINS:
                # Skip if this device already has a switch for this domain
                dedup_key = (stype, dom)
                if dedup_key in seen_switch_domains:
                    _LOGGER.debug(
                        "[SWITCH] Skipping duplicate mode switch for device=%s domain=%s svc=%s",
                        device_id, dom, service_id,
                    )
                    continue
                seen_switch_domains.add(dedup_key)
                label, icon = _label_for_mode_switch(dom, svc.get("serviceDeviceType") or "")
                entities.append(SmartHQModeSwitch(
                    hass=hass, entry=entry, ws=ws,
                    device_id=device_id, service_id=service_id,
                    label=label, icon=icon,
                    unique_id=make_unique_id(device_id, service_id, "mode_switch"),
                ))

            elif stype == LAUNDRY_TOGGLE_V2_SERVICE and CMD_LAUNDRY_TOGGLE_V2_SET in cmds:
                label = _pretty_dom(dom) or "Washer Link"
                entities.append(SmartHQLaundryToggleSwitch(
                    hass=hass, entry=entry, ws=ws,
                    device_id=device_id, service_id=service_id,
                    label=label, dom=dom,
                    unique_id=make_unique_id(device_id, service_id, "laundry_toggle_v2"),
                ))

        # ── Settings-based BOOLEAN notification/alert switches ──────────
        settings_list = device_item.get("settings") or []
        api = bucket.get("api")
        # coordinator.data[did]["info"] is set directly by coordinator._async_update_data
        info = device_item.get("info") or {}
        dev_name = info.get("nickname") or info.get("name") or DEFAULT_NAME
        _LOGGER.warning("[SWITCH_SETTINGS] device=%s settings_count=%d", device_id[:8], len(settings_list))
        for setting in settings_list:
            if not isinstance(setting, dict):
                continue
            if setting.get("type") != "BOOLEAN":
                continue
            rule_id = setting.get("id") or ""
            if not rule_id:
                continue
            title = setting.get("title") or setting.get("name") or rule_id
            # Strip device name prefix from title to avoid "Smoker Smoker Door Alert"
            if dev_name and title.lower().startswith(dev_name.lower() + " "):
                title = title[len(dev_name) + 1:]
            # Normalise all-caps titles like "BREW CYCLE STATUS" → "Brew Cycle Status"
            if title == title.upper():
                title = title.title()
            description = setting.get("description") or ""
            uid = make_unique_id(device_id, rule_id, "setting")
            entities.append(SmartHQSettingSwitch(
                hass=hass, entry=entry, api=api,
                device_id=device_id, rule_id=rule_id,
                dev_name=dev_name, title=title, description=description,
                initial_value=bool(setting.get("current", False)),
                unique_id=uid,
            ))

    _LOGGER.info("[SWITCH] Registering %d switch entities", len(entities))
    if entities:
        async_add_entities(entities, update_before_add=False)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------

class _SmartHQSwitchBase(SwitchEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass, entry, ws, device_id, service_id, label, icon, unique_id):
        self.hass = hass
        self._entry = entry
        self._ws = ws
        self._device_id = device_id
        self._service_id = service_id
        info = _dev_payload(hass, entry, device_id).get("info") or {}
        dev_name = info.get("nickname") or info.get("name") or DEFAULT_NAME
        self._attr_name = f"{dev_name} {label}"
        self._attr_icon = icon
        self._attr_unique_id = unique_id

    def _get_service_state(self):
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        return (snap.get("services") or {}).get(self._service_id) or {}

    def _find_cooking_state(self):
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        for st in (snap.get("services") or {}).values():
            if isinstance(st, dict) and "cooking" in str(st.get("serviceType") or ""):
                return st
        return {}

    @property
    def available(self):
        st = self._get_service_state()
        if not st or st.get("disabled"):
            return False
        dev_data = _dev_payload(self.hass, self._entry, self._device_id)
        if (dev_data.get("presence") or {}).get("presence") != "ONLINE":
            return False
        return True

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self):
        self.async_write_ha_state()


class SmartHQToggleSwitch(_SmartHQSwitchBase):
    """Switch for a toggle service (on/off via toggle.set)."""

    @property
    def is_on(self):
        st = self._get_service_state()
        value = st.get("on")
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value == 1
        if isinstance(value, str):
            return value.lower() in ("on", "true", "1")
        return False

    async def async_turn_on(self, **kwargs):
        _LOGGER.info("[TOGGLE] ON: %s", self._attr_name)
        await self._ws.async_set_toggle(device_id=self._device_id, service_id=self._service_id, on=True)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        _LOGGER.info("[TOGGLE] OFF: %s", self._attr_name)
        await self._ws.async_set_toggle(device_id=self._device_id, service_id=self._service_id, on=False)
        self._attr_is_on = False
        self.async_write_ha_state()


class SmartHQModeSwitch(_SmartHQSwitchBase):
    """Switch for a mode service whose domain is binary (e.g. cavity light, lock)."""

    _ON_SUFFIXES = frozenset({"on", "high", "dim", "enabled", "locked"})

    @property
    def is_on(self):
        st = self._get_service_state()
        if "on" in st:
            return bool(st["on"])
        mode = st.get("mode")
        if not mode:
            return False
        return str(mode).split(".")[-1].lower() in self._ON_SUFFIXES

    @property
    def available(self):
        if not super().available:
            return False
        # Light/brightness domains require device to be active
        name_lower = self._attr_name.lower()
        if "light" in name_lower or "cavity" in name_lower:
            run_status = str(self._find_cooking_state().get("runStatus") or "").lower()
            if run_status and "off" in run_status:
                return False
        return True

    async def async_turn_on(self, **kwargs):
        _LOGGER.info("[MODE_SWITCH] ON: %s", self._attr_name)
        try:
            await self._ws.async_set_mode(self._device_id, self._service_id, "cloud.smarthq.type.mode.on")
            self.async_write_ha_state()
        except Exception as exc:
            _LOGGER.error("[MODE_SWITCH] Error ON %s: %s", self._attr_name, exc)

    async def async_turn_off(self, **kwargs):
        _LOGGER.info("[MODE_SWITCH] OFF: %s", self._attr_name)
        try:
            await self._ws.async_set_mode(self._device_id, self._service_id, "cloud.smarthq.type.mode.off")
            self.async_write_ha_state()
        except Exception as exc:
            _LOGGER.error("[MODE_SWITCH] Error OFF %s: %s", self._attr_name, exc)


# ---------------------------------------------------------------------------
# Laundry Toggle v2 switch
# ---------------------------------------------------------------------------

class SmartHQLaundryToggleSwitch(_SmartHQSwitchBase):
    """Switch for laundry.toggle.v2 service (e.g. Washer Link dryer)."""

    def __init__(self, hass, entry, ws, device_id, service_id, label, dom, unique_id):
        super().__init__(
            hass=hass, entry=entry, ws=ws,
            device_id=device_id, service_id=service_id,
            label=label, icon="mdi:washing-machine",
            unique_id=unique_id,
        )
        self._dom = dom

    @property
    def is_on(self) -> bool:
        return bool(self._get_service_state().get("on", False))

    @property
    def extra_state_attributes(self) -> dict:
        st = self._get_service_state()
        cycle = st.get("cycle")
        return {"cycle": cycle.split(".")[-1].upper() if cycle else None}

    async def async_turn_on(self, **kwargs):
        _LOGGER.info("[LAUNDRY_TOGGLE_V2] ON: %s", self._attr_name)
        await self._ws.async_set_laundry_toggle_v2(
            device_id=self._device_id, service_id=self._service_id, on=True
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        _LOGGER.info("[LAUNDRY_TOGGLE_V2] OFF: %s", self._attr_name)
        await self._ws.async_set_laundry_toggle_v2(
            device_id=self._device_id, service_id=self._service_id, on=False
        )
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Settings-based BOOLEAN switch (notification / alert toggles)
# ---------------------------------------------------------------------------

def _icon_for_setting(title: str) -> str:
    """Pick an MDI icon based on alert/notification title keywords."""
    t = title.lower()
    if "door" in t:
        return "mdi:door-alert"
    if "smoke" in t or "clear" in t:
        return "mdi:smoke-detector"
    if "preheat" in t:
        return "mdi:thermometer-alert"
    if "finish" in t or "complete" in t or "cycle" in t:
        return "mdi:check-circle-outline"
    if "early" in t or "reminder" in t:
        return "mdi:bell-ring-outline"
    if "warm" in t:
        return "mdi:fire-alert"
    if "start" in t:
        return "mdi:play-circle-outline"
    if "software" in t or "update" in t:
        return "mdi:update"
    if "lint" in t or "filter" in t or "mesh" in t:
        return "mdi:air-filter"
    if "balance" in t:
        return "mdi:scale-unbalanced"
    if "unattended" in t or "clothes" in t:
        return "mdi:tshirt-crew-outline"
    if "dispense" in t or "refill" in t:
        return "mdi:cup-water"
    if "delay" in t:
        return "mdi:timer-outline"
    if "wash" in t:
        return "mdi:washing-machine"
    if "self clean" in t or "clean" in t:
        return "mdi:auto-fix"
    return "mdi:bell-outline"


class SmartHQSettingSwitch(SwitchEntity):
    """Switch entity backed by a REST settings BOOLEAN rule.

    State is read from store[device_id]['settings'] (refreshed every 30 s by
    the _poll_settings task in __init__.py).  Writes go straight to the
    SmartHQ REST API via api.async_set_setting().
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self, hass, entry, api,
        device_id: str, rule_id: str,
        dev_name: str, title: str, description: str,
        initial_value: bool, unique_id: str,
    ):
        self.hass = hass
        self._entry = entry
        self._api = api
        self._device_id = device_id
        self._rule_id = rule_id
        self._title = title
        self._attr_name = f"{dev_name} {title}"
        self._attr_unique_id = unique_id
        self._attr_icon = _icon_for_setting(title)
        self._attr_entity_category = EntityCategory.CONFIG  # shown under Configuration, not Controls
        self._attr_extra_state_attributes = {"description": description} if description else {}
        self._current: bool = initial_value

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _get_current_from_store(self) -> bool | None:
        """Return the latest value from the settings list in the store."""
        store = _store(self.hass, self._entry)
        settings = (store.get(self._device_id) or {}).get("settings") or []
        for s in settings:
            if isinstance(s, dict) and s.get("id") == self._rule_id:
                return bool(s.get("current", self._current))
        return None

    @property
    def is_on(self) -> bool:
        v = self._get_current_from_store()
        return v if v is not None else self._current

    @property
    def available(self) -> bool:
        return True  # Settings are always reachable via REST

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )

    @callback
    def _signal_update(self):
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs):
        _LOGGER.info("[SETTING_SW] ON: %s (rule=%s)", self._title, self._rule_id)
        ok = await self._api.async_set_setting(self._device_id, self._rule_id, True)
        if ok:
            self._current = True
            # Optimistically update the store so the next poll sees the new value
            self._update_store(True)
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        _LOGGER.info("[SETTING_SW] OFF: %s (rule=%s)", self._title, self._rule_id)
        ok = await self._api.async_set_setting(self._device_id, self._rule_id, False)
        if ok:
            self._current = False
            self._update_store(False)
            self.async_write_ha_state()

    def _update_store(self, value: bool) -> None:
        """Optimistically update the settings list in the store."""
        store = _store(self.hass, self._entry)
        settings = (store.get(self._device_id) or {}).get("settings") or []
        for s in settings:
            if isinstance(s, dict) and s.get("id") == self._rule_id:
                s["current"] = value
                return
