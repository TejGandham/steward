"""Tests for hooks/model_plan_apply.py, `/steward-models apply` (Phase 3 of
docs/roadmap/pi-model-plan.md).

Every test builds its own temp HOME and PI_CODING_AGENT_DIR. Nothing here
reads or writes the real ~/.pi/agent. The profile-file tests drive the
installed pi-subagents 0.77.0 profile code through tests/pi/profile_check.mjs
and skip, with the reason, when node or the package is missing.
"""

import copy
import datetime
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS = REPO_ROOT / "hooks"
HOOK = HOOKS / "steward_hook.py"
HELPER = Path(__file__).resolve().parent / "pi" / "profile_check.mjs"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

_spec = importlib.util.spec_from_file_location("model_plan_apply", str(HOOKS / "model_plan_apply.py"))
mpa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mpa)

ALL = ["off", "minimal", "low", "medium", "high", "xhigh", "max"]
OLLAMA = "ollama-cloud/deepseek-v4.1-flash"
FIREWORKS = "fireworks/accounts/fireworks/models/deepseek-v4p1-flash"
SOL = "openai-codex/gpt-6.1-sol"
OPUS = "amorphic/claude-opus-5-5"
SONNET = "amorphic/claude-sonnet-5-5"
HAIKU = "amorphic/claude-haiku-5-5"
NOCREDS = "openai/gpt-6.1-nocreds"


def model(full, available=True):
    provider, _, mid = full.partition("/")
    return {"provider": provider, "id": mid, "available": available, "thinkingLevels": list(ALL),
            "maxTokens": 128000}


CATALOG = [model(OLLAMA), model(FIREWORKS), model(SOL), model(OPUS), model(SONNET), model(HAIKU),
           model("anthropic/claude-opus-5-5"), model(NOCREDS, available=False)]

PLAN = {
    "version": 1,
    "providers": {"ollama-cloud": {"maxConcurrent": 3}},
    "roles": {
        "*": {"model": OLLAMA, "thinking": "high", "fallback": [FIREWORKS]},
        "mechanic": {"thinking": "low"},
        "reviewer": {"model": SONNET, "thinking": "high", "fallback": [SOL + ":medium"],
                     "byMainProvider": {"amorphic": {"model": SOL, "thinking": "medium"}}},
        "deep-reasoner": {"model": "main", "thinking": "xhigh", "fallback": [OPUS]},
        "top-reviewer": {"model": OPUS, "thinking": "max", "fallback": None},
    },
}

EXPECTED_OVERRIDES = {
    "steward.coder": {"model": OLLAMA, "thinking": "high"},
    "steward.deep-reasoner": {"model": "inherit", "thinking": "xhigh"},
    "steward.reviewer": {"model": SONNET, "thinking": "high"},
    "steward.researcher": {"model": OLLAMA, "thinking": "high"},
    "steward.writer": {"model": OLLAMA, "thinking": "high"},
    "steward.mechanic": {"model": OLLAMA, "thinking": "low"},
    "steward.top-reviewer": {"model": OPUS, "thinking": "max"},
}

# pi writes settings.json as JSON.stringify(settings, null, 2), no trailing newline.
OPERATOR_SETTINGS = {
    "defaultProvider": "amorphic",
    "defaultModel": "claude-opus-5-5",
    "defaultThinkingLevel": "xhigh",
    "modelThinkingLevels": {"amorphic/claude-opus-5-5": "xhigh"},
    "packages": ["git:github.com/tejgandham/steward", "npm:pi-subagents"],
    "unknownTopLevel": {"nested": [1, 2, {"x": "ü"}]},
    "subagents": {
        "modelScope": {"enforce": False, "allow": ["*"]},
        "agentOverrides": {
            "worker": {"model": HAIKU, "thinking": "low"},
            "steward.coder": {"model": HAIKU, "thinking": "medium", "machine": "gpu-box"},
        },
    },
}


def pi_json(data):
    return json.dumps(data, indent=2, ensure_ascii=False)


def pi_subagents_dir():
    value = os.environ.get("PI_SUBAGENTS_DIR")
    if value:
        return Path(value)
    return Path(os.path.expanduser("~")) / ".pi" / "agent" / "npm" / "node_modules" / "pi-subagents"


