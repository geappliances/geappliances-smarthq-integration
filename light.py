"""SmartHQ Light platform.

Entity registration is driven entirely by coordinator.data[device_id]["item"]["services"].

Service → entity mapping:
  cloud.smarthq.service.color                        → SmartHQColorLight
  cloud.smarthq.service.cooking.prorange.accent.light → SmartHQAccentLight
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.light import (
    LightEntity,
    ColorMode,
    ATTR_RGB_COLOR,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_BRIGHTNESS,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_NAME
from .dispatcher import SIGNAL_DEVICE_UPDATED
from .service_registry import (
    COLOR_SERVICE,
    COOKING_PRORANGE_ACCENT_LIGHT_SERVICE,
    CMD_COLOR_SET,
    CMD_ACCENT_LIGHT_SET,
    get_device_services,
    make_unique_id,
)

_LOGGER = logging.getLogger(__name__)

# color service colorspace type constants
COLORSPACE_RGB = "cloud.smarthq.type.colorspace.rgb"
COLORSPACE_HSB = "cloud.smarthq.type.colorspace.hsb"
COLORSPACE_RGB_INTENSITY = "cloud.smarthq.type.colorspace.rgb.intensity"
COLORSPACE_WHITENESS = "cloud.smarthq.type.colorspace.whiteness"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SmartHQ light entities from coordinator service definitions."""
    from .coordinator import SmartHQCoordinator

    bucket: Dict[str, Any] = hass.data[DOMAIN][entry.entry_id]
    coordinator: SmartHQCoordinator = bucket["coordinator"]
    ws = bucket.get("ws")

    entities: List[LightEntity] = []
    existing_uids: set[str] = set()

    for device_id, dev_data in coordinator.data.items():
        item = dev_data.get("item", {})
        _info = dev_data.get("info") or {}
        dev_name: str = _info.get("nickname") or _info.get("name") or DEFAULT_NAME
        services_list = item.get("services") or []
        if not isinstance(services_list, list):
            continue

        for svc in services_list:
            stype = svc.get("serviceType") or ""
            service_id = svc.get("id") or svc.get("serviceId") or ""
            cmds = svc.get("supportedCommands") or []
            config = svc.get("config") or {}

            if not service_id:
                continue

            # ── color service ────────────────────────────────────────────────
            if stype == COLOR_SERVICE:
                uid = make_unique_id(device_id, service_id, "color_light")
                if uid not in existing_uids:
                    color_spaces = config.get("colorSpaces") or []
                    entities.append(SmartHQColorLight(
                        hass=hass,
                        entry=entry,
                        device_id=device_id,
                        service_id=service_id,
                        device_name=dev_name,
                        unique_id=uid,
                        color_spaces=color_spaces,
                        controllable=CMD_COLOR_SET in cmds,
                        ws=ws,
                    ))
                    existing_uids.add(uid)

            # ── cooking.prorange.accent.light ────────────────────────────────
            elif stype == COOKING_PRORANGE_ACCENT_LIGHT_SERVICE:
                uid = make_unique_id(device_id, service_id, "accent_light")
                if uid not in existing_uids:
                    entities.append(SmartHQAccentLight(
                        hass=hass,
                        entry=entry,
                        device_id=device_id,
                        service_id=service_id,
                        device_name=dev_name,
                        unique_id=uid,
                        config=config,
                        controllable=CMD_ACCENT_LIGHT_SET in cmds,
                        ws=ws,
                    ))
                    existing_uids.add(uid)

    async_add_entities(entities, update_before_add=False)


