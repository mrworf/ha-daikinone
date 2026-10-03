# Slice 01: Grouped Heat-Pump Operating Sensors

## Goal and outcome

A user can see useful outdoor-unit operation and weather readings on each grouped mini-split heat-pump device in
Home Assistant, with group values that tolerate delayed or missing copies from individual indoor heads.

## Scope

- Parse outdoor temperature, operating direction, compressor frequency, defrost, outdoor fan speed, and consumed
  current from each supported head's `odu*` fields.
- Aggregate valid values from online members of each persisted or inferred heat-pump group.
- Expose Outdoor Temperature, Operating State, Defrost, Compressor Frequency, Outdoor Fan Speed, and Electrical
  Current entities with Home Assistant metadata and stable unique IDs.
- Mark compressor frequency, fan speed, and current as diagnostic; keep the other new entities prominent.
- Update the README in its current plain-language style.

## Non-scope

- Compressor discharge, target discharge, heat-exchanger, expansion-valve, rated-power, and request fields.
- Raw compressor on/off, which is inconsistent between copies in the captured data.
- Changes to heat-pump grouping, configuration, controls, power, or cumulative energy behavior.
- Legacy communicating outdoor-equipment entities.

## Dependencies and behavior

This slice builds on the existing grouped mini-split heat-pump devices. Numeric values use the median of valid online
member reports. Defrost is true when any valid online report is true. Operating state gives Defrosting priority, then
uses compressor frequency to distinguish running from idle and the strict-majority outdoor direction to distinguish
Heating from Cooling. If frequency is missing, positive group power is the running fallback. Active operation with no
clear direction is Unknown.

## Data and state transitions

Each cloud refresh replaces per-head outdoor telemetry and rebuilds each heat-pump value. A sensor becomes unavailable
when no online member supplies its field. Defrost becomes unavailable when no online member supplies a valid boolean.
Operating state becomes unavailable with no online member data, Idle when the compressor is stopped, and Unknown when
active reports conflict or use an unsupported direction.

## Authorization

Not applicable. The new entities are read-only and use the existing authenticated Daikin polling request.

## Validation and recovery

- Positive tests cover median aggregation, all five operating states, defrost priority, sensor metadata, entity
  categories, units, unique IDs, and refresh behavior.
- Negative tests cover offline members, missing optional fields, invalid booleans/numbers, conflicting directions,
  unsupported directions, and complete unavailability.
- Run focused heat-pump and sensor tests, the full pytest suite, Pyright, Ruff, Black, JSON parsing, and Git whitespace
  checks.

## Implementation surfaces

- Outdoor telemetry and grouped heat-pump models and aggregation.
- Sensor and binary-sensor platform setup.
- Heat-pump tests, integration platform registration, and README.

## Acceptance criteria

- The six new entities appear on supported grouped heat-pump devices and update from current online member data.
- Existing groups and entity IDs remain stable and existing power and energy tests stay green.
- Unsupported or missing fields produce unavailable entities rather than false zero values or setup failures.
- All required validation passes.

## Commit boundary

Commit this plan, the complete sensor behavior, tests, and documentation as one semantic payload, followed only by the
exact-SHA provenance closeout required by the delivery transaction contract.

## Completion

- Status: complete.
- Payload commit: pending.
- Validation: 83 tests passed; Pyright, Ruff, per-file Black checks, JSON parsing, and Git whitespace checks passed.
