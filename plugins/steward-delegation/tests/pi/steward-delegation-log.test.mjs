// Phase 4 of docs/roadmap/pi-model-plan.md: one JSON line per finished steward.* launch in
// $XDG_STATE_HOME/steward-delegation/pi-delegations.jsonl, and /steward-models stats. The fake
// pi-subagents results and events below copy the shapes pi-subagents 0.77.0 produced in a
// live probe on 2026-10-13 (see the plan doc): a sync result carries results[] with model,
// thinking and progressSummary.durationMs; an async launch result has asyncId and
// results: []; completion arrives as `subagent:async-complete` on pi.events.

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { classifyKind, createSteward, errorClass } from "../../pi/extensions/steward-delegation/index.ts";

const ENV_KEYS = ["HOME", "XDG_STATE_HOME", "PI_CODING_AGENT_DIR", "STEWARD_DELEGATION_GATE", "STEWARD_DELEGATION_PYTHON", "PI_SUBAGENT_CHILD", "STEWARD_DELEGATION_HOOK_LOG"];
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
	process.env.STEWARD_DELEGATION_HOOK_LOG = join(tmp, "hook.jsonl");
	for (const k of ["STEWARD_DELEGATION_GATE", "STEWARD_DELEGATION_PYTHON", "PI_SUBAGENT_CHILD"]) delete process.env[k];
});

afterEach(() => {
	for (const [k, v] of Object.entries(savedEnv)) {
		if (v === undefined) delete process.env[k];
		else process.env[k] = v;
	}
	rmSync(tmp, { recursive: true, force: true });
});

const logPath = () => join(tmp, "state", "steward-delegation", "pi-delegations.jsonl");
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
	const dir = join(tmp, "config", "steward-delegation");
	mkdirSync(dir, { recursive: true });
	writeFileSync(join(dir, "model-plan.json"), JSON.stringify({
		version: 1,
		roles: { mechanic: { model: "anthropic/claude-haiku-5-5", thinking: "low", fallback: ["anthropic/claude-sonnet-5-5"], escalate: "anthropic/claude-opus-5-5:high" } },
	}));
}

function launchStrings() {
	for (const line of readFileSync(process.env.STEWARD_DELEGATION_HOOK_LOG, "utf8").trim().split("\n")) {
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

test("the log rotates to a stamped name above the cap", async () => {
	const { fire } = load({ delegationLogMaxBytes: 200 });
	await fire("session_start", { type: "session_start", reason: "startup" });
	for (let i = 0; i < 3; i++) await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET }, { mode: "single", runId: `r${i}`, results: [syncRow()] }));
	assert.ok(readdirSync(join(tmp, "state", "steward-delegation")).some((n) => /^pi-delegations\.jsonl\.\d{8}T\d{9}Z-\d+$/.test(n)));
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

// Phase 4 review fixes.

test("errorClass reads anchored transport phrases, not any number or word", () => {
	for (const text of [
		"429 Too Many Requests",
		"HTTP 503 Service Unavailable",
		"status 502: bad gateway",
		"Error: 500 Internal Server Error",
		"provider returned rate_limit_error",
		"overloaded_error: Overloaded",
		"request timed out",
		"read ECONNRESET",
		"fetch failed",
	]) assert.equal(errorClass(text), "provider", text);
	for (const text of [
		"expected 500 items, got 499",
		"tests failed: assert status == 500",
		"network test suite failed",
		"provider config file missing",
		"forbidden word found in output",
		"Child exited with code 1",
	]) assert.equal(errorClass(text), "other", text);
});

test("a failed sync row is classified from its error field, never from the child's output", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET }, { mode: "single", runId: "e1", results: [syncRow({ exitCode: 1 })] }, { isError: true, text: "HTTP 503 rate limit overloaded" }));
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET }, { mode: "single", runId: "e2", results: [syncRow({ exitCode: 1, error: "429 Too Many Requests" })] }, { isError: true, text: "x" }));
	assert.deepEqual(logLines().map((l) => [l.status, l.errorClass]), [["error", "other"], ["error", "provider"]]);
});

