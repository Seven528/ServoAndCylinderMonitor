import { markdown } from "./text.js";
import { bindDownload, saveDownload } from "./transport.js";
import { replyReportRequested } from "./report-request.js";

export function analysisDocument(message, format = "html") {
  const text = String(message.text || "");
  if (text.length > 1024 * 1024) throw new Error("本段分析内容超过下载上限。");
  const complete = ["completed", "succeeded", "complete"].includes(
    message.status,
  );
  const heading =
    "MOE6 CD Auto Analysis Agent" + (complete ? "" : " · 当前内容");
  const content = "# " + heading + "\n\n" + text + "\n";
  if (format === "md")
    return new Blob([content], { type: "text/markdown;charset=utf-8" });
  return new Blob(
    [
      '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>' +
        heading +
        "</title><style>body{max-width:1000px;margin:40px auto;padding:0 24px;font:14px/1.7 system-ui;color:#2e3033}h1{font-size:20px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #d0d4d8;padding:6px 10px;text-align:left}th{background:#eff1f2}code{background:#eff1f2;padding:2px 4px}.chat-table{overflow:auto}</style><h1>" +
        heading +
        "</h1>" +
        markdown(text) +
        "</html>",
    ],
    { type: "text/html;charset=utf-8" },
  );
}
export function renderMessageDownloads(container, message, snapshot, onError) {
  container.replaceChildren();
  container.hidden = true;
  if (
    message.role !== "assistant" ||
    !message.text ||
    message.status === "running" ||
    !replyReportRequested(message, snapshot)
  )
    return;
  container.hidden = false;
  const id = String(message.id)
    .replace(/[^A-Za-z0-9_-]/g, "")
    .slice(0, 64);
  for (const [format, label] of [
    ["html", "下载分析报告"],
    ["md", "Markdown"],
  ]) {
    const link = document.createElement("a");
    link.href = "#";
    link.textContent = label;
    link.onclick = (event) => {
      event.preventDefault();
      try {
        saveDownload(
          analysisDocument(message, format),
          "agent-analysis-" + id + "." + format,
        );
      } catch (error) {
        onError(error);
      }
    };
    container.append(link);
  }
  const artifacts = new Map(
    (snapshot.jobs || [])
      .flatMap((job) => job.artifacts || [])
      .map((a) => [a.id, a]),
  );
  const seen = new Set();
  for (const ref of message.analysis_refs || []) {
    const artifact = artifacts.get(ref.report_id);
    if (
      !artifact ||
      seen.has(artifact.id) ||
      artifact.mime_type !== "application/json"
    )
      continue;
    seen.add(artifact.id);
    const link = document.createElement("a");
    link.href = artifact.url;
    link.textContent =
      "原始 JSON · " + (ref.context?.file_name || artifact.name);
    link.title = link.textContent;
    bindDownload(link, { ...artifact, server_id: snapshot.server_id }, onError);
    container.append(link);
  }
}
