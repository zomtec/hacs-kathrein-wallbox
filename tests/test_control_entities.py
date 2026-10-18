"""Tests for disabling control entities while control is not allowed."""

from datetime import timedelta

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.kathrein_wallbox.const import CONF_ALLOW_CONTROL

CONTROL_ENTITIES = (
    ("number", "ems_charging_current"),
    ("select", "ems_relay_matrix"),
)


@pytest.fixture
def allow_control() -> bool:
    """Start without control by Home Assistant."""
    return False


async def _async_set_allow_control(hass, entry, allowed: bool) -> None:
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ALLOW_CONTROL: allowed}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


def _disabled_by(hass, entity_id_of) -> dict[str, er.RegistryEntryDisabler | None]:
    registry = er.async_get(hass)
    return {
        key: registry.async_get(entity_id_of(platform, key)).disabled_by
        for platform, key in CONTROL_ENTITIES
    }


async def test_controls_are_created_disabled_without_control_allowed(
    hass, setup_integration, entity_id_of
) -> None:
    """Create control entities disabled while control is not allowed."""
    await setup_integration()

    assert set(_disabled_by(hass, entity_id_of).values()) == {
        er.RegistryEntryDisabler.INTEGRATION
    }
    sensor_id = entity_id_of("sensor", "charging_state")
    assert er.async_get(hass).async_get(sensor_id).disabled_by is None


async def test_controls_follow_allow_control_option(
    hass, entry, setup_integration, entity_id_of
) -> None:
    """Disable controls when control is withdrawn and enable them when allowed."""
    await setup_integration()

    await _async_set_allow_control(hass, entry, True)
    assert set(_disabled_by(hass, entity_id_of).values()) == {None}
    assert hass.states.get(entity_id_of("number", "ems_charging_current"))

    await _async_set_allow_control(hass, entry, False)
    assert set(_disabled_by(hass, entity_id_of).values()) == {
        er.RegistryEntryDisabler.INTEGRATION
    }


@pytest.mark.parametrize("allow_control", [True])
async def test_user_disabled_controls_stay_disabled(
    hass, entry, setup_integration, entity_id_of
) -> None:
    """Keep controls the user disabled, whatever the control option says."""
    await setup_integration()
    er.async_get(hass).async_update_entity(
        entity_id_of("number", "ems_charging_current"),
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    await _async_set_allow_control(hass, entry, False)
    await _async_set_allow_control(hass, entry, True)

    assert _disabled_by(hass, entity_id_of) == {
        "ems_charging_current": er.RegistryEntryDisabler.USER,
        "ems_relay_matrix": None,
    }


@pytest.mark.parametrize("allow_control", [True])
async def test_keep_alive_runs_with_disabled_timeout_sensor(
    hass, mock_modbus_unit, setup_integration, entity_id_of
) -> None:
    """Read the EMS timeout from the coordinator, not from its disabled sensor."""
    mock_modbus_unit.holding[0x00A0] = 0x8000
    mock_modbus_unit.holding[0x00A2] = 13000
    mock_modbus_unit.holding[0x00A3] = 60
    await setup_integration()
    sensor_id = entity_id_of("sensor", "timeout_period")
    assert er.async_get(hass).async_get(sensor_id).disabled_by is (
        er.RegistryEntryDisabler.INTEGRATION
    )

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()

    assert [
        values for address, values in mock_modbus_unit.writes if address == 0x00A2
    ] == [[13000]]
