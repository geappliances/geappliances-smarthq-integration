"""SmartHQ Service Registry.

Central mapping of SmartHQ ServiceType / DomainType constants to HA platforms.

Design principle: ServiceType determines the HA entity — DeviceType is never referenced.
supportedCommands determines whether an entity is read-only (sensor) or controllable.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# ServiceType constants
# ---------------------------------------------------------------------------

TOGGLE_SERVICE = "cloud.smarthq.service.toggle"
MODE_SERVICE = "cloud.smarthq.service.mode"
TEMPERATURE_SERVICE = "cloud.smarthq.service.temperature"
CYCLETIMER_SERVICE = "cloud.smarthq.service.cycletimer"
METER_SERVICE = "cloud.smarthq.service.meter"
INTEGER_SERVICE = "cloud.smarthq.service.integer"
DOUBLE_SERVICE = "cloud.smarthq.service.double"
STRING_SERVICE = "cloud.smarthq.service.string"
FIRMWARE_SERVICE = "cloud.smarthq.service.firmware.v1"
BATTERY_SERVICE = "cloud.smarthq.service.battery"
ENVIRONMENTAL_SERVICE = "cloud.smarthq.service.environmental.sensor"
TRIGGER_SERVICE = "cloud.smarthq.service.trigger"
DOOR_SERVICE = "cloud.smarthq.service.door"
FILTER_SERVICE = "cloud.smarthq.service.filter.v1"
COOKING_STATE_SERVICE = "cloud.smarthq.service.cooking.state.v1"
COOKING_MODE_SERVICE = "cloud.smarthq.service.cooking.mode.v1"
COFFEEBREWER_V1_SERVICE = "cloud.smarthq.service.coffeebrewer.v1"
COFFEEBREWER_V2_SERVICE = "cloud.smarthq.service.coffeebrewer.v2"
BREW_MODE_SERVICE = "cloud.smarthq.service.brew.mode.v1"
LAUNDRY_STATE_SERVICE = "cloud.smarthq.service.laundry.state.v1"
LAUNDRY_MODE_SERVICE = "cloud.smarthq.service.laundry.mode.v1"
LAUNDRY_TOGGLE_V2_SERVICE = "cloud.smarthq.service.laundry.toggle.v2"
DELAYWINDOW_SERVICE = "cloud.smarthq.service.delaywindow"
CONNECT_SERVICE = "cloud.smarthq.service.connect.v1"
ENHANCEDFEATURE_SERVICE = "cloud.smarthq.service.enhancedfeature.v1"
STOPWATCH_SERVICE = "cloud.smarthq.service.stopwatch"
VOLUME_LIQUID_SERVICE = "cloud.smarthq.service.volume.liquid.v1"
SCALE_SERVICE = "cloud.smarthq.service.scale.v1"
POWER_USAGE_SERVICE = "cloud.smarthq.service.power.usage"
DISHWASHER_STATE_V1_SERVICE = "cloud.smarthq.service.dishwasher.state.v1"
DISHWASHER_STATE_SERVICE = "cloud.smarthq.service.dishwasher.state"
DISHWASHER_MODE_V1_SERVICE = "cloud.smarthq.service.dishwasher.mode.v1"
DISHWASHER_RINSE_AGENT_SERVICE = "cloud.smarthq.service.dishwasher.rinse.agent"
DESCALE_V1_SERVICE = "cloud.smarthq.service.descale.v1"
DRYER_RACK_SERVICE = "cloud.smarthq.service.dryer.rack"
DRYER_VENT_HEALTH_MODE_SERVICE = "cloud.smarthq.service.dryer.vent.health.mode"
LAUNDRY_BULKTANK_SERVICE = "cloud.smarthq.service.laundry.bulktank"
OUTDOORUNIT_INFO_SERVICE = "cloud.smarthq.service.outdoorunit.info"
SMARTDISPENSE_SERVICE = "cloud.smarthq.service.smartdispense"
FLEXDISPENSE_SERVICE = "cloud.smarthq.service.flexdispense"
STAINREMOVAL_SERVICE = "cloud.smarthq.service.stainremoval"
LAUNDRY_PETHAIR_SERVICE = "cloud.smarthq.service.laundry.pethair"
COOKING_OVEN_PROBE_TEMP_SERVICE = "cloud.smarthq.service.cooking.oven.probe.temperature"
COOKING_BURNER_STATUS_SERVICE = "cloud.smarthq.service.cooking.burner.status.v1"
COOKING_ADVANTIUM_SERVICE = "cloud.smarthq.service.cooking.advantium"
COLOR_SERVICE = "cloud.smarthq.service.color"
COOKING_PRORANGE_ACCENT_LIGHT_SERVICE = "cloud.smarthq.service.cooking.prorange.accent.light"
COOKTOP_CLOSEDLOOP_SERVICE = "cloud.smarthq.service.cooktop.closedloop"
COOKTOP_SOUSVIDE_SERVICE = "cloud.smarthq.service.cooktop.sousvide"
OVEN_FLEXTIMER_SERVICE = "cloud.smarthq.service.oven.flextimer"
DRYER_CONFIG_CYCLE_V1_SERVICE = "cloud.smarthq.service.dryer.config.cycle.v1"
DRYER_MYCYCLE_SERVICE = "cloud.smarthq.service.dryer.mycycle"
WASHER_CONFIG_CYCLE_V1_SERVICE = "cloud.smarthq.service.washer.config.cycle.v1"
WASHER_MYCYCLE_SERVICE = "cloud.smarthq.service.washer.mycycle"
DEMANDRESPONSE_STATE_V1_SERVICE = "cloud.smarthq.service.demandresponse.state.v1"
OVEN_MENUTREE_SERVICE = "cloud.smarthq.service.oven.menutree"
LAUNDRY_COMMERCIAL_V1_SERVICE = "cloud.smarthq.service.laundry.commercial.v1"
LAUNDRY_DOWNLOADABLECYCLE_SERVICE = "cloud.smarthq.service.laundry.downloadablecycle"
DISH_CONFIG_V1_SERVICE = "cloud.smarthq.service.dish.config.v1"
DEMANDRESPONSE_EVENT_V1_SERVICE = "cloud.smarthq.service.demandresponse.event.v1"
LAUNDRY_PRICEMENU_V1_SERVICE = "cloud.smarthq.service.laundry.pricemenu.v1"
REMOTECYCLESELECTION_SERVICE = "cloud.smarthq.service.remotecycleselection"
DISHDRAWER_MODE_LEGACY_SERVICE = "cloud.smarthq.service.dishdrawer.mode.legacy"
DISHDRAWER_STATE_LEGACY_SERVICE = "cloud.smarthq.service.dishdrawer.state.legacy"
DISHWASHER_STATE_LEGACY_SERVICE = "cloud.smarthq.service.dishwasher.state.legacy"
DISHWASHER_CUSTOM_CYCLE_SERVICE = "cloud.smarthq.service.dishwasher.custom.cycle"
DISHWASHER_FAVORITES_V1_SERVICE = "cloud.smarthq.service.dishwasher.favorites.v1"

# ---------------------------------------------------------------------------
# Command type constants
# ---------------------------------------------------------------------------

CMD_TOGGLE_SET = "cloud.smarthq.command.toggle.set"
CMD_MODE_SET = "cloud.smarthq.command.mode.set"
CMD_TEMPERATURE_SET = "cloud.smarthq.command.temperature.set"
CMD_INTEGER_SET = "cloud.smarthq.command.integer.set"
CMD_INTEGER_ADJUST = "cloud.smarthq.command.integer.adjust"
CMD_TRIGGER_DO = "cloud.smarthq.command.trigger.do"
# Legacy alias kept for backward compat (will be removed in Phase 3)
CMD_TRIGGER = CMD_TRIGGER_DO
CMD_FIRMWARE_UPGRADE = "cloud.smarthq.command.firmware.v1.upgrade"
CMD_COOKING_MODE_SET = "cloud.smarthq.command.cooking.mode.v1.set"
CMD_COOKING_MODE_START = "cloud.smarthq.command.cooking.mode.v1.start"
CMD_COOKING_STATE_STOP = "cloud.smarthq.command.cooking.state.v1.stop"
CMD_COOKING_STATE_PAUSE = "cloud.smarthq.command.cooking.state.v1.pause"
CMD_COOKING_STATE_RESUME = "cloud.smarthq.command.cooking.state.v1.resume"
CMD_LAUNDRY_MODE_SET = "cloud.smarthq.command.laundry.mode.v1.set"
CMD_LAUNDRY_TOGGLE_V2_SET = "cloud.smarthq.command.laundry.toggle.v2.set"
CMD_DELAYWINDOW_SET = "cloud.smarthq.command.delaywindow.set"
CMD_BREW_MODE_SET = "cloud.smarthq.command.brew.mode.v1.set"
CMD_DISHWASHER_STATE_START = "cloud.smarthq.command.dishwasher.state.v1.start"
CMD_DISHWASHER_STATE_STOP = "cloud.smarthq.command.dishwasher.state.v1.stop"
CMD_DISHWASHER_STATE_PAUSE = "cloud.smarthq.command.dishwasher.state.v1.pause"
CMD_DISHWASHER_MODE_SET = "cloud.smarthq.command.dishwasher.mode.v1.set"
CMD_FLEXDISPENSE_MODE_SET = "cloud.smarthq.command.flexdispense.mode.set"
CMD_STAINREMOVAL_MODE_SET = "cloud.smarthq.command.stainremoval.mode.set"
CMD_ADVANTIUM_START = "cloud.smarthq.command.cooking.advantium.start"
CMD_ADVANTIUM_STOP = "cloud.smarthq.command.cooking.advantium.stop"
CMD_ADVANTIUM_PAUSE = "cloud.smarthq.command.cooking.advantium.pause"
CMD_ADVANTIUM_RESUME = "cloud.smarthq.command.cooking.advantium.resume"
CMD_MIXER_CANCEL = "cloud.smarthq.command.mixer.v1.cancel"
CMD_MIXER_PAUSE = "cloud.smarthq.command.mixer.v1.pause"
CMD_COLOR_SET = "cloud.smarthq.command.color.set"
CMD_ACCENT_LIGHT_SET = "cloud.smarthq.command.cooking.prorange.accent.light.set"
CMD_COOKTOP_CLOSEDLOOP_SET = "cloud.smarthq.command.cooktop.closedloop.set"
CMD_COOKTOP_SOUSVIDE_COOKTIME_SET = "cloud.smarthq.command.cooktop.sousvide.cooktime.target.set"
CMD_OVEN_FLEXTIMER_EXPIRATION_SET = "cloud.smarthq.command.oven.flextimer.expiration.set"
CMD_OVEN_FLEXTIMER_ADDORSUBTRACT_SET = "cloud.smarthq.command.oven.flextimer.addorsubtract.set"
CMD_STRING_SET = "cloud.smarthq.command.string.set"
CMD_REMOTECYCLESELECTION_SET = "cloud.smarthq.command.remotecycleselection.set"
CMD_LAUNDRY_PRICEMENU_SET = "cloud.smarthq.command.laundry.pricemenu.v1.set"
CMD_DISHDRAWER_MODE_LEGACY_SET = "cloud.smarthq.command.dishdrawer.mode.legacy.set"
CMD_DISHDRAWER_STATE_LEGACY_START = "cloud.smarthq.command.dishdrawer.state.legacy.start"
CMD_DISHDRAWER_STATE_LEGACY_STOP = "cloud.smarthq.command.dishdrawer.state.legacy.stop"
CMD_DISHDRAWER_STATE_LEGACY_PAUSE = "cloud.smarthq.command.dishdrawer.state.legacy.pause"
CMD_DISHWASHER_CUSTOM_CYCLE_SET = "cloud.smarthq.command.dishwasher.custom.cycle.set"
CMD_DISHWASHER_FAVORITES_V1_SET = "cloud.smarthq.command.dishwasher.favorites.v1.set"

# ---------------------------------------------------------------------------
# Service type constants — Todo #7
# ---------------------------------------------------------------------------
ESPRESSOMAKER_SERVICE = "cloud.smarthq.service.espressomaker.v1"
MIXER_SERVICE = "cloud.smarthq.service.mixer.v1"
PIZZAOVEN_STATE_SERVICE = "cloud.smarthq.service.pizzaoven.state"
PIZZAOVEN_REMINDERS_SERVICE = "cloud.smarthq.service.pizzaoven.reminders"
SOURDOUGHSTARTER_SERVICE = "cloud.smarthq.service.sourdoughstarter.v1"
THERMOSTAT_SERVICE = "cloud.smarthq.service.thermostat.v1"
WATERHEATER_SERVICE = "cloud.smarthq.service.waterheater.v1"
CMD_THERMOSTAT_SET = "cloud.smarthq.command.thermostat.v1.set"
CMD_WATERHEATER_SET = "cloud.smarthq.command.waterheater.v1.set"

# ---------------------------------------------------------------------------
# DomainType classification sets
# ---------------------------------------------------------------------------

# mode services with these domains are exposed as HA switches (binary on/off)
# rather than selects with multiple options
BRIGHTNESS_DOMAINS: frozenset[str] = frozenset({
    "cloud.smarthq.domain.brightness",
    "cloud.smarthq.domain.light",
})

# mode/toggle services with these domains are exposed as HA switches (binary lock)
LOCK_DOMAINS: frozenset[str] = frozenset({
    "cloud.smarthq.domain.controls.lock",
    "cloud.smarthq.domain.lock",
    "cloud.smarthq.domain.override",
})

# All domains that cause a mode service to map to a switch instead of select
SWITCH_MODE_DOMAINS: frozenset[str] = BRIGHTNESS_DOMAINS | LOCK_DOMAINS

# mode services that are display-only (read-only sensor, no select)
READONLY_MODE_DOMAINS: frozenset[str] = frozenset({
    "cloud.smarthq.domain.icemaker",
    # demandresponse is set by the utility grid program automatically;
    # it is not user-controllable and does not appear in the SmartHQ app
    "cloud.smarthq.domain.demandresponse",
})

# environmental.sensor domainType → HA SensorDeviceClass mapping
ENVIRONMENTAL_DOMAIN_DEVICE_CLASS: dict[str, str] = {
    "cloud.smarthq.domain.sensor.temperature.environmental": "temperature",
    "cloud.smarthq.domain.sensor.humidity": "humidity",
    "cloud.smarthq.domain.sensor.voc": "volatile_organic_compounds",
    "cloud.smarthq.domain.sensor.particles.fine.air": "pm25",
    "cloud.smarthq.domain.sensor.particles.10um": "pm10",
    "cloud.smarthq.domain.sensor.particles.1um": "pm1",
    "cloud.smarthq.domain.sensor.particles.4um": "pm4",
    "cloud.smarthq.domain.sensor.particles.fine.air.index": "aqi",
    "cloud.smarthq.domain.sensor.particles.10um.index": "aqi",
    "cloud.smarthq.domain.sensor.particles.1um.index": "aqi",
    "cloud.smarthq.domain.sensor.particles.4um.index": "aqi",
}

# meter domainType → (HA unit, HA SensorDeviceClass)
METER_DOMAIN_UNIT_CLASS: dict[str, tuple[str, str]] = {
    "cloud.smarthq.domain.energy": ("kWh", "energy"),
    "cloud.smarthq.domain.voltage": ("V", "voltage"),
    "cloud.smarthq.domain.water.cold": ("L", "water"),
    "cloud.smarthq.domain.water.hot": ("L", "water"),
}

# ---------------------------------------------------------------------------
# cooking.mode.v1 parameter support values
# ---------------------------------------------------------------------------

# Values that indicate a cooking parameter is supported (required/optional/defaulted)
COOKING_PARAM_SUPPORTED: frozenset[str] = frozenset({
    "cloud.smarthq.type.parameter.required",
    "cloud.smarthq.type.parameter.optional",
    "cloud.smarthq.type.parameter.defaulted",
})

# ---------------------------------------------------------------------------
# Common Alert types
# ---------------------------------------------------------------------------

COMMON_ALERTS: frozenset[str] = frozenset({
    "cloud.smarthq.alert.contractormode.disabled",
    "cloud.smarthq.alert.ota.update.critical",
    "cloud.smarthq.alert.enhancedfeature.disabled",
    "cloud.smarthq.alert.enhancedfeature.enabled",
    "cloud.smarthq.alert.enhancedfeature.initialized",
    "cloud.smarthq.alert.enhancedfeature.supportedchanged",
    "cloud.smarthq.alert.ota.update",
})

# ---------------------------------------------------------------------------
# Helper: retrieve services from coordinator data
# ---------------------------------------------------------------------------


def get_device_services(coordinator_data: dict, device_id: str) -> list[dict]:
    """Return the services array for a given device_id from coordinator data."""
    item = coordinator_data.get(device_id, {}).get("item", {})
    services = item.get("services", [])
    return services if isinstance(services, list) else []


def get_services_by_type(
    coordinator_data: dict,
    device_id: str,
    service_type: str,
) -> list[dict]:
    """Return all services of a specific serviceType for a device."""
    return [
        svc
        for svc in get_device_services(coordinator_data, device_id)
        if svc.get("serviceType") == service_type
    ]


def get_entity_name(device_nickname: str, svc: dict, suffix: str = "") -> str:
    """Generate a human-readable entity name from a service's domainType.

    Example:
        domain = "cloud.smarthq.domain.cooking.food.salmon"
        → label = "Salmon"
        → entity name = "{nickname} Salmon {suffix}".strip()
    """
    domain: str = svc.get("domainType", "")
    domain_label = domain.split(".")[-1].replace("_", " ").title()
    parts = [device_nickname, domain_label]
    if suffix:
        parts.append(suffix)
    return " ".join(p for p in parts if p)


def make_unique_id(device_id: str, service_id: str, suffix: str) -> str:
    """Build a stable, collision-free unique_id for an entity.

    Format: {device_id}_{service_id}_{suffix}
    """
    return f"{device_id}_{service_id}_{suffix}"


# ---------------------------------------------------------------------------
# SERVICE_MAPPING: Allowlist of all supported serviceTypes
#
# Each entry defines how a serviceType maps to HA platform(s).
#   type:     "standard" → handled by a shared generic handler
#             "custom"   → handled by dedicated hand-written entity class(es)
#   platform: HA platform string or list of strings
#   handler:  class name (string reference) used by the platform setup logic
#   params:   optional extra kwargs passed to the handler (e.g. device_class)
#
# serviceTypes NOT in this dict are silently ignored (never exposed to HA).
# This prevents accidental exposure of private/unsupported services such as
# factory_reset, assistant, autoreorder, etc.
# ---------------------------------------------------------------------------

SERVICE_MAPPING: dict[str, dict] = {
    # ------------------------------------------------------------------
    # STANDARD mappings — generic handlers, no custom entity class needed
    # ------------------------------------------------------------------

    # switch
    TOGGLE_SERVICE: {
        "type": "standard",
        "platform": "switch",
        "handler": "StandardToggleSwitch",
    },
    LAUNDRY_TOGGLE_V2_SERVICE: {
        "type": "standard",
        "platform": "switch",
        "handler": "StandardLaundryToggleV2Switch",
    },

    # binary_sensor
    DOOR_SERVICE: {
        "type": "standard",
        "platform": "binary_sensor",
        "handler": "StandardDoorBinarySensor",
        "params": {"device_class": "door"},
    },
    FILTER_SERVICE: {
        "type": "standard",
        "platform": "binary_sensor",
        "handler": "StandardFilterBinarySensor",
        "params": {"device_class": "problem"},
    },
    CONNECT_SERVICE: {
        "type": "standard",
        "platform": "binary_sensor",
        "handler": "StandardConnectBinarySensor",
        "params": {"device_class": "connectivity"},
    },
    ENHANCEDFEATURE_SERVICE: {
        "type": "standard",
        "platform": "binary_sensor",
        "handler": "StandardEnhancedFeatureBinarySensor",
    },
    DRYER_RACK_SERVICE: {
        "type": "standard",
        "platform": "binary_sensor",
        "handler": "StandardDryerRackBinarySensor",
    },

    # sensor (read-only)
    TEMPERATURE_SERVICE: {
        "type": "standard",
        "platform": ["sensor", "select"],
        "handler": "StandardTemperature",
    },
    INTEGER_SERVICE: {
        "type": "standard",
        "platform": ["sensor", "number"],
        "handler": "StandardInteger",
    },
    DOUBLE_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardDoubleSensor",
    },
    STRING_SERVICE: {
        "type": "standard",
        "platform": ["sensor", "text"],
        "handler": "StandardString",
    },
    METER_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardMeterSensor",
    },
    BATTERY_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardBatterySensor",
    },
    CYCLETIMER_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardCycleTimerSensor",
    },
    STOPWATCH_SERVICE: {
        "type": "standard",
        "platform": ["sensor", "binary_sensor"],
        "handler": "StandardStopwatch",
    },
    ENVIRONMENTAL_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardEnvironmentalSensor",
    },
    DELAYWINDOW_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardDelayWindowSensor",
    },
    POWER_USAGE_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardPowerUsageSensor",
    },
    VOLUME_LIQUID_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardVolumeLiquidSensor",
    },
    SCALE_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardScaleSensor",
    },
    OUTDOORUNIT_INFO_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardOutdoorUnitInfoSensor",
    },
    SMARTDISPENSE_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardSmartDispenseSensor",
    },
    DRYER_VENT_HEALTH_MODE_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardDryerVentHealthSensor",
    },
    LAUNDRY_BULKTANK_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardLaundryBulkTankSensor",
    },
    LAUNDRY_PETHAIR_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardLaundryPetHairSensor",
    },
    DISHWASHER_RINSE_AGENT_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardDishwasherRinseAgentSensor",
    },
    COOKTOP_CLOSEDLOOP_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardCooktopClosedLoopSensor",
    },
    COOKTOP_SOUSVIDE_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardCooktopSousVideSensor",
    },
    DRYER_CONFIG_CYCLE_V1_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardDryerConfigCycleSensor",
    },
    DRYER_MYCYCLE_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardDryerMyCycleSensor",
    },
    WASHER_CONFIG_CYCLE_V1_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardWasherConfigCycleSensor",
    },
    WASHER_MYCYCLE_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardWasherMyCycleSensor",
    },
    DEMANDRESPONSE_STATE_V1_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardDemandResponseStateSensor",
    },
    OVEN_MENUTREE_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardOvenMenuTreeSensor",
    },
    LAUNDRY_COMMERCIAL_V1_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardLaundryCommercialSensor",
    },
    LAUNDRY_DOWNLOADABLECYCLE_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardLaundryDownloadableCycleSensor",
    },
    ESPRESSOMAKER_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardEspressoMakerSensor",
    },
    SOURDOUGHSTARTER_SERVICE: {
        "type": "standard",
        "platform": "sensor",
        "handler": "StandardSourdoughStarterSensor",
    },

    # select
    MODE_SERVICE: {
        "type": "standard",
        "platform": ["select", "switch"],
        "handler": "StandardMode",
    },
    STAINREMOVAL_SERVICE: {
        "type": "standard",
        "platform": "select",
        "handler": "StandardStainRemovalSelect",
    },
    FLEXDISPENSE_SERVICE: {
        "type": "standard",
        "platform": ["select", "binary_sensor"],
        "handler": "StandardFlexDispense",
    },

    # button
    TRIGGER_SERVICE: {
        "type": "standard",
        "platform": "button",
        "handler": "StandardTriggerButton",
    },

    # ------------------------------------------------------------------
    # CUSTOM mappings — dedicated hand-written entity classes
    # ------------------------------------------------------------------

    # FIRMWARE_SERVICE is intentionally excluded (blocked):
    # Firmware update is a sensitive operation that should not be exposed
    # as a general HA entity. Kept here as a comment for documentation.
    # FIRMWARE_SERVICE → blocked

    COOKING_MODE_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "select", "button", "number"],
        "handler": "SmartHQCookingMode",
    },
    COOKING_STATE_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "button"],
        "handler": "SmartHQCookingState",
    },
    COOKING_OVEN_PROBE_TEMP_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "binary_sensor"],
        "handler": "SmartHQCookingOvenProbeTemp",
    },
    COOKING_BURNER_STATUS_SERVICE: {
        "type": "custom",
        "platform": "sensor",
        "handler": "SmartHQCookingBurnerStatus",
    },
    COOKING_ADVANTIUM_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "binary_sensor", "button"],
        "handler": "SmartHQCookingAdventium",
    },
    BREW_MODE_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "button"],
        "handler": "SmartHQBrewMode",
    },
    COFFEEBREWER_V1_SERVICE: {
        "type": "custom",
        "platform": ["button", "select", "binary_sensor"],
        "handler": "SmartHQCoffeeBrewerV1",
    },
    COFFEEBREWER_V2_SERVICE: {
        "type": "custom",
        "platform": ["button", "select", "binary_sensor"],
        "handler": "SmartHQCoffeeBrewerV2",
    },
    LAUNDRY_STATE_SERVICE: {
        "type": "custom",
        "platform": "sensor",
        "handler": "SmartHQLaundryState",
    },
    LAUNDRY_MODE_SERVICE: {
        "type": "custom",
        "platform": "select",
        "handler": "SmartHQLaundryMode",
    },
    LAUNDRY_PRICEMENU_V1_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "binary_sensor"],
        "handler": "SmartHQLaundryPriceMenu",
    },
    DISHWASHER_STATE_V1_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "button"],
        "handler": "SmartHQDishwasherStateV1",
    },
    DISHWASHER_STATE_SERVICE: {
        "type": "custom",
        "platform": "binary_sensor",
        "handler": "SmartHQDishwasherState",
    },
    DISHWASHER_MODE_V1_SERVICE: {
        "type": "custom",
        "platform": "select",
        "handler": "SmartHQDishwasherModeV1",
    },
    DISHWASHER_CUSTOM_CYCLE_SERVICE: {
        "type": "custom",
        "platform": ["select", "binary_sensor"],
        "handler": "SmartHQDishwasherCustomCycle",
    },
    DISHWASHER_FAVORITES_V1_SERVICE: {
        "type": "custom",
        "platform": "select",
        "handler": "SmartHQDishwasherFavoritesV1",
    },
    DESCALE_V1_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "binary_sensor"],
        "handler": "SmartHQDescaleV1",
    },
    DISH_CONFIG_V1_SERVICE: {
        "type": "custom",
        "platform": "binary_sensor",
        "handler": "SmartHQDishConfigV1",
    },
    DISHDRAWER_MODE_LEGACY_SERVICE: {
        "type": "custom",
        "platform": ["select", "binary_sensor", "number"],
        "handler": "SmartHQDishDrawerModeLegacy",
    },
    DISHDRAWER_STATE_LEGACY_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "binary_sensor", "button"],
        "handler": "SmartHQDishDrawerStateLegacy",
    },
    DISHWASHER_STATE_LEGACY_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "binary_sensor"],
        "handler": "SmartHQDishwasherStateLegacy",
    },
    REMOTECYCLESELECTION_SERVICE: {
        "type": "custom",
        "platform": ["binary_sensor", "select"],
        "handler": "SmartHQRemoteCycleSelection",
    },
    DEMANDRESPONSE_EVENT_V1_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "binary_sensor"],
        "handler": "SmartHQDemandResponseEvent",
    },
    PIZZAOVEN_STATE_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "binary_sensor"],
        "handler": "SmartHQPizzaOvenState",
    },
    PIZZAOVEN_REMINDERS_SERVICE: {
        "type": "custom",
        "platform": "binary_sensor",
        "handler": "SmartHQPizzaOvenReminders",
    },
    MIXER_SERVICE: {
        "type": "custom",
        "platform": ["sensor", "button"],
        "handler": "SmartHQMixer",
    },
    OVEN_FLEXTIMER_SERVICE: {
        "type": "custom",
        "platform": "sensor",
        "handler": "SmartHQOvenFlexTimer",
    },
    COLOR_SERVICE: {
        "type": "custom",
        "platform": "light",
        "handler": "SmartHQColorLight",
    },
    COOKING_PRORANGE_ACCENT_LIGHT_SERVICE: {
        "type": "custom",
        "platform": "light",
        "handler": "SmartHQAccentLight",
    },
    THERMOSTAT_SERVICE: {
        "type": "custom",
        "platform": "climate",
        "handler": "SmartHQThermostatClimate",
    },
    WATERHEATER_SERVICE: {
        "type": "custom",
        "platform": "water_heater",
        "handler": "SmartHQWaterHeater",
    },
}


def get_service_mapping(service_type: str) -> dict | None:
    """Return the SERVICE_MAPPING entry for a serviceType, or None if not mapped.

    serviceTypes not in SERVICE_MAPPING are silently ignored — never exposed to HA.
    """
    return SERVICE_MAPPING.get(service_type)


def is_platform_mapped(service_type: str, platform: str) -> bool:
    """Return True if the given serviceType is mapped to the specified HA platform."""
    mapping = get_service_mapping(service_type)
    if mapping is None:
        return False
    platforms = mapping["platform"]
    if isinstance(platforms, list):
        return platform in platforms
    return platforms == platform


def get_mapped_service_types(platform: str) -> list[str]:
    """Return all serviceTypes that are mapped to the given HA platform."""
    result = []
    for svc_type, mapping in SERVICE_MAPPING.items():
        platforms = mapping["platform"]
        if isinstance(platforms, list):
            if platform in platforms:
                result.append(svc_type)
        elif platforms == platform:
            result.append(svc_type)
    return result


def is_cooking_mode_domain(domain: str) -> bool:
    """Return True if this domainType represents a startable cooking mode.

    Covers two families of cooking.mode.v1 services:
      • Smoker: cloud.smarthq.domain.cooking.food.*  (e.g. .food.salmon)
                cloud.smarthq.domain.cooking.custom.*
      • Toaster Oven / Oven / Microwave:
                cloud.smarthq.domain.cooking.<mode>  (e.g. .bake, .airfry, .toast)
                cloud.smarthq.domain.cooking.warm.auto
                cloud.smarthq.domain.cooking.bake.auto.*  (Microwave auto-cook)
                cloud.smarthq.domain.cooking.convection.*

    Excluded (not startable cooking modes):
      • cloud.smarthq.domain.cooking          (generic cooking state domain)
    """
    if not domain:
        return False
    d = domain.lower()
    # Must start with the cooking prefix
    prefix = "cloud.smarthq.domain.cooking."
    if not d.startswith(prefix):
        return False
    tail = d[len(prefix):]
    # Exclude the bare "cooking" domain used by cooking.state.v1
    if not tail:
        return False
    # Explicit Smoker patterns
    if tail.startswith("food.") or tail.startswith("custom"):
        return True
    # Toaster Oven / Oven patterns (all cooking.<mode> tails)
    # Exclude "state" sub-tail just in case
    if tail.startswith("state"):
        return False
    return True
