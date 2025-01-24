import copy
import json
import logging
from datetime import timedelta
from enum import Enum, auto
from urllib.parse import urljoin
from typing import Any

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
    outdoor_temperature: Temperature
    outdoor_humidity: int
    air_quality_outdoor: DaikinOneAirQualitySensorOutdoor | None
    air_quality_indoor: DaikinOneAirQualitySensorIndoor | None
    equipment: dict[str, DaikinEquipment]


class DaikinDeviceDataResponse(BaseModel):
    id: str
    locationId: str
    name: str
    model: str
    firmware: str
    online: bool
    data: dict[str, Any]


class DaikinOne:
    """Manages connection to Daikin API and fetching device data"""

    @dataclass
    class _AuthState:
        authenticated: bool = False
        refresh_token: str | None = None
        access_token: str | None = None

    __auth = _AuthState()

    __thermostats: dict[str, DaikinThermostat] = dict()

    def __init__(self, creds: DaikinUserCredentials):
        self.creds = creds

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

    async def set_thermostat_mode(self, thermostat_id: str, mode: DaikinThermostatMode) -> None:
        """Set thermostat mode"""
        await self.__req(
            url=f"{DAIKIN_API_URL_DEVICE_DATA}/{thermostat_id}",
            method="PUT",
            body={"mode": mode.value},
        )

    async def set_thermostat_home_set_points(
        self,
        thermostat_id: str,
        heat: Temperature | None = None,
        cool: Temperature | None = None,
        override_schedule: bool = False,
    ) -> None:
        """Set thermostat home set points"""
        if not heat and not cool:
            raise ValueError("At least one of heat or cool set points must be set")

        payload: dict[str, Any] = {}
        if heat:
            payload["hspHome"] = heat.celsius
        if cool:
            payload["cspHome"] = cool.celsius
        if override_schedule:
            payload["schedOverride"] = 1

        await self.__req(
            url=f"{DAIKIN_API_URL_DEVICE_DATA}/{thermostat_id}",
            method="PUT",
            body=payload,
        )

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

        log.info(f"Cached {len(self.__thermostats)} thermostats")

    def __map_thermostat(self, payload: DaikinDeviceDataResponse) -> DaikinThermostat:
        try:
            capabilities = set(DaikinThermostatCapability)
            if payload.data.get("ctSystemCapHeat"):
                capabilities.add(DaikinThermostatCapability.HEAT)
            if payload.data.get("ctSystemCapCool"):
                capabilities.add(DaikinThermostatCapability.COOL)
            if payload.data.get("ctSystemCapEmergencyHeat"):
                capabilities.add(DaikinThermostatCapability.EMERGENCY_HEAT)

            thermostat = DaikinThermostat(
                id=payload.id,
                location_id=payload.locationId,
                name=payload.name,
                model=payload.model,
                firmware_version=payload.firmware,
                online=payload.online,
                capabilities=capabilities,
                mode=DaikinThermostatMode(payload.data.get("mode", DaikinThermostatMode.OFF)),
                status=DaikinThermostatStatus(payload.data.get("equipmentStatus", DaikinThermostatStatus.IDLE)),
                fan_mode=DaikinThermostatFanMode(payload.data["fanCirculate"]),
                fan_speed=DaikinThermostatFanSpeed(payload.data["fanCirculateSpeed"]),
                schedule=DaikinThermostatSchedule(enabled=payload.data["schedEnabled"]),
                indoor_temperature=Temperature.from_celsius(payload.data["tempIndoor"]),
                indoor_humidity=payload.data["humIndoor"],
                set_point_heat=Temperature.from_celsius(payload.data["hspActive"]),
                set_point_heat_min=Temperature.from_celsius(payload.data["EquipProtocolMinHeatSetpoint"]),
                set_point_heat_max=Temperature.from_celsius(payload.data["EquipProtocolMaxHeatSetpoint"]),
                set_point_cool=Temperature.from_celsius(payload.data["cspActive"]),
                set_point_cool_min=Temperature.from_celsius(payload.data["EquipProtocolMinCoolSetpoint"]),
                set_point_cool_max=Temperature.from_celsius(payload.data["EquipProtocolMaxCoolSetpoint"]),
                outdoor_temperature=Temperature.from_celsius(payload.data["tempOutdoor"]),
                outdoor_humidity=payload.data["humOutdoor"],
                air_quality_outdoor=self.__map_air_quality_outdoor(payload),
                air_quality_indoor=self.__map_air_quality_indoor(payload),
                equipment=self.__map_equipment(payload),
            )
        except Exception as e:
            # Improve logging when Daikin changes payload
            log.exception('Failed to setup thermostat')
            log.error(f'Contents of payload: {payload}')
            raise e


        return thermostat

    def __map_air_quality_outdoor(self, payload: DaikinDeviceDataResponse) -> DaikinOneAirQualitySensorOutdoor | None:
        if not payload.data["aqOutdoorAvailable"]:
            return None

        return DaikinOneAirQualitySensorOutdoor(
            aqi=payload.data["aqOutdoorValue"],
            aqi_summary_level=payload.data["aqOutdoorLevel"],
            particles_microgram_m3=payload.data["aqOutdoorParticles"],
            ozone_microgram_m3=payload.data["aqOutdoorOzone"],
        )

    def __map_air_quality_indoor(self, payload: DaikinDeviceDataResponse) -> DaikinOneAirQualitySensorIndoor | None:
        if not payload.data["aqIndoorAvailable"]:
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
        if 'ctAHUnitType' in payload.data and payload.data["ctAHUnitType"] < 255:
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
        if 'ctIFCUnitType' in payload.data and payload.data["ctIFCUnitType"] < 255:
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
        if 'ctOutdoorUnitType' in payload.data and payload.data["ctOutdoorUnitType"] < 255:
            model = payload.data["ctOutdoorModelNoCharacter1_15"].strip()
            serial = payload.data["ctOutdoorSerialNoCharacter1_15"].strip()
            eid = f"{model}-{serial}"

            # assume it can cool, and if it can also heat it should be a heat pump
            name = "Condensing Unit"
            if payload.data.get("ctOutdoorHeatMaxRPS",0) != 0 and payload.data.get("ctOutdoorHeatMaxRPS",0) != 65535:
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
        if 'ctCoilUnitType' in payload.data and payload.data["ctCoilUnitType"] < 255:
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
