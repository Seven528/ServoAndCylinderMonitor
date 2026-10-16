import test from "node:test";
import assert from "node:assert/strict";
import {
  createAutoPreview,
  previewSpec,
  cachedPreview,
  AUTO_PREVIEW_LABEL,
} from "../web/auto-preview.js";
import { defaults, createResultState } from "../web/result-state.js";
const spec = (side = "side1", surface = "full") =>
  previewSpec(
    { ...defaults, side, surface_view: surface },
    { pcb_ids: ["A"], holder_id: null },
  );
const ready = (id, wanted) => ({
  id,
  label: AUTO_PREVIEW_LABEL,
  status: "succeeded",
  presentations: wanted.map((context, i) => ({
    id: id + "/" + i,
    context,
    status: "succeeded",
    image_id: "png-" + id + i,
  })),
});
const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
};
function harness() {
  let timer = null;
  const calls = [],
    installs = [],
    errors = [];
  const auto = createAutoPreview({
    submit: async (args) => {
      calls.push(args);
      return { id: "j" + calls.length };
    },
    install: (job, cached, id) => installs.push({ job: job.id, cached, id }),
    onError: (e) => errors.push(e.message),
    schedule: (fn) => {
      timer = fn;
      return fn;
    },
    unschedule: (fn) => {
      if (timer === fn) timer = null;
    },
  });
  return {
    auto,
    calls,
    installs,
    errors,
    fire: async () => {
      const fn = timer;
      timer = null;
      fn?.();
      await flush();
    },
  };
}
test("rapid changes coalesce into one latest request", async () => {
  const h = harness();
  h.auto.request(spec());
  h.auto.request(spec("side2"));
  h.auto.request(spec("side2", "components"));
  assert.equal(h.calls.length, 0);
  await h.fire();
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].tasks[0].render_jobs[0].surface_view, "components");
});
test("obsolete completion is retained but never installed; only one successor runs", async () => {
  const h = harness();
  const a = spec(),
    b = spec("side2");
  h.auto.request(a);
  await h.fire();
  h.auto.observe({ active_job: "j1", jobs: [{ id: "j1", status: "running" }] });
  h.auto.request(b);
  await h.fire();
  assert.equal(h.calls.length, 1);
  h.auto.observe({ active_job: null, jobs: [ready("j1", a.wanted)] });
  await flush();
  assert.equal(h.installs.length, 0);
  assert.equal(h.calls.length, 2);
  h.auto.observe({
    active_job: null,
    jobs: [ready("j1", a.wanted), ready("j2", b.wanted)],
  });
  assert.deepEqual(
    h.installs.map((x) => x.job),
    ["j2"],
  );
});
test("waits for an unrelated analysis without cancelling or adding parallel requests", async () => {
  const h = harness();
  h.auto.observe({
    active_job: "analysis",
    jobs: [{ id: "analysis", status: "running" }],
  });
  h.auto.request(spec());
  await h.fire();
  h.auto.request(spec("side2"));
  await h.fire();
  assert.equal(h.calls.length, 0);
  h.auto.observe({ active_job: null, jobs: [] });
  await flush();
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.calls[0].tasks[0].render_jobs[0].sides, ["side2"]);
});
test("reuses matching delivered image even inside a multi-surface job", async () => {
  const h = harness(),
    a = spec(),
    b = spec("side2");
  const job = ready("existing", [...a.wanted, ...b.wanted]);
  h.auto.observe({ active_job: null, jobs: [job] });
  h.auto.request(b);
  await h.fire();
  assert.equal(h.calls.length, 0);
  assert.deepEqual(h.installs, [
    { job: "existing", cached: true, id: "existing/1" },
  ]);
  h.auto.observe({ active_job: null, jobs: [job] });
  assert.equal(h.installs.length, 1);
  assert.equal(
    cachedPreview({ jobs: [{ ...job, status: "failed" }] }, b),
    null,
  );
});
test("failure is not repeatedly retried by polling; explicit retry runs once", async () => {
  const h = harness();
  h.auto.request(spec());
  await h.fire();
  const snapshot = {
    active_job: null,
    jobs: [{ id: "j1", status: "failed", stage: "cannot render" }],
  };
  h.auto.observe(snapshot);
  h.auto.observe(snapshot);
  await flush();
  assert.equal(h.calls.length, 1);
  assert.equal(h.errors.length, 1);
  assert.equal(h.auto.error, true);
  h.auto.retry();
  await h.fire();
  assert.equal(h.calls.length, 2);
});
test("leaving preview or selecting history prevents a late install", async () => {
  const h = harness(),
    a = spec();
  h.auto.request(a);
  await h.fire();
  h.auto.pause();
  h.auto.observe({ active_job: null, jobs: [ready("j1", a.wanted)] });
  assert.equal(h.installs.length, 0);
  assert.equal(h.auto.pending, false);
  assert.equal(
    previewSpec({ ...defaults, kind: "height_map" }, { pcb_ids: ["A"] }),
    null,
  );
});
test("state does not install deferred auto results over a previous picture", () => {
  const s = createResultState();
  const old = ready("old", spec().wanted),
    stale = ready("stale", spec("side2").wanted);
  old.label = "Manual";
  s.ingest({ files: [], jobs: [old] });
  s.ingest(
    { files: [], jobs: [old, stale] },
    { deferJob: (j) => j.label === AUTO_PREVIEW_LABEL },
  );
  assert.equal(s.result.id, "old/0");
  s.select("stale/0");
  assert.equal(s.result.id, "stale/0");
});
test("Holder preview identity ignores controls that are not supported for Holder", () => {
  const a = previewSpec(defaults, { pcb_ids: [], holder_id: "H" }),
    b = previewSpec(
      { ...defaults, side: "side2", surface_view: "copper" },
      { pcb_ids: [], holder_id: "H" },
    );
  assert.equal(a.key, b.key);
  assert.equal(previewSpec(defaults, { pcb_ids: [], holder_id: null }), null);
});
