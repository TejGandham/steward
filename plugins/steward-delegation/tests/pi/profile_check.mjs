// Helper for ../test_pi_model_plan_apply.py. Drives the installed
// pi-subagents profile code against a temporary agent dir (the caller sets
// PI_CODING_AGENT_DIR; this file never reads the real one).
//
// usage: node profile_check.mjs <pi-subagents dir> <action> [profile name]
//   read   -> readSubagentProfile(name): pi-subagents' own profile validation
//   load   -> applySubagentProfile(name): what /subagents-load-profile writes
//   format -> stdin is a JSON file's text; prints whether it equals
//             JSON.stringify(JSON.parse(text), null, 2) (pi's settings style)
// stdout: one JSON object, {"ok": true, ...} or {"ok": false, "error": "..."}.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [dir, action, name = "steward"] = process.argv.slice(2);
const out = (value) => process.stdout.write(`${JSON.stringify(value)}\n`);

try {
	const version = JSON.parse(readFileSync(join(dir, "package.json"), "utf8")).version;
	if (action === "format") {
		const text = readFileSync(0, "utf8");
		const body = text.endsWith("\n") ? text.slice(0, -1) : text;
		out({ ok: true, version, same: JSON.stringify(JSON.parse(body), null, 2) === body });
	} else {
		const profiles = await import(pathToFileURL(join(dir, "src/profiles/profiles.js")).href);
		if (action === "read") {
			const { filePath, profile } = profiles.readSubagentProfile(name);
			out({ ok: true, version, filePath, profile });
		} else if (action === "load") {
			const result = profiles.applySubagentProfile(name);
			out({ ok: true, version, ...result });
		} else {
			out({ ok: false, error: `unknown action ${action}` });
		}
	}
} catch (err) {
	out({ ok: false, error: String(err?.message ?? err) });
}
