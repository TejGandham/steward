#!/usr/bin/env python3
"""Publish one plugin release to the Engen-Tech plugin marketplace.

Called by each product's scripts/release_marketplace.sh after it has
checked the tag and assembled the plugin folder. Stdlib only, python3.9+.
The canonical copy lives in steward; common-skills holds a byte-for-byte
copy, and every release commit records this file's sha256.

What it does (design "Release pipeline", step 5 and 6):
1. Shallow-clone marketplace main into a temp dir.
2. Replace plugins/<name>/ with the assembled folder.
3. Rewrite only this plugin's entry in the lock, the two catalogs and the
   package.json pi lists. JSON is json.dumps(indent=2) plus a newline,
   entries sorted by name, so other entries' bytes never change.
4. Validate the whole tree.
5. Commit "release: <name> <version>" with source/tag/commit/publisher lines.
6. Push HEAD:main. If main moved meanwhile, start again from a fresh clone,
   at most PUSH_RETRIES more times. Never force.

With --dry-run it stops after the commit, prints the clone path and the
commit, and pushes nothing. The token, when set, comes from the
MARKETPLACE_TOKEN environment variable and reaches git only as an HTTP
header through GIT_CONFIG_* variables: never in a URL, argv or output.
The commit author is whatever git identity the caller set.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

DEFAULT_MARKETPLACE = "https://github.com/Engen-Tech/plugin-marketplace.git"
PUSH_RETRIES = 3
CODEX_POLICY = {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}
MANIFESTS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json",
             ".github/plugin/plugin.json")
CLAUDE_CATALOG = ".claude-plugin/marketplace.json"
CODEX_CATALOG = ".agents/plugins/marketplace.json"
PACKAGE = "package.json"
LOCK = "plugins.lock.json"
SHARED_FILES = (CLAUDE_CATALOG, CODEX_CATALOG, PACKAGE, LOCK)
PI_KINDS = ("extensions", "skills", "agents")
LOCK_FIELDS = ["version", "source", "tag", "commit", "tree", "pi"]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class PublishError(Exception):
    pass


class Release(NamedTuple):
    name: str
    version: str
    source: str    # the product repo URL; it owns this lock entry
    tag: str
    commit: str    # the commit the tag points at
    folder: Path   # the assembled plugin folder
    pi: dict       # {"extensions": [...], "skills": [...], "agents": [...]}, paths inside the folder


def publisher_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, indent=2) + "\n")


def git_env(token):
    env = dict(os.environ)
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update({"GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "http.extraHeader",
                    "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}"})
    return env


def git(cwd, *args, token=None, check=True, stdin=None):
    proc = subprocess.run(["git", *args], cwd=cwd, env=git_env(token),
                          input=stdin, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise PublishError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


# --- expected contents, derived from the plugin folders and the lock -------

def claude_entry(root, name):
    manifest = load_json(root / "plugins" / name / ".claude-plugin" / "plugin.json")
    return {"name": name, "description": manifest["description"],
            "source": f"./plugins/{name}"}


def codex_entry(root, name):
    path = root / "plugins" / name / ".codex-plugin" / "plugin.json"
    if not path.is_file():
        return None
    return {"name": name,
            "source": {"source": "local", "path": f"./plugins/{name}"},
            "policy": CODEX_POLICY,
            "category": load_json(path)["interface"]["category"]}


def pi_lists(lock):
    lists = {kind: [] for kind in PI_KINDS}
    for name in sorted(lock):
        for kind in PI_KINDS:
            lists[kind] += [f"./plugins/{name}/{p}" for p in lock[name]["pi"].get(kind, [])]
    return {"extensions": lists["extensions"], "skills": lists["skills"],
            "subagents": {"agents": lists["agents"]}}


def plugin_folders(root):
    plugins = root / "plugins"
    return sorted(p.name for p in plugins.iterdir() if p.is_dir()) if plugins.is_dir() else []


def folder_tree(root, name):
    git(root, "add", "-A", "--", f"plugins/{name}")
    return git(root, "write-tree", f"--prefix=plugins/{name}/").stdout.strip()


# --- apply one release to a clone ------------------------------------------

def check_release(release):
    if not VERSION_RE.match(release.version):
        raise PublishError(f"version {release.version!r} is not MAJOR.MINOR.PATCH")
    if not set(release.pi) <= set(PI_KINDS):
        raise PublishError(f"unknown pi kinds: {sorted(set(release.pi) - set(PI_KINDS))}")
    for rel in MANIFESTS:
        path = release.folder / rel
        if path.is_file():
            manifest = load_json(path)
            if manifest.get("name") != release.name or manifest.get("version") != release.version:
                raise PublishError(f"{rel} says {manifest.get('name')} {manifest.get('version')},"
                                   f" release is {release.name} {release.version}")
    if not (release.folder / MANIFESTS[0]).is_file():
        raise PublishError(f"{release.folder} has no {MANIFESTS[0]}")


def apply_release(root, release):
    lock = load_json(root / LOCK)
    old = lock.get(release.name)
    if old is not None and old["source"] != release.source:
        raise PublishError(f"lock entry {release.name} has source {old['source']},"
                           f" not {release.source}; refusing to replace it")

    target = root / "plugins" / release.name
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(exist_ok=True)
    shutil.copytree(release.folder, target)

    lock[release.name] = {
        "version": release.version, "source": release.source, "tag": release.tag,
        "commit": release.commit, "tree": folder_tree(root, release.name),
        "pi": {kind: release.pi[kind] for kind in PI_KINDS if release.pi.get(kind)},
    }
    dump_json(root / LOCK, {name: lock[name] for name in sorted(lock)})

    claude = load_json(root / CLAUDE_CATALOG)
    entries = [e for e in claude["plugins"] if e["name"] != release.name]
    entries.append(claude_entry(root, release.name))
    claude["plugins"] = sorted(entries, key=lambda e: e["name"])
    dump_json(root / CLAUDE_CATALOG, claude)

    codex = load_json(root / CODEX_CATALOG)
    entries = [e for e in codex["plugins"] if e["name"] != release.name]
    entry = codex_entry(root, release.name)
    if entry is not None:
        entries.append(entry)
    codex["plugins"] = sorted(entries, key=lambda e: e["name"])
    dump_json(root / CODEX_CATALOG, codex)

    package = load_json(root / PACKAGE)
    package["pi"] = pi_lists(lock)
    dump_json(root / PACKAGE, package)


# --- validator --------------------------------------------------------------

def validate(root, run_claude=True):
    """Check the whole tree; raise PublishError listing every problem."""
    root = Path(root)
    errors = []
    lock = load_json(root / LOCK)
    folders = plugin_folders(root)

    for name in sorted(set(folders) - set(lock)):
        errors.append(f"plugins/{name}/ has no lock entry")
    for name in sorted(set(lock) - set(folders)):
        errors.append(f"lock entry {name} has no plugins/{name}/ folder")
    for name in sorted(set(folders) & set(lock)):
        entry = lock[name]
        if list(entry) != LOCK_FIELDS:
            errors.append(f"lock entry {name} has fields {list(entry)}, expected {LOCK_FIELDS}")
            continue
        tree = folder_tree(root, name)
        if tree != entry["tree"]:
            errors.append(f"plugins/{name}/ tree is {tree}, lock says {entry['tree']}")
        for rel in MANIFESTS:
            path = root / "plugins" / name / rel
            if not path.is_file():
                continue
            manifest = load_json(path)
            if manifest.get("name") != name:
                errors.append(f"plugins/{name}/{rel} name is {manifest.get('name')!r}")
            if manifest.get("version") != entry["version"]:
                errors.append(f"plugins/{name}/{rel} version is {manifest.get('version')!r},"
                              f" lock says {entry['version']}")

    if errors:
        raise PublishError("validation failed:\n  " + "\n  ".join(errors))

    names = sorted(lock)
    expected = [claude_entry(root, n) for n in names]
    if load_json(root / CLAUDE_CATALOG)["plugins"] != expected:
        errors.append(f"{CLAUDE_CATALOG} plugins differ from the plugin folders")
    expected = [e for e in (codex_entry(root, n) for n in names) if e is not None]
    if load_json(root / CODEX_CATALOG)["plugins"] != expected:
        errors.append(f"{CODEX_CATALOG} plugins differ from the plugin folders")

    pi = load_json(root / PACKAGE).get("pi")
    expected = pi_lists(lock)
    if pi != expected:
        errors.append(f"{PACKAGE} pi is {json.dumps(pi)}, the lock gives {json.dumps(expected)}")
    for path in expected["extensions"] + expected["skills"] + expected["subagents"]["agents"]:
        if not (root / path).exists():
            errors.append(f"pi path {path} does not exist")

    if run_claude:
        if shutil.which("claude"):
            proc = subprocess.run(["claude", "plugin", "validate", "."], cwd=root,
                                  capture_output=True, text=True)
            print(proc.stdout.rstrip())
            if proc.returncode != 0:
                errors.append(f"claude plugin validate failed: {proc.stderr.strip()}")
        else:
            print("note: claude not on PATH, skipped claude plugin validate")

    if errors:
        raise PublishError("validation failed:\n  " + "\n  ".join(errors))


# --- one attempt and the push loop ------------------------------------------

def commit_message(release):
    return (f"release: {release.name} {release.version}\n\n"
            f"source: {release.source}\n"
            f"tag: {release.tag}\n"
            f"commit: {release.commit}\n"
            f"publisher: {publisher_sha256()}\n")


def prepare(release, marketplace, token, run_claude):
    """Clone, apply, validate and commit. Returns (clone, base commit)."""
    clone = Path(tempfile.mkdtemp(prefix="marketplace-")) / "marketplace"
    try:
        git(None, "clone", "--quiet", "--depth", "1", "--branch", "main",
            marketplace, str(clone), token=token)
        base = git(clone, "rev-parse", "HEAD").stdout.strip()
        apply_release(clone, release)
        validate(clone, run_claude=run_claude)
        git(clone, "add", "-A")
        git(clone, "commit", "--quiet", "-F", "-", stdin=commit_message(release))
    except BaseException:
        shutil.rmtree(clone.parent, ignore_errors=True)
        raise
    return clone, base


def publish(release, marketplace, dry_run=False, token=None, run_claude=True,
            before_push=None):
    """Publish one release. Returns the clone path (kept only on a dry run).

    before_push(clone) runs after the commit and before each push; tests use
    it to move main the way a second product's release would.
    """
    check_release(release)
    for attempt in range(PUSH_RETRIES + 1):
        clone, base = prepare(release, marketplace, token, run_claude)
        if dry_run:
            print(f"clone: {clone}")
            print(git(clone, "show", "--stat", "HEAD").stdout.rstrip())
            lock = load_json(clone / LOCK)
            print(f"lock entry: {json.dumps({release.name: lock[release.name]}, indent=2)}")
            for catalog in (CLAUDE_CATALOG, CODEX_CATALOG):
                entry = [e for e in load_json(clone / catalog)["plugins"]
                         if e["name"] == release.name]
                print(f"{catalog}: {json.dumps(entry, indent=2)}")
            print("dry run: nothing pushed")
            return clone
        try:
            if before_push is not None:
                before_push(clone)
            pushed = git(clone, "push", "--quiet", "origin", "HEAD:main",
                         token=token, check=False)
            if pushed.returncode == 0:
                print(f"pushed: release: {release.name} {release.version}")
                return clone
            remote = git(clone, "ls-remote", "origin", "refs/heads/main",
                         token=token).stdout.split()
            if not remote or remote[0] == base:
                raise PublishError(f"push failed: {pushed.stderr.strip()}")
            print(f"main moved during attempt {attempt + 1}; starting again from a fresh clone")
        finally:
            shutil.rmtree(clone.parent, ignore_errors=True)
    raise PublishError(f"main kept moving; gave up after {PUSH_RETRIES + 1} attempts")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source", required=True, help="product repo URL")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--pi", required=True, help="JSON object of pi lists")
    parser.add_argument("--marketplace", default=DEFAULT_MARKETPLACE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    release = Release(name=args.name, version=args.version, source=args.source,
                      tag=args.tag, commit=args.commit, folder=args.folder,
                      pi=json.loads(args.pi))
    try:
        publish(release, args.marketplace, dry_run=args.dry_run,
                token=os.environ.get("MARKETPLACE_TOKEN") or None)
    except PublishError as e:
        print(f"publish_marketplace: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
