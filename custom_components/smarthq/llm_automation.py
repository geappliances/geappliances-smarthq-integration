"""Persist LLM-generated appliance-completion automations.

This module lets an LLM tool create a *persistent* Home Assistant automation
that runs when a SmartHQ appliance finishes its current cycle/run. The
automation is appended to the instance's ``automations.yaml`` (the same file the
UI automation editor manages) and then reloaded, so it shows up in the UI and
survives restarts.

Writing is done off the event loop (executor), with a backup copy and an atomic
replace, so a malformed write cannot corrupt the existing automations file.
"""
from __future__ import annotations

import logging
import os
import shutil
from typing import Any

import yaml
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

AUTOMATIONS_FILE = "automations.yaml"
_BACKUP_SUFFIX = ".llmbak"


def _load_automations(path: str) -> list[Any]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError("automations.yaml does not contain a list")
    return data


def _save_automations(path: str, data: list[Any]) -> None:
    if os.path.exists(path):
        shutil.copy2(path, path + _BACKUP_SUFFIX)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    os.replace(tmp_path, path)


def build_completion_automation(
    auto_id: str, alias: str, trigger_entity: str, actions: list[Any]
) -> dict[str, Any]:
    """Build a standard HA automation dict triggered by appliance completion."""
    return {
        "id": auto_id,
        "alias": alias,
        "description": "Created automatically from a natural-language request.",
        "triggers": [
            {"platform": "state", "entity_id": trigger_entity, "to": "OFF"}
        ],
        "conditions": [
            {
                "condition": "template",
                "value_template": (
                    "{{ trigger.from_state is not none and "
                    "trigger.from_state.state not in "
                    "['OFF', 'unknown', 'unavailable'] }}"
                ),
            }
        ],
        "actions": actions,
    }


async def async_add_automation(
    hass: HomeAssistant, automation_config: dict[str, Any]
) -> None:
    """Append an automation to automations.yaml and reload automations."""
    path = hass.config.path(AUTOMATIONS_FILE)
    data = await hass.async_add_executor_job(_load_automations, path)

    new_id = automation_config.get("id")
    if any(isinstance(item, dict) and item.get("id") == new_id for item in data):
        raise ValueError(f"An automation with id '{new_id}' already exists")

    data.append(automation_config)
    await hass.async_add_executor_job(_save_automations, path, data)
    await hass.services.async_call("automation", "reload", {}, blocking=True)
    _LOGGER.info("Created automation id=%s alias=%s", new_id, automation_config.get("alias"))
