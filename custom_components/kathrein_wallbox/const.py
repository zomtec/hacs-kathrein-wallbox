"""Constants for the Kathrein Wallbox integration."""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from homeassistant.const import Platform

DOMAIN = "kathrein_wallbox"
DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 0
MIN_PORT = 1
MAX_PORT = 65535
MIN_UNIT_ID = 0
MAX_UNIT_ID = 255
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=15)
MIN_SCAN_INTERVAL_SECONDS = 5
MAX_SCAN_INTERVAL_SECONDS = 300
EXPECTED_MAPPING_VERSION = 0x0002

PLATFORMS = (Platform.SENSOR, Platform.BINARY_SENSOR)

CONF_HOST = "host"
CONF_PORT = "port"
CONF_UNIT_ID = "unit_id"


def get_scan_interval(source: Any) -> timedelta:
    """Resolve the polling interval from config entry data/options or the default."""
    value: Any = DEFAULT_SCAN_INTERVAL.total_seconds()

    if hasattr(source, "options") and hasattr(source, "data"):
        options = getattr(source, "options", {})
        data = getattr(source, "data", {})
        if isinstance(options, Mapping) and CONF_SCAN_INTERVAL in options:
            value = options[CONF_SCAN_INTERVAL]
        elif isinstance(data, Mapping) and CONF_SCAN_INTERVAL in data:
            value = data[CONF_SCAN_INTERVAL]
    elif isinstance(source, Mapping):
        options = source.get("options", {})
        data = source.get("data", {})
        if isinstance(options, Mapping) and CONF_SCAN_INTERVAL in options:
            value = options[CONF_SCAN_INTERVAL]
        elif isinstance(data, Mapping) and CONF_SCAN_INTERVAL in data:
            value = data[CONF_SCAN_INTERVAL]

    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = int(DEFAULT_SCAN_INTERVAL.total_seconds())

    seconds = max(MIN_SCAN_INTERVAL_SECONDS, min(seconds, MAX_SCAN_INTERVAL_SECONDS))
    return timedelta(seconds=seconds)
