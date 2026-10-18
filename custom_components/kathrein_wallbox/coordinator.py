"""Polling coordinator for Kathrein Wallbox register data."""

import logging
from collections.abc import Iterable
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
from modbus_connection.model import UpdateReport

from .const import (
    CONF_METER_DETECTED,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_NAME,
    DOMAIN,
    get_allow_control,
)
from .model import (
    COMPONENT_CHARGING_SESSION,
    COMPONENT_EMS_CONTROL,
    COMPONENT_EVSE,
    COMPONENT_METER,
    COMPONENT_SESSION_ENERGY,
    EMS_CHARGING_PAUSED_A,
    EMS_CONTROL_DISABLED,
    EMS_CONTROL_ENABLED,
    EMS_MAX_CHARGING_CURRENT_A,
    EMS_MIN_CHARGING_CURRENT_A,
    MAX_CURRENT_11_KW_A,
    WallboxDevice,
)

_LOGGER = logging.getLogger(__name__)

# Rewrite the setpoint twice per timeout period so one missed write is tolerated.
KEEP_ALIVE_WRITES_PER_TIMEOUT = 2
# Never rewrite the setpoint more often than this, whatever the EMS timeout.
KEEP_ALIVE_MIN_INTERVAL = timedelta(seconds=5)

ESSENTIAL_COMPONENTS = (COMPONENT_EVSE, COMPONENT_EMS_CONTROL)
# Subjects of the log lines when an optional component is lost or back.
OPTIONAL_COMPONENT_SUBJECTS = {
    COMPONENT_CHARGING_SESSION: "Charging session registers are",
    COMPONENT_METER: "Energy meter registers are",
    COMPONENT_SESSION_ENERGY: "Session energy register is",
}


def _update_failed(err: ModbusError) -> UpdateFailed:
    """Wrap a Modbus error as a translated coordinator update failure."""
    return UpdateFailed(
        translation_domain=DOMAIN,
        translation_key="update_failed",
        translation_placeholders={"error": str(err)},
    )


class KathreinCoordinator(DataUpdateCoordinator[UpdateReport]):
    """Poll the Wallbox components at a fixed interval."""

    config_entry: KathreinConfigEntry
    # Set by _async_setup, which refuses a Wallbox without a serial number.
    serial: str

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
        self.device = WallboxDevice(unit)
        # A detected meter is final; otherwise check again once per setup.
        self.meter_detected: bool | None = (
            True if entry.data.get(CONF_METER_DETECTED) else None
        )
        self._lost_components: set[str] = set()
        self.control_allowed = get_allow_control(entry)
        self._keep_alive_interval: timedelta | None = None
        self._cancel_keep_alive: CALLBACK_TYPE | None = None
        self._keep_alive_failed = False

    async def _async_setup(self) -> None:
        """Read the static device identity once before the first poll."""
        try:
            await self.device.async_ensure_setup()
        except ModbusError as err:
            raise _update_failed(err) from err

        if not self.device.identity.serial:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="missing_serial_number",
            )
        self.serial = self.device.identity.serial

    async def _async_update_data(self) -> UpdateReport:
        """Poll the essential components and isolate the optional ones."""
        report = await self._async_poll(ESSENTIAL_COMPONENTS)
        if report.failed:
            raise _update_failed(next(iter(report.failed.values())))

        self._async_schedule_keep_alive()

        optional = [COMPONENT_CHARGING_SESSION]
        if self.meter_detected is not False:
            optional.append(COMPONENT_METER)
        await self._async_poll(optional, report)
        self._async_settle_meter(report)
        if COMPONENT_METER in report.updated:
            await self._async_poll([COMPONENT_SESSION_ENERGY], report)

        self._async_log_optional_components(report)
        return report

    async def _async_poll(
        self, names: Iterable[str], report: UpdateReport | None = None
    ) -> UpdateReport:
        """Poll components, failing the update when the connection is lost."""
        try:
            return await self.device.async_poll(names, report)
        except ModbusError as err:
            raise _update_failed(err) from err

    @callback
    def _async_settle_meter(self, report: UpdateReport) -> None:
        """Check a new meter once and drop the readings of an undetected one."""
        if self.meter_detected is None and COMPONENT_METER in report.updated:
            self._async_store_meter_detected(self.device.meter.has_plausible_reference)
        if not self.meter_detected:
            # A read without a detected meter only settles detection.
            report.updated.discard(COMPONENT_METER)

    @callback
    def _async_log_optional_components(self, report: UpdateReport) -> None:
        """Log once when an optional component stops answering and when it is back."""
        previous = self.data.updated if self.data else set()
        for name, err in report.failed.items():
            if name in previous:
                _LOGGER.warning(
                    "%s no longer available: %s", OPTIONAL_COMPONENT_SUBJECTS[name], err
                )
                self._lost_components.add(name)
        for name in self._lost_components & report.updated:
            _LOGGER.info("%s available again", OPTIONAL_COMPONENT_SUBJECTS[name])
            self._lost_components.discard(name)

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
                await self.device.ems_control.write(field, value)
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

    def validate_ems_current(self, current: float) -> None:
        """Reject EMS currents the Wallbox cannot charge with."""
        if not current.is_integer():
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="current_not_whole",
            )
        if current != EMS_CHARGING_PAUSED_A and current < EMS_MIN_CHARGING_CURRENT_A:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="current_below_minimum",
                translation_placeholders={
                    "min_current": str(EMS_MIN_CHARGING_CURRENT_A)
                },
            )
        if self.device.identity.is_11_kw and current > MAX_CURRENT_11_KW_A:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="current_limit_11_kw",
                translation_placeholders={"max_current": str(MAX_CURRENT_11_KW_A)},
            )
        if current > EMS_MAX_CHARGING_CURRENT_A:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="current_above_maximum",
                translation_placeholders={
                    "max_current": str(EMS_MAX_CHARGING_CURRENT_A)
                },
            )

    async def async_shutdown(self) -> None:
        """Stop the keep-alive timer together with polling."""
        await super().async_shutdown()
        self._async_cancel_keep_alive()

    @callback
    def _async_schedule_keep_alive(self) -> None:
        """Run the keep-alive timer at a pace matching the current EMS timeout."""
        timeout_period = self.device.ems_control.timeout_period
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
        current = self.device.ems_control.charging_current
        if not self.device.ems_control.is_enabled or current is None:
            return
        try:
            await self.device.ems_control.write("charging_current", current)
        except ModbusError as err:
            if not self._keep_alive_failed:
                _LOGGER.warning("EMS keep-alive write failed: %s", err)
            self._keep_alive_failed = True
            return
        if self._keep_alive_failed:
            _LOGGER.info("EMS keep-alive write succeeded again")
        self._keep_alive_failed = False


@dataclass(slots=True)
class WallboxRuntimeData:
    """Runtime objects owned by a config entry."""

    coordinator: KathreinCoordinator


type KathreinConfigEntry = ConfigEntry[WallboxRuntimeData]
