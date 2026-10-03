"""Binary sensors for grouped Daikin heat pumps."""

from collections.abc import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.daikinone import DOMAIN, DaikinOneData
from custom_components.daikinone.daikinone import DaikinHeatPump
from custom_components.daikinone.entity import DaikinOneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up grouped heat-pump binary sensors."""
    data: DaikinOneData = hass.data[DOMAIN]
    async_add_entities(
        [
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
        ],
        True,
    )


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
