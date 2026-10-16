import test from "node:test";
import assert from "node:assert/strict";
import { createLayoutState } from "../web/layout-state.js";

test("assistant defaults docked on wide entry and avoids a modal on narrow entry", () => {
  for (const width of [520, 1024, 1280, 1440, 1920]) {
    const state = createLayoutState({}, width);
    assert.equal(state.project(width).files, "closed");
    assert.equal(
      state.project(width).chat,
      width >= 1280 ? "docked" : "closed",
    );
  }
});
test("an explicit assistant close is remembered after the new default", () => {
  const state = createLayoutState();
  state.close("chat");
  assert.equal(
    createLayoutState(state.serialize()).project(1440).chat,
    "closed",
  );
});
test("assistant docks only when width can preserve a useful canvas", () => {
  const state = createLayoutState({ chat: false });
  state.toggle("chat");
  assert.equal(state.project(1279).chat, "drawer");
  assert.equal(state.project(1280).chat, "docked");
  state.toggle("files");
  assert.equal(state.project(1440).files, "drawer");
  assert.equal(state.project(1600).files, "docked");
});
test("narrow projection shows at most one modal and preserves wide preferences", () => {
  const state = createLayoutState({ files: true, chat: true, last: "chat" });
  assert.equal(state.project(520).files, "closed");
  assert.equal(state.project(520).chat, "drawer");
  assert.equal(state.project(1920).files, "docked");
  assert.equal(state.project(1920).chat, "docked");
});
test("focus does not destroy preceding panel preferences or section", () => {
  const state = createLayoutState({
    files: true,
    chat: true,
    section: "history",
  });
  const before = state.project(1920);
  state.focus();
  assert.equal(state.project(1920).files, "closed");
  assert.equal(state.project(1920).chat, "closed");
  state.focus(false);
  assert.deepEqual(state.project(1920), before);
});
test("file and history entries share one panel without toggling it off", () => {
  const state = createLayoutState({ chat: false });
  state.toggle("files", "files");
  state.toggle("files", "history");
  assert.equal(state.project(1440).section, "history");
  assert.equal(state.project(1440).files, "docked");
  state.toggle("files", "history");
  assert.equal(state.project(1440).files, "closed");
});
test("serialized layout contains only bounded presentation preferences", () => {
  const state = createLayoutState({
    files: true,
    chat: true,
    section: "history",
    last: "chat",
  });
  state.focus();
  const saved = state.serialize();
  assert.deepEqual(Object.keys(saved), ["files", "chat", "section", "last"]);
  assert.equal(createLayoutState(saved).project(1920).focused, false);
});
