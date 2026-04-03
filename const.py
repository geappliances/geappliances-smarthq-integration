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
DEVICES_URL                 = f"{API_BASE}/v2/device"
DEVICE_PRESENCE_URL         = f"{API_BASE}/v2/device/{{device_id}}/presence"
DEVICE_SETTINGS_URL         = f"{API_BASE}/v2/device/{{device_id}}/setting"
DEVICE_SETTING_DETAIL_URL   = f"{API_BASE}/v2/device/{{device_id}}/setting/{{rule_id}}"
DEVICE_ITEM_URL             = f"{API_BASE}/v2/device/{{device_id}}"

INSTANT_METRICS_URL         = f"{API_BASE}/v2/device/instant/calculated"
HISTORY_METRICS_URL         = f"{API_BASE}/v2/device/history/calculated"

# Polling interval (legacy) - unused after WS-only transition
# DEFAULT_POLL_SECONDS = 15

# ---- Runtime tuning parameters ----
# Initial seed timeouts (seconds)
SEED_SETTINGS_TIMEOUT       = 4.0
SEED_SNAPSHOT_TIMEOUT       = 4.0
SEED_ALL_TIMEOUT            = 6.0
LIST_DEVICES_TIMEOUT        = 10.0

# WebSocket
WS_HEARTBEAT_SECONDS        = 60  # Heartbeat interval for idle connections
WS_BACKOFF_MAX              = 60  # Maximum backoff for reconnection
WS_RESUBSCRIBE_SECONDS      = 300
WS_MAX_RETRIES              = 3
WS_SUBSCRIBE_SETTLE_SECONDS = 0.5
WS_DEBUG_LOG_PATH           = "/config/smarthq_ws_debug.log"
WS_RECV_LOG_PATH            = "/config/smarthq_ws_recv.log"

# Polling / notifications
SETTINGS_POLL_INTERVAL_SECONDS      = 30
NOTIFICATION_ID_WEBSOCKET_FAILURE   = "smarthq_websocket_failure"
NOTIFICATION_ID_SNAPSHOT_PREFIX     = "smarthq_snapshot"

# ---- Options ----
OPTION_SHOW_ALT_TEMPS = "show_alt_temperature_units"  # Show alternative temperature units
DEFAULT_OPTIONS = {
    OPTION_SHOW_ALT_TEMPS: False,  # Default: show system units only
}
