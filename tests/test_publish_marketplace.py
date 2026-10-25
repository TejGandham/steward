"""Tests for scripts/publish_marketplace.py, the marketplace publisher.

Every test builds a marketplace skeleton (the files of build step 1) in a
temp dir, turns it into a bare repo and talks to it over file://. Nothing
here touches the network or the real marketplace.

Covered: an upsert leaves the other entries byte-identical; each validator
row rejects its drift case; a lock entry from another product is refused;
a dry run pushes nothing; a push rejected because main moved re-clones,
keeps the other product's entry, then pushes.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "publish_marketplace.py"

_spec = importlib.util.spec_from_file_location("publish_marketplace", SCRIPT)
pm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pm)

STEWARD = "https://github.com/TejGandham/steward"
FORGEJO = "https://forgejo.example/stackhouse/common-skills"
IDENTITY = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "author@example.com",
}


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def write_skeleton(root):
    dump(root / ".claude-plugin" / "marketplace.json",
         {"name": "engen-tech", "owner": {"name": "Engen-Tech"},
          "description": "Test marketplace.", "plugins": []})
    dump(root / ".agents" / "plugins" / "marketplace.json",
         {"name": "engen-tech", "interface": {"displayName": "Engen-Tech"},
          "plugins": []})
    dump(root / "package.json",
         {"name": "engen-tech-plugins", "version": "1.0.0", "private": True,
          "keywords": ["pi-package"], "type": "module",
          "pi": {"extensions": [], "skills": [], "subagents": {"agents": []}},
          "peerDependencies": {"@earendil-works/pi-coding-agent": "*"}})
    dump(root / "plugins.lock.json", {})
    (root / "README.md").write_text("# test\n", encoding="utf-8")


def write_plugin(root, name, version, codex=True, pi=True, note="v"):
    """A small plugin folder with every manifest kind and an executable hook."""
    base = {"name": name, "version": version,
            "description": f"{name} description."}
    dump(root / ".claude-plugin" / "plugin.json", base)
    dump(root / ".github" / "plugin" / "plugin.json", base)
    if codex:
        dump(root / ".codex-plugin" / "plugin.json",
             dict(base, interface={"category": "Productivity"}))
    hook = root / "hooks" / "hook.py"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f"print('{note}')\n", encoding="utf-8")
    hook.chmod(0o755)
    if pi:
        ext = root / "pi" / "extensions" / name / "index.ts"
        ext.parent.mkdir(parents=True, exist_ok=True)
        ext.write_text("export default () => {};\n", encoding="utf-8")
        (root / "pi" / "skills" / "s").mkdir(parents=True, exist_ok=True)
        (root / "pi" / "skills" / "s" / "SKILL.md").write_text(
            "---\nname: s\n---\n", encoding="utf-8")


class MarketplaceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="publish-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict(os.environ, IDENTITY)
        env.start()
        self.addCleanup(env.stop)
        seed = self.tmp / "seed"
        seed.mkdir()
        write_skeleton(seed)
        git(seed, "init", "-q", "-b", "main")
        git(seed, "add", "-A")
        git(seed, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "skeleton")
        self.bare = self.tmp / "marketplace.git"
        git(self.tmp, "clone", "-q", "--bare", str(seed), str(self.bare))
        self.url = self.bare.as_uri()
        self.work = self.tmp / "work"
        self.work.mkdir()

    def release(self, name, version="1.0.0", source=STEWARD, codex=True,
                pi=True, note="v"):
        folder = self.work / f"{name}-{version}-{note}"
        write_plugin(folder, name, version, codex=codex, pi=pi, note=note)
        lists = ({"extensions": [f"pi/extensions/{name}/index.ts"],
                  "skills": ["pi/skills"]} if pi else {})
        return pm.Release(name=name, version=version, source=source,
                          tag=f"{name}--v{version}", commit="a" * 40,
                          folder=folder, pi=lists)

    def publish(self, release, **kw):
        kw.setdefault("run_claude", False)
        with contextlib.redirect_stdout(io.StringIO()):
            return pm.publish(release, self.url, **kw)

    def main_sha(self):
        return git(self.bare, "rev-parse", "main")

    def show(self, path, rev="main"):
        return git(self.bare, "show", f"{rev}:{path}") + "\n"


class UpsertTests(MarketplaceCase):
    def test_first_release_writes_every_generated_field(self):
        self.publish(self.release("alpha"))
        lock = json.loads(self.show("plugins.lock.json"))
        entry = lock["alpha"]
        self.assertEqual(list(entry), ["version", "source", "tag", "commit", "tree", "pi"])
        self.assertEqual(entry["tree"], git(self.bare, "rev-parse", "main:plugins/alpha"))
        claude = json.loads(self.show(".claude-plugin/marketplace.json"))
        self.assertEqual(claude["plugins"], [{"name": "alpha",
                                              "description": "alpha description.",
                                              "source": "./plugins/alpha"}])
        codex = json.loads(self.show(".agents/plugins/marketplace.json"))
        self.assertEqual(codex["plugins"], [{
            "name": "alpha",
            "source": {"source": "local", "path": "./plugins/alpha"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity"}])
        pkg = json.loads(self.show("package.json"))
        self.assertEqual(pkg["pi"], {
            "extensions": ["./plugins/alpha/pi/extensions/alpha/index.ts"],
            "skills": ["./plugins/alpha/pi/skills"],
            "subagents": {"agents": []}})
        mode = git(self.bare, "ls-tree", "main", "plugins/alpha/hooks/hook.py").split()[0]
        self.assertEqual(mode, "100755")

    def test_commit_message_and_author(self):
        self.publish(self.release("alpha"))
        msg = git(self.bare, "log", "-1", "--format=%B", "main")
        sha = pm.publisher_sha256()
        self.assertEqual(msg, "release: alpha 1.0.0\n\n"
                              f"source: {STEWARD}\ntag: alpha--v1.0.0\n"
                              f"commit: {'a' * 40}\npublisher: {sha}")
        self.assertEqual(git(self.bare, "log", "-1", "--format=%an <%ae>", "main"),
                         "Test Author <author@example.com>")

    def test_upsert_leaves_other_entries_byte_identical(self):
        self.publish(self.release("beta", codex=False, pi=False))
        self.publish(self.release("alpha"))
        before = self.main_sha()
        self.publish(self.release("alpha", version="1.0.1", note="w"))
        changed = git(self.bare, "diff", "--name-only", before, "main").splitlines()
        self.assertTrue(all(p in pm.SHARED_FILES or p.startswith("plugins/alpha/")
                            for p in changed), changed)
        self.assertNotIn("README.md", changed)
        # Put alpha's old entry back into each new file: the bytes must equal
        # the old file, so nothing outside alpha's entry moved.
        old_lock = json.loads(self.show("plugins.lock.json", before))
        new_lock = json.loads(self.show("plugins.lock.json"))
        new_lock["alpha"] = old_lock["alpha"]
        self.assertEqual(json.dumps(new_lock, indent=2) + "\n",
                         self.show("plugins.lock.json", before))
        for path in (".claude-plugin/marketplace.json",
                     ".agents/plugins/marketplace.json", "package.json"):
            self.assertEqual(self.show(path), self.show(path, before), path)
        self.assertEqual(git(self.bare, "rev-parse", "main:plugins/beta"),
                         git(self.bare, "rev-parse", f"{before}:plugins/beta"))

    def test_entries_sorted_by_name(self):
        self.publish(self.release("zeta"))
        self.publish(self.release("alpha"))
        lock = json.loads(self.show("plugins.lock.json"))
        self.assertEqual(list(lock), ["alpha", "zeta"])
        claude = json.loads(self.show(".claude-plugin/marketplace.json"))
        self.assertEqual([p["name"] for p in claude["plugins"]], ["alpha", "zeta"])
        pkg = json.loads(self.show("package.json"))
        self.assertEqual(pkg["pi"]["skills"],
                         ["./plugins/alpha/pi/skills", "./plugins/zeta/pi/skills"])

    def test_losing_the_codex_manifest_drops_the_codex_entry(self):
        self.publish(self.release("alpha"))
        self.publish(self.release("alpha", version="1.1.0", codex=False))
        codex = json.loads(self.show(".agents/plugins/marketplace.json"))
        self.assertEqual(codex["plugins"], [])
        self.assertFalse(git(self.bare, "ls-tree", "main", "plugins/alpha/.codex-plugin"))

    def test_foreign_source_is_refused(self):
        self.publish(self.release("plainlanguage", source=FORGEJO, codex=False))
        before = self.main_sha()
        with self.assertRaises(pm.PublishError) as cm:
            self.publish(self.release("plainlanguage", version="1.0.1"))
        self.assertIn("source", str(cm.exception))
        self.assertEqual(self.main_sha(), before)

    def test_release_version_must_match_manifests(self):
        rel = self.release("alpha")
        rel = rel._replace(version="2.0.0")
        with self.assertRaises(pm.PublishError):
            self.publish(rel)

    def test_dry_run_pushes_nothing(self):
        before = self.main_sha()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            clone = pm.publish(self.release("alpha"), self.url,
                               dry_run=True, run_claude=False)
        self.addCleanup(shutil.rmtree, clone.parent, ignore_errors=True)
        self.assertEqual(self.main_sha(), before)
        self.assertIn(str(clone), out.getvalue())
        self.assertIn("release: alpha 1.0.0", out.getvalue())
        self.assertIn('"alpha"', out.getvalue())
        self.assertEqual(git(clone, "log", "-1", "--format=%s"), "release: alpha 1.0.0")

    def test_cli_dry_run(self):
        rel = self.release("alpha")
        env = dict(os.environ, PATH="/usr/bin:/bin")
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--name", "alpha", "--version", "1.0.0",
             "--source", STEWARD, "--tag", rel.tag, "--commit", rel.commit,
             "--folder", str(rel.folder), "--pi", json.dumps(rel.pi),
             "--marketplace", self.url, "--dry-run"],
            capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        clone = Path(proc.stdout.split("clone: ", 1)[1].splitlines()[0])
        self.addCleanup(shutil.rmtree, clone.parent, ignore_errors=True)
        self.assertIn("claude not on PATH", proc.stdout)
        self.assertIn("plugins/alpha/hooks/hook.py", proc.stdout)


class PushRaceTests(MarketplaceCase):
    def test_rejected_push_reclones_keeps_other_entry_then_pushes(self):
        calls = []

        def other_product_releases_first(clone):
            calls.append(clone)
            if len(calls) == 1:
                self.publish(self.release("plainlanguage", source=FORGEJO, codex=False))

        self.publish(self.release("alpha"), before_push=other_product_releases_first)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0], calls[1])
        self.assertFalse(calls[0].exists())
        lock = json.loads(self.show("plugins.lock.json"))
        self.assertEqual(sorted(lock), ["alpha", "plainlanguage"])
        self.assertEqual(lock["plainlanguage"]["source"], FORGEJO)
        log = git(self.bare, "log", "--format=%s", "main").splitlines()
        self.assertEqual(log[:2], ["release: alpha 1.0.0", "release: plainlanguage 1.0.0"])
        check = self.tmp / "check"
        git(self.tmp, "clone", "-q", self.url, str(check))
        pm.validate(check, run_claude=False)

    def test_gives_up_after_the_retries(self):
        def always_move(clone):
            self.publish(self.release("other", source=FORGEJO, codex=False,
                                      version=f"1.0.{len(moves)}"))
            moves.append(clone)

        moves = []
        with self.assertRaises(pm.PublishError):
            self.publish(self.release("alpha"), before_push=always_move)
        self.assertEqual(len(moves), pm.PUSH_RETRIES + 1)
        self.assertNotIn("alpha", json.loads(self.show("plugins.lock.json")))


class ValidatorTests(MarketplaceCase):
    """Each validator row rejects the drift it is there to catch."""

    def setUp(self):
        super().setUp()
        self.publish(self.release("beta", codex=False, pi=False))
        with contextlib.redirect_stdout(io.StringIO()):
            self.clone = pm.publish(self.release("alpha"), self.url,
                                    dry_run=True, run_claude=False)
        self.addCleanup(shutil.rmtree, self.clone.parent, ignore_errors=True)
        pm.validate(self.clone, run_claude=False)

    def edit_json(self, rel, change):
        path = self.clone / rel
        obj = json.loads(path.read_text(encoding="utf-8"))
        change(obj)
        dump(path, obj)

    def assert_rejects(self, fragment):
        with self.assertRaises(pm.PublishError) as cm:
            pm.validate(self.clone, run_claude=False)
        self.assertIn(fragment, str(cm.exception))

    def test_hand_edit_under_plugins(self):
        (self.clone / "plugins/alpha/hooks/hook.py").write_text("x\n", encoding="utf-8")
        self.assert_rejects("tree")

    def test_mode_change_under_plugins(self):
        (self.clone / "plugins/alpha/hooks/hook.py").chmod(0o644)
        self.assert_rejects("tree")

    def test_folder_without_lock_entry(self):
        write_plugin(self.clone / "plugins" / "gamma", "gamma", "1.0.0")
        self.assert_rejects("gamma")

    def test_lock_entry_without_folder(self):
        shutil.rmtree(self.clone / "plugins" / "beta")
        self.assert_rejects("beta")

    def test_manifest_name_differs_from_folder(self):
        self.edit_json("plugins/alpha/.github/plugin/plugin.json",
                       lambda o: o.update(name="other"))
        self.assert_rejects("name")

    def test_half_bumped_version(self):
        self.edit_json("plugins/alpha/.codex-plugin/plugin.json",
                       lambda o: o.update(version="9.9.9"))
        self.assert_rejects("version")

    def test_claude_catalog_with_version(self):
        self.edit_json(".claude-plugin/marketplace.json",
                       lambda o: o["plugins"][0].update(version="1.0.0"))
        self.assert_rejects(".claude-plugin/marketplace.json")

    def test_claude_catalog_lost_entry(self):
        self.edit_json(".claude-plugin/marketplace.json",
                       lambda o: o["plugins"].pop())
        self.assert_rejects(".claude-plugin/marketplace.json")

    def test_codex_catalog_entry_for_plugin_without_codex_manifest(self):
        self.edit_json(".agents/plugins/marketplace.json", lambda o: o["plugins"].append({
            "name": "beta", "source": {"source": "local", "path": "./plugins/beta"},
            "policy": pm.CODEX_POLICY, "category": "Productivity"}))
        self.assert_rejects(".agents/plugins/marketplace.json")

    def test_codex_catalog_wrong_field(self):
        self.edit_json(".agents/plugins/marketplace.json",
                       lambda o: o["plugins"][0].update(category="Coding"))
        self.assert_rejects(".agents/plugins/marketplace.json")

    def test_stale_pi_path(self):
        self.edit_json("package.json",
                       lambda o: o["pi"]["skills"].append("./plugins/gone/skills"))
        self.assert_rejects("package.json")

    def test_missing_pi_path(self):
        self.edit_json("plugins.lock.json",
                       lambda o: o["alpha"]["pi"]["skills"].append("pi/missing"))
        self.edit_json("package.json",
                       lambda o: o["pi"]["skills"].insert(1, "./plugins/alpha/pi/missing"))
        self.assert_rejects("does not exist")

    def test_claude_validate_skipped_with_note_when_not_on_path(self):
        out = io.StringIO()
        with mock.patch.object(pm.shutil, "which", return_value=None), \
                contextlib.redirect_stdout(out):
            pm.validate(self.clone, run_claude=True)
        self.assertIn("claude not on PATH", out.getvalue())


if __name__ == "__main__":
    unittest.main()
