"""Tests for Phase 2b of docs/roadmap/pi-model-plan.md: the model plan
block rendered into pi's session-start output, and the `model-plan` hook
subcommand that /steward-models check (2c) calls.

Every test builds its own temp HOME, agent dir and project dir; nothing
here reads the real ~/.pi/agent.
"""

import copy
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_pi_model_plan import (CATALOG, FIREWORKS, OLLAMA, OPUS, REPO_ROOT, SOL, SONNET,
                                PlanTestCase, model, mp)
from test_pi_model_plan_review2 import doc_operator_plan
from test_steward_hook import EM_DASH, StewardTestCase, hook

HOOKS = REPO_ROOT / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))
render = importlib.import_module("model_plan_render")

# The commit 2b builds on; regression output is captured from its script.
BASE_COMMIT = "eb80786"
# Set to 1 to skip, not fail, the regression tests when BASE_COMMIT is missing
# (a shallow clone, say).
ALLOW_MISSING_BASE_ENV = "STEWARD_ALLOW_MISSING_BASE_COMMIT"
BOX_DRAWING = re.compile("[\u2500-\u257f]")

# The operator's Phase 0 settings from the doc, equal to what apply writes
# for the operator's-case plan.
PHASE0_SETTINGS = {
    "subagents": {
        "agentOverrides": {
            "steward.coder": {"model": OLLAMA, "thinking": "high"},
            "steward.researcher": {"model": OLLAMA, "thinking": "high"},
            "steward.writer": {"model": OLLAMA, "thinking": "high"},
            "steward.mechanic": {"model": OLLAMA, "thinking": "low"},
            "steward.reviewer": {"model": SONNET, "thinking": "high"},
            "steward.deep-reasoner": {"model": "inherit", "thinking": "xhigh"},
            "steward.top-reviewer": {"model": OPUS, "thinking": "xhigh"},
        },
        "agentOverridesByProvider": {
            "amorphic": {"steward.reviewer": {"model": SOL, "thinking": "medium"}},
        },
    }
}


def table_rows(block):
    """{runtime name: [cells]} for every table row of a rendered block."""
    rows = {}
    for line in block.splitlines():
        if line.startswith("| steward."):
            cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
            rows[cells[0]] = cells
    return rows


def header_cells(block):
    for line in block.splitlines():
        if line.startswith("| Profile"):
            return [c.strip() for c in line.strip().strip("|").split(" | ")]
    return None


class RenderCase(PlanTestCase):
    def operator(self):
        self.user_plan(doc_operator_plan())
        self.user_settings(dict(PHASE0_SETTINGS, defaultThinkingLevel="xhigh"))

    def block(self, capped=True, **kw):
        return render.render_block(self.run_plan(**kw), capped=capped)

    def assert_clean(self, text):
        self.assertNotIn(EM_DASH, text)
        self.assertIsNone(BOX_DRAWING.search(text))
        for line in text.splitlines():
            if line.startswith("|-"):
                self.assertRegex(line, r"^\|(-\|)+$")


