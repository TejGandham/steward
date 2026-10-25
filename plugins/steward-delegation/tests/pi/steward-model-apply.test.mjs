// Tests for `/steward-models apply` in the pi extension (Phase 3 of
// docs/roadmap/pi-model-plan.md). The extension only asks, calls the hook's
// `model-plan-apply` subcommand and reloads; the hook runs for real against a
// temporary PI_CODING_AGENT_DIR, never the real ~/.pi/agent.
import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdtempSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { createSteward } from "../../pi/extensions/steward-delegation/index.ts";

const ENV_KEYS = ["HOME", "XDG_STATE_HOME", "PI_CODING_AGENT_DIR", "STEWARD_DELEGATION_GATE", "STEWARD_DELEGATION_PYTHON", "PI_SUBAGENT_CHILD", "STEWARD_DELEGATION_HOOK_LOG"];
const ALL_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];
const SONNET = "anthropic/claude-sonnet-5-5";

let tmp;
let savedEnv;
let counter = 0;

beforeEach(() => {
	savedEnv = Object.fromEntries(ENV_KEYS.map((k) => [k, process.env[k]]));
	tmp = mkdtempSync(join(tmpdir(), "steward-pi-apply-test-"));
	for (const dir of ["home", "state", "config", "project"]) mkdirSync(join(tmp, dir));
	process.env.HOME = join(tmp, "home");
	process.env.XDG_STATE_HOME = join(tmp, "state");
	process.env.PI_CODING_AGENT_DIR = join(tmp, "config");
	for (const k of ["STEWARD_DELEGATION_GATE", "STEWARD_DELEGATION_PYTHON", "PI_SUBAGENT_CHILD", "STEWARD_DELEGATION_HOOK_LOG"]) delete process.env[k];
});

afterEach(() => {
	for (const [k, v] of Object.entries(savedEnv)) {
		if (v === undefined) delete process.env[k];
		else process.env[k] = v;
	}
	rmSync(tmp, { recursive: true, force: true });
});

function m(full) {
	const i = full.indexOf("/");
	return { provider: full.slice(0, i), id: full.slice(i + 1), levels: ALL_LEVELS, maxTokens: 128000, reasoning: true };
}

const MODELS = [m("anthropic/claude-opus-5-5"), m(SONNET), m("anthropic/claude-haiku-5-5"), m("amorphic/claude-opus-5-5")];
const registry = {
	getAll: () => [...MODELS],
	getAvailable: () => [...MODELS],
	find: (p, id) => MODELS.find((x) => x.provider === p && x.id === id),
	hasConfiguredAuth: () => true,
};
const fakePiAi = { getSupportedThinkingLevels: (model) => [...model.levels] };

const config = (...parts) => join(tmp, "config", ...parts);
const settingsPath = () => config("settings.json");
const SETTINGS_TEXT = JSON.stringify({ theme: "dark", subagents: { agentOverrides: { worker: { model: "x/y" } } } }, null, 2);

function writePlan(plan = { version: 1, roles: { coder: { model: SONNET, thinking: "high" } } }) {
	mkdirSync(config("steward-delegation"), { recursive: true });
	writeFileSync(config("steward-delegation", "model-plan.json"), JSON.stringify(plan));
	writeFileSync(settingsPath(), SETTINGS_TEXT);
}

const backups = () => readdirSync(config()).filter((name) => name.startsWith("settings.json.bak-"));

