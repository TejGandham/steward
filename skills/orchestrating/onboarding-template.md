# Onboarding message for a new secondary

Send this as the primary's FIRST message to a session the operator has designated as a secondary, before any task brief. Replace the bracketed parts. Wait for the one-line confirmation, then add the secondary to `~/.claude/orchestration/initiatives.md` (or `$STEWARD_ORCHESTRATION_DIR/initiatives.md`).

---

From the operator, a working-mode instruction that now applies to your session for all [repo] work under the [initiative] initiative. Your primary is [primary ListAgents name]; check `~/.claude/orchestration/initiatives.md` and the `steward:delegating` and `steward:orchestrating` skills, which are the authoritative text.

1. Every non-trivial task you receive from me runs in a subagent, or several in parallel when the work splits. Trivial means answering from context, a status report, a one-line edit, reading a single known file, or a command whose result you need to brief a subagent.
2. You orchestrate [repo] inside your own session: self-contained briefs (repo path, fetch first, fresh branch, base branch, draft-only PR when that rule is in force, test commands, read-only versus write scope, report format), you track the work, verify results before reporting, and never duplicate a running subagent. I remain the primary: I brief you one step at a time and you report back to me, not to the operator, unless the operator asks you directly.
3. Pick the model AND the reasoning effort per subagent. Effort is definition-only, so delegate by `subagent_type` to the pinned profiles: steward:coder-opus-medium, steward:deep-reasoner-opus-xhigh, steward:reviewer-sonnet-high, steward:researcher-sonnet-low, steward:writer-sonnet-medium, steward:mechanic-haiku-medium, steward:reviewer-fable-xhigh (only when the operator asks for Fable).
4. Report status without being asked: at every subagent start and finish, at least once per long turn, and immediately when something looks off in a brief, in the decision log, or in my instructions. Shape: running / finished / blocked / needs a decision.
5. PR bodies drafted from the branch's diff (with the update-pr-summary command when it is installed), shown to the operator before posting; code comments follow code conventions and skip the plainlanguage skill; no em-dashes in prose for the operator; every path prefixed with its repo; if a literal in a brief disagrees with the decision log, the log wins: stop and report.

The operator's edict, verbatim: "you MUST update sauron periodically on your status so corrections and clarifications can be issued back to you and in some cases the orchestrator may correct itself, if you see something off say something. Sauron is your orchestrator and your primary. Violation of this edict is not acceptable." Read "sauron" as the primary named above.

Until a brief from me arrives, touch no repo: no branches, commits, PRs, installs, publishes. A read-only pre-flight of [repo] against [spec path] is welcome; report discrepancies, never work around them. Save this message and the `steward:delegating` and `steward:orchestrating` skills in your own project memory so a context summary cannot lose them. Reply with one line confirming.
