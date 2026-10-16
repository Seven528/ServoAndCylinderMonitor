import test from "node:test";
import assert from "node:assert/strict";
import {
  canvasScope,
  selectedBatch,
  chatScopeRequest,
  supportsExplicitScope,
} from "../web/canvas-scope.js";

const files = ["A", "B", "C"].map((id) => ({
  id,
  name: id + ".uni",
  role: "pcb",
}));
test("visible second PCB outranks multi-selection and unexecuted draft", () => {
  const state = {
    snapshot: { files },
    selection: { pcb_ids: ["A", "B", "C"], holder_id: null },
    draft: { side: "side1" },
    result: {
      id: "view-B",
      context: {
        file_name: "B.uni",
        pcb_file_id: "B",
        side: "side2",
        view_mode: "panel",
        surface_view: "copper",
      },
    },
  };
  assert.deepEqual(canvasScope(state).request, { presentation_id: "view-B" });
  assert.match(canvasScope(state).label, /B.uni.*Side 2.*Panel.*Copper/);
  assert.equal(selectedBatch(state).length, 3);
});
test("no arbitrary first file when canvas is empty", () => {
  const state = {
    snapshot: { files },
    selection: { pcb_ids: ["A", "B"], holder_id: null },
    result: null,
  };
  assert.equal(canvasScope(state).request, null);
  state.selection.pcb_ids = ["B"];
  assert.equal(canvasScope(state).request, null);
});
test("pending or failed new image cannot authorize the wrong visible bitmap", () => {
  const state = { result: { id: "B", context: { file_name: "B.uni" } } };
  assert.equal(canvasScope(state, false).request, null);
});
test("natural target requests reach the host without granting checked files", () => {
  assert.deepEqual(
    chatScopeRequest({
      request: { presentation_id: "view-B" },
      batchFiles: files,
    }),
    { presentation_id: "view-B" },
  );
  assert.deepEqual(chatScopeRequest({ request: null, batchFiles: files }), {
    presentation_id: null,
  });
  assert.equal(supportsExplicitScope({ canvas_scope_version: 1 }), false);
  assert.equal(
    supportsExplicitScope({
      canvas_scope_version: 1,
      explicit_file_scope_version: 1,
    }),
    true,
  );
});
