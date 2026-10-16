import test from "node:test";
import assert from "node:assert/strict";
import { createPressureDetails } from "../web/pressure-details.js";

const tick = () => new Promise(setImmediate);

function harness(t, { highlights = true } = {}) {
  const prior = globalThis.document;
  class Node {
    constructor(tag = "div") {
      this.tag = tag;
      this.children = [];
      this.attributes = {};
      this.dataset = {};
      this.style = {};
      this.ownText = "";
    }
    set textContent(text) {
      this.ownText = String(text);
      this.children = [];
    }
    get textContent() {
      return (
        this.ownText + this.children.map((child) => child.textContent).join(" ")
      );
    }
    append(...children) {
      this.children.push(...children);
    }
    replaceChildren(...children) {
      this.children = children;
      this.ownText = "";
    }
    setAttribute(key, value) {
      this.attributes[key] = value;
    }
    querySelectorAll(selector) {
      const all = this.children.flatMap((child) => [
        child,
        ...child.querySelectorAll("*"),
      ]);
      return all.filter(
        (child) =>
          selector === "*" ||
          (selector.startsWith(".")
            ? child.className?.split(" ").includes(selector.slice(1))
            : child.tag === selector),
      );
    }
    focus() {
      document.activeElement = this;
    }
    getBoundingClientRect() {
      return this.rect;
    }
  }
  const nodes = new Map();
  const node = (id) => {
    if (!nodes.has(id)) nodes.set(id, new Node());
    return nodes.get(id);
  };
  globalThis.document = {
    getElementById: node,
    createElement: (tag) => new Node(tag),
  };
  t.after(() => {
    if (prior === undefined) delete globalThis.document;
    else globalThis.document = prior;
  });
  const box = new Node(),
    img = new Node();
  box.rect = { left: 10, top: 20, width: 700, height: 500 };
  img.rect = { left: 100, top: 30, width: 500, height: 250 };
  const view = {
    id: "v",
    image_id: "image",
    report_id: "report",
    status: "succeeded",
    picking_available: true,
    context: {
      kind: "pressure2d",
      view_mode: "panel",
      side: "side1",
      surface_view: "components",
      file_name: "REMOVE_FILENAME.uni",
    },
  };
  const binding = {
    ok: true,
    presentation_id: "v",
    image_id: "image",
    report_id: "report",
  };
  const component = (id, x) => ({
    component_id: id,
    owner_name: "C5405",
    refdes: "C5405",
    package: "CC-0402-H0.55-Z01-RD50",
    role: "component_body",
    part_number_or_value: "REMOVE_PART_NUMBER",
    source_board_id: "REMOVE_BOARD",
    placement_index: 42,
    source: { start_line: 123, end_line: 123 },
    component_source: { start_line: 456, end_line: 456 },
    ...(highlights
      ? {
          highlight: {
            component_id: id,
            x_px: x,
            y_px: 100,
            width_px: 20,
            height_px: 10,
          },
        }
      : {}),
  });
  const a = component("placement/0", 200),
    b = component("placement/1", 700);
  const calls = [],
    focused = [];
  const control = createPressureDetails(box, img, () => true, {
    request: async (url) => {
      calls.push(url);
      if (!url.includes("head_index"))
        return {
          ...binding,
          width_px: 1000,
          height_px: 500,
          targets: [
            {
              head_index: 0,
              pressure_head_id: "head",
              refdes: "NDH1",
              x_px: 200,
              y_px: 100,
              rx_px: 10,
              ry_px: 10,
            },
          ],
        };
      return {
        ...binding,
        head_index: 0,
        head: {
          pressure_head_id: "head",
          result: "component_hit",
          clearance_band: "component_contact",
          component_body_clearance_mm: 0,
          reason: "REMOVE_ENGLISH_REASON",
          placement_index: 42,
          source: { start_line: 123 },
        },
        contacts: [a, { ...a }],
        contacts_total: 2,
        component_contacts_total: 2,
        contact_components_total: 1,
        offset: 0,
        next_offset: null,
        nearest_components: [b],
      };
    },
    ensureVisible: (h) => focused.push(h.component_id),
  });
  control.configure(view, view.context, true);
  const content = node("pressure-detail-content");
  const open = async () => {
    await tick();
    control.key({ key: "Enter", preventDefault() {} });
    await tick();
  };
  return { control, node, content, calls, focused, open, img, view };
}

test("pressure card prioritizes names/packages and omits all requested noisy fields", async (t) => {
  const h = harness(t);
  await h.open();
  const text = h.content.textContent;
  for (const forbidden of [
    "REMOVE_FILENAME",
    "REMOVE_PART_NUMBER",
    "REMOVE_BOARD",
    "REMOVE_ENGLISH_REASON",
    "实例索引",
    "UNI",
    "元件本体",
    "料号",
    "本体证据",
  ])
    assert.equal(text.includes(forbidden), false, forbidden);
  assert.match(text, /C5405/);
  assert.match(text, /CC-0402-H0.55-Z01-RD50/);
  assert.match(text, /干涉元件/);
  assert.match(text, /最近元件/);
  assert.equal(
    h.content.querySelectorAll(".pressure-component").length,
    2,
    "Repeated body evidence should not duplicate the same contact row",
  );
  assert.equal(
    h.content.querySelectorAll("h4")[0].className,
    "pressure-section-title",
  );
});

test("contact and nearest clicks highlight separate same-name placements without requests", async (t) => {
  const h = harness(t);
  await h.open();
  const [contact, nearest] = h.content.querySelectorAll(".pressure-component");
  assert.equal(contact.disabled, false);
  contact.onclick();
  assert.equal(h.node("pressure-component-highlight").hidden, false);
  assert.equal(
    parseFloat(h.node("pressure-component-highlight").style.left),
    195,
  );
  assert.equal(contact.attributes["aria-pressed"], "true");
  const disclosure = h.content.querySelectorAll("details")[0];
  disclosure.open = true;
  nearest.focus();
  nearest.onclick();
  assert.equal(h.content.querySelectorAll("details")[0], disclosure);
  assert.equal(disclosure.open, true);
  assert.equal(document.activeElement, nearest);
  assert.equal(
    parseFloat(h.node("pressure-component-highlight").style.left),
    445,
  );
  assert.equal(h.node("pressure-component-label").textContent, "C5405");
  assert.deepEqual(h.focused, ["placement/0", "placement/1"]);
  assert.equal(
    h.calls.length,
    2,
    "Highlight clicks must not fetch or run an analysis",
  );
  h.img.rect = { ...h.img.rect, left: 130, top: 50, width: 1000, height: 500 };
  h.control.repaint();
  assert.equal(
    parseFloat(h.node("pressure-component-highlight").style.left),
    830,
  );
  h.control.configure(
    h.view,
    { ...h.view.context, surface_view: "full" },
    true,
  );
  assert.equal(h.node("pressure-component-highlight").hidden, true);
  assert.equal(h.node("pressure-details").hidden, true);
});

test("old results remain readable but unavailable component locations are disabled", async (t) => {
  const h = harness(t, { highlights: false });
  await h.open();
  const rows = h.content.querySelectorAll(".pressure-component");
  assert.equal(
    rows.every((r) => r.disabled),
    true,
  );
  rows[0].onclick();
  assert.equal(h.node("pressure-component-highlight").hidden, true);
  assert.match(h.content.textContent, /C5405/);
  h.control.dispose();
  assert.equal(h.node("pressure-component-highlight").hidden, true);
});
