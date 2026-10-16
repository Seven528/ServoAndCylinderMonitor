import { filterLabel } from "./result-state.js";
const labels = {
  known_height_count: "已知高度",
  unknown_height_count: "未知高度",
  minimum_height_mm: "最低高度 mm",
  maximum_height_mm: "最高高度 mm",
  pressure_target_count: "压棒目标",
  critical_count: "Critical",
  warning_count: "Warning",
  clear_count: "Clear",
  pressure_head_count: "压头",
  component_hit: "命中元件",
  no_component_hit: "未命中元件",
  manual_review: "需复核",
  component_contact: "接触",
  component_near: "邻近",
  component_clear: "距离充足",
  board_count: "板定义",
  component_instance_count: "源元件实例",
  via_count: "过孔",
};
export function renderSummary(view) {
  const main = document.getElementById("summary-main"),
    sub = document.getElementById("summary-sub"),
    details = document.getElementById("summary-details");
  main.replaceChildren();
  sub.replaceChildren();
  details.replaceChildren();
  const stats = view?.statistics || {},
    c = view?.context || {};
  document.getElementById("summary-bar").hidden = !view;
  if (!view) return;
  const number = (n) => (typeof n === "number" ? n.toLocaleString() : "—");
  const part = (parent, value, label, cls = "") => {
    const node = document.createElement("span");
    node.className = "metric " + cls;
    const strong = document.createElement("strong"),
      text = document.createElement("span");
    strong.textContent = String(value);
    text.textContent = label;
    node.append(strong, text);
    parent.append(node);
  };
  if (view.analysis_status !== "succeeded") {
    part(
      main,
      view.status === "cancelled"
        ? "已取消"
        : view.status === "disabled"
          ? "暂未开放"
          : "未完成",
      "统计不可用",
    );
    return;
  }
  if (c.kind === "height_map") {
    part(
      main,
      `${number(stats.matching_count)} / ${number(stats.component_count)}`,
      stats.count_semantics === "placement_instance" ? "匹配实例" : "匹配元件",
    );
    part(sub, filterLabel(c.filter), "筛选范围");
    part(sub, number(stats.maximum_height_mm), "最高 mm");
  } else if (c.kind === "single_board_pressure") {
    part(main, number(stats.pressure_target_count), "压棒目标");
    for (const [key, cls] of [
      ["critical_count", "danger"],
      ["warning_count", "warning"],
      ["clear_count", "good"],
    ])
      part(sub, number(stats[key]), labels[key], stats[key] > 0 ? cls : "");
  } else if (c.kind === "pressure2d") {
    part(
      main,
      `${number(stats.component_hit)} / ${number(stats.pressure_head_count)}`,
      "命中元件 / 压头",
    );
    part(
      sub,
      number(stats.manual_review),
      "需复核",
      stats.manual_review > 0 ? "warning" : "",
    );
    part(sub, number(stats.component_near), "邻近");
  } else {
    part(main, number(stats.board_count), "板定义");
    part(sub, number(stats.component_instance_count), "源元件实例");
  }
  for (const [key, label] of Object.entries(labels)) {
    if (!(key in stats)) continue;
    const row = document.createElement("div");
    const term = document.createElement("span"),
      value = document.createElement("strong");
    term.textContent = label;
    value.textContent = number(stats[key]);
    row.append(term, value);
    details.append(row);
  }
}
