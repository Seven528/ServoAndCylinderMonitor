import test from "node:test";
import assert from "node:assert/strict";
import {
  createResultState,
  defaults,
  buildRequest,
  contextLabel,
} from "../web/result-state.js";
const view = (id, board = "A", mode = "single", surface = "full") => ({
  id,
  job_id: "j",
  unit_id: board,
  report_id: "report-" + board,
  context: {
    kind: "height_map",
    pcb_file_id: board,
    file_name: board + ".uni",
    side: "side1",
    view_mode: mode,
    surface_view: surface,
    filter: { kind: "above_2_0_mm" },
  },
  statistics: {
    component_count: mode === "single" ? 652 : 2608,
    matching_count: mode === "single" ? 10 : 40,
  },
});
test("single-board requests carry selected surface without changing default Full", () => {
  const selection = { pcb_ids: ["A"], holder_id: null };
  const draft = {
    ...defaults,
    kind: "single_board_pressure",
    side: "side2",
    surface_view: "copper",
  };
  assert.deepEqual(buildRequest(draft, selection).tasks[0], {
    task_id: "pcb_1",
    pcb_file_id: "A",
    kind: "single_board_pressure",
    sides: ["side2"],
    surface_view: "copper",
  });
  assert.equal(
    buildRequest({ ...draft, surface_view: "full" }, selection).tasks[0]
      .surface_view,
    undefined,
  );
});
test("draft edits never relabel the displayed result", () => {
  const s = createResultState();
  s.ingest({
    session_id: "one",
    files: [],
    jobs: [
      {
        id: "j",
        arguments: { pcb_file_id: "A" },
        presentations: [view("one")],
      },
    ],
  });
  s.setSelection({ pcb_ids: ["A"] });
  s.setDraft({
    ...defaults,
    kind: "height_map",
    filter: { kind: "above_2_0_mm" },
  });
  assert.equal(s.dirty(), false);
  s.setDraft({ ...s.draft, view_mode: "panel" });
  assert.equal(s.dirty(), true);
  assert.equal(s.result.statistics.matching_count, 10);
  assert.equal(s.result.context.view_mode, "single");
});
test("selecting a surface or PCB switches the complete result tuple", () => {
  const s = createResultState();
  s.ingest({
    session_id: "one",
    files: [],
    jobs: [
      {
        id: "j",
        presentations: [
          view("a"),
          view("b", "B", "panel"),
          view("c", "B", "panel", "components"),
        ],
      },
    ],
  });
  s.select("b");
  assert.equal(s.result.statistics.matching_count, 40);
  assert.equal(s.result.report_id, "report-B");
  s.select("c");
  assert.equal(s.result.report_id, "report-B");
  assert.equal(s.result.context.surface_view, "components");
  s.ingest(s.snapshot);
  assert.equal(s.result.id, "c");
});
test("restore is session-scoped and preserves a pending draft", () => {
  const s = createResultState();
  const snapshot = {
    session_id: "one",
    files: [],
    jobs: [{ id: "j", presentations: [view("a"), view("b", "B", "panel")] }],
  };
  s.ingest(snapshot);
  s.select("b");
  s.setDraft({ ...defaults, side: "side2" });
  const saved = s.serialize();
  const other = createResultState();
  other.ingest(snapshot);
  other.restore(saved);
  assert.equal(other.result.id, "b");
  assert.equal(other.draft.side, "side2");
  other.restore({ ...saved, session_id: "two", draft: { kind: "invalid" } });
  assert.equal(other.draft.side, "side2");
});
test("new pending jobs do not erase the previous result", () => {
  const s = createResultState();
  s.ingest({ files: [], jobs: [{ id: "j", presentations: [view("a")] }] });
  s.ingest({
    files: [],
    jobs: [
      ...s.snapshot.jobs,
      { id: "pending", status: "running", presentations: [] },
    ],
  });
  assert.equal(s.result.id, "a");
});
test("controls build the same explicit native contracts without execution", () => {
  const request = buildRequest(
    { ...defaults, kind: "height_map", filter: { kind: "above_2_0_mm" } },
    { pcb_ids: ["A", "B"] },
  );
  assert.equal(request.tasks.length, 2);
  assert.equal(request.tasks[1].pcb_file_id, "B");
  assert.equal(request.tasks[0].jobs[0].filter.kind, "above_2_0_mm");
  assert.throws(() =>
    buildRequest(
      {
        ...defaults,
        kind: "height_map",
        filter: { kind: "custom", minimum_mm: 3, maximum_mm: 2 },
      },
      { pcb_ids: ["A"] },
    ),
  );
  assert.match(contextLabel(view("a").context), /Single/);
});
test("custom filter identity follows native micrometre normalization and ignores property order", () => {
  const s = createResultState(),
    v = view("a");
  v.context.filter = { kind: "custom", maximum_mm: 4.75, minimum_mm: 2.25 };
  s.ingest({
    files: [],
    jobs: [{ id: "j", arguments: { pcb_file_id: "A" }, presentations: [v] }],
  });
  s.setSelection({ pcb_ids: ["A"] });
  s.setDraft({
    ...defaults,
    kind: "height_map",
    filter: { kind: "custom", minimum_mm: 2.2501, maximum_mm: 4.7501 },
  });
  assert.equal(s.dirty(), false);
});

