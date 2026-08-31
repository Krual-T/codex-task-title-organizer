# Codex Task Title Organizer

A standalone Codex plugin for keeping task titles compact, searchable, visually
consistent, and tied to the right project or repository.

The plugin bundles one skill and one privacy-conscious `UserPromptSubmit` Hook:

- prompt 2 asks the active Codex turn to establish a useful title;
- prompt 4 refines it only when clearer task context is available;
- prompt 10 refreshes it only when the project, object, or purpose changed materially;
- the Hook never reads or persists prompt text;
- old tasks can still be normalized manually in batches of at most 10.

## Title standard

`Marker Domain｜Project/repository key｜Work type｜Concrete object: purpose or symptom`

Color blocks remain the default, while semantic icons and explicit custom
markers are supported:

| Primary outcome | Color blocks (default) | Semantic icons |
| --- | --- | --- |
| Analysis or diagnosis | `🟥` | `🔎` |
| Fix or implementation | `🟦` | `🔧` |
| Validation or testing | `🟩` | `🧪` |
| Delivery or synchronization | `🟪` | `📦` |
| Review | `🟧` | `👀` |
| Documentation or reporting | `🟨` | `📝` |
| Environment, tooling, or automation | `🟫` | `⚙️` |

Use exactly one leading marker. A project may define one custom marker or a
complete category mapping in `AGENTS.md`; explicit instructions for the current
operation take precedence. Invalid or incomplete custom mappings fall back to
color blocks at automatic checkpoints.

## Sidebar examples

Color blocks (default):

![Color-block title examples](docs/assets/title-organizer-sidebar-examples-en-color-blocks.png)

Semantic icons:

![Semantic-icon title examples](docs/assets/title-organizer-sidebar-examples-en-semantic-icons.png)

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

## Configure checkpoints

The default schedule is `2,4,10`. For one project, create
`.codex/task-title-organizer.json`:

    {
      "enabled": true,
      "checkpoints": [2, 4, 10]
    }

Set `"enabled": false` to disable the Hook for that project.

For a user-wide override, set `CODEX_TASK_TITLE_CHECKPOINTS` to a comma-separated
list such as `1,3,8`. The Hook also supports `PLUGIN_DATA/config.json` for managed
or advanced installs. Precedence is project file, environment variable,
plugin-data file, then defaults. Values must be 1-50, unique, with at most eight
checkpoints. Invalid configuration safely falls through to the next source.

Schedule changes do not replay checkpoint numbers that already passed in an
active task.

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

```text
Use $organize-codex-task-titles to migrate recent compliant titles to semantic
icons, changing only the leading marker.
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
