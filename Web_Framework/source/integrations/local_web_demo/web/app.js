import { api, connect, upload } from "./transport.js";
import { createResultState, buildRequest, titles } from "./result-state.js";
import { createControls } from "./controls.js";
import { createLayout } from "./layout.js";
import {
  createFilePanel,
  confirmFileRemoval,
  restoreFileFocus,
} from "./file-panel.js";
import { createResultView } from "./result-view.js";
import { createChatPanel } from "./chat-panel.js";
import { canvasScope, selectedBatch } from "./canvas-scope.js";
import { createViewer } from "./viewer.js";
import { createConnectionRecovery } from "./connection-recovery.js";
import {
  createAutoPreview,
  previewSpec,
  AUTO_PREVIEW_LABEL,
} from "./auto-preview.js";
const $ = (id) => document.getElementById(id),
  state = createResultState(),
  layout = createLayout(),
  viewer = createViewer();
let loading = false,
  removingFile = false,
  bootstrapped = false,
  lastHealth = null,
  healthCheckedAt = 0,
  sessionNotice = "",
  uploadRole = "pcb",
  previewPaused = false,
  selectedSignature = "";
const connection = createConnectionRecovery();
const persist = () =>
  localStorage.setItem(
    "pcb-demo-view-v2",
    JSON.stringify({
      ...state.serialize(),
      preview_paused: previewPaused,
    }),
  );