def skip_reason():
    if not shutil.which("node"):
        return "node is not on PATH; the pi-subagents profile check needs it"
    directory = pi_subagents_dir()
    if not (directory / "src" / "profiles" / "profiles.js").is_file():
        return "pi-subagents is not installed at %s (set PI_SUBAGENTS_DIR)" % directory
    return None


class ApplyTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="steward-apply-"))
        self.home = self.tmp / "home"
        self.agent_dir = self.tmp / "agent"
        self.agent_dir.mkdir(parents=True)
        self.home.mkdir()
        self.project = self.tmp / "work" / "repo"
        (self.project / ".pi").mkdir(parents=True)
        self.env = {"HOME": str(self.home), "PI_CODING_AGENT_DIR": str(self.agent_dir)}
        self.settings_path = self.agent_dir / "settings.json"
        self.profile_path = self.agent_dir / "profiles" / "pi-subagents" / "steward.json"
        self.clock = datetime.datetime(2026, 10, 13, 9, 30, 0)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def user_plan(self, data):
        path = self.agent_dir / "steward" / "model-plan.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def user_settings(self, data, text=None):
        self.settings_path.write_text(pi_json(data) if text is None else text, encoding="utf-8")
        return self.settings_path

    def settings(self):
        return json.loads(self.settings_path.read_text(encoding="utf-8"))

    def facts(self, models=None, main=OPUS, cwd=None):
        provider, _, mid = main.partition("/")
        return {"main": {"provider": provider, "id": mid, "thinkingLevel": "xhigh"},
                "models": copy.deepcopy(CATALOG if models is None else models),
                "projectTrusted": True, "cwd": str(cwd or self.project)}

    def apply(self, dry_run=False, **kw):
        now = kw.pop("now", self.clock)
        facts = kw.pop("facts", None) or self.facts()
        return mpa.apply(facts, env=self.env, dry_run=dry_run, now=now, **kw)

    def backups(self, name="settings.json"):
        parent = self.settings_path.parent if name == "settings.json" else self.profile_path.parent
        if not parent.is_dir():
            return []
        return sorted(p.name for p in parent.iterdir() if p.name.startswith(name + ".bak-"))

    def finding(self, result, code, role=None):
        return [f for f in result["findings"] if f["code"] == code and (role is None or f["role"] == role)]


