import test from "node:test";
import assert from "node:assert/strict";
import { createDictationControl } from "../web/dictation-control.js";

function harness(t) {
  const prior = Object.fromEntries(
    ["window", "document", "MutationObserver"].map((k) => [k, globalThis[k]]),
  );
  const nodes = new Map();
  const node = (id) => {
    if (!nodes.has(id))
      nodes.set(id, {
        value: "",
        selectionStart: 0,
        selectionEnd: 0,
        readOnly: false,
        hidden: false,
        disabled: false,
        open: false,
        dataset: {},
        attributes: {},
        classList: { toggle() {} },
        textContent: "",
        title: "",
        setAttribute(key, value) {
          this.attributes[key] = value;
        },
        showModal() {
          this.open = true;
          this.modalCount = (this.modalCount || 0) + 1;
        },
        close() {
          this.open = false;
        },
        focus() {},
        setSelectionRange() {},
        dispatchEvent() {},
      });
    return nodes.get(id);
  };
  globalThis.window = { addEventListener() {} };
  globalThis.document = {
    getElementById: node,
    addEventListener() {},
    hidden: false,
  };
  globalThis.MutationObserver = class {
    observe() {}
    disconnect() {}
  };
  const calls = { starts: 0, stops: 0, aborts: 0 };
  class Recognition {
    static supported() {
      return true;
    }
    start() {
      calls.starts++;
      this.onstart?.();
    }
    stop() {
      calls.stops++;
      this.onend?.();
    }
    abort() {
      calls.aborts++;
    }
  }
  Object.defineProperty(Recognition.prototype, "processLocally", {
    value: false,
    writable: true,
  });
  const control = createDictationControl(() => {}, {
    NativeRecognition: Recognition,
  });
  t.after(() => {
    control.cancel();
    for (const [key, value] of Object.entries(prior)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  });
  return { node, calls, control };
}

test("ready native microphone click starts immediately without app modal", async (t) => {
  const { node, calls, control } = harness(t);
  control.configure({ available: true, model_ready: true });
  assert.equal(calls.starts, 0);
  await node("dictate").onclick();
  assert.equal(calls.starts, 1);
  assert.equal(node("dictation-dialog").modalCount || 0, 0);
  assert.equal(node("dictate").attributes["aria-pressed"], "true");
  await node("dictate").onclick();
  assert.equal(calls.stops, 1);
  assert.equal(control.active, false);
});

test("missing offline model opens setup without recording or downloading", async (t) => {
  const { node, calls, control } = harness(t);
  control.configure({ available: true, model_ready: false });
  await node("dictate").onclick();
  assert.equal(calls.starts, 0);
  assert.equal(node("dictation-dialog").modalCount, 1);
  assert.equal(node("dictation-start").disabled, true);
  assert.equal(node("dictation-install").hidden, false);
});
