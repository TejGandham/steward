"""Final 0.12.0 fixes for `/steward-models apply` (verification of b197298:
N1 hand-set byProvider fields, N2 thinking-only byMainProvider with a
fallback level, and the nits). Same temp-dir rules as
test_pi_model_plan_apply.py: nothing here touches the real ~/.pi/agent.
"""

import json
import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path

import test_pi_model_plan_apply as base

mpa = base.mpa
OPUS, SOL, SONNET, HAIKU, OLLAMA, NOCREDS = base.OPUS, base.SOL, base.SONNET, base.HAIKU, base.OLLAMA, base.NOCREDS


def drift(result, role):
    return [f for f in result["findings"] if f["code"] == "binding-drift" and f["role"] == role]


class HandSetFieldTests(base.ApplyTestCase):
    """N1: only model and thinking are removed from an unlisted provider's entry."""

    def test_other_fields_survive(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": SONNET, "thinking": "high"}}})
        self.user_settings({"subagents": {
            "agentOverrides": {"steward.coder": {"model": SONNET, "thinking": "high"}},
            "agentOverridesByProvider": {
                "openai-codex": {"steward.coder": {"fast": True, "toolBudget": {"bash": 5}}, "worker": {"fast": True}},
                "amorphic": {"steward.coder": {"disabled": True}}}}})
        result = self.apply(dry_run=True)
        self.assertFalse(result["settingsChanged"])
        self.assertEqual([c for c in result["changes"] if "agentOverridesByProvider" in c], [])

    def test_model_and_thinking_are_popped_rest_kept(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": SONNET, "thinking": "high"}}})
        self.user_settings({"subagents": {"agentOverridesByProvider": {
            "openai-codex": {"steward.coder": {"model": SOL, "thinking": "max", "machine": "box"}},
            "amorphic": {"steward.coder": {"thinking": "low"}}}}})
        result = self.apply()
        by_provider = self.settings()["subagents"]["agentOverridesByProvider"]
        self.assertEqual(by_provider["openai-codex"], {"steward.coder": {"machine": "box"}})
        self.assertEqual(by_provider["amorphic"], {})
        self.assertEqual(len([c for c in result["changes"] if "agentOverridesByProvider" in c]), 2)
        for main in (SOL, OPUS):
            self.assertEqual(drift(mpa.mp.evaluate(self.facts(main=main), env=self.env), "coder"), [])
        self.assertFalse(self.apply(dry_run=True)["changed"])


class ThinkingOnlyFallbackTests(base.ApplyTestCase):
    """N2: a thinking-only byMainProvider entry takes the level of the
    candidate that is bound, as the check does."""

    def test_apply_check_apply_converges(self):
        self.user_plan({"version": 1, "roles": {"coder": {
            "model": NOCREDS, "thinking": "high", "fallback": [SONNET + ":medium"],
            "byMainProvider": {"amorphic": {"thinking": "low"}}}}})
        self.user_settings({})
        self.apply()
        entry = self.settings()["subagents"]["agentOverridesByProvider"]["amorphic"]["steward.coder"]
        self.assertEqual(entry, {"thinking": "medium"})
        self.assertEqual(drift(mpa.mp.evaluate(self.facts(main=OPUS), env=self.env), "coder"), [])
        self.assertFalse(self.apply(dry_run=True)["changed"])

    def test_bound_model_keeps_the_entry_level(self):
        self.user_plan({"version": 1, "roles": {"coder": {
            "model": SONNET, "thinking": "high", "fallback": [HAIKU + ":medium"],
            "byMainProvider": {"amorphic": {"thinking": "low"}}}}})
        self.user_settings({})
        self.apply()
        entry = self.settings()["subagents"]["agentOverridesByProvider"]["amorphic"]["steward.coder"]
        self.assertEqual(entry, {"thinking": "low"})
        self.assertEqual(drift(mpa.mp.evaluate(self.facts(main=OPUS), env=self.env), "coder"), [])


class UnchangedRoleTests(base.ApplyTestCase):
    """A role with no available candidate keeps its provider entries too."""

    def test_unchanged_role_keeps_byprovider_entries(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": NOCREDS, "thinking": "high"}}})
        settings = {"subagents": {
            "agentOverrides": {"steward.coder": {"model": SONNET}},
            "agentOverridesByProvider": {"amorphic": {"steward.coder": {"model": HAIKU}}}}}
        self.user_settings(settings)
        result = self.apply(dry_run=True)
        self.assertFalse(result["settingsChanged"])
        self.assertTrue(self.finding(result, "no-available-candidate", "coder"))


class LeaseTokenTests(base.ApplyTestCase):
    """pi-subagents 0.83.0 file-lease.js:64-65: after moving a dead owner's
    lease aside, the retired directory must still carry that owner's token."""

    def test_token_changed_during_recovery_refuses(self):
        self.user_plan(base.PLAN)
        self.user_settings({})
        before = self.settings_path.read_bytes()
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        lease = Path(os.path.realpath(self.settings_path) + ".write-lock")
        lease.mkdir()
        (lease / "owner.json").write_text(json.dumps({"token": "dead-token", "pid": proc.pid,
                                                      "hostname": socket.gethostname()}))
        real = mpa.os.rename

        def rename(src, dst):
            real(src, dst)
            if ".retired-" in str(dst):
                # A new holder's lease was renamed in place of the dead one.
                (Path(dst) / "owner.json").write_text(json.dumps({
                    "token": "other-token", "pid": os.getpid(), "hostname": socket.gethostname()}))

        mpa.os.rename = rename
        try:
            with self.assertRaises(mpa.Refused) as caught:
                self.apply(lock_wait=0.05)
        finally:
            mpa.os.rename = real
        self.assertIn("owner changed", str(caught.exception))
        self.assertEqual(self.settings_path.read_bytes(), before)
        self.assertFalse(Path(str(self.settings_path) + ".lock").exists())


class FirstRenameFailureTests(base.ApplyTestCase):
    def test_backups_are_removed(self):
        self.user_plan(base.PLAN)
        self.user_settings(base.OPERATOR_SETTINGS)
        self.profile_path.parent.mkdir(parents=True)
        self.profile_path.write_text('{"subagents": {"agentOverrides": {}}}\n')
        before = self.settings_path.read_bytes()
        real = mpa.os.replace

        def replace(src, dst):
            if str(dst).endswith("settings.json"):
                raise PermissionError(13, "Permission denied")
            return real(src, dst)

        mpa.os.replace = replace
        try:
            with self.assertRaises(mpa.Refused) as caught:
                self.apply()
        finally:
            mpa.os.replace = real
        self.assertIn("nothing was written", str(caught.exception))
        self.assertEqual(self.settings_path.read_bytes(), before)
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.backups("steward.json"), [])
        self.assertEqual([p for p in self.agent_dir.rglob("*.tmp")], [])


class PartialWordingTests(base.ApplyTestCase):
    def test_no_old_profile_is_not_called_old_mapping(self):
        self.user_plan(base.PLAN)
        self.user_settings(base.OPERATOR_SETTINGS)
        real = mpa.os.replace

        def replace(src, dst):
            if str(dst).endswith("steward.json"):
                raise PermissionError(13, "Permission denied")
            return real(src, dst)

        mpa.os.replace = replace
        try:
            result = self.apply()
        finally:
            mpa.os.replace = real
        self.assertTrue(result["partial"])
        self.assertEqual(len(result["backups"]), 1)
        self.assertNotIn("old mapping", result["report"])
        self.assertIn("backup below", result["report"])


if __name__ == "__main__":
    unittest.main()
