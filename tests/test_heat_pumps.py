# pyright: reportPrivateUsage=false

import asyncio
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor.const import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    REVOLUTIONS_PER_MINUTE,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from custom_components.daikinone import _update_heat_pump_grouping_issue
from custom_components.daikinone.binary_sensor import (
    DaikinOneHeatPumpBinarySensor,
    async_setup_entry as async_setup_binary_sensors,
)
from custom_components.daikinone.config_flow import (
    CONF_DELETE_GROUP,
    CONF_GROUP_ID,
    CONF_GROUP_MEMBERS,
    CONF_GROUP_NAME,
    DaikinOneOptionsFlow,
    validate_heat_pump_group,
)
from custom_components.daikinone.const import (
    CONF_OPTION_HEAT_PUMP_GROUPS_KEY,
    CONF_OPTION_HEAT_PUMP_GROUPS_SCHEMA_VERSION_KEY,
    DOMAIN,
    HEAT_PUMP_GROUPS_SCHEMA_VERSION,
)
from custom_components.daikinone.daikinone import (
    DaikinDeviceDataResponse,
    DaikinHeatPump,
    DaikinHeatPumpGroup,
    DaikinHeatPumpOperatingState,
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
    current: float = 0,
    defrost: bool = False,
    outdoor_mode: int = 2,
    online: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "iduHeatSetpoint": 20,
        "iduCoolSetpoint": 24,
        "oduConnectedIduUnitNumber": connected,
        "oduConsumedPower": power,
        "oduIntPowerConsumption": energy,
        "oduOperatingMode": outdoor_mode,
        "oduOutdoorTemp": outdoor_temperature,
        "oduConsumedCurrent": current,
        "oduDefrost": defrost,
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
            current=0.7,
        ),
        _payload(
            "kira",
            "Kira's bedroom",
            3,
            591.4,
            120,
            frequency=10,
            fan_speed=540,
            discharge=26,
            outdoor_temperature=15.5,
            current=0.5,
        ),
        _payload(
            "study",
            "Study",
            3,
            577.0,
            160,
            frequency=10,
            fan_speed=510,
            discharge=28,
            outdoor_temperature=15.5,
            current=0.6,
        ),
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


def _group(*thermostat_ids: str) -> dict[str, Any]:
    return DaikinHeatPumpGroup(
        id="heat-pump",
        name="Heat Pump",
        location_id="location",
        thermostat_ids=thermostat_ids,
        energy_source_id=thermostat_ids[0],
    ).as_dict()


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
    assert active.outdoor_temperature == 15.5
    assert active.operating_state is DaikinHeatPumpOperatingState.COOLING
    assert active.defrost is False
    assert active.compressor_frequency == 10
    assert active.outdoor_fan_speed == 510
    assert active.current == 0.6

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


@pytest.mark.parametrize(
    ("power", "frequency", "outdoor_mode", "defrost", "expected"),
    [
        (0, 0, 1, False, DaikinHeatPumpOperatingState.IDLE),
        (900, 30, 1, False, DaikinHeatPumpOperatingState.HEATING),
        (900, 30, 2, False, DaikinHeatPumpOperatingState.COOLING),
        (0, 0, 1, True, DaikinHeatPumpOperatingState.DEFROSTING),
        (900, 30, 9, False, DaikinHeatPumpOperatingState.UNKNOWN),
    ],
)
def test_heat_pump_operating_state(
    power: float,
    frequency: float,
    outdoor_mode: int,
    defrost: bool,
    expected: DaikinHeatPumpOperatingState,
) -> None:
    payload = _payload(
        "head",
        "Head",
        1,
        10,
        power,
        frequency=frequency,
        fan_speed=500,
        discharge=30,
        outdoor_temperature=12,
        outdoor_mode=outdoor_mode,
        defrost=defrost,
    )
    connector = _connector([payload], [_group("head")])

    asyncio.run(connector.update())

    assert connector.get_heat_pump("heat-pump").operating_state is expected


