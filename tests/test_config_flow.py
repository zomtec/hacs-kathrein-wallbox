"""Tests for the Kathrein Wallbox config flow."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.exceptions import HomeAssistantError
from modbus_connection import ModbusError
from pytest_homeassistant_custom_component.common import MockConfigEntry

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


CONNECTION = {
    "host": "wallbox.local",
    "port": 502,
    "unit_id": 1,
    "scan_interval": 20,
}
NEW_CONNECTION = {**CONNECTION, "host": "new-wallbox.local"}


@pytest.fixture
def wallbox_entry(hass, enable_custom_integrations) -> MockConfigEntry:
    """Add a configured Wallbox entry whose setup is not exercised."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="SERIAL123", data=CONNECTION, title="Kathrein"
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(autouse=True)
def skip_entry_setup():
    """Avoid loading the integration when a flow reloads its entry."""
    with patch(
        "custom_components.kathrein_wallbox.async_setup_entry", return_value=True
    ):
        yield


@pytest.mark.asyncio
async def test_user_flow_aborts_for_already_configured_wallbox(
    hass, monkeypatch, wallbox_entry
) -> None:
    """Prevent configuring the same Wallbox twice."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(return_value=("SERIAL123", "Kathrein 11 kW")),
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], NEW_CONNECTION
    )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_reconfigure_updates_connection_data(
    hass, monkeypatch, wallbox_entry
) -> None:
    """Store the new connection settings for the same Wallbox."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(return_value=("SERIAL123", "Kathrein 22 kW")),
    )
    result = await wallbox_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], NEW_CONNECTION
    )

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert wallbox_entry.data == NEW_CONNECTION
    assert wallbox_entry.title == "Kathrein 22 kW"


@pytest.mark.asyncio
async def test_reconfigure_aborts_for_a_different_wallbox(
    hass, monkeypatch, wallbox_entry
) -> None:
    """Refuse to repoint an entry to another Wallbox."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(return_value=("OTHER", "Kathrein 11 kW")),
    )
    result = await wallbox_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], NEW_CONNECTION
    )

    assert result["type"] == "abort"
    assert result["reason"] == "unique_id_mismatch"
    assert wallbox_entry.data == CONNECTION


@pytest.mark.parametrize(
    ("error_type", "expected_error"),
    [
        (config_flow.InvalidWallbox, "unsupported_device"),
        (ModbusError, "cannot_connect"),
    ],
)
@pytest.mark.asyncio
async def test_reconfigure_reports_validation_errors(
    hass, monkeypatch, wallbox_entry, error_type, expected_error
) -> None:
    """Keep the form open and show the matching error."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(side_effect=error_type("test failure")),
    )
    result = await wallbox_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], NEW_CONNECTION
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": expected_error}


@pytest.mark.asyncio
async def test_options_flow_updates_connection_data(
    hass, monkeypatch, wallbox_entry
) -> None:
    """Store connection settings changed through the options menu."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(return_value=("SERIAL123", "Kathrein 11 kW")),
    )
    result = await hass.config_entries.options.async_init(wallbox_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], NEW_CONNECTION
    )

    assert result["type"] == "create_entry"
    assert wallbox_entry.data == NEW_CONNECTION
    assert wallbox_entry.options == {}


@pytest.mark.parametrize(
    ("validation", "expected_error"),
    [
        (AsyncMock(return_value=("OTHER", "Kathrein 11 kW")), "unique_id_mismatch"),
        (AsyncMock(side_effect=ModbusError("test failure")), "cannot_connect"),
    ],
)
@pytest.mark.asyncio
async def test_options_flow_rejects_invalid_connection(
    hass, monkeypatch, wallbox_entry, validation, expected_error
) -> None:
    """Keep the stored settings when the new connection is not the same Wallbox."""
    monkeypatch.setattr(config_flow, "_async_validate_input", validation)
    result = await hass.config_entries.options.async_init(wallbox_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], NEW_CONNECTION
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": expected_error}
    assert wallbox_entry.data == CONNECTION
