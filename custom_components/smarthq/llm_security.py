"""Security helpers for SmartHQ LLM tools.

Defense-in-depth controls applied by every SmartHQ LLM tool BEFORE any action
is taken. These checks are intentionally simple, deterministic, and independent
of the LLM so they cannot be reasoned around by prompt injection.

Controls implemented here:
- Sensitive-domain block: refuse to act on locks / alarm / camera entities.
- Dangerous-action confirmation: actions touching cooking appliances require a
  short-lived one-time confirmation token before they execute.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Final

from homeassistant.core import HomeAssistant, split_entity_id

from .const import LLM_BLOCKED_DOMAINS, LLM_DANGEROUS_KEYWORDS

# How long a pending confirmation token stays valid.
CONFIRMATION_TTL_SECONDS: Final = 120.0


def is_entity_blocked(entity_id: str) -> bool:
    """Return True if the entity belongs to a domain that must never be controlled."""
    try:
        domain = split_entity_id(entity_id)[0]
    except ValueError:
        return True  # malformed entity id -> block by default
    return domain in LLM_BLOCKED_DOMAINS


def is_dangerous_target(*texts: str) -> bool:
    """Return True if any provided text refers to a safety-sensitive appliance.

    Used to decide whether a control action needs explicit confirmation.
    """
    haystack = " ".join(t for t in texts if t).lower()
    return any(keyword in haystack for keyword in LLM_DANGEROUS_KEYWORDS)


@dataclass(slots=True)
class _PendingConfirmation:
    """A control action awaiting user confirmation."""

    token: str
    summary: str
    created_at: float = field(default_factory=time.monotonic)

    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > CONFIRMATION_TTL_SECONDS


class ConfirmationStore:
    """In-memory store of pending dangerous-action confirmations.

    Tokens are single-use and time-limited. The store is per-HA-instance and
    not persisted, so a restart clears all pending confirmations (fail-safe).
    """

    def __init__(self) -> None:
        self._pending: dict[str, _PendingConfirmation] = {}

    def _purge_expired(self) -> None:
        expired = [tok for tok, p in self._pending.items() if p.is_expired()]
        for tok in expired:
            self._pending.pop(tok, None)

    def issue(self, token: str, summary: str) -> None:
        """Record a pending confirmation for the given token."""
        self._purge_expired()
        self._pending[token] = _PendingConfirmation(token=token, summary=summary)

    def consume(self, token: str) -> bool:
        """Validate and consume a confirmation token. Returns True if valid."""
        self._purge_expired()
        pending = self._pending.pop(token, None)
        return pending is not None and not pending.is_expired()


def get_confirmation_store(hass: HomeAssistant, domain: str) -> ConfirmationStore:
    """Return the shared ConfirmationStore for this integration, creating it once."""
    root = hass.data.setdefault(domain, {})
    store = root.get("_llm_confirmations")
    if not isinstance(store, ConfirmationStore):
        store = ConfirmationStore()
        root["_llm_confirmations"] = store
    return store
