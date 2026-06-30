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
