"""Drift guard: the pi-subagents mirrors in hooks/model_plan.py against the
installed pi-subagents.

A fixed corpus of model spellings, provider-id segments, package names and
agent frontmatter runs through both the Python mirror and the installed
pi-subagents (via tests/pi/resolve_model.mjs), and every result must agree.
The mirrors were read against PI_SUBAGENTS_MIRRORED; another installed
version fails test_installed_version_is_the_mirrored_one until the mirrors
are re-verified.

pi-subagents is found at $PI_SUBAGENTS_DIR, else
~/.pi/agent/npm/node_modules/pi-subagents. Without node or the package the
tests skip and say why.
"""

import json
import os
import hashlib
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from test_pi_model_plan import mp

PI_SUBAGENTS_MIRRORED = "0.78.0"
HELPER = Path(__file__).resolve().parent / "pi" / "resolve_model.mjs"

# The mirrors that are not differential-tested here; re-read them on a version change.
NON_DIFFERENTIAL_MIRRORS = (
    "PS/src/agents/agents.js:1073-1132,1237-1257,1374-1387 (override layering, defaults, false clears)",
    "PS/src/agents/agents.js:573-652 (findConfiguredProjectRoot)",
    "PS/src/agents/agents.js:1611-1758,1891-1910,2253-2414 (agent discovery, runtime names, scan dirs)",
    "PS/src/agents/agents.js:2563 (modelScope project ?? user)",
    "PS/src/agents/agent-selection.js:1-21 (later sources replace earlier ones)",
    "PS/src/runs/shared/model-scope.js:22-64,115-145 (modelScope globs and checks)",
    "PS/src/runs/shared/child-tool-plan.js:48-57 (:level suffix)",
)


def pi_subagents_dir():
    value = os.environ.get("PI_SUBAGENTS_DIR")
    if value:
        return Path(value)
    return Path(os.path.expanduser("~")) / ".pi" / "agent" / "npm" / "node_modules" / "pi-subagents"


def skip_reason():
    if not shutil.which("node"):
        return "node is not on PATH; the pi-subagents drift guard needs it"
    directory = pi_subagents_dir()
    if not (directory / "package.json").is_file():
        return "pi-subagents is not installed at %s (set PI_SUBAGENTS_DIR)" % directory
    return None


CATALOG = [
    ("ollama-cloud", "deepseek-v4.1-flash"), ("fireworks", "accounts/fireworks/models/deepseek-v4p1-flash"),
    ("openai-codex", "gpt-6.1-sol"), ("amorphic", "claude-opus-5-5"), ("anthropic", "claude-opus-5-5"),
    ("anthropic", "claude-sonnet-5-5-20260101"), ("amorphic", "claude-sonnet-5-5"),
    ("openrouter", "openrouter/auto-beta"), ("openrouter", "deepseek/deepseek-v4.1-flash"),
    ("huggingface", "Qwen/Qwen3-Coder"), ("my.provider", "x-model"), ("Ollama_Cloud", "kimi-k3"),
    ("ollama-cloud", "kimi-k3"), ("deepseek", "deepseek-v4.1-flash"), ("anthropic", "claude-haiku-5-5:thinking"),
    ("openai", "gpt-6.1-sol"),
]
LEVELS = ("", ":high", ":max", ":off", ":bogus")
HOMOGLYPHS = {"a": "\u0430", "o": "\u043e", "e": "\u0435", "i": "\u0456", "c": "\u0441", "p": "\u0440",
              "k": "\u212a"}
# The fail-open spellings of the first review (B1), against a deny on ollama-cloud.
B1_SPELLINGS = (
    "Ollama-Cloud/deepseek-v4.1-flash", "ollama-cloud:deepseek-v4.1-flash", "deepseek-v4-1-flash",
    "ollama_cloud/deepseek_v4.1_flash", "ollama-cloud/deepseek-v4.1-flash/", "/ollama-cloud/deepseek-v4.1-flash",
    "amorphic/ollama-cloud/deepseek-v4.1-flash", "\u043ellama-cloud/deepseek-v4.1-flash",
    "ollama-cloud/deepseek-v4.1-flash:high", "ollama-cloud/deepseek-v4.1-flash:bogus",
    " ollama-cloud/deepseek-v4.1-flash ", "claude-opus-5-5",
)


