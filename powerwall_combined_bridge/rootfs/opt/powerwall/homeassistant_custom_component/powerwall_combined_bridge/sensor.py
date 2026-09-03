from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import PowerwallCombinedBridgeConfigEntry
from .const import DOMAIN


def _totals_value(data: dict[str, Any], key: str) -> Any:
    return ((data.get("totals") or {}) if isinstance(data, dict) else {}).get(key)


def _site_value(data: dict[str, Any], site_key: str, path: tuple[str, ...]) -> Any:
    site = ((data.get("sites") or {}) if isinstance(data, dict) else {}).get(site_key) or {}
    current: Any = site
    for item in path:
        if not isinstance(current, dict):
            return None
        current = current.get(item)
    return current


def _shelly_value(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data.get("shelly") or {}
    for item in path:
        if not isinstance(current, dict):
            return None
        current = current.get(item)
    return current


@dataclass(frozen=True, kw_only=True)
class BridgeSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]


TOTAL_SENSOR_DESCRIPTIONS: tuple[BridgeSensorDescription, ...] = (
    BridgeSensorDescription(
        key="bridge_error_count",
        translation_key="bridge_error_count",
        name="Bridge Error Count",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.get("errors") or {}) if isinstance(data, dict) else 0,
    ),
    BridgeSensorDescription(
        key="combined_solar_power",
        translation_key="combined_solar_power",
        name="Combined Solar Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _totals_value(data, "solar_w"),
    ),
    BridgeSensorDescription(
        key="combined_home_load",
        translation_key="combined_home_load",
        name="Combined Home Load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _totals_value(data, "home_w"),
    ),
    BridgeSensorDescription(
        key="combined_battery_power",
        translation_key="combined_battery_power",
        name="Combined Battery Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _totals_value(data, "battery_w"),
    ),
    BridgeSensorDescription(
        key="combined_grid_power",
        translation_key="combined_grid_power",
        name="Combined Grid Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _totals_value(data, "grid_w"),
    ),
    BridgeSensorDescription(
        key="combined_powerwall_site_sum",
        translation_key="combined_powerwall_site_sum",
        name="Combined Powerwall Site Sum",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _totals_value(data, "powerwall_site_sum_w"),
    ),
    BridgeSensorDescription(
        key="combined_balance_power",
        translation_key="combined_balance_power",
        name="Combined Balance Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _totals_value(data, "balance_w"),
    ),
    BridgeSensorDescription(
        key="combined_grid_source",
        translation_key="combined_grid_source",
        name="Combined Grid Source",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _totals_value(data, "grid_source"),
    ),
    BridgeSensorDescription(
        key="snapshot_generated_at",
        translation_key="snapshot_generated_at",
        name="Snapshot Generated At",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: dt_util.parse_datetime(data.get("generated_at")) if isinstance(data, dict) else None,
    ),
)


SITE_SENSOR_DEFINITIONS: tuple[BridgeSensorDescription, ...] = (
    BridgeSensorDescription(
        key="bridge_error",
        translation_key="bridge_error",
        name="Bridge Error",
        icon="mdi:alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: None,
    ),
    BridgeSensorDescription(
        key="battery_level_percent",
        translation_key="battery_level_percent",
        name="Battery Level",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        value_fn=lambda data: None,
    ),
    BridgeSensorDescription(
        key="solar_power",
        translation_key="solar_power",
        name="Solar Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: None,
    ),
    BridgeSensorDescription(
        key="home_load",
        translation_key="home_load",
        name="Home Load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: None,
    ),
    BridgeSensorDescription(
        key="battery_power",
        translation_key="battery_power",
        name="Battery Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: None,
    ),
    BridgeSensorDescription(
        key="site_power",
        translation_key="site_power",
        name="Site Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: None,
    ),
    BridgeSensorDescription(
        key="grid_status",
        translation_key="grid_status",
        name="Grid Status",
        icon="mdi:transmission-tower",
        value_fn=lambda data: None,
    ),
)


