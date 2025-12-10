# /config/custom_components/smarthq/__init__.py
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .const import DOMAIN
from .coordinator import SmartHQCoordinator

_LOGGER = logging.getLogger(__name__)

# LIGHT platform removed (switch handles lights)
PLATFORMS = ["sensor", "number", "switch", "binary_sensor", "select", "button"]

async def _maybe_await(x):
    """Await if x is a coroutine, else return as-is."""
    if asyncio.iscoroutine(x):
        return await x
    return x

async def _ws_start(ws) -> None:
    """Safely start ws regardless of start API."""
    if hasattr(ws, "async_start"):
        await ws.async_start()
        return
    if hasattr(ws, "start"):
        await _maybe_await(ws.start())
        return
    # Some implementations may use connect/use or other names
    if hasattr(ws, "connect"):
        await _maybe_await(ws.connect())
        return
    raise AttributeError("SmartHQWebsocket has no start/async_start/connect")

async def _ws_close(ws) -> None:
    """Safely close ws regardless of close API."""
    if hasattr(ws, "async_close"):
        await ws.async_close()
        return
    if hasattr(ws, "stop"):
        await _maybe_await(ws.stop())
        return
    if hasattr(ws, "close"):
        await _maybe_await(ws.close())
        return

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the SmartHQ component."""
    # Register OAuth2 implementation
    config_entry_oauth2_flow.async_register_implementation(
        hass,
        DOMAIN,
        config_entry_oauth2_flow.LocalOAuth2Implementation(
            hass,
            DOMAIN,
            client_id="YOUR_CLIENT_ID",  # Replace with actual Client ID
            client_secret="YOUR_CLIENT_SECRET",  # Replace with actual Client Secret
            authorize_url="https://accounts.brillion.geappliances.com/oauth2/auth",
            token_url="https://accounts.brillion.geappliances.com/oauth2/token",
        ),
    )
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """SmartHQ: One-time bootstrap + WebSocket real-time updates."""
    # Shared bucket
    hass.data.setdefault(DOMAIN, {})
    bucket: Dict[str, Any] = {}
    hass.data[DOMAIN][entry.entry_id] = bucket

    # API
    from .api import SmartHQApi  # Lazy import
    api = SmartHQApi(hass, entry)
    bucket["api"] = api

    # Coordinator (no polling; one-time load at boot)
    coord = SmartHQCoordinator(hass, api)
    bucket["coord"] = coord
    bucket["coordinator"] = coord  # For compatibility with number.py, switch.py

    # Real-time reference store
    store: Dict[str, Any] = {}
    bucket["store"] = store

    # First load (devices/settings/snapshot)
    await coord.async_config_entry_first_refresh()

    # Reflect coordinator data to store
    for did, payload in (coord.data or {}).items():
        info = payload.get("info") or {}
        settings_list = payload.get("settings") or []
        
        # Extract services from GET /v2/device/{did} response
        item = payload.get("item") or {}
        services_raw = item.get("services") or []
        
        # Convert services array to {serviceId: state} map
        services_map = {}
        index_map = {}
        for svc in services_raw:
            sid = str(svc.get("serviceId") or "")
            stype = str(svc.get("serviceType") or "")
            dtype = str(svc.get("domainType") or "")
            state = svc.get("state") or {}
            
            if sid:
                # Store metadata as well (same structure as ws_client.py)
                full_state = dict(state) if isinstance(state, dict) else {}
                full_state["serviceType"] = stype
                full_state["domainType"] = dtype
                if "serviceDeviceType" in svc:
                    full_state["serviceDeviceType"] = svc["serviceDeviceType"]
                if "label" in svc:
                    full_state["label"] = svc["label"]
                if "name" in svc:
                    full_state["name"] = svc["name"]
                if "config" in svc:
                    full_state["config"] = svc["config"]
                services_map[sid] = full_state
            if stype and dtype and sid:
                index_map[(stype, dtype)] = sid
        
        snapshot = {
            "raw": item,
            "services": services_map,
            "index": index_map,
            "deviceType": item.get("deviceType"),  # Add deviceType for switch.py
        }
        
        store[did] = {
            "info": info,
            "presence": payload.get("presence") or {},
            "settings": settings_list,
            "metrics": payload.get("metrics") or {"instant": {}},
            "snapshot": snapshot,
        }
        
        _LOGGER.debug(
            "Device %s: info=%s settings=%d services=%d",
            did, info.get("nickname"), len(settings_list), len(services_map)
        )

    # WebSocket connection
    from .ws_client import SmartHQWebsocket  # Lazy import
    ws = SmartHQWebsocket(
        hass=hass,
        api=api,
        store=store,
        device_ids=list(store.keys()),
    )
    await _ws_start(ws)

    # Store with key expected by entities (switch.py looks up 'client')
    bucket["client"] = ws
    # Optional: provide 'ws' alias for legacy code compatibility
    bucket["ws"] = ws
    
    # Settings polling task (every 30 seconds)
    async def _poll_settings():
        """Poll settings every 30 seconds since WebSocket doesn't update them."""
        from .dispatcher import SIGNAL_DEVICE_UPDATED
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        
        while True:
            await asyncio.sleep(30)
            try:
                for device_id in list(store.keys()):
                    try:
                        settings = await api.get_device_settings(device_id)
                        if settings:
                            old_settings = store.get(device_id, {}).get("settings", [])
                            # Detect changes
                            changed = False
                            if len(settings) != len(old_settings):
                                changed = True
                            else:
                                for new_s, old_s in zip(settings, old_settings):
                                    if new_s.get("current") != old_s.get("current"):
                                        changed = True
                                        break
                            
                            if changed:
                                store[device_id]["settings"] = settings
                                _LOGGER.info("[SETTINGS_POLL] Updated settings for %s", device_id[:8])
                                async_dispatcher_send(hass, SIGNAL_DEVICE_UPDATED.format(device_id=device_id))
                    except Exception as e:
                        _LOGGER.debug("[SETTINGS_POLL] Failed for %s: %s", device_id[:8], e)
            except Exception as e:
                _LOGGER.error("[SETTINGS_POLL] Error: %s", e)
    
    polling_task = hass.async_create_task(_poll_settings())
    bucket["settings_polling_task"] = polling_task

    # Register debug dump service
    async def _async_dump_service(call):
        did = call.data.get("device_id")
        store = bucket.get("store") or {}
        if did:
            data = store.get(did, {})
            _LOGGER.warning("[DUMP] %s -> %s", did, data)
        else:
            _LOGGER.warning("[DUMP_ALL] %s", store)

    hass.services.async_register(DOMAIN, "dump", _async_dump_service)
    
    # ----- Snapshot Debug Services -----
    root = hass.data.setdefault(DOMAIN, {})
    if not root.get("_services_registered"):

        async def _svc_alert_snapshot(call):
            """Display current store state as notification."""
            target_entry_id = call.data.get("entry_id")
            device_id = call.data.get("device_id")
            service_id_filter = call.data.get("service_id")

            target_bucket = None
            if target_entry_id:
                target_bucket = hass.data.get(DOMAIN, {}).get(target_entry_id)
            else:
                for eid, bkt in hass.data.get(DOMAIN, {}).items():
                    if isinstance(bkt, dict) and "store" in bkt:
                        target_bucket = bkt
                        target_entry_id = eid
                        break

            store = (target_bucket or {}).get("store") or {}
            dev = (store.get(device_id) or {}) if device_id else {}
            snap = dev.get("snapshot") or {}
            services = snap.get("services") or {}
            index = snap.get("index") or {}
            
            lines = []
            for sid, svc in services.items():
                if service_id_filter and sid != service_id_filter:
                    continue
                # Extract type/domain/label/mode/supportedModes
                stype = svc.get("serviceType") or ""
                dom = svc.get("domainType") or ""
                label = svc.get("label") or svc.get("name") or ""
                mode = svc.get("mode")
                cfg = svc.get("config") or {}
                sup = cfg.get("supportedModes") or []
                # Convert token array to clean string
                tokens = []
                for m in sup:
                    tokens.append(m if isinstance(m, str) else str(m.get("token")))
                # Reverse index (if available)
                rev = {v: k for k, v in index.items()} if isinstance(index, dict) else {}
                pair = rev.get(sid)  # ('cloud.smarthq.service.mode','cloud.smarthq.domain.light')
                lines.append(
                    f"- {sid}\n"
                    f"  type={stype}  domain={dom}  label={label}\n"
                    f"  index={pair}\n"
                    f"  mode={mode}\n"
                    f"  supportedModes={tokens}\n"
                )

            msg = (
                f"entry_id: {target_entry_id or 'none'}\n"
                f"device_id: {device_id or 'none'}\n"
                f"services_total: {len(services)}\n"
                f"detail:\n" + ("\n".join(lines) if lines else "  (no matching services)")
            )

            await hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title": "SmartHQ Snapshot",
                    "message": msg,
                    "notification_id": f"smarthq_snapshot_{(target_entry_id or 'none')}_{device_id or 'none'}",
                },
                blocking=False,
            )

        hass.services.async_register(DOMAIN, "alert_snapshot", _svc_alert_snapshot)
        root["_services_registered"] = True
    # ----- end Snapshot Debug -----

    # Enable debug notification service
    async def _async_enable_debug_alerts(call):
        """Enable debug persistent notifications for WS messages."""
        store["_debug_alerts"] = True
        _LOGGER.warning("[DEBUG] WS message notifications enabled")

    async def _async_disable_debug_alerts(call):
        """Disable debug persistent notifications."""
        store["_debug_alerts"] = False
        _LOGGER.warning("[DEBUG] WS message notifications disabled")

    hass.services.async_register(DOMAIN, "enable_debug_alerts", _async_enable_debug_alerts)
    hass.services.async_register(DOMAIN, "disable_debug_alerts", _async_disable_debug_alerts)

    # Cavity Light service
    async def _async_set_cavity_light_mode(call):
        """Set cavity light brightness mode."""
        device_id = call.data.get("device_id")
        service_id = call.data.get("service_id")
        mode = call.data.get("mode")
        
        if not device_id or not service_id or not mode:
            _LOGGER.error("Missing required parameters for set_cavity_light_mode")
            return
        
        client = bucket.get("client") or bucket.get("ws")
        if client:
            await client.async_set_mode(device_id, service_id, mode)
            _LOGGER.info("Cavity light mode set: device=%s service=%s mode=%s", device_id[:8], service_id[:8], mode)
        else:
            _LOGGER.error("WebSocket client not available")

    hass.services.async_register(DOMAIN, "set_cavity_light_mode", _async_set_cavity_light_mode)

    # Load platforms
    _LOGGER.info("[INIT] Loading platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("[INIT] Platforms loaded successfully")

    _LOGGER.info("SmartHQ setup complete (devices=%d)", len(store))
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry and clean up resources."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, {})
    
    # Cancel settings polling task
    polling_task = data.get("settings_polling_task")
    if polling_task and not polling_task.done():
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
    
    # Close WebSocket
    try:
        ws = data.get("client") or data.get("ws")
        if ws:
            await _ws_close(ws)
    except Exception as e:
        _LOGGER.debug("WebSocket close error: %s", e)

    return ok
