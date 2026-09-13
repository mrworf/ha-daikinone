# Slice 01: Native Auto single-setpoint support

## Goal and observable outcome

When a user selects Daikin-native Auto, the existing climate entity shows one
target temperature and accepts target changes through Home Assistant. Heat,
Cool, Off, presets, and fan behavior remain unchanged.

## Scope

- Map `iduAutoSetpoint` as the target while the physical device is in Auto.
- Accept a single Auto target and send it to the Daikin API.
- Remove the accidental duplicate mode PUT in the common mode-setting path.
- Add focused climate and connector tests.

Emulated Heat/Cool, restore state, options, group arbitration, remote overrides,
status attributes, and notifications belong to slice 02.

## Dependencies and ordering

This slice starts from the governing plan's parent commit and establishes the
correct native-Auto contract required to distinguish native from emulated mode.

## Entry point and end-to-end behavior

Selecting Auto continues to send the physical Auto mode. A subsequent
`climate.set_temperature` call sends `iduAutoSetpoint`; refreshed state exposes
that value through the entity's single target-temperature property.

## State, validation, and recovery

- Auto accepts `ATTR_TEMPERATURE`, not range-only input.
- The connector requires at least one heat, cool, or auto setpoint and includes
  only supplied values in its PUT payload.
- Cloud/API errors retain existing propagation and entity refresh behavior.
- Existing account authorization is reused; no permission changes apply.

## Implementation surfaces

Climate mode/temperature mapping, connector setpoint payload construction, and
focused tests.

## Tests and validation

- Positive: Auto exposes `set_point_auto` as a single target.
- Positive: setting an Auto target sends only `iduAutoSetpoint`.
- Negative: an empty setpoint request is rejected.
- Regression: one mode request produces exactly one PUT.
- Run focused pytest, full pytest, Ruff, Pyright, Black check, compileall, and
  translation JSON validation.

## Acceptance and commit boundary

Commit this plan, native-Auto implementation, and its tests together only after
all required validation succeeds.

## Delivery result

Delivered with 18 passing tests. Ruff, Pyright, Black, compileall, and
translation JSON validation pass. The two touched production files had
pre-existing Black drift and were formatted in full so the canonical CI check
passes.
