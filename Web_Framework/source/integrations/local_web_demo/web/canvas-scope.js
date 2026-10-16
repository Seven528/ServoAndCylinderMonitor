import { contextLabel } from "./result-state.js";

export function canvasScope(state, imageReady = true) {
  const view = state.result;
  if (view && !imageReady)
    return { request: null, label: "主图加载中或不可用，暂不开放 Agent 分析" };
  if (view)
    return {
      request: { presentation_id: view.id },
      label: "当前画布 · " + contextLabel(view.context),
    };
  return { request: null, label: "请先在主画布显示一个文件" };
}

export function selectedBatch(state) {
  const ids = [...state.selection.pcb_ids];
  if (state.selection.holder_id) ids.push(state.selection.holder_id);
  return ids
    .map((id) => state.snapshot.files.find((f) => f.id === id))
    .filter(Boolean);
}

export function supportsExplicitScope(health) {
  return (
    health?.canvas_scope_version === 1 &&
    health?.explicit_file_scope_version === 1
  );
}

// Only the host resolves current human text against its live upload catalog.
// An unready canvas is never authority; explicit file requests still may work.
export function chatScopeRequest(canvas) {
  return canvas.request || { presentation_id: null };
}
