import asyncio
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any, cast

from homeassistant.components.sensor.const import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from custom_components.daikinone.const import DOMAIN
from custom_components.daikinone.daikinone import (
    DaikinDeviceDataResponse,
    DaikinHeatPump,
    DaikinOne,
    DaikinUserCredentials,
    discover_heat_pump_groups,
)
from custom_components.daikinone.sensor import DaikinOneHeatPumpSensor, async_setup_entry


def _payload(
    thermostat_id: str,
    name: str,
    connected: int,
    energy: float,
    power: float,
    *,
    frequency: float,
    fan_speed: float,
    discharge: float,
    outdoor_temperature: float,
    online: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "iduHeatSetpoint": 20,
        "iduCoolSetpoint": 24,
        "oduConnectedIduUnitNumber": connected,
        "oduConsumedPower": power,
        "oduIntPowerConsumption": energy,
        "oduOperatingMode": 2,
        "oduOutdoorTemp": outdoor_temperature,
        "oduCompCurrentFrequency": frequency,
        "oduFanMotorCurrentSpeed": fan_speed,
        "oduCompDischargeTemp": discharge,
        "oduCompTargetDischargeTemp": 35,
    }
    data.update(extra or {})
    return {
        "id": thermostat_id,
        "locationId": "location",
        "name": name,
        "model": "DENEB",
        "firmware": "3.2.0",
        "online": online,
        "data": data,
    }


def _six_head_payloads() -> list[dict[str, Any]]:
    return [
        _payload("living", "Living room", 4, 1629.7, 0, frequency=0, fan_speed=0, discharge=19, outdoor_temperature=15),
        _payload(
            "bath",
            "Master Bathroom",
            3,
            577.5,
            170,
            frequency=10,
            fan_speed=510,
            discharge=29,
            outdoor_temperature=15.5,
        ),
        _payload(
            "kira", "Kira's bedroom", 3, 591.4, 120, frequency=10, fan_speed=540, discharge=26, outdoor_temperature=15.5
        ),
        _payload("study", "Study", 3, 577.0, 160, frequency=10, fan_speed=510, discharge=28, outdoor_temperature=15.5),
        _payload("dining", "Dining room", 4, 1631.9, 0, frequency=0, fan_speed=0, discharge=19, outdoor_temperature=15),
        _payload(
            "master", "Master Bedroom", 4, 1626.8, 0, frequency=0, fan_speed=0, discharge=19, outdoor_temperature=15
        ),
    ]


def _connector(payloads: list[dict[str, Any]], groups: list[dict[str, Any]] | None = None) -> DaikinOne:
    connector = DaikinOne(DaikinUserCredentials("user@example.invalid", "unused"), heat_pump_groups=groups)

    async def request(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return payloads

    connector._DaikinOne__req = request  # type: ignore[attr-defined]
    return connector


def test_discovers_two_heat_pumps_and_aggregates_power() -> None:
    connector = _connector(_six_head_payloads())
    asyncio.run(connector.update())

    heat_pumps = connector.get_heat_pumps()
    assert len(heat_pumps) == 2
    assert {heat_pump.thermostat_ids for heat_pump in heat_pumps.values()} == {
        ("bath", "kira", "study"),
        ("dining", "living", "master"),
    }

    active = next(heat_pump for heat_pump in heat_pumps.values() if "bath" in heat_pump.thermostat_ids)
    assert active.power_usage == 160
    assert active.energy_source_id == "kira"
    assert active.energy_consumption == 591.4

    for thermostat in connector.get_thermostats().values():
        assert thermostat.heat_pump_id in heat_pumps


def test_persisted_groups_do_not_regroup_when_telemetry_changes() -> None:
    first = _connector(_six_head_payloads())
    asyncio.run(first.update())
    groups = first.get_heat_pump_groups()

    changed = _six_head_payloads()
    for payload in changed:
        payload["data"]["oduConnectedIduUnitNumber"] = 1
        payload["data"]["oduIntPowerConsumption"] = 100
        payload["data"]["oduConsumedPower"] = 50

    restored = _connector(changed, groups)
    asyncio.run(restored.update())

    assert restored.get_heat_pump_groups() == groups
    assert {heat_pump.thermostat_ids for heat_pump in restored.get_heat_pumps().values()} == {
        ("bath", "kira", "study"),
        ("dining", "living", "master"),
    }


def test_missing_or_legacy_outdoor_data_is_not_discovered() -> None:
    missing = _payload("missing", "Missing", 1, 1, 1, frequency=1, fan_speed=1, discharge=1, outdoor_temperature=1)
    del missing["data"]["oduIntPowerConsumption"]
    legacy = _payload(
        "legacy",
        "Legacy",
        1,
        1,
        1,
        frequency=1,
        fan_speed=1,
        discharge=1,
        outdoor_temperature=1,
        extra={"ctOutdoorUnitType": 1},
    )

    responses = [DaikinDeviceDataResponse(**payload) for payload in (missing, legacy)]
    assert discover_heat_pump_groups(responses) == []


def test_energy_source_offline_does_not_switch_counters() -> None:
    first = _connector(_six_head_payloads())
    asyncio.run(first.update())
    groups = first.get_heat_pump_groups()

    changed = _six_head_payloads()
    next(payload for payload in changed if payload["id"] == "kira")["online"] = False
    restored = _connector(changed, groups)
    asyncio.run(restored.update())

    active = next(heat_pump for heat_pump in restored.get_heat_pumps().values() if "bath" in heat_pump.thermostat_ids)
    assert active.power_usage == 165
    assert active.energy_consumption is None


def test_heat_pump_sensor_metadata() -> None:
    heat_pump = DaikinHeatPump(
        id="heat-pump-id",
        name="Heat Pump 1",
        model="Mini-split Heat Pump",
        firmware_version="",
        location_id="location",
        thermostat_ids=("head",),
        energy_source_id="head",
        power_usage=123,
        energy_consumption=456.7,
    )

    class FakeConnector:
        def get_heat_pumps(self) -> dict[str, DaikinHeatPump]:
            return {heat_pump.id: heat_pump}

        def get_thermostats(self) -> dict[str, Any]:
            return {}

    hass = cast(HomeAssistant, SimpleNamespace(data={DOMAIN: SimpleNamespace(daikin=FakeConnector())}))
    entities: list[Any] = []

    def add_entities(new_entities: Iterable[Entity], update_before_add: bool = False) -> None:
        entities.extend(new_entities)

    asyncio.run(async_setup_entry(hass, cast(ConfigEntry, SimpleNamespace()), add_entities))

    assert len(entities) == 2
    power = next(entity for entity in entities if entity.entity_description.key == "power_usage")
    energy = next(entity for entity in entities if entity.entity_description.key == "energy_consumption")
    assert isinstance(power, DaikinOneHeatPumpSensor)
    assert power.unique_id == "heat-pump-id-power_usage"
    assert power.device_class is SensorDeviceClass.POWER
    assert power.state_class is SensorStateClass.MEASUREMENT
    assert power.native_unit_of_measurement == UnitOfPower.WATT
    assert energy.device_class is SensorDeviceClass.ENERGY
    assert energy.state_class is SensorStateClass.TOTAL_INCREASING
    assert energy.native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR
