# Entity Creation Rules Based on Service Mapping

> Last updated: 2026-05-18 (v1.1.0)

## Overview

The SmartHQ integration converts the service list received from the GE Appliances API
into Home Assistant entities using the **`SERVICE_MAPPING` Allowlist**.

### Core Principles
- **Allowlist approach**: Any serviceType not present in `SERVICE_MAPPING` is automatically blocked
- **Two mapping types**: `standard` (shared handlers) / `custom` (device-specific classes)
- **Device-agnostic**: Unified flow — serviceType → mapping → entity creation

---

## Entity Creation Flow

```
API service (serviceType)
        │
        ▼
  Is it in SERVICE_MAPPING?
        │
   YES  │  NO
        │   └─→ Ignored (not exposed)
        ▼
  Per-platform async_setup_entry
   1. Confirm coordinator is ready
   2. Iterate devices and services[]
   3. Allowlist check
   4. Verify current platform is the target
   5. Branch on domainType / supportedCommands
        ▼
  HA entity created
```

---

## Block Policy (entities not created)

| Target | Block method | User access |
|---|---|---|
| `factory` / `restore` trigger | button.py `continue` | ❌ Not accessible |
| `icemaker` / `demandresponse` mode | `READONLY_MODE_DOMAINS` → `continue` | ❌ Not accessible |
| Firmware upgrade button | button.py `continue` | ❌ Not accessible |
| Firmware update binary sensor | binary_sensor.py `continue` | ❌ Not accessible |
| Firmware version/status sensors | sensor.py spec commented out | ❌ Not accessible |
| `laundry.mode.v1` select | service_registry `platform: "sensor"` | ❌ Not selectable |
| `early.*` (temperature/time) | `disabled_by_default=True` | ✅ Manually enableable |

---

## domainType Branching Rules

### `mode` service

```
mode service
    ├─ SWITCH_MODE_DOMAINS          → switch
    │     lock, override, brightness, light
    │
    ├─ READONLY_MODE_DOMAINS        → not created (read-only, ignored)
    │     icemaker
    │     demandresponse  ← controlled by utility provider, not user-operable
    │
    └─ others                       → select (multiple options)
```

### `temperature` service

```
temperature service
    ├─ no CMD_TEMPERATURE_SET       → sensor (read-only)
    └─ has CMD_TEMPERATURE_SET      → select
          stepped integer list (API min/max range)
```

### `integer` service

```
integer service
    ├─ integerUnits contains hour/minute  → select (h+min pair or single)
    │     svc_max <= 60  → single select
    │     svc_max > 60   → Hours select + Minutes select pair
    └─ others                             → number (slider)
```

### `trigger` service (button)

```
trigger service
    ├─ domain contains "factory" or "restore"  → fully blocked (not created)
    ├─ laundry device (has laundry.state.v1)
    │     domain.start  → enabled only when runStatus == "delayed"
    │     domain.stop   → enabled when runStatus ∉ {standby, idle, off, delayed}
    └─ other devices    → based on trigger.state.disabled flag
```

### `toggle` service

```
toggle service
    ├─ LOCK_DOMAINS       → switch (device_class: lock)
    ├─ BRIGHTNESS_DOMAINS → light
    └─ others             → switch (generic)
```

---

## Implementation Status

| Phase | Description | Status |
|------|------|------|
| Phase 1 | `SERVICE_MAPPING` Registry design | ✅ |
| Phase 2 | `switch.py` pilot implementation | ✅ |
| Phase 3 | `binary_sensor.py` implementation | ✅ |
| Phase 4 | Full rollout: `sensor`, `select`, `button`, `number`, etc. | ✅ |
| Phase 5 | Data-driven dispatch — `elif` 86 → 26 | ✅ |
| Validation | 6 real-device tests — all entities confirmed working | ✅ |
| v1.1.0 | Washer Start/Stop, firmware block, time select conversion | ✅ |

---

## Git Status

- Working branch: `feature/service-mapping`
- Latest on main: `v1.1.0` (2026-05-18)
- Recent commits:
  - `308f893` fix: block all firmware entities from creation
  - `ef2f23e` fix(button): block factory/restore triggers from entity creation
  - `87284a7` fix(washer): Start/Stop button availability based on runStatus
  - `47e6fd9` refactor(select): convert all time-unit integers to select entities
  - `bbc8bc5` refactor(smoker): replace time number entities with h+min select entities
