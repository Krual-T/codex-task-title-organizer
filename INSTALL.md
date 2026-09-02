# Install Codex Task Title Organizer

This repository is a complete one-plugin Codex marketplace.

## GitHub installation

```text
codex plugin marketplace add znbsf/codex-task-title-organizer --ref main
codex plugin add codex-task-title-organizer@codex-task-title-organizer
```

## Local checkout or extracted ZIP

From any terminal, keep the repository at a stable path and run:

```text
codex plugin marketplace add "<repository-root>"
codex plugin add codex-task-title-organizer@codex-task-title-organizer
```

If the marketplace is already configured, inspect `codex plugin marketplace
list` and reuse it instead of creating a duplicate.

## Required review

1. Verify Python 3 with `py -3 --version` on Windows or `python3 --version` on
   macOS/Linux.
2. Refresh or restart Codex and start a new task.
3. Open `/hooks`, inspect the `UserPromptSubmit` command, and trust it.
4. The counter begins when the enabled and trusted plugin first observes a
   prompt in that task session.

Do not claim the automatic checkpoints are active before the Hook is trusted.

## Migrating from codex-personal-skills

The package ID remains `codex-task-title-organizer`, so titles and skill prompts
do not need to change. Add this standalone marketplace and install the package
qualified by its new marketplace name:

```text
codex plugin add codex-task-title-organizer@codex-task-title-organizer
```

Do not delete the old repository. Remove or disable an older installed copy only
after confirming the standalone package appears in `codex plugin list` and the
new Hook has been reviewed. Existing Hook counters are marketplace-local and do
not need to be copied.

## Ask Codex to install a local ZIP

After extracting the ZIP and opening it as a Codex project, ask:

```text
Install the Codex plugin marketplace in this repository. Read INSTALL.md,
verify the package and Python 3, install codex-task-title-organizer, and stop for
me to review and trust its Hook. Do not edit Codex session or database files.
```

The plugin does not create a scheduled automation. Its Hook handles current-task
checkpoints; old-task batch cleanup remains an explicit skill action.

The default Hook checkpoints are `2,4,10`. Configure one repository with
`.codex/task-title-organizer.json`, or set the user-wide
`CODEX_TASK_TITLE_CHECKPOINTS` environment variable. Title-based sidebar
routing is disabled by default and needs an explicit bounded Domain allowlist
before it may create sections. See the configuration section in `README.md`
before applying a broader override.
