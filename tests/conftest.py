"""Shared test fixtures for the Kathrein Wallbox integration."""

from collections.abc import AsyncGenerator

import pytest
from homeassistant.const import CONF_HOST
from modbus_connection.mock import (
    MockModbusConnection,
    MockModbusUnit,
    WriteEvent,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kathrein_wallbox.const import CONF_ALLOW_CONTROL, DOMAIN
from custom_components.kathrein_wallbox.coordinator import KathreinCoordinator
from custom_components.kathrein_wallbox.model import SERIAL_ADDRESS

HOST = "192.0.2.10"
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


async def _async_coordinator(
    hass, unit, allow_control: bool
) -> AsyncGenerator[KathreinCoordinator]:
    """Create a coordinator with a read identity on an in-memory config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST},
        options={CONF_ALLOW_CONTROL: allow_control},
    )
    entry.add_to_hass(hass)
    coordinator = KathreinCoordinator(hass, entry, unit)
    await coordinator._async_setup()
    yield coordinator
    # Stop the poll and keep-alive timers so they do not outlive the test.
    await coordinator.async_shutdown()


@pytest.fixture
async def coordinator(hass, mock_modbus_unit) -> AsyncGenerator[KathreinCoordinator]:
    """Create a coordinator that may write to the Wallbox."""
    async for coordinator in _async_coordinator(hass, mock_modbus_unit, True):
        yield coordinator


@pytest.fixture
async def read_only_coordinator(
    hass, mock_modbus_unit
) -> AsyncGenerator[KathreinCoordinator]:
    """Create a coordinator whose user did not allow control by Home Assistant."""
    async for coordinator in _async_coordinator(hass, mock_modbus_unit, False):
        yield coordinator
