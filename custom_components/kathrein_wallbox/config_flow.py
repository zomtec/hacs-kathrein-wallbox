"""Config flow for Kathrein Wallbox."""

import logging
from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant import config_entries
from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from modbus_connection import ModbusError, ModbusTcpParams

from .const import (
    CONF_ALLOW_CONTROL,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_ID,
    DEFAULT_ALLOW_CONTROL,
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
    get_allow_control,
    get_scan_interval,
)
from .model import WallboxIdentity

_LOGGER = logging.getLogger(__name__)

ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_UNSUPPORTED_DEVICE = "unsupported_device"
# The Wallbox registers in DHCP as "KWB" followed by its serial number.
DHCP_HOSTNAME_PREFIX = "kwb"


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


def _modbus_schema(defaults: Mapping[str, Any]) -> probatio.Schema:
    """Build the port and unit ID form schema with the given default values."""
    return probatio.Schema(
        {
            probatio.Optional(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): _number_selector(MIN_PORT, MAX_PORT),
            probatio.Optional(
                CONF_UNIT_ID, default=defaults.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)
            ): _number_selector(MIN_UNIT_ID, MAX_UNIT_ID),
        }
    )


def _connection_schema(defaults: Mapping[str, Any]) -> probatio.Schema:
    """Build the connection form schema with the given default values."""
    return probatio.Schema(
        {
            probatio.Required(
                CONF_HOST, default=defaults.get(CONF_HOST, probatio.UNDEFINED)
            ): str
        }
    ).extend(_modbus_schema(defaults).schema)


def _options_schema(
    default_seconds: int, default_allow_control: bool
) -> probatio.Schema:
    """Build the polling interval and control form schema with the given defaults."""
    return probatio.Schema(
        {
            probatio.Optional(CONF_SCAN_INTERVAL, default=default_seconds): (
                _number_selector(MIN_SCAN_INTERVAL_SECONDS, MAX_SCAN_INTERVAL_SECONDS)
            ),
            probatio.Optional(CONF_ALLOW_CONTROL, default=default_allow_control): bool,
        }
    )


def _setup_options_schema() -> probatio.Schema:
    """Build the options part of a setup form with the default values."""
    return _options_schema(
        int(DEFAULT_SCAN_INTERVAL.total_seconds()), DEFAULT_ALLOW_CONTROL
    )


def _options_data(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Return the entry options from a submitted form."""
    return {
        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
        CONF_ALLOW_CONTROL: user_input[CONF_ALLOW_CONTROL],
    }


class InvalidWallbox(Exception):
    """Raised when the device does not report a supported mapping."""


def _normalize_connection_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalize numeric connection settings returned by number selectors."""
    normalized = dict(user_input)
    for key in (CONF_PORT, CONF_UNIT_ID):
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
    """Handle a user-configured or discovered Wallbox."""

    VERSION = 1
    _discovered_host: str

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow for the polling interval and control permission."""
        return KathreinWallboxOptionsFlowHandler()

    async def _async_create_validated_entry(
        self, user_input: dict[str, Any]
    ) -> tuple[ConfigFlowResult | None, dict[str, str]]:
        """Create the entry if the device validates, otherwise return form errors."""
        identity, error = await _async_validate_or_error(self.hass, user_input)
        if identity is None:
            return None, {"base": error} if error is not None else {}
        serial, device_type = identity
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured()
        options = _options_data(user_input)
        data = _normalize_connection_data(
            {key: value for key, value in user_input.items() if key not in options}
        )
        return (
            self.async_create_entry(title=device_type, data=data, options=options),
            {},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the connection and create a config entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            result, errors = await self._async_create_validated_entry(user_input)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema({}).extend(_setup_options_schema().schema),
            errors=errors,
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a Wallbox found by DHCP and update the address of a known one."""
        serial = discovery_info.hostname[len(DHCP_HOSTNAME_PREFIX) :].upper()
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})
        self._discovered_host = discovery_info.ip
        self.context["title_placeholders"] = {CONF_HOST: discovery_info.ip}
        return await self.async_step_dhcp_confirm()

    async def async_step_dhcp_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered Wallbox after reading it like a manual setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            result, errors = await self._async_create_validated_entry(
                {CONF_HOST: self._discovered_host, **user_input}
            )
            if result is not None:
                return result

        return self.async_show_form(
            step_id="dhcp_confirm",
            data_schema=_modbus_schema({}).extend(_setup_options_schema().schema),
            description_placeholders={CONF_HOST: self._discovered_host},
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
                    title=device_type,
                )
            if error is not None:
                errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(entry.data),
            errors=errors,
        )


class KathreinWallboxOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle the polling interval and control permission after initial setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the options; connection settings belong to reconfigure."""
        if user_input is not None:
            return self.async_create_entry(data=_options_data(user_input))

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(
                int(get_scan_interval(self.config_entry).total_seconds()),
                get_allow_control(self.config_entry),
            ),
        )