class OperatorCaseTests(RenderCase):
    def test_main_on_sol(self):
        self.operator()
        block = self.block(main=SOL)
        self.assert_clean(block)
        lines = block.splitlines()
        self.assertEqual(lines[0], "## Model plan on this machine (generated at session start; rebuilt on a model or thinking switch)")
        self.assertIn("Main thread: openai-codex/gpt-6.1-sol at xhigh. In the plan: yes. Judgment-grade: yes.", lines)
        self.assertNotIn("STEWARD WARNING", block)
        self.assertEqual(len(header_cells(block)), 7)
        self.assertIn("|-|-|-|-|-|-|-|", lines)
        rows = table_rows(block)
        self.assertEqual(sorted(rows), sorted("steward." + r for r in mp.ROLES))
        self.assertEqual(rows["steward.coder"], [
            "steward.coder", OLLAMA, "high", "no", "deepseek", FIREWORKS + ":high", SOL + ":high"])
        self.assertEqual(rows["steward.mechanic"][2], "low")
        self.assertEqual(rows["steward.mechanic"][6], SOL + ":low")
        self.assertEqual(rows["steward.reviewer"], [
            "steward.reviewer", SONNET, "high", "no", "claude", SOL + ":medium", "use steward.deep-reasoner"])
        self.assertEqual(rows["steward.deep-reasoner"], [
            "steward.deep-reasoner", SOL + " (inherits the main thread)", "xhigh", "yes", "gpt",
            OPUS + ":xhigh", "keep it on the main thread"])
        self.assertEqual(rows["steward.top-reviewer"], [
            "steward.top-reviewer", OPUS, "xhigh", "yes", "claude", "anthropic/claude-opus-5-5:xhigh",
            "keep it on the main thread"])
        self.assertIn("At most 3 children at a time on ollama-cloud.", lines)

    def test_main_on_opus(self):
        self.operator()
        block = self.block(main=OPUS)
        self.assert_clean(block)
        self.assertIn("Main thread: amorphic/claude-opus-5-5 at xhigh. In the plan: yes. Judgment-grade: yes.",
                      block.splitlines())
        rows = table_rows(block)
        # byMainProvider.amorphic moves the reviewer to Sol; its only
        # fallback is then the bound model, so no relaunch is left.
        self.assertEqual(rows["steward.reviewer"], [
            "steward.reviewer", SOL, "medium", "yes", "gpt", "none", "use steward.deep-reasoner"])
        self.assertEqual(rows["steward.deep-reasoner"][1], OPUS + " (inherits the main thread)")
        # The bound model (main, Opus) equals the first fallback, so Sol is next.
        self.assertEqual(rows["steward.deep-reasoner"][5], SOL + ":xhigh")
        self.assertEqual(rows["steward.coder"][6], OPUS + ":high")
        self.assertIn("At most 3 children at a time on ollama-cloud.", block.splitlines())

    def test_main_not_in_plan_warns_first(self):
        self.operator()
        block = self.block(main=SONNET, thinking="high")
        lines = block.splitlines()
        self.assertTrue(lines[1].startswith("STEWARD WARNING:"), lines[1])
        warnings = [l for l in lines if l.startswith("STEWARD WARNING:")]
        main_index = next(i for i, l in enumerate(lines) if l.startswith("Main thread:"))
        self.assertTrue(all(lines.index(w) < main_index for w in warnings))
        joined = "\n".join(warnings)
        self.assertIn("not in main.models", joined)
        self.assertIn("/model", joined)
        self.assertIn("outside judgmentModels", joined)
        self.assertIn("steward.deep-reasoner", joined)  # inherits the main thread
        self.assertIn("/thinking", joined)
        self.assertIn("In the plan: no. Judgment-grade: no.", block)
        # main-thread findings are not repeated as finding lines
        self.assertEqual(sum("not in main.models" in l for l in lines), 1)

    def test_no_plan_file_gives_five_columns(self):
        self.user_settings(PHASE0_SETTINGS)
        block = self.block(main=SOL)
        self.assert_clean(block)
        self.assertEqual(header_cells(block), ["Profile", "Runs on", "Thinking", "Judgment-grade", "Family"])
        self.assertIn("|-|-|-|-|-|", block.splitlines())
        rows = table_rows(block)
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(len(cells) == 5 for cells in rows.values()))
        self.assertEqual(rows["steward.coder"][:3], ["steward.coder", OLLAMA, "high"])
        self.assertEqual(rows["steward.coder"][3], "not checked")
        self.assertIn("In the plan: no plan file.", block)
        self.assertNotIn("children at a time", block)

    def test_no_plan_no_settings_lists_frontmatter_models(self):
        rows = table_rows(self.block(main=SOL))
        self.assertTrue(rows["steward.coder"][1].startswith("anthropic/claude-") or
                        rows["steward.coder"][1].startswith("amorphic/claude-"), rows["steward.coder"])


