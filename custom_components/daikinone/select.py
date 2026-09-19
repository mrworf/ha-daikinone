from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.daikinone import DOMAIN, DaikinOneData
from custom_components.daikinone.const import CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY
from custom_components.daikinone.daikinone import (
    DaikinThermostat,
    DaikinThermostatCirculationMode,
    DaikinThermostatCirculationSpeed,
)
from custom_components.daikinone.entity import DaikinOneEntity


CIRCULATION_MODE_OPTIONS = {
    "Off": DaikinThermostatCirculationMode.OFF,
    "Always On": DaikinThermostatCirculationMode.ALWAYS_ON,
    "Scheduled": DaikinThermostatCirculationMode.SCHEDULED,
}
CIRCULATION_SPEED_OPTIONS = {
    "Low": DaikinThermostatCirculationSpeed.LOW,
    "Medium": DaikinThermostatCirculationSpeed.MEDIUM,
    "High": DaikinThermostatCirculationSpeed.HIGH,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daikin One circulation select entities."""
    data: DaikinOneData = hass.data[DOMAIN]
    entities: list[SelectEntity] = []
    registry = er.async_get(hass)

    for thermostat in data.daikin.get_thermostats().values():
        if thermostat.circulation_mode_supported:
            entities.append(
                DaikinOneCirculationModeSelect(
                    SelectEntityDescription(
                        key="circulation_mode",
                        name="Circulation Mode",
                        has_entity_name=True,
                        icon="mdi:fan-clock",
                        options=list(CIRCULATION_MODE_OPTIONS),
                    ),
                    data,
                    thermostat,
                )
            )

        if thermostat.circulation_speed_supported:
            entities.append(
                DaikinOneCirculationSpeedSelect(
                    SelectEntityDescription(
                        key="fan_speed",
                        name="Circulation Speed",
                        has_entity_name=True,
                        icon="mdi:fan",
                        options=list(CIRCULATION_SPEED_OPTIONS),
                    ),
                    data,
                    thermostat,
                )
            )
        elif (
            stale_entity_id := registry.async_get_entity_id(Platform.SELECT, DOMAIN, f"{thermostat.id}-fan_speed")
        ) is not None:
            registry.async_remove(stale_entity_id)

    async_add_entities(entities, True)


class DaikinOneCirculationSelect(DaikinOneEntity[DaikinThermostat], SelectEntity):
    """Base class for optional unitary-system circulation controls."""

    def __init__(
        self,
        description: SelectEntityDescription,
        data: DaikinOneData,
        thermostat: DaikinThermostat,
    ) -> None:
        super().__init__(data, thermostat)
        self.entity_description = description

        match data.entry.data[CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY]:
            case 0 | 1:
                self._attr_unique_id = f"{self._device.id}-{description.key}"
            case _:
                raise ValueError("unexpected entity uid schema version")

    @property
    def device_name(self) -> str:
        return f"{self._device.name} Thermostat"

    async def async_get_device(self) -> DaikinThermostat:
        return self._data.daikin.get_thermostat(self._device.id)


class DaikinOneCirculationModeSelect(DaikinOneCirculationSelect):
    """Select the unitary thermostat circulation policy."""

    async def async_select_option(self, option: str) -> None:
        if (target := CIRCULATION_MODE_OPTIONS.get(option)) is None:
            raise ValueError(f"Attempted to set unsupported circulation mode: {option}")

        def update(thermostat: DaikinThermostat) -> None:
            thermostat.circulation_mode = target

        await self.update_state_optimistically(
            operation=lambda: self._data.daikin.set_thermostat_circulation_mode(self._device.id, target),
            optimistic_update=update,
            check=lambda thermostat: thermostat.circulation_mode == target,
        )

    def update_entity_attributes(self) -> None:
        self._attr_current_option = next(
            (label for label, mode in CIRCULATION_MODE_OPTIONS.items() if mode is self._device.circulation_mode),
            None,
        )


class DaikinOneCirculationSpeedSelect(DaikinOneCirculationSelect):
    """Select the unitary thermostat circulation speed."""

    async def async_select_option(self, option: str) -> None:
        if (target := CIRCULATION_SPEED_OPTIONS.get(option)) is None:
            raise ValueError(f"Attempted to set unsupported circulation speed: {option}")

        def update(thermostat: DaikinThermostat) -> None:
            thermostat.circulation_speed = target

        await self.update_state_optimistically(
            operation=lambda: self._data.daikin.set_thermostat_circulation_speed(self._device.id, target),
            optimistic_update=update,
            check=lambda thermostat: thermostat.circulation_speed == target,
        )

    def update_entity_attributes(self) -> None:
        self._attr_current_option = next(
            (label for label, speed in CIRCULATION_SPEED_OPTIONS.items() if speed is self._device.circulation_speed),
            None,
        )
