import { contextLabel } from "./result-state.js";
import { historySubjects } from "./history-subjects.js";
export const statusNames = {
  running: "计算中",
  cancelling: "正在取消",
  cancelled: "已取消",
  succeeded: "已完成",
  failed: "未完成",
  disabled: "暂未开放",
};
export function confirmFileRemoval(file) {
  const dialog = document.getElementById("remove-file-dialog");
  if (dialog.open) return Promise.resolve(false);
  document.getElementById("remove-file-name").textContent = file.name;
  dialog.returnValue = "cancel";
  return new Promise((resolve) => {
    dialog.onclose = () => {
      dialog.onclose = null;
      resolve(dialog.returnValue === "remove");
    };
    dialog.showModal();
  });
}
export function restoreFileFocus(file, files) {
  if (document.activeElement !== document.body) return;
  const original = document.querySelector(`[data-remove-file-id="${file.id}"]`);
  const next = files.find((item) => item.role === file.role);
  const target =
    original && !original.disabled
      ? original
      : (next && document.querySelector(`[data-file-id="${next.id}"]`)) ||
        document.getElementById("upload-" + file.role);
  target?.focus();
}
export function createFilePanel(onSelection, onHistory, onRemove) {
  let filesSignature = "",
    historySignature = "";
  const $ = (id) => document.getElementById(id);
  return {
    render(state, { removing = false, removalSupported = false } = {}) {
      const files = state.snapshot.files,
        selection = state.selection,
        busy =
          removing ||
          !!state.snapshot.active_job ||
          !!state.snapshot.export_busy ||
          !!state.snapshot.chat_busy;
      const sig = JSON.stringify([
        files,
        selection,
        busy,
        removing,
        removalSupported,
      ]);
      if (sig !== filesSignature) {
        const focusedFile = document.activeElement?.dataset.fileId;
        const focusedRemove = document.activeElement?.dataset.removeFileId;
        filesSignature = sig;
        $("file-count").textContent = files.length;
        $("dropzone").classList.toggle("has-files", files.length > 0);
        for (const role of ["pcb", "holder"]) {
          const box = $(role + "-files");
          box.replaceChildren();
          for (const f of files.filter((f) => f.role === role)) {
            const row = document.createElement("div"),
              label = document.createElement("label"),
              input = document.createElement("input"),
              info = document.createElement("div"),
              name = document.createElement("strong"),
              detail = document.createElement("small"),
              remove = document.createElement("button");
            const checked =
              role === "pcb"
                ? selection.pcb_ids.includes(f.id)
                : selection.holder_id === f.id;
            row.className = "file-row" + (checked ? " selected" : "");
            label.className = "file-select";
            label.title = f.name;
            input.type = role === "pcb" ? "checkbox" : "radio";
            input.name = role;
            input.dataset.fileId = f.id;
            input.checked = checked;
            input.disabled = removing;
            input.setAttribute("aria-label", f.name);
            name.textContent = f.name;
            name.tabIndex = 0;
            name.setAttribute("aria-label", f.name);
            detail.textContent =
              (role === "pcb" ? "PCB" : "Holder") +
              " · " +
              (f.size / 1024 / 1024).toFixed(1) +
              " MB";
            input.onchange = () => {
              const next = {
                pcb_ids: [...state.selection.pcb_ids],
                holder_id: state.selection.holder_id,
              };
              if (role === "pcb")
                next.pcb_ids = input.checked
                  ? [...next.pcb_ids, f.id]
                  : next.pcb_ids.filter((id) => id !== f.id);
              else next.holder_id = f.id;
              onSelection(next);
            };
            info.append(name, detail);
            label.append(input, info);
            remove.type = "button";
            remove.className = "file-remove";
            remove.dataset.removeFileId = f.id;
            remove.setAttribute("aria-label", "删除文件 " + f.name);
            remove.disabled = busy || !removalSupported;
            remove.title = !removalSupported
              ? "更新并重启后端后可删除文件"
              : busy
                ? "请等待分析、导出或对话结束后再删除"
                : "从当前工作区删除此文件";
            remove.innerHTML =
              '<svg aria-hidden="true"><use href="#i-trash"></use></svg>';
            remove.onclick = () => onRemove(f);
            row.append(label, remove);
            box.append(row);
          }
          if (!box.children.length) {
            const p = document.createElement("p");
            p.className = "muted";
            p.textContent = "尚未添加 " + (role === "pcb" ? "PCB" : "Holder");
            box.append(p);
          }
        }
        if (focusedFile)
          document.querySelector(`[data-file-id="${focusedFile}"]`)?.focus();
        if (focusedRemove)
          (
            document.querySelector(
              `[data-remove-file-id="${focusedRemove}"]`,
            ) || $("upload-pcb")
          )?.focus();
      }
      const jobs = state.snapshot.jobs;
      const hs = JSON.stringify([
        jobs.map((j) => [
          j.id,
          j.status,
          j.elapsed_ms,
          j.presentations?.length,
        ]),
        state.job?.id,
      ]);
      if (hs === historySignature) return;
      historySignature = hs;
      $("job-count").textContent = jobs.length;
      const box = $("history");
      const focusedJob = document.activeElement?.dataset.jobId;
      const scroll = box.parentElement.scrollTop;
      box.replaceChildren();
      for (const job of [...jobs].reverse()) {
        const b = document.createElement("button"),
          name = document.createElement("span"),
          context = document.createElement("small"),
          status = document.createElement("small");
        b.className =
          "history-item" + (state.job?.id === job.id ? " selected" : "");
        b.dataset.jobId = job.id;
        const subjects = historySubjects(job, files);
        name.textContent = subjects.join("、") || "执行对象待确认";
        name.title = subjects.join("\n");
        const views = job.presentations || [];
        context.textContent =
          job.label +
          " · " +
          (views.length > 1
            ? `${views.length} 项结果`
            : views[0]
              ? contextLabel(views[0].context, { file: false, surface: false })
              : "等待结果");
        status.textContent =
          (statusNames[job.status] || job.status) +
          (job.elapsed_ms ? ` · ${(job.elapsed_ms / 1000).toFixed(1)}s` : "");
        status.className = job.status;
        b.append(name, context, status);
        b.title =
          subjects.join("\n") +
          "\n" +
          (views[0]
            ? contextLabel(views[0].context, { file: false })
            : job.label);
        b.onclick = () => onHistory(job);
        box.append(b);
      }
      box.parentElement.scrollTop = scroll;
      if (focusedJob)
        box.querySelector(`[data-job-id="${focusedJob}"]`)?.focus();
    },
  };
}
