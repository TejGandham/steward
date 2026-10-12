"""Release-review fixes for `/steward-models apply` (0.12.0 review, B1-B2,
S1-S3 and the lock and null-section nits). Same temp-dir rules as
test_pi_model_plan_apply.py: nothing here touches the real ~/.pi/agent.
"""

import copy
import json
import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

import test_pi_model_plan_apply as base

mpa = base.mpa
PLAN, OPUS, SOL, SONNET, HAIKU, OLLAMA = base.PLAN, base.OPUS, base.SOL, base.SONNET, base.HAIKU, base.OLLAMA


def drift(result, role):
    return [f for f in result["findings"] if f["code"] == "binding-drift" and f["role"] == role]


class ByProviderTests(base.ApplyTestCase):
    """B1: apply and the check agree on agentOverridesByProvider entries."""

    def test_dropped_byprovider_thinking_is_rewritten(self):
        self.user_plan(PLAN)
        self.user_settings({})
        self.apply()
        plan = copy.deepcopy(PLAN)
        del plan["roles"]["reviewer"]["byMainProvider"]["amorphic"]["thinking"]
        self.user_plan(plan)
        result = self.apply()
        self.assertTrue(result["settingsChanged"])
        entry = self.settings()["subagents"]["agentOverridesByProvider"]["amorphic"]["steward.reviewer"]
        self.assertEqual(entry, {"model": SOL, "thinking": "high"})
        check = mpa.mp.evaluate(self.facts(main=OPUS), env=self.env)
        self.assertEqual(drift(check, "reviewer"), [])
        self.assertFalse(self.apply(dry_run=True)["changed"])

    def test_dropped_byprovider_entry_is_removed(self):
        self.user_plan(PLAN)
        self.user_settings({"subagents": {"agentOverridesByProvider": {
            "amorphic": {"worker": {"model": HAIKU}},
            "openai-codex": {"steward.writer": {"model": SOL}}}}})
        self.apply()
        plan = copy.deepcopy(PLAN)
        del plan["roles"]["reviewer"]["byMainProvider"]
        self.user_plan(plan)
        result = self.apply()
        by_provider = self.settings()["subagents"]["agentOverridesByProvider"]
        self.assertNotIn("steward.reviewer", by_provider["amorphic"])
        # non-steward keys stay; an unnamed role's byProvider entry is still a leftover
        self.assertEqual(by_provider["amorphic"], {"worker": {"model": HAIKU}})
        self.assertTrue(any("removed" in line and "steward.reviewer" in line for line in result["changes"]))
        check = mpa.mp.evaluate(self.facts(main=OPUS), env=self.env)
        self.assertEqual(drift(check, "reviewer"), [])

    def test_emptied_provider_object_is_left_empty(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS, "thinking": "low"}}})
        self.user_settings({"subagents": {"agentOverridesByProvider": {
            "openai-codex": {"steward.coder": {"model": SOL, "thinking": "max"}}}}})
        self.apply()
        self.assertEqual(self.settings()["subagents"]["agentOverridesByProvider"], {"openai-codex": {}})
        check = mpa.mp.evaluate(self.facts(main=SOL), env=self.env)
        self.assertEqual(drift(check, "coder"), [])

    def test_unavailable_byprovider_entry_is_kept(self):
        plan = {"version": 1, "roles": {"coder": {
            "model": OPUS, "thinking": "low", "byMainProvider": {"amorphic": {"model": base.NOCREDS}}}}}
        self.user_plan(plan)
        self.user_settings({"subagents": {"agentOverridesByProvider": {
            "amorphic": {"steward.coder": {"model": SONNET}}}}})
        result = self.apply()
        self.assertEqual(self.settings()["subagents"]["agentOverridesByProvider"]["amorphic"]["steward.coder"],
                         {"model": SONNET})
        self.assertTrue(self.finding(result, "no-available-candidate", "coder"))

    def test_thinking_only_byprovider_drops_a_stale_model(self):
        plan = {"version": 1, "roles": {"coder": {
            "model": OPUS, "thinking": "low", "byMainProvider": {"openai-codex": {"thinking": "high"}}}}}
        self.user_plan(plan)
        self.user_settings({"subagents": {"agentOverridesByProvider": {
            "openai-codex": {"steward.coder": {"model": SOL, "machine": "box"}}}}})
        self.apply()
        self.assertEqual(self.settings()["subagents"]["agentOverridesByProvider"]["openai-codex"]["steward.coder"],
                         {"thinking": "high", "machine": "box"})
        check = mpa.mp.evaluate(self.facts(main=SOL), env=self.env)
        self.assertEqual(drift(check, "coder"), [])

    def test_no_change_with_warnings_does_not_claim_a_match(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": base.NOCREDS, "thinking": "high"}}})
        self.user_settings({})
        self.apply()
        result = self.apply(dry_run=True)
        self.assertFalse(result["changed"])
        self.assertNotIn("already match", result["report"])


class PlanHashTests(base.ApplyTestCase):
    """B2: the plan is part of the preview hash."""

    def test_plan_edited_after_preview_refuses(self):
        self.user_plan(PLAN)
        self.user_settings(base.OPERATOR_SETTINGS)
        before = self.settings_path.read_bytes()
        preview = self.apply(dry_run=True)
        self.assertIn("plan", preview["hashes"])
        plan = copy.deepcopy(PLAN)
        plan["roles"]["coder"] = {"model": HAIKU, "thinking": "off"}
        self.user_plan(plan)
        with self.assertRaises(mpa.Refused) as caught:
            self.apply(expect=preview["hashes"])
        self.assertIn("model-plan.json", str(caught.exception))
        self.assertEqual(self.settings_path.read_bytes(), before)
        self.assertFalse(self.profile_path.exists())


class SettingsValueTests(base.ApplyTestCase):
    def test_non_finite_number_refuses(self):
        self.user_plan(PLAN)
        for text in ('{"x": 1e400}', '{"x": -1e999}', '{"x": NaN}', '{"x": Infinity}'):
            self.user_settings(None, text=text)
            for dry in (True, False):
                with self.assertRaises(mpa.Refused, msg=text):
                    self.apply(dry_run=dry)
            self.assertEqual(self.settings_path.read_text(), text)
        with self.assertRaises(ValueError):
            mpa._dump({"x": float("inf")}, "  ", False)

    def test_null_sections_are_treated_as_empty(self):
        self.user_plan(PLAN)
        for data in ({"subagents": None}, {"subagents": {"agentOverrides": None, "agentOverridesByProvider": None}}):
            self.user_settings(data)
            self.apply()
            overrides = self.settings()["subagents"]["agentOverrides"]
            self.assertEqual(overrides["steward.coder"], {"model": OLLAMA, "thinking": "high"})


class ProfileValidityTests(base.ApplyTestCase):
    """S3: the profile always passes pi-subagents' profile validation."""

    def test_invalid_non_steward_entry_is_skipped_with_a_finding(self):
        self.user_plan(PLAN)
        self.user_settings({"subagents": {"agentOverrides": {
            "scout": {"model": False}, "probe": {"machine": " "}, "worker": {"model": HAIKU}}}})
        result = self.apply()
        overrides = json.loads(self.profile_path.read_text())["subagents"]["agentOverrides"]
        self.assertNotIn("scout", overrides)
        self.assertNotIn("probe", overrides)
        self.assertEqual(overrides["worker"], {"model": HAIKU})
        skipped = self.finding(result, "profile-entry-skipped")
        self.assertEqual(len(skipped), 2)
        self.assertTrue(all(f["severity"] == "warn" for f in skipped))
        # settings keep the entry: pi-subagents accepts it there
        self.assertEqual(self.settings()["subagents"]["agentOverrides"]["scout"], {"model": False})

    def test_profile_always_names_the_provider_map(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS}}})
        self.user_settings({})
        self.apply()
        profile = json.loads(self.profile_path.read_text())
        self.assertEqual(profile["subagents"]["agentOverridesByProvider"], {})


