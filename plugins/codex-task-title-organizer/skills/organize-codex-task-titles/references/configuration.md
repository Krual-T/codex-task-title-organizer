# Configure title checkpoints

The Hook defaults to checkpoints `2, 4, 10`:

- `2`: establish a useful title early;
- `4`: refine only when the title is missing, inaccurate, or materially clearer;
- `10`: refresh only after a material change in project, work type, object, or purpose.

## Project-level configuration

Use this for one repository. Create `.codex/task-title-organizer.json` under the
project root:

    {
      "enabled": true,
      "checkpoints": [2, 4, 10]
    }

To disable the Hook for that project:

    {
      "enabled": false
    }

Write this file only when the user explicitly asks to configure the project.
Do not add it merely because the skill was loaded.

## User-wide environment override

Set `CODEX_TASK_TITLE_CHECKPOINTS` to a comma-separated list such as `2,4,10`.
Use `off`, `false`, `disabled`, or `none` to disable the Hook. Restart Codex
so the desktop process inherits a changed environment variable.

Change the user environment only when the user explicitly asks for a user-wide
setting. Do not set it as a side effect of project-level configuration.

## Plugin-data configuration

Managed or advanced installations may place this JSON at
`PLUGIN_DATA/config.json`, using the same schema as the project file. Codex
provides `PLUGIN_DATA` to the Hook process as its writable plugin data directory.
Do not guess or derive that path from Codex databases or session files.

## Precedence and validation

Configuration precedence is:

1. project `.codex/task-title-organizer.json`;
2. `CODEX_TASK_TITLE_CHECKPOINTS`;
3. `PLUGIN_DATA/config.json`;
4. default `2,4,10`.

Checkpoint values must be unique integers from 1 through 50. At most eight are
accepted. The Hook sorts valid values. Invalid, oversized, or malformed config
is ignored and the next valid source is used.

Changing a schedule during an active task never replays newly added checkpoints
whose prompt numbers already passed. Future checkpoints in the new schedule
remain eligible.

## Sidebar routing

Sidebar routing uses the same project file and plugin-data file, but its
user-wide override is `CODEX_TASK_TITLE_SECTION_ROUTING`. It is disabled by
default and has its own per-field precedence so a project routing policy can
override a user-wide one without changing checkpoints. Read
[section-routing.md](section-routing.md) before enabling it.
