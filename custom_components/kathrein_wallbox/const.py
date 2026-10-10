"""Constants for the Kathrein Wallbox integration."""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

DOMAIN = "kathrein_wallbox"
MANUFACTURER = "Kathrein"
DEVICE_NAME = "Kathrein Wallbox"
DEFAULT_PORT = 502
# The device ignores the unit ID; the manual recommends 0 (broadcast).
DEFAULT_UNIT_ID = 0
MIN_PORT = 1
MAX_PORT = 65535
MIN_UNIT_ID = 0
MAX_UNIT_ID = 255
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=15)
MIN_SCAN_INTERVAL_SECONDS = 5
MAX_SCAN_INTERVAL_SECONDS = 300
# Register mapping version this integration supports.
EXPECTED_MAPPING_VERSION = 0x0002

PLATFORMS = (Platform.SENSOR, Platform.BINARY_SENSOR)

CONF_UNIT_ID = "unit_id"


def get_scan_interval(entry: ConfigEntry) -> timedelta:
    """Resolve the polling interval from entry options, data, or the default."""
    seconds = int(
        entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds()),
        )
    )
    seconds = max(MIN_SCAN_INTERVAL_SECONDS, min(seconds, MAX_SCAN_INTERVAL_SECONDS))
    return timedelta(seconds=seconds)
