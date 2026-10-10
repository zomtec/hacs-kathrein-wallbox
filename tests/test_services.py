"""Tests for the Kathrein Wallbox EMS services."""

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from modbus_connection import ModbusError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kathrein_wallbox import (
    SERVICE_SET_CHARGING_CURRENT,
    SERVICE_SET_EMS_CONTROL_ENABLED,
    SERVICE_SET_RELAY_MATRIX,
    SERVICE_SET_TIMEOUT_FALLBACK_CURRENT,
    SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX,
    SERVICE_SET_TIMEOUT_PERIOD,
    async_setup,
)
from custom_components.kathrein_wallbox.const import DOMAIN
from custom_components.kathrein_wallbox.coordinator import (
    KathreinCoordinator,
    WallboxRuntimeData,
)

DEVICE_INFO_ADDRESS = 0x0019
DEVICE_INFO_11_KW = 0x0001


@pytest.fixture
async def ems_entry(hass, mock_modbus_unit) -> MockConfigEntry:
    """Add a loaded config entry connected to the in-memory unit."""
    entry = MockConfigEntry(domain=DOMAIN, title="Wallbox")
    entry.add_to_hass(hass)
    coordinator = KathreinCoordinator(hass, entry, mock_modbus_unit)
    await coordinator.identity.async_update()
    entry.runtime_data = WallboxRuntimeData(coordinator=coordinator)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    await async_setup(hass, {})
    return entry


async def _async_call(hass, entry, service, service_data) -> None:
    """Call a Wallbox service for the given config entry."""
    await hass.services.async_call(
        DOMAIN,
        service,
        {"entry_id": entry.entry_id, **service_data},
        blocking=True,
    )


@pytest.mark.parametrize(
    ("service", "service_data", "address", "value"),
    [
        (SERVICE_SET_EMS_CONTROL_ENABLED, {"enabled": True}, 0x00A0, 0x8000),
        (SERVICE_SET_EMS_CONTROL_ENABLED, {"enabled": False}, 0x00A0, 0),
        (SERVICE_SET_RELAY_MATRIX, {"value": "phase_1"}, 0x00A1, 1),
        (SERVICE_SET_RELAY_MATRIX, {"value": "three_phases"}, 0x00A1, 7),
        (SERVICE_SET_CHARGING_CURRENT, {"value": "20"}, 0x00A2, 20000),
        (SERVICE_SET_CHARGING_CURRENT, {"value": "0"}, 0x00A2, 0),
        (SERVICE_SET_TIMEOUT_PERIOD, {"value": "60"}, 0x00A3, 60),
        (
            SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX,
            {"value": "three_phases"},
            0x00A4,
            7,
        ),
        (SERVICE_SET_TIMEOUT_FALLBACK_CURRENT, {"value": "0"}, 0x00A5, 0),
    ],
)
async def test_ems_services_write_expected_register(
    hass, mock_modbus_unit, ems_entry, service, service_data, address, value
) -> None:
    """Write each supported EMS command to its documented register."""
    await _async_call(hass, ems_entry, service, service_data)

    assert [
        (event.address, event.values) for event in mock_modbus_unit.write_events
    ] == [(address, [value])]


@pytest.mark.parametrize(
    ("service", "value"),
    [
        (SERVICE_SET_RELAY_MATRIX, "line_1"),
        (SERVICE_SET_RELAY_MATRIX, "phase_2"),
        (SERVICE_SET_RELAY_MATRIX, "three_lines"),
        (SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX, "phase_3"),
        (SERVICE_SET_CHARGING_CURRENT, "17"),
        (SERVICE_SET_TIMEOUT_PERIOD, "45"),
        (SERVICE_SET_TIMEOUT_FALLBACK_CURRENT, "40"),
    ],
)
async def test_ems_services_reject_unsupported_values(
    hass, mock_modbus_unit, ems_entry, service, value
) -> None:
    """Reject values the Wallbox does not support before writing anything."""
    with pytest.raises(vol.Invalid):
        await _async_call(hass, ems_entry, service, {"value": value})

    assert mock_modbus_unit.write_events == []


@pytest.mark.parametrize(
    ("service", "value", "address"),
    [
        (SERVICE_SET_CHARGING_CURRENT, "16", 0x00A2),
        (SERVICE_SET_TIMEOUT_FALLBACK_CURRENT, "16", 0x00A5),
    ],
)
async def test_11_kw_wallbox_accepts_maximum_ems_current(
    hass, mock_modbus_unit, ems_entry, service, value, address
) -> None:
    """Allow exactly 16 A on an 11 kW wallbox."""
    mock_modbus_unit.holding[DEVICE_INFO_ADDRESS] = DEVICE_INFO_11_KW
    await ems_entry.runtime_data.coordinator.identity.async_update()

    await _async_call(hass, ems_entry, service, {"value": value})

    assert [
        (event.address, event.values) for event in mock_modbus_unit.write_events
    ] == [(address, [16000])]


@pytest.mark.parametrize(
    "service", [SERVICE_SET_CHARGING_CURRENT, SERVICE_SET_TIMEOUT_FALLBACK_CURRENT]
)
async def test_11_kw_wallbox_rejects_ems_current_above_limit(
    hass, mock_modbus_unit, ems_entry, service
) -> None:
    """Reject current values above 16 A without writing a register."""
    mock_modbus_unit.holding[DEVICE_INFO_ADDRESS] = DEVICE_INFO_11_KW
    await ems_entry.runtime_data.coordinator.identity.async_update()

    with pytest.raises(ServiceValidationError) as error:
        await _async_call(hass, ems_entry, service, {"value": "20"})

    assert error.value.translation_key == "current_limit_11_kw"
    assert mock_modbus_unit.write_events == []


async def test_ems_service_rejects_unknown_config_entry(
    hass, mock_modbus_unit, ems_entry
) -> None:
    """Reject service calls that do not refer to a wallbox entry."""
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_RELAY_MATRIX,
            {"entry_id": "missing-entry", "value": "phase_1"},
            blocking=True,
        )

    assert error.value.translation_key == "entry_not_found"
    assert mock_modbus_unit.write_events == []


async def test_ems_service_rejects_entry_that_is_not_loaded(
    hass, mock_modbus_unit, ems_entry
) -> None:
    """Reject service calls for a wallbox entry that failed to set up."""
    ems_entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)

    with pytest.raises(ServiceValidationError) as error:
        await _async_call(
            hass, ems_entry, SERVICE_SET_RELAY_MATRIX, {"value": "phase_1"}
        )

    assert error.value.translation_key == "entry_not_loaded"
    assert mock_modbus_unit.write_events == []


async def test_ems_service_reports_device_write_failure(
    hass, mock_modbus_unit, ems_entry
) -> None:
    """Surface a failed register write as a Home Assistant error."""
    mock_modbus_unit.fail_write(0x00A1, ModbusError("write rejected"))

    with pytest.raises(HomeAssistantError) as error:
        await _async_call(
            hass, ems_entry, SERVICE_SET_RELAY_MATRIX, {"value": "phase_1"}
        )

    assert error.value.translation_key == "write_failed"