def mutations(provider, mid):
    homo = lambda text: "".join(HOMOGLYPHS.get(ch, ch) for ch in text)
    full = "%s/%s" % (provider, mid)
    return [
        full, mid, "%s:%s" % (provider, mid), "%s.%s" % (provider, mid), full.upper(), full + "/", "/" + full,
        "%s//%s" % (provider, mid), "%s/%s" % (provider, full), "%s/%s" % (provider.replace("-", "_"),
                                                                          mid.replace(".", "_")),
        mid.replace(".", "-"), mid + "-20260101", mid + "-2026-01-01", full + "-20991231", " %s " % full,
        "%s /%s" % (provider, mid), mid.title(), homo(full), homo(mid), "%s\u200b/%s" % (provider, mid),
        full.replace("-", "\u2013"), full.replace("o", "\uff4f"), "%s-/%s" % (provider, mid),
        "-%s/%s" % (provider, mid), "%s/-%s-" % (provider, mid), mid.replace("-", "."), "%s::%s" % (provider, mid),
        "%s:%s" % (full, mid), mid.split("/")[-1], "%s/%s" % (provider, mid.split("/")[-1]), "\u0130" + mid,
        mid.upper().replace("I", "\u0130"),
    ]


PREFERRED = (None, "anthropic", "amorphic", "ollama-cloud", "Ollama-Cloud")


def resolve_corpus():
    """Deterministic, deduplicated cases. Every catalog entry and spelling runs bare against every preferred
    provider; each :level suffix runs once per spelling with the preferred provider rotating, so all levels
    meet all providers across the corpus; restricted availability uses rotating catalog windows."""
    providers = sorted({p for p, _ in CATALOG})
    rotation = list(PREFERRED) + providers
    cases, seen = [], set()

    def add(model, avail, pref):
        key = (model, tuple(avail), pref)
        if model.strip() and model.strip() != "inherit" and key not in seen:
            seen.add(key)
            cases.append({"model": model, "avail": list(avail), "preferred": pref})

    step = 0
    for provider, mid in CATALOG:
        for spelling in mutations(provider, mid):
            for pref in PREFERRED + (providers[step % len(providers)],):
                add(spelling, CATALOG, pref)
            for li, level in enumerate(LEVELS[1:]):
                add(spelling + level, CATALOG, rotation[(step + li * 5) % len(rotation)])
            step += 1
    n = len(CATALOG)
    for k in range(40):
        subset = [CATALOG[(k + j) % n] for j in range(1 + k % n)]
        for t in range(4):
            provider, mid = CATALOG[(k * 5 + t * 3) % n]
            spellings = mutations(provider, mid)
            for u in range(6):
                add(spellings[(k + u * 5) % len(spellings)], subset, rotation[(k + t + u) % len(rotation)])
    for spelling in B1_SPELLINGS:
        for pref in (None, "anthropic", "amorphic", "ollama-cloud"):
            add(spelling, CATALOG, pref)
    return cases


def wire_corpus(resolve_cases, normalize_cases):
    """The helper payload: each distinct availability list is sent once and cases refer to it by index."""
    avails, index = [], {}
    rows = []
    for case in resolve_cases:
        key = tuple(map(tuple, case["avail"]))
        if key not in index:
            index[key] = len(avails)
            avails.append([list(pair) for pair in key])
        rows.append([case["model"], index[key], case["preferred"]])
    return {"avails": avails, "resolve": rows, "normalize": normalize_cases, "package": PACKAGE_NAMES,
            "frontmatter": FRONTMATTER}


PACKAGE_NAMES = ["steward", "Steward", "STEWARD", "steward.", ".steward", " steward ", "-Steward-", "my pkg",
                 "a..b", "a--b", "a_b", "\u00e9t\u00e9", "!!!", "   ", "", "a.-b", "x\u00a0y", "x\ufeffy",
                 "\u212aelvin", "steward\u200b", "1abc", "a.b.c", "A B\tC", "steward\n"]
