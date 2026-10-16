import { contextLabel, titles } from "./result-state.js";
import { statusNames } from "./file-panel.js";
import { renderSummary } from "./summary.js";
export function createResultView(viewer, onSelect) {
  const $ = (id) => document.getElementById(id);
  let signature = "";
  $("result-select").onchange = () => onSelect($("result-select").value);
  return {
    render(state) {
      $("draft-notice").textContent =
        state.draft.kind === "preview"
          ? "正在自动更新预览；下方仍为上一次结果。"
          : "参数已更改，尚未执行；下方仍为已生成结果。";
      $("draft-notice").hidden = !state.dirty();
      const job = state.job,
        view = state.result;
      const sig = JSON.stringify([
        view,
        job?.status,
        job?.presentations.map((item) => item.id),
      ]);
      if (sig === signature) return;
      signature = sig;
      if (!view) {
        renderSummary(null);
        viewer.show(null);
        $("result-title").textContent = "从一份 PCB 开始";
        $("context-label").textContent = "添加 PCB，查看布局、高度和压棒接触。";
        $("result-select").hidden = true;
        $("result-status").textContent = "";
        $("empty").querySelector("h2").textContent = "看清结构，再开始分析";
        $("empty").querySelector("p").textContent =
          "从左侧文件栏添加 PCB 或 Holder 文件。";
        $("upload-empty").hidden = false;
        return;
      }
      $("result-title").textContent = titles[view.context.kind] || "分析结果";
      const label = `${titles[view.context.kind] || "分析结果"} · ${contextLabel(view.context)}`;
      $("context-label").textContent = label;
      $("context-label").title = label;
      $("result-status").textContent = statusNames[view.status] || view.status;
      $("result-status").className = "result-status " + view.status;
      const selector = $("result-select");
      selector.replaceChildren();
      selector.hidden = job.presentations.length < 2;
      for (const [i, item] of job.presentations.entries()) {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = `${i + 1}. ${contextLabel(item.context)}`;
        selector.append(option);
      }
      selector.value = view.id;
      renderSummary(view);
      const image = job.artifacts.find((a) => a.id === view.image_id);
      viewer.show(
        image
          ? {
              ...image,
              server_id: state.snapshot.server_id,
              presentation_id: view.id,
            }
          : null,
      );
      if (!image) {
        $("empty").querySelector("h2").textContent =
          view.status === "cancelled" ? "分析已取消" : "没有可显示的图片";
        $("empty").querySelector("p").textContent = view.report_id
          ? "分析报告已保留，可请 Agent 查询。"
          : "请查看任务诊断或选择其他结果。";
        $("upload-empty").hidden = true;
      }
    },
  };
}