class BlockedTests(RenderCase):
    def test_untrusted_repo_denying_flash_providers(self):
        self.operator()
        self.project_plan({"denyProviders": ["ollama-cloud", "fireworks"]})
        block = self.block(main=SOL, trusted=False)
        self.assert_clean(block)
        rows = table_rows(block)
        for role in ("coder", "researcher", "writer", "mechanic"):
            self.assertIn("blocked", rows["steward." + role][1])
            self.assertIn("Do not launch steward.%s" % role, block)
        for role in ("reviewer", "deep-reasoner", "top-reviewer"):
            self.assertNotIn("blocked", rows["steward." + role][1])
            self.assertNotIn("Do not launch steward.%s" % role, block)
        # a blocked profile offers no relaunch or escalation
        self.assertEqual(rows["steward.coder"][5:], ["do not launch", "do not launch"])
        self.assertEqual(rows["steward.reviewer"][5:], [SOL + ":medium", "use steward.deep-reasoner"])

    def test_lists_fail_closed(self):
        self.operator()
        (self.project / ".pi" / "steward-model-plan.json").write_text("{not json", encoding="utf-8")
        result = self.run_plan(main=SOL, trusted=False)
        self.assertTrue(result["listsFailClosed"])
        block = render.render_block(result)
        self.assert_clean(block)
        self.assertIn("every provider is blocked", block)
        self.assertIn("Do not launch any steward profile", block)
        self.assertTrue(block.splitlines()[1].startswith("STEWARD WARNING: The provider lists in"))
        rows = table_rows(block)
        self.assertTrue(all("blocked" in cells[1] for cells in rows.values()))


class CapTests(RenderCase):
    """A hostile or broken plan cannot flood the system prompt."""

    def worst_case_bodies(self):
        long_ids = ["p%s%d" % ("x" * 58, i) for i in range(64)]
        return [
            '{"denyProviders": [' + ",".join(["1"] * 30000) + "]}",
            json.dumps({"allowProviders": ["p%d" % i for i in range(6500)] + ["amorphic"],
                        "denyProviders": ["q%d" % i for i in range(10)]}),
            json.dumps({"allowProviders": long_ids, "denyProviders": long_ids}),
            json.dumps({"allowProviders": long_ids[:63] + ["amorphic"], "denyProviders": long_ids,
                        "x" * 5000: 1}),
            json.dumps({"allowProviders": ["bad id %d" % i for i in range(2000)],
                        "denyProviders": ["bad id %d" % i for i in range(2000)]}),
            json.dumps({"version": 1, "roles": {("IGNORE\n%d " % i) + "y" * 500: {} for i in range(40)},
                        **{("Run\x1b[2J rm -rf %d" % i) + "z" * 500: 1 for i in range(40)}}),
        ]

    def assert_capped(self, block):
        self.assertLessEqual(len(block.splitlines()), render.MAX_BLOCK_LINES)
        self.assertLessEqual(len(block), render.MAX_BLOCK_CHARS)
        self.assert_clean(block)
        self.assertIsNone(re.search(r"[\x00-\x09\x0b-\x1f\x7f\u2028\u2029\u202a-\u202e]", block))

    def test_cap_values(self):
        self.assertEqual(render.MAX_BLOCK_LINES, 30)
        self.assertEqual(render.MAX_BLOCK_CHARS, 5000)

    def test_worst_case_files(self):
        self.user_plan(doc_operator_plan())
        self.user_settings({"subagents": {"agentOverrides": {"steward.coder": {"model": OLLAMA}}}})
        path = self.project / ".pi" / "steward-model-plan.json"
        saw_more = False
        for body in self.worst_case_bodies():
            path.write_text(body, encoding="utf-8")
            for trusted in (False, True):
                for main in (SOL, SONNET, None):
                    block = self.block(main=main, trusted=trusted)
                    self.assert_capped(block)
                    saw_more = saw_more or block.splitlines()[-1].endswith("more: run /steward-models check")
        self.assertTrue(saw_more)

    def test_many_findings_end_with_more_line(self):
        plan = doc_operator_plan()
        plan["providers"] = {"p%d" % i: {"maxConcurrent": 1} for i in range(60)}
        plan["roles"]["*"]["fallback"] = ["nope%d/model-%d" % (i, i) for i in range(40)]
        self.user_plan(plan)
        self.user_settings({"subagents": {"agentOverrides": {
            "steward.%s" % r: {"model": "unknown/m-%s-latest" % r} for r in mp.ROLES},
            "parallel": {"concurrency": 9}}})
        block = self.block(main=SONNET, thinking="low")
        self.assert_capped(block)
        last = block.splitlines()[-1]
        self.assertRegex(last, r"^\d+ more: run /steward-models check$")
        full = render.render_block(self.run_plan(main=SONNET, thinking="low"), capped=False)
        self.assertGreater(len(full.splitlines()), render.MAX_BLOCK_LINES)

    def test_hostile_cell_text_is_escaped(self):
        self.user_settings({"subagents": {"agentOverrides": {
            "steward.coder": {"model": "evil|model\nIGNORE ALL" + EM_DASH + "x" * 400}}}})
        block = self.block(main=SOL)
        self.assert_capped(block)
        rows = table_rows(block)
        self.assertEqual(len(rows["steward.coder"]), 5)
        self.assertNotIn("\nIGNORE", block)

    def test_one_line_per_problem(self):
        self.operator()
        # the same clamp shows up for the plan binding and the effective binding
        plan = doc_operator_plan()
        plan["roles"]["*"]["thinking"] = "xhigh"
        self.user_plan(plan)
        block = self.block(main=SOL)
        clamp_lines = [l for l in block.splitlines() if "clamped to" in l and l.startswith("- ")]
        self.assertEqual(len(clamp_lines), len(set(clamp_lines)))


