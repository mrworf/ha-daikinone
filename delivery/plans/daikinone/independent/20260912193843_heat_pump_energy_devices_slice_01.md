# Slice 01: Automatic heat-pump devices and energy sensors

## Goal and observable outcome

On first setup, supported mini-split heads are conservatively clustered into
outdoor heat pumps. Home Assistant shows a device for each confident heat pump,
with Power and Energy consumption sensors, while existing head entities remain
unchanged and appear through their heat pump.

## Scope

- Parse mini-split ODU power, energy, and fingerprint fields.
- Infer groups per location and connected-IDU count, validating compatible ODU
  telemetry before merging heads.
- Persist stable group IDs, names, members, and an energy-source head.
- Expose cached heat pumps and add their two sensor entities.
- Preserve legacy `ctOutdoor*` behavior and all existing entity IDs.

Options UI, manual reassignment, and Repairs issues are slice 02.

## Dependencies and ordering

This is the first implementation slice and depends only on the existing cloud
refresh and sensor platform.

## Entry point and behavior

`DaikinOne.update()` maps all thermostat payloads, loads persisted groups supplied
by the integration data wrapper, infers groups when no persisted state exists,
and builds cached heat-pump models. Sensor setup creates Power and Energy
consumption entities for those models. A grouped thermostat reports the heat-pump
device identifier as `via_device`.

## State transitions and validation

- First confident discovery creates versioned group records in config-entry
  options; later refreshes treat those records as authoritative.
- Group candidates must be online mini-split payloads with valid ODU measurements.
- Pair compatibility uses the governing plan's fixed tolerances: integrated
  consumption within `max(25 kWh, 5%)`, equal mode, outdoor temperature within
  2 C, plus at least two matching operating signals (compressor frequency 5 Hz,
  fan speed 100 RPM, discharge temperature 5 C, target temperature 2 C).
- Power is the median valid online member reading in W.
- Energy uses the persisted source head (highest initial counter) in kWh and is
  unavailable if that source is unavailable.
- No authorization behavior is added; the integration uses its existing account
  authentication and read-only polling path.

## Implementation surfaces

Domain models and refresh mapping, integration setup/state persistence, entity
device relationships, sensor setup, and focused tests/fixtures.

## Tests and validation

- Positive: the sanitized six-head sample forms the two expected groups and
  emits correctly described power and energy sensors.
- Positive: persisted groups remain stable when live telemetry converges or
  changes.
- Negative: missing/invalid ODU data does not create a group or break heads.
- Negative: legacy `ctOutdoor*` equipment does not create a duplicate heat pump.
- Verify existing head/entity IDs are unchanged.
- Run focused pytest tests, `ruff check`, and `pyright`.

## Acceptance and commit boundary

Commit the domain behavior, persistence hook, entities, tests, and this slice
plan together once the focused and static validations pass.
