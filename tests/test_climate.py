import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from homeassistant.components.climate import ClimateEntityDescription
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode

from custom_components.daikinone.climate import DaikinOneThermostat
from custom_components.daikinone.daikinone import (
    DaikinOne,
    DaikinThermostat,
    DaikinThermostatCapability,
    DaikinThermostatFanSpeed,
    DaikinThermostatFanSpeeds,
    DaikinThermostatMode,
    DaikinThermostatSchedule,
    DaikinThermostatStatus,
    DaikinUserCredentials,
)
from custom_components.daikinone.utils import Temperature


class NullExternalTemperature:
    def register(self, thermostat_id: str, callback: Any) -> None:
        del thermostat_id, callback

    def unregister(self, thermostat_id: str) -> None:
        del thermostat_id

    def configured(self, thermostat_id: str) -> bool:
        del thermostat_id
        return False

    def external_temperature(self, thermostat_id: str) -> float | None:
        del thermostat_id
        return None

    def external_humidity(self, thermostat_id: str) -> int | None:
        del thermostat_id
        return None

    def logical_heat(self, device: DaikinThermostat) -> float:
        return device.set_point_heat.celsius

    def logical_cool(self, device: DaikinThermostat) -> float:
        return device.set_point_cool.celsius

    def state(self, thermostat_id: str) -> None:
        del thermostat_id
        return None

    def config(self, thermostat_id: str) -> None:
        del thermostat_id
        return None


def thermostat(mode: DaikinThermostatMode = DaikinThermostatMode.AUTO) -> DaikinThermostat:
    return DaikinThermostat(
        id="head",
        name="Living room",
        model="DENEB",
        firmware_version="3.2.0",
        location_id="location",
        online=True,
        capabilities={DaikinThermostatCapability.HEAT, DaikinThermostatCapability.COOL},
        mode=mode,
        status=DaikinThermostatStatus.IDLE,
        fan_speeds=DaikinThermostatFanSpeeds(
            heat=DaikinThermostatFanSpeed.AUTO,
            cool=DaikinThermostatFanSpeed.AUTO,
            auto=DaikinThermostatFanSpeed.AUTO,
            dry=DaikinThermostatFanSpeed.AUTO,
            fan=DaikinThermostatFanSpeed.AUTO,
        ),
        operating_fan_speed_supported=True,
        fan_speed_supported_modes={
            DaikinThermostatMode.HEAT,
            DaikinThermostatMode.COOL,
            DaikinThermostatMode.AUTO,
            DaikinThermostatMode.DRY,
        },
        circulation_mode=None,
        circulation_mode_supported=False,
        circulation_speed=None,
        circulation_speed_supported=False,
        schedule=DaikinThermostatSchedule(enabled=False),
        indoor_temperature=Temperature.from_celsius(21),
        indoor_humidity=40,
        set_point_heat=Temperature.from_celsius(19),
        set_point_heat_min=Temperature.from_celsius(10),
        set_point_heat_max=Temperature.from_celsius(30),
        set_point_cool=Temperature.from_celsius(25),
        set_point_cool_min=Temperature.from_celsius(18),
        set_point_cool_max=Temperature.from_celsius(32),
        set_point_auto=Temperature.from_celsius(22),
        set_point_auto_min=Temperature.from_celsius(18),
        set_point_auto_max=Temperature.from_celsius(30),
        outdoor_temperature=Temperature.from_celsius(10),
        outdoor_humidity=70,
        air_quality_outdoor=None,
        air_quality_indoor=None,
        equipment={},
    )


def climate_entity(
    device: DaikinThermostat,
    connector: Any | None = None,
    external_temperature: Any | None = None,
    logical_mode: HVACMode | None = None,
) -> DaikinOneThermostat:
    daikin = connector or SimpleNamespace()

    class FakeEmulation:
        def __init__(self) -> None:
            self.mode = logical_mode or {
                DaikinThermostatMode.AUTO: HVACMode.AUTO,
                DaikinThermostatMode.HEAT: HVACMode.HEAT,
                DaikinThermostatMode.COOL: HVACMode.COOL,
                DaikinThermostatMode.OFF: HVACMode.OFF,
            }.get(device.mode, HVACMode.HEAT)

        def register(self, registered: DaikinThermostat, callback: Any) -> None:
            assert registered.id == device.id

        def supports_emulation(self, registered: DaikinThermostat) -> bool:
            return True

        def logical_mode(self, thermostat_id: str) -> HVACMode:
            return self.mode

        def status(self, thermostat_id: str) -> None:
            return None

        def expected_physical_mode(self, thermostat_id: str) -> DaikinThermostatMode:
            return device.mode

        def previous_mode(self, thermostat_id: str) -> HVACMode:
            return HVACMode.HEAT

        async def async_set_manual_mode(self, thermostat_id: str, mode: DaikinThermostatMode) -> None:
            await daikin.set_thermostat_mode(thermostat_id, mode)
            self.mode = {
                DaikinThermostatMode.AUTO: HVACMode.AUTO,
                DaikinThermostatMode.HEAT: HVACMode.HEAT,
                DaikinThermostatMode.COOL: HVACMode.COOL,
                DaikinThermostatMode.OFF: HVACMode.OFF,
            }.get(mode, HVACMode.HEAT)

    data = cast(
        Any,
        SimpleNamespace(
            daikin=daikin,
            emulation=FakeEmulation(),
            external_temperature=external_temperature or NullExternalTemperature(),
        ),
    )
    return DaikinOneThermostat(
        ClimateEntityDescription(key=device.id, has_entity_name=True, name=None),
        data,
        device,
    )


