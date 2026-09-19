import copy
import json
import logging
from datetime import timedelta
from enum import Enum, auto
from statistics import median
from urllib.parse import urljoin
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import aiohttp
from aiohttp import ClientError
from pydantic import BaseModel
from pydantic.dataclasses import dataclass

from .exceptions import DaikinServiceException
from custom_components.daikinone.utils import Temperature

log = logging.getLogger(__name__)

DAIKIN_API_URL_BASE = "https://api.daikinskyport.com"
DAIKIN_API_URL_LOGIN = urljoin(DAIKIN_API_URL_BASE, "/users/auth/login")
DAIKIN_API_URL_REFRESH_TOKEN = urljoin(DAIKIN_API_URL_BASE, "/users/auth/token")
DAIKIN_API_URL_LOCATIONS = urljoin(DAIKIN_API_URL_BASE, "/locations")
DAIKIN_API_URL_DEVICES = urljoin(DAIKIN_API_URL_BASE, "/devices")
DAIKIN_API_URL_DEVICE_DATA = urljoin(DAIKIN_API_URL_BASE, "/deviceData")


@dataclass
class DaikinUserCredentials:
    email: str
    password: str


@dataclass
class DaikinDevice:
    id: str
    name: str
    model: str
    firmware_version: str


@dataclass
class DaikinEquipment(DaikinDevice):
    thermostat_id: str
    serial: str


@dataclass
class DaikinIndoorUnit(DaikinEquipment):
    mode: str
    current_airflow: int
    fan_demand_requested_percent: int
    fan_demand_current_percent: int
    heat_demand_requested_percent: int
    heat_demand_current_percent: int
    cool_demand_requested_percent: int | None
    cool_demand_current_percent: int | None
    humidification_demand_requested_percent: int
    dehumidification_demand_requested_percent: int | None
    power_usage: float


class DaikinOutdoorUnitReversingValveStatus(Enum):
    OFF = 0
    ON = 1
    UNKNOWN = 255


class DaikinOutdoorUnitHeaterStatus(Enum):
    OFF = 0
    ON = 1
    UNKNOWN = 255


@dataclass
class DaikinOutdoorUnit(DaikinEquipment):
    inverter_software_version: str | None
    total_runtime: timedelta
    mode: str
    compressor_speed_target: int
    compressor_speed_current: int
    outdoor_fan_target_rpm: int
    outdoor_fan_rpm: int
    suction_pressure_psi: int
    eev_opening_percent: int
    reversing_valve: DaikinOutdoorUnitReversingValveStatus
    heat_demand_percent: int
    cool_demand_percent: int
    fan_demand_percent: int
    fan_demand_airflow: int
    dehumidify_demand_percent: int
    air_temperature: Temperature
    coil_temperature: Temperature
    discharge_temperature: Temperature
    liquid_temperature: Temperature
    defrost_sensor_temperature: Temperature
    inverter_fin_temperature: Temperature
    power_usage: float
    compressor_amps: float
    inverter_amps: float
    fan_motor_amps: float
    crank_case_heater: DaikinOutdoorUnitHeaterStatus
    drain_pan_heater: DaikinOutdoorUnitHeaterStatus
    preheat_heater: DaikinOutdoorUnitHeaterStatus

    # needs confirmation on unit in raw data
    # preheat_output_watts: int | None

    # compressor reduction mode - ctOutdoorCompressorReductionMode - 1=off, ?


class DaikinOneAirQualitySensorSummaryLevel(Enum):
    GOOD = 0
    MODERATE = 1
    UNHEALTHY = 2
    # The app shows 3 as "Unhealthy" but with a red color instead of orange, so we will call it "Hazardous"
    HAZARDOUS = 3


@dataclass
class DaikinOneAirQualitySensorOutdoor:
    aqi: int
    aqi_summary_level: DaikinOneAirQualitySensorSummaryLevel
    particles_microgram_m3: int
    # even though the app displays ppb, the levels seem to be µg/m³ based on my local weather data
    ozone_microgram_m3: int


@dataclass
class DaikinOneAirQualitySensorIndoor:
    aqi: int
    aqi_summary_level: DaikinOneAirQualitySensorSummaryLevel
    # TODO: see if there is unit data available from somewhere
    particles: int
    particles_summary_level: DaikinOneAirQualitySensorSummaryLevel
    voc: int
    voc_summary_level: DaikinOneAirQualitySensorSummaryLevel


@dataclass
class DaikinEEVCoil(DaikinEquipment):
    indoor_superheat_temperature: Temperature
    liquid_temperature: Temperature
    suction_temperature: Temperature
    pressure_psi: int


class DaikinThermostatCapability(Enum):
    HEAT = auto()
    COOL = auto()
    EMERGENCY_HEAT = auto()


