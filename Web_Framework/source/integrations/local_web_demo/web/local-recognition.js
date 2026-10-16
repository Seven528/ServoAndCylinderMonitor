import { api, transcribeAudio } from "./transport.js";

export function pcmWav(channels, sampleRate = 16000) {
  const length = Math.min(channels[0]?.length || 0, sampleRate * 60);
  const bytes = new ArrayBuffer(44 + length * 2),
    view = new DataView(bytes);
  const word = (offset, text) => {
    for (let i = 0; i < text.length; i++)
      view.setUint8(offset + i, text.charCodeAt(i));
  };
  word(0, "RIFF");
  view.setUint32(4, 36 + length * 2, true);
  word(8, "WAVE");
  word(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  word(36, "data");
  view.setUint32(40, length * 2, true);
  for (let i = 0; i < length; i++) {
    let value =
      channels.reduce((sum, channel) => sum + (channel[i] || 0), 0) /
      Math.max(1, channels.length);
    value = Math.max(-1, Math.min(1, value));
    view.setInt16(44 + i * 2, value < 0 ? value * 32768 : value * 32767, true);
  }
  return new Blob([bytes], { type: "audio/wav" });
}

// Media capture stays in this page; only localhost receives PCM for the OS on-device recognizer.
export class LocalMacRecognition {
  get processLocally() {
    return true;
  }
  set processLocally(value) {
    if (value !== true) throw new Error("Only local recognition is supported");
  }
  static supported() {
    return (
      !!navigator.mediaDevices?.getUserMedia &&
      typeof MediaRecorder === "function" &&
      typeof OfflineAudioContext === "function"
    );
  }
  start() {
    this.cancelled = false;
    this.stopping = false;
    this.chunks = [];
    this.bytes = 0;
    this.id = crypto.randomUUID();
    this.controller = new AbortController();
    void this.capture();
  }
  async capture() {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true },
        video: false,
      });
      if (this.cancelled || this.stopping) {
        this.release();
        this.onend?.();
        return;
      }
      const mime = ["audio/webm;codecs=opus", "audio/mp4"].find((type) =>
        MediaRecorder.isTypeSupported(type),
      );
      this.recorder = new MediaRecorder(
        this.stream,
        mime ? { mimeType: mime } : undefined,
      );
      this.recorder.ondataavailable = (event) => {
        if (this.cancelled) return;
        this.bytes += event.data.size;
        if (this.bytes > 8 * 1024 * 1024) {
          this.fail("录音超过本机处理上限。");
          return;
        }
        this.chunks.push(event.data);
      };
      this.recorder.onstart = () => this.onstart?.();
      this.recorder.onerror = () => this.fail("录音设备不可用。");
      this.recorder.onstop = () => {
        this.release();
        if (!this.cancelled) void this.transcribe();
      };
      this.recorder.start(1000);
    } catch (error) {
      this.fail(
        error.name === "NotAllowedError" ? "未获得麦克风权限。" : error.message,
      );
    }
  }
  async transcribe() {
    try {
      const recording = new Blob(this.chunks, { type: this.recorder.mimeType });
      this.chunks = [];
      const decoder = new OfflineAudioContext(1, 1, 16000);
      const audio = await decoder.decodeAudioData(
        await recording.arrayBuffer(),
      );
      if (this.cancelled) return;
      const channels = Array.from(
        { length: Math.min(2, audio.numberOfChannels) },
        (_, index) => audio.getChannelData(index),
      );
      const wav = pcmWav(channels);
      this.processing = true;
      const result = await transcribeAudio(
        wav,
        this.id,
        this.controller.signal,
      );
      if (this.cancelled) return;
      if (result.on_device !== true || typeof result.text !== "string")
        throw new Error("本机转写结果无效。");
      this.onresult?.({
        results: [{ 0: { transcript: result.text }, isFinal: true }],
      });
      this.onend?.();
    } catch (error) {
      if (!this.cancelled) this.fail(error.message || "本机转写失败。");
    } finally {
      this.chunks = [];
    }
  }
  release() {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }
  stop() {
    this.stopping = true;
    if (this.recorder?.state === "recording") this.recorder.stop();
    this.release();
  }
  fail(message) {
    this.onerror?.({ error: "local-engine", local: true, message });
    this.abort();
  }
  abort() {
    this.cancelled = true;
    this.controller?.abort();
    if (this.recorder?.state === "recording") this.recorder.stop();
    this.release();
    this.chunks = [];
    if (this.processing)
      void api("dictation/cancel", { request_id: this.id }).catch(() => {});
  }
}