def test_active_conflicting_directions_report_unknown() -> None:
    heating = _payload(
        "heat",
        "Heat",
        2,
        10,
        900,
        frequency=30,
        fan_speed=500,
        discharge=30,
        outdoor_temperature=12,
        outdoor_mode=1,
    )
    cooling = _payload(
        "cool",
        "Cool",
        2,
        11,
        900,
        frequency=30,
        fan_speed=500,
        discharge=30,
        outdoor_temperature=12,
        outdoor_mode=2,
    )
    connector = _connector([heating, cooling], [_group("heat", "cool")])

    asyncio.run(connector.update())

    assert connector.get_heat_pump("heat-pump").operating_state is DaikinHeatPumpOperatingState.UNKNOWN


def test_optional_telemetry_uses_valid_online_members() -> None:
    first = _payload(
        "first",
        "First",
        3,
        10,
        800,
        frequency=20,
        fan_speed=500,
        discharge=30,
        outdoor_temperature=10,
        current=4,
        defrost=False,
        outdoor_mode=1,
    )
    second = _payload(
        "second",
        "Second",
        3,
        11,
        1000,
        frequency=40,
        fan_speed=700,
        discharge=30,
        outdoor_temperature=14,
        current=6,
        defrost=True,
        outdoor_mode=1,
    )
    missing = _payload(
        "missing",
        "Missing",
        3,
        12,
        5000,
        frequency=99,
        fan_speed=999,
        discharge=30,
        outdoor_temperature=30,
        current=99,
        defrost=True,
        outdoor_mode=2,
        online=False,
    )
    first["data"].pop("oduDefrost")
    first["data"].pop("oduConsumedCurrent")
    connector = _connector([first, second, missing], [_group("first", "second", "missing")])

    asyncio.run(connector.update())
    heat_pump = connector.get_heat_pump("heat-pump")

    assert heat_pump.outdoor_temperature == 12
    assert heat_pump.compressor_frequency == 30
    assert heat_pump.outdoor_fan_speed == 600
    assert heat_pump.current == 6
    assert heat_pump.defrost is True
    assert heat_pump.operating_state is DaikinHeatPumpOperatingState.DEFROSTING


def test_all_offline_heat_pump_readings_are_unavailable() -> None:
    payload = _payload(
        "offline",
        "Offline",
        1,
        10,
        900,
        frequency=30,
        fan_speed=500,
        discharge=30,
        outdoor_temperature=12,
        current=5,
        defrost=True,
        online=False,
    )
    connector = _connector([payload], [_group("offline")])

    asyncio.run(connector.update())
    heat_pump = connector.get_heat_pump("heat-pump")

    assert heat_pump.power_usage is None
    assert heat_pump.energy_consumption is None
    assert heat_pump.outdoor_temperature is None
    assert heat_pump.operating_state is None
    assert heat_pump.defrost is None
    assert heat_pump.compressor_frequency is None
    assert heat_pump.outdoor_fan_speed is None
    assert heat_pump.current is None


