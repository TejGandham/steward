/**
 * steward for pi: injects the delegation edict and runs the delegation gate, the prose gate and
 * the PR-body gate.
 *
 * Every decision is made by hooks/steward_hook.py, the same engine the Claude Code plugin runs.
 * This file only translates pi events into that script's JSON payloads (with STEWARD_HARNESS=pi)
 * and maps its answers back onto pi's event results. Like the Claude Code hooks, it fails open:
 * if python3 is missing or the script errors, the tool call or reply goes through.
 *
 * For the model plan (docs/roadmap/pi-model-plan.md) it also reads pi's model registry and sends
 * those facts with the session-start payload, rebuilds the edict when the main model changes, and
 * adds the /steward-models command, which runs the hook's `model-plan` subcommand.
 *
 * Debugging: with STEWARD_HOOK_LOG=<file>, every hook call appends one JSON line to that file
 * ({kind: "hook", subcommand, payload, stdout, ms}), and each facts gathering one line
 * ({kind: "facts", ms, models, bytes}). Unset, nothing is written.
 *
 * Delegation runs through the pi-subagents extension's `subagent` tool. Its foreground children
 * never load ambient extensions, and its background runner sets PI_SUBAGENT_CHILD=1, so this file
 * registers nothing in a child: the edict and its gates apply to the main thread only.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { spawn } from "node:child_process";
import { appendFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const PLUGIN_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const HOOK_SCRIPT = resolve(PLUGIN_ROOT, "hooks", "steward_hook.py");
const HOOK_TIMEOUT_MS = 15_000;

/** pi's built-in tools that write: the same set the Claude Code gate watches. */
const GATED_TOOLS = new Set(["bash", "edit", "write"]);
/** The delegation tool registered by pi-subagents, and its loader. */
const SUBAGENT_TOOL = "subagent";
const SUBAGENT_LOADER_TOOL = "subagents_enable";
/** System prompt section name; pi renders it as <steward>...</steward>. */
const SECTION = "steward";
const PROSE_GATE_MESSAGE_TYPE = "steward-prose-gate";
const EDICT_MESSAGE_TYPE = "steward-edict";
const DELEGATION_GATE_PREFIX = "steward delegation gate";
const MODELS_COMMAND = "steward-models";
const MODELS_MESSAGE_TYPE = "steward-models";
const MODELS_PLAN_SUBCOMMAND = "model-plan";
const MODELS_USAGE = "Usage: /steward-models [check|apply|stats]";

type HookOutput = Record<string, any> | undefined;

interface HookResult {
	output: HookOutput;
	/** Set when the python interpreter itself could not be started. */
	missingPython?: boolean;
}

/** Appends one JSON line to $STEWARD_HOOK_LOG when it is set. Never throws. */
function debugLog(entry: Record<string, unknown>): void {
	const path = process.env.STEWARD_HOOK_LOG;
	if (!path) return;
	try {
		appendFileSync(path, `${JSON.stringify({ time: new Date().toISOString(), pid: process.pid, ...entry })}\n`);
	} catch {
		// debugging only
	}
}

export function runHook(subcommand: string, payload: Record<string, unknown>): Promise<HookResult> {
	return new Promise((done) => {
		let settled = false;
		const finish = (result: HookResult) => {
			if (!settled) {
				settled = true;
				done(result);
			}
		};
		const started = Date.now();
		const logged = (result: HookResult, stdout: string) => {
			debugLog({ kind: "hook", subcommand, payload, stdout, ms: Date.now() - started });
			finish(result);
		};
		let child;
		try {
			child = spawn(process.env.STEWARD_PYTHON || "python3", [HOOK_SCRIPT, subcommand], {
				env: { ...process.env, STEWARD_HARNESS: "pi", STEWARD_PLUGIN_ROOT: PLUGIN_ROOT },
				stdio: ["pipe", "pipe", "ignore"],
			});
		} catch {
			finish({ output: undefined, missingPython: true });
			return;
		}
		const chunks: Buffer[] = [];
		const timer = setTimeout(() => {
			child.kill("SIGKILL");
			finish({ output: undefined });
		}, HOOK_TIMEOUT_MS);
		child.stdout.on("data", (chunk: Buffer) => {
			chunks.push(chunk);
		});
		child.on("error", (err: NodeJS.ErrnoException) => {
			clearTimeout(timer);
			finish({ output: undefined, missingPython: err.code === "ENOENT" });
		});
		child.on("close", () => {
			clearTimeout(timer);
			const text = Buffer.concat(chunks).toString("utf8").trim();
			if (!text) return logged({ output: undefined }, text);
			try {
				const parsed = JSON.parse(text);
				logged({ output: parsed && typeof parsed === "object" ? parsed : undefined }, text);
			} catch {
				logged({ output: undefined }, text);
			}
		});
		child.stdin.on("error", () => {});
		child.stdin.end(JSON.stringify(payload));
	});
}

/**
 * True when a `subagent` call starts work, so it counts as a delegation: a direct child
 * (`agent`), a workflow, or `action: "resume"` of a retained child. Other management calls
 * (`action: "list"`, `"status"`, `"guide"`, ...) and the `subagents_enable` loader do not.
 */
export function launchesWork(input: unknown): boolean {
	if (!input || typeof input !== "object") return false;
	const args = input as Record<string, unknown>;
	if (args.action === "resume") return true;
	if (args.action !== undefined) return false;
	return Boolean(args.agent) || Boolean(args.workflow);
}

/** Text of the most recent assistant message, or undefined when it has none. */
export function lastAssistantText(messages: readonly unknown[]): string | undefined {
	for (let i = messages.length - 1; i >= 0; i--) {
		const message = messages[i] as { role?: string; content?: unknown };
		if (message?.role !== "assistant") continue;
		const { content } = message;
		if (typeof content === "string") return content.trim() ? content : undefined;
		if (!Array.isArray(content)) return undefined;
		const text = content
			.filter((part) => part && part.type === "text" && typeof part.text === "string")
			.map((part) => part.text as string)
			.join("");
		return text.trim() ? text : undefined;
	}
	return undefined;
}

/**
 * True when the latest reply answers a prose-gate message, so it is already the one revision the
 * gate allows. Walks back from the end: the gate's own message means yes; a user message or any
 * other custom message (a new prompt, a background-completion notice) means no.
 */
export function isProseRevision(messages: readonly unknown[]): boolean {
	for (let i = messages.length - 1; i >= 0; i--) {
		const message = messages[i] as { role?: string; customType?: string };
		if (message?.role === "user") return false;
		if (message?.role === "custom") return message.customType === PROSE_GATE_MESSAGE_TYPE;
	}
	return false;
}

/** What the extension needs from `@earendil-works/pi-ai`. */
export interface PiAi {
	getSupportedThinkingLevels?: (model: any) => unknown;
}

/** pi's extension loader aliases pi packages, so this import works without node_modules. */
const defaultLoadPiAi = () => import("@earendil-works/pi-ai") as Promise<PiAi>;

function nonEmpty(value: unknown): value is string {
	return typeof value === "string" && value.length > 0;
}

/**
 * The registry facts hooks/model_plan.py reads (its docstring is the contract): main model and
 * thinking level, every catalog model with whether its provider has configured auth, supported
 * thinking levels and max output tokens, project trust and the absolute cwd. Returns undefined
 * when anything is missing or throws, so the caller sends no facts and the hook falls back to the
 * plain edict.
 */
export function gatherModelFacts(ctx: ExtensionContext, piAi: PiAi | undefined): Record<string, unknown> | undefined {
	try {
		const levelsOf = piAi?.getSupportedThinkingLevels;
		if (typeof levelsOf !== "function") return undefined;
		const registry = ctx.modelRegistry;
		if (!registry || typeof registry.getAll !== "function" || typeof registry.hasConfiguredAuth !== "function") {
			return undefined;
		}
		const all = registry.getAll();
		if (!Array.isArray(all)) return undefined;
		const auth = new Map<string, boolean>();
		const models: Record<string, unknown>[] = [];
		for (const model of all) {
			if (!model || !nonEmpty(model.provider) || !nonEmpty(model.id)) continue;
			let available = auth.get(model.provider);
			if (available === undefined) {
				available = registry.hasConfiguredAuth(model) === true;
				auth.set(model.provider, available);
			}
			const entry: Record<string, unknown> = { provider: model.provider, id: model.id, available };
			const levels = levelsOf(model);
			if (Array.isArray(levels) && levels.every((level) => typeof level === "string")) entry.thinkingLevels = [...levels];
			if (Number.isInteger(model.maxTokens) && model.maxTokens > 0) entry.maxTokens = model.maxTokens;
			models.push(entry);
		}
		if (models.length === 0) return undefined;
		let main: Record<string, string> | null = null;
		const current = ctx.model;
		if (current) {
			const thinkingLevel = ctx.thinkingLevel;
			if (!nonEmpty(current.provider) || !nonEmpty(current.id) || !nonEmpty(thinkingLevel)) return undefined;
			main = { provider: current.provider, id: current.id, thinkingLevel };
		}
		const projectTrusted = ctx.isProjectTrusted();
		if (typeof projectTrusted !== "boolean") return undefined;
		if (!nonEmpty(ctx.cwd)) return undefined;
		return { main, models, projectTrusted, cwd: resolve(ctx.cwd) };
	} catch {
		return undefined;
	}
}

