# Nullable Outdoor Telemetry Compatibility

## Summary

Accept Daikin mini-split payloads that contain explicit null outdoor-unit values. Thermostat setup must continue,
configured heat-pump devices must remain present, valid fields such as cumulative energy must still update, and
unavailable readings must be reported as unavailable rather than as zero.

## Slice index

1. `20261015181244_nullable_outdoor_telemetry_slice_01.md` - Make environmental and outdoor telemetry mapping
   null-safe, preserve configured devices from partial reports, and add sanitized regression coverage.

## Acceptance

- A null `oduOutdoorTemp` cannot prevent the integration from loading.
- The new `iduRoomHum` value is used for indoor humidity, with the legacy field retained as a fallback.
- Persisted heat-pump groups and head assignments survive partial or null outdoor telemetry.
- Valid fields in a partial report remain available; invalid or null fields become unavailable, not zero.
- Automatic group discovery remains conservative and does not group heads from incomplete evidence.

## Transaction

- Parent commit: `31db30ae609aa9924b8898d43bd35c9730bb2b32`.
- Payload commit: `b2fd541d5dd2ac5c346ada6b059cc38cf87f37a0`.
- Slice status: complete.
