#!/usr/bin/env python3
"""Emit configurable title-maintenance context without reading prompt text."""

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
PROJECT_CONFIG_RELATIVE = Path(".codex") / "task-title-organizer.json"
PLUGIN_DATA_CONFIG_NAME = "config.json"
MAX_CONFIG_BYTES = 16 * 1024
MAX_CHECKPOINTS = 8
MAX_CHECKPOINT_VALUE = 50
MAX_SEEN_TURNS = 64
SCHEMA_VERSION = 4


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


def _read_config_file(path: Path, source: str) -> tuple[bool, tuple[int, ...], str] | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return _parse_config(payload, source)


def _load_config(
    payload: dict[str, Any], data_root: Path
) -> tuple[bool, tuple[int, ...], str]:
    cwd_text = payload.get("cwd")
    if isinstance(cwd_text, str) and cwd_text:
        cwd = Path(cwd_text)
        if cwd.is_absolute():
            project = _read_config_file(cwd / PROJECT_CONFIG_RELATIVE, "project")
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


def _default_state(checkpoints: tuple[int, ...]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_count": 0,
        "seen_turns": [],
        "fired_thresholds": [],
        "checkpoint_signature": list(checkpoints),
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


def _load_state(path: Path, checkpoints: tuple[int, ...]) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, UnicodeError):
        return _default_state(checkpoints)
    if not isinstance(loaded, dict) or loaded.get("schema_version") not in (2, 3, 4):
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


def _checkpoint_context(
    prompt_count: int,
    threshold: int,
    checkpoints: tuple[int, ...],
    config_source: str,
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
        "exists. Call `codex_app__set_thread_title` without threadId only when this is "
        "a confirmed Codex task and the tool is available. Do not list or read other "
        "tasks, create a task, send a follow-up, inspect persisted prompts, transcripts, "
        "rollouts, databases, or session files, or use UI automation. Skip quietly when "
        "the task kind or required tool is unsuitable."
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
    return _checkpoint_context(
        state["prompt_count"], threshold, checkpoints, config_source
    )


def main() -> int:
    data_root_text = os.environ.get("PLUGIN_DATA")
    if not data_root_text:
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "UserPromptSubmit":
        return 0

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return 0

    data_root = Path(data_root_text)
    try:
        enabled, checkpoints, config_source = _load_config(payload, data_root)
        if not enabled:
            return 0
        data_root.mkdir(parents=True, exist_ok=True)
        session_key = _digest(session_id)
        state_path = data_root / f"{session_key}.json"
        lock_path = data_root / f"{session_key}.lock"
        output: dict[str, Any] | None = None
        with _state_lock(lock_path):
            state = _load_state(state_path, checkpoints)
            output = _handle_user_prompt(
                payload, state, checkpoints, config_source
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