test("detached and interrupted rows are not logged; the later completion is logged once with launch-time kind", async () => {
	writePlan();
	const { fire, emit } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	const strings = launchStrings();
	const input = { agent: "steward.mechanic", task: SECRET, model: strings.relaunch };
	await fire("tool_result", result(input, { mode: "single", runId: "D1", results: [syncRow({ exitCode: -2, detached: true, detachedReason: "user request" })] }, { text: "Detached at user request: steward.mechanic." }));
	await fire("tool_result", result(input, { mode: "single", runId: "I1", results: [syncRow({ interrupted: true })] }, { text: "Run paused after interrupt (steward.mechanic)." }));
	await fire("tool_result", result(input, { mode: "single", runId: "S1", results: [syncRow({ exitCode: 1, stopped: true })] }, { text: "stopped" }));
	assert.equal(logLines().length, 0);
	emit("subagent:async-complete", { id: "D1", runId: "D1", agent: "steward.mechanic", mode: "single", success: true, results: [{ agent: "steward.mechanic", success: true, model: "anthropic/claude-haiku-5-5:low" }] });
	emit("subagent:async-complete", { id: "D1", runId: "D1", agent: "steward.mechanic", mode: "single", success: true, results: [{ agent: "steward.mechanic", success: true }] });
	const lines = logLines();
	assert.equal(lines.length, 1);
	assert.deepEqual([lines[0].runId, lines[0].status, lines[0].mode, lines[0].kind, lines[0].modelParam], ["D1", "ok", "async", "relaunch", strings.relaunch]);
	// a stopped row with an error is a real outcome and is logged
	await fire("tool_result", result(input, { mode: "single", runId: "S2", results: [syncRow({ exitCode: 1, stopped: true, error: "Subagent stopped by user." })] }, { isError: true }));
	assert.equal(logLines().length, 2);
});

test("async kind is decided at launch, not at completion", async () => {
	writePlan();
	const { fire, emit } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	const strings = launchStrings();
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, async: true, model: strings.escalation }, { mode: "single", runId: "K1", asyncId: "K1", results: [] }));
	// the plan changes before the run finishes
	writeFileSync(join(tmp, "config", "steward-delegation", "model-plan.json"), JSON.stringify({ version: 1, roles: { mechanic: { model: "anthropic/claude-haiku-5-5", thinking: "low" } } }));
	await fire("session_start", { type: "session_start", reason: "reload" });
	emit("subagent:async-complete", { id: "K1", runId: "K1", agent: "steward.mechanic", mode: "single", success: true, results: [{ agent: "steward.mechanic", success: true }] });
	assert.equal(logLines()[0].kind, "escalation");
});

test("top-level tasks and chain launches are logged", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ tasks: [{ agent: "steward.mechanic", task: SECRET }, { agent: "steward.mechanic", task: SECRET, model: "other/model" }] },
		{ mode: "parallel", runId: "P1", results: [syncRow({ index: 0 }), syncRow({ index: 1 })] }));
	await fire("tool_result", result({ chain: [{ agent: "steward.mechanic", task: SECRET, model: "other/model" }] },
		{ mode: "chain", runId: "C1", results: [syncRow({ index: 0 })] }));
	assert.deepEqual(logLines().map((l) => [l.runId, l.kind]), [["P1", "plain"], ["P1", "operator"], ["C1", "operator"]]);
});

test("the log directory is 0700 and the file 0600, tightened when looser", async () => {
	const dir = join(tmp, "state", "steward-delegation");
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET }, { mode: "single", runId: "m1", results: [syncRow()] }));
	assert.equal(statSync(dir).mode & 0o777, 0o700);
	assert.equal(statSync(logPath()).mode & 0o777, 0o600);
	chmodSync(dir, 0o755);
	chmodSync(logPath(), 0o644);
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET }, { mode: "single", runId: "m2", results: [syncRow()] }));
	assert.equal(statSync(dir).mode & 0o777, 0o700);
	assert.equal(statSync(logPath()).mode & 0o777, 0o600);
});

test("a rejected launch caps and cleans the agent name and model param", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: `steward.x\n"${"y".repeat(300)}`, task: SECRET, model: `bad model\u0000${"z".repeat(300)}` }, {}, { isError: true, text: "Unknown agent" }));
	const [line] = logLines();
	assert.ok(line.agent.length <= 100 && /^[\w.:/@+-]+$/.test(line.agent), line.agent);
	assert.ok(line.modelParam.length <= 100 && /^[\w.:/@+-]+$/.test(line.modelParam), line.modelParam);
	assert.ok(line.agent.startsWith("steward.x_"));
});

