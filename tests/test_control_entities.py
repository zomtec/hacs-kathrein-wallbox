"""Tests for creating control entities only while control is allowed."""

from datetime import timedelta

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.kathrein_wallbox.const import CONF_ALLOW_CONTROL, DOMAIN

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


def _registry_entries(hass, serial) -> dict[str, er.RegistryEntry | None]:
    registry = er.async_get(hass)
    return {
        key: registry.async_get(
            registry.async_get_entity_id(platform, DOMAIN, f"{serial}_{key}") or ""
        )
        for platform, key in CONTROL_ENTITIES
    }


async def test_controls_are_not_created_without_control_allowed(
    hass, serial, setup_integration, entity_id_of
) -> None:
    """Create no control entities while control is not allowed."""
    await setup_integration()

    assert _registry_entries(hass, serial) == dict.fromkeys(
        ("ems_charging_current", "ems_relay_matrix")
    )
    assert hass.states.get(entity_id_of("sensor", "charging_state"))


async def test_controls_follow_allow_control_option(
    hass, entry, serial, setup_integration, entity_id_of
) -> None:
    """Create controls when control is allowed and remove them when withdrawn."""
    await setup_integration()

    await _async_set_allow_control(hass, entry, True)
    entries = _registry_entries(hass, serial)
    assert all(
        registry_entry and registry_entry.disabled_by is None
        for registry_entry in entries.values()
    )
    assert hass.states.get(entity_id_of("number", "ems_charging_current"))
    assert hass.states.get(entity_id_of("select", "ems_relay_matrix"))

    await _async_set_allow_control(hass, entry, False)
    assert set(_registry_entries(hass, serial).values()) == {None}
    assert not hass.states.async_entity_ids(("number", "select"))


@pytest.mark.parametrize("allow_control", [True])
async def test_user_settings_are_restored_when_control_is_allowed_again(
    hass, entry, serial, setup_integration, entity_id_of
) -> None:
    """Restore the entity ID and user disabling of controls allowed again."""
    await setup_integration()
    registry = er.async_get(hass)
    registry.async_update_entity(
        entity_id_of("number", "ems_charging_current"),
        new_entity_id="number.my_charging_current",
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    await _async_set_allow_control(hass, entry, False)
    await _async_set_allow_control(hass, entry, True)

    entries = _registry_entries(hass, serial)
    assert entries["ems_charging_current"].entity_id == "number.my_charging_current"
    assert entries["ems_charging_current"].disabled_by is (
        er.RegistryEntryDisabler.USER
    )
    assert entries["ems_relay_matrix"].disabled_by is None


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
