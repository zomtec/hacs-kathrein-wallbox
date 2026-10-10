"""Tests for sensor and binary-sensor values."""

import pytest
from homeassistant.const import STATE_UNKNOWN

from custom_components.kathrein_wallbox.binary_sensor import (
    ENTITY_DESCRIPTIONS,
    KathreinBinarySensor,
)
from custom_components.kathrein_wallbox.sensor import (
    SENSOR_DESCRIPTIONS,
    KathreinRestoredSensor,
    KathreinSensor,
)

SERIAL = "G0R1234567"
FLOAT_230 = [0x4366, 0x0000]
FLOAT_50 = [0x4248, 0x0000]
FLOAT_NAN = [0x7FC0, 0x0000]
FLOAT_1000 = [0x447A, 0x0000]


def _sensor(coordinator, key) -> KathreinSensor:
    description = next(item for item in SENSOR_DESCRIPTIONS if item.key == key)
    return KathreinSensor(coordinator, description)


def _binary_sensor(coordinator, key) -> KathreinBinarySensor:
    description = next(item for item in ENTITY_DESCRIPTIONS if item.key == key)
    return KathreinBinarySensor(coordinator, description)


def test_entity_keys_are_stable() -> None:
    """Keep entity keys unchanged because they are part of the unique IDs."""
    assert {item.key for item in SENSOR_DESCRIPTIONS} == {
        "voltage_l1",
        "voltage_l2",
        "voltage_l3",
        "current_l1",
        "current_l2",
        "current_l3",
        "active_power_l1",
        "active_power_l2",
        "active_power_l3",
        "total_active_power",
        "total_energy",
        "frequency",
        "charging_state",
        "pp_state",
        "cp_state",
        "granted_current",
        "granted_power",
        "charging_duration",
        "charging_energy",
        "relay_matrix",
        "charging_current",
        "timeout_period",
        "timeout_fallback_relay_matrix",
        "timeout_fallback_current",
    }
    assert {item.key for item in ENTITY_DESCRIPTIONS} == {
        "relay_welded",
        "residual_dc_current",
        "socket_lock_error",
        "charging_overcurrent",
        "ventilation_unavailable",
        "cp_short_circuit",
        "cp_loop_broken",
        "pp_short_circuit",
        "internal_error",
        "relay_l1",
        "relay_l2",
        "relay_l3",
        "ems_control_enabled",
        "meter_available",
    }


async def test_entity_identifies_device_by_serial(coordinator) -> None:
    """Derive the unique ID and device identifiers from the serial number."""
    entity = _sensor(coordinator, "charging_state")

    assert entity.unique_id == f"{SERIAL}_charging_state"
    assert entity.device_info["serial_number"] == SERIAL
    assert {identifier[1] for identifier in entity.device_info["identifiers"]} == {
        SERIAL
    }


@pytest.mark.parametrize(
    ("key", "address", "value", "component", "expected"),
    [
        ("charging_state", 0x0060, 4, "evse", "charging_active"),
        ("charging_state", 0x0060, 99, "evse", STATE_UNKNOWN),
        ("cp_state", 0x0063, 2, "evse", "state_c"),
        ("granted_current", 0x0065, 6000, "evse", 6),
        ("granted_power", 0x0066, 4140, "evse", 4140),
        ("charging_current", 0x00A2, 8000, "ems_control", 8),
        ("timeout_fallback_current", 0x00A5, 16000, "ems_control", 16),
        ("timeout_period", 0x00A3, 60, "ems_control", 60),
        ("relay_matrix", 0x00A1, 1, "ems_control", "phase_1"),
        ("relay_matrix", 0x00A1, 7, "ems_control", "three_phases"),
        ("timeout_fallback_relay_matrix", 0x00A4, 4, "ems_control", "phase_3"),
        ("relay_matrix", 0x00A1, 5, "ems_control", STATE_UNKNOWN),
    ],
)
async def test_sensor_maps_register_values(
    coordinator, mock_modbus_unit, key, address, value, component, expected
) -> None:
    """Translate charging enums and milliamps to their entity values."""
    mock_modbus_unit.holding[address] = value
    await getattr(coordinator, component).async_update()

    assert _sensor(coordinator, key).native_value == expected


