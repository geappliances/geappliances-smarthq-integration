from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .dispatcher import SIGNAL_DEVICE_UPDATED
from .service_registry import (
    FIRMWARE_SERVICE,
    DOOR_SERVICE,
    FILTER_SERVICE,
    CONNECT_SERVICE,
    TOGGLE_SERVICE,
    CMD_TOGGLE_SET,
    FILTER_STATUS_DOMAIN,
    STOPWATCH_SERVICE,
    ENHANCEDFEATURE_SERVICE,
    DISHWASHER_STATE_SERVICE,
    DRYER_RACK_SERVICE,
    DESCALE_V1_SERVICE,
    FLEXDISPENSE_SERVICE,
    COOKING_OVEN_PROBE_TEMP_SERVICE,
    COOKING_ADVANTIUM_SERVICE,
    PIZZAOVEN_STATE_SERVICE,
    PIZZAOVEN_REMINDERS_SERVICE,
    DISH_CONFIG_V1_SERVICE,
    DEMANDRESPONSE_EVENT_V1_SERVICE,
    LAUNDRY_PRICEMENU_V1_SERVICE,
    REMOTECYCLESELECTION_SERVICE,
    DISHDRAWER_MODE_LEGACY_SERVICE,
    DISHDRAWER_STATE_LEGACY_SERVICE,
    DISHWASHER_STATE_LEGACY_SERVICE,
    DISHWASHER_CUSTOM_CYCLE_SERVICE,
    COFFEEBREWER_V2_SERVICE,
    COMMON_ALERTS,
    make_unique_id,
    get_service_mapping,
    is_platform_mapped,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data-driven standard binary sensor specs
# ---------------------------------------------------------------------------
# _BF: one entry per (state_key, uid_suffix) for SmartHQDishwasherFaultBinarySensor.
# cls values:
#   "F"  → SmartHQDishwasherFaultBinarySensor(label, key, dev_cls, uid)
#   "R"  → SmartHQReminderBinarySensor(label, key, uid)
#   "CB" → SmartHQCoffeeBrewerStatusBinarySensor(label, key, dev_cls, uid)
from dataclasses import dataclass, field as dc_field

@dataclass
class _BF:
    key: str
    uid: str
    label: str
    dev_cls: Optional[BinarySensorDeviceClass]
    cls: str = "F"   # "F", "R", "CB"


_STANDARD_BINARY_SPECS: dict[str, list[_BF]] = {
    DRYER_RACK_SERVICE: [
        _BF("on",     "dryer_rack_on",  "Rack Dry",      BinarySensorDeviceClass.RUNNING),
    ],
    DESCALE_V1_SERVICE: [
        _BF("needed", "descale_needed", "Descale Needed", BinarySensorDeviceClass.PROBLEM),
    ],
    DISHWASHER_STATE_SERVICE: [
        _BF("criticalFaultActive",    "dw_critical_fault",    "Critical Fault",     BinarySensorDeviceClass.PROBLEM),
        _BF("nonCriticalFaultActive", "dw_noncritical_fault", "Non-Critical Fault", BinarySensorDeviceClass.PROBLEM),
    ],
    COOKING_OVEN_PROBE_TEMP_SERVICE: [
        _BF("probePresentUpperOven", "probe_upper_present", "Upper Probe Present", BinarySensorDeviceClass.CONNECTIVITY),
        _BF("probePresentLowerOven", "probe_lower_present", "Lower Probe Present", BinarySensorDeviceClass.CONNECTIVITY),
    ],
    COOKING_ADVANTIUM_SERVICE: [
        _BF("doorClosed",       "adv_door",         "Door",               BinarySensorDeviceClass.DOOR),
        _BF("coolingFanActive", "adv_cooling_fan",  "Cooling Fan Active", BinarySensorDeviceClass.RUNNING),
        _BF("sensingActive",    "adv_sensing",      "Sensing Active",     BinarySensorDeviceClass.RUNNING),
    ],
    PIZZAOVEN_STATE_SERVICE: [
        _BF("domeState", "pzo_dome_open", "Dome Open", BinarySensorDeviceClass.OPENING),
    ],
    PIZZAOVEN_REMINDERS_SERVICE: [
        _BF("pizzaRotateReminder",     "pzo_rem_rotate", "Rotate Reminder",      None, "R"),
        _BF("pizzaFinalCheckReminder", "pzo_rem_final",  "Final Check Reminder", None, "R"),
        _BF("pizzaDoneReminder",       "pzo_rem_done",   "Done Reminder",        None, "R"),
    ],
    DISH_CONFIG_V1_SERVICE: [
        _BF("disabled", "dish_cfg_disabled", "Dish Config Disabled", BinarySensorDeviceClass.PROBLEM),
    ],
    DEMANDRESPONSE_EVENT_V1_SERVICE: [
        _BF("disabled", "dr_event_disabled", "Demand Response Event Disabled", BinarySensorDeviceClass.PROBLEM),
    ],
    LAUNDRY_PRICEMENU_V1_SERVICE: [
        _BF("disabled", "pricemenu_disabled", "Laundry Price Menu Disabled", BinarySensorDeviceClass.PROBLEM),
    ],
    REMOTECYCLESELECTION_SERVICE: [
        _BF("disabled", "rcs_disabled", "Remote Cycle Selection Disabled", BinarySensorDeviceClass.PROBLEM),
    ],
    DISHDRAWER_STATE_LEGACY_SERVICE: [
        _BF("canStart",     "ddr_can_start",     "Dishdrawer Can Start",    BinarySensorDeviceClass.RUNNING),
        _BF("remoteEnable", "ddr_remote_enable", "Dishdrawer Remote Enable",BinarySensorDeviceClass.CONNECTIVITY),
        _BF("disabled",     "ddr_disabled",      "Dishdrawer Disabled",     BinarySensorDeviceClass.PROBLEM),
    ],
    DISHWASHER_STATE_LEGACY_SERVICE: [
        _BF("disabled",   "dws_lg_disabled",    "Dishwasher Disabled",    BinarySensorDeviceClass.PROBLEM),
        _BF("bottleWash", "dws_lg_bottle_wash", "Dishwasher Bottle Wash", BinarySensorDeviceClass.RUNNING),
        _BF("steam",      "dws_lg_steam",       "Dishwasher Steam",       BinarySensorDeviceClass.RUNNING),
    ],
    DISHWASHER_CUSTOM_CYCLE_SERVICE: [
        _BF("disabled", "dw_custom_cycle_disabled", "Custom Cycle Disabled", BinarySensorDeviceClass.PROBLEM),
    ],
    COFFEEBREWER_V2_SERVICE: [
        _BF("potPresent",      "coffee_pot_present",  "Pot Present",       BinarySensorDeviceClass.CONNECTIVITY, "CB"),
        _BF("outOfWater",      "coffee_out_water",    "Out of Water",      BinarySensorDeviceClass.PROBLEM,      "CB"),
        _BF("outOfBeans",      "coffee_out_beans",    "Out of Beans",      BinarySensorDeviceClass.PROBLEM,      "CB"),
        _BF("cleanBrewBasket", "coffee_clean_basket", "Clean Brew Basket", BinarySensorDeviceClass.PROBLEM,      "CB"),
    ],
}


def _build_standard_binary_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_id: str,
    service_id: str,
    stype: str,
    created: set[str],
) -> list[BinarySensorEntity]:
    """Create binary sensor entities for a standard (data-driven) serviceType."""
    result: list[BinarySensorEntity] = []
    for f in _STANDARD_BINARY_SPECS.get(stype, []):
        uid = make_unique_id(device_id, service_id, f.uid)
        if uid in created:
            continue
        created.add(uid)
        if f.cls == "R":
            result.append(SmartHQReminderBinarySensor(
                hass, entry, device_id, service_id, f.label, f.key, uid,
            ))
        elif f.cls == "CB":
            result.append(SmartHQCoffeeBrewerStatusBinarySensor(
                hass, entry, device_id, service_id, f.label, f.key, f.dev_cls, uid,
            ))
        else:  # "F"
            result.append(SmartHQDishwasherFaultBinarySensor(
                hass, entry, device_id, service_id, f.label, f.key, f.dev_cls, uid,
            ))
    return result


