import { api, chat } from "./transport.js";
import { markdown } from "./text.js";
import { contextLabel } from "./result-state.js";
import { createModelPicker } from "./model-picker.js";
import { chatConnection } from "./chat-connection.js";
import { createDictationControl } from "./dictation-control.js";
import { renderMessageDownloads } from "./message-downloads.js";
import { chatScopeRequest, supportsExplicitScope } from "./canvas-scope.js";
export function createChatPanel(refresh, onReference, readCanvas) {
  const $ = (id) => document.getElementById(id);
  const picker = createModelPicker();
  let pending = false,
    remoteBusy = false,
    connected = false,
    scopeReady = false;
  let epoch = 0,
    controller = null;
  const messageNodes = new Map();
  let dictation = null;
  const updateSend = () => {
    $("send").disabled =
      pending ||
      remoteBusy ||
      !connected ||
      !scopeReady ||
      !picker.valid ||
      !!dictation?.active;
    document
      .querySelector(".compose-box")
      .setAttribute("aria-busy", String(pending || remoteBusy));
  };
  dictation = createDictationControl(updateSend);
  const quickPrompts = document.querySelector(".quick-prompts");
  document.addEventListener("click", (event) => {
    if (!event.composedPath().includes(quickPrompts)) quickPrompts.open = false;
  });
  quickPrompts.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && quickPrompts.open) {
      event.preventDefault();
      event.stopPropagation();
      quickPrompts.open = false;
      quickPrompts.querySelector("summary").focus();
    }
  });
  const setConnection = (health, reachable) => {
    dictation.configure(health?.local_dictation);
    const status = chatConnection(health, reachable);
    connected = status.online;
    scopeReady = supportsExplicitScope(health);
    $("chat-indicator").textContent = status.label;
    $("chat-indicator").className = "connection-label " + status.label;
    $("chat-indicator").title = status.description;
    updateSend();
  };
  const confirmBatch = (files, message) =>
    new Promise((resolve) => {
      const dialog = $("batch-scope-dialog");
      $("batch-scope-message").textContent = message.slice(0, 200);
      $("batch-scope-files").replaceChildren(
        ...files.map((file) => {
          const item = document.createElement("li");
          item.textContent = `${file.role === "pcb" ? "PCB" : "Holder"} · ${file.name}`;
          return item;
        }),
      );
      dialog.returnValue = "cancel";
      dialog.onclose = () => {
        dialog.onclose = null;
        resolve(dialog.returnValue === "confirm");
      };
      dialog.showModal();
    });
  const send = async (batchRequested = false) => {
    const message = $("message").value.trim();
    if (!message || pending || remoteBusy || dictation.active) return;
    if (!connected || !picker.valid || !scopeReady) {
      $("chat-error").hidden = false;
      $("chat-error").textContent = scopeReady
        ? "当前连接或模型不可用，请恢复后再发送。"
        : "本地服务尚未启用主画布范围保护，请完成服务更新后再发送。";
      return;
    }
    const canvas = readCanvas();
    let scope = chatScopeRequest(canvas);
    if (batchRequested === true) {
      if (!canvas.batchFiles.length) {
        $("chat-error").hidden = false;
        $("chat-error").textContent = "请先勾选需要批量处理的文件。";
        return;
      }
      if (!(await confirmBatch(canvas.batchFiles, message))) return;
      scope = {
        ...(scope || { presentation_id: null }),
        batch_confirmed: true,
        batch_file_ids: canvas.batchFiles.map((file) => file.id),
      };
    }
    pending = true;
    const generation = epoch;
    controller = new AbortController();
    $("message").value = "";
    $("chat-error").hidden = true;
    $("send").disabled = true;
    $("stop-chat").hidden = false;

    try {
      await chat(
        {
          message,
          request_id: crypto.randomUUID(),
          settings: picker.read(),
          scope,
        },
        (kind, data) => {
          if (generation !== epoch) return;
          if (kind === "error") {
            $("chat-error").hidden = false;
            $("chat-error").textContent = data.message;
            // Host scope rejection happens before a turn/message is admitted.
            // Keep the draft so the user can clarify a name instead of retyping.
            if (!data.request_id && !$("message").value)
              $("message").value = message;
          }

          refresh();
        },
        { signal: controller.signal },
      );
    } catch (e) {
      if (generation !== epoch) return;
      $("chat-error").hidden = false;
      $("chat-error").textContent = e.message;
    } finally {
      if (generation === epoch) {
        pending = false;
        controller = null;
        refresh();
      }
    }
  };
  $("send").onclick = () => send();
  $("batch-chat").onclick = () => {
    quickPrompts.open = false;
    if (!$("message").value.trim()) {
      $("chat-error").hidden = false;
      $("chat-error").textContent = "先输入批量分析要求，再确认本轮文件清单。";
      $("message").focus();
      return;
    }
    void send(true);
  };
  $("message").onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      send();
    }
  };
  document.querySelectorAll("[data-prompt]").forEach(
    (b) =>
      (b.onclick = () => {
        if (dictation.active) return;
        b.closest("details")?.removeAttribute("open");
        $("message").value = b.dataset.prompt;
        send();
      }),
  );
  $("stop-chat").onclick = async () => {
    try {
      await api("chat/cancel", {});
    } catch (e) {
      $("chat-error").hidden = false;
      $("chat-error").textContent = e.message;
    }
  };
  return {
    setConnection,
    reset() {
      dictation.cancel();
      epoch++;
      controller?.abort();
      controller = null;
      pending = false;
      messageNodes.clear();
      $("messages").replaceChildren();
      $("chat-error").hidden = true;
    },
    initialize(health, snapshot) {
      picker.initialize(health.models, snapshot.settings || health.defaults);
      setConnection(health, true);
      if (health.chat_error) {
        $("chat-error").hidden = false;
        $("chat-error").textContent = health.chat_error;
      }
    },
    render(snapshot) {
      const box = $("messages"),
        nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 90;
      const messages = snapshot.messages || [];
      const availableViews = new Set(
        (snapshot.jobs || [])
          .flatMap((job) => job.presentations || [])
          .map((view) => view.id),
      );
      if (messages.length) box.querySelector(".welcome")?.remove();
      const ids = new Set(messages.map((m) => m.id));
      for (const [id, item] of messageNodes)
        if (!ids.has(id)) {
          item.node.remove();
          messageNodes.delete(id);
        }
      let changed = false;
      for (const m of messages) {
        let item = messageNodes.get(m.id);
        if (!item) {
          const node = document.createElement("article"),
            label = document.createElement("span"),
            content = document.createElement("div"),
            refs = document.createElement("div"),
            error = document.createElement("p"),
            scope = document.createElement("small"),
            downloads = document.createElement("div");
          node.className = "message " + m.role;
          label.className = "message-label";
          label.textContent =
            m.role === "user" ? "你" : "MOE6 CD Auto Analysis Agent";
          refs.className = "analysis-refs";
          error.className = "chat-error";
          downloads.className = "message-downloads";
          scope.className = "message-scope";
          node.append(label, scope, content, refs, downloads, error);
          box.append(node);
          item = {
            node,
            content,
            refs,
            downloads,
            error,
            scope,
            signature: "",
          };
          messageNodes.set(m.id, item);
        }
        const sig = JSON.stringify([m, snapshot.file_revision || 0]);
        if (sig === item.signature) continue;
        item.signature = sig;
        changed = true;
        item.scope.hidden = !m.scope || m.role !== "assistant";
        item.scope.textContent = m.scope?.label || "";
        item.scope.title = item.scope.textContent;
        if (m.role === "assistant")
          item.content.innerHTML = markdown(
            m.text || (m.status === "running" ? "正在思考…" : ""),
          );
        else item.content.textContent = m.text;
        item.error.textContent = m.error || "";
        item.error.hidden = !m.error;
        renderMessageDownloads(item.downloads, m, snapshot, (error) => {
          item.error.textContent = error.message;
          item.error.hidden = false;
        });
        const refsig = JSON.stringify([
          m.analysis_refs || [],
          snapshot.file_revision || 0,
        ]);
        if (refsig !== item.refsig) {
          item.refsig = refsig;
          item.refs.replaceChildren();
          for (const ref of m.analysis_refs || []) {
            const b = document.createElement("button"),
              file = document.createElement("span"),
              config = document.createElement("small");
            b.className = "analysis-ref";
            b.disabled = !availableViews.has(ref.presentation_id);
            b.title = contextLabel(ref.context);
            file.textContent = ref.context.file_name;
            config.textContent = contextLabel(ref.context, { file: false });
            if (b.disabled) {
              config.textContent += " · 结果已移除";
              b.title += "（源文件已从当前工作区删除）";
            }
            b.append(file, config);
            b.onclick = () => onReference(ref);
            item.refs.append(b);
          }
        }
      }
      if (changed && nearBottom) box.scrollTop = box.scrollHeight;
      remoteBusy = !!snapshot.chat_busy;
      $("stop-chat").hidden = !(remoteBusy || pending);
      updateSend();
    },
  };
}