async def test_meter_sensor_is_unavailable_without_optional_meter(coordinator) -> None:
    """Disable meter entities until a plausible meter has been detected."""
    entity = _sensor(coordinator, "voltage_l1")

    assert not entity.available
    assert not entity.entity_registry_enabled_default


async def test_meter_sensor_is_enabled_once_a_meter_is_detected(coordinator) -> None:
    """Enable meter entities when the coordinator detected a plausible meter."""
    coordinator.meter_available = True
    entity = _sensor(coordinator, "voltage_l1")

    assert entity.entity_registry_enabled_default


@pytest.mark.parametrize(
    ("key", "address", "raw", "expected"),
    [
        ("voltage_l1", 0x0030, FLOAT_230, 230.0),
        ("voltage_l1", 0x0030, FLOAT_1000, None),
        ("voltage_l1", 0x0030, FLOAT_NAN, None),
        ("frequency", 0x005E, FLOAT_50, 50.0),
        ("frequency", 0x005E, FLOAT_230, None),
        ("current_l1", 0x0036, FLOAT_NAN, None),
        ("total_active_power", 0x0054, FLOAT_1000, 1000.0),
    ],
)
async def test_meter_sensors_reject_implausible_values(
    coordinator, mock_modbus_unit, key, address, raw, expected
) -> None:
    """Report mains readings only when finite and within the plausible range."""
    mock_modbus_unit.holding[address] = raw
    await coordinator.meter.async_update()

    assert _sensor(coordinator, key).native_value == expected


@pytest.mark.parametrize(
    ("device_info", "expected"),
    [
        (0x0001, "fixed_cable_mounted"),
        (0x0011, "cable_not_connected"),
    ],
)
async def test_pp_sensor_uses_identity_to_describe_fixed_cable(
    coordinator, mock_modbus_unit, device_info, expected
) -> None:
    """Resolve the ambiguous PP value using the fixed-cable identity bit."""
    mock_modbus_unit.holding[0x0019] = device_info
    mock_modbus_unit.holding[0x0062] = 0
    await coordinator.identity.async_update()
    await coordinator.evse.async_update()

    assert _sensor(coordinator, "pp_state").native_value == expected


async def test_restored_sensor_stays_available_across_meter_gaps(
    coordinator, mock_modbus_unit
) -> None:
    """Keep the last total energy value when the meter stops answering."""
    mock_modbus_unit.holding[0x005C] = [0x4366, 0x0000]
    await coordinator.meter.async_update()
    coordinator.meter_available = True
    description = next(i for i in SENSOR_DESCRIPTIONS if i.key == "total_energy")
    entity = KathreinRestoredSensor(coordinator, description)

    assert entity.available
    assert entity.native_value == 230.0

    coordinator.meter_available = False
    assert not entity.available


async def test_binary_sensors_decode_fault_relay_and_ems_bits(
    coordinator, mock_modbus_unit
) -> None:
    """Expose fault, relay, and EMS-enabled register bits as booleans."""
    mock_modbus_unit.holding[0x0061] = 0x0001
    mock_modbus_unit.holding[0x0064] = 0x0004
    mock_modbus_unit.holding[0x00A0] = 0x8000
    await coordinator.evse.async_update()
    await coordinator.ems_control.async_update()

    assert _binary_sensor(coordinator, "relay_welded").is_on is True
    assert _binary_sensor(coordinator, "internal_error").is_on is False
    assert _binary_sensor(coordinator, "relay_l3").is_on is True
    assert _binary_sensor(coordinator, "relay_l1").is_on is False
    assert _binary_sensor(coordinator, "ems_control_enabled").is_on is True
