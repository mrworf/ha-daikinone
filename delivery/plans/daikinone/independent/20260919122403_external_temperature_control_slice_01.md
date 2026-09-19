# Slice 01: Optional Adaptive Heat and Cool Bias

## Goal and outcome

A user can assign an optional HA temperature sensor to any Daikin head, set a per-head maximum bias defaulting to 5 C,
and have ordinary Heat or Cool operation continuously adapt a physical Daikin setpoint while HA displays the logical
target and external temperature.

## Scope

- Per-head options UI, validation, translations, and durable options schema.
- A controller with persisted logical targets and separate heat/cool biases.
- Continuous one-minute/sensor/refresh evaluation, +/-0.3 C deadband, 15-minute sustained-error window, and 0.5 C
  adjustments.
- Equipment and configured-bias clamping, anti-windup, sensor validation, and 0.5 C connector payloads.
- Climate presentation and diagnostic attributes for ordinary Heat and Cool.
- Focused positive and negative tests.

## Non-scope

- External-temperature demand in emulated Heat/Cool.
- Daikin-side manual edit adoption, schedule disabling, stale-sensor fallback, and disable cleanup; these complete in
  slice 02.
- Native Auto, emergency heat, Dry, Fan, or Off adaptation.

## Dependencies and ordering

This is the first slice and depends only on the existing climate entity and Daikin connector. Slice 02 consumes the
controller interface and persistence introduced here.

## Application and state flow

1. Options select a thermostat, temperature-sensor entity, and maximum absolute bias.
2. Integration setup loads controller state and subscribes to configured sensor changes and a one-minute timer.
3. Climate target writes become logical-target updates; the controller sends logical target plus applicable bias.
4. Valid external readings accumulate continuous directional error. A sign change or return to deadband resets the
   sustained-error timer. Each completed interval adjusts 0.5 C and starts another interval.
5. Controller state is saved with debounced HA storage writes and restored before entities publish state.

## Authorization

No new authorization boundary is introduced. Configuration requires normal Home Assistant integration-options access,
and cloud writes use the existing authenticated Daikin connection.

## Validation and recovery

- Reject a non-temperature entity, missing head, nonnumeric reading, or maximum bias outside 0.5-10 C.
- Do not adapt while the physical/logical mode is unsupported or the external reading is invalid.
- Clamp physical setpoints to equipment limits and stop increasing a bias that cannot change the physical result.
- Leave unconfigured heads on the current code path.

## Implementation surfaces

- Integration constants/options flow and translations.
- New external-temperature controller integrated with setup and climate entities.
- Daikin setpoint serialization precision.
- Controller, config-flow, climate, and connector tests.

## Tests and validation

- Positive: configure a sensor; set logical Heat and Cool targets; cross a sustained error window; observe 0.5 C bias
  changes and biased connector calls while logical targets remain stable.
- Negative: invalid sensor/value/limit, unsupported mode, deadband, incomplete duration, configured/equipment limits,
  duplicate evaluation, and unconfigured heads do not create unintended writes.
- Commands: focused new controller/config/climate tests; related climate and emulation tests; pyright, ruff, and Black
  checks for changed code.

## Acceptance criteria

- Optional configuration works per head with a 5 C default.
- Heat and Cool continuously adapt and persist independent biases.
- HA exposes logical values and documented diagnostics.
- Existing unconfigured behavior and tests remain intact.

## Commit boundary

Commit this slice's plan, configuration, controller, Heat/Cool integration, connector precision change, diagnostics,
and focused tests together as one coherent behavior commit.

## Delivery result

- Status: complete.
- Commit: `d60245a`.
- Focused validation: 25 tests passed; Pyright reported 0 errors; Ruff passed.