test("removing the displayed source leaves a persistent blank canvas, not another source", () => {
  const state = createResultState();
  const initial = {
    server_id: "s",
    session_id: "s",
    file_revision: 0,
    files: [{ id: "A" }, { id: "B" }],
    jobs: [
      {
        id: "j",
        arguments: { file_ids: ["A", "B"] },
        presentations: [view("a"), view("b", "B")],
      },
    ],
  };
  state.ingest(initial);
  state.setSelection({ pcb_ids: ["A", "B"], holder_id: null });
  const removed = {
    ...initial,
    file_revision: 1,
    files: [{ id: "B" }],
    jobs: [
      {
        ...initial.jobs[0],
        removed_file_ids: ["A"],
        presentations: [view("b", "B")],
      },
    ],
  };
  state.ingest(removed);
  assert.equal(state.result, null);
  assert.deepEqual(state.selection.pcb_ids, ["B"]);
  state.ingest(removed);
  assert.equal(state.result, null);
  state.select("a");
  assert.equal(state.result, null);
  const reopened = createResultState();
  reopened.ingest(removed);
  reopened.restore(state.serialize());
  assert.equal(reopened.result, null);
  reopened.select("b");
  assert.equal(reopened.result.id, "b");
});

test("old polling snapshots cannot resurrect a removed file or its image", () => {
  const state = createResultState();
  const initial = {
    server_id: "s",
    file_revision: 0,
    files: [{ id: "A" }],
    jobs: [{ id: "j", presentations: [view("a")] }],
  };
  state.ingest(initial);
  state.ingest({ server_id: "s", file_revision: 1, files: [], jobs: [] });
  assert.equal(state.ingest(initial), false);
  assert.equal(state.result, null);
  assert.equal(state.snapshot.files.length, 0);
});

test("removing a different batch PCB preserves the current result and its parameter identity", () => {
  const state = createResultState();
  const initial = {
    server_id: "s",
    file_revision: 0,
    files: [{ id: "A" }, { id: "B" }],
    jobs: [
      {
        id: "j",
        arguments: { tasks: [{ pcb_file_id: "A" }, { pcb_file_id: "B" }] },
        presentations: [view("a"), view("b", "B")],
      },
    ],
  };
  state.ingest(initial);
  state.select("b");
  state.setSelection({ pcb_ids: ["A", "B"], holder_id: null });
  state.setDraft({
    ...defaults,
    kind: "height_map",
    filter: { kind: "above_2_0_mm" },
  });
  state.ingest({
    ...initial,
    file_revision: 1,
    files: [{ id: "B" }],
    jobs: [
      {
        ...initial.jobs[0],
        removed_file_ids: ["A"],
        presentations: [view("b", "B")],
      },
    ],
  });
  assert.equal(state.result.id, "b");
  assert.equal(state.dirty(), false);
});
