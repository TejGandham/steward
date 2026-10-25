// Tests for the steward-prose-gate pi extension. A stand-in `pi` object
// records the handlers the extension registers; the handlers then run against
// the real hooks/prose_gate_hook.py, with HOME, the state dir and pi's config
// dir pointed at a throwaway directory.

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import proseGate, {
	HOOK_SCRIPT,
	PLUGIN_ROOT,
	isProseRevision,
	lastAssistantText,
} from "../../pi/extensions/steward-prose-gate/index.ts";

// Two distinct markers from data/ai-tells.txt: enough to block on their own.
const TWO_MARKERS = "This is crucial and pivotal.";
const ENV_KEYS = ["HOME", "XDG_STATE_HOME", "PI_CODING_AGENT_DIR", "STEWARD_PROSE_GATE", "STEWARD_PROSE_GATE_PYTHON", "PI_SUBAGENT_CHILD"];

let tmp;
let savedEnv;

beforeEach(() => {
	savedEnv = Object.fromEntries(ENV_KEYS.map((k) => [k, process.env[k]]));
	tmp = mkdtempSync(join(tmpdir(), "steward-prose-gate-pi-test-"));
	for (const dir of ["home", "state", "config"]) mkdirSync(join(tmp, dir));
	process.env.HOME = join(tmp, "home");
	process.env.XDG_STATE_HOME = join(tmp, "state");
	process.env.PI_CODING_AGENT_DIR = join(tmp, "config");
	for (const k of ["STEWARD_PROSE_GATE", "STEWARD_PROSE_GATE_PYTHON", "PI_SUBAGENT_CHILD"]) delete process.env[k];
});

afterEach(() => {
	for (const [k, v] of Object.entries(savedEnv)) {
		if (v === undefined) delete process.env[k];
		else process.env[k] = v;
	}
	rmSync(tmp, { recursive: true, force: true });
});

function load() {
	const handlers = {};
	const notices = [];
	const pi = {
		on(name, handler) {
			(handlers[name] ??= []).push(handler);
		},
	};
	proseGate(pi);
	const ctx = {
		cwd: "/some/project",
		hasUI: true,
		ui: { notify: (msg, level) => notices.push({ msg, level }) },
	};
	const fire = async (name, event) => {
		let result;
		for (const h of handlers[name] ?? []) result = await h(event, ctx);
		return result;
	};
	return { handlers, fire, notices };
}

let callCounter = 0;
const call = (toolName, input) => ({ type: "tool_call", toolCallId: `c${++callCounter}`, toolName, input });
const reply = (text) => ({ role: "assistant", content: [{ type: "thinking", thinking: "t" }, { type: "text", text }] });
const settle = (contextMessages, outcome = "completed", entries = []) => ({
	type: "agent_before_settle",
	outcome,
	entries,
	continue: false,
	// what pi reports for a finished reply: the context ends on the assistant turn
	context: { canContinue: false, contextMessages },
});

test("the hook script resolves inside this plugin", () => {
	const here = dirname(fileURLToPath(import.meta.url));
	assert.equal(PLUGIN_ROOT, resolve(here, "..", ".."));
	assert.equal(HOOK_SCRIPT, join(PLUGIN_ROOT, "hooks", "prose_gate_hook.py"));
});

test("registers nothing inside a pi-subagents child", () => {
	process.env.PI_SUBAGENT_CHILD = "1";
	const { handlers } = load();
	assert.deepEqual(handlers, {});
});

test("PR gate blocks a gh pr edit body with two markers", async () => {
	const { fire } = load();
	const pr = await fire("tool_call", call("bash", { command: `gh pr edit --body "${TWO_MARKERS}"` }));
	assert.equal(pr.block, true);
	assert.match(pr.reason, /PR gate/);
});

test("PR gate blocks a gh pr create body with two markers", async () => {
	const { fire } = load();
	const result = await fire("tool_call", call("bash", { command: `gh pr create --title t --body "${TWO_MARKERS}"` }));
	assert.equal(result.block, true);
	assert.match(result.reason, /PR gate/);
	assert.match(result.reason, /crucial, pivotal/);
});

