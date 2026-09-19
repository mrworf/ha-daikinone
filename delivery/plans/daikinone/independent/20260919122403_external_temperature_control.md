# Optional Adaptive External Temperature Control

## Summary

Add optional, per-head external temperature control that preserves Daikin inverter modulation through a continuously
adapting setpoint bias. Support Heat, Cool, and emulated Heat/Cool while leaving native Auto, Dry, Fan, Off, emergency
heat, and unconfigured heads unchanged.

Home Assistant displays the external temperature and logical user targets. Daikin receives physical targets equal to
the logical target plus a bounded, continuously relearned bias. Home Assistant owns scheduling whenever this feature is
enabled.

## Behavior

- Configure one Home Assistant temperature sensor and an absolute maximum bias per head. The default is 5 C, with a
  supported range of 0.5 C through 10 C in 0.5 C increments.
- Persist separate heating and cooling biases, logical targets, and evaluation timestamps per head. Persisted biases
  are restart starting points and continue adapting whenever their direction is active.
- Evaluate on sensor changes, Daikin refreshes, and a one-minute timer. After 15 continuous minutes outside a fixed
  +/-0.3 C deadband, change the applicable bias by 0.5 C, reset the interval, and continue evaluating indefinitely.
- Clamp bias and physical equipment targets, prevent windup, and write only changed 0.5 C targets.
- Treat Daikin-side setpoint edits as new logical targets after excluding commands still within propagation time.
- If the sensor is invalid, unavailable, or unchanged for 30 minutes, freeze targets and learning, show the head
  temperature, and use it for emulated Heat/Cool demand until the sensor recovers and completes a fresh observation
  interval.
- Disabling the feature restores logical targets as unbiased physical targets and removes adaptive state.

## Observable Interface

Configured climate entities expose logical targets plus external-control diagnostics: internal and external
temperatures, sensor entity ID, controller status, heating and cooling biases, physical target(s), last evaluation and
adjustment timestamps, and limit status.

## Slices

1. `20260919122403_external_temperature_control_slice_01.md` - Optional controller, configuration, persistence, and
   adaptive Heat/Cool behavior. Delivered in `d60245a`.
2. `20260919122403_external_temperature_control_slice_02.md` - Emulated Heat/Cool integration, stale/manual/schedule
   recovery, documentation, and full validation. Delivered in the commit containing this final plan update.

## Acceptance

- Heads without an external sensor behave exactly as before.
- Configured Heat and Cool heads continuously adapt physical setpoints while HA retains logical targets.
- Emulated Heat/Cool uses the external temperature and direction-specific adaptive biases without weakening existing
  outdoor-unit coordination.
- Required focused tests, full pytest suite, pyright, ruff, and Black checks pass.
