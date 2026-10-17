"""Daikin residential error-code descriptions."""

import re
from typing import Any

# Daikin's official Simple Self-Diagnosis chart marks these codes as applying
# to Split/Multi-Split (RA) equipment:
# https://www.daikin.com/products/ac/services/error_codes
RESIDENTIAL_ERROR_DESCRIPTIONS: dict[str, str] = {
    "A1": "Indoor unit circuit board malfunction",
    "A3": "Drain level control system problem",
    "A4": "Freeze protection problem",
    "A5": "High-pressure heating control or cooling freeze protection",
    "A6": "Indoor fan motor malfunction",
    "AH": "Air-cleaner dust collector malfunction",
    "C4": "Heat exchanger liquid-pipe temperature sensor malfunction",
    "C5": "Heat exchanger gas-pipe temperature sensor malfunction",
    "C7": "Front panel motor malfunction",
    "C9": "Room air temperature sensor malfunction",
    "CA": "Discharge air temperature sensor malfunction",
    "CC": "Humidity sensor malfunction",
    "CJ": "Remote controller room temperature sensor malfunction",
    "E1": "Outdoor unit circuit board malfunction",
    "E3": "High-pressure switch activated",
    "E5": "Inverter compressor motor malfunction or overheat",
    "E6": "Standard compressor motor overcurrent or lock",
    "E7": "Outdoor unit fan motor malfunction",
    "E8": "Inverter compressor overcurrent",
    "EA": "Four-way valve or heating/cooling switching malfunction",
    "F3": "Discharge pipe temperature malfunction",
    "F6": "High pressure or too much refrigerant",
    "H0": "Compressor sensor system malfunction",
    "H1": "Room temperature sensor or humidifier damper malfunction",
    "H3": "High-pressure switch malfunction",
    "H5": "Compressor motor overload temperature sensor malfunction",
    "H6": "Position detection sensor malfunction",
    "H8": "Compressor current sensor malfunction",
    "H9": "Outdoor air temperature sensor malfunction",
    "HJ": "Thermal storage tank water-level malfunction",
    "J2": "Compressor current sensor malfunction",
    "J3": "Discharge pipe temperature sensor malfunction",
    "J6": "Heat exchanger temperature sensor malfunction",
    "J8": "Refrigerant circuit temperature sensor malfunction",
    "J9": "Refrigerant circuit temperature sensor malfunction",
    "L3": "Electrical component box temperature too high",
    "L4": "Inverter cooling-fin temperature too high",
    "L5": "Inverter instantaneous overcurrent",
    "L8": "Inverter compressor overcurrent malfunction",
    "LC": "Communication malfunction between control and inverter circuit boards",
    "M1": "Central remote controller circuit board malfunction",
    "M8": "Communication malfunction between optional central controllers",
    "MA": "Incorrect combination of optional central controllers",
    "MC": "Duplicate address or incorrect setting",
    "P3": "Switch-box temperature sensor malfunction",
    "P4": "Inverter cooling-fin temperature sensor malfunction",
    "P9": "Humidifier fan motor malfunction",
    "PA": "Humidifier heater wire is broken",
    "PH": "Refrigerant cylinder condition during automatic charging",
    "U0": "Not enough refrigerant",
    "U1": "Reversed or missing power-supply phase",
    "U2": "Power-supply malfunction or momentary power failure",
    "U3": "Check operation not completed or communication error",
    "U4": "Communication malfunction between indoor and outdoor unit",
    "U5": "Communication malfunction between indoor unit and remote controller",
    "U7": "Communication malfunction between outdoor units",
    "UA": "Indoor/outdoor power-supply problem",
    "UH": "System malfunction",
    "UJ": "Communication malfunction with an accessory device",
}


def normalize_error_code(value: Any) -> str | None:
    """Return an active API error code, or None for Daikin's no-error value."""
    if value is None:
        return None

    code = str(value).strip()
    compact = re.sub(r"[^A-Z0-9]", "", code.upper())
    if not compact or set(compact) == {"0"}:
        return None
    return code


def error_description(code: str | None) -> str | None:
    """Describe an active Daikin code using its documented main code."""
    if code is None:
        return None

    match = re.match(r"^([A-Z0-9]{2})", code.strip().upper())
    if match is None:
        return "Unknown Daikin error code"
    return RESIDENTIAL_ERROR_DESCRIPTIONS.get(match.group(1), "Unknown Daikin error code")
