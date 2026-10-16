import test from "node:test";
import assert from "node:assert/strict";
import { chatConnection } from "../web/chat-connection.js";

test("online requires a fresh reachable initialized Codex health response", () => {
  assert.equal(
    chatConnection({ chat_ready: true, chat_error: null }, true).label,
    "online",
  );
  for (const health of [
    null,
    {},
    { chat_ready: false },
    { chat_ready: "true" },
    { chat_ready: true, chat_error: "bridge failed" },
  ])
    assert.equal(chatConnection(health, true).label, "offline");
});
test("HTTP loss cannot retain a stale green connection label", () => {
  const health = { chat_ready: true };
  assert.equal(chatConnection(health, false).online, false);
  assert.match(chatConnection(health, false).description, /中断/);
  assert.equal(chatConnection(health, true).online, true);
});
test("analysis errors do not determine Codex connection status", () => {
  assert.equal(
    chatConnection(
      { chat_ready: true, native_error: "native unavailable" },
      true,
    ).online,
    true,
  );
  assert.equal(
    chatConnection({ chat_ready: false, native_ready: true }, true).online,
    false,
  );
});
