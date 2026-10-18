"""Tests for privacy-safe Wallbox diagnostics."""

import pytest
from modbus_connection import IllegalDataAddressError
from modbus_connection.encode import encode_string
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)


def _holding_addresses(diagnostics) -> set[int]:
    return {int(address) for address in diagnostics["registers"]["holding"]}


async def test_diagnostics_omit_serial_registers(
    hass, hass_client, entry, setup_integration
) -> None:
    """Remove serial-number words from the returned raw register snapshot."""
    await setup_integration()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert "error" not in diagnostics
    holding = _holding_addresses(diagnostics)
    assert set(range(0x0011, 0x0019)).isdisjoint(holding)
    assert 0x001A in holding


async def test_diagnostics_omit_charging_tag_and_session_id(
    hass, hass_client, entry, mock_modbus_unit, setup_integration
) -> None:
    """Keep the authorization tag and session GUID out of the register snapshot."""
    mock_modbus_unit.holding[0x0070] = encode_string("RFID:A07", length=4)
    mock_modbus_unit.holding[0x0088] = encode_string("3659", length=2)
    await setup_integration()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    holding = _holding_addresses(diagnostics)
    assert set(range(0x0070, 0x009A)).isdisjoint(holding)
    assert 0x0060 in holding


@pytest.mark.parametrize(
    ("address", "has_error"),
    [(0x0000, True), (0x0030, False), (0x0069, False)],
)
async def test_diagnostics_isolate_optional_register_failures(
    hass, hass_client, entry, mock_modbus_unit, setup_integration, address, has_error
) -> None:
    """Report essential read failures but tolerate missing optional blocks."""
    await setup_integration()
    mock_modbus_unit.fail_read(address, IllegalDataAddressError())

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert ("error" in diagnostics) is has_error
