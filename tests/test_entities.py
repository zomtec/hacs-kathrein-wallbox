"""Tests for sensor and binary-sensor values."""

import math

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_HOST,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfElectricCurrent,
    UnitOfTime,
)
from homeassistant.helpers import device_registry as dr, entity_registry as er
from modbus_connection import IllegalDataAddressError
from modbus_connection.encode import encode_float32, encode_string

from custom_components.kathrein_wallbox.const import CONF_METER_DETECTED, DOMAIN

VOLTAGE_L1_ADDRESS = 0x0030
CHARGING_STATE_ADDRESS = 0x0060
SESSION_ID = "36598160-9E55-4B09-1702-7ED324945443"

ENTITY_KEYS = {
    "sensor": {
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
        "charging_tag",
        "charging_session_id",
        "timeout_period",
        "timeout_fallback_relay_matrix",
        "timeout_fallback_current",
    },
    "binary_sensor": {
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
        "ems_control",
        "meter_available",
    },
    "number": {"ems_charging_current"},
    "select": {"ems_relay_matrix"},
}


def _registry_entries(hass, entry) -> list[er.RegistryEntry]:
    return er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


async def test_entity_keys_are_stable(hass, entry, serial, setup_integration) -> None:
    """Keep entity keys unchanged because they are part of the unique IDs."""
    await setup_integration()

    assert {
        (entity.domain, entity.unique_id) for entity in _registry_entries(hass, entry)
    } == {
        (platform, f"{serial}_{key}")
        for platform, keys in ENTITY_KEYS.items()
        for key in keys
    }


def _charging_state_device(hass, entity_id_of) -> dr.DeviceEntry:
    entity = er.async_get(hass).async_get(entity_id_of("sensor", "charging_state"))
    return dr.async_get(hass).async_get(entity.device_id)


async def test_entity_identifies_device_by_serial(
    hass, serial, setup_integration, entity_id_of
) -> None:
    """Derive the unique ID and device identifiers from the serial number."""
    await setup_integration()

    device = _charging_state_device(hass, entity_id_of)
    assert device.identifiers == {(DOMAIN, serial)}
    assert device.serial_number == serial


async def test_device_info_links_device_number_and_web_interface(
    hass, entry, mock_modbus_unit, setup_integration, entity_id_of
) -> None:
    """Expose the device number as model ID and link the web interface."""
    mock_modbus_unit.holding[0x0001] = encode_string("62012345", length=8)
    await setup_integration()

    device = _charging_state_device(hass, entity_id_of)
    assert device.model_id == "62012345"
    assert device.configuration_url == f"http://{entry.data[CONF_HOST]}"


@pytest.mark.parametrize(
    ("key", "address", "value", "expected"),
    [
        ("charging_state", 0x0060, 4, "charging_active"),
        ("charging_state", 0x0060, 99, STATE_UNKNOWN),
        ("cp_state", 0x0063, 2, "state_c"),
        ("granted_current", 0x0065, 6000, "6.0"),
        ("granted_power", 0x0066, 4140, "4140"),
        ("timeout_fallback_current", 0x00A5, 16000, "16.0"),
        ("timeout_period", 0x00A3, 60, "60"),
        ("timeout_fallback_relay_matrix", 0x00A4, 4, "phase_3"),
        ("timeout_fallback_relay_matrix", 0x00A4, 7, "three_phases"),
        ("timeout_fallback_relay_matrix", 0x00A4, 5, STATE_UNKNOWN),
    ],
)
async def test_sensor_maps_register_values(
    mock_modbus_unit,
    setup_integration,
    enable_entity,
    state_of,
    key,
    address,
    value,
    expected,
) -> None:
    """Translate charging enums and milliamps to their entity values."""
    enable_entity("sensor", key)
    mock_modbus_unit.holding[address] = value

    await setup_integration()

    assert state_of("sensor", key) == expected


@pytest.mark.parametrize(
    ("tag_info", "expected"),
    [
        ("RFID:A07E3F27FFE0", "RFID:A07E3F27FFE0"),
        ("RFID:A07E3F27FFE0\x00OLD", "RFID:A07E3F27FFE0"),
        ("VOID", "VOID"),
        ("", STATE_UNKNOWN),
    ],
)
async def test_charging_tag_ends_at_terminator(
    mock_modbus_unit, setup_integration, enable_entity, state_of, tag_info, expected
) -> None:
    """Show the tag up to its 0x00 terminator and unknown without a tag."""
    enable_entity("sensor", "charging_tag")
    mock_modbus_unit.holding[0x0070] = encode_string(tag_info, length=24)

    await setup_integration()

    assert state_of("sensor", "charging_tag") == expected


