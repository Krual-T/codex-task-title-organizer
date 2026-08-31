#!/usr/bin/env python3
"""Emit title-maintenance context without reading prompt text or transcripts."""

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


TRIGGERS = (4, 10)
MAX_SEEN_TURNS = 64
SCHEMA_VERSION = 3


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _default_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_count": 0,
        "seen_turns": [],
        "fired_thresholds": [],
    }


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _threshold_set(value: Any) -> set[int]:
    if not isinstance(value, list):
        return set()
    parsed = {
        int(item)
        for item in value
        if isinstance(item, int) or (isinstance(item, str) and item.isdigit())
    }
    return parsed.intersection(TRIGGERS)


def _load_state(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(loaded, dict) or loaded.get("schema_version") not in (2, 3):
        return _default_state()

    # Schema 2 recorded tool receipts. Some runtimes do not emit nested-tool
    # lifecycle events, so schema 3 keeps counters and drops receipt-only data.
    state = _default_state()
    state["prompt_count"] = _nonnegative_int(loaded.get("prompt_count"))
    state["seen_turns"] = _string_list(loaded.get("seen_turns"))[-MAX_SEEN_TURNS:]
    state["fired_thresholds"] = sorted(
        _threshold_set(loaded.get("fired_thresholds"))
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


def _checkpoint_context(prompt_count: int, threshold: int) -> dict[str, Any]:
    activity_mmdd = datetime.now().astimezone().strftime("%m%d")
    if threshold == TRIGGERS[0]:
        checkpoint_action = "Set a useful current-task title at this first checkpoint."
    else:
        checkpoint_action = (
            "This is a refresh checkpoint. Rename only when the current object or "
            "purpose changed materially since the earlier checkpoint; otherwise skip."
        )

    context = (
        "Codex Task Title Organizer checkpoint: this is user prompt "
        f"{prompt_count} observed after the plugin was enabled (checkpoint "
        f"{threshold}). {checkpoint_action} Finish the user's main request first, "
        "then explicitly use $organize-codex-task-titles in Current-task checkpoint "
        "mode before ending this same foreground turn. Generate the title only from "
        "current-task context using `Colored emoji Domain｜Project/repository key｜"
        "Work type｜Concrete object: purpose or symptom`, matching the task language. "
        "When no Jira, Gerrit, issue, PR, or change key exists, prefer the project "
        "name, repository name, or cwd basename; never emit `NO-ID`. Only use local "
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
    payload: dict[str, Any], state: dict[str, Any]
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
        for item in TRIGGERS
        if state["prompt_count"] >= item and item not in fired
    ]
    if not eligible:
        state["fired_thresholds"] = sorted(fired)
        return None

    threshold = eligible[0]
    fired.add(threshold)
    state["fired_thresholds"] = sorted(fired)
    return _checkpoint_context(state["prompt_count"], threshold)


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
        data_root.mkdir(parents=True, exist_ok=True)
        session_key = _digest(session_id)
        state_path = data_root / f"{session_key}.json"
        lock_path = data_root / f"{session_key}.lock"
        output: dict[str, Any] | None = None
        with _state_lock(lock_path):
            state = _load_state(state_path)
            output = _handle_user_prompt(payload, state)
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
