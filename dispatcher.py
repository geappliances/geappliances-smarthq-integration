# /config/custom_components/smarthq/dispatcher.py
from __future__ import annotations

SIGNAL_DEVICE_UPDATED = "smarthq_device_updated_{device_id}"

# Fired whenever the user picks a new cook mode (pending_cook_params is already
# refreshed before this signal is sent).  All param entities (time, temp,
# doneness, option, numeric) must subscribe so they re-render immediately.
SIGNAL_COOK_MODE_CHANGED = "smarthq_cook_mode_changed_{device_id}"
