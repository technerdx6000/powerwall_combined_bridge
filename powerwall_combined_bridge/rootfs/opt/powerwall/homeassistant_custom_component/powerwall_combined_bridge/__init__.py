from __future__ import annotations

from dataclasses import dataclass

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv

from .bridge_api import PowerwallCombinedBridgeApiClient, PowerwallCombinedBridgeApiError
from .const import CONF_RESOURCE, DOMAIN
from .coordinator import PowerwallCombinedBridgeCoordinator

ATTR_ENTRY_ID = "entry_id"
ATTR_SITE = "site"
ATTR_MODE = "mode"
ATTR_RESERVE_PERCENT = "reserve_percent"
ATTR_POWER_WATTS = "power_watts"
ATTR_DURATION_SECONDS = "duration_seconds"

SERVICE_SET_MODE = "set_mode"
SERVICE_SET_OPERATION = "set_operation"
SERVICE_SET_RESERVE = "set_reserve"
SERVICE_DISPATCH_POWER = "dispatch_power"
SERVICE_RESUME_OPERATION = "resume_operation"


def _resolve_entry(hass: HomeAssistant, entry_id: str | None) -> PowerwallCombinedBridgeConfigEntry:
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED and getattr(entry, "runtime_data", None) is not None
    ]
    if entry_id is not None:
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry  # type: ignore[return-value]
        raise HomeAssistantError(f"No {DOMAIN} entry found for entry_id '{entry_id}'")

    if len(entries) == 1:
        return entries[0]  # type: ignore[return-value]
    if not entries:
        raise HomeAssistantError(f"No loaded {DOMAIN} config entries")
    raise HomeAssistantError(f"Multiple {DOMAIN} entries found; pass entry_id")


async def _refresh_after_control(entry: PowerwallCombinedBridgeConfigEntry) -> None:
    await entry.runtime_data.coordinator.async_request_refresh()


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_MODE):
        return

    async def handle_set_mode(call) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        await entry.runtime_data.api.async_set_mode(
            mode=call.data[ATTR_MODE],
            site=call.data.get(ATTR_SITE),
        )
        await _refresh_after_control(entry)

    async def handle_set_operation(call) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        mode = call.data.get(ATTR_MODE)
        reserve = call.data.get(ATTR_RESERVE_PERCENT)
        if mode is None and reserve is None:
            raise HomeAssistantError("set_operation requires mode and/or reserve_percent")
        await entry.runtime_data.api.async_set_operation(
            site=call.data.get(ATTR_SITE),
            mode=mode,
            reserve_percent=reserve,
        )
        await _refresh_after_control(entry)

    async def handle_set_reserve(call) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        await entry.runtime_data.api.async_set_reserve(
            reserve_percent=call.data[ATTR_RESERVE_PERCENT],
            site=call.data.get(ATTR_SITE),
        )
        await _refresh_after_control(entry)

    async def handle_dispatch_power(call) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        await entry.runtime_data.api.async_dispatch_power(
            power_watts=call.data[ATTR_POWER_WATTS],
            duration_seconds=call.data[ATTR_DURATION_SECONDS],
            site=call.data.get(ATTR_SITE),
        )
        await _refresh_after_control(entry)

    async def handle_resume_operation(call) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        await entry.runtime_data.api.async_resume_operation(
            site=call.data.get(ATTR_SITE),
        )
        await _refresh_after_control(entry)

    common_optional = {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional(ATTR_SITE): cv.string,
    }

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MODE,
        handle_set_mode,
        schema=vol.Schema(
            {
                **common_optional,
                vol.Required(ATTR_MODE): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_OPERATION,
        handle_set_operation,
        schema=vol.Schema(
            {
                **common_optional,
                vol.Optional(ATTR_MODE): cv.string,
                vol.Optional(ATTR_RESERVE_PERCENT): vol.Coerce(float),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_RESERVE,
        handle_set_reserve,
        schema=vol.Schema(
            {
                **common_optional,
                vol.Required(ATTR_RESERVE_PERCENT): vol.Coerce(float),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DISPATCH_POWER,
        handle_dispatch_power,
        schema=vol.Schema(
            {
                **common_optional,
                vol.Required(ATTR_POWER_WATTS): vol.Coerce(float),
                vol.Required(ATTR_DURATION_SECONDS): vol.All(vol.Coerce(int), vol.Range(min=1)),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESUME_OPERATION,
        handle_resume_operation,
        schema=vol.Schema(common_optional),
    )


def _remove_services(hass: HomeAssistant) -> None:
    if hass.config_entries.async_entries(DOMAIN):
        return
    for service in (
        SERVICE_SET_MODE,
        SERVICE_SET_OPERATION,
        SERVICE_SET_RESERVE,
        SERVICE_DISPATCH_POWER,
        SERVICE_RESUME_OPERATION,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


@dataclass
class PowerwallCombinedBridgeRuntimeData:
    """Runtime data for the integration."""

    api: PowerwallCombinedBridgeApiClient
    coordinator: PowerwallCombinedBridgeCoordinator


type PowerwallCombinedBridgeConfigEntry = ConfigEntry[PowerwallCombinedBridgeRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML."""
    _register_services(hass)
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
    _register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PowerwallCombinedBridgeConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])
    if unloaded:
        _remove_services(hass)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: PowerwallCombinedBridgeConfigEntry) -> None:
    """Reload when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
