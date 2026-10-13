// Phase 4 of docs/roadmap/pi-model-plan.md: one JSON line per finished steward.* launch in
// $XDG_STATE_HOME/steward/pi-delegations.jsonl, and /steward-models stats. The fake
// pi-subagents results and events below copy the shapes pi-subagents 0.77.0 produced in a
// live probe on 2026-10-13 (see the plan doc): a sync result carries results[] with model,
// thinking and progressSummary.durationMs; an async launch result has asyncId and
// results: []; completion arrives as `subagent:async-complete` on pi.events.

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { classifyKind, createSteward, errorClass } from "../../pi/extensions/steward/index.ts";

const ENV_KEYS = ["HOME", "XDG_STATE_HOME", "PI_CODING_AGENT_DIR", "STEWARD_GATE", "STEWARD_PYTHON", "PI_SUBAGENT_CHILD", "STEWARD_HOOK_LOG"];
const LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];
const SECRET = "SECRET-TASK-TEXT";
const OUTPUT = "SECRET-CHILD-OUTPUT";

let tmp;
let savedEnv;
let counter = 0;

beforeEach(() => {
	savedEnv = Object.fromEntries(ENV_KEYS.map((k) => [k, process.env[k]]));
	tmp = mkdtempSync(join(tmpdir(), "steward-pi-log-test-"));
	for (const dir of ["home", "state", "config", "project"]) mkdirSync(join(tmp, dir));
	process.env.HOME = join(tmp, "home");
	process.env.XDG_STATE_HOME = join(tmp, "state");
	process.env.PI_CODING_AGENT_DIR = join(tmp, "config");
	process.env.STEWARD_HOOK_LOG = join(tmp, "hook.jsonl");
	for (const k of ["STEWARD_GATE", "STEWARD_PYTHON", "PI_SUBAGENT_CHILD"]) delete process.env[k];
});

afterEach(() => {
	for (const [k, v] of Object.entries(savedEnv)) {
		if (v === undefined) delete process.env[k];
		else process.env[k] = v;
	}
	rmSync(tmp, { recursive: true, force: true });
});

const logPath = () => join(tmp, "state", "steward", "pi-delegations.jsonl");
const logLines = () => (existsSync(logPath()) ? readFileSync(logPath(), "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l)) : []);

function m(full) {
	const i = full.indexOf("/");
	return { provider: full.slice(0, i), id: full.slice(i + 1), levels: LEVELS, maxTokens: 64000 };
}
const MODELS = ["anthropic/claude-opus-5-5", "anthropic/claude-sonnet-5-5", "anthropic/claude-haiku-5-5"].map(m);

function load(opts = {}) {
	const handlers = {};
	const listeners = {};
	const commands = {};
	const stdout = [];
	const pi = {
		on(name, handler) {
			(handlers[name] ??= []).push(handler);
		},
		events: {
			on(channel, fn) {
				(listeners[channel] ??= []).push(fn);
				return () => {};
			},
		},
		registerCommand(name, options) {
			commands[name] = options;
		},
		appendEntry() {},
		getAllTools: () => ["read", "bash", "edit", "write", "subagent"].map((name) => ({ name })),
		getActiveTools: () => ["read", "bash", "edit", "write", "subagent"],
	};
	createSteward({
		writeStdout: (t) => stdout.push(t),
		loadPiAi: async () => ({ getSupportedThinkingLevels: (model) => [...model.levels] }),
		...opts,
	})(pi);
	const id = `s${++counter}`;
	const ctx = {
		cwd: join(tmp, "project"),
		hasUI: false,
		mode: "print",
		ui: { notify() {} },
		sessionManager: { getSessionId: () => id },
		modelRegistry: {
			getAll: () => [...MODELS],
			getAvailable: () => [...MODELS],
			find: (p, i) => MODELS.find((x) => x.provider === p && x.id === i),
			hasConfiguredAuth: () => true,
		},
		model: MODELS[0],
		thinkingLevel: "high",
		isProjectTrusted: () => true,
	};
	const fire = async (name, event) => {
		let result;
		for (const h of handlers[name] ?? []) result = await h(event, ctx);
		return result;
	};
	const emit = (channel, data) => {
		for (const fn of listeners[channel] ?? []) fn(data);
	};
	return { handlers, listeners, fire, emit, commands, ctx, stdout, id };
}

let callCounter = 0;
function result(input, details, { isError = false, text = "ok" } = {}) {
	return { type: "tool_result", toolCallId: `c${++callCounter}`, toolName: "subagent", input, details, content: [{ type: "text", text }], isError };
}

function syncRow(over = {}) {
	return {
		index: 0,
		agent: "steward.mechanic",
		task: SECRET,
		exitCode: 0,
		finalOutput: OUTPUT,
		model: "anthropic/claude-haiku-5-5:low",
		thinking: "low",
		requestedModel: "anthropic/claude-haiku-5-5",
		progressSummary: { durationMs: 1046 },
		...over,
	};
}

function writePlan() {
	const dir = join(tmp, "config", "steward");
	mkdirSync(dir, { recursive: true });
	writeFileSync(join(dir, "model-plan.json"), JSON.stringify({
		version: 1,
		roles: { mechanic: { model: "anthropic/claude-haiku-5-5", thinking: "low", fallback: ["anthropic/claude-sonnet-5-5"], escalate: "anthropic/claude-opus-5-5:high" } },
	}));
}

function launchStrings() {
	for (const line of readFileSync(process.env.STEWARD_HOOK_LOG, "utf8").trim().split("\n")) {
		const row = JSON.parse(line);
		if (row.subcommand !== "session-start" || !row.stdout) continue;
		const out = JSON.parse(row.stdout).hookSpecificOutput;
		if (out.stewardLaunches) return out.stewardLaunches["steward.mechanic"];
	}
	return undefined;
}

test("classifyKind and errorClass", () => {
	const strings = { "steward.coder": { relaunch: "a/b:high", escalation: "c/d:xhigh" } };
	assert.equal(classifyKind("steward.coder", undefined, strings), "plain");
	assert.equal(classifyKind("steward.coder", "a/b:high", strings), "relaunch");
	assert.equal(classifyKind("steward.coder", "c/d:xhigh", strings), "escalation");
	assert.equal(classifyKind("steward.coder", "x/y", strings), "operator");
	assert.equal(classifyKind("steward.writer", "a/b:high", strings), "operator");
	assert.equal(errorClass("429 Too Many Requests: rate limit"), "provider");
	assert.equal(errorClass("HTTP 503 overloaded"), "provider");
	assert.equal(errorClass("Child exited with code 1: tests failed"), "other");
	assert.equal(errorClass(undefined), "other");
});

test("a sync launch logs one line with the resolved model and no task text", async () => {
	const { fire, id } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET }, { mode: "single", runId: "r1", results: [syncRow()] }, { text: OUTPUT }));
	const lines = logLines();
	assert.equal(lines.length, 1);
	const [line] = lines;
	assert.equal(line.agent, "steward.mechanic");
	assert.equal(line.model, "anthropic/claude-haiku-5-5");
	assert.equal(line.thinking, "low");
	assert.equal(line.modelParam, null);
	assert.equal(line.status, "ok");
	assert.equal(line.isError, false);
	assert.equal(line.errorClass, null);
	assert.equal(line.durationMs, 1046);
	assert.equal(line.mode, "sync");
	assert.equal(line.kind, "plain");
	assert.equal(line.sessionId, `pi-${id}`);
	assert.equal(line.cwd, join(tmp, "project"));
	assert.ok(!Number.isNaN(Date.parse(line.ts)));
	const raw = readFileSync(logPath(), "utf8");
	assert.doesNotMatch(raw, new RegExp(`${SECRET}|${OUTPUT}`));
});

