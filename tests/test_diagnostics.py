"""Tests for privacy-safe Wallbox diagnostics."""

from types import SimpleNamespace

import pytest
from modbus_connection import IllegalDataAddressError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kathrein_wallbox.const import DOMAIN
from custom_components.kathrein_wallbox.coordinator import KathreinCoordinator
from custom_components.kathrein_wallbox.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.mark.asyncio
async def test_diagnostics_omit_serial_registers(hass, mock_modbus_unit) -> None:
    """Remove serial-number words from the returned raw register snapshot."""
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
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        coordinator=KathreinCoordinator(hass, entry, mock_modbus_unit)
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert "error" not in diagnostics
    holding = diagnostics["registers"]["holding"]
    assert set(range(0x0011, 0x0019)).isdisjoint(holding)


@pytest.mark.parametrize(
    ("address", "has_error"),
    [(0x0000, True), (0x0030, False), (0x0069, False)],
)
@pytest.mark.asyncio
async def test_diagnostics_isolate_optional_register_failures(
    hass, mock_modbus_unit, address, has_error
) -> None:
    """Report essential read failures but tolerate missing optional blocks."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        coordinator=KathreinCoordinator(hass, entry, mock_modbus_unit)
    )
    mock_modbus_unit.fail_read(address, IllegalDataAddressError())

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert ("error" in diagnostics) is has_error
