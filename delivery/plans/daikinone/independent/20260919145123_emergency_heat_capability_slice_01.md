# Slice 01: Advertise Emergency Heat Only When Supported

## Goal and outcome

Home Assistant shows the Emergency Heat preset only for Daikin equipment that explicitly reports auxiliary-only
heating support.

## Scope

- Initialize thermostat capabilities as empty rather than pre-populating every enum member.
- Continue inferring Heat and Cool from their existing capability or setpoint fields.
- Infer Emergency Heat from truthy `ctSystemCapEmergencyHeat` or `modeEmHeatAvailable`.
- Add positive and negative mapper and climate-presentation coverage.

## Non-scope

- Changing the existing mode-4 Emergency Heat command.
- Adding auxiliary heat to mini-splits that do not advertise it.
- Adding vane controls; that is a separate behavior slice requiring its own UI contract.

## Dependencies and behavior

Thermostat discovery maps only capabilities proven by the payload. The climate constructor continues to add the
Emergency Heat preset and preset feature from the mapped capability, so no separate presentation heuristic is
introduced.

## Authorization

No new authority or API writes are introduced. This change only narrows presentation of an existing command to
equipment that reports support.

## Validation and recovery

- A payload with neither emergency field omits the capability and preset.
- A false field omits the capability.
- Either recognized truthy field includes the capability and preset.
- Run focused capability tests, the full pytest suite, Pyright, Ruff, Black, JSON parsing, and Git whitespace checks.

## Implementation surfaces

- Daikin thermostat payload mapper.
- Mapper and climate tests.

## Acceptance criteria

- Unsupported mini-split heads no longer show Emergency Heat.
- Supported unitary systems retain the existing preset.
- Heat and Cool modes remain available when their existing evidence is present.

## Commit boundary

Commit the plan, capability correction, and tests as one semantic payload, followed only by the exact-SHA
provenance closeout.

## Completion

- Status: complete.
- Payload commit: `5a5497cafb34a30bb78b76f3d58d8dae526501bd`.
- Validation: 66 tests passed; Pyright, Ruff, Black, JSON parsing, and Git whitespace checks passed.