class CompileTests(ApplyTestCase):
    def test_only_steward_fields_change(self):
        self.user_plan(PLAN)
        self.user_settings(OPERATOR_SETTINGS)
        result = self.apply()
        self.assertTrue(result["changed"])
        after = self.settings()
        before = copy.deepcopy(OPERATOR_SETTINGS)
        # everything outside subagents is untouched
        for key in before:
            if key != "subagents":
                self.assertEqual(after[key], before[key], key)
        self.assertEqual(after["subagents"]["modelScope"], before["subagents"]["modelScope"])
        overrides = after["subagents"]["agentOverrides"]
        self.assertEqual(overrides["worker"], {"model": HAIKU, "thinking": "low"})
        # machine survives on the steward entry
        self.assertEqual(overrides["steward.coder"], {"model": OLLAMA, "thinking": "high", "machine": "gpu-box"})
        for key, want in EXPECTED_OVERRIDES.items():
            got = {k: v for k, v in overrides[key].items() if k != "machine"}
            self.assertEqual(got, want, key)
        self.assertEqual(after["subagents"]["agentOverridesByProvider"],
                         {"amorphic": {"steward.reviewer": {"model": SOL, "thinking": "medium"}}})
        # never writes these
        for key in ("defaultModel", "modelThinkingLevels", "enabledModels"):
            self.assertEqual(after.get(key), before.get(key))
        self.assertFalse((self.agent_dir / "extensions" / "subagent" / "config.json").exists())

    def test_main_becomes_inherit(self):
        self.user_plan({"version": 1, "roles": {"deep-reasoner": {"model": "main", "thinking": "xhigh"}}})
        self.user_settings({})
        self.apply()
        self.assertEqual(self.settings()["subagents"]["agentOverrides"]["steward.deep-reasoner"],
                         {"model": "inherit", "thinking": "xhigh"})

    def test_by_main_provider_compiles(self):
        self.user_plan({"version": 1, "roles": {
            "coder": {"model": OLLAMA, "thinking": "high",
                      "byMainProvider": {"amorphic": {"model": OPUS, "thinking": "medium"},
                                         "openai-codex": {"thinking": "low"},
                                         "anthropic": {"model": "main"}}}}})
        self.user_settings({})
        self.apply()
        sub = self.settings()["subagents"]
        self.assertEqual(sub["agentOverrides"]["steward.coder"], {"model": OLLAMA, "thinking": "high"})
        self.assertEqual(sub["agentOverridesByProvider"], {
            "amorphic": {"steward.coder": {"model": OPUS, "thinking": "medium"}},
            "openai-codex": {"steward.coder": {"thinking": "low"}},
            # a byProvider model always carries thinking: the role's when the entry names none
            "anthropic": {"steward.coder": {"model": "inherit", "thinking": "high"}},
        })

    def test_star_by_main_provider_does_not_beat_role_model(self):
        # Same rank rule as the check: a "*" byMainProvider model loses to the role's own model.
        self.user_plan({"version": 1, "roles": {
            "*": {"byMainProvider": {"amorphic": {"model": OPUS}}},
            "coder": {"model": OLLAMA, "thinking": "high"},
            "writer": {"thinking": "high"}}})
        self.user_settings({})
        self.apply()
        sub = self.settings()["subagents"]
        amorphic = sub["agentOverridesByProvider"]["amorphic"]
        self.assertNotIn("steward.coder", amorphic)
        self.assertEqual(amorphic["steward.writer"], {"model": OPUS, "thinking": "high"})
        self.assertEqual(sorted(amorphic), sorted("steward." + r for r in mpa.mp.ROLES if r != "coder"))
        self.assertEqual(sub["agentOverrides"]["steward.writer"], {"thinking": "high"})

    def test_disabled_provider_is_skipped(self):
        plan = {"version": 1, "providers": {"ollama-cloud": {"enabled": False}},
                "roles": {"coder": {"model": OLLAMA, "thinking": "high", "fallback": [FIREWORKS]}}}
        self.user_plan(plan)
        self.user_settings({})
        self.apply()
        self.assertEqual(self.settings()["subagents"]["agentOverrides"]["steward.coder"]["model"], FIREWORKS)

    def test_unavailable_candidate_falls_to_next(self):
        self.user_plan({"version": 1, "roles": {
            "coder": {"model": NOCREDS, "thinking": "high", "fallback": ["nope/not-in-catalog", FIREWORKS + ":max"]}}})
        self.user_settings({})
        result = self.apply()
        self.assertEqual(self.settings()["subagents"]["agentOverrides"]["steward.coder"],
                         {"model": FIREWORKS, "thinking": "max"})
        self.assertTrue(self.finding(result, "candidate-skipped", "coder"))

    def test_no_candidate_leaves_role_unchanged(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": NOCREDS, "thinking": "high"},
                                                 "mechanic": {"model": HAIKU, "thinking": "low"}}})
        self.user_settings({"subagents": {"agentOverrides": {"steward.coder": {"model": SONNET, "thinking": "low"}}}})
        result = self.apply()
        overrides = self.settings()["subagents"]["agentOverrides"]
        self.assertEqual(overrides["steward.coder"], {"model": SONNET, "thinking": "low"})
        self.assertEqual(overrides["steward.mechanic"], {"model": HAIKU, "thinking": "low"})
        found = self.finding(result, "no-available-candidate", "coder")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "warn")

    def test_stale_keys_migrate(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS, "thinking": "medium"}}})
        self.user_settings({"subagents": {
            "agentOverrides": {
                "steward.coder-opus-medium": {"model": HAIKU, "thinking": "low", "machine": "box"},
                "worker": {"model": HAIKU},
                "steward.reviewer-fable-xhigh": {"model": OPUS, "thinking": "xhigh"},
                "steward.reviewer-opus-max": {"model": SONNET, "thinking": "max"},
                "steward.mechanic": {"thinking": "high"},
                "steward.mechanic-haiku-medium": {"model": HAIKU, "thinking": "medium", "machine": "m2"},
            },
            "agentOverridesByProvider": {"amorphic": {"steward.writer-sonnet-medium": {"model": SONNET}}}}})
        result = self.apply()
        sub = self.settings()["subagents"]
        overrides = sub["agentOverrides"]
        for old in mpa.STALE_KEYS:
            self.assertNotIn(old, overrides)
        # the plan's fields win; the rest of the old entry moves with it
        self.assertEqual(overrides["steward.coder"], {"model": OPUS, "thinking": "medium", "machine": "box"})
        self.assertEqual(overrides["worker"], {"model": HAIKU})
        # the first old name in file order fills top-reviewer; the second adds only missing fields
        self.assertEqual(overrides["steward.top-reviewer"], {"model": OPUS, "thinking": "xhigh"})
        # an existing new-name entry keeps its fields; missing ones come from the old entry
        self.assertEqual(overrides["steward.mechanic"], {"thinking": "high", "model": HAIKU, "machine": "m2"})
        self.assertEqual(sub["agentOverridesByProvider"], {"amorphic": {"steward.writer": {"model": SONNET}}})
        self.assertTrue(self.finding(result, "stale-key-merged"))
        self.assertTrue(any("steward.coder-opus-medium" in c for c in result["changes"]))

    def test_leftovers_are_reported_not_deleted(self):
        # One exception (review B1): a named role's byProvider entry for a
        # provider the plan does not list is removed; an unnamed role's stays.
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS}}})
        self.user_settings({"subagents": {
            "agentOverrides": {"steward.coder": {"model": HAIKU, "thinking": "low"},
                               "steward.writer": {"model": SONNET, "thinking": "high"}},
            "agentOverridesByProvider": {"openai-codex": {"steward.coder": {"model": SOL},
                                                          "steward.writer": {"model": OPUS}}}}})
        result = self.apply()
        sub = self.settings()["subagents"]
        self.assertEqual(sub["agentOverrides"]["steward.coder"], {"model": OPUS, "thinking": "low"})
        self.assertEqual(sub["agentOverrides"]["steward.writer"], {"model": SONNET, "thinking": "high"})
        self.assertEqual(sub["agentOverridesByProvider"], {"openai-codex": {"steward.writer": {"model": OPUS}}})
        self.assertTrue(any("openai-codex steward.coder: removed" in c for c in result["changes"]))
        self.assertEqual(len(self.finding(result, "leftover-override", "writer")), 2)
        self.assertFalse(self.finding(result, "leftover-override", "coder"))
        self.assertTrue(self.finding(result, "thinking-not-in-plan", "coder"))

    def test_project_plan_and_cwd_have_no_effect(self):
        self.user_plan(PLAN)
        self.user_settings(OPERATOR_SETTINGS)
        dry = self.apply(dry_run=True)
        (self.project / ".pi" / "steward-model-plan.json").write_text(json.dumps({
            "version": 1, "denyProviders": ["ollama-cloud", "fireworks"], "allowProviders": ["amorphic"],
            "roles": {"*": {"model": HAIKU, "thinking": "off"}}}), encoding="utf-8")
        (self.project / ".pi" / "settings.json").write_text(json.dumps({"subagents": {"agentOverrides": {
            "steward.coder": {"model": HAIKU}}}}), encoding="utf-8")
        for cwd in (self.project, self.tmp, Path("/")):
            for trusted in (True, False):
                facts = self.facts(cwd=cwd)
                facts["projectTrusted"] = trusted
                again = self.apply(dry_run=True, facts=facts)
                self.assertEqual(again["changes"], dry["changes"])
                self.assertEqual(again["newSettings"], dry["newSettings"])
        self.apply(facts=self.facts(cwd=self.project))
        self.assertEqual(self.settings()["subagents"]["agentOverrides"]["steward.coder"]["model"], OLLAMA)

    def test_main_model_does_not_change_the_result(self):
        self.user_plan(PLAN)
        self.user_settings({})
        a = self.apply(dry_run=True, facts=self.facts(main=OPUS))
        b = self.apply(dry_run=True, facts=self.facts(main=SOL))
        self.assertEqual(a["newSettings"], b["newSettings"])