/** One extension instance with a fake pi and ctx; `confirm` is what the UI answers. */
function load({ hasUI = false, confirm = true, reload } = {}) {
	const handlers = {};
	const commands = {};
	const entries = [];
	const notices = [];
	const asked = [];
	const pi = {
		on(name, handler) {
			(handlers[name] ??= []).push(handler);
		},
		registerCommand(name, options) {
			commands[name] = options;
		},
		sendMessage() {},
		appendEntry(customType, data) {
			entries.push({ customType, data });
		},
		registerEntryRenderer() {},
		getAllTools: () => ["read", "bash", "edit", "write", "subagent"].map((name) => ({ name })),
		getActiveTools: () => ["read", "bash", "edit", "write", "subagent"],
	};
	createSteward({ loadPiAi: async () => fakePiAi })(pi);
	const id = `a${++counter}`;
	const env = { handlers, commands, entries, notices, asked, reloads: 0 };
	env.ctx = {
		cwd: join(tmp, "project"),
		hasUI,
		ui: {
			notify: (msg, level) => notices.push({ msg, level }),
			confirm: async (title, message) => {
				asked.push({ title, message });
				return confirm;
			},
		},
		sessionManager: { getSessionId: () => id },
		modelRegistry: registry,
		model: MODELS[3],
		thinkingLevel: "xhigh",
		isProjectTrusted: () => true,
		reload: async () => {
			env.reloads++;
			if (reload) await reload();
		},
	};
	env.fire = async (name, event) => {
		for (const h of handlers[name] ?? []) await h(event, env.ctx);
	};
	env.shown = () => entries.filter((e) => e.customType === "steward-models").map((e) => e.data.text);
	env.run = (args) => commands["steward-models"].handler(args, env.ctx);
	return env;
}

/** reload() as pi does it: the old instance is replaced and the new one gets session_start "reload". */
function reloadInto(holder) {
	return async () => {
		holder.next = load({ hasUI: holder.hasUI });
		await holder.next.fire("session_start", { type: "session_start", reason: "reload" });
	};
}

test("apply with a UI shows the changes, asks, writes, reloads and shows the fresh check", async () => {
	writePlan();
	const holder = { hasUI: true };
	const env = load({ hasUI: true, confirm: true, reload: reloadInto(holder) });
	await env.run("apply");
	assert.equal(env.asked.length, 1, "asked once");
	const question = env.asked[0].message;
	assert.match(question, /steward\.coder model: \(unset\) -> "anthropic\/claude-sonnet-5-5"/);
	assert.ok(question.includes(settingsPath()), "names the settings file");
	assert.ok(question.includes(config("profiles", "pi-subagents", "steward.json")), "names the profile file");
	const written = JSON.parse(readFileSync(settingsPath(), "utf8"));
	assert.deepEqual(written.subagents.agentOverrides["steward.coder"], { model: SONNET, thinking: "high" });
	assert.deepEqual(written.subagents.agentOverrides.worker, { model: "x/y" });
	assert.equal(written.theme, "dark");
	assert.equal(backups().length, 1);
	assert.ok(existsSync(config("profiles", "pi-subagents", "steward.json")));
	assert.equal(env.reloads, 1, "ctx.reload() called");
	assert.match(env.shown().at(-1), /apply: written/);
	// The reloaded instance shows the fresh check, once.
	const after = holder.next.shown();
	assert.equal(after.length, 1);
	assert.match(after[0], /Model plan on this machine/);
	assert.match(after[0], /steward\.coder/);
	await holder.next.fire("session_start", { type: "session_start", reason: "reload" });
	assert.equal(holder.next.shown().length, 1, "a later reload shows nothing");
});

test("apply with a UI: declining writes nothing and does not reload", async () => {
	writePlan();
	const env = load({ hasUI: true, confirm: false });
	await env.run("apply");
	assert.equal(env.asked.length, 1);
	assert.equal(readFileSync(settingsPath(), "utf8"), SETTINGS_TEXT);
	assert.equal(backups().length, 0);
	assert.equal(env.reloads, 0);
	assert.match(env.shown().at(-1), /cancelled; nothing was written/);
});

test("apply without a UI needs --yes: the plain command only previews", async () => {
	writePlan();
	const env = load();
	await env.run("apply");
	assert.equal(env.asked.length, 0);
	assert.equal(readFileSync(settingsPath(), "utf8"), SETTINGS_TEXT);
	assert.equal(env.reloads, 0);
	const text = env.shown().at(-1);
	assert.match(text, /preview/);
	assert.match(text, /\/steward-models apply --yes/);
	assert.ok(env.notices.some((n) => n.msg === text), "no UI: notified too");
});

