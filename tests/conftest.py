"""Shared test fixtures for the Kathrein Wallbox integration."""

from collections.abc import Awaitable, Callable
from unittest.mock import Mock

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from modbus_connection.encode import encode_string
from modbus_connection.mock import (
    MockModbusConnection,
    MockModbusUnit,
    WriteEvent,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.kathrein_wallbox.const import (
    CONF_ALLOW_CONTROL,
    CONF_UNIT_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from custom_components.kathrein_wallbox.model import (
    SERIAL_ADDRESS,
    SERIAL_REGISTER_COUNT,
)

HOST = "192.0.2.10"
SERIAL = "G0R1234567"


class RecordingMockModbusUnit(MockModbusUnit):
    """Mock Modbus unit that records successful writes for assertions."""

    def __init__(self, connection: MockModbusConnection, unit_id: int) -> None:
        super().__init__(connection, unit_id)
        self.writes: list[tuple[int, list[int] | list[bool]]] = []
        self.on_write(self._record_write)

    def _record_write(self, event: WriteEvent) -> None:
        self.writes.append((event.address, event.values))


@pytest.fixture
def serial() -> str:
    """Return the serial number the mock Wallbox reports."""
    return SERIAL


@pytest.fixture
def mock_modbus_unit(serial: str) -> RecordingMockModbusUnit:
    """Return an in-memory Wallbox with a serial number and observable writes."""
    unit = RecordingMockModbusUnit(MockModbusConnection(), 1)
    unit.holding[SERIAL_ADDRESS] = encode_string(serial, length=SERIAL_REGISTER_COUNT)
    return unit


@pytest.fixture
def allow_control() -> bool:
    """Allow control by Home Assistant unless a test overrides this fixture."""
    return True


@pytest.fixture
def entry(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    mock_modbus_unit: RecordingMockModbusUnit,
    serial: str,
    allow_control: bool,
    enable_custom_integrations: None,
) -> MockConfigEntry:
    """Add a Wallbox entry that talks to the in-memory unit."""
    monkeypatch.setattr(
        "custom_components.kathrein_wallbox.async_get_unit",
        Mock(return_value=mock_modbus_unit),
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=serial,
        title="Garage",
        data={CONF_HOST: HOST, CONF_PORT: 502, CONF_UNIT_ID: 0},
        options={CONF_ALLOW_CONTROL: allow_control},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def setup_integration(
    hass: HomeAssistant, entry: MockConfigEntry
) -> Callable[[], Awaitable[None]]:
    """Return a function that sets up the Wallbox entry with the current registers."""

    async def _async_setup_integration() -> None:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return _async_setup_integration


@pytest.fixture
def poll(hass: HomeAssistant) -> Callable[[], Awaitable[None]]:
    """Return a function that lets one default polling interval pass."""

    async def _async_poll() -> None:
        async_fire_time_changed(hass, dt_util.utcnow() + DEFAULT_SCAN_INTERVAL)
        await hass.async_block_till_done(wait_background_tasks=True)

    return _async_poll


@pytest.fixture
def entity_id_of(hass: HomeAssistant, serial: str) -> Callable[[str, str], str]:
    """Return a function that looks up a Wallbox entity ID by platform and key."""
    registry = er.async_get(hass)

    def _entity_id_of(platform: str, key: str) -> str:
        entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{serial}_{key}")
        assert entity_id is not None, key
        return entity_id

    return _entity_id_of


@pytest.fixture
def state_of(
    hass: HomeAssistant, entity_id_of: Callable[[str, str], str]
) -> Callable[[str, str], str]:
    """Return a function that reads the state of a Wallbox entity."""

    def _state_of(platform: str, key: str) -> str:
        state = hass.states.get(entity_id_of(platform, key))
        assert state is not None, key
        return state.state

    return _state_of


@pytest.fixture
def enable_entity(
    hass: HomeAssistant, entry: MockConfigEntry, serial: str
) -> Callable[[str, str], None]:
    """Return a function that enables a Wallbox entity before the first setup."""
    registry = er.async_get(hass)

    def _enable_entity(platform: str, key: str) -> None:
        registry.async_get_or_create(
            platform, DOMAIN, f"{serial}_{key}", config_entry=entry
        )

    return _enable_entity
