import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { loadBoundedJson, validateReport, REPORT_LIMIT } from "../report.js";

const fixture = () => JSON.parse(JSON.stringify({ schemaVersion: 1, scenario: "hostile",
  facts: [{ claim: "<img src=x onerror=alert(1)>", evidence: ["e1"] }], inferences: [],
  unresolved: [], rejections: [], trace: [], evidence: [{ id: "e1", tool: "logs.search",
    actionId: "example", responseId: 2, structured: {} }] }));

test("hostile text remains data and evidence references remain resolvable", () => {
  const report = validateReport(fixture());
  assert.match(report.facts[0].claim, /<img/);
  report.facts[0].evidence = ["missing"];
  assert.throws(() => validateReport(report), /Orphan/);
});

test("duplicate identities and oversized collections are rejected", () => {
  const report = fixture();
  report.evidence.push(report.evidence[0]);
  assert.throws(() => validateReport(report), /identity/);
  const oversized = fixture();
  oversized.trace = Array(129).fill({});
  assert.throws(() => validateReport(oversized), /bound/);
});

test("stream byte bound cancels oversized downloads", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response("x".repeat(REPORT_LIMIT + 1));
    await assert.rejects(loadBoundedJson("unused"), /byte bound/);
    globalThis.fetch = async () => new Response(JSON.stringify(fixture()));
    assert.equal((await loadBoundedJson("unused")).scenario, "hostile");
  } finally { globalThis.fetch = original; }
});

test("viewer inserts evidence through text nodes, not HTML parsing", async () => {
  const script = await readFile(new URL("../app.js", import.meta.url), "utf8");
  assert.doesNotMatch(script, /innerHTML|outerHTML|insertAdjacentHTML|document\.write/);
  assert.match(script, /textContent/);
});
