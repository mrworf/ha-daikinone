import asyncio
from types import SimpleNamespace
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from custom_components.daikinone.const import DOMAIN
from custom_components.daikinone.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)


class FakeDaikin:
    async def get_all_raw_device_data(self) -> list[dict[str, Any]]:
        return [{"id": "head"}]

    async def get_raw_device_data(self, device_id: str) -> dict[str, Any]:
        return {"id": device_id}


class FakeExternalTemperature:
    def all_diagnostics(self) -> dict[str, dict[str, Any]]:
        return {"head": {"external_temperature": 20.5}}

    def diagnostics(self, thermostat_id: str) -> dict[str, Any] | None:
        if thermostat_id == "head":
            return {"external_temperature": 20.5}
        return None


def make_hass() -> HomeAssistant:
    data = SimpleNamespace(
        daikin=FakeDaikin(),
        external_temperature=FakeExternalTemperature(),
    )
    return cast(HomeAssistant, SimpleNamespace(data={DOMAIN: data}))


def test_config_entry_diagnostics_include_all_external_controls() -> None:
    result = asyncio.run(
        async_get_config_entry_diagnostics(
            make_hass(),
            cast(ConfigEntry, SimpleNamespace()),
        )
    )

    assert result == {
        "raw": [{"id": "head"}],
        "external_temperature_control": {"head": {"external_temperature": 20.5}},
    }


def test_device_diagnostics_include_matching_external_control_or_none() -> None:
    entry = cast(ConfigEntry, SimpleNamespace())
    configured = cast(DeviceEntry, SimpleNamespace(identifiers={(DOMAIN, "head")}))
    unconfigured = cast(DeviceEntry, SimpleNamespace(identifiers={(DOMAIN, "heat-pump")}))

    configured_result = asyncio.run(async_get_device_diagnostics(make_hass(), entry, configured))
    unconfigured_result = asyncio.run(async_get_device_diagnostics(make_hass(), entry, unconfigured))

    assert configured_result == {
        "raw": {"id": "head"},
        "external_temperature_control": {"external_temperature": 20.5},
    }
    assert unconfigured_result == {
        "raw": {"id": "heat-pump"},
        "external_temperature_control": None,
    }
