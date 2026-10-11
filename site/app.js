import { loadBoundedJson, validateReport } from "./report.js";

const descriptions = {
  recovered: "The approved log reports recovery. All four native tools return bounded, correlated evidence.",
  inconclusive: "The search hits its match cap. The ELF header also differs from the expected deployment target. Recovery remains unproven.",
  hostile: "The log contains hostile instructions. A scripted traversal reaches C++ and is denied; an invented shell tool is rejected before execution.",
};
let current;
let selection = 0;
const element = (id) => document.getElementById(id);
function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = text;
  if (className) result.className = className;
  return result;
}
function inspect(id, focus = false) {
  const item = current.evidence.find((value) => value.id === id);
  if (!item) return;
  const detail = element("evidence-detail");
  detail.replaceChildren(node("h3", `${item.id} / ${item.tool}`),
    node("p", `Response ${item.responseId} · action ${item.actionId}`, "evidence-meta"),
    node("p", item.isError ? "Native tool returned a policy error." : "Native result validated by the client.", "small"),
    node("h4", "Requested arguments"), node("pre", JSON.stringify(item.arguments, null, 2)),
    node("h4", "Validated result projection"), node("pre", JSON.stringify(item.structured, null, 2)));
  document.querySelectorAll("[data-evidence]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.evidence === id)));
  if (focus) detail.focus({ preventScroll: true });
}
function statements(id, values) {
  const container = element(id);
  container.replaceChildren();
  if (!values.length) container.append(node("p", "No supported conclusion from the available evidence.", "small"));
  for (const value of values) {
    const paragraph = node("p", value.claim, "fact");
    for (const ref of value.evidence) {
      const button = node("button", ref, "ref");
      button.type = "button";
      button.setAttribute("aria-label", `Inspect evidence ${ref}`);
      button.addEventListener("click", () => inspect(ref, true));
      paragraph.append(" ", button);
    }
    container.append(paragraph);
  }
}
async function choose(scenario) {
  const generation = ++selection;
  element("load-status").textContent = "Loading recorded evidence…";
  try {
    const report = validateReport(await loadBoundedJson(`data/${scenario}/report.json`));
    if (generation !== selection) return;
    current = report;
    document.querySelectorAll("[data-scenario]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.scenario === scenario)));
    element("outcome").textContent = report.result;
    element("outcome").className = "badge" + (scenario === "inconclusive" ? " warning" : "");
    element("scenario-description").textContent = descriptions[scenario];
    element("download").href = `data/${scenario}/report.json`;
    statements("facts", report.facts);
    statements("inferences", report.inferences);
    element("unresolved").replaceChildren(...report.unresolved.map((text) => node("li", text)));
    element("rejections").replaceChildren();
    for (const rejection of report.rejections) {
      const box = node("div", undefined, "rejection");
      box.append(node("strong", rejection.layer), node("code", rejection.attempt), node("div", rejection.reason));
      element("rejections").append(box);
    }
    element("evidence-buttons").replaceChildren();
    for (const item of report.evidence) {
      const button = node("button", `${item.id} ${item.tool}`);
      button.type = "button";
      button.dataset.evidence = item.id;
      button.addEventListener("click", () => inspect(item.id));
      element("evidence-buttons").append(button);
    }
    element("trace").replaceChildren(...report.trace.map((event) => node("li", `${event.event} ${JSON.stringify(event.metadata)}`)));
    inspect(report.evidence[0].id);
    element("load-status").textContent = `${report.evidence.length} validated native responses · recorded synthetic run · no live model`;
  } catch (error) {
    if (generation === selection) element("load-status").textContent = `Could not display this report: ${error.message}`;
  }
}
document.querySelectorAll("[data-scenario]").forEach((button) => button.addEventListener("click", () => choose(button.dataset.scenario)));
void choose("recovered");
loadBoundedJson("data/study.json", 2 * 1024 * 1024).then((study) => {
  for (const [label, value] of [["Samples / native case", study.components[0].samples],
    ["Cold start + initialize", `${(study.stdio["cold-start-initialize"].median / 1e6).toFixed(2)} ms`],
    ["Four tools + lifecycle", `${(study.stdio["four-tool-investigation"].median / 1e6).toFixed(2)} ms`]]) {
    element("measurement-summary").append(node("dt", label), node("dd", String(value)));
  }
}).catch(() => element("measurement-summary").append(node("p", "Measurements unavailable. Use the raw artifact link.")));
