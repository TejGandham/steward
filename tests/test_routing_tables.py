"""The task-to-profile routing table is copied into each harness's edict.
Check that every copy carries the same rows, each in its harness's profile
naming, so a routing change cannot land in one copy and miss another."""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# file -> (heading that opens its table, mechanic profile name)
COPIES = {
    "skills/delegating/SKILL.md": ("## Routing table (task to profile)", "steward:mechanic-haiku-medium"),
    "skills/delegating/routing.md": ("## Rubric (task to profile)", "steward:mechanic-haiku-medium"),
    "pi/skills/steward-delegating/SKILL.md": ("## Routing table (task to profile)", "steward.mechanic"),
    "copilot/skills/delegating/SKILL.md": ("## Routing table (task to profile)", "steward:mechanic"),
}

BROWSER_TASK = ("Ad-hoc browser chores (open a page, read, click, fill, count, screenshot "
                "via a CDP/chrome-devtools MCP server or playwright-cli)")


def routing_rows(rel_path, heading):
    text = (REPO_ROOT / rel_path).read_text()
    section = text.split(heading, 1)[1]
    rows = {}
    for line in section.splitlines()[1:]:
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] in ("Task", "-") or set(cells[0]) <= {"-"}:
            continue
        rows[cells[0]] = cells[1]
    return rows


class RoutingTableTests(unittest.TestCase):
    def test_every_copy_has_the_same_tasks(self):
        tasks = {path: list(routing_rows(path, h)) for path, (h, _) in COPIES.items()}
        reference = tasks["skills/delegating/SKILL.md"]
        for path, rows in tasks.items():
            self.assertEqual(rows, reference, path)

    def test_browser_chores_route_to_the_haiku_mechanic_with_a_turn_cap(self):
        for path, (heading, mechanic) in COPIES.items():
            rows = routing_rows(path, heading)
            self.assertIn(BROWSER_TASK, rows, path)
            profile = rows[BROWSER_TASK]
            self.assertTrue(profile.startswith(mechanic + " "), (path, profile))
            self.assertRegex(profile, r"turn cap", path)

    def test_routing_md_carries_the_browser_rule_and_sources(self):
        text = (REPO_ROOT / "skills/delegating/routing.md").read_text()
        for needle in ("never full snapshots", "2FA", "fails twice",
                       "https://www.anthropic.com/claude-haiku-5-5",
                       "https://code.claude.com/docs/en/sub-agents",
                       "https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code",
                       "https://www.checklyhq.com/blog/mcp-vs-cli-token-efficiency/"):
            self.assertIn(needle, text)
        self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
