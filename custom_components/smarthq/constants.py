"""Constants for the SmartHQ ↔ Home Assistant Integration."""

from __future__ import annotations

# ---------------------------------------------------------------------
# ---------------------------------------------------------------------

DOMAIN = "smarthq"
NAME = "SmartHQ Integration"
MANUFACTURER = "GE Appliances"

# ---------------------------------------------------------------------
# ---------------------------------------------------------------------

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_TOKEN_EXPIRY = "token_expiry"
CONF_REGION = "region"
CONF_DEBUG = "debug"

CONF_RAW_DUMP = "raw_dump_enabled"
CONF_RAW_DUMP_DIR = "raw_dump_dir"
DEFAULT_DUMP_DIR = ".storage/smarthq_debug"

CONF_POLL_INTERVAL = "poll_interval"

# ---------------------------------------------------------------------
# ---------------------------------------------------------------------

API_BASE_URL = "https://api.smarthq.geappliances.com"
API_VERSION = "v2"

ENDPOINT_DEVICES = f"/{API_VERSION}/devices"
ENDPOINT_SERVICES = f"/{API_VERSION}/services"

API_TIMEOUT = 30

# ---------------------------------------------------------------------
# ---------------------------------------------------------------------

SENSOR_PREFIX = "sensor.smarthq_"
SWITCH_PREFIX = "switch.smarthq_"
BINARY_SENSOR_PREFIX = "binary_sensor.smarthq_"

# ---------------------------------------------------------------------
# ---------------------------------------------------------------------

DATA_API = f"{DOMAIN}_api"
DATA_COORDINATOR = f"{DOMAIN}_coordinator"

LOG_NAMESPACE = f"custom_components.{DOMAIN}"

SENSITIVE_KEYS = {
    "authorization",
    "access_token",
    "refresh_token",
    "id_token",
    "api-key",
    "x-api-key",
}

# ---------------------------------------------------------------------
# ---------------------------------------------------------------------

SERVICE_DUMP_SNAPSHOT = "dump_snapshot"
SERVICE_REFRESH = "force_refresh"

# ---------------------------------------------------------------------
# ---------------------------------------------------------------------

STATE_UNKNOWN = "unknown"
STATE_UNAVAILABLE = "unavailable"
STATE_ON = "on"
STATE_OFF = "off"

# ---------------------------------------------------------------------
# ---------------------------------------------------------------------

MAX_DEBUG_DATA_LEN = 3000

LOG_INFO = "[SmartHQ]"
LOG_DEBUG = "[SmartHQ DEBUG]"
LOG_ERROR = "[SmartHQ ERROR]"
