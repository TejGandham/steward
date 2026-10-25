// Drift-guard helper for ../test_pi_model_plan_resolver.py. Runs a corpus
// through the installed pi-subagents and prints the results as JSON.
//
// usage: node resolve_model.mjs <pi-subagents dir> <sha256 of stdin>   (corpus on stdin)
// stdin:  {"avails": [[[provider, id], ...]], "resolve": [[model, avail index, preferred]],
//          "normalize": [string], "package": [string], "frontmatter": [string]}
// stdout: "<sha256 of body>\n<body>", body is
//         {"version", "resolve": [string|null], "normalize": [string],
//          "package": [{packageName}|{error: true}], "frontmatter": [object]}
// exit 3: the stdin sha256 differs from the argument ("input corrupted in transit").
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const INPUT_CORRUPTED = 3;
const sha256 = (text) => createHash("sha256").update(text, "utf8").digest("hex");

const dir = process.argv[2];
const expected = process.argv[3];
// Synchronous read: the async stdin stream truncated input or crashed under Node 24.
const raw = readFileSync(0, "utf8");
if (sha256(raw) !== expected) {
  process.stderr.write(`input corrupted in transit: stdin sha256 ${sha256(raw)}, expected ${expected}\n`);
  process.exit(INPUT_CORRUPTED);
}

const load = (rel) => import(pathToFileURL(join(dir, rel)).href);
const { resolveEffectiveSubagentModel, normalizeModelSegment } = await load("src/runs/shared/model-resolution.js");
const { parsePackageName } = await load("src/agents/identity.js");
const { parseFrontmatter } = await load("src/agents/frontmatter.js");
const version = JSON.parse(readFileSync(join(dir, "package.json"), "utf8")).version;

{
  const corpus = JSON.parse(raw);
  const parent = { provider: "amorphic", id: "claude-opus-5-5" };
  const avails = (corpus.avails ?? []).map((list) =>
    list.map(([provider, id]) => ({ provider, id, fullId: `${provider}/${id}` })));
  const resolve = (corpus.resolve ?? []).map(([model, availIndex, preferred]) => {
    try {
      const avail = avails[availIndex].map((m) => ({ ...m }));
      return resolveEffectiveSubagentModel(undefined, model, parent, avail, preferred ?? undefined, {}) ?? null;
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
  const body = JSON.stringify({ version, resolve, normalize, package: pkg, frontmatter });
  process.stdout.write(`${sha256(body)}\n${body}`);
}
