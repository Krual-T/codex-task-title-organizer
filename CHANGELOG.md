# Changelog

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
