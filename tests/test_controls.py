"""Tests for the EMS number, select and switch entities."""

import pytest
from homeassistant.exceptions import HomeAssistantError
from modbus_connection import ModbusError

from custom_components.kathrein_wallbox.number import KathreinChargingCurrentNumber
from custom_components.kathrein_wallbox.select import KathreinRelayMatrixSelect
from custom_components.kathrein_wallbox.switch import KathreinEmsControlSwitch

DEVICE_INFO_ADDRESS = 0x0019
DEVICE_INFO_11_KW = 0x0001
EMS_CONTROL_ADDRESS = 0x00A0
EMS_RELAY_MATRIX_ADDRESS = 0x00A1
EMS_CHARGING_CURRENT_ADDRESS = 0x00A2


def _writes(unit) -> list[tuple[int, list[int]]]:
    return [(event.address, event.values) for event in unit.write_events]


async def _set_ems_register(coordinator, unit, address, value) -> None:
    unit.holding[address] = value
    await coordinator.ems_control.async_update()


@pytest.mark.parametrize(
    ("register", "expected"),
    [(16000, 16.0), (13000, 13.0), (0, None), (0xFFFF, None)],
)
async def test_charging_current_number_reads_setpoint(
    coordinator, mock_modbus_unit, register, expected
) -> None:
    """Show the setpoint in A and hide paused or cancelled values."""
    await _set_ems_register(
        coordinator, mock_modbus_unit, EMS_CHARGING_CURRENT_ADDRESS, register
    )

    assert KathreinChargingCurrentNumber(coordinator).native_value == expected


async def test_charging_current_number_limits_11_kw_wallbox(
    coordinator, mock_modbus_unit
) -> None:
    """Offer 6 to 32 A, or 6 to 16 A on an 11 kW Wallbox."""
    number = KathreinChargingCurrentNumber(coordinator)
    assert (number.native_min_value, number.native_max_value) == (6, 32)

    mock_modbus_unit.holding[DEVICE_INFO_ADDRESS] = DEVICE_INFO_11_KW
    await coordinator.identity.async_update()

    assert number.native_max_value == 16


async def test_charging_current_number_writes_milliamperes(
    coordinator, mock_modbus_unit
) -> None:
    """Write a whole-ampere setpoint as mA and read it back right away."""
    number = KathreinChargingCurrentNumber(coordinator)

    await number.async_set_native_value(13)

    assert _writes(mock_modbus_unit) == [(EMS_CHARGING_CURRENT_ADDRESS, [13000])]
    assert number.native_value == 13


@pytest.mark.parametrize(
    ("register", "expected"),
    [(0x0001, "phase_1"), (0x0007, "three_phases"), (0x0002, None)],
)
async def test_relay_matrix_select_reads_phases(
    coordinator, mock_modbus_unit, register, expected
) -> None:
    """Map the relay matrix register to the selectable phase options."""
    await _set_ems_register(
        coordinator, mock_modbus_unit, EMS_RELAY_MATRIX_ADDRESS, register
    )

    assert KathreinRelayMatrixSelect(coordinator).current_option == expected


@pytest.mark.parametrize(("option", "value"), [("phase_1", 1), ("three_phases", 7)])
async def test_relay_matrix_select_writes_phases(
    coordinator, mock_modbus_unit, option, value
) -> None:
    """Write the selected phases to the relay matrix register."""
    await KathreinRelayMatrixSelect(coordinator).async_select_option(option)

    assert _writes(mock_modbus_unit) == [(EMS_RELAY_MATRIX_ADDRESS, [value])]


@pytest.mark.parametrize(("register", "expected"), [(0x8000, True), (0, False)])
async def test_ems_control_switch_reads_control_bit(
    coordinator, mock_modbus_unit, register, expected
) -> None:
    """Report EMS control from bit 15 of the control register."""
    await _set_ems_register(
        coordinator, mock_modbus_unit, EMS_CONTROL_ADDRESS, register
    )

    assert KathreinEmsControlSwitch(coordinator).is_on is expected


async def test_ems_control_switch_writes_control_register(
    coordinator, mock_modbus_unit
) -> None:
    """Turn EMS control on and off through the control register."""
    switch = KathreinEmsControlSwitch(coordinator)

    await switch.async_turn_on()
    await switch.async_turn_off()

    assert _writes(mock_modbus_unit) == [
        (EMS_CONTROL_ADDRESS, [0x8000]),
        (EMS_CONTROL_ADDRESS, [0]),
    ]


async def test_control_reports_device_write_failure(
    coordinator, mock_modbus_unit
) -> None:
    """Surface a failed register write as a Home Assistant error."""
    mock_modbus_unit.fail_write(EMS_CONTROL_ADDRESS, ModbusError("write rejected"))

    with pytest.raises(HomeAssistantError) as error:
        await KathreinEmsControlSwitch(coordinator).async_turn_on()

    assert error.value.translation_key == "write_failed"