class SmartHQColorLight(LightEntity):
    """Light entity for cloud.smarthq.service.color.

    Supports RGB, HSB, RGB+Intensity, and whiteness (color temperature) color spaces.
    colorSpace is determined from the service config.colorSpaces list.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        service_id: str,
        device_name: str,
        unique_id: str,
        color_spaces: list[str],
        controllable: bool,
        ws: Any,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._device_name = device_name
        self._color_spaces = color_spaces
        self._controllable = controllable
        self._ws = ws

        self._attr_unique_id = unique_id
        self._attr_name = f"{device_name} Color Light"

        # Determine supported color modes from colorSpaces
        self._attr_supported_color_modes: set[ColorMode] = set()
        if COLORSPACE_RGB in color_spaces or COLORSPACE_RGB_INTENSITY in color_spaces:
            self._attr_supported_color_modes.add(ColorMode.RGB)
        if COLORSPACE_HSB in color_spaces:
            self._attr_supported_color_modes.add(ColorMode.HS)
        if COLORSPACE_WHITENESS in color_spaces:
            self._attr_supported_color_modes.add(ColorMode.COLOR_TEMP)
        # Default fallback
        if not self._attr_supported_color_modes:
            self._attr_supported_color_modes.add(ColorMode.RGB)

        # Use highest-capability mode as default
        if ColorMode.RGB in self._attr_supported_color_modes:
            self._attr_color_mode = ColorMode.RGB
        elif ColorMode.HS in self._attr_supported_color_modes:
            self._attr_color_mode = ColorMode.HS
        else:
            self._attr_color_mode = ColorMode.COLOR_TEMP

        # State placeholders
        self._attr_is_on: bool = True
        self._attr_rgb_color: Optional[tuple[int, int, int]] = None
        self._attr_hs_color: Optional[tuple[float, float]] = None
        self._attr_color_temp_kelvin: Optional[int] = None
        self._attr_brightness: Optional[int] = None

        self._state: dict = {}

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": MANUFACTURER,
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_DEVICE_UPDATED}_{self._device_id}",
                self._handle_coordinator_update,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update state from coordinator data."""
        from .coordinator import SmartHQCoordinator
        bucket = self.hass.data[DOMAIN][self._entry.entry_id]
        coordinator: SmartHQCoordinator = bucket["coordinator"]
        dev_data = coordinator.data.get(self._device_id, {})
        services = get_device_services(coordinator.data, self._device_id)
        for svc in services:
            if (svc.get("id") or svc.get("serviceId")) == self._service_id:
                self._state = svc.get("state") or {}
                self._update_from_state()
                break
        self.async_write_ha_state()

    def _update_from_state(self) -> None:
        """Parse state dict into HA light attributes."""
        st = self._state

        # RGB hex → tuple
        rgb_hex = st.get("rgb") or st.get("rgbCalculated")
        if rgb_hex and isinstance(rgb_hex, str) and rgb_hex.startswith("#") and len(rgb_hex) == 7:
            try:
                r = int(rgb_hex[1:3], 16)
                g = int(rgb_hex[3:5], 16)
                b = int(rgb_hex[5:7], 16)
                self._attr_rgb_color = (r, g, b)
                self._attr_is_on = any([r, g, b])
            except ValueError:
                pass

        # RGB intensity components
        if "red" in st and "green" in st and "blue" in st:
            try:
                r = int(st["red"])
                g = int(st["green"])
                b = int(st["blue"])
                self._attr_rgb_color = (r, g, b)
                self._attr_is_on = any([r, g, b])
            except (TypeError, ValueError):
                pass
            # intensity → brightness (0-100 → 0-255)
            if "intensity" in st:
                try:
                    self._attr_brightness = round(int(st["intensity"]) * 255 / 100)
                except (TypeError, ValueError):
                    pass

        # HSB
        hsb = st.get("hsb") or st.get("hsbCalculated")
        if isinstance(hsb, dict):
            hue = hsb.get("hue", 0.0)
            sat = hsb.get("saturation", 0.0)
            bri = hsb.get("brightness", 0.0)
            self._attr_hs_color = (float(hue), float(sat) * 100.0)
            self._attr_brightness = round(float(bri) * 255)
            self._attr_is_on = bri > 0

        # Whiteness (color temperature in Kelvin)
        kelvin = st.get("whitenessTemperatureKelvin") or st.get("whitenessTemperatureKelvinCalculated")
        if kelvin is not None:
            try:
                self._attr_color_temp_kelvin = int(kelvin)
            except (TypeError, ValueError):
                pass

        # disabled flag
        if st.get("disabled") is True:
            self._attr_is_on = False

    @property
    def extra_state_attributes(self) -> dict:
        return {"raw_state": self._state}

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self._controllable or not self._ws:
            return

        command: dict[str, Any] = {}

        # RGB
        if ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            command["rgb"] = f"#{r:02X}{g:02X}{b:02X}"

        # Color temperature (Kelvin)
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            command["whitenessTemperatureKelvin"] = kwargs[ATTR_COLOR_TEMP_KELVIN]

        # Brightness only → adjust intensity field
        elif ATTR_BRIGHTNESS in kwargs:
            bri = kwargs[ATTR_BRIGHTNESS]
            if self._attr_rgb_color:
                r, g, b = self._attr_rgb_color
                command["rgb"] = f"#{r:02X}{g:02X}{b:02X}"
                command["intensity"] = round(bri * 100 / 255)

        if not command:
            # No specific color arg — keep current color
            if self._attr_rgb_color:
                r, g, b = self._attr_rgb_color
                command["rgb"] = f"#{r:02X}{g:02X}{b:02X}"

        await self._ws.async_set_color(
            device_id=self._device_id,
            service_id=self._service_id,
            **command,
        )
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off: set rgb to #000000."""
        if not self._controllable or not self._ws:
            return
        await self._ws.async_set_color(
            device_id=self._device_id,
            service_id=self._service_id,
            rgb="#000000",
        )
        self._attr_is_on = False
        self.async_write_ha_state()


