import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location(
    "maintain", Path(__file__).resolve().parents[1] / "scripts/maintain.py")
maintain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintain)


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        self.origin = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.origin)], check=True, capture_output=True)
        self.work = self.root / "work"
        self.work.mkdir()
        os.chdir(self.work)
        maintain.git("init", "-b", "main")
        maintain.git("config", "user.name", "Test")
        maintain.git("config", "user.email", "test@example.test")
        maintain.git("config", "commit.gpgsign", "false")
        # Redirect only this test checkout's upstream URL to the local fixture.
        maintain.git("config", f"url.{self.origin}.insteadOf",
                     "https://github.com/omer-faruq/assistant.koplugin.git")
        for name, content in {
            "_meta.lua": 'return { version = "1.22-dev" }\n',
            "main.lua": "return {}\n",
            ".releaseignore": ".*\n*.md\ntest/\nconfiguration.lua\n",
            "README.md": "Excluded\n",
            "test/check.lua": "Excluded\n",
            "core/module.lua": "return {}\n",
        }.items():
            path = Path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        maintain.git("add", ".")
        maintain.git("commit", "-m", "fixture")
        maintain.git("remote", "add", "origin", str(self.origin))
        maintain.git("push", "origin", "main")
        self.state = self.root / "state.json"

    def test_date_versions(self):
        now = dt.datetime(2026, 10, 29)
        self.assertEqual("v2026.10.29.1", maintain.next_tag(["v1.22"], now))
        self.assertEqual("v2026.10.29.3", maintain.next_tag(["v2026.10.29.2"], now))
        self.assertEqual("v2026.11.1.2", maintain.next_tag(["v2026.11.1.1"], now))

    def test_package_uses_tag_and_excludes_development_files(self):
        Path("_meta.lua").write_text('return { version = "2026.10.29.1" }\n')
        maintain.git("commit", "-am", "version")
        maintain.git("tag", "v2026.10.29.1")
        Path("configuration.lua").write_text("worktree-only fixture")
        archive = maintain.package("v2026.10.29.1", self.root / "output")
        with zipfile.ZipFile(archive) as result:
            self.assertEqual(
                {"assistant.koplugin/_meta.lua", "assistant.koplugin/main.lua",
                 "assistant.koplugin/core/module.lua"}, set(result.namelist()))

    def test_prepare_is_local_until_publish(self):
        base = maintain.git("rev-parse", "origin/main")
        maintain.prepare(self.state, "owner/repo", True)
        state = json.loads(self.state.read_text())
        self.assertEqual(base, maintain.git("rev-parse", "origin/main"))
        self.assertNotEqual(base, state["candidate"])
        self.assertFalse(maintain.git("tag", "--list"))

    def test_published_head_is_noop_and_draft_is_resumable(self):
        tag = "v2026.10.29.1"
        Path("_meta.lua").write_text('return { version = "2026.10.29.1" }\n')
        maintain.git("commit", "-am", "version")
        maintain.git("tag", tag)
        maintain.git("push", "origin", "main", tag)
        with patch.object(maintain, "release_info", return_value={"draft": False}):
            maintain.prepare(self.state, "owner/repo", True)
        self.assertTrue(json.loads(self.state.read_text())["noop"])
        with patch.object(maintain, "release_info", return_value={"draft": True}):
            maintain.prepare(self.state, "owner/repo", True)
        state = json.loads(self.state.read_text())
        self.assertFalse(state["noop"])
        self.assertEqual(tag, state["tag"])

    def test_changed_main_blocks_publish(self):
        maintain.prepare(self.state, "owner/repo", False)
        maintain.git("switch", "main")
        Path("new.lua").write_text("return true\n")
        maintain.git("add", "new.lua")
        maintain.git("commit", "-m", "concurrent edit")
        maintain.git("push", "origin", "main")
        maintain.git("switch", "automation/candidate")
        with self.assertRaisesRegex(RuntimeError, "main changed"):
            maintain.publish(self.state, self.root / "output")
        self.assertFalse(maintain.git("tag", "--list"))

    def test_conflict_leaves_main_unchanged(self):
        maintain.git("branch", "upstream-fixture")
        Path("main.lua").write_text("return 'custom'\n")
        maintain.git("commit", "-am", "custom")
        maintain.git("push", "origin", "main")
        base = maintain.git("rev-parse", "origin/main")
        maintain.git("switch", "upstream-fixture")
        Path("main.lua").write_text("return 'upstream'\n")
        maintain.git("commit", "-am", "upstream")
        # Separate bare upstream so fetch cannot overwrite origin/main.
        upstream = self.root / "upstream.git"
        subprocess.run(["git", "clone", "--bare", str(self.work), str(upstream)],
                       check=True, capture_output=True)
        subprocess.run(["git", "--git-dir", str(upstream), "update-ref",
                        "refs/heads/main", maintain.git("rev-parse", "HEAD")], check=True)
        maintain.git("config", "--unset-all", f"url.{self.origin}.insteadOf")
        maintain.git("config", f"url.{upstream}.insteadOf",
                     "https://github.com/omer-faruq/assistant.koplugin.git")
        maintain.git("switch", "main")
        with self.assertRaisesRegex(RuntimeError, "merge conflict"):
            maintain.prepare(self.state, "owner/repo", True)
        self.assertEqual(base, maintain.git("rev-parse", "origin/main"))
        self.assertFalse(self.state.exists())

    def test_success_publishes_candidate_and_rerun_is_noop(self):
        maintain.prepare(self.state, "owner/repo", False)
        state = json.loads(self.state.read_text())
        original_run = maintain.run
        calls = []
        def local_run(*args, **kwargs):
            if args[0] == "gh":
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, "", "")
            return original_run(*args, **kwargs)
        with patch.object(maintain, "release_info", return_value=None), \
                patch.object(maintain, "run", side_effect=local_run):
            maintain.publish(self.state, self.root / "output")
        self.assertEqual(state["candidate"], maintain.git("rev-parse", "origin/main"))
        self.assertEqual(state["candidate"], maintain.git("rev-parse", state["tag"]))
        self.assertEqual(["create", "upload", "edit"], [args[2] for args in calls])
        with patch.object(maintain, "release_info", return_value={"draft": False}):
            maintain.prepare(self.state, "owner/repo", True)
        self.assertTrue(json.loads(self.state.read_text())["noop"])

    def test_modified_candidate_blocks_publish(self):
        maintain.prepare(self.state, "owner/repo", False)
        Path("main.lua").write_text("changed after tests")
        with self.assertRaisesRegex(RuntimeError, "Candidate changed"):
            maintain.publish(self.state, self.root / "output")
        self.assertFalse(maintain.git("tag", "--list"))

    def test_ignore_negation(self):
        self.assertTrue(maintain.excluded("deep/test/a.lua", "test/"))
        self.assertFalse(maintain.excluded("l10n/fr/a.mo", "*.mo\n!l10n/fr/a.mo"))
        self.assertTrue(maintain.excluded("l10n/de/a.mo", "*.mo\n!l10n/fr/a.mo"))


if __name__ == "__main__":
    unittest.main()
