# pyright: reportPrivateUsage=false

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant

from custom_components.daikinone.const import CONF_OPTION_EXTERNAL_TEMPERATURE_CONTROLS
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


def make_controller(
    *,
    mode: DaikinThermostatMode,
    external: float | str,
    max_bias: float = 5.0,
) -> tuple[ExternalTemperatureController, FakeDaikin, list[datetime], Any]:
    device = thermostat(mode)
    daikin = FakeDaikin(device)
    sensor = SimpleNamespace(
        state=str(external),
        attributes={"unit_of_measurement": UnitOfTemperature.CELSIUS},
    )
    hass = cast(
        HomeAssistant,
        SimpleNamespace(
            states=FakeStates({"sensor.room": sensor}),
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
                    ExternalTemperatureConfig("head", "sensor.room", max_bias).as_dict()
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
