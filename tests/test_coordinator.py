"""Tests for coordinator polling and optional register blocks."""

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from modbus_connection import IllegalDataAddressError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kathrein_wallbox.const import DOMAIN
from custom_components.kathrein_wallbox.coordinator import KathreinCoordinator


@pytest.fixture
def coordinator(hass, mock_modbus_unit):
    """Create a coordinator attached to an in-memory config entry."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    return KathreinCoordinator(hass, entry, mock_modbus_unit)


@pytest.mark.asyncio
async def test_missing_meter_does_not_fail_wallbox_poll(
    coordinator, mock_modbus_unit
) -> None:
    """Keep essential EVSE polling available when the optional meter is absent."""
    mock_modbus_unit.holding[0x0060] = 4
    mock_modbus_unit.fail_read(0x0030, IllegalDataAddressError())

    data = await coordinator._async_update_data()

    assert data.evse.charging_state == 4
    assert not coordinator.meter_available
    assert not coordinator.session_energy_available


@pytest.mark.asyncio
async def test_required_register_failure_fails_wallbox_poll(
    coordinator, mock_modbus_unit
) -> None:
    """Surface identity-register failures as coordinator update failures."""
    mock_modbus_unit.fail_read(0x0000, IllegalDataAddressError())

    with pytest.raises(UpdateFailed, match="Unable to read Kathrein Wallbox"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_session_energy_failure_recovers_without_losing_meter(
    coordinator, mock_modbus_unit
) -> None:
    """Keep meter availability and recover session energy after a read failure."""
    mock_modbus_unit.holding[0x0030] = [0x4366, 0]
    mock_modbus_unit.holding[0x005E] = [0x4248, 0]
    mock_modbus_unit.fail_read(0x0069, IllegalDataAddressError())

    await coordinator._async_update_data()

    assert coordinator.meter_available
    assert not coordinator.session_energy_available

    mock_modbus_unit.fail_read(0x0069, None)
    mock_modbus_unit.holding[0x0069] = [0, 1500]
    data = await coordinator._async_update_data()

    assert coordinator.meter_available
    assert coordinator.session_energy_available
    assert data.session_energy.charging_energy == 1500