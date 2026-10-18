"""Tests for Kathrein Wallbox register decoding."""

import logging
from datetime import timedelta

import pytest
from homeassistant.const import CONF_SCAN_INTERVAL
from modbus_connection import IllegalDataAddressError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kathrein_wallbox.const import (
    CONF_ALLOW_CONTROL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EXPECTED_MAPPING_VERSION,
    get_allow_control,
    get_scan_interval,
)
from custom_components.kathrein_wallbox.model import (
    ErrorState,
    RelayState,
    WallboxEMSControl,
    WallboxEVSE,
    WallboxIdentity,
    WallboxMeter,
    WallboxSessionEnergy,
)


async def test_meter_decodes_float32_and_detects_mains_reference(
    mock_modbus_unit,
) -> None:
    """Decode meter floats and require a plausible voltage or frequency."""
    mock_modbus_unit.holding[0x0030] = [0x4366, 0x0000]
    mock_modbus_unit.holding[0x005E] = [0x4248, 0x0000]

    meter = WallboxMeter(mock_modbus_unit)
    await meter.async_update()

    assert meter.voltage_l1 == 230.0
    assert meter.frequency == 50.0
    assert meter.has_plausible_reference


async def test_zero_meter_registers_are_not_reported_as_a_meter(
    mock_modbus_unit,
) -> None:
    """Treat unpopulated zero-filled meter registers as unavailable."""
    mock_modbus_unit.holding[0x0030] = [0] * 18
    mock_modbus_unit.holding[0x0054] = [0] * 2
    mock_modbus_unit.holding[0x005C] = [0] * 4

    meter = WallboxMeter(mock_modbus_unit)
    await meter.async_update()

    assert not meter.has_plausible_reference


async def test_nan_meter_references_are_not_reported_as_a_meter(
    mock_modbus_unit,
) -> None:
    """Treat invalid IEEE-754 reference values as absent meter data."""
    mock_modbus_unit.holding[0x0030] = [0x7FC0, 0x0000]
    mock_modbus_unit.holding[0x005E] = [0x7FC0, 0x0000]

    meter = WallboxMeter(mock_modbus_unit)
    await meter.async_update()

    assert meter.voltage_l1 is None
    assert meter.frequency is None
    assert not meter.has_plausible_reference


async def test_missing_meter_registers_do_not_block_evse_reads(
    mock_modbus_unit,
) -> None:
    """Keep EVSE polling independent when the meter block is rejected."""
    mock_modbus_unit.fail_read(0x0030, IllegalDataAddressError())
    mock_modbus_unit.holding[0x0060] = 4

    with pytest.raises(IllegalDataAddressError):
        await WallboxMeter(mock_modbus_unit).async_update()

    evse = WallboxEVSE(mock_modbus_unit)
    await evse.async_update()

    assert evse.charging_state == 4
    assert evse.charging_duration == 0


async def test_evse_decodes_amperes_and_flag_registers(
    mock_modbus_unit, caplog
) -> None:
    """Decode the granted current in A and keep unmapped fault and relay bits."""
    mock_modbus_unit.holding[0x0061] = 0x8101
    mock_modbus_unit.holding[0x0064] = 0x00F5
    mock_modbus_unit.holding[0x0065] = 6500

    evse = WallboxEVSE(mock_modbus_unit)
    await evse.async_update()

    assert evse.granted_current == 6.5
    assert evse.error_states == 0x8101
    assert ErrorState.RELAY_WELDED in evse.error_states
    assert ErrorState.INTERNAL_ERROR in evse.error_states
    assert ErrorState.RESIDUAL_DC_CURRENT not in evse.error_states
    assert evse.relay_state == 0x00F5
    assert RelayState.RELAY_L3 in evse.relay_state
    assert RelayState.RELAY_L2 not in evse.relay_state
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_ems_control_reads_and_writes_currents_in_amperes(
    mock_modbus_unit,
) -> None:
    """Scale the EMS current setpoints between mA registers and A values."""
    mock_modbus_unit.holding[0x00A2] = 13500
    mock_modbus_unit.holding[0x00A5] = 6000

    ems_control = WallboxEMSControl(mock_modbus_unit)
    await ems_control.async_update()

    assert ems_control.charging_current == 13.5
    assert ems_control.timeout_fallback_current == 6.0

    await ems_control.write("charging_current", ems_control.charging_current)
    await ems_control.write("timeout_fallback_current", 16)

    assert mock_modbus_unit.writes == [(0x00A2, [13500]), (0x00A5, [16000])]


async def test_session_energy_decodes_as_big_endian_uint32(mock_modbus_unit) -> None:
    """Read session energy independently from the EVSE state block."""
    mock_modbus_unit.holding[0x0069] = [0x0000, 0x05DC]

    energy = WallboxSessionEnergy(mock_modbus_unit)
    await energy.async_update()

    assert energy.charging_energy == 1500


@pytest.mark.parametrize(
    ("data", "options", "expected"),
    [
        ({CONF_SCAN_INTERVAL: 30}, {CONF_SCAN_INTERVAL: 15}, timedelta(seconds=15)),
        ({CONF_SCAN_INTERVAL: 30}, {}, DEFAULT_SCAN_INTERVAL),
        ({}, {}, DEFAULT_SCAN_INTERVAL),
    ],
)
def test_get_scan_interval_reads_options_or_default(data, options, expected) -> None:
    """Resolve the polling interval from the options only, else the default."""
    entry = MockConfigEntry(domain=DOMAIN, data=data, options=options)

    assert get_scan_interval(entry) == expected


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({}, False),
        ({CONF_ALLOW_CONTROL: False}, False),
        ({CONF_ALLOW_CONTROL: True}, True),
    ],
)
def test_get_allow_control_is_opt_in(options, expected) -> None:
    """Allow control by Home Assistant only after the user turned it on."""
    entry = MockConfigEntry(domain=DOMAIN, options=options)

    assert get_allow_control(entry) is expected


async def test_identity_reads_mapping_version_and_serial(mock_modbus_unit) -> None:
    """Decode the version and null-terminated serial used by config flow."""
    mock_modbus_unit.holding[0x0000] = EXPECTED_MAPPING_VERSION
    mock_modbus_unit.holding[0x0011] = [
        0x4730,
        0x5231,
        0x3233,
        0x3435,
        0x3637,
        0,
        0,
        0,
    ]

    identity = WallboxIdentity(mock_modbus_unit)
    await identity.async_update()

    assert identity.mapping_version == 0x0002
    assert identity.serial == "G0R1234567"


@pytest.mark.parametrize(
    ("device_info", "is_11_kw", "cable_is_fixed"),
    [
        (0x0001, True, True),
        (0x0011, True, False),
        (0x0101, True, True),
        (0x0002, False, True),
        (0x0012, False, False),
        (0x0102, False, True),
    ],
)
async def test_identity_decodes_device_info(
    mock_modbus_unit, device_info: int, is_11_kw: bool, cable_is_fixed: bool
) -> None:
    """Read power class and fixed-cable state from the device info register."""
    mock_modbus_unit.holding[0x0019] = device_info

    identity = WallboxIdentity(mock_modbus_unit)
    await identity.async_update()

    assert identity.is_11_kw is is_11_kw
    assert identity.cable_is_fixed is cable_is_fixed
