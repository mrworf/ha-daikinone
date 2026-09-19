"""Adaptive external-temperature control for Daikin heads."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import logging
from typing import Any, cast

from homeassistant.components.climate.const import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.core import Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_OPTION_EXTERNAL_TEMPERATURE_CONTROLS,
    DEFAULT_EXTERNAL_TEMPERATURE_MAX_BIAS,
    DOMAIN,
    EXTERNAL_TEMPERATURE_ADJUSTMENT_MINUTES,
    EXTERNAL_TEMPERATURE_BIAS_STEP,
    EXTERNAL_TEMPERATURE_DEADBAND,
    EXTERNAL_TEMPERATURE_STALE_MINUTES,
)
from .daikinone import DaikinOne, DaikinThermostat, DaikinThermostatMode
from .utils import Temperature

log = logging.getLogger(__name__)

STORE_VERSION = 1
COMMAND_PROPAGATION_TIME = timedelta(seconds=45)


class ExternalTemperatureStatus(StrEnum):
    """Observable adaptive-controller status."""

    MONITORING = "monitoring"
    ADAPTING_HEAT = "adapting_heat"
    ADAPTING_COOL = "adapting_cool"
    WAITING_FOR_SENSOR = "waiting_for_sensor"
    STALE_SENSOR = "stale_sensor"
    LIMITED = "limited"
    ERROR = "error"


@dataclass(frozen=True)
class ExternalTemperatureConfig:
    """Configuration for one controlled head."""

    thermostat_id: str
    sensor_entity_id: str
    max_bias: float = DEFAULT_EXTERNAL_TEMPERATURE_MAX_BIAS
    humidity_sensor_entity_id: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ExternalTemperatureConfig:
        """Deserialize an options entry."""
        return cls(
            thermostat_id=str(value["thermostat_id"]),
            sensor_entity_id=str(value["sensor_entity_id"]),
            max_bias=float(value.get("max_bias", DEFAULT_EXTERNAL_TEMPERATURE_MAX_BIAS)),
            humidity_sensor_entity_id=(
                str(value["humidity_sensor_entity_id"]) if value.get("humidity_sensor_entity_id") else None
            ),
        )

    def as_dict(self) -> dict[str, str | float]:
        """Serialize an options entry."""
        result: dict[str, str | float] = {
            "thermostat_id": self.thermostat_id,
            "sensor_entity_id": self.sensor_entity_id,
            "max_bias": self.max_bias,
        }
        if self.humidity_sensor_entity_id is not None:
            result["humidity_sensor_entity_id"] = self.humidity_sensor_entity_id
        return result


@dataclass
class AdaptiveHeadState:
    """Persisted and transient adaptive state for one head."""

    logical_heat: float
    logical_cool: float
    heat_bias: float = 0.0
    cool_bias: float = 0.0
    error_sign: int = 0
    error_since: datetime | None = None
    last_evaluated: datetime | None = None
    last_adjusted: datetime | None = None
    status: ExternalTemperatureStatus = ExternalTemperatureStatus.MONITORING
    limited: bool = False
    expected_heat: float | None = None
    expected_cool: float | None = None
    pending_until: datetime | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any], thermostat: DaikinThermostat) -> AdaptiveHeadState:
        """Deserialize state, using live setpoints for missing fields."""
        return cls(
            logical_heat=float(value.get("logical_heat", thermostat.set_point_heat.celsius)),
            logical_cool=float(value.get("logical_cool", thermostat.set_point_cool.celsius)),
            heat_bias=float(value.get("heat_bias", 0.0)),
            cool_bias=float(value.get("cool_bias", 0.0)),
            last_evaluated=_parse_datetime(value.get("last_evaluated")),
            last_adjusted=_parse_datetime(value.get("last_adjusted")),
        )

    def as_dict(self) -> dict[str, str | float | None]:
        """Serialize durable state."""
        return {
            "logical_heat": self.logical_heat,
            "logical_cool": self.logical_cool,
            "heat_bias": self.heat_bias,
            "cool_bias": self.cool_bias,
            "last_evaluated": self.last_evaluated.isoformat() if self.last_evaluated else None,
            "last_adjusted": self.last_adjusted.isoformat() if self.last_adjusted else None,
        }


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _round_half(value: float) -> float:
    return round(value * 2) / 2


class ExternalTemperatureController:
    """Continuously adapt Daikin setpoints from optional HA sensors."""

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
        self._now = now or (lambda: datetime.now(UTC))
        self._configs = {
            config.thermostat_id: config
            for raw in entry.options.get(CONF_OPTION_EXTERNAL_TEMPERATURE_CONTROLS, [])
            if isinstance(raw, dict)
            for config in [ExternalTemperatureConfig.from_dict(cast(dict[str, Any], raw))]
        }
        self._heads: dict[str, AdaptiveHeadState] = {}
        self._cleanup: dict[str, AdaptiveHeadState] = {}
        self._callbacks: dict[str, Callable[[], None]] = {}
        self._unsubscribers: list[Callable[[], None]] = []
        self._demand_reconciler: Callable[[], Awaitable[None]] | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.external_temperature",
        )
        self._initialized = False

    async def async_initialize(self) -> None:
        """Load durable state and subscribe to sensor/timer changes."""
        stored = await self._store.async_load() or {}
        stored_heads_value = cast(object, stored.get("heads", {}))
        stored_heads = cast(dict[str, object], stored_heads_value) if isinstance(stored_heads_value, dict) else {}
        thermostats = self._daikin.get_thermostats()
        for thermostat_id in self._configs:
            thermostat = thermostats.get(thermostat_id)
            if thermostat is None:
                continue
            raw = stored_heads.get(thermostat_id, {})
            self._heads[thermostat_id] = AdaptiveHeadState.from_dict(
                cast(dict[str, Any], raw) if isinstance(raw, dict) else {}, thermostat
            )
            head = self._heads[thermostat_id]
            head.expected_heat, head.expected_cool = self.physical_targets(thermostat)

        cleanup_value = cast(object, stored.get("cleanup", {}))
        cleanup = cast(dict[str, object], cleanup_value) if isinstance(cleanup_value, dict) else {}
        removed_ids = (set(stored_heads) | set(cleanup)) - set(self._configs)
        for thermostat_id in removed_ids:
            thermostat = thermostats.get(thermostat_id)
            raw = cleanup.get(thermostat_id, stored_heads.get(thermostat_id, {}))
            if thermostat is not None and isinstance(raw, dict):
                self._cleanup[thermostat_id] = AdaptiveHeadState.from_dict(cast(dict[str, Any], raw), thermostat)

        sensor_ids = {config.sensor_entity_id for config in self._configs.values()}
        humidity_sensor_ids = {
            config.humidity_sensor_entity_id
            for config in self._configs.values()
            if config.humidity_sensor_entity_id is not None
        }
        if sensor_ids:
            self._unsubscribers.append(
                async_track_state_change_event(self._hass, sensor_ids, self._async_sensor_changed)
            )
        if humidity_sensor_ids:
            self._unsubscribers.append(
                async_track_state_change_event(self._hass, humidity_sensor_ids, self._async_humidity_changed)
            )
        if sensor_ids or humidity_sensor_ids or self._cleanup:
            self._unsubscribers.append(
                async_track_time_interval(self._hass, self._async_periodic_update, timedelta(minutes=1))
            )
        self._initialized = True
        await self.async_reconcile()

    def register(self, thermostat_id: str, callback: Callable[[], None]) -> None:
        """Register a climate entity callback."""
        self._callbacks[thermostat_id] = callback

    def set_demand_reconciler(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Arrange for emulated demand to be refreshed before adaptive learning."""
        self._demand_reconciler = callback

    def unregister(self, thermostat_id: str) -> None:
        """Unregister a climate entity callback."""
        self._callbacks.pop(thermostat_id, None)

    def configured(self, thermostat_id: str) -> bool:
        return thermostat_id in self._configs and thermostat_id in self._heads

    def config(self, thermostat_id: str) -> ExternalTemperatureConfig | None:
        return self._configs.get(thermostat_id)

    def state(self, thermostat_id: str) -> AdaptiveHeadState | None:
        return self._heads.get(thermostat_id)

    def logical_heat(self, thermostat: DaikinThermostat) -> float:
        state = self._heads.get(thermostat.id)
        return state.logical_heat if state is not None else thermostat.set_point_heat.celsius

    def logical_cool(self, thermostat: DaikinThermostat) -> float:
        state = self._heads.get(thermostat.id)
        return state.logical_cool if state is not None else thermostat.set_point_cool.celsius

    def external_temperature(self, thermostat_id: str) -> float | None:
        """Return a valid configured sensor reading converted to Celsius."""
        config = self._configs.get(thermostat_id)
        if config is None:
            return None
        sensor_state = self._hass.states.get(config.sensor_entity_id)
        if sensor_state is None or sensor_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        last_updated = getattr(sensor_state, "last_updated", None)
        if isinstance(last_updated, datetime):
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=UTC)
            if self._now() - last_updated > timedelta(minutes=EXTERNAL_TEMPERATURE_STALE_MINUTES):
                return None
        try:
            value = float(sensor_state.state)
        except (TypeError, ValueError):
            return None
        attributes = cast(
            dict[str, Any],
            cast(object, sensor_state.attributes),  # pyright: ignore[reportUnknownMemberType]
        )
        unit = attributes.get("unit_of_measurement")
        if isinstance(unit, str) and unit != UnitOfTemperature.CELSIUS:
            try:
                value = TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
            except ValueError:
                return None
        return value

    def effective_temperature(self, thermostat: DaikinThermostat) -> float | None:
        """Return the fresh external reading, falling back to the head sensor."""
        external = self.external_temperature(thermostat.id)
        if external is not None:
            return external
        return thermostat.indoor_temperature.celsius if thermostat.indoor_temperature_valid else None

    def external_humidity(self, thermostat_id: str) -> int | None:
        """Return a fresh, valid configured humidity reading."""
        config = self._configs.get(thermostat_id)
        if config is None or config.humidity_sensor_entity_id is None:
            return None
        sensor_state = self._hass.states.get(config.humidity_sensor_entity_id)
        if sensor_state is None or sensor_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        last_updated = getattr(sensor_state, "last_updated", None)
        if isinstance(last_updated, datetime):
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=UTC)
            if self._now() - last_updated > timedelta(minutes=EXTERNAL_TEMPERATURE_STALE_MINUTES):
                return None
        try:
            value = float(sensor_state.state)
        except (TypeError, ValueError):
            return None
        return round(value) if 0 <= value <= 100 else None

    def physical_targets(self, thermostat: DaikinThermostat) -> tuple[float, float]:
        """Return bounded physical heat and cool targets."""
        state = self._heads.get(thermostat.id)
        config = self._configs.get(thermostat.id)
        if state is None or config is None:
            return thermostat.set_point_heat.celsius, thermostat.set_point_cool.celsius
        heat_bias = max(-config.max_bias, min(config.max_bias, state.heat_bias))
        cool_bias = max(-config.max_bias, min(config.max_bias, state.cool_bias))
        heat = max(
            thermostat.set_point_heat_min.celsius,
            min(thermostat.set_point_heat_max.celsius, state.logical_heat + heat_bias),
        )
        cool = max(
            thermostat.set_point_cool_min.celsius,
            min(thermostat.set_point_cool_max.celsius, state.logical_cool + cool_bias),
        )
        return _round_half(heat), _round_half(cool)

    async def async_set_logical_targets(
        self,
        thermostat_id: str,
        *,
        heat: float | None = None,
        cool: float | None = None,
    ) -> None:
        """Save logical targets and send their current physical equivalents."""
        state = self._heads[thermostat_id]
        if heat is not None:
            state.logical_heat = heat
        if cool is not None:
            state.logical_cool = cool
        thermostat = self._daikin.get_thermostat(thermostat_id)
        physical_heat, physical_cool = self.physical_targets(thermostat)
        await self._daikin.set_thermostat_home_set_points(
            thermostat_id,
            heat=Temperature.from_celsius(physical_heat) if heat is not None else None,
            cool=Temperature.from_celsius(physical_cool) if cool is not None else None,
            override_schedule=False,
        )
        if heat is not None:
            state.expected_heat = physical_heat
        if cool is not None:
            state.expected_cool = physical_cool
        state.pending_until = self._now() + COMMAND_PROPAGATION_TIME
        self._schedule_save()
        self._notify(thermostat_id)

    async def async_reconcile(self) -> None:
        """Evaluate every configured head and apply due bias changes."""
        if not self._initialized:
            return
        now = self._now()
        await self._async_cleanup_removed()
        for thermostat_id, state in self._heads.items():
            thermostat = self._daikin.get_thermostat(thermostat_id)
            try:
                if thermostat.schedule.enabled:
                    await self._daikin.set_thermostat_schedule_enabled(thermostat_id, False)
                    thermostat.schedule.enabled = False
                self._adopt_manual_setpoints(thermostat, state, now)
            except Exception:
                log.exception("Failed to prepare external-temperature control for %s", thermostat_id)
                state.status = ExternalTemperatureStatus.ERROR
                self._notify(thermostat_id)
                continue
            external = self.external_temperature(thermostat_id)
            state.last_evaluated = now
            if external is None:
                state.status = (
                    ExternalTemperatureStatus.STALE_SENSOR
                    if self._sensor_is_stale(thermostat_id)
                    else ExternalTemperatureStatus.WAITING_FOR_SENSOR
                )
                state.error_sign = 0
                state.error_since = None
                self._notify(thermostat_id)
                continue

            if thermostat.mode is DaikinThermostatMode.HEAT:
                await self._async_evaluate_direction(thermostat, HVACMode.HEAT, state.logical_heat - external, now)
            elif thermostat.mode is DaikinThermostatMode.COOL:
                await self._async_evaluate_direction(thermostat, HVACMode.COOL, state.logical_cool - external, now)
            else:
                state.status = ExternalTemperatureStatus.MONITORING
                state.limited = False
                state.error_sign = 0
                state.error_since = None
                self._notify(thermostat_id)
        self._schedule_save()

    def _sensor_is_stale(self, thermostat_id: str) -> bool:
        config = self._configs.get(thermostat_id)
        sensor_state = self._hass.states.get(config.sensor_entity_id) if config is not None else None
        last_updated = getattr(sensor_state, "last_updated", None)
        if not isinstance(last_updated, datetime):
            return False
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=UTC)
        return self._now() - last_updated > timedelta(minutes=EXTERNAL_TEMPERATURE_STALE_MINUTES)

    def _adopt_manual_setpoints(self, thermostat: DaikinThermostat, state: AdaptiveHeadState, now: datetime) -> None:
        """Turn confirmed out-of-band physical changes into new logical targets."""
        if state.pending_until is not None and now < state.pending_until:
            return
        reported_heat = thermostat.set_point_heat.celsius
        reported_cool = thermostat.set_point_cool.celsius
        if state.expected_heat is not None and abs(reported_heat - state.expected_heat) > 0.01:
            state.logical_heat = _round_half(
                max(
                    thermostat.set_point_heat_min.celsius,
                    min(thermostat.set_point_heat_max.celsius, reported_heat - state.heat_bias),
                )
            )
        if state.expected_cool is not None and abs(reported_cool - state.expected_cool) > 0.01:
            state.logical_cool = _round_half(
                max(
                    thermostat.set_point_cool_min.celsius,
                    min(thermostat.set_point_cool_max.celsius, reported_cool - state.cool_bias),
                )
            )
        state.expected_heat = reported_heat
        state.expected_cool = reported_cool
        state.pending_until = None

    async def _async_cleanup_removed(self) -> None:
        """Restore unbiased logical targets for heads removed from configuration."""
        for thermostat_id, state in list(self._cleanup.items()):
            try:
                await self._daikin.set_thermostat_home_set_points(
                    thermostat_id,
                    heat=Temperature.from_celsius(state.logical_heat),
                    cool=Temperature.from_celsius(state.logical_cool),
                    override_schedule=False,
                )
            except Exception:
                log.exception("Failed to remove external-temperature bias from %s; retrying later", thermostat_id)
                continue
            self._cleanup.pop(thermostat_id)

    async def _async_evaluate_direction(
        self,
        thermostat: DaikinThermostat,
        direction: HVACMode,
        error: float,
        now: datetime,
    ) -> None:
        state = self._heads[thermostat.id]
        if abs(error) <= EXTERNAL_TEMPERATURE_DEADBAND:
            state.status = ExternalTemperatureStatus.MONITORING
            state.limited = False
            state.error_sign = 0
            state.error_since = None
            self._notify(thermostat.id)
            return

        sign = 1 if error > 0 else -1
        if state.error_sign != sign or state.error_since is None:
            state.error_sign = sign
            state.error_since = now
            state.status = (
                ExternalTemperatureStatus.ADAPTING_HEAT
                if direction is HVACMode.HEAT
                else ExternalTemperatureStatus.ADAPTING_COOL
            )
            state.limited = False
            self._notify(thermostat.id)
            return
        if now - state.error_since < timedelta(minutes=EXTERNAL_TEMPERATURE_ADJUSTMENT_MINUTES):
            self._notify(thermostat.id)
            return

        config = self._configs[thermostat.id]
        old_physical = self.physical_targets(thermostat)
        old_heat_bias = state.heat_bias
        old_cool_bias = state.cool_bias
        if direction is HVACMode.HEAT:
            candidate = max(
                -config.max_bias, min(config.max_bias, state.heat_bias + sign * EXTERNAL_TEMPERATURE_BIAS_STEP)
            )
            state.heat_bias = _round_half(candidate)
        else:
            candidate = max(
                -config.max_bias, min(config.max_bias, state.cool_bias + sign * EXTERNAL_TEMPERATURE_BIAS_STEP)
            )
            state.cool_bias = _round_half(candidate)
        new_physical = self.physical_targets(thermostat)
        state.error_since = now
        state.limited = new_physical == old_physical
        if state.limited:
            state.heat_bias = old_heat_bias
            state.cool_bias = old_cool_bias
            state.status = ExternalTemperatureStatus.LIMITED
            self._notify(thermostat.id)
            return

        if direction is HVACMode.HEAT:
            await self._daikin.set_thermostat_home_set_points(
                thermostat.id,
                heat=Temperature.from_celsius(new_physical[0]),
                override_schedule=False,
            )
            state.expected_heat = new_physical[0]
        else:
            await self._daikin.set_thermostat_home_set_points(
                thermostat.id,
                cool=Temperature.from_celsius(new_physical[1]),
                override_schedule=False,
            )
            state.expected_cool = new_physical[1]
        state.pending_until = now + COMMAND_PROPAGATION_TIME
        state.last_adjusted = now
        state.limited = False
        self._notify(thermostat.id)

    async def _async_sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        del event
        if self._demand_reconciler is not None:
            await self._demand_reconciler()
        await self.async_reconcile()

    async def _async_periodic_update(self, now: datetime) -> None:
        del now
        if self._demand_reconciler is not None:
            await self._demand_reconciler()
        await self.async_reconcile()

    async def _async_humidity_changed(self, event: Event[EventStateChangedData]) -> None:
        """Publish humidity changes without reevaluating temperature bias."""
        entity_id = event.data.get("entity_id")
        for thermostat_id, config in self._configs.items():
            if config.humidity_sensor_entity_id == entity_id:
                self._notify(thermostat_id)

    def _notify(self, thermostat_id: str) -> None:
        callback = self._callbacks.get(thermostat_id)
        if callback is not None:
            callback()

    def _schedule_save(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "heads": {thermostat_id: state.as_dict() for thermostat_id, state in self._heads.items()},
                "cleanup": {thermostat_id: state.as_dict() for thermostat_id, state in self._cleanup.items()},
            },
            60,
        )

    async def async_shutdown(self) -> None:
        """Remove runtime subscriptions and flush durable state."""
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        if self._heads or self._cleanup:
            await self._store.async_save(
                {
                    "heads": {thermostat_id: state.as_dict() for thermostat_id, state in self._heads.items()},
                    "cleanup": {thermostat_id: state.as_dict() for thermostat_id, state in self._cleanup.items()},
                }
            )
