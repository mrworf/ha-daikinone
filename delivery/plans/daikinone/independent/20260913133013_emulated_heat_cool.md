# Emulated Heat/Cool delivery plan

Parent commit: `d88e167b46a0fc18174521c9752b773cdb64a457`

## Goal

Expose Daikin-native Auto truthfully as a single-setpoint Home Assistant mode and
add a separate emulated Heat/Cool mode. Emulation manages each head from a
low/high temperature range while coordinating all heads connected to one outdoor
heat pump so it is never deliberately commanded to heat and cool simultaneously.

## Compatibility contract

- Existing thermostat entity/device identifiers, manual Heat/Cool/Off behavior,
  fan controls, emergency heat, energy sensors, and grouping remain unchanged.
- Native Auto remains available and uses `iduAutoSetpoint`.
- Emulated state is additive, restored through the existing climate entity, and
  never persisted by repeatedly rewriting config-entry options.
- Physical-remote manual changes take precedence over emulation.
- `data_from_daikin.json` is private diagnostic input and remains untracked.

## Slice index

1. [Native Auto single-setpoint support](20260913133013_emulated_heat_cool_slice_01.md) — completed
2. [Group-aware emulated Heat/Cool controller](20260913133013_emulated_heat_cool_slice_02.md)

## Completion criteria

- Native Auto presents and updates one target temperature.
- Emulated Heat/Cool presents low/high targets and selects physical Heat, Cool,
  or Off with configured hysteresis and dwell.
- Shared pumps arbitrate demands without deliberate opposing commands, and
  manual/native-Auto ownership visibly suspends incompatible emulated demand.
- Logical state survives restart, remote changes are respected, and existing
  functionality passes the full validation suite.
