// Phase 2c of docs/roadmap/pi-model-plan.md: the extension gathers registry
// facts for the session-start payload, rebuilds the edict on model_select,
// and adds /steward-models. Handlers run against the real
// hooks/steward_hook.py; HOME and pi's config dir point at a throwaway
// directory. STEWARD_HOOK_LOG captures the real hook stdin and stdout.

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join } from "node:path";

import steward, { createSteward, FACTS_TIMEOUT_MS, gatherModelFacts, HOOK_TIMEOUT_MS, runHook } from "../../pi/extensions/steward/index.ts";

const ENV_KEYS = ["HOME", "XDG_STATE_HOME", "PI_CODING_AGENT_DIR", "STEWARD_GATE", "STEWARD_PYTHON", "PI_SUBAGENT_CHILD", "STEWARD_HOOK_LOG"];
const ALL_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];
const BLOCK_HEADING = "## Model plan on this machine";

let tmp;
let savedEnv;
let counter = 0;

beforeEach(() => {
	savedEnv = Object.fromEntries(ENV_KEYS.map((k) => [k, process.env[k]]));
	tmp = mkdtempSync(join(tmpdir(), "steward-pi-plan-test-"));
	for (const dir of ["home", "state", "config", "project"]) mkdirSync(join(tmp, dir));
	process.env.HOME = join(tmp, "home");
	process.env.XDG_STATE_HOME = join(tmp, "state");
	process.env.PI_CODING_AGENT_DIR = join(tmp, "config");
	for (const k of ["STEWARD_GATE", "STEWARD_PYTHON", "PI_SUBAGENT_CHILD"]) delete process.env[k];
	process.env.STEWARD_HOOK_LOG = join(tmp, "hook.jsonl");
});

afterEach(() => {
	for (const [k, v] of Object.entries(savedEnv)) {
		if (v === undefined) delete process.env[k];
		else process.env[k] = v;
	}
	rmSync(tmp, { recursive: true, force: true });
});

function m(full, { levels = ALL_LEVELS, maxTokens = 128000, reasoning = true } = {}) {
	const i = full.indexOf("/");
	return { provider: full.slice(0, i), id: full.slice(i + 1), levels, maxTokens, reasoning, api: "anthropic-messages" };
}

const REGISTRY_MODELS = [
	m("anthropic/claude-opus-5-5"),
	m("anthropic/claude-sonnet-5-5"),
	m("anthropic/claude-haiku-5-5", { levels: ["off", "minimal", "low", "medium", "high"] }),
	m("amorphic/claude-opus-5-5"),
	m("openai-codex/gpt-6.1-sol", { levels: ["off", "minimal", "low", "medium", "high", "xhigh"] }),
	m("ollama-cloud/deepseek-v4.1-flash", { levels: ["off", "minimal", "low", "medium", "high"], maxTokens: 16384 }),
];
const NO_AUTH = new Set(["ollama-cloud"]);

function fakeRegistry(models = REGISTRY_MODELS) {
	return {
		getAll: () => [...models],
		getAvailable: () => models.filter((x) => !NO_AUTH.has(x.provider)),
		find: (p, id) => models.find((x) => x.provider === p && x.id === id),
		hasConfiguredAuth: (model) => !NO_AUTH.has(model.provider),
	};
}

const fakePiAi = { getSupportedThinkingLevels: (model) => [...model.levels] };

