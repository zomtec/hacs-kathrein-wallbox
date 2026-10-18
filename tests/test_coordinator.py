"""Tests for coordinator polling and optional register blocks."""

import logging
from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.util import dt as dt_util
from modbus_connection import IllegalDataAddressError, ModbusError
from modbus_connection.encode import encode_float32, encode_uint32
from modbus_connection.mock import MockModbusUnit
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.kathrein_wallbox.const import CONF_METER_DETECTED, DOMAIN
from custom_components.kathrein_wallbox.model import (
    SERIAL_ADDRESS,
    SERIAL_REGISTER_COUNT,
)

MAPPING_VERSION_ADDRESS = 0x0000
VOLTAGE_L1_ADDRESS = 0x0030
FREQUENCY_ADDRESS = 0x005E
CHARGING_STATE_ADDRESS = 0x0060
CHARGING_ENERGY_ADDRESS = 0x0069
CHARGING_TAG_INFO_ADDRESS = 0x0070
EMS_CONTROL_ADDRESS = 0x00A0
EMS_CHARGING_CURRENT_ADDRESS = 0x00A2
EMS_TIMEOUT_PERIOD_ADDRESS = 0x00A3


async def test_missing_meter_does_not_fail_wallbox_poll(
    mock_modbus_unit, setup_integration, enable_entity, state_of
) -> None:
    """Keep essential EVSE polling available when the optional meter is absent."""
    enable_entity("sensor", "total_active_power")
    enable_entity("sensor", "charging_energy")
    mock_modbus_unit.holding[CHARGING_STATE_ADDRESS] = 4
    mock_modbus_unit.fail_read(VOLTAGE_L1_ADDRESS, IllegalDataAddressError())

    await setup_integration()

    assert state_of("sensor", "charging_state") == "charging_active"
    assert state_of("sensor", "total_active_power") == STATE_UNAVAILABLE
    assert state_of("sensor", "charging_energy") == STATE_UNAVAILABLE


def _fail_identity(unit: MockModbusUnit) -> None:
    unit.fail_read(MAPPING_VERSION_ADDRESS, IllegalDataAddressError())


def _report_no_serial(unit: MockModbusUnit) -> None:
    unit.holding[SERIAL_ADDRESS] = [0] * SERIAL_REGISTER_COUNT


def _fail_evse(unit: MockModbusUnit) -> None:
    unit.fail_read(CHARGING_STATE_ADDRESS, IllegalDataAddressError())


@pytest.mark.parametrize(
    ("break_device", "translation_key"),
    [
        (_fail_identity, "update_failed"),
        (_report_no_serial, "missing_serial_number"),
        (_fail_evse, "update_failed"),
    ],
    ids=["identity", "serial", "evse"],
)
async def test_device_failure_retries_setup(
    hass, entry, mock_modbus_unit, break_device, translation_key
) -> None:
    """Retry the setup with a translated reason while the Wallbox cannot be read."""
    break_device(mock_modbus_unit)

    assert not await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.error_reason_translation_domain == DOMAIN
    assert entry.error_reason_translation_key == translation_key


async def test_poll_does_not_read_identity_again(
    mock_modbus_unit, setup_integration, poll, state_of
) -> None:
    """Read the static identity once during setup, not on every poll."""
    await setup_integration()
    mock_modbus_unit.fail_read(MAPPING_VERSION_ADDRESS, IllegalDataAddressError())
    mock_modbus_unit.holding[CHARGING_STATE_ADDRESS] = 4

    await poll()

    assert state_of("sensor", "charging_state") == "charging_active"


