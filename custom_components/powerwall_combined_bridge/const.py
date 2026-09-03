from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "powerwall_combined_bridge"
NAME: Final = "Powerwall Combined Bridge"

CONF_RESOURCE: Final = "resource"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_RESOURCE: Final = "http://homeassistant.local:8676/status"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=15)
MIN_SCAN_INTERVAL_SECONDS: Final = 5
MAX_SCAN_INTERVAL_SECONDS: Final = 300

PLATFORMS: Final = ("sensor",)