// An option given as undefined stays undefined (no default), so tests can model a missing value.
function load(opts = {}) {
	const pick = (key, fallback) => (Object.hasOwn(opts, key) ? opts[key] : fallback);
	const piAi = pick("piAi", fakePiAi);
	const registry = pick("registry", fakeRegistry());
	const model = pick("model", REGISTRY_MODELS[3]);
	const thinkingLevel = pick("thinkingLevel", "xhigh");
	const { cwd, factory, hookTimeoutMs, factsTimeoutMs } = opts;
	const stdout = [];
	const handlers = {};
	const commands = {};
	const sent = [];
	const entries = [];
	const entryRenderers = {};
	const notices = [];
	const pi = {
		on(name, handler) {
			(handlers[name] ??= []).push(handler);
		},
		registerCommand(name, options) {
			commands[name] = options;
		},
		sendMessage(message, options) {
			sent.push({ message, options });
		},
		appendEntry(customType, data) {
			entries.push({ customType, data });
		},
		registerEntryRenderer(customType, renderer) {
			entryRenderers[customType] = renderer;
		},
		getAllTools: () => ["read", "bash", "edit", "write", "subagent"].map((name) => ({ name })),
		getActiveTools: () => ["read", "bash", "edit", "write", "subagent"],
	};
	const make = factory ?? createSteward({ hookTimeoutMs, factsTimeoutMs, writeStdout: (text) => stdout.push(text), loadPiAi: async () => {
		if (piAi instanceof Error) throw piAi;
		return piAi;
	} });
	make(pi);
	const id = `p${++counter}`;
	const ctx = {
		cwd: cwd ?? join(tmp, "project"),
		hasUI: false,
		ui: { notify: (msg, level) => notices.push({ msg, level }) },
		sessionManager: { getSessionId: () => id },
		modelRegistry: registry,
		model,
		thinkingLevel,
		isProjectTrusted: () => true,
	};
	// `at` is the ctx a handler sees: by default the shared one; a test of overlapping events
	// passes a snapshot so each event keeps the model it was fired with.
	const fire = async (name, event, at = ctx) => {
		let result;
		for (const h of handlers[name] ?? []) result = await h(event, at);
		return result;
	};
	const shown = () => entries.filter((e) => e.customType === "steward-models").map((e) => e.data.text);
	return { handlers, commands, sent, entries, entryRenderers, shown, notices, stdout, ctx, fire };
}

function promptEvent() {
	return { type: "before_agent_start", prompt: "hi", systemPrompt: "base", systemPromptOptions: { sections: {} } };
}

async function sectionAfterStart(env) {
	await env.fire("session_start", { type: "session_start", reason: "startup" });
	const event = promptEvent();
	await env.fire("before_agent_start", event);
	return event.systemPromptOptions.sections.steward;
}

function hookLog() {
	const path = process.env.STEWARD_HOOK_LOG;
	if (!existsSync(path)) return [];
	return readFileSync(path, "utf8").trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
}

function sessionStartPayloads() {
	return hookLog().filter((e) => e.kind === "hook" && e.subcommand === "session-start").map((e) => e.payload);
}

test("gatherModelFacts builds the facts contract from the registry", () => {
	const env = load();
	const facts = gatherModelFacts(env.ctx, fakePiAi);
	assert.deepEqual(Object.keys(facts).sort(), ["cwd", "main", "models", "projectTrusted"]);
	assert.deepEqual(facts.main, { provider: "amorphic", id: "claude-opus-5-5", thinkingLevel: "xhigh" });
	assert.equal(facts.projectTrusted, true);
	assert.equal(facts.cwd, join(tmp, "project"));
	assert.equal(facts.models.length, REGISTRY_MODELS.length);
	const flash = facts.models.find((x) => x.provider === "ollama-cloud");
	assert.deepEqual(flash, {
		provider: "ollama-cloud",
		id: "deepseek-v4.1-flash",
		available: false,
		thinkingLevels: ["off", "minimal", "low", "medium", "high"],
		maxTokens: 16384,
	});
	assert.equal(facts.models.find((x) => x.id === "gpt-6.1-sol").available, true);
});

test("gatherModelFacts: no main model gives main null; a relative cwd is made absolute", () => {
	const env = load({ model: undefined, cwd: "rel/dir" });
	const facts = gatherModelFacts(env.ctx, fakePiAi);
	assert.equal(facts.main, null);
	assert.ok(isAbsolute(facts.cwd));
});

test("gatherModelFacts returns undefined when anything is missing or throws", () => {
	const bad = [
		{ registry: { ...fakeRegistry(), getAll: () => { throw new Error("boom"); } } },
		{ registry: undefined },
		{ registry: { ...fakeRegistry(), hasConfiguredAuth: () => { throw new Error("boom"); } } },
		{ thinkingLevel: undefined },
	];
	for (const opts of bad) {
		const env = load(opts);
		assert.equal(gatherModelFacts(env.ctx, fakePiAi), undefined, JSON.stringify(Object.keys(opts)));
	}
	const env = load();
	assert.equal(gatherModelFacts(env.ctx, undefined), undefined);
	assert.equal(gatherModelFacts(env.ctx, { getSupportedThinkingLevels: () => { throw new Error("x"); } }), undefined);
	env.ctx.isProjectTrusted = () => { throw new Error("x"); };
	assert.equal(gatherModelFacts(env.ctx, fakePiAi), undefined);
});

