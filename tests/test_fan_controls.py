# pyright: reportPrivateUsage=false

import asyncio
from collections.abc import Callable, Iterable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from custom_components.daikinone.const import (
    CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY,
    DOMAIN,
)
from custom_components.daikinone.daikinone import (
    DaikinDeviceDataResponse,
    DaikinOne,
    DaikinThermostat,
    DaikinThermostatCapability,
    DaikinThermostatCirculationMode,
    DaikinThermostatCirculationSpeed,
    DaikinThermostatFanSpeed,
    DaikinThermostatMode,
    DaikinUserCredentials,
)
from custom_components.daikinone.select import (
    DaikinOneCirculationModeSelect,
    DaikinOneCirculationSpeedSelect,
    async_setup_entry,
)


def payload(thermostat_id: str, extra: dict[str, Any]) -> DaikinDeviceDataResponse:
    return DaikinDeviceDataResponse(
        id=thermostat_id,
        locationId="location",
        name=thermostat_id.capitalize(),
        model="DENEB",
        firmware="3.2.0",
        online=True,
        data={
            "iduOnOff": True,
            "iduOperatingMode": DaikinThermostatMode.HEAT.value,
            "iduHeatSetpoint": 20,
            "iduCoolSetpoint": 24,
            **extra,
        },
    )


def map_thermostat(connector: DaikinOne, raw_payload: DaikinDeviceDataResponse) -> DaikinThermostat:
    mapper = cast(
        Callable[[DaikinDeviceDataResponse], DaikinThermostat],
        getattr(connector, "_DaikinOne__map_thermostat"),
    )
    return mapper(raw_payload)


def test_mapper_reads_operating_and_optional_circulation_controls(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = DaikinOne(DaikinUserCredentials("user@example.invalid", "unused"))

    head = map_thermostat(
        connector,
        payload(
            "head",
            {
                "iduHeatFanSpeed": 3,
                "iduCoolFanSpeed": 7,
                "iduAutoFanSpeed": 10,
                "iduDryFanSpeed": 11,
                "iduFanModeFanSpeed": 5,
            },
        ),
    )
    unitary = map_thermostat(connector, payload("unitary", {"fanCirculate": 2, "fanCirculateSpeed": 1}))
    unknown = map_thermostat(connector, payload("future", {"iduHeatFanSpeed": 99}))

    assert head.fan_speeds.heat is DaikinThermostatFanSpeed.LOW
    assert head.fan_speeds.cool is DaikinThermostatFanSpeed.HIGH
    assert head.fan_speeds.auto is DaikinThermostatFanSpeed.AUTO
    assert head.fan_speeds.dry is DaikinThermostatFanSpeed.QUIET
    assert head.fan_speeds.fan is DaikinThermostatFanSpeed.MEDIUM
    assert head.fan_speed_supported_modes == {
        DaikinThermostatMode.HEAT,
        DaikinThermostatMode.COOL,
        DaikinThermostatMode.AUTO,
        DaikinThermostatMode.DRY,
    }
    assert not head.circulation_mode_supported
    assert not head.circulation_speed_supported
    assert unitary.circulation_mode is DaikinThermostatCirculationMode.SCHEDULED
    assert unitary.circulation_speed is DaikinThermostatCirculationSpeed.MEDIUM
    assert unknown.operating_fan_speed_supported
    assert unknown.fan_speeds.heat is None
    assert "Ignoring unsupported iduHeatFanSpeed value 99" in caplog.text


@pytest.mark.parametrize(
    ("extra", "supported"),
    [
        ({}, False),
        ({"ctSystemCapEmergencyHeat": False}, False),
        ({"ctSystemCapEmergencyHeat": True}, True),
        ({"modeEmHeatAvailable": True}, True),
    ],
)
def test_mapper_only_advertises_emergency_heat_when_reported(extra: dict[str, Any], supported: bool) -> None:
    connector = DaikinOne(DaikinUserCredentials("user@example.invalid", "unused"))

    mapped = map_thermostat(connector, payload("head", extra))

    assert (DaikinThermostatCapability.EMERGENCY_HEAT in mapped.capabilities) is supported
    assert DaikinThermostatCapability.HEAT in mapped.capabilities
    assert DaikinThermostatCapability.COOL in mapped.capabilities


def test_select_setup_gates_circulation_controls_and_removes_stale_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = DaikinOne(DaikinUserCredentials("user@example.invalid", "unused"))
    mini_split = map_thermostat(connector, payload("mini", {"iduHeatFanSpeed": 10}))
    unitary = map_thermostat(connector, payload("unitary", {"fanCirculate": 0, "fanCirculateSpeed": 2}))

    class FakeConnector:
        def get_thermostats(self) -> dict[str, Any]:
            return {mini_split.id: mini_split, unitary.id: unitary}

    class FakeRegistry:
        removed: list[str] = []

        def async_get_entity_id(self, platform: Any, domain: str, unique_id: str) -> str | None:
            del platform
            assert domain == DOMAIN
            return "select.mini_fan_speed" if unique_id == "mini-fan_speed" else None

        def async_remove(self, entity_id: str) -> None:
            self.removed.append(entity_id)

    registry = FakeRegistry()

    def get_registry(hass: HomeAssistant) -> FakeRegistry:
        del hass
        return registry

    monkeypatch.setattr("custom_components.daikinone.select.er.async_get", get_registry)
    data = SimpleNamespace(
        daikin=FakeConnector(),
        entry=SimpleNamespace(data={CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY: 1}),
    )
    hass = cast(HomeAssistant, SimpleNamespace(data={DOMAIN: data}))
    entities: list[Entity] = []

    def add_entities(new_entities: Iterable[Entity], update_before_add: bool = False) -> None:
        del update_before_add
        entities.extend(new_entities)

    asyncio.run(async_setup_entry(hass, cast(ConfigEntry, SimpleNamespace()), add_entities))

    assert [type(entity) for entity in entities] == [
        DaikinOneCirculationModeSelect,
        DaikinOneCirculationSpeedSelect,
    ]
    assert [entity.unique_id for entity in entities] == [
        "unitary-circulation_mode",
        "unitary-fan_speed",
    ]
    assert registry.removed == ["select.mini_fan_speed"]
