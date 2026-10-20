from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "codex-task-title-organizer"
SCRIPT = PLUGIN_ROOT / "scripts" / "title_turn_trigger.py"
HOOKS_CONFIG = PLUGIN_ROOT / "hooks" / "hooks.json"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"
SKILL = PLUGIN_ROOT / "skills" / "organize-codex-task-titles" / "SKILL.md"
CONFIG_REFERENCE = SKILL.parent / "references" / "configuration.md"
SECTION_ROUTING_REFERENCE = SKILL.parent / "references" / "section-routing.md"
STYLE_REFERENCE = SKILL.parent / "references" / "title-styles.md"
CHECKPOINT_ENV = "CODEX_TASK_TITLE_CHECKPOINTS"
SECTION_ROUTING_ENV = "CODEX_TASK_TITLE_SECTION_ROUTING"
TITLE_TOOL_NAME = "mcp__codex_app__set_thread_title"


def run_hook(
    data_dir: str,
    payload: dict[str, object],
    extra_env: dict[str, str] | None = None,
) -> str:
    env = os.environ.copy()
    env.pop(CHECKPOINT_ENV, None)
    env.pop(SECTION_ROUTING_ENV, None)
    env["PLUGIN_DATA"] = data_dir
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    return result.stdout.strip()


def prompt_payload(
    number: int,
    prompt: str = "secret prompt",
    *,
    session_id: str = "thr-test",
    cwd: str | None = None,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "transcript_path": "/unavailable/synthetic-transcript.jsonl",
        "turn_id": f"{session_id}-turn-{number}",
        "cwd": cwd or str(REPO_ROOT),
        "hook_event_name": "UserPromptSubmit",
        "prompt": prompt,
    }


def post_tool_payload(
    number: int,
    *,
    session_id: str = "thr-test",
    tool_name: str = TITLE_TOOL_NAME,
    title: str = "secret generated title",
    cwd: str | None = None,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "transcript_path": "/unavailable/synthetic-transcript.jsonl",
        "turn_id": f"{session_id}-turn-{number}",
        "cwd": cwd or str(REPO_ROOT),
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_use_id": "secret-tool-use-id",
        "tool_input": {"title": title},
        "tool_response": {"threadId": session_id, "title": title},
    }


def state_path_for(data_dir: str, session_id: str = "thr-test") -> Path:
    session_key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return Path(data_dir) / f"{session_key}.json"