async def test_session_energy_failure_recovers_without_losing_meter(
    mock_modbus_unit, setup_integration, enable_entity, poll, state_of
) -> None:
    """Keep meter availability and recover session energy after a read failure."""
    enable_entity("sensor", "charging_energy")
    mock_modbus_unit.holding[VOLTAGE_L1_ADDRESS] = encode_float32(230.0)
    mock_modbus_unit.holding[FREQUENCY_ADDRESS] = encode_float32(50.0)
    mock_modbus_unit.fail_read(CHARGING_ENERGY_ADDRESS, IllegalDataAddressError())
    await setup_integration()

    assert state_of("sensor", "total_active_power") != STATE_UNAVAILABLE
    assert state_of("sensor", "charging_energy") == STATE_UNAVAILABLE

    mock_modbus_unit.fail_read(CHARGING_ENERGY_ADDRESS, None)
    mock_modbus_unit.holding[CHARGING_ENERGY_ADDRESS] = encode_uint32(1500)
    await poll()

    assert state_of("sensor", "total_active_power") != STATE_UNAVAILABLE
    assert state_of("sensor", "charging_energy") == "1500"


async def test_charging_session_failure_keeps_evse_data(
    mock_modbus_unit, setup_integration, enable_entity, poll, state_of
) -> None:
    """Keep EVSE data when the session tag registers fail, and recover later."""
    enable_entity("sensor", "charging_tag")
    mock_modbus_unit.holding[CHARGING_STATE_ADDRESS] = 4
    mock_modbus_unit.fail_read(CHARGING_TAG_INFO_ADDRESS, IllegalDataAddressError())
    await setup_integration()

    assert state_of("sensor", "charging_state") == "charging_active"
    assert state_of("sensor", "charging_tag") == STATE_UNAVAILABLE

    mock_modbus_unit.fail_read(CHARGING_TAG_INFO_ADDRESS, None)
    await poll()

    assert state_of("sensor", "charging_tag") != STATE_UNAVAILABLE


async def test_detected_meter_is_stored_and_never_reported_missing(
    entry, mock_modbus_unit, setup_integration, poll, state_of
) -> None:
    """Keep a detected meter detected when its readings later fail or vanish."""
    mock_modbus_unit.holding[VOLTAGE_L1_ADDRESS] = encode_float32(230.0)
    await setup_integration()

    assert entry.data[CONF_METER_DETECTED] is True
    assert state_of("binary_sensor", "meter_available") == STATE_ON
    assert state_of("sensor", "total_active_power") != STATE_UNAVAILABLE

    mock_modbus_unit.holding[VOLTAGE_L1_ADDRESS] = encode_float32(0.0)
    await poll()

    assert state_of("binary_sensor", "meter_available") == STATE_ON
    assert state_of("sensor", "total_active_power") != STATE_UNAVAILABLE

    mock_modbus_unit.fail_read(VOLTAGE_L1_ADDRESS, IllegalDataAddressError())
    await poll()

    assert entry.data[CONF_METER_DETECTED] is True
    assert state_of("binary_sensor", "meter_available") == STATE_ON
    assert state_of("sensor", "total_active_power") == STATE_UNAVAILABLE


async def test_missing_meter_is_stored_and_not_checked_again(
    entry, mock_modbus_unit, setup_integration, enable_entity, poll, state_of
) -> None:
    """Decide on a missing meter once and ignore later meter readings."""
    enable_entity("sensor", "total_active_power")
    enable_entity("sensor", "charging_energy")
    await setup_integration()

    assert entry.data[CONF_METER_DETECTED] is False

    mock_modbus_unit.holding[VOLTAGE_L1_ADDRESS] = encode_float32(230.0)
    await poll()

    assert entry.data[CONF_METER_DETECTED] is False
    assert state_of("binary_sensor", "meter_available") == STATE_OFF
    assert state_of("sensor", "total_active_power") == STATE_UNAVAILABLE
    assert state_of("sensor", "charging_energy") == STATE_UNAVAILABLE


