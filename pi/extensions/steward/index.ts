/**
 * steward for pi: injects the delegation edict and runs the delegation gate, the prose gate and
 * the PR-body gate.
 *
 * Every decision is made by hooks/steward_hook.py, the same engine the Claude Code plugin runs.
 * This file only translates pi events into that script's JSON payloads (with STEWARD_HARNESS=pi)
 * and maps its answers back onto pi's event results. Like the Claude Code hooks, it fails open:
 * if python3 is missing or the script errors, the tool call or reply goes through.
 *
 * Delegation runs through the pi-subagents extension's `subagent` tool. Its foreground children
 * never load ambient extensions, and its background runner sets PI_SUBAGENT_CHILD=1, so this file
 * registers nothing in a child: the edict and its gates apply to the main thread only.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { spawn } from "node:child_process";
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

type HookOutput = Record<string, any> | undefined;

interface HookResult {
	output: HookOutput;
	/** Set when the python interpreter itself could not be started. */
	missingPython?: boolean;
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
			if (!text) return finish({ output: undefined });
			try {
				const parsed = JSON.parse(text);
				finish({ output: parsed && typeof parsed === "object" ? parsed : undefined });
			} catch {
				finish({ output: undefined });
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

export default function steward(pi: ExtensionAPI): void {
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

	async function loadEdict(ctx: ExtensionContext): Promise<string | undefined> {
		const { output, missingPython } = await runHook("session-start", { session_id: sessionId(ctx) });
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
}