test("rotation never overwrites an earlier rotated file", async () => {
	const { fire } = load({ delegationLogMaxBytes: 200 });
	await fire("session_start", { type: "session_start", reason: "startup" });
	for (let i = 0; i < 6; i++) await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET }, { mode: "single", runId: `q${i}`, results: [syncRow()] }));
	const dir = join(tmp, "state", "steward-delegation");
	const rotated = readdirSync(dir).filter((n) => n.startsWith("pi-delegations.jsonl."));
	assert.ok(rotated.length >= 1 && rotated.length <= 2, rotated.join(","));
	for (const n of rotated) assert.equal(statSync(join(dir, n)).mode & 0o777, 0o600);
});

// 0.14.2: `cwd` is where the child ran, `sessionCwd` where the session ran; line schema v2.
// pi-subagents 0.83.0 reports the run directory as `cwd` on `subagent:async-started`
// (src/runs/background/async-execution.js:1524,2115; workflows src/runs/foreground/
// subagent-executor.js:5379) and in the async result file the completion spreads
// (src/runs/background/subagent-runner.js:4800, src/runs/foreground/subagent-executor.js:6014).
// Sync results and workflow child records carry no cwd, so those fall back to the launch input.

test("a sync launch without a cwd logs the session directory as both fields, v2", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET }, { mode: "single", runId: "cw1", results: [syncRow()] }));
	const [line] = logLines();
	assert.equal(line.v, 2);
	assert.equal(line.cwd, join(tmp, "project"));
	assert.equal(line.sessionCwd, join(tmp, "project"));
});

test("a sync launch with an absolute or relative cwd logs the launch directory", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, cwd: "/tmp" }, { mode: "single", runId: "cw2", results: [syncRow()] }));
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, cwd: "sub/dir" }, { mode: "single", runId: "cw3", results: [syncRow()] }));
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, cwd: "../other" }, { mode: "single", runId: "cw4", results: [syncRow()] }));
	assert.deepEqual(logLines().map((l) => [l.cwd, l.sessionCwd]), [
		["/tmp", join(tmp, "project")],
		[join(tmp, "project", "sub", "dir"), join(tmp, "project")],
		[join(tmp, "other"), join(tmp, "project")],
	]);
});

test("per-item cwd in tasks and chain resolves against the top-level cwd", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result(
		{ cwd: "/srv", tasks: [{ agent: "steward.mechanic", task: SECRET, cwd: "a" }, { agent: "steward.mechanic", task: SECRET }, { agent: "steward.mechanic", task: SECRET, cwd: "/opt/x" }] },
		{ mode: "parallel", runId: "cw5", results: [syncRow({ index: 0 }), syncRow({ index: 1 }), syncRow({ index: 2 })] }));
	await fire("tool_result", result(
		{ chain: [{ agent: "steward.mechanic", task: SECRET, cwd: "c" }] },
		{ mode: "chain", runId: "cw6", results: [syncRow({ index: 0 })] }));
	assert.deepEqual(logLines().map((l) => l.cwd), ["/srv/a", "/srv", "/opt/x", join(tmp, "project", "c")]);
});

test("an async launch takes the cwd pi-subagents reports, else the launch input", async () => {
	const { fire, emit } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	// reported on async-started
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, async: true, cwd: "/tmp" }, { mode: "single", runId: "B1", asyncId: "B1", results: [] }));
	emit("subagent:async-started", { id: "B1", agent: "steward.mechanic", mode: "single", cwd: "/tmp/real" });
	emit("subagent:async-complete", { id: "B1", runId: "B1", agent: "steward.mechanic", mode: "single", success: true, results: [{ agent: "steward.mechanic", success: true }] });
	// reported only on the completion payload
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, async: true }, { mode: "single", runId: "B2", asyncId: "B2", results: [] }));
	emit("subagent:async-complete", { id: "B2", runId: "B2", agent: "steward.mechanic", mode: "single", success: true, cwd: "/var/tmp", results: [{ agent: "steward.mechanic", success: true }] });
	// not reported: relative launch cwd against the session
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, async: true, cwd: "rel" }, { mode: "single", runId: "B3", asyncId: "B3", results: [] }));
	emit("subagent:async-complete", { id: "B3", runId: "B3", agent: "steward.mechanic", mode: "single", success: true, results: [{ agent: "steward.mechanic", success: true }] });
	// not reported and no launch cwd
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, async: true }, { mode: "single", runId: "B4", asyncId: "B4", results: [] }));
	emit("subagent:async-complete", { id: "B4", runId: "B4", agent: "steward.mechanic", mode: "single", success: true, results: [{ agent: "steward.mechanic", success: true }] });
	const lines = logLines();
	assert.deepEqual(lines.map((l) => [l.mode, l.v, l.cwd, l.sessionCwd]), [
		["async", 2, "/tmp/real", join(tmp, "project")],
		["async", 2, "/var/tmp", join(tmp, "project")],
		["async", 2, join(tmp, "project", "rel"), join(tmp, "project")],
		["async", 2, join(tmp, "project"), join(tmp, "project")],
	]);
});