function sessionId(ctx: ExtensionContext): string {
	try {
		const id = ctx.sessionManager.getSessionId();
		if (id) return `pi-${id}`;
	} catch {
		// fall through
	}
	// Per process, so two sessions without an id never share one edit counter.
	return `pi-pid-${process.pid}`;
}

const MISSING_SUBAGENTS_WARNING =
	"STEWARD WARNING: the pi-subagents extension is not loaded, so there is no subagent tool and " +
	"the edict cannot be followed. Install it with `pi install npm:pi-subagents`. Until then " +
	"the delegation gate only reminds instead of blocking. Tell the operator before starting " +
	"non-trivial work.";

const SUBAGENT_NOT_ACTIVE_WARNING =
	"STEWARD WARNING: the pi-subagents extension is installed, but the subagent tool is not available " +
	"in this session, so the delegation gate only reminds instead of blocking. Tell the operator: " +
	'setting `"toolActivation": "eager"` in ~/.pi/agent/extensions/subagent/config.json and running ' +
	"/reload, or starting a new session, makes it available. Restarting pi and resuming this " +
	"conversation does not, because pi restores the conversation's recorded tools on resume.";

export interface StewardOptions {
	/** Loads `@earendil-works/pi-ai`; tests pass a stand-in. */
	loadPiAi?: () => Promise<PiAi>;
}

export function createSteward(options: StewardOptions = {}): (pi: ExtensionAPI) => void {
	return (pi) => register(pi, options.loadPiAi ?? defaultLoadPiAi);
}

const steward = createSteward();
export default steward;

