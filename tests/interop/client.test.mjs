import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

test("official SDK exercises the real native tools and denial contract", { timeout: 15000 }, async () => {
  assert.ok(process.env.NMS_SERVER, "set NMS_SERVER to the native executable");
  const workspace = await mkdtemp(join(tmpdir(), "nms-sdk-"));
  const client = new Client({ name: "independent-sdk-check", version: "1" });
  let diagnostics = "";
  let transport;
  try {
    await writeFile(join(workspace, "application.log"), "INC-042 failed\nINC-042 recovered\n");
    const header = Buffer.alloc(64);
    Buffer.from([0x7f, 0x45, 0x4c, 0x46, 2, 1, 1, 3]).copy(header);
    header.writeUInt16LE(2, 16);
    header.writeUInt16LE(62, 18);
    header.writeUInt32LE(1, 20);
    header.writeUInt16LE(64, 52);
    header.writeUInt16LE(56, 54);
    await writeFile(join(workspace, "sample.elf"), header, { mode: 0o600 });
    const policy = join(workspace, "policy.json");
    await writeFile(policy, JSON.stringify({
      version: 2,
      roots: [{ name: "evidence", path: workspace, maxFileBytes: 65536 }],
      processes: [{ name: "server", pid: "self" }],
    }), { mode: 0o600 });
    transport = new StdioClientTransport({
      command: resolve(process.env.NMS_SERVER), args: ["--policy-config", policy],
      env: { LANG: "C" }, stderr: "pipe",
    });
    transport.stderr?.on("data", (chunk) => {
      diagnostics += chunk.toString();
      if (diagnostics.length > 65536) void client.close();
    });
    await client.connect(transport);
    const surface = await client.listTools();
    assert.deepEqual(surface.tools.map((tool) => tool.name).sort(),
      ["elf.inspect", "logs.search", "logs.tail", "proc.memory"]);
    await client.ping();
    const search = await client.callTool({ name: "logs.search", arguments: {
      root: "evidence", path: "application.log", query: "INC-042",
    } });
    assert.equal(search.isError, false);
    assert.equal(search.structuredContent.matches.length, 2);
    const [tail, elf] = await Promise.all([
      client.callTool({ name: "logs.tail", arguments: {
        root: "evidence", path: "application.log", maxLines: 1,
      } }),
      client.callTool({ name: "elf.inspect", arguments: {
        root: "evidence", path: "sample.elf",
      } }),
    ]);
    assert.equal(tail.structuredContent.lines[0].preview, "INC-042 recovered");
    assert.equal(elf.structuredContent.machineNumber, 62);
    const memory = await client.callTool({ name: "proc.memory", arguments: { process: "server" } });
    assert.equal(memory.structuredContent.pidfdPinned, true);
    assert.equal(memory.structuredContent.threads, 3);
    const denied = await client.callTool({ name: "logs.search", arguments: {
      root: "evidence", path: "../outside.txt", query: "secret",
    } });
    assert.equal(denied.isError, true);
    assert.equal(JSON.parse(denied.content[0].text).error.code, "invalid_relative_path");
    const unknown = await client.callTool({ name: "proc.memory", arguments: { process: "unknown" } });
    assert.equal(unknown.isError, true);
    assert.equal(JSON.parse(unknown.content[0].text).error.code, "unknown_process");
    assert.equal(diagnostics, "");
  } finally {
    await client.close();
    await transport?.close();
    await rm(workspace, { recursive: true, force: true });
  }
});