@pytest.mark.parametrize(
    ("session_id", "expected"), [(SESSION_ID, SESSION_ID), ("", STATE_UNKNOWN)]
)
async def test_charging_session_id_reads_unterminated_guid(
    mock_modbus_unit, setup_integration, enable_entity, state_of, session_id, expected
) -> None:
    """Read all 36 GUID characters, which have no terminator."""
    enable_entity("sensor", "charging_session_id")
    mock_modbus_unit.holding[0x0088] = encode_string(session_id, length=18)

    await setup_integration()

    assert state_of("sensor", "charging_session_id") == expected


async def test_detail_entities_are_disabled_by_default(
    hass, entry, serial, mock_modbus_unit, setup_integration
) -> None:
    """Enable only the main charging and meter entities for new installations."""
    # With a detected meter only the detail entities stay disabled.
    mock_modbus_unit.holding[VOLTAGE_L1_ADDRESS] = encode_float32(230.0)

    await setup_integration()

    disabled = {
        entity.unique_id.removeprefix(f"{serial}_")
        for entity in _registry_entries(hass, entry)
        if entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    }
    assert disabled == {
        *(
            f"{q}_l{p}"
            for q in ("voltage", "current", "active_power")
            for p in (1, 2, 3)
        ),
        "frequency",
        "pp_state",
        "cp_state",
        "relay_l1",
        "relay_l2",
        "relay_l3",
        "timeout_period",
        "timeout_fallback_relay_matrix",
        "timeout_fallback_current",
        "relay_welded",
        "residual_dc_current",
        "socket_lock_error",
        "charging_overcurrent",
        "ventilation_unavailable",
        "cp_short_circuit",
        "cp_loop_broken",
        "pp_short_circuit",
        "internal_error",
        "charging_tag",
        "charging_session_id",
    }


@pytest.mark.parametrize("key", ["granted_current", "granted_power"])
async def test_granted_charging_sensors_are_not_diagnostic(
    hass, setup_integration, entity_id_of, key
) -> None:
    """List granted charging current and power with the regular sensors."""
    await setup_integration()

    entity = er.async_get(hass).async_get(entity_id_of("sensor", key))
    assert entity.entity_category is None


@pytest.mark.parametrize(
    ("key", "device_class", "unit"),
    [
        ("granted_current", SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE),
        (
            "timeout_fallback_current",
            SensorDeviceClass.CURRENT,
            UnitOfElectricCurrent.AMPERE,
        ),
        ("timeout_period", SensorDeviceClass.DURATION, UnitOfTime.SECONDS),
    ],
)
async def test_current_and_timeout_sensors_have_device_class(
    hass, setup_integration, enable_entity, entity_id_of, key, device_class, unit
) -> None:
    """Classify currents and the EMS timeout, shown in whole amperes and seconds."""
    enable_entity("sensor", key)

    await setup_integration()

    entity_id = entity_id_of("sensor", key)
    attributes = hass.states.get(entity_id).attributes
    assert attributes[ATTR_DEVICE_CLASS] == device_class
    assert attributes[ATTR_UNIT_OF_MEASUREMENT] == unit
    sensor_options = er.async_get(hass).async_get(entity_id).options["sensor"]
    assert sensor_options["suggested_display_precision"] == 0


async def test_meter_sensor_is_unavailable_without_optional_meter(
    hass, setup_integration, enable_entity, entity_id_of, state_of
) -> None:
    """Disable meter entities until a plausible meter has been detected."""
    enable_entity("sensor", "voltage_l1")

    await setup_integration()

    assert state_of("sensor", "voltage_l1") == STATE_UNAVAILABLE
    entity = er.async_get(hass).async_get(entity_id_of("sensor", "total_active_power"))
    assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_meter_sensor_is_enabled_once_a_meter_is_detected(
    hass, mock_modbus_unit, setup_integration, entity_id_of
) -> None:
    """Enable meter entities once a plausible meter has been detected."""
    mock_modbus_unit.holding[VOLTAGE_L1_ADDRESS] = encode_float32(230.0)

    await setup_integration()

    entity = er.async_get(hass).async_get(entity_id_of("sensor", "total_active_power"))
    assert entity.disabled_by is None


