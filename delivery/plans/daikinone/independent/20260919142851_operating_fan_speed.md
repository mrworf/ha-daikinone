# Operating Fan Speed Controls

## Summary

Replace the climate entity's misleading circulation policy with the head unit's real mode-specific operating fan
speed. Preserve circulation as separately named selects only when the Daikin payload explicitly contains circulation
fields.

The Daikin app APK establishes these operating speed values: Low `3`, Medium Low `4`, Medium `5`, Medium High `6`,
High `7`, Auto `10`, and Quiet `11`. It reads and writes `iduHeatFanSpeed`, `iduCoolFanSpeed`, `iduAutoFanSpeed`,
`iduDryFanSpeed`, or `iduFanModeFanSpeed` according to operating mode.

## Slice index

1. `20260919142851_operating_fan_speed_slice_01.md` - Add operating fan-speed modeling and climate control, separate
   circulation entities, clean obsolete mini-split selects, document behavior, and validate.

## Acceptance

- Supported heads show all seven operating speeds in the thermostat Fan mode control.
- Native Heat, Cool, and Auto write only their mode-specific setting.
- Emulated Heat/Cool writes both Heat and Cool settings and remains controllable while physically idle.
- Native Off does not expose operating fan-speed control.
- Circulation mode and speed appear as separate selects only when their raw payload fields exist.
- Existing supported circulation-speed entity IDs remain stable; obsolete mini-split entries are removed.

## Transaction

- Parent commit: `724e6cea401c54762b2ac7aa8d1f316691aedb1f`.
- Payload commit: recorded by the provenance closeout after delivery.
