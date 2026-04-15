# SmartHQ Home Assistant Integration — Service-Based Architecture

## Overview

### Goals
Implement a universal integration that automatically supports **all SmartHQ appliances**.
Instead of hardcoding device types (DeviceType), dynamically analyze each appliance's **service list** and **alert list** to auto-generate HA entities.

### Core Principles
1. **Zero DeviceType hardcoding** — Code like `if "smoker" in device_type` must not exist
2. **Service-driven entity generation** — The appliance's `services[]` array is the entity specification
3. **Alert-driven notifications** — Use the appliance's `alertTypes[]` array to generate HA notifications/events
4. **Graceful degradation** — Unknown services/alerts are silently ignored; known ones work normally
5. **Universal compatibility** — New appliances added by GE Appliances are supported automatically, without code changes

---

## Implementation Roadmap

Based on the SmartHQ documentation structure (`https://docs.smarthq.com/data-model/`), the implementation is divided into 3 stages:

```
Stage 1: Common Services  (current focus)
  └── Implement 22 services common to all appliances
  └── Implemented first → immediately applies to all registered devices

Stage 2: Common Alerts
  └── Implement 7 common alerts that can occur on any appliance
  └── Expressed as HA Notifications, Events, or Binary Sensors

Stage 3: Device-Specific Services (~80+ ServiceTypes)
  └── Services exclusive to specific appliances (cooking, laundry, refrigeration, AC, etc.)
  └── Extended on top of the Common Services foundation
```

---

## Stage 1: Common Services (22 entries)

Services defined in the SmartHQ `Common > Services` page that are common to all appliances.
Implementing these services instantly applies to **all currently registered devices and any future devices**.

| # | Common Service Name | ServiceType | DomainType | HA Platform | Notes |
|---|---|---|---|---|---|
| 1 | Appliance Air Quality Color Scheme Mode | `mode` | `airquality.colorscheme` | **select** | Air quality color setting |
| 2 | Appliance Contractor Mode Toggle | `toggle` | `lock` | **switch** | 🔒 Property Mgmt Only |
| 3 | Appliance Cost Comfort Integer | `integer` | `savings.strategy` | **number** | Energy savings strategy |
| 4 | Appliance Demand Response Event V1 | `demandresponse.event.v1` | `demandresponse` | future | DR event read/write |
| 5 | Appliance Demand Response State V1 | `demandresponse.state.v1` | `demandresponse` | **sensor** | DR status |
| 6 | Appliance Enhanced Feature V1 | `enhancedfeature.v1` | `enhanced.feature` | future | Digital feature activation |
| 7 | Appliance Env Temperature Sensor | `environmental.sensor` | `sensor.temperature.environmental` | **sensor** | Ambient temperature |
| 8 | Appliance Fine Air Particles Sensor | `environmental.sensor` | `sensor.particles.fine.air` | **sensor** | Fine particulate matter |
| 9 | Appliance Firmware V1 (Appliance) | `firmware.v1` | `firmware` / `device.appliance` | **update** | Appliance firmware update |
| 10 | Appliance Humidity Sensor | `environmental.sensor` | `sensor.humidity` | **sensor** | Relative humidity |
| 11 | Appliance Linux Firmware V1 | `firmware.v1` | `firmware` / `device.linux` | **update** | Linux firmware |
| 12 | Appliance Override Toggle | `toggle` | `override` | **switch** | Energy override |
| 13 | Appliance PM10 Sensor | `environmental.sensor` | `sensor.particles.10um` | **sensor** | PM10 particulates |
| 14 | Appliance PM1 Sensor | `environmental.sensor` | `sensor.particles.1um` | **sensor** | PM1 particulates |
| 15 | Appliance PM4 Sensor | `environmental.sensor` | `sensor.particles.4um` | **sensor** | PM4 particulates |
| 16 | Appliance Pricingstructure | `pricingstructure` | `pricingstructure.electrical` | future | Electricity pricing structure |
| 17 | Appliance Relative Fine Air Particles | `environmental.sensor` | `sensor.particles.fine.air.index` | **sensor** | Fine particulate index |
| 18 | Appliance Relative PM10 | `environmental.sensor` | `sensor.particles.10um.index` | **sensor** | PM10 index |
| 19 | Appliance Relative PM1 | `environmental.sensor` | `sensor.particles.1um.index` | **sensor** | PM1 index |
| 20 | Appliance Relative PM4 | `environmental.sensor` | `sensor.particles.4um.index` | **sensor** | PM4 index |
| 21 | Appliance Reset Wifi Trigger | `trigger` | `reset` | **button** | 🔒 Property Mgmt Only |
| 22 | Appliance Resource Management kWh | `meter` | `energy` | **sensor** | Energy (kWh) metering |
| 23 | Appliance Set Control Lock Toggle | `toggle` | `controls.lock` | **switch** | UI control lock |
| 24 | Appliance Set Model Number | `string` | `model` | ignored | 🔒 Property Mgmt Only |
| 25 | Appliance Temperature Units Mode | `mode` | `temperatureunits` | **select** | °F / °C unit setting |
| 26 | Appliance Time of Use Season 1-4 | `timeofuse.v1` | `season.1~4` | future | Time-of-use pricing |
| 27 | Appliance VOC Sensor | `environmental.sensor` | `sensor.voc` | **sensor** | VOC organic compounds |
| 28 | Appliance Wi-Fi Firmware V1 | `firmware.v1` | `firmware` / `device.wifi` | **update** | WiFi firmware |
| 29 | Appliance Wifi Signal Strength | `integer` | `rssi` | **sensor** | WiFi signal strength |