async def test_meter_check_waits_for_a_successful_read(
    entry, mock_modbus_unit, setup_integration, poll, state_of
) -> None:
    """Leave the meter undecided while its registers cannot be read."""
    mock_modbus_unit.fail_read(VOLTAGE_L1_ADDRESS, IllegalDataAddressError())
    await setup_integration()

    assert state_of("binary_sensor", "meter_available") == STATE_UNKNOWN
    assert CONF_METER_DETECTED not in entry.data

    mock_modbus_unit.fail_read(VOLTAGE_L1_ADDRESS, None)
    mock_modbus_unit.holding[VOLTAGE_L1_ADDRESS] = encode_float32(230.0)
    await poll()

    assert entry.data[CONF_METER_DETECTED] is True
    assert state_of("binary_sensor", "meter_available") == STATE_ON


@pytest.mark.parametrize(
    ("voltage_before", "voltage_after", "detected"),
    [(230.0, 0.0, True), (0.0, 230.0, True), (0.0, 0.0, False)],
)
async def test_meter_check_after_reload(
    hass,
    entry,
    mock_modbus_unit,
    setup_integration,
    state_of,
    voltage_before,
    voltage_after,
    detected,
) -> None:
    """Keep a stored meter and check again once after a reload without one."""
    mock_modbus_unit.holding[VOLTAGE_L1_ADDRESS] = encode_float32(voltage_before)
    await setup_integration()
    mock_modbus_unit.holding[VOLTAGE_L1_ADDRESS] = encode_float32(voltage_after)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.data[CONF_METER_DETECTED] is detected
    assert state_of("binary_sensor", "meter_available") == (
        STATE_ON if detected else STATE_OFF
    )


def _integration_logs(caplog) -> list[tuple[int, str]]:
    return [
        (level, message)
        for logger, level, message in caplog.record_tuples
        if logger.startswith(f"custom_components.{DOMAIN}")
    ]


@pytest.mark.parametrize(
    ("address", "subject"),
    [
        (CHARGING_TAG_INFO_ADDRESS, "Charging session registers are"),
        (VOLTAGE_L1_ADDRESS, "Energy meter registers are"),
        (CHARGING_ENERGY_ADDRESS, "Session energy register is"),
    ],
    ids=["charging_session", "meter", "session_energy"],
)
async def test_optional_block_logs_loss_and_return_once(
    mock_modbus_unit, setup_integration, poll, caplog, address, subject
) -> None:
    """Log a lost optional block once as a warning and its return once as info."""
    caplog.set_level(logging.INFO)
    mock_modbus_unit.holding[VOLTAGE_L1_ADDRESS] = encode_float32(230.0)
    await setup_integration()

    mock_modbus_unit.fail_read(address, ModbusError("connection reset"))
    for _ in range(2):
        await poll()
    mock_modbus_unit.fail_read(address, None)
    for _ in range(2):
        await poll()

    assert _integration_logs(caplog) == [
        (logging.WARNING, f"{subject} no longer available: connection reset"),
        (logging.INFO, f"{subject} available again"),
    ]


@pytest.mark.parametrize(
    ("address", "voltage"),
    [
        (CHARGING_TAG_INFO_ADDRESS, 230.0),
        (VOLTAGE_L1_ADDRESS, 230.0),
        (VOLTAGE_L1_ADDRESS, 0.0),
        (CHARGING_ENERGY_ADDRESS, 230.0),
    ],
    ids=["charging_session", "meter", "meter_not_detected", "session_energy"],
)
async def test_optional_block_first_read_is_not_logged(
    mock_modbus_unit, setup_integration, poll, caplog, address, voltage
) -> None:
    """Log nothing when a block or an undetected meter answers for the first time."""
    caplog.set_level(logging.INFO)
    mock_modbus_unit.holding[VOLTAGE_L1_ADDRESS] = encode_float32(voltage)
    mock_modbus_unit.fail_read(address, ModbusError("connection reset"))
    await setup_integration()

    mock_modbus_unit.fail_read(address, None)
    await poll()

    assert _integration_logs(caplog) == []


def _report_ems_setpoint(unit, timeout_s: int, control: int = 0x8000) -> None:
    """Report a 13 A EMS setpoint with the given timeout and control register."""
    unit.holding[EMS_CONTROL_ADDRESS] = control
    unit.holding[EMS_CHARGING_CURRENT_ADDRESS] = 13000
    unit.holding[EMS_TIMEOUT_PERIOD_ADDRESS] = timeout_s


