# SmartHQ Home Assistant Integration

[![GitHub Release](https://img.shields.io/github/v/release/geappliances/geappliances-smarthq-integration?style=flat-square&color=orange&label=RELEASE)](https://github.com/geappliances/geappliances-smarthq-integration/releases)
[![License: BSD 3-Clause](https://img.shields.io/badge/LICENSE-BSD--3--CLAUSE-green?style=flat-square)](https://github.com/geappliances/geappliances-smarthq-integration/blob/main/LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square)](https://github.com/hacs/integration)
[![Community](https://img.shields.io/badge/COMMUNITY-forum-blue?style=flat-square)](https://community.home-assistant.io)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=geappliances&repository=geappliances-smarthq-integration&category=integration)

---

Home Assistant custom integration for GE Appliances SmartHQ connected devices.

This integration uses **OAuth2 Application Credentials** with Authorization Code flow (no PKCE, empty scope).

---

## How It Works — Service-Based Entity Discovery

This integration is built on the **SmartHQ Developer Portal Cloud API**, which exposes each appliance's capabilities as a list of **Services**. Every SmartHQ device commissioning declares which services it supports (e.g. `cooking.mode.v1`, `laundry.state.v1`, `toggle`, `meter`, etc.).

**At startup, the integration:**
1. Queries the SmartHQ Cloud API for all devices commissioned to your account
2. Reads the **Services** list returned for each device
3. Automatically creates the appropriate Home Assistant entities based on the service types and supported commands found

This means **no hardcoded device support is needed** — any appliance commissioned through SmartHQ and supported by the Developer Portal API will automatically get entities in Home Assistant, as long as the relevant service types are handled by the integration.

### Service → Entity Mapping

| Service Type | Supported Commands | HA Platform |
|---|---|---|
| `cooking.mode.v1` | `set`, `adjust.timer` | **select**, **number**, **button** |
| `cooking.state.v1` | `stop` | **button**, **sensor** |
| `laundry.state.v1` | *(read-only)* | **sensor** |
| `laundry.mode.v1` | `set` | **select** |
| `toggle` | `toggle.set` | **switch** |
| `mode` | `mode.set` | **select** or **switch** |
| `trigger` | `trigger.do` | **button** |
| `temperature` | `temperature.set` | **sensor** or **number** |
| `integer` | `integer.set` | **number** or **sensor** |
| `meter` | *(read-only)* | **sensor** |
| `firmware.v1` | `firmware.v1.upgrade` | **sensor** + **button** |
| `door` | *(read-only)* | **binary_sensor** |
| `filter.v1` | *(read-only)* | **binary_sensor** |
| `brew.mode.v1` | *(read-only)* | **sensor** |
| `coffeebrewer.v1/v2` | `set` | **select**, **button**, **binary_sensor** |
| `cycletimer` | *(read-only)* | **sensor** |
| `stopwatch` | *(read-only)* | **sensor** |
| Settings API (BOOLEAN) | REST PUT/PATCH | **switch** (notifications/alerts) |

> In addition to service-based entities, the **Settings API** (REST `/v2/device/{id}/setting/*`) is polled every 30 seconds to expose BOOLEAN notification/alert toggles as switches.

---

## Installation

### Option A: Install via HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=geappliances&repository=geappliances-smarthq-integration&category=integration)

1. Click the button above — your Home Assistant will open the HACS custom repository dialog automatically
2. Click **"Download"** to install the integration
3. Restart Home Assistant

> **Don't have HACS?** Install it from [hacs.xyz](https://hacs.xyz/docs/use/download/download/) first, then return here.

### Option B: Manual Installation

Copy this folder to your Home Assistant configuration directory:
```bash
/config/custom_components/smarthq
```

Restart Home Assistant after installation.

### 2. Setup Application Credentials

Before adding the integration, you need to obtain OAuth2 credentials from SmartHQ Developer Portal:

#### Step 1: Register Your Application
1. Open a browser and go to [SmartHQ Developer Portal](https://developer.smarthq.com)
2. Log in with your SmartHQ account
3. Click **"Apps"** in the top menu
4. Click **"Add app"** button

<img width="944" height="585" alt="image" src="https://github.com/user-attachments/assets/65e43b22-27cc-499d-bab4-097d6e0d70cb" />

#### Step 2: Configure Your App
1. Enter a **Machine name** (e.g., "homeassistant")
2. Set **Callback URL** to: `https://my.home-assistant.io/redirect/oauth`
3. Click **"ADD APP"**
4. Copy your **Client ID** and **Client Secret** (you'll need these)

<img width="1245" height="636" alt="image" src="https://github.com/user-attachments/assets/9d70bb9d-72d4-456c-a72c-ddd713edda7d" />

#### Step 3: Add Credentials to Home Assistant
1. In Home Assistant, go to **Settings** → **Devices & Services**
2. Click the three-dot menu (⋮) in the top right
3. Select **"Application Credentials"**
4. Click **"Add application credential"** in the bottom right
5. Search for and select **"SmartHQ"** in **"Integration"** section
6. If you already have OAuth Client ID/Client Secret:
   - Enter **Name**
   - Enter your **Client ID** (OAuth2 Client ID)
   - Enter your **Client Secret** (OAuth2 Client Secret)
   - Click **"Add"**

   <img width="544" height="655" alt="image" src="https://github.com/user-attachments/assets/425033db-7b29-4329-a819-9615b2dd0eca" />

7. If you don't have credentials yet:
   - Follow **Step 1** & **Step 2** and complete the app registration steps above
   - Return and enter your credentials

### 3. Add the SmartHQ Integration
1. Go to **Settings** → **Devices & Services**
2. Click **"+ Add Integration"**
3. Search for and select **"SmartHQ"**
   - If the integration is not found in the list, restart HA then try again.
4. You'll be redirected to SmartHQ login page
5. Log in with your SmartHQ account
6. If you see an **"Authorize"** window, click **"Authorize"** to grant Home Assistant access and click **"Save"**

   <img width="742" height="308" alt="image" src="https://github.com/user-attachments/assets/21aff895-9903-45f1-add8-25baea30c9ed" />

7. Click **"Link account"** to complete the setup

   <img width="355" height="269" alt="image" src="https://github.com/user-attachments/assets/e7b7b933-7ce2-4fbb-a59f-da79c7d679d3" />

8. Click **"Finish"** when you see the success message

Your SmartHQ devices will now appear in Home Assistant with entities automatically created based on each appliance's services!

---

## Supported Devices

Because entity creation is **fully service-driven**, any SmartHQ-commissioned appliance whose service types are handled by this integration will work automatically. The devices below have been verified and tested.

### Indoor Smoker (Arden)
- **Sensors**: Cavity temperature, Probe temperature, Cook time remaining, Preheat progress, Signal strength, Firmware version
- **Switches**: Control Lock, Cavity Light, Smoke On/Off, Auto Warm
- **Selects**: Cooking mode (Brisket, Chicken, Wings, Pork Ribs, Pork Butt, Salmon, Custom, Warm), Doneness level, Smoke level, Temperature units, Cook Target Method (Probe / Timer)
- **Numbers**: Cavity target temperature, Probe target temperature, Cook time, Auto Warm hold time, Early alert time
- **Buttons**: Send to Smoker, Restore defaults, Firmware Update
- **Binary Sensors**: Probe connected
- **Switches (Alerts)**: Smoke Clear Alert, Start Alert, Door Alert, Finish Alert, Early Alert, Preheat Complete, Auto Warm Reminder, Software Updates

Total: **~40 entities**

<img width="1492" height="690" alt="image" src="https://github.com/user-attachments/assets/2353d041-47b1-43ef-aa01-206864a775a2" />

### Café Coffee Brewer
- **Sensors**: Run status, Cycle, Sub-cycle
- **Selects**: Brew Strength (Light/Medium/Bold), Brew Size (10/12/14 Oz, Carafe), Brew Temperature (85–95°C)
- **Buttons**: Brew Start, Brew Stop, Firmware Update
- **Binary Sensors**: Pot Present, Out of Water, Out of Beans, Clean Brew Basket
- **Switches (Alerts)**: Add Beans, Add Water, Clean Brew Basket, Lock/Check Brew Basket, Lock/Check Burr Grinder, Align Carafe, Brew Cycle Status, Brewing Completed, Software Updates

Total: **~20 entities**

<img width="1498" height="533" alt="image" src="https://github.com/user-attachments/assets/7f212918-5ae6-45d4-a5aa-e1e13007736a" />

### Dryer
- **Sensors**: Run status, Cycle, Sub-cycle, Spin, Temperature, Rinse, Soil level, Energy meter, Firmware version, Signal strength
- **Buttons**: Start, Stop, Firmware Update
- **Selects**: Remote cycle selection
- **Switches**: Control Lock, Washer Link
- **Switches (Alerts)**: Cycle Complete, Clothes Damp, Cycle Ending Soon, Delay Start, Dryer Sheets alerts, Dryer Vent Blocked, Unattended Clothes, Software Updates

Total: **~30 entities**

### Combination Washer/Dryer
- **Sensors**: Run status, Cycle, Sub-cycle, Spin, Temperature, Rinse, Soil level, Energy meter, Signal strength, Firmware version
- **Switches (Alerts)**: Pre-Cycle End, Wash Complete, Cycle Complete, Lint Filter Clogged, Clean Lint Mesh Filter, Self Clean Reminder, Out of Balance, Smart Dispense Refill, Unattended Clothes, Delayed Cycle Start, Software Updates

Total: **~20 entities**

### Toaster Oven
- **Sensors**: Cook status, Firmware version, Signal strength
- **Selects**: Cooking mode (Bake, Air Fry, Toast, Bagel, Broil, Warm, Pizza, Cookies, Reheat, Custom), Cook option, Numeric option (slices / size)
- **Numbers**: Cavity temperature, Cook time
- **Buttons**: Start Cooking, Stop Cooking, Firmware Update
- **Switches**: Control Lock

Total: **~15 entities**

> **Note**: The list above reflects devices verified during development. Any other SmartHQ appliance with supported service types will also generate entities automatically.

---

## Features

### Automatic Entity Discovery
Entities are created at startup by inspecting each device's **Services** list from the SmartHQ Cloud API — no device-specific code required. When a new appliance is commissioned to your SmartHQ account, simply restart Home Assistant to pick it up.

### Real-time Updates
- WebSocket connection for instant device state changes
- Automatic reconnection on connection loss (max 3 attempts with exponential backoff)
- Persistent notification when max retries reached
- Snapshot-based state management per service ID

### Notification / Alert Toggles
Each device exposes a set of **notification settings** via the REST Settings API. These are surfaced as **switch entities** in the HA **Configuration** section, letting you enable or disable individual alerts (e.g. "Cycle Complete", "Door Alert") directly from Home Assistant.

### Entity Platforms
| Platform | Purpose |
|---|---|
| **sensor** | Status, temperatures, timers, energy, signal strength |
| **binary_sensor** | Door open, filter status, problem alerts |
| **switch** | On/off toggles (lock, light, smoke) + notification alert toggles |
| **select** | Cooking/laundry modes, brew settings, temperature units |
| **number** | Adjustable setpoints (temperature, timer, smoke level) |
| **button** | Action commands (Start, Stop, Firmware Update) |
| **climate** | HVAC-style temperature control |
| **water_heater** | Water heater control |
| **light** | Cavity light with brightness |
| **text** | Free-text input fields |

---

## Debugging

### Debug Services
- `smarthq.diagnose`: Dump all services and state for a specific device as a persistent notification
- `smarthq.dump`: Dump full cached device data to HA logs
- `smarthq.alert_snapshot`: Show service state snapshots as persistent notifications

### Logging
Enable debug logging in `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.smarthq: debug
```

---

## Brand Icon/Logo
- Official SmartHQ icons can be submitted to Home Assistant **brands** repository
- See `BRANDS-PR/` folder for required assets:
  - `custom_integrations/smarthq/icon.png` (256×256, transparent background)
  - `custom_integrations/smarthq/logo.png` (512×512, transparent background)
- Until merged, the UI shows the default integration icon

---

## Troubleshooting

### "Failed to authenticate"
- Verify your Client ID and Client Secret are correct in Application Credentials
- Ensure the Callback URL in SmartHQ Developer Portal is exactly: `https://my.home-assistant.io/redirect/oauth`
- Try removing and re-adding the Application Credentials

### Entities not appearing
- Check that your devices are online in the SmartHQ mobile app
- Restart Home Assistant after installation
- Check logs for any error messages (**Settings** → **System** → **Logs**)
- Use `smarthq.diagnose` service to inspect what services are detected for a device

### WebSocket disconnections
- Integration automatically reconnects on connection loss (up to 3 attempts)
- After max retries, a persistent notification alerts you to manually reload the integration
- Check your internet connection and SmartHQ service status if reconnection fails

---

## Architecture

For detailed architecture and sequence diagrams, see:
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — Service-based entity discovery, data flow
- [SEQUENCE_DIAGRAMS.md](docs/SEQUENCE_DIAGRAMS.md) — Auth flow, appliance control, real-time updates

**Quick Overview:**
- **Authentication**: OAuth2 authorization code flow with automatic token refresh
- **Boot**: REST API queries all devices + services → entities created automatically
- **Control**: WS commands for service-based entities; REST API for settings toggles
- **Updates**: WebSocket push for real-time state sync (services); 30s polling for settings

---

## Contributing

Contributions are welcome! Because entity creation is fully service-driven, adding support for a new appliance type typically only requires:
1. Identifying the new service types from the SmartHQ Developer Portal
2. Adding the service type constants to `service_registry.py`
3. Adding the entity creation logic to the relevant platform file

---

## Credits
Based on the SmartHQ Cloud API for GE Appliances connected devices.