class SafetyTests(ApplyTestCase):
    def test_one_backup_per_changing_run_and_idempotent(self):
        self.user_plan(PLAN)
        original = pi_json(OPERATOR_SETTINGS)
        self.user_settings(None, text=original)
        result = self.apply()
        self.assertTrue(result["settingsChanged"])
        backups = self.backups()
        self.assertEqual(backups, ["settings.json.bak-20261013-093000"])
        self.assertEqual((self.agent_dir / backups[0]).read_text(encoding="utf-8"), original)
        first = self.settings_path.read_bytes()
        mtime = self.settings_path.stat().st_mtime_ns
        profile = self.profile_path.read_bytes()

        again = self.apply(now=self.clock + datetime.timedelta(seconds=5))
        self.assertFalse(again["changed"])
        self.assertTrue(again["report"].startswith("steward model plan apply: nothing to change"))
        self.assertNotIn("preview", self.apply(dry_run=True)["report"])
        self.assertFalse(again["settingsChanged"])
        self.assertFalse(again["profileChanged"])
        self.assertEqual(again["changes"], [])
        self.assertEqual(self.backups(), backups)
        self.assertEqual(self.backups("steward.json"), [])
        self.assertEqual(self.settings_path.read_bytes(), first)
        self.assertEqual(self.settings_path.stat().st_mtime_ns, mtime)
        self.assertEqual(self.profile_path.read_bytes(), profile)

    def test_backup_name_never_overwrites(self):
        self.user_plan(PLAN)
        self.user_settings({})
        (self.agent_dir / "settings.json.bak-20261013-093000").write_text("older", encoding="utf-8")
        self.apply()
        self.assertEqual((self.agent_dir / "settings.json.bak-20261013-093000").read_text(), "older")
        self.assertEqual(len(self.backups()), 2)

    def test_dry_run_writes_nothing(self):
        self.user_plan(PLAN)
        self.user_settings(OPERATOR_SETTINGS)
        before = self.settings_path.read_bytes()
        result = self.apply(dry_run=True)
        self.assertTrue(result["changed"])
        self.assertTrue(result["changes"])
        self.assertEqual(self.settings_path.read_bytes(), before)
        self.assertEqual(self.backups(), [])
        self.assertFalse(self.profile_path.exists())
        self.assertEqual(result["hashes"]["settings"], mpa.content_hash(before))

    def test_changed_between_read_and_write_refuses(self):
        self.user_plan(PLAN)
        self.user_settings(OPERATOR_SETTINGS)
        racer = pi_json(dict(OPERATOR_SETTINGS, defaultModel="claude-sonnet-5-5"))

        def race():
            self.settings_path.write_text(racer, encoding="utf-8")

        with self.assertRaises(mpa.Refused) as caught:
            self.apply(before_write=race)
        self.assertIn("changed", str(caught.exception))
        self.assertEqual(self.settings_path.read_text(encoding="utf-8"), racer)
        self.assertEqual(self.backups(), [])
        self.assertFalse(self.profile_path.exists())

    def test_expected_hash_from_the_preview(self):
        self.user_plan(PLAN)
        self.user_settings(OPERATOR_SETTINGS)
        preview = self.apply(dry_run=True)
        self.user_settings(dict(OPERATOR_SETTINGS, defaultThinkingLevel="high"))
        before = self.settings_path.read_bytes()
        with self.assertRaises(mpa.Refused) as caught:
            self.apply(expect=preview["hashes"])
        self.assertIn("since the preview", str(caught.exception))
        self.assertEqual(self.settings_path.read_bytes(), before)
        # with a matching hash it writes
        fresh = self.apply(dry_run=True)
        self.apply(expect=fresh["hashes"])
        self.assertEqual(self.settings()["subagents"]["agentOverrides"]["steward.coder"]["model"], OLLAMA)

    def test_malformed_settings_refuses(self):
        self.user_plan(PLAN)
        for text in ("{not json", "[]", '{"subagents": []}', '{"subagents": {"agentOverrides": []}}',
                     '{"subagents": {"agentOverrides": {"steward.coder": "x"}}}',
                     '{"subagents": {"agentOverridesByProvider": {"amorphic": []}}}'):
            self.user_settings(None, text=text)
            with self.assertRaises(mpa.Refused, msg=text):
                self.apply()
            self.assertEqual(self.settings_path.read_text(encoding="utf-8"), text)
            self.assertEqual(self.backups(), [])
            self.assertFalse(self.profile_path.exists())

    def test_schema_error_in_plan_refuses(self):
        self.user_settings(OPERATOR_SETTINGS)
        before = self.settings_path.read_bytes()
        bad_plans = [
            {"version": 1, "roles": {"coder": {"model": "deepseek-v4.1-flash"}}},
            {"version": 1, "roles": {"coder": {"model": OLLAMA, "thinking": "ultra"}}},
            {"version": 1, "roles": {"nobody": {"model": OLLAMA}}},
            {"version": 2, "roles": {}},
            {"version": 1, "allowProviders": ["amorphic"]},
        ]
        for plan in bad_plans:
            self.user_plan(plan)
            with self.assertRaises(mpa.Refused, msg=json.dumps(plan)):
                self.apply()
            self.assertEqual(self.settings_path.read_bytes(), before)
        (self.agent_dir / "steward" / "model-plan.json").write_text("{oops", encoding="utf-8")
        with self.assertRaises(mpa.Refused):
            self.apply()
        (self.agent_dir / "steward" / "model-plan.json").unlink()
        with self.assertRaises(mpa.Refused) as caught:
            self.apply()
        self.assertIn("no user plan", str(caught.exception))
        self.assertEqual(self.settings_path.read_bytes(), before)
        self.assertEqual(self.backups(), [])

    def test_permissions_and_formatting_preserved(self):
        self.user_plan(PLAN)
        original = pi_json(OPERATOR_SETTINGS)
        self.user_settings(None, text=original)
        os.chmod(self.settings_path, 0o640)
        self.apply()
        self.assertEqual(stat.S_IMODE(self.settings_path.stat().st_mode), 0o640)
        text = self.settings_path.read_text(encoding="utf-8")
        # pi's style: two-space JSON, no trailing newline, keys in their old order
        self.assertEqual(text, pi_json(json.loads(text)))
        self.assertFalse(text.endswith("\n"))
        self.assertEqual(list(json.loads(text)), list(OPERATOR_SETTINGS))
        self.assertIn('"x": "ü"', text)
        backup = self.agent_dir / self.backups()[0]
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o640)
        # a file with a trailing newline and four-space indent keeps both
        self.user_settings(None, text=json.dumps({"a": {"b": 1}}, indent=4) + "\n")
        self.apply(now=self.clock + datetime.timedelta(seconds=1))
        text = self.settings_path.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(text, json.dumps(json.loads(text), indent=4, ensure_ascii=False) + "\n")

    def test_symlinked_settings_stays_a_symlink(self):
        self.user_plan(PLAN)
        real = self.tmp / "dotfiles" / "pi-settings.json"
        real.parent.mkdir()
        real.write_text(pi_json({"theme": "dark"}), encoding="utf-8")
        self.settings_path.symlink_to(real)
        self.apply()
        self.assertTrue(self.settings_path.is_symlink())
        self.assertEqual(json.loads(real.read_text())["theme"], "dark")
        self.assertIn("steward.coder", json.loads(real.read_text())["subagents"]["agentOverrides"])

    def test_missing_settings_file_is_created(self):
        self.user_plan(PLAN)
        self.apply()
        self.assertEqual(self.settings()["subagents"]["agentOverrides"]["steward.top-reviewer"],
                         {"model": OPUS, "thinking": "max"})
        self.assertEqual(self.backups(), [])

    def test_lock_held_by_another_writer_refuses(self):
        self.user_plan(PLAN)
        self.user_settings(OPERATOR_SETTINGS)
        before = self.settings_path.read_bytes()
        lock = Path(str(self.settings_path) + ".lock")
        lock.mkdir()
        with self.assertRaises(mpa.Refused) as caught:
            self.apply(lock_wait=0.05)
        self.assertIn("lock", str(caught.exception))
        self.assertEqual(self.settings_path.read_bytes(), before)
        self.assertTrue(lock.is_dir(), "another writer's lock is never removed")
        lock.rmdir()
        self.apply()
        self.assertFalse(lock.exists())
        self.assertFalse(Path(str(self.settings_path) + ".write-lock").exists())


