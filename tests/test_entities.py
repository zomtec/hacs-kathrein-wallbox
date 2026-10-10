"""Tests for sensor and binary-sensor values."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kathrein_wallbox.binary_sensor import (
    ENTITY_DESCRIPTIONS,
    KathreinBinarySensor,
)
from custom_components.kathrein_wallbox.const import DOMAIN
from custom_components.kathrein_wallbox.coordinator import KathreinCoordinator
from custom_components.kathrein_wallbox.sensor import (
    SENSOR_DESCRIPTIONS,
    KathreinSensor,
)


@pytest.fixture
def coordinator(hass, mock_modbus_unit):
    """Create a coordinator attached to an in-memory config entry."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    return KathreinCoordinator(hass, entry, mock_modbus_unit)


@pytest.mark.parametrize(
    ("key", "address", "value", "component", "expected"),
    [
        ("charging_state", 0x0060, 4, "evse", "charging_active"),
        ("granted_current", 0x0065, 6000, "evse", 6),
        ("charging_current", 0x00A2, 8000, "ems_control", 8),
    ],
)
@pytest.mark.asyncio
async def test_sensor_maps_register_values(
    coordinator, mock_modbus_unit, key, address, value, component, expected
) -> None:
    """Translate charging enums and milliamps to their entity values."""
    mock_modbus_unit.holding[address] = value
    await getattr(coordinator, component).async_update()
    description = next(item for item in SENSOR_DESCRIPTIONS if item.key == key)
    entity = KathreinSensor(coordinator, description)

    assert entity.native_value == expected


@pytest.mark.asyncio
async def test_meter_sensor_is_unavailable_without_optional_meter(coordinator) -> None:
    """Disable meter entities until a plausible meter has been detected."""
    description = next(item for item in SENSOR_DESCRIPTIONS if item.key == "voltage_l1")
    entity = KathreinSensor(coordinator, description)

    assert not entity.available
    assert not entity.entity_registry_enabled_default


@pytest.mark.parametrize(
    ("device_info", "expected"),
    [
        (0x0001, "fixed_cable_mounted"),
        (0x0011, "cable_not_connected"),
    ],
)
@pytest.mark.asyncio
async def test_pp_sensor_uses_identity_to_describe_fixed_cable(
    coordinator, mock_modbus_unit, device_info, expected
) -> None:
    """Resolve the ambiguous PP value using the fixed-cable identity bit."""
    mock_modbus_unit.holding[0x0019] = device_info
    mock_modbus_unit.holding[0x0062] = 0
    await coordinator.identity.async_update()
    await coordinator.evse.async_update()
    description = next(item for item in SENSOR_DESCRIPTIONS if item.key == "pp_state")
    entity = KathreinSensor(coordinator, description)

    assert entity.native_value == expected


@pytest.mark.asyncio
async def test_binary_sensors_decode_fault_relay_and_ems_bits(
    coordinator, mock_modbus_unit
) -> None:
    """Expose fault, relay, and EMS-enabled register bits as booleans."""
    mock_modbus_unit.holding[0x0061] = 0x0001
    mock_modbus_unit.holding[0x0064] = 0x0004
    mock_modbus_unit.holding[0x00A0] = 0x8000
    await coordinator.evse.async_update()
    await coordinator.ems_control.async_update()

    entities = {
        key: KathreinBinarySensor(
            coordinator,
            next(item for item in ENTITY_DESCRIPTIONS if item.key == key),
        )
        for key in ("relay_welded", "relay_l3", "ems_control_enabled")
    }

    assert entities["relay_welded"].is_on is True
    assert entities["relay_l3"].is_on is True
    assert entities["ems_control_enabled"].is_on is True
