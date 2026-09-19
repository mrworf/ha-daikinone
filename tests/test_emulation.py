# pyright: reportPrivateUsage=false

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from homeassistant.components.climate import ClimateEntityDescription
from homeassistant.components.climate.const import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.daikinone.climate import DaikinOneThermostat
from custom_components.daikinone.config_flow import (
    CONF_CONVERT_EXTERNAL_AUTO,
    CONF_EMULATION_DWELL_MINUTES,
    CONF_EMULATION_TOLERANCE,
    DaikinOneOptionsFlow,
)
from custom_components.daikinone.const import (
    CONF_OPTION_CONVERT_EXTERNAL_AUTO,
    CONF_OPTION_EMULATION_DWELL_MINUTES,
    CONF_OPTION_EMULATION_TOLERANCE,
)
from custom_components.daikinone.daikinone import DaikinThermostat, DaikinThermostatMode
from custom_components.daikinone.emulation import DaikinEmulationController, EmulationStatus
from custom_components.daikinone.utils import Temperature
from test_climate import NullExternalTemperature, thermostat


class FakeDaikin:
    def __init__(self, devices: list[DaikinThermostat]) -> None:
        self.devices = {device.id: device for device in devices}
        self.commands: list[tuple[str, DaikinThermostatMode]] = []
        self.candidates = {device.id for device in devices if device.heat_pump_id is not None}
        self.setpoint_commands: list[tuple[str, float | None, float | None]] = []
        self.fail_ids: set[str] = set()

    def get_thermostats(self) -> dict[str, DaikinThermostat]:
        return deepcopy(self.devices)

    def get_thermostat(self, thermostat_id: str) -> DaikinThermostat:
        return deepcopy(self.devices[thermostat_id])

    def get_heat_pump_candidate_ids(self) -> set[str]:
        return self.candidates

    def get_heat_pumps(self) -> dict[str, Any]:
        return {"pump": SimpleNamespace(name="Main heat pump")}

    async def set_thermostat_mode(self, thermostat_id: str, mode: DaikinThermostatMode) -> None:
        if thermostat_id in self.fail_ids:
            raise RuntimeError("simulated command failure")
        self.commands.append((thermostat_id, mode))
        self.devices[thermostat_id].mode = mode

    async def set_thermostat_home_set_points(
        self,
        thermostat_id: str,
        *,
        heat: Temperature | None = None,
        cool: Temperature | None = None,
        override_schedule: bool = False,
    ) -> None:
        self.setpoint_commands.append(
            (thermostat_id, heat.celsius if heat is not None else None, cool.celsius if cool is not None else None)
        )
        if heat is not None:
            self.devices[thermostat_id].set_point_heat = heat
        if cool is not None:
            self.devices[thermostat_id].set_point_cool = cool


def head(
    thermostat_id: str,
    temperature: float,
    *,
    mode: DaikinThermostatMode = DaikinThermostatMode.OFF,
    heat_pump_id: str | None = "pump",
) -> DaikinThermostat:
    return replace(
        thermostat(mode),
        id=thermostat_id,
        name=thermostat_id.capitalize(),
        indoor_temperature=Temperature.from_celsius(temperature),
        heat_pump_id=heat_pump_id,
    )


def make_controller(
    devices: list[DaikinThermostat],
    *,
    options: dict[str, Any] | None = None,
    now: list[datetime] | None = None,
    external_temperature: Any | None = None,
) -> tuple[DaikinEmulationController, FakeDaikin]:
    daikin = FakeDaikin(devices)
    entry = cast(ConfigEntry, SimpleNamespace(entry_id="entry", options=options or {}))
    clock = now or [datetime(2026, 1, 1, tzinfo=UTC)]
    controller = DaikinEmulationController(
        cast(HomeAssistant, SimpleNamespace()),
        entry,
        cast(Any, daikin),
        external_temperature=external_temperature,
        now=lambda: clock[0],
    )
    for device in devices:
        controller.register(device, lambda: None)
    return controller, daikin


@pytest.fixture(autouse=True)
def notification_mocks(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock]:
    create = Mock()
    dismiss = Mock()
    monkeypatch.setattr("custom_components.daikinone.emulation.persistent_notification.async_create", create)
    monkeypatch.setattr("custom_components.daikinone.emulation.persistent_notification.async_dismiss", dismiss)
    return create, dismiss


def restore_heat_cool(controller: DaikinEmulationController, daikin: FakeDaikin, *ids: str) -> None:
    for thermostat_id in ids:
        controller.restore(thermostat_id, HVACMode.HEAT_COOL, daikin.devices[thermostat_id].mode)


def test_hysteresis_starts_heat_and_stops_at_low_target() -> None:
    device = head("living", 18)
    controller, daikin = make_controller(
        [device], options={CONF_OPTION_EMULATION_TOLERANCE: 0.5, CONF_OPTION_EMULATION_DWELL_MINUTES: 0}
    )
    restore_heat_cool(controller, daikin, "living")

    asyncio.run(controller.async_reconcile())
    assert daikin.commands == [("living", DaikinThermostatMode.HEAT)]
    assert controller.status("living") is EmulationStatus.HEATING

    daikin.devices["living"].indoor_temperature = Temperature.from_celsius(19)
    asyncio.run(controller.async_reconcile())
    assert daikin.commands[-1] == ("living", DaikinThermostatMode.OFF)
    assert controller.status("living") is EmulationStatus.IDLE


def test_emulated_heat_cool_uses_external_temperature_and_logical_range() -> None:
    class ExternalTemperature:
        def effective_temperature(self, device: DaikinThermostat) -> float:
            del device
            return 26

        def logical_heat(self, device: DaikinThermostat) -> float:
            del device
            return 20

        def logical_cool(self, device: DaikinThermostat) -> float:
            del device
            return 24

    device = head("living", 21)
    controller, daikin = make_controller(
        [device],
        options={CONF_OPTION_EMULATION_DWELL_MINUTES: 0},
        external_temperature=ExternalTemperature(),
    )
    restore_heat_cool(controller, daikin, "living")

    asyncio.run(controller.async_reconcile())

    assert daikin.commands == [("living", DaikinThermostatMode.COOL)]
    assert controller.status("living") is EmulationStatus.COOLING


def test_largest_deviation_selects_one_group_direction() -> None:
    cold = head("cold", 17)
    hot = head("hot", 29)
    controller, daikin = make_controller([cold, hot], options={CONF_OPTION_EMULATION_DWELL_MINUTES: 0})
    restore_heat_cool(controller, daikin, "cold", "hot")

    asyncio.run(controller.async_reconcile())

    assert ("hot", DaikinThermostatMode.COOL) in daikin.commands
    assert ("cold", DaikinThermostatMode.HEAT) not in daikin.commands
    assert controller.status("cold") is EmulationStatus.WAITING_FOR_HEATING
    assert controller.status("hot") is EmulationStatus.COOLING


def test_equal_deviations_retain_the_existing_direction() -> None:
    cold = head("cold", 18)
    hot = head("hot", 26, mode=DaikinThermostatMode.COOL)
    controller, daikin = make_controller([cold, hot], options={CONF_OPTION_EMULATION_DWELL_MINUTES: 0})
    restore_heat_cool(controller, daikin, "cold", "hot")

    asyncio.run(controller.async_reconcile())

    assert daikin.devices["hot"].mode is DaikinThermostatMode.COOL
    assert daikin.devices["cold"].mode is DaikinThermostatMode.OFF


