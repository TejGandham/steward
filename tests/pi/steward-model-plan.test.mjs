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

import steward, { createSteward, gatherModelFacts, runHook } from "../../pi/extensions/steward/index.ts";

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
	const { cwd, factory } = opts;
	const handlers = {};
	const commands = {};
	const sent = [];
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
		getAllTools: () => ["read", "bash", "edit", "write", "subagent"].map((name) => ({ name })),
		getActiveTools: () => ["read", "bash", "edit", "write", "subagent"],
	};
	const make = factory ?? createSteward({ loadPiAi: async () => {
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
	const fire = async (name, event) => {
		let result;
		for (const h of handlers[name] ?? []) result = await h(event, ctx);
		return result;
	};
	return { handlers, commands, sent, notices, ctx, fire };
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
		env.sent.length = 0;
		await env.commands["steward-models"].handler(args, env.ctx);
		assert.equal(env.sent.length, 1, `args ${JSON.stringify(args)}`);
		const { message } = env.sent[0];
		assert.equal(message.customType, "steward-models");
		assert.equal(message.display, true);
		assert.ok(message.content.includes(BLOCK_HEADING), message.content.slice(0, 500));
	}
	const calls = hookLog().filter((e) => e.kind === "hook" && e.subcommand === "model-plan");
	assert.equal(calls.length, 3);
	for (const call of calls) {
		assert.ok(isAbsolute(call.payload.cwd));
		assert.ok(call.payload.model_facts);
		assert.ok(isAbsolute(call.payload.model_facts.cwd));
		assert.match(call.stdout, /"report"/);
	}
});

test("/steward-models apply and stats reply that they arrive in a later phase", async () => {
	const env = load();
	for (const sub of ["apply", "stats"]) {
		env.sent.length = 0;
		await env.commands["steward-models"].handler(sub, env.ctx);
		assert.equal(env.sent.length, 1);
		assert.match(env.sent[0].message.content, new RegExp(`${sub}.*later phase`));
	}
	assert.equal(hookLog().filter((e) => e.subcommand === "model-plan").length, 0);
	env.sent.length = 0;
	await env.commands["steward-models"].handler("frobnicate", env.ctx);
	assert.match(env.sent[0].message.content, /Usage: \/steward-models \[check\|apply\|stats\]/);
});

test("/steward-models check: a failing hook gives a short error, never a crash", async () => {
	const fake = join(tmp, "fake-python");
	writeFileSync(fake, "#!/bin/sh\necho 'not json'\nexit 1\n");
	chmodSync(fake, 0o755);
	process.env.STEWARD_PYTHON = fake;
	const env = load();
	await env.commands["steward-models"].handler("check", env.ctx);
	assert.equal(env.sent.length, 1);
	assert.match(env.sent[0].message.content, /^steward: \/steward-models check failed/);
	assert.ok(env.sent[0].message.content.length < 300);

	process.env.STEWARD_PYTHON = join(tmp, "no-such-python");
	env.sent.length = 0;
	await env.commands["steward-models"].handler("check", env.ctx);
	assert.match(env.sent[0].message.content, /python3 was not found/);
});

test("/steward-models check: the hook's error message is shown", async () => {
	const fake = join(tmp, "fake-python");
	writeFileSync(fake, `#!/bin/sh\necho '{"error": "model-plan: cwd must be an absolute path, got a relative one"}'\nexit 2\n`);
	chmodSync(fake, 0o755);
	process.env.STEWARD_PYTHON = fake;
	const env = load();
	await env.commands["steward-models"].handler("check", env.ctx);
	assert.match(env.sent[0].message.content, /failed: model-plan: cwd must be an absolute path/);
});

test("/steward-models check without registry facts says so", async () => {
	const env = load({ registry: undefined });
	await env.commands["steward-models"].handler("check", env.ctx);
	assert.match(env.sent[0].message.content, /could not read pi's model registry/);
	assert.equal(hookLog().filter((e) => e.subcommand === "model-plan").length, 0);
});

test("the child guard registers no command and no handler", () => {
	process.env.PI_SUBAGENT_CHILD = "1";
	const env = load();
	assert.deepEqual(env.handlers, {});
	assert.deepEqual(env.commands, {});
});