SHELLY_SENSOR_DEFINITIONS: tuple[BridgeSensorDescription, ...] = (
    BridgeSensorDescription(
        key="phase_a_power",
        translation_key="phase_a_power",
        name="Phase A Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: None,
    ),
    BridgeSensorDescription(
        key="phase_b_power",
        translation_key="phase_b_power",
        name="Phase B Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: None,
    ),
    BridgeSensorDescription(
        key="phase_c_power",
        translation_key="phase_c_power",
        name="Phase C Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerwallCombinedBridgeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data

    entities: list[SensorEntity] = [
        BridgeSensorEntity(entry, description) for description in TOTAL_SENSOR_DESCRIPTIONS
    ]

    for site_key, site in sorted((data.get("sites") or {}).items()):
        if not isinstance(site, dict):
            continue
        for description in SITE_SENSOR_DEFINITIONS:
            entities.append(SiteSensorEntity(entry, site_key, description))

    if isinstance(data.get("shelly"), dict):
        for description in SHELLY_SENSOR_DEFINITIONS:
            entities.append(ShellySensorEntity(entry, description))

    async_add_entities(entities)


class PowerwallCombinedBridgeEntity(CoordinatorEntity, SensorEntity):
    """Base entity for bridge-backed sensors."""

    def __init__(self, entry: PowerwallCombinedBridgeConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self._entry = entry
        self._attr_has_entity_name = True


class BridgeSensorEntity(PowerwallCombinedBridgeEntity):
    """A top-level combined bridge sensor."""

    entity_description: BridgeSensorDescription

    def __init__(self, entry: PowerwallCombinedBridgeConfigEntry, description: BridgeSensorDescription) -> None:
        super().__init__(entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Tesla / Shelly",
            model="Powerwall Combined Bridge",
            entry_type=None,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "snapshot_generated_at":
            return None
        errors = self.coordinator.data.get("errors")
        if not isinstance(errors, dict) or not errors:
            return None
        return {"errors": errors}


class SiteSensorEntity(PowerwallCombinedBridgeEntity):
    """A sensor representing one field for one Powerwall site."""

    entity_description: BridgeSensorDescription

    def __init__(self, entry: PowerwallCombinedBridgeConfigEntry, site_key: str, description: BridgeSensorDescription) -> None:
        super().__init__(entry)
        self.entity_description = description
        self._site_key = site_key
        self._attr_unique_id = f"{entry.entry_id}_{site_key}_{description.key}"

    @property
    def native_value(self) -> Any:
        if self.entity_description.key == "bridge_error":
            errors = self.coordinator.data.get("errors") or {}
            return errors.get(self._site_key)
        if self.entity_description.key == "battery_level_percent":
            return _site_value(self.coordinator.data, self._site_key, ("battery_level_percent",))
        if self.entity_description.key == "solar_power":
            return _site_value(self.coordinator.data, self._site_key, ("current_power_w", "SOLAR"))
        if self.entity_description.key == "home_load":
            return _site_value(self.coordinator.data, self._site_key, ("current_power_w", "LOAD"))
        if self.entity_description.key == "battery_power":
            return _site_value(self.coordinator.data, self._site_key, ("current_power_w", "BATTERY"))
        if self.entity_description.key == "site_power":
            return _site_value(self.coordinator.data, self._site_key, ("current_power_w", "SITE"))
        if self.entity_description.key == "grid_status":
            return _site_value(self.coordinator.data, self._site_key, ("grid_status",))
        return None

    @property
    def device_info(self) -> DeviceInfo:
        site = ((self.coordinator.data.get("sites") or {}).get(self._site_key) or {})
        din = site.get("din") or self._site_key
        return DeviceInfo(
            identifiers={(DOMAIN, f"site_{din}")},
            via_device=(DOMAIN, self._entry.entry_id),
            name=site.get("site_name") or self._site_key,
            manufacturer="Tesla",
            model=site.get("gateway_part_number") or "Powerwall",
            serial_number=site.get("gateway_serial_number") or din,
            suggested_area=self._site_key.replace("_", " ").title(),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        site = ((self.coordinator.data.get("sites") or {}).get(self._site_key) or {})
        errors = self.coordinator.data.get("errors") or {}
        attrs: dict[str, Any] = {}
        if site.get("host"):
            attrs["host"] = site["host"]
        if site.get("firmware_version"):
            attrs["firmware_version"] = site["firmware_version"]
        if site.get("din"):
            attrs["din"] = site["din"]
        if self._site_key in errors:
            attrs["bridge_error"] = errors[self._site_key]
        return attrs or None


class ShellySensorEntity(PowerwallCombinedBridgeEntity):
    """A sensor for the optional Shelly EM data."""

    entity_description: BridgeSensorDescription

    def __init__(self, entry: PowerwallCombinedBridgeConfigEntry, description: BridgeSensorDescription) -> None:
        super().__init__(entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_shelly_{description.key}"

    @property
    def available(self) -> bool:
        return super().available and isinstance(self.coordinator.data.get("shelly"), dict)

    @property
    def native_value(self) -> Any:
        if self.entity_description.key == "phase_a_power":
            return _shelly_value(self.coordinator.data, ("summary", "phase_a", "active_power_w"))
        if self.entity_description.key == "phase_b_power":
            return _shelly_value(self.coordinator.data, ("summary", "phase_b", "active_power_w"))
        if self.entity_description.key == "phase_c_power":
            return _shelly_value(self.coordinator.data, ("summary", "phase_c", "active_power_w"))
        return None

    @property
    def device_info(self) -> DeviceInfo:
        shelly = self.coordinator.data.get("shelly") or {}
        summary = shelly.get("summary") or {}
        device = shelly.get("device") or {}
        device_id = summary.get("device_id") or "shelly_em"
        return DeviceInfo(
            identifiers={(DOMAIN, f"shelly_{device_id}")},
            via_device=(DOMAIN, self._entry.entry_id),
            name="Shelly Grid Meter",
            manufacturer="Shelly",
            model=summary.get("model") or device.get("model") or "Shelly EM",
            sw_version=summary.get("firmware_version"),
            serial_number=summary.get("device_id"),
        )
