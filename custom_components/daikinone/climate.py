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
    FAN_OFF,
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
    DaikinThermostatFanMode,
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
    OFF = FAN_OFF
    ALWAYS_ON = "always_on"
    SCHEDULED = "schedule"


class DaikinOneThermostatFanSpeed(Enum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2


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
        self._attr_supported_features = (
            ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE  # It's a lie
            | ClimateEntityFeature.FAN_MODE
        )
        self._attr_hvac_modes = self.get_hvac_modes()
        self._attr_fan_modes = [m.value for m in DaikinOneThermostatFanMode]

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
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
            self._attr_preset_modes += [DaikinOneThermostatPresetMode.EMERGENCY_HEAT.value]

        self._data.emulation.register(thermostat, self._controller_updated)

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
        await super().async_will_remove_from_hass()

    def _controller_updated(self) -> None:
        """Publish logical/controller state after a group reconciliation."""
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
        target_fan_mode: DaikinThermostatFanMode
        match fan_mode:
            case DaikinOneThermostatFanMode.OFF.value:
                target_fan_mode = DaikinThermostatFanMode.OFF
            case DaikinOneThermostatFanMode.ALWAYS_ON.value:
                target_fan_mode = DaikinThermostatFanMode.ALWAYS_ON
            case DaikinOneThermostatFanMode.SCHEDULED.value:
                target_fan_mode = DaikinThermostatFanMode.SCHEDULED
            case _:
                raise ValueError(f"Attempted to set unsupported fan mode: {fan_mode}")

        # update fan mode optimistically
        def update(t: DaikinThermostat):
            t.fan_mode = target_fan_mode

        await self.update_state_optimistically(
            operation=lambda: self._data.daikin.set_thermostat_fan_mode(self._device.id, target_fan_mode),
            optimistic_update=update,
            check=lambda t: t.fan_mode == target_fan_mode,
        )

    async def async_get_device(self) -> DaikinThermostat:
        return self._data.daikin.get_thermostat(self._device.id)

    def update_entity_attributes(self) -> None:
        self._attr_available = self._device.online
        self._attr_current_temperature = self._device.indoor_temperature.celsius
        self._attr_current_humidity = self._device.indoor_humidity

        # hvac current mode and preset
        self._attr_preset_mode = DaikinOneThermostatPresetMode.NONE.value
        logical_mode = self._data.emulation.logical_mode(self._device.id)
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
            self._attr_target_temperature_low = self._device.set_point_heat.celsius
            self._attr_target_temperature_high = self._device.set_point_cool.celsius
        else:
            match self._device.mode:
                case DaikinThermostatMode.HEAT | DaikinThermostatMode.AUX_HEAT:
                    self._attr_target_temperature = self._device.set_point_heat.celsius
                case DaikinThermostatMode.COOL:
                    self._attr_target_temperature = self._device.set_point_cool.celsius
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

        # fan settings
        match self._device.fan_mode:
            case DaikinThermostatFanMode.OFF:
                self._attr_fan_mode = DaikinOneThermostatFanMode.OFF.value
            case DaikinThermostatFanMode.ALWAYS_ON:
                self._attr_fan_mode = DaikinOneThermostatFanMode.ALWAYS_ON.value
            case DaikinThermostatFanMode.SCHEDULED:
                self._attr_fan_mode = DaikinOneThermostatFanMode.SCHEDULED.value