test("session-start payload carries model_facts and the edict carries the block", async () => {
	const env = load();
	const text = await sectionAfterStart(env);
	const payloads = sessionStartPayloads();
	assert.equal(payloads.length, 1);
	const facts = payloads[0].model_facts;
	assert.ok(facts, "model_facts in the payload");
	assert.deepEqual(facts.main, { provider: "amorphic", id: "claude-opus-5-5", thinkingLevel: "xhigh" });
	assert.equal(facts.models.length, REGISTRY_MODELS.length);
	assert.match(text, /steward-delegating/);
	assert.ok(text.includes(BLOCK_HEADING), "block in the edict");
	assert.ok(text.includes("Main thread: amorphic/claude-opus-5-5 at xhigh."));
	assert.ok(hookLog().some((e) => e.kind === "facts" && typeof e.ms === "number" && e.models === REGISTRY_MODELS.length));
});

async function plainEdict() {
	const { output } = await runHook("session-start", { session_id: "pi-plain" });
	return output.hookSpecificOutput.additionalContext;
}

test("a throwing registry omits model_facts and the edict is byte-identical to today", async () => {
	const registry = { ...fakeRegistry(), getAll: () => { throw new Error("registry down"); } };
	const text = await sectionAfterStart(load({ registry }));
	assert.equal(text, await plainEdict());
	assert.ok(!text.includes(BLOCK_HEADING));
	assert.ok(sessionStartPayloads().every((p) => !("model_facts" in p)));
});

test("pi-ai that cannot be imported omits model_facts", async () => {
	const text = await sectionAfterStart(load({ piAi: new Error("Cannot find module '@earendil-works/pi-ai'") }));
	assert.equal(text, await plainEdict());
	assert.ok(sessionStartPayloads().every((p) => !("model_facts" in p)));
});

test("the default factory outside pi (no pi-ai alias) omits model_facts", async () => {
	const text = await sectionAfterStart(load({ factory: steward }));
	assert.equal(text, await plainEdict());
});

test("model_select rebuilds the edict; the next before_agent_start uses the new block", async () => {
	const env = load();
	const before = await sectionAfterStart(env);
	assert.ok(before.includes("Main thread: amorphic/claude-opus-5-5 at xhigh."));
	const sol = REGISTRY_MODELS[4];
	const previous = env.ctx.model;
	env.ctx.model = sol;
	env.ctx.thinkingLevel = "high";
	await env.fire("model_select", { type: "model_select", model: sol, previousModel: previous, source: "set" });
	const event = promptEvent();
	await env.fire("before_agent_start", event);
	const after = event.systemPromptOptions.sections.steward;
	assert.ok(after.includes("Main thread: openai-codex/gpt-6.1-sol at high."), after.slice(-2000));
	assert.ok(!after.includes("Main thread: amorphic/claude-opus-5-5"));
	const payloads = sessionStartPayloads();
	assert.equal(payloads.length, 2);
	assert.equal(payloads[1].model_facts.main.id, "gpt-6.1-sol");
});

test("model_select with a failing registry falls back to the plain edict", async () => {
	const env = load();
	await sectionAfterStart(env);
	env.ctx.modelRegistry = { getAll: () => { throw new Error("gone"); } };
	await env.fire("model_select", { type: "model_select", model: REGISTRY_MODELS[4], previousModel: undefined, source: "cycle" });
	const event = promptEvent();
	await env.fire("before_agent_start", event);
	assert.equal(event.systemPromptOptions.sections.steward, await plainEdict());
});