def test_native_auto_exposes_single_target_temperature() -> None:
    entity = climate_entity(thermostat())

    entity.update_entity_attributes()

    assert entity.hvac_mode is HVACMode.AUTO
    assert entity.target_temperature == 22
    assert entity.target_temperature_low is None
    assert entity.target_temperature_high is None


def test_configured_external_readings_are_shown_while_head_is_off() -> None:
    class ExternalReadings(NullExternalTemperature):
        def configured(self, thermostat_id: str) -> bool:
            del thermostat_id
            return True

        def external_temperature(self, thermostat_id: str) -> float:
            del thermostat_id
            return 18.5

        def external_humidity(self, thermostat_id: str) -> int:
            del thermostat_id
            return 56

    entity = climate_entity(
        thermostat(DaikinThermostatMode.OFF),
        external_temperature=ExternalReadings(),
    )

    entity.update_entity_attributes()

    assert entity.current_temperature == 18.5
    assert entity.current_humidity == 56


def test_missing_external_humidity_falls_back_independently() -> None:
    class MissingExternalHumidity(NullExternalTemperature):
        def configured(self, thermostat_id: str) -> bool:
            del thermostat_id
            return True

        def external_temperature(self, thermostat_id: str) -> float:
            del thermostat_id
            return 18.5

    entity = climate_entity(
        thermostat(DaikinThermostatMode.OFF),
        external_temperature=MissingExternalHumidity(),
    )

    entity.update_entity_attributes()

    assert entity.current_temperature == 18.5
    assert entity.current_humidity == 40


def test_native_auto_target_writes_auto_setpoint() -> None:
    device = thermostat()
    calls: list[dict[str, Any]] = []

    class FakeConnector:
        async def set_thermostat_home_set_points(self, thermostat_id: str, **kwargs: Any) -> None:
            calls.append({"thermostat_id": thermostat_id, **kwargs})

    entity = climate_entity(device, FakeConnector())

    async def update_optimistically(operation: Any, optimistic_update: Any, check: Any) -> None:
        await operation()
        optimistic_update(device)
        assert check(device)

    entity.update_state_optimistically = update_optimistically  # type: ignore[method-assign]

    asyncio.run(entity.async_set_temperature(temperature=23))

    assert calls == [{"thermostat_id": "head", "auto": Temperature.from_celsius(23)}]


def test_connector_setpoint_payload_supports_auto_and_rejects_empty() -> None:
    connector = DaikinOne(DaikinUserCredentials("user@example.invalid", "unused"))
    requests: list[dict[str, Any]] = []

    async def request(*args: Any, **kwargs: Any) -> None:
        requests.append(kwargs)

    connector._DaikinOne__req = request  # type: ignore[attr-defined]

    asyncio.run(connector.set_thermostat_home_set_points("head", auto=Temperature.from_celsius(22.4)))
    assert requests[0]["body"] == {"iduAutoSetpoint": 22.5}

    with pytest.raises(ValueError, match="At least one"):
        asyncio.run(connector.set_thermostat_home_set_points("head"))


def test_climate_mode_change_sends_one_request() -> None:
    device = thermostat(DaikinThermostatMode.OFF)
    calls: list[DaikinThermostatMode] = []

    class FakeConnector:
        async def set_thermostat_mode(self, thermostat_id: str, mode: DaikinThermostatMode) -> None:
            assert thermostat_id == "head"
            calls.append(mode)

    entity = climate_entity(device, FakeConnector())

    async def update_optimistically(operation: Any, optimistic_update: Any, check: Any) -> None:
        await operation()
        optimistic_update(device)
        assert check(device)

    entity.update_state_optimistically = update_optimistically  # type: ignore[method-assign]

    asyncio.run(entity.async_set_hvac_mode(HVACMode.HEAT))

    assert calls == [DaikinThermostatMode.HEAT]


