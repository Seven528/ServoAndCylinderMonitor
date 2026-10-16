import test from "node:test";
import assert from "node:assert/strict";
import { createDictation } from "../web/dictation.js";
function setup({ maximum = 8000 } = {}) {
  const speech = [],
    text = [],
    state = [],
    timers = new Map();
  let id = 0;
  class Recognition {
    constructor() {
      speech.push(this);
      this.stops = 0;
      this.aborts = 0;
    }
    start() {
      this.onstart?.();
    }
    stop() {
      this.stops++;
    }
    abort() {
      this.aborts++;
    }
  }
  Recognition.prototype.processLocally = false;
  const controller = createDictation({
    Recognition,
    maximum,
    onText: (t) => text.push(t),
    onState: (s) => state.push(s),
    schedule: (fn, ms) => {
      timers.set(++id, { fn, ms });
      return id;
    },
    cancelTimer: (t) => timers.delete(t),
  });
  return { controller, speech, text, state, timers };
}
const result = (text, final = true) => ({
  0: { transcript: text },
  isFinal: final,
});
test("recognition starts only explicitly and interim text is never inserted", () => {
  const s = setup();
  assert.equal(s.speech.length, 0);
  s.controller.start();
  const r = s.speech[0];
  assert.equal(r.lang, "zh-CN");
  assert.equal(r.processLocally, true);
  r.onresult({ results: [result("测试", false)] });
  assert.deepEqual(s.text, []);
  r.onresult({ results: [result("测试")] });
  r.onresult({ results: [result("测试")] });
  assert.deepEqual(s.text, ["测试"]);
  s.controller.cancel();
});
test("cancelled recognition cannot append late results or keep timers", () => {
  const s = setup();
  s.controller.start();
  const old = s.speech[0].onresult;
  s.controller.cancel();
  s.controller.start();
  old({ results: [result("late")] });
  assert.deepEqual(s.text, []);
  s.controller.cancel();
  assert.equal(s.timers.size, 0);
});
test("60 second cap stops and bounded drain aborts unresponsive recognition", () => {
  const s = setup();
  s.controller.start();
  [...s.timers.values()].find((t) => t.ms === 60000).fn();
  assert.equal(s.speech[0].stops, 1);
  [...s.timers.values()].find((t) => t.ms === 3000).fn();
  assert.equal(s.controller.active, false);
  assert.equal(s.speech[0].aborts, 1);
  assert.equal(s.timers.size, 0);
});
test("permissions failure is explicit and releases the recognizer", () => {
  const s = setup();
  s.controller.start();
  s.speech[0].onerror({ error: "not-allowed" });
  assert.equal(s.controller.active, false);
  assert.match(s.state.at(-1).message, /授权/);
  assert.equal(s.timers.size, 0);
});
test("dictated text is bounded and is never sent to a chat transport", () => {
  const s = setup({ maximum: 4 });
  s.controller.start();
  s.speech[0].onresult({ results: [result("1234567")] });
  assert.deepEqual(s.text, ["1234"]);
  assert.equal(s.speech[0].stops, 1);
  s.controller.cancel();
});
test("unsupported browsers cannot fall back to remote recognition", () => {
  const states = [];
  const s = createDictation({
    onText: () => assert.fail("unexpected text"),
    onState: (v) => states.push(v),
  });
  assert.equal(s.supported, false);
  assert.equal(s.start(), false);
  assert.match(states[0].message, /禁止在线/);
});