test("/steward-models is registered and check shows the report", async () => {
	const env = load({ cwd: "relative/project" });
	assert.ok(env.commands["steward-models"], "command registered");
	assert.equal(typeof env.commands["steward-models"].description, "string");
	for (const args of ["check", "", "  check  "]) {
		env.entries.length = 0;
		await env.commands["steward-models"].handler(args, env.ctx);
		assert.equal(env.entries.length, 1, `args ${JSON.stringify(args)}`);
		const { customType, data } = env.entries[0];
		assert.equal(customType, "steward-models");
		assert.ok(data.text.includes(BLOCK_HEADING), data.text.slice(0, 500));
	}
	assert.equal(env.sent.length, 0, "the report is never a session message");
	const calls = hookLog().filter((e) => e.kind === "hook" && e.subcommand === "model-plan");
	assert.equal(calls.length, 3);
	for (const call of calls) {
		assert.ok(isAbsolute(call.payload.cwd));
		assert.ok(call.payload.model_facts);
		assert.ok(isAbsolute(call.payload.model_facts.cwd));
		assert.match(call.stdout, /"report"/);
	}
});

test("/steward-models stats shows the summary; bad arguments show the usage", async () => {
	const env = load();
	for (const sub of ["stats", "stats --days 30"]) {
		env.entries.length = 0;
		await env.commands["steward-models"].handler(sub, env.ctx);
		assert.equal(env.shown().length, 1);
		assert.match(env.shown()[0], /No steward launches logged/);
	}
	assert.equal(hookLog().filter((e) => e.subcommand === "model-plan").length, 0);
	for (const args of ["frobnicate", "apply --force", "check --yes", "stats --days", "stats --days 0", "stats 7"]) {
		env.entries.length = 0;
		await env.commands["steward-models"].handler(args, env.ctx);
		assert.match(env.shown()[0], /Usage: \/steward-models \[check\|apply \[--yes\]\|stats \[--days N\]\]/, args);
	}
	env.entries.length = 0;
	await env.commands["steward-models"].handler("frobnicate", env.ctx);
	assert.match(env.shown()[0], /Usage: \/steward-models \[check\|apply \[--yes\]\|stats \[--days N\]\]/);
	assert.equal(env.sent.length, 0);
});

test("/steward-models check: a failing hook gives a short error, never a crash", async () => {
	const fake = join(tmp, "fake-python");
	writeFileSync(fake, "#!/bin/sh\necho 'not json'\nexit 1\n");
	chmodSync(fake, 0o755);
	process.env.STEWARD_PYTHON = fake;
	const env = load();
	await env.commands["steward-models"].handler("check", env.ctx);
	assert.equal(env.shown().length, 1);
	assert.match(env.shown()[0], /^steward: \/steward-models check failed/);
	assert.ok(env.shown()[0].length < 300);

	process.env.STEWARD_PYTHON = join(tmp, "no-such-python");
	env.entries.length = 0;
	await env.commands["steward-models"].handler("check", env.ctx);
	assert.match(env.shown()[0], /python3 was not found/);
});

test("/steward-models check: the hook's error message is shown", async () => {
	const fake = join(tmp, "fake-python");
	writeFileSync(fake, `#!/bin/sh\necho '{"error": "model-plan: cwd must be an absolute path, got a relative one"}'\nexit 2\n`);
	chmodSync(fake, 0o755);
	process.env.STEWARD_PYTHON = fake;
	const env = load();
	await env.commands["steward-models"].handler("check", env.ctx);
	assert.match(env.shown()[0], /failed: model-plan: cwd must be an absolute path/);
});