**Key observation**: Common Services are actually composed of just **8 base ServiceTypes**:
`toggle`, `mode`, `environmental.sensor`, `firmware.v1`, `integer`, `meter`, `trigger`, `string`.
Implementing these 8 ServiceTypes covers all Common Services automatically.

---

## Stage 2: Common Alerts (7 entries)

Alerts defined in the SmartHQ `Common > Alerts` page that can occur on any appliance.

| Alert Type | Description | HA Implementation |
|---|---|---|
| `cloud.smarthq.alert.contractormode.disabled` | Contractor mode deactivated | HA Persistent Notification |
| `cloud.smarthq.alert.ota.update.critical` | Critical update required | HA Persistent Notification + `update` entity |
| `cloud.smarthq.alert.enhancedfeature.disabled` | Feature deactivated | HA Event |
| `cloud.smarthq.alert.enhancedfeature.enabled` | Feature activated | HA Event |
| `cloud.smarthq.alert.enhancedfeature.initialized` | Enhanced Features initialized | HA Event |
| `cloud.smarthq.alert.enhancedfeature.supportedchanged` | Supported features changed | HA Event + coordinator reload |
| `cloud.smarthq.alert.ota.update` | General update available | HA Persistent Notification + `update` entity |

**Implementation approach**: Parse Alert messages received via WebSocket in `ws_client.py`
→ Publish as `smarthq_alert` event on the HA event bus
→ Users can handle freely via HA automations

---

## Stage 3: Device-Specific Services (~80+ ServiceTypes)

Services exclusive to specific appliances, listed in the SmartHQ documentation `Services` tab.
Below is a grouping from the HA implementation perspective.

### 3-A. Generic Data Services (read-only sensors)
| ServiceType | HA Platform | Example Appliances |
|---|---|---|
| `temperature` | **sensor** / **number** | All appliances |
| `cycletimer` | **sensor** | Dishwasher, Washer, Oven |
| `meter` | **sensor** | Energy meter, Refrigerator, Washer |
| `integer` | **sensor** | WiFi signal, config values |
| `double` | **sensor** | Precision measurements |
| `string` | **sensor** / ignored | Model number, etc. |
| `battery` | **sensor** | Battery-powered devices |
| `door` | **binary_sensor** | Refrigerator, Oven |
| `stopwatch` | **sensor** | Timers |

### 3-B. Control Services (bidirectional)
| ServiceType | HA Platform | Example Appliances |
|---|---|---|
| `toggle` | **switch** | All appliances |
| `mode` | **select** / **switch** | All appliances |
| `trigger` | **button** | Washer start, filter reset |
| `thermostat.v1` | **climate** | Air conditioner, Zoneline |

