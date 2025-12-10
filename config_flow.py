# /config/custom_components/smarthq/config_flow.py
from __future__ import annotations

import logging
from typing import Any, Dict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow

from .const import (
    DOMAIN,
    DEFAULT_OPTIONS,
    OPTION_SHOW_ALT_TEMPS,
)

_LOGGER = logging.getLogger(__name__)


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle SmartHQ OAuth2 flow via Application Credentials."""

    DOMAIN = DOMAIN
    VERSION = 1

    @property
    def logger(self) -> logging.Logger:
        """Logger required by AbstractOAuth2FlowHandler."""
        return _LOGGER

    async def async_step_pick_implementation(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle implementation picker - auto-select if existing auth exists."""
        implementations = await config_entry_oauth2_flow.async_get_implementations(
            self.hass, self.DOMAIN
        )
        
        # Auto-select if existing auth is available
        if len(implementations) > 1:
            # Skip "local" (Local application credentials) and use existing auth
            for impl_id, impl in implementations.items():
                if impl_id != "local":  # Skip local credentials
                    _LOGGER.debug(f"Auto-selecting existing auth: {impl_id}")
                    return await self.async_step_auth(
                        user_input={"implementation": impl_id}
                    )
        
        # Show picker if no existing auth
        return await super().async_step_pick_implementation(user_input)

    async def async_oauth_create_entry(self, data: dict) -> FlowResult:
        """Create the config entry after OAuth finishes."""
        # Include initial options
        return self.async_create_entry(title="SmartHQ", data=data, options=DEFAULT_OPTIONS)


class SmartHQOptionsFlowHandler(config_entries.OptionsFlow):
    """Options for SmartHQ integration."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = {**DEFAULT_OPTIONS, **(self.entry.options or {})}
        schema = vol.Schema(
            {
                vol.Optional(
                    OPTION_SHOW_ALT_TEMPS,
                    default=opts[OPTION_SHOW_ALT_TEMPS],
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


async def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> SmartHQOptionsFlowHandler:
    """Return the options flow handler."""
    return SmartHQOptionsFlowHandler(config_entry)
