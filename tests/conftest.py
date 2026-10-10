"""Shared test fixtures for the Kathrein Wallbox integration."""

import pytest
from modbus_connection.mock import (
    MockModbusConnection,
    MockModbusUnit,
    WriteEvent,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kathrein_wallbox.const import DOMAIN
from custom_components.kathrein_wallbox.coordinator import KathreinCoordinator
from custom_components.kathrein_wallbox.model import SERIAL_ADDRESS

SERIAL_REGISTERS = [0x4730, 0x5231, 0x3233, 0x3435, 0x3637, 0, 0, 0]


class RecordingMockModbusUnit(MockModbusUnit):
    """Mock Modbus unit that retains write events for assertions."""

    def __init__(self, connection: MockModbusConnection, unit_id: int) -> None:
        super().__init__(connection, unit_id)
        self.write_events: list[WriteEvent] = []
        self.on_write(self.write_events.append)


@pytest.fixture
def mock_modbus_unit() -> RecordingMockModbusUnit:
    """Return an in-memory unit with a serial number and observable writes."""
    connection = MockModbusConnection()
    unit = RecordingMockModbusUnit(connection, 1)
    unit.holding[SERIAL_ADDRESS] = SERIAL_REGISTERS
    return unit


@pytest.fixture
async def coordinator(hass, mock_modbus_unit) -> KathreinCoordinator:
    """Create a coordinator with a read identity on an in-memory config entry."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    coordinator = KathreinCoordinator(hass, entry, mock_modbus_unit)
    await coordinator.identity.async_update()
    return coordinator
