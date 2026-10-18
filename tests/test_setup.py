"""Tests for config-entry setup and unload."""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_SCAN_INTERVAL, STATE_UNAVAILABLE
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.kathrein_wallbox import CONFIG_SCHEMA

CHARGING_STATE_ADDRESS = 0x0060
# One entity of each platform.
PLATFORM_ENTITIES = (
    ("sensor", "charging_state"),
    ("binary_sensor", "ems_control"),
    ("number", "ems_charging_current"),
    ("select", "ems_relay_matrix"),
)


def test_config_schema_accepts_empty_config() -> None:
    """Declare the integration as config-entry-only to Hassfest."""
    assert CONFIG_SCHEMA({}) == {}


async def test_setup_entry_initializes_coordinator_before_platforms(
    hass, entry, mock_modbus_unit, setup_integration, state_of
) -> None:
    """Show the first refresh on every platform and keep the selected interval."""
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SCAN_INTERVAL: 20}
    )
    mock_modbus_unit.holding[CHARGING_STATE_ADDRESS] = 4

    await setup_integration()

    assert entry.state is ConfigEntryState.LOADED
    assert state_of("sensor", "charging_state") == "charging_active"
    for platform, key in PLATFORM_ENTITIES:
        assert state_of(platform, key) != STATE_UNAVAILABLE

    mock_modbus_unit.holding[CHARGING_STATE_ADDRESS] = 1
    start = dt_util.utcnow()
    async_fire_time_changed(hass, start + timedelta(seconds=15))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert state_of("sensor", "charging_state") == "charging_active"

    async_fire_time_changed(hass, start + timedelta(seconds=20))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert state_of("sensor", "charging_state") == "ev_connected"


async def test_unload_entry_unloads_all_platforms(
    hass, entry, setup_integration, state_of
) -> None:
    """Unload every platform together with the config entry."""
    await setup_integration()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    for platform, key in PLATFORM_ENTITIES:
        assert state_of(platform, key) == STATE_UNAVAILABLE
