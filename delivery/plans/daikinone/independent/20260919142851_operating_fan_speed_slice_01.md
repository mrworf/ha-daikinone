# Slice 01: Real Fan Speed and Separate Circulation Controls

## Goal and outcome

Make Home Assistant's thermostat Fan mode match the Daikin app while retaining accurately named circulation controls
on unitary equipment that supports them.

## Scope

- Model all mode-specific operating fan-speed values and tolerate unknown codes.
- Read and write the correct mode-specific Daikin fields.
- Expose operating speed through the climate entity.
- In emulated Heat/Cool, synchronize Heat and Cool fan speeds from one HA selection.
- Replace the old generic Fan Speed select with capability-gated Circulation Mode and Circulation Speed selects.
- Remove stale legacy circulation-speed registry entries from heads that do not support circulation.
- Update documentation and tests.

## Non-scope

- Exposing Dry or fan-only HVAC modes.
- Fan direction/louver controls, schedule fan-speed fields, or automatic idle circulation.
- Inferring capabilities from model names when raw field presence is available.

## Dependencies and behavior

The connector stores recognized operating speeds per Daikin mode and optional circulation mode/speed independently.
The climate entity advertises the seven APK-defined values when operating fan-speed fields exist. Native Heat, Cool,
and Auto update their corresponding field. Emulated Heat/Cool updates both Heat and Cool. Native Off removes the
Fan-mode feature and reports no selection; emulated Heat/Cool retains it while physically Off. If its idle Heat and
Cool values differ, the selection is unknown until a direction is active or HA synchronizes them.

Circulation selects are created solely from `fanCirculate` and `fanCirculateSpeed` field presence. The current
`<head>-fan_speed` unique ID is retained for supported circulation speed and its name changes to Circulation Speed. A
new `<head>-circulation_mode` entity controls circulation policy. Unsupported legacy speed entries are removed during
select setup.

## Authorization

No new authority is introduced. Writes use the existing authenticated Daikin device-data endpoint.

## Validation and recovery

- Unknown operating speed codes are logged and omitted without breaking thermostat discovery.
- Attempts to set speed in unsupported native modes fail validation without sending a request.
- Optimistic cache updates match each submitted field and retain other mode-specific settings.
- Registry cleanup targets only the obsolete select unique ID for heads lacking circulation-speed support.
- Run focused connector, climate, emulation, and select tests, then full pytest, Pyright, Ruff, and Black.

## Implementation surfaces

- Connector thermostat model and request mapping.
- Climate fan-mode presentation and service handling.
- Select platform circulation entities and legacy cleanup.
- Tests and README.

## Acceptance criteria

- The thermostat Fan mode matches the app's labels and wire values.
- Emulated direction changes retain the HA-selected speed.
- Circulation is no longer presented as operating fan speed.
- Existing unrelated climate and external-temperature behavior remains green.

## Commit boundary

Commit the plan, complete fan-control behavior, compatibility cleanup, documentation, and tests as one coherent
payload, followed only by the required provenance closeout.

## Completion

- Status: complete.
- Payload commit: `305035ee434d8b88e0393ace9f5fe90ae7bfb543`.
- Validation: 61 tests passed; Pyright, Ruff, Black, JSON parsing, and Git whitespace checks passed.
