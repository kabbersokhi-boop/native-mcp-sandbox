import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { validateReport } from "../report.js";

const data = new URL("../data/", import.meta.url);
const readJson = async (name) => JSON.parse(await readFile(new URL(name, data), "utf8"));

test("public artifacts match the source evidence manifest", async () => {
  const manifest = await readJson("manifest.json");
  assert.equal(manifest.schemaVersion, 1);
  assert.match(manifest.publication, /not a tagged release/);
  for (const [name, digest] of Object.entries(manifest.artifacts)) {
    assert.ok(!name.includes("..") && !name.startsWith("/"));
    assert.ok(!name.endsWith("run.json"));
    const bytes = await readFile(new URL(name, data));
    assert.equal(createHash("sha256").update(bytes).digest("hex"), digest, name);
  }
  const evaluation = await readJson("evaluation.json");
  assert.equal(evaluation.binarySha256, manifest.serverSha256);
  assert.equal(evaluation.passed, true);
  assert.ok(evaluation.cases.every((entry) => entry.passed));
  assert.ok(evaluation.cases.some((entry) => entry.actual === "allowed"));
  for (const entry of evaluation.cases.filter((entry) => entry.artifact)) {
    const bytes = await readFile(new URL(entry.artifact, data));
    if (entry.sha256) assert.equal(createHash("sha256").update(bytes).digest("hex"), entry.sha256);
  }
});

test("recorded scenarios retain references and honest outcomes", async () => {
  for (const [name, outcome] of Object.entries({ recovered: "recovery-observed",
    inconclusive: "inconclusive", hostile: "boundary-held" })) {
    const report = validateReport(await readJson(`${name}/report.json`));
    assert.equal(report.result, outcome);
    assert.equal(new Set(report.evidence.filter((entry) => !entry.isError)
      .map((entry) => entry.tool)).size, 4);
  }
});

test("study retains 100 observations per measurement and post-exec memory methodology", async () => {
  const study = await readJson("study.json");
  const manifest = await readJson("manifest.json");
  assert.equal(study.serverSha256, manifest.serverSha256);
  assert.equal(study.mode, "study");
  assert.equal(study.components.length, 6);
  for (const component of study.components) {
    assert.match(component.memorySource, /VmHWM/);
  }
  for (const entry of [...study.components.flatMap((component) => component.cases),
    ...Object.values(study.stdio)]) {
    assert.equal(entry.rawSamples.length, 100);
    assert.ok(entry.rawSamples.every((value) => Number.isFinite(value) && value >= 0));
    assert.equal(entry.minimum, Math.min(...entry.rawSamples));
    assert.equal(entry.maximum, Math.max(...entry.rawSamples));
    assert.ok(entry.median >= entry.minimum && entry.median <= entry.maximum);
    assert.equal(entry.p95, [...entry.rawSamples].sort((left, right) => left - right)[94]);
    assert.ok(!("p99" in entry));
  }
});
