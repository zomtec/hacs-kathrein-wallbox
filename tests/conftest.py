"""Shared test fixtures for the Kathrein Wallbox integration."""

import pytest
from modbus_connection.mock import (
    MockModbusConnection,
    MockModbusUnit,
    WriteEvent,
)


class RecordingMockModbusUnit(MockModbusUnit):
    """Mock Modbus unit that retains write events for assertions."""

    def __init__(self, connection: MockModbusConnection, unit_id: int) -> None:
        super().__init__(connection, unit_id)
        self.write_events: list[WriteEvent] = []
        self.on_write(self.write_events.append)


@pytest.fixture
def mock_modbus_unit() -> RecordingMockModbusUnit:
    """Return an in-memory unit with observable holding-register writes."""
    connection = MockModbusConnection()
    return RecordingMockModbusUnit(connection, 1)
