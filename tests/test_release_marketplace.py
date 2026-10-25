"""Tests for scripts/release_marketplace.sh and the release workflow.

The script is run from a temp clone of this repo, so scratch tags never
reach the real repo, against a temp file:// bare marketplace. The dry-run
test runs the whole pipeline for the existing tag steward-prose-gate--v0.15.0,
including the suite at that tag, and pushes nothing.

These tests need this repo's git history. They skip when it is missing (the
pipeline runs the suite from a `git archive` of the tag, which has no .git)
and inside the pipeline's own suite run (STEWARD_RELEASE_SUITE is set), so
the dry run never calls itself.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "release_marketplace.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-marketplace.yml"
PROSE_TAG = "steward-prose-gate--v0.15.0"

_spec = importlib.util.spec_from_file_location(
    "test_publish_marketplace", Path(__file__).with_name("test_publish_marketplace.py"))
helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helpers)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def has_tag(tag):
    proc = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                          cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.returncode == 0


def tool_path():
    """PATH with git, python3, node and npm but no claude, so runs are repeatable."""
    dirs = []
    for tool in ("git", "python3", "node", "npm", "tar", "bash"):
        found = shutil.which(tool)
        if found and os.path.dirname(found) not in dirs:
            dirs.append(os.path.dirname(found))
    return os.pathsep.join(dirs + ["/usr/bin", "/bin"])


@unittest.skipIf(os.environ.get("STEWARD_RELEASE_SUITE"), "inside the release suite run")
@unittest.skipUnless((REPO_ROOT / ".git").exists(), "needs this repo's git history")
@unittest.skipUnless(has_tag(PROSE_TAG), f"needs local tag {PROSE_TAG}")
class ReleaseScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="release-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "steward"
        git(self.tmp, "clone", "-q", "--no-checkout", REPO_ROOT.as_uri(), str(self.repo))
        self.tag_commit = git(self.repo, "rev-parse", f"{PROSE_TAG}^{{commit}}")
        # origin/main of the clone is whatever this repo's main is; pin it so
        # the test means the same on every checkout.
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.tag_commit)
        seed = self.tmp / "seed"
        seed.mkdir()
        helpers.write_skeleton(seed)
        git(seed, "init", "-q", "-b", "main")
        git(seed, "add", "-A")
        git(seed, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "skeleton")
        self.bare = self.tmp / "marketplace.git"
        git(self.tmp, "clone", "-q", "--bare", str(seed), str(self.bare))
        self.before = git(self.bare, "rev-parse", "main")

    def run_script(self, *args):
        env = dict(os.environ, PATH=tool_path(), **helpers.IDENTITY)
        env.pop("MARKETPLACE_TOKEN", None)
        return subprocess.run(["bash", str(SCRIPT), *args, "--marketplace", self.bare.as_uri()],
                              cwd=self.repo, env=env, capture_output=True, text=True,
                              timeout=600)

    def assert_fails(self, tag, fragment):
        proc = self.run_script(tag, "--dry-run")
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn(fragment, proc.stderr)
        self.assertEqual(git(self.bare, "rev-parse", "main"), self.before)

    def test_tag_version_differs_from_manifests(self):
        git(self.repo, "tag", "steward-prose-gate--v0.0.1", self.tag_commit)
        self.assert_fails("steward-prose-gate--v0.0.1", "0.15.0")

    def test_unknown_plugin(self):
        git(self.repo, "tag", "steward--v0.15.0", self.tag_commit)
        self.assert_fails("steward--v0.15.0", "not a plugin of this repo")

    def test_version_not_semver(self):
        git(self.repo, "tag", "steward-prose-gate--v0.15", self.tag_commit)
        self.assert_fails("steward-prose-gate--v0.15", "MAJOR.MINOR.PATCH")

    def test_tag_commit_not_on_origin_main(self):
        tree = git(self.repo, "rev-parse", f"{self.tag_commit}^{{tree}}")
        side = subprocess.run(["git", "commit-tree", tree, "-p", self.tag_commit, "-m", "side"],
                              cwd=self.repo, capture_output=True, text=True, check=True,
                              env=dict(os.environ, **helpers.IDENTITY)).stdout.strip()
        git(self.repo, "tag", "-d", PROSE_TAG)
        git(self.repo, "tag", PROSE_TAG, side)
        self.assert_fails(PROSE_TAG, "origin/main")

    def test_dry_run_builds_one_commit_with_the_shipped_set(self):
        proc = self.run_script(PROSE_TAG, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        clone = Path(re.search(r"^clone: (.+)$", proc.stdout, re.M).group(1))
        self.addCleanup(shutil.rmtree, clone.parent, ignore_errors=True)
        self.assertEqual(git(self.bare, "rev-parse", "main"), self.before)
        self.assertEqual(git(clone, "rev-list", "--count", f"{self.before}..HEAD"), "1")
        self.assertEqual(git(clone, "log", "-1", "--format=%s"),
                         "release: steward-prose-gate 0.15.0")
        changed = git(clone, "diff", "--name-only", self.before, "HEAD").splitlines()
        shipped = [p for p in changed if p.startswith("plugins/")]
        self.assertEqual(len(shipped), 10, shipped)
        self.assertTrue(all(p.startswith("plugins/steward-prose-gate/") for p in shipped))
        self.assertFalse([p for p in shipped if "/tests/" in p])
        lock = json.loads((clone / "plugins.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["steward-prose-gate"]["commit"], self.tag_commit)
        self.assertEqual(lock["steward-prose-gate"]["tag"], PROSE_TAG)
        self.assertEqual(lock["steward-prose-gate"]["source"], "https://github.com/TejGandham/steward")
        self.assertEqual(lock["steward-prose-gate"]["pi"], {
            "extensions": ["pi/extensions/steward-prose-gate/index.ts"]})
        self.assertEqual(lock["steward-prose-gate"]["tree"],
                         git(clone, "rev-parse", "HEAD:plugins/steward-prose-gate"))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_only_a_release_tag_push_starts_it(self):
        trigger = self.text.split("\non:", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(re.sub(r"\s+", " ", trigger).strip(),
                         'push: tags: ["steward-delegation--v*", "steward-prose-gate--v*",'
                         ' "steward-orchestration--v*"]')
        for word in ("workflow_dispatch", "schedule", "branches", "pull_request"):
            self.assertNotIn(word, self.text)

    def test_token_only_from_the_secret_into_the_environment(self):
        lines = [line.strip() for line in self.text.splitlines() if "secrets." in line]
        self.assertEqual(lines, ["MARKETPLACE_TOKEN: ${{ secrets.MARKETPLACE_TOKEN }}"])
        self.assertNotIn("x-access-token", self.text)
        self.assertNotIn("@github.com", self.text)

    def test_author_is_the_operator_identity(self):
        for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
            self.assertIn(f"{key}: Tej\n", self.text)
        for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
            self.assertIn(f"{key}: 46010260+TejGandham@users.noreply.github.com\n", self.text)

    def test_runs_the_release_script_on_the_pushed_tag(self):
        self.assertIn('scripts/release_marketplace.sh "$GITHUB_REF_NAME"', self.text)
        self.assertIn("fetch-depth: 0", self.text)


if __name__ == "__main__":
    unittest.main()