### 3-C. Cooking Service Group
| ServiceType | HA Platform | Example Appliances |
|---|---|---|
| `cooking.state.v1` | sensor + button + binary_sensor | Smoker, Oven, Microwave, Toaster Oven |
| `cooking.mode.v1` | select + number + button | All cooking-capable appliances |
| `cooking.mode.multistage` | future | Oven |
| `cooking.advantium` | future | Advantium |
| `cooking.oven.probe.temperature` | sensor + number | Oven |
| `cooking.burner.status.v1` | sensor | Gas/induction cooktop |
| `cooktop.closedloop` | number | Induction cooktop |
| `cooktop.sousvide` | number | Sous vide feature |
| `oven.flextimer` | sensor | Oven timer |

### 3-D. Laundry Service Group
| ServiceType | HA Platform | Example Appliances |
|---|---|---|
| `laundry.state.v1` | sensor + button | Washer, Dryer |
| `laundry.mode.v1` | select | Wash cycle |
| `laundry.toggle.v2` | switch | Wash options |
| `dryer.vent.health.mode` | sensor | Dryer vent |
| `dryer.rack` | binary_sensor | Drying rack detection |
| `remotecycleselection` | select | Remote cycle selection |

### 3-E. Dishwasher Service Group
| ServiceType | HA Platform | Example Appliances |
|---|---|---|
| `dishwasher.state.v1` | sensor | Dishwasher |
| `dishwasher.mode.v1` | select | Dishwasher |
| `dishwasher.state.legacy` | sensor | Legacy dishwasher |

### 3-F. Coffee/Beverage Service Group
| ServiceType | HA Platform | Example Appliances |
|---|---|---|
| `coffeebrewer.v1` | select + button | Coffee Brewer |
| `coffeebrewer.v2` | select + button | Coffee Brewer v2 |
| `brew.mode.v1` | select | Brew mode |
| `espressomaker.v1` | select + button | Espresso Maker |

### 3-G. Refrigerator-Specific Service Group
| ServiceType | HA Platform | Example Appliances |
|---|---|---|
| `temperature` (writable) | number | Fresh food/freezer temp setpoint |
| `flexdispense` | select | Water/ice dispenser |
| `filter.v1` | sensor + button | Water filter |

### 3-H. Energy/IoT Service Group
| ServiceType | HA Platform | Example Appliances |
|---|---|---|
| `demandresponse.event.v1` | future | Energy management |
| `demandresponse.state.v1` | sensor | Energy management |
| `power.usage` | sensor | Power consumption |
| `timeofuse.v1` | future | Time-of-use pricing |
| `photovoltaicpanel` | sensor | Solar panels |

### 3-I. Other Specialized Service Group
| ServiceType | HA Platform | Example Appliances |
|---|---|---|
| `waterheater.v1` | select + number | Water heater |
| `descale.v1` | button | Descaling |
| `filter.v1` | sensor + button | Filter status |
| `scale.v1` | sensor | Scale (mixer) |
| `mixer.v1` | select + number | Stand Mixer |
| `sourdoughstarter.v1` | select | Sourdough Starter |
| `pizzaoven.state` | sensor | Pizza Oven |
| `smartdispense` | select | Auto detergent dispense |
| `volume.liquid.v1` | sensor | Liquid volume |

---

## Architecture Design

### Current Structure (Problems)

```
coordinator.py
  └── _guess_kind()  ← DeviceType-based guessing (root problem)
       ↓
switch.py, select.py, sensor.py, number.py, button.py
  └── Each file decides whether to create entities by comparing device_type strings
       ← Hardcoded "smoker", "oven", "coffeebrewer"
```

**Problem**: Adding a new appliance (Toaster Oven, Refrigerator, etc.) requires modifying every file.

### Target Structure (Service-based)

```
coordinator.py
  └── No change needed (already fetches items with services[] array)

service_registry.py  ← NEW
  └── SERVICE_HANDLERS: serviceType → (platform, handler_class)
  └── DOMAIN_HINTS: domainType → additional context (e.g., brightness → switch)

Each Platform File (switch.py, select.py, sensor.py, ...)
  └── Iterate over device services[]
  └── Check service_registry whether service is handled
  └── If handled, create Entity — no DeviceType check
```

