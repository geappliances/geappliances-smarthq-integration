# SmartHQ Integration Sequence Diagrams

This document provides high-level sequence diagrams for the SmartHQ Home Assistant
integration. For detailed technical flows, see the [Appendix](#appendix).

---

## 1. Authentication Flow

```mermaid
sequenceDiagram
    participant User
    participant HA as Home Assistant
    participant Config as ConfigFlow
    participant OAuth as OAuth2 Provider
    participant API as SmartHQ API

    User->>HA: Add SmartHQ Integration
    HA->>Config: Start config flow
    Config->>OAuth: Redirect to login
    User->>OAuth: Enter credentials
    OAuth->>Config: Return auth code
    Config->>OAuth: Exchange code for tokens
    OAuth->>Config: Access token + Refresh token
    Config->>API: Validate token
    API->>Config: Success
    Config->>HA: Create config entry
    HA->>User: Integration ready
```

**Key Points:**
- Uses OAuth2 authorization code flow
- Tokens stored securely in Home Assistant
- Automatic token refresh when expired

---

## 2. Appliance Control Flow

```mermaid
sequenceDiagram
    participant User
    participant Entity as HA Entity
    participant WS as WebSocket Client
    participant API as SmartHQ API (REST)
    participant Cloud as SmartHQ Cloud
    participant Appliance

    Note over User,Appliance: Path A — Service-based Control (e.g. temperature, mode, cook time)
    User->>Entity: Set value / press button
    Entity->>WS: async_send_service_command()
    WS->>Cloud: WebSocket command message
    Cloud->>Appliance: Execute command
    Appliance->>Cloud: State changed
    Cloud->>WS: WebSocket push update
    WS->>WS: Update store[device_id].services
    WS->>Entity: SIGNAL_DEVICE_UPDATED dispatch
    Entity->>User: UI reflects new state

    Note over User,Appliance: Path B — Settings-based Control (e.g. alert/notification toggles)
    User->>Entity: Toggle switch (SmartHQSettingSwitch)
    Entity->>API: PATCH /v2/device/{did}/setting/{key}
    API->>Cloud: Apply setting
    Entity->>Entity: _update_store() optimistic update
    Entity->>User: UI reflects new state immediately
    Note over Entity,API: Next 30 s poll confirms actual value
```

**Key Points:**
- **Service entities** (climate, select, number, button, sensor): commands go via WebSocket; state updates arrive via WebSocket push
- **Settings entities** (SmartHQSettingSwitch): writes go via REST API; state is refreshed every 30 seconds by background polling task
- No coordinator involvement at runtime — coordinator is boot-only

---

## 3. Use Case: Controlling a Smoker

```mermaid
sequenceDiagram
    participant User
    participant Select as CookingMode Select
    participant Button as Send to Smoker Button
    participant Climate as Climate Entity
    participant WS as WebSocket Client
    participant Smoke as Smoker Appliance

    Note over User,Smoke: Start a cook session
    User->>Select: Choose cooking mode (e.g. "Smoke")
    Select->>Select: Store pending mode (optimistic)
    User->>Climate: Set target temperature (e.g. 225 F)
    User->>Button: Press "Send to Smoker"
    Button->>WS: async_set_cooking_mode(mode, temp, cook_time)
    WS->>Smoke: WebSocket command (mode + setpoint)
    Smoke->>WS: WebSocket push — state updated
    WS->>WS: Update store[did].services
    WS->>Select: SIGNAL_DEVICE_UPDATED
    WS->>Climate: SIGNAL_DEVICE_UPDATED
    Select->>User: Show active mode
    Climate->>User: Show current / target temp

    Note over User,Smoke: Real-time monitoring
    loop Every WebSocket push
        Smoke->>WS: Probe temps, cook time, smoke level
        WS->>WS: Update store[did].services
        WS->>Climate: Dispatch update
        Climate->>User: Current temp / probe 1-4
    end

    Note over User,Smoke: Alert / notification settings
    User->>User: Toggle "Probe Alert" switch
    User->>WS: SmartHQSettingSwitch.async_turn_on()
    WS->>WS: REST API PATCH setting
    Note over WS: Confirmed by next 30 s poll
```

**Service-Based Entities Created for Smoker:**

| Entity Type | Source | Example |
|-------------|--------|---------|
| `climate` | cooking service (setpoint/currentTemp) | Smoker temperature |
| `select` | cooking mode service | Cooking mode (Smoke / Grill / …) |
| `number` | cook time service | Cook time (minutes) |
| `button` | send command service | Send to Smoker |
| `sensor` | probe / cook time services | Probe 1–4 temps, cook time remaining |
| `binary_sensor` | smoke level service | Smoke level active |
| `switch` (Settings) | REST BOOLEAN settings | Probe alert, door alert, … |

---

## 4. Initial Setup & Device Discovery

```mermaid
sequenceDiagram
    participant HA as Home Assistant
    participant Coord as Coordinator
    participant API as SmartHQ API
    participant Platforms as Entity Platforms
    participant WS as WebSocket Client

    Note over HA,WS: Boot (runs once)

    HA->>Coord: async_config_entry_first_refresh()
    Coord->>API: GET /v2/appliance → device list
    loop For each device
        Coord->>API: GET /v2/device/{did} → services[]
        Coord->>API: GET /v2/device/{did}/setting/* → settings[]
    end
    Coord->>HA: coord.data ready

    HA->>Platforms: async_forward_entry_setups()
    Platforms->>Platforms: services[] → entity per serviceType
    Platforms->>Platforms: settings[] BOOLEAN → SmartHQSettingSwitch
    Platforms->>HA: All entities registered

    HA->>WS: Connect & subscribe all devices
    HA->>HA: Start 30 s settings poll task

    Note over HA,WS: Ready — WS push (services) + poll (settings)
```

**Key Points:**
- `SmartHQCoordinator` runs **once at boot** — no periodic polling schedule
- Entity creation is driven by the `services[]` array; each `serviceType` maps to a specific entity class
- `SmartHQSettingSwitch` entities are created from the `settings[]` array (BOOLEAN type only)
- After boot, state updates flow via WebSocket (service entities) or the 30 s settings poll (setting switches)

---

# Appendix

## A1. Detailed OAuth2 Token Refresh Flow

```mermaid
sequenceDiagram
    participant Entity
    participant API as SmartHQ API
    participant OAuth as OAuth2Session
    participant Storage as Token Storage
    participant Provider as OAuth2 Provider

    Entity->>API: Make API request
    API->>OAuth: Check token expiry

    alt Token expired
        OAuth->>Storage: Get refresh token
        Storage->>OAuth: Refresh token
        OAuth->>Provider: POST /oauth2/token
        Provider->>OAuth: New access token + refresh token
        OAuth->>Storage: Save new tokens
        OAuth->>API: Token refreshed
    else Token valid
        OAuth->>API: Continue
    end

    API->>Provider: Request with Bearer token
    Provider->>API: Response
    API->>Entity: Success
```

---

## A2. WebSocket Reconnection with Exponential Backoff

```mermaid
sequenceDiagram
    participant WS as WebSocket Client
    participant Cloud as SmartHQ Cloud
    participant Coordinator
    participant HA as Home Assistant

    WS->>Cloud: Heartbeat (60 s idle → ping frame)
    Cloud->>WS: Pong

    Note over WS,Cloud: Connection lost
    WS->>WS: Detect disconnection / exception
    WS->>WS: consecutive_failures = 0
    WS->>WS: backoff = 1 s

    loop Reconnection attempts (max_retries = 3)
        WS->>WS: consecutive_failures += 1
        WS->>WS: sleep(backoff)
        WS->>Cloud: GET new WebSocket endpoint URL
        Cloud->>WS: wss://... URL
        WS->>Cloud: Attempt WebSocket connection

        alt Connection successful
            Cloud->>WS: Connected
            WS->>WS: consecutive_failures = 0, backoff = 1 s
            WS->>Cloud: Resubscribe all devices
            WS->>Coordinator: SIGNAL_DEVICE_UPDATED (resume)
            Note over WS: Exit reconnection loop
        else Connection failed AND consecutive_failures < 3
            WS->>WS: backoff = min(backoff x 2, 60 s)
            Note over WS: Continue to next attempt
        else Connection failed AND consecutive_failures >= 3
            WS->>HA: Create persistent notification<br/>"SmartHQ Connection Failed"<br/>"Please reload integration"
            Note over WS: Reconnection stopped<br/>Manual intervention required
        end
    end
```

**Backoff Schedule:**

| Attempt | Sleep before attempt |
|---------|----------------------|
| 1 | 1 s |
| 2 | 2 s |
| 3 | 4 s |
| (cap) | max 60 s |

---

## A3. Service-Type → Entity-Class Mapping

```mermaid
sequenceDiagram
    participant Platform as Entity Platform (setup)
    participant Dispatch as Service Dispatcher
    participant HA as Home Assistant

    Platform->>Platform: Read coord.data[did]["item"]["services"]

    loop For each service in services[]
        Platform->>Dispatch: (serviceType, domainType) → entity class?

        alt serviceType contains "cooking" AND domainType "setpoint"
            Dispatch->>HA: SmartHQCookingClimate
        else serviceType contains "cooking" AND domainType "cookingMode"
            Dispatch->>HA: SmartHQCookingModeSelect
        else serviceType contains "cooking" AND domainType "cookTime"
            Dispatch->>HA: SmartHQCookTimeNumber
        else serviceType contains "cooking" AND domainType "probe"
            Dispatch->>HA: SmartHQProbeTemperatureSensor
        else serviceType ends "light" AND domainType "toggle"
            Dispatch->>HA: SmartHQLightToggleSwitch
        else serviceType ends "light" AND domainType "brightness"
            Dispatch->>HA: SmartHQLightNumber
        else serviceType is "laundry"
            Dispatch->>HA: SmartHQLaundrySensor / SmartHQRemoteEnableSwitch
        else serviceType is "dishwasher"
            Dispatch->>HA: SmartHQDishwasherSensor / SmartHQDishwasherSelect
        else serviceType is "thermostat"
            Dispatch->>HA: SmartHQThermostatClimate
        else BOOLEAN setting (from settings[])
            Dispatch->>HA: SmartHQSettingSwitch (EntityCategory.CONFIG)
        end
    end

    HA->>Platform: All entities registered
```

---

## A4. WebSocket Message Processing

```mermaid
sequenceDiagram
    participant Cloud as SmartHQ Cloud
    participant WS as WebSocket Client
    participant Store as In-Memory Store
    participant Dispatcher
    participant Entities as HA Entities

    Cloud->>WS: WebSocket push message (JSON)
    WS->>WS: Parse message — extract serviceId, serviceType, domainType, state

    alt Service state update
        WS->>Store: store[did]["snapshot"]["services"][serviceId] = new_state
        Note over Store: Merge metadata (serviceType, domainType, config)
    else Presence / info update
        WS->>Store: store[did]["presence"] = updated
    end

    WS->>Dispatcher: async_dispatcher_send(SIGNAL_DEVICE_UPDATED.format(did))
    Dispatcher->>Entities: Notify all subscribed entities for did

    loop For each subscribed entity
        Entities->>Store: Read store[did]["snapshot"]["services"][serviceId]
        Entities->>Entities: Recompute state from updated data
        Entities->>HA: async_write_ha_state()
    end

    Note over HA: UI updates automatically
```

---

## Notes

- **REST API**: Used for initial boot data fetch (`GET /v2/device/{did}`, `GET /v2/device/{did}/setting/*`) and settings writes (`PATCH`)
- **WebSocket**: Used for real-time service state updates — no polling overhead for service entities
- **Settings Polling**: 30 s background task — required because WebSocket does not push settings changes
- **Coordinator**: Runs only once at boot (`async_config_entry_first_refresh`); no periodic update schedule
- **Entity Platforms**: `sensor`, `binary_sensor`, `switch`, `climate`, `number`, `select`, `button`, `light`, `water_heater`
- **Reconnection**: Automatic with exponential backoff (1 s → 2 s → 4 s), max 3 attempts before persistent notification
- **Token Refresh**: Automatic and transparent to user via `OAuth2Session`

For implementation details, see:
- `config_flow.py` — OAuth2 flow
- `coordinator.py` — One-time boot data fetch
- `__init__.py` — Bootstrap, store wiring, WS start, settings poll
- `ws_client.py` — WebSocket connection, reconnection, command dispatch
- `api.py` — REST API calls
- `switch.py` — `SmartHQSettingSwitch` (settings) + service-based switches
- Platform files (`sensor.py`, `climate.py`, `select.py`, `number.py`, `button.py`, …) — Entity implementations
