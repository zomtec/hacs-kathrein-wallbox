"""Tests for the Kathrein Wallbox config flow."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.exceptions import HomeAssistantError
from modbus_connection import ModbusError

from custom_components.kathrein_wallbox import config_flow
from custom_components.kathrein_wallbox.const import DOMAIN


@pytest.mark.asyncio
async def test_user_flow_creates_entry_with_normalized_connection_data(
    hass, monkeypatch, enable_custom_integrations
) -> None:
    """Normalize selector values after validating and identifying the device."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(return_value=("SERIAL123", "Kathrein 11 kW")),
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "wallbox.local",
            "port": 502.0,
            "unit_id": 1.0,
            "scan_interval": 20.0,
        },
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "Kathrein 11 kW"
    assert result["data"] == {
        "host": "wallbox.local",
        "port": 502,
        "unit_id": 1,
        "scan_interval": 20,
    }


@pytest.mark.parametrize(
    ("error_type", "expected_error"),
    [
        (config_flow.InvalidWallbox, "unsupported_device"),
        (HomeAssistantError, "cannot_connect"),
        (ModbusError, "cannot_connect"),
    ],
)
@pytest.mark.asyncio
async def test_user_flow_reports_validation_errors(
    hass, monkeypatch, enable_custom_integrations, error_type, expected_error
) -> None:
    """Show a distinct form error for unsupported and unreachable devices."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(side_effect=error_type("test failure")),
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "wallbox.local"}
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": expected_error}