---

## New File Structure

```
custom_components/smarthq/
├── __init__.py              (unchanged)
├── api.py                   (unchanged)
├── coordinator.py           (improved: remove _guess_kind(), add helper functions)
├── ws_client.py             (improved: generic service command + alert reception)
│
├── service_registry.py      ← NEW: Central service → platform mapping registry
│
├── switch.py                ← Refactored: toggle + mode(brightness/lock) service-based
├── select.py                ← Refactored: mode + cooking.mode.v1 service-based
├── sensor.py                ← Refactored: temperature/cycletimer/meter/integer/environmental service-based
├── number.py                ← Refactored: temperature(settable) + cooking.mode.v1 parameters
├── button.py                ← Refactored: trigger + cooking.state.v1 commands
├── binary_sensor.py         ← Refactored: door + cooking.state.v1.remoteEnable
│
└── docs/
    └── ARCHITECTURE.md      ← This file
```

---

## service_registry.py Design

```python
# service_registry.py

# Declares which platform handles each serviceType
# Each entry: (platform, additional_hints)

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

# domainType is brightness → handled as switch (on/off)
BRIGHTNESS_DOMAINS = {
    "cloud.smarthq.domain.brightness",
    "cloud.smarthq.domain.light",
}

# domainType is binary lock → handled as switch
LOCK_DOMAINS = {
    "cloud.smarthq.domain.controls.lock",
    "cloud.smarthq.domain.lock",
    "cloud.smarthq.domain.override",
}

# mode services that are read-only by domain (treated as sensor)
READONLY_MODE_DOMAINS = {
    "cloud.smarthq.domain.icemaker",  # display-only
}

# Common Alert types
COMMON_ALERTS = {
    "cloud.smarthq.alert.contractormode.disabled",
    "cloud.smarthq.alert.ota.update.critical",
    "cloud.smarthq.alert.enhancedfeature.disabled",
    "cloud.smarthq.alert.enhancedfeature.enabled",
    "cloud.smarthq.alert.enhancedfeature.initialized",
    "cloud.smarthq.alert.enhancedfeature.supportedchanged",
    "cloud.smarthq.alert.ota.update",
}
```

---

## Entity Generation Logic

### switch.py

```python
def _iter_switch_services(coordinator, device_id):
    """Yield switch entities for toggle services and mode services with brightness/lock domains."""
    services = get_services(coordinator, device_id)
    for svc in services:
        stype = svc.get("serviceType", "")
        domain = svc.get("domainType", "")
        cmds = svc.get("supportedCommands", [])
        
        # toggle service → switch
        if stype == TOGGLE_SERVICE:
            if "cloud.smarthq.command.toggle.set" in cmds:
                yield SmartHQToggleSwitch(coordinator, device_id, svc)
        
        # mode service with brightness/lock domain → switch (on/off)
        elif stype == MODE_SERVICE and domain in BRIGHTNESS_DOMAINS | LOCK_DOMAINS:
            if "cloud.smarthq.command.mode.set" in cmds:
                yield SmartHQModeSwitch(coordinator, device_id, svc)
```

### select.py

```python
def _iter_select_services(coordinator, device_id):
    """Yield select entities for mode services and cooking.mode.v1 services."""
    services = get_services(coordinator, device_id)
    for svc in services:
        stype = svc.get("serviceType", "")
        domain = svc.get("domainType", "")
        cmds = svc.get("supportedCommands", [])
        
        # mode service (excluding brightness/lock) → select
        if stype == MODE_SERVICE:
            if domain not in BRIGHTNESS_DOMAINS | LOCK_DOMAINS:
                if "cloud.smarthq.command.mode.set" in cmds:
                    yield SmartHQModeSelect(coordinator, device_id, svc)
        
        # cooking.mode.v1 → Cook Mode select (separate aggregation logic needed)
        elif stype == COOKING_MODE_SERVICE:
            pass  # see aggregation pattern below
```

