"""Button platform for SmartHQ integration.

Entity registration is driven entirely by coordinator.data[device_id]["item"]["services"].

Service → entity mapping:
  trigger                          → SmartHQTriggerButton   (trigger.do)
  firmware.v1 + CMD_FIRMWARE_UPGRADE → SmartHQFirmwareUpgradeButton
  coffeebrewer.v1/.v2              → SmartHQCoffeeBrewerButton (start + stop)
  cooking.mode.v1 (with food doms) → SmartHQStartCookingButton (send pending params)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_NAME
from .dispatcher import SIGNAL_DEVICE_UPDATED
from .service_registry import (
    TRIGGER_SERVICE,
    FIRMWARE_SERVICE,
    COFFEEBREWER_V1_SERVICE,
    COFFEEBREWER_V2_SERVICE,
    COOKING_MODE_SERVICE,
    is_cooking_mode_domain,
    DISHWASHER_STATE_V1_SERVICE,
    DISHDRAWER_STATE_LEGACY_SERVICE,
    CMD_TRIGGER_DO,
    CMD_FIRMWARE_UPGRADE,
    CMD_COOKING_MODE_SET,
    CMD_COOKING_MODE_START,
    CMD_DISHWASHER_STATE_START,
    CMD_DISHWASHER_STATE_STOP,
    CMD_DISHWASHER_STATE_PAUSE,
    CMD_DISHDRAWER_STATE_LEGACY_START,
    CMD_DISHDRAWER_STATE_LEGACY_STOP,
    CMD_DISHDRAWER_STATE_LEGACY_PAUSE,
    COOKING_ADVANTIUM_SERVICE,
    CMD_ADVANTIUM_START,
    CMD_ADVANTIUM_STOP,
    CMD_ADVANTIUM_PAUSE,
    CMD_ADVANTIUM_RESUME,
    MIXER_SERVICE,
    CMD_MIXER_CANCEL,
    CMD_MIXER_PAUSE,
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


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SmartHQ button entities from coordinator service definitions."""
    bucket = _bucket(hass, entry)
    coordinator = bucket.get("coordinator")
    client = bucket.get("client")
    api = bucket.get("api")

    if not coordinator or not coordinator.data:
        _LOGGER.warning("[BUTTON] Coordinator data not available yet")
        return

    entities: List[ButtonEntity] = []

    for device_id, device_item in coordinator.data.items():
        item = device_item.get("item") or {}
        services_list = item.get("services") or []
        if not isinstance(services_list, list):
            continue

        info = item.get("info") or {}
        dev_name = info.get("nickname") or info.get("name") or DEFAULT_NAME

        # Detect cooking.mode.v1 food-domain services for StartCookingButton
        has_cooking_mode = False
        # True when device has probe-based cooking (Smoker-style: cooking.food.*)
        has_probe_mode = False

        for svc in services_list:
            if not isinstance(svc, dict):
                continue

            stype = svc.get("serviceType") or ""
            dom = svc.get("domainType") or ""
            service_id = svc.get("id") or svc.get("serviceId") or ""
            cmds = svc.get("supportedCommands") or []

            # ── trigger → button ────────────────────────────────────────────
            if stype == TRIGGER_SERVICE:
                label = dom.split(".")[-1].replace("_", " ").title() if dom else "Trigger"
                entities.append(SmartHQTriggerButton(
                    hass=hass, entry=entry, client=client,
                    device_id=device_id, service_id=service_id,
                    dev_name=dev_name, label=label,
                    unique_id=make_unique_id(device_id, service_id, "trigger"),
                ))

            # ── firmware upgrade → button ───────────────────────────────────
            elif stype == FIRMWARE_SERVICE and CMD_FIRMWARE_UPGRADE in cmds:
                entities.append(SmartHQFirmwareUpgradeButton(
                    hass=hass, entry=entry, client=client,
                    device_id=device_id, service_id=service_id,
                    dev_name=dev_name,
                    unique_id=make_unique_id(device_id, service_id, "fw_upgrade"),
                ))

            # ── coffee brewer start/stop ────────────────────────────────────
            elif stype in (COFFEEBREWER_V1_SERVICE, COFFEEBREWER_V2_SERVICE):
                version = "v1" if stype == COFFEEBREWER_V1_SERVICE else "v2"
                for btn_type in ("start", "stop"):
                    cmd = f"cloud.smarthq.command.coffeebrewer.{version}.{btn_type}"
                    entities.append(SmartHQCoffeeBrewerButton(
                        hass=hass, entry=entry, api=api,
                        device_id=device_id, service_id=service_id,
                        dev_name=dev_name, command_type=cmd, button_type=btn_type,
                        unique_id=make_unique_id(device_id, service_id, f"brew_{btn_type}"),
                    ))

            # ── cooking.mode.v1 (any startable cooking domain) → start cooking button
            # Covers Smoker (food.*), Toaster Oven (bake/airfry/toast…), Oven, Microwave
            elif stype == COOKING_MODE_SERVICE:
                if is_cooking_mode_domain(dom):
                    has_cooking_mode = True
                    # Smoker-style: probe-based cooking (cooking.food.*)
                    if "cooking.food." in dom:
                        has_probe_mode = True

            # ── dishwasher.state.v1 → start/stop/pause buttons ────────────────
            elif stype == DISHWASHER_STATE_V1_SERVICE:
                ws = bucket.get("client") or bucket.get("ws")
                if ws:
                    for btn_label, cmd_type, uid_sfx in [
                        ("Start",  CMD_DISHWASHER_STATE_START, "dw_start"),
                        ("Stop",   CMD_DISHWASHER_STATE_STOP,  "dw_stop"),
                        ("Pause",  CMD_DISHWASHER_STATE_PAUSE, "dw_pause"),
                    ]:
                        if cmd_type in cmds:
                            entities.append(SmartHQDishwasherStateButton(
                                hass=hass, entry=entry, ws=ws,
                                device_id=device_id, service_id=service_id,
                                dev_name=dev_name, label=btn_label,
                                command_type=cmd_type,
                                unique_id=make_unique_id(device_id, service_id, uid_sfx),
                            ))

            # ── dishdrawer.state.legacy → start/stop/pause buttons ────────────
            elif stype == DISHDRAWER_STATE_LEGACY_SERVICE:
                ws = bucket.get("client") or bucket.get("ws")
                if ws:
                    for btn_label, cmd_type, uid_sfx in [
                        ("Start",  CMD_DISHDRAWER_STATE_LEGACY_START, "ddr_start"),
                        ("Stop",   CMD_DISHDRAWER_STATE_LEGACY_STOP,  "ddr_stop"),
                        ("Pause",  CMD_DISHDRAWER_STATE_LEGACY_PAUSE, "ddr_pause"),
                    ]:
                        if cmd_type in cmds:
                            entities.append(SmartHQDishwasherStateButton(
                                hass=hass, entry=entry, ws=ws,
                                device_id=device_id, service_id=service_id,
                                dev_name=dev_name, label=f"Dishdrawer {btn_label}",
                                command_type=cmd_type,
                                unique_id=make_unique_id(device_id, service_id, uid_sfx),
                            ))

            # ── cooking.advantium → start/stop/pause/resume buttons ───────────
            elif stype == COOKING_ADVANTIUM_SERVICE:
                ws = bucket.get("client") or bucket.get("ws")
                if ws:
                    for btn_label, cmd_type, uid_sfx, icon in [
                        ("Start",  CMD_ADVANTIUM_START,  "adv_start",  "mdi:play"),
                        ("Stop",   CMD_ADVANTIUM_STOP,   "adv_stop",   "mdi:stop"),
                        ("Pause",  CMD_ADVANTIUM_PAUSE,  "adv_pause",  "mdi:pause"),
                        ("Resume", CMD_ADVANTIUM_RESUME, "adv_resume", "mdi:play-pause"),
                    ]:
                        if cmd_type in cmds:
                            entities.append(SmartHQAdvantiumButton(
                                hass=hass, entry=entry, ws=ws,
                                device_id=device_id, service_id=service_id,
                                dev_name=dev_name, label=btn_label,
                                command_type=cmd_type, icon=icon,
                                unique_id=make_unique_id(device_id, service_id, uid_sfx),
                            ))

            # ── mixer.v1 → cancel/pause buttons ──────────────────────────────
            elif stype == MIXER_SERVICE:
                ws = bucket.get("client") or bucket.get("ws")
                if ws:
                    for btn_label, cmd_type, uid_sfx, icon in [
                        ("Cancel", CMD_MIXER_CANCEL, "mixer_cancel", "mdi:stop"),
                        ("Pause",  CMD_MIXER_PAUSE,  "mixer_pause",  "mdi:pause"),
                    ]:
                        if cmd_type in cmds:
                            entities.append(SmartHQAdvantiumButton(
                                hass=hass, entry=entry, ws=ws,
                                device_id=device_id, service_id=service_id,
                                dev_name=dev_name, label=btn_label,
                                command_type=cmd_type, icon=icon,
                                unique_id=make_unique_id(device_id, service_id, uid_sfx),
                            ))

        # One cooking start button per device that has cooking.mode.v1 startable services
        if has_cooking_mode:
            entities.append(SmartHQStartCookingButton(
                hass=hass, entry=entry, client=client,
                device_id=device_id, dev_name=dev_name,
                is_smoker_style=has_probe_mode,
                unique_id=make_unique_id(device_id, device_id, "start_cooking"),
            ))

    _LOGGER.info("[BUTTON] Registering %d button entities", len(entities))
    if entities:
        async_add_entities(entities, update_before_add=False)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------

