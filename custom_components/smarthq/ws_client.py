from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import SmartHQApi
from .dispatcher import SIGNAL_DEVICE_UPDATED

_LOGGER = logging.getLogger(__name__)

PING_IDLE_SECONDS = 60
RESUBSCRIBE_SECONDS = 300


def _iter_service_items(container: Any) -> Iterable[Dict[str, Any]]:
    """Safely extract service items from services payload."""
    if isinstance(container, list):
        yield from (x for x in container if isinstance(x, dict))
        return
    if isinstance(container, dict):
        for key in ("update", "updates", "changed", "delta", "items", "services", "add"):
            val = container.get(key)
            if isinstance(val, list):
                yield from (x for x in val if isinstance(x, dict))


def _extract_service_tuple(item: Dict[str, Any]) -> Tuple[str, str, str, Dict[str, Any]] | None:
    """Extract (sid, stype, dom, state) from item."""
    sid = str(item.get("serviceId") or "")
    if not sid:
        return None
    stype = str(item.get("serviceType") or "")
    dom = str(item.get("domainType") or "")
    state = item.get("state") or {}
    state = state if isinstance(state, dict) else {}
    return sid, stype, dom, state


class SmartHQWebsocket:
    """SmartHQ WebSocket client."""

    def __init__(self, hass: HomeAssistant, *, api: SmartHQApi, device_ids: List[str], store: Dict[str, Any]) -> None:
        self.hass = hass
        self._api = api
        self._store = store or {}
        incoming = set(device_ids or [])
        known_in_store = {k for k, v in (self._store or {}).items() if isinstance(v, dict)}
        self._device_ids = set(incoming or known_in_store)
        self._session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        """Start the WebSocket connection."""
        self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._runner())

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._stopped.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
        if self._session:
            await self._session.close()

    async def _runner(self) -> None:
        """Main WebSocket connection loop with reconnection logic."""
        # Prepare debug file
        debug_file = "/config/smarthq_ws_debug.log"
        
        backoff = 1
        consecutive_failures = 0
        max_retries = 3
        
        while not self._stopped.is_set():
            try:
                endpoint = await self._api.async_get_websocket_endpoint()
                _LOGGER.info("Connecting SmartHQ WS -> %s", endpoint)

                async with self._session.ws_connect(endpoint, heartbeat=PING_IDLE_SECONDS) as ws:
                    self._ws = ws
                    _LOGGER.info("SmartHQ WS connected")
                    backoff = 1
                    consecutive_failures = 0  # Reset on successful connection

                    await self._subscribe_all(ws)

                    loop = asyncio.get_event_loop()
                    last_activity = loop.time()
                    last_subscribe = last_activity

                    async for msg in ws:
                        now = loop.time()
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            last_activity = now
                            try:
                                payload = json.loads(msg.data)

                                _LOGGER.debug("[WS_RECV_RAW] %s", json.dumps(payload, indent=2))
                                await self._on_message(payload)
                            except Exception as e:
                                _LOGGER.debug("WS message parse error: %s data=%s", e, msg.data)
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                            raise aiohttp.ClientError(str(msg))

                        if now - last_activity > PING_IDLE_SECONDS:
                            with contextlib.suppress(Exception):
                                await ws.send_json({"kind": "websocket#ping", "action": "ping"})
                            last_activity = now

                        if now - last_subscribe > RESUBSCRIBE_SECONDS:
                            with contextlib.suppress(Exception):
                                await self._subscribe_all(ws)
                            last_subscribe = now

            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                
                if consecutive_failures >= max_retries:
                    error_msg = (
                        f"SmartHQ WebSocket connection failed {consecutive_failures} times.\n\n"
                        f"Last error: {str(e)}\n\n"
                        f"Please check:\n"
                        f"- Internet connection\n"
                        f"- SmartHQ service status\n"
                        f"- OAuth2 credentials validity\n\n"
                        f"The integration will stop attempting to reconnect. "
                        f"Please restart Home Assistant or reload the SmartHQ integration to retry."
                    )
                    
                    _LOGGER.error(
                        "SmartHQ WS: Max retry limit (%d) reached. Stopping reconnection attempts. Error: %s",
                        max_retries, e
                    )
                    
                    # Send persistent notification to Home Assistant UI
                    try:
                        await self._hass.services.async_call(
                            "persistent_notification", "create",
                            {
                                "title": "⚠️ SmartHQ Connection Failed",
                                "message": error_msg,
                                "notification_id": "smarthq_websocket_failure",
                            },
                            blocking=False,
                        )
                    except Exception as notification_error:
                        _LOGGER.error("Failed to create notification: %s", notification_error)
                    
                    break  # Stop reconnection loop
                
                _LOGGER.warning(
                    "WS error (attempt %d/%d): %s; reconnect in %s sec",
                    consecutive_failures, max_retries, e, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            finally:
                self._ws = None

    async def _subscribe_all(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Subscribe to pubsub for account and all devices (strictly follow documentation)."""
        # Global subscription (page 2 Account Pubsub structure in docs)
        global_sub = {
            "kind": "websocket#pubsub",
            "action": "pubsub",
            "pubsub": True,
            "services": True,
            "presence": False,
            "alerts": True
        }
        _LOGGER.info("[SUBSCRIBE] Sending global subscription (FIXED): %s", json.dumps(global_sub, indent=2))
        await ws.send_json(global_sub)
        await asyncio.sleep(0.5)  # Wait for server response (increased)
        
        # Device-specific subscription (page 2 Device Pubsub structure in docs)
        for idx, did in enumerate(self._device_ids, 1):
            device_sub = {
                "kind": "websocket#pubsub",
                "action": "pubsub",
                "deviceId": did,
                "services": True,
                "presence": False,
                "alerts": True
            }
            _LOGGER.info(
                "[SUBSCRIBE] Sending device subscription %d/%d (FIXED): deviceId=%s",
                idx,
                len(self._device_ids),
                did[:8]
            )
            _LOGGER.debug("[SUBSCRIBE] Device sub payload: %s", json.dumps(device_sub, indent=2))
            await ws.send_json(device_sub)
            await asyncio.sleep(0.5)  # Wait for server response (increased)
        
        _LOGGER.info("[SUBSCRIBE] ✓ All subscriptions sent (%d devices), waiting for ACKs...", len(self._device_ids))

    async def _send_message(self, msg: Dict[str, Any]) -> None:
        """Send a message via WebSocket."""
        if not self._ws or self._ws.closed:
            raise RuntimeError("WebSocket is not connected")

        _LOGGER.debug("[WS_SEND] %s", json.dumps(msg, indent=2))
        await self._ws.send_json(msg)
    
    def _get_cooking_state(self, device_id: str) -> Dict[str, Any]:
        """Get cooking state service for a device."""
        snap = self._store.get(device_id, {}).get("snapshot", {})
        services = snap.get("services", {})
        
        # Find cooking.state.v1 service
        for service_id, state in services.items():
            if not isinstance(state, dict):
                continue
            if state.get("serviceType") == "cloud.smarthq.service.cooking.state.v1":
                return state
        
        return {}
    
    def _check_device_ready_for_commands(self, device_id: str, service_type: str = "") -> Tuple[bool, str]:
        """
        Check if device is in a state where it can accept commands.
        Returns (is_ready, reason_if_not_ready)
        
        service_type: Optional service type to determine if runStatus check is needed
        """
        # Check presence
        device_data = self._store.get(device_id, {})
        presence_info = device_data.get("presence", {})
        presence_status = presence_info.get("presence", "UNKNOWN")
        
        if presence_status != "ONLINE":
            return False, f"Device is {presence_status}"
        
        # For light/brightness services, presence check is enough
        # These should work even when device is in standby (runStatus=off)
        is_light_service = any(keyword in service_type.lower() for keyword in ["light", "brightness"])

        if is_light_service:
            _LOGGER.debug(
                "[DEVICE_STATE] %s: Light service detected - skipping runStatus check",
                device_id[:8]
            )
            return True, ""

        # Preference/settings services (e.g. temperatureunits, mode selections
        # that are device configuration rather than active cooking commands)
        # do NOT require remoteEnable — they are always available when ONLINE.
        _PREFERENCE_SERVICE_KEYWORDS = (
            "temperatureunits",
            "service.mode",
            "service.setting",
        )
        is_preference_service = any(kw in service_type.lower() for kw in _PREFERENCE_SERVICE_KEYWORDS)

        if is_preference_service:
            _LOGGER.debug(
                "[DEVICE_STATE] %s: Preference/settings service detected - skipping remoteEnable check",
                device_id[:8]
            )
            return True, ""
        
        # Check cooking state for non-light services
        cooking_state = self._get_cooking_state(device_id)
        if not cooking_state:
            # No cooking state - might be okay for simple devices
            return True, ""
        
        remote_enable = cooking_state.get("remoteEnable")
        if remote_enable is False:
            return False, "Remote control is disabled"
        
        run_status = cooking_state.get("runStatus", "")
        cooking_status = cooking_state.get("cookingStatus", "")
        
        _LOGGER.debug(
            "[DEVICE_STATE] %s: presence=%s, runStatus=%s, cookingStatus=%s, remoteEnable=%s",
            device_id[:8],
            presence_status,
            run_status,
            cooking_status,
            remote_enable
        )
        
        # For cooking services, warn if device is off but still allow the command
        # Let the device/server decide if the command should be accepted
        if "off" in str(run_status).lower():
            _LOGGER.warning(
                "[DEVICE_STATE] Device %s is OFF - some commands may timeout. "
                "Light commands should still work in standby.",
                device_id[:8]
            )
        
        return True, ""

    async def async_send_service_command(
        self,
        device_id: str,
        service: dict,
        command_type: str,
        command_params: dict | None = None,
    ) -> None:
        """Send a generic service command via the REST API.

        Args:
            device_id:      The target appliance's device ID.
            service:        The full service object from coordinator data
                            (must contain serviceType, domainType, serviceDeviceType).
            command_type:   The commandType string (e.g. "cloud.smarthq.command.toggle.set").
            command_params: Additional command parameters merged into the command body.
        """
        service_type = service.get("serviceType", "")
        domain_type = service.get("domainType", "")
        service_device_type = service.get("serviceDeviceType", "")

        if not service_type:
            raise ValueError("service must contain a non-empty 'serviceType'")
        if not service_device_type:
            raise ValueError("service must contain a non-empty 'serviceDeviceType'")

        _LOGGER.info(
            "[SERVICE_CMD] device=%s serviceType=%s domain=%s commandType=%s params=%s",
            device_id[:8],
            service_type,
            domain_type,
            command_type,
            command_params,
        )

        command: dict = {"commandType": command_type, **(command_params or {})}

        try:
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )
            _LOGGER.info("[SERVICE_CMD] ✓ Command sent successfully")
        except Exception as err:
            _LOGGER.error("[SERVICE_CMD] ✗ Failed: %s", err, exc_info=True)
            raise

    async def async_set_toggle(
        self,
        device_id: str,
        service_id: str,
        on: bool
    ) -> None:
        """Send toggle command via REST API."""
        _LOGGER.info(
            "[TOGGLE_CMD] device=%s service=%s -> on=%s",
            device_id[:8],
            service_id[:8],
            on,
        )
        
        # Get service metadata first to determine type
        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType", "cloud.smarthq.service.toggle")
        
        # Check device state with service type context
        is_ready, reason = self._check_device_ready_for_commands(device_id, service_type)
        if not is_ready:
            _LOGGER.error("[TOGGLE_CMD] Device not ready: %s - aborting command", reason)
            raise RuntimeError(f"Device not ready: {reason}")
        
        # Log device state before sending command
        cooking_state = self._get_cooking_state(device_id)
        presence_info = self._store.get(device_id, {}).get("presence", {})
        
        domain_type = service_meta.get("domainType", "")
        service_device_type = service_meta.get("serviceDeviceType", "")
        
        # Validate metadata - critical fields must not be empty
        if not service_type:
            _LOGGER.error("[TOGGLE_CMD] CRITICAL: serviceType is empty! metadata=%s", service_meta)
            raise ValueError("serviceType cannot be empty")
        if not service_device_type:
            _LOGGER.error("[TOGGLE_CMD] CRITICAL: serviceDeviceType is empty! metadata=%s", service_meta)
            raise ValueError("serviceDeviceType cannot be empty")
        
        _LOGGER.info(
            "[TOGGLE_CMD_STATE] Sending command with device state:\n"
            "  ServiceType: %s\n"
            "  ServiceDeviceType: %s\n"
            "  DomainType: %s\n"
            "  Presence: %s\n"
            "  RunStatus: %s\n"
            "  CookingStatus: %s\n"
            "  RemoteEnable: %s",
            service_type,
            service_device_type,
            domain_type,
            presence_info.get("presence", "UNKNOWN"),
            cooking_state.get("runStatus", "N/A"),
            cooking_state.get("cookingStatus", "N/A"),
            cooking_state.get("remoteEnable", "N/A")
        )

        # Build command dict
        command = {
            "commandType": "cloud.smarthq.command.toggle.set",
            "on": on
        }

        try:
            # Send via REST API
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )

            # Optimistic update
            snap = self._store.get(device_id, {}).get("snapshot", {})
            services = snap.get("services", {})
            if service_id in services:
                services[service_id]["on"] = on
                _LOGGER.debug(
                    "[TOGGLE_CMD] Optimistic update: service %s on=%s",
                    service_id[:8],
                    on,
                )

            _LOGGER.info("[TOGGLE_CMD] ✓ Command sent successfully")

        except Exception as e:
            _LOGGER.error("[TOGGLE_CMD] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_set_cooking_mode(self, device_id: str, service_id: str, mode_token: str,
                                     cavity_temp_f: int = None, cook_time_minutes: int = None,
                                     probe_temp_f: int = None, smoke_level: int = None,
                                     auto_keep_warm: bool = None,
                                     doneness_level: str = None,
                                     cook_option: str = None,
                                     numeric_option: int = None) -> None:
        """Send cooking mode command via REST API.

        Note: cooking mode command does not use serviceId,
        but directly sets selected cook mode in domainType.
        Temperature, timer, probe target, smoke level, auto keep warm,
        doneness level, option and numeric option can also be set together.
        """
        _LOGGER.info(
            "[COOKING_MODE_CMD] device=%s mode_domain=%s, temp=%s°F, timer=%smin, probe=%s°F, smoke=%s, warm=%s",
            device_id[:8], mode_token, cavity_temp_f, cook_time_minutes, probe_temp_f, smoke_level, auto_keep_warm
        )
        
        # Check device state
        is_ready, reason = self._check_device_ready_for_commands(device_id)
        if not is_ready:
            _LOGGER.error("[COOKING_MODE_CMD] Cannot send command: %s", reason)
            raise RuntimeError(f"Device not ready for commands: {reason}")
        
        # Build command object
        command = {
            "commandType": "cloud.smarthq.command.cooking.mode.v1.set"
        }
        
        # Add temperature if provided
        if cavity_temp_f is not None:
            command["cavityFahrenheit"] = cavity_temp_f
        
        # Add probe target if provided
        if probe_temp_f is not None:
            command["probeFahrenheit"] = probe_temp_f
        
        # Add cook time if provided
        if cook_time_minutes is not None:
            command["cookTimeSeconds"] = cook_time_minutes * 60
        
        # Add smoke level if provided (Smoker-specific; uses numericOptionValue
        # ONLY when no generic numeric_option is also set).
        if smoke_level is not None and numeric_option is None:
            command["numericOptionValue"] = smoke_level

        # Add auto keep warm if provided
        if auto_keep_warm is not None:
            command["autoKeepWarm"] = auto_keep_warm

        # Add doneness level if provided (cookie, pizza, toast, bagel…)
        if doneness_level is not None:
            command["donenessLevel"] = doneness_level

        # Add cook option if provided (cookie freshness, pizza type…)
        if cook_option is not None:
            command["option"] = cook_option

        # Add numeric option if provided (slice count, pizza size…).
        # This wins over smoke_level because they share numericOptionValue.
        if numeric_option is not None:
            command["numericOptionValue"] = numeric_option

        # Look up the serviceDeviceType for this mode domain from the stored snapshot.
        # This is required because different device types (Toaster Oven, Smoker, Oven)
        # use different serviceDeviceType values in the REST API.
        # We only look within THIS device's snapshot — never fall back to another device.
        snap = self._store.get(device_id, {}).get("snapshot", {})
        service_device_type: str | None = None

        # Pass 1: exact match on domainType == mode_token
        for svc in (snap.get("services") or {}).values():
            if not isinstance(svc, dict):
                continue
            if svc.get("domainType") == mode_token:
                sdt = svc.get("serviceDeviceType") or ""
                if sdt:
                    service_device_type = sdt
                break

        # Pass 2: any cooking.mode.v1 service on this device (same device, different domain)
        if not service_device_type:
            for svc in (snap.get("services") or {}).values():
                if not isinstance(svc, dict):
                    continue
                if svc.get("serviceType") == "cloud.smarthq.service.cooking.mode.v1":
                    sdt = svc.get("serviceDeviceType") or ""
                    if sdt:
                        service_device_type = sdt
                        break

        if not service_device_type:
            _LOGGER.error(
                "[COOKING_MODE_CMD] Could not determine serviceDeviceType for device=%s "
                "mode=%s — aborting to avoid sending command to wrong device type",
                device_id[:8], mode_token,
            )
            raise RuntimeError(
                f"serviceDeviceType unknown for device {device_id[:8]}, mode {mode_token}"
            )

        _LOGGER.info("[COOKING_MODE_CMD] Using serviceDeviceType=%s", service_device_type)

        try:
            # Send via REST API
            await self._api.async_send_command(
                device_id=device_id,
                service_type="cloud.smarthq.service.cooking.mode.v1",
                domain_type=mode_token,
                service_device_type=service_device_type,
                command=command,
            )
            
            _LOGGER.info("[COOKING_MODE_CMD] ✓ Command sent successfully")
            
        except Exception as e:
            _LOGGER.error("[COOKING_MODE_CMD] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_power_off_smoker(self, device_id: str) -> None:
        """Power off smoker (set to Standby state).
        
        Approach: Send minimal cooking mode command without optional parameters.
        Let the device/API handle the power off based on command structure.
        """
        _LOGGER.info("[POWER_OFF_CMD] device=%s - Powering off smoker to Standby", device_id[:8])
        
        # Get current cooking mode from device state
        snap = self._store.get(device_id, {}).get("snapshot", {})
        services = snap.get("services", {})
        
        # Find cooking.mode service to get current mode
        current_mode = "cloud.smarthq.domain.cooking.custom"  # default fallback
        for sid, svc in services.items():
            if not isinstance(svc, dict):
                continue
            stype = str(svc.get("serviceType") or "")
            if stype == "cloud.smarthq.service.cooking.mode.v1":
                domain = str(svc.get("domainType") or "")
                if domain and "cooking" in domain:
                    current_mode = domain
                    break
        
        _LOGGER.debug("[POWER_OFF_CMD] Using cooking mode: %s", current_mode)
        
        # Look up serviceDeviceType from this device's snapshot
        service_device_type: str | None = None
        for svc in services.values():
            if not isinstance(svc, dict):
                continue
            if svc.get("serviceType") == "cloud.smarthq.service.cooking.mode.v1":
                sdt = svc.get("serviceDeviceType") or ""
                if sdt:
                    service_device_type = sdt
                    break

        if not service_device_type:
            _LOGGER.error("[POWER_OFF_CMD] Could not determine serviceDeviceType for device=%s", device_id[:8])
            raise RuntimeError(f"serviceDeviceType unknown for device {device_id[:8]}")

        # Try sending just the command type - let API handle power off
        # Don't include cooking parameters at all
        command = {
            "commandType": "cloud.smarthq.command.cooking.mode.v1.set"
        }
        
        try:
            # Send via REST API
            await self._api.async_send_command(
                device_id=device_id,
                service_type="cloud.smarthq.service.cooking.mode.v1",
                domain_type=current_mode,
                service_device_type=service_device_type,
                command=command,
            )
            
            _LOGGER.info("[POWER_OFF_CMD] ✓ Power off command sent successfully")
            
        except Exception as e:
            _LOGGER.error("[POWER_OFF_CMD] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_set_mode(self, device_id: str, service_id: str, mode_token: str) -> None:
        """Send mode change command via REST API."""
        _LOGGER.info("[MODE_CMD] device=%s service=%s -> mode=%s", device_id[:8], service_id[:8], mode_token)
        
        # Get service metadata first to determine type
        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType", "cloud.smarthq.service.mode")
        domain_type = service_meta.get("domainType", "")
        service_device_type = service_meta.get("serviceDeviceType", "")
        
        # Check device state with service type context
        is_ready, reason = self._check_device_ready_for_commands(device_id, service_type)
        if not is_ready:
            _LOGGER.error("[MODE_CMD] Device not ready: %s - aborting command", reason)
            raise RuntimeError(f"Device not ready: {reason}")
        
        # Log device state before sending command
        cooking_state = self._get_cooking_state(device_id)
        presence_info = self._store.get(device_id, {}).get("presence", {})
        
        # Validate metadata - critical fields must not be empty
        if not service_type:
            _LOGGER.error("[MODE_CMD] CRITICAL: serviceType is empty! metadata: serviceType=%s, serviceDeviceType=%s, domainType=%s", service_type, service_device_type, domain_type)
            raise ValueError("serviceType cannot be empty")
        if not service_device_type:
            _LOGGER.error("[MODE_CMD] CRITICAL: serviceDeviceType is empty! metadata: serviceType=%s, serviceDeviceType=%s, domainType=%s", service_type, service_device_type, domain_type)
            raise ValueError("serviceDeviceType cannot be empty")
        
        _LOGGER.info(
            "[MODE_CMD_STATE] Sending command with device state:\n"
            "  ServiceType: %s\n"
            "  ServiceDeviceType: %s\n"
            "  DomainType: %s\n"
            "  Presence: %s\n"
            "  RunStatus: %s\n"
            "  CookingStatus: %s\n"
            "  RemoteEnable: %s",
            service_type,
            service_device_type,
            domain_type,
            presence_info.get("presence", "UNKNOWN"),
            cooking_state.get("runStatus", "N/A"),
            cooking_state.get("cookingStatus", "N/A"),
            cooking_state.get("remoteEnable", "N/A")
        )
        
        # Build command dict
        command = {
            "commandType": "cloud.smarthq.command.mode.set",
            "mode": mode_token
        }
        
        try:
            # Send via REST API
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )
            
            # Optimistic update
            snap = self._store.get(device_id, {}).get("snapshot", {})
            services = snap.get("services", {})
            if service_id in services:
                services[service_id]["mode"] = mode_token
                # Update on state based on mode
                mode_str = str(mode_token).lower()
                services[service_id]["on"] = mode_str.endswith(".on") or "on" in mode_str
                _LOGGER.debug(
                    "[MODE_CMD] Optimistic update: service %s mode=%s",
                    service_id[:8],
                    mode_token,
                )
            
            _LOGGER.info("[MODE_CMD] ✓ Command sent successfully")
            
        except Exception as e:
            _LOGGER.error("[MODE_CMD] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_set_laundry_mode(
        self, device_id: str, service_id: str, domain_token: str
    ) -> None:
        """Send cloud.smarthq.command.laundry.mode.v1.set via REST API.

        Args:
            device_id:    Device ID string
            service_id:   The specific laundry.mode.v1 service ID for this domain
            domain_token: The full domain type token (e.g. cloud.smarthq.domain.laundry.jeans)
        """
        _LOGGER.info(
            "[LAUNDRY_MODE] device=%s service=%s -> domain=%s",
            device_id[:8], service_id[:8], domain_token,
        )

        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType") or "cloud.smarthq.service.laundry.mode.v1"
        service_device_type = service_meta.get("serviceDeviceType") or ""
        domain_type = service_meta.get("domainType") or domain_token

        if not service_device_type:
            _LOGGER.error("[LAUNDRY_MODE] serviceDeviceType missing for service %s", service_id[:8])
            raise ValueError("serviceDeviceType cannot be empty for laundry mode command")

        command = {
            "commandType": "cloud.smarthq.command.laundry.mode.v1.set",
        }

        try:
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )
            _LOGGER.info("[LAUNDRY_MODE] ✓ Command sent successfully")
        except Exception as e:
            _LOGGER.error("[LAUNDRY_MODE] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_set_laundry_toggle_v2(
        self, device_id: str, service_id: str, on: bool
    ) -> None:
        """Send cloud.smarthq.command.laundry.toggle.v2.set via REST API."""
        _LOGGER.info(
            "[LAUNDRY_TOGGLE_V2] device=%s service=%s -> on=%s",
            device_id[:8], service_id[:8], on,
        )
        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType") or "cloud.smarthq.service.laundry.toggle.v2"
        service_device_type = service_meta.get("serviceDeviceType") or ""
        domain_type = service_meta.get("domainType") or ""

        if not service_device_type:
            raise ValueError("serviceDeviceType cannot be empty for laundry.toggle.v2 command")

        command = {
            "commandType": "cloud.smarthq.command.laundry.toggle.v2.set",
            "on": on,
        }

        try:
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )
            _LOGGER.info("[LAUNDRY_TOGGLE_V2] ✓ Command sent successfully")
        except Exception as e:
            _LOGGER.error("[LAUNDRY_TOGGLE_V2] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_set_dishwasher_mode(
        self, device_id: str, service_id: str, domain_token: str
    ) -> None:
        """Send cloud.smarthq.command.dishwasher.mode.v1.set via REST API."""
        _LOGGER.info(
            "[DISHWASHER_MODE] device=%s service=%s -> domain=%s",
            device_id[:8], service_id[:8], domain_token,
        )
        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType") or "cloud.smarthq.service.dishwasher.mode.v1"
        service_device_type = service_meta.get("serviceDeviceType") or ""
        domain_type = service_meta.get("domainType") or domain_token

        if not service_device_type:
            raise ValueError("serviceDeviceType cannot be empty for dishwasher mode command")

        command = {"commandType": "cloud.smarthq.command.dishwasher.mode.v1.set"}
        try:
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )
            _LOGGER.info("[DISHWASHER_MODE] ✓ Command sent successfully")
        except Exception as e:
            _LOGGER.error("[DISHWASHER_MODE] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_dishwasher_state_command(
        self, device_id: str, service_id: str, command_type: str
    ) -> None:
        """Send dishwasher.state.v1 start/stop/pause command via REST API."""
        _LOGGER.info(
            "[DISHWASHER_STATE] device=%s service=%s -> %s",
            device_id[:8], service_id[:8], command_type,
        )
        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType") or "cloud.smarthq.service.dishwasher.state.v1"
        service_device_type = service_meta.get("serviceDeviceType") or ""
        domain_type = service_meta.get("domainType") or ""

        if not service_device_type:
            raise ValueError("serviceDeviceType cannot be empty for dishwasher state command")

        command = {"commandType": command_type}
        try:
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )
            _LOGGER.info("[DISHWASHER_STATE] ✓ %s sent successfully", command_type)
        except Exception as e:
            _LOGGER.error("[DISHWASHER_STATE] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_advantium_command(
        self, device_id: str, service_id: str, command_type: str
    ) -> None:
        """Send cooking.advantium start/stop/pause/resume command via REST API."""
        _LOGGER.info(
            "[ADVANTIUM] device=%s service=%s -> %s",
            device_id[:8], service_id[:8], command_type,
        )
        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType") or "cloud.smarthq.service.cooking.advantium"
        service_device_type = service_meta.get("serviceDeviceType") or ""
        domain_type = service_meta.get("domainType") or ""

        command = {"commandType": command_type}
        try:
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )
            _LOGGER.info("[ADVANTIUM] ✓ %s sent successfully", command_type)
        except Exception as e:
            _LOGGER.error("[ADVANTIUM] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_set_generic_mode(
        self,
        device_id: str,
        service_id: str,
        command_type: str,
        mode_token: str,
        extra_params: dict | None = None,
    ) -> None:
        """Send a generic mode set command (flexdispense, stainremoval, etc.)."""
        _LOGGER.info(
            "[GENERIC_MODE] device=%s service=%s cmd=%s mode=%s",
            device_id[:8], service_id[:8], command_type, mode_token,
        )
        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType") or ""
        service_device_type = service_meta.get("serviceDeviceType") or ""
        domain_type = service_meta.get("domainType") or ""

        command: dict = {"commandType": command_type, "mode": mode_token}
        if extra_params:
            command.update(extra_params)

        try:
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )
            _LOGGER.info("[GENERIC_MODE] ✓ Command sent successfully")
        except Exception as e:
            _LOGGER.error("[GENERIC_MODE] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_set_thermostat(
        self,
        device_id: str,
        service_id: str,
        **params,
    ) -> None:
        """Send thermostat.v1.set command — pass kwargs as command fields (mode, on, fanSpeed, coolFahrenheit, etc.)."""
        _LOGGER.info("[THERMOSTAT] device=%s service=%s params=%s", device_id[:8], service_id[:8], params)
        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType") or "cloud.smarthq.service.thermostat.v1"
        service_device_type = service_meta.get("serviceDeviceType") or ""
        domain_type = service_meta.get("domainType") or ""

        command: dict = {"commandType": "cloud.smarthq.command.thermostat.v1.set"}
        command.update(params)
        try:
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )
            _LOGGER.info("[THERMOSTAT] ✓ Command sent successfully")
        except Exception as e:
            _LOGGER.error("[THERMOSTAT] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_set_waterheater(
        self,
        device_id: str,
        service_id: str,
        **params,
    ) -> None:
        """Send waterheater.v1.set command — pass kwargs as command fields (mode, setpointFahrenheit, capacity)."""
        _LOGGER.info("[WATERHEATER] device=%s service=%s params=%s", device_id[:8], service_id[:8], params)
        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType") or "cloud.smarthq.service.waterheater.v1"
        service_device_type = service_meta.get("serviceDeviceType") or ""
        domain_type = service_meta.get("domainType") or ""

        command: dict = {"commandType": "cloud.smarthq.command.waterheater.v1.set"}
        command.update(params)
        try:
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )
            _LOGGER.info("[WATERHEATER] ✓ Command sent successfully")
        except Exception as e:
            _LOGGER.error("[WATERHEATER] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_set_color(
        self,
        device_id: str,
        service_id: str,
        **params,
    ) -> None:
        """Send color.set command.

        Accepted kwargs (at least one required):
          rgb="#RRGGBB"                         — RGB hex string
          hsb={"hue": 0, "saturation": 0.5, "brightness": 0.5}
          whitenessTemperatureKelvin=3100
          red, green, blue, intensity           — individual RGB+intensity components
        """
        _LOGGER.info("[COLOR] device=%s service=%s params=%s", device_id[:8], service_id[:8], params)
        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType") or "cloud.smarthq.service.color"
        domain_type = service_meta.get("domainType") or ""
        service_device_type = service_meta.get("serviceDeviceType") or ""

        command: dict = {"commandType": "cloud.smarthq.command.color.set"}
        command.update(params)
        try:
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )
            _LOGGER.info("[COLOR] ✓ Command sent successfully")
        except Exception as e:
            _LOGGER.error("[COLOR] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_set_accent_light(
        self,
        device_id: str,
        service_id: str,
        **params,
    ) -> None:
        """Send cooking.prorange.accent.light.set command.

        Accepted kwargs (all optional):
          brightness       : int (0-100)
          colorTemperature : int (Kelvin)
          customColorActive: bool
          customColorCode  : str
        """
        _LOGGER.info("[ACCENT_LIGHT] device=%s service=%s params=%s", device_id[:8], service_id[:8], params)
        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType") or "cloud.smarthq.service.cooking.prorange.accent.light"
        domain_type = service_meta.get("domainType") or ""
        service_device_type = service_meta.get("serviceDeviceType") or ""

        command: dict = {"commandType": "cloud.smarthq.command.cooking.prorange.accent.light.set"}
        command.update(params)
        try:
            await self._api.async_send_command(
                device_id=device_id,
                service_type=service_type,
                domain_type=domain_type,
                service_device_type=service_device_type,
                command=command,
            )
            _LOGGER.info("[ACCENT_LIGHT] ✓ Command sent successfully")
        except Exception as e:
            _LOGGER.error("[ACCENT_LIGHT] ✗ Failed: %s", e, exc_info=True)
            raise

    async def async_set_smoke_level(self, device_id: str, service_id: str, level: int) -> None:
        """Send smoke level command using official format."""
        _LOGGER.info("[SMOKE_CMD] device=%s service=%s -> level=%s", device_id[:8], service_id[:8], level)        
        service_meta = self._get_service_metadata(device_id, service_id)
        service_type = service_meta.get("serviceType", "cloud.smarthq.service.integer")
        domain_type = service_meta.get("domainType", "")
        device_type = service_meta.get("deviceType", "")
        
        payload = {
            "kind": "service#command",
            "deviceId": device_id,
            "serviceType": service_type,
            "domainType": domain_type,
            "serviceDeviceType": device_type,
            "command": {
                "commandType": "cloud.smarthq.command.integer.set",
                "numericOptionValue": level
            }
        }
        
        try:
            _LOGGER.info("[SMOKE_CMD] Sending: %s", json.dumps(payload, indent=2))
            if self._ws and not self._ws.closed:
                await self._ws.send_json(payload)
                await asyncio.sleep(0.5)
                _LOGGER.info("[SMOKE_CMD] ✓ Command sent")
                return
        except Exception as e:
            _LOGGER.error("[SMOKE_CMD] ✗ Exception: %s", e, exc_info=True)

    def _get_service_metadata(self, device_id: str, service_id: str) -> Dict[str, Any]:
        """Extract service metadata from store for command construction."""
        dev_data = self._store.get(device_id, {})
        snap = dev_data.get("snapshot", {})
        info = dev_data.get("info", {})
        
        # 1. First, search directly in services array of raw data (most accurate)
        raw_item = snap.get("raw", {})
        if isinstance(raw_item, dict):
            # raw_item itself could be a service update
            if raw_item.get("serviceId") == service_id:
                result = {
                    "serviceType": raw_item.get("serviceType", ""),
                    "domainType": raw_item.get("domainType", ""),
                    "serviceDeviceType": raw_item.get("serviceDeviceType", info.get("deviceType", "")),
                }
                _LOGGER.debug(
                    "[METADATA] Found via raw_item direct match (case 1): %s",
                    json.dumps(result, indent=2)
                )
                return result
            
            # Search services array
            if "services" in raw_item:
                for svc in raw_item.get("services", []):
                    if svc.get("serviceId") == service_id:
                        result = {
                            "serviceType": svc.get("serviceType", ""),
                            "domainType": svc.get("domainType", ""),
                            "serviceDeviceType": svc.get("serviceDeviceType", info.get("deviceType", "")),
                        }
                        _LOGGER.debug(
                            "[METADATA] Found via raw services array (case 1b): %s",
                            json.dumps(result, indent=2)
                        )
                        return result
        
        # 2. Check metadata in services dictionary (meta saved during update)
        services = snap.get("services", {})
        if service_id in services:
            svc_state = services[service_id]
            if "serviceType" in svc_state or "domainType" in svc_state:
                result = {
                    "serviceType": svc_state.get("serviceType", ""),
                    "domainType": svc_state.get("domainType", ""),
                    "serviceDeviceType": svc_state.get("serviceDeviceType", info.get("deviceType", "")),
                }
                _LOGGER.debug(
                    "[METADATA] Found via services dict (case 2): %s",
                    json.dumps(result, indent=2)
                )
                return result
        
        # 3. Reverse infer from index
        index = snap.get("index", {})
        for (stype, dtype), sid in index.items():
            if sid == service_id:
                # serviceDeviceType must be fetched directly from services!
                svc_state = services.get(service_id, {})
                service_device_type = svc_state.get("serviceDeviceType", "")
                
                parent_device_type = info.get("deviceType", "")
                
                # Fallback: use parent deviceType if serviceDeviceType is missing
                if not service_device_type:
                    _LOGGER.warning(
                        "[METADATA] serviceDeviceType missing, using parent deviceType: %s",
                        parent_device_type
                    )
                    service_device_type = parent_device_type
                
                result = {
                    "serviceType": stype,
                    "domainType": dtype,
                    "serviceDeviceType": service_device_type,
                }
                _LOGGER.debug(
                    "[METADATA] Found via index (case 3): %s",
                    json.dumps(result, indent=2)
                )
                return result
        
        # 4. Final fallback
        _LOGGER.warning(
            "[METADATA] No metadata found for service %s/%s, returning empty fallback",
            device_id[:8],
            service_id[:8]
        )
        return {
            "serviceType": "",
            "domainType": "",
            "serviceDeviceType": info.get("deviceType", ""),
        }

    def _optimistic_toggle_update(self, service_id: str, on: bool) -> None:
        """Optimistically update toggle state before server confirmation."""
        for device_id, dev_data in self._store.items():
            snap = dev_data.get("snapshot") or {}
            services = snap.get("services") or {}
            if service_id in services:
                services[service_id]["on"] = on
                _LOGGER.debug("[TOGGLE_CMD] Optimistic update: service %s on=%s", service_id[:8], on)
                # Send dispatcher signal
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_DEVICE_UPDATED.format(device_id=device_id)
                )
                break

    async def _on_message(self, payload: Dict[str, Any]) -> None:
        """Apply events to store and notify entities."""
        kind = str(payload.get("kind") or "")

        # ===== Log kind of all messages =====
        _LOGGER.debug("[WS_RECV] kind=%s, keys=%s", kind, list(payload.keys()))
        # ==================================
        
        # Handle subscription confirmation (ACK) - websocket#pubsub with success
        if kind == "websocket#pubsub" and "success" in payload:
            success = payload.get("success", False)
            device_id = payload.get("deviceId")
            
            if device_id:
                _LOGGER.info(
                    "[SUBSCRIBE_ACK] ✓ Device subscription confirmed: deviceId=%s, success=%s",
                    device_id[:8] if device_id else "N/A",
                    success
                )
            else:
                _LOGGER.info("[SUBSCRIBE_ACK] ✓ Global subscription confirmed: success=%s", success)
            
            return
        
        # Command API response (websocket#api)
        if kind == "websocket#api":
            cmd_id = payload.get("id")
            code = payload.get("code")
            body = payload.get("body", {})
            
            # Handle error responses
            if code >= 400:
                error_kind = body.get("kind", "")
                error_msg = body.get("message", "")
                error_reason = body.get("reason", "")
                
                _LOGGER.error(
                    "[COMMAND_ERROR] id=%s, code=%s, kind=%s, message=%s, reason=%s",
                    cmd_id,
                    code,
                    error_kind,
                    error_msg,
                    error_reason
                )
                return
            
            success = body.get("success", False)
            outcome = body.get("outcome", "")
            
            _LOGGER.info(
                "[COMMAND_RESPONSE] id=%s, code=%s, success=%s, outcome=%s",
                cmd_id,
                code,
                success,
                outcome
            )
            
            return
        
        # Handle general ACK (websocket#ack)
        if kind == "websocket#ack" or "ack" in kind.lower():
            msg_id = payload.get("id") or payload.get("messageId")
            success = payload.get("success", True)
            action = payload.get("action")
            
            _LOGGER.debug("[WS_ACK] Command acknowledged: id=%s, action=%s, success=%s", msg_id, action, success)
            
            return
        
        # Handle error
        if "error" in kind.lower() or "error" in payload:
            error_msg = payload.get("error") or payload.get("message") or payload
            _LOGGER.error("[WS_ERROR] Server error: %s", json.dumps(error_msg, indent=2))
            return
        
        # Handle ACK
        if kind == "websocket#ack" or "ack" in kind.lower():
            _LOGGER.debug("[WS_ACK] Command acknowledged: %s", payload.get("id"))
            return
        
        # Extract device ID
        did = (
            payload.get("deviceId") 
            or payload.get("device_id")
            or (payload.get("item") or {}).get("deviceId")
            or (payload.get("body") or {}).get("deviceId")
        )
        
        if did:
            did = str(did)
            if did not in self._device_ids:
                self._device_ids.add(did)
                _LOGGER.debug("Learned new deviceId: %s", did)

        # Handle command outcome (timeout detection)
        if kind == "pubsub#command" and "outcome" in payload:
            outcome = payload.get("outcome", "")
            correlation_id = payload.get("correlationId", "N/A")
            command_type = payload.get("command", {}).get("commandType", "unknown")
            service_type = payload.get("serviceType", "")
            domain_type = payload.get("domainType", "")
            
            if "timeout" in outcome.lower():
                # Timeout occurred - log device state
                _LOGGER.error(
                    "[COMMAND_TIMEOUT] Command failed after 20s\n"
                    "  Device: %s\n"
                    "  Command: %s\n"
                    "  Service: %s\n"
                    "  Domain: %s\n"
                    "  CorrelationId: %s",
                    did[:8] if did else "N/A",
                    command_type,
                    service_type,
                    domain_type,
                    correlation_id
                )
                
                # Additional logging of device state info
                if did:
                    cooking_state = self._get_cooking_state(did)
                    presence_info = self._store.get(did, {}).get("presence", {})
                    presence = presence_info.get("presence", "UNKNOWN")
                    
                    _LOGGER.error(
                        "[COMMAND_TIMEOUT_STATE] Device state when timeout occurred:\n"
                        "  Presence: %s\n"
                        "  RunStatus: %s\n"
                        "  CookingStatus: %s\n"
                        "  RemoteEnable: %s\n"
                        "  → Device may not respond to commands in current state",
                        presence,
                        cooking_state.get("runStatus", "N/A"),
                        cooking_state.get("cookingStatus", "N/A"),
                        cooking_state.get("remoteEnable", "N/A")
                    )
            else:
                _LOGGER.info(
                    "[COMMAND_OUTCOME] Command completed: %s (correlation=%s)",
                    outcome,
                    correlation_id[:8] if len(correlation_id) > 8 else correlation_id
                )
            return
        
        # Handle alert
        if kind.startswith("publish#alert") or "alert" in kind.lower():
            body = payload.get("body") or payload.get("item") or payload
            alert_type = body.get("alertType") or body.get("type")
            
            if did and isinstance(alert_type, str) and alert_type.startswith("cloud.smarthq.alert."):
                dev = self._store.setdefault(did, {})
                alerts = dev.setdefault("alerts", {})
                
                is_clear = "clear" in kind.lower() or body.get("cleared") is True
                
                alerts[alert_type] = {
                    "last_ts": body.get("timestamp") or payload.get("timestamp"),
                    "message": body.get("message") or body.get("title") or "",
                    "raw": body,
                    "active": not is_clear,
                }
                
                _LOGGER.info("[ALERT] %s: %s (active=%s)", did[:8], alert_type, not is_clear)
                async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATED.format(device_id=did))

                # Publish to HA Event Bus so automations can react
                self.hass.bus.async_fire(
                    "smarthq_alert",
                    {
                        "device_id": did,
                        "alert_type": alert_type,
                        "active": not is_clear,
                        "data": body,
                    },
                )
                return

        # Handle presence
        if "presence" in payload and did:
            dev = self._store.setdefault(did, {})
            pres = payload.get("presence")
            dev["presence"] = pres if isinstance(pres, dict) else {"status": pres}
            _LOGGER.debug("[PRESENCE] %s: %s", did[:8], dev["presence"])
            async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATED.format(device_id=did))
            return

        # Handle settings update
        if kind == "device#setting" or "setting" in kind.lower():
            _LOGGER.warning("[SETTING_RECV] Received settings message! kind=%s, payload=%s", kind, json.dumps(payload, indent=2))
            body = payload.get("body") or payload.get("item") or payload
            setting_id = body.get("id") or body.get("ruleId") or body.get("settingId")
            
            if did and setting_id:
                dev = self._store.setdefault(did, {})
                settings = dev.setdefault("settings", [])
                
                # Find and update the setting
                updated = False
                for s in settings:
                    if s.get("id") == setting_id:
                        # Update current value
                        if "current" in body:
                            s["current"] = body["current"]
                            updated = True
                        elif "enabled" in body:
                            s["current"] = body["enabled"]
                            updated = True
                        elif "value" in body:
                            s["current"] = body["value"]
                            updated = True
                        elif "ruleEnabled" in body:
                            s["current"] = body["ruleEnabled"]
                            updated = True
                        break
                
                if updated:
                    _LOGGER.info("[SETTING_UPDATE] %s: setting %s = %s", did[:8], setting_id[:8], body.get("current", body.get("enabled", body.get("value", body.get("ruleEnabled")))))
                    async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATED.format(device_id=did))
                else:
                    _LOGGER.debug("[SETTING_UPDATE] %s: setting %s not found in store", did[:8], setting_id)
                return

        # Handle service update
        changed = False
        svc_states: Dict[str, Dict[str, Any]] = {}
        index: Dict[tuple, str] = {}

        # When multiple services come at once
        if "services" in payload:
            for item in _iter_service_items(payload.get("services")):
                tup = _extract_service_tuple(item)
                if not tup:
                    continue
                sid, stype, dom, state = tup
                
                # Preserve metadata in state (used when sending commands)
                state["serviceType"] = stype
                state["domainType"] = dom
                if "serviceDeviceType" in item:
                    state["serviceDeviceType"] = item["serviceDeviceType"]
                
                svc_states[sid] = state
                if stype and dom:
                    index[(stype, dom)] = sid
                changed = True

        # Single service update
        if not changed and ("serviceId" in payload or kind == "publish#service-state"):
            item = payload.get("item") or payload
            tup = _extract_service_tuple(item)
            if tup:
                sid, stype, dom, state = tup
                
                # Preserve metadata in state
                state["serviceType"] = stype
                state["domainType"] = dom
                if "serviceDeviceType" in item:
                    state["serviceDeviceType"] = item["serviceDeviceType"]
                
                svc_states[sid] = state
                if stype and dom:
                    index[(stype, dom)] = sid
                changed = True
                if not did:
                    did = item.get("deviceId")

        # Update store and send signal
        if changed and did:
            dev = self._store.setdefault(did, {})
            snap = dev.setdefault("snapshot", {"raw": {}, "services": {}, "index": {}})
            
            # Save raw data (preserve metadata)
            snap["raw"] = payload
            
            # Normalize state
            for sid, st in list(svc_states.items()):
                if not isinstance(st, dict):
                    continue
                
                # Convert enabled → on
                if "enabled" in st:
                    st["on"] = bool(st["enabled"])
                
                # Infer on state from mode value
                if "mode" in st:
                    m = str(st["mode"]).lower()
                    st["on"] = st.get("on", m.endswith(".on") or m in ("on", "enabled", "1", "true"))

            # Update existing service state (merge)
            cur_services = snap.setdefault("services", {})
            for sid, st in svc_states.items():
                base = dict(cur_services.get(sid) or {})
                base.update(st)
                cur_services[sid] = base
            
            # Update index
            cur_index = snap.setdefault("index", {})
            cur_index.update(index)
            
            _LOGGER.debug("[SERVICE_UPDATE] %s: %d services updated", did[:8], len(svc_states))
            # Log trigger service disabled state changes for Remote Start debugging
            for sid, st in svc_states.items():
                if st.get("serviceType") == "cloud.smarthq.service.trigger":
                    _LOGGER.debug(
                        "[TRIGGER_STATE] %s domain=%s disabled=%s",
                        did[:8],
                        st.get("domainType", "").split(".")[-1],
                        st.get("disabled"),
                    )
            async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATED.format(device_id=did))
            return

        # Log other messages
        if kind and did:
            _LOGGER.debug("[WS_MESSAGE] %s kind=%s", did[:8], kind)