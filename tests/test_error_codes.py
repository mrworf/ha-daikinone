# pyright: reportPrivateUsage=false

import asyncio
from collections.abc import Callable, Iterable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from custom_components.daikinone.binary_sensor import (
    DaikinOneThermostatProblemBinarySensor,
    async_setup_entry as async_setup_binary_sensors,
)
from custom_components.daikinone.const import CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY, DOMAIN
from custom_components.daikinone.daikinone import (
    DaikinDeviceDataResponse,
    DaikinOne,
    DaikinThermostat,
    DaikinUserCredentials,
)
from custom_components.daikinone.error_codes import error_description, normalize_error_code
from custom_components.daikinone.sensor import (
    DaikinOneThermostatSensor,
    async_setup_entry as async_setup_sensors,
)


def _map_thermostat(error_code: Any) -> DaikinThermostat:
    connector = DaikinOne(DaikinUserCredentials("user@example.invalid", "unused"))
    mapper = cast(
        Callable[[DaikinDeviceDataResponse], DaikinThermostat],
        getattr(connector, "_DaikinOne__map_thermostat"),
    )
    return mapper(
        DaikinDeviceDataResponse(
            id=f"head-{error_code}",
            locationId="location",
            name="Bedroom",
            model="DENEB",
            firmware="3.2.0",
            online=True,
            data={
                "iduErrorCode": error_code,
                "iduRoomTemp": 22,
                "iduRoomHum": 40,
                "iduHeatSetpoint": 20,
                "iduCoolSetpoint": 24,
                "iduAutoSetpoint": 22,
            },
        )
    )


@pytest.mark.parametrize("value", [None, "", "00", "00-00", 0, "0-0"])
def test_no_error_values_are_blank(value: Any) -> None:
    assert normalize_error_code(value) is None


def test_mapper_preserves_full_error_code_and_decodes_main_code() -> None:
    thermostat = _map_thermostat("U4-00")

    assert thermostat.error_code == "U4-00"
    assert error_description(thermostat.error_code) == "Communication malfunction between indoor and outdoor unit"
    assert error_description("u4-01") == "Communication malfunction between indoor and outdoor unit"
    assert error_description("ZZ-99") == "Unknown Daikin error code"


def test_error_entities_show_problem_and_leave_clear_text_sensors_blank() -> None:
    faulted = _map_thermostat("U4-00")
    clear = _map_thermostat("00-00")

    class FakeConnector:
        def get_heat_pumps(self) -> dict[str, Any]:
            return {}

        def get_thermostats(self) -> dict[str, DaikinThermostat]:
            return {faulted.id: faulted, clear.id: clear}

        def get_thermostat(self, thermostat_id: str) -> DaikinThermostat:
            return self.get_thermostats()[thermostat_id]

    data = SimpleNamespace(
        daikin=FakeConnector(),
        entry=SimpleNamespace(data={CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY: 1}),
    )
    hass = cast(HomeAssistant, SimpleNamespace(data={DOMAIN: data}))
    entities: list[Entity] = []

    def add_entities(new_entities: Iterable[Entity], update_before_add: bool = False) -> None:
        del update_before_add
        entities.extend(new_entities)

    asyncio.run(async_setup_sensors(hass, cast(ConfigEntry, SimpleNamespace()), add_entities))
    asyncio.run(async_setup_binary_sensors(hass, cast(ConfigEntry, SimpleNamespace()), add_entities))

    text_sensors = [entity for entity in entities if isinstance(entity, DaikinOneThermostatSensor)]
    for sensor in text_sensors:
        sensor.update_entity_attributes()

    def text_sensor(device: DaikinThermostat, key: str) -> DaikinOneThermostatSensor:
        return next(
            sensor for sensor in text_sensors if sensor._device.id == device.id and sensor.entity_description.key == key
        )

    assert text_sensor(faulted, "error_code").native_value == "U4-00"
    assert (
        text_sensor(faulted, "error_description").native_value
        == "Communication malfunction between indoor and outdoor unit"
    )
    assert text_sensor(clear, "error_code").native_value == ""
    assert text_sensor(clear, "error_description").native_value == ""

    problem_entities = [entity for entity in entities if isinstance(entity, DaikinOneThermostatProblemBinarySensor)]
    faulted_problem = next(entity for entity in problem_entities if entity._device.id == faulted.id)
    clear_problem = next(entity for entity in problem_entities if entity._device.id == clear.id)
    assert faulted_problem.is_on is True
    assert faulted_problem.extra_state_attributes == {
        "error_code": "U4-00",
        "description": "Communication malfunction between indoor and outdoor unit",
    }
    assert clear_problem.is_on is False
    assert clear_problem.extra_state_attributes == {}
