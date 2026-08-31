# Changelog

## 0.3.0

- Extract the organizer into a dedicated one-plugin repository and marketplace.
- Prefer project, repository, or `cwd` basename identifiers when Jira/Gerrit
  keys are absent; never generate `NO-ID`.
- Harden malformed-state handling while preserving schema 2 migration.
- Add cross-platform concurrency, privacy, manifest, marketplace, and skill
  tests plus Windows/Linux CI.
- Point installation and package metadata at the standalone repository.
