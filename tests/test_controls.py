"""Tests for the EMS number, select and switch entities."""

import pytest
from homeassistant.components.number import NumberMode
from homeassistant.core import State
from homeassistant.exceptions import HomeAssistantError
from modbus_connection import ModbusError
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.kathrein_wallbox.number import KathreinChargingCurrentNumber
from custom_components.kathrein_wallbox.select import KathreinRelayMatrixSelect
from custom_components.kathrein_wallbox.switch import (
    KathreinEmsControlSwitch,
    KathreinEmsKeepAliveSwitch,
)

DEVICE_INFO_ADDRESS = 0x0019
DEVICE_INFO_11_KW = 0x0001
EMS_CONTROL_ADDRESS = 0x00A0
EMS_RELAY_MATRIX_ADDRESS = 0x00A1
EMS_CHARGING_CURRENT_ADDRESS = 0x00A2
EMS_TIMEOUT_PERIOD_ADDRESS = 0x00A3
KEEP_ALIVE_ENTITY_ID = "switch.kathrein_wallbox_ems_keep_alive"


def _writes(unit) -> list[tuple[int, list[int]]]:
    return [(event.address, event.values) for event in unit.write_events]


async def _set_ems_register(coordinator, unit, address, value) -> None:
    unit.holding[address] = value
    await coordinator.ems_control.async_update()


@pytest.mark.parametrize(
    ("register", "expected"),
    [(16000, 16.0), (13000, 13.0), (0, 0.0), (0xFFFF, None)],
)
async def test_charging_current_number_reads_setpoint(
    coordinator, mock_modbus_unit, register, expected
) -> None:
    """Show the setpoint in A, 0 A while paused, and hide a cancel value."""
    await _set_ems_register(
        coordinator, mock_modbus_unit, EMS_CHARGING_CURRENT_ADDRESS, register
    )

    assert KathreinChargingCurrentNumber(coordinator).native_value == expected


async def test_charging_current_number_limits_11_kw_wallbox(
    coordinator, mock_modbus_unit
) -> None:
    """Offer 0 to 32 A, or 0 to 16 A on an 11 kW Wallbox."""
    number = KathreinChargingCurrentNumber(coordinator)
    assert (number.native_min_value, number.native_max_value) == (0, 32)

    mock_modbus_unit.holding[DEVICE_INFO_ADDRESS] = DEVICE_INFO_11_KW
    await coordinator.identity.async_update()

    assert number.native_max_value == 16


async def test_charging_current_number_is_input_box(coordinator) -> None:
    """Show the setpoint as a numeric input box instead of a slider."""
    assert KathreinChargingCurrentNumber(coordinator).mode == NumberMode.BOX


async def test_charging_current_number_writes_milliamperes(
    coordinator, mock_modbus_unit
) -> None:
    """Write a whole-ampere setpoint as mA and read it back right away."""
    number = KathreinChargingCurrentNumber(coordinator)

    await number.async_set_native_value(13)

    assert _writes(mock_modbus_unit) == [(EMS_CHARGING_CURRENT_ADDRESS, [13000])]
    assert number.native_value == 13


async def test_charging_current_number_pauses_at_zero(
    coordinator, mock_modbus_unit
) -> None:
    """Pause charging by writing 0 mA."""
    await KathreinChargingCurrentNumber(coordinator).async_set_native_value(0)

    assert _writes(mock_modbus_unit) == [(EMS_CHARGING_CURRENT_ADDRESS, [0])]


@pytest.mark.parametrize("value", [1, 5])
async def test_charging_current_number_pauses_below_minimum(
    coordinator, mock_modbus_unit, value
) -> None:
    """Pause charging for 1 to 5 A, which the Wallbox cannot charge with."""
    number = KathreinChargingCurrentNumber(coordinator)

    await number.async_set_native_value(value)

    assert _writes(mock_modbus_unit) == [(EMS_CHARGING_CURRENT_ADDRESS, [0])]
    assert number.native_value == 0


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


@pytest.mark.parametrize(("timeout_s", "available"), [(60, True), (0, False)])
async def test_keep_alive_switch_needs_ems_timeout(
    coordinator, mock_modbus_unit, timeout_s, available
) -> None:
    """Start off and allow control only with an EMS timeout above 0 s."""
    mock_modbus_unit.holding[EMS_CONTROL_ADDRESS] = 0x8000
    await _set_ems_register(
        coordinator, mock_modbus_unit, EMS_TIMEOUT_PERIOD_ADDRESS, timeout_s
    )
    switch = KathreinEmsKeepAliveSwitch(coordinator)

    assert switch.available is available
    assert switch.is_on is False


async def test_keep_alive_switch_turns_keep_alive_on_and_off(
    coordinator, mock_modbus_unit
) -> None:
    """Switch the keep-alive without writing to the Wallbox."""
    await _set_ems_register(
        coordinator, mock_modbus_unit, EMS_TIMEOUT_PERIOD_ADDRESS, 60
    )
    switch = KathreinEmsKeepAliveSwitch(coordinator)

    await switch.async_turn_on()
    assert switch.is_on is True

    await switch.async_turn_off()
    assert switch.is_on is False
    assert _writes(mock_modbus_unit) == []


@pytest.mark.parametrize(("timeout_s", "restored"), [(60, True), (0, False)])
async def test_keep_alive_switch_restores_state(
    hass, coordinator, mock_modbus_unit, timeout_s, restored
) -> None:
    """Resume a keep-alive turned on before a restart if a timeout is still set."""
    await _set_ems_register(
        coordinator, mock_modbus_unit, EMS_TIMEOUT_PERIOD_ADDRESS, timeout_s
    )
    mock_restore_cache(hass, [State(KEEP_ALIVE_ENTITY_ID, "on")])
    switch = KathreinEmsKeepAliveSwitch(coordinator)
    switch.hass = hass
    switch.entity_id = KEEP_ALIVE_ENTITY_ID

    await switch.async_added_to_hass()

    assert switch.is_on is restored


@pytest.mark.parametrize(
    "entity_class",
    [
        KathreinChargingCurrentNumber,
        KathreinRelayMatrixSelect,
        KathreinEmsKeepAliveSwitch,
    ],
)
@pytest.mark.parametrize(("control", "available"), [(0x8000, True), (0, False)])
async def test_controls_need_ems_control(
    coordinator, mock_modbus_unit, entity_class, control, available
) -> None:
    """Allow the other controls only while EMS control is on."""
    mock_modbus_unit.holding[EMS_TIMEOUT_PERIOD_ADDRESS] = 60
    await _set_ems_register(coordinator, mock_modbus_unit, EMS_CONTROL_ADDRESS, control)

    assert entity_class(coordinator).available is available


async def test_ems_control_switch_stays_available_while_off(
    coordinator, mock_modbus_unit
) -> None:
    """Keep EMS control itself switchable while it is off."""
    await _set_ems_register(coordinator, mock_modbus_unit, EMS_CONTROL_ADDRESS, 0)

    assert KathreinEmsControlSwitch(coordinator).available