**cooking.mode.v1 aggregation pattern:**
```python
# Aggregate all cooking.mode.v1 services for a device into one Select
cooking_modes = [
    svc for svc in services 
    if svc.get("serviceType") == COOKING_MODE_SERVICE
]
if cooking_modes:
    yield SmartHQCookModeSelect(coordinator, device_id, cooking_modes)
    # + SEND TO button from cooking.state.v1 (start command)
    # + cavityTemperature/cookTime number entities
```

### sensor.py

```python
def _iter_sensor_services(coordinator, device_id):
    services = get_services(coordinator, device_id)
    for svc in services:
        stype = svc.get("serviceType", "")
        
        # temperature service (read-only; settable → handled by number.py)
        if stype == TEMPERATURE_SERVICE:
            cmds = svc.get("supportedCommands", [])
            if "cloud.smarthq.command.temperature.set" not in cmds:
                yield SmartHQTemperatureSensor(coordinator, device_id, svc)
        
        # cycletimer → remaining time sensor
        elif stype == CYCLETIMER_SERVICE:
            yield SmartHQCycleTimerSensor(coordinator, device_id, svc)
        
        # meter → energy/voltage sensor
        elif stype == METER_SERVICE:
            yield SmartHQMeterSensor(coordinator, device_id, svc)
        
        # integer → integer sensor (RSSI, etc.)
        elif stype == INTEGER_SERVICE:
            yield SmartHQIntegerSensor(coordinator, device_id, svc)
        
        # environmental.sensor → air quality sensor
        elif stype == ENVIRONMENTAL_SERVICE:
            yield SmartHQEnvironmentalSensor(coordinator, device_id, svc)
        
        # cooking.state.v1 → cooking state sensor (runStatus, cookingStatus)
        elif stype == COOKING_STATE_SERVICE:
            yield SmartHQCookingStateSensor(coordinator, device_id, svc)
```

### number.py

```python
def _iter_number_services(coordinator, device_id):
    services = get_services(coordinator, device_id)
    for svc in services:
        stype = svc.get("serviceType", "")
        
        # temperature service + set command available → settable temperature Number
        if stype == TEMPERATURE_SERVICE:
            cmds = svc.get("supportedCommands", [])
            if "cloud.smarthq.command.temperature.set" in cmds:
                yield SmartHQTemperatureNumber(coordinator, device_id, svc)
        
        # cooking.mode.v1 cavityTemperature parameter → target temp Number
        # cooking.mode.v1 cookTime parameter → cook time Number
        elif stype == COOKING_MODE_SERVICE:
            config = svc.get("config", {})
            if config.get("cavityTemperatureSupported") in [
                "cloud.smarthq.type.parameter.required",
                "cloud.smarthq.type.parameter.optional",
                "cloud.smarthq.type.parameter.defaulted",
            ]:
                yield SmartHQCavityTempNumber(coordinator, device_id, svc)
            if config.get("cookTimeSupported") in [
                "cloud.smarthq.type.parameter.required",
                "cloud.smarthq.type.parameter.optional",
                "cloud.smarthq.type.parameter.defaulted",
            ]:
                yield SmartHQCookTimeNumber(coordinator, device_id, svc)
```

### button.py

```python
def _iter_button_services(coordinator, device_id):
    services = get_services(coordinator, device_id)
    
    for svc in services:
        stype = svc.get("serviceType", "")
        cmds = svc.get("supportedCommands", [])
        
        # trigger service → button
        if stype == TRIGGER_SERVICE:
            yield SmartHQTriggerButton(coordinator, device_id, svc)
        
        # cooking.state.v1 → Stop, Pause, Resume buttons
        elif stype == COOKING_STATE_SERVICE:
            if "cloud.smarthq.command.cooking.state.v1.stop" in cmds:
                yield SmartHQStopButton(coordinator, device_id, svc)
            if "cloud.smarthq.command.cooking.state.v1.pause" in cmds:
                yield SmartHQPauseButton(coordinator, device_id, svc)
            if "cloud.smarthq.command.cooking.state.v1.resume" in cmds:
                yield SmartHQResumeButton(coordinator, device_id, svc)
    
    # Devices with cooking.mode.v1 + start command → SEND TO button
    cooking_modes = [
        svc for svc in services
        if svc.get("serviceType") == COOKING_MODE_SERVICE
        and "cloud.smarthq.command.cooking.mode.v1.start" in svc.get("supportedCommands", [])
    ]
    if cooking_modes:
        yield SmartHQSendToButton(coordinator, device_id, cooking_modes)
```

