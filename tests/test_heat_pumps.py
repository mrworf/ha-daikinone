# pyright: reportPrivateUsage=false

import asyncio
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from homeassistant.components.sensor.const import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from custom_components.daikinone import _update_heat_pump_grouping_issue
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