class _SmartHQButtonBase(ButtonEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass, entry, device_id, dev_name, unique_id):
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._attr_unique_id = unique_id

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)


class SmartHQTriggerButton(_SmartHQButtonBase):
    """Button for a trigger service — sends trigger.do with no parameters."""

    _attr_icon = "mdi:gesture-tap-button"

    def __init__(self, hass, entry, client, device_id, service_id,
                 dev_name, label, unique_id):
        super().__init__(hass, entry, device_id, dev_name, unique_id)
        self._client = client
        self._service_id = service_id
        self._attr_name = f"{dev_name} {label}"

    async def async_press(self) -> None:
        if self._client:
            await self._client.async_send_service_command(
                device_id=self._device_id,
                service_id=self._service_id,
                command_type=CMD_TRIGGER_DO,
                params={},
            )
            _LOGGER.info("[TRIGGER] Sent trigger.do for %s", self._attr_name)
        else:
            _LOGGER.error("[TRIGGER] WebSocket client not available")


class SmartHQFirmwareUpgradeButton(_SmartHQButtonBase):
    """Button to initiate a firmware upgrade."""

    _attr_icon = "mdi:update"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass, entry, client, device_id, service_id,
                 dev_name, unique_id):
        super().__init__(hass, entry, device_id, dev_name, unique_id)
        self._client = client
        self._service_id = service_id
        self._attr_name = f"{dev_name} Start Firmware Upgrade"

    async def async_press(self) -> None:
        if self._client:
            await self._client.async_send_service_command(
                device_id=self._device_id,
                service_id=self._service_id,
                command_type=CMD_FIRMWARE_UPGRADE,
                params={},
            )
            _LOGGER.info("[FW_UPGRADE] Sent firmware.v1.upgrade for %s", self._attr_name)
        else:
            _LOGGER.error("[FW_UPGRADE] WebSocket client not available")


