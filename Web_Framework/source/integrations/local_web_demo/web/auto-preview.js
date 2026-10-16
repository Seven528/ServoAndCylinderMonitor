import { buildRequest } from "./result-state.js";
export const AUTO_PREVIEW_LABEL = "自动预览";

export function previewSpec(draft, selection) {
  if (draft.kind !== "preview") return null;
  const wanted = selection.pcb_ids.length
    ? selection.pcb_ids.map((id) => ({
        kind: "pcb_preview",
        pcb_file_id: id,
        side: draft.side,
        view_mode: draft.view_mode,
        surface_view: draft.surface_view,
      }))
    : selection.holder_id
      ? [
          {
            kind: "holder_preview",
            holder_file_id: selection.holder_id,
            side: null,
            view_mode: "panel",
            surface_view: "full",
          },
        ]
      : [];
  if (!wanted.length) return null;
  return {
    key: JSON.stringify(wanted),
    wanted,
    arguments: buildRequest(draft, selection),
  };
}

export function cachedPreview(snapshot, spec) {
  for (const job of [...snapshot.jobs].reverse()) {
    if (job.status !== "succeeded") continue;
    const matches = spec.wanted.map((wanted) =>
      job.presentations?.find(
        (view) =>
          view.status === "succeeded" &&
          view.image_id &&
          Object.entries(wanted).every(
            ([key, value]) => (view.context[key] ?? null) === value,
          ),
      ),
    );
    if (matches.every(Boolean)) return { job, presentationId: matches[0].id };
  }
  return null;
}

// One pending selection, one native request at a time; the native cache remains authoritative.
export function createAutoPreview({
  submit,
  install,
  onError,
  delay = 250,
  schedule = setTimeout,
  unschedule = clearTimeout,
}) {
  let snapshot = { jobs: [], active_job: null },
    desired = null,
    satisfied = null,
    failed = null;
  let timer = null,
    settling = false,
    posting = false,
    running = null;
  let epoch = 0,
    online = true;
  async function pump() {
    if (
      !online ||
      !desired ||
      settling ||
      posting ||
      running ||
      failed ||
      satisfied === desired.key
    )
      return;
    const cached = cachedPreview(snapshot, desired);
    if (cached) {
      satisfied = desired.key;
      install(cached.job, true, cached.presentationId);
      return;
    }
    if (snapshot.active_job || snapshot.export_busy) return;
    const issued = desired;
    const issuedEpoch = epoch;
    posting = true;
    try {
      const job = await submit(issued.arguments);
      if (issuedEpoch === epoch) running = { id: job.id, key: issued.key };
    } catch (error) {
      if (issuedEpoch === epoch && desired?.key === issued.key) {
        failed = issued.key;
        onError(error);
      }
    } finally {
      if (issuedEpoch === epoch) posting = false;
    }
  }
  function pause() {
    if (timer !== null) unschedule(timer);
    timer = null;
    settling = false;
    desired = null;
    satisfied = null;
    failed = null;
  }
  return {
    reset() {
      pause();
      epoch++;
      posting = false;
      running = null;
      snapshot = { jobs: [], active_job: null };
    },
    setOnline(value) {
      online = value;
      if (value) void pump();
    },
    request(spec, { force = false } = {}) {
      if (!spec) {
        pause();
        return;
      }
      if (!force && desired?.key === spec.key) return;
      if (timer !== null) unschedule(timer);
      desired = spec;
      satisfied = null;
      failed = null;
      settling = true;
      timer = schedule(() => {
        timer = null;
        settling = false;
        void pump();
      }, delay);
    },
    observe(value) {
      snapshot = value;
      if (running) {
        const job = value.jobs.find((j) => j.id === running.id);
        if (job && !["running", "cancelling"].includes(job.status)) {
          const completed = running;
          running = null;
          if (desired?.key === completed.key) {
            if (job.status === "succeeded") {
              satisfied = completed.key;
              install(job, false);
            } else {
              failed = completed.key;
              onError(
                new Error(
                  job.diagnostics
                    ?.map((d) => d.message)
                    .filter(Boolean)
                    .join("；") ||
                    job.stage ||
                    "预览未完成",
                ),
              );
            }
          }
        }
      }
      void pump();
    },
    pause,
    retry() {
      if (desired) this.request(desired, { force: true });
    },
    get pending() {
      return !!desired && satisfied !== desired.key && !failed;
    },
    get error() {
      return !!failed;
    },
    get active() {
      return !!desired;
    },
    get message() {
      if (failed) return "预览未完成";
      if (!desired || satisfied === desired.key) return "自动预览";
      if (!online) return "等待连接恢复";
      return snapshot.active_job && snapshot.active_job !== running?.id
        ? "等待当前任务结束"
        : "正在更新预览…";
    },
  };
}
