# Slice 02: Emulated Heat/Cool and Operational Recovery

## Goal and outcome

External temperature control also governs emulated Heat/Cool safely, remains authoritative over schedules, adopts
manual Daikin setpoint edits, and recovers predictably from stale sensors or feature removal.

## Scope

- Route emulated Heat/Cool demand through a valid external sensor and apply direction-specific physical biases.
- Preserve group direction selection, command propagation, dwell, and suspension behavior.
- Disable Daikin scheduling while external control is active.
- Detect Daikin-side physical setpoint edits and adopt them as logical targets after subtracting bias.
- Treat unavailable, invalid, or unchanged-for-30-minute sensors as stale; freeze learning/targets, show and use the
  head temperature as fallback, then require a fresh 15-minute interval after recovery.
- Restore unbiased logical targets and delete adaptive state when configuration is removed.
- Complete README documentation and regression/full-suite validation.

## Non-scope

- Native Auto, emergency heat, Dry, Fan, or Off adaptation.
- Compressor-capacity commands or binary replacement of Daikin's internal inverter controller.
- User-configurable deadband, interval, step, or stale timeout.

## Dependencies and ordering

Requires slice 01's controller, persisted state, climate logical/physical target separation, and per-head options.

## Application and state flow

1. Emulated demand reads the controller's effective temperature: external when valid, internal during stale fallback.
2. Heat demand uses the logical low target and heating bias; cool demand uses the logical high target and cooling bias.
3. Only the currently demanded direction learns. Bias holds in the comfort range or while another outdoor-unit
   direction owns the group.
4. Connector refresh compares reported physical setpoints with expected commands. Once propagation time expires, a
   mismatch becomes a new logical target calculated as physical minus bias.
5. Sensor failure freezes learning and commands. Recovery clears accumulated error time before adaptation resumes.
6. Removing configuration sends stored logical targets without bias, unsubscribes listeners, and removes saved state.

## Authorization

No new authorization boundary is introduced. Schedule and setpoint writes use the existing Daikin account authority.

## Validation and recovery

- Never classify an integration command within propagation time as a manual edit.
- Never learn from an invalid or stale sensor, an unsupported mode, or a direction suspended by group/manual control.
- If disabling a schedule or restoring targets fails, retain state and retry during later reconciliation rather than
  discarding recovery information.
- Recovery from a sensor outage cannot immediately adjust bias.

## Implementation surfaces

- Existing emulation controller and integration lifecycle.
- External controller reconciliation, schedule/manual-change logic, and climate diagnostics.
- README and controller/emulation/integration tests.

## Tests and validation

- Positive: external readings start/stop emulated heat and cool; separate biases apply; manual edits become logical
  targets; schedules disable; sensor recovery resumes after a fresh interval; removal restores targets.
- Negative: pending commands are not manual edits; stale sensors do not learn or write; suspended/opposite directions
  do not learn; cleanup failures retain retry state; native Auto and emergency heat remain unchanged.
- Commands: focused controller and emulation tests, complete pytest suite, `uv run pyright`, `uv run ruff check .`, and
  `uv run black --check custom_components`.

## Acceptance criteria

- Emulated Heat/Cool responds to external temperature without regressing group safety.
- Stale sensors, manual control, schedules, restart, recovery, and disable cleanup match the governing plan.
- Documentation describes logical versus physical targets and continuous relearning.
- All required validation passes or an environmental blocker is recorded precisely.

## Commit boundary

Commit Heat/Cool integration, recovery/manual/schedule behavior, documentation, and all related tests together as the
second coherent behavior commit.

## Delivery result

- Status: complete.
- Slice 01 dependency: `d60245a`.
- Slice 02 commit: the commit containing this delivery result.
- Validation: 47 tests passed; Pyright reported 0 errors; Ruff passed; Black left all 13 component files unchanged.
