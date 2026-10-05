# Slice 01: Symmetric Emulated Heat/Cool Hysteresis

## Goal and outcome

An emulated Heat/Cool head runs past the edge of its selected comfort range by the configured tolerance before
turning off. This creates a useful on/off temperature span without forcing wide ranges all the way to their midpoint.

## Scope

- Keep the existing outside-range heating and cooling start thresholds.
- Apply the same tolerance inside the range to calculate active heating and cooling stop thresholds.
- Cap both stop thresholds at the range midpoint so they cannot cross.
- Use the existing global temperature-tolerance option and its current default.
- Update focused tests and the README.

## Non-scope

- New settings, option migrations, or changes to the tolerance's allowed range or default.
- Changes to shared outdoor-unit arbitration, direction dwell, manual overrides, native Auto, adaptive external-sensor
  bias, or physical setpoint calculation.
- Changes to the earlier external-temperature display behavior.

## Dependencies and behavior

The emulation controller already resolves each head's effective temperature and logical low/high targets. For an
idle head, demand begins at `low - tolerance` or `high + tolerance`, as it does today. For an actively heating head,
demand ends at `min(low + tolerance, midpoint)`. For an actively cooling head, demand ends at
`max(high - tolerance, midpoint)`. Inclusive comparisons preserve the existing threshold convention.

## Data and state transitions

No durable schema changes. Only the transient demand transition changes: active demand persists after entering the
range until its inner stop threshold is reached. At zero tolerance, the stop thresholds remain the low and high
targets. Existing status and physical-mode transitions remain unchanged.

## Authorization

Not applicable. This changes local control decisions and uses the integration's existing authenticated mode command.

## Validation and recovery

- Positive: heating and cooling continue through their range boundary and stop at the inner threshold.
- Negative/boundary: just short of an inner threshold retains demand; reaching it clears demand.
- Safety: a range narrower than twice the tolerance caps both stop points at the midpoint.
- Compatibility: zero tolerance stops at the original boundary.
- Integration: an external effective temperature follows the same symmetric thresholds.
- Run focused emulation tests, the complete pytest suite, Pyright, Ruff, Black check, JSON parsing, and Git whitespace
  checks.

## Implementation surfaces

- Emulated demand calculation in `custom_components/daikinone/emulation.py`.
- Emulation regression tests in `tests/test_emulation.py`.
- User-facing Heat/Cool and tolerance explanation in `README.md`.

## Acceptance criteria

- The new thresholds match the governing plan for heating, cooling, narrow ranges, and zero tolerance.
- All unrelated emulation behavior is unchanged and all required validation passes.

## Commit boundary

Commit this plan, behavior, tests, and documentation as one semantic payload, followed only by the exact-SHA
provenance closeout required by the delivery transaction contract.

## Completion

- Status: complete.
- Payload commit: pending.
- Validation: 87 tests passed; Pyright reported 0 errors; Ruff, Black, bytecode compilation, JSON parsing, and Git
  whitespace checks passed.