class SmartHQCoffeeBrewerButton(_SmartHQButtonBase):
    """Coffee Brewer start/stop button."""

    def __init__(self, hass, entry, api, device_id, service_id,
                 dev_name, command_type, button_type, unique_id):
        super().__init__(hass, entry, device_id, dev_name, unique_id)
        self._api = api
        self._service_id = service_id
        self._command_type = command_type
        self._button_type = button_type
        self._attr_name = f"{dev_name} Brew {button_type.title()}"
        self._attr_icon = "mdi:coffee" if button_type == "start" else "mdi:stop"

    async def async_press(self) -> None:
        bucket = _bucket(self.hass, self._entry)
        api = self._api or bucket.get("api")
        if not api:
            _LOGGER.error("[COFFEE] API not available")
            return

        command: Dict[str, Any] = {"commandType": self._command_type}

        if self._button_type == "start":
            settings = (bucket.get("coffee_brewer_settings") or {}).get(self._device_id, {})
            strength_map = {"Light": 0, "Medium": 1, "Bold": 2}
            size_str = settings.get("size", "12 Oz")
            temp_str = settings.get("temperature", "90°C")
            try:
                volume = float(size_str.split()[0]) if size_str != "Carafe" else 14.0
            except (ValueError, IndexError):
                volume = 12.0
            try:
                temp = float(temp_str.replace("°C", ""))
            except ValueError:
                temp = 90.0
            command.update({
                "strength": strength_map.get(settings.get("strength", "Medium"), 1),
                "volumeSingle": volume,
                "volumeUnits": "cloud.smarthq.type.volumeunits.fluidounces",
                "temperatureCelsius": temp,
            })

        # Retrieve service metadata from WS snapshot for the API call
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}

        await api.async_send_command(
            device_id=self._device_id,
            service_type=svc.get("serviceType", ""),
            domain_type=svc.get("domainType", ""),
            service_device_type=svc.get("serviceDeviceType", ""),
            command=command,
        )
        _LOGGER.info("[COFFEE] ✓ Sent %s command", self._button_type.upper())


