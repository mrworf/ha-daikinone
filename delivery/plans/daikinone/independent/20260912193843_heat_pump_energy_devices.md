# Heat-pump energy devices delivery plan

Parent commit: `f6b43ddfc2c37a759ca80f7d826f9fe1ca0e8c0c`

## Goal

Add inferred and user-correctable outdoor heat-pump devices to the existing
Daikin One integration. Each heat pump exposes instantaneous power and cumulative
energy while all existing head-unit device identifiers, entity unique IDs, and
controls remain unchanged.

## Compatibility contract

- The new behavior is additive and limited to mini-split payloads containing the
  `odu*` telemetry fields.
- Existing thermostat/head entities retain their unique IDs and device
  identifiers. Grouped heads gain only a `via_device` relationship.
- Existing `ctOutdoor*` equipment parsing and sensors are not replaced or
  duplicated.
- `data_from_daikin.json` is private diagnostic input and must remain untracked.

## Slice index

1. [Automatic heat-pump devices and energy sensors](20260912193843_heat_pump_energy_devices_slice_01.md)
2. [Grouping correction, ambiguity recovery, and documentation](20260912193843_heat_pump_energy_devices_slice_02.md)

## Completion criteria

- The supplied diagnostic topology resolves to two three-head heat pumps.
- Heat-pump power and energy sensors have Home Assistant-compatible metadata.
- Grouping persists across refreshes and restarts and can be corrected by the
  user without changing existing head entity IDs.
- Focused tests, Ruff, and Pyright pass, subject to recorded environment limits.
