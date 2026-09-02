# Changelog

## Unreleased

- Add optional, bounded `sectionCapacity` retention: route the current task to
  the top, keep a configured maximum, and return confirmed Codex overflow tasks
  to the default Tasks area without deleting or archiving them.
- Add an optional, allowlist-bound `sectionDomainMap` so detailed title Domains
  can route to an approved parent sidebar section without rewriting the title.

## 0.5.0

- Add optional, bounded title-Domain routing to custom sidebar sections after a
  successful current-task rename.
- Require explicit routing configuration; missing-section creation needs a
  non-empty Domain allowlist and a section-count limit.
- Keep routing fail-open, current-task-only at Hook checkpoints, and separate
  from explicit batch cleanup.

## 0.4.0

- Keep color blocks as the default and add semantic-icon and explicit custom
  marker styles.
- Preserve compliant title fields during marker-only migrations.
- Let explicit requests and project instructions select a marker style without
  expanding Hook state or weakening privacy boundaries.

## 0.3.0+codex.20260831144036

- Change the default Hook schedule from `4,10` to `2,4,10`.
- Distinguish initial, refinement, and final refresh checkpoint semantics.
- Add project JSON, environment, and plugin-data configuration with explicit
  precedence, validation, disable support, and non-replaying schedule migration.
- Migrate existing schema 2/3 state without firing newly added past checkpoints.

## 0.3.0

- Extract the organizer into a dedicated one-plugin repository and marketplace.
- Prefer project, repository, or `cwd` basename identifiers when Jira/Gerrit
  keys are absent; never generate `NO-ID`.
- Harden malformed-state handling while preserving schema 2 migration.
- Add cross-platform concurrency, privacy, manifest, marketplace, and skill
  tests plus Windows/Linux CI.
- Point installation and package metadata at the standalone repository.
