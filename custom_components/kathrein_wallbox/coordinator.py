"""Polling coordinator for Kathrein Wallbox register data."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from modbus_connection import ModbusError, ModbusUnit

from .const import (
    CONF_METER_DETECTED,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_NAME,
    DOMAIN,
    get_allow_control,
)
from .model import (
    EMS_CONTROL_DISABLED,
    EMS_CONTROL_ENABLED,
    WallboxChargingSession,
    WallboxEMSControl,
    WallboxEVSE,
    WallboxIdentity,
    WallboxMeter,
    WallboxSessionEnergy,
)

_LOGGER = logging.getLogger(__name__)

# Rewrite the setpoint twice per timeout period so one missed write is tolerated.
KEEP_ALIVE_WRITES_PER_TIMEOUT = 2
# Never rewrite the setpoint more often than this, whatever the EMS timeout.
KEEP_ALIVE_MIN_INTERVAL = timedelta(seconds=5)


class KathreinCoordinator(DataUpdateCoordinator["WallboxData"]):
    """Fetch the Wallbox model at a fixed polling interval."""

    config_entry: KathreinConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: KathreinConfigEntry,
        unit: ModbusUnit,
        update_interval: timedelta | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DEVICE_NAME,
            update_interval=update_interval or DEFAULT_SCAN_INTERVAL,
        )
        self.unit = unit
        self.identity = WallboxIdentity(unit)
        self.meter = WallboxMeter(unit)
        self.session_energy = WallboxSessionEnergy(unit)
        self.evse = WallboxEVSE(unit)
        self.charging_session = WallboxChargingSession(unit)
        self.ems_control = WallboxEMSControl(unit)
        # A detected meter is final; otherwise check again once per setup.
        self.meter_detected: bool | None = (
            True if entry.data.get(CONF_METER_DETECTED) else None
        )
        self.meter_available = False
        self.session_energy_available = False
        self.charging_session_available = False
        self._meter_unavailable_logged = False
        self._session_energy_unavailable_logged = False
        self._charging_session_unavailable_logged = False
        self.control_allowed = get_allow_control(entry)
        self._keep_alive_interval: timedelta | None = None
        self._cancel_keep_alive: CALLBACK_TYPE | None = None
        self._keep_alive_failed = False

    async def _async_setup(self) -> None:
        """Read the static device identity once before the first poll."""
        try:
            await self.identity.async_update()
        except ModbusError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        if not self.identity.serial:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="missing_serial_number",
            )

    async def _async_update_data(self) -> WallboxData:
        """Read essential registers and isolate the optional energy meter."""
        try:
            await self.evse.async_update()
            await self.ems_control.async_update()
        except ModbusError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        self._async_schedule_keep_alive()

        await self._async_update_charging_session()
        await self._async_update_meter()

        return WallboxData(
            identity=self.identity,
            meter=self.meter,
            session_energy=self.session_energy,
            evse=self.evse,
            charging_session=self.charging_session,
            ems_control=self.ems_control,
        )

    async def _async_update_charging_session(self) -> None:
        """Read the session tag and GUID without blocking the EVSE data."""
        try:
            await self.charging_session.async_update()
        except ModbusError as err:
            if self.charging_session_available:
                _LOGGER.warning(
                    "Charging session registers are no longer available: %s", err
                )
                self._charging_session_unavailable_logged = True
            self.charging_session_available = False
        else:
            if self._charging_session_unavailable_logged:
                _LOGGER.info("Charging session registers are available again")
                self._charging_session_unavailable_logged = False
            self.charging_session_available = True

    async def _async_update_meter(self) -> None:
        """Read the optional meter and session energy if a meter was detected."""
        if self.meter_detected is False:
            return
        try:
            await self.meter.async_update()
        except ModbusError as err:
            if self.meter_available:
                _LOGGER.warning(
                    "Energy meter registers are no longer available: %s", err
                )
                self._meter_unavailable_logged = True
            self.meter_available = False
            self.session_energy_available = False
            return
        if self.meter_detected is None:
            self._async_store_meter_detected(self.meter.has_plausible_reference)
        self.meter_available = bool(self.meter_detected)
        if not self.meter_available:
            return
        if self._meter_unavailable_logged:
            _LOGGER.info("Energy meter registers are available again")
            self._meter_unavailable_logged = False
        try:
            await self.session_energy.async_update()
        except ModbusError as err:
            if self.session_energy_available:
                _LOGGER.warning(
                    "Session energy register is no longer available: %s", err
                )
                self._session_energy_unavailable_logged = True
            self.session_energy_available = False
        else:
            if self._session_energy_unavailable_logged:
                _LOGGER.info("Session energy register is available again")
                self._session_energy_unavailable_logged = False
            self.session_energy_available = True

    @callback
    def _async_store_meter_detected(self, detected: bool) -> None:
        """Persist the result of this setup's meter check in the config entry."""
        self.meter_detected = detected
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**self.config_entry.data, CONF_METER_DETECTED: detected},
        )

    async def async_write_ems(
        self, field: str, value: int, *, enable_ems: bool = False
    ) -> None:
        """Write an allowed EMS field, optionally enabling EMS control first."""
        self.validate_control_allowed()
        writes = [(field, value)]
        if enable_ems:
            # Setpoints only take effect while EMS control is enabled.
            writes.insert(0, ("control_register", EMS_CONTROL_ENABLED))
        await self._async_write_ems_fields(writes)

    async def async_set_ems_control(self, enabled: bool) -> None:
        """Switch EMS control, even while control by Home Assistant is not allowed."""
        value = EMS_CONTROL_ENABLED if enabled else EMS_CONTROL_DISABLED
        await self._async_write_ems_fields([("control_register", value)])

    async def _async_write_ems_fields(self, writes: list[tuple[str, int]]) -> None:
        """Write EMS fields in order, report device failures and refresh."""
        try:
            for field, value in writes:
                await self.ems_control.write(field, value)
        except ModbusError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # A debounced refresh would delay the read-back of a quick second write.
        await self.async_refresh()

    def validate_control_allowed(self) -> None:
        """Reject writes unless the user allowed control by Home Assistant."""
        if not self.control_allowed:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="control_not_allowed",
            )

    async def async_shutdown(self) -> None:
        """Stop the keep-alive timer together with polling."""
        await super().async_shutdown()
        self._async_cancel_keep_alive()

    @callback
    def _async_schedule_keep_alive(self) -> None:
        """Run the keep-alive timer at a pace matching the current EMS timeout."""
        timeout_period = self.ems_control.timeout_period
        interval = None
        if self.control_allowed and timeout_period:
            interval = max(
                KEEP_ALIVE_MIN_INTERVAL,
                timedelta(seconds=timeout_period / KEEP_ALIVE_WRITES_PER_TIMEOUT),
            )
        if interval == self._keep_alive_interval:
            return
        self._async_cancel_keep_alive()
        if interval is None:
            return
        self._keep_alive_interval = interval
        self._cancel_keep_alive = async_track_time_interval(
            self.hass, self._async_keep_alive, interval, name="EMS keep-alive"
        )

    @callback
    def _async_cancel_keep_alive(self) -> None:
        """Stop the keep-alive timer if it runs."""
        if self._cancel_keep_alive is not None:
            self._cancel_keep_alive()
            self._cancel_keep_alive = None
        self._keep_alive_interval = None

    async def _async_keep_alive(self, _now: datetime) -> None:
        """Rewrite the charging current setpoint to reset the EMS timeout."""
        current = self.ems_control.charging_current
        if not self.ems_control.is_enabled or current is None:
            return
        try:
            await self.ems_control.write("charging_current", current)
        except ModbusError as err:
            if not self._keep_alive_failed:
                _LOGGER.warning("EMS keep-alive write failed: %s", err)
            self._keep_alive_failed = True
            return
        if self._keep_alive_failed:
            _LOGGER.info("EMS keep-alive write succeeded again")
        self._keep_alive_failed = False


@dataclass(slots=True)
class WallboxData:
    """Decoded identity, optional meter, EVSE, session and EMS control components."""

    identity: WallboxIdentity
    meter: WallboxMeter
    session_energy: WallboxSessionEnergy
    evse: WallboxEVSE
    charging_session: WallboxChargingSession
    ems_control: WallboxEMSControl


@dataclass(slots=True)
class WallboxRuntimeData:
    """Runtime objects owned by a config entry."""

    coordinator: KathreinCoordinator


type KathreinConfigEntry = ConfigEntry[WallboxRuntimeData]
