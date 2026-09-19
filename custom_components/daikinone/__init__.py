import logging
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.issue_registry import IssueSeverity
from homeassistant.util import Throttle

from custom_components.daikinone.const import (
    CONF_OPTION_HEAT_PUMP_GROUPS_KEY,
    CONF_OPTION_HEAT_PUMP_GROUPS_SCHEMA_VERSION_KEY,
    CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY,
    HEAT_PUMP_GROUPS_SCHEMA_VERSION,
    PLATFORMS,
    DOMAIN,
    MIN_TIME_BETWEEN_UPDATES,
)
from custom_components.daikinone.daikinone import DaikinOne, DaikinUserCredentials
from custom_components.daikinone.emulation import DaikinEmulationController
from custom_components.daikinone.external_temperature import ExternalTemperatureController

log = logging.getLogger(__name__)


@dataclass
class DaikinOneData:
    _hass: HomeAssistant
    entry: ConfigEntry
    daikin: DaikinOne
    emulation: DaikinEmulationController = field(init=False)
    external_temperature: ExternalTemperatureController = field(init=False)

    def __post_init__(self) -> None:
        self.emulation = DaikinEmulationController(self._hass, self.entry, self.daikin)
        self.external_temperature = ExternalTemperatureController(self._hass, self.entry, self.daikin)

    async def update(self, no_throttle: bool = False) -> None:
        """Get the latest data from Daikin cloud"""
        await self._update(no_throttle=no_throttle)  # type: ignore

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def _update(self) -> None:
        """
        @Throttle throws off the type checker so use internal implementation that can be type ignored in one place
        instead of everywhere that calls update
        """
        log.debug("Updating Daikin One data from cloud")
        await self.daikin.update()
        await self.external_temperature.async_reconcile()
        await self.emulation.async_reconcile()


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when heat-pump grouping options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _update_heat_pump_grouping_issue(hass: HomeAssistant, entry: ConfigEntry, data: DaikinOneData) -> None:
    """Keep one actionable issue in sync with unresolved supported heads."""
    unassigned_ids = data.daikin.get_unassigned_heat_pump_thermostat_ids()
    issue_id = f"{entry.entry_id}_heat_pump_grouping"
    if not unassigned_ids:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    thermostat_names = sorted(
        thermostat.name for thermostat in data.daikin.get_thermostats().values() if thermostat.id in unassigned_ids
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=True,
        severity=IssueSeverity.WARNING,
        translation_key="heat_pump_grouping",
        translation_placeholders={"heads": ", ".join(thermostat_names)},
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the given config entry"""

    log.info(f"Setting up Daikin One integration for {entry.data[CONF_EMAIL]}")

    configured_groups = None
    if entry.options.get(CONF_OPTION_HEAT_PUMP_GROUPS_SCHEMA_VERSION_KEY) == HEAT_PUMP_GROUPS_SCHEMA_VERSION:
        configured_groups = entry.options.get(CONF_OPTION_HEAT_PUMP_GROUPS_KEY, [])

    # create daikin one connector
    data = DaikinOneData(
        hass,
        entry,
        DaikinOne(
            DaikinUserCredentials(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]),
            heat_pump_groups=configured_groups,
        ),
    )
    await data.update()
    await data.external_temperature.async_initialize()

    if data.daikin.heat_pump_groups_inferred:
        hass.config_entries.async_update_entry(
            entry,
            options={
                **entry.options,
                CONF_OPTION_HEAT_PUMP_GROUPS_SCHEMA_VERSION_KEY: HEAT_PUMP_GROUPS_SCHEMA_VERSION,
                CONF_OPTION_HEAT_PUMP_GROUPS_KEY: data.daikin.get_heat_pump_groups(),
            },
        )
    hass.data[DOMAIN] = data

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _update_heat_pump_grouping_issue(hass, entry, data)

    # load platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry and platforms"""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await hass.data[DOMAIN].external_temperature.async_shutdown()
        await hass.data[DOMAIN].emulation.async_shutdown()
        hass.data.pop(DOMAIN)
    return ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    log.debug("Migrating from version %s.%s", entry.version, entry.minor_version)

    if entry.version > 1:
        log.error(
            "Incompatible downgrade detected, please restore from a earlier backup or remove and re-add the integration",
            entry.version,
            entry.minor_version,
        )
        return False

    if entry.version == 1:
        new = {**entry.data}

        # migrate to 1.2
        if entry.minor_version < 2:
            entry.minor_version = 2

            # retain legacy id schema if this is an upgrade of an existing entry
            new[CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY] = 0

        hass.config_entries.async_update_entry(entry, data=new)

    log.info("Migration to version %s.%s successful", entry.version, entry.minor_version)

    return True