@pytest.mark.parametrize(
    ("key", "address", "value", "expected"),
    [
        ("voltage_l1", 0x0030, 230.0, "230.0"),
        ("voltage_l1", 0x0030, 1000.0, STATE_UNKNOWN),
        ("voltage_l1", 0x0030, math.nan, STATE_UNKNOWN),
        ("frequency", 0x005E, 50.0, "50.0"),
        ("frequency", 0x005E, 230.0, STATE_UNKNOWN),
        ("current_l1", 0x0036, math.nan, STATE_UNKNOWN),
        ("total_active_power", 0x0054, 1000.0, "1000.0"),
    ],
)
async def test_meter_sensors_reject_implausible_values(
    mock_modbus_unit,
    setup_integration,
    enable_entity,
    state_of,
    key,
    address,
    value,
    expected,
) -> None:
    """Report mains readings only when finite and within the plausible range."""
    enable_entity("sensor", key)
    # A plausible L2 voltage lets the meter be detected whatever the tested value.
    mock_modbus_unit.holding[0x0032] = encode_float32(230.0)
    mock_modbus_unit.holding[address] = encode_float32(value)

    await setup_integration()

    assert state_of("sensor", key) == expected


@pytest.mark.parametrize(
    ("device_info", "expected"),
    [
        (0x0001, "fixed_cable_mounted"),
        (0x0011, "cable_not_connected"),
    ],
)
async def test_pp_sensor_uses_identity_to_describe_fixed_cable(
    mock_modbus_unit, setup_integration, enable_entity, state_of, device_info, expected
) -> None:
    """Resolve the ambiguous PP value using the fixed-cable identity bit."""
    enable_entity("sensor", "pp_state")
    mock_modbus_unit.holding[0x0019] = device_info
    mock_modbus_unit.holding[0x0062] = 0

    await setup_integration()

    assert state_of("sensor", "pp_state") == expected


async def test_total_energy_stays_available_across_communication_gaps(
    mock_modbus_unit, setup_integration, poll, state_of
) -> None:
    """Keep total energy through a failed poll, but not once the meter is lost."""
    mock_modbus_unit.holding[VOLTAGE_L1_ADDRESS] = encode_float32(230.0)
    mock_modbus_unit.holding[0x005C] = encode_float32(1000.0)
    await setup_integration()

    assert state_of("sensor", "total_energy") == "1000.0"

    mock_modbus_unit.fail_read(CHARGING_STATE_ADDRESS, IllegalDataAddressError())
    await poll()

    assert state_of("sensor", "charging_state") == STATE_UNAVAILABLE
    assert state_of("sensor", "total_energy") == "1000.0"

    mock_modbus_unit.fail_read(CHARGING_STATE_ADDRESS, None)
    mock_modbus_unit.fail_read(VOLTAGE_L1_ADDRESS, IllegalDataAddressError())
    await poll()

    assert state_of("sensor", "total_energy") == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("stored", "meter_error", "expected"),
    [
        ({CONF_METER_DETECTED: True}, IllegalDataAddressError(), STATE_ON),
        ({}, None, STATE_OFF),
        ({}, IllegalDataAddressError(), STATE_UNKNOWN),
    ],
    ids=["detected", "not_detected", "undecided"],
)
async def test_meter_binary_sensor_reports_stored_detection(
    hass,
    entry,
    mock_modbus_unit,
    setup_integration,
    state_of,
    stored,
    meter_error,
    expected,
) -> None:
    """Report the one-time meter detection, not the latest meter reading."""
    hass.config_entries.async_update_entry(entry, data={**entry.data, **stored})
    mock_modbus_unit.fail_read(VOLTAGE_L1_ADDRESS, meter_error)

    await setup_integration()

    assert state_of("binary_sensor", "meter_available") == expected


async def test_binary_sensors_decode_fault_and_relay_bits(
    mock_modbus_unit, setup_integration, enable_entity, state_of
) -> None:
    """Expose fault and relay register bits as booleans."""
    for key in ("relay_welded", "internal_error", "relay_l3", "relay_l1"):
        enable_entity("binary_sensor", key)
    mock_modbus_unit.holding[0x0061] = 0x0001
    mock_modbus_unit.holding[0x0064] = 0x0004

    await setup_integration()

    assert state_of("binary_sensor", "relay_welded") == STATE_ON
    assert state_of("binary_sensor", "internal_error") == STATE_OFF
    assert state_of("binary_sensor", "relay_l3") == STATE_ON
    assert state_of("binary_sensor", "relay_l1") == STATE_OFF


@pytest.mark.parametrize("allow_control", [False])
@pytest.mark.parametrize(("register", "expected"), [(0x8000, STATE_ON), (0, STATE_OFF)])
async def test_ems_control_binary_sensor_reads_control_bit(
    mock_modbus_unit, setup_integration, state_of, register, expected
) -> None:
    """Report EMS control from bit 15 of the control register, even read-only."""
    mock_modbus_unit.holding[0x00A0] = register

    await setup_integration()

    assert state_of("binary_sensor", "ems_control") == expected
