"""Binary sensors for Daikin equipment."""

from collections.abc import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.daikinone import DOMAIN, DaikinOneData
from custom_components.daikinone.const import CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY
from custom_components.daikinone.daikinone import DaikinHeatPump, DaikinThermostat
from custom_components.daikinone.entity import DaikinOneEntity
from custom_components.daikinone.error_codes import error_description


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daikin binary sensors."""
    data: DaikinOneData = hass.data[DOMAIN]
    entities: list[BinarySensorEntity] = [
        DaikinOneHeatPumpBinarySensor(
            description=BinarySensorEntityDescription(
                key="defrost",
                name="Defrost",
                has_entity_name=True,
                device_class=BinarySensorDeviceClass.RUNNING,
                icon="mdi:snowflake-melt",
            ),
            data=data,
            device=heat_pump,
            attribute=lambda item: item.defrost,
        )
        for heat_pump in data.daikin.get_heat_pumps().values()
    ]
    entities.extend(
        DaikinOneThermostatProblemBinarySensor(
            description=BinarySensorEntityDescription(
                key="equipment_problem",
                name="Equipment Problem",
                has_entity_name=True,
                device_class=BinarySensorDeviceClass.PROBLEM,
                entity_category=EntityCategory.DIAGNOSTIC,
                icon="mdi:alert-circle-outline",
            ),
            data=data,
            device=thermostat,
        )
        for thermostat in data.daikin.get_thermostats().values()
    )
    async_add_entities(entities, True)


class DaikinOneHeatPumpBinarySensor(DaikinOneEntity[DaikinHeatPump], BinarySensorEntity):
    """A binary sensor attached to a grouped mini-split heat pump."""

    def __init__(
        self,
        description: BinarySensorEntityDescription,
        data: DaikinOneData,
        device: DaikinHeatPump,
        attribute: Callable[[DaikinHeatPump], bool | None],
    ) -> None:
        super().__init__(data, device)
        self.entity_description = description
        self._attribute = attribute
        self._attr_unique_id = f"{self._device.id}-{self.entity_description.key}"
        self.update_entity_attributes()

    async def async_get_device(self) -> DaikinHeatPump:
        return self._data.daikin.get_heat_pump(self._device.id)

    def update_entity_attributes(self) -> None:
        value = self._attribute(self._device)
        self._attr_is_on = value
        self._attr_available = value is not None


class DaikinOneThermostatProblemBinarySensor(DaikinOneEntity[DaikinThermostat], BinarySensorEntity):
    """Report an equipment fault on an indoor head."""

    def __init__(
        self,
        description: BinarySensorEntityDescription,
        data: DaikinOneData,
        device: DaikinThermostat,
    ) -> None:
        super().__init__(data, device)
        self.entity_description = description
        match data.entry.data[CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY]:
            case 0:
                self._attr_unique_id = f"{self._device.id}-{self.name}"
            case 1:
                self._attr_unique_id = f"{self._device.id}-{self.entity_description.key}"
            case _:
                raise ValueError("unexpected entity uid schema version")
        self.update_entity_attributes()

    async def async_get_device(self) -> DaikinThermostat:
        return self._data.daikin.get_thermostat(self._device.id)

    def update_entity_attributes(self) -> None:
        self._attr_is_on = self._device.error_code is not None
        self._attr_available = self._device.online
        self._attr_extra_state_attributes = (
            {
                "error_code": self._device.error_code,
                "description": error_description(self._device.error_code),
            }
            if self._device.error_code is not None
            else {}
        )
