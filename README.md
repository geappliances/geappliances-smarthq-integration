# SmartHQ (Authorization Code, no PKCE, empty scope)

This integration uses Home Assistant **Application Credentials** and the **My Home Assistant** redirect.
- No PKCE (client secret auth)
- Empty scope

## Install
1) Copy this folder to `/config/custom_components/smarthq`
2) Restart Home Assistant
3) Go to Settings → Devices & Services → **Application Credentials**, add **Client ID/Secret** for SmartHQ
4) Add Integration → SmartHQ → Link

## Supported Devices
Based on your current setup, this integration supports:
- **Coffee Brewer** - 3 entities
- **Oven** - 4 entities
- **Smoker** - 16 entities
- **Toaster Oven** - 6 entities

Total: **4 devices, 29 entities**

## Features
- Real-time updates via WebSocket
- Sensors (temperature, timer, signal strength, etc.)
- Switches (Control Lock, Cavity Light, Smoke control)
- Selects (cooking modes)
- Numbers (temperature/timer settings)
- Buttons (Send to Smoker commands)
- Binary Sensors (alerts and warnings)

## Brand icon/logo
- Submit official SmartHQ icons to Home Assistant **brands** repo.
  See `BRANDS-PR/` for the required paths:
    - `custom_integrations/smarthq/icon.png` (256x256, transparent)
    - `custom_integrations/smarthq/logo.png` (512x512, transparent)
- Until merged, the UI will show `mdi:washing-machine`.

## Debug Services
Available debug services:
- `smarthq.dump`: Dump cached device data to Home Assistant notifications
- `smarthq.alert_snapshot`: Show service state snapshots as alerts