test("PR gate passes clean bash and never checks other tools", async () => {
	const { fire } = load();
	assert.equal(await fire("tool_call", call("bash", { command: `gh pr create --title t --body "plain body"` })), undefined);
	assert.equal(await fire("tool_call", call("bash", { command: "git status && ls -la" })), undefined);
	assert.equal(await fire("tool_call", call("write", { path: "a.txt", content: TWO_MARKERS })), undefined);
});

test("prose gate sends a reply back once, keeping earlier entries", async () => {
	const { fire } = load();
	const earlier = { type: "custom", customType: "other" };
	const bad = reply(TWO_MARKERS);
	const first = await fire("agent_before_settle", settle([{ role: "user", content: "q" }, bad], "completed", [earlier]));
	assert.equal(first.continue, true);
	assert.deepEqual(first.entries[0], earlier);
	assert.equal(first.entries[1].type, "custom_message");
	assert.equal(first.entries[1].customType, "steward-prose-gate");
	assert.match(first.entries[1].content, /prose gate/);

	// the revision is not sent back again, even if it still has tells
	const gateMessage = { role: "custom", customType: "steward-prose-gate", content: first.entries[1].content };
	const revised = [{ role: "user", content: "q" }, bad, gateMessage, reply("Still crucial and pivotal here.")];
	assert.equal(await fire("agent_before_settle", settle(revised)), undefined);

	// a later turn is checked again
	const later = [...revised, { role: "user", content: "next" }, reply("Again crucial and pivotal here.")];
	assert.equal((await fire("agent_before_settle", settle(later))).continue, true);

	// clean replies pass
	assert.equal(await fire("agent_before_settle", settle([{ role: "user", content: "q" }, reply("All done.")])), undefined);
});

test("isProseRevision", () => {
	const gate = { role: "custom", customType: "steward-prose-gate" };
	const notice = { role: "custom", customType: "subagent-done" };
	const a = { role: "assistant", content: [] };
	const tr = { role: "toolResult", content: [] };
	assert.equal(isProseRevision([]), false);
	assert.equal(isProseRevision([{ role: "user" }, a]), false);
	assert.equal(isProseRevision([{ role: "user" }, a, gate, a, tr, a]), true);
	assert.equal(isProseRevision([{ role: "user" }, a, gate, a, notice, a]), false);
	assert.equal(isProseRevision([gate, a, { role: "user" }, a]), false);
});

test("prose gate skips aborted runs", async () => {
	const { fire } = load();
	const result = await fire("agent_before_settle", {
		type: "agent_before_settle",
		outcome: "aborted",
		entries: [],
		continue: false,
		context: { canContinue: true, contextMessages: [{ role: "assistant", content: TWO_MARKERS }] },
	});
	assert.equal(result, undefined);
});

test("lastAssistantText", () => {
	assert.equal(lastAssistantText([]), undefined);
	assert.equal(
		lastAssistantText([
			{ role: "assistant", content: [{ type: "text", text: "old" }] },
			{ role: "user", content: "q" },
			{ role: "assistant", content: [{ type: "text", text: "a" }, { type: "toolCall" }, { type: "text", text: "b" }] },
		]),
		"ab",
	);
	assert.equal(lastAssistantText([{ role: "assistant", content: [{ type: "toolCall" }] }]), undefined);
	assert.equal(lastAssistantText([{ role: "assistant", content: "plain" }]), "plain");
});

test("python missing: one notice, then both gates fail open", async () => {
	process.env.STEWARD_PROSE_GATE_PYTHON = join(tmp, "no-such-python");
	const { fire, notices } = load();
	const pr = () => call("bash", { command: `gh pr create --title t --body "${TWO_MARKERS}"` });
	assert.equal(await fire("tool_call", pr()), undefined);
	assert.equal(await fire("tool_call", pr()), undefined);
	assert.equal(await fire("agent_before_settle", settle([{ role: "user", content: "q" }, reply(TWO_MARKERS)])), undefined);
	assert.equal(notices.length, 1);
	assert.match(notices[0].msg, /python3 was not found/);
	assert.equal(notices[0].level, "warning");
});
