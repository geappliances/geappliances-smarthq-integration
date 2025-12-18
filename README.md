# SmartHQ Home Assistant Integration

Home Assistant custom integration for GE Appliances SmartHQ connected devices.

This integration uses **OAuth2 Application Credentials** with Authorization Code flow (no PKCE, empty scope).

## Installation

### 1. Install the Integration
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
   - Follow the **Step1** & **Step2** and complete the app registration steps above
   - Return and enter your credentials

### 3. Add the SmartHQ Integration
1. Go to **Settings** → **Devices & Services**
2. Click **"+ Add Integration"**
3. Search for and select **"SmartHQ"**
   - After selecting **"SmartHQ"** , if the integration is not found in the list, please restart HA then try again.
5. You'll be redirected to SmartHQ login page
6. Log in with your SmartHQ account
7. If you found **"Authorize"** window, Click **"Authorize"** to grant Home Assistant access and click **"Save"**

   <img width="742" height="308" alt="image" src="https://github.com/user-attachments/assets/21aff895-9903-45f1-add8-25baea30c9ed" />

8. Click **"Link account"** to complete the setup

   <img width="355" height="269" alt="image" src="https://github.com/user-attachments/assets/e7b7b933-7ce2-4fbb-a59f-da79c7d679d3" />

9. Click **"Finish"** when you see the success message

Your SmartHQ devices will now appear in Home Assistant!

## Supported Devices

This integration dynamically creates entities based on your connected appliances:
Currently implemented appliances include the Arden Indoor Smoker and the Café Coffee Brewer. 
Some features may still need improvement. 
**"Contributions are welcome"** —feel free to add support for appliances you own or help enhance the existing implementations.

### Indoor Smoker (Arden)
- **Sensors**: Probe temperatures, Target temperature, Timer, Cook mode, Signal strength
- **Switches**: Control Lock, Cavity Light, Smoke control
- **Selects**: Cooking modes (Brisket, Chicken, Pork, etc.), Temperature units, Cook Target Method (Probe/Timer/Manual)
- **Numbers**: Target temperature, Timer settings, Smoke level
- **Buttons**: Send to Smoker
- **Binary Sensors**: Probe alerts, Low pellet warning

Total: **~31 entities**

<img width="1492" height="690" alt="image" src="https://github.com/user-attachments/assets/2353d041-47b1-43ef-aa01-206864a775a2" />

### Café Coffee Brewer
- **Sensors**: Run Status (Off/Active/Complete)
- **Selects**: Brew Strength (Light/Medium/Bold), Brew Size (10/12/14 Oz, Carafe), Brew Temperature (85-95°C)
- **Buttons**: Brew Start (with selected settings), Brew Stop
- **Binary Sensors**: Probe alerts

Total: **18 entities**

<img width="1498" height="533" alt="image" src="https://github.com/user-attachments/assets/7f212918-5ae6-45d4-a5aa-e1e13007736a" />

## Features

### Real-time Updates
- WebSocket connection for instant device state changes
- Automatic reconnection on connection loss
- Snapshot-based state management

### Entity Types
- **Sensors**: Monitor device status, temperatures, timers, signal strength
- **Binary Sensors**: Alerts and warning indicators
- **Switches**: Control locks, lights, and on/off features
- **Selects**: Cooking modes, temperature units, brew settings
- **Numbers**: Adjustable temperature and timer values
- **Buttons**: Quick action commands (Start brew, Send to Smoker, etc.)

### Coffee Brewer Brewing Control
The integration stores your brew preferences (Strength, Size, Temperature) and automatically sends them when you press the **Start** button. Settings persist between brews.

### Smoker Advanced Features
- Multiple probe temperature monitoring
- Cook Target Method selection (Probe-based, Timer-based, or Manual)
- Smoke level control
- Pre-programmed cooking modes for different meats

## Debugging

### Debug Services
- `smarthq.dump`: Dump cached device data to Home Assistant notifications
- `smarthq.alert_snapshot`: Show service state snapshots as persistent notifications

### Logging
Enable debug logging in `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.smarthq: debug
```

## Brand Icon/Logo
- Official SmartHQ icons can be submitted to Home Assistant **brands** repository
- See `BRANDS-PR/` folder for required assets:
  - `custom_integrations/smarthq/icon.png` (256×256, transparent background)
  - `custom_integrations/smarthq/logo.png` (512×512, transparent background)
- Until merged, the UI shows the default integration icon

## Troubleshooting

### "Failed to authenticate"
- Verify your Client ID and Client Secret are correct in Application Credentials
- Ensure the Callback URL in SmartHQ Developer Portal is exactly: `https://my.home-assistant.io/redirect/oauth`
- Try removing and re-adding the Application Credentials

### Entities not appearing
- Check that your devices are online in the SmartHQ mobile app
- Restart Home Assistant after installation
- Check logs for any error messages (`Settings` → `System` → `Logs`)

### WebSocket disconnections
- Integration automatically reconnects on connection loss
- If persistent, check your internet connection and SmartHQ service status

## Credits
Based on the SmartHQ Cloud API for GE Appliances connected devices.
