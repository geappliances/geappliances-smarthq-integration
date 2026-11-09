"""Tests for the SmartHQ light platform."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_RGB_COLOR

from custom_components.smarthq.const import DOMAIN
from custom_components.smarthq.dispatcher import SIGNAL_DEVICE_UPDATED
from custom_components.smarthq.light import (
    COLORSPACE_RGB,
    COLORSPACE_RGB_INTENSITY,
    SmartHQAccentLight,
    SmartHQColorLight,
)

DEVICE = "test-device"
SERVICE = "svc-color"


def _light(color_spaces: list[str], snapshot_state: dict | None = None, rest_state: dict | None = None):
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test-entry"
    coordinator = MagicMock()
    coordinator.data = {DEVICE: {"item": {"services": [{"id": SERVICE, "state": rest_state or {}}]}}}
    store = {DEVICE: {"snapshot": {"services": {SERVICE: snapshot_state}}}} if snapshot_state else {}
    hass.data = {DOMAIN: {"test-entry": {"coordinator": coordinator, "store": store}}}
    ws = MagicMock()
    ws.async_set_color = AsyncMock()
    light = SmartHQColorLight(
        hass=hass,
        entry=entry,
        device_id=DEVICE,
        service_id=SERVICE,
        device_name="Ice Maker",
        unique_id="uid",
        color_spaces=color_spaces,
        controllable=True,
        ws=ws,
    )
    light.async_write_ha_state = MagicMock()
    return light, ws


def test_subscribes_to_the_signal_the_ws_client_sends():
    light, _ = _light([COLORSPACE_RGB_INTENSITY])
    with patch("custom_components.smarthq.light.async_dispatcher_connect") as connect:
        asyncio.run(light.async_added_to_hass())
    assert connect.call_args.args[1] == SIGNAL_DEVICE_UPDATED.format(device_id=DEVICE)


def test_reads_live_snapshot_over_rest_state():
    snapshot = {"intensity": 50, "red": 6, "green": 0, "blue": 255, "rgbCalculated": "#60FF"}
    light, _ = _light([COLORSPACE_RGB_INTENSITY], snapshot_state=snapshot, rest_state={"intensity": 0})
    light._handle_coordinator_update()
    assert light._attr_is_on is True
    assert light._attr_rgb_color == (6, 0, 255)
    assert light._attr_brightness == round(50 * 255 / 100)


def test_intensity_zero_is_off():
    light, _ = _light([COLORSPACE_RGB_INTENSITY], snapshot_state={"intensity": 0, "red": 6, "green": 0, "blue": 255})
    light._handle_coordinator_update()
    assert light._attr_is_on is False
    assert light._attr_rgb_color == (6, 0, 255)


def test_intensity_above_zero_is_on_even_with_black_components():
    light, _ = _light([COLORSPACE_RGB_INTENSITY], snapshot_state={"intensity": 30, "red": 0, "green": 0, "blue": 0})
    light._handle_coordinator_update()
    assert light._attr_is_on is True
    assert light._attr_brightness == round(30 * 255 / 100)


def test_rgb_intensity_turn_on_sends_components():
    light, ws = _light([COLORSPACE_RGB_INTENSITY])
    asyncio.run(light.async_turn_on(**{ATTR_RGB_COLOR: (10, 20, 30), ATTR_BRIGHTNESS: 128}))
    kwargs = ws.async_set_color.call_args.kwargs
    assert "rgb" not in kwargs
    assert (kwargs["red"], kwargs["green"], kwargs["blue"], kwargs["intensity"]) == (10, 20, 30, 50)


def test_rgb_intensity_turn_on_restores_last_intensity():
    light, ws = _light([COLORSPACE_RGB_INTENSITY], snapshot_state={"intensity": 40, "red": 1, "green": 2, "blue": 3})
    light._handle_coordinator_update()
    light._state = {"intensity": 0, "red": 1, "green": 2, "blue": 3}
    light._update_from_state()
    asyncio.run(light.async_turn_on())
    kwargs = ws.async_set_color.call_args.kwargs
    assert (kwargs["red"], kwargs["green"], kwargs["blue"], kwargs["intensity"]) == (1, 2, 3, 40)


def test_rgb_intensity_turn_off_sets_intensity_zero():
    light, ws = _light([COLORSPACE_RGB_INTENSITY], snapshot_state={"intensity": 50, "red": 6, "green": 0, "blue": 255})
    light._handle_coordinator_update()
    asyncio.run(light.async_turn_off())
    kwargs = ws.async_set_color.call_args.kwargs
    assert "rgb" not in kwargs
    assert (kwargs["red"], kwargs["green"], kwargs["blue"], kwargs["intensity"]) == (6, 0, 255, 0)


def test_rgb_devices_still_send_hex():
    light, ws = _light([COLORSPACE_RGB])
    asyncio.run(light.async_turn_on(**{ATTR_RGB_COLOR: (255, 0, 16)}))
    assert ws.async_set_color.call_args.kwargs == {"device_id": DEVICE, "service_id": SERVICE, "rgb": "#FF0010"}
    asyncio.run(light.async_turn_off())
    assert ws.async_set_color.call_args.kwargs["rgb"] == "#000000"


def _accent_light(snapshot_state: dict | None = None, rest_state: dict | None = None):
    light, ws = _light([], snapshot_state=snapshot_state, rest_state=rest_state)
    accent = SmartHQAccentLight(
        hass=light.hass,
        entry=light._entry,
        device_id=DEVICE,
        service_id=SERVICE,
        device_name="Range",
        unique_id="accent-uid",
        config={},
        controllable=True,
        ws=ws,
    )
    accent.async_write_ha_state = MagicMock()
    return accent


def test_accent_light_subscribes_to_the_signal_the_ws_client_sends():
    accent = _accent_light()
    with patch("custom_components.smarthq.light.async_dispatcher_connect") as connect:
        asyncio.run(accent.async_added_to_hass())
    assert connect.call_args.args[1] == SIGNAL_DEVICE_UPDATED.format(device_id=DEVICE)


def test_accent_light_reads_live_snapshot_on_add_and_update():
    accent = _accent_light(snapshot_state={"brightness": 60, "colorTemperature": 3000}, rest_state={"brightness": 0})
    with patch("custom_components.smarthq.light.async_dispatcher_connect"):
        asyncio.run(accent.async_added_to_hass())
    assert accent._attr_is_on is True
    assert accent._attr_brightness == round(60 * 255 / 100)
    assert accent._attr_color_temp_kelvin == 3000

    accent.hass.data[DOMAIN]["test-entry"]["store"][DEVICE]["snapshot"]["services"][SERVICE]["brightness"] = 0
    accent._handle_coordinator_update()
    assert accent._attr_is_on is False
    accent.async_write_ha_state.assert_called()
