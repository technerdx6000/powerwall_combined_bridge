from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


SECONDS_PER_HOUR = 3600.0

TOTAL_SOLAR_ENERGY_KEY = "solar_energy_kwh"
TOTAL_BATTERY_CHARGE_ENERGY_KEY = "battery_charge_energy_kwh"
TOTAL_BATTERY_DISCHARGE_ENERGY_KEY = "battery_discharge_energy_kwh"


def _snapshot_timestamp(snapshot: dict[str, Any]) -> datetime | None:
    generated_at = snapshot.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        return None

    normalized = generated_at.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).astimezone(UTC)
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _site_power(snapshot: dict[str, Any], site_key: str, channel: str) -> float | None:
    site = ((snapshot.get("sites") or {}) if isinstance(snapshot, dict) else {}).get(site_key) or {}
    current_power = site.get("current_power_w") if isinstance(site, dict) else None
    if not isinstance(current_power, dict):
        return None
    return _number(current_power.get(channel))


def _total_power(snapshot: dict[str, Any], key: str) -> float | None:
    totals = snapshot.get("totals") if isinstance(snapshot, dict) else None
    if not isinstance(totals, dict):
        return None
    return _number(totals.get(key))


def _positive_power(power_w: float | None) -> float | None:
    if power_w is None:
        return None
    return max(power_w, 0.0)


def _charging_power(power_w: float | None) -> float | None:
    if power_w is None:
        return None
    return max(-power_w, 0.0)


def _integrate_kwh(previous_power_w: float | None, current_power_w: float | None, delta_hours: float) -> float:
    if previous_power_w is None or current_power_w is None or delta_hours <= 0:
        return 0.0
    average_power_w = (previous_power_w + current_power_w) / 2.0
    return average_power_w * delta_hours / 1000.0


def empty_derived_energy() -> dict[str, Any]:
    return {
        "totals": {
            TOTAL_SOLAR_ENERGY_KEY: 0.0,
            TOTAL_BATTERY_CHARGE_ENERGY_KEY: 0.0,
            TOTAL_BATTERY_DISCHARGE_ENERGY_KEY: 0.0,
        },
        "sites": {},
    }


class DerivedEnergyTracker:
    """Integrate instantaneous power readings into cumulative energy counters."""

    def __init__(self) -> None:
        self._derived_energy = empty_derived_energy()
        self._previous_snapshot: dict[str, Any] | None = None
        self._previous_timestamp: datetime | None = None

    def _ensure_site(self, site_key: str) -> None:
        self._derived_energy["sites"].setdefault(
            site_key,
            {
                TOTAL_SOLAR_ENERGY_KEY: 0.0,
                TOTAL_BATTERY_CHARGE_ENERGY_KEY: 0.0,
                TOTAL_BATTERY_DISCHARGE_ENERGY_KEY: 0.0,
            },
        )

    def _integrate_site_channel(
        self,
        site_key: str,
        energy_key: str,
        previous_power_w: float | None,
        current_power_w: float | None,
        delta_hours: float,
    ) -> None:
        self._ensure_site(site_key)
        self._derived_energy["sites"][site_key][energy_key] += _integrate_kwh(
            previous_power_w,
            current_power_w,
            delta_hours,
        )

    def _integrate_interval(self, snapshot: dict[str, Any], delta_hours: float) -> None:
        if self._previous_snapshot is None:
            return

        self._derived_energy["totals"][TOTAL_SOLAR_ENERGY_KEY] += _integrate_kwh(
            _positive_power(_total_power(self._previous_snapshot, "solar_w")),
            _positive_power(_total_power(snapshot, "solar_w")),
            delta_hours,
        )
        self._derived_energy["totals"][TOTAL_BATTERY_CHARGE_ENERGY_KEY] += _integrate_kwh(
            _charging_power(_total_power(self._previous_snapshot, "battery_w")),
            _charging_power(_total_power(snapshot, "battery_w")),
            delta_hours,
        )
        self._derived_energy["totals"][TOTAL_BATTERY_DISCHARGE_ENERGY_KEY] += _integrate_kwh(
            _positive_power(_total_power(self._previous_snapshot, "battery_w")),
            _positive_power(_total_power(snapshot, "battery_w")),
            delta_hours,
        )

        for site_key in set((self._previous_snapshot.get("sites") or {}).keys()) | set((snapshot.get("sites") or {}).keys()):
            self._integrate_site_channel(
                site_key,
                TOTAL_SOLAR_ENERGY_KEY,
                _positive_power(_site_power(self._previous_snapshot, site_key, "SOLAR")),
                _positive_power(_site_power(snapshot, site_key, "SOLAR")),
                delta_hours,
            )
            self._integrate_site_channel(
                site_key,
                TOTAL_BATTERY_CHARGE_ENERGY_KEY,
                _charging_power(_site_power(self._previous_snapshot, site_key, "BATTERY")),
                _charging_power(_site_power(snapshot, site_key, "BATTERY")),
                delta_hours,
            )
            self._integrate_site_channel(
                site_key,
                TOTAL_BATTERY_DISCHARGE_ENERGY_KEY,
                _positive_power(_site_power(self._previous_snapshot, site_key, "BATTERY")),
                _positive_power(_site_power(snapshot, site_key, "BATTERY")),
                delta_hours,
            )

    def apply_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        timestamp = _snapshot_timestamp(snapshot)
        if timestamp is None:
            timestamp = self._previous_timestamp

        if self._previous_snapshot is not None and timestamp is not None and self._previous_timestamp is not None:
            delta_seconds = (timestamp - self._previous_timestamp).total_seconds()
            if delta_seconds > 0:
                self._integrate_interval(snapshot, delta_seconds / SECONDS_PER_HOUR)

        for site_key in (snapshot.get("sites") or {}).keys():
            self._ensure_site(site_key)

        self._previous_snapshot = snapshot
        self._previous_timestamp = timestamp
        return {
            **snapshot,
            "derived_energy": {
                "totals": dict(self._derived_energy["totals"]),
                "sites": {
                    site_key: dict(values)
                    for site_key, values in self._derived_energy["sites"].items()
                },
            },
        }