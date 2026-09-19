# External Environmental Sensor Display Fix

## Summary

When external-temperature control is configured for a head, its Home Assistant climate entity must always present a
fresh external sensor reading as the current temperature, regardless of HVAC mode. HVAC mode continues to determine
whether adaptive bias learning runs. An unavailable, invalid, or stale external sensor still falls back to the head's
internal temperature.

Because Home Assistant normally represents temperature and humidity as separate entities, each head may also select
an optional external humidity entity. A fresh valid reading is shown as the climate entity's current humidity in every
mode; otherwise humidity falls back independently to the head's internal reading. Existing temperature-only options
remain valid.

## Slice index

1. `20260919124734_external_temperature_display_fix_slice_01.md` - Correct environmental presentation, add optional
   humidity configuration, and add regression coverage.

## Acceptance

- A configured head in Off, Auto, Heat, Cool, emulated Heat/Cool, or Emergency Heat shows its fresh external reading.
- A configured head with no valid fresh external reading shows the internal head temperature.
- An unconfigured head remains unchanged.
- A configured external humidity entity is shown in every mode when fresh and valid, with independent internal
  humidity fallback when it is not.

## Transaction

- Parent commit: `b44cfdbb7f9ced76bcc5afe6e93d9abc6c434a41`.
- Payload commit: `7775b82c4a14aa35f54684ec4dda3eab522e46ff`.
