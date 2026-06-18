# /config/custom_components/smarthq/config_flow.py
from __future__ import annotations

import logging
from typing import Any, Dict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow, selector

from .const import (
    DOMAIN,
    DEFAULT_OPTIONS,
    OPTION_SHOW_ALT_TEMPS,
    OPTION_AUTO_EXPOSE,
    OPTION_ENABLE_TELEGRAM,
    OPTION_CONVERSATION_AGENT,
    OPTION_TELEGRAM_CHAT_IDS,
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

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "SmartHQOptionsFlowHandler":
        """Return the options flow handler."""
        return SmartHQOptionsFlowHandler(config_entry)

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
            # Normalize the optional agent selector (absent => empty string).
            data = dict(user_input)
            data.setdefault(OPTION_CONVERSATION_AGENT, "")
            return self.async_create_entry(title="", data=data)

        opts = {**DEFAULT_OPTIONS, **(self.entry.options or {})}
        schema_dict: Dict[Any, Any] = {
            vol.Optional(
                OPTION_SHOW_ALT_TEMPS,
                default=opts[OPTION_SHOW_ALT_TEMPS],
            ): bool,
            vol.Optional(
                OPTION_AUTO_EXPOSE,
                default=opts[OPTION_AUTO_EXPOSE],
            ): bool,
            vol.Optional(
                OPTION_ENABLE_TELEGRAM,
                default=opts[OPTION_ENABLE_TELEGRAM],
            ): bool,
        }
        # The conversation-agent selector is optional; default only if set.
        agent_default = opts.get(OPTION_CONVERSATION_AGENT) or ""
        agent_key = (
            vol.Optional(OPTION_CONVERSATION_AGENT, default=agent_default)
            if agent_default
            else vol.Optional(OPTION_CONVERSATION_AGENT)
        )
        schema_dict[agent_key] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="conversation")
        )
        schema_dict[
            vol.Optional(
                OPTION_TELEGRAM_CHAT_IDS,
                default=opts[OPTION_TELEGRAM_CHAT_IDS],
            )
        ] = str

        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema_dict)
        )