FRONTMATTER = [
    "---\nname: coder\npackage: Steward\ndescription: x\n---\n",
    "---\nname:\n  steward.coder\ndescription: x\n---\n",
    "---\nname: |\n  steward.coder\ndescription: x\n---\n",
    "---\nname: >-\n  steward.coder\ndescription: >\n  one\n  two\n\n  three\n    four\n---\nbody",
    "---\nname: 'coder'\npackage: \"steward\"\ndescription: \"\n---\n",
    "---\n\"name\": steward.coder\nNAME: x\n name: y\ndescription: x\n---\n",
    "---\r\nname: coder # comment\r\ndescription: x\r\n---\r\n",
    "---\ntools:\n  - a\n  - b\nmodel: x/y\nthinking: high\n---\n",
    "---\nname: |-\n  line one\n\n  line two\ndescription: x\n---",
    "no frontmatter\nname: x\n",
    "---\nname: x\n",
    "\ufeff---\nname: x\ndescription: y\n---\n",
    "---\nkey_with-dash: v\nempty:\nlast: |\n",
    "---\nname:   steward.coder   \ndescription:\tx\t\n---\n",
    "---\nname: a\u2028b\ndescription: x\n---\n",
]


HELPER_INPUT_CORRUPTED = 3  # resolve_model.mjs: stdin did not match the sha256 it was given
HELPER_ATTEMPTS = 3
MIRROR_DRIFT = "the mirror in plugins/steward-delegation/hooks/model_plan.py and the installed pi-subagents disagree: re-verify the mirror"


class TransportFault(Exception):
    """The payload or the result was damaged between the two processes, or the helper died on a signal."""


def run_helper_once(payload):
    proc = subprocess.run(["node", str(HELPER), str(pi_subagents_dir()), hashlib.sha256(payload).hexdigest()],
                          input=payload, capture_output=True, timeout=120)
    stderr = proc.stderr.decode("utf-8", "replace")[-2000:]
    if proc.returncode < 0:
        raise TransportFault("resolve_model.mjs died on signal %d: %s" % (-proc.returncode, stderr))
    if proc.returncode == HELPER_INPUT_CORRUPTED:
        raise TransportFault(stderr.strip() or "input corrupted in transit")
    if proc.returncode != 0:
        raise AssertionError("resolve_model.mjs failed (exit %d): %s" % (proc.returncode, stderr))
    digest, _, body = proc.stdout.partition(b"\n")
    if hashlib.sha256(body).hexdigest().encode() != digest:
        raise TransportFault("resolve_model.mjs output corrupted in transit")
    return json.loads(body)


def run_helper(corpus):
    """Run the helper, retrying only transport faults; a wrong answer is the caller's to report."""
    payload = json.dumps(corpus, separators=(",", ":")).encode("utf-8")
    faults = []
    for _ in range(HELPER_ATTEMPTS):
        try:
            return run_helper_once(payload), faults
        except TransportFault as fault:
            faults.append(str(fault))
    raise AssertionError("resolve_model.mjs failed %d times in transit: %s" % (HELPER_ATTEMPTS, " | ".join(faults)))


