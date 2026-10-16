// Local-only browser speech lifecycle. Never fall back to a remote recognizer.
export function supportsLocalRecognition(Recognition) {
  if (typeof Recognition !== "function") return false;
  try {
    return "processLocally" in Recognition.prototype;
  } catch {
    return false;
  }
}
export function createDictation({
  Recognition,
  onText,
  onState,
  schedule = setTimeout,
  cancelTimer = clearTimeout,
  maximum = 8000,
  drainMs = 3000,
}) {
  let recognizer = null,
    generation = 0,
    deadline = null,
    drain = null,
    active = false;
  const clear = () => {
    cancelTimer(deadline);
    cancelTimer(drain);
    deadline = drain = null;
    if (recognizer)
      recognizer.onstart =
        recognizer.onresult =
        recognizer.onerror =
        recognizer.onend =
          null;
    recognizer = null;
    active = false;
  };
  const finish = (message = "", error = false) => {
    clear();
    onState({ phase: error ? "error" : "idle", message });
  };
  const stop = () => {
    if (!recognizer || !active || drain !== null) return;
    onState({ phase: "stopping", message: "正在结束听写…" });
    try {
      recognizer.stop();
    } catch {
      finish();
      return;
    }
    if (!active) return;
    drain = schedule(() => {
      const old = recognizer;
      finish();
      old?.abort();
    }, drainMs);
  };
  return {
    get supported() {
      return supportsLocalRecognition(Recognition);
    },
    get active() {
      return active;
    },
    start() {
      if (active) return false;
      if (!supportsLocalRecognition(Recognition)) {
        onState({
          phase: "error",
          message: "当前浏览器不能保证本机识别，已禁止在线听写。",
        });
        return false;
      }
      const version = ++generation;
      let lastText = "";
      try {
        const speech = new Recognition();
        speech.processLocally = true;
        if (speech.processLocally !== true)
          throw new Error("local recognition cannot be enforced");
        recognizer = speech;
        active = true;
        speech.lang = "zh-CN";
        speech.continuous = true;
        speech.interimResults = true;
        speech.maxAlternatives = 1;
        const current = () => version === generation && recognizer === speech;
        speech.onstart = () => {
          if (current())
            onState({
              phase: "listening",
              message: "正在听写，再点麦克风结束。",
            });
        };
        speech.onresult = (event) => {
          if (!current()) return;
          let final = "",
            interim = "";
          for (let i = 0; i < event.results.length; i++) {
            const result = event.results[i],
              text = result[0]?.transcript || "";
            if (result.isFinal) final += text;
            else interim += text;
          }
          const bounded = final.slice(0, maximum);
          if (bounded !== lastText) {
            lastText = bounded;
            onText(bounded);
          }
          if (final.length >= maximum) {
            stop();
            return;
          }
          if (drain === null)
            onState({
              phase: "listening",
              message: interim
                ? "听写中：" + interim.slice(0, 120)
                : "正在听写，再点麦克风结束。",
            });
        };
        speech.onerror = (event) => {
          if (!current()) return;
          const messages = {
            "not-allowed": "未获得麦克风或语音识别授权。",
            "service-not-allowed": "浏览器未开放语音识别服务，请使用系统听写。",
            "audio-capture": "无法使用麦克风，请检查设备权限。",
            network: "浏览器语音服务连接失败，可改用系统听写。",
            "no-speech": "未识别到语音，请重试。",
            "language-not-supported":
              "浏览器暂不支持中文识别，请使用系统听写。",
          };
          finish(
            messages[event.error] ||
              (event.local ? event.message : "听写未完成，请重试。"),
            true,
          );
          try {
            speech.abort();
          } catch {}
        };
        speech.onend = () => {
          if (current()) finish();
        };
        onState({ phase: "starting", message: "正在请求语音识别…" });
        deadline = schedule(stop, 60000);
        speech.start();
        return true;
      } catch {
        const old = recognizer;
        finish("无法启动浏览器听写，可使用系统听写。", true);
        try {
          old?.abort();
        } catch {}
        return false;
      }
    },
    stop,
    cancel() {
      generation++;
      const old = recognizer;
      finish();
      try {
        old?.abort();
      } catch {}
    },
  };
}