class DaikinThermostatMode(Enum):
    OFF = 0
    HEAT = 1
    COOL = 2
    AUTO = 3
    AUX_HEAT = 4
    DRY = 5


class DaikinThermostatStatus(Enum):
    COOLING = 1
    DRYING = 2
    HEATING = 3
    CIRCULATING_AIR = 4
    IDLE = 5


@dataclass
class DaikinThermostatSchedule:
    enabled: bool


class DaikinThermostatFanMode(Enum):
    OFF = 0
    ALWAYS_ON = 1
    SCHEDULED = 2


class DaikinThermostatFanSpeed(Enum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2


@dataclass
class DaikinThermostat(DaikinDevice):
    location_id: str
    online: bool
    capabilities: set[DaikinThermostatCapability]
    mode: DaikinThermostatMode
    status: DaikinThermostatStatus
    fan_mode: DaikinThermostatFanMode
    fan_speed: DaikinThermostatFanSpeed
    schedule: DaikinThermostatSchedule
    indoor_temperature: Temperature
    indoor_humidity: int
    set_point_heat: Temperature
    set_point_heat_min: Temperature
    set_point_heat_max: Temperature
    set_point_cool: Temperature
    set_point_cool_min: Temperature
    set_point_cool_max: Temperature
    set_point_auto: Temperature
    set_point_auto_min: Temperature
    set_point_auto_max: Temperature
    outdoor_temperature: Temperature
    outdoor_humidity: int
    air_quality_outdoor: DaikinOneAirQualitySensorOutdoor | None
    air_quality_indoor: DaikinOneAirQualitySensorIndoor | None
    equipment: dict[str, DaikinEquipment]
    indoor_temperature_valid: bool = True
    heat_pump_id: str | None = None


@dataclass(frozen=True)
class DaikinHeatPumpGroup:
    id: str
    name: str
    location_id: str
    thermostat_ids: tuple[str, ...]
    energy_source_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "location_id": self.location_id,
            "thermostat_ids": list(self.thermostat_ids),
            "energy_source_id": self.energy_source_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DaikinHeatPumpGroup":
        thermostat_ids = tuple(str(item) for item in value["thermostat_ids"])
        return cls(
            id=str(value["id"]),
            name=str(value["name"]),
            location_id=str(value["location_id"]),
            thermostat_ids=thermostat_ids,
            energy_source_id=str(value["energy_source_id"]),
        )


@dataclass
class DaikinHeatPump(DaikinDevice):
    location_id: str
    thermostat_ids: tuple[str, ...]
    energy_source_id: str
    power_usage: float | None
    energy_consumption: float | None


@dataclass(frozen=True)
class _DaikinOutdoorTelemetry:
    thermostat_id: str
    location_id: str
    online: bool
    connected_indoor_units: int
    power_usage: float
    energy_consumption: float
    mode: int | str
    outdoor_temperature: float
    compressor_frequency: float | None
    fan_speed: float | None
    discharge_temperature: float | None
    target_discharge_temperature: float | None


class DaikinDeviceDataResponse(BaseModel):
    id: str
    locationId: str
    name: str
    model: str
    firmware: str
    online: bool
    data: dict[str, Any]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _map_outdoor_telemetry(payload: DaikinDeviceDataResponse) -> _DaikinOutdoorTelemetry | None:
    """Map mini-split outdoor telemetry, excluding legacy communicating equipment."""
    if "ctOutdoorUnitType" in payload.data:
        return None

    connected = _number(payload.data.get("oduConnectedIduUnitNumber"))
    power = _number(payload.data.get("oduConsumedPower"))
    energy = _number(payload.data.get("oduIntPowerConsumption"))
    outdoor_temperature = _number(payload.data.get("oduOutdoorTemp"))
    mode = payload.data.get("oduOperatingMode")
    if (
        connected is None
        or connected < 1
        or power is None
        or power < 0
        or energy is None
        or energy < 0
        or outdoor_temperature is None
        or not isinstance(mode, (int, str))
        or isinstance(mode, bool)
    ):
        return None

    return _DaikinOutdoorTelemetry(
        thermostat_id=payload.id,
        location_id=payload.locationId,
        online=payload.online,
        connected_indoor_units=int(connected),
        power_usage=power,
        energy_consumption=energy,
        mode=mode,
        outdoor_temperature=outdoor_temperature,
        compressor_frequency=_number(payload.data.get("oduCompCurrentFrequency")),
        fan_speed=_number(payload.data.get("oduFanMotorCurrentSpeed")),
        discharge_temperature=_number(payload.data.get("oduCompDischargeTemp")),
        target_discharge_temperature=_number(payload.data.get("oduCompTargetDischargeTemp")),
    )


def _outdoor_telemetry_compatible(left: _DaikinOutdoorTelemetry, right: _DaikinOutdoorTelemetry) -> bool:
    if left.location_id != right.location_id or left.connected_indoor_units != right.connected_indoor_units:
        return False

    energy_tolerance = max(25.0, max(left.energy_consumption, right.energy_consumption) * 0.05)
    if abs(left.energy_consumption - right.energy_consumption) > energy_tolerance:
        return False
    if left.mode != right.mode or abs(left.outdoor_temperature - right.outdoor_temperature) > 2.0:
        return False

    signals = (
        (left.compressor_frequency, right.compressor_frequency, 5.0),
        (left.fan_speed, right.fan_speed, 100.0),
        (left.discharge_temperature, right.discharge_temperature, 5.0),
        (left.target_discharge_temperature, right.target_discharge_temperature, 2.0),
    )
    matches = sum(
        1
        for left_value, right_value, tolerance in signals
        if left_value is not None and right_value is not None and abs(left_value - right_value) <= tolerance
    )
    return matches >= 2


def discover_heat_pump_groups(payloads: list[DaikinDeviceDataResponse]) -> list[DaikinHeatPumpGroup]:
    """Discover conservative, stable initial groupings from a single API snapshot."""
    telemetry = [
        mapped for payload in payloads if (mapped := _map_outdoor_telemetry(payload)) is not None and mapped.online
    ]
    partitions: dict[tuple[str, int], list[_DaikinOutdoorTelemetry]] = {}
    for item in telemetry:
        partitions.setdefault((item.location_id, item.connected_indoor_units), []).append(item)

    components: list[tuple[list[_DaikinOutdoorTelemetry], int]] = []
    for candidates in partitions.values():
        remaining = {candidate.thermostat_id: candidate for candidate in candidates}
        while remaining:
            _, seed = remaining.popitem()
            component = [seed]
            changed = True
            while changed:
                changed = False
                for thermostat_id, candidate in list(remaining.items()):
                    if any(_outdoor_telemetry_compatible(candidate, member) for member in component):
                        component.append(remaining.pop(thermostat_id))
                        changed = True
            components.append((component, len(candidates)))

    groups: list[DaikinHeatPumpGroup] = []
    for component, partition_size in components:
        if len(component) == 1 and partition_size > 1 and component[0].connected_indoor_units > 1:
            continue
        member_ids = tuple(sorted(item.thermostat_id for item in component))
        location_id = component[0].location_id
        group_seed = f"daikinone:{location_id}:{','.join(member_ids)}"
        energy_source = max(component, key=lambda item: item.energy_consumption).thermostat_id
        groups.append(
            DaikinHeatPumpGroup(
                id=f"heat-pump-{uuid5(NAMESPACE_URL, group_seed)}",
                name="",
                location_id=location_id,
                thermostat_ids=member_ids,
                energy_source_id=energy_source,
            )
        )

    groups.sort(key=lambda group: min(group.thermostat_ids))
    return [
        DaikinHeatPumpGroup(
            id=group.id,
            name=f"Heat Pump {index}",
            location_id=group.location_id,
            thermostat_ids=group.thermostat_ids,
            energy_source_id=group.energy_source_id,
        )
        for index, group in enumerate(groups, start=1)
    ]


class DaikinOne:
    """Manages connection to Daikin API and fetching device data"""

    @dataclass
    class _AuthState:
        authenticated: bool = False
        refresh_token: str | None = None
        access_token: str | None = None

    __auth = _AuthState()

    __thermostats: dict[str, DaikinThermostat] = dict()

    def __init__(
        self,
        creds: DaikinUserCredentials,
        heat_pump_groups: list[dict[str, Any]] | None = None,
    ):
        self.creds = creds
        self.__thermostats: dict[str, DaikinThermostat] = {}
        self.__heat_pumps: dict[str, DaikinHeatPump] = {}
        try:
            self.__heat_pump_groups = (
                None
                if heat_pump_groups is None
                else [DaikinHeatPumpGroup.from_dict(group) for group in heat_pump_groups]
            )
        except (KeyError, TypeError, ValueError):
            log.warning("Ignoring invalid persisted heat-pump groups", exc_info=True)
            self.__heat_pump_groups = None
        self.__heat_pump_groups_inferred = False
        self.__outdoor_telemetry: dict[str, _DaikinOutdoorTelemetry] = {}

    async def get_all_raw_device_data(self) -> list[dict[str, Any]]:
        """Get raw device data"""
        return await self.__req(DAIKIN_API_URL_DEVICE_DATA)

    async def get_raw_device_data(self, device_id: str) -> dict[str, Any]:
        """Get raw device data"""
        return await self.__req(f"{DAIKIN_API_URL_DEVICE_DATA}/{device_id}")

    async def update(self) -> None:
        await self.__refresh_thermostats()

    def get_thermostat(self, thermostat_id: str) -> DaikinThermostat:
        return copy.deepcopy(self.__thermostats[thermostat_id])

    def get_thermostats(self) -> dict[str, DaikinThermostat]:
        return copy.deepcopy(self.__thermostats)

    def get_heat_pump(self, heat_pump_id: str) -> DaikinHeatPump:
        return copy.deepcopy(self.__heat_pumps[heat_pump_id])

    def get_heat_pumps(self) -> dict[str, DaikinHeatPump]:
        return copy.deepcopy(self.__heat_pumps)

    def get_heat_pump_groups(self) -> list[dict[str, Any]]:
        return [group.as_dict() for group in self.__heat_pump_groups or []]

    def get_heat_pump_candidate_ids(self) -> set[str]:
        return set(self.__outdoor_telemetry)

    def get_unassigned_heat_pump_thermostat_ids(self) -> set[str]:
        assigned = {thermostat_id for group in self.__heat_pump_groups or [] for thermostat_id in group.thermostat_ids}
        return self.get_heat_pump_candidate_ids() - assigned

    def select_heat_pump_energy_source(self, thermostat_ids: set[str]) -> str:
        candidates = [self.__outdoor_telemetry[item] for item in thermostat_ids if item in self.__outdoor_telemetry]
        if not candidates:
            raise ValueError("Heat-pump group has no supported head units")
        return max(candidates, key=lambda item: item.energy_consumption).thermostat_id

    @property
    def heat_pump_groups_inferred(self) -> bool:
        return self.__heat_pump_groups_inferred

    async def set_thermostat_mode(self, thermostat_id: str, mode: DaikinThermostatMode) -> None:
        """Set thermostat mode"""

        # There's a difference, if we're turning off, we need to set specific values
        if mode == DaikinThermostatMode.OFF:
            await self.__req(
                url=f"{DAIKIN_API_URL_DEVICE_DATA}/{thermostat_id}",
                method="PUT",
                body={"iduOperatingMode": 3, "iduOnOff": False},
            )
        else:
            await self.__req(
                url=f"{DAIKIN_API_URL_DEVICE_DATA}/{thermostat_id}",
                method="PUT",
                body={"iduOperatingMode": mode.value, "iduOnOff": True},  # old: mode
            )
        if thermostat_id in self.__thermostats:
            self.__thermostats[thermostat_id].mode = mode

    async def set_thermostat_home_set_points(
        self,
        thermostat_id: str,
        heat: Temperature | None = None,
        cool: Temperature | None = None,
        auto: Temperature | None = None,
        override_schedule: bool = False,
    ) -> None:
        """Set thermostat home set points"""
        if heat is None and cool is None and auto is None:
            raise ValueError("At least one of heat, cool or auto set points must be set")

        payload: dict[str, Any] = {}
        if heat is not None:
            payload["iduHeatSetpoint"] = round(heat.celsius * 2) / 2
        if cool is not None:
            payload["iduCoolSetpoint"] = round(cool.celsius * 2) / 2
        if auto is not None:
            payload["iduAutoSetpoint"] = round(auto.celsius * 2) / 2

        if override_schedule:
            payload["schedOverride"] = 1

        await self.__req(
            url=f"{DAIKIN_API_URL_DEVICE_DATA}/{thermostat_id}",
            method="PUT",
            body=payload,
        )
        if thermostat_id in self.__thermostats:
            thermostat = self.__thermostats[thermostat_id]
            if heat is not None:
                thermostat.set_point_heat = heat
            if cool is not None:
                thermostat.set_point_cool = cool
            if auto is not None:
                thermostat.set_point_auto = auto

    async def set_thermostat_fan_mode(self, thermostat_id: str, fan_mode: DaikinThermostatFanMode) -> None:
        """Set thermostat fan mode"""
        await self.__req(
            url=f"{DAIKIN_API_URL_DEVICE_DATA}/{thermostat_id}",
            method="PUT",
            body={"fanCirculate": fan_mode.value},
        )

    async def set_thermostat_fan_speed(self, thermostat_id: str, fan_speed: DaikinThermostatFanSpeed) -> None:
        """Set thermostat fan speed"""
        await self.__req(
            url=f"{DAIKIN_API_URL_DEVICE_DATA}/{thermostat_id}",
            method="PUT",
            body={"fanCirculateSpeed": fan_speed.value},
        )

    async def __refresh_thermostats(self):
        devices = await self.__req(DAIKIN_API_URL_DEVICE_DATA)
        devices = [DaikinDeviceDataResponse(**device) for device in devices]

        self.__thermostats = {device.id: self.__map_thermostat(device) for device in devices}

        if self.__heat_pump_groups is None:
            self.__heat_pump_groups = discover_heat_pump_groups(devices)
            self.__heat_pump_groups_inferred = True

        self.__outdoor_telemetry = {
            mapped.thermostat_id: mapped for device in devices if (mapped := _map_outdoor_telemetry(device)) is not None
        }
        self.__heat_pumps = self.__map_heat_pumps(self.__outdoor_telemetry)

        log.info(f"Cached {len(self.__thermostats)} thermostats and {len(self.__heat_pumps)} heat pumps")

    def __map_heat_pumps(self, telemetry: dict[str, _DaikinOutdoorTelemetry]) -> dict[str, DaikinHeatPump]:
        heat_pumps: dict[str, DaikinHeatPump] = {}
        for group in self.__heat_pump_groups or []:
            members = [telemetry[member_id] for member_id in group.thermostat_ids if member_id in telemetry]
            if not members:
                continue

            online_members = [member for member in members if member.online]
            power_usage = median(member.power_usage for member in online_members) if online_members else None
            energy_source = telemetry.get(group.energy_source_id)
            energy_consumption = (
                energy_source.energy_consumption if energy_source is not None and energy_source.online else None
            )
            heat_pumps[group.id] = DaikinHeatPump(
                id=group.id,
                name=group.name,
                model="Mini-split Heat Pump",
                firmware_version="",
                location_id=group.location_id,
                thermostat_ids=group.thermostat_ids,
                energy_source_id=group.energy_source_id,
                power_usage=power_usage,
                energy_consumption=energy_consumption,
            )
            for member_id in group.thermostat_ids:
                if member_id in self.__thermostats:
                    self.__thermostats[member_id].heat_pump_id = group.id

        return heat_pumps

    def __map_thermostat(self, payload: DaikinDeviceDataResponse) -> DaikinThermostat:
        try:
            capabilities = set(DaikinThermostatCapability)
            if payload.data.get("ctSystemCapHeat") or payload.data.get("iduHeatSetpoint"):
                capabilities.add(DaikinThermostatCapability.HEAT)
            if payload.data.get("ctSystemCapCool") or payload.data.get("iduCoolSetpoint"):
                capabilities.add(DaikinThermostatCapability.COOL)
            if payload.data.get("ctSystemCapEmergencyHeat"):
                capabilities.add(DaikinThermostatCapability.EMERGENCY_HEAT)

            # Fields beginning with
            # 'adpt' relate to the wifi adapter
            # 'idu' relate to indoor unit (wall mounted head unit)
            # 'odu' relate to outdoor unit (heatpump)
            # 'shed' relate to scheduling functionality

            # Determine mode
            status = DaikinThermostatStatus.IDLE
            if payload.data.get("iduOnOff", False):
                if payload.data.get("iduThermoState", False):
                    # System is doing something (because power is on and thermostat is active)
                    # Let's determine what exactly it's doing
                    if payload.data.get("iduFanMotorCurrentRotationSpeed", 0) > 0:
                        if payload.data.get("iduHeatPumpCycleMode", 0) == 0:
                            status = DaikinThermostatStatus.CIRCULATING_AIR
                        elif payload.data.get("iduHeatPumpCycleMode", 0) == 1:
                            status = DaikinThermostatStatus.HEATING
                        elif payload.data.get("iduHeatPumpCycleMode", 0) == 2:
                            status = DaikinThermostatStatus.COOLING
                elif payload.data.get("iduFanMotorCurrentRotationSpeed", 0) > 0:
                    if payload.data.get("iduHeatPumpCycleMode", 0) == 2:
                        status = DaikinThermostatStatus.CIRCULATING_AIR  # DRYING # Drying has not thermostat properties
                    else:
                        status = DaikinThermostatStatus.CIRCULATING_AIR

            thermostat = DaikinThermostat(
                id=payload.id,
                location_id=payload.locationId,
                name=payload.name,
                model=payload.model,
                firmware_version=payload.firmware,
                online=payload.online,
                capabilities=capabilities,
                # Mode is special, since when the thermostat is OFF, it will show AUTO but iduOnOff is false
                mode=DaikinThermostatMode(
                    payload.data.get("iduOperatingMode", DaikinThermostatMode.OFF)
                    if payload.data.get("iduOnOff", False)
                    else DaikinThermostatMode.OFF
                ),
                status=status,
                fan_mode=DaikinThermostatFanMode(payload.data.get("fanCirculate", DaikinThermostatFanMode.OFF)),
                fan_speed=DaikinThermostatFanSpeed(payload.data.get("fanCirculateSpeed", DaikinThermostatFanSpeed.LOW)),
                schedule=DaikinThermostatSchedule(enabled=payload.data.get("schedEnabled", False)),
                indoor_temperature=Temperature.from_celsius(payload.data.get("iduRoomTemp", 0)),  # old: tempIndoor
                indoor_humidity=payload.data.get("humIndoor", 0),
                set_point_heat=Temperature.from_celsius(payload.data.get("iduHeatSetpoint", 0)),  # old: hspActive
                set_point_heat_min=Temperature.from_celsius(payload.data.get("EquipProtocolMinHeatSetpoint", 10)),
                set_point_heat_max=Temperature.from_celsius(payload.data.get("EquipProtocolMaxHeatSetpoint", 30)),
                set_point_cool=Temperature.from_celsius(payload.data.get("iduCoolSetpoint", 0)),  # old:cspActive
                set_point_cool_min=Temperature.from_celsius(payload.data.get("EquipProtocolMinCoolSetpoint", 18)),
                set_point_cool_max=Temperature.from_celsius(payload.data.get("EquipProtocolMaxCoolSetpoint", 32)),
                set_point_auto=Temperature.from_celsius(payload.data.get("iduAutoSetpoint", 0)),  # old: hspActive
                set_point_auto_min=Temperature.from_celsius(payload.data.get("EquipProtocolMinHeatSetpoint", 18)),
                set_point_auto_max=Temperature.from_celsius(payload.data.get("EquipProtocolMaxHeatSetpoint", 30)),
                outdoor_temperature=Temperature.from_celsius(payload.data.get("oduOutdoorTemp", 0)),  # old: tempOutdoor
                outdoor_humidity=payload.data.get("humOutdoor", 0),
                air_quality_outdoor=self.__map_air_quality_outdoor(payload),
                air_quality_indoor=self.__map_air_quality_indoor(payload),
                equipment=self.__map_equipment(payload),
                indoor_temperature_valid="iduRoomTemp" in payload.data,
            )
        except Exception as e:
            # Improve logging when Daikin changes payload
            log.exception("Failed to setup thermostat")
            log.error(f"Contents of payload: {payload}")
            raise e

        return thermostat

    def __map_air_quality_outdoor(self, payload: DaikinDeviceDataResponse) -> DaikinOneAirQualitySensorOutdoor | None:
        if "aqOutdoorAvailable" not in payload.data:
            return None

        return DaikinOneAirQualitySensorOutdoor(
            aqi=payload.data["aqOutdoorValue"],
            aqi_summary_level=payload.data["aqOutdoorLevel"],
            particles_microgram_m3=payload.data["aqOutdoorParticles"],
            ozone_microgram_m3=payload.data["aqOutdoorOzone"],
        )

    def __map_air_quality_indoor(self, payload: DaikinDeviceDataResponse) -> DaikinOneAirQualitySensorIndoor | None:
        if "aqIndoorAvailable" not in payload.data:
            return None

        return DaikinOneAirQualitySensorIndoor(
            aqi=payload.data["aqIndoorValue"],
            aqi_summary_level=payload.data["aqIndoorLevel"],
            particles=payload.data["aqIndoorParticlesValue"],
            particles_summary_level=payload.data["aqIndoorParticlesLevel"],
            voc=payload.data["aqIndoorVOCValue"],
            voc_summary_level=payload.data["aqIndoorVOCLevel"],
        )

    def __map_equipment(self, payload: DaikinDeviceDataResponse) -> dict[str, DaikinEquipment]:
        equipment: dict[str, DaikinEquipment] = {}

        # air handler
        if "ctAHUnitType" in payload.data and payload.data["ctAHUnitType"] < 255:
            model = payload.data["ctAHModelNoCharacter1_15"].strip()
            serial = payload.data["ctAHSerialNoCharacter1_15"].strip()
            eid = f"{model}-{serial}"
            name = "Air Handler"

            equipment[eid] = DaikinIndoorUnit(
                id=eid,
                thermostat_id=payload.id,
                name=name,
                model=model,
                firmware_version=payload.data["ctAHControlSoftwareVersion"].strip(),
                serial=serial,
                mode=payload.data["ctAHMode"].strip().capitalize(),
                current_airflow=payload.data["ctAHCurrentIndoorAirflow"],
                fan_demand_requested_percent=round(payload.data["ctAHFanRequestedDemand"] / 2),
                fan_demand_current_percent=round(payload.data["ctAHFanCurrentDemandStatus"] / 2),
                heat_demand_requested_percent=round(payload.data["ctAHHeatRequestedDemand"] / 2),
                heat_demand_current_percent=round(payload.data["ctAHHeatCurrentDemandStatus"] / 2),
                cool_demand_requested_percent=None,
                cool_demand_current_percent=None,
                humidification_demand_requested_percent=round(payload.data["ctAHHumidificationRequestedDemand"] / 2),
                dehumidification_demand_requested_percent=None,
                power_usage=payload.data["ctIndoorPower"] / 10,
            )

        # furnace
        if "ctIFCUnitType" in payload.data and payload.data["ctIFCUnitType"] < 255:
            model = payload.data["ctIFCModelNoCharacter1_15"].strip()
            serial = payload.data["ctIFCSerialNoCharacter1_15"].strip()
            eid = f"{model}-{serial}"
            name = "Furnace"

            equipment[eid] = DaikinIndoorUnit(
                id=eid,
                thermostat_id=payload.id,
                name=name,
                model=model,
                firmware_version=payload.data["ctIFCControlSoftwareVersion"].strip(),
                serial=serial,
                mode=payload.data["ctIFCOperatingHeatCoolMode"].strip().capitalize(),
                current_airflow=payload.data["ctIFCIndoorBlowerAirflow"],
                fan_demand_requested_percent=round(payload.data["ctIFCFanRequestedDemandPercent"] / 2),
                fan_demand_current_percent=round(payload.data["ctIFCCurrentFanActualStatus"] / 2),
                heat_demand_requested_percent=round(payload.data["ctIFCHeatRequestedDemandPercent"] / 2),
                heat_demand_current_percent=round(payload.data["ctIFCCurrentHeatActualStatus"] / 2),
                cool_demand_requested_percent=round(payload.data["ctIFCCoolRequestedDemandPercent"] / 2),
                cool_demand_current_percent=round(payload.data["ctIFCCurrentCoolActualStatus"] / 2),
                humidification_demand_requested_percent=round(payload.data["ctIFCHumRequestedDemandPercent"] / 2),
                dehumidification_demand_requested_percent=round(payload.data["ctIFCDehumRequestedDemandPercent"] / 2),
                power_usage=payload.data["ctIndoorPower"] / 10,
            )

        # outdoor unit
        if "ctOutdoorUnitType" in payload.data and payload.data["ctOutdoorUnitType"] < 255:
            model = payload.data["ctOutdoorModelNoCharacter1_15"].strip()
            serial = payload.data["ctOutdoorSerialNoCharacter1_15"].strip()
            eid = f"{model}-{serial}"

            # assume it can cool, and if it can also heat it should be a heat pump
            name = "Condensing Unit"
            if payload.data.get("ctOutdoorHeatMaxRPS", 0) != 0 and payload.data.get("ctOutdoorHeatMaxRPS", 0) != 65535:
                name = "Heat Pump"

            equipment[eid] = DaikinOutdoorUnit(
                id=eid,
                thermostat_id=payload.id,
                name=name,
                model=model,
                serial=serial,
                firmware_version=payload.data["ctOutdoorControlSoftwareVersion"].strip(),
                inverter_software_version=payload.data["ctOutdoorInverterSoftwareVersion"].strip(),
                total_runtime=timedelta(hours=payload.data["ctOutdoorCompressorRunTime"]),
                mode=payload.data["ctOutdoorMode"].strip().capitalize(),
                compressor_speed_target=payload.data["ctTargetCompressorspeed"],
                compressor_speed_current=payload.data["ctCurrentCompressorRPS"],
                outdoor_fan_target_rpm=payload.data["ctTargetODFanRPM"] * 10,
                outdoor_fan_rpm=payload.data["ctOutdoorFanRPM"],
                suction_pressure_psi=payload.data["ctOutdoorSuctionPressure"],
                eev_opening_percent=payload.data["ctOutdoorEEVOpening"],
                reversing_valve=DaikinOutdoorUnitReversingValveStatus(payload.data["ctReversingValve"]),
                heat_demand_percent=round(payload.data["ctOutdoorHeatRequestedDemand"] / 2),
                cool_demand_percent=round(payload.data["ctOutdoorCoolRequestedDemand"] / 2),
                fan_demand_percent=round(payload.data["ctOutdoorFanRequestedDemandPercentage"] / 2),
                fan_demand_airflow=payload.data["ctOutdoorRequestedIndoorAirflow"],
                dehumidify_demand_percent=round(payload.data["ctOutdoorDeHumidificationRequestedDemand"] / 2),
                air_temperature=Temperature.from_fahrenheit(payload.data["ctOutdoorAirTemperature"] / 10),
                coil_temperature=Temperature.from_fahrenheit(payload.data["ctOutdoorCoilTemperature"] / 10),
                discharge_temperature=Temperature.from_fahrenheit(payload.data["ctOutdoorDischargeTemperature"] / 10),
                liquid_temperature=Temperature.from_fahrenheit(payload.data["ctOutdoorLiquidTemperature"] / 10),
                defrost_sensor_temperature=Temperature.from_fahrenheit(
                    payload.data["ctOutdoorDefrostSensorTemperature"] / 10
                ),
                inverter_fin_temperature=Temperature.from_celsius(payload.data["ctInverterFinTemp"]),
                power_usage=payload.data["ctOutdoorPower"] * 10,
                compressor_amps=payload.data["ctCompressorCurrent"] / 10,
                inverter_amps=payload.data["ctInverterCurrent"] / 10,
                fan_motor_amps=payload.data["ctODFanMotorCurrent"] / 10,
                crank_case_heater=DaikinOutdoorUnitHeaterStatus(payload.data["ctCrankCaseHeaterOnOff"]),
                drain_pan_heater=DaikinOutdoorUnitHeaterStatus(payload.data["ctDrainPanHeaterOnOff"]),
                preheat_heater=DaikinOutdoorUnitHeaterStatus(payload.data["ctPreHeatOnOff"]),
            )

        # eev coil
        if "ctCoilUnitType" in payload.data and payload.data["ctCoilUnitType"] < 255:
            model = "EEV Coil"
            serial = payload.data["ctCoilSerialNoCharacter1_15"].strip()
            eid = f"eevcoil-{serial}"
            name = "EEV Coil"

            equipment[eid] = DaikinEEVCoil(
                id=eid,
                thermostat_id=payload.id,
                name=name,
                model=model,
                serial=serial,
                firmware_version=payload.data["ctCoilControlSoftwareVersion"].strip(),
                pressure_psi=payload.data["ctEEVCoilPressureSensor"],
                indoor_superheat_temperature=Temperature.from_fahrenheit(payload.data["ctEEVCoilSuperHeatValue"] / 10),
                liquid_temperature=Temperature.from_fahrenheit(payload.data["ctEEVCoilSubCoolValue"] / 10),
                suction_temperature=Temperature.from_fahrenheit(payload.data["ctEEVCoilSuctionTemperature"] / 10),
            )

        return equipment

    async def login(self) -> bool:
        """Log in to the Daikin API with the given credentials to auth tokens"""
        log.info("Logging in to Daikin API")
        try:
            async with aiohttp.ClientSession(
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                }
            ) as session:
                async with session.post(
                    url=DAIKIN_API_URL_LOGIN,
                    json={"email": self.creds.email, "password": self.creds.password},
                ) as response:
                    if response.status != 200:
                        log.error(f"Request to login failed: {response}")
                        return False

                    payload = await response.json()
                    refresh_token = payload["refreshToken"]
                    access_token = payload["accessToken"]

                    if refresh_token is None:
                        log.error("No refresh token found in login response")
                        return False
                    if access_token is None:
                        log.error("No access token found in login response")
                        return False

                    # save token
                    self.__auth.refresh_token = refresh_token
                    self.__auth.access_token = access_token
                    self.__auth.authenticated = True

                    return True

        except ClientError as e:
            log.error(f"Request to login failed: {e}")
            return False

    async def __refresh_token(self) -> bool:
        log.debug("Refreshing access token")
        if self.__auth.authenticated is not True:
            await self.login()

        async with aiohttp.ClientSession(
            headers={"Accept": "application/json", "Content-Type": "application/json"}
        ) as session:
            async with session.post(
                url=DAIKIN_API_URL_REFRESH_TOKEN,
                json={
                    "email": self.creds.email,
                    "refreshToken": self.__auth.refresh_token,
                },
            ) as response:
                if response.status != 200:
                    log.error(f"Request to refresh access token: {response}")
                    self.__auth.authenticated = False
                    return False

                payload = await response.json()
                access_token = payload["accessToken"]

                if access_token is None:
                    log.error("No access token found in refresh response")
                    self.__auth.authenticated = False
                    return False

                # save token
                log.info("Refreshed access token")
                self.__auth.access_token = access_token
                self.__auth.authenticated = True

                return True

    async def __req(
        self,
        url: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> Any:
        if self.__auth.authenticated is not True:
            await self.login()

        log.debug(f"Sending request to Daikin API: {method} {url}")
        async with aiohttp.ClientSession(
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.__auth.access_token}",
            }
        ) as session:
            async with session.request(method, url, json=body) as response:
                log.debug(f"Got response: {response.status}")

                if response.status == 200:
                    payload = await response.json()
                    return payload

                if response.status == 401:
                    if retry:
                        await self.__refresh_token()
                        return await self.__req(url, method, body, retry=False)

                raise DaikinServiceException(
                    f"Failed to send request to Daikin API: method={method} url={url} body={json.dumps(body)}, response_code={response.status} response_body={await response.text()}",
                    status=response.status,
                )
