# Slice 01: Accept Partial Daikin Outdoor Telemetry

## Goal and outcome

Home Assistant can load and retain a configured Daikin mini-split system when the API returns explicit null values
for outdoor-unit telemetry. Users continue to see the thermostat and configured heat-pump device, with each sensor
showing only currently valid data.

## Scope

- Treat thermostat outdoor temperature and indoor/outdoor humidity as optional readings.
- Read `iduRoomHum` first and retain `humIndoor` as a legacy humidity fallback.
- Map supported mini-split outdoor reports even when individual telemetry fields are missing, null, or invalid.
- Keep configured heat-pump devices and head assignments present when all or part of their telemetry is unavailable.
- Preserve valid cumulative energy and other valid fields from partial reports.
- Keep automatic grouping limited to complete, compatible reports.
- Add sanitized regression tests derived from the reported payload shape.

## Non-scope

- Guessing values for null fields, changing entity IDs, or adding new entities.
- Inferring a shared outdoor-unit grouping from incomplete telemetry.
- Changes to climate control, external-room-sensor control, or Heat/Cool emulation decisions.
- Persisting or documenting any account, network, adapter, or device identifiers from the supplied log.

## Dependencies and behavior

Thermostat mapping remains the setup entry point. Optional numeric conversion rejects nulls, booleans, strings, and
negative counters where applicable. Runtime heat-pump aggregation accepts partial reports; automatic discovery first
filters them through the existing complete-evidence requirements. A configured group is materialized even with no
usable live member fields, and every known member thermostat retains its group assignment.

## Data and state transitions

No stored schema or migration changes. Model fields that can be absent become optional. On refresh, valid readings
replace previous readings and null readings become unavailable. A partial energy-source report may update cumulative
energy while power, outdoor temperature, operating state, compressor, fan, and current remain unavailable.

## Authorization

Not applicable. The slice only parses the existing authenticated Daikin response and changes no permissions or
outbound commands.

## Validation and recovery

- Positive: a sanitized new-shape payload loads, maps `iduRoomHum`, retains its configured group, and exposes its
  cumulative energy.
- Negative: null outdoor values do not become zero and do not produce a false Idle operating state.
- Discovery: incomplete reports are not automatically grouped but remain available for manual assignment.
- Compatibility: complete legacy-shaped telemetry still discovers and aggregates as before; `humIndoor` remains a
  supported fallback.
- Run focused heat-pump and thermostat-mapper tests, the full pytest suite because shared payload mapping affects all
  platforms, Pyright, Ruff, Black check, JSON parsing, bytecode compilation, and Git whitespace checks.

## Implementation surfaces

- Thermostat and outdoor telemetry models/mapping in `custom_components/daikinone/daikinone.py`.
- Sanitized mapper and aggregation regressions in `tests/test_heat_pumps.py` and nearby mapper tests if needed.

## Acceptance criteria

- The supplied null-field failure path no longer raises.
- Configured devices remain stable and report partial availability accurately.
- Existing discovery, aggregation, and platform tests remain green.

## Commit boundary

Commit the plan, null-safe mapping, stable-device behavior, and regression tests as one semantic payload, followed
only by the exact-SHA provenance closeout required by the delivery transaction contract.

## Completion

- Status: complete.
- Payload commit: `b2fd541d5dd2ac5c346ada6b059cc38cf87f37a0`.
- Validation: 90 tests passed; Pyright reported 0 errors; Ruff, Black, bytecode compilation, JSON parsing, and Git
  whitespace checks passed.
