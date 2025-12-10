from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DEVICES_URL,
    DEVICE_PRESENCE_URL,
    DEVICE_SETTINGS_URL,
    DEVICE_SETTING_DETAIL_URL,
    INSTANT_METRICS_URL,
    HISTORY_METRICS_URL,
    DEVICE_ITEM_URL,
)

_LOGGER = logging.getLogger(__name__)


class SmartHQError(Exception):
    """API error wrapper."""


def _is_2xx(status: int) -> bool:
    return 200 <= status < 300


async def _gather_limited(coros, limit: int = 4):
    """Gather with concurrency limit."""
    sem = asyncio.Semaphore(limit)

    async def _run(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*[_run(c) for c in coros])


class SmartHQApi:
    """Thin wrapper around SmartHQ Digital Twin (Client) API."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self._oauth: config_entry_oauth2_flow.OAuth2Session | None = None
        self._base_url = "https://client.mysmarthq.com"  # Add BASE URL

    async def async_get_websocket_endpoint(self) -> str:
        """Return a per-user WebSocket URL (contains access_token)."""
        url = "https://client.mysmarthq.com/v2/websocket"
        data = await self._request_json("GET", url)
        ep = (data or {}).get("endpoint")
        if not ep or not isinstance(ep, str):
            raise RuntimeError(f"Invalid websocket endpoint response: {data!r}")
        return ep

    # ---------- OAuth session ----------
    async def _oauth_session(self) -> config_entry_oauth2_flow.OAuth2Session:
        if self._oauth:
            return self._oauth
        impl = await config_entry_oauth2_flow.async_get_config_entry_implementation(
            self.hass, self.entry
        )
        self._oauth = config_entry_oauth2_flow.OAuth2Session(
            self.hass, self.entry, impl
        )
        return self._oauth

    # ---------- HTTP helper ----------
    async def _request_json(self, method: str, url: str, **kwargs) -> Any:
        session = async_get_clientsession(self.hass)
        oauth = await self._oauth_session()
        await oauth.async_ensure_token_valid()

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {oauth.token['access_token']}"
        headers.setdefault("Accept", "application/json")

        _LOGGER.debug("SmartHQ HTTP %s %s", method, url)
        resp = await session.request(method, url, headers=headers, **kwargs)
        text = await resp.text()
        _LOGGER.debug("SmartHQ HTTP %s -> %s body: %s", method, resp.status, text[:500])

        if not _is_2xx(resp.status):
            raise SmartHQError(f"{method} {url} -> {resp.status}: {text}")

        try:
            return json.loads(text)
        except Exception:
            return text

    # ---------- Command API (REST) ----------
    async def async_send_command(
        self,
        device_id: str,
        service_type: str,
        domain_type: str,
        service_device_type: str,
        command: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send a command via REST API POST /v2/command.
        
        Args:
            device_id: Device ID
            service_type: e.g., 'cloud.smarthq.service.toggle'
            domain_type: e.g., 'cloud.smarthq.domain.cooking'
            service_device_type: e.g., 'cloud.smarthq.device.smoker'
            command: Command dict with commandType and parameters
        
        Returns:
            Response dict from the server
        """
        url = f"{self._base_url}/v2/command"
        
        payload = {
            "kind": "service#command",
            "deviceId": device_id,
            "serviceType": service_type,
            "domainType": domain_type,
            "serviceDeviceType": service_device_type,
            "command": command,
        }
        
        _LOGGER.info(
            "[REST_CMD] POST /v2/command: device=%s, serviceType=%s, command=%s",
            device_id[:8],
            service_type,
            command.get("commandType", "unknown"),
        )
        _LOGGER.debug("[REST_CMD] Full payload: %s", json.dumps(payload, indent=2))
        
        try:
            result = await self._request_json("POST", url, json=payload)
            _LOGGER.info("[REST_CMD] ✓ Command successful: %s", result)
            return result
        except SmartHQError as e:
            _LOGGER.error("[REST_CMD] ✗ Command failed: %s", e)
            raise

    # ---------- List devices ----------
    async def async_list_devices(self) -> List[Dict[str, Any]]:
        data = await self._request_json("GET", DEVICES_URL)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "devices", "data", "result"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    # ---------- Presence ----------
    async def async_get_presence(self, device_id: str) -> Dict[str, Any]:
        url = DEVICE_PRESENCE_URL.format(device_id=device_id)
        data = await self._request_json("GET", url)
        return data if isinstance(data, dict) else {"raw": data}

    # ---------- Settings (summary) ----------
    async def async_get_settings(self, device_id: str) -> List[Dict[str, Any]]:
        url = DEVICE_SETTINGS_URL.format(device_id=device_id)
        try:
            data = await self._request_json("GET", url)
        except SmartHQError as e:
            if " 403:" in str(e) or "403" in str(e):
                _LOGGER.warning("Settings 403 for %s; skip", device_id)
                return []
            raise

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items") or data.get("settings") or data.get("data") or []
        return []
        
    async def async_get_setting_detail(self, device_id: str, rule_id: str) -> dict:
        """GET /v2/device/{deviceId}/setting/{ruleId} and return raw dict."""
        url = DEVICE_SETTING_DETAIL_URL.format(device_id=device_id, rule_id=rule_id)
        try:
            data = await self._request_json("GET", url)
        except SmartHQError as e:
            _LOGGER.warning("get_setting_detail failed for %s/%s: %s", device_id, rule_id, e)
            return {}
        return data if isinstance(data, dict) else {}

    # ---------- Calculated Instant ----------
    async def async_get_instant_metrics(
        self,
        device_id: str,
        *,
        services: List[dict] | None = None,
        metrics: List[str] | None = None,   # Not allowed in most tenants (kept for compatibility)
        timezone: str | None = None,
    ) -> dict:
        """
        POST /v2/device/instant/calculated
        - Schema is strict, try minimal body and few variations sequentially
        """
        def _ok(resp: Any) -> bool:
            if not isinstance(resp, dict):
                return False
            # Consider OK if any of data, items, result is filled as dict/list
            for k in ("data", "items", "result"):
                v = resp.get(k)
                if isinstance(v, (dict, list)) and v:
                    return True
            return False

        base: Dict[str, Any] = {"kind": "device#instanthistory"}
        if timezone:
            base["timezone"] = timezone

        # (1) Recommended: service-level request
        candidates: List[Dict[str, Any]] = [
            {**base, "data": [{"type": "service", "deviceId": device_id}]},
        ]

        # (2) Some environment variation (directly to device)
        candidates.extend([
            {**base, "data": [{"type": "device", "deviceId": device_id}]},
            {**base, "data": [{"type": "device", "id": device_id}]},
        ])

        # (3) metrics method usually gives 400 → try last (ignorable)
        if metrics is not None:
            candidates.append({**base, "data": [{"type": "service", "deviceId": device_id}], "metrics": metrics})

        last_err: Optional[Exception] = None
        for idx, body in enumerate(candidates, 1):
            try:
                resp = await self._request_json("POST", INSTANT_METRICS_URL, json=body)
                if _ok(resp):
                    _LOGGER.debug("instant variant#%d worked for %s", idx, device_id)
                    return resp
                _LOGGER.debug("instant variant#%d returned empty for %s", idx, device_id)
            except SmartHQError as e:
                last_err = e
                _LOGGER.debug("instant variant#%d failed for %s: %s", idx, device_id, e)
            except Exception as e:
                last_err = e
                _LOGGER.debug("instant variant#%d error for %s: %s", idx, device_id, e)

        if last_err:
            _LOGGER.warning("instant failed for %s: no variant returned data", device_id)
        return {}

    # ---------- Calculated History (optional) ----------
    async def async_get_history_metrics(
        self,
        device_id: str,
        start_iso: str,
        end_iso: str,
        bucket_seconds: int = 300,
        metrics: list[str] | None = None,
    ) -> dict:
        body = {
            "deviceId": device_id,
            "startTime": start_iso,
            "endTime": end_iso,
            "bucketSeconds": bucket_seconds,
        }
        if metrics is not None:
            body["metrics"] = metrics
        try:
            data = await self._request_json("POST", HISTORY_METRICS_URL, json=body)
        except SmartHQError as e:
            if "403" in str(e) or "404" in str(e):
                _LOGGER.debug("history metrics not available for %s: %s", device_id, e)
                return {}
            raise
        return data if isinstance(data, dict) else {}

    # ---------- Device state snapshot (workaround) ----------
    async def async_get_device_state_snapshot(self, device_id: str) -> Dict[str, Any]:
        """Try a handful of likely device-state endpoints and return first non-empty dict."""
        urls = [
            f"https://client.mysmarthq.com/v2/device/{device_id}/state",
            f"https://client.mysmarthq.com/v2/device/{device_id}",
            f"https://client.mysmarthq.com/v2/device/state?deviceId={device_id}",
        ]
        for url in urls:
            try:
                data = await self._request_json("GET", url)
            except SmartHQError as e:
                _LOGGER.debug("device state snapshot GET %s failed for %s: %s", url, device_id, e)
                continue

            if isinstance(data, dict) and data:
                return data
            if isinstance(data, dict):
                for k in ("data", "result", "item"):
                    v = data.get(k)
                    if isinstance(v, dict) and v:
                        return v
            if isinstance(data, list) and data and isinstance(data[0], dict):
                return data[0]

        return {}

    # ---------- Service states (query state per service if possible) ----------
    async def async_get_all_service_states(self, device_id: str) -> Dict[str, Any]:
        """
        Try available service list endpoints, then query /state for each service and combine.
        """
        # 1) Candidate service list endpoints
        list_urls = [
            f"https://client.mysmarthq.com/v2/device/{device_id}/service",
            f"https://client.mysmarthq.com/v2/device/{device_id}/services",
            f"https://client.mysmarthq.com/v2/service?deviceId={device_id}",
        ]
        services: List[Dict[str, Any]] = []
        for url in list_urls:
            try:
                raw = await self._request_json("GET", url)
            except SmartHQError as e:
                _LOGGER.debug("service list GET %s failed for %s: %s", url, device_id, e)
                continue

            # Standardize
            if isinstance(raw, list):
                services = [x for x in raw if isinstance(x, dict)]
            elif isinstance(raw, dict):
                for k in ("items", "services", "data", "result"):
                    v = raw.get(k)
                    if isinstance(v, list):
                        services = [x for x in v if isinstance(x, dict)]
                        break

            if services:
                break

        if not services:
            return {}

    # 2) Query state for each service
    async def _fetch_state(self, s: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        sid = str(s.get("id") or s.get("serviceId") or "")
        if not sid:
            return ("", {})
        # Candidate state endpoints
        state_urls = [
            f"https://client.mysmarthq.com/v2/service/{sid}/state",
            f"https://client.mysmarthq.com/v2/service/{sid}",
        ]
        for su in state_urls:
            try:
                st = await self._request_json("GET", su)
            except SmartHQError:
                continue
            if isinstance(st, dict) and st:
                return (sid, st)
            if isinstance(st, dict):
                for k in ("data", "result", "item"):
                    v = st.get(k)
                    if isinstance(v, dict) and v:
                        return (sid, v)
        return (sid, {})

        results = await _gather_limited([_fetch_state(s) for s in services], limit=4)
        return {sid: st for sid, st in results if sid}

    # ---------- Settings (detail + normalize) ----------
    async def get_device_settings(self, device_id: str) -> List[Dict[str, Any]]:
        summary = await self.async_get_settings(device_id)
        rule_ids: List[str] = []
        for it in summary:
            if isinstance(it, dict):
                rid = it.get("ruleId") or it.get("id") or it.get("ruleID")
                if rid:
                    rule_ids.append(str(rid))

        if not rule_ids:
            _LOGGER.debug("No rule ids for %s", device_id)
            return []

        coros = [
            self._request_json(
                "GET",
                DEVICE_SETTING_DETAIL_URL.format(device_id=device_id, rule_id=rid),
            )
            for rid in rule_ids
        ]
        try:
            details = await _gather_limited(coros, limit=4)
        except Exception as err:
            _LOGGER.warning("Detail fetch failed for %s: %s", device_id, err)
            return []

        normalized: List[Dict[str, Any]] = []
        for rid, d in zip(rule_ids, details):
            n = self._normalize_setting_detail(d)
            if not n or not n.get("type"):
                _LOGGER.debug("DETAIL RAW (missing type) %s: %s", rid, str(d)[:500])
            if n:
                normalized.append(n)
        return normalized

    @staticmethod
    def _normalize_setting_detail(d: Any) -> Optional[Dict[str, Any]]:
        # May receive a list
        if isinstance(d, list) and d and isinstance(d[0], dict):
            d = d[0]
        if not isinstance(d, dict):
            return None

        for k in ("data", "item", "result", "payload"):
            if isinstance(d.get(k), dict):
                d = d[k]
        for k in ("rule", "setting"):
            if isinstance(d.get(k), dict):
                d = d[k]

        rid = (
            d.get("ruleId") or d.get("id") or d.get("ruleID")
            or d.get("settingId") or d.get("settingID")
        )
        if not rid:
            return None

        typ = (
            d.get("type") or d.get("valueType") or d.get("dataType")
            or d.get("settingType")
        )

        current_candidates = [
            d.get("current"), d.get("value"), d.get("currentValue"),
            (d.get("state") or {}).get("value"),
            (d.get("status") or {}).get("value"),
            (d.get("selection") or {}).get("value"),
            (d.get("properties") or {}).get("current"),
            (d.get("properties") or {}).get("value"),
            d.get("ruleEnabled"), d.get("enabled"),
        ]
        value = next((v for v in current_candidates if v is not None), None)

        opts = (
            d.get("options") or d.get("values") or d.get("allowedValues")
            or d.get("enum") or d.get("choices") or d.get("possibleValues")
            or (d.get("selection") or {}).get("options")
        )
        min_v = (
            d.get("min") or d.get("minimum") or d.get("minValue")
            or (d.get("range") or {}).get("min")
            or (d.get("allowedRange") or {}).get("min")
        )
        max_v = (
            d.get("max") or d.get("maximum") or d.get("maxValue")
            or (d.get("range") or {}).get("max")
            or (d.get("allowedRange") or {}).get("max")
        )
        step_v = (
            d.get("step") or d.get("increment") or d.get("stepSize") or d.get("stepValue")
            or (d.get("range") or {}).get("step")
            or (d.get("allowedRange") or {}).get("step")
        )

        if (str(d.get("kind")).lower() == "device#setting"
            and value is None
            and not isinstance(opts, list)
            and min_v is None and max_v is None):
            return None

        if not typ:
            if ("ruleEnabled" in d) or ("enabled" in d) or isinstance(value, bool):
                typ = "BOOLEAN"
            elif isinstance(opts, list):
                typ = "ENUM"
            elif isinstance(value, (int, float)) or (min_v is not None or max_v is not None):
                typ = "RANGE" if (min_v is not None or max_v is not None) else "NUMBER"
            elif isinstance(value, str):
                typ = "STRING"

        if typ and str(typ).upper() in {"RANGE", "NUMBER"}:
            def _num(x):
                try:
                    return float(x) if x is not None else None
                except Exception:
                    return None
            min_v, max_v, step_v = _num(min_v), _num(max_v), _num(step_v)
            try:
                if value is not None and not isinstance(value, (int, float)):
                    value = float(value)
            except Exception:
                pass

        norm: Dict[str, Any] = {
            "id": str(rid),
            "type": (str(typ).upper() if typ else None),
            "current": value,
        }
        if isinstance(opts, list) and opts:
            norm["options"] = opts
        if min_v is not None:
            norm["min"] = min_v
        if max_v is not None:
            norm["max"] = max_v
        if step_v is not None:
            norm["step"] = step_v

        title = d.get("title") or d.get("name") or d.get("label")
        if title:
            norm["title"] = title
        desc = d.get("description")
        if desc:
            norm["description"] = desc

        return norm

    async def async_set_setting_boolean(
        self,
        device_id: str,
        rule_id: str,
        enabled: bool,
    ) -> dict:
        """
        Toggle BOOLEAN setting.
        SmartHQ expects: {"kind":"device#setting","ruleEnabled": <bool>}
        Try POST → PUT → PATCH in sequence due to method differences in some environments.
        """
        url = DEVICE_SETTING_DETAIL_URL.format(device_id=device_id, rule_id=rule_id)
        body = {"kind": "device#setting", "ruleEnabled": bool(enabled)}

        last_err: Exception | None = None
        for method in ("POST", "PUT", "PATCH"):
            try:
                resp = await self._request_json(method, url, json=body)
                # Success response usually setting detail (or empty body), so dict or empty dict
                return resp if isinstance(resp, dict) else {}
            except SmartHQError as e:
                # If 405/404 method issue, fallback to next method
                txt = str(e)
                if "405" in txt or "Method Not Allowed" in txt:
                    last_err = e
                    continue
                # 400(JSONSchema) may be body issue, but other methods may succeed, so continue
                if "400" in txt:
                    last_err = e
                    continue
                # Otherwise, abort immediately
                raise

        # All failed
        if last_err:
            _LOGGER.error("set_setting_boolean failed for %s/%s -> %s: %s",
                          device_id, rule_id, enabled, last_err)
        return {}

    async def async_set_setting(self, device_id: str, rule_id: str, enabled: bool) -> bool:
        """
        Toggle a boolean rule/setting. To absorb schema differences per tenant
        try various variations sequentially and consider first 2xx response as success.
        """
        _LOGGER.info("[API] Setting %s/%s to %s", device_id[:8], rule_id, enabled)
        
        def _body(variant: str) -> Dict[str, Any]:
            base = {"kind": "device#setting"}
            if variant == "current":
                base["current"] = enabled
            elif variant in ("ruleEnabled", "enabled", "value"):
                base[variant] = enabled
            elif variant == "payload_with_ruleId_ruleEnabled":
                base.update({"ruleId": rule_id, "ruleEnabled": enabled})
            elif variant == "payload_with_ruleId_enabled":
                base.update({"ruleId": rule_id, "enabled": enabled})
            elif variant == "payload_with_ruleId_value":
                base.update({"ruleId": rule_id, "value": enabled})
            return base

        attempts: list[tuple[str, str, str]] = [
            ("PUT",   "/v2/device/{did}/setting/{rid}", "current"),
            ("PATCH", "/v2/device/{did}/setting/{rid}", "current"),
            ("PUT",   "/v2/device/{did}/setting/{rid}", "ruleEnabled"),
            ("PATCH", "/v2/device/{did}/setting/{rid}", "ruleEnabled"),
            ("POST",  "/v2/device/{did}/setting/{rid}", "ruleEnabled"),
            ("PATCH", "/v2/device/{did}/setting/{rid}", "enabled"),
            ("PATCH", "/v2/device/{did}/setting/{rid}", "value"),
            ("POST",  "/v2/device/{did}/setting", "payload_with_ruleId_ruleEnabled"),
            ("POST",  "/v2/device/{did}/setting", "payload_with_ruleId_enabled"),
            ("POST",  "/v2/device/{did}/setting", "payload_with_ruleId_value"),
        ]

        last_err: Exception | None = None
        for method, url_fmt, variant in attempts:
            url = "https://client.mysmarthq.com" + url_fmt.format(did=device_id, rid=rule_id)
            body = _body(variant)
            _LOGGER.debug("[API] Trying %s %s with body: %s", method, url, body)
            try:
                resp = await self._request_json(method, url, json=body)
                _LOGGER.info(
                    "[API] ✓ Setting succeeded: %s %s (variant=%s) -> %s",
                    method, url_fmt, variant, str(resp)[:200],
                )
                return True
            except SmartHQError as e:
                last_err = e
                err_msg = str(e)
                # 405 is method issue so try next, 400 is schema issue so try next variant
                if "405" in err_msg or "Method Not Allowed" in err_msg:
                    _LOGGER.debug("[API] Method not allowed, trying next: %s", err_msg)
                elif "400" in err_msg:
                    _LOGGER.debug("[API] Bad request (schema issue), trying next variant: %s", err_msg)
                else:
                    # 403, 404, 500 may be fatal but try next variant
                    _LOGGER.warning("[API] Unexpected error: %s", err_msg)
            except Exception as e:
                last_err = e
                _LOGGER.debug("[API] Network/parse error: %s", e)

        if last_err:
            _LOGGER.error(
                "[API] ✗ All setting attempts failed for %s/%s=%s: %s",
                device_id, rule_id, enabled, last_err,
            )
        return False
    
    async def async_update_setting(self, device_id: str, setting_id: str, enabled: bool) -> bool:
        """Alias for async_set_setting - update a boolean setting."""
        return await self.async_set_setting(device_id, setting_id, enabled)
    
    async def async_get_device_item(self, device_id: str) -> dict:
        """
        GET /v2/device/{device_id}
        Get device meta + services[] + each service.state entirely.
        """
        url = f"{DEVICES_URL}/{device_id}"
        try:
            data = await self._request_json("GET", url)
        except SmartHQError as e:
            _LOGGER.warning("device item failed for %s: %s", device_id, e)
            return {}
        return data if isinstance(data, dict) else {}
        
    # Single device snapshot: contains services array and each service.state
    async def async_get_device_item(self, device_id: str) -> dict:
        url = f"{DEVICES_URL}/{device_id}"
        data = await self._request_json("GET", url)
        return data if isinstance(data, dict) else {}

    # When you want to see only individual state of specific service (optional)
    async def async_get_service_state(self, device_id: str, service_id: str) -> dict:
        url = f"{DEVICES_URL}/{device_id}/service/{service_id}"
        data = await self._request_json("GET", url)
        # Usually {"state": {...}, ...} format
        return data.get("state", data) if isinstance(data, dict) else {}

    # Helper to create serviceId -> state mapping from snapshot (for diagnostics)
    @staticmethod
    def extract_service_states_map(device_item: dict) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for svc in (device_item or {}).get("services", []) or []:
            sid = str(svc.get("serviceId") or "")
            if sid:
                out[sid] = svc.get("state") or {}
        return out
    def build_snapshot_index(item: dict) -> dict:
        """Convert services array to {serviceId: state}, {(type,domain): serviceId}."""
        services = item.get("services") or []
        svc_states: dict[str, dict] = {}
        index: dict[tuple[str, str], str] = {}
        for s in services:
            sid = str(s.get("serviceId") or "")
            stype = str(s.get("serviceType") or "")
            dtype = str(s.get("domainType") or "")
            state = s.get("state") or {}
            if sid:
                svc_states[sid] = state
            if stype and dtype and sid:
                index[(stype, dtype)] = sid
        return {"raw": item, "services": svc_states, "index": index}

    async def send_command(self, appliance_id: str, command: dict) -> bool:
        """Send a control command to an appliance."""
        try:
            url = f"{self.base_url}/v1/appliance/{appliance_id}/control"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            async with self.session.post(url, json=command, headers=headers) as response:
                if response.status == 200:
                    _LOGGER.debug(f"Command sent successfully to {appliance_id}: {command}")
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error(f"Failed to send command: {response.status} - {error_text}")
                    return False
        except Exception as e:
            _LOGGER.error(f"Error sending command: {e}")
            return False

    async def set_erd_value(self, appliance_id: str, erd_code: str, erd_value: any) -> bool:
        """Set an ERD (Electronic Refrigerator Data) value for an appliance."""
        command = {
            "kind": "appliance#applianceCommand",
            "code": erd_code,
            "value": erd_value
        }
        return await self.send_command(appliance_id, command)

    async def set_auto_warm(self, device_id: str, enabled: bool) -> bool:
        """Set auto warm mode."""
        try:
            if not self.ws or self.ws.closed:
                _LOGGER.warning("WebSocket not connected, reconnecting...")
                await self.connect_websocket()
            
            # Generate Auto Warm setting command
            command = {
                "kind": "publish#erd",
                "id": f"auto_warm_{device_id}_{enabled}",
                "request": {
                    "host": device_id,
                    "method": "UPDATE",
                    "path": "/erd/0x29",  # Auto Warm ERD code
                    "data": {
                        "erd_code": "0x29",
                        "erd_value": 1 if enabled else 0
                    }
                }
            }
            
            _LOGGER.debug(f"Sending auto warm command: {command}")
            await self.ws.send_json(command)
            
            # Wait for response (5 second timeout)
            response = await asyncio.wait_for(
                self._wait_for_response(command["id"]),
                timeout=5.0
            )
            
            if response and response.get("success"):
                _LOGGER.info(f"Auto warm set to {enabled} for device {device_id}")
                return True
            else:
                _LOGGER.error(f"Failed to set auto warm: {response}")
                return False
                
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout waiting for auto warm response")
            return False
        except Exception as e:
            _LOGGER.error(f"Error setting auto warm: {e}")
            return False

    async def _wait_for_response(self, request_id: str):
        """Wait for a specific response."""
        # Wait for response logic (no modification needed if already implemented)
        for _ in range(50):  # Check every 0.1s for 5 seconds
            if hasattr(self, '_responses') and request_id in self._responses:
                return self._responses.pop(request_id)
            await asyncio.sleep(0.1)
        return None