def test_native_heat_fan_mode_sets_only_heat_speed() -> None:
    device = thermostat(DaikinThermostatMode.HEAT)
    calls: list[tuple[DaikinThermostatFanSpeed, set[DaikinThermostatMode]]] = []

    class FakeConnector:
        async def set_thermostat_fan_speed(
            self,
            thermostat_id: str,
            speed: DaikinThermostatFanSpeed,
            modes: set[DaikinThermostatMode],
        ) -> None:
            assert thermostat_id == "head"
            calls.append((speed, modes))

    entity = climate_entity(device, FakeConnector())

    async def update_optimistically(operation: Any, optimistic_update: Any, check: Any) -> None:
        await operation()
        optimistic_update(device)
        assert check(device)

    entity.update_state_optimistically = update_optimistically  # type: ignore[method-assign]
    entity.update_entity_attributes()

    assert entity.fan_modes == [
        "auto",
        "quiet",
        "low",
        "medium low",
        "medium",
        "medium high",
        "high",
    ]
    assert entity.supported_features & ClimateEntityFeature.FAN_MODE
    assert entity.fan_mode == "auto"

    asyncio.run(entity.async_set_fan_mode("medium high"))

    assert calls == [(DaikinThermostatFanSpeed.MEDIUM_HIGH, {DaikinThermostatMode.HEAT})]
    assert device.fan_speeds.heat is DaikinThermostatFanSpeed.MEDIUM_HIGH
    assert device.fan_speeds.cool is DaikinThermostatFanSpeed.AUTO


def test_emulated_heat_cool_sets_both_speeds_while_head_is_off() -> None:
    device = thermostat(DaikinThermostatMode.OFF)
    calls: list[set[DaikinThermostatMode]] = []

    class FakeConnector:
        async def set_thermostat_fan_speed(
            self,
            thermostat_id: str,
            speed: DaikinThermostatFanSpeed,
            modes: set[DaikinThermostatMode],
        ) -> None:
            del thermostat_id, speed
            calls.append(modes)

    entity = climate_entity(device, FakeConnector(), logical_mode=HVACMode.HEAT_COOL)

    async def update_optimistically(operation: Any, optimistic_update: Any, check: Any) -> None:
        await operation()
        optimistic_update(device)
        assert check(device)

    entity.update_state_optimistically = update_optimistically  # type: ignore[method-assign]
    entity.update_entity_attributes()

    assert entity.supported_features & ClimateEntityFeature.FAN_MODE
    assert entity.fan_mode == "auto"

    asyncio.run(entity.async_set_fan_mode("quiet"))

    assert calls == [{DaikinThermostatMode.HEAT, DaikinThermostatMode.COOL}]
    assert device.fan_speeds.heat is DaikinThermostatFanSpeed.QUIET
    assert device.fan_speeds.cool is DaikinThermostatFanSpeed.QUIET


def test_emulated_heat_cool_idle_omits_mismatched_speed() -> None:
    device = thermostat(DaikinThermostatMode.OFF)
    device.fan_speeds.cool = DaikinThermostatFanSpeed.HIGH
    entity = climate_entity(device, logical_mode=HVACMode.HEAT_COOL)

    entity.update_entity_attributes()

    assert entity.supported_features & ClimateEntityFeature.FAN_MODE
    assert entity.fan_mode is None


def test_native_off_hides_operating_fan_control() -> None:
    entity = climate_entity(thermostat(DaikinThermostatMode.OFF))

    entity.update_entity_attributes()

    assert not entity.supported_features & ClimateEntityFeature.FAN_MODE
    assert entity.fan_mode is None


def test_connector_fan_speed_payload_uses_mode_specific_fields() -> None:
    connector = DaikinOne(DaikinUserCredentials("user@example.invalid", "unused"))
    requests: list[dict[str, Any]] = []

    async def request(*args: Any, **kwargs: Any) -> None:
        requests.append(kwargs)

    connector._DaikinOne__req = request  # type: ignore[attr-defined]

    asyncio.run(
        connector.set_thermostat_fan_speed(
            "head",
            DaikinThermostatFanSpeed.MEDIUM_LOW,
            {DaikinThermostatMode.HEAT, DaikinThermostatMode.COOL},
        )
    )

    assert requests[0]["body"] == {"iduHeatFanSpeed": 4, "iduCoolFanSpeed": 4}
    with pytest.raises(ValueError, match="Unsupported"):
        asyncio.run(
            connector.set_thermostat_fan_speed("head", DaikinThermostatFanSpeed.AUTO, {DaikinThermostatMode.OFF})
        )
