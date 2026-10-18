"""Config flow for Kathrein Wallbox."""

import logging
from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant import config_entries
from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from modbus_connection import ModbusError, ModbusTcpParams

from .const import (
    CONF_ALLOW_CONTROL,
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


def _number_selector(minimum: int, maximum: int) -> probatio.All[int]:
    """Return a whole-number input box limited to the given range."""
    return probatio.All(
        selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=minimum,
                max=maximum,
                step=1,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        probatio.Coerce(int),
    )


# Forms are prefilled with suggested values; a cleared field keeps the shown value.
MODBUS_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_PORT): _number_selector(MIN_PORT, MAX_PORT),
        probatio.Optional(CONF_UNIT_ID): _number_selector(MIN_UNIT_ID, MAX_UNIT_ID),
    }
)
CONNECTION_SCHEMA = probatio.Schema({probatio.Required(CONF_HOST): str}).extend(
    MODBUS_SCHEMA.schema
)
OPTIONS_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_SCAN_INTERVAL): _number_selector(
            MIN_SCAN_INTERVAL_SECONDS, MAX_SCAN_INTERVAL_SECONDS
        ),
        probatio.Optional(CONF_ALLOW_CONTROL): bool,
    }
)
DEFAULT_OPTIONS = {
    CONF_SCAN_INTERVAL: int(DEFAULT_SCAN_INTERVAL.total_seconds()),
    CONF_ALLOW_CONTROL: DEFAULT_ALLOW_CONTROL,
}
SETUP_DEFAULTS = {
    CONF_PORT: DEFAULT_PORT,
    CONF_UNIT_ID: DEFAULT_UNIT_ID,
    **DEFAULT_OPTIONS,
}


class InvalidWallbox(Exception):
    """Raised when the device does not report a supported mapping."""


async def _async_validate_input(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> tuple[str, str]:
    """Check the mapping version and retrieve the device identity."""
    params = ModbusTcpParams(host=user_input[CONF_HOST], port=user_input[CONF_PORT])
    async with async_get_temporary_unit(hass, params, user_input[CONF_UNIT_ID]) as unit:
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


async def _async_reports_serial(
    hass: HomeAssistant, connection_data: Mapping[str, Any], serial: str
) -> bool:
    """Return whether the connection reaches the Wallbox with this serial number."""
    try:
        reported_serial, _ = await _async_validate_input(hass, dict(connection_data))
    except (InvalidWallbox, HomeAssistantError, ModbusError) as err:
        _LOGGER.debug("No Wallbox at %s: %s", connection_data[CONF_HOST], err)
        return False
    return reported_serial == serial


async def _async_wallbox_moved(
    hass: HomeAssistant, entry: ConfigEntry, serial: str, ip: str
) -> bool:
    """Return whether the Wallbox no longer answers at its stored host but at the IP."""
    # The stored host may be a Modbus proxy, so only replace an address that failed.
    if entry.data[CONF_HOST] == ip or await _async_reports_serial(
        hass, entry.data, serial
    ):
        return False
    return await _async_reports_serial(hass, {**entry.data, CONF_HOST: ip}, serial)


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
        user_input = {**SETUP_DEFAULTS, **user_input}
        identity, error = await _async_validate_or_error(self.hass, user_input)
        if identity is None:
            return None, {"base": error} if error is not None else {}
        serial, device_type = identity
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured()
        options = {key: user_input[key] for key in DEFAULT_OPTIONS}
        data = {key: value for key, value in user_input.items() if key not in options}
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
            data_schema=self.add_suggested_values_to_schema(
                CONNECTION_SCHEMA.extend(OPTIONS_SCHEMA.schema), SETUP_DEFAULTS
            ),
            errors=errors,
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a Wallbox found by DHCP and update the address of a known one."""
        serial = discovery_info.hostname[len(DHCP_HOSTNAME_PREFIX) :].upper()
        await self.async_set_unique_id(serial)
        entry = self.hass.config_entries.async_entry_for_domain_unique_id(
            DOMAIN, serial
        )
        if entry is not None and await _async_wallbox_moved(
            self.hass, entry, serial, discovery_info.ip
        ):
            self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})
        self._abort_if_unique_id_configured()
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
            data_schema=self.add_suggested_values_to_schema(
                MODBUS_SCHEMA.extend(OPTIONS_SCHEMA.schema), SETUP_DEFAULTS
            ),
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
            user_input = {**entry.data, **user_input}
            identity, error = await _async_validate_or_error(self.hass, user_input)
            if identity is not None:
                serial, device_type = identity
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=user_input,
                    title=device_type,
                )
            if error is not None:
                errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                CONNECTION_SCHEMA, entry.data
            ),
            errors=errors,
        )


class KathreinWallboxOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle the polling interval and control permission after initial setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the options; connection settings belong to reconfigure."""
        current = {
            CONF_SCAN_INTERVAL: int(
                get_scan_interval(self.config_entry).total_seconds()
            ),
            CONF_ALLOW_CONTROL: get_allow_control(self.config_entry),
        }
        if user_input is not None:
            return self.async_create_entry(data={**current, **user_input})

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, current),
        )
