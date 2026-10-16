// Pure presentation state. Editing a request never changes an already computed result.
export const titles = {
  preview: "结构预览",
  pcb_preview: "结构预览",
  holder_preview: "Holder 预览",
  pcb_inspect: "PCB 摘要",
  holder_inspect: "Holder 摘要",
  single_board_pressure: "单板压棒",
  height_map: "高度图",
  pressure2d: "干涉分析",
};
export const defaults = {
  kind: "preview",
  side: "side1",
  view_mode: "single",
  surface_view: "full",
  filter: { kind: "all" },
};
export const filterOptions = [
  ["all", "全部高度"],
  ["at_most_0_5_mm", "≤ 0.5 mm"],
  ["from_0_5_to_1_0_mm", "0.5–1.0 mm"],
  ["from_1_0_to_2_0_mm", "1.0–2.0 mm"],
  ["above_2_0_mm", "> 2.0 mm"],
  ...Array.from({ length: 10 }, (_, i) => [
    `from_${i + 2}_to_${i + 3}_mm`,
    `${i + 2}–${i + 3} mm`,
  ]),
  ["above_12_mm", "> 12 mm"],
  ["unknown", "高度未知"],
  ["custom", "自定义范围…"],
];
export function filterLabel(filter) {
  if (!filter) return "";
  if (filter.kind === "custom")
    return `${Number(filter.minimum_mm).toFixed(3)}–${Number(filter.maximum_mm).toFixed(3)} mm`;
  return filterOptions.find(([k]) => k === filter.kind)?.[1] || "范围未确认";
}
export function contextLabel(context, { file = true, surface = true } = {}) {
  if (!context) return "结果上下文未确认";
  return [
    file ? context.file_name : null,
    context.side?.replace("side", "Side "),
    context.view_mode === "single"
      ? "Single"
      : context.view_mode === "panel"
        ? "Panel"
        : null,
    surface
      ? context.surface_view?.replace(/^./, (x) => x.toUpperCase())
      : null,
    context.kind === "height_map" ? filterLabel(context.filter) : null,
  ]
    .filter(Boolean)
    .join(" · ");
}
const stable = (value) =>
  JSON.stringify(value, (_key, item) =>
    item && !Array.isArray(item) && typeof item === "object"
      ? Object.fromEntries(
          Object.keys(item)
            .sort()
            .map((key) => [key, item[key]]),
        )
      : item,
  );