class SmartHQAccentLight(LightEntity):
    """Light entity for cloud.smarthq.service.cooking.prorange.accent.light.

    State:
      brightness         : INTEGER
      colorTemperature   : INTEGER
      customColorActive  : BOOLEAN
      customColorCode    : STRING
    Command: cloud.smarthq.command.cooking.prorange.accent.light.set
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_color_mode = ColorMode.COLOR_TEMP
    _attr_supported_color_modes: set[ColorMode] = {ColorMode.COLOR_TEMP, ColorMode.BRIGHTNESS}

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        service_id: str,
        device_name: str,
        unique_id: str,
        config: dict,
        controllable: bool,
        ws: Any,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._device_name = device_name
        self._config = config
        self._controllable = controllable
        self._ws = ws

        self._attr_unique_id = unique_id
        self._attr_name = f"{device_name} Accent Light"

        # Min/max from config
        bri_min = config.get("brightnessMin", 0)
        bri_max = config.get("brightnessMax", 100)
        ct_min = config.get("colorTemperatureMin")
        ct_max = config.get("colorTemperatureMax")

        if ct_min and ct_max:
            self._attr_min_color_temp_kelvin = int(ct_min)
            self._attr_max_color_temp_kelvin = int(ct_max)

        self._attr_is_on: bool = False
        self._attr_brightness: Optional[int] = None
        self._attr_color_temp_kelvin: Optional[int] = None
        self._state: dict = {}

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": MANUFACTURER,
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_DEVICE_UPDATED}_{self._device_id}",
                self._handle_coordinator_update,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        from .coordinator import SmartHQCoordinator
        bucket = self.hass.data[DOMAIN][self._entry.entry_id]
        coordinator: SmartHQCoordinator = bucket["coordinator"]
        services = get_device_services(coordinator.data, self._device_id)
        for svc in services:
            if (svc.get("id") or svc.get("serviceId")) == self._service_id:
                self._state = svc.get("state") or {}
                self._update_from_state()
                break
        self.async_write_ha_state()

    def _update_from_state(self) -> None:
        st = self._state
        bri = st.get("brightness")
        if bri is not None:
            try:
                self._attr_brightness = round(int(bri) * 255 / 100)
                self._attr_is_on = int(bri) > 0
            except (TypeError, ValueError):
                pass

        ct = st.get("colorTemperature")
        if ct is not None:
            try:
                self._attr_color_temp_kelvin = int(ct)
            except (TypeError, ValueError):
                pass

        # customColorActive can mean it's "on"
        if st.get("customColorActive") is True:
            self._attr_is_on = True

    @property
    def extra_state_attributes(self) -> dict:
        attrs: dict = {"raw_state": self._state}
        if self._state.get("customColorCode"):
            attrs["custom_color_code"] = self._state["customColorCode"]
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self._controllable or not self._ws:
            return

        params: dict[str, Any] = {}

        if ATTR_BRIGHTNESS in kwargs:
            params["brightness"] = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            params["colorTemperature"] = kwargs[ATTR_COLOR_TEMP_KELVIN]

        # Default: turn on at full brightness if no params given
        if not params:
            params["brightness"] = 100

        await self._ws.async_set_accent_light(
            device_id=self._device_id,
            service_id=self._service_id,
            **params,
        )
        self._attr_is_on = True
        if "brightness" in params:
            self._attr_brightness = round(params["brightness"] * 255 / 100)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if not self._controllable or not self._ws:
            return
        await self._ws.async_set_accent_light(
            device_id=self._device_id,
            service_id=self._service_id,
            brightness=0,
        )
        self._attr_is_on = False
        self._attr_brightness = 0
        self.async_write_ha_state()
