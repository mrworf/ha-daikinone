# Slice 01: Always Present Configured External Environmental Readings

## Goal and outcome

Correct the climate entity so a configured head always displays its fresh external sensor reading, including while
the head is Off. Preserve internal-temperature fallback when that reading cannot be used.
Allow an optional external humidity entity and apply the same mode-independent presentation with its own fallback.

## Scope

- Remove HVAC-mode gating from current-temperature presentation.
- Add an optional humidity sensor to each head's external-temperature options without invalidating existing entries.
- Validate humidity device class and expose fresh, valid humidity through the climate entity and diagnostics.
- Add positive regression coverage for a configured, Off head.
- Add negative/fallback coverage for unavailable external readings and for an unconfigured head.

## Non-scope

- Adaptive learning eligibility, setpoint biasing, emulated demand, schedule ownership, and stale-timeout behavior.
- Automatic sibling-entity discovery; users explicitly select the humidity entity because a device can expose more
  than one humidity measurement.

## Dependencies and behavior

The existing external controller remains the authority for whether a sensor is configured and whether its current
reading is valid and fresh. The climate entity selects that reading whenever both conditions hold; otherwise it uses
the existing internal temperature. Humidity follows the same independent selection rule. These presentation choices
do not mutate learned bias state.

## Authorization

Not applicable. The slice reads existing local state and performs no new external operation.

## Validation and recovery

- A fresh configured value wins even in Off mode.
- `None` from the external controller falls back to the internal value.
- No configuration also falls back to the internal value.
- Existing options without a humidity entity deserialize normally.
- Humidity values outside 0-100%, with invalid device class, or stale/unavailable state are rejected or fall back.
- Run focused climate tests, then the full pytest suite, Pyright, Ruff, and Black checks.

## Implementation surfaces

- `custom_components/daikinone/climate.py`
- `custom_components/daikinone/config_flow.py`
- `custom_components/daikinone/external_temperature.py`
- `custom_components/daikinone/translations/en.json`
- `tests/test_climate.py`
- `tests/test_external_temperature.py`

## Acceptance criteria

- Current-temperature presentation is independent of HVAC mode once an external sensor is configured.
- Current humidity is likewise mode-independent when an optional external humidity entity is configured.
- Existing fallback behavior and all repository validation remain green.

## Commit boundary

Commit this plan, the climate presentation correction, and its regression tests as one coherent behavior change.

## Delivery result

- Status: complete.
- Validation: 51 tests passed; Pyright reported 0 errors; Ruff passed; Black left all 13 component files unchanged.
- Payload commit: recorded in the governing plan's transaction closeout.
