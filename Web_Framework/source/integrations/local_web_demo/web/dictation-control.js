import { createDictation } from "./dictation.js";
import { LocalMacRecognition } from "./local-recognition.js";
import { api } from "./transport.js";

export function createDictationControl(
  onActivity,
  { NativeRecognition = LocalMacRecognition } = {},
) {
  const $ = (id) => document.getElementById(id);
  const input = $("message"),
    button = $("dictate"),
    status = $("dictation-status"),
    dialog = $("dictation-dialog");
  const start = $("dictation-start"),
    install = $("dictation-install");
  const browserRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = browserRecognition,
    engine = "browser-on-device",
    checkId = 0,
    phase = "idle",
    nativeCapability = null;
  let prefix = "",
    suffix = "",
    wasReadonly = false;
  const make = () =>
    createDictation({
      Recognition: recognition,
      drainMs: engine === "macos-on-device" ? 90000 : 3000,
      onText(text) {
        const room = Math.max(0, 8000 - prefix.length - suffix.length);
        input.value = prefix + text.slice(0, room) + suffix;
        input.setSelectionRange(
          input.value.length - suffix.length,
          input.value.length - suffix.length,
        );
        input.dispatchEvent(new Event("input", { bubbles: true }));
      },
      onState(state) {
        phase = state.phase;
        const running = ["starting", "listening", "stopping"].includes(phase);
        input.readOnly = running || wasReadonly;
        button.setAttribute("aria-pressed", String(running));
        button.setAttribute(
          "aria-label",
          phase === "stopping" ? "取消转写" : running ? "停止听写" : "听写",
        );
        button.title = running ? "停止本机听写" : "本机听写";
        status.textContent =
          phase === "stopping" && engine === "macos-on-device"
            ? "正在这台 Mac 上转写…"
            : state.message;
        status.hidden = !status.textContent;
        status.classList.toggle("error", phase === "error");
        onActivity(running);
      },
    });
  let speech = make();
  const reflect = () => {
    button.dataset.supported = String(speech.supported);
    button.dataset.engine = engine;
    button.title = speech.supported
      ? "本机听写"
      : "本机识别不可用，在线听写已禁用";
  };
  reflect();
  const begin = () => {
    if (speech.active || !speech.supported) return;
    if (dialog.open) dialog.close();
    prefix = input.value.slice(0, input.selectionStart);
    suffix = input.value.slice(input.selectionEnd);
    wasReadonly = input.readOnly;
    speech.start();
  };
  const checkLocal = async () => {
    const generation = ++checkId;
    start.disabled = true;
    install.hidden = true;
    if (!speech.supported) return;
    if (engine === "macos-on-device") {
      const ready = nativeCapability?.model_ready === true;
      button.dataset.localAvailability = ready ? "available" : "downloadable";
      start.disabled = !ready;
      install.hidden = ready;
      if (!ready)
        $("dictation-description").textContent =
          "需先下载苹果官方中文离线模型。只下载模型，录音不上传；安装完成后可在本机转写。";
      else
        $("dictation-description").textContent =
          "中文离线模型已就绪。录音只在这台 Mac 转写，处理后移除；只需浏览器麦克风权限，不会自动发送文字。";
      return;
    }
    try {
      const availability =
        typeof recognition.available === "function"
          ? await recognition.available({
              langs: ["zh-CN"],
              processLocally: true,
            })
          : "unknown";
      if (generation !== checkId || !dialog.open) return;
      button.dataset.localAvailability = availability;
      start.disabled = !["available", "unknown"].includes(availability);
      install.hidden = !(
        availability === "downloadable" &&
        typeof recognition.install === "function"
      );
      if (start.disabled)
        $("dictation-description").textContent =
          availability === "downloadable"
            ? "需先准备中文离线语言包。仅下载模型；录音不发送到在线语音服务。"
            : "本机中文识别资源尚不可用；已禁用云端回退。";
    } catch {
      button.dataset.localAvailability = "unavailable";
      $("dictation-description").textContent =
        "无法确认本机中文识别资源，听写未启动。";
    }
  };
  button.onclick = async () => {
    if (speech.active) {
      if (phase === "stopping") speech.cancel();
      else speech.stop();
      return;
    }
    if (
      engine === "macos-on-device" &&
      nativeCapability?.model_ready === true
    ) {
      begin();
      return;
    }
    if (engine === "browser-on-device" && speech.supported) {
      // Probe only local assets; never substitute remote speech recognition.
      try {
        const availability =
          typeof recognition.available === "function"
            ? await recognition.available({
                langs: ["zh-CN"],
                processLocally: true,
              })
            : "unknown";
        if (["available", "unknown"].includes(availability)) {
          begin();
          return;
        }
      } catch {
        // Missing/unavailable resources use setup, not recording or cloud fallback.
      }
    }
    $("dictation-description").textContent =
      engine === "macos-on-device"
        ? "使用 macOS 本机离线转写。只需浏览器麦克风权限，录音不发往云端，处理后立即移除；不会自动发送文字，单次最长 60 秒。"
        : speech.supported
          ? "听写强制在本机处理，不发送音频到在线语音服务。需要本地中文语言包和麦克风权限；单次最长 60 秒，不自动发送。"
          : "本机语音识别未就绪，已禁止在线识别。";
    start.hidden = !speech.supported;
    dialog.showModal();
    void checkLocal();
  };
  install.onclick = async () => {
    install.disabled = true;
    button.dataset.localInstall = "pending";
    try {
      let done;
      if (engine === "macos-on-device") {
        $("dictation-description").textContent =
          "正在下载或准备苹果中文离线模型，尚未录音…";
        const value = await api("dictation/prepare", {}, { timeout: 270000 });
        nativeCapability = value.local_dictation;
        done = nativeCapability?.model_ready === true;
      } else done = await recognition.install({ langs: ["zh-CN"] });
      button.dataset.localInstall = done ? "success" : "incomplete";
      await checkLocal();
      if (!done)
        $("dictation-description").textContent =
          "浏览器未完成中文离线包安装，未启动录音或在线识别。";
    } catch (error) {
      $("dictation-description").textContent =
        error.message || "本地语言包准备失败，未启用云端识别。";
    } finally {
      install.disabled = false;
    }
  };
  start.onclick = () => {
    if (start.disabled) return;
    begin();
  };
  $("dictation-cancel").onclick = () => {
    dialog.close();
    input.focus();
  };
  const panel = $("chat-panel");
  const observer = new MutationObserver(() => {
    if (panel.dataset.presentation === "closed") speech.cancel();
  });
  observer.observe(panel, {
    attributes: true,
    attributeFilter: ["data-presentation"],
  });
  window.addEventListener("pagehide", () => {
    speech.cancel();
    observer.disconnect();
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted)
      observer.observe(panel, {
        attributes: true,
        attributeFilter: ["data-presentation"],
      });
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) speech.cancel();
  });
  return {
    configure(capability) {
      nativeCapability = capability;
      const next =
        capability?.available === true && NativeRecognition.supported()
          ? "macos-on-device"
          : "browser-on-device";
      if (next === engine) return;
      checkId++;
      speech.cancel();
      engine = next;
      recognition =
        engine === "macos-on-device" ? NativeRecognition : browserRecognition;
      speech = make();
      reflect();
    },
    get active() {
      return speech.active;
    },
    cancel: () => speech.cancel(),
  };
}