class ProfileFileTests(ApplyTestCase):
    def profile(self):
        return json.loads(self.profile_path.read_text(encoding="utf-8"))

    def test_profile_carries_the_full_mapping(self):
        self.user_plan(PLAN)
        self.user_settings(OPERATOR_SETTINGS)
        result = self.apply()
        self.assertTrue(result["profileChanged"])
        profile = self.profile()
        self.assertEqual(sorted(profile), ["subagents"])
        overrides = profile["subagents"]["agentOverrides"]
        self.assertEqual(overrides, self.settings()["subagents"]["agentOverrides"])
        self.assertEqual(overrides["worker"], {"model": HAIKU, "thinking": "low"})
        self.assertEqual(profile["subagents"]["agentOverridesByProvider"],
                         self.settings()["subagents"]["agentOverridesByProvider"])
        for entry in overrides.values():
            self.assertNotIn("fallbackModels", entry)
        self.assertTrue(self.profile_path.read_text().endswith("}\n"))

    def test_existing_profile_is_backed_up_once(self):
        self.user_plan(PLAN)
        self.user_settings({})
        self.profile_path.parent.mkdir(parents=True)
        self.profile_path.write_text('{"subagents": {"agentOverrides": {}}}\n', encoding="utf-8")
        self.apply()
        self.assertEqual(self.backups("steward.json"), ["steward.json.bak-20261013-093000"])
        self.apply(now=self.clock + datetime.timedelta(seconds=3))
        self.assertEqual(len(self.backups("steward.json")), 1)

    def test_profile_changed_between_read_and_write_refuses(self):
        self.user_plan(PLAN)
        self.user_settings(OPERATOR_SETTINGS)
        before = self.settings_path.read_bytes()

        def race():
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            self.profile_path.write_text('{"subagents": {"agentOverrides": {}}}', encoding="utf-8")

        with self.assertRaises(mpa.Refused):
            self.apply(before_write=race)
        self.assertEqual(self.settings_path.read_bytes(), before)

    def test_profile_rewritten_when_only_the_profile_differs(self):
        self.user_plan(PLAN)
        self.user_settings({})
        self.apply()
        backups = self.backups()
        self.profile_path.unlink()
        settings = self.settings_path.read_bytes()
        result = self.apply(now=self.clock + datetime.timedelta(seconds=9))
        self.assertFalse(result["settingsChanged"])
        self.assertTrue(result["profileChanged"])
        self.assertEqual(self.settings_path.read_bytes(), settings)
        self.assertEqual(self.backups(), backups)
        self.assertTrue(self.profile_path.exists())


