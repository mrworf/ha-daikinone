# Vertical Vane Swing Control

## Summary

Expose each compatible Daikin indoor head's vertical vane as Home Assistant's climate Swing mode. Use the
mode-specific fields and values confirmed by the Daikin application and the captured mini-split payloads.

## Slice index

1. `20260919145828_vertical_vane_control_slice_01.md` - Model, write, display, test, document, commit, and push
   vertical Fixed/Oscillate control.

## Acceptance

- Compatible heads show Fixed and Oscillate in the thermostat Swing mode control.
- Native Heat, Cool, and Auto write only their corresponding vertical-direction field.
- Emulated Heat/Cool writes both Heat and Cool vertical-direction fields and remains controllable while idle.
- Native Off hides Swing mode.
- Heads or modes without a reported vertical-direction field do not advertise Swing mode.
- Read value `23` is accepted as Fixed; unknown values do not break discovery.

## Transaction

- Parent commit: `d665c1738d2ad228ee495cacddd07cf6166aee04`.
- Payload commit: `f53a4fd2d19482e2a2dd7b6192daa3a3c8b71c33`.
- Slice status: complete.