class HelperRetryTests(unittest.TestCase):
    def run_with(self, outcomes):
        calls = []

        def fake(payload):
            calls.append(payload)
            outcome = outcomes[len(calls) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        original = globals()["run_helper_once"]
        globals()["run_helper_once"] = fake
        try:
            return run_helper({}), calls
        finally:
            globals()["run_helper_once"] = original

    def test_transport_faults_retry_up_to_two_more_times(self):
        (result, faults), calls = self.run_with([TransportFault("a"), TransportFault("b"), {"ok": 1}])
        self.assertEqual((result, faults, len(calls)), ({"ok": 1}, ["a", "b"], 3))
        with self.assertRaisesRegex(AssertionError, "failed 3 times in transit"):
            self.run_with([TransportFault("a")] * 3 + [{"ok": 1}])

    def test_a_helper_error_does_not_retry(self):
        with self.assertRaisesRegex(AssertionError, "exit 1"):
            self.run_with([AssertionError("resolve_model.mjs failed (exit 1)"), {"ok": 1}])


@unittest.skipIf(skip_reason(), skip_reason() or "")
class ResolverDriftGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolve_cases = resolve_corpus()
        cls.normalize_cases = sorted({c["model"] for c in cls.resolve_cases} | set(PACKAGE_NAMES))
        cls.js, cls.transport_faults = run_helper(wire_corpus(cls.resolve_cases, cls.normalize_cases))
        for fault in cls.transport_faults:
            print("drift guard retried after a transport fault: %s" % fault, file=sys.stderr)

    def test_helper_answered_every_case(self):
        for key, sent in (("resolve", self.resolve_cases), ("normalize", self.normalize_cases),
                          ("package", PACKAGE_NAMES), ("frontmatter", FRONTMATTER)):
            self.assertEqual(len(self.js[key]), len(sent), key)

    def test_helper_rejects_a_payload_that_does_not_match_its_sha256(self):
        payload = json.dumps(wire_corpus(self.resolve_cases[:3], [])).encode("utf-8")
        proc = subprocess.run(["node", str(HELPER), str(pi_subagents_dir()), hashlib.sha256(b"other").hexdigest()],
                              input=payload, capture_output=True, timeout=60)
        self.assertEqual(proc.returncode, HELPER_INPUT_CORRUPTED)
        self.assertIn(b"input corrupted in transit", proc.stderr)

    def test_installed_version_is_the_mirrored_one(self):
        self.assertEqual(
            self.js["version"], PI_SUBAGENTS_MIRRORED,
            "pi-subagents %s is installed but plugins/steward-delegation/hooks/model_plan.py mirrors %s: re-verify the mirror, then update "
            "PI_SUBAGENTS_MIRRORED. The differential tests here cover model resolution, normalizeModelSegment, "
            "parsePackageName and parseFrontmatter; re-read these by hand: %s"
            % (self.js["version"], PI_SUBAGENTS_MIRRORED, "; ".join(NON_DIFFERENTIAL_MIRRORS)))

    def test_model_resolution_matches(self):
        self.assertGreater(len(self.resolve_cases), 4000)
        mismatches = []
        for case, js in zip(self.resolve_cases, self.js["resolve"]):
            avail = [{"provider": p, "id": i} for p, i in case["avail"]]
            request = case["model"].strip()  # resolveSubagentModelOverride trims first
            py = mp.resolve_subagent_model(request, avail, case["preferred"]) or request
            if py != js:
                mismatches.append((case["model"], case["preferred"], len(case["avail"]), py, js))
        self.assertEqual(mismatches[:10], [],
                         "%s: %d of %d differ" % (MIRROR_DRIFT, len(mismatches), len(self.resolve_cases)))

    def test_b1_spellings_resolve_alike(self):
        b1 = [c for c in self.resolve_cases if c["model"] in B1_SPELLINGS]
        self.assertGreaterEqual(len(b1), len(B1_SPELLINGS) * 4)

    def test_normalize_segment_matches(self):
        mismatches = [(s, mp.normalize_segment(s), js) for s, js in zip(self.normalize_cases, self.js["normalize"])
                      if mp.normalize_segment(s) != js]
        self.assertEqual(mismatches[:10], [], MIRROR_DRIFT)

    def test_package_names_match(self):
        for raw, js in zip(PACKAGE_NAMES, self.js["package"]):
            if raw == "":
                py = {"packageName": None}
            else:
                name = mp.normalize_package_name(raw)
                py = {"packageName": name} if name and mp.PACKAGE_ID_RE.match(name) else {"error": True}
            self.assertEqual(py, js, "%s: %r" % (MIRROR_DRIFT, raw))

    def test_frontmatter_matches(self):
        for text, js in zip(FRONTMATTER, self.js["frontmatter"]):
            self.assertEqual(mp.parse_frontmatter(text), js, "%s: %r" % (MIRROR_DRIFT, text))


if __name__ == "__main__":
    unittest.main()