test("apply --yes without a UI writes, reloads and shows the result", async () => {
	writePlan();
	const holder = { hasUI: false };
	const env = load({ reload: reloadInto(holder) });
	await env.run("apply --yes");
	assert.equal(env.asked.length, 0);
	assert.deepEqual(JSON.parse(readFileSync(settingsPath(), "utf8")).subagents.agentOverrides["steward.coder"], { model: SONNET, thinking: "high" });
	assert.equal(env.reloads, 1);
	assert.match(env.shown().at(-1), /apply: written/);
	assert.match(holder.next.shown()[0], /Model plan on this machine/);
	assert.ok(holder.next.notices.length >= 1, "the fresh check is notified without a UI");
});

test("apply with nothing to change neither asks nor reloads", async () => {
	writePlan();
	const env = load({ hasUI: true });
	await env.run("apply --yes");
	assert.equal(env.reloads, 1);
	const again = load({ hasUI: true });
	await again.run("apply");
	assert.equal(again.asked.length, 0);
	assert.equal(again.reloads, 0);
	assert.match(again.shown().at(-1), /nothing to change/i);
	assert.equal(backups().length, 1);
});

test("a failing subcommand writes nothing and shows an error", async () => {
	writePlan();
	const cases = [
		["#!/bin/sh\necho 'not json'\nexit 1\n", /apply failed: the hook gave no result/],
		[`#!/bin/sh\necho '{"error": "model-plan-apply: boom", "refused": true}'\nexit 3\n`, /apply failed: model-plan-apply: boom/],
	];
	for (const [script, pattern] of cases) {
		const fake = join(tmp, `fake-python-${++counter}`);
		writeFileSync(fake, script);
		chmodSync(fake, 0o755);
		process.env.STEWARD_DELEGATION_PYTHON = fake;
		const env = load({ hasUI: true });
		await env.run("apply --yes");
		assert.match(env.shown().at(-1), pattern);
		assert.ok(env.shown().at(-1).length < 400);
		assert.equal(env.reloads, 0);
		assert.equal(readFileSync(settingsPath(), "utf8"), SETTINGS_TEXT);
	}
	process.env.STEWARD_DELEGATION_PYTHON = join(tmp, "no-such-python");
	const env = load();
	await env.run("apply --yes");
	assert.match(env.shown().at(-1), /python3 was not found/);
	assert.equal(env.reloads, 0);
});

test("a refusal (schema error in the plan) writes nothing and shows why", async () => {
	writePlan({ version: 1, roles: { coder: { model: "claude-sonnet-5-5" } } });
	const env = load({ hasUI: true });
	await env.run("apply --yes");
	assert.match(env.shown().at(-1), /apply failed: .*schema error/);
	assert.equal(env.asked.length, 0);
	assert.equal(env.reloads, 0);
	assert.equal(readFileSync(settingsPath(), "utf8"), SETTINGS_TEXT);
});

test("settings changed after the preview: the write is refused", async () => {
	writePlan();
	const edited = SETTINGS_TEXT.replace("dark", "light");
	const env = load({ hasUI: true });
	env.ctx.ui.confirm = async () => {
		writeFileSync(settingsPath(), edited);
		return true;
	};
	await env.run("apply");
	assert.match(env.shown().at(-1), /apply failed: .*changed since the preview/);
	assert.equal(readFileSync(settingsPath(), "utf8"), edited);
	assert.equal(env.reloads, 0);
	assert.equal(backups().length, 0);
});

test("the preview works but the writing call fails: nothing written, error shown, no reload", async () => {
	writePlan();
	const fake = join(tmp, "half-python");
	writeFileSync(fake, `#!/bin/sh\ninput=$(cat)\ncase "$input" in *'"dryRun":false'*) echo '{"error": "model-plan-apply: disk full", "refused": true}'; exit 3 ;; esac\nprintf '%s' "$input" | exec python3 "$@"\n`);
	chmodSync(fake, 0o755);
	process.env.STEWARD_DELEGATION_PYTHON = fake;
	const env = load({ hasUI: true, confirm: true });
	await env.run("apply");
	assert.equal(env.asked.length, 1, "the preview ran and was confirmed");
	assert.match(env.shown().at(-1), /apply failed: model-plan-apply: disk full/);
	assert.equal(env.reloads, 0);
	assert.equal(readFileSync(settingsPath(), "utf8"), SETTINGS_TEXT);
	assert.equal(backups().length, 0);
});