def test_invalid_optional_telemetry_is_unavailable_without_hiding_operation() -> None:
    payload = _payload(
        "head",
        "Head",
        1,
        10,
        900,
        frequency=30,
        fan_speed=500,
        discharge=30,
        outdoor_temperature=12,
        current=5,
        outdoor_mode=1,
    )
    payload["data"].update(
        {
            "oduCompCurrentFrequency": "fast",
            "oduFanMotorCurrentSpeed": True,
            "oduConsumedCurrent": "5",
            "oduDefrost": 1,
        }
    )
    connector = _connector([payload], [_group("head")])

    asyncio.run(connector.update())
    heat_pump = connector.get_heat_pump("heat-pump")

    assert heat_pump.compressor_frequency is None
    assert heat_pump.outdoor_fan_speed is None
    assert heat_pump.current is None
    assert heat_pump.defrost is None
    assert heat_pump.operating_state is DaikinHeatPumpOperatingState.HEATING


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
        outdoor_temperature=12.5,
        operating_state=DaikinHeatPumpOperatingState.HEATING,
        defrost=True,
        compressor_frequency=42,
        outdoor_fan_speed=780,
        current=6.5,
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

    assert len(entities) == 7
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

    outdoor_temperature = next(
        entity for entity in entities if entity.entity_description.key == "outdoor_temperature"
    )
    assert outdoor_temperature.device_class is SensorDeviceClass.TEMPERATURE
    assert outdoor_temperature.native_unit_of_measurement == UnitOfTemperature.CELSIUS
    assert outdoor_temperature.entity_category is None

    operating_state = next(entity for entity in entities if entity.entity_description.key == "operating_state")
    assert operating_state.device_class is SensorDeviceClass.ENUM
    assert operating_state.options == [state.value for state in DaikinHeatPumpOperatingState]
    assert operating_state.native_value is DaikinHeatPumpOperatingState.HEATING

    compressor = next(entity for entity in entities if entity.entity_description.key == "compressor_frequency")
    assert compressor.device_class is SensorDeviceClass.FREQUENCY
    assert compressor.native_unit_of_measurement == UnitOfFrequency.HERTZ
    assert compressor.entity_category is EntityCategory.DIAGNOSTIC

    fan = next(entity for entity in entities if entity.entity_description.key == "outdoor_fan_speed")
    assert fan.native_unit_of_measurement == REVOLUTIONS_PER_MINUTE
    assert fan.entity_category is EntityCategory.DIAGNOSTIC

    current = next(entity for entity in entities if entity.entity_description.key == "current")
    assert current.device_class is SensorDeviceClass.CURRENT
    assert current.native_unit_of_measurement == UnitOfElectricCurrent.AMPERE
    assert current.entity_category is EntityCategory.DIAGNOSTIC

    binary_entities: list[Any] = []

    def add_binary_entities(new_entities: Iterable[Entity], update_before_add: bool = False) -> None:
        binary_entities.extend(new_entities)

    asyncio.run(async_setup_binary_sensors(hass, cast(ConfigEntry, SimpleNamespace()), add_binary_entities))
    assert len(binary_entities) == 1
    defrost = binary_entities[0]
    assert isinstance(defrost, DaikinOneHeatPumpBinarySensor)
    assert defrost.unique_id == "heat-pump-id-defrost"
    assert defrost.device_class is BinarySensorDeviceClass.RUNNING
    assert defrost.is_on is True
    assert defrost.available is True

    heat_pump.defrost = None
    defrost.update_entity_attributes()
    assert defrost.is_on is None
    assert defrost.available is False

    heat_pump.outdoor_temperature = None
    outdoor_temperature.update_entity_attributes()
    assert outdoor_temperature.native_value is None
    assert outdoor_temperature.available is False


def _options_flow(connector: DaikinOne, groups: list[dict[str, Any]]) -> DaikinOneOptionsFlow:
    entry = cast(
        ConfigEntry,
        SimpleNamespace(
            entry_id="entry",
            options={
                CONF_OPTION_HEAT_PUMP_GROUPS_SCHEMA_VERSION_KEY: HEAT_PUMP_GROUPS_SCHEMA_VERSION,
                CONF_OPTION_HEAT_PUMP_GROUPS_KEY: groups,
            },
        ),
    )
    flow = DaikinOneOptionsFlow(entry)
    flow.hass = cast(HomeAssistant, SimpleNamespace(data={DOMAIN: SimpleNamespace(daikin=connector)}))
    return flow


def test_options_flow_renames_group_without_changing_id() -> None:
    connector = _connector(_six_head_payloads())
    asyncio.run(connector.update())
    groups = connector.get_heat_pump_groups()
    flow = _options_flow(connector, groups)
    original = groups[0]

    asyncio.run(flow.async_step_edit_group({CONF_GROUP_ID: original["id"]}))
    asyncio.run(
        flow.async_step_group(
            {
                CONF_GROUP_NAME: "Main floor heat pump",
                CONF_GROUP_MEMBERS: original["thermostat_ids"],
            }
        )
    )

    updated = next(group for group in flow._groups if group.id == original["id"])
    assert updated.name == "Main floor heat pump"
    assert updated.thermostat_ids == tuple(original["thermostat_ids"])


@pytest.mark.parametrize(
    ("name", "members", "locations", "expected"),
    [
        ("", {"head"}, {"head": "location"}, {CONF_GROUP_NAME: "empty_name"}),
        ("Heat Pump", set[str](), {"head": "location"}, {CONF_GROUP_MEMBERS: "empty_members"}),
        ("Heat Pump", {"unknown"}, {"head": "location"}, {CONF_GROUP_MEMBERS: "unknown_head"}),
        (
            "Heat Pump",
            {"first", "second"},
            {"first": "one", "second": "two"},
            {CONF_GROUP_MEMBERS: "different_locations"},
        ),
    ],
)
def test_group_validation_rejects_invalid_input(
    name: str,
    members: set[str],
    locations: dict[str, str],
    expected: dict[str, str],
) -> None:
    assert validate_heat_pump_group(name, members, None, [], locations) == expected


