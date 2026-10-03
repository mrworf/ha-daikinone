# Heat-Pump Operating Sensors

## Summary

Expose six useful outdoor-unit readings on each grouped mini-split heat-pump device: outdoor temperature, operating
state, defrost activity, compressor frequency, outdoor fan speed, and electrical current. Keep the existing power and
energy sensors unchanged.

## Slice index

1. `20261003153032_heat_pump_operating_sensors_slice_01.md` - Aggregate outdoor telemetry, expose the six entities,
   test availability and state behavior, and update user documentation.

## Acceptance

- Each grouped heat-pump device gains the six agreed entities with stable group-based unique IDs.
- Outdoor temperature, operating state, and defrost are normal entities; frequency, fan speed, and current are
  diagnostic entities.
- Numeric readings use the median of valid online member reports.
- Defrost is active when any valid online member reports it.
- Operating state is Idle, Heating, Cooling, Defrosting, or Unknown and does not present a stale raw direction as
  active operation.
- Missing, invalid, conflicting, and offline reports degrade to Unknown or unavailable without breaking existing
  power, energy, or grouping behavior.

## Transaction

- Parent commit: `b8140aaf43b535a4ba1d36b2ebe0cf69c27be514`.
- Payload commit: pending.
- Slice status: complete.
