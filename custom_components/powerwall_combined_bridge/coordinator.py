from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .bridge_api import PowerwallCombinedBridgeApiClient, PowerwallCombinedBridgeApiError
from .const import CONF_SCAN_INTERVAL, DOMAIN, MIN_SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)


class PowerwallCombinedBridgeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for bridge data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: PowerwallCombinedBridgeApiClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=max(
                    int(entry.options.get(CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, 15))),
                    MIN_SCAN_INTERVAL_SECONDS,
                )
            ),
            always_update=True,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.api.async_get_snapshot()
        except PowerwallCombinedBridgeApiError as err:
            raise UpdateFailed(str(err)) from err


def build_entry_title(snapshot: dict[str, Any]) -> str:
    """Build a friendly config entry title from bridge data."""
    site_names = [
        site.get("site_name")
        for site in snapshot.get("sites", {}).values()
        if isinstance(site, dict) and site.get("site_name")
    ]
    if site_names:
        return f"Powerwall Combined Bridge: {' + '.join(site_names)}"
    return "Powerwall Combined Bridge"


def entry_unique_key(snapshot: dict[str, Any]) -> str:
    """Create a stable key for the configured bridge snapshot."""
    dins = sorted(
        site.get("din")
        for site in snapshot.get("sites", {}).values()
        if isinstance(site, dict) and site.get("din")
    )
    if not dins:
        raise ConfigEntryError("Bridge response did not include any Powerwall DIN values")
    return "|".join(dins)