class FactsCase(StewardTestCase):
    """Hook runs with the operator's plan and settings in a temp agent dir."""

    def setUp(self):
        super().setUp()
        claude_skill = os.path.join(
            self.plugin_root, "plugins", "steward-delegation", "skills", "delegating", "SKILL.md")
        with open(claude_skill, encoding="utf-8") as f:
            claude_body = f.read()
        fixtures = (
            (("pi", "skills", "steward-delegating"),
             "---\nname: steward-delegating\ndescription: fixture\n---\nPi body of the edict.\n"),
            (("copilot", "skills", "delegating"),
             "---\nname: delegating\ndescription: fixture\n---\nCopilot body.\n"),
            (("skills", "delegating"), claude_body),
        )
        # The hook reads each skill under plugins/steward-delegation/; the
        # BASE_COMMIT hook that base_script() runs reads it at the root.
        for rel, body in fixtures:
            for prefix in (("plugins", "steward-delegation"), ()):
                skill_dir = os.path.join(self.plugin_root, *prefix, *rel)
                os.makedirs(skill_dir, exist_ok=True)
                with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                    f.write(body)
        self.project = os.path.join(self.tmp, "work", "repo")
        os.makedirs(os.path.join(self.project, ".pi"), exist_ok=True)
        plan_dir = os.path.join(self.config, "steward")
        os.makedirs(plan_dir, exist_ok=True)
        with open(os.path.join(plan_dir, "model-plan.json"), "w", encoding="utf-8") as f:
            json.dump(doc_operator_plan(), f)
        with open(os.path.join(self.config, "settings.json"), "w", encoding="utf-8") as f:
            json.dump(PHASE0_SETTINGS, f)

    def facts(self, main=SOL):
        provider, _, mid = main.partition("/")
        return {"main": {"provider": provider, "id": mid, "thinkingLevel": "xhigh"},
                "models": copy.deepcopy(CATALOG), "projectTrusted": True, "cwd": self.project}

    def pi_env(self):
        return self.make_env(STEWARD_HARNESS="pi", PI_CODING_AGENT_DIR=self.config)

    def run_text(self, script, subcommand, payload, env, raw=None):
        result = subprocess.run([sys.executable, str(script), subcommand],
                                input=raw if raw is not None else json.dumps(payload),
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def base_script(self):
        """steward_hook.py as it was at BASE_COMMIT, written to a temp dir."""
        try:
            source = subprocess.run(["git", "-C", str(REPO_ROOT), "show", "%s:hooks/steward_hook.py" % BASE_COMMIT],
                                    capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            message = ("base commit %s is not in this checkout, so the regression tests cannot run; fetch it, "
                       "or set %s=1 to skip them" % (BASE_COMMIT, ALLOW_MISSING_BASE_ENV))
            if os.environ.get(ALLOW_MISSING_BASE_ENV) == "1":
                self.skipTest(message)
            self.fail(message)
        path = Path(self.tmp) / "base" / "hooks" / "steward_hook.py"
        path.parent.mkdir(parents=True)
        path.write_bytes(source)
        return path

    def pi_env_dict(self):
        return self.env_dict(STEWARD_HARNESS="pi", PI_CODING_AGENT_DIR=self.config)


class FailOpenTests(FactsCase):
    """Session start appends the block only for harness pi with valid facts."""

    def test_pi_without_facts_matches_base(self):
        base = self.base_script()
        env = self.pi_env()
        for payload, raw in (({"session_id": "s1"}, None), ({}, None), (None, "not json"),
                             ({"session_id": "s1", "model_facts": None}, None)):
            self.assertEqual(self.run_text(HOOKS / "steward_hook.py", "session-start", payload, env, raw),
                             self.run_text(base, "session-start", payload, env, raw))

    def test_pi_with_facts_appends_block(self):
        base = self.base_script()
        env = self.pi_env()
        today = json.loads(self.run_text(base, "session-start", {"session_id": "s1"}, env))
        out = json.loads(self.run_text(HOOKS / "steward_hook.py", "session-start",
                                       {"session_id": "s1", "model_facts": self.facts()}, env))
        text = out["hookSpecificOutput"]["additionalContext"]
        before = today["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(text.startswith(before + "\n\n## Model plan on this machine"), text[:400])
        self.assertIn("| steward.coder | %s | high |" % OLLAMA, text)
        self.assertEqual(set(out), set(today))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_other_harnesses_ignore_facts(self):
        base = self.base_script()
        payloads = ({"session_id": "s1"}, {"session_id": "s1", "model_facts": self.facts()})
        for harness in ("claude", "copilot"):
            env = self.make_env(STEWARD_HARNESS=harness, COPILOT_HOME=self.config)
            outputs = {self.run_text(script, "session-start", p, env)
                       for script in (HOOKS / "steward_hook.py", base) for p in payloads}
            self.assertEqual(len(outputs), 1, harness)
        env = self.make_env(STEWARD_HARNESS="codex", CODEX_HOME=self.config)
        codex = REPO_ROOT / "codex" / "steward.py"
        self.assertEqual(self.run_text(codex, "session-start", payloads[0], env),
                         self.run_text(codex, "session-start", payloads[1], env))

    def test_fail_open_cases(self):
        base = self.base_script()
        env = self.pi_env()
        today = self.run_text(base, "session-start", {"session_id": "s1"}, env)
        bad = self.facts()
        del bad["models"]
        wrong_types = self.facts()
        wrong_types["projectTrusted"] = "yes"
        for facts in (bad, wrong_types, "facts", [1, 2], 7, {"main": None}):
            self.assertEqual(self.run_text(HOOKS / "steward_hook.py", "session-start",
                                           {"session_id": "s1", "model_facts": facts}, env), today, facts)

    def test_exception_inside_evaluate_fails_open(self):
        env = self.pi_env_dict()
        payload = {"session_id": "s1", "model_facts": self.facts()}
        without = hook.cmd_session_start({"session_id": "s1"}, env)
        self.assertIn("## Model plan", hook.cmd_session_start(payload, env))
        model_plan = importlib.import_module("model_plan")
        with mock.patch.object(model_plan, "_evaluate", side_effect=RuntimeError("boom")):
            self.assertEqual(hook.cmd_session_start(payload, env), without)
        with mock.patch.object(model_plan, "evaluate", side_effect=RuntimeError("boom")):
            self.assertEqual(hook.cmd_session_start(payload, env), without)
        with mock.patch.object(render, "render_block", side_effect=ValueError("bad")):
            self.assertEqual(hook.cmd_session_start(payload, env), without)

    def test_real_size_facts_are_fast(self):
        facts = self.facts()
        for i in range(1600):
            facts["models"].append(model("prov%d/model-%d" % (i % 40, i), max_tokens=8192 + i,
                                         available=bool(i % 3)))
        env = self.pi_env()
        start = time.monotonic()
        out = self.run_text(HOOKS / "steward_hook.py", "session-start",
                            {"session_id": "s1", "model_facts": facts}, env)
        elapsed = time.monotonic() - start
        self.assertIn("## Model plan", out)
        self.assertLess(elapsed, 2.0)


class ModelPlanSubcommandTests(FactsCase):
    def run_cmd(self, raw, env=None):
        return subprocess.run([sys.executable, str(HOOKS / "steward_hook.py"), "model-plan"],
                              input=raw, capture_output=True, text=True, env=env or self.pi_env())

    def test_report_has_every_finding_and_source(self):
        facts = self.facts(main=SONNET)
        out = self.run_cmd(json.dumps({"model_facts": facts, "cwd": self.project}))
        self.assertEqual(out.returncode, 0, out.stderr)
        report = json.loads(out.stdout)["report"]
        self.assertNotIn(EM_DASH, report)
        evaluated = mp.evaluate(facts, env=self.pi_env())
        self.assertTrue(evaluated["findings"])
        for f in evaluated["findings"]:
            self.assertIn(f["message"], report)
            self.assertIn("%s %s" % (f["severity"], f["code"]), report)
            if f["source"]:
                self.assertIn(f["source"], report)
        for role, row in evaluated["roles"].items():
            src = row["effective"]["modelSource"]["file"]
            if src:
                self.assertIn(src, report)
        self.assertIn(os.path.join(self.config, "steward", "model-plan.json"), report)
        self.assertIn("## Model plan on this machine", report)
        self.assertNotIn("more: run /steward-models check", report)

    def test_cwd_fills_missing_facts_cwd(self):
        facts = self.facts()
        del facts["cwd"]
        out = self.run_cmd(json.dumps({"model_facts": facts, "cwd": self.project}))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("report", json.loads(out.stdout))

    def test_writes_nothing(self):
        before = sorted(str(p) for p in Path(self.tmp).rglob("*"))
        self.run_cmd(json.dumps({"model_facts": self.facts()}))
        self.assertEqual(sorted(str(p) for p in Path(self.tmp).rglob("*")), before)

    def test_bad_input_exits_nonzero(self):
        bad_facts = self.facts()
        bad_facts["models"] = "x"
        for raw in ("", "not json", "[1]", json.dumps({"cwd": "/"}), json.dumps({"model_facts": bad_facts})):
            out = self.run_cmd(raw)
            self.assertNotEqual(out.returncode, 0, raw)
            self.assertIn("model-plan:", out.stderr)
            self.assertIn("error", json.loads(out.stdout))

    def test_pi_only(self):
        out = self.run_cmd(json.dumps({"model_facts": self.facts()}), env=self.make_env())
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("pi", out.stderr)


if __name__ == "__main__":
    unittest.main()
