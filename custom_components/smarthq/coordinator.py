from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .api import SmartHQApi
from .service_registry import get_device_services, get_services_by_type  # noqa: F401

_LOGGER = logging.getLogger(__name__)

_AUTH_ERROR_CODES = ("401", "403", "invalid_grant", "invalid_token", "unauthorized")


def _is_auth_error(err: Exception) -> bool:
    """Return True if the exception indicates an authentication failure."""
    msg = str(err).lower()
    return any(code in msg for code in _AUTH_ERROR_CODES)


class SmartHQCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Keep SmartHQ data fresh (presence / settings / device snapshot)."""

    def __init__(self, hass: HomeAssistant, api: SmartHQApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API."""
        try:
            devices = await self.api.async_list_devices()
        except Exception as err:
            if _is_auth_error(err):
                raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
            _LOGGER.error("Failed to list devices: %s", err)
            raise UpdateFailed(f"Failed to list devices: {err}")

        result = {}
        for dev in devices:
            did = str(dev.get("id") or dev.get("deviceId") or "")
            if not did:
                continue

            try:
                # GET /v2/device/{did} - full response including services
                item = await self.api.async_get_device_item(did)
                
                # Settings
                settings = await self.api.get_device_settings(did)
                
                # Presence (optional)
                try:
                    presence = await self.api.async_get_presence(did)
                except Exception:
                    presence = {}

                result[did] = {
                    "info": {
                        "id": did,
                        "nickname": dev.get("nickname") or dev.get("name"),
                        "model": dev.get("model"),
                        "deviceType": dev.get("deviceType"),
                        "firmwareRevision": dev.get("firmwareRevision"),
                    },
                    "item": item,  # includes services array
                    "settings": settings,
                    "presence": presence,
                }
                
                # ── Diagnostic: dump ALL service types received from Cloud ──
                svc_raw = item.get("services") if isinstance(item, dict) else None
                if isinstance(svc_raw, list):
                    for _svc in svc_raw:
                        if not isinstance(_svc, dict):
                            continue
                        _stype = _svc.get("serviceType", "")
                        _domain = _svc.get("domainType", "")
                        _sid = str(_svc.get("serviceId") or _svc.get("id") or "")
                        _cmds = _svc.get("supportedCommands") or []
                        _state_keys = list((_svc.get("state") or {}).keys())
                        _cfg_keys = list((_svc.get("config") or {}).keys())
                        _LOGGER.warning(
                            "[COORD_SVC_AUDIT] device=%s stype=%s domain=%s sid=%s cmds=%s state_keys=%s cfg_keys=%s",
                            did[:8], _stype, _domain, _sid[:12], _cmds, _state_keys, _cfg_keys,
                        )
                    # Cooking mode services — detailed config/state
                    for _svc in svc_raw:
                        if isinstance(_svc, dict) and "cooking.mode" in str(_svc.get("serviceType", "")):
                            _LOGGER.warning(
                                "[COORD_COOKING_SVC] device=%s domain=%s config=%s state=%s",
                                did[:8],
                                _svc.get("domainType"),
                                _svc.get("config"),
                                _svc.get("state"),
                            )
                # ── end diagnostic ───────────────────────────────────────────

                # ── File-based dump for specific devices ──
                if did.startswith("b6f41982") or did.startswith("5f482f0a") or did.startswith("7d27fcd8") or did.startswith("1bc2476f") or did.startswith("9d2faee3") or True:
                    import json as _json, asyncio as _asyncio
                    _fname = (
                        "/config/smoker_services_dump.json" if did.startswith("b6f41982")
                        else "/config/dryer_services_dump.json" if did.startswith("7d27fcd8")
                        else "/config/washerdryer_services_dump.json" if did.startswith("1bc2476f")
                        else "/config/toasteroven_services_dump.json" if did.startswith("9d2faee3")
                        else "/config/refrigerator_services_dump.json" if did.startswith("a8a7bcac")
                        else "/config/coffeebrewer_services_dump.json"
                    )
                    _tag = (
                        "SMOKER_DUMP" if did.startswith("b6f41982")
                        else "DRYER_DUMP" if did.startswith("7d27fcd8")
                        else "WASHERDRYER_DUMP" if did.startswith("1bc2476f")
                        else "TOASTEROVEN_DUMP" if did.startswith("9d2faee3")
                        else "REFRIGERATOR_DUMP" if did.startswith("a8a7bcac")
                        else "COFFEE_DUMP"
                    )
                    _dump_data = _json.dumps(svc_raw or [], indent=2, default=str)
                    async def _write_dump(fname=_fname, tag=_tag, data=_dump_data, cnt=len(svc_raw or [])):
                        import aiofiles
                        try:
                            async with aiofiles.open(fname, "w") as _f:
                                await _f.write(data)
                            _LOGGER.warning("[%s] Wrote %d services to %s", tag, cnt, fname)
                        except Exception as _e:
                            # fallback: write synchronously in executor
                            try:
                                await self.hass.async_add_executor_job(
                                    lambda: open(fname, "w").write(data)
                                )
                                _LOGGER.warning("[%s] Wrote %d services to %s (executor)", tag, cnt, fname)
                            except Exception as _e2:
                                _LOGGER.error("[%s] Failed: %s", tag, _e2)
                    self.hass.async_create_task(_write_dump())
                # ── Settings dump for smoker + washer/dryer ──
                if did.startswith("b6f41982"):
                    import json as _json3
                    _smoker_settings_dump = _json3.dumps(settings, indent=2, default=str)
                    async def _write_smoker_settings(data=_smoker_settings_dump, cnt=len(settings)):
                        try:
                            with open("/config/smoker_settings_dump.json", "w") as _f:
                                _f.write(data)
                            _LOGGER.warning("[SMOKER_SETTINGS] Wrote %d settings", cnt)
                        except Exception as _e:
                            _LOGGER.error("[SMOKER_SETTINGS] Failed: %s", _e)
                    self.hass.async_create_task(_write_smoker_settings())
                if did.startswith("1bc2476f"):
                    import json as _json2
                    _settings_dump = _json2.dumps(settings, indent=2, default=str)
                    async def _write_settings(data=_settings_dump, cnt=len(settings)):
                        try:
                            with open("/config/washerdryer_settings_dump.json", "w") as _f:
                                _f.write(data)
                            _LOGGER.warning("[WASHERDRYER_SETTINGS] Wrote %d settings", cnt)
                        except Exception as _e:
                            _LOGGER.error("[WASHERDRYER_SETTINGS] Failed: %s", _e)
                    self.hass.async_create_task(_write_settings())
                # ── end settings dump ──

                _LOGGER.debug(
                    "Loaded device %s: services=%d settings=%d",
                    did,
                    len(item.get("services", [])),
                    len(settings)
                )

            except Exception as err:
                _LOGGER.warning("Failed to load device %s: %s", did, err)
                continue

        return result