test("/steward-models check without registry facts says so", async () => {
	const env = load({ registry: undefined });
	await env.commands["steward-models"].handler("check", env.ctx);
	assert.match(env.shown()[0], /could not read pi's model registry/);
	assert.equal(hookLog().filter((e) => e.subcommand === "model-plan").length, 0);
});

test("the child guard registers no command and no handler", () => {
	process.env.PI_SUBAGENT_CHILD = "1";
	const env = load();
	assert.deepEqual(env.handlers, {});
	assert.deepEqual(env.commands, {});
});

// ---- Phase 2c review fixes: generation guard, plain-edict retry, display-only report,
// thinking-level rebuild.

/** A stand-in python that runs `prelude` (shell, with the payload in $input) and then the real hook. */
function wrapPython(prelude) {
	const path = join(tmp, `py-${++counter}`);
	writeFileSync(path, `#!/bin/sh\ninput=$(cat)\n${prelude}\nprintf '%s' "$input" | exec python3 "$@"\n`);
	chmodSync(path, 0o755);
	return path;
}

const SONNET_ANTHROPIC = REGISTRY_MODELS[1];
const SOL = REGISTRY_MODELS[4];
// "Main thread: <model> at <level>." without the plan-membership tail.
const mainLine = (text) => (text ?? "").split("\n").find((line) => line.startsWith("Main thread:"))?.split(". ")[0] + ".";

async function sectionNow(env, at) {
	const event = promptEvent();
	await env.fire("before_agent_start", event, at);
	return event.systemPromptOptions.sections.steward;
}

test("two overlapping model switches resolving out of order end on the newest block", async () => {
	const env = load();
	await sectionAfterStart(env);
	process.env.STEWARD_PYTHON = wrapPython(`case "$input" in *'"main":{"provider":"openai-codex"'*) sleep 1 ;; esac`);
	const first = { ...env.ctx, model: SOL, thinkingLevel: "high" };
	const second = { ...env.ctx, model: SONNET_ANTHROPIC, thinkingLevel: "medium" };
	const slow = env.fire("model_select", { type: "model_select", model: SOL, previousModel: env.ctx.model, source: "set" }, first);
	const fast = env.fire("model_select", { type: "model_select", model: SONNET_ANTHROPIC, previousModel: SOL, source: "set" }, second);
	await Promise.all([slow, fast]);
	assert.equal(mainLine(await sectionNow(env, second)), "Main thread: anthropic/claude-sonnet-5-5 at medium.");
	// The handlers do not wait for the hook, so the older, slower load is still running: let it
	// end, then check that it changed nothing.
	await new Promise((r) => setTimeout(r, 1300));
	assert.equal(mainLine(await sectionNow(env, second)), "Main thread: anthropic/claude-sonnet-5-5 at medium.");
});

test("a thinking change then a model switch, out of order, end on the newest block", async () => {
	const env = load();
	await sectionAfterStart(env);
	process.env.STEWARD_PYTHON = wrapPython(`case "$input" in *'"thinkingLevel":"low"'*) sleep 1 ;; esac`);
	const first = { ...env.ctx, thinkingLevel: "low" };
	const second = { ...env.ctx, model: SOL, thinkingLevel: "high" };
	const slow = env.fire("thinking_level_select", { type: "thinking_level_select", level: "low", previousLevel: "xhigh" }, first);
	const fast = env.fire("model_select", { type: "model_select", model: SOL, previousModel: env.ctx.model, source: "set" }, second);
	await Promise.all([slow, fast]);
	assert.equal(mainLine(await sectionNow(env, second)), "Main thread: openai-codex/gpt-6.1-sol at high.");
	// The handlers do not wait for the hook, so the older, slower load is still running: let it
	// end, then check that it changed nothing.
	await new Promise((r) => setTimeout(r, 1300));
	assert.equal(mainLine(await sectionNow(env, second)), "Main thread: openai-codex/gpt-6.1-sol at high.");
});

test("before_agent_start during a failing rebuild keeps the previous edict and starts no second load", async () => {
	const env = load();
	const before = await sectionAfterStart(env);
	const calls = sessionStartPayloads().length;
	process.env.STEWARD_PYTHON = wrapPython("sleep 0.3; exit 1");
	const at = { ...env.ctx, model: SOL, thinkingLevel: "high" };
	const switching = env.fire("model_select", { type: "model_select", model: SOL, previousModel: env.ctx.model, source: "set" }, at);
	const during = await sectionNow(env, at);
	await switching;
	assert.equal(during, before, "the previous edict, never none");
	// The rebuild's own two calls (facts, then plain); the prompt shared that load.
	assert.equal(sessionStartPayloads().length - calls, 2);
	// The reminder for prompt-less runs still has an edict while the rebuild fails.
	await env.fire("agent_settled", { type: "agent_settled" });
	const ctxResult = await env.fire("context", { type: "context", messages: [] }, at);
	assert.ok(ctxResult?.messages?.some((m) => m.customType === "steward-edict"));
});

test("before_agent_start during a slow rebuild shares the in-flight load and gets the new block", async () => {
	const env = load();
	await sectionAfterStart(env);
	const calls = sessionStartPayloads().length;
	process.env.STEWARD_PYTHON = wrapPython("sleep 0.3");
	const at = { ...env.ctx, model: SOL, thinkingLevel: "high" };
	const switching = env.fire("model_select", { type: "model_select", model: SOL, previousModel: env.ctx.model, source: "set" }, at);
	const during = await sectionNow(env, at);
	await switching;
	assert.equal(mainLine(during), "Main thread: openai-codex/gpt-6.1-sol at high.");
	assert.equal(sessionStartPayloads().length - calls, 1);
});

for (const [name, prelude, factsTimeoutMs] of [
	["times out", "sleep 3", 300],
	["prints bad JSON", "echo 'not json'; exit 0", undefined],
	["crashes", "echo 'Traceback' >&2; exit 1", undefined],
]) {
	test(`a facts-bearing session-start that ${name} falls back to the plain edict, once per switch`, async () => {
		const reallyPlain = await plainEdict();
		process.env.STEWARD_PYTHON = wrapPython(`case "$input" in *'"model_facts"'*) ${prelude} ;; esac`);
		const env = load({ factsTimeoutMs });
		const text = await sectionAfterStart(env);
		assert.equal(text, reallyPlain);
		const payloads = sessionStartPayloads().slice(1); // [0] is plainEdict() above
		assert.deepEqual(payloads.map((p) => "model_facts" in p), [true, false]);
		if (factsTimeoutMs) assert.ok(hookLog().some((e) => e.kind === "hook" && e.timedOut === true));
		// Later prompts do not retry with facts.
		await env.fire("agent_settled", { type: "agent_settled" });
		assert.equal(await sectionNow(env), reallyPlain);
		assert.equal(sessionStartPayloads().length - 1, 2);
		// A thinking switch tries the facts again, and falls back again.
		env.ctx.thinkingLevel = "low";
		await env.fire("thinking_level_select", { type: "thinking_level_select", level: "low", previousLevel: "xhigh" });
		assert.equal(await sectionNow(env), reallyPlain);
		assert.deepEqual(sessionStartPayloads().slice(1).map((p) => "model_facts" in p), [true, false, true, false]);
	});
}

test("thinking_level_select rebuilds the main-thread line", async () => {
	const env = load();
	const before = await sectionAfterStart(env);
	assert.equal(mainLine(before), "Main thread: amorphic/claude-opus-5-5 at xhigh.");
	env.ctx.thinkingLevel = "low";
	await env.fire("thinking_level_select", { type: "thinking_level_select", level: "low", previousLevel: "xhigh" });
	assert.equal(mainLine(await sectionNow(env)), "Main thread: amorphic/claude-opus-5-5 at low.");
	assert.equal(sessionStartPayloads().at(-1).model_facts.main.thinkingLevel, "low");
});

test("a hook that cannot start is logged", async () => {
	process.env.STEWARD_PYTHON = join(tmp, "no-such-python");
	const { missingPython } = await runHook("session-start", { session_id: "pi-x" });
	assert.equal(missingPython, true);
	assert.ok(hookLog().some((e) => e.kind === "hook" && e.subcommand === "session-start" && e.error === "ENOENT"));
});

test("STEWARD_HOOK_LOG records session-start and model-plan calls only, never gate inputs or replies", async () => {
	await runHook("gate", { session_id: "pi-x", tool_name: "Bash", tool_input: { command: "echo secret-gate-input" } });
	await runHook("prose-gate", { session_id: "pi-x", last_assistant_message: "secret-reply-text" });
	await runHook("delegated", { session_id: "pi-x" });
	await runHook("session-start", { session_id: "pi-x" });
	const subcommands = hookLog().filter((e) => e.kind === "hook").map((e) => e.subcommand);
	assert.deepEqual(subcommands, ["session-start"]);
	const raw = existsSync(process.env.STEWARD_HOOK_LOG) ? readFileSync(process.env.STEWARD_HOOK_LOG, "utf8") : "";
	assert.ok(!raw.includes("secret-gate-input") && !raw.includes("secret-reply-text"));
});

test("/steward-models check is display-only: an entry, never a message in the model's context", async () => {
	const env = load();
	await sectionAfterStart(env);
	assert.equal(typeof env.entryRenderers["steward-models"], "function");
	env.ctx.hasUI = true;
	await env.commands["steward-models"].handler("check", env.ctx);
	assert.equal(env.sent.length, 0);
	assert.equal(env.shown().length, 1);
	assert.equal(env.notices.length, 0, "with a UI the entry is the display");
	// Nothing the extension adds to a request carries the report.
	const result = await env.fire("context", { type: "context", messages: [] });
	for (const m of result?.messages ?? []) assert.ok(!JSON.stringify(m).includes("Effective bindings"));
	// The renderer draws the report text.
	const theme = { fg: (_c, t) => t, bg: (_c, t) => t, bold: (t) => t };
	const component = env.entryRenderers["steward-models"]({ type: "custom", customType: "steward-models", data: { text: env.shown()[0] } }, { expanded: false }, theme);
	const lines = component.render(100).join("\n");
	assert.ok(lines.includes(BLOCK_HEADING), lines.slice(0, 300));
	assert.ok(component.render(100).every((line) => line.length <= 100));
});

test("/steward-models check without a UI also notifies", async () => {
	const env = load();
	await env.commands["steward-models"].handler("stats", env.ctx);
	assert.equal(env.sent.length, 0);
	assert.equal(env.notices.length, 1);
	assert.match(env.notices[0].msg, /No steward launches logged/);
});

// ---- Print mode drops notify and draws no entries, so the report goes to stdout there.
// pi 1.1.0 takes over process.stdout in every non-interactive mode (main.js, takeOverStdout),
// so the extension writes fd 1 itself; JSON and RPC already stream the entry as entry_appended.

test("/steward-models check in print mode writes the report to stdout", async () => {
	const env = load();
	env.ctx.mode = "print";
	await env.commands["steward-models"].handler("check", env.ctx);
	assert.equal(env.sent.length, 0);
	assert.equal(env.stdout.length, 1);
	assert.ok(env.stdout[0].includes(BLOCK_HEADING), env.stdout[0].slice(0, 300));
	assert.ok(env.stdout[0].endsWith("\n"));
	assert.equal(env.notices.length, 0, "print mode has no UI to notify");
});

test("/steward-models in the TUI stays an entry: no stdout, no notice, nothing sent", async () => {
	const env = load();
	env.ctx.mode = "tui";
	env.ctx.hasUI = true;
	await env.commands["steward-models"].handler("check", env.ctx);
	assert.equal(env.stdout.length, 0);
	assert.equal(env.notices.length, 0);
	assert.equal(env.sent.length, 0);
	assert.equal(env.shown().length, 1);
});

test("/steward-models in JSON mode leaves stdout to pi's JSONL: the entry is the output", async () => {
	const env = load();
	env.ctx.mode = "json";
	await env.commands["steward-models"].handler("check", env.ctx);
	assert.equal(env.stdout.length, 0);
	assert.equal(env.sent.length, 0);
	assert.equal(env.shown().length, 1);
});

test("/steward-models in RPC mode notifies the client as well as appending the entry", async () => {
	const env = load();
	env.ctx.mode = "rpc";
	env.ctx.hasUI = true;
	await env.commands["steward-models"].handler("stats", env.ctx);
	assert.equal(env.stdout.length, 0);
	assert.equal(env.sent.length, 0);
	assert.equal(env.shown().length, 1);
	assert.equal(env.notices.length, 1);
});

test("model_select and thinking_level_select return without waiting for a slow hook", async () => {
	// pi awaits model_select handlers inside setModel, so a handler that waited for the hook
	// would hold up the model switch for as long as the hook runs.
	const env = load();
	await sectionAfterStart(env);
	process.env.STEWARD_PYTHON = wrapPython("sleep 1");
	const at = { ...env.ctx, model: SOL, thinkingLevel: "high" };
	for (const [name, event] of [
		["model_select", { type: "model_select", model: SOL, previousModel: env.ctx.model, source: "set" }],
		["thinking_level_select", { type: "thinking_level_select", level: "high", previousLevel: "xhigh" }],
	]) {
		const started = Date.now();
		await env.fire(name, event, at);
		assert.ok(Date.now() - started < 500, `${name} handler took ${Date.now() - started} ms`);
	}
	assert.equal(mainLine(await sectionNow(env, at)), "Main thread: openai-codex/gpt-6.1-sol at high.");
});

// ---- Release review N9: a failed load is not retried on every prompt, and session start is
// bounded by one hook budget.

/** Times one before_agent_start; returns the section and the elapsed ms. */
async function timedSection(env, at) {
	const started = Date.now();
	const text = await sectionNow(env, at);
	return { text, ms: Date.now() - started };
}

test("the defaults: the facts call gets 5 s inside the 15 s hook budget", () => {
	assert.equal(FACTS_TIMEOUT_MS, 5_000);
	assert.equal(HOOK_TIMEOUT_MS, 15_000);
});

test("after a switch whose load hangs, later prompts start no load and do not wait; the next switch starts one", async () => {
	const env = load({ hookTimeoutMs: 1000, factsTimeoutMs: 200 });
	const before = await sectionAfterStart(env);
	assert.ok(before);
	// Every call from here hangs until killed (exec, so the kill reaches the sleep).
	process.env.STEWARD_PYTHON = wrapPython("exec sleep 30");
	const at = { ...env.ctx, model: SOL, thinkingLevel: "high" };
	await env.fire("model_select", { type: "model_select", model: SOL, previousModel: env.ctx.model, source: "set" }, at);
	// The first prompt shares the switch's load, which fails within the budget.
	const first = await timedSection(env, at);
	assert.equal(first.text, before, "the last good edict");
	assert.ok(first.ms < 1500, `first prompt took ${first.ms} ms`);
	const calls = sessionStartPayloads().length;
	for (let i = 0; i < 4; i++) {
		const later = await timedSection(env, at);
		assert.equal(later.text, before);
		assert.ok(later.ms < 150, `prompt ${i} took ${later.ms} ms`);
	}
	assert.equal(sessionStartPayloads().length, calls, "no prompt started a load");
	// The next switch starts exactly one load: one facts call, then the plain retry.
	await env.fire("thinking_level_select", { type: "thinking_level_select", level: "low", previousLevel: "high" }, at);
	assert.equal((await timedSection(env, at)).text, before);
	assert.deepEqual(sessionStartPayloads().slice(calls).map((p) => "model_facts" in p), [true, false]);
});

test("session start with a hanging facts call: the facts call is killed at the facts timeout and the plain retry lands within the budget", async () => {
	const reallyPlain = await plainEdict();
	process.env.STEWARD_PYTHON = wrapPython(`case "$input" in *'"model_facts"'*) exec sleep 30 ;; esac`);
	const env = load({ hookTimeoutMs: 1500, factsTimeoutMs: 300 });
	const started = Date.now();
	await env.fire("session_start", { type: "session_start", reason: "startup" });
	const total = Date.now() - started;
	assert.equal(await sectionNow(env), reallyPlain);
	const calls = hookLog().filter((e) => e.kind === "hook" && e.subcommand === "session-start").slice(1);
	assert.deepEqual(calls.map((e) => "model_facts" in e.payload), [true, false]);
	assert.equal(calls[0].timedOut, true);
	assert.ok(calls[0].ms < 800, `facts call ran ${calls[0].ms} ms`);
	assert.ok(total < 1500, `session start took ${total} ms`);
});

test("session start where both calls hang stays within the budget, then behaves as 0.10.0: no edict, the next prompt retries the plain call", async () => {
	const reallyPlain = await plainEdict();
	process.env.STEWARD_PYTHON = wrapPython("exec sleep 30");
	const env = load({ hookTimeoutMs: 1000, factsTimeoutMs: 200 });
	const started = Date.now();
	await env.fire("session_start", { type: "session_start", reason: "startup" });
	const total = Date.now() - started;
	assert.ok(total < 1300, `session start took ${total} ms`);
	assert.equal(await sectionNow(env), undefined);
	delete process.env.STEWARD_PYTHON;
	const calls = sessionStartPayloads().length;
	assert.equal(await sectionNow(env), reallyPlain);
	assert.deepEqual(sessionStartPayloads().slice(calls).map((p) => "model_facts" in p), [false]);
});
