import logging
from typing import Any, cast
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY,
    CONF_OPTION_CONVERT_EXTERNAL_AUTO,
    CONF_OPTION_EMULATION_DWELL_MINUTES,
    CONF_OPTION_EMULATION_TOLERANCE,
    CONF_OPTION_EXTERNAL_TEMPERATURE_CONTROLS,
    CONF_OPTION_HEAT_PUMP_GROUPS_KEY,
    CONF_OPTION_HEAT_PUMP_GROUPS_SCHEMA_VERSION_KEY,
    DOMAIN,
    DEFAULT_CONVERT_EXTERNAL_AUTO,
    DEFAULT_EMULATION_DWELL_MINUTES,
    DEFAULT_EMULATION_TOLERANCE,
    DEFAULT_EXTERNAL_TEMPERATURE_MAX_BIAS,
    HEAT_PUMP_GROUPS_SCHEMA_VERSION,
)
from .daikinone import DaikinHeatPumpGroup, DaikinOne, DaikinUserCredentials
from .external_temperature import ExternalTemperatureConfig

log = logging.getLogger(__name__)

CONF_GROUP_ID = "group_id"
CONF_GROUP_NAME = "name"
CONF_GROUP_MEMBERS = "members"
CONF_DELETE_GROUP = "delete_group"
CONF_EMULATION_TOLERANCE = "emulation_tolerance"
CONF_EMULATION_DWELL_MINUTES = "emulation_dwell_minutes"
CONF_CONVERT_EXTERNAL_AUTO = "convert_external_auto"
CONF_THERMOSTAT_ID = "thermostat_id"
CONF_SENSOR_ENTITY_ID = "sensor_entity_id"
CONF_HUMIDITY_SENSOR_ENTITY_ID = "humidity_sensor_entity_id"
CONF_MAX_BIAS = "max_bias"
CONF_DELETE_EXTERNAL_CONTROL = "delete_external_control"


def validate_heat_pump_group(
    name: str,
    member_ids: set[str],
    current_group_id: str | None,
    groups: list[DaikinHeatPumpGroup],
    known_locations: dict[str, str],
) -> dict[str, str]:
    """Validate an edited heat-pump group without changing saved options."""
    errors: dict[str, str] = {}
    if not name.strip():
        errors[CONF_GROUP_NAME] = "empty_name"
    if not member_ids:
        errors[CONF_GROUP_MEMBERS] = "empty_members"
        return errors
    if not member_ids <= known_locations.keys():
        errors[CONF_GROUP_MEMBERS] = "unknown_head"
        return errors
    if len({known_locations[member_id] for member_id in member_ids}) != 1:
        errors[CONF_GROUP_MEMBERS] = "different_locations"
    assigned_elsewhere = {
        member_id for group in groups if group.id != current_group_id for member_id in group.thermostat_ids
    }
    if member_ids & assigned_elsewhere:
        errors[CONF_GROUP_MEMBERS] = "duplicate_head"
    return errors


class DaikinOneConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Daikin One config flow."""

    VERSION = 1
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the heat-pump grouping options flow."""
        return DaikinOneOptionsFlow(config_entry)

    @property
    def schema(self):
        """Return current schema."""
        return vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            # check auth before finishing setup to ensure credentials work
            daikin = DaikinOne(DaikinUserCredentials(email, password))
            ok = await daikin.login()

            if ok is False:
                errors["base"] = "auth_failed"
            else:
                return self.async_create_entry(
                    title="Daikin One",
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                        # internal options
                        CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY: 1,
                    },
                )

        return self.async_show_form(step_id="user", data_schema=self.schema, errors=errors)


class DaikinOneOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Manage inferred heat-pump names and head-unit membership."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        super().__init__(config_entry)
        self._groups = [
            DaikinHeatPumpGroup.from_dict(group) for group in self.options.get(CONF_OPTION_HEAT_PUMP_GROUPS_KEY, [])
        ]
        self._selected_group_id: str | None = None
        self._selected_thermostat_id: str | None = None
        self._removed_group_ids: set[str] = set()
        self._emulation_tolerance = float(
            self.options.get(CONF_OPTION_EMULATION_TOLERANCE, DEFAULT_EMULATION_TOLERANCE)
        )
        self._emulation_dwell_minutes = int(
            self.options.get(CONF_OPTION_EMULATION_DWELL_MINUTES, DEFAULT_EMULATION_DWELL_MINUTES)
        )
        self._convert_external_auto = bool(
            self.options.get(CONF_OPTION_CONVERT_EXTERNAL_AUTO, DEFAULT_CONVERT_EXTERNAL_AUTO)
        )
        self._external_controls = {
            config.thermostat_id: config
            for raw in self.options.get(CONF_OPTION_EXTERNAL_TEMPERATURE_CONTROLS, [])
            if isinstance(raw, dict)
            for config in [ExternalTemperatureConfig.from_dict(cast(dict[str, Any], raw))]
        }

    @property
    def _connector(self) -> DaikinOne:
        return self.hass.data[DOMAIN].daikin

    def _known_locations(self) -> dict[str, str]:
        candidates = self._connector.get_heat_pump_candidate_ids()
        return {
            thermostat.id: thermostat.location_id
            for thermostat in self._connector.get_thermostats().values()
            if thermostat.id in candidates
        }

    def _head_options(self) -> dict[str, str]:
        candidates = self._connector.get_heat_pump_candidate_ids()
        return {
            thermostat.id: thermostat.name
            for thermostat in sorted(self._connector.get_thermostats().values(), key=lambda item: item.name.lower())
            if thermostat.id in candidates
        }

    def _thermostat_options(self) -> dict[str, str]:
        return {
            thermostat.id: thermostat.name
            for thermostat in sorted(self._connector.get_thermostats().values(), key=lambda item: item.name.lower())
        }

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show grouping actions."""
        menu_options = ["add_group", "emulation_settings", "external_temperature", "finish"]
        if self._groups:
            menu_options.insert(0, "edit_group")
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_emulation_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Configure global emulated Heat/Cool behavior."""
        if user_input is not None:
            self._emulation_tolerance = float(user_input[CONF_EMULATION_TOLERANCE])
            self._emulation_dwell_minutes = int(user_input[CONF_EMULATION_DWELL_MINUTES])
            self._convert_external_auto = bool(user_input[CONF_CONVERT_EXTERNAL_AUTO])
            return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required(CONF_EMULATION_TOLERANCE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
                vol.Required(CONF_EMULATION_DWELL_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
                vol.Required(CONF_CONVERT_EXTERNAL_AUTO): bool,
            }
        )
        return self.async_show_form(
            step_id="emulation_settings",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_EMULATION_TOLERANCE: self._emulation_tolerance,
                    CONF_EMULATION_DWELL_MINUTES: self._emulation_dwell_minutes,
                    CONF_CONVERT_EXTERNAL_AUTO: self._convert_external_auto,
                },
            ),
        )

    async def async_step_external_temperature(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Select a head for optional external-temperature control."""
        if user_input is not None:
            self._selected_thermostat_id = str(user_input[CONF_THERMOSTAT_ID])
            return await self.async_step_external_temperature_head()
        return self.async_show_form(
            step_id="external_temperature",
            data_schema=vol.Schema({vol.Required(CONF_THERMOSTAT_ID): vol.In(self._thermostat_options())}),
        )

    async def async_step_external_temperature_head(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Configure one head's external sensor and bias limit."""
        thermostat_id = self._selected_thermostat_id
        if thermostat_id is None or thermostat_id not in self._thermostat_options():
            return self.async_abort(reason="unknown_head")
        existing = self._external_controls.get(thermostat_id)
        errors: dict[str, str] = {}
        if user_input is not None:
            if existing is not None and bool(user_input.get(CONF_DELETE_EXTERNAL_CONTROL, False)):
                self._external_controls.pop(thermostat_id, None)
                self._selected_thermostat_id = None
                return await self.async_step_init()
            sensor_entity_id = str(user_input[CONF_SENSOR_ENTITY_ID])
            sensor_state = self.hass.states.get(sensor_entity_id)
            attributes = (
                cast(
                    dict[str, Any],
                    cast(object, sensor_state.attributes),  # pyright: ignore[reportUnknownMemberType]
                )
                if sensor_state is not None
                else {}
            )
            if sensor_state is None or attributes.get("device_class") != SensorDeviceClass.TEMPERATURE:
                errors[CONF_SENSOR_ENTITY_ID] = "not_temperature_sensor"
            humidity_sensor_entity_id = str(user_input.get(CONF_HUMIDITY_SENSOR_ENTITY_ID) or "") or None
            if humidity_sensor_entity_id is not None:
                humidity_state = self.hass.states.get(humidity_sensor_entity_id)
                humidity_attributes = (
                    cast(
                        dict[str, Any],
                        cast(object, humidity_state.attributes),  # pyright: ignore[reportUnknownMemberType]
                    )
                    if humidity_state is not None
                    else {}
                )
                if humidity_state is None or humidity_attributes.get("device_class") != SensorDeviceClass.HUMIDITY:
                    errors[CONF_HUMIDITY_SENSOR_ENTITY_ID] = "not_humidity_sensor"
            if not errors:
                self._external_controls[thermostat_id] = ExternalTemperatureConfig(
                    thermostat_id=thermostat_id,
                    sensor_entity_id=sensor_entity_id,
                    max_bias=float(user_input[CONF_MAX_BIAS]),
                    humidity_sensor_entity_id=humidity_sensor_entity_id,
                )
                self._selected_thermostat_id = None
                return await self.async_step_init()

        schema: dict[vol.Marker, Any] = {
            vol.Required(CONF_SENSOR_ENTITY_ID): selector.EntitySelector(  # pyright: ignore[reportUnknownMemberType]
                selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.TEMPERATURE)
            ),
            vol.Optional(
                CONF_HUMIDITY_SENSOR_ENTITY_ID
            ): selector.EntitySelector(  # pyright: ignore[reportUnknownMemberType]
                selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.HUMIDITY)
            ),
            vol.Required(CONF_MAX_BIAS): selector.NumberSelector(  # pyright: ignore[reportUnknownMemberType]
                selector.NumberSelectorConfig(
                    min=0.5,
                    max=10.0,
                    step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="°C",
                )
            ),
        }
        if existing is not None:
            schema[vol.Optional(CONF_DELETE_EXTERNAL_CONTROL)] = bool
        return self.async_show_form(
            step_id="external_temperature_head",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema),
                {
                    CONF_SENSOR_ENTITY_ID: existing.sensor_entity_id if existing else None,
                    CONF_HUMIDITY_SENSOR_ENTITY_ID: existing.humidity_sensor_entity_id if existing else None,
                    CONF_MAX_BIAS: existing.max_bias if existing else DEFAULT_EXTERNAL_TEMPERATURE_MAX_BIAS,
                    CONF_DELETE_EXTERNAL_CONTROL: False,
                },
            ),
            errors=errors,
            description_placeholders={"head": self._thermostat_options()[thermostat_id]},
        )

    async def async_step_edit_group(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Select a group to edit."""
        if user_input is not None:
            self._selected_group_id = str(user_input[CONF_GROUP_ID])
            return await self.async_step_group()

        options = {group.id: group.name for group in self._groups}
        return self.async_show_form(
            step_id="edit_group",
            data_schema=vol.Schema({vol.Required(CONF_GROUP_ID): vol.In(options)}),
        )

    async def async_step_add_group(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Start a new heat-pump group."""
        self._selected_group_id = None
        return await self.async_step_group(user_input)

    async def async_step_group(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create, edit, or remove one group."""
        existing = next((group for group in self._groups if group.id == self._selected_group_id), None)
        errors: dict[str, str] = {}
        if user_input is not None:
            if existing is not None and user_input.get(CONF_DELETE_GROUP, False):
                self._groups.remove(existing)
                self._removed_group_ids.add(existing.id)
                self._selected_group_id = None
                return await self.async_step_init()

            name = str(user_input[CONF_GROUP_NAME]).strip()
            member_ids = {str(item) for item in user_input[CONF_GROUP_MEMBERS]}
            errors = validate_heat_pump_group(
                name,
                member_ids,
                self._selected_group_id,
                self._groups,
                self._known_locations(),
            )
            if not errors:
                energy_source_id = (
                    existing.energy_source_id
                    if existing is not None and existing.energy_source_id in member_ids
                    else self._connector.select_heat_pump_energy_source(member_ids)
                )
                updated = DaikinHeatPumpGroup(
                    id=existing.id if existing is not None else f"heat-pump-{uuid4()}",
                    name=name,
                    location_id=self._known_locations()[next(iter(member_ids))],
                    thermostat_ids=tuple(sorted(member_ids)),
                    energy_source_id=energy_source_id,
                )
                if existing is not None:
                    self._groups[self._groups.index(existing)] = updated
                else:
                    self._groups.append(updated)
                self._selected_group_id = None
                return await self.async_step_init()

        default_name = existing.name if existing is not None else f"Heat Pump {len(self._groups) + 1}"
        default_members = list(existing.thermostat_ids) if existing is not None else []
        schema: dict[vol.Marker, Any] = {
            vol.Required(CONF_GROUP_NAME): str,
            vol.Required(CONF_GROUP_MEMBERS): cv.multi_select(self._head_options()),
        }
        if existing is not None:
            schema[vol.Optional(CONF_DELETE_GROUP)] = bool
        data_schema = self.add_suggested_values_to_schema(
            vol.Schema(schema),
            {
                CONF_GROUP_NAME: default_name,
                CONF_GROUP_MEMBERS: default_members,
                CONF_DELETE_GROUP: False,
            },
        )
        return self.async_show_form(step_id="group", data_schema=data_schema, errors=errors)

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Persist staged groups and clean registry entries for removed groups."""
        registry = er.async_get(self.hass)
        for entry in er.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            if any(entry.unique_id.startswith(f"{group_id}-") for group_id in self._removed_group_ids):
                registry.async_remove(entry.entity_id)

        return self.async_create_entry(
            title="",
            data={
                **self.options,
                CONF_OPTION_HEAT_PUMP_GROUPS_SCHEMA_VERSION_KEY: HEAT_PUMP_GROUPS_SCHEMA_VERSION,
                CONF_OPTION_HEAT_PUMP_GROUPS_KEY: [group.as_dict() for group in self._groups],
                CONF_OPTION_EMULATION_TOLERANCE: self._emulation_tolerance,
                CONF_OPTION_EMULATION_DWELL_MINUTES: self._emulation_dwell_minutes,
                CONF_OPTION_CONVERT_EXTERNAL_AUTO: self._convert_external_auto,
                CONF_OPTION_EXTERNAL_TEMPERATURE_CONTROLS: [
                    config.as_dict()
                    for config in sorted(self._external_controls.values(), key=lambda item: item.thermostat_id)
                ],
            },
        )
