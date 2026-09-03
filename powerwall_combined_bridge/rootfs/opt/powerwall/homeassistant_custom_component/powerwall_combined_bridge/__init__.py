from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .bridge_api import PowerwallCombinedBridgeApiClient, PowerwallCombinedBridgeApiError
from .const import CONF_RESOURCE, DOMAIN
from .coordinator import PowerwallCombinedBridgeCoordinator


@dataclass
class PowerwallCombinedBridgeRuntimeData:
    """Runtime data for the integration."""

    api: PowerwallCombinedBridgeApiClient
    coordinator: PowerwallCombinedBridgeCoordinator


type PowerwallCombinedBridgeConfigEntry = ConfigEntry[PowerwallCombinedBridgeRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PowerwallCombinedBridgeConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    session = async_get_clientsession(hass)
    resource = entry.options.get(CONF_RESOURCE, entry.data[CONF_RESOURCE])
    api = PowerwallCombinedBridgeApiClient(session, resource)
    coordinator = PowerwallCombinedBridgeCoordinator(hass, entry, api)

    try:
        await coordinator.async_config_entry_first_refresh()
    except PowerwallCombinedBridgeApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = PowerwallCombinedBridgeRuntimeData(api=api, coordinator=coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PowerwallCombinedBridgeConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])


async def _async_update_listener(hass: HomeAssistant, entry: PowerwallCombinedBridgeConfigEntry) -> None:
    """Reload when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
