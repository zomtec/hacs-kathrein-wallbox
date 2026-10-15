"""Tests for disabling control entities while control is not allowed."""

from unittest.mock import Mock

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kathrein_wallbox.const import (
    CONF_ALLOW_CONTROL,
    CONF_UNIT_ID,
    DOMAIN,
)

SERIAL = "G0R1234567"
CONTROL_ENTITIES = (
    ("switch", "ems_control"),
    ("number", "ems_charging_current"),
    ("select", "ems_relay_matrix"),
)
SENSOR_UNIQUE_ID = f"{SERIAL}_charging_state"


@pytest.fixture
def entry(
    hass, monkeypatch, mock_modbus_unit, enable_custom_integrations
) -> MockConfigEntry:
    """Add a Wallbox entry that talks to the in-memory unit."""
    monkeypatch.setattr(
        "custom_components.kathrein_wallbox.async_get_unit",
        Mock(return_value=mock_modbus_unit),
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        data={CONF_HOST: "wallbox.local", CONF_PORT: 502, CONF_UNIT_ID: 0},
        options={CONF_ALLOW_CONTROL: False},
    )
    entry.add_to_hass(hass)
    return entry


async def _async_set_allow_control(hass, entry, allowed: bool) -> None:
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ALLOW_CONTROL: allowed}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


def _disabled_by(hass) -> dict[str, er.RegistryEntryDisabler | None]:
    registry = er.async_get(hass)
    return {
        key: registry.async_get(
            registry.async_get_entity_id(platform, DOMAIN, f"{SERIAL}_{key}")
        ).disabled_by
        for platform, key in CONTROL_ENTITIES
    }


async def test_controls_are_created_disabled_without_control_allowed(
    hass, entry
) -> None:
    """Create control entities disabled while control is not allowed."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert set(_disabled_by(hass).values()) == {er.RegistryEntryDisabler.INTEGRATION}
    sensor_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, SENSOR_UNIQUE_ID
    )
    assert er.async_get(hass).async_get(sensor_id).disabled_by is None


async def test_controls_follow_allow_control_option(hass, entry) -> None:
    """Disable controls when control is withdrawn and enable them when allowed."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await _async_set_allow_control(hass, entry, True)
    assert set(_disabled_by(hass).values()) == {None}
    assert hass.states.get(
        er.async_get(hass).async_get_entity_id(
            "switch", DOMAIN, f"{SERIAL}_ems_control"
        )
    )

    await _async_set_allow_control(hass, entry, False)
    assert set(_disabled_by(hass).values()) == {er.RegistryEntryDisabler.INTEGRATION}


async def test_user_disabled_controls_stay_disabled(hass, entry) -> None:
    """Keep controls the user disabled, whatever the control option says."""
    hass.config_entries.async_update_entry(entry, options={CONF_ALLOW_CONTROL: True})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    switch_id = registry.async_get_entity_id("switch", DOMAIN, f"{SERIAL}_ems_control")
    registry.async_update_entity(switch_id, disabled_by=er.RegistryEntryDisabler.USER)

    await _async_set_allow_control(hass, entry, False)
    await _async_set_allow_control(hass, entry, True)

    assert _disabled_by(hass) == {
        "ems_control": er.RegistryEntryDisabler.USER,
        "ems_charging_current": None,
        "ems_relay_matrix": None,
    }
