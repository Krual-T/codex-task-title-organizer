#!/usr/bin/env python3
"""Emit title-maintenance context without reading prompt or title tool payloads."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


DEFAULT_CHECKPOINTS = (2, 4, 10)
CHECKPOINT_ENV = "CODEX_TASK_TITLE_CHECKPOINTS"
SECTION_ROUTING_ENV = "CODEX_TASK_TITLE_SECTION_ROUTING"
PROJECT_CONFIG_RELATIVE = Path(".codex") / "task-title-organizer.json"
PLUGIN_DATA_CONFIG_NAME = "config.json"
MAX_CONFIG_BYTES = 16 * 1024
MAX_CHECKPOINTS = 8
MAX_CHECKPOINT_VALUE = 50
DEFAULT_SECTION_PREFIX = "🗂️"
DEFAULT_MAX_SECTIONS = 12
DEFAULT_MAX_SECTION_ITEMS = 10
DEFAULT_SECTION_OVERFLOW_DESTINATION = "default"
DISABLED_SECTION_CAPACITY = (
    False,
    DEFAULT_MAX_SECTION_ITEMS,
    DEFAULT_SECTION_OVERFLOW_DESTINATION,
)
MAX_SECTION_PREFIX_LENGTH = 16
MAX_SECTION_COUNT = 20
MAX_SECTION_ITEMS = 50
MAX_ROUTED_DOMAINS = 16
MAX_ROUTED_DOMAIN_LENGTH = 40
MAX_SECTION_DOMAIN_MAPPINGS = 16
MAX_SEEN_TURNS = 64
MAX_TITLE_TOOL_COMPLETION_OBSERVATIONS = MAX_CHECKPOINTS
SCHEMA_VERSION = 5
TITLE_TOOL_NAME = "mcp__codex_app__set_thread_title"

SectionDomainMap = tuple[tuple[str, str], ...]
SectionCapacity = tuple[bool, int, str]
SectionRoutingConfig = tuple[
    bool,
    str,
    bool,
    tuple[str, ...],
    SectionDomainMap,
    int,
    SectionCapacity,
    str,
]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _normalize_checkpoints(value: Any) -> tuple[int, ...] | None:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        raw_items: Any = [item.strip() for item in text.split(",")]
    elif isinstance(value, (list, tuple)):
        raw_items = value
    else:
        return None

    parsed: list[int] = []
    for item in raw_items:
        if isinstance(item, bool):
            return None
        if isinstance(item, int):
            checkpoint = item
        elif isinstance(item, str) and item.isdigit():
            checkpoint = int(item)
        else:
            return None
        if not 1 <= checkpoint <= MAX_CHECKPOINT_VALUE:
            return None
        parsed.append(checkpoint)

    if not parsed or len(parsed) > MAX_CHECKPOINTS or len(set(parsed)) != len(parsed):
        return None
    return tuple(sorted(parsed))


def _parse_config(payload: Any, source: str) -> tuple[bool, tuple[int, ...], str] | None:
    if not isinstance(payload, dict):
        return None
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        return None
    if not enabled:
        return False, (), source
    checkpoints = _normalize_checkpoints(payload.get("checkpoints"))
    if checkpoints is None:
        return None
    return True, checkpoints, source


def _read_json_file(path: Path) -> Any | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def _read_config_file(path: Path, source: str) -> tuple[bool, tuple[int, ...], str] | None:
    payload = _read_json_file(path)
    if payload is None:
        return None
    return _parse_config(payload, source)


def _project_config_path(payload: dict[str, Any]) -> Path | None:
    cwd_text = payload.get("cwd")
    if not isinstance(cwd_text, str) or not cwd_text:
        return None
    cwd = Path(cwd_text)
    if not cwd.is_absolute():
        return None
    return cwd / PROJECT_CONFIG_RELATIVE


def _load_config(
    payload: dict[str, Any], data_root: Path
) -> tuple[bool, tuple[int, ...], str]:
    project_path = _project_config_path(payload)
    if project_path is not None:
        project = _read_config_file(project_path, "project")
        if project is not None:
            return project

    env_value = os.environ.get(CHECKPOINT_ENV)
    if env_value is not None:
        if env_value.strip().lower() in {"off", "false", "disabled", "none"}:
            return False, (), "environment"
        checkpoints = _normalize_checkpoints(env_value)
        if checkpoints is not None:
            return True, checkpoints, "environment"

    plugin_data = _read_config_file(
        data_root / PLUGIN_DATA_CONFIG_NAME, "plugin-data"
    )
    if plugin_data is not None:
        return plugin_data

    return True, DEFAULT_CHECKPOINTS, "default"


def _normalize_section_prefix(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    prefix = value.strip()
    if (
        not prefix
        or len(prefix) > MAX_SECTION_PREFIX_LENGTH
        or "｜" in prefix
        or "\r" in prefix
        or "\n" in prefix
    ):
        return None
    return prefix


def _normalize_max_sections(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not 1 <= value <= MAX_SECTION_COUNT:
        return None
    return value


def _normalize_max_section_items(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not 1 <= value <= MAX_SECTION_ITEMS:
        return None
    return value


def _normalize_routed_domain(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    domain = value.strip()
    if (
        not domain
        or len(domain) > MAX_ROUTED_DOMAIN_LENGTH
        or "｜" in domain
        or "/" in domain
        or "\\" in domain
        or "://" in domain
        or "@" in domain
        or "\r" in domain
        or "\n" in domain
    ):
        return None
    return domain


def _normalize_routed_domains(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)):
        return None
    domains: list[str] = []
    for item in value:
        domain = _normalize_routed_domain(item)
        if domain is None:
            return None
        if domain not in domains:
            domains.append(domain)
    if len(domains) > MAX_ROUTED_DOMAINS:
        return None
    return tuple(domains)


def _normalize_section_domain_map(value: Any) -> SectionDomainMap | None:
    if value is None:
        return ()
    if not isinstance(value, dict) or len(value) > MAX_SECTION_DOMAIN_MAPPINGS:
        return None
    mappings: list[tuple[str, str]] = []
    normalized_sources: set[str] = set()
    for source, target in value.items():
        normalized_source = _normalize_routed_domain(source)
        normalized_target = _normalize_routed_domain(target)
        if normalized_source is None or normalized_target is None:
            return None
        if normalized_source in normalized_sources:
            return None
        normalized_sources.add(normalized_source)
        mappings.append((normalized_source, normalized_target))
    if any(target in normalized_sources for _, target in mappings):
        return None
    return tuple(mappings)


def _parse_section_capacity(value: Any) -> SectionCapacity | None:
    if value is None:
        return DISABLED_SECTION_CAPACITY
    if not isinstance(value, dict):
        return None

    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        return None
    if not enabled:
        return DISABLED_SECTION_CAPACITY

    max_items = _normalize_max_section_items(
        value.get("maxItems", DEFAULT_MAX_SECTION_ITEMS)
    )
    overflow_destination = value.get(
        "overflowDestination", DEFAULT_SECTION_OVERFLOW_DESTINATION
    )
    if (
        max_items is None
        or overflow_destination != DEFAULT_SECTION_OVERFLOW_DESTINATION
    ):
        return None
    return True, max_items, overflow_destination


def _parse_section_routing_value(
    routing: Any, source: str
) -> SectionRoutingConfig | None:
    if not isinstance(routing, dict):
        return None
    enabled = routing.get("enabled", False)
    if not isinstance(enabled, bool):
        return None
    if not enabled:
        return (
            False,
            DEFAULT_SECTION_PREFIX,
            False,
            (),
            (),
            DEFAULT_MAX_SECTIONS,
            DISABLED_SECTION_CAPACITY,
            source,
        )

    prefix = _normalize_section_prefix(
        routing.get("sectionPrefix", DEFAULT_SECTION_PREFIX)
    )
    max_sections = _normalize_max_sections(
        routing.get("maxSections", DEFAULT_MAX_SECTIONS)
    )
    create_missing = routing.get("createMissingSections", False)
    if not isinstance(create_missing, bool):
        return None
    raw_domains = routing.get("allowedDomains", [])
    domains = _normalize_routed_domains(raw_domains)
    domain_map = _normalize_section_domain_map(routing.get("sectionDomainMap"))
    section_capacity = _parse_section_capacity(routing.get("sectionCapacity"))
    if (
        prefix is None
        or max_sections is None
        or domains is None
        or domain_map is None
        or section_capacity is None
    ):
        return None
    # Creating a new section from arbitrary title text would be surprising and
    # vulnerable to untrusted title data. It is permitted only for an explicit,
    # bounded domain allowlist.
    if create_missing and not domains:
        return None
    if domain_map and (
        not domains
        or any(
            source_domain not in domains or target_domain not in domains
            for source_domain, target_domain in domain_map
        )
    ):
        return None
    return (
        True,
        prefix,
        create_missing,
        domains,
        domain_map,
        max_sections,
        section_capacity,
        source,
    )


def _parse_section_routing(
    payload: Any, source: str
) -> SectionRoutingConfig | None:
    if not isinstance(payload, dict) or "sectionRouting" not in payload:
        return None
    return _parse_section_routing_value(payload["sectionRouting"], source)


def _parse_section_routing_environment(
    value: str | None,
) -> SectionRoutingConfig | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"off", "false", "disabled", "none"}:
        return (
            False,
            DEFAULT_SECTION_PREFIX,
            False,
            (),
            (),
            DEFAULT_MAX_SECTIONS,
            DISABLED_SECTION_CAPACITY,
            "environment",
        )
    if normalized in {"domain", "on", "true", "enabled"}:
        return (
            True,
            DEFAULT_SECTION_PREFIX,
            False,
            (),
            (),
            DEFAULT_MAX_SECTIONS,
            DISABLED_SECTION_CAPACITY,
            "environment",
        )
    try:
        return _parse_section_routing_value(json.loads(value), "environment")
    except json.JSONDecodeError:
        return None


def _read_section_routing_file(
    path: Path, source: str
) -> SectionRoutingConfig | None:
    payload = _read_json_file(path)
    if payload is None:
        return None
    return _parse_section_routing(payload, source)


def _load_section_routing(
    payload: dict[str, Any], data_root: Path
) -> SectionRoutingConfig:
    project_path = _project_config_path(payload)
    if project_path is not None:
        project = _read_section_routing_file(project_path, "project")
        if project is not None:
            return project

    environment = _parse_section_routing_environment(
        os.environ.get(SECTION_ROUTING_ENV)
    )
    if environment is not None:
        return environment

    plugin_data = _read_section_routing_file(
        data_root / PLUGIN_DATA_CONFIG_NAME, "plugin-data"
    )
    if plugin_data is not None:
        return plugin_data

    return (
        False,
        DEFAULT_SECTION_PREFIX,
        False,
        (),
        (),
        DEFAULT_MAX_SECTIONS,
        DISABLED_SECTION_CAPACITY,
        "default",
    )


def _default_state(checkpoints: tuple[int, ...]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_count": 0,
        "seen_turns": [],
        "fired_thresholds": [],
        "checkpoint_signature": list(checkpoints),
        "pending_title_tool_completions": [],
        "title_tool_completion_observations": [],
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _threshold_set(value: Any) -> set[int]:
    if not isinstance(value, list):
        return set()
    parsed: set[int] = set()
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            threshold = item
        elif isinstance(item, str) and item.isdigit():
            threshold = int(item)
        else:
            continue
        if 1 <= threshold <= MAX_CHECKPOINT_VALUE:
            parsed.add(threshold)
    return parsed


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _checkpoint_turn_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    records: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        turn_token = item.get("turn_token")
        checkpoint = item.get("checkpoint")
        if (
            not _is_digest(turn_token)
            or isinstance(checkpoint, bool)
            or not isinstance(checkpoint, int)
            or not 1 <= checkpoint <= MAX_CHECKPOINT_VALUE
        ):
            continue
        record = {"turn_token": turn_token, "checkpoint": checkpoint}
        if record not in records:
            records.append(record)
    return records[-MAX_TITLE_TOOL_COMPLETION_OBSERVATIONS:]


def _load_state(path: Path, checkpoints: tuple[int, ...]) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, UnicodeError):
        return _default_state(checkpoints)
    if not isinstance(loaded, dict) or loaded.get("schema_version") not in (2, 3, 4, 5):
        return _default_state(checkpoints)

    state = _default_state(checkpoints)
    state["prompt_count"] = _nonnegative_int(loaded.get("prompt_count"))
    state["seen_turns"] = _string_list(loaded.get("seen_turns"))[-MAX_SEEN_TURNS:]
    fired = _threshold_set(loaded.get("fired_thresholds"))

    previous_signature = (
        _normalize_checkpoints(loaded.get("checkpoint_signature"))
        if loaded.get("schema_version") == SCHEMA_VERSION
        else None
    )
    if previous_signature != checkpoints:
        # A newly introduced checkpoint must not replay after its prompt has
        # already passed. Future checkpoints in the new schedule remain eligible.
        fired.update(
            checkpoint
            for checkpoint in checkpoints
            if checkpoint <= state["prompt_count"]
        )

    state["fired_thresholds"] = sorted(fired)
    if loaded.get("schema_version") == SCHEMA_VERSION:
        state["pending_title_tool_completions"] = _checkpoint_turn_records(
            loaded.get("pending_title_tool_completions")
        )
        state["title_tool_completion_observations"] = _checkpoint_turn_records(
            loaded.get("title_tool_completion_observations")
        )
    return state


def _write_state(path: Path, state: dict[str, Any]) -> None:
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(state, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _try_lock(handle: Any) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        for _ in range(50):
            if _try_lock(handle):
                break
            time.sleep(0.02)
        else:
            raise TimeoutError("could not acquire title checkpoint state lock")
        try:
            yield
        finally:
            _unlock(handle)


def _section_routing_context(
    enabled: bool,
    section_prefix: str,
    create_missing_sections: bool,
    allowed_domains: tuple[str, ...],
    section_domain_map: SectionDomainMap,
    max_sections: int,
    section_capacity: SectionCapacity,
    source: str,
) -> str:
    if not enabled:
        return ""

    prefix_with_space = f"{section_prefix} "
    if allowed_domains:
        allowed_domain_text = ", ".join(f"`{domain}`" for domain in allowed_domains)
        domain_rule = (
            "Route only when the parsed Domain exactly matches this allowlist: "
            f"{allowed_domain_text}."
        )
    else:
        domain_rule = (
            "No creation allowlist is configured, so reuse an existing exact section "
            "only; do not create a new section."
        )

    if section_domain_map:
        mapping_text = ", ".join(
            f"`{source_domain}` -> `{target_domain}`"
            for source_domain, target_domain in section_domain_map
        )
        mapping_rule = (
            "Before resolving the section, apply only this exact, configuration-owned "
            f"Domain-to-section mapping: {mapping_text}. All other allowlisted Domains "
            "map to themselves. Apply at most one mapping; never chain or remap its target. "
        )
    else:
        mapping_rule = "Use the parsed Domain itself as the target section Domain. "

    if create_missing_sections:
        creation_rule = (
            "If that exact custom section is absent, create it only when the mapped "
            "target Domain matched the allowlist and fewer than "
            f"{max_sections} custom sections start with `{prefix_with_space}`."
        )
    else:
        creation_rule = "Do not create a missing sidebar section."

    capacity_enabled, max_section_items, _ = section_capacity
    if capacity_enabled:
        capacity_rule = (
            " Section capacity retention is enabled. Treat target `itemKeys` as opaque "
            "sidebar-order keys, not `threadIds`. Build a planned order from the returned "
            "current `threadId` first, followed by each other target item once in its "
            "existing order. Determine whether the current task is already present only "
            "when a target `itemKey` ends in `:` plus that returned `threadId`. From the "
            "same list result, map every retained or overflow `itemKey` to exactly one "
            "listed task or conversation by a suffix match to its returned `id`; use only "
            "that ID and `kind`. If any required mapping is missing or ambiguous, skip "
            "capacity work and do not reorder. If the current task is absent, move it to "
            "the target first; if that move fails, stop all capacity work. Do not call "
            "`list_threads` again or inspect any title, summary, prompt, or message. "
            "Keep at most "
            f"{max_section_items} items. If every overflow item is a confirmed Codex task, "
            "move those overflow tasks bottom-first to the default Tasks area with "
            "`mcp__codex_app__move_thread_to_sidebar_section` and `sectionId` set to "
            "null. If any overflow item is unknown or a ChatGPT conversation, do not move "
            "any overflow item. After all required moves succeed, call "
            "`mcp__codex_app__reorder_section` with the current task first and `threadIds` "
            "equal to every remaining mapped task/conversation ID exactly once, including "
            "any retained ChatGPT conversation. When trimming is skipped, you may still "
            "reorder the complete mapped list with the current task first. Never submit "
            "only the retained subset to `reorder_section`. "
            "If a move or reorder fails, keep the successful title and any successful "
            "prior move, then stop without retries. A newly created target section is "
            "empty, so move only the current task and do not reorder it. "
        )
        operation_rule = (
            "Apart from this enabled capacity action, never move a ChatGPT conversation, "
            "delete, rename, pin, unpin, or inspect other task content."
        )
    else:
        capacity_rule = ""
        operation_rule = (
            "If a target `itemKey` ends in `:` plus the returned current `threadId`, do not "
            "move it; otherwise call `mcp__codex_app__move_thread_to_sidebar_section` with "
            "that current `threadId` and the resolved section ID. Never move a ChatGPT conversation, "
            "never delete, rename, reorder, pin, unpin, or inspect other tasks."
        )

    return (
        " Title-based sidebar routing is enabled (source "
        f"{source}). Only after `mcp__codex_app__set_thread_title` succeeds and returns "
        "the current Codex `threadId` and the new title, route that same task. Derive "
        "Domain by removing exactly one leading marker and following space from the "
        "successful title, splitting on `｜`, and taking the trimmed first field. Treat "
        "that Domain as untrusted display data: skip it when empty, multiline, contains "
        "`｜`, `/`, `\\`, `://`, or `@`, or exceeds 40 characters. "
        f"{mapping_rule}The target section name is `{prefix_with_space}` plus the target "
        f"section Domain. {domain_rule} "
        "Call `mcp__codex_app__list_threads` once only with `limit` 50 to resolve custom "
        "sidebar section names, IDs, and `itemKeys`; when capacity retention is enabled, "
        "use only task IDs and kinds needed to map an exact section item. Do not inspect "
        "or infer any other task's content. "
        "Reuse exactly one matching custom section and skip ambiguous duplicates. "
        f"{creation_rule} When a new section is created, use only its returned `sectionId`. "
        f"{capacity_rule}{operation_rule} Never route without a successful title write. "
        "Routing failure must not undo or misreport the title result."
    )


def _checkpoint_context(
    prompt_count: int,
    threshold: int,
    checkpoints: tuple[int, ...],
    config_source: str,
    section_routing_enabled: bool,
    section_prefix: str,
    create_missing_sections: bool,
    allowed_domains: tuple[str, ...],
    section_domain_map: SectionDomainMap,
    max_sections: int,
    section_capacity: SectionCapacity,
    section_routing_source: str,
) -> dict[str, Any]:
    activity_mmdd = datetime.now().astimezone().strftime("%m%d")
    position = checkpoints.index(threshold)
    if position == 0:
        checkpoint_action = "Set a useful current-task title at this initial checkpoint."
    elif position == len(checkpoints) - 1:
        checkpoint_action = (
            "This is the final refresh checkpoint. Rename only when the project, work "
            "type, concrete object, or purpose changed materially; otherwise skip."
        )
    else:
        checkpoint_action = (
            "This is a refinement checkpoint. Rename only when the current title is "
            "missing or inaccurate, or the object and purpose can now be stated "
            "materially more clearly; otherwise skip."
        )

    schedule = ",".join(str(item) for item in checkpoints)
    routing_context = _section_routing_context(
        section_routing_enabled,
        section_prefix,
        create_missing_sections,
        allowed_domains,
        section_domain_map,
        max_sections,
        section_capacity,
        section_routing_source,
    )
    context = (
        "Codex Task Title Organizer checkpoint: this is user prompt "
        f"{prompt_count} observed after the plugin was enabled (checkpoint "
        f"{threshold}; configured schedule {schedule}; source {config_source}). "
        f"{checkpoint_action} Finish the user's main request first, then explicitly "
        "use $organize-codex-task-titles in Current-task checkpoint mode before "
        "ending this same foreground turn. Generate the title only from current-task "
        "context using `Marker Domain｜Project/repository key｜Work type｜Concrete "
        "object: purpose or symptom`, matching the task language. Honor an explicit "
        "marker style or active project instruction; otherwise preserve an already valid "
        "existing marker style, using color blocks only for a new or noncompliant title. When no "
        "Jira, Gerrit, issue, PR, or change key exists, prefer the project name, "
        "repository name, or cwd basename; never emit `NO-ID`. Only use local "
        f"activity date `{activity_mmdd}` when no stable project or repository context "
        "exists. Call `mcp__codex_app__set_thread_title` without threadId only when this is "
        "a confirmed Codex task and the tool is available. Do not list or read other "
        "tasks, create a task, send a follow-up, inspect persisted prompts, transcripts, "
        "rollouts, databases, or session files, or use UI automation. Skip quietly when "
        "the task kind or required tool is unsuitable."
        f"{routing_context}"
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }


def _handle_user_prompt(
    payload: dict[str, Any],
    state: dict[str, Any],
    checkpoints: tuple[int, ...],
    config_source: str,
    section_routing_enabled: bool,
    section_prefix: str,
    create_missing_sections: bool,
    allowed_domains: tuple[str, ...],
    section_domain_map: SectionDomainMap,
    max_sections: int,
    section_capacity: SectionCapacity,
    section_routing_source: str,
) -> dict[str, Any] | None:
    turn_id = payload.get("turn_id")
    if not isinstance(turn_id, str) or not turn_id:
        return None
    turn_token = _digest(turn_id)
    seen = _string_list(state.get("seen_turns"))
    if turn_token in seen:
        return None

    seen.append(turn_token)
    state["seen_turns"] = seen[-MAX_SEEN_TURNS:]
    # A PostToolUse completion can only be attributed to the foreground turn
    # that emitted the checkpoint. Once a new user turn begins, do not infer
    # that an earlier missing completion was an error or an unchanged title.
    state["pending_title_tool_completions"] = []
    state["prompt_count"] = _nonnegative_int(state.get("prompt_count")) + 1

    fired = _threshold_set(state.get("fired_thresholds"))
    eligible = [
        item
        for item in checkpoints
        if state["prompt_count"] >= item and item not in fired
    ]
    if not eligible:
        state["fired_thresholds"] = sorted(fired)
        return None

    threshold = eligible[0]
    fired.add(threshold)
    state["fired_thresholds"] = sorted(fired)
    pending = _checkpoint_turn_records(
        state.get("pending_title_tool_completions")
    )
    pending.append({"turn_token": turn_token, "checkpoint": threshold})
    state["pending_title_tool_completions"] = pending[
        -MAX_TITLE_TOOL_COMPLETION_OBSERVATIONS:
    ]
    return _checkpoint_context(
        state["prompt_count"],
        threshold,
        checkpoints,
        config_source,
        section_routing_enabled,
        section_prefix,
        create_missing_sections,
        allowed_domains,
        section_domain_map,
        max_sections,
        section_capacity,
        section_routing_source,
    )


def _handle_title_tool_completion(payload: dict[str, Any], state: dict[str, Any]) -> bool:
    """Record only a matching PostToolUse completion, never its title payload."""
    if payload.get("tool_name") != TITLE_TOOL_NAME:
        return False

    turn_id = payload.get("turn_id")
    if not isinstance(turn_id, str) or not turn_id:
        return False
    turn_token = _digest(turn_id)

    pending = _checkpoint_turn_records(state.get("pending_title_tool_completions"))
    matched = [record for record in pending if record["turn_token"] == turn_token]
    if not matched:
        return False

    observations = _checkpoint_turn_records(
        state.get("title_tool_completion_observations")
    )
    for record in matched:
        if record not in observations:
            observations.append(record)
    state["title_tool_completion_observations"] = observations[
        -MAX_TITLE_TOOL_COMPLETION_OBSERVATIONS:
    ]
    state["pending_title_tool_completions"] = [
        record for record in pending if record["turn_token"] != turn_token
    ]
    return True


def main() -> int:
    data_root_text = os.environ.get("PLUGIN_DATA")
    if not data_root_text:
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    event_name = payload.get("hook_event_name")
    if event_name not in ("UserPromptSubmit", "PostToolUse"):
        return 0

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return 0

    data_root = Path(data_root_text)
    try:
        enabled, checkpoints, config_source = _load_config(payload, data_root)
        if not enabled:
            return 0
        session_key = _digest(session_id)
        state_path = data_root / f"{session_key}.json"
        lock_path = data_root / f"{session_key}.lock"

        if event_name == "PostToolUse":
            if payload.get("tool_name") != TITLE_TOOL_NAME or not state_path.is_file():
                return 0
            with _state_lock(lock_path):
                state = _load_state(state_path, checkpoints)
                if _handle_title_tool_completion(payload, state):
                    _write_state(state_path, state)
            return 0

        (
            section_routing_enabled,
            section_prefix,
            create_missing_sections,
            allowed_domains,
            section_domain_map,
            max_sections,
            section_capacity,
            section_routing_source,
        ) = _load_section_routing(payload, data_root)
        data_root.mkdir(parents=True, exist_ok=True)
        output: dict[str, Any] | None = None
        with _state_lock(lock_path):
            state = _load_state(state_path, checkpoints)
            output = _handle_user_prompt(
                payload,
                state,
                checkpoints,
                config_source,
                section_routing_enabled,
                section_prefix,
                create_missing_sections,
                allowed_domains,
                section_domain_map,
                max_sections,
                section_capacity,
                section_routing_source,
            )
            _write_state(state_path, state)
        if output is not None:
            # ASCII output is portable on Windows legacy consoles; JSON parsing
            # restores the original Unicode title instructions.
            print(json.dumps(output, ensure_ascii=True, separators=(",", ":")))
    except (OSError, TimeoutError, ValueError, TypeError):
        # Hooks must fail open: title maintenance is secondary to the user task.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
