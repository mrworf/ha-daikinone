from enum import Enum
import logging
from typing import Any, cast

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
)
from homeassistant.components.climate.const import (
    HVACMode,
    ClimateEntityFeature,
    HVACAction,
    ATTR_TARGET_TEMP_LOW,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_HVAC_MODE,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.daikinone import DaikinOneData, DOMAIN
from custom_components.daikinone.entity import DaikinOneEntity
from custom_components.daikinone.daikinone import (
    DaikinThermostat,
    DaikinThermostatCapability,
    DaikinThermostatMode,
    DaikinThermostatStatus,
    DaikinThermostatFanSpeed,
    DaikinThermostatSwingMode,
)
from custom_components.daikinone.utils import Temperature

log = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daikin One thermostats"""
    data: DaikinOneData = hass.data[DOMAIN]

    entities = [
        DaikinOneThermostat(
            ClimateEntityDescription(key=device.id, has_entity_name=True, name=None),
            data,
            device,
        )
        for device in data.daikin.get_thermostats().values()
    ]

    async_add_entities(entities, True)


class DaikinOneThermostatPresetMode(Enum):
    NONE = "none"
    EMERGENCY_HEAT = "emergency_heat"


class DaikinOneThermostatFanMode(Enum):
    AUTO = "auto"
    QUIET = "quiet"
    LOW = "low"
    MEDIUM_LOW = "medium low"
    MEDIUM = "medium"
    MEDIUM_HIGH = "medium high"
    HIGH = "high"


FAN_MODE_TO_SPEED = {fan_mode.value: DaikinThermostatFanSpeed[fan_mode.name] for fan_mode in DaikinOneThermostatFanMode}
FAN_SPEED_TO_MODE = {speed: fan_mode for fan_mode, speed in FAN_MODE_TO_SPEED.items()}


class DaikinOneThermostatSwingMode(Enum):
    FIXED = "fixed"
    OSCILLATE = "oscillate"


SWING_MODE_TO_DAIKIN = {
    swing_mode.value: DaikinThermostatSwingMode[swing_mode.name] for swing_mode in DaikinOneThermostatSwingMode
}
DAIKIN_TO_SWING_MODE = {mode: name for name, mode in SWING_MODE_TO_DAIKIN.items()}


class DaikinOneThermostat(DaikinOneEntity[DaikinThermostat], ClimateEntity):
    """Thermostat entity for Daikin One"""

    # to be removed in a future version of HA
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        description: ClimateEntityDescription,
        data: DaikinOneData,
        thermostat: DaikinThermostat,
    ):
        super().__init__(data, thermostat)

        self.entity_description = description

        self._attr_translation_key = "daikinone_thermostat"
        self._attr_unique_id = f"{self._device.id}-climate"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._base_supported_features = (
            ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE  # It's a lie
        )
        self._attr_supported_features = self._base_supported_features
        self._attr_hvac_modes = self.get_hvac_modes()
        self._attr_fan_modes = [m.value for m in DaikinOneThermostatFanMode]
        self._attr_swing_modes = [m.value for m in DaikinOneThermostatSwingMode]

        # These attributes must be initialized otherwise HA `CachedProperties` doesn't create a
        # backing prop. If they are not initialized, climate will error during setup because we support
        # TARGET_TEMPERATURE_RANGE and it tries to read them. These attributes are not initialized in
        # `ClimateEntity` like most others, and in a case where the thermostat is not set to auto,
        # they do not get set in async_update either.
        self._attr_target_temperature_low = None
        self._attr_target_temperature_high = None

        # Set up preset modes based on thermostat capabilities. The preset climate feature will only be
        # enabled if at least one preset is detected as supported.
        self._attr_preset_modes = [DaikinOneThermostatPresetMode.NONE.value]
        self._attr_preset_mode = None

        if DaikinThermostatCapability.EMERGENCY_HEAT in self._device.capabilities:
            self._base_supported_features |= ClimateEntityFeature.PRESET_MODE
            self._attr_supported_features = self._base_supported_features
            self._attr_preset_modes += [DaikinOneThermostatPresetMode.EMERGENCY_HEAT.value]

        self._data.emulation.register(thermostat, self._controller_updated)
        self._data.external_temperature.register(thermostat.id, self._external_controller_updated)

    async def async_added_to_hass(self) -> None:
        """Restore logical emulation state after the entity is added."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                logical_mode = HVACMode(last_state.state)
            except ValueError:
                logical_mode = None
            attributes = cast(dict[str, Any], last_state.attributes)  # pyright: ignore[reportUnknownMemberType]
            previous_physical = cast(object, attributes.get("emulation_physical_mode"))
            physical_mode: DaikinThermostatMode | None = None
            try:
                if isinstance(previous_physical, (int, str)):
                    physical_mode = DaikinThermostatMode(int(previous_physical))
            except ValueError:
                pass
            if logical_mode is not None:
                self._data.emulation.restore(self._device.id, logical_mode, physical_mode)
                self.update_entity_attributes()

    async def async_will_remove_from_hass(self) -> None:
        """Remove controller callbacks when the entity unloads."""
        self._data.emulation.unregister(self._device.id)
        self._data.external_temperature.unregister(self._device.id)
        await super().async_will_remove_from_hass()

    def _controller_updated(self) -> None:
        """Publish logical/controller state after a group reconciliation."""
        self._device = self._data.daikin.get_thermostat(self._device.id)
        self.update_entity_attributes()
        if getattr(self, "entity_id", None):
            self.async_write_ha_state()

    def _external_controller_updated(self) -> None:
        """Publish adaptive external-temperature state."""
        self._device = self._data.daikin.get_thermostat(self._device.id)
        self.update_entity_attributes()
        if getattr(self, "entity_id", None):
            self.async_write_ha_state()

    def get_hvac_modes(self) -> list[HVACMode]:
        modes: list[HVACMode] = []

        if (
            DaikinThermostatCapability.HEAT in self._device.capabilities
            and DaikinThermostatCapability.COOL in self._device.capabilities
            and self._data.emulation.supports_emulation(self._device)
        ):
            modes.append(HVACMode.HEAT_COOL)

        if DaikinThermostatCapability.HEAT in self._device.capabilities:
            modes.append(HVACMode.HEAT)
        if DaikinThermostatCapability.COOL in self._device.capabilities:
            modes.append(HVACMode.COOL)

        modes.append(HVACMode.AUTO)  # This is used for when Daikin is in full auto

        modes.append(HVACMode.OFF)

        return modes

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        target_mode: DaikinThermostatMode
        match hvac_mode:
            case HVACMode.HEAT_COOL:
                if HVACMode.HEAT_COOL not in self.hvac_modes:
                    raise ServiceValidationError(
                        "Emulated Heat/Cool requires a resolved heat-pump assignment",
                        translation_domain=DOMAIN,
                        translation_key="unassigned_heat_pump",
                    )
                await self._data.emulation.async_set_logical_mode(self._device.id, hvac_mode)
                self._device = self._data.daikin.get_thermostat(self._device.id)
                self.update_entity_attributes()
                if getattr(self, "entity_id", None):
                    self.async_write_ha_state()
                return
            case HVACMode.AUTO:
                target_mode = DaikinThermostatMode.AUTO
            case HVACMode.HEAT:
                target_mode = DaikinThermostatMode.HEAT
            case HVACMode.COOL:
                target_mode = DaikinThermostatMode.COOL
            case HVACMode.OFF:
                target_mode = DaikinThermostatMode.OFF
            case _:
                raise ValueError(f"Attempted to set unsupported HVAC mode: {hvac_mode}")

        await self.set_thermostat_mode(target_mode)

    async def set_thermostat_mode(self, target_mode: DaikinThermostatMode) -> None:
        log.debug("Setting thermostat mode to %s", target_mode)

        # update thermostat mode optimistically
        def update(t: DaikinThermostat):
            t.mode = target_mode

        await self.update_state_optimistically(
            operation=lambda: self._data.emulation.async_set_manual_mode(self._device.id, target_mode),
            optimistic_update=update,
            check=lambda t: t.mode == target_mode,
        )

    async def async_turn_on(self) -> None:
        """Restore the previous logical non-Off mode."""
        await self.async_set_hvac_mode(self._data.emulation.previous_mode(self._device.id))

    async def async_turn_off(self) -> None:
        """Turn off physical and emulated control."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_preset_mode(self, preset_mode: str):
        """Set new target preset mode."""
        match preset_mode:

            case DaikinOneThermostatPresetMode.EMERGENCY_HEAT.value:
                await self.set_thermostat_mode(DaikinThermostatMode.AUX_HEAT)

            case DaikinOneThermostatPresetMode.NONE.value:
                match self._device.mode:

                    # turning off emergency heat should set the thermostat mode to heat
                    case DaikinThermostatMode.AUX_HEAT:
                        await self.set_thermostat_mode(DaikinThermostatMode.HEAT)

                    # any other thermostat mode should already be "none", and if its not,
                    # we don't need to do anything
                    case _:
                        pass

            case _:
                raise ValueError(f"Attempted to set unsupported preset mode: {preset_mode}")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature(s)."""

        temperature = kwargs.get(ATTR_TEMPERATURE)
        target_temp_low = kwargs.get(ATTR_TARGET_TEMP_LOW)
        target_temp_high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)

        logical_mode = self._data.emulation.logical_mode(self._device.id)
        if hvac_mode is HVACMode.HEAT_COOL or (hvac_mode is None and logical_mode is HVACMode.HEAT_COOL):
            if target_temp_low is None or target_temp_high is None or target_temp_low >= target_temp_high:
                raise ServiceValidationError(
                    "Emulated Heat/Cool requires a valid low and high target",
                    translation_domain=DOMAIN,
                    translation_key="invalid_temperature_range",
                )
            heat = Temperature.from_celsius(target_temp_low)
            cool = Temperature.from_celsius(target_temp_high)

            if self._data.external_temperature.configured(self._device.id):
                await self._data.external_temperature.async_set_logical_targets(
                    self._device.id,
                    heat=heat.celsius,
                    cool=cool.celsius,
                )
                self._device = self._data.daikin.get_thermostat(self._device.id)
                if hvac_mode is HVACMode.HEAT_COOL:
                    await self.async_set_hvac_mode(HVACMode.HEAT_COOL)
                else:
                    await self._data.emulation.async_reconcile()
                self.update_entity_attributes()
                return

            def update_range(t: DaikinThermostat) -> None:
                t.set_point_heat = heat
                t.set_point_cool = cool

            await self.update_state_optimistically(
                operation=lambda: self._data.daikin.set_thermostat_home_set_points(
                    self._device.id,
                    heat=heat,
                    cool=cool,
                    override_schedule=self._device.schedule.enabled,
                ),
                optimistic_update=update_range,
                check=lambda t: t.set_point_heat == heat and t.set_point_cool == cool,
            )
            if hvac_mode is HVACMode.HEAT_COOL:
                await self.async_set_hvac_mode(HVACMode.HEAT_COOL)
            else:
                await self._data.emulation.async_reconcile()
            return

        if hvac_mode:
            await self.async_set_hvac_mode(hvac_mode)

        if target_temp_low or target_temp_high:
            heat = Temperature.from_celsius(target_temp_low) if target_temp_low is not None else None
            cool = Temperature.from_celsius(target_temp_high) if target_temp_high is not None else None

            # TODO: take min temp delta into account

            log.debug("Setting thermostat set points: heat=%s and cool=%s", heat, cool)

            # update set points optimistically
            def update(t: DaikinThermostat):
                if heat is not None:
                    t.set_point_heat = heat
                if cool is not None:
                    t.set_point_cool = cool

            await self.update_state_optimistically(
                operation=lambda: self._data.daikin.set_thermostat_home_set_points(
                    self._device.id,
                    heat=heat,
                    cool=cool,
                    override_schedule=self._device.schedule.enabled,
                ),
                optimistic_update=update,
                check=lambda t: t.set_point_heat == heat and t.set_point_cool == cool,
            )

        elif temperature is not None:
            # setting a single temperature is only valid if the thermostat is in a mode that allows us to infer whether
            # it is a heat or cool set point
            temperature = Temperature.from_celsius(temperature)

            if self._data.external_temperature.configured(self._device.id):
                if self._device.mode is DaikinThermostatMode.HEAT:
                    await self._data.external_temperature.async_set_logical_targets(
                        self._device.id, heat=temperature.celsius
                    )
                    self._device = self._data.daikin.get_thermostat(self._device.id)
                    self.update_entity_attributes()
                    return
                if self._device.mode is DaikinThermostatMode.COOL:
                    await self._data.external_temperature.async_set_logical_targets(
                        self._device.id, cool=temperature.celsius
                    )
                    self._device = self._data.daikin.get_thermostat(self._device.id)
                    self.update_entity_attributes()
                    return

            match self._device.mode:
                case DaikinThermostatMode.HEAT | DaikinThermostatMode.AUX_HEAT:
                    log.debug("Setting thermostat set point: heat=%s ", temperature)

                    # update set points optimistically
                    def update(t: DaikinThermostat):
                        t.set_point_heat = temperature

                    await self.update_state_optimistically(
                        operation=lambda: self._data.daikin.set_thermostat_home_set_points(
                            self._device.id,
                            heat=temperature,
                        ),
                        optimistic_update=update,
                        check=lambda t: t.set_point_heat == temperature,
                    )

                case DaikinThermostatMode.COOL:
                    log.debug("Setting thermostat set point: cool=%s ", temperature)

                    # update set points optimistically
                    def update(t: DaikinThermostat):
                        t.set_point_cool = temperature

                    await self.update_state_optimistically(
                        operation=lambda: self._data.daikin.set_thermostat_home_set_points(
                            self._device.id,
                            cool=temperature,
                        ),
                        optimistic_update=update,
                        check=lambda t: t.set_point_cool == temperature,
                    )

                case DaikinThermostatMode.AUTO:
                    log.debug("Setting thermostat set point: auto=%s ", temperature)

                    def update(t: DaikinThermostat):
                        t.set_point_auto = temperature

                    await self.update_state_optimistically(
                        operation=lambda: self._data.daikin.set_thermostat_home_set_points(
                            self._device.id,
                            auto=temperature,
                        ),
                        optimistic_update=update,
                        check=lambda t: t.set_point_auto == temperature,
                    )

                case _:
                    raise ValueError("Invalid thermostat mode and set temperature combination")
        else:
            raise ValueError("Set temperature called with no temperature values")

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the operating fan speed for the active logical mode."""
        if (target_fan_speed := FAN_MODE_TO_SPEED.get(fan_mode)) is None:
            raise ValueError(f"Attempted to set unsupported fan mode: {fan_mode}")
        modes = self._fan_speed_modes()
        if not modes or not modes.issubset(self._device.fan_speed_supported_modes):
            raise ValueError("Operating fan speed is unavailable in the current mode")

        def update(t: DaikinThermostat) -> None:
            for mode in modes:
                setattr(t.fan_speeds, mode.name.lower(), target_fan_speed)

        await self.update_state_optimistically(
            operation=lambda: self._data.daikin.set_thermostat_fan_speed(self._device.id, target_fan_speed, modes),
            optimistic_update=update,
            check=lambda t: all(getattr(t.fan_speeds, mode.name.lower()) == target_fan_speed for mode in modes),
        )

    def _fan_speed_modes(self) -> set[DaikinThermostatMode]:
        """Return physical modes controlled by the current logical mode."""
        if self._data.emulation.logical_mode(self._device.id) is HVACMode.HEAT_COOL:
            return {DaikinThermostatMode.HEAT, DaikinThermostatMode.COOL}
        if self._device.mode in {
            DaikinThermostatMode.HEAT,
            DaikinThermostatMode.COOL,
            DaikinThermostatMode.AUTO,
        }:
            return {self._device.mode}
        return set()

    def _current_fan_speed(self) -> DaikinThermostatFanSpeed | None:
        """Resolve the speed shown for the active or emulated operating mode."""
        if self._data.emulation.logical_mode(self._device.id) is HVACMode.HEAT_COOL:
            physical_mode = self._data.emulation.expected_physical_mode(self._device.id)
            if physical_mode in {DaikinThermostatMode.HEAT, DaikinThermostatMode.COOL}:
                return getattr(self._device.fan_speeds, physical_mode.name.lower())
            if self._device.fan_speeds.heat == self._device.fan_speeds.cool:
                return self._device.fan_speeds.heat
            return None
        if self._device.mode in {
            DaikinThermostatMode.HEAT,
            DaikinThermostatMode.COOL,
            DaikinThermostatMode.AUTO,
        }:
            return getattr(self._device.fan_speeds, self._device.mode.name.lower())
        return None

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set vertical vane behavior for the active logical mode."""
        if (target_swing_mode := SWING_MODE_TO_DAIKIN.get(swing_mode)) is None:
            raise ValueError(f"Attempted to set unsupported swing mode: {swing_mode}")
        modes = self._swing_mode_modes()
        if not modes or not modes.issubset(self._device.swing_mode_supported_modes):
            raise ValueError("Swing mode is unavailable in the current mode")

        def update(t: DaikinThermostat) -> None:
            for mode in modes:
                setattr(t.swing_modes, mode.name.lower(), target_swing_mode)

        await self.update_state_optimistically(
            operation=lambda: self._data.daikin.set_thermostat_swing_mode(self._device.id, target_swing_mode, modes),
            optimistic_update=update,
            check=lambda t: all(getattr(t.swing_modes, mode.name.lower()) == target_swing_mode for mode in modes),
        )

    def _swing_mode_modes(self) -> set[DaikinThermostatMode]:
        """Return physical modes controlled by the current logical mode."""
        if self._data.emulation.logical_mode(self._device.id) is HVACMode.HEAT_COOL:
            return {DaikinThermostatMode.HEAT, DaikinThermostatMode.COOL}
        if self._device.mode in {
            DaikinThermostatMode.HEAT,
            DaikinThermostatMode.COOL,
            DaikinThermostatMode.AUTO,
        }:
            return {self._device.mode}
        return set()

    def _current_swing_mode(self) -> DaikinThermostatSwingMode | None:
        """Resolve the vertical vane behavior for the logical mode."""
        if self._data.emulation.logical_mode(self._device.id) is HVACMode.HEAT_COOL:
            physical_mode = self._data.emulation.expected_physical_mode(self._device.id)
            if physical_mode in {DaikinThermostatMode.HEAT, DaikinThermostatMode.COOL}:
                return getattr(self._device.swing_modes, physical_mode.name.lower())
            if self._device.swing_modes.heat == self._device.swing_modes.cool:
                return self._device.swing_modes.heat
            return None
        if self._device.mode in {
            DaikinThermostatMode.HEAT,
            DaikinThermostatMode.COOL,
            DaikinThermostatMode.AUTO,
        }:
            return getattr(self._device.swing_modes, self._device.mode.name.lower())
        return None

    async def async_get_device(self) -> DaikinThermostat:
        return self._data.daikin.get_thermostat(self._device.id)

    def update_entity_attributes(self) -> None:
        self._attr_available = self._device.online
        logical_mode = self._data.emulation.logical_mode(self._device.id)
        external_temperature = self._data.external_temperature.external_temperature(self._device.id)
        self._attr_current_temperature = (
            external_temperature
            if self._data.external_temperature.configured(self._device.id) and external_temperature is not None
            else self._device.indoor_temperature.celsius
        )
        external_humidity = self._data.external_temperature.external_humidity(self._device.id)
        self._attr_current_humidity = (
            external_humidity
            if self._data.external_temperature.configured(self._device.id) and external_humidity is not None
            else self._device.indoor_humidity
        )

        # hvac current mode and preset
        self._attr_preset_mode = DaikinOneThermostatPresetMode.NONE.value
        if logical_mode is HVACMode.HEAT_COOL:
            self._attr_hvac_mode = HVACMode.HEAT_COOL
        else:
            match self._device.mode:
                case DaikinThermostatMode.AUTO:
                    self._attr_hvac_mode = HVACMode.AUTO
                case DaikinThermostatMode.HEAT:
                    self._attr_hvac_mode = HVACMode.HEAT
                case DaikinThermostatMode.COOL:
                    self._attr_hvac_mode = HVACMode.COOL
                case DaikinThermostatMode.AUX_HEAT:
                    self._attr_hvac_mode = HVACMode.HEAT
                    self._attr_preset_mode = DaikinOneThermostatPresetMode.EMERGENCY_HEAT.value
                case DaikinThermostatMode.OFF:
                    self._attr_hvac_mode = HVACMode.OFF
                case DaikinThermostatMode.DRY:
                    # DRY is not currently advertised as a supported Home Assistant mode.
                    pass

        # hvac current action
        match self._device.status:
            case DaikinThermostatStatus.HEATING:
                self._attr_hvac_action = HVACAction.HEATING
            case DaikinThermostatStatus.COOLING:
                self._attr_hvac_action = HVACAction.COOLING
            case DaikinThermostatStatus.CIRCULATING_AIR:
                self._attr_hvac_action = HVACAction.FAN
            case DaikinThermostatStatus.DRYING:
                self._attr_hvac_action = HVACAction.DRYING
            case DaikinThermostatStatus.IDLE:
                self._attr_hvac_action = HVACAction.IDLE

        # target temperature

        # reset target temperature attributes first, single target temp takes precedence and can conflict with range
        self._attr_target_temperature = None
        self._attr_target_temperature_low = None
        self._attr_target_temperature_high = None

        if logical_mode is HVACMode.HEAT_COOL:
            self._attr_target_temperature_low = self._data.external_temperature.logical_heat(self._device)
            self._attr_target_temperature_high = self._data.external_temperature.logical_cool(self._device)
        else:
            match self._device.mode:
                case DaikinThermostatMode.HEAT | DaikinThermostatMode.AUX_HEAT:
                    self._attr_target_temperature = (
                        self._data.external_temperature.logical_heat(self._device)
                        if self._device.mode is DaikinThermostatMode.HEAT
                        else self._device.set_point_heat.celsius
                    )
                case DaikinThermostatMode.COOL:
                    self._attr_target_temperature = self._data.external_temperature.logical_cool(self._device)
                case DaikinThermostatMode.AUTO:
                    self._attr_target_temperature = self._device.set_point_auto.celsius
                case _:
                    pass

        emulation_status = self._data.emulation.status(self._device.id)
        self._attr_extra_state_attributes = {
            "emulation_physical_mode": self._data.emulation.expected_physical_mode(self._device.id).value,
        }
        if emulation_status is not None:
            self._attr_extra_state_attributes["emulation_status"] = emulation_status.value

        external_state = self._data.external_temperature.state(self._device.id)
        external_config = self._data.external_temperature.config(self._device.id)
        if external_state is not None and external_config is not None:
            physical_heat, physical_cool = self._data.external_temperature.physical_targets(self._device)
            self._attr_extra_state_attributes.update(
                {
                    "internal_temperature": self._device.indoor_temperature.celsius,
                    "external_temperature_sensor": external_config.sensor_entity_id,
                    "external_temperature": external_temperature,
                    "external_humidity_sensor": external_config.humidity_sensor_entity_id,
                    "external_humidity": external_humidity,
                    "external_control_status": external_state.status.value,
                    "heating_bias": external_state.heat_bias,
                    "cooling_bias": external_state.cool_bias,
                    "physical_heat_target": physical_heat,
                    "physical_cool_target": physical_cool,
                    "bias_last_evaluated": (
                        external_state.last_evaluated.isoformat() if external_state.last_evaluated else None
                    ),
                    "bias_last_adjusted": (
                        external_state.last_adjusted.isoformat() if external_state.last_adjusted else None
                    ),
                    "setpoint_limited": external_state.limited,
                }
            )

        # temperature bounds
        # these should be the same but just in case, take the larger of the two for the min
        self._attr_min_temp = max(
            self._device.set_point_heat_min.celsius,
            self._device.set_point_cool_min.celsius,
        )
        # these should be the same but just in case, take the smaller of the two for the max
        self._attr_max_temp = min(
            self._device.set_point_heat_max.celsius,
            self._device.set_point_cool_max.celsius,
        )

        # The climate fan control is the head unit's operating speed, not its
        # separate unitary-system circulation policy.
        fan_speed_modes = self._fan_speed_modes()
        fan_speed_available = bool(fan_speed_modes) and fan_speed_modes.issubset(self._device.fan_speed_supported_modes)
        self._attr_supported_features = self._base_supported_features
        if fan_speed_available:
            self._attr_supported_features |= ClimateEntityFeature.FAN_MODE
        current_fan_speed = self._current_fan_speed() if fan_speed_available else None
        self._attr_fan_mode = FAN_SPEED_TO_MODE.get(current_fan_speed) if current_fan_speed is not None else None

        swing_mode_modes = self._swing_mode_modes()
        swing_mode_available = bool(swing_mode_modes) and swing_mode_modes.issubset(
            self._device.swing_mode_supported_modes
        )
        if swing_mode_available:
            self._attr_supported_features |= ClimateEntityFeature.SWING_MODE
        current_swing_mode = self._current_swing_mode() if swing_mode_available else None
        self._attr_swing_mode = DAIKIN_TO_SWING_MODE.get(current_swing_mode) if current_swing_mode is not None else None
