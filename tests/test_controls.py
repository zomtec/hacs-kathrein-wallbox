"""Tests for the EMS number and select entities."""

import pytest
from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_MIN,
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
    NumberMode,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_MODE,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
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


async def _async_set_charging_current(hass, entity_id_of, value: float) -> None:
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {
            ATTR_ENTITY_ID: entity_id_of(NUMBER_DOMAIN, "ems_charging_current"),
            ATTR_VALUE: value,
        },
        blocking=True,
    )


async def _async_select_phases(hass, entity_id_of, option: str) -> None:
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: entity_id_of(SELECT_DOMAIN, "ems_relay_matrix"),
            ATTR_OPTION: option,
        },
        blocking=True,
    )


@pytest.mark.parametrize(
    ("register", "expected"),
    [
        (16000, "16.0"),
        (13000, "13.0"),
        (6500, "6.5"),
        (0, "0.0"),
        (5999, STATE_UNKNOWN),
        (32001, STATE_UNKNOWN),
        (0xFFFF, STATE_UNKNOWN),
    ],
)
async def test_charging_current_number_reads_setpoint(
    mock_modbus_unit, setup_integration, state_of, register, expected
) -> None:
    """Show the setpoint in A, 0 A while paused, and hide a cancel value."""
    mock_modbus_unit.holding[EMS_CHARGING_CURRENT_ADDRESS] = register

    await setup_integration()

    assert state_of(NUMBER_DOMAIN, "ems_charging_current") == expected


@pytest.mark.parametrize(
    ("device_info", "maximum"), [(0x0000, 32), (DEVICE_INFO_11_KW, 16)]
)
async def test_charging_current_number_limits_11_kw_wallbox(
    hass, mock_modbus_unit, setup_integration, entity_id_of, device_info, maximum
) -> None:
    """Offer 0 to 32 A, or 0 to 16 A on an 11 kW Wallbox."""
    mock_modbus_unit.holding[DEVICE_INFO_ADDRESS] = device_info

    await setup_integration()

    state = hass.states.get(entity_id_of(NUMBER_DOMAIN, "ems_charging_current"))
    assert (state.attributes[ATTR_MIN], state.attributes[ATTR_MAX]) == (0, maximum)


async def test_charging_current_number_is_input_box(
    hass, setup_integration, entity_id_of
) -> None:
    """Show the setpoint as a numeric input box instead of a slider."""
    await setup_integration()

    state = hass.states.get(entity_id_of(NUMBER_DOMAIN, "ems_charging_current"))
    assert state.attributes[ATTR_MODE] == NumberMode.BOX


async def test_charging_current_number_writes_milliamperes(
    hass, mock_modbus_unit, setup_integration, entity_id_of, state_of
) -> None:
    """Write a whole-ampere setpoint as mA and read it back right away."""
    await setup_integration()

    await _async_set_charging_current(hass, entity_id_of, 13)

    assert mock_modbus_unit.writes == [
        ENABLE_EMS,
        (EMS_CHARGING_CURRENT_ADDRESS, [13000]),
    ]
    assert state_of(NUMBER_DOMAIN, "ems_charging_current") == "13.0"


@pytest.mark.parametrize("value", [0, 1, 5])
async def test_charging_current_number_pauses_below_minimum(
    hass, mock_modbus_unit, setup_integration, entity_id_of, state_of, value
) -> None:
    """Pause charging with 0 A and for 1 to 5 A, which the Wallbox cannot charge with."""
    await setup_integration()

    await _async_set_charging_current(hass, entity_id_of, value)

    assert mock_modbus_unit.writes == [
        ENABLE_EMS,
        (EMS_CHARGING_CURRENT_ADDRESS, [0]),
    ]
    assert state_of(NUMBER_DOMAIN, "ems_charging_current") == "0.0"


