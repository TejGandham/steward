"""Phase 4: the per-launch outcome log summarizer (hooks/delegation_stats.py) and the
`delegation-stats` hook subcommand behind /steward-models stats."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN_HOOKS = os.path.join(os.path.dirname(HERE), "plugins", "steward-delegation", "hooks")
HOOK = os.path.join(os.path.dirname(HERE), "hooks", "steward_hook.py")
sys.path.insert(0, PLAN_HOOKS)
sys.path.insert(0, HERE)

import delegation_stats as ds  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400.0
FLASH = "ollama-cloud/deepseek-v4.1-flash"
SONNET = "anthropic/claude-sonnet-5-5"


def line(agent="steward.mechanic", model=FLASH, status="ok", duration=1000, kind="plain", age_days=0.5,
         error_class=None, **extra):
    from datetime import datetime, timezone
    ts = datetime.fromtimestamp(NOW - age_days * DAY, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    row = {"v": 1, "ts": ts, "agent": agent, "model": model, "thinking": "low", "status": status,
           "isError": status != "ok", "errorClass": error_class, "durationMs": duration, "mode": "sync",
           "kind": kind}
    row.update(extra)
    return json.dumps(row)


class PercentileTests(unittest.TestCase):
    def test_nearest_rank(self):
        values = list(range(1, 11))
        self.assertEqual(ds.percentile(values, 50), 5)
        self.assertEqual(ds.percentile(values, 90), 9)
        self.assertEqual(ds.percentile([7], 90), 7)
        self.assertIsNone(ds.percentile([], 50))


class SummarizeTests(unittest.TestCase):
    def test_groups_by_profile_and_model_with_rates_and_kinds(self):
        lines = [
            line(duration=1000),
            line(duration=3000),
            line(duration=2000, status="error", error_class="provider"),
            line(duration=4000, status="error", error_class="other", kind="relaunch"),
            line(agent="steward.coder", model=SONNET, duration=5000, kind="escalation"),
        ]
        summary = ds.summarize(lines, now=NOW, days=7)
        rows = {(r["agent"], r["model"]): r for r in summary["rows"]}
        mech = rows[("steward.mechanic", FLASH)]
        self.assertEqual(mech["launches"], 4)
        self.assertEqual(mech["ok"], 2)
        self.assertEqual(mech["providerErrors"], 1)
        self.assertEqual(mech["otherErrors"], 1)
        self.assertAlmostEqual(mech["successRate"], 0.5)
        self.assertEqual(mech["medianMs"], 2000)
        self.assertEqual(mech["p90Ms"], 4000)
        self.assertEqual(mech["relaunches"], 1)
        self.assertEqual(mech["escalations"], 0)
        coder = rows[("steward.coder", SONNET)]
        self.assertEqual((coder["launches"], coder["escalations"]), (1, 1))
        self.assertEqual(summary["corrupt"], 0)

    def test_window_drops_old_lines(self):
        lines = [line(age_days=1), line(age_days=10), line(age_days=29)]
        self.assertEqual(ds.summarize(lines, now=NOW, days=7)["rows"][0]["launches"], 1)
        self.assertEqual(ds.summarize(lines, now=NOW, days=30)["rows"][0]["launches"], 3)

    def test_corrupt_lines_are_skipped_and_counted(self):
        lines = [line(), "not json", "[1,2]", json.dumps({"ts": "garbage", "agent": "x"}),
                 json.dumps({"agent": "steward.coder"}), "", line()]
        summary = ds.summarize(lines, now=NOW, days=7)
        self.assertEqual(summary["corrupt"], 4)
        self.assertEqual(summary["rows"][0]["launches"], 2)

    def test_missing_model_and_duration(self):
        summary = ds.summarize([line(model=None, duration=None)], now=NOW, days=7)
        row = summary["rows"][0]
        self.assertEqual(row["model"], "unknown")
        self.assertIsNone(row["medianMs"])

    def test_v1_and_v2_lines_are_summarized_together(self):
        # 0.14.2 writes v2 lines (cwd is the child's directory, sessionCwd the session's); a
        # log can still hold v1 lines from before the upgrade.
        lines = [
            line(cwd="/repo"),
            line(v=2, cwd="/tmp", sessionCwd="/repo", duration=3000),
        ]
        summary = ds.summarize(lines, now=NOW, days=7)
        self.assertEqual(summary["corrupt"], 0)
        rows = {(r["agent"], r["model"]): r for r in summary["rows"]}
        self.assertEqual(rows[("steward.mechanic", FLASH)]["launches"], 2)
        self.assertEqual(rows[("steward.mechanic", FLASH)]["ok"], 2)

    def test_empty_log(self):
        summary = ds.summarize([], now=NOW, days=7)
        self.assertEqual(summary["rows"], [])
        self.assertIn("No steward launches", ds.render(summary))


class RenderTests(unittest.TestCase):
    def test_table_text(self):
        text = ds.render(ds.summarize([line(duration=1500), line(status="error", error_class="provider")],
                                      now=NOW, days=7))
        self.assertIn("last 7 days", text)
        self.assertIn("|-|", text)
        self.assertIn("steward.mechanic", text)
        self.assertIn(FLASH, text)
        self.assertIn("50%", text)
        self.assertIn("1 provider", text)
        self.assertNotIn("---", text)

    def test_corrupt_count_is_reported(self):
        text = ds.render(ds.summarize([line(), "oops"], now=NOW, days=7))
        self.assertIn("1 corrupt line", text)


class SubcommandTests(unittest.TestCase):
    def run_hook(self, payload, env_extra=None):
        env = dict(os.environ, STEWARD_HARNESS="pi")
        env.update(env_extra or {})
        proc = subprocess.run([sys.executable, HOOK, "delegation-stats"],
                              input=json.dumps(payload), capture_output=True, text=True, env=env)
        return proc.returncode, json.loads(proc.stdout)

    def test_reads_the_given_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            with open(path, "w") as f:
                f.write(line() + "\n" + "junk\n")
            code, out = self.run_hook({"path": path, "days": 7, "now": NOW})
            self.assertEqual(code, 0)
            self.assertIn("steward.mechanic", out["report"])
            self.assertIn("1 corrupt line", out["report"])

    def test_default_path_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ds.log_path({"XDG_STATE_HOME": tmp}),
                             os.path.join(tmp, "steward", "pi-delegations.jsonl"))
            self.assertEqual(ds.log_path({"HOME": tmp}),
                             os.path.join(tmp, ".local", "state", "steward", "pi-delegations.jsonl"))
            code, out = self.run_hook({"days": 7}, {"XDG_STATE_HOME": tmp})
            self.assertEqual(code, 0)
            self.assertIn("No steward launches", out["report"])

    def test_bad_days(self):
        code, out = self.run_hook({"days": 0})
        self.assertEqual(code, 2)
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()


from test_pi_model_plan_render import FactsCase  # noqa: E402


class SessionLaunchesTests(FactsCase):
    """Session start hands the extension each profile's relaunch and escalation strings as
    data, so the outcome log can classify a launch's `kind` without parsing the block."""

    def test_launches_are_structured(self):
        proc = subprocess.run([sys.executable, HOOK, "session-start"],
                              input=json.dumps({"session_id": "s1", "model_facts": self.facts()}),
                              capture_output=True, text=True, env=self.pi_env())
        out = json.loads(proc.stdout)["hookSpecificOutput"]
        launches = out["stewardLaunches"]
        text = out["additionalContext"]
        self.assertIn("steward.coder", launches)
        for agent, entry in launches.items():
            self.assertTrue(agent.startswith("steward."))
            self.assertEqual(set(entry), {"relaunch", "escalation"})
            for value in entry.values():
                if value is not None:
                    self.assertIn(value, text)
        self.assertTrue(any(e["relaunch"] for e in launches.values()))

    def test_no_facts_no_launches(self):
        proc = subprocess.run([sys.executable, HOOK, "session-start"],
                              input=json.dumps({"session_id": "s1"}), capture_output=True, text=True,
                              env=self.pi_env())
        self.assertNotIn("stewardLaunches", json.loads(proc.stdout)["hookSpecificOutput"])
