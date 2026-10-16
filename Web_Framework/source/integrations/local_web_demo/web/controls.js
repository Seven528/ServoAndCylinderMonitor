import { filterOptions } from "./result-state.js";
export function createControls(onChange) {
  const $ = (id) => document.getElementById(id);
  let draft,
    singleSurfaceSupported = false;
  const read = () => {
    const filter = { kind: $("height-filter").value };
    if (filter.kind === "custom") {
      filter.minimum_mm = Number($("minimum").value);
      filter.maximum_mm = Number($("maximum").value);
    }
    return { ...draft, surface_view: $("surface").value, filter };
  };
  const sync = () => {
    document.querySelectorAll("[data-kind]").forEach((b) => {
      const active = b.dataset.kind === draft.kind;
      b.setAttribute("aria-selected", String(active));
      b.tabIndex = active ? 0 : -1;
    });
    document
      .querySelectorAll("[data-side]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.side === draft.side)),
      );
    document.querySelectorAll("[data-view]").forEach((b) => {
      b.setAttribute(
        "aria-pressed",
        String(b.dataset.view === draft.view_mode),
      );
      b.disabled = ["pressure2d", "single_board_pressure"].includes(draft.kind);
    });
    $("surface").value = draft.surface_view;
    $("surface").disabled =
      draft.kind === "single_board_pressure" && !singleSurfaceSupported;
    $("height-controls").hidden = draft.kind !== "height_map";
    $("height-controls").inert = draft.kind !== "height_map";
    $("height-filter").value = draft.filter?.kind || "all";
    $("custom-range").hidden = draft.filter?.kind !== "custom";
    $("custom-range").inert = draft.filter?.kind !== "custom";
    if (draft.filter?.kind === "custom") {
      $("minimum").value = draft.filter.minimum_mm;
      $("maximum").value = draft.filter.maximum_mm;
    }
    $("run").hidden = draft.kind === "preview";
    $("preview-status").hidden = draft.kind !== "preview";
    $("preview-retry").hidden = true;
  };
  const commit = () => {
    sync();
    onChange(structuredClone(draft));
  };
  for (const [value, label] of filterOptions) {
    const op = document.createElement("option");
    op.value = value;
    op.textContent = label;
    $("height-filter").append(op);
  }
  document.querySelectorAll("[data-kind]").forEach((b) => {
    b.onclick = () => {
      draft = { ...read(), kind: b.dataset.kind };
      if (draft.kind === "pressure2d") {
        draft.view_mode = "panel";
        draft.surface_view = "components";
      }
      if (draft.kind === "single_board_pressure") {
        draft.view_mode = "single";
      }
      commit();
    };
    b.onkeydown = (e) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      const tabs = [...document.querySelectorAll("[data-kind]")];
      const at = tabs.indexOf(b);
      const n =
        e.key === "Home"
          ? 0
          : e.key === "End"
            ? tabs.length - 1
            : (at + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) %
              tabs.length;
      tabs[n].click();
      tabs[n].focus();
    };
  });
  for (const [attr, field] of [
    ["side", "side"],
    ["view", "view_mode"],
  ])
    document.querySelectorAll(`[data-${attr}]`).forEach(
      (b) =>
        (b.onclick = () => {
          draft = { ...read(), [field]: b.dataset[attr] };
          commit();
        }),
    );
  for (const id of ["surface", "height-filter", "minimum", "maximum"])
    $(id).onchange = () => {
      draft = read();
      commit();
    };
  return {
    configure(health) {
      const supported =
        Array.isArray(health?.single_board_surface_views) &&
        health.single_board_surface_views.includes("components");
      if (supported === singleSurfaceSupported) return;
      singleSurfaceSupported = supported;
      if (draft) sync();
    },
    set(value) {
      draft = structuredClone(value);
      sync();
    },
    read,
    busy(value) {
      $("run").disabled = value;
    },
  };
}
