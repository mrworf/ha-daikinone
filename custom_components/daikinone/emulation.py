"""Group-aware emulated Heat/Cool control."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import logging

from homeassistant.components import persistent_notification
from homeassistant.components.climate.const import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_OPTION_CONVERT_EXTERNAL_AUTO,
    CONF_OPTION_EMULATION_DWELL_MINUTES,
    CONF_OPTION_EMULATION_TOLERANCE,
    DEFAULT_CONVERT_EXTERNAL_AUTO,
    DEFAULT_EMULATION_DWELL_MINUTES,
    DEFAULT_EMULATION_TOLERANCE,
    DOMAIN,
)
from .daikinone import DaikinOne, DaikinThermostat, DaikinThermostatCapability, DaikinThermostatMode

log = logging.getLogger(__name__)

COMMAND_PROPAGATION_TIME = timedelta(seconds=45)


class EmulationStatus(StrEnum):
    """Observable state of one emulated head."""

    IDLE = "idle"
    HEATING = "heating"
    COOLING = "cooling"
    WAITING_FOR_HEATING = "waiting_for_heating"
    WAITING_FOR_COOLING = "waiting_for_cooling"
    WAITING_FOR_DWELL = "waiting_for_dwell"
    SUSPENDED_BY_MANUAL_CONTROL = "suspended_by_manual_control"
    WAITING_FOR_DATA = "waiting_for_data"


class Demand(StrEnum):
    """Physical direction requested by an emulated head."""

    HEAT = "heat"
    COOL = "cool"


@dataclass
class HeadControl:
    """Logical and command state for one head."""

    logical_mode: HVACMode
    previous_mode: HVACMode
    expected_mode: DaikinThermostatMode
    callback: Callable[[], None]
    demand: Demand | None = None
    status: EmulationStatus | None = None
    pending_until: datetime | None = None
    native_auto_selected_in_ha: bool = False


@dataclass
class GroupControl:
    """Direction and reversal state shared by an outdoor unit."""

    direction: Demand | None = None
    direction_since: datetime | None = None
    pending_direction: Demand | None = None
    off_cycle_pending: bool = False


def mode_to_hvac(mode: DaikinThermostatMode) -> HVACMode:
    """Map a physical Daikin mode to a Home Assistant mode."""
    if mode is DaikinThermostatMode.HEAT or mode is DaikinThermostatMode.AUX_HEAT:
        return HVACMode.HEAT
    if mode is DaikinThermostatMode.COOL:
        return HVACMode.COOL
    if mode is DaikinThermostatMode.AUTO:
        return HVACMode.AUTO
    return HVACMode.OFF


def mode_direction(mode: DaikinThermostatMode) -> Demand | None:
    """Return the outdoor-unit direction represented by a physical mode."""
    if mode in (DaikinThermostatMode.HEAT, DaikinThermostatMode.AUX_HEAT):
        return Demand.HEAT
    if mode is DaikinThermostatMode.COOL:
        return Demand.COOL
    return None


class DaikinEmulationController:
    """Coordinate logical Heat/Cool state and physical head modes."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        daikin: DaikinOne,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._daikin = daikin
        self._heads: dict[str, HeadControl] = {}
        self._groups: dict[str, GroupControl] = {}
        self._lock = asyncio.Lock()
        self._now = now or (lambda: datetime.now(UTC))
        self._notification_ids: set[str] = set()

    @property
    def tolerance(self) -> float:
        return float(self._entry.options.get(CONF_OPTION_EMULATION_TOLERANCE, DEFAULT_EMULATION_TOLERANCE))

    @property
    def dwell(self) -> timedelta:
        minutes = int(self._entry.options.get(CONF_OPTION_EMULATION_DWELL_MINUTES, DEFAULT_EMULATION_DWELL_MINUTES))
        return timedelta(minutes=minutes)

    @property
    def convert_external_auto(self) -> bool:
        return bool(self._entry.options.get(CONF_OPTION_CONVERT_EXTERNAL_AUTO, DEFAULT_CONVERT_EXTERNAL_AUTO))

    def register(self, thermostat: DaikinThermostat, callback: Callable[[], None]) -> None:
        """Register a climate entity before it is added to Home Assistant."""
        logical_mode = mode_to_hvac(thermostat.mode)
        default_mode = (
            HVACMode.HEAT
            if DaikinThermostatCapability.HEAT in thermostat.capabilities
            else HVACMode.COOL if DaikinThermostatCapability.COOL in thermostat.capabilities else HVACMode.AUTO
        )
        self._heads[thermostat.id] = HeadControl(
            logical_mode=logical_mode,
            previous_mode=logical_mode if logical_mode is not HVACMode.OFF else default_mode,
            expected_mode=thermostat.mode,
            callback=callback,
        )

    def unregister(self, thermostat_id: str) -> None:
        """Remove a climate entity from controller callbacks."""
        self._heads.pop(thermostat_id, None)

    def logical_mode(self, thermostat_id: str) -> HVACMode:
        return self._heads[thermostat_id].logical_mode

    def previous_mode(self, thermostat_id: str) -> HVACMode:
        return self._heads[thermostat_id].previous_mode

    def status(self, thermostat_id: str) -> EmulationStatus | None:
        return self._heads[thermostat_id].status

    def expected_physical_mode(self, thermostat_id: str) -> DaikinThermostatMode:
        return self._heads[thermostat_id].expected_mode

    def supports_emulation(self, thermostat: DaikinThermostat) -> bool:
        """Reject known mini-split heads whose outdoor group is unresolved."""
        return thermostat.id not in self._daikin.get_heat_pump_candidate_ids() or thermostat.heat_pump_id is not None

    def restore(
        self,
        thermostat_id: str,
        logical_mode: HVACMode,
        previous_physical_mode: DaikinThermostatMode | None,
    ) -> None:
        """Restore emulated/native-Auto intent without overriding remote changes made while HA was down."""
        record = self._heads[thermostat_id]
        thermostat = self._daikin.get_thermostat(thermostat_id)
        if logical_mode is HVACMode.HEAT_COOL:
            if not self.supports_emulation(thermostat):
                record.logical_mode = mode_to_hvac(thermostat.mode)
            elif previous_physical_mode is None or thermostat.mode is not previous_physical_mode:
                if thermostat.mode is DaikinThermostatMode.AUTO and self.convert_external_auto:
                    record.logical_mode = HVACMode.HEAT_COOL
                else:
                    record.logical_mode = mode_to_hvac(thermostat.mode)
            else:
                record.logical_mode = HVACMode.HEAT_COOL
        elif logical_mode is HVACMode.AUTO and thermostat.mode is DaikinThermostatMode.AUTO:
            record.logical_mode = HVACMode.AUTO
            record.native_auto_selected_in_ha = True
        record.expected_mode = thermostat.mode
        if record.logical_mode is not HVACMode.OFF:
            record.previous_mode = record.logical_mode

    async def async_set_logical_mode(self, thermostat_id: str, mode: HVACMode) -> None:
        """Set an HA-selected mode and reconcile its outdoor group."""
        if mode is HVACMode.HEAT_COOL:
            thermostat = self._daikin.get_thermostat(thermostat_id)
            if not self.supports_emulation(thermostat):
                raise ValueError("Heat/Cool requires a resolved heat-pump assignment")
            record = self._heads[thermostat_id]
            record.logical_mode = mode
            record.previous_mode = mode
            record.native_auto_selected_in_ha = False
            record.expected_mode = thermostat.mode
            await self.async_reconcile()
            return
        raise ValueError(f"Unsupported logical-only HVAC mode: {mode}")

    async def async_set_manual_mode(self, thermostat_id: str, mode: DaikinThermostatMode) -> None:
        """Send a manual command while keeping logical state and failure rollback consistent."""
        record = self._heads[thermostat_id]
        previous = (
            record.logical_mode,
            record.previous_mode,
            record.expected_mode,
            record.pending_until,
            record.native_auto_selected_in_ha,
        )
        logical_mode = mode_to_hvac(mode)
        if logical_mode is not HVACMode.OFF:
            record.previous_mode = logical_mode
        record.logical_mode = logical_mode
        record.native_auto_selected_in_ha = mode is DaikinThermostatMode.AUTO
        try:
            await self._async_command(thermostat_id, mode)
        except Exception:
            (
                record.logical_mode,
                record.previous_mode,
                record.expected_mode,
                record.pending_until,
                record.native_auto_selected_in_ha,
            ) = previous
            raise
        record.status = None
        self._notify_callbacks()

    async def async_reconcile(self) -> None:
        """Reconcile every registered head once under a shared lock."""
        if not self._heads:
            return
        async with self._lock:
            now = self._now()
            thermostats = self._daikin.get_thermostats()
            self._adopt_external_changes(thermostats, now)
            groups: dict[str, list[DaikinThermostat]] = {}
            for thermostat_id in self._heads:
                thermostat = thermostats.get(thermostat_id)
                if thermostat is None:
                    continue
                group_id = thermostat.heat_pump_id or f"head-{thermostat.id}"
                groups.setdefault(group_id, []).append(thermostat)

            for group_id, members in groups.items():
                suspended = await self._async_reconcile_group(group_id, members, now)
                notification_id = self._notification_id(group_id)
                if suspended:
                    self._create_suspension_notification(notification_id, group_id, members, suspended)
                elif notification_id in self._notification_ids:
                    persistent_notification.async_dismiss(self._hass, notification_id)
                    self._notification_ids.discard(notification_id)
            self._notify_callbacks()

    def _adopt_external_changes(self, thermostats: dict[str, DaikinThermostat], now: datetime) -> None:
        for thermostat_id, record in self._heads.items():
            thermostat = thermostats.get(thermostat_id)
            if thermostat is None:
                continue
            if thermostat.mode is record.expected_mode:
                record.pending_until = None
                continue
            if record.pending_until is not None and now < record.pending_until:
                continue

            if (
                thermostat.mode is DaikinThermostatMode.AUTO
                and self.convert_external_auto
                and self.supports_emulation(thermostat)
            ):
                if not record.native_auto_selected_in_ha:
                    record.logical_mode = HVACMode.HEAT_COOL
                    record.previous_mode = HVACMode.HEAT_COOL
                else:
                    record.logical_mode = HVACMode.AUTO
            else:
                record.logical_mode = mode_to_hvac(thermostat.mode)
                if record.logical_mode is not HVACMode.OFF:
                    record.previous_mode = record.logical_mode
                record.native_auto_selected_in_ha = False
            record.expected_mode = thermostat.mode
            record.pending_until = None
            record.demand = None
            record.status = None

    async def _async_reconcile_group(self, group_id: str, members: list[DaikinThermostat], now: datetime) -> list[str]:
        emulated = [member for member in members if self._heads[member.id].logical_mode is HVACMode.HEAT_COOL]
        if not emulated:
            return []

        for member in emulated:
            self._update_demand(member)

        manual_auto = [
            member for member in members if member.online and self._heads[member.id].logical_mode is HVACMode.AUTO
        ]
        manual_directions = {
            direction
            for member in members
            if member.online
            if self._heads[member.id].logical_mode is not HVACMode.HEAT_COOL
            if (direction := mode_direction(member.mode)) is not None
        }

        suspended: list[str] = []
        if manual_auto or len(manual_directions) > 1:
            for member in emulated:
                if not member.online or not member.indoor_temperature_valid:
                    continue
                await self._async_apply(member, DaikinThermostatMode.OFF)
                self._heads[member.id].status = EmulationStatus.SUSPENDED_BY_MANUAL_CONTROL
                suspended.append(member.id)
            return suspended

        if manual_directions:
            direction = next(iter(manual_directions))
            self._set_group_direction(group_id, direction, now)
            for member in emulated:
                record = self._heads[member.id]
                if not member.online or not member.indoor_temperature_valid:
                    continue
                if record.demand is not direction:
                    await self._async_apply(member, DaikinThermostatMode.OFF)
                    if record.demand is not None:
                        record.status = EmulationStatus.SUSPENDED_BY_MANUAL_CONTROL
                        suspended.append(member.id)
                    else:
                        record.status = EmulationStatus.IDLE
            for member in emulated:
                record = self._heads[member.id]
                if member.online and member.indoor_temperature_valid and record.demand is direction:
                    await self._async_apply_direction(member, direction)
            return suspended

        if group_id not in self._groups:
            physical_directions = {
                direction
                for member in emulated
                if member.online and member.indoor_temperature_valid
                if (direction := mode_direction(self._heads[member.id].expected_mode)) is not None
            }
            if len(physical_directions) > 1:
                pending_direction = self._largest_demand(emulated, None)
                self._groups[group_id] = GroupControl(
                    pending_direction=pending_direction,
                    off_cycle_pending=True,
                )
                for member in emulated:
                    if member.online and member.indoor_temperature_valid:
                        await self._async_apply(member, DaikinThermostatMode.OFF)
                        self._set_waiting_status(member, EmulationStatus.WAITING_FOR_DWELL)
                return []
            initial_direction = next(iter(physical_directions)) if physical_directions else None
            self._groups[group_id] = GroupControl(
                direction=initial_direction,
                direction_since=now if initial_direction is not None else None,
            )
        group = self._groups[group_id]
        winner = self._largest_demand(emulated, group.direction)

        if group.off_cycle_pending:
            for member in emulated:
                if not member.online or not member.indoor_temperature_valid:
                    continue
                await self._async_apply(member, DaikinThermostatMode.OFF)
                self._set_waiting_status(member, EmulationStatus.WAITING_FOR_DWELL)
            if any(
                self._heads[member.id].pending_until is not None or member.mode is not DaikinThermostatMode.OFF
                for member in emulated
                if member.online and member.indoor_temperature_valid
            ):
                return []
            group.off_cycle_pending = False
            group.direction = group.pending_direction
            group.pending_direction = None
            group.direction_since = now

        if winner is not None and group.direction is not None and winner is not group.direction:
            direction_since = group.direction_since or now
            if now - direction_since < self.dwell:
                winner = group.direction
            else:
                group.pending_direction = winner
                group.off_cycle_pending = True
                for member in emulated:
                    if not member.online or not member.indoor_temperature_valid:
                        continue
                    await self._async_apply(member, DaikinThermostatMode.OFF)
                    self._set_waiting_status(member, EmulationStatus.WAITING_FOR_DWELL)
                return []

        if group.direction is None and winner is not None:
            group.direction = winner
            group.direction_since = now
        selected = winner if winner is not None else group.direction

        for member in emulated:
            record = self._heads[member.id]
            if not member.online or not member.indoor_temperature_valid:
                continue
            if record.demand is None or record.demand is not selected:
                await self._async_apply(member, DaikinThermostatMode.OFF)
                if record.demand is Demand.HEAT:
                    record.status = EmulationStatus.WAITING_FOR_HEATING
                elif record.demand is Demand.COOL:
                    record.status = EmulationStatus.WAITING_FOR_COOLING
                else:
                    record.status = EmulationStatus.IDLE
        for member in emulated:
            record = self._heads[member.id]
            if (
                member.online
                and member.indoor_temperature_valid
                and record.demand is not None
                and record.demand is selected
            ):
                await self._async_apply_direction(member, selected)
        return []

    def _update_demand(self, thermostat: DaikinThermostat) -> None:
        record = self._heads[thermostat.id]
        if not thermostat.online or not thermostat.indoor_temperature_valid:
            record.demand = None
            record.status = EmulationStatus.WAITING_FOR_DATA
            return
        temperature = thermostat.indoor_temperature.celsius
        low = thermostat.set_point_heat.celsius
        high = thermostat.set_point_cool.celsius
        if record.demand is Demand.HEAT:
            if temperature >= low:
                record.demand = None
        elif record.demand is Demand.COOL:
            if temperature <= high:
                record.demand = None
        elif temperature <= low - self.tolerance:
            record.demand = Demand.HEAT
        elif temperature >= high + self.tolerance:
            record.demand = Demand.COOL

    def _largest_demand(self, members: list[DaikinThermostat], current: Demand | None) -> Demand | None:
        scores = {Demand.HEAT: 0.0, Demand.COOL: 0.0}
        for member in members:
            demand = self._heads[member.id].demand
            if demand is Demand.HEAT:
                scores[demand] = max(scores[demand], member.set_point_heat.celsius - member.indoor_temperature.celsius)
            elif demand is Demand.COOL:
                scores[demand] = max(scores[demand], member.indoor_temperature.celsius - member.set_point_cool.celsius)
        if scores[Demand.HEAT] == 0 and scores[Demand.COOL] == 0:
            return None
        if scores[Demand.HEAT] == scores[Demand.COOL]:
            return current if current is not None else Demand.HEAT
        return max(scores, key=scores.__getitem__)

    def _set_group_direction(self, group_id: str, direction: Demand, now: datetime) -> None:
        group = self._groups.setdefault(group_id, GroupControl())
        if group.direction is not direction:
            group.direction = direction
            group.direction_since = now
            group.pending_direction = None
            group.off_cycle_pending = False

    async def _async_apply_direction(self, thermostat: DaikinThermostat, direction: Demand | None) -> None:
        if direction is Demand.HEAT:
            applied = await self._async_apply(thermostat, DaikinThermostatMode.HEAT)
            self._heads[thermostat.id].status = (
                EmulationStatus.HEATING if applied else EmulationStatus.WAITING_FOR_HEATING
            )
        elif direction is Demand.COOL:
            applied = await self._async_apply(thermostat, DaikinThermostatMode.COOL)
            self._heads[thermostat.id].status = (
                EmulationStatus.COOLING if applied else EmulationStatus.WAITING_FOR_COOLING
            )

    async def _async_apply(self, thermostat: DaikinThermostat, mode: DaikinThermostatMode) -> bool:
        record = self._heads[thermostat.id]
        effective_mode = record.expected_mode if record.pending_until is not None else thermostat.mode
        if effective_mode is mode:
            return True
        try:
            await self._async_command(thermostat.id, mode)
        except Exception:
            log.exception("Failed to apply emulated mode %s to %s; retrying later", mode, thermostat.id)
            return False
        return True

    async def _async_command(self, thermostat_id: str, mode: DaikinThermostatMode) -> None:
        await self._daikin.set_thermostat_mode(thermostat_id, mode)
        record = self._heads[thermostat_id]
        record.expected_mode = mode
        record.pending_until = self._now() + COMMAND_PROPAGATION_TIME

    def _set_waiting_status(self, member: DaikinThermostat, fallback: EmulationStatus) -> None:
        record = self._heads[member.id]
        record.status = fallback if record.demand is not None else EmulationStatus.IDLE

    def _notification_id(self, group_id: str) -> str:
        safe_group_id = group_id.replace(":", "_")
        return f"{DOMAIN}_{self._entry.entry_id}_{safe_group_id}_emulation_suspended"

    def _create_suspension_notification(
        self,
        notification_id: str,
        group_id: str,
        members: list[DaikinThermostat],
        suspended_ids: list[str],
    ) -> None:
        names = {member.id: member.name for member in members}
        suspended = ", ".join(sorted(names[item] for item in suspended_ids))
        owners = ", ".join(
            sorted(
                member.name
                for member in members
                if self._heads[member.id].logical_mode is not HVACMode.HEAT_COOL
                and self._heads[member.id].logical_mode is not HVACMode.OFF
            )
        )
        heat_pump = self._daikin.get_heat_pumps().get(group_id)
        group_name = heat_pump.name if heat_pump is not None else "Daikin heat pump"
        persistent_notification.async_create(
            self._hass,
            (
                f"{suspended} cannot currently run emulated Heat/Cool because the shared outdoor unit is under "
                f"manual control by {owners}. Emulation will resume automatically when the modes are compatible."
            ),
            title=f"{group_name}: emulation suspended",
            notification_id=notification_id,
        )
        self._notification_ids.add(notification_id)

    def _notify_callbacks(self) -> None:
        for record in self._heads.values():
            record.callback()

    async def async_shutdown(self) -> None:
        """Remove temporary suspension notifications on unload."""
        for notification_id in self._notification_ids:
            persistent_notification.async_dismiss(self._hass, notification_id)
        self._notification_ids.clear()
