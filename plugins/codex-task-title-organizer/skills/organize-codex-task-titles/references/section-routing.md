# Route renamed Codex tasks to sidebar sections

This optional feature groups **Codex tasks** by the Domain field of a successful
standardized title:

`Marker Domain｜Project/repository key｜Work type｜Concrete object: purpose or symptom`

It never routes ChatGPT conversations, reads prompt text, or creates a section
from the project key or object description.

## Enable for one project

Add `sectionRouting` to that project's `.codex/task-title-organizer.json`:

```json
{
  "enabled": true,
  "checkpoints": [2, 4, 10],
  "sectionRouting": {
    "enabled": true,
    "sectionPrefix": "🗂️",
    "createMissingSections": true,
    "allowedDomains": ["Backend", "Mobile", "Infra"],
    "sectionDomainMap": {"Mobile": "Backend"},
    "maxSections": 12,
    "sectionCapacity": {
      "enabled": true,
      "maxItems": 10,
      "overflowDestination": "default"
    }
  }
}
```

`allowedDomains` is an exact, case-sensitive list of short, display-safe Domain
aliases. It may contain at most 16 entries; each may contain at most 40
characters and may not contain a newline, `｜`, `/`, `\\`, `://`, or `@`. Keep project- or
organization-specific aliases in this local file, not in the public plugin.

`createMissingSections` defaults to `false`. It may be `true` only with a
non-empty `allowedDomains` list. This prevents arbitrary title text from
creating a growing set of sidebar sections.

`sectionDomainMap` is optional. It maps one exact title Domain to one exact
parent section Domain while preserving the title itself. Both the source and
target must be present in `allowedDomains`; it accepts at most 16 safe mappings.
For example, a title with Domain `Mobile` can move into `🗂️ Backend` without
rewriting `Mobile` in the title. Omitted allowlisted Domains map to themselves.
Normalized duplicate sources, self-maps, and mapping chains are invalid: route
at most once from the title Domain to its configured parent.

`sectionCapacity` is optional and disabled by default. When enabled, it makes
each routed target section a newest-first bounded queue: the successfully
renamed current task is placed first, and at most `maxItems` entries remain.
`maxItems` is an integer from 1 through 50 and defaults to 10 when capacity is
enabled. `overflowDestination` currently accepts only `"default"`, which
returns confirmed overflow Codex tasks to the normal Tasks area; it does not
delete, archive, or persist a private destination section ID. Any malformed
capacity configuration disables that routing source and falls through to the
next configuration source.

With no allowlist, routing may reuse an existing exact generated section but
never creates one. With routing disabled or malformed configuration, title
maintenance continues and no task is moved.

## User-wide override

Set `CODEX_TASK_TITLE_SECTION_ROUTING=domain` to reuse existing generated
Domain sections without creating missing ones. For a user-wide allowlist or
creation policy, set the variable to one JSON object with the same fields as
`sectionRouting`, for example:

```text
{"enabled":true,"sectionPrefix":"🗂️","createMissingSections":true,"allowedDomains":["Backend","Mobile"],"maxSections":8}
```

Restart Codex after changing a user environment variable. Precedence is the
project `sectionRouting` object, this environment variable, then
`PLUGIN_DATA/config.json`, then disabled by default.

## Routing behavior

After a current task is successfully renamed, the active Codex turn:

1. Uses the returned `threadId` and final title only.
2. Parses the Domain after the one leading marker and before the first `｜`, then
   applies an enabled exact `sectionDomainMap` before choosing the target.
3. Looks up custom sidebar sections once, using only their IDs, names, and
   `itemKeys`, with `list_threads` `limit` set to 50 so current task IDs can be
   resolved without a second listing.
4. Reuses exactly one section named `<sectionPrefix> <mapped Domain>`.
5. Creates that section only when creation is enabled, the Domain is allowlisted,
   and fewer than `maxSections` generated sections share the prefix.
6. Moves only the returned current Codex task. If it is already in the target
   section, it is left in place unless optional capacity retention is enabled.
7. With enabled `sectionCapacity`, constructs the planned target order from the
   current task followed by the pre-move `itemKeys`, treating those keys as
   opaque ordering handles rather than task IDs. It maps each required key to
   exactly one returned task or conversation ID through an exact suffix match,
   and skips capacity work when any mapping is missing or ambiguous. It uses no
   second sidebar listing and never reads a title, summary, prompt, or message.
8. If that planned order exceeds `maxItems`, it checks only each overflow
   item's ID and `kind` from the same list result. When every overflow item is
   a confirmed Codex task, it moves all overflow entries bottom-first to the
   default Tasks area, then calls `reorder_section` with the remaining complete
   mapped `threadIds` list and the current task at the top. That list includes
   every retained task or conversation ID, including a retained ChatGPT
   conversation, exactly once. It never passes raw `itemKeys` to
   `reorder_section` or moves a ChatGPT conversation. If an overflow item is
   unknown or non-Codex, capacity trimming is skipped; the current task may
   still be moved to the top with the complete mapped list.

Duplicate target names, invalid Domains, missing tool results, and any tool
error are fail-open: the title remains and the move is skipped. The feature does
not delete, rename, pin, or unpin sections or tasks. Capacity reordering is
allowed only when explicitly enabled and must include every remaining target
item exactly once; a partial `reorder_section` list is invalid. Any capacity
move or reorder failure leaves the successful title and prior successful move in
place, then stops without retrying.

For manual batch routing, use an explicit request such as:

```text
Use $organize-codex-task-titles to normalize and route recent Codex task titles into sidebar sections.
```

The batch still handles at most 10 eligible Codex tasks and reports renamed and
moved counts separately. Capacity retention applies only to the current-task
Hook routing flow, not to batch cleanup.
