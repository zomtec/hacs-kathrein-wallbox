"""Tests for config-entry setup and unload."""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kathrein_wallbox import (
    CONFIG_SCHEMA,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.kathrein_wallbox.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_ID,
    DOMAIN,
    PLATFORMS,
)
from custom_components.kathrein_wallbox.coordinator import KathreinCoordinator


def test_config_schema_accepts_empty_config() -> None:
    """Declare the integration as config-entry-only to Hassfest."""
    assert CONFIG_SCHEMA({}) == {}


@pytest.mark.asyncio
async def test_setup_entry_initializes_coordinator_before_platforms(
    hass, monkeypatch, mock_modbus_unit
) -> None:
    """Refresh the coordinator and retain the selected scan interval."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "wallbox.local",
            CONF_PORT: 502,
            CONF_UNIT_ID: 1,
            CONF_SCAN_INTERVAL: 20,
        },
    )
    entry.add_to_hass(hass)
    monkeypatch.setattr(
        "custom_components.kathrein_wallbox.async_get_unit",
        Mock(return_value=mock_modbus_unit),
    )
    first_refresh = AsyncMock()
    monkeypatch.setattr(
        KathreinCoordinator, "async_config_entry_first_refresh", first_refresh
    )
    forward_platforms = AsyncMock()
    monkeypatch.setattr(
        hass.config_entries, "async_forward_entry_setups", forward_platforms
    )

    assert await async_setup_entry(hass, entry)

    coordinator = entry.runtime_data.coordinator
    assert coordinator.unit is mock_modbus_unit
    assert coordinator.update_interval == timedelta(seconds=20)
    first_refresh.assert_awaited_once()
    forward_platforms.assert_awaited_once_with(entry, PLATFORMS)


@pytest.mark.asyncio
async def test_unload_entry_unloads_all_platforms(hass, monkeypatch) -> None:
    """Delegate config-entry unload to all forwarded platforms."""
    entry = MockConfigEntry(domain=DOMAIN)
    unload_platforms = AsyncMock(return_value=True)
    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", unload_platforms)

    assert await async_unload_entry(hass, entry)

    unload_platforms.assert_awaited_once_with(entry, PLATFORMS)