@unittest.skipIf(skip_reason(), skip_reason() or "")
class PiSubagentsProfileTests(ApplyTestCase):
    """The written profile goes through pi-subagents 0.77.0's own code."""

    def node(self, action, stdin=None):
        env = dict(os.environ, PI_CODING_AGENT_DIR=str(self.agent_dir), HOME=str(self.home))
        proc = subprocess.run(["node", str(HELPER), str(pi_subagents_dir()), action], input=stdin,
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_version_is_pinned(self):
        self.assertEqual(self.node("format", "{}")["version"], "0.77.0",
                         "pi-subagents changed version: re-verify the profile format (src/profiles/profiles.js)")

    def test_profile_passes_validation_and_load_restores_mapping(self):
        self.user_plan(PLAN)
        self.user_settings(OPERATOR_SETTINGS)
        self.apply()
        read = self.node("read")
        self.assertTrue(read["ok"], read.get("error"))
        applied = self.settings()["subagents"]
        # Another profile replaces the whole mapping, as /subagents-load-profile does.
        other = self.agent_dir / "profiles" / "pi-subagents" / "other.json"
        other.write_text(json.dumps({"subagents": {"agentOverrides": {"worker": {"model": SOL}}}}), encoding="utf-8")
        loaded = self.node_load("other")
        self.assertTrue(loaded["ok"], loaded.get("error"))
        self.assertEqual(set(self.settings()["subagents"]["agentOverrides"]), {"worker", "steward.coder"})
        # Loading the steward profile restores every override and the provider map.
        loaded = self.node_load("steward")
        self.assertTrue(loaded["ok"], loaded.get("error"))
        restored = self.settings()["subagents"]
        self.assertEqual(restored["agentOverrides"], applied["agentOverrides"])
        self.assertEqual(restored["agentOverridesByProvider"], applied["agentOverridesByProvider"])
        # pi-subagents' own write is a fixed point for apply: nothing left to change
        again = self.apply(dry_run=True)
        self.assertEqual(again["changes"], [])

    def node_load(self, name):
        env = dict(os.environ, PI_CODING_AGENT_DIR=str(self.agent_dir), HOME=str(self.home))
        proc = subprocess.run(["node", str(HELPER), str(pi_subagents_dir()), "load", name],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_settings_keep_pis_json_style(self):
        self.user_plan(PLAN)
        self.user_settings(OPERATOR_SETTINGS)
        self.apply()
        self.assertTrue(self.node("format", self.settings_path.read_text(encoding="utf-8"))["same"])
        self.assertTrue(self.node("format", self.profile_path.read_text(encoding="utf-8"))["same"])


class HookSubcommandTests(ApplyTestCase):
    def run_hook(self, payload, *args):
        env = dict(self.env, STEWARD_HARNESS="pi", PATH=os.environ.get("PATH", ""))
        proc = subprocess.run([sys.executable, str(HOOK), "model-plan-apply", *args],
                              input=json.dumps(payload) if not isinstance(payload, str) else payload,
                              capture_output=True, text=True, env=env, timeout=60)
        return proc.returncode, json.loads(proc.stdout), proc.stderr

    def test_dry_run_then_apply(self):
        self.user_plan(PLAN)
        self.user_settings(OPERATOR_SETTINGS)
        before = self.settings_path.read_bytes()
        code, out, _ = self.run_hook({"model_facts": self.facts(), "dryRun": True})
        self.assertEqual(code, 0)
        self.assertTrue(out["changed"])
        self.assertIn("steward.coder", out["report"])
        self.assertIn(str(self.settings_path), out["report"])
        self.assertIn("->", out["report"])
        self.assertEqual(self.settings_path.read_bytes(), before)
        # --dry-run wins over dryRun false
        code, out2, _ = self.run_hook({"model_facts": self.facts(), "dryRun": False}, "--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(out2["dryRun"])
        self.assertEqual(self.settings_path.read_bytes(), before)
        # no dryRun key at all is a dry run too
        code, out3, _ = self.run_hook({"model_facts": self.facts()})
        self.assertTrue(out3["dryRun"])
        self.assertEqual(self.settings_path.read_bytes(), before)
        code, done, _ = self.run_hook({"model_facts": self.facts(), "dryRun": False, "expect": out["hashes"]})
        self.assertEqual(code, 0, done)
        self.assertFalse(done["dryRun"])
        self.assertTrue(done["settingsChanged"])
        self.assertEqual(len(done["backups"]), 1)
        self.assertEqual(self.settings()["subagents"]["agentOverrides"]["steward.coder"]["model"], OLLAMA)

    def test_refusal_and_bad_input(self):
        code, out, err = self.run_hook({"model_facts": self.facts(), "dryRun": False})
        self.assertEqual(code, 3)
        self.assertIn("no user plan", out["error"])
        self.assertTrue(out["refused"])
        self.assertIn("no user plan", err)
        for payload in ("not json", {"dryRun": False}, {"model_facts": {"models": []}, "dryRun": False}):
            code, out, _ = self.run_hook(payload)
            self.assertEqual(code, 2, payload)
            self.assertIn("error", out)
        env = dict(self.env, STEWARD_HARNESS="claude", PATH=os.environ.get("PATH", ""))
        proc = subprocess.run([sys.executable, str(HOOK), "model-plan-apply"], input="{}", capture_output=True,
                              text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 2)


class DriftHintTests(ApplyTestCase):
    def test_user_plan_drift_says_run_apply(self):
        mp = mpa.mp
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS}}})
        result = mp.evaluate(self.facts(), env=self.env)
        drift = [f for f in result["findings"] if f["code"] == "binding-drift" and f["role"] == "coder"]
        self.assertEqual(len(drift), 1)
        self.assertIn("run /steward-models apply", drift[0]["message"])
        # after apply the drift is gone
        self.apply()
        result = mp.evaluate(self.facts(), env=self.env)
        self.assertFalse([f for f in result["findings"] if f["code"] == "binding-drift" and f["role"] == "coder"])

    def test_project_plan_drift_still_names_the_repo_settings(self):
        mp = mpa.mp
        (self.project / ".pi" / "steward-model-plan.json").write_text(json.dumps(
            {"version": 1, "roles": {"coder": {"model": OPUS}}}), encoding="utf-8")
        result = mp.evaluate(self.facts(), env=self.env)
        drift = [f for f in result["findings"] if f["code"] == "binding-drift" and f["role"] == "coder"]
        self.assertNotIn("/steward-models apply", drift[0]["message"])
        self.assertIn(str(self.project / ".pi" / "settings.json"), drift[0]["message"])


if __name__ == "__main__":
    unittest.main()
