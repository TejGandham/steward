// Tests for the steward pi extension. A stand-in `pi` object records the
// handlers the extension registers; the handlers then run against the real
// hooks/steward_hook.py, with HOME, the state dir and pi's config dir pointed
// at a throwaway directory. The real pi runtime is exercised by the smoke run
// described in README.md, not here.

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import steward, { isProseRevision, launchesWork, lastAssistantText } from "../../pi/extensions/steward/index.ts";

const EM_DASH = String.fromCodePoint(0x2014);
const ENV_KEYS = ["HOME", "XDG_STATE_HOME", "PI_CODING_AGENT_DIR", "STEWARD_GATE", "STEWARD_PYTHON", "PI_SUBAGENT_CHILD"];

let tmp;
let savedEnv;
let sessionCounter = 0;

beforeEach(() => {
	savedEnv = Object.fromEntries(ENV_KEYS.map((k) => [k, process.env[k]]));
	tmp = mkdtempSync(join(tmpdir(), "steward-pi-test-"));
	for (const dir of ["home", "state", "config"]) mkdirSync(join(tmp, dir));
	process.env.HOME = join(tmp, "home");
	process.env.XDG_STATE_HOME = join(tmp, "state");
	process.env.PI_CODING_AGENT_DIR = join(tmp, "config");
	for (const k of ["STEWARD_GATE", "STEWARD_PYTHON", "PI_SUBAGENT_CHILD"]) delete process.env[k];
});

afterEach(() => {
	for (const [k, v] of Object.entries(savedEnv)) {
		if (v === undefined) delete process.env[k];
		else process.env[k] = v;
	}
	rmSync(tmp, { recursive: true, force: true });
});

// `active`: the names getActiveTools returns (default: every registered tool), a function to run
// instead, or null for a host without getActiveTools.
function load({ tools = ["read", "bash", "edit", "write", "subagent"], active = tools } = {}) {
	const handlers = {};
	const notices = [];
	const pi = {
		on(name, handler) {
			(handlers[name] ??= []).push(handler);
		},
		getAllTools: () => tools.map((name) => ({ name })),
	};
	if (typeof active === "function") pi.getActiveTools = active;
	else if (active !== null) pi.getActiveTools = () => [...active];
	steward(pi);
	const id = `t${++sessionCounter}`;
	const ctx = {
		cwd: "/some/project",
		hasUI: true,
		ui: { notify: (msg, level) => notices.push({ msg, level }) },
		sessionManager: { getSessionId: () => id },
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
const write = (path = "/some/project/src/a.txt") => call("write", { path, content: "x" });
const subagentResult = (input, isError = false) => ({
	type: "tool_result",
	toolCallId: `c${++callCounter}`,
	toolName: "subagent",
	input,
	content: [{ type: "text", text: "ok" }],
	isError,
});

function promptEvent(force) {
	return {
		type: "before_agent_start",
		prompt: "hi",
		systemPrompt: force ?? "base prompt",
		systemPromptOptions: { sections: {}, forceSystemPrompt: force },
	};
}

test("registers nothing inside a pi-subagents child", () => {
	process.env.PI_SUBAGENT_CHILD = "1";
	const { handlers } = load();
	assert.deepEqual(handlers, {});
});

test("injects the pi edict as the steward section", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	const event = promptEvent();
	assert.equal(await fire("before_agent_start", event), undefined);
	const text = event.systemPromptOptions.sections.steward;
	assert.match(text, /steward-delegating/);
	assert.match(text, /steward\.coder-opus-medium/);
	assert.doesNotMatch(text, /STEWARD WARNING: the pi-subagents extension is not loaded/);
	assert.doesNotMatch(text, /<STEWARD>/);
});

test("warns when pi-subagents is not loaded", async () => {
	const { fire } = load({ tools: ["read", "bash", "edit", "write"] });
	await fire("session_start", { type: "session_start", reason: "startup" });
	const event = promptEvent();
	await fire("before_agent_start", event);
	assert.match(event.systemPromptOptions.sections.steward, /STEWARD WARNING: the pi-subagents extension is not loaded/);
});

test("appends to a prompt another extension already replaced", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	const result = await fire("before_agent_start", promptEvent("forced prompt"));
	assert.match(result.systemPrompt, /^forced prompt\n\n<steward>\n/);
	assert.match(result.systemPrompt, /<\/steward>$/);
	assert.equal(await fire("before_agent_start", promptEvent(result.systemPrompt)), undefined);
});

