"""Select platform for SmartHQ integration.

Entity registration is driven entirely by coordinator.data[device_id]["item"]["services"].
Live state is read from the WebSocket snapshot store.

Service → entity mapping:
  mode + CMD_MODE_SET + domain NOT in SWITCH_MODE_DOMAINS  → SmartHQModeSelect
  cooking.mode.v1                                           → SmartHQCookingModeSelect
  coffeebrewer.v1 / .v2                                     → SmartHQCoffeeBrewerSelect (×3)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_NAME
from .dispatcher import SIGNAL_DEVICE_UPDATED, SIGNAL_COOK_MODE_CHANGED
from .service_registry import (
    MODE_SERVICE,
    COOKING_MODE_SERVICE,
    COFFEEBREWER_V1_SERVICE,
    COFFEEBREWER_V2_SERVICE,
    LAUNDRY_MODE_SERVICE,
    DISHWASHER_MODE_V1_SERVICE,
    FLEXDISPENSE_SERVICE,
    STAINREMOVAL_SERVICE,
    REMOTECYCLESELECTION_SERVICE,
    DISHDRAWER_MODE_LEGACY_SERVICE,
    DISHWASHER_CUSTOM_CYCLE_SERVICE,
    DISHWASHER_FAVORITES_V1_SERVICE,
    CMD_MODE_SET,
    CMD_LAUNDRY_MODE_SET,
    CMD_DISHWASHER_MODE_SET,
    CMD_FLEXDISPENSE_MODE_SET,
    CMD_STAINREMOVAL_MODE_SET,
    CMD_REMOTECYCLESELECTION_SET,
    CMD_DISHDRAWER_MODE_LEGACY_SET,
    CMD_DISHWASHER_CUSTOM_CYCLE_SET,
    CMD_DISHWASHER_FAVORITES_V1_SET,
    SWITCH_MODE_DOMAINS,
    READONLY_MODE_DOMAINS,
    make_unique_id,
    is_cooking_mode_domain,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------

def _bucket(hass, entry):
    return hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}

def _store(hass, entry):
    return _bucket(hass, entry).get("store") or {}

def _dev_payload(hass, entry, device_id):
    return _store(hass, entry).get(device_id) or {}

def _snapshot_for(hass, entry, device_id):
    return _dev_payload(hass, entry, device_id).get("snapshot") or {}

def _device_info_for(hass, entry, device_id):
    info = _dev_payload(hass, entry, device_id).get("info") or {}
    name = info.get("nickname") or info.get("name") or DEFAULT_NAME
    model = info.get("model") or info.get("deviceType") or ""
    sw_version = info.get("firmwareRevision") or ""
    return {
        "identifiers": {(DOMAIN, device_id)},
        "manufacturer": MANUFACTURER,
        "name": name,
        "model": model,
        "sw_version": sw_version,
    }


def _pretty(tok: str) -> str:
    """Convert a SmartHQ token tail to a human-readable name."""
    return tok.split(".")[-1].replace("_", " ").replace("-", " ").title()


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SmartHQ select entities from coordinator service definitions."""
    bucket = _bucket(hass, entry)
    coordinator = bucket.get("coordinator")
    client = bucket.get("client")

    if not coordinator or not coordinator.data:
        _LOGGER.warning("[SELECT] Coordinator data not available yet")
        return

    entities: List[SelectEntity] = []

    for device_id, device_item in coordinator.data.items():
        item = device_item.get("item") or {}
        services_list = item.get("services") or []
        if not isinstance(services_list, list):
            continue

        info = item.get("info") or {}
        dev_name = info.get("nickname") or info.get("name") or DEFAULT_NAME

        # Track cooking.mode.v1 services grouped by device for virtual aggregation
        cooking_mode_svcs: List[dict] = []
        # Track laundry.mode.v1 services for aggregation into one select per device
        laundry_mode_svcs: List[dict] = []
        # Track dishwasher.mode.v1 services for aggregation into one cycle select
        dishwasher_mode_svcs: List[dict] = []
        # Track dishdrawer.mode.legacy services for aggregation
        dishdrawer_mode_legacy_svcs: List[dict] = []

        for svc in services_list:
            if not isinstance(svc, dict):
                continue

            stype = svc.get("serviceType") or ""
            dom = svc.get("domainType") or ""
            service_id = svc.get("id") or svc.get("serviceId") or ""
            cmds = svc.get("supportedCommands") or []
            cfg = svc.get("config") or {}

            # ── standard mode select ────────────────────────────────────────
            if stype == MODE_SERVICE and CMD_MODE_SET in cmds:
                if dom in SWITCH_MODE_DOMAINS:
                    continue  # handled by switch.py
                if dom in READONLY_MODE_DOMAINS:
                    continue  # read-only, skip
                entities.append(SmartHQModeSelect(
                    hass=hass, entry=entry, client=client,
                    device_id=device_id, service_id=service_id,
                    dev_name=dev_name, dom=dom, cfg=cfg,
                    unique_id=make_unique_id(device_id, service_id, "mode_select"),
                ))

            # ── cooking mode (collect for aggregation) ──────────────────────
            elif stype == COOKING_MODE_SERVICE:
                cooking_mode_svcs.append(svc)

            # ── coffee brewer selects ───────────────────────────────────────
            elif stype in (COFFEEBREWER_V1_SERVICE, COFFEEBREWER_V2_SERVICE):
                for select_type in ("strength", "size", "temperature"):
                    entities.append(SmartHQCoffeeBrewerSelect(
                        hass=hass, entry=entry,
                        device_id=device_id, service_id=service_id,
                        dev_name=dev_name, select_type=select_type,
                        unique_id=make_unique_id(device_id, service_id, f"coffee_{select_type}"),
                    ))

            # ── laundry mode select ───────────────────────────────────────
            elif stype == LAUNDRY_MODE_SERVICE and CMD_LAUNDRY_MODE_SET in cmds:
                laundry_mode_svcs.append(svc)

            # ── dishwasher mode select (collect for aggregation) ──────────────
            elif stype == DISHWASHER_MODE_V1_SERVICE and CMD_DISHWASHER_MODE_SET in cmds:
                dishwasher_mode_svcs.append(svc)

            # ── flexdispense mode select ──────────────────────────────────────
            elif stype == FLEXDISPENSE_SERVICE and CMD_FLEXDISPENSE_MODE_SET in cmds:
                dom_label = dom.split(".")[-1].replace("_", " ").title() if dom else "Flex Dispense"
                entities.append(SmartHQGenericModeSelect(
                    hass=hass, entry=entry, client=client,
                    device_id=device_id, service_id=service_id,
                    dev_name=dev_name, label=f"{dom_label}",
                    command_type=CMD_FLEXDISPENSE_MODE_SET,
                    cfg=cfg,
                    unique_id=make_unique_id(device_id, service_id, "flexdispense_mode"),
                ))

            # ── stainremoval mode select ──────────────────────────────────────
            elif stype == STAINREMOVAL_SERVICE and CMD_STAINREMOVAL_MODE_SET in cmds:
                entities.append(SmartHQGenericModeSelect(
                    hass=hass, entry=entry, client=client,
                    device_id=device_id, service_id=service_id,
                    dev_name=dev_name, label="Stain Removal",
                    command_type=CMD_STAINREMOVAL_MODE_SET,
                    cfg=cfg,
                    unique_id=make_unique_id(device_id, service_id, "stain_removal_mode"),
                ))

            # ── remote cycle selection select ─────────────────────────────────
            elif stype == REMOTECYCLESELECTION_SERVICE and CMD_REMOTECYCLESELECTION_SET in cmds:
                # config.supportedModes → list of LAUNDRY_CYCLE tokens
                entities.append(SmartHQGenericModeSelect(
                    hass=hass, entry=entry, client=client,
                    device_id=device_id, service_id=service_id,
                    dev_name=dev_name, label="Remote Cycle",
                    command_type=CMD_REMOTECYCLESELECTION_SET,
                    cfg=cfg,
                    unique_id=make_unique_id(device_id, service_id, "remote_cycle_select"),
                ))

            # ── dishdrawer.mode.legacy (collect for aggregation) ──────────────
            elif stype == DISHDRAWER_MODE_LEGACY_SERVICE and CMD_DISHDRAWER_MODE_LEGACY_SET in cmds:
                dishdrawer_mode_legacy_svcs.append(svc)

            # ── dishwasher.custom.cycle select ────────────────────────────────
            elif stype == DISHWASHER_CUSTOM_CYCLE_SERVICE and CMD_DISHWASHER_CUSTOM_CYCLE_SET in cmds:
                # config.supportedModes → list of DISHWASHER_MODE_DOMAIN tokens
                entities.append(SmartHQGenericModeSelect(
                    hass=hass, entry=entry, client=client,
                    device_id=device_id, service_id=service_id,
                    dev_name=dev_name, label="Custom Cycle",
                    command_type=CMD_DISHWASHER_CUSTOM_CYCLE_SET,
                    cfg=cfg,
                    unique_id=make_unique_id(device_id, service_id, "dw_custom_cycle"),
                ))

            # ── dishwasher.favorites.v1 select ────────────────────────────────
            elif stype == DISHWASHER_FAVORITES_V1_SERVICE and CMD_DISHWASHER_FAVORITES_V1_SET in cmds:
                entities.append(SmartHQDishwasherFavoritesSelect(
                    hass=hass, entry=entry, client=client,
                    device_id=device_id, service_id=service_id,
                    dev_name=dev_name, cfg=cfg,
                    unique_id=make_unique_id(device_id, service_id, "dw_favorites"),
                ))

        # ── aggregate cooking.mode.v1 services → single cooking mode select ─
        if cooking_mode_svcs:
            # Use the first service id as the representative; collect all cooking domains
            # Covers Smoker (cooking.food.*), Toaster Oven (cooking.bake, cooking.airfry…),
            # Oven (cooking.bake, cooking.broil…) and Microwave (cooking.bake.auto.*).
            food_svcs = [
                s for s in cooking_mode_svcs
                if is_cooking_mode_domain(s.get("domainType") or "")
            ]
            if food_svcs:
                rep = food_svcs[0]
                rep_id = rep.get("id") or rep.get("serviceId") or ""
                all_domains = [s.get("domainType") or "" for s in food_svcs]
                _LOGGER.info(
                    "[COOK_MODE_DOMAINS] device=%s total_cooking_svcs=%d food_svcs=%d domains=%s",
                    device_id[:8], len(cooking_mode_svcs), len(food_svcs),
                    [d.split(".")[-1] for d in all_domains],
                )
                entities.append(SmartHQCookingModeSelect(
                    hass=hass, entry=entry, client=client,
                    device_id=device_id, service_id=rep_id,
                    dev_name=dev_name, all_domains=all_domains,
                    cooking_svcs=food_svcs,
                    unique_id=make_unique_id(device_id, rep_id, "cooking_mode"),
                ))
                # Cook Target Method select (Probe Temp / Time Based)
                # Only create for devices that support probe temperature (e.g. Smoker).
                # Toaster Oven and Oven only use Time Based — no probe select needed.
                has_probe = any(
                    (s.get("config") or {}).get("probeTemperatureSupported")
                    in ("cloud.smarthq.type.parameter.required",
                        "cloud.smarthq.type.parameter.optional",
                        "cloud.smarthq.type.parameter.defaulted")
                    for s in food_svcs
                )
                if has_probe:
                    entities.append(SmartHQCookTargetMethodSelect(
                        hass=hass, entry=entry,
                        device_id=device_id, dev_name=dev_name,
                        unique_id=make_unique_id(device_id, device_id, "cook_target_method"),
                    ))

                # ── Mode-specific parameter selects ──────────────────────────
                # Doneness Level select: created once per device if ANY mode supports it.
                # The select auto-hides/shows options based on the currently pending mode.
                has_doneness = any(
                    (s.get("config") or {}).get("donenessLevelSupported")
                    in ("cloud.smarthq.type.parameter.required",
                        "cloud.smarthq.type.parameter.optional",
                        "cloud.smarthq.type.parameter.defaulted")
                    for s in food_svcs
                )
                if has_doneness:
                    entities.append(SmartHQCookDonenessSelect(
                        hass=hass, entry=entry,
                        device_id=device_id, dev_name=dev_name,
                        cooking_svcs=food_svcs,
                        unique_id=make_unique_id(device_id, device_id, "cook_doneness"),
                    ))

                # Cook Option select (freshness, pizza type…)
                has_option = any(
                    (s.get("config") or {}).get("optionsSupported")
                    in ("cloud.smarthq.type.parameter.required",
                        "cloud.smarthq.type.parameter.optional",
                        "cloud.smarthq.type.parameter.defaulted")
                    for s in food_svcs
                )
                if has_option:
                    entities.append(SmartHQCookOptionSelect(
                        hass=hass, entry=entry,
                        device_id=device_id, dev_name=dev_name,
                        cooking_svcs=food_svcs,
                        unique_id=make_unique_id(device_id, device_id, "cook_option"),
                    ))

                # Numeric Option select (toast/bagel count, pizza size…)
                has_numeric = any(
                    (s.get("config") or {}).get("numericOptionSupported")
                    in ("cloud.smarthq.type.parameter.required",
                        "cloud.smarthq.type.parameter.optional",
                        "cloud.smarthq.type.parameter.defaulted")
                    and "smoke" not in (s.get("config") or {}).get("numericOptionUnits", "").lower()
                    for s in food_svcs
                )
                if has_numeric:
                    entities.append(SmartHQCookNumericOptionSelect(
                        hass=hass, entry=entry,
                        device_id=device_id, dev_name=dev_name,
                        cooking_svcs=food_svcs,
                        unique_id=make_unique_id(device_id, device_id, "cook_numeric_option"),
                    ))

        # ── aggregate laundry.mode.v1 → one select per device ───────────────────────
        if laundry_mode_svcs:
            rep = laundry_mode_svcs[0]
            rep_id = rep.get("id") or rep.get("serviceId") or ""
            rep_dom = rep.get("domainType") or ""
            rep_cfg = rep.get("config") or {}
            entities.append(SmartHQLaundryModeSelect(
                hass=hass, entry=entry, client=client,
                device_id=device_id, service_id=rep_id,
                dev_name=dev_name, dom=rep_dom, cfg=rep_cfg,
                unique_id=make_unique_id(device_id, rep_id, "laundry_mode"),
                all_svcs=laundry_mode_svcs,
            ))

        # ── aggregate dishwasher.mode.v1 → one cycle select per device ─────────
        if dishwasher_mode_svcs:
            entities.append(SmartHQDishwasherModeSelect(
                hass=hass, entry=entry, client=client,
                device_id=device_id, dev_name=dev_name,
                all_svcs=dishwasher_mode_svcs,
                unique_id=make_unique_id(device_id, device_id, "dishwasher_mode"),
            ))

        # ── aggregate dishdrawer.mode.legacy → cycle select + option select ──
        if dishdrawer_mode_legacy_svcs:
            rep = dishdrawer_mode_legacy_svcs[0]
            rep_id = rep.get("id") or rep.get("serviceId") or ""
            # Cycle select: domains are the cycle options
            entities.append(SmartHQDishdrawerModeLegacyCycleSelect(
                hass=hass, entry=entry, client=client,
                device_id=device_id, dev_name=dev_name,
                all_svcs=dishdrawer_mode_legacy_svcs,
                unique_id=make_unique_id(device_id, rep_id, "dishdrawer_cycle"),
            ))
            # Option select: per-representative service (option list from config)
            entities.append(SmartHQDishdrawerModeLegacyOptionSelect(
                hass=hass, entry=entry, client=client,
                device_id=device_id, service_id=rep_id,
                dev_name=dev_name,
                all_svcs=dishdrawer_mode_legacy_svcs,
                cfg=rep.get("config") or {},
                unique_id=make_unique_id(device_id, rep_id, "dishdrawer_option"),
            ))

    _LOGGER.info("[SELECT] Registering %d select entities", len(entities))
    if entities:
        async_add_entities(entities, update_before_add=False)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------

