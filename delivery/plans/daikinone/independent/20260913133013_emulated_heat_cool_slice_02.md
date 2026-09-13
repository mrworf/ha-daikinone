# Slice 02: Group-aware emulated Heat/Cool controller

## Goal and observable outcome

Users can select Home Assistant Heat/Cool on supported heads, configure a low
and high target, and have the integration select physical Heat, Cool, or Off.
Heads sharing an outdoor unit are coordinated, manual controls take precedence,
and suspended emulation is visible and explained.

## Scope

- Add logical Heat/Cool state, restore behavior, low/high range presentation,
  and per-head demand/status calculation.
- Add centralized per-entry reconciliation with heat-pump group arbitration,
  hysteresis, dwell, one-Off-cycle reversals, command de-duplication, and
  isolated retryable failures.
- Add global tolerance, dwell, and external-Auto conversion options.
- Respect physical-remote Heat/Cool/Off changes; optionally convert external
  native Auto while preserving HA-selected native Auto.
- Add suspension notifications and the `emulation_status` state attribute.
- Document user-visible behavior and limitations.

No new entities, service names, device identifiers, or automatic changes to
existing users' selected modes are in scope.

## Dependencies and ordering

Depends on slice 01's truthful native-Auto single-setpoint behavior. Existing
heat-pump grouping is authoritative for shared-unit arbitration.

## Entry point and end-to-end behavior

Climate setup registers each capable head with one per-entry controller. Setting
Heat/Cool records the logical mode, uses the device's heat/cool setpoints, and
reconciles immediately. Later cloud refreshes reconcile the whole account once,
calculating demand and issuing only required physical commands. Climate entities
continue reporting logical Heat/Cool while exposing actual action and controller
status.

## State transitions and arbitration

- Start heat at or below `low - tolerance` and stop at `low`; start cool at or
  above `high + tolerance` and stop at `high`.
- Without manual ownership, the direction with the largest raw boundary
  deviation wins; deterministic ties retain the active direction, then prefer
  heat when no direction exists.
- Direction cannot reverse before the configured dwell expires. All emulated
  heads are Off for at least one reconciliation between opposite directions.
- Explicit manual Heat/Cool owns the group; matching emulated demand may run and
  opposite demand waits Off. Opposing manual directions or native Auto suspend
  all emulated control on that pump.
- Offline/missing-temperature heads wait without commands. Unassigned known
  mini-split heads do not advertise Heat/Cool; other capable single-controller
  systems arbitrate independently.
- Successful controller commands record expected physical state. A mismatch
  outside a short propagation window is treated as a remote override and exits
  emulation. Remote Auto is converted only when the opt-in option is enabled and
  native Auto was not explicitly selected through HA.
- Logical mode restores from HA state. On restart, current physical direction
  initializes dwell conservatively.

## Options, validation, and recovery

- Global hysteresis defaults to 0.5 C and accepts 0.0-5.0 C in 0.1 C steps.
- Global dwell defaults to 15 minutes and accepts 0-120 whole minutes.
- External-Auto conversion defaults Off.
- Reject incomplete or inverted Heat/Cool ranges with a Home Assistant service
  validation error and do not send partial commands.
- Per-head command failures are logged, preserve desired state, and retry later
  without failing unrelated entity updates.
- Existing account authorization is reused; no permission changes apply.

## Notifications and status

The climate entity exposes stable `emulation_status` values for idle, active,
waiting, dwell, suspension, and missing-data states. One persistent notification
per heat pump names manual owners and suspended heads, updates without
duplication, and is dismissed automatically when suspension ends.

## Implementation surfaces

Per-entry runtime/controller state, climate lifecycle and service methods,
connector cache/command support, options flow/translations, tests, and README.

## Tests and validation

- Positive and negative range/hysteresis demand cases.
- Largest-deviation, tie, grouping, dwell, Off-cycle, and independent-group
  cases.
- Manual ownership, manual conflicts, native Auto suspension, statuses, and
  notification create/update/dismiss cases.
- Remote exit, external-Auto conversion, pending-command delay, restore, restart,
  unavailable data, and unassigned-mini-split cases.
- Regression coverage for manual modes, presets, fan, grouping, energy entities,
  and unchanged unique IDs.
- Run focused pytest, full pytest, Ruff, Pyright, Black check, compileall, and
  translation JSON validation.

## Acceptance and commit boundary

Commit controller behavior, options, climate integration, documentation, tests,
and this completed slice record as one coherent slice after all validation
passes.