def test_group_validation_rejects_duplicate_assignment() -> None:
    group = DaikinHeatPumpGroup(
        id="existing",
        name="Existing",
        location_id="location",
        thermostat_ids=("head",),
        energy_source_id="head",
    )
    assert validate_heat_pump_group("Other", {"head"}, None, [group], {"head": "location"}) == {
        CONF_GROUP_MEMBERS: "duplicate_head"
    }


def test_options_flow_adds_and_removes_groups_with_stable_ids() -> None:
    connector = _connector(_six_head_payloads())
    asyncio.run(connector.update())
    groups = connector.get_heat_pump_groups()
    flow = _options_flow(connector, groups[:1])
    members = groups[1]["thermostat_ids"]

    asyncio.run(
        flow.async_step_add_group(
            {
                CONF_GROUP_NAME: "Upstairs heat pump",
                CONF_GROUP_MEMBERS: members,
            }
        )
    )
    added = next(group for group in flow._groups if group.name == "Upstairs heat pump")
    assert added.id.startswith("heat-pump-")
    assert added.thermostat_ids == tuple(members)

    asyncio.run(flow.async_step_edit_group({CONF_GROUP_ID: added.id}))
    asyncio.run(flow.async_step_group({CONF_DELETE_GROUP: True}))
    assert added.id not in {group.id for group in flow._groups}
    assert added.id in flow._removed_group_ids


def test_finish_removes_deleted_heat_pump_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _connector(_six_head_payloads())
    asyncio.run(connector.update())
    groups = connector.get_heat_pump_groups()
    flow = _options_flow(connector, groups)
    removed_group_id = groups[0]["id"]
    flow._groups = [DaikinHeatPumpGroup.from_dict(groups[1])]
    flow._removed_group_ids = {removed_group_id}

    registry = Mock()

    def get_registry(hass: HomeAssistant) -> Mock:
        return registry

    def entries_for_config_entry(registry_value: Any, entry_id: str) -> list[Any]:
        return [
            SimpleNamespace(unique_id=f"{removed_group_id}-power_usage", entity_id="sensor.removed"),
            SimpleNamespace(unique_id="head-climate", entity_id="climate.head"),
        ]

    monkeypatch.setattr("custom_components.daikinone.config_flow.er.async_get", get_registry)
    monkeypatch.setattr(
        "custom_components.daikinone.config_flow.er.async_entries_for_config_entry",
        entries_for_config_entry,
    )

    result = asyncio.run(flow.async_step_finish())

    registry.async_remove.assert_called_once_with("sensor.removed")
    result_data = result.get("data")
    assert isinstance(result_data, dict)
    assert result_data[CONF_OPTION_HEAT_PUMP_GROUPS_KEY] == groups[1:]


def test_grouping_issue_tracks_unassigned_heads(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _connector(_six_head_payloads())
    asyncio.run(connector.update())
    groups = connector.get_heat_pump_groups()
    partial = _connector(_six_head_payloads(), groups[:1])
    asyncio.run(partial.update())
    hass = cast(HomeAssistant, SimpleNamespace())
    entry = cast(ConfigEntry, SimpleNamespace(entry_id="entry"))
    create_issue = Mock()
    delete_issue = Mock()
    monkeypatch.setattr("custom_components.daikinone.ir.async_create_issue", create_issue)
    monkeypatch.setattr("custom_components.daikinone.ir.async_delete_issue", delete_issue)

    _update_heat_pump_grouping_issue(hass, entry, SimpleNamespace(daikin=partial))  # type: ignore[arg-type]
    assert create_issue.call_args.kwargs["translation_placeholders"]["heads"] == (
        "Dining room, Living room, Master Bedroom"
    )
    delete_issue.assert_not_called()

    complete = _connector(_six_head_payloads(), groups)
    asyncio.run(complete.update())
    _update_heat_pump_grouping_issue(hass, entry, SimpleNamespace(daikin=complete))  # type: ignore[arg-type]
    delete_issue.assert_called_once_with(hass, DOMAIN, "entry_heat_pump_grouping")
