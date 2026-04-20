# /config/custom_components/smarthq/const.py

DOMAIN = "smarthq"

# Branding
MANUFACTURER = "GE Appliances"
DEFAULT_NAME = "SmartHQ"

# OAuth
OAUTH2_AUTHORIZE = "https://accounts.brillion.geappliances.com/oauth2/auth"
OAUTH2_TOKEN     = "https://accounts.brillion.geappliances.com/oauth2/token"
OAUTH2_SCOPE     = ""  # SmartHQ requires empty scope

# Digital Twin (Client) API base
API_BASE = "https://client.mysmarthq.com"

# REST endpoints
DEVICES_URL               = f"{API_BASE}/v2/device"
DEVICE_PRESENCE_URL       = f"{API_BASE}/v2/device/{{device_id}}/presence"
DEVICE_SETTINGS_URL       = f"{API_BASE}/v2/device/{{device_id}}/setting"
DEVICE_SETTING_DETAIL_URL = f"{API_BASE}/v2/device/{{device_id}}/setting/{{rule_id}}"
DEVICE_ITEM_URL           = f"{API_BASE}/v2/device/{{device_id}}"

INSTANT_METRICS_URL = f"{API_BASE}/v2/device/instant/calculated"
HISTORY_METRICS_URL = f"{API_BASE}/v2/device/history/calculated"

# Polling interval (legacy) - unused after WS-only transition
# DEFAULT_POLL_SECONDS = 15

# ---- Runtime tuning parameters ----
# Initial seed timeouts (seconds)
SEED_SETTINGS_TIMEOUT = 4.0
SEED_SNAPSHOT_TIMEOUT = 4.0
SEED_ALL_TIMEOUT      = 6.0
LIST_DEVICES_TIMEOUT  = 10.0

# WebSocket
WS_HEARTBEAT_SECONDS  = 60  # Heartbeat interval for idle connections
WS_BACKOFF_MAX        = 60  # Maximum backoff for reconnection

# ---- Options ----
OPTION_SHOW_ALT_TEMPS = "show_alt_temperature_units"  # Show alternative temperature units
DEFAULT_OPTIONS = {
    OPTION_SHOW_ALT_TEMPS: False,  # Default: show system units only
}

# ---------------------------------------------------------------------------
# serviceDeviceType → human-readable component prefix
# ---------------------------------------------------------------------------
# Maps the last segment of a serviceDeviceType value to a display prefix.
# Used to disambiguate entities that share the same label on multi-component
# devices (e.g. Refrigerator has freshfood + freezer + icemaker sub-devices).
_SDEV_COMPONENT_LABELS: dict[str, str] = {
    "freshfood":    "Fresh Food",
    "freezer":      "Freezer",
    "icemaker":     "Ice Maker",
    "icemaker0":    "Ice Maker",
    "icemaker1":    "Ice Maker 2",
    "icedispenser": "Ice Dispenser",
    "dispenser":    "Dispenser",
    "hotwater":     "Hot Water",
    "door":         "Door",
    "probe":        "Probe",
    "cavity":       "Cavity",
    "drawer":       "Drawer",
    "pantry":       "Pantry",
}


def sdev_prefix(sdev: str) -> str:
    """Return a human-readable prefix from a serviceDeviceType string.

    Examples:
      "cloud.smarthq.device.refrigerator.freshfood"              → "Fresh Food"
      "cloud.smarthq.device.refrigerator.freezer"                → "Freezer"
      "cloud.smarthq.device.refrigerator.convertibledrawer.mode2"→ "Convertible Drawer Mode 2"
      "cloud.smarthq.device.refrigerator"                        → ""
      "cloud.smarthq.device.washer"                              → ""
    """
    if not sdev:
        return ""
    # Special case: convertibledrawer.modeN
    if "convertibledrawer" in sdev:
        last = sdev.split(".")[-1].lower()
        if last.startswith("mode"):
            n = last[4:]
            return f"Convertible Drawer Mode {n}" if n.isdigit() else "Convertible Drawer"
    last = sdev.split(".")[-1].lower()
    return _SDEV_COMPONENT_LABELS.get(last, "")