### binary_sensor.py

```python
def _iter_binary_sensor_services(coordinator, device_id):
    services = get_services(coordinator, device_id)
    for svc in services:
        stype = svc.get("serviceType", "")
        
        # firmware.v1 → update available binary sensor
        if stype == FIRMWARE_SERVICE:
            yield SmartHQFirmwareBinarySensor(coordinator, device_id, svc)
        
        # cooking.state.v1 → remoteEnable binary sensor
        elif stype == COOKING_STATE_SERVICE:
            yield SmartHQRemoteEnableSensor(coordinator, device_id, svc)
        
        # door service → door open binary sensor
        elif stype == DOOR_SERVICE:
            yield SmartHQDoorSensor(coordinator, device_id, svc)
```

---

## Entity Unique ID Design

```
{device_id}_{service_id}_{entity_suffix}
```

Examples:
- Toggle switch: `abc123_svcdef456_toggle`
- Cook Mode Select: `abc123_svcdef456_cook_mode_select`
- Cavity Temp Number: `abc123_svcdef456_cavity_temp`
- Stop Button: `abc123_svcdef456_stop`
- Remote Enable Sensor: `abc123_svcdef456_remote_enable`

**Important**: Using `serviceId` means no unique_id collision even when a device has multiple services of the same type.

---

## Entity Name Generation Rule

```python
def get_entity_name(device_nickname, svc, suffix=""):
    domain = svc.get("domainType", "")
    # "cloud.smarthq.domain.cooking.food.salmon" → "Salmon"
    domain_label = domain.split(".")[-1].replace("_", " ").title()
    
    if suffix:
        return f"{device_nickname} {domain_label} {suffix}"
    return f"{device_nickname} {domain_label}"
```

---

## ws_client.py Improvements

### Current Problem
```python
# Hardcoded device type
"serviceDeviceType": "cloud.smarthq.device.smoker"
```

### Proposed Solution
```python
async def async_send_service_command(
    self,
    device_id: str,
    service: dict,        # Full service object (contains serviceDeviceType)
    command_type: str,
    command_params: dict = None,
) -> dict:
    """Generic service command sender."""
    payload = {
        "kind": "service#command",
        "deviceId": device_id,
        "serviceType": service["serviceType"],
        "domainType": service["domainType"],
        "serviceDeviceType": service["serviceDeviceType"],  # dynamic, not hardcoded
        "command": {
            "commandType": command_type,
            **(command_params or {}),
        },
    }
    return await self._api.async_send_command(device_id, payload)
```

### Alert Reception Handling
```python
# ws_client.py — when WebSocket message is received
def _handle_ws_message(self, message: dict):
    kind = message.get("kind", "")
    
    if kind == "publish#event":
        # Service state update
        self._handle_service_update(message)
    
    elif kind == "alert#item":
        # Alert received → publish to HA Event Bus
        alert_type = message.get("alertType", "")
        device_id = message.get("deviceId", "")
        self.hass.bus.async_fire(
            "smarthq_alert",
            {
                "device_id": device_id,
                "alert_type": alert_type,
                "data": message,
            }
        )
```

---

## coordinator.py Improvements

### Remove
- `_guess_kind()` function — deleted entirely

### Add
- Service lookup helper functions

```python
def get_device_services(coordinator_data: dict, device_id: str) -> list:
    """Return the services array for a given device_id."""
    item = coordinator_data.get(device_id, {}).get("item", {})
    return item.get("services", [])

def get_services_by_type(coordinator_data: dict, device_id: str, service_type: str) -> list:
    """Filter services by a specific serviceType."""
    return [
        svc for svc in get_device_services(coordinator_data, device_id)
        if svc.get("serviceType") == service_type
    ]
```

---

## Expected Entity Output per Appliance

