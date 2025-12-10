"""Number platform for SmartHQ integration."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import SmartHQSmokerNumber

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartHQ number entities."""
    bucket = hass.data[DOMAIN][entry.entry_id]
    store = bucket.get("store") or {}
    
    entities = []
    for device_id, device_data in store.items():
        info = device_data.get("info") or {}
        device_type = info.get("deviceType", "").lower()
        
        if "smoker" in device_type or "grill" in device_type:
            nickname = info.get("nickname") or info.get("name") or "Smoker"
            
            # Target temperature control
            entities.append(
                SmartHQSmokerNumber(
                    bucket.get("api"),
                    hass,
                    bucket.get("coordinator"),
                    entry,  # Pass entry for pending state access
                    device_id,
                    f"{nickname} Target Temperature",
                    "target_temperature",
                    50,  # min temp in F
                    500  # max temp in F
                )
            )
            
            # Cook Time control (in minutes)
            entities.append(
                SmartHQSmokerNumber(
                    bucket.get("api"),
                    hass,
                    bucket.get("coordinator"),
                    entry,  # Pass entry for pending state access
                    device_id,
                    f"{nickname} Cook Time",
                    "cook_timer",
                    0,
                    720  # 12 hours max
                )
            )
            
            # Smoke Level control (0-5)
            entities.append(
                SmartHQSmokerNumber(
                    bucket.get("api"),
                    hass,
                    bucket.get("coordinator"),
                    entry,  # Pass entry for pending state access
                    device_id,
                    f"{nickname} Smoke Level",
                    "smoke_level",
                    0,  # min
                    5,  # max
                    step=1  # integer steps
                )
            )
            
            # Probe Target temperature
            entities.append(
                SmartHQSmokerNumber(
                    bucket.get("api"),
                    hass,
                    bucket.get("coordinator"),
                    entry,
                    device_id,
                    f"{nickname} Probe Target",
                    "probe_target",
                    32,  # min temp in F
                    250  # max temp in F
                )
            )
    
    if entities:
        async_add_entities(entities)