def test_direction_dwell_requires_an_off_cycle_before_reversal() -> None:
    clock = [datetime(2026, 1, 1, tzinfo=UTC)]
    cold = head("cold", 17)
    hot = head("hot", 21)
    controller, daikin = make_controller([cold, hot], options={CONF_OPTION_EMULATION_DWELL_MINUTES: 15}, now=clock)
    restore_heat_cool(controller, daikin, "cold", "hot")
    asyncio.run(controller.async_reconcile())
    assert daikin.commands[-1] == ("cold", DaikinThermostatMode.HEAT)

    daikin.devices["cold"].indoor_temperature = Temperature.from_celsius(20)
    daikin.devices["hot"].indoor_temperature = Temperature.from_celsius(29)
    clock[0] += timedelta(minutes=5)
    asyncio.run(controller.async_reconcile())
    assert ("hot", DaikinThermostatMode.COOL) not in daikin.commands

    clock[0] += timedelta(minutes=11)
    asyncio.run(controller.async_reconcile())
    command_count = len(daikin.commands)
    assert daikin.commands[-1][1] is DaikinThermostatMode.OFF

    asyncio.run(controller.async_reconcile())
    assert len(daikin.commands) == command_count + 1
    assert daikin.commands[-1] == ("hot", DaikinThermostatMode.COOL)


def test_restart_initializes_dwell_from_the_physical_direction() -> None:
    hot = head("hot", 29, mode=DaikinThermostatMode.HEAT)
    controller, daikin = make_controller([hot], options={CONF_OPTION_EMULATION_DWELL_MINUTES: 15})
    restore_heat_cool(controller, daikin, "hot")

    asyncio.run(controller.async_reconcile())

    assert daikin.commands == [("hot", DaikinThermostatMode.OFF)]
    assert controller.status("hot") is EmulationStatus.WAITING_FOR_COOLING


def test_manual_mode_suspends_opposite_demand_and_notification_clears(
    notification_mocks: tuple[Mock, Mock],
) -> None:
    create, dismiss = notification_mocks
    manual = head("manual", 20, mode=DaikinThermostatMode.HEAT)
    hot = head("hot", 29)
    controller, daikin = make_controller([manual, hot], options={CONF_OPTION_EMULATION_DWELL_MINUTES: 0})
    restore_heat_cool(controller, daikin, "hot")

    asyncio.run(controller.async_reconcile())

    assert controller.status("hot") is EmulationStatus.SUSPENDED_BY_MANUAL_CONTROL
    assert daikin.devices["hot"].mode is DaikinThermostatMode.OFF
    assert create.call_count == 1
    assert "Manual" in create.call_args.args[1]
    notification_id = create.call_args.kwargs["notification_id"]

    asyncio.run(controller.async_set_manual_mode("manual", DaikinThermostatMode.OFF))
    asyncio.run(controller.async_reconcile())

    dismiss.assert_any_call(controller._hass, notification_id)
    asyncio.run(controller.async_reconcile())
    assert daikin.devices["hot"].mode is DaikinThermostatMode.COOL


@pytest.mark.parametrize(
    "manual_modes",
    [
        (DaikinThermostatMode.HEAT, DaikinThermostatMode.COOL),
        (DaikinThermostatMode.AUTO,),
    ],
)
def test_conflicting_manual_modes_or_native_auto_suspend_all_emulation(
    manual_modes: tuple[DaikinThermostatMode, ...],
) -> None:
    manual = [head(f"manual-{index}", 21, mode=mode) for index, mode in enumerate(manual_modes)]
    emulated = head("emulated", 17)
    controller, daikin = make_controller([*manual, emulated])
    restore_heat_cool(controller, daikin, "emulated")

    asyncio.run(controller.async_reconcile())

    assert daikin.devices["emulated"].mode is DaikinThermostatMode.OFF
    assert controller.status("emulated") is EmulationStatus.SUSPENDED_BY_MANUAL_CONTROL


def test_external_manual_change_exits_emulation() -> None:
    device = head("living", 18)
    controller, daikin = make_controller([device], options={CONF_OPTION_EMULATION_DWELL_MINUTES: 0})
    restore_heat_cool(controller, daikin, "living")
    asyncio.run(controller.async_reconcile())
    asyncio.run(controller.async_reconcile())  # observe the commanded mode and clear its pending marker

    daikin.devices["living"].mode = DaikinThermostatMode.COOL
    asyncio.run(controller.async_reconcile())

    assert controller.logical_mode("living") is HVACMode.COOL