### Smoker (`cloud.smarthq.device.smoker`)
| Service | Generated Entities |
|---|---|
| `cooking.state.v1` | Cooking status sensor, Remote Enable sensor, Stop button |
| `cooking.mode.v1` × N (chicken, salmon, ...) | Cook Mode Select, Cavity Temp Number, Cook Time Number, SEND TO button |
| `temperature` × 2 (probe, cavity) | Probe/cavity temperature sensors |
| `toggle` (controls.lock) | Control Lock switch |
| `firmware.v1` | Firmware update sensor |
| `integer` (rssi) | WiFi signal strength sensor |

### Toaster Oven (`cloud.smarthq.device.toasteroven`)
| Service | Generated Entities |
|---|---|
| `cooking.state.v1` | Cooking status sensor, Remote Enable sensor, Stop/Pause/Resume buttons |
| `cooking.mode.v1` × N (bake, toast, airfry, ...) | Cook Mode Select, Cavity Temp Number, Cook Time Number, SEND TO button |
| `toggle` | Various switches |
| `firmware.v1` | Firmware update |
| `integer` (rssi) | WiFi signal strength |

### Refrigerator (`cloud.smarthq.device.refrigerator`)
| Service | Generated Entities |
|---|---|
| `temperature` × 2 (settable setpoints) | Fresh Food Temp, Freezer Temp Numbers |
| `mode` (icemaker) | Icemaker mode Select |
| `toggle` | Icemaker on/off, etc. |
| `door` | Fresh food / freezer door Open Binary Sensor |
| `firmware.v1` | Firmware update |
| `integer` (rssi) | WiFi signal strength |

### Dishwasher (`cloud.smarthq.device.dishwasher`)
| Service | Generated Entities |
|---|---|
| `dishwasher.state.v1` | Wash state sensor |
| `dishwasher.mode.v1` | Wash mode Select |
| `cycletimer` | Remaining time sensor |
| `toggle` | Delay start, etc. |
| `firmware.v1` | Firmware update |
| `integer` (rssi) | WiFi signal strength |

### Washer/Dryer
| Service | Generated Entities |
|---|---|
| `laundry.state.v1` | Laundry state sensor |
| `laundry.mode.v1` | Laundry mode Select |
| `cycletimer` | Remaining time sensor |
| `laundry.toggle.v2` | Toggle options Switch |
| `integer` (rssi) | WiFi signal strength |

### Air Conditioner
| Service | Generated Entities |
|---|---|
| `thermostat.v1` | Climate Entity |
| `toggle` | Power Switch |
| `mode` | Operation mode Select |
| `temperature` | Current temperature sensor |
| `firmware.v1` | Firmware update |
| `integer` (rssi) | WiFi signal strength |

### Coffee Brewer
| Service | Generated Entities |
|---|---|
| `coffeebrewer.v1` or `coffeebrewer.v2` | Strength/Size Select, Brew button |
| `toggle` | Various switches |
| `integer` (rssi) | WiFi signal strength |

---

## Implementation Phase Plan

### Phase 1: Core Infrastructure
- [ ] Create `service_registry.py` — define serviceType/domainType constants + classification sets
- [ ] `coordinator.py` — remove `_guess_kind()`, add `get_device_services()` helper
- [ ] `ws_client.py` — add `async_send_service_command()` generic function + Alert event publishing

### Phase 2: Stage 1 — Common Services Implementation
- [ ] `switch.py` — refactor based on `toggle` + `mode` (brightness/lock/override domain)
- [ ] `select.py` — refactor based on `mode` service (temperatureunits, airquality.colorscheme, etc.)
- [ ] `sensor.py` — based on `temperature`(read-only) / `cycletimer` / `meter` / `integer` / `environmental.sensor`
- [ ] `number.py` — based on `temperature`(writable) / `integer`(writable)
- [ ] `binary_sensor.py` — based on `firmware.v1` update status
- [ ] `button.py` — based on `trigger` service (WiFi reset, etc.)

### Phase 3: Stage 2 — Common Alerts Implementation
- [ ] `ws_client.py` — Alert message reception and parsing
- [ ] Publish `smarthq_alert` events to HA Event Bus
- [ ] OTA update Alert → `update` entity or persistent notification integration

