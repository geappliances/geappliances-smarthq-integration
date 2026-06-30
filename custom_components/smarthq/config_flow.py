# /config/custom_components/smarthq/config_flow.py
from __future__ import annotations

import logging
from typing import Any, Dict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_REAUTH
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

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Trigger re-authentication when the token is invalid or expired."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show confirmation dialog before re-launching the OAuth flow."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict) -> FlowResult:
        """Create or update the config entry after OAuth finishes."""
        if self.source == SOURCE_REAUTH:
            # Update the existing entry with the new tokens and reload.
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data_updates=data,
            )
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
        # Convenience: if the user has not chosen one yet but exactly one
        # conversation agent exists, pre-select it so they don't have to.
        agent_default = opts.get(OPTION_CONVERSATION_AGENT) or ""
        if not agent_default:
            from .llm_messaging import async_list_conversation_agents

            agents = async_list_conversation_agents(self.hass)
            if len(agents) == 1:
                agent_default = agents[0]
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
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"setup_status": self._setup_status()},
        )

    def _setup_status(self) -> str:
        """Build a short prerequisite checklist shown above the options."""
        from .llm_messaging import async_list_conversation_agents

        agents = async_list_conversation_agents(self.hass)
        has_telegram = any(
            e.domain == "telegram_bot"
            for e in self.hass.config_entries.async_entries()
        )
        agent_line = (
            f"✅ Conversation agent available ({len(agents)} found)."
            if agents
            else "⚠️ No conversation agent found. Add an OpenAI, Google or "
            "other conversation integration first, then return here."
        )
        tg_line = (
            "✅ Telegram bot integration installed."
            if has_telegram
            else "ℹ️ Telegram not installed. Only needed if you enable "
            "Telegram control — add the **Telegram bot** integration."
        )
        return f"{agent_line}\n\n{tg_line}"