def test_restore_does_not_override_a_remote_change_made_while_ha_was_down() -> None:
    device = head("living", 21, mode=DaikinThermostatMode.HEAT)
    controller, _ = make_controller([device])

    controller.restore("living", HVACMode.HEAT_COOL, DaikinThermostatMode.COOL)

    assert controller.logical_mode("living") is HVACMode.HEAT


def test_external_auto_conversion_is_opt_in() -> None:
    converted = head("converted", 21, mode=DaikinThermostatMode.HEAT)
    controller, daikin = make_controller([converted], options={CONF_OPTION_CONVERT_EXTERNAL_AUTO: True})
    daikin.devices["converted"].mode = DaikinThermostatMode.AUTO
    asyncio.run(controller.async_reconcile())
    assert controller.logical_mode("converted") is HVACMode.HEAT_COOL

    native = head("native", 21, mode=DaikinThermostatMode.HEAT)
    controller, daikin = make_controller([native])
    daikin.devices["native"].mode = DaikinThermostatMode.AUTO
    asyncio.run(controller.async_reconcile())
    assert controller.logical_mode("native") is HVACMode.AUTO

    intentional = head("intentional", 21, mode=DaikinThermostatMode.HEAT)
    controller, _ = make_controller([intentional], options={CONF_OPTION_CONVERT_EXTERNAL_AUTO: True})
    asyncio.run(controller.async_set_manual_mode("intentional", DaikinThermostatMode.AUTO))
    asyncio.run(controller.async_reconcile())
    assert controller.logical_mode("intentional") is HVACMode.AUTO


def test_unassigned_known_mini_split_does_not_support_emulation() -> None:
    device = head("unassigned", 21, heat_pump_id=None)
    controller, daikin = make_controller([device])
    daikin.candidates.add(device.id)

    assert controller.supports_emulation(device) is False

    daikin.candidates.clear()
    assert controller.supports_emulation(device) is True


def test_unassigned_known_mini_split_does_not_advertise_or_enable_heat_cool() -> None:
    device = head("unassigned", 21, heat_pump_id=None)
    controller, daikin = make_controller([device])
    daikin.candidates.add(device.id)
    data = cast(
        Any,
        SimpleNamespace(
            daikin=daikin,
            emulation=controller,
            external_temperature=NullExternalTemperature(),
        ),
    )
    entity = DaikinOneThermostat(
        ClimateEntityDescription(key=device.id, has_entity_name=True, name=None),
        data,
        device,
    )

    assert HVACMode.HEAT_COOL not in entity.hvac_modes
    with pytest.raises(ServiceValidationError):
        asyncio.run(entity.async_set_hvac_mode(HVACMode.HEAT_COOL))

    controller.restore("unassigned", HVACMode.HEAT_COOL, DaikinThermostatMode.OFF)
    assert controller.logical_mode("unassigned") is HVACMode.OFF

    daikin.devices["unassigned"].mode = DaikinThermostatMode.AUTO
    cast(dict[str, Any], controller._entry.options)[CONF_OPTION_CONVERT_EXTERNAL_AUTO] = True
    asyncio.run(controller.async_reconcile())
    assert controller.logical_mode("unassigned") is HVACMode.AUTO


def test_offline_head_waits_without_a_command() -> None:
    device = replace(head("offline", 10), online=False)
    controller, daikin = make_controller([device])
    restore_heat_cool(controller, daikin, "offline")

    asyncio.run(controller.async_reconcile())

    assert daikin.commands == []
    assert controller.status("offline") is EmulationStatus.WAITING_FOR_DATA

    missing = replace(head("missing", 0), indoor_temperature_valid=False)
    controller, daikin = make_controller([missing])
    restore_heat_cool(controller, daikin, "missing")
    asyncio.run(controller.async_reconcile())
    assert daikin.commands == []
    assert controller.status("missing") is EmulationStatus.WAITING_FOR_DATA


