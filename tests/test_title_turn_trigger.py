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


def run_hook(data_dir: str, payload: dict[str, object]) -> str:
    env = os.environ.copy()
    env["PLUGIN_DATA"] = data_dir
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    return result.stdout.strip()


def prompt_payload(number: int, prompt: str = "secret prompt") -> dict[str, object]:
    return {
        "session_id": "thr-test",
        "turn_id": f"turn-{number}",
        "cwd": "workspace/project-alpha",
        "hook_event_name": "UserPromptSubmit",
        "prompt": prompt,
    }


class TitleTurnTriggerTests(unittest.TestCase):
    def test_packaged_hook_command_runs(self) -> None:
        config = json.loads(HOOKS_CONFIG.read_text(encoding="utf-8"))
        handler = config["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        command = handler["commandWindows"] if os.name == "nt" else handler["command"]
        with tempfile.TemporaryDirectory() as data_dir:
            env = os.environ.copy()
            env["PLUGIN_ROOT"] = str(PLUGIN_ROOT)
            env["PLUGIN_DATA"] = data_dir
            output = ""
            for number in range(1, 5):
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
            self.assertIn("user prompt 4", parsed["hookSpecificOutput"]["additionalContext"])

    def test_thresholds_deduplication_and_content_privacy(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            for number in range(1, 4):
                self.assertEqual(run_hook(data_dir, prompt_payload(number)), "")

            first = json.loads(run_hook(data_dir, prompt_payload(4)))
            first_context = first["hookSpecificOutput"]["additionalContext"]
            self.assertIn("user prompt 4", first_context)
            self.assertIn("Current-task checkpoint mode", first_context)
            self.assertIn("project name, repository name, or cwd basename", first_context)
            self.assertEqual(run_hook(data_dir, prompt_payload(4)), "")

            for number in range(5, 10):
                self.assertEqual(run_hook(data_dir, prompt_payload(number)), "")

            second = json.loads(run_hook(data_dir, prompt_payload(10)))
            second_context = second["hookSpecificOutput"]["additionalContext"]
            self.assertIn("refresh checkpoint", second_context)
            self.assertIn("changed materially", second_context)
            for number in range(11, 14):
                self.assertEqual(run_hook(data_dir, prompt_payload(number)), "")

            state_paths = list(Path(data_dir).glob("*.json"))
            self.assertEqual(len(state_paths), 1)
            state_text = state_paths[0].read_text(encoding="utf-8")
            state = json.loads(state_text)
            self.assertEqual(
                set(state),
                {"schema_version", "prompt_count", "seen_turns", "fired_thresholds"},
            )
            self.assertEqual(state["schema_version"], 3)
            self.assertNotIn("secret prompt", state_text)
            self.assertNotIn("thr-test", state_text)
            self.assertNotIn("turn-4", state_text)

    def test_migrates_v2_state_without_replaying_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            session_key = hashlib.sha256(b"thr-test").hexdigest()
            state_path = Path(data_dir) / f"{session_key}.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "prompt_count": 6,
                        "seen_turns": [hashlib.sha256(b"turn-6").hexdigest()],
                        "fired_thresholds": [4],
                        "successful_updates": 0,
                        "pending_turn": hashlib.sha256(b"turn-4").hexdigest(),
                        "pending_threshold": 4,
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(run_hook(data_dir, prompt_payload(7)), "")
            migrated = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], 3)
            self.assertEqual(migrated["prompt_count"], 7)
            self.assertEqual(migrated["fired_thresholds"], [4])
            self.assertNotIn("successful_updates", migrated)

            self.assertEqual(run_hook(data_dir, prompt_payload(8)), "")
            self.assertEqual(run_hook(data_dir, prompt_payload(9)), "")
            refresh = json.loads(run_hook(data_dir, prompt_payload(10)))
            self.assertIn("refresh checkpoint", refresh["hookSpecificOutput"]["additionalContext"])

    def test_corrupt_and_wrong_shaped_state_fail_open(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            session_key = hashlib.sha256(b"thr-test").hexdigest()
            state_path = Path(data_dir) / f"{session_key}.json"
            state_path.write_text("{broken", encoding="utf-8")
            self.assertEqual(run_hook(data_dir, prompt_payload(1)), "")
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "prompt_count": "bad",
                        "seen_turns": "not-a-list",
                        "fired_thresholds": {"bad": True},
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(run_hook(data_dir, prompt_payload(2)), "")

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
            self.assertEqual(len(contexts), 2)
            state_path = next(Path(data_dir).glob("*.json"))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["prompt_count"], 16)
            self.assertEqual(state["fired_thresholds"], [4, 10])

    def test_package_manifests_and_hook_layout(self) -> None:
        plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        hooks = json.loads(HOOKS_CONFIG.read_text(encoding="utf-8"))

        self.assertEqual(plugin["name"], "codex-task-title-organizer")
        self.assertNotIn("hooks", plugin)
        self.assertEqual(set(hooks["hooks"]), {"UserPromptSubmit"})
        self.assertEqual(marketplace["name"], "codex-task-title-organizer")
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], plugin["name"])
        source = (REPO_ROOT / entry["source"]["path"]).resolve()
        self.assertEqual(source, PLUGIN_ROOT.resolve())
        self.assertTrue((source / ".codex-plugin" / "plugin.json").is_file())

    def test_skill_frontmatter_and_private_project_fallback(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: organize-codex-task-titles\n"))
        self.assertIn("project name, repository name, or only the basename of `cwd`", text)
        self.assertIn("Never invent an identifier", text)
        self.assertIn("Modify at most 10 tasks per batch", text)

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
            "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
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