function register(pi: ExtensionAPI, loadPiAi: () => Promise<PiAi>): void {
	if (process.env.PI_SUBAGENT_CHILD === "1") return;

	let edict: string | undefined;
	let warnedMissingPython = false;
	/** True while the current run's system prompt carries the edict (set by before_agent_start). */
	let edictInPrompt = false;
	const softNotes = new Map<string, string>();

	function hasDelegationTool(names: readonly string[]): boolean {
		return names.includes(SUBAGENT_TOOL) || names.includes(SUBAGENT_LOADER_TOOL);
	}

	/** pi-subagents is registered. On error, assume it is, so no false warning is shown. */
	function subagentsInstalled(): boolean {
		try {
			return hasDelegationTool(pi.getAllTools().map((tool) => tool.name));
		} catch {
			return true;
		}
	}

	/**
	 * The model can call a delegation tool right now. pi-subagents can leave `subagent` registered
	 * but inactive (a resumed conversation recorded before it was installed), so check the active
	 * tools. On error, return false: the gate then reminds instead of blocking.
	 */
	function canDelegateNow(): boolean {
		try {
			const getActiveTools = (pi as Partial<ExtensionAPI>).getActiveTools;
			if (typeof getActiveTools !== "function") return subagentsInstalled();
			return hasDelegationTool(getActiveTools.call(pi));
		} catch {
			return false;
		}
	}

	/** Why the model cannot delegate in this session. */
	function cannotDelegateNote(): string {
		return subagentsInstalled() ? SUBAGENT_NOT_ACTIVE_WARNING : MISSING_SUBAGENTS_WARNING;
	}

	let piAi: Promise<PiAi | undefined> | undefined;
	function piAiModule(): Promise<PiAi | undefined> {
		piAi ??= loadPiAi().catch(() => undefined);
		return piAi;
	}

	/** Registry facts for the hook, or undefined (the hook then gives the plain edict). */
	async function modelFacts(ctx: ExtensionContext): Promise<Record<string, unknown> | undefined> {
		try {
			const started = Date.now();
			const facts = gatherModelFacts(ctx, await piAiModule());
			if (facts && process.env.STEWARD_HOOK_LOG) {
				debugLog({
					kind: "facts",
					ms: Date.now() - started,
					models: (facts.models as unknown[]).length,
					bytes: Buffer.byteLength(JSON.stringify(facts)),
				});
			}
			return facts;
		} catch {
			return undefined;
		}
	}

	async function loadEdict(ctx: ExtensionContext): Promise<string | undefined> {
		const payload: Record<string, unknown> = { session_id: sessionId(ctx) };
		const facts = await modelFacts(ctx);
		if (facts) payload.model_facts = facts;
		const { output, missingPython } = await runHook("session-start", payload);
		if (missingPython && ctx.hasUI && !warnedMissingPython) {
			warnedMissingPython = true;
			ctx.ui.notify("steward: python3 was not found, so the edict and its gates are off.", "warning");
		}
		const text = output?.hookSpecificOutput?.additionalContext;
		// undefined, not "", so the next prompt tries again
		if (typeof text !== "string" || !text) return undefined;
		return subagentsInstalled() ? text : `${MISSING_SUBAGENTS_WARNING}\n\n${text}`;
	}

	pi.on("session_start", async (_event, ctx) => {
		try {
			softNotes.clear();
			edictInPrompt = false;
			edict = await loadEdict(ctx);
		} catch {
			edict = undefined;
		}
	});

	// The main model changed (set, cycle or restore): rebuild so the next run's system prompt
	// carries a block for the new model. pi sets the model and its thinking level before it emits
	// this event, so ctx reads the new values.
	pi.on("model_select", async (_event, ctx) => {
		try {
			edict = undefined;
			edict = await loadEdict(ctx);
		} catch {
			edict = undefined;
		}
	});

	pi.on("before_agent_start", async (event, ctx) => {
		try {
			if (edict === undefined) edict = await loadEdict(ctx);
			if (!edict) return undefined;
			edictInPrompt = true;
			const options = event.systemPromptOptions;
			// An earlier handler replaced the whole prompt, so a section would be ignored: append to
			// the replacement instead. A later handler that replaces the prompt starts from
			// event.systemPrompt, which already renders this section.
			if (options.forceSystemPrompt != null) {
				if (options.forceSystemPrompt.includes(`<${SECTION}>`)) return undefined;
				return { systemPrompt: `${event.systemPrompt}\n\n<${SECTION}>\n${edict}\n</${SECTION}>` };
			}
			options.sections[SECTION] = edict;
		} catch {
			// fail open
		}
		return undefined;
	});

	// A run that pi starts without a user prompt (for example a pi-subagents background-completion
	// notice) skips before_agent_start and uses the base system prompt, which has no edict. For
	// those runs, add the edict to the end of each request's messages. Request-local: nothing is
	// stored in the session.
	pi.on("context", async (event) => {
		try {
			if (edictInPrompt || !edict) return undefined;
			const reminder = {
				role: "custom" as const,
				customType: EDICT_MESSAGE_TYPE,
				content:
					`<${SECTION}>\nThis turn started without a user prompt, so the steward edict is ` +
					`repeated here. It is standing instructions, not a new request.\n\n${edict}\n</${SECTION}>`,
				display: false,
				timestamp: Date.now(),
			};
			return { messages: [...event.messages, reminder] };
		} catch {
			return undefined;
		}
	});

	pi.on("tool_call", async (event, ctx) => {
		try {
			if (!GATED_TOOLS.has(event.toolName)) return undefined;
			const { output } = await runHook("gate", {
				session_id: sessionId(ctx),
				tool_name: event.toolName,
				tool_input: event.input,
				cwd: ctx.cwd,
			});
			const decision = output?.hookSpecificOutput;
			if (decision?.permissionDecision === "deny") {
				const reason = String(decision.permissionDecisionReason ?? "steward gate");
				// Without a delegation tool the model cannot delegate, so a delegation-gate denial
				// could never be cleared. Downgrade it to a reminder. The PR gate still blocks.
				if (reason.startsWith(DELEGATION_GATE_PREFIX) && !canDelegateNow()) {
					softNotes.set(event.toolCallId, `${reason}\n\n${cannotDelegateNote()}`);
					return undefined;
				}
				return { block: true, reason };
			}
			if (typeof decision?.additionalContext === "string") {
				// Soft mode: let the call run and attach the reminder to its result.
				const note = canDelegateNow()
					? decision.additionalContext
					: `${decision.additionalContext}\n\n${cannotDelegateNote()}`;
				softNotes.set(event.toolCallId, note);
			}
		} catch {
			// fail open: pi blocks a tool when its handler throws
		}
		return undefined;
	});

	pi.on("tool_result", async (event, ctx) => {
		try {
			if (event.toolName === SUBAGENT_TOOL) {
				// Only a launch that pi-subagents accepted counts as a delegation.
				if (!event.isError && launchesWork(event.input)) {
					await runHook("delegated", { session_id: sessionId(ctx) });
				}
				return undefined;
			}
			const note = softNotes.get(event.toolCallId);
			if (note === undefined || !Array.isArray(event.content)) return undefined;
			softNotes.delete(event.toolCallId);
			return {
				content: [...event.content, { type: "text" as const, text: note }],
				structuredContent: event.structuredContent,
			};
		} catch {
			return undefined;
		}
	});

	pi.on("agent_before_settle", async (event, ctx) => {
		try {
			// No canContinue check: it describes the context before this handler's entries, and a
			// finished reply always ends on the assistant turn. The custom message added below is what
			// makes the next request runnable.
			if (event.outcome !== "completed") return undefined;
			const messages = event.context.contextMessages;
			const text = lastAssistantText(messages);
			if (!text) return undefined;
			const { output } = await runHook("prose-gate", {
				session_id: sessionId(ctx),
				last_assistant_message: text,
				// One revision per reply, like Claude Code's stop_hook_active.
				stop_hook_active: isProseRevision(messages),
			});
			if (output?.decision !== "block" || typeof output.reason !== "string") return undefined;
			return {
				entries: [
					...event.entries,
					{ type: "custom_message" as const, customType: PROSE_GATE_MESSAGE_TYPE, content: output.reason, display: true },
				],
				continue: true,
			};
		} catch {
			return undefined;
		}
	});

	pi.on("agent_settled", async () => {
		edictInPrompt = false;
		// Notes for calls that never produced a result (blocked by another extension, aborted).
		softNotes.clear();
	});

	function show(text: string): void {
		pi.sendMessage({ customType: MODELS_MESSAGE_TYPE, content: text, display: true });
	}

	async function checkReport(ctx: ExtensionContext): Promise<string> {
		const facts = await modelFacts(ctx);
		if (!facts) return "steward: /steward-models check could not read pi's model registry, so no check ran.";
		const { output, missingPython } = await runHook(MODELS_PLAN_SUBCOMMAND, { model_facts: facts, cwd: facts.cwd });
		if (missingPython) return "steward: /steward-models check failed: python3 was not found.";
		if (typeof output?.report === "string" && output.report) return output.report;
		const reason = typeof output?.error === "string" && output.error ? output.error.slice(0, 200) : "the hook gave no report";
		return `steward: /steward-models check failed: ${reason}`;
	}

	// A host without commands (or a registration error) leaves the edict and gates as they are.
	try {
		registerModelsCommand();
	} catch {
		// no command
	}

	function registerModelsCommand(): void {
		if (typeof pi.registerCommand !== "function") return;
		pi.registerCommand(MODELS_COMMAND, {
			description: "Check the steward model plan: what each steward profile runs on, and every warning",
			getArgumentCompletions: (prefix: string) =>
				["check", "apply", "stats"].filter((sub) => sub.startsWith(prefix.trim())).map((sub) => ({ value: sub, label: sub })),
			handler: async (args, ctx) => {
				try {
					const sub = (args ?? "").trim() || "check";
					if (sub === "check") show(await checkReport(ctx));
					else if (sub === "apply" || sub === "stats") {
						show(`steward: /steward-models ${sub} arrives in a later phase (${sub === "apply" ? "Phase 3" : "Phase 4"}); only check works now.`);
					} else show(MODELS_USAGE);
				} catch {
					try {
						show("steward: /steward-models failed with an internal error.");
					} catch {
						// never crash the command
					}
				}
			},
		});
	}
}