test("workflow children log the child's reported cwd, else the workflow's, else the launch input", async () => {
	const { fire, emit } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ workflow: "parallel", cwd: "wf", args: { tasks: [{ agent: "steward.mechanic", task: SECRET }] } },
		{ mode: "workflow", runId: "W2", asyncId: "W2", results: [], workflowChildren: { children: [] } }));
	emit("subagent:async-started", { id: "d1", mode: "single", agent: "steward.mechanic", parentWorkflowRunId: "W2", cwd: "/child/dir" });
	emit("subagent:async-complete", {
		id: "W2", runId: "W2", agent: "workflow", mode: "workflow", success: true, cwd: "/wf/reported",
		workflowChildren: { children: [
			{ childId: "k1", state: "completed", runId: "d1", agent: "steward.mechanic", model: "x/y" },
			{ childId: "k2", state: "completed", runId: "d2", agent: "steward.mechanic", model: "x/y" },
		] },
		results: [],
	});
	// no reported workflow cwd: the launch input, relative to the session
	await fire("tool_result", result({ workflow: "parallel", cwd: "wf", args: {} },
		{ mode: "workflow", runId: "W3", asyncId: "W3", results: [], workflowChildren: { children: [] } }));
	emit("subagent:async-complete", {
		id: "W3", runId: "W3", agent: "workflow", mode: "workflow", success: true,
		workflowChildren: { children: [{ childId: "k1", state: "completed", runId: "e1", agent: "steward.mechanic", model: "x/y" }] },
		results: [],
	});
	// no launch cwd at all: the session directory
	await fire("tool_result", result({ workflow: "parallel", args: {} },
		{ mode: "workflow", runId: "W4", asyncId: "W4", results: [], workflowChildren: { children: [] } }));
	emit("subagent:async-complete", {
		id: "W4", runId: "W4", agent: "workflow", mode: "workflow", success: true,
		workflowChildren: { children: [{ childId: "k1", state: "completed", runId: "f1", agent: "steward.mechanic", model: "x/y" }] },
		results: [],
	});
	assert.deepEqual(logLines().map((l) => [l.mode, l.v, l.cwd, l.sessionCwd]), [
		["workflow-child", 2, "/child/dir", join(tmp, "project")],
		["workflow-child", 2, "/wf/reported", join(tmp, "project")],
		["workflow-child", 2, join(tmp, "project", "wf"), join(tmp, "project")],
		["workflow-child", 2, join(tmp, "project"), join(tmp, "project")],
	]);
});

test("a rejected launch logs its launch cwd", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, cwd: "/nowhere" }, { results: [] }, { isError: true, text: "cwd does not exist" }));
	const [line] = logLines();
	assert.equal(line.cwd, "/nowhere");
	assert.equal(line.sessionCwd, join(tmp, "project"));
});

