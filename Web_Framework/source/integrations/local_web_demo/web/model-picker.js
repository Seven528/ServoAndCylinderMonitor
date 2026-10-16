// Composer-owned model controls. Catalog values remain the native request values.
export const effortLabel = (value) =>
  ({
    none: "None",
    minimal: "Minimal",
    low: "Low",
    medium: "Medium",
    high: "High",
    xhigh: "XHigh",
    max: "Max",
    ultra: "Ultra",
  })[value] || value;

export function resolveModelSettings(catalog, requested) {
  const model = catalog.find((item) => item.id === requested?.model);
  if (!model || !model.efforts?.length || !model.speeds?.length) return null;
  return {
    model: model.id,
    effort: model.efforts.includes(requested.effort)
      ? requested.effort
      : model.efforts[0],
    speed: model.speeds.some((item) => item.id === requested.speed)
      ? requested.speed
      : model.speeds[0].id,
  };
}
export function createModelPicker() {
  const $ = (id) => document.getElementById(id);
  const root = document.querySelector(".model-settings");
  let models = [],
    current = null,
    initial = null;
  const closeList = () => {
    $("model-list").hidden = true;
    $("model-current").setAttribute("aria-expanded", "false");
  };
  const render = () => {
    const model = models.find((item) => item.id === current?.model);
    $("reasoning-slider").disabled = !model;
    $("model-current").disabled = !models.length;
    $("speed-toggle").disabled = !model || model.speeds.length < 2;
    $("model-reset").disabled = !initial;
    $("effort-dots").replaceChildren();
    $("model-list").replaceChildren();
    for (const item of models) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = item.name;
      button.setAttribute("role", "menuitemradio");
      button.setAttribute("aria-checked", String(item.id === current?.model));
      button.onclick = () => {
        current = resolveModelSettings(models, { ...current, model: item.id });
        closeList();
        render();
        $("model-current").focus();
      };
      $("model-list").append(button);
    }
    if (!model) {
      $("model-label").textContent = "模型不可用";
      $("model-current").textContent = "选择模型";
      $("reasoning-label").textContent = "—";
      return;
    }
    const level = model.efforts.indexOf(current.effort);
    const speed = model.speeds.find((item) => item.id === current.speed);
    $("model-label").textContent = model.name;
    $("model-label").title =
      model.name + " · " + effortLabel(current.effort) + " · " + speed.name;
    $("model-current").textContent = model.name + " ›";
    $("reasoning-label").textContent = effortLabel(current.effort);
    $("reasoning-slider").max = model.efforts.length - 1;
    $("reasoning-slider").value = level;
    $("reasoning-slider").setAttribute(
      "aria-valuetext",
      effortLabel(current.effort),
    );
    $("speed-toggle").title = "速度：" + speed.name + "（点击切换）";
    $("speed-toggle").setAttribute(
      "aria-label",
      "速度：" + speed.name + "，点击切换",
    );
    $("speed-toggle").setAttribute(
      "aria-pressed",
      String(current.speed !== model.speeds[0].id),
    );
    $("effort-fill").style.width =
      (model.efforts.length > 1
        ? (level / (model.efforts.length - 1)) * 100
        : 0) + "%";
    for (const [index] of model.efforts.entries()) {
      const dot = document.createElement("i");
      dot.className = index <= level ? "active" : "";
      $("effort-dots").append(dot);
    }
  };
  $("reasoning-slider").oninput = () => {
    const model = models.find((item) => item.id === current?.model);
    const index = Number($("reasoning-slider").value);
    if (!model || !Number.isInteger(index) || !model.efforts[index]) return;
    current = { ...current, effort: model.efforts[index] };
    render();
  };
  $("speed-toggle").onclick = () => {
    const model = models.find((item) => item.id === current?.model);
    if (!model) return;
    const index = model.speeds.findIndex((item) => item.id === current.speed);
    current = {
      ...current,
      speed: model.speeds[(index + 1) % model.speeds.length].id,
    };
    render();
  };
  $("model-reset").onclick = () => {
    current = initial ? { ...initial } : null;
    closeList();
    render();
  };
  $("model-current").onclick = () => {
    $("model-list").hidden = !$("model-list").hidden;
    $("model-current").setAttribute(
      "aria-expanded",
      String(!$("model-list").hidden),
    );
  };
  document.addEventListener("click", (event) => {
    if (!event.composedPath().includes(root)) {
      root.open = false;
      closeList();
    }
  });
  root.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && root.open) {
      event.preventDefault();
      event.stopPropagation();
      if (!$("model-list").hidden) {
        closeList();
        $("model-current").focus();
      } else {
        root.open = false;
        $("model-label").focus();
      }
    }
  });
  return {
    initialize(catalog, preferred) {
      models = catalog || [];
      initial = resolveModelSettings(models, preferred);
      current = initial ? { ...initial } : null;
      render();
    },
    read: () => ({ ...current }),
    get valid() {
      return !!current;
    },
  };
}