def _bucket(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    return _bucket(hass, entry).get("store") or {}


def _known_devices(hass: HomeAssistant, entry: ConfigEntry) -> List[str]:
    return list(_store(hass, entry).keys())


def _iter_alert_tokens(hass: HomeAssistant, entry: ConfigEntry, did: str) -> Iterable[str]:
    alerts = (_store(hass, entry).get(did) or {}).get("alerts") or {}
    for token in alerts.keys():
        if isinstance(token, str) and token.startswith("cloud.smarthq.alert."):
            yield token


def _dev_payload(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Dict[str, Any]:
    """Get device payload from store."""
    return _store(hass, entry).get(device_id) or {}


def _device_info_for(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> Dict[str, Any]:
    """Build device_info for a given deviceId."""
    info = _dev_payload(hass, entry, device_id).get("info") or {}
    return {
        "identifiers": {(DOMAIN, device_id)},
        "name": info.get("nickname") or info.get("model") or device_id[:8],
        "manufacturer": "GE Appliances",
        "model": info.get("model"),
    }


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SmartHQ binary sensors.

    Sources:
    1. COMMON_ALERTS (pre-registered) → SmartHQAlertBinarySensor (7 per device, always present)
    2. WS store dynamic alerts        → SmartHQAlertBinarySensor (device-specific, on receive)
    3. coordinator.data               → SmartHQFirmwareUpdateBinarySensor (firmware.v1)
                                      → SmartHQDoorBinarySensor (door)
                                      → SmartHQFilterBinarySensor (filter.v1)
    """
    store = _store(hass, entry)
    if not store:
        return

    created: set[str] = set()
    entities: List[BinarySensorEntity] = []

    # 1) Pre-register COMMON_ALERTS for every known device.
    #    This ensures all 7 common alert entities exist immediately after HA
    #    startup — before any WS alert message is received — so automations
    #    can reference them reliably.
    for did in _known_devices(hass, entry):
        for token in COMMON_ALERTS:
            uid = f"{DOMAIN}:{did}:alert:{token}"
            if uid in created:
                continue
            created.add(uid)
            entities.append(SmartHQAlertBinarySensor(hass, entry, did, token))

    # 2) Also register any device-specific alerts already in the WS store
    #    (e.g. alerts received before this setup_entry call, or non-common ones).
    for did in _known_devices(hass, entry):
        for token in _iter_alert_tokens(hass, entry, did):
            uid = f"{DOMAIN}:{did}:alert:{token}"
            if uid in created:
                continue
            created.add(uid)
            entities.append(SmartHQAlertBinarySensor(hass, entry, did, token))

    if entities:
        async_add_entities(entities, update_before_add=True)

    # 2) Coordinator-based sensors: firmware / door / filter
    bucket = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    coordinator = bucket.get("coordinator")
    if coordinator and coordinator.data:
        coord_entities: List[BinarySensorEntity] = []

        for device_id, device_item in coordinator.data.items():
            item = device_item.get("item") or {}
            services_list: list = item.get("services") or []
            if not isinstance(services_list, list):
                continue

            for svc in services_list:
                if not isinstance(svc, dict):
                    continue

                stype = svc.get("serviceType") or ""
                service_id = svc.get("id") or svc.get("serviceId") or ""
                cmds = svc.get("supportedCommands") or []

                # ── Allowlist check ──
                if get_service_mapping(stype) is None:
                    _LOGGER.debug("[BINARY_SENSOR] Skipping unmapped serviceType=%s", stype)
                    continue
                if not is_platform_mapped(stype, "binary_sensor"):
                    continue

                if stype == TOGGLE_SERVICE:
                    # Read-only toggle (no supportedCommands) on the filter-status
                    # domain: expose as a diagnostic problem binary_sensor instead
                    # of skipping it (switch.py only creates a switch when
                    # CMD_TOGGLE_SET is present, so this is mutually exclusive).
                    dom = svc.get("domainType") or ""
                    if CMD_TOGGLE_SET in cmds or dom != FILTER_STATUS_DOMAIN:
                        continue
                    uid = make_unique_id(device_id, service_id, "filter_status")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQToggleProblemBinarySensor(
                                hass, entry, device_id, service_id, "Filter Status", uid
                            )
                        )
                    continue

                if stype == FIRMWARE_SERVICE:
                    # Firmware update status is not exposed as a user-facing entity.
                    _LOGGER.debug("[BINARY_SENSOR] Blocking firmware service for %s", device_id[:8])
                    continue

                elif stype == DOOR_SERVICE:
                    uid = make_unique_id(device_id, service_id, "door")
                    if uid not in created:
                        created.add(uid)
                        dom = svc.get("domainType") or ""
                        label = dom.split(".")[-1].replace("_", " ").title() + " Door"
                        coord_entities.append(
                            SmartHQDoorBinarySensor(hass, entry, device_id, service_id, label, uid)
                        )

                elif stype == FILTER_SERVICE:
                    uid = make_unique_id(device_id, service_id, "filter")
                    if uid not in created:
                        created.add(uid)
                        dom = svc.get("domainType") or ""
                        label = dom.split(".")[-1].replace("_", " ").title() + " Filter"
                        coord_entities.append(
                            SmartHQFilterBinarySensor(hass, entry, device_id, service_id, label, uid)
                        )

                elif stype == CONNECT_SERVICE:
                    uid = make_unique_id(device_id, service_id, "connect")
                    if uid not in created:
                        created.add(uid)
                        dom = svc.get("domainType") or ""
                        label = dom.split(".")[-1].replace("_", " ").title() + " Connected"
                        coord_entities.append(
                            SmartHQConnectBinarySensor(hass, entry, device_id, service_id, label, uid)
                        )

                elif stype == STOPWATCH_SERVICE:
                    uid = make_unique_id(device_id, service_id, "sw_paused")
                    if uid not in created:
                        created.add(uid)
                        dom = svc.get("domainType") or ""
                        label = dom.split(".")[-1].replace("_", " ").title() + " Paused"
                        coord_entities.append(
                            SmartHQStopwatchPausedBinarySensor(hass, entry, device_id, service_id, label, uid)
                        )

                elif stype == ENHANCEDFEATURE_SERVICE:
                    uid = make_unique_id(device_id, service_id, "enhancedfeat")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQEnhancedFeatureBinarySensor(hass, entry, device_id, service_id, uid)
                        )

                elif stype == DISHDRAWER_MODE_LEGACY_SERVICE:
                    # domain-derived label — cannot use static spec table
                    dom = svc.get("domainType") or ""
                    cycle_label = dom.split(".")[-1].replace("_", " ").title() if dom else "Dishdrawer"
                    uid = make_unique_id(device_id, service_id, "dishdrawer_mode_disabled")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQDishwasherFaultBinarySensor(
                                hass, entry, device_id, service_id,
                                f"Dishdrawer {cycle_label} Disabled", "disabled",
                                BinarySensorDeviceClass.PROBLEM, uid,
                            )
                        )

                elif stype == FLEXDISPENSE_SERVICE:
                    dom = svc.get("domainType") or ""
                    label = dom.split(".")[-1].replace("_", " ").title() + " Flex Dispense Active"
                    uid = make_unique_id(device_id, service_id, "flexdispense_on")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQDishwasherFaultBinarySensor(
                                hass, entry, device_id, service_id,
                                label, "on", BinarySensorDeviceClass.RUNNING, uid,
                            )
                        )

                # ── standard (data-driven) binary sensors ───────────────────
                elif stype in _STANDARD_BINARY_SPECS:
                    coord_entities.extend(_build_standard_binary_sensors(
                        hass, entry, device_id, service_id, stype, created,
                    ))

        if coord_entities:
            async_add_entities(coord_entities, update_before_add=True)

    @callback
    def _on_device_update() -> None:
        """Handle device update signal to discover new alerts."""
        for device_id in _known_devices(hass, entry):
            new_list: List[SmartHQAlertBinarySensor] = []
            for token in _iter_alert_tokens(hass, entry, device_id):
                uid = f"{DOMAIN}:{device_id}:alert:{token}"
                if uid in created:
                    continue
                created.add(uid)
                new_list.append(SmartHQAlertBinarySensor(hass, entry, device_id, token))
            if new_list:
                _LOGGER.debug("[ALERT_ENTITIES] add %d for %s", len(new_list), device_id[:8])
                async_add_entities(new_list)

    for device_id in _known_devices(hass, entry):
        async_dispatcher_connect(
            hass,
            SIGNAL_DEVICE_UPDATED.format(device_id=device_id),
            _on_device_update,
        )


class SmartHQAlertBinarySensor(BinarySensorEntity):
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_id: str, token: str) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._token = token
        nice = token.split(".")[-1].replace("_", " ").title()
        self._attr_name = f"Alert: {nice}"
        self._attr_unique_id = f"{DOMAIN}:{device_id}:alert:{token}"

    def _get_alert(self) -> dict:
        return (
            (_store(self.hass, self._entry).get(self._device_id) or {})
            .get("alerts", {})
            .get(self._token)
        ) or {}

    @property
    def is_on(self) -> bool:
        a = self._get_alert()
        if "active" in a:
            return bool(a["active"])
        return bool(a)  # False when no alert data (pre-registered, not yet received)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        a = self._get_alert()
        return {
            "token": self._token,
            "last_ts": a.get("last_ts"),
            "message": a.get("message"),
        }

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
        self.async_write_ha_state()

    @callback
    def _signal_update(self) -> None:
        """Handle device update signal."""
        self.async_write_ha_state()


class SmartHQDoorBinarySensor(BinarySensorEntity):
    """Binary sensor for door open/close state (door service)."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        service_id: str,
        label: str,
        unique_id: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._attr_name = label
        self._attr_unique_id = unique_id

    def _get_state(self) -> dict:
        store = _store(self.hass, self._entry)
        snap = (store.get(self._device_id) or {}).get("snapshot") or {}
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def is_on(self) -> bool:
        """Return True when door is open."""
        st = self._get_state()
        raw = st.get("doorState") or st.get("state") or st.get("open") or ""
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in {"open", "true", "1"}

    @property
    def available(self) -> bool:
        return bool(self._get_state())

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
        self.async_write_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


class SmartHQToggleProblemBinarySensor(BinarySensorEntity):
    """Diagnostic binary sensor for a read-only toggle service (e.g. filter status).

    Routed here instead of switch.py because the service has no
    supportedCommands (CMD_TOGGLE_SET absent) — it can only be observed, not
    controlled. `on` means the condition needs attention (e.g. filter cleaning
    required).
    """

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        service_id: str,
        label: str,
        unique_id: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._attr_name = label
        self._attr_unique_id = unique_id

    def _get_state(self) -> dict:
        store = _store(self.hass, self._entry)
        snap = (store.get(self._device_id) or {}).get("snapshot") or {}
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def is_on(self) -> bool:
        return bool(self._get_state().get("on"))

    @property
    def available(self) -> bool:
        return bool(self._get_state())

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
        self.async_write_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


class SmartHQFilterBinarySensor(BinarySensorEntity):
    """Binary sensor that is ON when a filter needs replacement (filter.v1 service)."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        service_id: str,
        label: str,
        unique_id: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._attr_name = label
        self._attr_unique_id = unique_id

    def _get_state(self) -> dict:
        store = _store(self.hass, self._entry)
        snap = (store.get(self._device_id) or {}).get("snapshot") or {}
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def is_on(self) -> bool:
        """Return True when filter replacement is needed."""
        st = self._get_state()
        # Common keys: filterStatus, state, replacementNeeded
        status = str(st.get("filterStatus") or st.get("state") or "").lower()
        if status in {"replace", "replacement_needed", "dirty", "problem", "true", "1"}:
            return True
        replacement = st.get("replacementNeeded")
        if isinstance(replacement, bool):
            return replacement
        return False

    @property
    def extra_state_attributes(self) -> dict:
        st = self._get_state()
        return {
            "filter_status": st.get("filterStatus") or st.get("state"),
            "life_remaining": st.get("lifeRemaining"),
        }

    @property
    def available(self) -> bool:
        return bool(self._get_state())

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
        self.async_write_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Firmware update binary sensor
# ---------------------------------------------------------------------------

class SmartHQFirmwareUpdateBinarySensor(BinarySensorEntity):
    """Binary sensor that is ON when a firmware upgrade is available.

    Reads upgradeStatus from the WS snapshot; True when the status is anything
    other than 'idle' (e.g. 'available', 'delayed', 'downloading', 'updating').
    """

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.UPDATE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False

    # Statuses that mean "no update pending"
    _IDLE_STATUSES = frozenset({"idle", ""})

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        service_id: str,
        unique_id: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._attr_unique_id = unique_id
        self._attr_name = "Firmware Update"

    def _get_state(self) -> dict:
        store = _store(self.hass, self._entry)
        snap = (store.get(self._device_id) or {}).get("snapshot") or {}
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def is_on(self) -> bool:
        st = self._get_state()
        status = str(st.get("upgradeStatus") or "").lower()
        return status not in self._IDLE_STATUSES

    @property
    def extra_state_attributes(self) -> dict:
        st = self._get_state()
        return {
            "upgrade_status": st.get("upgradeStatus"),
            "version_current": st.get("versionCurrent"),
            "version_available": st.get("versionAvailable"),
        }

    @property
    def available(self) -> bool:
        return bool(self._get_state())

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
        self.async_write_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# connect.v1 binary sensor
# ---------------------------------------------------------------------------

class SmartHQConnectBinarySensor(BinarySensorEntity):
    """Binary sensor for connect.v1 — ON when overallState > 0 (connected)."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True

    def __init__(self, hass, entry, device_id, service_id, label, unique_id):
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._attr_name = label
        self._attr_unique_id = unique_id

    def _get_state(self) -> dict:
        store = _store(self.hass, self._entry)
        snap = (store.get(self._device_id) or {}).get("snapshot") or {}
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def is_on(self) -> bool:
        return bool(self._get_state().get("overallState", 0))

    @property
    def available(self) -> bool:
        return "overallState" in self._get_state()

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
        self.async_write_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# stopwatch paused binary sensor
# ---------------------------------------------------------------------------

class SmartHQStopwatchPausedBinarySensor(BinarySensorEntity):
    """Binary sensor for stopwatch — ON when paused."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass, entry, device_id, service_id, label, unique_id):
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._attr_name = label
        self._attr_unique_id = unique_id
        self._attr_icon = "mdi:timer-pause"

    def _get_state(self) -> dict:
        store = _store(self.hass, self._entry)
        snap = (store.get(self._device_id) or {}).get("snapshot") or {}
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def is_on(self) -> bool:
        return bool(self._get_state().get("paused", False))

    @property
    def available(self) -> bool:
        return "paused" in self._get_state()

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
        self.async_write_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# enhancedfeature.v1 binary sensor
# ---------------------------------------------------------------------------

class SmartHQEnhancedFeatureBinarySensor(BinarySensorEntity):
    """Binary sensor for enhancedfeature.v1 — ON when any feature is enabled."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass, entry, device_id, service_id, unique_id):
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._attr_name = "Enhanced Features Enabled"
        self._attr_unique_id = unique_id
        self._attr_icon = "mdi:star-check"

    def _get_state(self) -> dict:
        store = _store(self.hass, self._entry)
        snap = (store.get(self._device_id) or {}).get("snapshot") or {}
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def is_on(self) -> bool:
        ids = self._get_state().get("enabledFeaturesIds") or []
        return bool(ids)

    @property
    def available(self) -> bool:
        st = self._get_state()
        return "enabledFeaturesIds" in st or "lastTransactionId" in st

    @property
    def extra_state_attributes(self) -> dict:
        st = self._get_state()
        return {
            "enabled_feature_ids": st.get("enabledFeaturesIds"),
            "last_transaction_id": st.get("lastTransactionId"),
        }

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
        self.async_write_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# dishwasher.state fault binary sensor
# ---------------------------------------------------------------------------

class SmartHQDishwasherFaultBinarySensor(BinarySensorEntity):
    """Binary sensor for dishwasher.state — criticalFaultActive / nonCriticalFaultActive."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass, entry, device_id, service_id, label, state_key, dev_cls, unique_id):
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._state_key = state_key
        self._attr_name = label
        self._attr_device_class = dev_cls
        self._attr_unique_id = unique_id

    def _get_state(self) -> dict:
        store = _store(self.hass, self._entry)
        snap = (store.get(self._device_id) or {}).get("snapshot") or {}
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def is_on(self) -> bool:
        return bool(self._get_state().get(self._state_key, False))

    @property
    def available(self) -> bool:
        return self._state_key in self._get_state()

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
        self.async_write_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()

# ---------------------------------------------------------------------------
# pizzaoven.reminders reminder status binary sensor
# ---------------------------------------------------------------------------

class SmartHQCoffeeBrewerStatusBinarySensor(BinarySensorEntity):
    """Binary sensor for coffeebrewer.v2 boolean status flags.

    Covers: potPresent, outOfWater, outOfBeans, cleanBrewBasket.
    State is read from the WS snapshot store so it updates in real-time.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    _ICONS: dict[str, str] = {
        "potPresent":      "mdi:coffee-maker",
        "outOfWater":      "mdi:water-off",
        "outOfBeans":      "mdi:coffee-off",
        "cleanBrewBasket": "mdi:broom",
    }

    def __init__(
        self,
        hass,
        entry,
        device_id: str,
        service_id: str,
        label: str,
        state_key: str,
        dev_cls,
        unique_id: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._state_key = state_key
        self._attr_name = label
        self._attr_device_class = dev_cls
        self._attr_unique_id = unique_id
        self._attr_icon = self._ICONS.get(state_key, "mdi:coffee")

    def _get_state(self) -> dict:
        store = _store(self.hass, self._entry)
        snap = (store.get(self._device_id) or {}).get("snapshot") or {}
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def is_on(self) -> bool:
        return bool(self._get_state().get(self._state_key, False))

    @property
    def available(self) -> bool:
        return self._state_key in self._get_state()

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
        self.async_write_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()


class SmartHQReminderBinarySensor(BinarySensorEntity):
    """Binary sensor for pizzaoven.reminders — ON when reminder is enabled."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _ENABLED_TOKEN = "cloud.smarthq.type.reminder.status.enabled"

    def __init__(self, hass, entry, device_id, service_id, label, state_key, unique_id):
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._service_id = service_id
        self._state_key = state_key
        self._attr_name = label
        self._attr_unique_id = unique_id
        self._attr_icon = "mdi:bell"

    def _get_state(self) -> dict:
        store = _store(self.hass, self._entry)
        snap = (store.get(self._device_id) or {}).get("snapshot") or {}
        return (snap.get("services") or {}).get(self._service_id) or {}

    @property
    def is_on(self) -> bool:
        return self._get_state().get(self._state_key) == self._ENABLED_TOKEN

    @property
    def available(self) -> bool:
        return self._state_key in self._get_state()

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
        self.async_write_ha_state()

    @callback
    def _signal_update(self) -> None:
        self.async_write_ha_state()
