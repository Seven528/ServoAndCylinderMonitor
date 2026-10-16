// Hit tests consume native pixel coordinates, never image colors or CAD inference.
export function pressurePickingEligible(view, draft) {
  const c = view?.context;
  return (
    !!view?.image_id &&
    !!view?.report_id &&
    view.status === "succeeded" &&
    c?.kind === "pressure2d" &&
    c.surface_view === "components" &&
    c.view_mode === "panel" &&
    draft?.kind === "pressure2d" &&
    draft.surface_view === "components" &&
    draft.view_mode === "panel" &&
    draft.side === c.side
  );
}

export function uniqueComponents(values) {
  const seen = new Set();
  return values.filter((component, index) => {
    const id =
      typeof component.component_id === "string" && component.component_id
        ? "component:" + component.component_id
        : "record:" + index;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

export function contactSections(value) {
  const contacts = value.contacts || [];
  const components = uniqueComponents(
    contacts.filter((item) => item.role === "component_body"),
  );
  const others = contacts.filter((item) => item.role !== "component_body");
  const complete = !value.offset && value.next_offset == null;
  const total = Number.isInteger(value.contact_components_total)
    ? value.contact_components_total
    : complete
      ? components.length
      : null;
  return { components, others, complete, total };
}

export function validComponentHighlight(component, map) {
  const h = component?.highlight;
  return (
    !!map &&
    typeof component?.component_id === "string" &&
    !!component.component_id &&
    h?.component_id === component.component_id &&
    [h.x_px, h.y_px, h.width_px, h.height_px].every(Number.isFinite) &&
    h.x_px >= 0 &&
    h.y_px >= 0 &&
    h.width_px > 0 &&
    h.height_px > 0 &&
    h.x_px + h.width_px <= map.width_px + 1e-6 &&
    h.y_px + h.height_px <= map.height_px + 1e-6
  );
}

export function componentPanOffset(highlight, map, image, viewport) {
  const cx =
    image.left +
    ((highlight.x_px + highlight.width_px / 2) * image.width) / map.width_px;
  const cy =
    image.top +
    ((highlight.y_px + highlight.height_px / 2) * image.height) / map.height_px;
  return {
    x:
      cx < viewport.left + 18 || cx > viewport.left + viewport.width - 18
        ? viewport.left + viewport.width / 2 - cx
        : 0,
    y:
      cy < viewport.top + 18 || cy > viewport.top + viewport.height - 18
        ? viewport.top + viewport.height / 2 - cy
        : 0,
  };
}

export function pressureHit(map, rect, clientX, clientY) {
  if (
    !map ||
    !(rect.width > 0 && rect.height > 0) ||
    clientX < rect.left ||
    clientX > rect.left + rect.width ||
    clientY < rect.top ||
    clientY > rect.top + rect.height
  )
    return null;
  const sx = rect.width / map.width_px,
    sy = rect.height / map.height_px;
  let found = null,
    nearest = Infinity;
  for (const target of map.targets) {
    const dx = clientX - (rect.left + target.x_px * sx);
    const dy = clientY - (rect.top + target.y_px * sy);
    const rx = Math.max(5, target.rx_px * sx) + 2;
    const ry = Math.max(5, target.ry_px * sy) + 2;
    const distance = dx * dx + dy * dy;
    if ((dx / rx) ** 2 + (dy / ry) ** 2 <= 1 && distance < nearest) {
      found = target;
      nearest = distance;
    }
  }
  return found;
}

function validBinding(value, view) {
  return (
    value?.ok === true &&
    value.presentation_id === view.id &&
    value.image_id === view.image_id &&
    value.report_id === view.report_id
  );
}

export function createPressureSelection({
  loadMap,
  loadHead,
  changed = () => {},
}) {
  let key = "",
    epoch = 0,
    detailEpoch = 0,
    mapRequest = null,
    headRequest = null;
  let state = {
    phase: "idle",
    view: null,
    map: null,
    target: null,
    detail: null,
    component: null,
  };
  const emit = () => changed(state);
  const clearDetail = () => {
    headRequest?.abort();
    headRequest = null;
    detailEpoch++;
    state = {
      ...state,
      target: null,
      detail: null,
      loadingDetail: false,
      detailError: "",
      component: null,
    };
  };
  const control = {
    get state() {
      return state;
    },
    configure(view, draft, ready, supported = true) {
      const eligible = pressurePickingEligible(view, draft);
      const nextKey = JSON.stringify([
        view?.id,
        view?.image_id,
        view?.report_id,
        eligible,
        ready,
        supported,
        view?.picking_available,
      ]);
      if (nextKey === key) return;
      key = nextKey;
      epoch++;
      mapRequest?.abort();
      mapRequest = null;
      clearDetail();
      state = {
        phase: "idle",
        view,
        map: null,
        target: null,
        detail: null,
        component: null,
      };
      if (!eligible || !ready) {
        emit();
        return;
      }
      if (!supported || !view.picking_available) {
        state.phase = "unavailable";
        state.error = !supported
          ? "点选功能需要更新后端后使用。"
          : "此历史图未包含点选坐标，重新运行干涉分析后可用。";
        emit();
        return;
      }
      state.phase = "loading";
      emit();
      const current = epoch;
      const controller = (mapRequest = new AbortController());
      Promise.resolve()
        .then(() => loadMap(view, controller.signal))
        .then((value) => {
          if (current !== epoch) return;
          if (
            !validBinding(value, view) ||
            !Number.isInteger(value.width_px) ||
            !Number.isInteger(value.height_px) ||
            !(value.width_px > 0 && value.height_px > 0) ||
            !Array.isArray(value.targets) ||
            value.targets.length > 4096 ||
            value.targets.some(
              (t, i) =>
                !t ||
                t.head_index !== i ||
                ![t.x_px, t.y_px, t.rx_px, t.ry_px].every(Number.isFinite) ||
                t.rx_px <= 0 ||
                t.ry_px <= 0 ||
                t.x_px < 0 ||
                t.x_px > value.width_px ||
                t.y_px < 0 ||
                t.y_px > value.height_px,
            )
          )
            throw Error("压棒坐标与当前图片不一致。");
          state = { ...state, phase: "ready", map: value };
          emit();
        })
        .catch((error) => {
          if (current !== epoch) return;
          state = { ...state, phase: "error", error: error.message };
          emit();
        });
    },
    select(index, offset = 0) {
      if (
        state.phase !== "ready" ||
        !Number.isInteger(index) ||
        !state.map.targets[index]
      )
        return;
      clearDetail();
      const target = state.map.targets[index],
        view = state.view;
      state = { ...state, target, loadingDetail: true };
      emit();
      const current = epoch,
        request = detailEpoch;
      const controller = (headRequest = new AbortController());
      Promise.resolve()
        .then(() => loadHead(view, index, offset, controller.signal))
        .then((value) => {
          if (current !== epoch || request !== detailEpoch) return;
          if (
            !validBinding(value, view) ||
            value.head_index !== index ||
            value.head?.pressure_head_id !== target.pressure_head_id
          )
            throw Error("压棒详情已失效，请重新点选。");
          state = { ...state, detail: value, loadingDetail: false };
          emit();
        })
        .catch((error) => {
          if (current !== epoch || request !== detailEpoch) return;
          state = {
            ...state,
            loadingDetail: false,
            detailError: error.message,
          };
          emit();
        });
    },
    selectComponent(id, fromDetail = state.detail) {
      if (
        state.phase !== "ready" ||
        !state.detail ||
        fromDetail !== state.detail
      )
        return false;
      const candidates = [
        ...(state.detail.contacts || []).filter(
          (c) => c.role === "component_body",
        ),
        ...(state.detail.nearest_components || []),
      ];
      const component = candidates.find(
        (c) => c.component_id === id && validComponentHighlight(c, state.map),
      );
      if (!component) return false;
      state = { ...state, component };
      emit();
      return true;
    },
    click(x, y, rect) {
      const target = pressureHit(state.map, rect, x, y);
      if (target) control.select(target.head_index);
      else control.clear();
      return target;
    },
    clear() {
      clearDetail();
      emit();
    },
    retry() {
      key = "";
    },
    dispose() {
      epoch++;
      key = "";
      mapRequest?.abort();
      mapRequest = null;
      clearDetail();
      state = {
        phase: "idle",
        view: null,
        map: null,
        target: null,
        detail: null,
        component: null,
      };
      emit();
    },
  };
  return control;
}
