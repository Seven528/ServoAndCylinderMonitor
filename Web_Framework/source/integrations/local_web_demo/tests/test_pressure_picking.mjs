import test from "node:test";
import assert from "node:assert/strict";
import {
  createPressureSelection,
  pressureHit,
  pressurePickingEligible,
  contactSections,
  componentPanOffset,
  validComponentHighlight,
} from "../web/pressure-picking.js";
import { createTransport } from "../web/transport.js";

const view = (id = "v") => ({
  id,
  image_id: "image-" + id,
  report_id: "report-" + id,
  status: "succeeded",
  picking_available: true,
  context: {
    kind: "pressure2d",
    side: "side2",
    view_mode: "panel",
    surface_view: "components",
  },
});
const draft = { ...view().context };
const binding = (v) => ({
  ok: true,
  presentation_id: v.id,
  image_id: v.image_id,
  report_id: v.report_id,
});
const map = (v = view()) => ({
  ...binding(v),
  width_px: 1000,
  height_px: 500,
  targets: [200, 300].map((x, i) => ({
    head_index: i,
    pressure_head_id: "same-id",
    refdes: "NDH1",
    x_px: x,
    y_px: 100,
    rx_px: 10,
    ry_px: 10,
  })),
});
const detail = (v, i) => ({
  ...binding(v),
  head_index: i,
  head: { pressure_head_id: "same-id", placement_index: i },
  contacts: [],
});
const tick = () => new Promise(setImmediate);
const deferred = () => {
  let resolve;
  const promise = new Promise((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

test("non-component contacts never become interference components and pages stay explicit", () => {
  const value = {
    offset: 0,
    next_offset: null,
    contacts: [
      { role: "through_hole", owner_name: "via1" },
      { role: "debug_context", owner_name: "C9003" },
      {
        role: "component_body",
        owner_name: "C5405",
        component_id: "instance/0",
      },
      {
        role: "component_body",
        owner_name: "C5405",
        component_id: "instance/1",
      },
    ],
  };
  const sections = contactSections(value);
  assert.equal(sections.total, 2);
  assert.deepEqual(
    sections.components.map((c) => c.component_id),
    ["instance/0", "instance/1"],
  );
  assert.equal(sections.others.length, 2);
  assert.equal(
    contactSections({
      ...value,
      contacts: value.contacts.slice(0, 2),
      next_offset: 50,
    }).total,
    null,
  );
  assert.equal(
    contactSections({ ...value, contact_components_total: 7 }).total,
    7,
  );
});

test("component rows deduplicate only exact native identity", () => {
  const c = {
    role: "component_body",
    owner_name: "C1",
    component_id: "placement/0",
  };
  const sections = contactSections({
    offset: 0,
    next_offset: null,
    contacts: [c, { ...c }, { ...c, component_id: "placement/1" }],
  });
  assert.equal(sections.components.length, 2);
  assert.equal(sections.total, 2);
});

const component = (id, x) => ({
  component_id: id,
  role: "component_body",
  owner_name: "C5405",
  package: "PKG",
  highlight: {
    component_id: id,
    x_px: x,
    y_px: 100,
    width_px: 20,
    height_px: 10,
  },
});

test("component selection is local and bound to the active head, not refdes", async () => {
  let reads = 0;
  const a = component("placement/0", 200),
    b = component("placement/1", 700);
  const c = createPressureSelection({
    loadMap: async (v) => map(v),
    loadHead: async (v, i) => {
      reads++;
      return { ...detail(v, i), contacts: [a], nearest_components: [b] };
    },
  });
  c.configure(view(), draft, true);
  await tick();
  c.select(0);
  await tick();
  const oldDetail = c.state.detail;
  assert.equal(c.selectComponent(a.component_id, oldDetail), true);
  assert.equal(c.state.component.highlight.x_px, 200);
  assert.equal(c.selectComponent(b.component_id, oldDetail), true);
  assert.equal(c.state.component.highlight.x_px, 700);
  assert.equal(c.selectComponent("foreign"), false);
  assert.equal(reads, 1);
  c.select(1);
  await tick();
  assert.equal(c.state.component, null);
  assert.equal(c.selectComponent(a.component_id, oldDetail), false);
  c.selectComponent(a.component_id);
  c.configure(view(), { ...draft, surface_view: "full" }, true);
  assert.equal(c.state.component, null);
  assert.equal(c.selectComponent(a.component_id), false);
});

test("missing, foreign, malformed or out-of-image bounds cannot be highlighted", () => {
  const c = component("placement/0", 200);
  assert.equal(validComponentHighlight(c, map()), true);
  for (const highlight of [
    null,
    { ...c.highlight, component_id: "foreign" },
    { ...c.highlight, x_px: -1 },
    { ...c.highlight, width_px: 0 },
    { ...c.highlight, x_px: 999 },
  ])
    assert.equal(validComponentHighlight({ ...c, highlight }, map()), false);
});

test("off-screen components pan into view without changing zoom or visible components", () => {
  const m = map(),
    h = component("id", 200).highlight;
  const viewport = { left: 0, top: 0, width: 500, height: 300 };
  assert.deepEqual(
    componentPanOffset(
      h,
      m,
      { left: 0, top: 0, width: 1000, height: 500 },
      viewport,
    ),
    { x: 0, y: 0 },
  );
  assert.deepEqual(
    componentPanOffset(
      h,
      m,
      { left: -400, top: -300, width: 1000, height: 500 },
      viewport,
    ),
    { x: 440, y: 345 },
  );
});

test("picking requires actual and draft Pressure2D/Components/Panel/same-side", () => {
  assert.equal(pressurePickingEligible(view(), draft), true);
  for (const kind of [
    "preview",
    "pcb_preview",
    "height_map",
    "single_board_pressure",
  ]) {
    assert.equal(pressurePickingEligible(view(), { ...draft, kind }), false);
    assert.equal(
      pressurePickingEligible(
        { ...view(), context: { ...draft, kind } },
        draft,
      ),
      false,
    );
  }
  for (const surface_view of ["full", "copper", "drawings", "mechanical"]) {
    assert.equal(
      pressurePickingEligible(view(), { ...draft, surface_view }),
      false,
    );
    assert.equal(
      pressurePickingEligible(
        { ...view(), context: { ...draft, surface_view } },
        draft,
      ),
      false,
    );
  }
  assert.equal(
    pressurePickingEligible(view(), { ...draft, side: "side1" }),
    false,
  );
  assert.equal(
    pressurePickingEligible({ ...view(), status: "failed" }, draft),
    false,
  );
  assert.equal(pressurePickingEligible(null, draft), false);
});

test("native image pixels map correctly under fit, zoom, pan and unequal rounding scales", () => {
  for (const rect of [
    { left: 100, top: 20, width: 500, height: 250 },
    { left: -800, top: -50, width: 2400, height: 1201 },
    { left: 30, top: 70, width: 100, height: 50 },
  ]) {
    for (const target of map().targets) {
      const x = rect.left + (target.x_px * rect.width) / 1000;
      const y = rect.top + (target.y_px * rect.height) / 500;
      assert.equal(
        pressureHit(map(), rect, x, y).head_index,
        target.head_index,
      );
    }
    assert.equal(pressureHit(map(), rect, rect.left - 1, rect.top), null);
    assert.equal(
      pressureHit(map(), rect, rect.left + rect.width, rect.top + rect.height),
      null,
    );
  }
});

test("unready images, stale reports and unsupported backends never request a map", async () => {
  let calls = 0;
  const c = createPressureSelection({
    loadMap: () => {
      calls++;
    },
    loadHead() {},
  });
  c.configure(view(), draft, false, true);
  c.configure({ ...view(), picking_available: false }, draft, true, true);
  assert.equal(c.state.phase, "unavailable");
  c.configure(view(), draft, true, false);
  await tick();
  assert.equal(calls, 0);
});

test("same-refdes placements use exact row identity and background click closes details", async () => {
  const calls = [];
  const c = createPressureSelection({
    loadMap: async (v) => map(v),
    loadHead: async (v, index, offset) => {
      calls.push([index, offset]);
      return detail(v, index);
    },
  });
  c.configure(view(), draft, true);
  await tick();
  c.select(1);
  await tick();
  assert.equal(c.state.detail.head.placement_index, 1);
  c.select(0, 50);
  await tick();
  assert.deepEqual(calls, [
    [1, 0],
    [0, 50],
  ]);
  c.click(900, 400, { left: 0, top: 0, width: 1000, height: 500 });
  assert.equal(c.state.target, null);
  assert.equal(c.state.detail, null);
});

test("changing view aborts its map and ignores a late response", async () => {
  const first = deferred(),
    requests = [];
  const c = createPressureSelection({
    loadMap: (v, signal) => {
      requests.push({ id: v.id, signal });
      return v.id === "old" ? first.promise : Promise.resolve(map(v));
    },
    loadHead() {},
  });
  c.configure(view("old"), draft, true);
  await tick();
  c.configure(view("new"), draft, true);
  await tick();
  assert.equal(requests[0].signal.aborted, true);
  first.resolve(map(view("old")));
  await tick();
  assert.equal(c.state.map.presentation_id, "new");
  c.dispose();
  assert.equal(requests[1].signal.aborted, true);
  assert.equal(c.state.map, null);
});

test("late head reads cannot replace a newer head or survive a mode change", async () => {
  const reads = [],
    pending = [deferred(), deferred()];
  const c = createPressureSelection({
    loadMap: async (v) => map(v),
    loadHead: (v, i, _offset, signal) => {
      reads.push(signal);
      return pending[i].promise;
    },
  });
  c.configure(view(), draft, true);
  await tick();
  c.select(0);
  await tick();
  c.select(1);
  await tick();
  assert.equal(reads[0].aborted, true);
  pending[1].resolve(detail(view(), 1));
  await tick();
  pending[0].resolve(detail(view(), 0));
  await tick();
  assert.equal(c.state.detail.head_index, 1);
  c.configure(view(), { ...draft, surface_view: "full" }, true);
  assert.equal(reads[1].aborted, true);
  assert.equal(c.state.target, null);
  assert.equal(c.state.phase, "idle");
});

test("invalid bindings and oversized maps fail closed without retry loops", async () => {
  let calls = 0;
  const v = view();
  const c = createPressureSelection({
    loadMap: async () => {
      calls++;
      return { ...map(), image_id: "foreign" };
    },
    loadHead() {},
  });
  c.configure(v, draft, true);
  await tick();
  assert.equal(c.state.phase, "error");
  c.configure(v, draft, true);
  await tick();
  assert.equal(calls, 1);
  c.retry();
  c.configure(v, draft, true);
  await tick();
  assert.equal(calls, 2);
  const large = createPressureSelection({
    loadMap: async () => ({
      ...map(),
      targets: Array(4097).fill(map().targets[0]),
    }),
    loadHead() {},
  });
  large.configure(v, draft, true);
  await tick();
  assert.equal(large.state.phase, "error");
});

test("disposing before queued calls start aborts the correct request signals", async () => {
  let signal;
  const c = createPressureSelection({
    loadMap: async (_v, s) => {
      signal = s;
      return map();
    },
    loadHead() {},
  });
  c.configure(view(), draft, true);
  c.dispose();
  await tick();
  assert.equal(signal.aborted, true);
  assert.equal(c.state.phase, "idle");
});

test("GET detail reads receive and clean up caller cancellation", async () => {
  let requestSignal;
  const client = createTransport({
    fetcher: async (url, options) => {
      if (url === "/api/health")
        return new Response(JSON.stringify({ token: "test", server_id: "s" }));
      requestSignal = options.signal;
      return new Promise((_resolve, reject) =>
        options.signal.addEventListener(
          "abort",
          () => reject(new DOMException("Cancelled", "AbortError")),
          { once: true },
        ),
      );
    },
  });
  await client.connect();
  const abort = new AbortController();
  const pending = client.api("pressure-picking?presentation_id=v", undefined, {
    signal: abort.signal,
  });
  await tick();
  abort.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(requestSignal.aborted, true);
});
