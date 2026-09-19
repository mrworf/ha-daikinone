# External Sensor Diagnostics

## Summary

Expose each configured head's current external temperature and optional humidity information in Home Assistant's
downloadable integration and device diagnostics. Diagnostics should show configuration, current usable readings, and
adaptive-controller status without changing runtime control behavior.

## Slice index

1. `20260919133924_external_sensor_diagnostics_slice_01.md` - Add controller diagnostic snapshots and include them in
   config-entry and device diagnostics.

## Acceptance

- Config-entry diagnostics contain an external-control snapshot for every configured head.
- Thermostat device diagnostics contain the matching head snapshot.
- Unconfigured devices report no external-control snapshot.
- Invalid or stale readings appear as `null`, matching the values the climate entity can actually use.

## Transaction

- Parent commit: `89d471e37d88e347a5f833ad402dc6ccfc48cc03`.
- Payload commit: `043df8dbe64807ade46add0a431cb67e1aa8be7c`.
