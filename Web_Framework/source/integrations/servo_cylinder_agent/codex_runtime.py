"""Codex transport adapted from local_web_demo/codex_bridge.py for equipment Q&A."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None  # Python 3.9: only MCP section names are needed below.


def _configured_mcp_names(text):
    if tomllib is not None:
        return list(tomllib.loads(text).get('mcp_servers', {}))
    names = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        match = re.match(r'^\[mcp_servers\.(?:"([A-Za-z0-9_-]+)"|([A-Za-z0-9_-]+))(?:\.|\])', line)
        if match:
            names.add(match.group(1) or match.group(2))
        elif re.match(r'^(?:\[mcp_servers|mcp_servers[. =])', line):
            raise BridgeError('Python 3.9 无法安全读取当前 MCP 配置格式，请使用 Python 3.11+。')
    return sorted(names)

DEFAULTS = {"model": "gpt-6.1-sol", "effort": "xhigh", "speed": "priority"}
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
BUNDLED = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"


class BridgeError(RuntimeError):
    pass


def runtime_path():
    explicit = os.environ.get("SERVO_AGENT_CODEX_BIN")
    candidate = explicit or (
        BUNDLED if Path(BUNDLED).is_file() else shutil.which("codex")
    )
    if (
        not candidate
        or not Path(candidate).is_file()
        or not os.access(candidate, os.X_OK)
    ):
        raise BridgeError(
            "找不到可用的 Codex。请通过 SERVO_AGENT_CODEX_BIN 配置新版运行程序。"
        )
    return str(Path(candidate).resolve())


def isolated_args():
    args = []
    for feature in (
        "apps",
        "plugins",
        "hooks",
        "multi_agent",
        "shell_tool",
        "unified_exec",
        "browser_use",
        "browser_use_external",
        "computer_use",
        "in_app_browser",
        "image_generation",
        "view_image",
        "memories",
        "chronicle",
        "skill_search",
        "skill_mcp_dependency_install",
        "workspace_dependencies",
        "sleep_tool",
        "goals",
    ):
        args += ["--disable", feature]
    args += ["--enable", "skip_host_skill_discovery", "--enable", "fast_mode"]
    for value in (
        'web_search="disabled"',
        'sandbox_mode="read-only"',
        'approval_policy="never"',
        'approvals_reviewer="user"',
        "notify=[]",
        'history.persistence="none"',
    ):
        args += ["-c", value]
    # Only identifiers are read; never copy credentials into arguments or logs.
    config_path = (
        Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    )
    if config_path.is_file():
        names = _configured_mcp_names(config_path.read_text(encoding="utf-8"))
        for name in names:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                raise BridgeError("当前 MCP 配置名称不能被安全隔离，演示未启动。")
            args += ["-c", f"mcp_servers.{name}.enabled=false"]
    return args


class CodexBridge:
    def __init__(self, defaults=None):
        self.defaults = dict(defaults or DEFAULTS)
        self.binary = runtime_path()
        self.version = subprocess.check_output(
            [self.binary, "--version"], text=True, timeout=10
        ).strip()
        self.workspace = tempfile.TemporaryDirectory(prefix="servo-web-app-server-")
        self.process = subprocess.Popen(
            [self.binary, "app-server", "--listen", "stdio://", *isolated_args()],
            cwd=self.workspace.name,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            start_new_session=True,
        )
        self.write_lock = threading.Lock()
        self.lock = threading.RLock()
        self.pending = {}
        self.inboxes = {}
        self.counter = 0
        self.closed = False
        self.diagnostics = deque(maxlen=20)
        self.read_thread = threading.Thread(target=self._read, daemon=True)
        self.error_thread = threading.Thread(target=self._drain_errors, daemon=True)
        self.read_thread.start()
        self.error_thread.start()
        try:
            self.request(
                "initialize",
                {
                    "clientInfo": {"name": "servo_monitor_agent", "version": "0.3"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            self.notify("initialized", {})
            self.models = self._models()
            if defaults is None and self.models:
                preferred = next((m for m in self.models if m.get('is_default')), self.models[0])
                self.defaults = {'model': preferred['id'], 'effort': preferred['default_effort'], 'speed': 'default'}
            self.validate(self.defaults)
            login = subprocess.run(
                [self.binary, "login", "status"],
                capture_output=True,
                timeout=15,
                check=False,
            )
            if login.returncode:
                raise BridgeError("Codex 尚未登录。请在本机登录后重启演示。")
        except Exception:
            self.close()
            raise

    def _write(self, message):
        with self.write_lock:
            if self.closed or self.process.poll() is not None:
                raise BridgeError("Codex 连接已结束，请重新连接。")
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def request(self, method, params, timeout=30):
        with self.lock:
            self.counter += 1
            rid = self.counter
            response = queue.Queue(maxsize=1)
            self.pending[rid] = response
        try:
            self._write({"id": rid, "method": method, "params": params})
            try:
                message = response.get(timeout=timeout)
            except queue.Empty:
                raise BridgeError(
                    f"Codex 未及时完成 {method}，本次未切换到其他模型。"
                ) from None
            if "error" in message:
                error = message["error"]
                raise BridgeError(str(error.get("message", "Codex 请求失败"))[:500])
            return message.get("result", {})
        finally:
            with self.lock:
                self.pending.pop(rid, None)

    def notify(self, method, params):
        self._write({"method": method, "params": params})

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if "id" in message and "method" not in message:
                    with self.lock:
                        receiver = self.pending.get(message["id"])
                    if receiver:
                        receiver.put(message)
                    continue
                params = message.get("params") or {}
                thread_id = params.get("threadId") or (params.get("thread") or {}).get(
                    "id"
                )
                with self.lock:
                    inbox = self.inboxes.get(thread_id)
                if inbox:
                    inbox.put(message)
                elif "id" in message:
                    self._write(
                        {
                            "id": message["id"],
                            "error": {
                                "code": -32601,
                                "message": "Tool not available in this demonstration",
                            },
                        }
                    )
        finally:
            with self.lock:
                failure = {"error": {"message": "Codex 连接中断；分析记录仍保留。"}}
                for receiver in self.pending.values():
                    try:
                        receiver.put_nowait(failure)
                    except queue.Full:
                        pass
                for inbox in self.inboxes.values():
                    inbox.put({"method": "_connection_closed"})

    def _drain_errors(self):
        for line in self.process.stderr:
            self.diagnostics.append(line[:600])

    def _models(self):
        models = []
        cursor = None
        while True:
            params = {"limit": 100, "includeHidden": False}
            if cursor:
                params["cursor"] = cursor
            result = self.request("model/list", params)
            for model in result.get("data", []):
                efforts = [
                    item["reasoningEffort"]
                    for item in model.get("supportedReasoningEfforts", [])
                    if item["reasoningEffort"] in EFFORTS
                ]
                tiers = [{"id": "default", "name": "标准"}]
                tiers += [
                    {"id": t["id"], "name": t["name"]}
                    for t in model.get("serviceTiers", [])
                    if t["id"] == "priority"
                ]
                if efforts:
                    models.append(
                        {
                            "id": model["model"],
                            "name": model["displayName"],
                            "is_default": bool(model.get('isDefault')),
                            "default_effort": model.get('defaultReasoningEffort') if model.get('defaultReasoningEffort') in efforts else efforts[0],
                            "efforts": efforts,
                            "speeds": tiers,
                        }
                    )
            cursor = result.get("nextCursor")
            if not cursor:
                return models

    def validate(self, settings):
        if not isinstance(settings, dict) or set(settings) != set(DEFAULTS):
            raise BridgeError("请选择模型、推理强度和速度。")
        model = next((m for m in self.models if m["id"] == settings["model"]), None)
        if not model:
            raise BridgeError("当前运行程序或账号不提供所选模型；不会自动替换。")
        if settings["effort"] not in model["efforts"]:
            raise BridgeError("这个模型不支持所选推理强度，请重新选择。")
        if settings["speed"] not in [t["id"] for t in model["speeds"]]:
            raise BridgeError("这个模型不支持所选速度，请重新选择。")
        return dict(settings)

    def start_thread(self, settings, instructions, tools):
        self.validate(settings)
        result = self.request(
            "thread/start",
            {
                "model": settings["model"],
                "allowProviderModelFallback": False,
                "serviceTier": settings["speed"],
                "ephemeral": True,
                "cwd": self.workspace.name,
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "baseInstructions": instructions,
                "developerInstructions": instructions,
                "config": {"model_reasoning_effort": settings["effort"]},
                "selectedCapabilityRoots": [],
                "dynamicTools": tools,
                "serviceName": "servo_monitor_agent",
            },
        )
        if (
            result.get("model") != settings["model"]
            or result.get("reasoningEffort") != settings["effort"]
        ):
            raise BridgeError("Codex 返回的模型或推理强度与选择不同，本次未开始对话。")
        tier = result.get("serviceTier") or "default"
        if tier != settings["speed"]:
            raise BridgeError("Codex 返回的速度与选择不同，本次未开始对话。")
        thread_id = result["thread"]["id"]
        if result["thread"].get("ephemeral") is not True:
            raise BridgeError("Codex 没有确认临时会话，本次未开始对话。")
        with self.lock:
            self.inboxes[thread_id] = queue.Queue(maxsize=2048)
        return thread_id, {
            "model": result["model"],
            "effort": result["reasoningEffort"],
            "speed": tier,
        }

    def release_thread(self, thread_id):
        """Detach only this bridge's owned ephemeral thread; never delete history."""
        if not thread_id:
            return
        try:
            self.request("thread/unsubscribe", {"threadId": thread_id}, timeout=10)
        finally:
            with self.lock:
                self.inboxes.pop(thread_id, None)

    def interrupt(self, thread_id, turn_id):
        if thread_id and turn_id:
            self.request(
                "turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=10
            )

    def run_turn(self, session, text, settings, tool_handler, emit):
        self.validate(settings)
        inbox = self.inboxes.get(session["thread_id"])
        if inbox is None:
            raise BridgeError("会话连接已失效，请重新开始。")
        while not inbox.empty():
            inbox.get_nowait()
        result = self.request(
            "turn/start",
            {
                "threadId": session["thread_id"],
                "input": [{"type": "text", "text": text}],
                "model": settings["model"],
                "effort": settings["effort"],
                "serviceTierForTurn": settings["speed"],
                "summary": "none",
            },
        )
        turn_id = result["turn"]["id"]
        session["turn_id"] = turn_id
        session["applied_settings"] = dict(settings)
        emit(
            "turn.started",
            {"turn_id": turn_id, "settings": settings, "runtime_version": self.version},
        )
        if session["cancel"].is_set():
            self.interrupt(session["thread_id"], turn_id)
        deadline = time.monotonic() + 150
        texts = {}
        calls = {}
        tool_count = 0
        while time.monotonic() < deadline:
            try:
                message = inbox.get(timeout=1)
            except queue.Empty:
                continue
            method = message.get("method", "")
            params = message.get("params") or {}
            event_turn = params.get("turnId") or (params.get("turn") or {}).get("id")
            if event_turn and event_turn != turn_id:
                continue
            if method == "_connection_closed":
                raise BridgeError("Codex 连接中断；不会用固定话术替代回复。")
            if method == "item/tool/call":
                call_id = params["callId"]
                if call_id not in calls:
                    tool_count += 1
                    if session["cancel"].is_set() or tool_count > 48:
                        output = {
                            "ok": False,
                            "error": "Turn interrupted or tool budget exceeded. Do not claim analysis succeeded.",
                        }
                    else:
                        try:
                            output = tool_handler(
                                params["tool"], params.get("arguments") or {}
                            )
                        except (ValueError, TypeError, KeyError) as error:
                            output = {
                                "ok": False,
                                "error": str(error),
                                "instruction": "Explain or clarify naturally; do not claim the update succeeded.",
                            }
                    calls[call_id] = {
                        "success": bool(output.get("ok", True)),
                        "contentItems": [
                            {
                                "type": "inputText",
                                "text": json.dumps(output, ensure_ascii=False),
                            }
                        ],
                    }
                self._write({"id": message["id"], "result": calls[call_id]})
            elif "id" in message:
                self._write(
                    {
                        "id": message["id"],
                        "error": {
                            "code": -32601,
                            "message": "Only the registered equipment tools are available",
                        },
                    }
                )
            elif method == "item/agentMessage/delta":
                item_id = params["itemId"]
                texts[item_id] = texts.get(item_id, "") + params["delta"]
                emit("message.delta", {"item_id": item_id, "delta": params["delta"]})
            elif (
                method == "item/completed"
                and params.get("item", {}).get("type") == "agentMessage"
            ):
                item = params["item"]
                item_id = item["id"]
                texts[item_id] = item.get("text", texts.get(item_id, ""))
                emit("message.completed", {"item_id": item_id, "text": texts[item_id]})
            elif method == "item/started":
                kind = params.get("item", {}).get("type")
                if kind in (
                    "commandExecution",
                    "fileChange",
                    "mcpToolCall",
                    "webSearch",
                    "collabAgentToolCall",
                ):
                    self.interrupt(session["thread_id"], turn_id)
                    raise BridgeError("本轮调用超出设备问答范围，已停止。")
                if kind == "reasoning":
                    emit("status", {"text": "正在思考"})
            elif method == "turn/completed":
                turn = params["turn"]
                status = turn.get("status", "completed")
                if status == "failed":
                    error = turn.get("error") or {}
                    raise BridgeError(
                        str(error.get("message", "Codex 未完成本轮回复"))[:400]
                    )
                return {
                    "status": status,
                    "text": "\n\n".join(texts.values()),
                    "turn_id": turn_id,
                    "settings": dict(settings),
                    "tool_calls": tool_count,
                }
        self.interrupt(session["thread_id"], turn_id)
        raise BridgeError("本轮等待超时，已停止；已记录的结果仍保留。")

    def release(self, thread_id):
        with self.lock:
            self.inboxes.pop(thread_id, None)
        try:
            self.request("thread/unsubscribe", {"threadId": thread_id}, timeout=5)
        except BridgeError:
            pass

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.read_thread.join(timeout=5)
        self.error_thread.join(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()
        self.workspace.cleanup()
