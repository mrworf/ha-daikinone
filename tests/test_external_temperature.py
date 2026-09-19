# pyright: reportPrivateUsage=false

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant

from custom_components.daikinone.const import CONF_OPTION_EXTERNAL_TEMPERATURE_CONTROLS
from custom_components.daikinone.config_flow import (
    CONF_HUMIDITY_SENSOR_ENTITY_ID,
    CONF_MAX_BIAS,
    CONF_SENSOR_ENTITY_ID,
    CONF_THERMOSTAT_ID,
    DaikinOneOptionsFlow,
)
from custom_components.daikinone.daikinone import DaikinThermostat, DaikinThermostatMode
from custom_components.daikinone.external_temperature import (
    AdaptiveHeadState,
    ExternalTemperatureConfig,
    ExternalTemperatureController,
    ExternalTemperatureStatus,
)
from custom_components.daikinone.utils import Temperature
from test_climate import thermostat


class FakeStates:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    def get(self, entity_id: str) -> Any:
        return self.values.get(entity_id)


class FakeStore:
    def __init__(self) -> None:
        self.saved: dict[str, Any] | None = None

    def async_delay_save(self, data: Any, delay: int) -> None:
        del delay
        self.saved = data()

    async def async_save(self, data: dict[str, Any]) -> None:
        self.saved = data


class FakeDaikin:
    def __init__(self, device: DaikinThermostat) -> None:
        self.device = device
        self.commands: list[tuple[float | None, float | None]] = []
        self.schedule_commands: list[bool] = []
        self.fail_setpoints = False

    def get_thermostat(self, thermostat_id: str) -> DaikinThermostat:
        assert thermostat_id == self.device.id
        return deepcopy(self.device)

    def get_thermostats(self) -> dict[str, DaikinThermostat]:
        return {self.device.id: deepcopy(self.device)}

    async def set_thermostat_home_set_points(
        self,
        thermostat_id: str,
        *,
        heat: Temperature | None = None,
        cool: Temperature | None = None,
        override_schedule: bool = False,
    ) -> None:
        del override_schedule
        assert thermostat_id == self.device.id
        if self.fail_setpoints:
            raise RuntimeError("simulated setpoint failure")
        self.commands.append(
            (
                heat.celsius if heat is not None else None,
                cool.celsius if cool is not None else None,
            )
        )
        if heat is not None:
            self.device.set_point_heat = heat
        if cool is not None:
            self.device.set_point_cool = cool

    async def set_thermostat_schedule_enabled(self, thermostat_id: str, enabled: bool) -> None:
        assert thermostat_id == self.device.id
        self.schedule_commands.append(enabled)
        self.device.schedule.enabled = enabled


def make_controller(
    *,
    mode: DaikinThermostatMode,
    external: float | str,
    max_bias: float = 5.0,
    humidity: float | str | None = None,
) -> tuple[ExternalTemperatureController, FakeDaikin, list[datetime], Any]:
    device = thermostat(mode)
    daikin = FakeDaikin(device)
    sensor = SimpleNamespace(
        state=str(external),
        attributes={"unit_of_measurement": UnitOfTemperature.CELSIUS},
    )
    sensor_values: dict[str, Any] = {"sensor.room": sensor}
    if humidity is not None:
        sensor_values["sensor.room_humidity"] = SimpleNamespace(state=str(humidity), attributes={})
    hass = cast(
        HomeAssistant,
        SimpleNamespace(
            states=FakeStates(sensor_values),
            data={},
            config=SimpleNamespace(config_dir="/tmp"),
        ),
    )
    entry = cast(
        ConfigEntry,
        SimpleNamespace(
            entry_id="entry",
            options={
                CONF_OPTION_EXTERNAL_TEMPERATURE_CONTROLS: [
                    ExternalTemperatureConfig(
                        "head",
                        "sensor.room",
                        max_bias,
                        "sensor.room_humidity" if humidity is not None else None,
                    ).as_dict()
                ]
            },
        ),
    )
    clock = [datetime(2026, 9, 19, tzinfo=UTC)]
    controller = ExternalTemperatureController(hass, entry, cast(Any, daikin), now=lambda: clock[0])
    controller._heads["head"] = AdaptiveHeadState(logical_heat=22, logical_cool=24)
    controller._store = cast(Any, FakeStore())
    controller._initialized = True
    return controller, daikin, clock, sensor


