# Slice 01: Vertical Vane Fixed/Oscillate Control

## Goal and outcome

A user can control a supported head's vertical vane from the thermostat's standard Home Assistant Swing mode
control, with behavior matching the Daikin application.

## Scope

- Parse the mode-specific `idu*AirDirectionUpDown` fields.
- Treat `0` and `23` as Fixed on read, `15` as Oscillate, and write `0` or `15` as the app does.
- Advertise Fixed and Oscillate through the climate Swing mode feature when supported in the logical mode.
- Write one field for native Heat, Cool, or Auto and both Heat and Cool for emulated Heat/Cool.
- Preserve control while emulated Heat/Cool is physically Off and hide it in native Off.
- Add positive and negative connector, mapping, and climate tests plus user documentation.

## Non-scope

- Horizontal vane control because the captured heads do not report `idu*AirDirectionLeftRight` fields.
- Numbered fixed vane positions, which the app does not expose for this device-data interface.
- Exposing Dry or fan-only HVAC modes.

## Dependencies and behavior

Support is established only by raw vertical-direction field presence for the relevant operating mode. The displayed
value follows the active physical direction under emulated Heat/Cool; while idle it is shown only when stored Heat
and Cool values agree. Unknown values are logged and represented as unavailable without preventing thermostat
discovery.

## Data and state transitions

Selecting Fixed or Oscillate sends the app-confirmed numeric value to the current mode field. Emulated Heat/Cool
sends one partial update containing both Heat and Cool fields. Connector and entity caches update optimistically
without changing other modes.

## Authorization

No new authority is introduced. Writes use the existing authenticated Daikin device-data endpoint.

## Validation and recovery

- Verify mapping for Fixed `0`, legacy/current Fixed `23`, Oscillate `15`, missing fields, and unknown values.
- Verify native single-field and emulated dual-field writes.
- Verify native Off and unsupported modes reject service calls without requests.
- Run focused tests, the full pytest suite, Pyright, Ruff, Black, JSON parsing, and Git whitespace checks.

## Implementation surfaces

- Connector thermostat model, mapping, request method, and cache update.
- Climate Swing mode feature, presentation, and service handling.
- Tests, translations/icons, and README.

## Acceptance criteria

- The standard thermostat card can display and change vertical vane swing on supported heads.
- Existing fan-speed, temperature, and emulation behavior remains green.
- Unsupported heads do not gain a nonfunctional control.

## Commit boundary

Commit the plan, complete vertical-vane behavior, tests, and documentation as one semantic payload, followed only
by the exact-SHA provenance closeout.

## Completion

- Status: complete.
- Payload commit: `f53a4fd2d19482e2a2dd7b6192daa3a3c8b71c33`.
- Validation: 71 tests passed; Pyright, Ruff, Black, JSON parsing, and Git whitespace checks passed.
