"""Tests for the Kathrein Wallbox EMS services."""

from types import SimpleNamespace

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.exceptions import HomeAssistantError

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


@pytest.fixture
def ems_entry(hass, mock_modbus_unit):
    """Add a config entry connected to the in-memory unit."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        coordinator=SimpleNamespace(
            unit=mock_modbus_unit,
            identity=SimpleNamespace(is_11_kw=False),
        )
    )
    return entry


@pytest.mark.parametrize(
    ("service", "service_data", "address", "value"),
    [
        (SERVICE_SET_EMS_CONTROL_ENABLED, {"enabled": True}, 0x00A0, 0x8000),
        (SERVICE_SET_EMS_CONTROL_ENABLED, {"enabled": False}, 0x00A0, 0),
        (SERVICE_SET_RELAY_MATRIX, {"value": "line_1"}, 0x00A1, 1),
        (SERVICE_SET_CHARGING_CURRENT, {"value": "20"}, 0x00A2, 20000),
        (SERVICE_SET_TIMEOUT_PERIOD, {"value": "60"}, 0x00A3, 60),
        (
            SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX,
            {"value": "three_lines"},
            0x00A4,
            7,
        ),
        (
            SERVICE_SET_TIMEOUT_FALLBACK_CURRENT,
            {"value": "0"},
            0x00A5,
            0,
        ),
    ],
)
@pytest.mark.asyncio
async def test_ems_services_write_expected_register(
    hass, mock_modbus_unit, ems_entry, service, service_data, address, value
) -> None:
    """Write each supported EMS command to its documented register."""
    await async_setup(hass, {})

    await hass.services.async_call(
        DOMAIN,
        service,
        {"entry_id": ems_entry.entry_id, **service_data},
        blocking=True,
    )

    assert [(event.address, event.values) for event in mock_modbus_unit.write_events] == [
        (address, [value])
    ]


@pytest.mark.parametrize(
    ("service", "value", "address"),
    [
        (SERVICE_SET_CHARGING_CURRENT, "16", 0x00A2),
        (SERVICE_SET_TIMEOUT_FALLBACK_CURRENT, "16", 0x00A5),
    ],
)
@pytest.mark.asyncio
async def test_11_kw_wallbox_accepts_maximum_ems_current(
    hass, mock_modbus_unit, ems_entry, service, value, address
) -> None:
    """Allow exactly 16 A on an 11 kW wallbox."""
    ems_entry.runtime_data.coordinator.identity.is_11_kw = True
    await async_setup(hass, {})

    await hass.services.async_call(
        DOMAIN,
        service,
        {"entry_id": ems_entry.entry_id, "value": value},
        blocking=True,
    )

    assert [(event.address, event.values) for event in mock_modbus_unit.write_events] == [
        (address, [16000])
    ]


@pytest.mark.parametrize(
    ("service", "value"),
    [
        (SERVICE_SET_CHARGING_CURRENT, "20"),
        (SERVICE_SET_TIMEOUT_FALLBACK_CURRENT, "20"),
    ],
)
@pytest.mark.asyncio
async def test_11_kw_wallbox_rejects_ems_current_above_limit(
    hass, mock_modbus_unit, ems_entry, service, value
) -> None:
    """Reject current values above 16 A without writing a register."""
    ems_entry.runtime_data.coordinator.identity.is_11_kw = True
    await async_setup(hass, {})

    with pytest.raises(HomeAssistantError, match="maximum EMS charging current"):
        await hass.services.async_call(
            DOMAIN,
            service,
            {"entry_id": ems_entry.entry_id, "value": value},
            blocking=True,
        )

    assert mock_modbus_unit.write_events == []


@pytest.mark.asyncio
async def test_ems_service_rejects_unknown_config_entry(
    hass, mock_modbus_unit, ems_entry
) -> None:
    """Reject service calls that do not refer to a wallbox entry."""
    await async_setup(hass, {})

    with pytest.raises(HomeAssistantError, match="No Kathrein Wallbox config entry"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_RELAY_MATRIX,
            {"entry_id": "missing-entry", "value": "line_1"},
            blocking=True,
        )

    assert mock_modbus_unit.write_events == []