@pytest.mark.parametrize(("value", "milliamperes"), [(6.5, 6000), (7.5, 8000)])
async def test_charging_current_number_rounds_to_whole_amperes(
    hass, mock_modbus_unit, setup_integration, entity_id_of, value, milliamperes
) -> None:
    """Round a fractional setpoint to whole amperes, a half to the even number."""
    await setup_integration()

    await _async_set_charging_current(hass, entity_id_of, value)

    assert mock_modbus_unit.writes == [
        ENABLE_EMS,
        (EMS_CHARGING_CURRENT_ADDRESS, [milliamperes]),
    ]


@pytest.mark.parametrize(
    ("register", "expected"),
    [(0x0001, "phase_1"), (0x0007, "three_phases"), (0x0002, STATE_UNKNOWN)],
)
async def test_relay_matrix_select_reads_phases(
    mock_modbus_unit, setup_integration, state_of, register, expected
) -> None:
    """Map the relay matrix register to the selectable phase options."""
    mock_modbus_unit.holding[EMS_RELAY_MATRIX_ADDRESS] = register

    await setup_integration()

    assert state_of(SELECT_DOMAIN, "ems_relay_matrix") == expected


@pytest.mark.parametrize(("option", "value"), [("phase_1", 1), ("three_phases", 7)])
async def test_relay_matrix_select_writes_phases(
    hass, mock_modbus_unit, setup_integration, entity_id_of, state_of, option, value
) -> None:
    """Write the selected phases to the relay matrix register."""
    await setup_integration()

    await _async_select_phases(hass, entity_id_of, option)

    assert mock_modbus_unit.writes == [
        ENABLE_EMS,
        (EMS_RELAY_MATRIX_ADDRESS, [value]),
    ]
    assert state_of(SELECT_DOMAIN, "ems_relay_matrix") == option


async def test_control_reports_device_write_failure(
    hass, mock_modbus_unit, setup_integration, entity_id_of
) -> None:
    """Surface a failed register write as a Home Assistant error."""
    await setup_integration()
    mock_modbus_unit.fail_write(EMS_CONTROL_ADDRESS, ModbusError("write rejected"))

    with pytest.raises(HomeAssistantError) as error:
        await _async_select_phases(hass, entity_id_of, "phase_1")

    assert error.value.translation_key == "write_failed"


async def test_charging_current_number_enables_disabled_ems_control(
    hass, mock_modbus_unit, setup_integration, entity_id_of, state_of
) -> None:
    """Stay available while EMS control is off and enable it before the setpoint."""
    mock_modbus_unit.holding[EMS_CONTROL_ADDRESS] = 0
    await setup_integration()
    assert state_of(NUMBER_DOMAIN, "ems_charging_current") != STATE_UNAVAILABLE

    await _async_set_charging_current(hass, entity_id_of, 10)

    assert mock_modbus_unit.writes == [
        ENABLE_EMS,
        (EMS_CHARGING_CURRENT_ADDRESS, [10000]),
    ]
    assert state_of("binary_sensor", "ems_control") == STATE_ON


# Setup never adds the controls without control allowed; test their guards directly.
@pytest.mark.parametrize("allow_control", [False])
@pytest.mark.parametrize(
    "entity_class",
    [
        KathreinChargingCurrentNumber,
        KathreinRelayMatrixSelect,
    ],
)
async def test_controls_need_control_allowed(
    entry, mock_modbus_unit, setup_integration, entity_class
) -> None:
    """Disable all controls while control by Home Assistant is not allowed."""
    mock_modbus_unit.holding[EMS_CONTROL_ADDRESS] = 0x8000
    await setup_integration()

    assert entity_class(entry.runtime_data.coordinator).available is False


@pytest.mark.parametrize("allow_control", [False])
async def test_write_is_rejected_without_control_allowed(
    entry, mock_modbus_unit, setup_integration
) -> None:
    """Refuse to write while control by Home Assistant is not allowed."""
    await setup_integration()
    number = KathreinChargingCurrentNumber(entry.runtime_data.coordinator)

    with pytest.raises(ServiceValidationError) as error:
        await number.async_set_native_value(10)

    assert error.value.translation_key == "control_not_allowed"
    assert mock_modbus_unit.writes == []
