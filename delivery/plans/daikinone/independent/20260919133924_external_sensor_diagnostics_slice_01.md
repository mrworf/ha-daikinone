# Slice 01: External Sensor Diagnostic Snapshots

## Goal and outcome

Make external sensor behavior visible in Home Assistant's downloadable diagnostics so a user or maintainer can see
the configured entity IDs, currently usable external values, controller status, biases, and logical/physical targets.

## Scope

- Add a stable diagnostic snapshot API to the external-temperature controller.
- Include all configured snapshots in config-entry diagnostics.
- Include the matching snapshot in thermostat device diagnostics.
- Add focused positive and negative diagnostics tests.

## Non-scope

- Changing climate entity attributes, adaptive behavior, sensor selection, or persistence.
- Retrofitting redaction into the integration's existing raw Daikin diagnostics.

## Dependencies and behavior

Diagnostics consume the existing controller's validated readings and state. A stale, unavailable, invalid, or
out-of-range sensor is represented by `null`, exactly as it is at runtime. Snapshot generation is read-only and does
not trigger reconciliation or cloud requests. Existing raw diagnostics remain present.

## Authorization

No new authorization is introduced. Diagnostics are produced through Home Assistant's existing diagnostics action
and read only already-loaded integration state.

## Validation and recovery

- Configured heads include temperature value, optional humidity value, entity IDs, status, biases, and targets.
- Unconfigured device IDs return `null` for external control.
- A configured but unusable reading is represented as `null` rather than an exception or stale numeric value.
- Run focused diagnostics tests, the full pytest suite, Pyright, Ruff, and Black checks.

## Implementation surfaces

- `custom_components/daikinone/external_temperature.py`
- `custom_components/daikinone/diagnostics.py`
- `tests/test_diagnostics.py`

## Acceptance criteria

- Downloaded diagnostics expose the effective external temperature value requested by the user.
- Device and config-entry shapes are deterministic and existing `raw` content is unchanged.
- All required validation passes.

## Commit boundary

Commit this plan, diagnostic snapshot implementation, and tests as one coherent behavior change.

## Delivery result

- Status: complete.
- Validation: 54 tests passed; Pyright reported 0 errors; Ruff passed; Black left all 13 component files unchanged.
- Payload commit: recorded in the governing plan's transaction closeout.
