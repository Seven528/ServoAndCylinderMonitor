import test from "node:test";
import assert from "node:assert/strict";
import { createTransport, TransportError } from "../web/transport.js";
import { createImageLoader } from "../web/image-loader.js";
import { createConnectionRecovery } from "../web/connection-recovery.js";
import { createResultState } from "../web/result-state.js";
import { createAutoPreview } from "../web/auto-preview.js";

const json = (value, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const png = () =>
  new Response(new Uint8Array([1, 2, 3]), {
    headers: { "Content-Type": "image/png", "Content-Length": "3" },
  });
const artifact = {
  id: "a",
  url: "/api/artifacts/a",
  mime_type: "image/png",
  byte_count: 3,
  server_id: "one",
};
const settle = async () => {
  for (let i = 0; i < 12; i++) await Promise.resolve();
};

test("JSON and PNG use the header, omit cookies; concurrent handshakes coalesce", async () => {
  let health = 0;
  const seen = [];
  const client = createTransport({
    fetcher: async (path, options) => {
      seen.push([path, options]);
      if (path === "/api/health") {
        health++;
        return json({ token: "token", server_id: "one" });
      }
      return path.includes("artifacts") ? png() : json({ server_id: "one" });
    },
  });
  await Promise.all([client.connect(), client.connect()]);
  await client.api("state");
  assert.equal((await client.artifactBlob(artifact)).size, 3);
  assert.equal(health, 1);
  for (const [path, opts] of seen) {
    assert.equal(opts.credentials, "omit");
    if (path !== "/api/health")
      assert.equal(opts.headers["X-Demo-Token"], "token");
  }
});
test("403 refreshes credentials and retries a read exactly once", async () => {
  let health = 0,
    reads = 0;
  const client = createTransport({
    fetcher: async (path, options) => {
      if (path === "/api/health")
        return json({ token: "t" + ++health, server_id: "one" });
      reads++;
      if (reads === 1)
        return json({ error: "denied", code: "authentication_required" }, 403);
      assert.equal(options.headers["X-Demo-Token"], "t2");
      return png();
    },
  });
  await client.connect();
  await client.artifactBlob(artifact);
  assert.equal(health, 2);
  assert.equal(reads, 2);
});
test("a denied analysis POST is never automatically replayed", async () => {
  let posts = 0;
  const client = createTransport({
    fetcher: async (path) =>
      path === "/api/health"
        ? json({ token: "t", server_id: "one" })
        : (posts++,
          json({ error: "denied", code: "authentication_required" }, 403)),
  });
  await assert.rejects(
    client.api("analysis", { arguments: {} }),
    (e) => e.code === "authentication_renewed",
  );
  assert.equal(posts, 1);
});
test("new server identity rejects old artifacts even when their URL could be reused", async () => {
  let health = 0,
    reads = 0;
  const client = createTransport({
    fetcher: async (path) => {
      if (path === "/api/health")
        return json({ token: "t", server_id: ++health === 1 ? "one" : "two" });
      reads++;
      return json({ error: "denied", code: "authentication_required" }, 403);
    },
  });
  await client.connect();
  await assert.rejects(
    client.artifactBlob(artifact),
    (e) => e.code === "session_changed",
  );
  assert.equal(reads, 1);
  await assert.rejects(
    client.artifactBlob(artifact),
    (e) => e.code === "session_changed",
  );
  assert.equal(reads, 1);
});
test("MIME, length and byte budgets are validated before an image is published", async () => {
  for (const [response, code] of [
    [
      () => new Response("html", { headers: { "Content-Type": "text/html" } }),
      "artifact_mime",
    ],
    [
      () =>
        new Response("x", {
          headers: {
            "Content-Type": "image/png",
            "Content-Length": String(17 * 1024 * 1024),
          },
        }),
      "artifact_size",
    ],
    [
      () => new Response("x", { headers: { "Content-Type": "image/png" } }),
      "artifact_incomplete",
    ],
  ]) {
    const client = createTransport({
      fetcher: async (path) =>
        path === "/api/health"
          ? json({ token: "t", server_id: "one" })
          : response(),
    });
    await client.connect();
    await assert.rejects(client.artifactBlob(artifact), (e) => e.code === code);
  }
});
function loaderHarness(fetchBlob, decode = async () => {}) {
  const states = [],
    ready = [],
    released = [],
    timers = new Map();
  let sequence = 0;
  const loader = createImageLoader({
    fetchBlob,
    decode,
    createURL: () => `blob:${++sequence}`,
    revokeURL: (url) => released.push(url),
    onState: (s) => states.push(s.phase),
    onReady: (url, a) => ready.push([url, a.id]),
    schedule: (fn) => {
      const id = Symbol();
      timers.set(id, fn);
      return id;
    },
    unschedule: (id) => timers.delete(id),
  });
  return {
    loader,
    states,
    ready,
    released,
    timers,
    fire: async () => {
      const tasks = [...timers.values()];
      timers.clear();
      for (const fn of tasks) fn();
      await settle();
    },
  };
}
test("one failed PNG read recovers automatically without another analysis", async () => {
  let reads = 0;
  const h = loaderHarness(async () => {
    if (++reads === 1)
      throw new TransportError("temporary", { retryable: true });
    return new Blob(["png"]);
  });
  h.loader.show(artifact);
  await settle();
  assert.equal(h.loader.phase, "retrying");
  await h.fire();
  assert.equal(h.loader.phase, "ready");
  assert.equal(reads, 2);
  assert.equal(h.ready.length, 1);
  h.loader.dispose();
  assert.deepEqual(h.released, ["blob:1"]);
});
test("retry budget is finite, same-URL manual retry works, no retry loop on show()", async () => {
  let healthy = false,
    reads = 0;
  const h = loaderHarness(async () => {
    reads++;
    if (!healthy) throw new TransportError("network", { retryable: true });
    return new Blob(["png"]);
  });
  h.loader.show(artifact);
  await settle();
  await h.fire();
  await h.fire();
  assert.equal(reads, 3);
  assert.equal(h.loader.phase, "error");
  h.loader.show(artifact);
  await settle();
  assert.equal(reads, 3);
  healthy = true;
  h.loader.retry();
  await settle();
  assert.equal(reads, 4);
  assert.equal(h.loader.phase, "ready");
  h.loader.dispose();
});
test("superseded decode cannot install and every object URL is revoked once", async () => {
  let firstResolve;
  const first = new Promise((resolve) => {
    firstResolve = resolve;
  });
  const h = loaderHarness(
    async () => new Blob(["png"]),
    (url) => (url === "blob:1" ? first : Promise.resolve()),
  );
  h.loader.show(artifact);
  await settle();
  h.loader.show({ ...artifact, id: "b", url: "/api/artifacts/b" });
  await settle();
  assert.deepEqual(h.ready, [["blob:2", "b"]]);
  firstResolve();
  await settle();
  assert.deepEqual(h.ready, [["blob:2", "b"]]);
  h.loader.dispose();
  assert.deepEqual(h.released, ["blob:1", "blob:2"]);
});
test("same successful image is reused; replacement keeps previous until decode succeeds", async () => {
  let reads = 0,
    resolve;
  const h = loaderHarness(
    async () => {
      reads++;
      return new Blob(["png"]);
    },
    (url) =>
      url === "blob:2"
        ? new Promise((r) => {
            resolve = r;
          })
        : Promise.resolve(),
  );
  h.loader.show(artifact);
  await settle();
  h.loader.show(artifact);
  await settle();
  assert.equal(reads, 1);
  h.loader.show({ ...artifact, id: "b", url: "/api/artifacts/b" });
  await settle();
  assert.equal(h.loader.url, "blob:1");
  assert.deepEqual(h.released, []);
  resolve();
  await settle();
  assert.equal(h.loader.url, "blob:2");
  assert.deepEqual(h.released, ["blob:1"]);
  h.loader.dispose();
});
test("poll recovery uses capped backoff and can recover without a reload", () => {
  let time = 0;
  const c = createConnectionRecovery({ now: () => time });
  for (const seconds of [1, 2, 4, 8, 10, 10]) {
    assert.equal(c.failure(), seconds);
    assert.equal(c.ready, false);
    time += seconds * 1000;
    assert.equal(c.ready, true);
  }
  c.success();
  assert.equal(c.recovering, false);
  assert.equal(c.failure(), 1);
  c.retryNow();
  assert.equal(c.ready, true);
});
test("session reset discards stale references and does not replay a late submitted job", async () => {
  const state = createResultState();
  state.ingest({
    files: [],
    jobs: [{ id: "j", presentations: [{ id: "v" }] }],
  });
  state.reset();
  assert.equal(state.result, null);
  assert.deepEqual(state.snapshot.jobs, []);
  let resolve,
    installed = 0;
  const a = createAutoPreview({
    submit: () =>
      new Promise((r) => {
        resolve = r;
      }),
    install: () => installed++,
    onError: () => {},
    schedule: (fn) => {
      queueMicrotask(fn);
      return 1;
    },
    unschedule: () => {},
  });
  a.request({ key: "x", wanted: [{ kind: "pcb_preview" }], arguments: {} });
  await settle();
  a.reset();
  resolve({ id: "old" });
  await settle();
  a.observe({
    active_job: null,
    jobs: [{ id: "old", status: "succeeded", presentations: [{ id: "v" }] }],
  });
  assert.equal(installed, 0);
  assert.equal(a.active, false);
});