def write_project_config(project_root: str, payload: dict[str, object]) -> None:
    config_dir = Path(project_root) / ".codex"
    config_dir.mkdir()
    (config_dir / "task-title-organizer.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


class TitleTurnTriggerTests(unittest.TestCase):
    def test_subagent_events_do_not_create_state(self) -> None:
        for identity in ({"agent_id": "child-agent"}, {"agent_type": "explorer"}):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as data_dir:
                for payload in (prompt_payload(1), prompt_payload(2), post_tool_payload(2)):
                    payload.update(identity)
                    self.assertEqual(run_hook(data_dir, payload), "")
                    self.assertEqual(list(Path(data_dir).iterdir()), [])

    def test_subagent_events_leave_preexisting_state_unchanged(self) -> None:
        for payload in (prompt_payload(3), post_tool_payload(2)):
            with self.subTest(event=payload["hook_event_name"]), tempfile.TemporaryDirectory() as data_dir:
                run_hook(data_dir, prompt_payload(1))
                run_hook(data_dir, prompt_payload(2))
                before = state_path_for(data_dir).read_bytes()
                payload.update(agent_id="child-agent", agent_type="default")
                self.assertEqual(run_hook(data_dir, payload), "")
                self.assertEqual(state_path_for(data_dir).read_bytes(), before)

    def test_ephemeral_events_do_not_create_state(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            for payload in (prompt_payload(1), prompt_payload(2), post_tool_payload(2)):
                payload["transcript_path"] = None
                self.assertEqual(run_hook(data_dir, payload), "")
                self.assertEqual(list(Path(data_dir).iterdir()), [])

    def test_ephemeral_events_leave_preexisting_state_unchanged(self) -> None:
        for payload in (prompt_payload(3), post_tool_payload(2)):
            with self.subTest(event=payload["hook_event_name"]), tempfile.TemporaryDirectory() as data_dir:
                # Older versions could start title maintenance in side chats.
                run_hook(data_dir, prompt_payload(1))
                run_hook(data_dir, prompt_payload(2))
                before = state_path_for(data_dir).read_bytes()
                payload["transcript_path"] = None
                self.assertEqual(run_hook(data_dir, payload), "")
                self.assertEqual(state_path_for(data_dir).read_bytes(), before)

    def test_events_without_transcript_metadata_skip_title_maintenance(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            for payload in (prompt_payload(1), prompt_payload(2), post_tool_payload(2)):
                del payload["transcript_path"]
                self.assertEqual(run_hook(data_dir, payload), "")
                self.assertEqual(list(Path(data_dir).iterdir()), [])

    def test_packaged_hook_command_runs(self) -> None:
        config = json.loads(HOOKS_CONFIG.read_text(encoding="utf-8"))
        handler = config["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        command = handler["commandWindows"] if os.name == "nt" else handler["command"]
        post_handler = config["hooks"]["PostToolUse"][0]["hooks"][0]
        post_command = (
            post_handler["commandWindows"]
            if os.name == "nt"
            else post_handler["command"]
        )
        with tempfile.TemporaryDirectory() as data_dir:
            env = os.environ.copy()
            env.pop(CHECKPOINT_ENV, None)
            env.pop(SECTION_ROUTING_ENV, None)
            env["PLUGIN_ROOT"] = str(PLUGIN_ROOT)
            env["PLUGIN_DATA"] = data_dir
            output = ""
            for number in range(1, 3):
                result = subprocess.run(
                    command,
                    input=json.dumps(prompt_payload(number)),
                    text=True,
                    capture_output=True,
                    env=env,
                    shell=True,
                    check=True,
                )
                output = result.stdout.strip()
            parsed = json.loads(output)
            self.assertIn(
                "user prompt 2",
                parsed["hookSpecificOutput"]["additionalContext"],
            )
            result = subprocess.run(
                post_command,
                input=json.dumps(post_tool_payload(2)),
                text=True,
                capture_output=True,
                env=env,
                shell=True,
                check=True,
            )
            self.assertEqual(result.stdout.strip(), "")
            state = json.loads(state_path_for(data_dir).read_text(encoding="utf-8"))
            self.assertEqual(
                state["title_tool_completion_observations"],
                [
                    {
                        "checkpoint": 2,
                        "turn_token": hashlib.sha256(
                            b"thr-test-turn-2"
                        ).hexdigest(),
                    }
                ],
            )

    def test_default_thresholds_deduplication_and_content_privacy(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            self.assertEqual(run_hook(data_dir, prompt_payload(1)), "")

            first = json.loads(run_hook(data_dir, prompt_payload(2)))
            first_context = first["hookSpecificOutput"]["additionalContext"]
            self.assertIn("user prompt 2", first_context)
            self.assertIn("initial checkpoint", first_context)
            self.assertIn("configured schedule 2,4,10", first_context)
            self.assertIn(
                "preserve an already valid existing marker style",
                first_context,
            )
            self.assertNotIn("Title-based sidebar routing is enabled", first_context)
            self.assertEqual(run_hook(data_dir, prompt_payload(2)), "")

            self.assertEqual(run_hook(data_dir, prompt_payload(3)), "")
            second = json.loads(run_hook(data_dir, prompt_payload(4)))
            second_context = second["hookSpecificOutput"]["additionalContext"]
            self.assertIn("refinement checkpoint", second_context)
            self.assertIn("materially more clearly", second_context)

            for number in range(5, 10):
                self.assertEqual(run_hook(data_dir, prompt_payload(number)), "")

            third = json.loads(run_hook(data_dir, prompt_payload(10)))
            third_context = third["hookSpecificOutput"]["additionalContext"]
            self.assertIn("final refresh checkpoint", third_context)
            self.assertIn("changed materially", third_context)
            self.assertEqual(run_hook(data_dir, prompt_payload(11)), "")

            state_text = state_path_for(data_dir).read_text(encoding="utf-8")
            state = json.loads(state_text)
            self.assertEqual(
                set(state),
                {
                    "schema_version",
                    "prompt_count",
                    "seen_turns",
                    "fired_thresholds",
                    "checkpoint_signature",
                    "pending_title_tool_completions",
                    "title_tool_completion_observations",
                },
            )
            self.assertEqual(state["schema_version"], 5)
            self.assertEqual(state["checkpoint_signature"], [2, 4, 10])
            self.assertEqual(state["fired_thresholds"], [2, 4, 10])
            self.assertEqual(state["pending_title_tool_completions"], [])
            self.assertEqual(state["title_tool_completion_observations"], [])
            self.assertNotIn("secret prompt", state_text)
            self.assertNotIn("thr-test", state_text)
            self.assertNotIn("turn-2", state_text)
            self.assertNotIn(str(REPO_ROOT), state_text)
            self.assertNotIn("section", state_text)

    def test_matching_post_tool_use_observes_completion_without_title_data(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            self.assertEqual(run_hook(data_dir, prompt_payload(1)), "")
            self.assertTrue(run_hook(data_dir, prompt_payload(2)))

            state = json.loads(state_path_for(data_dir).read_text(encoding="utf-8"))
            expected = {
                "checkpoint": 2,
                "turn_token": hashlib.sha256(b"thr-test-turn-2").hexdigest(),
            }
            self.assertEqual(state["pending_title_tool_completions"], [expected])
            self.assertEqual(state["title_tool_completion_observations"], [])

            payload = post_tool_payload(2, title="secret title from tool payload")
            self.assertEqual(run_hook(data_dir, payload), "")
            self.assertEqual(run_hook(data_dir, payload), "")

            state_text = state_path_for(data_dir).read_text(encoding="utf-8")
            state = json.loads(state_text)
            self.assertEqual(state["prompt_count"], 2)
            self.assertEqual(state["fired_thresholds"], [2])
            self.assertEqual(state["pending_title_tool_completions"], [])
            self.assertEqual(state["title_tool_completion_observations"], [expected])
            self.assertNotIn("secret title from tool payload", state_text)
            self.assertNotIn("secret-tool-use-id", state_text)
            self.assertNotIn("thr-test", state_text)

    def test_missing_post_tool_completion_is_not_recorded_as_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            self.assertEqual(run_hook(data_dir, prompt_payload(1)), "")
            self.assertTrue(run_hook(data_dir, prompt_payload(2)))
            self.assertEqual(run_hook(data_dir, prompt_payload(3)), "")

            state = json.loads(state_path_for(data_dir).read_text(encoding="utf-8"))
            self.assertEqual(state["pending_title_tool_completions"], [])
            self.assertEqual(state["title_tool_completion_observations"], [])

    def test_nonmatching_post_tool_use_does_not_create_or_change_state(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            self.assertEqual(
                run_hook(data_dir, post_tool_payload(2, tool_name="Bash")), ""
            )
            self.assertEqual(list(Path(data_dir).iterdir()), [])

            self.assertEqual(run_hook(data_dir, prompt_payload(1)), "")
            self.assertTrue(run_hook(data_dir, prompt_payload(2)))
            before = state_path_for(data_dir).read_text(encoding="utf-8")
            self.assertEqual(
                run_hook(data_dir, post_tool_payload(2, tool_name="Bash")), ""
            )
            self.assertEqual(state_path_for(data_dir).read_text(encoding="utf-8"), before)

    def test_section_routing_project_configuration_and_state_privacy(self) -> None:
        with (
            tempfile.TemporaryDirectory() as data_dir,
            tempfile.TemporaryDirectory() as project_root,
        ):
            write_project_config(
                project_root,
                {
                    "enabled": True,
                    "checkpoints": [1],
                    "sectionRouting": {
                        "enabled": True,
                        "sectionPrefix": "🗂️",
                        "createMissingSections": True,
                        "allowedDomains": ["Backend", "Mobile"],
                        "sectionDomainMap": {"Mobile": "Backend"},
                        "maxSections": 3,
                    },
                },
            )
            context = json.loads(
                run_hook(data_dir, prompt_payload(1, cwd=project_root))
            )["hookSpecificOutput"]["additionalContext"]

            self.assertIn(
                "Title-based sidebar routing is enabled (source project)",
                context,
            )
            self.assertIn("`Backend`, `Mobile`", context)
            self.assertIn("`Mobile` -> `Backend`", context)
            self.assertIn("target section Domain", context)
            self.assertIn("fewer than 3 custom sections start with `🗂️ `", context)
            self.assertIn("current Codex `threadId`", context)
            self.assertIn("Never move a ChatGPT conversation", context)
            self.assertNotIn("Section capacity retention is enabled", context)
            self.assertNotIn("`mcp__codex_app__reorder_section`", context)

            state_text = state_path_for(data_dir).read_text(encoding="utf-8")
            self.assertNotIn("Backend", state_text)
            self.assertNotIn("Mobile", state_text)
            self.assertNotIn("sectionPrefix", state_text)

    def test_section_capacity_retention_is_bounded_and_private(self) -> None:
        with (
            tempfile.TemporaryDirectory() as data_dir,
            tempfile.TemporaryDirectory() as project_root,
        ):
            write_project_config(
                project_root,
                {
                    "enabled": True,
                    "checkpoints": [1],
                    "sectionRouting": {
                        "enabled": True,
                        "allowedDomains": ["Backend"],
                        "sectionCapacity": {
                            "enabled": True,
                            "maxItems": 10,
                            "overflowDestination": "default",
                        },
                    },
                },
            )
            context = json.loads(
                run_hook(data_dir, prompt_payload(1, cwd=project_root))
            )["hookSpecificOutput"]["additionalContext"]

            self.assertIn("Section capacity retention is enabled", context)
            self.assertIn("Keep at most 10 items", context)
            self.assertIn("`mcp__codex_app__reorder_section`", context)
            self.assertIn("`sectionId` set to null", context)
            self.assertIn("Never submit only the retained subset", context)
            self.assertIn("Do not call `list_threads` again or inspect any title", context)
            self.assertIn("never move a ChatGPT conversation", context)
            self.assertIn("Treat target `itemKeys` as opaque sidebar-order keys", context)
            self.assertIn("map every retained or overflow `itemKey`", context)
            self.assertIn("`limit` 50", context)

            state_text = state_path_for(data_dir).read_text(encoding="utf-8")
            self.assertNotIn("Backend", state_text)
            self.assertNotIn("sectionCapacity", state_text)
            self.assertNotIn("overflowDestination", state_text)

    def test_section_domain_map_requires_allowlisted_safe_values(self) -> None:
        environment = {
            CHECKPOINT_ENV: "1",
            SECTION_ROUTING_ENV: "domain",
        }
        with (
            tempfile.TemporaryDirectory() as data_dir,
            tempfile.TemporaryDirectory() as project_root,
        ):
            write_project_config(
                project_root,
                {
                    "enabled": True,
                    "checkpoints": [1],
                    "sectionRouting": {
                        "enabled": True,
                        "allowedDomains": ["Backend"],
                        "sectionDomainMap": {"Mobile": "Backend"},
                    },
                },
            )
            context = json.loads(
                run_hook(
                    data_dir,
                    prompt_payload(1, cwd=project_root),
                    environment,
                )
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn(
                "Title-based sidebar routing is enabled (source environment)",
                context,
            )

        for invalid_map in (
            {" Mobile": "Backend", "Mobile": "Infra"},
            {"Mobile": "Backend", "Backend": "Infra"},
        ):
            with (
                tempfile.TemporaryDirectory() as data_dir,
                tempfile.TemporaryDirectory() as project_root,
            ):
                write_project_config(
                    project_root,
                    {
                        "enabled": True,
                        "checkpoints": [1],
                        "sectionRouting": {
                            "enabled": True,
                            "allowedDomains": ["Backend", "Mobile", "Infra"],
                            "sectionDomainMap": invalid_map,
                        },
                    },
                )
                context = json.loads(
                    run_hook(
                        data_dir,
                        prompt_payload(1, cwd=project_root),
                        environment,
                    )
                )["hookSpecificOutput"]["additionalContext"]
                self.assertIn(
                    "Title-based sidebar routing is enabled (source environment)",
                    context,
                )
                self.assertNotIn("Domain-to-section mapping", context)
            self.assertNotIn("`Mobile` -> `Backend`", context)

        with (
            tempfile.TemporaryDirectory() as data_dir,
            tempfile.TemporaryDirectory() as project_root,
        ):
            write_project_config(
                project_root,
                {
                    "enabled": True,
                    "checkpoints": [1],
                    "sectionRouting": {
                        "enabled": True,
                        "allowedDomains": ["Backend", "Mobile"],
                        "sectionDomainMap": {"Mobile": "unsafe/domain"},
                    },
                },
            )
            context = json.loads(
                run_hook(
                    data_dir,
                    prompt_payload(1, cwd=project_root),
                    environment,
                )
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn(
                "Title-based sidebar routing is enabled (source environment)",
                context,
            )

    def test_invalid_section_capacity_falls_through_to_environment(self) -> None:
        environment = {
            CHECKPOINT_ENV: "1",
            SECTION_ROUTING_ENV: "domain",
        }
        for capacity in (
            {"enabled": True, "maxItems": 0, "overflowDestination": "default"},
            {"enabled": True, "maxItems": 51, "overflowDestination": "default"},
            {"enabled": True, "maxItems": True, "overflowDestination": "default"},
            {"enabled": True, "maxItems": 10, "overflowDestination": "archive"},
            [],
        ):
            with (
                tempfile.TemporaryDirectory() as data_dir,
                tempfile.TemporaryDirectory() as project_root,
            ):
                write_project_config(
                    project_root,
                    {
                        "enabled": True,
                        "checkpoints": [1],
                        "sectionRouting": {
                            "enabled": True,
                            "allowedDomains": ["Backend"],
                            "sectionCapacity": capacity,
                        },
                    },
                )
                context = json.loads(
                    run_hook(
                        data_dir,
                        prompt_payload(1, cwd=project_root),
                        environment,
                    )
                )["hookSpecificOutput"]["additionalContext"]
                self.assertIn(
                    "Title-based sidebar routing is enabled (source environment)",
                    context,
                )
                self.assertNotIn("Section capacity retention is enabled", context)

    def test_section_routing_environment_and_invalid_project_fallback(self) -> None:
        environment = {
            CHECKPOINT_ENV: "1",
            SECTION_ROUTING_ENV: "domain",
        }
        with tempfile.TemporaryDirectory() as data_dir:
            context = json.loads(
                run_hook(data_dir, prompt_payload(1), environment)
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn(
                "Title-based sidebar routing is enabled (source environment)",
                context,
            )
            self.assertIn("No creation allowlist is configured", context)
            self.assertIn("Do not create a missing sidebar section", context)

        with (
            tempfile.TemporaryDirectory() as data_dir,
            tempfile.TemporaryDirectory() as project_root,
        ):
            write_project_config(
                project_root,
                {
                    "enabled": True,
                    "checkpoints": [1],
                    "sectionRouting": {
                        "enabled": True,
                        "createMissingSections": True,
                        "allowedDomains": ["unsafe/domain"],
                    },
                },
            )
            context = json.loads(
                run_hook(
                    data_dir,
                    prompt_payload(1, cwd=project_root),
                    environment,
                )
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn(
                "Title-based sidebar routing is enabled (source environment)",
                context,
            )
            self.assertIn("Do not create a missing sidebar section", context)

    def test_section_routing_project_disable_overrides_environment(self) -> None:
        environment = {
            CHECKPOINT_ENV: "1",
            SECTION_ROUTING_ENV: "domain",
        }
        with (
            tempfile.TemporaryDirectory() as data_dir,
            tempfile.TemporaryDirectory() as project_root,
        ):
            write_project_config(
                project_root,
                {
                    "enabled": True,
                    "checkpoints": [1],
                    "sectionRouting": {"enabled": False},
                },
            )
            context = json.loads(
                run_hook(
                    data_dir,
                    prompt_payload(1, cwd=project_root),
                    environment,
                )
            )["hookSpecificOutput"]["additionalContext"]
            self.assertNotIn("Title-based sidebar routing is enabled", context)

    def test_environment_configuration(self) -> None:
        custom_env = {CHECKPOINT_ENV: "1,3,5"}
        with tempfile.TemporaryDirectory() as data_dir:
            first = json.loads(
                run_hook(data_dir, prompt_payload(1), custom_env)
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn("initial checkpoint", first)
            self.assertIn("configured schedule 1,3,5", first)
            self.assertIn("source environment", first)
            self.assertEqual(run_hook(data_dir, prompt_payload(2), custom_env), "")
            middle = json.loads(
                run_hook(data_dir, prompt_payload(3), custom_env)
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn("refinement checkpoint", middle)
            self.assertEqual(run_hook(data_dir, prompt_payload(4), custom_env), "")
            final = json.loads(
                run_hook(data_dir, prompt_payload(5), custom_env)
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn("final refresh checkpoint", final)

    def test_project_configuration_overrides_environment(self) -> None:
        with (
            tempfile.TemporaryDirectory() as data_dir,
            tempfile.TemporaryDirectory() as project_root,
        ):
            write_project_config(
                project_root, {"enabled": True, "checkpoints": [2, 6]}
            )
            custom_env = {CHECKPOINT_ENV: "1,3"}
            self.assertEqual(
                run_hook(
                    data_dir,
                    prompt_payload(1, cwd=project_root),
                    custom_env,
                ),
                "",
            )
            first = json.loads(
                run_hook(
                    data_dir,
                    prompt_payload(2, cwd=project_root),
                    custom_env,
                )
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn("configured schedule 2,6", first)
            self.assertIn("source project", first)
            for number in range(3, 6):
                self.assertEqual(
                    run_hook(
                        data_dir,
                        prompt_payload(number, cwd=project_root),
                        custom_env,
                    ),
                    "",
                )
            final = json.loads(
                run_hook(
                    data_dir,
                    prompt_payload(6, cwd=project_root),
                    custom_env,
                )
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn("final refresh checkpoint", final)

    def test_plugin_data_configuration_and_project_disable(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            (Path(data_dir) / "config.json").write_text(
                json.dumps({"enabled": True, "checkpoints": [1, 2]}),
                encoding="utf-8",
            )
            first = json.loads(run_hook(data_dir, prompt_payload(1)))[
                "hookSpecificOutput"
            ]["additionalContext"]
            self.assertIn("source plugin-data", first)
            final = json.loads(run_hook(data_dir, prompt_payload(2)))[
                "hookSpecificOutput"
            ]["additionalContext"]
            self.assertIn("final refresh checkpoint", final)

        with (
            tempfile.TemporaryDirectory() as data_dir,
            tempfile.TemporaryDirectory() as project_root,
        ):
            write_project_config(project_root, {"enabled": False})
            self.assertEqual(
                run_hook(data_dir, prompt_payload(1, cwd=project_root)),
                "",
            )
            self.assertEqual(list(Path(data_dir).iterdir()), [])

    def test_invalid_project_config_falls_through_to_environment(self) -> None:
        with (
            tempfile.TemporaryDirectory() as data_dir,
            tempfile.TemporaryDirectory() as project_root,
        ):
            write_project_config(
                project_root, {"enabled": True, "checkpoints": [2, 2]}
            )
            custom_env = {CHECKPOINT_ENV: "3,7"}
            for number in range(1, 3):
                self.assertEqual(
                    run_hook(
                        data_dir,
                        prompt_payload(number, cwd=project_root),
                        custom_env,
                    ),
                    "",
                )
            output = json.loads(
                run_hook(
                    data_dir,
                    prompt_payload(3, cwd=project_root),
                    custom_env,
                )
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn("source environment", output)
            self.assertIn("configured schedule 3,7", output)

    def test_migrates_v2_v3_and_v4_state_without_replaying_past_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            state_path = state_path_for(data_dir)
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "prompt_count": 6,
                        "seen_turns": [
                            hashlib.sha256(b"thr-test-turn-6").hexdigest()
                        ],
                        "fired_thresholds": [4],
                        "successful_updates": 0,
                        "pending_threshold": 4,
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(run_hook(data_dir, prompt_payload(7)), "")
            migrated = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], 5)
            self.assertEqual(migrated["prompt_count"], 7)
            self.assertEqual(migrated["checkpoint_signature"], [2, 4, 10])
            self.assertEqual(migrated["fired_thresholds"], [2, 4])
            self.assertNotIn("successful_updates", migrated)
            self.assertEqual(migrated["pending_title_tool_completions"], [])
            self.assertEqual(migrated["title_tool_completion_observations"], [])

            self.assertEqual(run_hook(data_dir, prompt_payload(8)), "")
            self.assertEqual(run_hook(data_dir, prompt_payload(9)), "")
            refresh = json.loads(run_hook(data_dir, prompt_payload(10)))
            self.assertIn(
                "final refresh checkpoint",
                refresh["hookSpecificOutput"]["additionalContext"],
            )

        with tempfile.TemporaryDirectory() as data_dir:
            state_path = state_path_for(data_dir)
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "prompt_count": 3,
                        "seen_turns": [],
                        "fired_thresholds": [],
                    }
                ),
                encoding="utf-8",
            )
            refinement = json.loads(run_hook(data_dir, prompt_payload(4)))
            self.assertIn(
                "refinement checkpoint",
                refinement["hookSpecificOutput"]["additionalContext"],
            )
            migrated = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["fired_thresholds"], [2, 4])

        with tempfile.TemporaryDirectory() as data_dir:
            state_path = state_path_for(data_dir)
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 4,
                        "prompt_count": 6,
                        "seen_turns": [],
                        "fired_thresholds": [2, 4],
                        "checkpoint_signature": [2, 4, 10],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(run_hook(data_dir, prompt_payload(7)), "")
            migrated = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], 5)
            self.assertEqual(migrated["fired_thresholds"], [2, 4])
            self.assertEqual(migrated["pending_title_tool_completions"], [])
            self.assertEqual(migrated["title_tool_completion_observations"], [])

    def test_schedule_change_does_not_replay_past_checkpoints(self) -> None:
        with (
            tempfile.TemporaryDirectory() as data_dir,
            tempfile.TemporaryDirectory() as project_root,
        ):
            for number in range(1, 6):
                run_hook(data_dir, prompt_payload(number, cwd=project_root))

            write_project_config(
                project_root, {"enabled": True, "checkpoints": [1, 3, 8]}
            )
            self.assertEqual(
                run_hook(data_dir, prompt_payload(6, cwd=project_root)),
                "",
            )
            self.assertEqual(
                run_hook(data_dir, prompt_payload(7, cwd=project_root)),
                "",
            )
            output = json.loads(
                run_hook(data_dir, prompt_payload(8, cwd=project_root))
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn("configured schedule 1,3,8", output)
            self.assertIn("final refresh checkpoint", output)

            state = json.loads(state_path_for(data_dir).read_text(encoding="utf-8"))
            self.assertEqual(state["checkpoint_signature"], [1, 3, 8])
            self.assertEqual(state["fired_thresholds"], [1, 2, 3, 4, 8])

    def test_corrupt_and_wrong_shaped_state_fail_open(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            state_path = state_path_for(data_dir)
            state_path.write_text("{broken", encoding="utf-8")
            self.assertEqual(run_hook(data_dir, prompt_payload(1)), "")
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 4,
                        "prompt_count": "bad",
                        "seen_turns": "not-a-list",
                        "fired_thresholds": {"bad": True},
                        "checkpoint_signature": "bad",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(run_hook(data_dir, prompt_payload(2)), "")
            output = json.loads(run_hook(data_dir, prompt_payload(3)))
            self.assertIn(
                "initial checkpoint",
                output["hookSpecificOutput"]["additionalContext"],
            )

    def test_non_prompt_events_do_not_create_state(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            payload = prompt_payload(1)
            payload["hook_event_name"] = "Stop"
            self.assertEqual(run_hook(data_dir, payload), "")
            self.assertEqual(list(Path(data_dir).iterdir()), [])

    def test_concurrent_unique_turns_are_not_lost(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                outputs = list(
                    pool.map(
                        lambda number: run_hook(data_dir, prompt_payload(number)),
                        range(1, 17),
                    )
                )
            contexts = [
                json.loads(output)["hookSpecificOutput"]["additionalContext"]
                for output in outputs
                if output
            ]
            self.assertEqual(len(contexts), 3)
            state = json.loads(
                state_path_for(data_dir).read_text(encoding="utf-8")
            )
            self.assertEqual(state["prompt_count"], 16)
            self.assertEqual(state["fired_thresholds"], [2, 4, 10])

    def test_package_manifests_and_hook_layout(self) -> None:
        plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        hooks = json.loads(HOOKS_CONFIG.read_text(encoding="utf-8"))

        self.assertEqual(plugin["name"], "codex-task-title-organizer")
        self.assertEqual(plugin["version"].split("+", 1)[0], "0.5.0")
        self.assertLessEqual(len(plugin["interface"]["defaultPrompt"]), 3)
        self.assertNotIn("hooks", plugin)
        self.assertEqual(set(hooks["hooks"]), {"UserPromptSubmit", "PostToolUse"})
        self.assertIn("2, 4, and 10", hooks["description"])
        post_hook = hooks["hooks"]["PostToolUse"]
        self.assertEqual(len(post_hook), 1)
        self.assertEqual(post_hook[0]["matcher"], "^mcp__codex_app__set_thread_title$")
        self.assertEqual(len(post_hook[0]["hooks"]), 1)
        self.assertEqual(post_hook[0]["hooks"][0]["type"], "command")
        self.assertEqual(marketplace["name"], "codex-task-title-organizer")
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], plugin["name"])
        source = (REPO_ROOT / entry["source"]["path"]).resolve()
        self.assertEqual(source, PLUGIN_ROOT.resolve())
        self.assertTrue((source / ".codex-plugin" / "plugin.json").is_file())

    def test_skill_and_configuration_reference(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        config_text = CONFIG_REFERENCE.read_text(encoding="utf-8")
        section_routing_text = SECTION_ROUTING_REFERENCE.read_text(encoding="utf-8")
        style_text = STYLE_REFERENCE.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: organize-codex-task-titles\n"))
        self.assertIn(
            "project name, repository name, or only the basename",
            text,
        )
        self.assertIn("Modify at most 10 tasks per batch", text)
        self.assertIn("references/configuration.md", text)
        self.assertIn("references/section-routing.md", text)
        self.assertIn("references/title-styles.md", text)
        self.assertIn("task-title-organizer.json", config_text)
        self.assertIn("default", config_text)
        self.assertIn("2,4,10", config_text)
        self.assertIn("CODEX_TASK_TITLE_SECTION_ROUTING", config_text)
        self.assertIn("allowedDomains", section_routing_text)
        self.assertIn("sectionCapacity", section_routing_text)
        self.assertIn("overflowDestination", section_routing_text)
        self.assertIn("reorder_section", section_routing_text)
        self.assertIn("never creates one", section_routing_text)
        self.assertIn("Color blocks (default)", style_text)
        self.assertIn("Semantic icons", style_text)
        self.assertIn("Custom styles", style_text)
        self.assertIn("exactly one leading marker", style_text)

    def test_public_files_avoid_obvious_sensitive_data(self) -> None:
        patterns = {
            "absolute user home": re.compile(
                r"(?:[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+|/(?:Users|home)/[^/\s]+)",
                re.IGNORECASE,
            ),
            "email address": re.compile(
                r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
                re.IGNORECASE,
            ),
            "credential-like token": re.compile(
                r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})",
                re.IGNORECASE,
            ),
            "private key": re.compile(
                r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
            ),
        }
        findings: list[str] = []
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for label, pattern in patterns.items():
                if pattern.search(content):
                    findings.append(f"{path.relative_to(REPO_ROOT)}: {label}")
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
