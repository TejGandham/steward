// Drift-guard helper for tests/test_pi_model_plan_resolver.py. Runs a corpus
// through the installed pi-subagents and prints the results as JSON.
//
// usage: node resolve_model.mjs <pi-subagents dir>   (corpus on stdin)
// stdin:  {"resolve": [{model, avail: [[provider, id], ...], preferred}],
//          "normalize": [string], "package": [string], "frontmatter": [string]}
// stdout: {"version", "resolve": [string|null], "normalize": [string],
//          "package": [{packageName}|{error: true}], "frontmatter": [object]}
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const dir = process.argv[2];
const load = (rel) => import(pathToFileURL(join(dir, rel)).href);
const { resolveEffectiveSubagentModel, normalizeModelSegment } = await load("src/runs/shared/model-resolution.js");
const { parsePackageName } = await load("src/agents/identity.js");
const { parseFrontmatter } = await load("src/agents/frontmatter.js");
const version = JSON.parse(readFileSync(join(dir, "package.json"), "utf8")).version;

let input = "";
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  const corpus = JSON.parse(input);
  const parent = { provider: "amorphic", id: "claude-opus-5-5" };
  const resolve = (corpus.resolve ?? []).map((c) => {
    const avail = c.avail.map(([provider, id]) => ({ provider, id, fullId: `${provider}/${id}` }));
    try {
      return resolveEffectiveSubagentModel(undefined, c.model, parent, avail, c.preferred ?? undefined, {}) ?? null;
    } catch (error) {
      return `THROW:${error.message}`;
    }
  });
  const normalize = (corpus.normalize ?? []).map((s) => normalizeModelSegment(s));
  const pkg = (corpus.package ?? []).map((s) => {
    const parsed = parsePackageName(s);
    return parsed.error ? { error: true } : { packageName: parsed.packageName ?? null };
  });
  const frontmatter = (corpus.frontmatter ?? []).map((s) => parseFrontmatter(s).frontmatter);
  process.stdout.write(JSON.stringify({ version, resolve, normalize, package: pkg, frontmatter }));
});