// Review fixes: async per-item cwd, chain parallel groups, cleaned cwd fields, remote launches.
test("an async tasks or chain run logs each row's own item cwd over the run-level cwd", async () => {
	const { fire, emit } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	const mech = (over = {}) => ({ agent: "steward.mechanic", task: SECRET, ...over });
	await fire("tool_result", result(
		{ async: true, cwd: "/srv", tasks: [mech({ cwd: "a", model: "x/one" }), mech(), mech({ cwd: "/opt/x" })] },
		{ mode: "parallel", runId: "P1", asyncId: "P1", results: [] }));
	// pi-subagents reports only the top-level runner directory for the whole run
	emit("subagent:async-started", { id: "P1", mode: "parallel", cwd: "/srv/real" });
	emit("subagent:async-complete", { id: "P1", runId: "P1", mode: "parallel", success: true, results: [
		{ agent: "steward.mechanic", success: true, index: 0 },
		{ agent: "steward.mechanic", success: true, index: 1 },
		{ agent: "steward.mechanic", success: true, index: 2 },
	] });
	// a single async launch keeps the reported run directory
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, async: true, cwd: "/tmp" }, { mode: "single", runId: "P2", asyncId: "P2", results: [] }));
	emit("subagent:async-started", { id: "P2", mode: "single", cwd: "/tmp/real" });
	emit("subagent:async-complete", { id: "P2", runId: "P2", mode: "single", success: true, results: [{ agent: "steward.mechanic", success: true }] });
	assert.deepEqual(logLines().map((l) => [l.cwd, l.modelParam]), [
		["/srv/real/a", "x/one"],
		["/srv/real", null],
		["/opt/x", null],
		["/tmp/real", null],
	]);
});

test("a chain with a parallel group indexes its flattened steps for cwd and model", async () => {
	const { fire, emit } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	const mech = (over = {}) => ({ agent: "steward.mechanic", task: SECRET, ...over });
	const chain = [
		mech({ cwd: "/a", model: "x/one" }),
		{ parallel: [mech({ cwd: "/b", model: "x/two" }), mech({ cwd: "/c" })] },
		mech({ cwd: "/d", model: "x/four" }),
	];
	await fire("tool_result", result({ chain }, { mode: "chain", runId: "G1", results: [0, 1, 2, 3].map((index) => syncRow({ index })) }));
	await fire("tool_result", result({ chain, async: true }, { mode: "chain", runId: "G2", asyncId: "G2", results: [] }));
	emit("subagent:async-complete", { id: "G2", runId: "G2", mode: "chain", success: true, results: [0, 1, 2, 3].map((index) => ({ agent: "steward.mechanic", success: true, index })) });
	const expected = [["/a", "x/one"], ["/b", "x/two"], ["/c", null], ["/d", "x/four"]];
	assert.deepEqual(logLines().map((l) => [l.cwd, l.modelParam]), [...expected, ...expected]);
});

test("cwd and sessionCwd are capped at 4096 characters with control characters stripped", async () => {
	const { fire } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, cwd: "/tmp/a\nb\u0007c\u001b[2Jd e" }, { mode: "single", runId: "S1", results: [syncRow()] }));
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, cwd: "/" + "x".repeat(5000) }, { mode: "single", runId: "S2", results: [syncRow()] }));
	const [a, b] = logLines();
	assert.equal(a.cwd, "/tmp/abc[2Jd e");
	assert.equal(b.cwd.length, 4096);
	assert.equal(a.sessionCwd, join(tmp, "project"));
});

test("a launch on a machine logs the session directory as cwd and names the machine as remote", async () => {
	const { fire, emit } = load();
	await fire("session_start", { type: "session_start", reason: "startup" });
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, machine: "build box", cwd: "/remote/dir" }, { mode: "single", runId: "R1", results: [syncRow()] }));
	await fire("tool_result", result(
		{ tasks: [{ agent: "steward.mechanic", task: SECRET, machine: "gpu1", cwd: "/r" }, { agent: "steward.mechanic", task: SECRET, cwd: "/local" }] },
		{ mode: "parallel", runId: "R2", results: [syncRow({ index: 0 }), syncRow({ index: 1 })] }));
	await fire("tool_result", result({ agent: "steward.mechanic", task: SECRET, async: true, machine: "gpu1", cwd: "/remote/dir" }, { mode: "single", runId: "R3", asyncId: "R3", results: [] }));
	emit("subagent:async-started", { id: "R3", mode: "single", cwd: "/remote/dir" });
	emit("subagent:async-complete", { id: "R3", runId: "R3", mode: "single", success: true, cwd: "/remote/dir", results: [{ agent: "steward.mechanic", success: true }] });
	const project = join(tmp, "project");
	assert.deepEqual(logLines().map((l) => [l.cwd, l.remote]), [
		[project, "build_box"],
		[project, "gpu1"],
		["/local", null],
		[project, "gpu1"],
	]);
});
