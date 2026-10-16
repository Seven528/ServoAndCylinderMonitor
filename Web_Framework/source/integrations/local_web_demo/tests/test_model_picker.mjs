import test from "node:test";
import assert from "node:assert/strict";
import { resolveModelSettings, effortLabel } from "../web/model-picker.js";
const catalog = [
  {
    id: "one",
    name: "One",
    efforts: ["low", "high", "max"],
    speeds: [
      { id: "default", name: "标准" },
      { id: "priority", name: "Fast" },
    ],
  },
  {
    id: "two",
    name: "Two",
    efforts: ["medium", "high"],
    speeds: [{ id: "default", name: "标准" }],
  },
];
test("valid provider settings keep exact native values", () => {
  const value = { model: "one", effort: "max", speed: "priority" };
  assert.deepEqual(resolveModelSettings(catalog, value), value);
  assert.equal(effortLabel(value.effort), "Max");
});
test("unknown model is never silently replaced", () => {
  assert.equal(resolveModelSettings(catalog, { model: "missing" }), null);
  assert.equal(resolveModelSettings([], {}), null);
});
test("model changes select only actual supported efforts and speeds", () => {
  assert.deepEqual(
    resolveModelSettings(catalog, {
      model: "two",
      effort: "max",
      speed: "priority",
    }),
    { model: "two", effort: "medium", speed: "default" },
  );
  assert.equal(
    resolveModelSettings(catalog, {
      model: "one",
      effort: "high",
      speed: "default",
    }).effort,
    "high",
  );
});
