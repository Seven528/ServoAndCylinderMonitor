import { createLayoutState } from "./layout-state.js";

export function createLayout() {
  const $ = (id) => document.getElementById(id);
  let saved = {};
  try {
    saved = JSON.parse(
      sessionStorage.getItem("pcb-workbench-layout-v2") || "{}",
    );
  } catch {}
  const state = createLayoutState(saved || {}, innerWidth);
  let returnTo = null,
    detailsBeforeFocus = null,
    previousOverlay = null;
  const project = () => state.project(innerWidth);
  const persist = () => {
    try {
      sessionStorage.setItem(
        "pcb-workbench-layout-v2",
        JSON.stringify(state.serialize()),
      );
    } catch {}
  };
  const restoreFocus = () => {
    const target =
      returnTo?.isConnected && returnTo.getClientRects().length
        ? returnTo
        : $("focus-view");
    target.focus();
  };
  const apply = () => {
    const layout = project();
    document.body.dataset.focus = String(layout.focused);
    for (const name of ["files", "chat"]) {
      const panel = $(name + "-panel"),
        mode = layout[name];
      panel.dataset.presentation = mode;
      panel.inert =
        mode === "closed" || (!!layout.overlay && layout.overlay !== name);
      panel.setAttribute("aria-hidden", String(panel.inert));
      panel.setAttribute(
        "role",
        mode === "drawer" ? "dialog" : "complementary",
      );
      if (mode === "drawer") panel.setAttribute("aria-modal", "true");
      else panel.removeAttribute("aria-modal");
    }
    $("file-browser").hidden = layout.section !== "files";
    $("history-browser").hidden = layout.section !== "history";
    $("file-panel-title").textContent =
      layout.section === "history" ? "分析记录" : "工作文件";
    $("file-count").hidden = layout.section === "history";
    for (const [id, section] of [
      ["open-files", "files"],
      ["open-history", "history"],
    ])
      $(id).setAttribute(
        "aria-expanded",
        String(layout.files !== "closed" && layout.section === section),
      );
    $("open-chat").setAttribute(
      "aria-expanded",
      String(layout.chat !== "closed"),
    );
    $("focus-view").setAttribute("aria-pressed", String(layout.focused));
    $("focus-label").textContent = layout.focused ? "退出专注" : "专注看图";
    $("drawer-backdrop").hidden = !layout.overlay;
    for (const id of ["result-panel", "navigation-rail", "app-header"])
      $(id).inert = !!layout.overlay;
    if (layout.overlay && previousOverlay !== layout.overlay)
      $(layout.overlay + "-panel")
        .querySelector("[data-close-panel]")
        .focus();
    previousOverlay = layout.overlay;
    persist();
  };
  const leaveFocus = () => {
    if (!project().focused) return;
    state.focus(false);
    if (detailsBeforeFocus) {
      $("summary-more").open = detailsBeforeFocus.summary;
    }
    detailsBeforeFocus = null;
  };
  const close = (name = project().overlay) => {
    if (!name) return;
    state.close(name);
    if (innerWidth < 1280) state.close(name === "files" ? "chat" : "files");
    apply();
    restoreFocus();
  };
  const toggle = (name, section) => {
    returnTo = document.activeElement;
    const wasFocused = project().focused;
    leaveFocus();
    if (wasFocused) state.close(name);
    if (innerWidth < 1280) state.close(name === "files" ? "chat" : "files");
    state.toggle(name, section);
    apply();
  };
  $("open-files").onclick = () => toggle("files", "files");
  $("open-history").onclick = () => toggle("files", "history");
  $("open-chat").onclick = () => toggle("chat");
  document.querySelectorAll("[data-close-panel]").forEach((button) => {
    button.onclick = () => close(button.dataset.closePanel);
  });
  $("drawer-backdrop").onclick = () => close();
  $("focus-view").onclick = () => {
    if (project().focused) leaveFocus();
    else {
      detailsBeforeFocus = {
        summary: $("summary-more").open,
      };
      $("summary-more").open = false;
      state.focus(true);
    }
    apply();
  };
  document.addEventListener("keydown", (event) => {
    const { overlay, focused } = project();
    if (event.key === "Escape") {
      if (overlay) {
        event.preventDefault();
        close();
      } else if (focused) {
        event.preventDefault();
        leaveFocus();
        apply();
        $("focus-view").focus();
      }
    }
    if (overlay && event.key === "Tab") {
      const nodes = [
        ...$(overlay + "-panel").querySelectorAll(
          "button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea,a[href],summary",
        ),
      ].filter((node) => node.getClientRects().length);
      const first = nodes[0],
        last = nodes.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });
  window.addEventListener("resize", () => {
    const active = document.activeElement;
    apply();
    if (active?.closest('[data-presentation="closed"]'))
      $("focus-view").focus();
  });
  apply();
  return { close, show: (name) => toggle(name) };
}