class SmartHQModeSelect(SelectEntity):
    """Select entity for a standard mode service."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass, entry, client, device_id, service_id,
                 dev_name, dom, cfg, unique_id):
        self.hass = hass
        self._entry = entry
        self._client = client
        self._device_id = device_id
        self._service_id = service_id
        self._attr_unique_id = unique_id

        # Label from domain tail
        dom_tail = dom.split(".")[-1].replace("_", " ").title() if dom else "Mode"
        self._attr_name = f"{dev_name} {dom_tail}"
        self._attr_icon = None

        # Build initial options from coordinator config
        self._token_to_name: Dict[str, str] = {}
        self._name_to_token: Dict[str, str] = {}
        self._build_options_from_cfg(cfg)

    def _build_options_from_cfg(self, cfg: dict) -> None:
        modes = cfg.get("supportedModes") or []
        tokens = []
        for m in modes:
            if isinstance(m, str):
                tokens.append(m)
            elif isinstance(m, dict) and "token" in m:
                tokens.append(str(m["token"]))
        self._token_to_name = {t: _pretty(t) for t in tokens}
        self._name_to_token = {v: k for k, v in self._token_to_name.items()}
        self._attr_options = list(self._name_to_token.keys())

    def _refresh_options_from_snapshot(self) -> None:
        """Update options from live WS snapshot (overrides coordinator config)."""
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        cfg = svc.get("config") or {}
        modes = cfg.get("supportedModes") or []
        if not modes:
            return
        tokens = []
        for m in modes:
            if isinstance(m, str):
                tokens.append(m)
            elif isinstance(m, dict) and "token" in m:
                tokens.append(str(m["token"]))
        self._token_to_name = {t: _pretty(t) for t in tokens}
        self._name_to_token = {v: k for k, v in self._token_to_name.items()}
        self._attr_options = list(self._name_to_token.keys())

    @property
    def current_option(self) -> Optional[str]:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        token = svc.get("mode")
        if token is None:
            return None
        return self._token_to_name.get(str(token)) or _pretty(str(token))

    @property
    def available(self) -> bool:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        if svc.get("disabled"):
            return False
        dev_data = _dev_payload(self.hass, self._entry, self._device_id)
        return (dev_data.get("presence") or {}).get("presence") == "ONLINE"

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_select_option(self, option: str) -> None:
        token = self._name_to_token.get(option) or (option if "." in option else None)
        if self._client and token:
            await self._client.async_set_mode(self._device_id, self._service_id, token)
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self) -> None:
        self._refresh_options_from_snapshot()
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# App-level hardcoded defaults for cooking modes where state={} in API.
# Temperatures in °F (API uses Fahrenheit).  Times in minutes.
# ---------------------------------------------------------------------------
_COOKING_MODE_APP_DEFAULTS: Dict[str, Dict] = {
    # domain suffix → defaults
    "cooking.airfry":  {"temp_f": 401, "time_min": 20},   # 205°C / 20 min
    "cooking.bake":    {"temp_f": 347, "time_min": 10},   # 175°C / 10 min
    "cooking.roast":   {"temp_f": 347, "time_min": 50},   # 175°C / 50 min
    "cooking.reheat":  {"temp_f": 311, "time_min": 61},   # 155°C / 61 min
    "cooking.warm":    {"temp_f": 176, "time_min": 58},   # 80°C  / 58 min
    "cooking.cake":    {"temp_f": 347, "time_min": 20},   # 175°C / 20 min (app default)
    # Cookie: API temp (360°F/180°C) is kept; option=frozen, time=16 min (frozen default)
    "cooking.cookie":  {"time_min": 16, "cook_option": "frozen"},
    # Pizza: API option/doneness kept; size=1 (Small/6-inch) since API returns 0 (invalid)
    "cooking.pizza":   {"numeric_option": 1},
    # Toast / Bagel: API returns numericOptionValue=0 (invalid); use app defaults
    "cooking.toast":   {"numeric_option": 6},
    "cooking.bagel":   {"numeric_option": 2},
}


def _app_defaults_for_domain(domain_token: str) -> Dict:
    """Return app-level hardcoded defaults for a cooking domain token."""
    for suffix, defaults in _COOKING_MODE_APP_DEFAULTS.items():
        if domain_token.endswith(suffix):
            return defaults
    return {}


class SmartHQCookingModeSelect(SelectEntity):
    """Cooking Mode select entity (Brisket, Chicken, etc.).

    Aggregates multiple cooking.mode.v1 food-domain services into a single select.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:chef-hat"

    def __init__(self, hass, entry, client, device_id, service_id,
                 dev_name, all_domains, cooking_svcs, unique_id):
        self.hass = hass
        self._entry = entry
        self._client = client
        self._device_id = device_id
        self._service_id = service_id  # representative service id
        self._cooking_svcs = cooking_svcs  # list of svc dicts for all food domains
        self._attr_unique_id = unique_id
        self._attr_name = f"{dev_name} Cook Mode"

        # Build options from all_domains
        self._domain_to_name: Dict[str, str] = {d: _pretty(d) for d in all_domains if d}
        self._name_to_domain: Dict[str, str] = {v: k for k, v in self._domain_to_name.items()}
        self._attr_options = list(self._name_to_domain.keys())

    def _current_domain(self) -> Optional[str]:
        """Read current active mode from cooking.state.v1 WS snapshot."""
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        for st in (snap.get("services") or {}).values():
            if not isinstance(st, dict):
                continue
            if st.get("serviceType") == "cloud.smarthq.service.cooking.state.v1":
                return str(st.get("mode") or "")
        # Fallback: representative service mode
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        return str(svc.get("mode") or "") or None

    @property
    def current_option(self) -> Optional[str]:
        # Pending selection takes priority
        bucket = _bucket(self.hass, self._entry)
        pending = (bucket.get("pending_cook_modes") or {}).get(self._device_id) or {}
        if pending.get("mode_token"):
            tok = pending["mode_token"]
            return self._domain_to_name.get(tok) or _pretty(tok)
        dom = self._current_domain()
        if dom:
            return self._domain_to_name.get(dom) or _pretty(dom)
        return None

    @property
    def available(self) -> bool:
        """Always available so the user can pre-select a cook mode while the
        device is off.  The select remains visible regardless of runStatus /
        cookingStatus; the device itself will reject the start command if it
        is not ready."""
        return bool(self._cooking_svcs)

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_select_option(self, option: str) -> None:
        """Store selection as pending — sent when user presses the start button.

        Also auto-populates default temp / time / doneness / option / numeric
        values from the service's state (API defaults) so the user immediately
        sees sensible values without having to touch every number/select.
        """
        token = self._name_to_domain.get(option) or (option if "." in option else None)
        if not token:
            return

        bucket = _bucket(self.hass, self._entry)
        bucket.setdefault("pending_cook_modes", {})[self._device_id] = {"mode_token": token}

        # ── Auto-apply defaults from service state ──────────────────────────
        # Find the matching cooking_svc for this domain
        svc_for_token = next(
            (s for s in self._cooking_svcs if s.get("domainType") == token), None
        )
        # Reset pending entirely so stale params from a previous mode don't bleed through
        bucket.setdefault("pending_cook_params", {})[self._device_id] = {}
        pending = bucket["pending_cook_params"][self._device_id]

        if svc_for_token:
            state = svc_for_token.get("state") or {}

            # Cavity temperature default (°F)
            temp_f = state.get("cavityTemperatureFahrenheitDefault") or state.get("cavityTemperatureFahrenheit")
            if temp_f is not None:
                pending["smoker_temp_f"] = int(temp_f)

            # Cook time default (seconds → minutes)
            time_s = state.get("cookTimeInitialDefault") or state.get("cookTimeInitial")
            if time_s:
                pending["cook_time_min"] = max(1, int(time_s) // 60)

            # Doneness level default
            doneness = state.get("donenessLevel")
            if doneness:
                pending["doneness_level"] = doneness

            # Option default (cookie freshness, pizza type…)
            option_val = state.get("option")
            if option_val is not None:
                pending["cook_option"] = option_val

            # Numeric option default (pizza size, toast/bagel count…)
            numeric_val = state.get("numericOptionValueDefault")
            if numeric_val is None:
                numeric_val = state.get("numericOptionValue")
            if numeric_val is not None:
                pending["numeric_option"] = int(numeric_val)

        # ── Apply app-level hardcoded fallbacks (for modes with state={}) ──
        app_def = _app_defaults_for_domain(token)
        if app_def:
            # Temp: only override if not already set from API state
            if pending.get("smoker_temp_f") is None and "temp_f" in app_def:
                pending["smoker_temp_f"] = app_def["temp_f"]
            # Time: override if not set OR if API returned invalid value
            if "time_min" in app_def:
                if pending.get("cook_time_min") is None:
                    pending["cook_time_min"] = app_def["time_min"]
                # Also override cookie time: API has no cookTime in state, app default wins
                elif token.endswith("cooking.cookie"):
                    pending["cook_time_min"] = app_def["time_min"]
            # Cook option: only override if not already set from API state
            if pending.get("cook_option") is None and "cook_option" in app_def:
                pending["cook_option"] = app_def["cook_option"]
            # Numeric option: override if not set or invalid (0 is uninitialized sentinel)
            if "numeric_option" in app_def:
                cur = pending.get("numeric_option")
                if cur is None or cur == 0:
                    pending["numeric_option"] = app_def["numeric_option"]

        if svc_for_token or app_def:
            _LOGGER.info(
                "[COOK_MODE] Pending: %s → %s  defaults: temp=%s°F time=%smin "
                "doneness=%s option=%s numeric=%s",
                option, token,
                pending.get("smoker_temp_f"), pending.get("cook_time_min"),
                pending.get("doneness_level"), pending.get("cook_option"),
                pending.get("numeric_option"),
            )
        else:
            _LOGGER.info("[COOK_MODE] Pending selection: %s → %s", option, token)

        # Notify all param entities (time, temp, doneness, option, quantity) to
        # re-render immediately with the new defaults.
        async_dispatcher_send(
            self.hass,
            SIGNAL_COOK_MODE_CHANGED.format(device_id=self._device_id),
        )
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Cooking mode parameter selects
# These show/hide their options dynamically based on the currently pending mode.
# ---------------------------------------------------------------------------

class _SmartHQCookParamSelectBase(SelectEntity):
    """Base for cooking parameter selects (Doneness / Option / Numeric)."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass, entry, device_id, dev_name, cooking_svcs, unique_id):
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._cooking_svcs = cooking_svcs  # list of svc dicts for all food domains
        self._attr_unique_id = unique_id
        self._attr_options = []

    def _pending_mode_token(self) -> str | None:
        """Return the currently pending cook mode domain token."""
        bucket = _bucket(self.hass, self._entry)
        return (bucket.get("pending_cook_modes") or {}).get(self._device_id, {}).get("mode_token")

    def _svc_for_pending(self) -> dict | None:
        """Return the cooking_svc dict for the currently pending mode, or None."""
        token = self._pending_mode_token()
        if not token:
            return None
        return next((s for s in self._cooking_svcs if s.get("domainType") == token), None)

    def _pending_params(self) -> dict:
        bucket = _bucket(self.hass, self._entry)
        return bucket.setdefault("pending_cook_params", {}).setdefault(self._device_id, {})

    @property
    def available(self) -> bool:
        """Available only when the current pending mode supports this parameter."""
        return bool(self._svc_for_pending() and self._attr_options)

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_COOK_MODE_CHANGED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


class SmartHQCookDonenessSelect(_SmartHQCookParamSelectBase):
    """Doneness Level select (Gooey / Normal / Crunchy, Level 1-8, etc.).

    Options are rebuilt each time the pending cook mode changes.
    """

    _attr_icon = "mdi:chef-hat"

    def __init__(self, hass, entry, device_id, dev_name, cooking_svcs, unique_id):
        super().__init__(hass, entry, device_id, dev_name, cooking_svcs, unique_id)
        self._attr_name = f"{dev_name} Doneness Level"

    def _options_for_svc(self, svc: dict) -> list[str]:
        levels = (svc.get("config") or {}).get("donenessLevelsAvailable") or []
        return [_pretty(lvl) for lvl in levels]

    @property
    def available(self) -> bool:
        svc = self._svc_for_pending()
        if not svc:
            return False
        cfg = svc.get("config") or {}
        return cfg.get("donenessLevelSupported") in (
            "cloud.smarthq.type.parameter.required",
            "cloud.smarthq.type.parameter.optional",
            "cloud.smarthq.type.parameter.defaulted",
        )

    @property
    def options(self) -> list[str]:
        svc = self._svc_for_pending()
        return self._options_for_svc(svc) if svc else []

    @property
    def current_option(self) -> str | None:
        raw = self._pending_params().get("doneness_level")
        if raw:
            return _pretty(raw)
        return None

    async def async_select_option(self, option: str) -> None:
        svc = self._svc_for_pending()
        if not svc:
            return
        levels = (svc.get("config") or {}).get("donenessLevelsAvailable") or []
        # Map display name back to token
        token = next((lvl for lvl in levels if _pretty(lvl) == option), option)
        self._pending_params()["doneness_level"] = token
        _LOGGER.info("[COOK_DONENESS] Set to %s (%s)", option, token)
        self.schedule_update_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


class SmartHQCookOptionSelect(_SmartHQCookParamSelectBase):
    """Cook Option select (fresh / frozen / warm up for Cookie; fresh/normal etc. for Pizza)."""

    _attr_icon = "mdi:list-box-outline"

    def __init__(self, hass, entry, device_id, dev_name, cooking_svcs, unique_id):
        super().__init__(hass, entry, device_id, dev_name, cooking_svcs, unique_id)
        self._attr_name = f"{dev_name} Cook Option"

    @property
    def available(self) -> bool:
        svc = self._svc_for_pending()
        if not svc:
            return False
        cfg = svc.get("config") or {}
        return cfg.get("optionsSupported") in (
            "cloud.smarthq.type.parameter.required",
            "cloud.smarthq.type.parameter.optional",
            "cloud.smarthq.type.parameter.defaulted",
        )

    @property
    def options(self) -> list[str]:
        svc = self._svc_for_pending()
        if not svc:
            return []
        available = (svc.get("config") or {}).get("optionsAvailable") or []
        # These are plain strings like "fresh", "frozen/normal" — title-case them
        return [opt.replace("/", " / ").replace("_", " ").title() for opt in available]

    def _raw_options(self) -> list[str]:
        svc = self._svc_for_pending()
        return ((svc.get("config") or {}).get("optionsAvailable") or []) if svc else []

    @property
    def current_option(self) -> str | None:
        raw = self._pending_params().get("cook_option")
        if raw is not None:
            return raw.replace("/", " / ").replace("_", " ").title()
        return None

    async def async_select_option(self, option: str) -> None:
        # Map display name back to raw API value
        raw_opts = self._raw_options()
        display_opts = [o.replace("/", " / ").replace("_", " ").title() for o in raw_opts]
        try:
            raw = raw_opts[display_opts.index(option)]
        except (ValueError, IndexError):
            raw = option
        self._pending_params()["cook_option"] = raw
        _LOGGER.info("[COOK_OPTION] Set to %s (%s)", option, raw)
        self.schedule_update_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


class SmartHQCookNumericOptionSelect(_SmartHQCookParamSelectBase):
    """Numeric Option select (Toast/Bagel slice count 2-6; Pizza size 1-3).

    Displays human-readable labels ("2 Slices", "Small", …) mapped to integer values.
    """

    _attr_icon = "mdi:numeric"

    # Units → label formatter
    _COUNT_LABEL = "{n} Slices"   # cloud.smarthq.type.numericoption.count
    _SIZE_LABELS = {1: "Small", 2: "Medium", 3: "Large"}  # cloud.smarthq.type.numericoption.size

    def __init__(self, hass, entry, device_id, dev_name, cooking_svcs, unique_id):
        super().__init__(hass, entry, device_id, dev_name, cooking_svcs, unique_id)
        self._attr_name = f"{dev_name} Cook Quantity"

    def _unit_type(self, svc: dict) -> str:
        units = (svc.get("config") or {}).get("numericOptionUnits") or ""
        if "count" in units:
            return "count"
        if "size" in units:
            return "size"
        return "unknown"

    def _make_options(self, svc: dict) -> list[str]:
        cfg = svc.get("config") or {}
        lo = int(cfg.get("numericOptionMinimum") or 1)
        hi = int(cfg.get("numericOptionMaximum") or 1)
        unit = self._unit_type(svc)
        if unit == "count":
            return [self._COUNT_LABEL.format(n=n) for n in range(lo, hi + 1)]
        if unit == "size":
            return [self._SIZE_LABELS.get(n, str(n)) for n in range(lo, hi + 1)]
        return [str(n) for n in range(lo, hi + 1)]

    def _value_for_label(self, svc: dict, label: str) -> int:
        cfg = svc.get("config") or {}
        lo = int(cfg.get("numericOptionMinimum") or 1)
        hi = int(cfg.get("numericOptionMaximum") or 1)
        unit = self._unit_type(svc)
        for n in range(lo, hi + 1):
            if unit == "count" and self._COUNT_LABEL.format(n=n) == label:
                return n
            if unit == "size" and self._SIZE_LABELS.get(n, str(n)) == label:
                return n
            if str(n) == label:
                return n
        return lo

    @property
    def available(self) -> bool:
        svc = self._svc_for_pending()
        if not svc:
            return False
        cfg = svc.get("config") or {}
        supported = cfg.get("numericOptionSupported") in (
            "cloud.smarthq.type.parameter.required",
            "cloud.smarthq.type.parameter.optional",
            "cloud.smarthq.type.parameter.defaulted",
        )
        not_smoke = "smoke" not in (cfg.get("numericOptionUnits") or "").lower()
        return supported and not_smoke

    @property
    def options(self) -> list[str]:
        svc = self._svc_for_pending()
        return self._make_options(svc) if svc else []

    @property
    def current_option(self) -> str | None:
        svc = self._svc_for_pending()
        if not svc:
            return None
        val = self._pending_params().get("numeric_option")
        if val is None:
            return None
        unit = self._unit_type(svc)
        if unit == "count":
            return self._COUNT_LABEL.format(n=int(val))
        if unit == "size":
            return self._SIZE_LABELS.get(int(val), str(val))
        return str(val)

    async def async_select_option(self, option: str) -> None:
        svc = self._svc_for_pending()
        if not svc:
            return
        val = self._value_for_label(svc, option)
        self._pending_params()["numeric_option"] = val
        _LOGGER.info("[COOK_NUMERIC] Set to %s (%s)", option, val)
        self.schedule_update_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


class SmartHQCoffeeBrewerSelect(SelectEntity):
    """Coffee Brewer parameter select (strength / size / temperature)."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    _STRENGTH_OPTIONS = ["Light", "Medium", "Bold"]
    _SIZE_OPTIONS = ["10 Oz", "12 Oz", "14 Oz", "Carafe"]
    _TEMP_OPTIONS = [f"{t}°C" for t in range(85, 96)]

    def __init__(self, hass, entry, device_id, service_id,
                 dev_name, select_type, unique_id):
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._select_type = select_type
        self._attr_unique_id = unique_id

        if select_type == "strength":
            self._attr_name = f"{dev_name} Brew Strength"
            self._attr_options = self._STRENGTH_OPTIONS
            self._attr_icon = "mdi:coffee-maker"
            self._default = "Medium"
        elif select_type == "size":
            self._attr_name = f"{dev_name} Brew Size"
            self._attr_options = self._SIZE_OPTIONS
            self._attr_icon = "mdi:cup"
            self._default = "12 Oz"
        else:  # temperature
            self._attr_name = f"{dev_name} Brew Temperature"
            self._attr_options = self._TEMP_OPTIONS
            self._attr_icon = "mdi:thermometer"
            self._default = "90°C"

    def _settings(self) -> dict:
        bucket = _bucket(self.hass, self._entry)
        settings = bucket.setdefault("coffee_brewer_settings", {})
        return settings.setdefault(self._device_id, {
            "strength": "Medium", "size": "12 Oz", "temperature": "90°C"
        })

    @property
    def current_option(self) -> str:
        return self._settings().get(self._select_type, self._default)

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_select_option(self, option: str) -> None:
        self._settings()[self._select_type] = option
        _LOGGER.info("[COFFEE] Set %s → %s", self._select_type, option)
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Laundry Mode Select
# ---------------------------------------------------------------------------

# Human-readable labels for laundry cycle tokens (tail → label)
_LAUNDRY_CYCLE_LABELS: Dict[str, str] = {
    "activewear": "Active Wear", "adaptivemysettings": "Adaptive Settings",
    "allergen": "Allergen", "antibacterial": "Antibacterial",
    "assistant": "Laundry Assistant", "autodampdry": "Auto Damp Dry",
    "autodry": "Auto Dry", "autoextradry": "Auto Extra Dry",
    "babycare": "Baby Care", "basketclean": "Basket Clean",
    "bulkybedding": "Bulky Bedding", "bulkyitems": "Bulky Items",
    "casuals": "Casuals", "coldwash": "Cold Wash", "colors": "Colors",
    "coolair": "Cool Air", "cottons": "Cottons", "darks": "Dark Colors",
    "deepclean": "Deep Clean", "delicates": "Delicates", "denim": "Denim",
    "dewrinkle": "DeWrinkle", "down": "Down", "drainandspin": "Drain and Spin",
    "drumclean": "Drum Clean", "durable": "Durable", "easycare": "Easy Care",
    "eco": "Eco", "energysaver": "Energy Saver", "everyday": "Everyday",
    "express": "Express", "freshen": "Freshen", "handwash": "Hand Wash",
    "heavy": "Heavy", "heavyduty": "Heavy Duty", "hotwash": "Hot Wash",
    "hygiene": "Hygiene", "jeans": "Jeans", "light": "Light",
    "mix": "Mix", "mixed": "Mixed", "normal": "Normal",
    "outdoor": "Outdoor", "outerwear": "Outerwear", "permpress": "Perm Press",
    "pethair": "Pet Hair", "powerclean": "Power Clean", "powersteam": "Power Steam",
    "quickcycle": "Quick Cycle", "quickdry": "Quick Dry", "quickwash": "Quick Wash",
    "rackdry": "Rack Dry", "refresh": "Refresh", "rinseandspin": "Rinse and Spin",
    "sanitize": "Sanitize", "sanitizesteam": "Sanitize Steam",
    "selfclean": "Self Clean", "sheets": "Sheets", "shirts": "Shirts",
    "silk": "Silk", "sneakers": "Sneakers", "soak": "Soak",
    "speeddry": "Speed Dry", "speedwash": "Speed Wash", "spinonly": "Spin Only",
    "sports": "Sports", "stainremoval": "Stain Removal",
    "steamfresh": "Steam Fresh", "steamnormal": "Steam Normal",
    "steamrefresh": "Steam Refresh", "steamsanitize": "Steam Sanitize",
    "synthetics": "Synthetics", "timeddry": "Timed Dry", "towels": "Towels",
    "tubclean": "Tub Clean", "ultradelicate": "Ultra Delicate",
    "warmwash": "Warm Wash", "whites": "Whites", "wool": "Wool",
}


def _laundry_cycle_label(token: str) -> str:
    """Return a human-readable label for a LAUNDRY_CYCLE token."""
    tail = token.split(".")[-1]
    return _LAUNDRY_CYCLE_LABELS.get(tail, tail.replace("-", " ").replace("_", " ").title())


class SmartHQLaundryModeSelect(SelectEntity):
    """Select entity for laundry.mode.v1 — cycle / option selection.

    Each laundry.mode.v1 service represents one *mode* (e.g. jeans, cottons).
    The domain tail is used as the option label.  When selected the
    cloud.smarthq.command.laundry.mode.v1.set command is sent via the WS client.

    Note: laundry.mode.v1 services list one domain per service (e.g.
    cloud.smarthq.domain.laundry.jeans).  A device will have many such
    services — we aggregate them into a single "Laundry Cycle" select by
    grouping per device and using the first service_id as the representative
    key.  The discovery loop therefore creates **one** entity per device
    (see async_setup_entry aggregation below).
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:washing-machine"

    def __init__(
        self,
        hass,
        entry,
        client,
        device_id: str,
        service_id: str,          # representative service id
        dev_name: str,
        dom: str,                 # representative domain (not critical)
        cfg: dict,
        unique_id: str,
        all_svcs: Optional[List[dict]] = None,  # all laundry.mode.v1 svcs for this device
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._client = client
        self._device_id = device_id
        self._service_id = service_id
        self._attr_unique_id = unique_id
        self._attr_name = f"{dev_name} Laundry Cycle"
        self._all_svcs: List[dict] = all_svcs or []

        # Optimistic: set when user picks an option; cleared when WS confirms.
        self._optimistic_option: Optional[str] = None

        # domain → service_id mapping for sending the correct command
        self._domain_to_svc: Dict[str, str] = {}
        # option label → domain token
        self._label_to_domain: Dict[str, str] = {}
        self._domain_to_label: Dict[str, str] = {}
        self._build_options()

    def _build_options(self) -> None:
        """Build the domain ↔ label maps from the coordinator-provided svcs."""
        self._domain_to_svc = {}
        self._label_to_domain = {}
        self._domain_to_label = {}

        for svc in self._all_svcs:
            dom = svc.get("domainType") or ""
            svc_id = svc.get("id") or svc.get("serviceId") or ""
            if not dom or not svc_id:
                continue
            label = _laundry_cycle_label(dom)
            self._domain_to_svc[dom] = svc_id
            self._domain_to_label[dom] = label
            self._label_to_domain[label] = dom

        self._attr_options = sorted(self._label_to_domain.keys())

    @property
    def current_option(self) -> Optional[str]:
        """Return the label of the currently active cycle.

        Priority:
          1. Optimistic value (set immediately when user selects; cleared on WS update)
          2. laundry.state.v1 "cycle" field from WS snapshot
          3. disabled=False heuristic from service states
        """
        # 1. Optimistic — show immediately after user selection
        if self._optimistic_option is not None:
            return self._optimistic_option

        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        services = snap.get("services") or {}

        # 2. Prefer the active domain from laundry.state.v1 "cycle" field
        for svc_state in services.values():
            if not isinstance(svc_state, dict):
                continue
            cycle_token = svc_state.get("cycle")
            if cycle_token and isinstance(cycle_token, str):
                # Find matching domain
                for dom in self._domain_to_label:
                    if dom.split(".")[-1] == cycle_token.split(".")[-1]:
                        return self._domain_to_label[dom]
                # Fallback: return tail label directly
                return _laundry_cycle_label(cycle_token)

        # 3. Fallback: find which mode service has disabled=False
        for svc in self._all_svcs:
            svc_id = svc.get("id") or svc.get("serviceId") or ""
            svc_state = services.get(svc_id) or {}
            if svc_state.get("disabled") is False:
                dom = svc.get("domainType") or ""
                return self._domain_to_label.get(dom)

        return None

    @property
    def available(self) -> bool:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        # Entity is available if device is reachable (presence check optional)
        return bool(snap)

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_select_option(self, option: str) -> None:
        """Send laundry.mode.v1.set command for the chosen cycle."""
        domain = self._label_to_domain.get(option)
        if not domain:
            _LOGGER.warning("[LAUNDRY_MODE] Unknown option: %s", option)
            return

        # Optimistic update — show selected option instantly in UI
        self._optimistic_option = option
        self.async_write_ha_state()

        svc_id = self._domain_to_svc.get(domain) or self._service_id
        if self._client:
            await self._client.async_set_laundry_mode(
                self._device_id, svc_id, domain
            )
        else:
            _LOGGER.warning("[LAUNDRY_MODE] No client available to send command")
            self._optimistic_option = None
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self) -> None:
        # Clear optimistic state — WS has confirmed the real state
        self._optimistic_option = None
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# dishwasher.mode.v1 cycle select
# ---------------------------------------------------------------------------

class SmartHQDishwasherModeSelect(SelectEntity):
    """Select entity for dishwasher cycle — aggregates all dishwasher.mode.v1 services."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:dishwasher"

    def __init__(self, hass, entry, client, device_id, dev_name, all_svcs, unique_id):
        self.hass = hass
        self._entry = entry
        self._client = client
        self._device_id = device_id
        self._attr_name = f"{dev_name} Dishwasher Cycle"
        self._attr_unique_id = unique_id

        # Build option → (service_id, domain) map from all dishwasher.mode.v1 services
        self._label_to_svc: dict[str, tuple[str, str]] = {}
        for svc in all_svcs:
            dom = svc.get("domainType") or ""
            svc_id = svc.get("id") or svc.get("serviceId") or ""
            label = _pretty(dom)
            if label and svc_id:
                self._label_to_svc[label] = (svc_id, dom)

        self._attr_options = sorted(self._label_to_svc.keys())
        # Use first service for state reading fallback
        first = all_svcs[0] if all_svcs else {}
        self._rep_service_id = first.get("id") or first.get("serviceId") or ""
        self._all_svcs = all_svcs

    def _get_dishwasher_state(self) -> dict:
        """Read dishwasher.state.v1 snapshot for current mode."""
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        for svc_state in (snap.get("services") or {}).values():
            if isinstance(svc_state, dict) and "mode" in svc_state:
                return svc_state
        return {}

    @property
    def current_option(self) -> str | None:
        st = self._get_dishwasher_state()
        mode = st.get("mode")
        if not mode:
            return None
        label = _pretty(mode)
        return label if label in self._attr_options else None

    @property
    def available(self) -> bool:
        st = _dev_payload(self.hass, self._entry, self._device_id)
        disabled = any(
            (s.get("state") or {}).get("disabled", False)
            for s in self._all_svcs
        )
        return bool(self._attr_options) and not disabled

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_select_option(self, option: str) -> None:
        result = self._label_to_svc.get(option)
        if not result:
            _LOGGER.warning("[DISHWASHER_MODE] Unknown option: %s", option)
            return
        svc_id, domain = result
        if self._client:
            await self._client.async_set_dishwasher_mode(self._device_id, svc_id, domain)
        else:
            _LOGGER.warning("[DISHWASHER_MODE] No client available")
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


class SmartHQGenericModeSelect(SelectEntity):
    """Generic select for services that expose a 'mode' state with a set command.

    Covers services like flexdispense and stainremoval where:
      - state.mode holds the current token
      - config.supportedModes lists valid tokens
      - command has {commandType, mode}
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass, entry, client, device_id, service_id,
                 dev_name, label, command_type, cfg, unique_id):
        self.hass = hass
        self._entry = entry
        self._client = client
        self._device_id = device_id
        self._service_id = service_id
        self._command_type = command_type
        self._attr_unique_id = unique_id
        self._attr_name = f"{dev_name} {label}"

        self._token_to_name: Dict[str, str] = {}
        self._name_to_token: Dict[str, str] = {}
        self._build_options_from_cfg(cfg)

    def _build_options_from_cfg(self, cfg: dict) -> None:
        modes = cfg.get("supportedModes") or []
        tokens = [m if isinstance(m, str) else str(m.get("token", "")) for m in modes if m]
        self._token_to_name = {t: _pretty(t) for t in tokens if t}
        self._name_to_token = {v: k for k, v in self._token_to_name.items()}
        self._attr_options = list(self._name_to_token.keys())

    def _refresh_options(self) -> None:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        cfg = svc.get("config") or {}
        modes = cfg.get("supportedModes") or []
        if modes:
            tokens = [m if isinstance(m, str) else str(m.get("token", "")) for m in modes if m]
            self._token_to_name = {t: _pretty(t) for t in tokens if t}
            self._name_to_token = {v: k for k, v in self._token_to_name.items()}
            self._attr_options = list(self._name_to_token.keys())

    @property
    def current_option(self) -> Optional[str]:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        token = svc.get("mode")
        if token is None:
            return None
        return self._token_to_name.get(str(token)) or _pretty(str(token))

    @property
    def available(self) -> bool:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        return not svc.get("disabled", False)

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_select_option(self, option: str) -> None:
        token = self._name_to_token.get(option) or (option if "." in option else None)
        if self._client and token:
            await self._client.async_set_generic_mode(
                self._device_id, self._service_id,
                self._command_type, token,
            )
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self) -> None:
        self._refresh_options()
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Dishdrawer Mode Legacy selects
# ---------------------------------------------------------------------------

# Human-readable labels for DISHWASHER_MODE_DOMAIN tails
_DISHDRAWER_CYCLE_LABELS: Dict[str, str] = {
    "auto": "Auto", "autosense": "Auto Sense", "autowash": "Auto Wash",
    "babycare": "Baby Care", "china": "China", "cookware": "Cookware",
    "crystal": "Crystal", "custom": "Custom", "delicate": "Delicate",
    "eco": "Eco", "everyday": "Everyday", "express": "Express",
    "gentle": "Gentle", "glass": "Glass", "heavy": "Heavy",
    "heavyduty": "Heavy Duty", "hydrosave": "HydroSave", "hygiene": "Hygiene",
    "intense": "Intense", "light": "Light", "medium": "Medium",
    "normal": "Normal", "plus": "Plus", "pots": "Pots",
    "preprinse": "Pre-Rinse", "quick": "Quick", "quiet": "Quiet",
    "quiet2": "Quiet 2", "rinse": "Rinse", "smart": "Smart",
    "steam": "Steam", "timesaver": "Time Saver", "unknown": "Unknown",
}

# Human-readable labels for DISHDRAWER_MODE_LEGACY_OPTION tails
_DISHDRAWER_OPTION_LABELS: Dict[str, str] = {
    "none": "None",
    "fast": "Fast",
    "sanitize": "Sanitize",
    "ultra.dry": "Ultra Dry",
}


def _dishdrawer_cycle_label(domain: str) -> str:
    tail = domain.split(".")[-1]
    return _DISHDRAWER_CYCLE_LABELS.get(tail, tail.replace("-", " ").replace("_", " ").title())


def _dishdrawer_option_label(token: str) -> str:
    tail = ".".join(token.split(".")[-2:]) if token.count(".") >= 2 else token.split(".")[-1]
    return _DISHDRAWER_OPTION_LABELS.get(tail, _pretty(token))


class SmartHQDishdrawerModeLegacyCycleSelect(SelectEntity):
    """Select entity for dishdrawer cycle (aggregates all dishdrawer.mode.legacy services).

    Each dishdrawer.mode.legacy service represents one cycle (domainType = cycle).
    Selecting a cycle sends cloud.smarthq.command.dishdrawer.mode.legacy.set with
    the domain as the 'mode' field. The dishdrawerModeLegacyOption is taken from
    the companion SmartHQDishdrawerModeLegacyOptionSelect entity via the HA store.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:dishwasher"

    def __init__(self, hass, entry, client, device_id, dev_name, all_svcs, unique_id):
        self.hass = hass
        self._entry = entry
        self._client = client
        self._device_id = device_id
        self._attr_unique_id = unique_id
        self._attr_name = f"{dev_name} Dishdrawer Cycle"
        self._all_svcs = all_svcs

        # domain → service_id map for sending the correct command
        self._domain_to_svc: Dict[str, str] = {}
        self._label_to_domain: Dict[str, str] = {}
        self._domain_to_label: Dict[str, str] = {}
        self._build_options()

    def _build_options(self) -> None:
        self._domain_to_svc = {}
        self._label_to_domain = {}
        self._domain_to_label = {}
        for svc in self._all_svcs:
            dom = svc.get("domainType") or ""
            svc_id = svc.get("id") or svc.get("serviceId") or ""
            if not dom or not svc_id:
                continue
            label = _dishdrawer_cycle_label(dom)
            self._domain_to_svc[dom] = svc_id
            self._domain_to_label[dom] = label
            self._label_to_domain[label] = dom
        self._attr_options = sorted(self._label_to_domain.keys())

    def _pending(self) -> dict:
        """Read the shared pending store for this device."""
        bucket = _bucket(self.hass, self._entry)
        return (bucket.get("dishdrawer_pending") or {}).get(self._device_id, {})

    @property
    def current_option(self) -> Optional[str]:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        services = snap.get("services") or {}
        # Active cycle = the service whose disabled == False
        for svc in self._all_svcs:
            svc_id = svc.get("id") or svc.get("serviceId") or ""
            svc_state = services.get(svc_id) or {}
            if svc_state.get("disabled") is False:
                dom = svc.get("domainType") or ""
                return self._domain_to_label.get(dom)
        return None

    @property
    def available(self) -> bool:
        return bool(_snapshot_for(self.hass, self._entry, self._device_id))

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_select_option(self, option: str) -> None:
        domain = self._label_to_domain.get(option)
        if not domain:
            _LOGGER.warning("[DISHDRAWER_CYCLE] Unknown option: %s", option)
            return
        svc_id = self._domain_to_svc.get(domain, "")
        pending = self._pending()
        option_token = pending.get(
            "option_token",
            "cloud.smarthq.type.dishdrawer.mode.legacy.option.none",
        )
        params: dict = {"mode": domain, "dishdrawerModeLegacyOption": option_token}
        delay = pending.get("delay_start")
        if delay is not None and delay > 0:
            params["delayStartValue"] = int(delay)
        if self._client:
            await self._client.async_send_service_command(
                device_id=self._device_id,
                service_id=svc_id,
                command_type="cloud.smarthq.command.dishdrawer.mode.legacy.set",
                params=params,
            )
        else:
            _LOGGER.warning("[DISHDRAWER_CYCLE] No client available")
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


class SmartHQDishdrawerModeLegacyOptionSelect(SelectEntity):
    """Select entity for dishdrawer legacy option (Fast / Sanitize / Ultra Dry / None).

    The selected option is stored in the HA bucket (dishdrawer_pending) and sent
    together with the cycle command by SmartHQDishdrawerModeLegacyCycleSelect.
    If the device supports only certain options (config.dishdrawerModeLegacyOptionAvailable),
    those are used; otherwise all four are shown.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:dishwasher-alert"

    # Full option set as fallback
    _ALL_OPTION_TOKENS = [
        "cloud.smarthq.type.dishdrawer.mode.legacy.option.none",
        "cloud.smarthq.type.dishdrawer.mode.legacy.option.fast",
        "cloud.smarthq.type.dishdrawer.mode.legacy.option.sanitize",
        "cloud.smarthq.type.dishdrawer.mode.legacy.option.ultra.dry",
    ]

    def __init__(self, hass, entry, client, device_id, service_id,
                 dev_name, all_svcs, cfg, unique_id):
        self.hass = hass
        self._entry = entry
        self._client = client
        self._device_id = device_id
        self._service_id = service_id
        self._all_svcs = all_svcs
        self._attr_unique_id = unique_id
        self._attr_name = f"{dev_name} Dishdrawer Option"

        self._token_to_label: Dict[str, str] = {}
        self._label_to_token: Dict[str, str] = {}
        self._build_options(cfg)

    def _build_options(self, cfg: dict) -> None:
        avail = cfg.get("dishdrawerModeLegacyOptionAvailable") or self._ALL_OPTION_TOKENS
        self._token_to_label = {t: _dishdrawer_option_label(t) for t in avail}
        self._label_to_token = {v: k for k, v in self._token_to_label.items()}
        self._attr_options = [self._token_to_label[t] for t in avail]

    def _pending(self) -> dict:
        bucket = _bucket(self.hass, self._entry)
        return bucket.setdefault("dishdrawer_pending", {}).setdefault(self._device_id, {
            "option_token": "cloud.smarthq.type.dishdrawer.mode.legacy.option.none"
        })

    @property
    def current_option(self) -> Optional[str]:
        token = self._pending().get(
            "option_token", "cloud.smarthq.type.dishdrawer.mode.legacy.option.none"
        )
        return self._token_to_label.get(token, _dishdrawer_option_label(token))

    @property
    def available(self) -> bool:
        return bool(_snapshot_for(self.hass, self._entry, self._device_id))

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_select_option(self, option: str) -> None:
        token = self._label_to_token.get(option)
        if not token:
            _LOGGER.warning("[DISHDRAWER_OPTION] Unknown option: %s", option)
            return
        self._pending()["option_token"] = token
        _LOGGER.info("[DISHDRAWER_OPTION] Pending option set: %s → %s", option, token)
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# dishwasher.favorites.v1 select
# ---------------------------------------------------------------------------

class SmartHQDishwasherFavoritesSelect(SelectEntity):
    """Select entity for dishwasher.favorites.v1 — sets the stored favorite mode."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:dishwasher"

    def __init__(self, hass, entry, client, device_id, service_id,
                 dev_name, cfg, unique_id):
        self.hass = hass
        self._entry = entry
        self._client = client
        self._device_id = device_id
        self._service_id = service_id
        self._attr_unique_id = unique_id
        self._attr_name = f"{dev_name} Dishwasher Favorite Mode"

        self._token_to_name: Dict[str, str] = {}
        self._name_to_token: Dict[str, str] = {}
        self._attr_options: List[str] = []

    def _refresh_options(self) -> None:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        live_cfg = svc.get("config") or {}
        modes = live_cfg.get("supportedModes") or []
        if modes:
            tokens = [m if isinstance(m, str) else str(m.get("token", "")) for m in modes if m]
        else:
            state = svc.get("state") or {}
            mode = state.get("mode")
            tokens = [mode] if mode else []
        self._token_to_name = {t: _pretty(t) for t in tokens if t}
        self._name_to_token = {v: k for k, v in self._token_to_name.items()}
        self._attr_options = list(self._name_to_token.keys())

    @property
    def current_option(self) -> Optional[str]:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        mode = (svc.get("state") or svc).get("mode")
        if not mode:
            return None
        return self._token_to_name.get(str(mode)) or _pretty(str(mode))

    @property
    def available(self) -> bool:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        state = svc.get("state") or svc
        return not state.get("disabled", False) and state.get("validStoredSettings", True)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Expose favorite settings as attributes."""
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        svc = (snap.get("services") or {}).get(self._service_id) or {}
        state = svc.get("state") or svc
        return {
            "wash_zone": _pretty(str(state.get("washZone", ""))),
            "wash_temp": _pretty(str(state.get("washTemp", ""))),
            "heated_dry": _pretty(str(state.get("heatedDry", ""))),
            "delay_start_minutes": state.get("delayStartInMinutes"),
            "steam": state.get("steam"),
            "bottle_blast": state.get("bottleBlast"),
            "silverware_wash": state.get("silverwareWash"),
        }

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_select_option(self, option: str) -> None:
        token = self._name_to_token.get(option) or (option if "." in option else None)
        if not token:
            _LOGGER.warning("[DW_FAVORITES] Unknown option: %s", option)
            return
        if self._client:
            await self._client.async_set_generic_mode(
                self._device_id, self._service_id,
                "cloud.smarthq.command.dishwasher.favorites.v1.set", token,
            )
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self) -> None:
        self._refresh_options()
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Cook Target Method select (Smoker: Probe Temp / Time Based)
# ---------------------------------------------------------------------------

class SmartHQCookTargetMethodSelect(SelectEntity):
    """Select entity for Smoker cook target method.

    Controls whether the cook finishes by probe temperature (Probe Temp)
    or by a fixed timer (Time Based).  The selection is stored in
    ``pending_cook_params[device_id]["is_probe_based"]`` and read by
    SmartHQStartCookingButton when the user presses Send To Smoker.
    It also drives the availability of the Probe Target and Cook Time
    number entities.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:target"

    _OPTIONS = ["Probe Temp", "Time Based"]

    def __init__(self, hass, entry, device_id: str, dev_name: str, unique_id: str) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._attr_unique_id = unique_id
        self._attr_name = f"{dev_name} Cook Target Method"
        self._attr_options = self._OPTIONS

    def _pending(self) -> dict:
        bucket = _bucket(self.hass, self._entry)
        return bucket.setdefault("pending_cook_params", {}).setdefault(
            self._device_id, {"is_probe_based": True}
        )

    @property
    def current_option(self) -> str:
        return "Probe Temp" if self._pending().get("is_probe_based", True) else "Time Based"

    @property
    def available(self) -> bool:
        snap = _snapshot_for(self.hass, self._entry, self._device_id)
        return bool(snap)

    @property
    def device_info(self):
        return _device_info_for(self.hass, self._entry, self._device_id)

    async def async_select_option(self, option: str) -> None:
        self._pending()["is_probe_based"] = (option == "Probe Temp")
        _LOGGER.info(
            "[COOK_TARGET] Device %s: method=%s",
            self._device_id[:8], option,
        )
        # Notify sibling number entities to refresh their availability
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(
            self.hass,
            SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
        )
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED.format(device_id=self._device_id),
                self._signal_update,
            )
        )
        self._signal_update()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()