def test_command_failure_does_not_block_another_group() -> None:
    failed = head("failed", 17, heat_pump_id="first")
    healthy = head("healthy", 17, heat_pump_id="second")
    controller, daikin = make_controller([failed, healthy])
    daikin.fail_ids.add("failed")
    restore_heat_cool(controller, daikin, "failed", "healthy")

    asyncio.run(controller.async_reconcile())

    assert daikin.devices["failed"].mode is DaikinThermostatMode.OFF
    assert daikin.devices["healthy"].mode is DaikinThermostatMode.HEAT


def test_climate_exposes_heat_cool_range_and_rejects_incomplete_range() -> None:
    device = head("living", 21)
    controller, daikin = make_controller([device])
    data = cast(
        Any,
        SimpleNamespace(
            daikin=daikin,
            emulation=controller,
            external_temperature=NullExternalTemperature(),
        ),
    )
    entity = DaikinOneThermostat(
        ClimateEntityDescription(key=device.id, has_entity_name=True, name=None),
        data,
        device,
    )

    async def update_optimistically(operation: Any, optimistic_update: Any, check: Any) -> None:
        await operation()
        optimistic_update(entity._device)
        assert check(entity._device)

    entity.update_state_optimistically = update_optimistically  # type: ignore[method-assign]

    assert HVACMode.HEAT_COOL in entity.hvac_modes
    asyncio.run(entity.async_set_hvac_mode(HVACMode.HEAT_COOL))
    entity.update_entity_attributes()
    assert entity.hvac_mode is HVACMode.HEAT_COOL
    assert entity.target_temperature_low == 19
    assert entity.target_temperature_high == 25

    asyncio.run(entity.async_set_temperature(target_temp_low=20, target_temp_high=24))
    assert daikin.setpoint_commands == [("living", 20, 24)]

    with pytest.raises(ServiceValidationError):
        asyncio.run(entity.async_set_temperature(target_temp_low=20))
    with pytest.raises(ServiceValidationError):
        asyncio.run(entity.async_set_temperature(target_temp_low=25, target_temp_high=24))
    assert daikin.setpoint_commands == [("living", 20, 24)]

    asyncio.run(entity.async_turn_off())
    assert controller.logical_mode("living") is HVACMode.OFF
    asyncio.run(entity.async_turn_on())
    assert controller.logical_mode("living") is HVACMode.HEAT_COOL


def test_options_flow_saves_emulation_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = cast(ConfigEntry, SimpleNamespace(entry_id="entry", options={}))
    flow = DaikinOneOptionsFlow(entry)
    registry = Mock()
    flow.hass = cast(HomeAssistant, SimpleNamespace(data={}))

    def get_registry(hass: HomeAssistant) -> Mock:
        return registry

    def entries_for_config_entry(registry_value: Any, entry_id: str) -> list[Any]:
        return []

    monkeypatch.setattr("custom_components.daikinone.config_flow.er.async_get", get_registry)
    monkeypatch.setattr(
        "custom_components.daikinone.config_flow.er.async_entries_for_config_entry",
        entries_for_config_entry,
    )

    asyncio.run(
        flow.async_step_emulation_settings(
            {
                CONF_EMULATION_TOLERANCE: 0.8,
                CONF_EMULATION_DWELL_MINUTES: 20,
                CONF_CONVERT_EXTERNAL_AUTO: True,
            }
        )
    )
    result = asyncio.run(flow.async_step_finish())

    result_data = result.get("data")
    assert isinstance(result_data, dict)
    assert result_data[CONF_OPTION_EMULATION_TOLERANCE] == 0.8
    assert result_data[CONF_OPTION_EMULATION_DWELL_MINUTES] == 20
    assert result_data[CONF_OPTION_CONVERT_EXTERNAL_AUTO] is True
