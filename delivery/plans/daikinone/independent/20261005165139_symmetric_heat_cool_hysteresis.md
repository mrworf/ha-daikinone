# Symmetric Heat/Cool Hysteresis

## Summary

Apply the existing emulated Heat/Cool temperature tolerance on both sides of each target. A head starts after the
room moves outside the selected range and keeps running the same distance inside the range before turning off, which
avoids stopping as soon as the room first touches a boundary.

## Slice index

1. `20261005165139_symmetric_heat_cool_hysteresis_slice_01.md` - Change active-demand shutoff thresholds, protect
   narrow ranges, add regression coverage, and explain the behavior in the README.

## Acceptance

- Heating starts at or below the low target minus tolerance and stops at or above the low target plus tolerance.
- Cooling starts at or above the high target plus tolerance and stops at or below the high target minus tolerance.
- Stop thresholds never cross the midpoint of the selected range.
- Zero tolerance preserves the existing boundary-stop behavior.
- External room sensors, shared-unit direction dwell, arbitration, manual control, and adaptive bias continue to work
  as before.

## Transaction

- Parent commit: `dfb2e37e15bcb869b817b12b79446097592b112f`.
- Payload commit: pending.
- Slice status: complete.