def test_heat_bias_continuously_relearns_when_conditions_change() -> None:
    controller, daikin, clock, sensor = make_controller(mode=DaikinThermostatMode.HEAT, external=20)

    asyncio.run(controller.async_reconcile())
    clock[0] += timedelta(minutes=15)
    asyncio.run(controller.async_reconcile())

    state = controller.state("head")
    assert state is not None
    assert state.heat_bias == 0.5
    assert daikin.commands == [(22.5, None)]

    sensor.state = "23"
    clock[0] += timedelta(minutes=1)
    asyncio.run(controller.async_reconcile())
    clock[0] += timedelta(minutes=15)
    asyncio.run(controller.async_reconcile())

    assert state.heat_bias == 0
    assert daikin.commands == [(22.5, None), (22, None)]


def test_cool_bias_moves_down_and_respects_configured_limit() -> None:
    controller, daikin, clock, _ = make_controller(
        mode=DaikinThermostatMode.COOL,
        external=27,
        max_bias=0.5,
    )

    asyncio.run(controller.async_reconcile())
    clock[0] += timedelta(minutes=15)
    asyncio.run(controller.async_reconcile())
    clock[0] += timedelta(minutes=15)
    asyncio.run(controller.async_reconcile())

    state = controller.state("head")
    assert state is not None
    assert state.cool_bias == -0.5
    assert daikin.commands == [(None, 23.5)]
    assert state.status is ExternalTemperatureStatus.LIMITED


def test_invalid_sensor_and_deadband_do_not_write() -> None:
    controller, daikin, clock, sensor = make_controller(mode=DaikinThermostatMode.HEAT, external="not-a-number")

    asyncio.run(controller.async_reconcile())
    clock[0] += timedelta(hours=1)
    asyncio.run(controller.async_reconcile())
    assert daikin.commands == []
    assert controller.state("head").status is ExternalTemperatureStatus.WAITING_FOR_SENSOR  # type: ignore[union-attr]

    sensor.state = "21.8"
    asyncio.run(controller.async_reconcile())
    clock[0] += timedelta(hours=1)
    asyncio.run(controller.async_reconcile())
    assert daikin.commands == []


def test_state_round_trip_preserves_biases_and_logical_targets() -> None:
    device = thermostat(DaikinThermostatMode.HEAT)
    adjusted = AdaptiveHeadState(
        logical_heat=21.5,
        logical_cool=25.5,
        heat_bias=2.0,
        cool_bias=-1.5,
        last_evaluated=datetime(2026, 9, 19, tzinfo=UTC),
    )

    restored = AdaptiveHeadState.from_dict(adjusted.as_dict(), device)

    assert restored.logical_heat == 21.5
    assert restored.logical_cool == 25.5
    assert restored.heat_bias == 2.0
    assert restored.cool_bias == -1.5
    assert restored.last_evaluated == datetime(2026, 9, 19, tzinfo=UTC)


def test_existing_temperature_only_config_remains_compatible() -> None:
    config = ExternalTemperatureConfig.from_dict(
        {
            "thermostat_id": "head",
            "sensor_entity_id": "sensor.room",
            "max_bias": 5,
        }
    )

    assert config.humidity_sensor_entity_id is None
    assert "humidity_sensor_entity_id" not in config.as_dict()


def test_external_humidity_requires_a_fresh_percentage() -> None:
    controller, _, clock, _ = make_controller(
        mode=DaikinThermostatMode.OFF,
        external=21,
        humidity=56,
    )
    humidity_sensor = controller._hass.states.get("sensor.room_humidity")
    assert humidity_sensor is not None
    humidity_sensor = cast(Any, humidity_sensor)

    assert controller.external_humidity("head") == 56

    humidity_sensor.state = "101"
    assert controller.external_humidity("head") is None

    humidity_sensor.state = "55"
    humidity_sensor.last_updated = clock[0] - timedelta(minutes=31)
    assert controller.external_humidity("head") is None


def test_stale_sensor_falls_back_without_changing_bias() -> None:
    controller, daikin, clock, sensor = make_controller(mode=DaikinThermostatMode.HEAT, external=18)
    sensor.last_updated = clock[0] - timedelta(minutes=31)

    asyncio.run(controller.async_reconcile())

    state = controller.state("head")
    assert controller.external_temperature("head") is None
    assert controller.effective_temperature(daikin.device) == 21
    assert state is not None
    assert state.status is ExternalTemperatureStatus.STALE_SENSOR
    assert state.heat_bias == 0
    assert daikin.commands == []


