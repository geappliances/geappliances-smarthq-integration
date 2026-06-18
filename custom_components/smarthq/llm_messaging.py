"""SmartHQ assistant convenience layer.

Two opt-in conveniences so that a user who installs the SmartHQ integration can
talk to their appliances without hand-wiring Assist exposure or a Telegram
automation package:

1. ``async_expose_entry_entities`` exposes the appliances' Home Assistant
   entities to the conversation/Assist assistant.
2. :class:`SmartHQTelegramBridge` listens for ``telegram_text`` events and
   routes the message through a user-selected conversation agent (which has the
   SmartHQ LLM API enabled), then replies via the Telegram bot.

Both features are gated by config-entry options and fail soft: if Home
Assistant lacks the expected helpers or the Telegram integration is not set up,
the rest of the integration keeps working.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Assistant key used by Home Assistant's exposed-entity registry for Assist.
_ASSISTANT_CONVERSATION = "conversation"

# Telegram integration event fired for plain text messages.
_EVENT_TELEGRAM_TEXT = "telegram_text"


def async_expose_entry_entities(hass: HomeAssistant, entry_id: str) -> int:
    """Expose all of a config entry's entities to the Assist assistant.

    Returns the number of entities exposed. Fails soft (returns 0) if the
    exposed-entities helper is unavailable on this Home Assistant version.
    """
    try:
        from homeassistant.components.homeassistant.exposed_entities import (
            async_expose_entity,
        )
    except Exception as err:  # noqa: BLE001 - optional helper
        _LOGGER.debug("[MSG] Entity exposure helper unavailable: %s", err)
        return 0

    ent_reg = er.async_get(hass)
    count = 0
    for ent in er.async_entries_for_config_entry(ent_reg, entry_id):
        try:
            async_expose_entity(
                hass, _ASSISTANT_CONVERSATION, ent.entity_id, True
            )
            count += 1
        except Exception as err:  # noqa: BLE001 - keep exposing the rest
            _LOGGER.debug(
                "[MSG] Could not expose %s: %s", ent.entity_id, err
            )
    if count:
        _LOGGER.info("[MSG] Exposed %d SmartHQ entities to Assist", count)
    return count


def _parse_chat_ids(raw: str) -> set[int]:
    """Parse a comma/space separated list of chat ids into a set of ints."""
    ids: set[int] = set()
    for token in raw.replace(",", " ").split():
        try:
            ids.add(int(token))
        except ValueError:
            _LOGGER.warning("[MSG] Ignoring invalid Telegram chat id: %r", token)
    return ids


class SmartHQTelegramBridge:
    """Route telegram_text messages through a conversation agent and reply."""

    def __init__(
        self,
        hass: HomeAssistant,
        agent_id: str,
        allowed_chat_ids: set[int],
    ) -> None:
        self._hass = hass
        self._agent_id = agent_id
        self._allowed = allowed_chat_ids
        # Per-chat conversation id so multi-turn flows (confirmations) keep
        # their context across messages.
        self._conversation_ids: dict[int, str] = {}
        self._unsub: Callable[[], None] | None = None

    @callback
    def async_start(self) -> None:
        """Begin listening for incoming Telegram text messages."""
        self._unsub = self._hass.bus.async_listen(
            _EVENT_TELEGRAM_TEXT, self._handle_event
        )
        _LOGGER.info(
            "[MSG] Telegram bridge active (agent=%s, chats=%s)",
            self._agent_id,
            sorted(self._allowed) or "ANY",
        )

    @callback
    def async_stop(self) -> None:
        """Stop listening."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    async def _handle_event(self, event: Event) -> None:
        data = event.data or {}
        try:
            chat_id = int(data.get("chat_id"))
        except (TypeError, ValueError):
            return
        text = (data.get("text") or "").strip()
        if not text:
            return
        # Defense in depth: only act on explicitly allow-listed chats.
        if self._allowed and chat_id not in self._allowed:
            _LOGGER.warning(
                "[MSG] Ignoring Telegram message from unlisted chat_id %s",
                chat_id,
            )
            return

        reply = await self._async_converse(chat_id, text)
        await self._async_reply(chat_id, reply)

    async def _async_converse(self, chat_id: int, text: str) -> str:
        """Send text to the conversation agent, returning the spoken reply."""
        from homeassistant.components import conversation
        from homeassistant.core import Context

        try:
            result = await conversation.async_converse(
                self._hass,
                text,
                self._conversation_ids.get(chat_id),
                Context(),
                agent_id=self._agent_id,
            )
        except Exception as err:  # noqa: BLE001 - surface to the user as text
            _LOGGER.exception("[MSG] conversation.async_converse failed")
            return f"Sorry, I could not process that ({err})."

        self._conversation_ids[chat_id] = result.conversation_id
        try:
            return result.response.speech["plain"]["speech"]
        except (AttributeError, KeyError, TypeError):
            return "Sorry, I could not process that."

    async def _async_reply(self, chat_id: int, message: str) -> None:
        """Send a reply back to the originating Telegram chat."""
        if not self._hass.services.has_service("telegram_bot", "send_message"):
            _LOGGER.warning(
                "[MSG] telegram_bot.send_message unavailable; is the Telegram "
                "integration configured?"
            )
            return
        try:
            await self._hass.services.async_call(
                "telegram_bot",
                "send_message",
                {"target": chat_id, "message": message},
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - log and move on
            _LOGGER.exception("[MSG] telegram_bot.send_message failed")