function relevant(draft) {
  return {
    kind: draft.kind,
    side: draft.side,
    view_mode: draft.view_mode,
    surface_view: draft.surface_view,
    filter:
      draft.kind === "height_map"
        ? draft.filter?.kind === "custom"
          ? {
              kind: "custom",
              minimum_mm: Math.round(draft.filter.minimum_mm * 1000) / 1000,
              maximum_mm: Math.round(draft.filter.maximum_mm * 1000) / 1000,
            }
          : draft.filter
        : null,
  };
}
export function contextDraft(context) {
  return {
    kind:
      titles[context.kind] &&
      ["height_map", "pressure2d", "single_board_pressure"].includes(
        context.kind,
      )
        ? context.kind
        : "preview",
    side: context.side || "side1",
    view_mode: context.view_mode || "single",
    surface_view: context.surface_view || "full",
    filter: context.filter || { kind: "all" },
  };
}
export function createResultState() {
  let snapshot = { files: [], jobs: [], messages: [] },
    draft = structuredClone(defaults),
    selectedId = null,
    emptyAfterRemoval = false,
    seen = new Set(),
    selection = { pcb_ids: [], holder_id: null };
  return {
    reset() {
      snapshot = { files: [], jobs: [], messages: [] };
      draft = structuredClone(defaults);
      selectedId = null;
      emptyAfterRemoval = false;
      seen = new Set();
      selection = { pcb_ids: [], holder_id: null };
    },
    get snapshot() {
      return snapshot;
    },
    get draft() {
      return draft;
    },
    get selection() {
      return selection;
    },
    get result() {
      return (
        snapshot.jobs
          .flatMap((j) => j.presentations || [])
          .find((v) => v.id === selectedId) || null
      );
    },
    get job() {
      return (
        snapshot.jobs.find((j) =>
          (j.presentations || []).some((v) => v.id === selectedId),
        ) || null
      );
    },
    ingest(value, { deferJob = () => false } = {}) {
      if (
        value.server_id === snapshot.server_id &&
        (value.file_revision || 0) < (snapshot.file_revision || 0)
      )
        return false;
      const remainingIds = new Set((value.files || []).map((f) => f.id));
      const removed = new Set(
        snapshot.files.filter((f) => !remainingIds.has(f.id)).map((f) => f.id),
      );
      const lostDisplay =
        removed.size > 0 &&
        selectedId &&
        !value.jobs.some((j) =>
          (j.presentations || []).some((v) => v.id === selectedId),
        );
      if (removed.size) {
        selection.pcb_ids = selection.pcb_ids.filter((id) => !removed.has(id));
        if (removed.has(selection.holder_id)) selection.holder_id = null;
      }
      if (lostDisplay) {
        selectedId = null;
        emptyAfterRemoval = true;
      }
      snapshot = value;
      let newest = null;
      for (const job of value.jobs) {
        if (!seen.has(job.id) && (job.presentations || []).length) {
          seen.add(job.id);
          if (!deferJob(job)) newest = job.presentations[0];
        }
      }
      if (newest && !lostDisplay) {
        selectedId = newest.id;
        emptyAfterRemoval = false;
      }
      if (!this.result)
        selectedId = emptyAfterRemoval
          ? null
          : value.jobs
              .filter((j) => !deferJob(j))
              .flatMap((j) => j.presentations || [])
              .at(-1)?.id || null;
      return true;
    },
    select(id) {
      if (
        snapshot.jobs.some((j) =>
          (j.presentations || []).some((v) => v.id === id),
        )
      ) {
        selectedId = id;
        emptyAfterRemoval = false;
      }
    },
    setDraft(value) {
      draft = structuredClone(value);
    },
    setSelection(value) {
      selection = {
        pcb_ids: [...value.pcb_ids],
        holder_id: value.holder_id || null,
      };
    },
    dirty() {
      const view = this.result;
      if (!view) return false;
      const c = view.context;
      if (stable(relevant(draft)) !== stable(relevant(contextDraft(c))))
        return true;
      if (c.pcb_file_id && !selection.pcb_ids.includes(c.pcb_file_id))
        return true;
      if (
        (c.kind === "pressure2d" || c.kind.startsWith("holder_")) &&
        selection.holder_id !== c.holder_file_id
      )
        return true;
      const ids = [];
      const walk = (v) => {
        if (Array.isArray(v)) v.forEach(walk);
        else if (v && typeof v === "object") {
          if (v.pcb_file_id) ids.push(v.pcb_file_id);
          Object.values(v).forEach(walk);
        }
      };
      walk(this.job?.arguments);
      return (
        stable(
          [...new Set(ids)]
            .filter((id) => !this.job?.removed_file_ids?.includes(id))
            .sort(),
        ) !== stable([...selection.pcb_ids].sort())
      );
    },
    restore(saved) {
      if (saved?.session_id !== snapshot.session_id) return;
      if (saved.draft) this.setDraft(saved.draft);
      if (saved.result_id) this.select(saved.result_id);
      if (saved.empty_after_removal) {
        emptyAfterRemoval = true;
        selectedId = null;
      }
    },
    serialize() {
      return {
        session_id: snapshot.session_id,
        result_id: selectedId,
        draft,
        empty_after_removal: emptyAfterRemoval,
      };
    },
  };
}
export function buildRequest(draft, selection) {
  const { kind, side, view_mode, surface_view } = draft,
    ids = selection.pcb_ids,
    holder = selection.holder_id;
  if (!ids.length) {
    if (kind === "preview" && holder)
      return {
        tasks: [
          {
            task_id: "holder_preview",
            kind: "holder_preview",
            holder_file_id: holder,
          },
        ],
      };
    throw Error("请先选择 PCB 文件。");
  }
  if (kind === "pressure2d") {
    if (!holder) throw Error("请先选择 Holder。");
    return {
      holder_file_id: holder,
      analysis: {
        kind,
        pcbs: ids.map((id) => ({
          pcb_file_id: id,
          sides: [{ side, surface_views: [surface_view] }],
        })),
      },
    };
  }
  const filter = draft.filter;
  if (
    kind === "height_map" &&
    filter.kind === "custom" &&
    !(
      Number.isFinite(filter.minimum_mm) &&
      Number.isFinite(filter.maximum_mm) &&
      filter.minimum_mm >= 0 &&
      filter.maximum_mm > filter.minimum_mm
    )
  )
    throw Error("自定义范围需要 0 ≤ 最小值 < 最大值。");
  return {
    tasks: ids.map((id, i) => {
      const base = { task_id: `pcb_${i + 1}`, pcb_file_id: id };
      if (kind === "preview")
        return {
          ...base,
          kind: "pcb_preview",
          render_jobs: [{ view_mode, surface_view, sides: [side] }],
        };
      if (kind === "height_map")
        return {
          ...base,
          kind,
          jobs: [{ side, view_mode, surface_view, filter }],
        };
      return {
        ...base,
        kind,
        sides: [side],
        ...(surface_view === "full" ? {} : { surface_view }),
      };
    }),
  };
}