### Phase 4: Stage 3-A — Cooking Services Implementation
- [ ] `select.py` — add `cooking.mode.v1` aggregation logic (Cook Mode Select)
- [ ] `number.py` — support `cooking.mode.v1` cavityTemp/cookTime parameters
- [ ] `button.py` — `cooking.state.v1` Stop/Pause/Resume, `cooking.mode.v1` SEND TO
- [ ] `sensor.py` — `cooking.state.v1` state sensor (runStatus, cookingStatus, mode)
- [ ] `binary_sensor.py` — `cooking.state.v1` remoteEnable
- [ ] Validation: Smoker + Toaster Oven + Coffee Brewer

### Phase 5: Stage 3-B — Device-Specific Services Implementation
- [ ] Laundry: `laundry.state.v1` / `laundry.mode.v1`
- [ ] Dishwasher: `dishwasher.state.v1` / `dishwasher.mode.v1`
- [ ] Air conditioner: `thermostat.v1` (HA Climate entity)
- [ ] Coffee: `coffeebrewer.v1/v2`
- [ ] Water heater: `waterheater.v1`
- [ ] Other device-specific services added sequentially

### Phase 6: Testing & Validation
- [ ] Full test with owned appliances (Smoker, Coffee Brewer, Toaster Oven)
- [ ] Unit test updates
- [ ] HACS submission preparation

---

## Important API Facts

### The Tuple Concept (SmartHQ Core)
In SmartHQ, a single Service is uniquely identified by 3 components:
```
serviceType  +  domainType  +  serviceDeviceType  =  Tuple (unique capability identifier)
```
Example: `temperature` + `setpoint` + `refrigerator` = Refrigerator fresh food compartment temperature setpoint

### supportedCommands Determines Controllability
- Empty `supportedCommands` array → **read-only sensor**
- `supportedCommands` contains `.set` → **controllable entity**
- Check only this array in code — no DeviceType check needed

### cooking.mode.v1 Command Distinction
- **`.set`**: Sets parameters only, does NOT start cooking (Smoker — physical start required)
- **`.start`**: Sets parameters AND immediately starts cooking (Microwave, Toaster Oven)
- Check `supportedCommands` array to determine which commands are available

### serviceDeviceType Dynamic Resolution
- Each service object contains a `serviceDeviceType` field
- Use this value directly when sending commands → no hardcoding needed
- Examples: `cloud.smarthq.device.smoker`, `cloud.smarthq.device.toasteroven`

### remoteEnable Condition
- Remote commands only work when `cooking.state.v1.state.remoteEnable == true`
- `config.supportedRemote`:
  - `cookingremote.full` = Full remote control (Microwave)
  - `cookingremote.enable` = Remote activation required (Smoker, Toaster Oven)
  - `cookingremote.none` = Remote control not supported

### toggle vs mode(brightness) Distinction
- `toggle` service: `state.on = true/false`
- `mode` service with `brightness` domain: `state.mode = off/dim/high`
  → When mapping to HA Switch: `off` = False, anything else = True

### environmental.sensor — Sensor Type by domainType
| domainType | HA Sensor Type | HA device_class |
|---|---|---|
| `sensor.temperature.environmental` | Ambient temperature | `temperature` |
| `sensor.humidity` | Relative humidity | `humidity` |
| `sensor.voc` | VOC | `volatile_organic_compounds` |
| `sensor.particles.fine.air` | PM2.5 | `pm25` |
| `sensor.particles.10um` | PM10 | `pm10` |
| `sensor.particles.1um` | PM1 | `pm1` |
| `sensor.particles.fine.air.index` | AQI | `aqi` |

### meter — Unit by domainType
| domainType | Unit | HA device_class |
|---|---|---|
| `energy` | kWh | `energy` |
| `voltage` | V | `voltage` |
| `water.cold`, `water.hot` | L / ft³ | `water` |

---

## Design Principles Summary

1. **ServiceType determines the entity** — DeviceType is never referenced
2. **supportedCommands determines capability** — Commands not in the list are not exposed in UI
3. **config determines the range** — min/max/supported values are read from config
4. **serviceId determines unique_id** — Reproducible, collision-free IDs
5. **serviceDeviceType determines command target** — No hardcoding allowed
6. **domainType determines context** — Same ServiceType creates different entities depending on domain
7. **Alerts are published as HA Events** — Users can freely handle them via Automations
