import { createImageLoader } from "./image-loader.js";
import { bindImageDownload } from "./image-download.js";
import { createPressureDetails } from "./pressure-details.js";
import { componentPanOffset } from "./pressure-picking.js";

export function createViewer() {
  const box = document.querySelector("#viewport"),
    img = document.querySelector("#pcb-image");
  let scale = 1,
    x = 0,
    y = 0,
    drag = null,
    fitMode = true,
    displayedId = null,
    wanted = null,
    pickContext = null;
  const feedback = document.querySelector("#image-feedback"),
    status = document.querySelector("#image-status"),
    retry = document.querySelector("#image-retry");
  const loader = createImageLoader({
    onReady(url, artifact) {
      if (displayedId !== artifact.id) fitMode = true;
      displayedId = artifact.id;
      img.src = url;
      img.hidden = false;
      syncPicking();
      document.querySelector("#image-caption").textContent =
        `${artifact.width_pixels} × ${artifact.height_pixels}`;
      bindImageDownload(
        document.querySelector("#image-download"),
        artifact,
        (error) => {
          feedback.hidden = false;
          feedback.classList.add("error");
          status.textContent = error.message;
        },
        (format) => {
          feedback.classList.remove("error");
          if (loader.phase === "ready") {
            feedback.hidden = true;
            status.textContent = "";
          }
          if (format === "svg") {
            feedback.hidden = false;
            status.textContent = "正在生成真正矢量 SVG，当前预览保持不变…";
          }
        },
        () => {
          if (wanted?.id === artifact.id) {
            feedback.hidden = true;
            status.textContent = "";
          }
        },
      );
    },
    onState(value) {
      feedback.hidden = ["ready", "idle"].includes(value.phase);
      feedback.classList.toggle("error", value.phase === "error");
      retry.hidden = value.phase !== "error";
      if (value.phase === "loading" || value.phase === "retrying") {
        status.textContent =
          (value.phase === "retrying"
            ? "图片读取暂时失败，正在重试…"
            : "正在加载图片…") +
          (value.hasPrevious ? " 暂显示上一张图片。" : "");
        document.querySelector("#image-download").hidden = true;
      } else if (value.phase === "error") {
        status.textContent =
          (value.error?.message || "图片加载失败。") +
          (value.hasPrevious ? " 当前仍是上一张图片。" : "") +
          " 可仅重试图片，无需重新分析。";
      } else status.textContent = "";
      syncPicking();
    },
  });
  const picking = createPressureDetails(
    box,
    img,
    () => matchesDisplayed(pickContext?.view),
    {
      ensureVisible(highlight, map) {
        const offset = componentPanOffset(
          highlight,
          map,
          img.getBoundingClientRect(),
          box.getBoundingClientRect(),
        );
        if (offset.x || offset.y) {
          fitMode = false;
          x += offset.x;
          y += offset.y;
          draw();
        }
      },
    },
  );
  function matchesDisplayed(view) {
    return (
      !!view?.image_id &&
      loader.phase === "ready" &&
      displayedId === view.image_id &&
      !img.hidden &&
      img.complete &&
      img.naturalWidth > 0
    );
  }
  function syncPicking() {
    if (pickContext)
      picking.configure(
        pickContext.view,
        pickContext.draft,
        pickContext.supported,
      );
    else picking.configure(null, null, false);
  }
  const draw = () => {
    img.style.width = img.naturalWidth + "px";
    img.style.height = img.naturalHeight + "px";
    img.style.transform = `translate(calc(-50% + ${x}px), calc(-50% + ${y}px)) scale(${scale})`;
    picking.repaint();
  };
  const fit = () => {
    if (!img.naturalWidth) return;
    fitMode = true;
    scale = Math.min(
      (box.clientWidth - 24) / img.naturalWidth,
      (box.clientHeight - 24) / img.naturalHeight,
    );
    x = y = 0;
    draw();
  };
  const zoom = (factor) => {
    fitMode = false;
    scale = Math.max(0.03, Math.min(6, scale * factor));
    draw();
  };
  img.onload = () => {
    if (fitMode) fit();
    else draw();
    syncPicking();
  };
  img.onerror = () => {
    if (img.getAttribute("src") === loader.url) loader.displayError();
  };
  retry.onclick = () => loader.retry();
  box.addEventListener(
    "wheel",
    (e) => {
      if (img.hidden || e.target.closest("[data-viewer-control]")) return;
      e.preventDefault();
      zoom(e.deltaY < 0 ? 1.12 : 1 / 1.12);
    },
    { passive: false },
  );
  box.onpointerdown = (e) => {
    if (
      img.hidden ||
      e.button !== 0 ||
      e.target.closest("[data-viewer-control]")
    )
      return;
    drag = {
      x: e.clientX - x,
      y: e.clientY - y,
      startX: e.clientX,
      startY: e.clientY,
      pointerId: e.pointerId,
      moved: false,
    };
    box.setPointerCapture(e.pointerId);
  };
  box.onpointermove = (e) => {
    if (drag && drag.pointerId === e.pointerId) {
      if (Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > 4)
        drag.moved = true;
      if (!drag.moved) return;
      fitMode = false;
      x = e.clientX - drag.x;
      y = e.clientY - drag.y;
      draw();
    } else
      box.style.cursor = picking.hover(e.clientX, e.clientY) ? "pointer" : "";
  };
  box.onpointerup = (e) => {
    if (!drag || drag.pointerId !== e.pointerId) return;
    const clicked =
      !drag.moved &&
      Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) <= 4;
    drag = null;
    if (box.hasPointerCapture(e.pointerId))
      box.releasePointerCapture(e.pointerId);
    if (clicked) picking.click(e.clientX, e.clientY);
  };
  box.onpointercancel = () => {
    drag = null;
  };
  box.onlostpointercapture = () => {
    drag = null;
  };
  box.onkeydown = (e) => {
    if (e.target.closest("[data-viewer-control]") && e.key !== "Escape") return;
    picking.key(e);
  };
  document.querySelector("#fit").onclick = fit;
  document.querySelector("#zoom-in").onclick = () => zoom(1.25);
  document.querySelector("#zoom-out").onclick = () => zoom(0.8);
  const observer = new ResizeObserver(() => {
    if (fitMode) fit();
    else picking.repaint();
  });
  observer.observe(box);
  box.addEventListener("dblclick", (e) => {
    if (e.target.closest("[data-viewer-control]")) return;
    picking.clear();
    fit();
  });
  const dispose = () => {
    observer.disconnect();
    loader.dispose();
    picking.dispose();
    img.removeAttribute("src");
  };
  window.addEventListener("pagehide", dispose);
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      observer.observe(box);
      if (wanted) loader.show(wanted);
    }
  });
  return {
    matchesDisplayed(view) {
      return matchesDisplayed(view);
    },
    setPickingContext(view, draft, supported) {
      pickContext = { view, draft, supported };
      syncPicking();
    },
    show(artifact) {
      wanted = artifact;
      document.querySelector("#empty").hidden = !!artifact;
      if (!artifact) {
        img.hidden = true;
        img.removeAttribute("src");
        displayedId = null;
        document.querySelector("#image-caption").textContent =
          "本机计算 · 真实 UNI";
        bindImageDownload(
          document.querySelector("#image-download"),
          null,
          () => {},
        );
      }
      loader.show(artifact);
    },
    setExportFormats(formats) {
      const option = document.querySelector(
        '#download-format option[value="svg"]',
      );
      option.disabled = !formats.includes("svg");
      option.textContent = option.disabled ? "SVG（待服务更新）" : "SVG";
    },
    recover: () => loader.recover(),
    dispose,
  };
}
