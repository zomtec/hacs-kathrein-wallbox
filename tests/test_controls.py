"""Tests for the EMS number and select entities."""

import pytest
from homeassistant.components.number import NumberMode
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from modbus_connection import ModbusError

from custom_components.kathrein_wallbox.number import KathreinChargingCurrentNumber
from custom_components.kathrein_wallbox.select import KathreinRelayMatrixSelect

DEVICE_INFO_ADDRESS = 0x0019
DEVICE_INFO_11_KW = 0x0001
EMS_CONTROL_ADDRESS = 0x00A0
EMS_RELAY_MATRIX_ADDRESS = 0x00A1
EMS_CHARGING_CURRENT_ADDRESS = 0x00A2
ENABLE_EMS = (EMS_CONTROL_ADDRESS, [0x8000])


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

    assert _writes(mock_modbus_unit) == [
        ENABLE_EMS,
        (EMS_CHARGING_CURRENT_ADDRESS, [13000]),
    ]
    assert number.native_value == 13


async def test_charging_current_number_pauses_at_zero(
    coordinator, mock_modbus_unit
) -> None:
    """Pause charging by writing 0 mA."""
    await KathreinChargingCurrentNumber(coordinator).async_set_native_value(0)

    assert _writes(mock_modbus_unit) == [
        ENABLE_EMS,
        (EMS_CHARGING_CURRENT_ADDRESS, [0]),
    ]


@pytest.mark.parametrize("value", [1, 5])
async def test_charging_current_number_pauses_below_minimum(
    coordinator, mock_modbus_unit, value
) -> None:
    """Pause charging for 1 to 5 A, which the Wallbox cannot charge with."""
    number = KathreinChargingCurrentNumber(coordinator)

    await number.async_set_native_value(value)

    assert _writes(mock_modbus_unit) == [
        ENABLE_EMS,
        (EMS_CHARGING_CURRENT_ADDRESS, [0]),
    ]
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

    assert _writes(mock_modbus_unit) == [
        ENABLE_EMS,
        (EMS_RELAY_MATRIX_ADDRESS, [value]),
    ]


async def test_control_reports_device_write_failure(
    coordinator, mock_modbus_unit
) -> None:
    """Surface a failed register write as a Home Assistant error."""
    mock_modbus_unit.fail_write(EMS_CONTROL_ADDRESS, ModbusError("write rejected"))

    with pytest.raises(HomeAssistantError) as error:
        await KathreinRelayMatrixSelect(coordinator).async_select_option("phase_1")

    assert error.value.translation_key == "write_failed"


async def test_charging_current_number_enables_disabled_ems_control(
    coordinator, mock_modbus_unit
) -> None:
    """Stay available while EMS control is off and enable it before the setpoint."""
    await _set_ems_register(coordinator, mock_modbus_unit, EMS_CONTROL_ADDRESS, 0)
    number = KathreinChargingCurrentNumber(coordinator)
    assert number.available

    await number.async_set_native_value(10)

    assert _writes(mock_modbus_unit) == [
        ENABLE_EMS,
        (EMS_CHARGING_CURRENT_ADDRESS, [10000]),
    ]
    assert coordinator.ems_control.is_enabled


@pytest.mark.parametrize(
    "entity_class",
    [
        KathreinChargingCurrentNumber,
        KathreinRelayMatrixSelect,
    ],
)
async def test_controls_need_control_allowed(
    read_only_coordinator, mock_modbus_unit, entity_class
) -> None:
    """Disable all controls while control by Home Assistant is not allowed."""
    await _set_ems_register(
        read_only_coordinator, mock_modbus_unit, EMS_CONTROL_ADDRESS, 0x8000
    )

    assert entity_class(read_only_coordinator).available is False


async def test_write_is_rejected_without_control_allowed(
    read_only_coordinator, mock_modbus_unit
) -> None:
    """Refuse to write while control by Home Assistant is not allowed."""
    with pytest.raises(ServiceValidationError) as error:
        await KathreinChargingCurrentNumber(
            read_only_coordinator
        ).async_set_native_value(10)

    assert error.value.translation_key == "control_not_allowed"
    assert _writes(mock_modbus_unit) == []