function notice(text) {
  $("notice").hidden = !text;
  $("notice").textContent = text || "";
}
function selectResult(id) {
  previewPaused = true;
  autoPreview.pause();
  state.select(id);
  render();
  persist();
}
const resultView = createResultView(viewer, selectResult);
const autoPreview = createAutoPreview({
  submit: (arguments_) =>
    api("analysis", { arguments: arguments_, label: AUTO_PREVIEW_LABEL }),
  install: (job, _cached, presentationId) => {
    state.select(presentationId || job.presentations?.[0]?.id);
    notice("");
    render();
    persist();
  },
  onError: (error) => {
    notice(error.message);
    render();
  },
});
function requestAutoPreview() {
  previewPaused = false;
  autoPreview.request(
    state.snapshot.native_error
      ? null
      : previewSpec(state.draft, state.selection),
  );
  autoPreview.observe(state.snapshot);
}
const controls = createControls((value) => {
  state.setDraft(value);
  requestAutoPreview();
  render();
  persist();
});
const filePanel = createFilePanel(
  async (value) => {
    try {
      await api("selection", value);
      state.setSelection(value);
      requestAutoPreview();
      render();
      persist();
    } catch (e) {
      notice(e.message);
    }
  },
  (job) => {
    const first = job.presentations?.[0];
    if (first) selectResult(first.id);
    else notice(job.stage || "此任务尚无结果。");
    layout.close();
  },
  async (file) => {
    if (removingFile || !(await confirmFileRemoval(file))) return;
    const serverId = state.snapshot.server_id;
    removingFile = true;
    previewPaused = true;
    autoPreview.reset();
    render();
    let message = "";
    try {
      const result = await api("files/remove", { file_id: file.id });
      if (state.snapshot.server_id !== serverId) return;
      if (
        state.ingest(result.state, {
          deferJob: (job) => job.label === AUTO_PREVIEW_LABEL,
        })
      )
        state.setSelection(result.state.selection);
      message = "已从工作区删除“" + file.name + "”。本机原始文件和报告未删除。";
    } catch (error) {
      message = error.message;
    } finally {
      removingFile = false;
      render();
      persist();
      restoreFileFocus(file, state.snapshot.files);
      if (message) notice(message);
    }
  },
);
const chatPanel = createChatPanel(
  refresh,
  (ref) => {
    selectResult(ref.presentation_id);
    layout.close();
  },
  () => ({
    ...canvasScope(state, viewer.matchesDisplayed(state.result)),
    batchFiles: selectedBatch(state),
  }),
);
function render() {
  filePanel.render(state, {
    removing: removingFile,
    removalSupported: lastHealth?.file_removal_version === 1,
  });
  resultView.render(state);
  viewer.setPickingContext(
    state.result,
    state.draft,
    lastHealth?.pressure_picking_version === 1,
  );
  chatPanel.render(state.snapshot);
  const active = state.snapshot.jobs.find(
    (j) => j.id === state.snapshot.active_job,
  );
  $("analysis-status").hidden = !active;
  $("stage").textContent = active?.stage || "";
  $("cancel-analysis").disabled = active?.status === "cancelling";
  controls.busy(
    removingFile ||
      connection.recovering ||
      !!active ||
      !!state.snapshot.export_busy ||
      !!state.snapshot.native_error,
  );
  $("preview-status").textContent = autoPreview.message;
  $("preview-retry").hidden =
    state.draft.kind !== "preview" || !autoPreview.error;
  if (state.draft.kind === "preview")
    $("draft-notice").hidden = !autoPreview.pending || !state.result;
  const signature = JSON.stringify([
    state.result?.id,
    state.result?.diagnostics,
    state.job?.status,
  ]);
  if (signature !== selectedSignature) {
    selectedSignature = signature;
    if (state.result && state.result.status !== "succeeded") {
      const text = state.result.diagnostics
        .map((d) => d.message)
        .filter(Boolean)
        .join("；");
      notice(text || "此结果未完整完成，请查看状态和可用报告。");
    } else notice("");
  }
  const latest = state.snapshot.jobs.at(-1);
  if (
    latest?.status === "failed" &&
    !latest.presentations?.length &&
    latest.label !== AUTO_PREVIEW_LABEL
  ) {
    notice(
      (latest.diagnostics
        ?.map((d) => d.message)
        .filter(Boolean)
        .join("；") || latest.stage) + "。画布保留上一次可用结果。",
    );
  }
  if (state.snapshot.native_error)
    notice("本机分析不可用：" + state.snapshot.native_error);
}
function initializeSnapshot(snapshot, health, restore = false) {
  state.ingest(snapshot);
  state.setSelection(snapshot.selection || { pcb_ids: [], holder_id: null });
  if (restore) {
    try {
      const saved = JSON.parse(
        localStorage.getItem("pcb-demo-view-v2") || "null",
      );
      state.restore(saved);
      if (saved?.session_id === snapshot.session_id) {
        previewPaused = !!saved.preview_paused;
      }
    } catch {
      localStorage.removeItem("pcb-demo-view-v2");
    }
  }
  controls.set(state.draft);
  chatPanel.initialize(health, snapshot);
  autoPreview.observe(snapshot);
}
async function refresh() {
  if (loading || !connection.ready) return;
  loading = true;
  const recovering = connection.recovering;
  try {
    if (!bootstrapped || recovering || Date.now() - healthCheckedAt >= 5000) {
      lastHealth = await connect();
      healthCheckedAt = Date.now();
    }
    const snapshot = await api("state");
    const changed =
      bootstrapped && state.snapshot.server_id !== snapshot.server_id;
    if (
      !changed &&
      (snapshot.file_revision || 0) < (state.snapshot.file_revision || 0)
    )
      return;
    const filesRemoved =
      !changed &&
      state.snapshot.files.some(
        (file) => !snapshot.files.some((f) => f.id === file.id),
      );
    if (filesRemoved) {
      autoPreview.reset();
      previewPaused = true;
    }
    if (changed) {
      autoPreview.reset();
      chatPanel.reset();
      viewer.show(null);
      state.reset();
      selectedSignature = "";
      previewPaused = true;
      localStorage.removeItem("pcb-demo-view-v2");
      lastHealth = await connect();
      initializeSnapshot(snapshot, lastHealth);
      sessionNotice =
        "本地服务已重启，已清除旧会话引用。原文件仍保留，请重新载入需要的文件。";
    } else if (!bootstrapped) {
      initializeSnapshot(snapshot, lastHealth, true);
      bootstrapped = true;
    } else {
      state.ingest(snapshot, {
        deferJob: (job) => job.label === AUTO_PREVIEW_LABEL,
      });
      autoPreview.observe(snapshot);
      if (filesRemoved) state.setSelection(snapshot.selection);
    }
    connection.success();
    chatPanel.setConnection(lastHealth, true);
    controls.configure(lastHealth);
    viewer.setExportFormats(lastHealth.image_export_formats || ["png", "jpg"]);
    autoPreview.setOnline(true);
    if (!previewPaused && !autoPreview.active) requestAutoPreview();
    render();
    if (sessionNotice && snapshot.files.length) sessionNotice = "";
    $("connection-status").hidden = !sessionNotice;
    $("connection-message").textContent = sessionNotice;
    $("reconnect").hidden = true;
    if (recovering && !changed) {
      viewer.recover();
    }
    if (changed || filesRemoved) persist();
  } catch (error) {
    const seconds = connection.failure();
    autoPreview.setOnline(false);
    controls.busy(true);
    chatPanel.setConnection(lastHealth, false);
    $("connection-status").hidden = false;
    $("connection-message").textContent =
      error.message + " 正在自动重连（" + seconds + "秒后）。";
    $("reconnect").hidden = false;
  } finally {
    loading = false;
  }
}
$("reconnect").onclick = () => {
  connection.retryNow();
  void refresh();
};
async function execute(arguments_, label) {
  notice("");
  await api("analysis", { arguments: arguments_, label });
  await refresh();
}
$("run").onclick = async () => {
  try {
    await execute(
      buildRequest(state.draft, state.selection),
      titles[state.draft.kind],
    );
  } catch (e) {
    notice(e.message);
  }
};
$("preview-retry").onclick = () => {
  notice("");
  autoPreview.retry();
  render();
};
$("cancel-analysis").onclick = async () => {
  try {
    autoPreview.pause();
    previewPaused = true;
    persist();
    await api("analysis/cancel", { job_id: state.snapshot.active_job });
    await refresh();
  } catch (e) {
    notice(e.message);
  }
};
async function setSelection(value) {
  await api("selection", value);
  state.setSelection(value);
  requestAutoPreview();
  render();
}
async function addFiles(files, role) {
  try {
    const selected = {
      pcb_ids: [...state.selection.pcb_ids],
      holder_id: state.selection.holder_id,
    };
    for (const file of files) {
      notice("正在上传 " + file.name + "…");
      const item = await upload(file, role);
      if (role === "pcb") {
        selected.pcb_ids.push(item.id);
      } else selected.holder_id = item.id;
    }
    await refresh();
    await setSelection(selected);
    layout.close();
    notice("");
  } catch (e) {
    notice(e.message);
  } finally {
    refresh();
  }
}
$("upload-empty").onclick = () => $("upload-pcb").click();
$("upload-pcb").onclick = () => {
  uploadRole = "pcb";
  $("file-input").click();
};
$("upload-holder").onclick = () => {
  uploadRole = "holder";
  $("file-input").click();
};
$("file-input").onchange = (e) => {
  addFiles([...e.target.files], uploadRole);
  e.target.value = "";
};
const drop = $("dropzone");
drop.ondragover = (e) => {
  e.preventDefault();
  drop.classList.add("drag");
};
drop.ondragleave = () => drop.classList.remove("drag");
drop.ondrop = (e) => {
  e.preventDefault();
  drop.classList.remove("drag");
  const files = [...e.dataTransfer.files],
    dialog = $("upload-dialog");
  dialog.onclose = () => {
    if (["pcb", "holder"].includes(dialog.returnValue))
      addFiles(files, dialog.returnValue);
  };
  dialog.showModal();
};
window.addEventListener("beforeunload", persist);
controls.set(state.draft);
controls.busy(true);
await refresh();
setInterval(refresh, 1000);
