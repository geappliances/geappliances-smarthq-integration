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
)

_LOGGER = logging.getLogger(__name__)


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

                if stype == FIRMWARE_SERVICE:
                    uid = make_unique_id(device_id, service_id, "fw_update")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQFirmwareUpdateBinarySensor(hass, entry, device_id, service_id, uid)
                        )

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

                elif stype == DRYER_RACK_SERVICE:
                    uid = make_unique_id(device_id, service_id, "dryer_rack_on")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQDishwasherFaultBinarySensor(
                                hass, entry, device_id, service_id,
                                "Rack Dry", "on", BinarySensorDeviceClass.RUNNING, uid,
                            )
                        )

                elif stype == DESCALE_V1_SERVICE:
                    uid = make_unique_id(device_id, service_id, "descale_needed")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQDishwasherFaultBinarySensor(
                                hass, entry, device_id, service_id,
                                "Descale Needed", "needed", BinarySensorDeviceClass.PROBLEM, uid,
                            )
                        )

                elif stype == FLEXDISPENSE_SERVICE:
                    uid = make_unique_id(device_id, service_id, "flexdispense_on")
                    if uid not in created:
                        created.add(uid)
                        dom = svc.get("domainType") or ""
                        label = dom.split(".")[-1].replace("_", " ").title() + " Flex Dispense Active"
                        coord_entities.append(
                            SmartHQDishwasherFaultBinarySensor(
                                hass, entry, device_id, service_id,
                                label, "on", BinarySensorDeviceClass.RUNNING, uid,
                            )
                        )

                elif stype == DISHWASHER_STATE_SERVICE:
                    for key, label, uid_sfx, dev_cls in [
                        ("criticalFaultActive",    "Critical Fault",     "dw_critical_fault",    BinarySensorDeviceClass.PROBLEM),
                        ("nonCriticalFaultActive", "Non-Critical Fault", "dw_noncritical_fault", BinarySensorDeviceClass.PROBLEM),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in created:
                            created.add(uid)
                            coord_entities.append(
                                SmartHQDishwasherFaultBinarySensor(
                                    hass, entry, device_id, service_id,
                                    label, key, dev_cls, uid,
                                )
                            )

                elif stype == COOKING_OVEN_PROBE_TEMP_SERVICE:
                    for key, label, uid_sfx in [
                        ("probePresentUpperOven", "Upper Probe Present", "probe_upper_present"),
                        ("probePresentLowerOven", "Lower Probe Present", "probe_lower_present"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in created:
                            created.add(uid)
                            coord_entities.append(
                                SmartHQDishwasherFaultBinarySensor(
                                    hass, entry, device_id, service_id,
                                    label, key, BinarySensorDeviceClass.CONNECTIVITY, uid,
                                )
                            )

                elif stype == COOKING_ADVANTIUM_SERVICE:
                    for key, label, uid_sfx, dev_cls in [
                        ("doorClosed",      "Door",              "adv_door",         BinarySensorDeviceClass.DOOR),
                        ("coolingFanActive","Cooling Fan Active","adv_cooling_fan",   BinarySensorDeviceClass.RUNNING),
                        ("sensingActive",   "Sensing Active",   "adv_sensing",       BinarySensorDeviceClass.RUNNING),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in created:
                            created.add(uid)
                            coord_entities.append(
                                SmartHQDishwasherFaultBinarySensor(
                                    hass, entry, device_id, service_id,
                                    label, key, dev_cls, uid,
                                )
                            )

                elif stype == PIZZAOVEN_STATE_SERVICE:
                    uid = make_unique_id(device_id, service_id, "pzo_dome_open")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQDishwasherFaultBinarySensor(
                                hass, entry, device_id, service_id,
                                "Dome Open", "domeState", BinarySensorDeviceClass.OPENING, uid,
                            )
                        )

                elif stype == PIZZAOVEN_REMINDERS_SERVICE:
                    for key, label, uid_sfx in [
                        ("pizzaRotateReminder",     "Rotate Reminder",      "pzo_rem_rotate"),
                        ("pizzaFinalCheckReminder", "Final Check Reminder", "pzo_rem_final"),
                        ("pizzaDoneReminder",       "Done Reminder",        "pzo_rem_done"),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in created:
                            created.add(uid)
                            coord_entities.append(
                                SmartHQReminderBinarySensor(
                                    hass, entry, device_id, service_id,
                                    label, key, uid,
                                )
                            )

                elif stype == DISH_CONFIG_V1_SERVICE:
                    # dish.config.v1 state: disabled (BOOLEAN)
                    uid = make_unique_id(device_id, service_id, "dish_cfg_disabled")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQDishwasherFaultBinarySensor(
                                hass, entry, device_id, service_id,
                                "Dish Config Disabled", "disabled",
                                BinarySensorDeviceClass.PROBLEM, uid,
                            )
                        )

                elif stype == DEMANDRESPONSE_EVENT_V1_SERVICE:
                    # demandresponse.event.v1 state: disabled (BOOLEAN)
                    uid = make_unique_id(device_id, service_id, "dr_event_disabled")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQDishwasherFaultBinarySensor(
                                hass, entry, device_id, service_id,
                                "Demand Response Event Disabled", "disabled",
                                BinarySensorDeviceClass.PROBLEM, uid,
                            )
                        )

                elif stype == LAUNDRY_PRICEMENU_V1_SERVICE:
                    # laundry.pricemenu.v1 state: disabled (BOOLEAN)
                    uid = make_unique_id(device_id, service_id, "pricemenu_disabled")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQDishwasherFaultBinarySensor(
                                hass, entry, device_id, service_id,
                                "Laundry Price Menu Disabled", "disabled",
                                BinarySensorDeviceClass.PROBLEM, uid,
                            )
                        )

                elif stype == REMOTECYCLESELECTION_SERVICE:
                    # remotecycleselection state: disabled (BOOLEAN)
                    uid = make_unique_id(device_id, service_id, "rcs_disabled")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQDishwasherFaultBinarySensor(
                                hass, entry, device_id, service_id,
                                "Remote Cycle Selection Disabled", "disabled",
                                BinarySensorDeviceClass.PROBLEM, uid,
                            )
                        )

                elif stype == DISHDRAWER_MODE_LEGACY_SERVICE:
                    # dishdrawer.mode.legacy state: disabled (BOOLEAN)
                    # domainType = cycle type (e.g. dishwasher.pots)
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

                elif stype == DISHDRAWER_STATE_LEGACY_SERVICE:
                    # State: canStart (BOOLEAN), remoteEnable (BOOLEAN), disabled (BOOLEAN)
                    for key, label, uid_sfx, dev_cls in [
                        ("canStart",     "Dishdrawer Can Start",   "ddr_can_start",    BinarySensorDeviceClass.RUNNING),
                        ("remoteEnable", "Dishdrawer Remote Enable","ddr_remote_enable",BinarySensorDeviceClass.CONNECTIVITY),
                        ("disabled",     "Dishdrawer Disabled",    "ddr_disabled",     BinarySensorDeviceClass.PROBLEM),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in created:
                            created.add(uid)
                            coord_entities.append(
                                SmartHQDishwasherFaultBinarySensor(
                                    hass, entry, device_id, service_id,
                                    label, key, dev_cls, uid,
                                )
                            )

                elif stype == DISHWASHER_STATE_LEGACY_SERVICE:
                    # State: disabled (BOOLEAN), bottleWash (BOOLEAN), steam (BOOLEAN)
                    for key, label, uid_sfx, dev_cls in [
                        ("disabled",   "Dishwasher Disabled",    "dws_lg_disabled",    BinarySensorDeviceClass.PROBLEM),
                        ("bottleWash", "Dishwasher Bottle Wash", "dws_lg_bottle_wash", BinarySensorDeviceClass.RUNNING),
                        ("steam",      "Dishwasher Steam",       "dws_lg_steam",       BinarySensorDeviceClass.RUNNING),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in created:
                            created.add(uid)
                            coord_entities.append(
                                SmartHQDishwasherFaultBinarySensor(
                                    hass, entry, device_id, service_id,
                                    label, key, dev_cls, uid,
                                )
                            )

                elif stype == DISHWASHER_CUSTOM_CYCLE_SERVICE:
                    # State: disabled (BOOLEAN)
                    uid = make_unique_id(device_id, service_id, "dw_custom_cycle_disabled")
                    if uid not in created:
                        created.add(uid)
                        coord_entities.append(
                            SmartHQDishwasherFaultBinarySensor(
                                hass, entry, device_id, service_id,
                                "Custom Cycle Disabled", "disabled",
                                BinarySensorDeviceClass.PROBLEM, uid,
                            )
                        )

                elif stype == COFFEEBREWER_V2_SERVICE:
                    # coffeebrewer.v2 status flags from state
                    for key, label, uid_sfx, dev_cls in [
                        ("potPresent",      "Pot Present",        "coffee_pot_present",   BinarySensorDeviceClass.CONNECTIVITY),
                        ("outOfWater",      "Out of Water",       "coffee_out_water",     BinarySensorDeviceClass.PROBLEM),
                        ("outOfBeans",      "Out of Beans",       "coffee_out_beans",     BinarySensorDeviceClass.PROBLEM),
                        ("cleanBrewBasket", "Clean Brew Basket",  "coffee_clean_basket",  BinarySensorDeviceClass.PROBLEM),
                    ]:
                        uid = make_unique_id(device_id, service_id, uid_sfx)
                        if uid not in created:
                            created.add(uid)
                            coord_entities.append(
                                SmartHQCoffeeBrewerStatusBinarySensor(
                                    hass, entry, device_id, service_id,
                                    label, key, dev_cls, uid,
                                )
                            )

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
