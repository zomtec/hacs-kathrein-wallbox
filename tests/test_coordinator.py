"""Tests for coordinator polling and optional register blocks."""

from datetime import timedelta

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from modbus_connection import IllegalDataAddressError, ModbusError
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.kathrein_wallbox.model import SERIAL_ADDRESS


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
async def test_missing_serial_number_fails_wallbox_poll(
    coordinator, mock_modbus_unit
) -> None:
    """Refuse to publish data for a device that reports no serial number."""
    mock_modbus_unit.holding[SERIAL_ADDRESS] = [0] * 8

    with pytest.raises(UpdateFailed, match="serial number"):
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


EMS_CONTROL_ADDRESS = 0x00A0
EMS_CHARGING_CURRENT_ADDRESS = 0x00A2
EMS_TIMEOUT_PERIOD_ADDRESS = 0x00A3


async def _poll_with_ems(coordinator, unit, timeout_s, control=0x8000) -> None:
    unit.holding[EMS_CONTROL_ADDRESS] = control
    unit.holding[EMS_CHARGING_CURRENT_ADDRESS] = 13000
    unit.holding[EMS_TIMEOUT_PERIOD_ADDRESS] = timeout_s
    await coordinator._async_update_data()


def _setpoint_writes(unit) -> list[list[int]]:
    return [
        event.values
        for event in unit.write_events
        if event.address == EMS_CHARGING_CURRENT_ADDRESS
    ]


async def test_keep_alive_rewrites_setpoint_within_timeout(
    hass, coordinator, mock_modbus_unit
) -> None:
    """Rewrite the charging current at half the EMS timeout period."""
    await _poll_with_ems(coordinator, mock_modbus_unit, 60)
    coordinator.async_set_keep_alive(True)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()

    assert _setpoint_writes(mock_modbus_unit) == [[13000]]


async def test_keep_alive_is_off_by_default(
    hass, coordinator, mock_modbus_unit
) -> None:
    """Leave the EMS timeout alone until the user turns the keep-alive on."""
    await _poll_with_ems(coordinator, mock_modbus_unit, 60)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()

    assert not coordinator.keep_alive_enabled
    assert _setpoint_writes(mock_modbus_unit) == []


async def test_keep_alive_turns_off_without_timeout(
    hass, coordinator, mock_modbus_unit
) -> None:
    """Stop the keep-alive when the Wallbox timeout is set to 0 s."""
    await _poll_with_ems(coordinator, mock_modbus_unit, 60)
    coordinator.async_set_keep_alive(True)

    await _poll_with_ems(coordinator, mock_modbus_unit, 0)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()

    assert not coordinator.keep_alive_supported
    assert not coordinator.keep_alive_enabled
    assert _setpoint_writes(mock_modbus_unit) == []


async def test_keep_alive_skips_disabled_ems_control(
    hass, coordinator, mock_modbus_unit
) -> None:
    """Write nothing while EMS control is off."""
    await _poll_with_ems(coordinator, mock_modbus_unit, 60, control=0)
    coordinator.async_set_keep_alive(True)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()

    assert _setpoint_writes(mock_modbus_unit) == []


async def test_keep_alive_survives_write_failure(
    hass, coordinator, mock_modbus_unit, caplog
) -> None:
    """Log a failed keep-alive write once and keep the timer running."""
    await _poll_with_ems(coordinator, mock_modbus_unit, 60)
    coordinator.async_set_keep_alive(True)
    mock_modbus_unit.fail_write(
        EMS_CHARGING_CURRENT_ADDRESS, ModbusError("write rejected")
    )

    for seconds in (31, 61):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
        await hass.async_block_till_done()

    mock_modbus_unit.fail_write(EMS_CHARGING_CURRENT_ADDRESS, None)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=91))
    await hass.async_block_till_done()

    assert caplog.text.count("EMS keep-alive write failed") == 1
    assert _setpoint_writes(mock_modbus_unit) == [[13000]]
