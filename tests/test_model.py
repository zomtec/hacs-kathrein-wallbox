"""Tests for Kathrein Wallbox register decoding."""

from datetime import timedelta

import pytest
from modbus_connection import IllegalDataAddressError

from custom_components.kathrein_wallbox.const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    EXPECTED_MAPPING_VERSION,
    get_scan_interval,
)
from custom_components.kathrein_wallbox.model import (
    WallboxEVSE,
    WallboxIdentity,
    WallboxMeter,
    WallboxSessionEnergy,
)


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_session_energy_decodes_as_big_endian_uint32(mock_modbus_unit) -> None:
    """Read session energy independently from the EVSE state block."""
    mock_modbus_unit.holding[0x0069] = [0x0000, 0x05DC]

    energy = WallboxSessionEnergy(mock_modbus_unit)
    await energy.async_update()

    assert energy.charging_energy == 1500


def test_get_scan_interval_prefers_options_then_data_then_default() -> None:
    """Resolve the polling interval from options, data, or the default."""
    assert get_scan_interval({"options": {CONF_SCAN_INTERVAL: 15}, "data": {CONF_SCAN_INTERVAL: 30}}) == timedelta(seconds=15)
    assert get_scan_interval({"data": {CONF_SCAN_INTERVAL: 30}}) == timedelta(seconds=30)
    assert get_scan_interval({}) == DEFAULT_SCAN_INTERVAL


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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