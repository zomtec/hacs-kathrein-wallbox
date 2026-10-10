"""Config flow for Kathrein Wallbox."""

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from modbus_connection import ModbusError, ModbusTcpParams

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_UNIT_ID,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    DEVICE_NAME,
    DOMAIN,
    EXPECTED_MAPPING_VERSION,
    MAX_PORT,
    MAX_SCAN_INTERVAL_SECONDS,
    MAX_UNIT_ID,
    MIN_PORT,
    MIN_SCAN_INTERVAL_SECONDS,
    MIN_UNIT_ID,
    get_scan_interval,
)
from .model import WallboxIdentity

_LOGGER = logging.getLogger(__name__)

ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_UNSUPPORTED_DEVICE = "unsupported_device"
ERROR_UNIQUE_ID_MISMATCH = "unique_id_mismatch"


def _number_selector(minimum: int, maximum: int) -> selector.NumberSelector:
    """Return a whole-number input box limited to the given range."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _connection_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Build the connection form schema with the given default values."""
    return vol.Schema(
        {
            vol.Required(
                CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)
            ): str,
            vol.Optional(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): _number_selector(MIN_PORT, MAX_PORT),
            vol.Optional(
                CONF_UNIT_ID, default=defaults.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)
            ): _number_selector(MIN_UNIT_ID, MAX_UNIT_ID),
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=defaults.get(
                    CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
                ),
            ): _number_selector(MIN_SCAN_INTERVAL_SECONDS, MAX_SCAN_INTERVAL_SECONDS),
        }
    )


def _entry_defaults(entry: ConfigEntry) -> dict[str, Any]:
    """Return the form defaults for an existing config entry."""
    return {
        **entry.data,
        CONF_SCAN_INTERVAL: int(get_scan_interval(entry).total_seconds()),
    }


class InvalidWallbox(Exception):
    """Raised when the device does not report a supported mapping."""


def _normalize_connection_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalize numeric connection settings returned by number selectors."""
    normalized = dict(user_input)
    for key in (CONF_PORT, CONF_UNIT_ID, CONF_SCAN_INTERVAL):
        if key in normalized:
            normalized[key] = int(normalized[key])
    return normalized


async def _async_validate_input(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> tuple[str, str]:
    """Check the mapping version and retrieve the device identity."""
    connection_data = _normalize_connection_data(user_input)
    params = ModbusTcpParams(
        host=connection_data[CONF_HOST],
        port=connection_data[CONF_PORT],
    )
    async with async_get_temporary_unit(
        hass, params, connection_data[CONF_UNIT_ID]
    ) as unit:
        identity = WallboxIdentity(unit)
        await identity.async_update()

    if identity.mapping_version != EXPECTED_MAPPING_VERSION or not identity.serial:
        raise InvalidWallbox
    return identity.serial, identity.device_type or DEVICE_NAME


async def _async_validate_or_error(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> tuple[tuple[str, str] | None, str | None]:
    """Validate the connection and return either the identity or a form error."""
    try:
        return await _async_validate_input(hass, user_input), None
    except InvalidWallbox:
        return None, ERROR_UNSUPPORTED_DEVICE
    except (HomeAssistantError, ModbusError) as err:
        _LOGGER.warning("Unable to connect to the Kathrein Wallbox: %s", err)
        return None, ERROR_CANNOT_CONNECT


class KathreinWallboxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a user-configured Wallbox."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow for adjusting the connection settings."""
        return KathreinWallboxOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the connection and create a config entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            identity, error = await _async_validate_or_error(self.hass, user_input)
            if identity is not None:
                serial, device_type = identity
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=device_type,
                    data=_normalize_connection_data(user_input),
                )
            if error is not None:
                errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema({}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow changing the connection parameters after the initial setup."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            identity, error = await _async_validate_or_error(self.hass, user_input)
            if identity is not None:
                serial, device_type = identity
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=_normalize_connection_data(user_input),
                    options={},
                    title=device_type,
                )
            if error is not None:
                errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(_entry_defaults(entry)),
            errors=errors,
        )


class KathreinWallboxOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle connection settings after initial setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit and validate all connection settings from the options menu."""
        errors: dict[str, str] = {}
        if user_input is not None:
            identity, error = await _async_validate_or_error(self.hass, user_input)
            if identity is not None and identity[0] != self.config_entry.unique_id:
                error = ERROR_UNIQUE_ID_MISMATCH
            if error is None:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=_normalize_connection_data(user_input),
                    options={},
                )
                self.hass.config_entries.async_schedule_reload(
                    self.config_entry.entry_id
                )
                return self.async_create_entry(title="", data={})
            errors["base"] = error

        return self.async_show_form(
            step_id="init",
            data_schema=_connection_schema(_entry_defaults(self.config_entry)),
            errors=errors,
        )
