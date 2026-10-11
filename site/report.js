export const REPORT_LIMIT = 128 * 1024;

export function validateReport(report) {
  if (!report || report.schemaVersion !== 1 || !["recovered", "inconclusive", "hostile"].includes(report.scenario)) {
    throw new Error("Unsupported report");
  }
  for (const key of ["facts", "inferences", "unresolved", "rejections", "evidence", "trace"]) {
    if (!Array.isArray(report[key]) || report[key].length > 128) throw new Error("Report collection exceeds its bound");
  }
  const ids = new Set();
  for (const item of report.evidence) {
    if (!item || typeof item.id !== "string" || !/^e[1-9][0-9]?$/.test(item.id) || ids.has(item.id)) throw new Error("Invalid evidence identity");
    if (typeof item.tool !== "string" || typeof item.actionId !== "string" || !Number.isInteger(item.responseId)) throw new Error("Invalid evidence reference");
    ids.add(item.id);
  }
  for (const item of [...report.facts, ...report.inferences, ...report.rejections]) {
    if (!Array.isArray(item.evidence) || item.evidence.some((id) => !ids.has(id))) throw new Error("Orphan evidence reference");
  }
  return report;
}

export async function loadBoundedJson(url, limit = REPORT_LIMIT) {
  const response = await fetch(url);
  if (!response.ok || !response.body) throw new Error("Evidence artifact unavailable");
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new Error("Evidence artifact exceeds its byte bound");
      chunks.push(value);
    }
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
}
