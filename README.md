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
- **Smoker** - 31 entities
<img width="1518" height="810" alt="image" src="https://github.com/user-attachments/assets/07a58a4d-d24f-4909-b4c0-4c3c1f038616" />
Total: **1 devices, 31 entities**

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