def _setpoint_writes(unit) -> list[list[int]]:
    return [
        values
        for address, values in unit.writes
        if address == EMS_CHARGING_CURRENT_ADDRESS
    ]


async def _async_advance(hass, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize(
    ("timeout_s", "interval_s"), [(60, 30), (30, 15), (8, 5), (6, 5), (2, 5)]
)
async def test_keep_alive_rewrites_setpoint_within_timeout(
    hass, mock_modbus_unit, setup_integration, timeout_s, interval_s
) -> None:
    """Rewrite the setpoint at half the EMS timeout, but at most every 5 s."""
    _report_ems_setpoint(mock_modbus_unit, timeout_s)
    await setup_integration()
    start = dt_util.utcnow()

    async_fire_time_changed(hass, start + timedelta(seconds=interval_s - 1))
    await hass.async_block_till_done()
    assert _setpoint_writes(mock_modbus_unit) == []

    async_fire_time_changed(hass, start + timedelta(seconds=interval_s + 0.5))
    await hass.async_block_till_done()
    assert _setpoint_writes(mock_modbus_unit) == [[13000]]


@pytest.mark.parametrize("setpoint", [6001, 13500])
async def test_keep_alive_rewrites_setpoint_as_read(
    hass, mock_modbus_unit, setup_integration, setpoint
) -> None:
    """Rewrite exactly the setpoint register value, also between whole amperes."""
    _report_ems_setpoint(mock_modbus_unit, 60)
    mock_modbus_unit.holding[EMS_CHARGING_CURRENT_ADDRESS] = setpoint
    await setup_integration()

    await _async_advance(hass, 31)

    assert _setpoint_writes(mock_modbus_unit) == [[setpoint]]


async def test_keep_alive_stops_without_timeout(
    hass, mock_modbus_unit, setup_integration, poll
) -> None:
    """Write nothing once the Wallbox timeout is set to 0 s."""
    _report_ems_setpoint(mock_modbus_unit, 60)
    await setup_integration()
    mock_modbus_unit.holding[EMS_TIMEOUT_PERIOD_ADDRESS] = 0
    await poll()

    await _async_advance(hass, 31)

    assert _setpoint_writes(mock_modbus_unit) == []


async def test_keep_alive_skips_disabled_ems_control(
    hass, mock_modbus_unit, setup_integration
) -> None:
    """Write nothing while EMS control is off."""
    _report_ems_setpoint(mock_modbus_unit, 60, control=0)
    await setup_integration()

    await _async_advance(hass, 31)

    assert _setpoint_writes(mock_modbus_unit) == []


@pytest.mark.parametrize("allow_control", [False])
async def test_keep_alive_needs_control_allowed(
    hass, mock_modbus_unit, setup_integration
) -> None:
    """Write nothing while the user does not allow control by Home Assistant."""
    _report_ems_setpoint(mock_modbus_unit, 60)
    await setup_integration()

    await _async_advance(hass, 31)

    assert _setpoint_writes(mock_modbus_unit) == []


async def test_keep_alive_survives_write_failure(
    hass, mock_modbus_unit, setup_integration, caplog
) -> None:
    """Log a failed keep-alive write once and keep the timer running."""
    _report_ems_setpoint(mock_modbus_unit, 60)
    await setup_integration()
    mock_modbus_unit.fail_write(
        EMS_CHARGING_CURRENT_ADDRESS, ModbusError("write rejected")
    )

    for seconds in (31, 61):
        await _async_advance(hass, seconds)

    mock_modbus_unit.fail_write(EMS_CHARGING_CURRENT_ADDRESS, None)
    await _async_advance(hass, 91)

    assert caplog.text.count("EMS keep-alive write failed") == 1
    assert _setpoint_writes(mock_modbus_unit) == [[13000]]