CASES = [
    {"a": {"model": False}}, {"a": {"model": 1}}, {"a": {"model": "x"}}, {"a": {"thinking": False}},
    {"a": {"thinking": 3}}, {"a": {"thinking": "high"}}, {"a": {"machine": False}}, {"a": {"machine": ""}},
    {"a": {"machine": "  "}}, {"a": {"machine": "box"}}, {"a": {"machine": "x" * 129}},
    {"a": {"machine": "b\u0001x"}}, {"a": {"machine": 7}}, {"a": {"fallbackModels": []}}, {"a": []},
    {"a": None}, {"a": {}},
]


@unittest.skipIf(base.skip_reason(), base.skip_reason() or "")
class ProfileValidatorMirrorTests(base.ApplyTestCase):
    """The Python mirror agrees with pi-subagents 0.77.0's validator, case by case."""

    def test_mirror_matches_installed_validator(self):
        directory = self.agent_dir / "profiles" / "pi-subagents"
        directory.mkdir(parents=True)
        env = dict(os.environ, PI_CODING_AGENT_DIR=str(self.agent_dir), HOME=str(self.home))
        for case in CASES:
            (directory / "case.json").write_text(json.dumps({"subagents": {"agentOverrides": case}}))
            proc = subprocess.run(["node", str(base.HELPER), str(base.pi_subagents_dir()), "read", "case"],
                                  capture_output=True, text=True, env=env, timeout=60)
            node_ok = json.loads(proc.stdout.strip().splitlines()[-1])["ok"]
            py_ok = mpa.profile_entry_problem(case["a"]) is None
            self.assertEqual(py_ok, node_ok, case)

    def test_profile_with_settings_model_false_loads(self):
        self.user_plan(PLAN)
        self.user_settings({"subagents": {"agentOverrides": {"scout": {"model": False}}}})
        self.apply()
        env = dict(os.environ, PI_CODING_AGENT_DIR=str(self.agent_dir), HOME=str(self.home))
        proc = subprocess.run(["node", str(base.HELPER), str(base.pi_subagents_dir()), "read"],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertTrue(json.loads(proc.stdout.strip().splitlines()[-1])["ok"], proc.stdout)


class PartialWriteTests(base.ApplyTestCase):
    """S2: both temp files are ready before either rename; a failed second
    rename is reported as a partial write, not as a failure."""

    def test_profile_temp_failure_writes_nothing(self):
        self.user_plan(PLAN)
        self.user_settings(base.OPERATOR_SETTINGS)
        before = self.settings_path.read_bytes()
        real = mpa.tempfile.mkstemp

        def mkstemp(*a, **kw):
            if "steward.json" in kw.get("prefix", ""):
                raise OSError(28, "No space left on device")
            return real(*a, **kw)

        mpa.tempfile.mkstemp = mkstemp
        try:
            with self.assertRaises(mpa.Refused):
                self.apply()
        finally:
            mpa.tempfile.mkstemp = real
        self.assertEqual(self.settings_path.read_bytes(), before)
        self.assertEqual(self.backups(), [])
        leftovers = [p for p in self.agent_dir.rglob("*.tmp")]
        self.assertEqual(leftovers, [])

    def test_profile_rename_failure_is_a_partial_write(self):
        self.user_plan(PLAN)
        self.user_settings(base.OPERATOR_SETTINGS)
        self.profile_path.parent.mkdir(parents=True)
        self.profile_path.write_text('{"subagents": {"agentOverrides": {}}}\n')
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
        self.assertEqual(self.settings()["subagents"]["agentOverrides"]["steward.coder"]["model"], OLLAMA)
        self.assertEqual(len(result["backups"]), 2)
        for path in result["backups"]:
            self.assertIn(path, result["report"])
        self.assertIn("profile", result["report"].lower())
        self.assertEqual(self.profile_path.read_text(), '{"subagents": {"agentOverrides": {}}}\n')
        self.assertEqual([p for p in self.agent_dir.rglob("*.tmp")], [])


class LockTests(base.ApplyTestCase):
    def test_stale_pi_lock_is_taken_over(self):
        self.user_plan(PLAN)
        self.user_settings({})
        lock = Path(str(self.settings_path) + ".lock")
        lock.mkdir()
        old = time.time() - mpa.PI_LOCK_STALE_S - 5
        os.utime(lock, (old, old))
        self.apply(lock_wait=0.05)
        self.assertFalse(lock.exists())

    def test_dead_owner_lease_is_reclaimed(self):
        self.user_plan(PLAN)
        self.user_settings({})
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        lease = Path(os.path.realpath(self.settings_path) + ".write-lock")
        lease.mkdir()
        (lease / "owner.json").write_text(json.dumps({"token": "dead-token", "pid": proc.pid,
                                                      "hostname": socket.gethostname()}))
        self.apply(lock_wait=0.05)
        self.assertFalse(lease.exists())
        self.assertEqual(self.settings()["subagents"]["agentOverrides"]["steward.coder"]["model"], OLLAMA)

    def test_ownerless_lease_names_the_path(self):
        self.user_plan(PLAN)
        self.user_settings({})
        lease = Path(os.path.realpath(self.settings_path) + ".write-lock")
        lease.mkdir()
        with self.assertRaises(mpa.Refused) as caught:
            self.apply(lock_wait=0.05)
        self.assertIn("remove %s" % lease, str(caught.exception))
        self.assertTrue(lease.is_dir())

    def test_failed_owner_write_leaves_no_lock(self):
        self.user_plan(PLAN)
        self.user_settings({})
        real = mpa.os.open

        def fake_open(path, *a, **kw):
            if str(path).endswith("owner.json"):
                raise OSError(28, "No space left on device")
            return real(path, *a, **kw)

        mpa.os.open = fake_open
        try:
            with self.assertRaises((mpa.Refused, OSError)):
                self.apply(lock_wait=0.05)
        finally:
            mpa.os.open = real
        self.assertFalse(Path(os.path.realpath(self.settings_path) + ".write-lock").exists())
        self.assertFalse(Path(str(self.settings_path) + ".lock").exists())


if __name__ == "__main__":
    unittest.main()