class SmartHQStartCookingButton(_SmartHQButtonBase):
    """Button to send all pending cooking parameters to the device.

    Replaces the device-type-specific SmartHQSendToSmoker.
    Works for any device that has cooking.mode.v1 food-domain services.
    """

    _attr_icon = "mdi:play-circle"

    def __init__(self, hass, entry, client, device_id, dev_name, unique_id, is_smoker_style: bool = False):
        super().__init__(hass, entry, device_id, dev_name, unique_id)
        self._client = client
        self._is_smoker_style = is_smoker_style
        # Smoker keeps the familiar "Send To Smoker" label; all other cooking
        # devices (Toaster Oven, Oven, etc.) use the generic "Start Cooking" label.
        if is_smoker_style:
            self._attr_name = f"{dev_name} Send To Smoker"
        else:
            self._attr_name = f"{dev_name} Start Cooking"

    @property
    def available(self) -> bool:
        """Available as long as the device is known (snapshot exists).
        The user can pre-configure all parameters before powering on, mirroring
        the SmartHQ app behaviour where NEW SMOKE is accessible at any time.
        """
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        return bool(snap)

    async def async_press(self) -> None:
        bucket = _bucket(self.hass, self._entry)
        client = self._client or bucket.get("client")
        if not client:
            _LOGGER.error("[START_COOKING] WebSocket client not available")
            return

        pending_modes = bucket.get("pending_cook_modes") or {}
        mode_info = pending_modes.get(self._device_id) or {}
        pending_params = bucket.get("pending_cook_params") or {}
        device_params = pending_params.get(self._device_id) or {}

        mode_token = mode_info.get("mode_token")
        temp_value = device_params.get("smoker_temp_f")
        is_probe_based = device_params.get("is_probe_based", True)
        probe_target = device_params.get("probe_target_f") if is_probe_based else None
        timer_value = device_params.get("cook_time_min") if not is_probe_based else None
        smoke_level = device_params.get("smoke_level")
        auto_keep_warm = device_params.get("auto_keep_warm")
        doneness_level = device_params.get("doneness_level")
        cook_option = device_params.get("cook_option")
        numeric_option = device_params.get("numeric_option")

        if not mode_token:
            # Fallback: read current mode from WS snapshot cooking.state
            snap = _snapshot_for(self.hass, self._entry, self._device_id)
            for st in (snap.get("services") or {}).values():
                if isinstance(st, dict) and st.get("serviceType") == "cloud.smarthq.service.cooking.state.v1":
                    mode_token = str(st.get("mode") or "")
                    break

        if not mode_token:
            _LOGGER.error("[START_COOKING] No cook mode selected or active")
            return

        _LOGGER.info(
            "[START_COOKING] Device %s: mode=%s temp=%s timer=%s probe=%s smoke=%s "
            "probe_based=%s warm=%s doneness=%s option=%s numeric=%s",
            self._device_id[:8], mode_token, temp_value, timer_value,
            probe_target, smoke_level, is_probe_based, auto_keep_warm,
            doneness_level, cook_option, numeric_option,
        )

        try:
            await client.async_set_cooking_mode(
                self._device_id,
                None,
                mode_token,
                cavity_temp_f=temp_value,
                cook_time_minutes=timer_value,
                probe_temp_f=probe_target,
                smoke_level=smoke_level,
                auto_keep_warm=auto_keep_warm,
                doneness_level=doneness_level,
                cook_option=cook_option,
                numeric_option=numeric_option,
            )
            _LOGGER.info("[START_COOKING] ✓ Settings sent to device %s", self._device_id[:8])

            # Persist last sent mode; clear one-shot pending params
            if mode_token:
                bucket.setdefault("pending_cook_modes", {}).setdefault(
                    self._device_id, {}
                )["last_sent_mode"] = mode_token
                mode_info.pop("mode_token", None)
            if device_params:
                pending_params.pop(self._device_id, None)

        except Exception as exc:
            _LOGGER.error("[START_COOKING] Failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Dishwasher state command buttons (start / stop / pause)
# ---------------------------------------------------------------------------

class SmartHQDishwasherStateButton(_SmartHQButtonBase):
    """Button to send a dishwasher.state.v1 command (start/stop/pause)."""

    def __init__(self, hass, entry, ws, device_id, service_id, dev_name, label, command_type, unique_id):
        super().__init__(hass, entry, device_id, dev_name, unique_id)
        self._ws = ws
        self._service_id = service_id
        self._command_type = command_type
        self._attr_name = f"{dev_name} Dishwasher {label}"
        self._attr_icon = {
            "Start": "mdi:play",
            "Stop":  "mdi:stop",
            "Pause": "mdi:pause",
        }.get(label, "mdi:gesture-tap-button")

    async def async_press(self) -> None:
        _LOGGER.info("[DISHWASHER_BTN] %s: %s", self._attr_name, self._command_type)
        try:
            await self._ws.async_dishwasher_state_command(
                device_id=self._device_id,
                service_id=self._service_id,
                command_type=self._command_type,
            )
        except Exception as exc:
            _LOGGER.error("[DISHWASHER_BTN] Failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Advantium command buttons (start / stop / pause / resume)
# ---------------------------------------------------------------------------

class SmartHQAdvantiumButton(_SmartHQButtonBase):
    """Button to send a cooking.advantium command (start/stop/pause/resume)."""

    def __init__(self, hass, entry, ws, device_id, service_id, dev_name, label, command_type, icon, unique_id):
        super().__init__(hass, entry, device_id, dev_name, unique_id)
        self._ws = ws
        self._service_id = service_id
        self._command_type = command_type
        self._attr_name = f"{dev_name} Advantium {label}"
        self._attr_icon = icon

    async def async_press(self) -> None:
        _LOGGER.info("[ADVANTIUM_BTN] %s: %s", self._attr_name, self._command_type)
        try:
            await self._ws.async_advantium_command(
                device_id=self._device_id,
                service_id=self._service_id,
                command_type=self._command_type,
            )
        except Exception as exc:
            _LOGGER.error("[ADVANTIUM_BTN] Failed: %s", exc, exc_info=True)