def test_sensor_recovery_requires_a_fresh_adjustment_interval() -> None:
    controller, daikin, clock, sensor = make_controller(mode=DaikinThermostatMode.HEAT, external=18)
    sensor.last_updated = clock[0] - timedelta(minutes=31)
    asyncio.run(controller.async_reconcile())

    sensor.last_updated = clock[0]
    asyncio.run(controller.async_reconcile())
    clock[0] += timedelta(minutes=14)
    asyncio.run(controller.async_reconcile())
    assert daikin.commands == []

    clock[0] += timedelta(minutes=1)
    sensor.last_updated = clock[0]
    asyncio.run(controller.async_reconcile())
    assert daikin.commands == [(22.5, None)]


def test_manual_physical_change_becomes_new_logical_target() -> None:
    controller, daikin, clock, _ = make_controller(mode=DaikinThermostatMode.OFF, external=21)
    state = controller.state("head")
    assert state is not None
    state.logical_heat = 19
    state.heat_bias = 1
    state.expected_heat = 20
    daikin.device.set_point_heat = Temperature.from_celsius(21.5)

    asyncio.run(controller.async_reconcile())

    assert state.logical_heat == 20.5
    assert state.expected_heat == 21.5
    assert state.pending_until is None
    assert clock[0] == datetime(2026, 9, 19, tzinfo=UTC)


def test_pending_command_is_not_adopted_as_manual_change() -> None:
    controller, daikin, clock, _ = make_controller(mode=DaikinThermostatMode.OFF, external=21)
    state = controller.state("head")
    assert state is not None
    state.logical_heat = 19
    state.heat_bias = 1
    state.expected_heat = 20
    state.pending_until = clock[0] + timedelta(seconds=45)
    daikin.device.set_point_heat = Temperature.from_celsius(21.5)

    asyncio.run(controller.async_reconcile())
    assert state.logical_heat == 19

    clock[0] += timedelta(seconds=46)
    asyncio.run(controller.async_reconcile())
    assert state.logical_heat == 20.5


def test_enabled_schedule_is_disabled_once_for_configured_head() -> None:
    controller, daikin, _, _ = make_controller(mode=DaikinThermostatMode.OFF, external=21)
    daikin.device.schedule.enabled = True

    asyncio.run(controller.async_reconcile())
    asyncio.run(controller.async_reconcile())

    assert daikin.schedule_commands == [False]


def test_removed_configuration_restores_unbiased_targets() -> None:
    controller, daikin, _, _ = make_controller(mode=DaikinThermostatMode.OFF, external=21)
    controller._heads.clear()
    controller._cleanup["head"] = AdaptiveHeadState(
        logical_heat=20.5,
        logical_cool=25.5,
        heat_bias=2,
        cool_bias=-1,
    )

    daikin.fail_setpoints = True
    asyncio.run(controller.async_reconcile())
    assert "head" in controller._cleanup

    daikin.fail_setpoints = False
    asyncio.run(controller.async_reconcile())

    assert daikin.commands == [(20.5, 25.5)]
    assert controller._cleanup == {}


def test_options_flow_adds_optional_sensor_with_default_bias() -> None:
    device = thermostat(DaikinThermostatMode.HEAT)
    connector = SimpleNamespace(get_thermostats=lambda: {device.id: device})
    sensor = SimpleNamespace(
        state="21",
        attributes={"device_class": SensorDeviceClass.TEMPERATURE},
    )
    humidity_sensor = SimpleNamespace(
        state="55",
        attributes={"device_class": SensorDeviceClass.HUMIDITY},
    )
    entry = cast(ConfigEntry, SimpleNamespace(entry_id="entry", options={}))
    flow = DaikinOneOptionsFlow(entry)
    flow.hass = cast(
        HomeAssistant,
        SimpleNamespace(
            data={"daikinone": SimpleNamespace(daikin=connector)},
            states=FakeStates({"sensor.room": sensor, "sensor.room_humidity": humidity_sensor}),
        ),
    )

    asyncio.run(flow.async_step_external_temperature({CONF_THERMOSTAT_ID: "head"}))
    asyncio.run(
        flow.async_step_external_temperature_head(
            {
                CONF_SENSOR_ENTITY_ID: "sensor.room",
                CONF_HUMIDITY_SENSOR_ENTITY_ID: "sensor.room_humidity",
                CONF_MAX_BIAS: 5.0,
            }
        )
    )

    assert flow._external_controls["head"] == ExternalTemperatureConfig(
        "head", "sensor.room", 5.0, "sensor.room_humidity"
    )
