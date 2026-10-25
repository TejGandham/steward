#!/usr/bin/env bash
# Release one steward plugin to the Engen-Tech plugin marketplace.
#
#   scripts/release_marketplace.sh <plugin>--v<version> [--dry-run] [--marketplace <url>]
#
# Run from a steward checkout that has the tag and origin/main. Steps, as in
# the marketplace design "Release pipeline (product side)":
#   1. check the tag: a plugin of this repo, a MAJOR.MINOR.PATCH version,
#      a commit on origin/main, and every manifest of the plugin at that
#      version;
#   2. run the suite at the tag (from a git archive, so no working-tree file
#      leaks in);
#   3. assemble plugins/<plugin>/ at the tag, minus tests/;
#   4. take the plugin's pi lists from the root package.json at the tag;
#   5. hand all of it to scripts/publish_marketplace.py, which commits and
#      (without --dry-run) pushes.
# The token, if any, is read by the publisher from MARKETPLACE_TOKEN.
set -euo pipefail

PLUGINS="steward-delegation steward-prose-gate steward-orchestration"
SOURCE="https://github.com/TejGandham/steward"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() { echo "release_marketplace: $*" >&2; exit 1; }

tag="${1:-}"
[ -n "$tag" ] || fail "usage: release_marketplace.sh <plugin>--v<version> [--dry-run] [--marketplace <url>]"
shift
publish_args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) publish_args+=(--dry-run); shift ;;
    --marketplace) [ $# -ge 2 ] || fail "--marketplace needs a URL"; publish_args+=(--marketplace "$2"); shift 2 ;;
    *) fail "unknown argument: $1" ;;
  esac
done

repo="$(git rev-parse --show-toplevel)"
cd "$repo"

# Step 1: check the tag.
case "$tag" in
  *--v*) plugin="${tag%%--v*}"; version="${tag#*--v}" ;;
  *) fail "tag $tag is not <plugin>--v<version>" ;;
esac
case " $PLUGINS " in
  *" $plugin "*) ;;
  *) fail "$plugin is not a plugin of this repo ($PLUGINS)" ;;
esac
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "version $version is not MAJOR.MINOR.PATCH"
commit="$(git rev-parse --verify --quiet "refs/tags/$tag^{commit}")" || fail "no tag $tag"
git merge-base --is-ancestor "$commit" origin/main || fail "$tag ($commit) is not on origin/main"
for manifest in .claude-plugin/plugin.json .codex-plugin/plugin.json .github/plugin/plugin.json; do
  path="plugins/$plugin/$manifest"
  git cat-file -e "$commit:$path" 2>/dev/null || continue
  found="$(git show "$commit:$path" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("version"))')"
  [ "$found" = "$version" ] || fail "$path at $tag says version $found, the tag says $version"
done
echo "tag $tag: $plugin $version at $commit"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Step 2: the suite at the tag. STEWARD_RELEASE_SUITE stops the release
# tests from calling this script again.
mkdir "$work/suite"
git archive "$commit" | tar -x -C "$work/suite"
echo "running the suite at $tag"
(cd "$work/suite" && PI_SUBAGENTS_DIR=/nonexistent STEWARD_RELEASE_SUITE=1 npm test >"$work/suite.log" 2>&1) \
  || { cat "$work/suite.log" >&2; fail "the suite failed at $tag"; }
echo "suite passed"

# Step 3: the shipped set.
mkdir "$work/archive"
git archive "$commit" "plugins/$plugin" | tar -x -C "$work/archive"
rm -rf "$work/archive/plugins/$plugin/tests"
folder="$work/archive/plugins/$plugin"

# Step 4: the pi lists, relative to the plugin folder.
pi="$(git show "$commit:package.json" | python3 -c '
import json, sys
prefix = "./plugins/" + sys.argv[1] + "/"
pi = json.load(sys.stdin).get("pi", {})
lists = {"extensions": pi.get("extensions", []), "skills": pi.get("skills", []),
         "agents": pi.get("subagents", {}).get("agents", [])}
print(json.dumps({kind: [p[len(prefix):] for p in paths if p.startswith(prefix)]
                  for kind, paths in lists.items()}))
' "$plugin")"

# Step 5: publish.
python3 "$SCRIPTS_DIR/publish_marketplace.py" \
  --name "$plugin" --version "$version" --source "$SOURCE" \
  --tag "$tag" --commit "$commit" --folder "$folder" --pi "$pi" \
  ${publish_args[@]+"${publish_args[@]}"}