test("relaunch and escalation strings come from the session-start data", async () => {
	writePlan();
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	const strings = launchStrings();
	assert.ok(strings?.relaunch, JSON.stringify(strings));
	assert.ok(strings?.escalation, JSON.stringify(strings));
	for (const model of [strings.relaunch, strings.escalation, "other/model", undefined]) {
		const input = { agent: "steward.mechanic", task: SECRET, ...(model ? { model } : {}) };
		await fire("tool_result", result(input, { mode: "single", runId: `k-${model}`, results: [syncRow()] }));
	}
	assert.deepEqual(logLines().map((l) => l.kind), ["relaunch", "escalation", "operator", "plain"]);
	assert.equal(logLines()[0].modelParam, strings.relaunch);
});

test("an async launch logs at completion, not at launch", async () => {
	const { fire, emit } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, async: true, model: "other/model" }, { mode: "single", runId: "A1", asyncId: "A1", results: [] }));
	emit("subagent:async-started", { id: "A1", agent: "steward.mechanic", mode: "single", task: SECRET });
	assert.equal(logLines().length, 0);
	emit("subagent:async-complete", {
		id: "A1", runId: "A1", agent: "steward.mechanic", mode: "single", success: false, state: "failed", summary: OUTPUT,
		results: [{ agent: "steward.mechanic", success: false, error: "provider returned 429 rate limit", output: OUTPUT, model: "anthropic/claude-haiku-5-5:low", thinking: "low" }],
	});
	// a repeated notice does not log twice
	emit("subagent:async-complete", { id: "A1", runId: "A1", agent: "steward.mechanic", mode: "single", success: false, results: [{ agent: "steward.mechanic", success: false }] });
	const lines = logLines();
	assert.equal(lines.length, 1);
	assert.equal(lines[0].mode, "async");
	assert.equal(lines[0].status, "error");
	assert.equal(lines[0].isError, true);
	assert.equal(lines[0].errorClass, "provider");
	assert.equal(lines[0].kind, "operator");
	assert.equal(lines[0].modelParam, "other/model");
	assert.equal(lines[0].model, "anthropic/claude-haiku-5-5");
	assert.equal(typeof lines[0].durationMs, "number");
	assert.doesNotMatch(readFileSync(logPath(), "utf8"), new RegExp(`${SECRET}|${OUTPUT}|429`));
});

