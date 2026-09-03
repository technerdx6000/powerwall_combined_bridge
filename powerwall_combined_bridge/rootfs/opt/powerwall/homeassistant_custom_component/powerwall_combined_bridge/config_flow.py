from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .bridge_api import PowerwallCombinedBridgeApiClient, PowerwallCombinedBridgeApiError
from .const import (
    CONF_RESOURCE,
    CONF_SCAN_INTERVAL,
    DEFAULT_RESOURCE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
)
from .coordinator import build_entry_title, entry_unique_key


def config_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_RESOURCE, default=defaults.get(CONF_RESOURCE, DEFAULT_RESOURCE)): str,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())),
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL_SECONDS, max=MAX_SCAN_INTERVAL_SECONDS)),
        }
    )


async def validate_input(hass, user_input: dict[str, Any]) -> dict[str, Any]:
    session = async_get_clientsession(hass)
    api = PowerwallCombinedBridgeApiClient(session, user_input[CONF_RESOURCE])
    snapshot = await api.async_get_snapshot()
    return {
        "title": build_entry_title(snapshot),
        "unique_key": entry_unique_key(snapshot),
    }


class PowerwallCombinedBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Powerwall Combined Bridge integration."""

    VERSION = 1

    async def async_step_hassio(self, discovery_info: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle discovery from the Supervisor add-on."""
        return await self.async_step_user()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except PowerwallCombinedBridgeApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["unique_key"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(step_id="user", data_schema=config_schema(), errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except PowerwallCombinedBridgeApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["unique_key"])
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data_updates=user_input)

        defaults = {**entry.data, **entry.options}
        return self.async_show_form(step_id="reconfigure", data_schema=config_schema(defaults), errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return PowerwallCombinedBridgeOptionsFlow(config_entry)


class PowerwallCombinedBridgeOptionsFlow(config_entries.OptionsFlow):
    """Handle the integration options flow."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_input(self.hass, {**self.config_entry.data, **user_input})
            except PowerwallCombinedBridgeApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title="", data=user_input)

        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=config_schema(defaults), errors=errors)