test("second direct write is blocked until a subagent launch", async () => {
	const { fire } = load();
	assert.equal(await fire("tool_call", write()), undefined);
	const blocked = await fire("tool_call", write());
	assert.equal(blocked.block, true);
	assert.match(blocked.reason, /direct edit #2/);
	assert.match(blocked.reason, /steward\.coder-opus-medium/);

	// a management call is not a delegation
	await fire("tool_result", subagentResult({ action: "list" }));
	assert.equal((await fire("tool_call", write())).block, true);

	// a launch pi-subagents rejected is not a delegation either
	await fire("tool_result", subagentResult({ agent: "steward.no-such-profile", task: "x" }, true));
	assert.equal((await fire("tool_call", write())).block, true);

	await fire("tool_result", subagentResult({ agent: "steward.mechanic-sonnet-low", task: "x" }));
	assert.equal(await fire("tool_call", write()), undefined);
	assert.equal((await fire("tool_call", write())).block, true);

	// resuming a retained child counts
	await fire("tool_result", subagentResult({ action: "resume", id: "r1", message: "go on" }));
	assert.equal(await fire("tool_call", write()), undefined);
});

test("without pi-subagents the delegation gate only reminds, the PR gate still blocks", async () => {
	const { fire } = load({ tools: ["read", "bash", "edit", "write"] });
	await fire("tool_call", write());
	const second = write();
	assert.equal(await fire("tool_call", second), undefined);
	const result = await fire("tool_result", {
		type: "tool_result",
		toolCallId: second.toolCallId,
		toolName: "write",
		input: second.input,
		content: [{ type: "text", text: "wrote it" }],
		isError: false,
	});
	assert.match(result.content[1].text, /direct edit #2/);
	assert.match(result.content[1].text, /STEWARD WARNING: the pi-subagents extension is not loaded/);
	const pr = await fire("tool_call", call("bash", { command: `gh pr edit --body "a ${EM_DASH} b"` }));
	assert.equal(pr.block, true);
});

const NOT_AVAILABLE_NOTE = /subagent tool is not available in this session/;

async function secondWriteNote(fire) {
	await fire("tool_call", write());
	const second = write();
	assert.equal(await fire("tool_call", second), undefined);
	const result = await fire("tool_result", {
		type: "tool_result",
		toolCallId: second.toolCallId,
		toolName: "write",
		input: second.input,
		content: [{ type: "text", text: "wrote it" }],
		isError: false,
	});
	return result.content[1].text;
}

test("subagent registered but not active: the delegation gate only reminds, the PR gate still blocks", async () => {
	const { fire } = load({ active: ["read", "bash", "edit", "write"] });
	const note = await secondWriteNote(fire);
	assert.match(note, /direct edit #2/);
	assert.match(note, NOT_AVAILABLE_NOTE);
	assert.match(note, /"toolActivation": "eager"/);
	assert.match(note, /\/reload/);
	assert.doesNotMatch(note, /STEWARD WARNING: the pi-subagents extension is not loaded/);
	assert.ok(!note.includes(EM_DASH));
	const pr = await fire("tool_call", call("bash", { command: `gh pr edit --body "a ${EM_DASH} b"` }));
	assert.equal(pr.block, true);
});

test("subagent registered but not active: no missing-extension warning in the edict", async () => {
	const { fire } = load({ active: ["read", "bash", "edit", "write"] });
	await fire("session_start", { type: "session_start", reason: "startup" });
	const event = promptEvent();
	await fire("before_agent_start", event);
	assert.doesNotMatch(event.systemPromptOptions.sections.steward, /STEWARD WARNING: the pi-subagents extension is not loaded/);
});

test("only the subagents_enable loader active: second write is blocked", async () => {
	const { fire } = load({ active: ["read", "bash", "edit", "write", "subagents_enable"] });
	await fire("tool_call", write());
	assert.equal((await fire("tool_call", write())).block, true);
});

test("subagent active: second write is blocked", async () => {
	const { fire } = load({ active: ["read", "write", "subagent"] });
	await fire("tool_call", write());
	assert.equal((await fire("tool_call", write())).block, true);
});

test("host without getActiveTools falls back to the registered tools", async () => {
	const blocking = load({ active: null });
	await blocking.fire("tool_call", write());
	assert.equal((await blocking.fire("tool_call", write())).block, true);

	const missing = load({ tools: ["read", "bash", "edit", "write"], active: null });
	const note = await secondWriteNote(missing.fire);
	assert.match(note, /STEWARD WARNING: the pi-subagents extension is not loaded/);
});

test("getActiveTools throwing makes the delegation gate remind, not block", async () => {
	const { fire } = load({
		active: () => {
			throw new Error("boom");
		},
	});
	const note = await secondWriteNote(fire);
	assert.match(note, /direct edit #2/);
	assert.match(note, NOT_AVAILABLE_NOTE);
});

test("soft mode adds the not-available note when no delegation tool is active", async () => {
	mkdirSync(join(tmp, "config", "steward"));
	writeFileSync(join(tmp, "config", "steward", "gate"), "soft\n");
	const { fire } = load({ active: ["read", "bash", "edit", "write"] });
	const note = await secondWriteNote(fire);
	assert.match(note, /direct edit #2/);
	assert.match(note, NOT_AVAILABLE_NOTE);
});

test("runs that skip before_agent_start get the edict in their messages", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	const messages = [{ role: "custom", customType: "subagent-done", content: "child finished", display: true }];

	// a run started by a notice, with no user prompt
	const result = await fire("context", { type: "context", messages });
	assert.equal(result.messages.length, 2);
	assert.equal(result.messages[1].role, "custom");
	assert.match(result.messages[1].content, /steward\.coder-opus-medium/);
	assert.equal(messages.length, 1);

	// a prompted run already has it in the system prompt
	await fire("before_agent_start", promptEvent());
	assert.equal(await fire("context", { type: "context", messages }), undefined);

	// after that run settles, the next unprompted run needs it again
	await fire("agent_settled", { type: "agent_settled" });
	assert.equal((await fire("context", { type: "context", messages })).messages.length, 2);
});

test("read-only bash and allowlisted paths pass", async () => {
	const { fire } = load();
	for (let i = 0; i < 3; i++) {
		assert.equal(await fire("tool_call", call("bash", { command: "git status && ls -la" })), undefined);
		assert.equal(await fire("tool_call", write("/tmp/scratch.txt")), undefined);
		assert.equal(await fire("tool_call", call("edit", { path: "AGENTS.md", edits: [] })), undefined);
	}
});

test("PR gate blocks a gh pr create body with an em-dash", async () => {
	const { fire } = load();
	const result = await fire("tool_call", call("bash", { command: `gh pr create --title t --body "a ${EM_DASH} b"` }));
	assert.equal(result.block, true);
	assert.match(result.reason, /PR gate/);
});

test("soft mode lets the edit run and appends the reminder to its result", async () => {
	mkdirSync(join(tmp, "config", "steward"));
	writeFileSync(join(tmp, "config", "steward", "gate"), "soft\n");
	const { fire } = load();
	await fire("tool_call", write());
	const second = write();
	assert.equal(await fire("tool_call", second), undefined);
	const result = await fire("tool_result", {
		type: "tool_result",
		toolCallId: second.toolCallId,
		toolName: "write",
		input: second.input,
		content: [{ type: "text", text: "wrote it" }],
		isError: false,
	});
	assert.equal(result.content.length, 2);
	assert.match(result.content[1].text, /direct edit #2/);
});

test("prose gate sends a reply back once, keeping earlier entries", async () => {
	const { fire } = load();
	const earlier = { type: "custom", customType: "other" };
	const reply = (text) => ({ role: "assistant", content: [{ type: "thinking", thinking: "t" }, { type: "text", text }] });
	const settle = (contextMessages) => ({
		type: "agent_before_settle",
		outcome: "completed",
		entries: [earlier],
		continue: false,
		// what pi reports for a finished reply: the context ends on the assistant turn
		context: { canContinue: false, contextMessages },
	});
	const bad = reply(`It is crucial ${EM_DASH} and pivotal.`);
	const first = await fire("agent_before_settle", settle([{ role: "user", content: "q" }, bad]));
	assert.equal(first.continue, true);
	assert.deepEqual(first.entries[0], earlier);
	assert.equal(first.entries[1].type, "custom_message");
	assert.equal(first.entries[1].customType, "steward-prose-gate");
	assert.match(first.entries[1].content, /prose gate/);

	// the revision is not sent back again, even if it still has tells
	const gateMessage = { role: "custom", customType: "steward-prose-gate", content: first.entries[1].content };
	const revised = [{ role: "user", content: "q" }, bad, gateMessage, reply(`Still ${EM_DASH} here.`)];
	assert.equal(await fire("agent_before_settle", settle(revised)), undefined);

	// a later turn is checked again
	const later = [...revised, { role: "user", content: "next" }, reply(`Again ${EM_DASH} here.`)];
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
		context: { canContinue: true, contextMessages: [{ role: "assistant", content: `a ${EM_DASH} b` }] },
	});
	assert.equal(result, undefined);
});

test("fails open when python cannot start", async () => {
	process.env.STEWARD_PYTHON = join(tmp, "no-such-python");
	const { fire, notices } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	assert.match(notices[0].msg, /python3 was not found/);
	const event = promptEvent();
	await fire("before_agent_start", event);
	assert.equal(event.systemPromptOptions.sections.steward, undefined);
	assert.equal(await fire("tool_call", write()), undefined);
	assert.equal(await fire("tool_call", write()), undefined);
});

test("launchesWork", () => {
	assert.equal(launchesWork({ agent: "steward.coder-opus-medium", task: "x" }), true);
	assert.equal(launchesWork({ workflow: true }), true);
	assert.equal(launchesWork({ workflow: "review", args: {} }), true);
	assert.equal(launchesWork({ action: "list" }), false);
	assert.equal(launchesWork({ action: "status", agent: "x" }), false);
	assert.equal(launchesWork({ action: "resume", id: "r1" }), true);
	assert.equal(launchesWork({}), false);
	assert.equal(launchesWork(undefined), false);
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
