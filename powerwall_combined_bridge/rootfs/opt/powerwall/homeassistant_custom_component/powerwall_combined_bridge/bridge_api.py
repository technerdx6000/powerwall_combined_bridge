from __future__ import annotations

import asyncio
from urllib.parse import urlsplit, urlunsplit
from typing import Any

from aiohttp import ClientError, ClientSession


class PowerwallCombinedBridgeApiError(Exception):
    """Raised when the bridge API cannot be read."""


class PowerwallCombinedBridgeApiClient:
    """Small client for the bridge JSON endpoint."""

    def __init__(self, session: ClientSession, resource: str) -> None:
        self._session = session
        self.resource = resource

    def _control_url(self) -> str:
        parts = urlsplit(self.resource)
        path = parts.path or ""
        if path.endswith("/status"):
            control_path = f"{path[:-7]}/control"
        elif path.endswith("/status/"):
            control_path = f"{path[:-8]}/control"
        elif path.endswith("/"):
            control_path = f"{path}control"
        else:
            control_path = f"{path}/control"
        return urlunsplit((parts.scheme, parts.netloc, control_path, "", ""))

    async def async_get_snapshot(self) -> dict[str, Any]:
        """Fetch a single JSON snapshot from the bridge endpoint."""
        try:
            async with asyncio.timeout(10):
                async with self._session.get(self.resource) as response:
                    response.raise_for_status()
                    payload = await response.json()
        except TimeoutError as err:
            raise PowerwallCombinedBridgeApiError("Timed out connecting to bridge") from err
        except ClientError as err:
            raise PowerwallCombinedBridgeApiError(f"HTTP error communicating with bridge: {err}") from err
        except ValueError as err:
            raise PowerwallCombinedBridgeApiError(f"Bridge returned invalid JSON: {err}") from err

        if not isinstance(payload, dict):
            raise PowerwallCombinedBridgeApiError("Bridge returned a non-object JSON payload")

        if not isinstance(payload.get("sites"), dict):
            raise PowerwallCombinedBridgeApiError("Bridge payload did not include a valid 'sites' object")

        return payload

    async def async_post_control(self, action: str, site: str | None = None, **kwargs: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": action}
        if site is not None:
            payload["site"] = site
        payload.update(kwargs)

        try:
            async with asyncio.timeout(20):
                async with self._session.post(self._control_url(), json=payload) as response:
                    response.raise_for_status()
                    body = await response.json()
        except TimeoutError as err:
            raise PowerwallCombinedBridgeApiError("Timed out posting control command to bridge") from err
        except ClientError as err:
            raise PowerwallCombinedBridgeApiError(f"HTTP error posting control command: {err}") from err
        except ValueError as err:
            raise PowerwallCombinedBridgeApiError(f"Bridge returned invalid control JSON: {err}") from err

        if not isinstance(body, dict):
            raise PowerwallCombinedBridgeApiError("Bridge returned a non-object control response")
        return body

    async def async_set_mode(self, mode: str, site: str | None = None) -> dict[str, Any]:
        return await self.async_post_control("set_mode", site=site, mode=mode)

    async def async_set_operation(
        self,
        site: str | None = None,
        mode: str | None = None,
        reserve_percent: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if mode is not None:
            payload["mode"] = mode
        if reserve_percent is not None:
            payload["reserve_percent"] = reserve_percent
        return await self.async_post_control("set_operation", site=site, **payload)

    async def async_set_reserve(self, reserve_percent: float, site: str | None = None) -> dict[str, Any]:
        return await self.async_post_control("set_reserve", site=site, reserve_percent=reserve_percent)

    async def async_dispatch_power(self, power_watts: float, duration_seconds: int, site: str | None = None) -> dict[str, Any]:
        return await self.async_post_control(
            "dispatch_power",
            site=site,
            power_watts=power_watts,
            duration_seconds=duration_seconds,
        )

    async def async_resume_operation(self, site: str | None = None) -> dict[str, Any]:
        return await self.async_post_control("resume_operation", site=site)
