# Slice 02: Grouping correction, ambiguity recovery, and documentation

## Goal and observable outcome

Users can inspect and correct automatically discovered heat-pump membership and
names from the integration Options flow. Ambiguous or newly unassigned heads stay
functional and produce an actionable Home Assistant repair instead of being
silently merged.

## Scope

- Add a multi-step Options flow for group selection, editing, naming, membership,
  creation, and removal.
- Validate that a head belongs to at most one group and preserve group IDs across
  edits.
- Reload after changes and remove runtime entities for deleted groups cleanly.
- Create/delete Repairs issues for ambiguous or unassigned supported heads.
- Document discovery, correction, power/energy semantics, and limitations.

Changing existing head controls, unique IDs, or legacy equipment is out of scope.

## Dependencies and ordering

Depends on slice 01's persisted group schema and heat-pump cache.

## Entry point and behavior

The config entry exposes an Options flow. Its overview lets a user choose an
existing group or add one; the editor accepts a name and one or more discovered
head IDs. Saving validated groups updates config-entry options and reloads the
entry. Unassigned supported heads remain normal standalone devices.

## State transitions and error handling

- Editing retains the stored heat-pump ID; adding generates a new stable ID;
  removing deletes that group from active configuration.
- Empty names, empty membership, duplicate assignment, and unknown head IDs are
  rejected in the form without changing saved options.
- Discovery ambiguity or newly found unassigned heads creates one config-entry
  scoped repair; resolving membership removes it.
- No additional authorization is needed beyond access to Home Assistant's
  integration configuration UI.

## Implementation surfaces

Config/options flow, integration reload listener, Repairs integration, entity
registry cleanup where needed, translations, README, and focused tests.

## Tests and validation

- Positive: rename and membership edits persist, preserve group IDs, reload, and
  update device hierarchy.
- Positive: creating and removing a group updates active devices/entities.
- Negative: duplicate, empty, and unknown membership submissions are rejected.
- Positive/negative: Repairs issue appears for unresolved heads and disappears
  after correction.
- Regression: existing config flow and head-unit entities remain unchanged.
- Run focused pytest tests, the full available suite, `ruff check`, and `pyright`.

## Acceptance and commit boundary

Commit the Options flow, recovery behavior, documentation, tests, and this slice
plan together after all available validation passes.
