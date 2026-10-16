import test from "node:test";
import assert from "node:assert/strict";
import {
  createFilePanel,
  confirmFileRemoval,
  restoreFileFocus,
} from "../web/file-panel.js";

function harness(t) {
  const prior = globalThis.document;
  const roots = new Map();
  class Element {
    constructor(tag) {
      this.tag = tag;
      this.children = [];
      this.dataset = {};
      this.attributes = {};
      this.classList = { toggle() {} };
      this.parentElement = { scrollTop: 0 };
    }
    setAttribute(key, value) {
      this.attributes[key] = value;
    }
    append(...nodes) {
      nodes.forEach((node) => {
        node.parentElement = this;
        this.children.push(node);
      });
    }
    replaceChildren(...nodes) {
      this.children = [];
      this.append(...nodes);
    }
    focus() {
      document.activeElement = this;
    }
    showModal() {
      this.open = true;
    }
  }
  const node = (id) => {
    if (!roots.has(id)) roots.set(id, new Element("div"));
    return roots.get(id);
  };
  const walk = (element) => [element, ...element.children.flatMap(walk)];
  globalThis.document = {
    body: new Element("body"),
    activeElement: null,
    createElement: (tag) => new Element(tag),
    getElementById: node,
    querySelector(selector) {
      const match = selector.match(
        /\[data-(file-id|remove-file-id)="([^"]+)"\]/,
      );
      const key = match?.[1] === "file-id" ? "fileId" : "removeFileId";
      return match
        ? [...roots.values()]
            .flatMap(walk)
            .find((item) => item.dataset[key] === match[2])
        : null;
    },
  };
  t.after(() => {
    if (prior === undefined) delete globalThis.document;
    else globalThis.document = prior;
  });
  const files = [
    { id: "f_A", name: "same.uni", role: "pcb", size: 100 },
    { id: "f_B", name: "same.uni", role: "holder", size: 100 },
  ];
  const state = {
    snapshot: { files, jobs: [] },
    selection: { pcb_ids: [], holder_id: null },
  };
  const removed = [],
    selected = [];
  const panel = createFilePanel(
    (value) => selected.push(value),
    () => {},
    (file) => removed.push(file),
  );
  return { node, state, panel, removed, selected };
}

test("PCB and Holder get exact-ID delete buttons outside selection labels", (t) => {
  const h = harness(t);
  h.panel.render(h.state, { removalSupported: true });
  for (const [index, role] of ["pcb", "holder"].entries()) {
    const row = h.node(role + "-files").children[0];
    assert.equal(row.tag, "div");
    assert.equal(row.children[0].tag, "label");
    const button = row.children[1];
    assert.equal(button.tag, "button");
    assert.equal(button.attributes["aria-label"], "删除文件 same.uni");
    assert.equal(button.disabled, false);
    button.onclick();
    assert.equal(h.removed[index].id, h.state.snapshot.files[index].id);
  }
  assert.deepEqual(h.selected, []);
  assert.deepEqual(h.state.selection, { pcb_ids: [], holder_id: null });
});

test("delete is disabled for pending mutations, running work and old backends", (t) => {
  const h = harness(t);
  for (const field of ["active_job", "export_busy", "chat_busy"]) {
    h.state.snapshot[field] = true;
    h.panel.render(h.state, { removalSupported: true });
    assert.equal(h.node("pcb-files").children[0].children[1].disabled, true);
    delete h.state.snapshot[field];
  }
  h.panel.render(h.state, { removalSupported: true, removing: true });
  assert.equal(
    h.node("pcb-files").children[0].children[0].children[0].disabled,
    true,
  );
  h.panel.render(h.state, { removalSupported: false });
  const button = h.node("pcb-files").children[0].children[1];
  assert.equal(button.disabled, true);
  assert.match(button.title, /重启后端/);
});

test("confirmation names the exact file safely and cancellation is side-effect free", async (t) => {
  const h = harness(t);
  const pending = confirmFileRemoval({ name: '<test name="安全">.uni' });
  assert.equal(
    h.node("remove-file-name").textContent,
    '<test name="安全">.uni',
  );
  assert.equal(h.node("remove-file-name").innerHTML, undefined);
  const dialog = h.node("remove-file-dialog");
  assert.equal(dialog.open, true);
  assert.equal(await confirmFileRemoval({ name: "another.uni" }), false);
  dialog.open = false;
  dialog.onclose();
  assert.equal(await pending, false);
  const accepted = confirmFileRemoval({ name: "same.uni" });
  dialog.returnValue = "remove";
  dialog.open = false;
  dialog.onclose();
  assert.equal(await accepted, true);
  assert.deepEqual(h.removed, []);
});

test("deleting a focused row restores focus to upload rather than a vanished element", (t) => {
  const h = harness(t);
  h.panel.render(h.state, { removalSupported: true });
  h.node("pcb-files").children[0].children[1].focus();
  h.state.snapshot.files = [];
  h.panel.render(h.state, { removalSupported: true });
  assert.equal(document.activeElement, h.node("upload-pcb"));
  assert.equal(h.node("file-count").textContent, 0);
});

test("focus lost by disabling the pending button is restored without selecting another file", (t) => {
  const h = harness(t);
  h.panel.render(h.state, { removalSupported: true });
  const removed = h.state.snapshot.files[0];
  h.state.snapshot.files = [h.state.snapshot.files[1]];
  h.panel.render(h.state, { removalSupported: true });
  document.activeElement = document.body;
  restoreFileFocus(removed, h.state.snapshot.files);
  assert.equal(document.activeElement, h.node("upload-pcb"));
  assert.deepEqual(h.selected, []);
  const userFocus = h.node("user-focus");
  userFocus.focus();
  restoreFileFocus(removed, h.state.snapshot.files);
  assert.equal(document.activeElement, userFocus);
});
