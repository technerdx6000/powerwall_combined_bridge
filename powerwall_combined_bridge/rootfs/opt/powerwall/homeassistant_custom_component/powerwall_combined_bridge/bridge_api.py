from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import ClientError, ClientSession


class PowerwallCombinedBridgeApiError(Exception):
    """Raised when the bridge API cannot be read."""


class PowerwallCombinedBridgeApiClient:
    """Small client for the bridge JSON endpoint."""

    def __init__(self, session: ClientSession, resource: str) -> None:
        self._session = session
        self.resource = resource

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