test("workflow children log one line each at workflow completion", async () => {
	const { fire, emit } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ workflow: "parallel", args: { tasks: [{ agent: "steward.mechanic", task: SECRET }, { agent: "steward.mechanic", task: SECRET }] } },
		{ mode: "workflow", runId: "W", asyncId: "W", results: [], workflowChildren: { children: [] } }));
	emit("subagent:async-started", { id: "W", mode: "workflow", agent: "workflow" });
	emit("subagent:async-started", { id: "c1", mode: "single", agent: "steward.mechanic", parentWorkflowRunId: "W" });
	emit("subagent:async-started", { id: "c2", mode: "single", agent: "steward.mechanic", parentWorkflowRunId: "W" });
	emit("subagent:async-complete", { id: "c1", runId: "c1", agent: "steward.mechanic", mode: "single", success: true, awaitedByWorkflow: true, parentWorkflowRunId: "W" });
	emit("subagent:async-complete", { id: "c2", runId: "c2", agent: "steward.mechanic", mode: "single", success: false, awaitedByWorkflow: true, parentWorkflowRunId: "W" });
	assert.equal(logLines().length, 0);
	emit("subagent:async-complete", {
		id: "W", runId: "W", agent: "workflow", mode: "workflow", success: false, output: OUTPUT,
		workflowChildren: { children: [
			{ childId: "task-1", state: "completed", runId: "c1", agent: "steward.mechanic", model: "ollama-cloud/deepseek-v4.1-flash:high" },
			{ childId: "task-2", state: "failed", runId: "c2", agent: "steward.mechanic", model: "ollama-cloud/deepseek-v4.1-flash:high" },
			{ childId: "task-3", state: "completed", runId: "c3", agent: "worker", model: "x/y" },
		] },
		results: [{ runId: "c1", agent: "steward.mechanic", success: true, output: OUTPUT }, { runId: "c2", agent: "steward.mechanic", success: false, error: "tests failed" }],
	});
	const lines = logLines();
	assert.equal(lines.length, 2);
	assert.deepEqual(lines.map((l) => [l.mode, l.status, l.model, l.thinking, l.kind]), [
		["workflow-child", "ok", "ollama-cloud/deepseek-v4.1-flash", "high", "plain"],
		["workflow-child", "error", "ollama-cloud/deepseek-v4.1-flash", "high", "plain"],
	]);
	assert.equal(lines[1].errorClass, "other");
	assert.ok(lines.every((l) => typeof l.durationMs === "number"));
	assert.doesNotMatch(readFileSync(logPath(), "utf8"), new RegExp(`${SECRET}|${OUTPUT}`));
});

test("non-steward agents and management calls are not logged", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: "worker", task: SECRET }, { mode: "single", runId: "x", results: [syncRow({ agent: "worker" })] }));
	await fire("tool_result", result({ action: "list" }, { results: [] }));
	assert.equal(logLines().length, 0);
});

test("a rejected launch logs an error line", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, model: "nope/model" }, {}, { isError: true, text: "Unknown model nope/model" }));
	const [line] = logLines();
	assert.equal(line.status, "error");
	assert.equal(line.errorClass, "other");
	assert.equal(line.model, null);
	assert.equal(line.kind, "operator");
});

test("write errors fail open", async () => {
	writeFileSync(join(tmp, "state-file"), "x");
	process.env.XDG_STATE_HOME = join(tmp, "state-file");
	const { fire, emit } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	assert.equal(await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET }, { mode: "single", runId: "r", results: [syncRow()] })), undefined);
	emit("subagent:async-complete", { id: "Z", runId: "Z", agent: "steward.mechanic", mode: "single", success: true, results: [{ agent: "steward.mechanic", success: true }] });
	emit("subagent:async-complete", null);
});

test("child sessions do not log", async () => {
	process.env.PI_SUBAGENT_CHILD = "1";
	const { handlers, listeners } = load();
	assert.deepEqual(handlers, {});
	assert.deepEqual(listeners, {});
});

test("the log rotates to .1 above the cap", async () => {
	const { fire } = load({ delegationLogMaxBytes: 200 });
	await fire("session_start", { type: "session_start", reason: "startup" });
	for (let i = 0; i < 3; i++) await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET }, { mode: "single", runId: `r${i}`, results: [syncRow()] }));
	assert.ok(existsSync(`${logPath()}.1`));
	assert.ok(logLines().length >= 1 && logLines().length < 3);
});

test("/steward-models stats prints the summary", async () => {
	const { fire, commands, ctx, stdout } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET }, { mode: "single", runId: "r1", results: [syncRow()] }));
	await commands["steward-models"].handler("stats", ctx);
	assert.match(stdout.join(""), /\| steward\.mechanic \| anthropic\/claude-haiku-5-5 \| 1 \| 1 \| 0 \| 100% \|/);
	stdout.length = 0;
	await commands["steward-models"].handler("stats --days 30", ctx);
	assert.match(stdout.join(""), /last 30 days/);
	stdout.length = 0;
	await commands["steward-models"].handler("stats --days x", ctx);
	assert.match(stdout.join(""), /Usage/);
});
