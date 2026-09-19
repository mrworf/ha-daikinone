# Emergency Heat Capability Detection

## Summary

Stop advertising Emergency Heat on thermostats that do not report an auxiliary-only heating mode. Preserve the
existing preset and mode command for systems that explicitly advertise the capability through either the current
device-data field or the legacy field used by the Daikin application.

## Slice index

1. `20260919145123_emergency_heat_capability_slice_01.md` - Correct capability mapping, cover supported and
   unsupported payloads, validate, commit, and push.

## Acceptance

- A mini-split payload without an emergency-heat capability does not expose the preset.
- `ctSystemCapEmergencyHeat` enables the preset only when truthy.
- Legacy `modeEmHeatAvailable` also enables the preset when truthy.
- Existing Heat and Cool capability discovery remains unchanged.

## Transaction

- Parent commit: `e23600bf69e3b7eb95da8a557a238431670dd3e1`.
- Payload commit: `5a5497cafb34a30bb78b76f3d58d8dae526501bd`.
- Slice status: complete.
