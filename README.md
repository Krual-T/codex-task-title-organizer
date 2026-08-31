# Codex Task Title Organizer

A standalone Codex plugin for keeping task titles compact, searchable, visually
consistent, and tied to the right project or repository.

The plugin bundles one skill and one privacy-conscious `UserPromptSubmit` Hook:

- prompt 4 asks the active Codex turn to set a useful title;
- prompt 10 refreshes it only when the object or purpose changed materially;
- the Hook never reads or persists prompt text;
- old tasks can still be normalized manually in batches of at most 10.

## Title standard

`Colored emoji Domain｜Project/repository key｜Work type｜Concrete object: purpose or symptom`

For private projects without Jira or Gerrit, the second field uses the project
name, repository name, or only the `cwd` basename. It never generates `NO-ID`.
A compact local activity date is the final fallback only when no project context
exists.

## How the Hook works

The command Hook does not rename a task by reaching into Codex internals. It
counts unique prompts, then adds a narrowly scoped developer instruction to the
same foreground turn. The active Codex turn uses the public current-task title
tool, without a thread ID, after finishing the user's main request.

State is stored under Codex's plugin data directory and contains only:

- a SHA-256 hash of the session ID in the filename;
- SHA-256 hashes of recently seen turn IDs;
- the prompt count and fired checkpoints.

It stores no generated titles, prompt excerpts, transcripts, rollout data,
database content, full user paths, or project taxonomy.

## Install from GitHub

```text
codex plugin marketplace add znbsf/codex-task-title-organizer --ref main
codex plugin add codex-task-title-organizer@codex-task-title-organizer
```

Restart or refresh Codex, open `/hooks`, inspect the exact command, and trust it.
Automatic checkpoints are not active until that user review is complete.

## Install from a local checkout or ZIP

```text
codex plugin marketplace add "<repository-root>"
codex plugin add codex-task-title-organizer@codex-task-title-organizer
```

Keep the local marketplace directory at a stable path. See [INSTALL.md](INSTALL.md)
for the full AI-oriented procedure and migration guidance.

## Manual use

The bundled skill remains available for explicit work:

```text
Use $organize-codex-task-titles to standardize the current Codex task title.
```

```text
Use $organize-codex-task-titles to normalize recent Codex task titles, changing
at most 10 and skipping active and ChatGPT tasks.
```

## Develop and verify

Python 3.10 or newer is recommended. The Hook itself has no third-party runtime
dependencies.

```text
python -m compileall -q plugins/codex-task-title-organizer/scripts
python -m unittest discover -s tests -v
```

CI exercises both Windows and Linux because the state lock is platform-specific.

## Safety boundaries

- Current-task checkpoints never list or read other tasks.
- Batch operations modify only `kind=codex`, skip active tasks by default, and
  stop at 10 changes per run.
- The plugin never uses Codex databases, session/rollout files, or UI automation
  as a title-management fallback.
- Installing the plugin does not create, edit, or delete recurring automations.
