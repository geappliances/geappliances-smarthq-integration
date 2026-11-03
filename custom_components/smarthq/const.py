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

# Assistant / messaging options (opt-in convenience features).
OPTION_AUTO_EXPOSE = "auto_expose_entities"  # Expose SmartHQ entities to Assist
OPTION_ENABLE_TELEGRAM = "enable_telegram_bridge"  # Telegram -> conversation bridge
OPTION_CONVERSATION_AGENT = "conversation_agent"  # conversation.* agent entity_id
OPTION_TELEGRAM_CHAT_IDS = "telegram_allowed_chat_ids"  # comma-separated chat ids

DEFAULT_OPTIONS = {
    OPTION_SHOW_ALT_TEMPS: False,  # Default: show system units only
    OPTION_AUTO_EXPOSE: True,  # Convenience: expose appliances to Assist by default
    OPTION_ENABLE_TELEGRAM: False,  # Telegram bridge is opt-in (needs a bot + agent)
    OPTION_CONVERSATION_AGENT: "",  # Empty until the user selects an agent
    OPTION_TELEGRAM_CHAT_IDS: "",  # Empty until the user lists allowed chat ids
}

# ---------------------------------------------------------------------------
# LLM tools / messaging control
# ---------------------------------------------------------------------------
# Identifier of the custom LLM API this integration registers with HA.
LLM_API_ID = "smarthq"
LLM_API_NAME = "SmartHQ Appliances"

# HA entity domains that must never be exposed to LLM-driven control through
# this integration's tools. Defense-in-depth: even if a user exposes these to
# Assist, the SmartHQ tools refuse to act on them.
LLM_BLOCKED_DOMAINS: frozenset[str] = frozenset(
    {
        "lock",
        "alarm_control_panel",
        "camera",
    }
)

# Appliance state values that are considered safety-sensitive. Any tool action
# that would start/modify these requires an explicit second confirmation.
LLM_DANGEROUS_KEYWORDS: tuple[str, ...] = (
    "oven",
    "cooktop",
    "range",
    "burner",
    "broil",
    "bake",
    "cook",
    "smoker",
    "advantium",
)

# ---------------------------------------------------------------------------
# serviceDeviceType → human-readable component prefix
# ---------------------------------------------------------------------------
# Maps the last segment of a serviceDeviceType value, or the last few run
# together ("dispenser.light" → "dispenserlight"), to a display prefix.
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
    "waterfilter":  "Water Filter",
    "fridgefocus":  "Fridge Focus",
    "defrostdelay": "Defrost Delay",
    "dispenserlight": "Dispenser Light",
}


# GE domain words that title-casing cannot split.
DOMAIN_WORDS: dict[str, str] = {
    "temperatureunits": "Temperature Units",
    "demandresponse": "Demand Response",
}


def domain_words(tail: str) -> str:
    """Readable words for a domain's last segment ("temperatureunits" → "Temperature Units")."""
    return DOMAIN_WORDS.get(tail.lower(), tail.replace("_", " ").title())


def strip_device_name(dev_name: str, label: str) -> str:
    """Drop a leading device name GE put in a label ("Refrigerator Light Wall" → "Light Wall").

    Entities here set has_entity_name, so Home Assistant composes the full name
    from the device name and the entity's own name; a device name inside the
    label would be shown twice.
    """
    if dev_name and label.lower().startswith(dev_name.lower() + " "):
        return label[len(dev_name) + 1:]
    return label  # an exact match is left alone; the caller decides what the main feature is


def entity_label(dev_name: str, sdev: str, label: str) -> str:
    """Build an entity's own name in one fixed order.

    1. Drop a leading appliance name GE put in the label ("Refrigerator Model"
       → "Model"); Home Assistant adds the device name itself.
    2. Put the sub-device in front once ("Model" + waterfilter → "Water Filter
       Model"), unless the label already starts with it.
    """
    label = strip_device_name(dev_name, label)
    prefix = sdev_prefix(sdev)
    if not prefix:
        return label
    lowered = label.lower()
    if lowered == prefix.lower() or lowered.startswith(prefix.lower() + " "):
        return label
    return f"{prefix} {label}"


def sdev_prefix(sdev: str) -> str:
    """Return a human-readable prefix from a serviceDeviceType string.

    Examples:
      "cloud.smarthq.device.refrigerator.freshfood"              → "Fresh Food"
      "cloud.smarthq.device.refrigerator.freezer"                → "Freezer"
      "cloud.smarthq.device.refrigerator.convertibledrawer.mode2"→ "Convertible Drawer Mode 2"
      "cloud.smarthq.device.refrigerator"                        → ""
      "cloud.smarthq.device.washer"                              → ""
      "cloud.smarthq.device.icemaker.1"                          → "Ice Maker"
      "cloud.smarthq.device.icemaker.2"                          → "Ice Maker 2"

    A trailing ".1" is omitted (a refrigerator's only ice maker is
    "icemaker.1"); any other numeric suffix is preserved, so ".2" reads
    "Ice Maker 2" and an unexpected ".0" reads "Ice Maker 0" rather than
    silently sharing a name.
    """
    if not sdev:
        return ""
    # Special case: convertibledrawer.modeN
    if "convertibledrawer" in sdev:
        last = sdev.split(".")[-1].lower()
        if last.startswith("mode"):
            n = last[4:]
            return f"Convertible Drawer Mode {n}" if n.isdigit() else "Convertible Drawer"
    parts = sdev.lower().split(".")[3:]  # after cloud.smarthq.device
    # A trailing instance number ("icemaker.1") is not a component name.
    suffix = ""
    if parts and parts[-1].isdigit():
        n = parts.pop()
        suffix = "" if n == "1" else f" {n}"
    # Longest known tail wins: "dispenser.light" before "light".
    for i in range(len(parts)):
        label = _SDEV_COMPONENT_LABELS.get("".join(parts[i:]))
        if label:
            return label + suffix
    return ""
