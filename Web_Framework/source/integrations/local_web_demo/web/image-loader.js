import { artifactBlob, TransportError } from "./transport.js";

async function decodeImage(url, signal) {
  const image = new Image();
  const abort = () => {
    image.src = "";
  };
  signal.addEventListener("abort", abort, { once: true });
  try {
    image.src = url;
    await image.decode();
    if (!image.naturalWidth) throw Error("Empty image");
  } catch (error) {
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    throw new TransportError("PNG 解码失败。", {
      code: "image_decode",
      retryable: true,
    });
  } finally {
    signal.removeEventListener("abort", abort);
    image.src = "";
  }
}

export function createImageLoader({
  fetchBlob = artifactBlob,
  decode = decodeImage,
  createURL = (blob) => URL.createObjectURL(blob),
  revokeURL = (url) => URL.revokeObjectURL(url),
  onState = () => {},
  onReady = () => {},
  schedule = setTimeout,
  unschedule = clearTimeout,
  retryDelays = [400, 1200],
} = {}) {
  let artifact = null,
    generation = 0,
    controller = null,
    timer = null,
    current = null,
    pending = null,
    phase = "idle",
    attempt = 0;
  const release = (record) => {
    if (record && !record.released) {
      record.released = true;
      revokeURL(record.url);
    }
  };
  const emit = (value, error = null) => {
    phase = value;
    onState({ phase, artifact, error, hasPrevious: !!current });
  };
  function cancel() {
    controller?.abort();
    controller = null;
    if (timer !== null) unschedule(timer);
    timer = null;
    release(pending);
    pending = null;
  }
  async function load(version, index) {
    if (version !== generation || !artifact) return;
    attempt = index;
    const requested = artifact;
    const abort = new AbortController();
    controller = abort;
    let record = null;
    emit(index ? "retrying" : "loading");
    try {
      const blob = await fetchBlob(requested, { signal: abort.signal });
      if (version !== generation || abort.signal.aborted) return;
      record = { url: createURL(blob), released: false };
      pending = record;
      await decode(record.url, abort.signal);
      if (version !== generation || abort.signal.aborted) {
        release(record);
        return;
      }
      const previous = current;
      current = record;
      pending = null;
      onReady(record.url, requested);
      release(previous);
      emit("ready");
    } catch (error) {
      release(record);
      if (pending === record) pending = null;
      if (version !== generation || abort.signal.aborted) return;
      if (error.retryable && index < retryDelays.length) {
        emit("retrying", error);
        timer = schedule(() => {
          timer = null;
          void load(version, index + 1);
        }, retryDelays[index]);
      } else emit("error", error);
    } finally {
      if (controller === abort) controller = null;
    }
  }
  return {
    show(value) {
      const same =
        value &&
        artifact &&
        value.id === artifact.id &&
        value.url === artifact.url;
      if (same) return;
      cancel();
      generation++;
      artifact = value;
      if (!value) {
        release(current);
        current = null;
        emit("idle");
        return;
      }
      void load(generation, 0);
    },
    retry() {
      if (!artifact) return;
      cancel();
      generation++;
      void load(generation, 0);
    },
    recover() {
      if (phase === "error" && artifact?.url) this.retry();
    },
    displayError() {
      if (phase !== "ready") return;
      const error = new TransportError("图片显示失败。", {
        code: "image_display",
        retryable: true,
      });
      if (attempt < retryDelays.length) {
        emit("retrying", error);
        timer = schedule(() => {
          timer = null;
          void load(generation, attempt + 1);
        }, retryDelays[attempt]);
      } else emit("error", error);
    },
    dispose() {
      cancel();
      generation++;
      artifact = null;
      release(current);
      current = null;
      emit("idle");
    },
    get url() {
      return current?.url;
    },
    get phase() {
      return phase;
    },
  };
}
