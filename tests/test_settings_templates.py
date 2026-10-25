"""The settings templates users copy into their repositories."""

from __future__ import annotations

import fnmatch
import json
import unittest

from helpers import PLUGIN

ASSETS = PLUGIN / "skills" / "clean-ledger" / "assets"
SANDBOXED = ASSETS / "settings.sandboxed.json"


def read_denied(cfg: dict, path: str) -> bool:
    """Would a Read deny rule or a sandbox denyRead entry match `path`?"""
    for rule in cfg["permissions"]["deny"]:
        if rule.startswith("Read(") and fnmatch.fnmatch(path, rule[5:-1].replace("/**", "/*")):
            return True
    for entry in cfg.get("sandbox", {}).get("filesystem", {}).get("denyRead", []):
        if path == entry or path.startswith(entry.rstrip("/") + "/"):
            return True
    return False


class SandboxedTemplate(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(SANDBOXED.read_text())

    def test_plugin_files_stay_readable(self):
        # A plugin installed from a GitHub marketplace lives in the plugin cache;
        # the first GitHub-install test was blocked because ~/.claude was denied.
        for path in ("~/.claude/plugins/cache/clean-ledger-marketplace/clean-ledger/1.4.1/skills/clean-ledger/ROADMAP.md",
                     "~/.claude/plugins/cache/clean-ledger-marketplace/clean-ledger/1.4.1/skills/clean-ledger/scripts/ledger.py"):
            with self.subTest(path=path):
                self.assertFalse(read_denied(self.cfg, path))

    def test_conversations_and_credentials_stay_blocked(self):
        for path in ("~/.claude/projects/x/transcript.jsonl", "~/.claude/.credentials.json", "~/.claude.json",
                     "~/.claude/history.jsonl", "~/.claude/settings.json", "~/.claude/sessions/s1",
                     "~/.ssh/id_ed25519", "~/.aws/credentials", "~/.config/gh/hosts.yml"):
            with self.subTest(path=path):
                self.assertTrue(read_denied(self.cfg, path))

    def test_sandbox_is_strict(self):
        sb = self.cfg["sandbox"]
        self.assertTrue(sb["enabled"])
        self.assertFalse(sb["allowUnsandboxedCommands"])
        self.assertTrue(sb["failIfUnavailable"])

    def test_package_registries_are_reachable(self):
        hosts = self.cfg["sandbox"]["network"]["allowedDomains"]
        for host in ("pypi.org", "files.pythonhosted.org", "registry.npmjs.org", "semgrep.dev"):
            self.assertIn(host, hosts)

    def test_dangerous_commands_are_denied(self):
        deny = self.cfg["permissions"]["deny"]
        for rule in ("Bash(git push:*)", "Bash(curl:*)", "Bash(sudo:*)", "Bash(security:*)", "Bash(gh:*)"):
            self.assertIn(rule, deny)

    def test_e2e_copy_matches(self):
        self.assertEqual(SANDBOXED.read_text(), (PLUGIN / "e2e" / "local" / "settings.json").read_text())


if __name__ == "__main__":
    unittest.main()
