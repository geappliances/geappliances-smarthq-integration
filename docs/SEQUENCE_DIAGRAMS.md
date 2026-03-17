# SmartHQ Integration Sequence Diagrams

This document provides high-level sequence diagrams for the SmartHQ Home Assistant integration. For detailed technical flows, see the [Appendix](#appendix).

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
    participant HA as Home Assistant Entity
    participant Coordinator
    participant API as SmartHQ API
    participant WS as WebSocket Client
    participant Cloud as SmartHQ Cloud
    participant Appliance

    Note over User,Appliance: Control Command
    User->>HA: Turn on/Set temperature
    HA->>API: Send command (REST API)
    API->>Cloud: Forward command
    Cloud->>Appliance: Execute command
    
    Note over User,Appliance: Real-time State Update
    Appliance->>Cloud: State changed
    Cloud->>WS: WebSocket message
    WS->>Coordinator: Parse & update
    Coordinator->>HA: Update entities
    HA->>User: UI updates automatically
```

**Key Points:**
- Commands sent via REST API
- State updates received via WebSocket for real-time sync
- Coordinator manages data flow and entity updates

---

## 3. Use Case: Controlling a Smoker

```mermaid
sequenceDiagram
    participant User
    participant HA as Home Assistant
    participant Smoker as Smoker Appliance
    participant Probe as Temperature Probe

    User->>HA: Set target temp to 225°F
    HA->>Smoker: Update temperature setting
    Smoker->>HA: Confirm setting updated
    
    loop Every state update
        Probe->>Smoker: Current temp reading
        Smoker->>HA: WebSocket update
        HA->>User: Display current: 180°F
    end
    
    Note over Smoker: Target reached
    Smoker->>HA: Temp: 225°F, Status: Active
    HA->>User: Temperature reached notification
    
    User->>HA: Check probe temperature
    HA->>User: Display probe: 165°F
    
    User->>HA: Turn off smoker
    HA->>Smoker: Power off command
    Smoker->>HA: Confirm powered off
```

**Entities Created for Smoker:**
- **Climate Entity**: Target temperature, current temperature, operating mode
- **Sensor Entities**: Probe temperatures, cook time
- **Binary Sensor**: Smoke level, power status
- **Switch**: Remote enable/disable

---

## 4. Initial Setup & Device Discovery

```mermaid
sequenceDiagram
    participant HA as Home Assistant
    participant Coordinator
    participant API as SmartHQ API
    participant WS as WebSocket Client
    participant Cloud as SmartHQ Cloud

    Note over HA,Cloud: Integration Startup
    HA->>Coordinator: Initialize
    Coordinator->>API: Get device list
    API->>Cloud: Fetch registered appliances
    Cloud->>API: Return device info
    API->>Coordinator: Devices data
    
    Coordinator->>Coordinator: Analyze device types
    Coordinator->>HA: Create entities<br/>(sensor, switch, climate, etc.)
    
    Coordinator->>WS: Connect to WebSocket
    WS->>Cloud: Establish connection
    Cloud->>WS: Connection established
    
    loop For each device
        WS->>Cloud: Subscribe to device updates
    end
    
    Note over HA,Cloud: Ready for operation
    WS->>Coordinator: Real-time updates begin
    Coordinator->>HA: Update all entities
```

**Entity Platform Mapping:**
- **Laundry**: Sensor (cycle status), Switch (remote enable), Binary Sensor (door lock)
- **Oven**: Climate (temperature), Sensor (cook mode), Binary Sensor (preheat status)
- **Refrigerator**: Number (temperature setpoint), Sensor (door status)
- **Dishwasher**: Sensor (cycle status), Binary Sensor (rinse aid level)
- **Smoker**: Climate (temperature), Sensor (probe temps), Binary Sensor (smoke level)

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

    WS->>Cloud: Heartbeat (60s interval)
    Cloud->>WS: Pong
    
    Note over WS,Cloud: Connection Lost
    WS->>WS: Detect disconnection
    WS->>Coordinator: Connection status: Disconnected
    
    loop Reconnection attempts
        WS->>WS: Wait backoff (1s, 2s, 4s...)
        WS->>Cloud: Get new WebSocket endpoint
        Cloud->>WS: New WebSocket URL
        WS->>Cloud: Connect
        
        alt Connection successful
            Cloud->>WS: Connected
            WS->>WS: Reset backoff = 1s
            WS->>Cloud: Resubscribe to all devices
            WS->>Coordinator: Connection restored
        else Connection failed
            WS->>WS: Increase backoff = min(backoff * 2, 60s)
        end
    end
```

---

## A3. Entity Creation Decision Logic

```mermaid
sequenceDiagram
    participant Platform as Entity Platform
    participant Factory as Entity Factory
    participant Device as Device Snapshot
    participant HA as Home Assistant

    Platform->>Device: Get device info
    Device->>Platform: services, settings, deviceType
    
    Platform->>Factory: Analyze services structure
    
    alt Laundry Platform
        Factory->>Factory: Check serviceType == 'laundry'
        Factory->>HA: Create SmartHQWasherSensor
        Factory->>HA: Create SmartHQDryerSensor
        Factory->>HA: Create SmartHQRemoteEnableSwitch
    else Oven Platform (has temperature keys)
        Factory->>Factory: Check for 'currentTemperature'
        Factory->>HA: Create SmartHQOvenClimate
        Factory->>HA: Create SmartHQCookModeSensor
    else Refrigerator Platform
        Factory->>Factory: Check domainType == 'brightness'
        Factory->>HA: Create SmartHQRefrigeratorNumber
    else Smoker Platform
        Factory->>Factory: Check for probe sensors
        Factory->>HA: Create SmartHQCookingModeSelect
        Factory->>HA: Create SmartHQCoffeeBrewer (if coffee)
        Factory->>HA: Create SmartHQBinarySensor
    end
    
    HA->>Platform: Entities registered
```

---

## A4. Full Snapshot Update Processing

```mermaid
sequenceDiagram
    participant Cloud as SmartHQ Cloud
    participant WS as WebSocket Client
    participant Store as Data Store
    participant Dispatcher
    participant Entities as HA Entities

    Cloud->>WS: WebSocket message<br/>(service update)
    WS->>WS: Parse message JSON
    WS->>WS: Extract serviceId, serviceType, state
    
    alt Full Snapshot Update
        WS->>Store: snapshot[device_id].services = new_data
        Note over Store: Replace entire services dict
    else Delta Update
        WS->>Store: Merge state changes into existing
        Note over Store: Update only changed fields
    end
    
    WS->>Store: Update device alerts (if any)
    WS->>Dispatcher: Send SIGNAL_DEVICE_UPDATED
    Dispatcher->>Entities: Notify all subscribed entities
    
    loop For each entity
        Entities->>Store: Read updated snapshot
        Entities->>Entities: Update internal state
        Entities->>HA: schedule_update_ha_state()
    end
    
    Note over HA: UI updates automatically
```

---

## Notes

- **REST API**: Used for commands and initial data fetch
- **WebSocket**: Used for real-time state updates (more efficient than polling)
- **Coordinator**: Central hub for data management and API coordination
- **Entity Platforms**: sensor, binary_sensor, switch, climate, number, select, button
- **Reconnection**: Automatic with exponential backoff (max 60s)
- **Token Refresh**: Automatic and transparent to user

For implementation details, see the source code in:
- `config_flow.py` - OAuth2 flow
- `coordinator.py` - Data coordination
- `ws_client.py` - WebSocket handling
- `api.py` - REST API calls
- Platform files (`sensor.py`, `switch.py`, etc.) - Entity implementations
