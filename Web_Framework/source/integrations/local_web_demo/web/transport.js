export class TransportError extends Error {
  constructor(
    message,
    { status = 0, code = "network_error", retryable = false } = {},
  ) {
    super(message);
    this.name = "TransportError";
    Object.assign(this, { status, code, retryable });
  }
}
const sessionError = () =>
  new TransportError("本地服务已重启，旧结果不属于当前会话。", {
    code: "session_changed",
  });
const aborted = () => new DOMException("Request aborted", "AbortError");
export function createTransport({
  fetcher = globalThis.fetch,
  timeoutMs = 8000,
} = {}) {
  let token = "",
    serverId = null,
    handshake = null;
  async function exchange(path, options, consume, signal, timeout = timeoutMs) {
    const controller = new AbortController();
    let timedOut = false;
    const abort = () => controller.abort();
    if (signal?.aborted) throw aborted();
    signal?.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeout);
    try {
      return await consume(
        await fetcher(path, {
          ...options,
          signal: controller.signal,
          credentials: "omit",
          cache: "no-store",
          redirect: "error",
        }),
      );
    } catch (error) {
      if (signal?.aborted) throw aborted();
      if (error instanceof TransportError) throw error;
      throw new TransportError(
        timedOut
          ? "请求超时，正在等待连接恢复。"
          : error.message || "连接暂时中断。",
        {
          code: timedOut ? "request_timeout" : "network_error",
          retryable: true,
        },
      );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
  async function responseError(response) {
    let message = "请求失败",
      code = "http_error";
    try {
      const data = await response.json();
      message = data.error || message;
      code = data.code || code;
    } catch {}
    return new TransportError(`${message}（HTTP ${response.status}）`, {
      status: response.status,
      code,
      retryable:
        response.status >= 500 ||
        response.status === 408 ||
        response.status === 429,
    });
  }
  async function connect() {
    if (!handshake)
      handshake = exchange("/api/health", {}, async (response) => {
        if (!response.ok) throw await responseError(response);
        const health = await response.json();
        if (
          typeof health.token !== "string" ||
          typeof health.server_id !== "string"
        )
          throw new TransportError("本地服务版本不匹配，请重新启动演示。", {
            code: "invalid_health",
          });
        token = health.token;
        serverId = health.server_id;
        return health;
      }).finally(() => {
        handshake = null;
      });
    return handshake;
  }
  async function request(
    path,
    {
      method = "GET",
      body,
      headers = {},
      signal,
      timeout,
      allowNewSession = false,
    } = {},
    consume = (response) => response.json(),
  ) {
    if (!token) await connect();
    const expected = serverId;
    for (let attempt = 0; attempt < 2; attempt++) {
      const outcome = await exchange(
        path,
        { method, body, headers: { ...headers, "X-Demo-Token": token } },
        async (response) => {
          if (response.status === 403 && attempt === 0) {
            const error = await responseError(response);
            if (error.code !== "authentication_required") throw error;
            return { renew: true };
          }
          if (!response.ok) throw await responseError(response);
          if (expected !== serverId && !allowNewSession) throw sessionError();
          const value = await consume(response);
          if (expected !== serverId && !allowNewSession) throw sessionError();
          return { value };
        },
        signal,
        timeout,
      );
      if (!outcome.renew) return outcome.value;
      await connect();
      if (expected !== serverId && !allowNewSession) throw sessionError();
      if (method !== "GET")
        throw new TransportError(
          "访问凭据已恢复；本次操作未自动重放，请重新提交。",
          { status: 403, code: "authentication_renewed" },
        );
    }
  }
  async function api(path, body, options = {}) {
    const value = await request(
      "/api/" + path,
      body === undefined
        ? {
            allowNewSession: path === "state",
            signal: options.signal,
            timeout: options.timeout,
          }
        : {
            method: "POST",
            body: JSON.stringify(body),
            headers: { "Content-Type": "application/json" },
            timeout: options.timeout,
            signal: options.signal,
          },
    );
    if (path === "state" && value.server_id !== serverId) throw sessionError();
    return value;
  }
  async function artifactBlob(artifact, { signal } = {}) {
    if (artifact.server_id && serverId && artifact.server_id !== serverId)
      throw sessionError();
    if (!/^\/api\/artifacts\/[A-Za-z0-9_-]+$/.test(artifact.url))
      throw new TransportError("结果地址无效。", {
        code: "invalid_artifact_url",
      });
    const maximum =
      artifact.mime_type === "image/svg+xml"
        ? 128 * 1024 * 1024
        : artifact.mime_type?.startsWith("image/")
          ? 16 * 1024 * 1024
          : 32 * 1024 * 1024;
    return request(
      artifact.url,
      { signal, timeout: 30000 },
      async (response) => {
        const mime = response.headers.get("Content-Type")?.split(";")[0];
        if (mime !== artifact.mime_type)
          throw new TransportError("结果文件类型不匹配。", {
            code: "artifact_mime",
          });
        const length = Number(response.headers.get("Content-Length"));
        if (length > maximum)
          throw new TransportError("结果文件超过读取上限。", {
            code: "artifact_size",
          });
        const reader = response.body.getReader(),
          parts = [];
        let size = 0;
        try {
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            size += value.byteLength;
            if (size > maximum)
              throw new TransportError("结果文件超过读取上限。", {
                code: "artifact_size",
              });
            parts.push(value);
          }
        } finally {
          await reader.cancel().catch(() => {});
          reader.releaseLock();
        }
        if (artifact.byte_count !== undefined && size !== artifact.byte_count)
          throw new TransportError("结果文件传输不完整。", {
            code: "artifact_incomplete",
            retryable: true,
          });
        return new Blob(parts, { type: mime });
      },
    );
  }
  async function upload(file, role) {
    return request(
      "/api/upload?" + new URLSearchParams({ name: file.name, role }),
      {
        method: "POST",
        body: file,
        headers: { "Content-Type": "application/octet-stream" },
        timeout: 120000,
      },
    );
  }
  async function chat(body, onEvent, { signal } = {}) {
    if (!token) await connect();
    const expected = serverId;
    const response = await fetcher("/api/chat", {
      method: "POST",
      headers: { "X-Demo-Token": token, "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
      credentials: "omit",
      redirect: "error",
    });
    if (response.status === 403) {
      const error = await responseError(response);
      if (error.code !== "authentication_required") throw error;
      await connect();
      throw expected !== serverId
        ? sessionError()
        : new TransportError("访问凭据已恢复，请重新发送这条消息。", {
            code: "authentication_renewed",
          });
    }
    if (!response.ok) throw await responseError(response);
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let buffer = "";
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (expected !== serverId) throw sessionError();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        let index;
        while ((index = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          const lines = frame.split("\n"),
            kind = lines.find((l) => l.startsWith("event: "))?.slice(7),
            raw = lines
              .filter((l) => l.startsWith("data: "))
              .map((l) => l.slice(6))
              .join("\n");
          if (kind && raw) onEvent(kind, JSON.parse(raw));
        }
        if (done) break;
      }
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
  const transcribeAudio = (blob, id, signal) =>
    request("/api/dictation", {
      method: "POST",
      body: blob,
      headers: { "Content-Type": "audio/wav", "X-Dictation-ID": id },
      signal,
      timeout: 90000,
    });
  return {
    connect,
    api,
    artifactBlob,
    upload,
    chat,
    transcribeAudio,
    get serverId() {
      return serverId;
    },
  };
}
const client = createTransport();
export const connect = () => client.connect();
export const api = (...args) => client.api(...args);
export const upload = (...args) => client.upload(...args);
export const chat = (...args) => client.chat(...args);
export const transcribeAudio = (...args) => client.transcribeAudio(...args);
export const artifactBlob = (...args) => client.artifactBlob(...args);
const downloadUrls = new Set();
const releaseDownload = (url) => {
  if (downloadUrls.delete(url)) URL.revokeObjectURL(url);
};
if (typeof window !== "undefined")
  window.addEventListener("pagehide", () => {
    for (const url of downloadUrls) releaseDownload(url);
  });
export function bindDownload(button, artifact, onError, onStart = () => {}) {
  button.hidden = !artifact;
  button.onclick = async (event) => {
    event.preventDefault();
    if (button.dataset.downloading || !artifact) return;
    button.dataset.downloading = "true";
    button.disabled = true;
    try {
      onStart();
      const blob = await artifactBlob(artifact);
      saveDownload(blob, artifact.name || "pcb-result");
    } catch (error) {
      onError(error);
    } finally {
      delete button.dataset.downloading;
      button.disabled = false;
    }
  };
}
export function saveDownload(blob, name) {
  const url = URL.createObjectURL(blob);
  downloadUrls.add(url);
  const link = document.createElement("a");
  try {
    link.href = url;
    link.download = name;
    document.body.append(link);
    link.click();
  } finally {
    link.remove();
    setTimeout(() => releaseDownload(url), 1000);
  }
}
