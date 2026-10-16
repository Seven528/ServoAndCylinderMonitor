import { api } from "./transport.js";
import {
  createPressureSelection,
  pressureHit,
  contactSections,
  uniqueComponents,
  validComponentHighlight,
} from "./pressure-picking.js";

const distance = (value) =>
  typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(3) + " mm"
    : "未提供";
const bands = {
  component_contact: "接触 / 命中",
  component_near: "邻近",
  component_clear: "未命中元件",
};
const element = (tag, text, className = "") => {
  const node = document.createElement(tag);
  node.textContent = text ?? "";
  node.className = className;
  return node;
};

export function createPressureDetails(
  box,
  img,
  ready,
  { request = api, ensureVisible = () => {} } = {},
) {
  const $ = (id) => document.getElementById(id);
  const panel = $("pressure-details"),
    content = $("pressure-detail-content"),
    ring = $("pressure-selection");
  const componentRing = $("pressure-component-highlight"),
    componentLabel = $("pressure-component-label");
  const hint = $("pressure-pick-hint"),
    hintText = $("pressure-pick-status"),
    retry = $("pressure-pick-retry");
  let configuration = null,
    rendered = [];
  const url = (view, extra = {}) =>
    "pressure-picking?" +
    new URLSearchParams({ presentation_id: view.id, ...extra });
  const selection = createPressureSelection({
    loadMap: (view, signal) => request(url(view), undefined, { signal }),
    loadHead: (view, index, offset, signal) =>
      request(url(view, { head_index: index, offset }), undefined, { signal }),
    changed(state) {
      hint.hidden = state.phase === "idle";
      retry.hidden = state.phase !== "error";
      hintText.textContent =
        state.phase === "ready"
          ? state.map.targets.length
            ? "点击压棒查看元件 · 方向键切换 · Esc 关闭"
            : "本图没有压棒记录。"
          : state.phase === "loading"
            ? "正在读取点选坐标…"
            : state.error || "";
      box.tabIndex = state.phase === "ready" ? 0 : -1;
      box.setAttribute(
        "aria-label",
        state.phase === "ready"
          ? "干涉分析元件图，可点击压棒或使用方向键查看详情"
          : "PCB 图像画布",
      );
      panel.hidden = !state.target;
      ring.hidden = !state.target;
      componentRing.hidden = !state.component;
      const signature = [
        state.view?.id,
        state.target?.head_index,
        state.detail,
        state.loadingDetail,
        state.detailError,
      ];
      if (signature.some((value, i) => value !== rendered[i])) {
        rendered = signature;
        content.replaceChildren();
        if (state.target) {
          $("pressure-detail-title").textContent =
            "压棒 " + (state.target.refdes || "#" + state.target.head_index);
          if (state.loadingDetail)
            content.append(element("p", "正在读取…", "pressure-muted"));
          else if (state.detailError)
            content.append(element("p", state.detailError, "chat-error"));
          else if (state.detail) renderDetail(state.detail);
        }
      }
      // Keep expanded sections and keyboard focus when only the selected component changes.
      for (const button of content.querySelectorAll(".pressure-component"))
        button.setAttribute(
          "aria-pressed",
          String(
            !!state.component &&
              button.dataset.componentId === state.component.component_id,
          ),
        );
      repaint();
    },
  });

  function componentButton(component, value, kind) {
    const name = component.refdes || component.owner_name || "未命名元件";
    const button = element("button", "", "pressure-component");
    button.type = "button";
    button.dataset.componentId = component.component_id || "";
    button.setAttribute("aria-label", "高亮" + kind + " " + name);
    button.setAttribute("aria-pressed", "false");
    button.disabled = !validComponentHighlight(component, selection.state.map);
    button.title = button.disabled
      ? "此结果缺少元件定位信息，请重新分析"
      : "点击在图中高亮";
    const line = element("span", "", "pressure-component-name");
    line.append(element("strong", name));
    if (kind === "最近元件")
      line.append(element("small", distance(component.distance_mm)));
    const pkg = element("span", "", "pressure-component-package");
    pkg.append(
      element("small", "封装"),
      element("span", component.package || "未提供"),
    );
    button.append(line, pkg);
    button.onclick = () => {
      if (selection.selectComponent(component.component_id, value)) {
        ensureVisible(selection.state.component.highlight, selection.state.map);
        repaint();
      }
    };
    return button;
  }

  function sectionTitle(tag, title, count) {
    const node = element(tag, "", "pressure-section-title");
    node.append(element("span", title));
    if (count != null)
      node.append(element("span", String(count), "pressure-count"));
    return node;
  }

  function renderDetail(value) {
    const head = value.head;
    const verdict = element("div", "", "pressure-verdict");
    verdict.title = "原生二维分析结果，不代表三维机械或现场验收。";
    verdict.append(
      element(
        "span",
        head.result === "manual_review"
          ? "需复核"
          : bands[head.clearance_band] || head.result,
        "pressure-status",
      ),
      element(
        "span",
        "净距 " + distance(head.component_body_clearance_mm),
        "pressure-clearance",
      ),
    );
    content.append(verdict);
    const sections = contactSections(value);
    content.append(sectionTitle("h4", "干涉元件", sections.total));
    const list = element("div", "", "pressure-component-list");
    for (const component of sections.components)
      list.append(componentButton(component, value, "干涉元件"));
    if (!sections.components.length)
      list.append(
        element(
          "p",
          sections.total === 0 ? "暂无命中元件" : "本页暂无元件",
          "pressure-muted",
        ),
      );
    content.append(list);
    if (value.offset || value.next_offset != null) {
      const pages = element("div", "", "pressure-pages");
      for (const [label, offset] of [
        ["上一页", value.offset ? Math.max(0, value.offset - 50) : null],
        ["下一页", value.next_offset],
      ]) {
        const button = element("button", label);
        button.type = "button";
        button.disabled = offset == null;
        button.onclick = () => selection.select(value.head_index, offset);
        pages.append(button);
      }
      content.append(pages);
    }
    const nearest = uniqueComponents(value.nearest_components || []);
    const nearby = element("details", "", "pressure-nearest");
    nearby.open =
      sections.total === 0 && head.clearance_band === "component_near";
    const summary = sectionTitle("summary", "最近元件", nearest.length);
    summary.title = "按距离排序，不等于干涉元件";
    nearby.append(summary);
    for (const component of nearest)
      nearby.append(componentButton(component, value, "最近元件"));
    content.append(nearby);
    if (sections.others.length) {
      const other = element("details", "", "pressure-other");
      other.append(sectionTitle("summary", "其他接触", sections.others.length));
      other.title = "孔、支撑等辅助证据，不作为元件干涉。";
      for (const contact of sections.others)
        other.append(
          element("div", contact.owner_name || "未命名对象", "pressure-muted"),
        );
      content.append(other);
    }
  }

  function repaint() {
    const { target, map, component } = selection.state;
    if (!target || !map || !ready()) {
      ring.hidden = true;
      componentRing.hidden = true;
      return;
    }
    const r = img.getBoundingClientRect(),
      b = box.getBoundingClientRect();
    const sx = r.width / map.width_px,
      sy = r.height / map.height_px;
    let x = r.left - b.left + target.x_px * sx,
      y = r.top - b.top + target.y_px * sy;
    ring.hidden = false;
    Object.assign(ring.style, {
      left: x + "px",
      top: y + "px",
      width: Math.max(12, 2 * target.rx_px * sx + 8) + "px",
      height: Math.max(12, 2 * target.ry_px * sy + 8) + "px",
    });
    componentRing.hidden = !component;
    if (component) {
      const h = component.highlight;
      x = r.left - b.left + (h.x_px + h.width_px / 2) * sx;
      y = r.top - b.top + (h.y_px + h.height_px / 2) * sy;
      Object.assign(componentRing.style, {
        left: x + "px",
        top: y + "px",
        width: Math.max(10, h.width_px * sx + 6) + "px",
        height: Math.max(10, h.height_px * sy + 6) + "px",
      });
      componentLabel.textContent =
        component.refdes || component.owner_name || "";
    }
    Object.assign(panel.style, {
      left: x > b.width / 2 ? "12px" : "auto",
      right: x > b.width / 2 ? "auto" : "12px",
      top: y > b.height / 2 ? "40px" : "auto",
      bottom: y > b.height / 2 ? "auto" : "12px",
    });
  }
  $("pressure-detail-close").onclick = () => {
    selection.clear();
    box.focus();
  };
  retry.onclick = () => {
    selection.retry();
    if (configuration) selection.configure(...configuration);
  };
  return {
    configure(view, draft, supported) {
      configuration = [view, draft, ready(), supported];
      selection.configure(...configuration);
    },
    click(x, y) {
      if (ready()) {
        selection.click(x, y, img.getBoundingClientRect());
        if (selection.state.phase === "ready") box.focus();
      }
    },
    hover(x, y) {
      return (
        ready() &&
        !!pressureHit(selection.state.map, img.getBoundingClientRect(), x, y)
      );
    },
    key(event) {
      if (selection.state.phase !== "ready" || !ready()) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        selection.clear();
      } else if (
        ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Enter"].includes(
          event.key,
        )
      ) {
        const count = selection.state.map.targets.length;
        if (!count) return;
        event.preventDefault();
        const current = selection.state.target?.head_index;
        const offset = ["ArrowLeft", "ArrowUp"].includes(event.key)
          ? -1
          : event.key === "Enter"
            ? 0
            : 1;
        selection.select(
          current == null ? 0 : (current + offset + count) % count,
        );
      }
    },
    repaint,
    clear: () => selection.clear(),
    dispose: () => {
      configuration = null;
      selection.dispose();
    },
  };
}
