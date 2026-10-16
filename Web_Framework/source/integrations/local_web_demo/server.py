"""Local-only HTTP shell. Analysis and chat are independently usable."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import signal
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from integrations.azure_agent.pcbuni_adapter.configuration import strict_json

from .analysis import APP, AnalysisService
from .codex_bridge import DEFAULTS, BridgeError
from .conversation import Conversation
from .image_exports import ImageExports
from .local_speech import LocalSpeech, SpeechError
from .pressure_picking import PressurePicking
from .storage import DemoError, FileStore, WorkspaceBusy

REPO = Path(__file__).resolve().parents[2]
SAMPLES = (
    ("data/PCB_EP8000_1039N05842_v03_pnl.uni", "pcb"),
    ("data/Holder_EP8000_1039N06549_v01_pnl.uni", "holder"),
)


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, port, executable, root, *, with_codex=True):
        try:
            super().__init__(("127.0.0.1", port), Handler)
        except OSError as error:
            if error.errno != 48 and error.errno != 98:
                raise
            super().__init__(("127.0.0.1", 0), Handler)
        self.token = secrets.token_urlsafe(32)
        self.instance_id = uuid.uuid4().hex
        self.selection = {"pcb_ids": [], "holder_id": None}
        self._http_error_count = 0
        self._http_error_lock = threading.Lock()
        self.store = FileStore(root)
        self.analysis = AnalysisService(self.store, executable)
        self.exports = ImageExports(self.store, self.analysis)
        self.picking = PressurePicking(self.store, self.analysis)
        self.speech = LocalSpeech(REPO / "build/local-web-demo/speech/PCBLocalSpeech")
        self.conversation = (
            Conversation(self.store, self.analysis) if with_codex else None
        )
        self.sample_ids = []
        self.sample_lock = threading.Lock()

    def state(self):
        with self.analysis.lock:
            conversation = (
                self.conversation.snapshot()
                if self.conversation
                else {"messages": [], "settings": DEFAULTS}
            )
            return {
                "server_id": self.instance_id,
                "session_id": conversation.get("session_id", self.instance_id),
                "selection": self.selection,
                "files": self.store.listing(),
                "file_revision": self.store.file_revision,
                **self.analysis.snapshot(),
                **conversation,
            }

    def remove_file(self, body):
        if set(body) != {"file_id"} or not isinstance(body["file_id"], str):
            raise DemoError("删除只接受当前会话的 file_id。")
        chat = self.conversation
        if chat and not chat.lock.acquire(blocking=False):
            raise WorkspaceBusy("Agent 正在回答，请完成或停止后再删除文件。")
        try:
            with self.analysis.lock:
                fid = body["file_id"]
                result = self.analysis.remove_file(fid)
                self.selection = {
                    "pcb_ids": [x for x in self.selection["pcb_ids"] if x != fid],
                    "holder_id": None
                    if self.selection["holder_id"] == fid
                    else self.selection["holder_id"],
                }
                if chat:
                    chat.selection = self.selection
                state = self.state()
                if chat:
                    state["chat_busy"] = (
                        False  # The turn lock is owned by this removal.
                    )
                return {"ok": True, **result, "state": state}
        finally:
            if chat:
                chat.lock.release()

    def http_error(self, status, code, resource):
        with self._http_error_lock:
            if self._http_error_count >= 32:
                return
            self._http_error_count += 1
        print(
            json.dumps({"http_status": status, "code": code, "resource": resource}),
            file=sys.stderr,
            flush=True,
        )

    def samples(self):
        with self.sample_lock:
            if not self.sample_ids:
                for relative, role in SAMPLES:
                    path = REPO / relative
                    with path.open("rb") as stream:
                        item = self.store.upload(
                            stream, path.stat().st_size, path.name, role
                        )
                    self.sample_ids.append(item["id"])
            return {"files": self.store.listing(), "sample_ids": self.sample_ids}

    def close_owned(self):
        self.speech.cancel()
        self.exports.close()
        if self.conversation:
            try:
                self.conversation.stop()
            except (BridgeError, OSError):
                pass
        try:
            self.analysis.close()
        finally:
            if self.conversation:
                self.conversation.close()
            self.server_close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(650)

    def allowed_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def authenticated(self):
        token = self.headers.get("X-Demo-Token", "")
        return bool(token) and secrets.compare_digest(token, self.server.token)

    def send_headers(self, code, mime, length=None, *, download=None):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        if download:
            self.send_header(
                "Content-Disposition", "attachment; filename*=UTF-8''" + quote(download)
            )
        if length is not None:
            self.send_header("Content-Length", str(length))
        else:
            self.send_header("Connection", "close")
        self.end_headers()

    def respond(self, code, body):
        raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        self.send_headers(code, "application/json; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def fail(self, status, code, message, resource="api"):
        self.server.http_error(status, code, resource)
        return self.respond(status, {"error": message, "code": code})

    def do_GET(self):
        try:
            self.get()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except (DemoError, ValueError, KeyError, OSError) as error:
            self.respond(400, {"error": str(error)[:500]})

    def get(self):
        if not self.allowed_host():
            return self.respond(403, {"error": "仅支持本机访问。"})
        url = urlsplit(self.path)
        path, query = url.path, parse_qs(url.query)
        if path == "/api/health":
            chat = self.server.conversation
            bridge = chat.bridge if chat else None
            return self.respond(
                200,
                {
                    "token": self.server.token,
                    "server_id": self.server.instance_id,
                    "native_ready": not self.server.analysis.error,
                    "image_export_formats": self.server.exports.formats,
                    "single_board_surface_views": getattr(
                        self.server.analysis, "single_board_surfaces", []
                    ),
                    "local_dictation": self.server.speech.capability,
                    "canvas_scope_version": 1,
                    "explicit_file_scope_version": 1,
                    "file_removal_version": 1,
                    "pressure_picking_version": 1,
                    "pressure_component_highlight_version": 1,
                    "native_error": self.server.analysis.error,
                    "chat_ready": bridge is not None and bridge.process.poll() is None,
                    "chat_error": chat.error if chat else "对话未启用",
                    "models": bridge.models if bridge else [],
                    "defaults": DEFAULTS,
                    "runtime_version": bridge.version if bridge else None,
                },
            )
        if path.startswith("/api/"):
            if not self.authenticated():
                return self.fail(
                    403,
                    "authentication_required",
                    "访问凭据已失效，需要重新连接。",
                    "artifact" if path.startswith("/api/artifacts/") else "api",
                )
            if path == "/api/state":
                return self.respond(200, self.server.state())
            if path == "/api/pressure-picking":
                if set(query) - {"presentation_id", "head_index", "offset"} or any(
                    len(values) != 1 for values in query.values()
                ):
                    raise DemoError("压棒点选参数无效。")
                return self.respond(
                    200,
                    self.server.picking.read(
                        query.get("presentation_id", [""])[0],
                        int(query["head_index"][0]) if "head_index" in query else None,
                        int(query.get("offset", [0])[0]),
                    ),
                )
            if path == "/api/report":
                options = {
                    "offset": int(query.get("offset", [0])[0]),
                    "limit": int(query.get("limit", [25])[0]),
                }
                if query.get("refdes"):
                    options["refdes"] = query["refdes"][0]
                return self.respond(
                    200, self.server.store.report(query.get("id", [""])[0], **options)
                )
            if path.startswith("/api/artifacts/"):
                try:
                    item = self.server.store.artifact(path.rsplit("/", 1)[-1])
                except DemoError:
                    return self.fail(
                        404,
                        "artifact_not_found",
                        "结果文件不属于当前会话。",
                        "artifact",
                    )
                file = item["path"]
                try:
                    stream = file.open("rb")
                except FileNotFoundError:
                    return self.fail(
                        404,
                        "artifact_missing",
                        "结果文件已不存在，请检查保存目录。",
                        "artifact",
                    )
                except OSError:
                    return self.fail(
                        500, "artifact_unreadable", "结果文件暂时无法读取。", "artifact"
                    )
                with stream:
                    self.send_headers(
                        200,
                        {
                            ".png": "image/png",
                            ".svg": "image/svg+xml; charset=utf-8",
                            ".json": "application/json; charset=utf-8",
                        }.get(file.suffix, "application/octet-stream"),
                        os.fstat(stream.fileno()).st_size,
                        download=file.name if "download" in query else None,
                    )
                    while chunk := stream.read(65536):
                        self.wfile.write(chunk)
                return
            return self.respond(404, {"error": "接口不存在。"})
        name = "index.html" if path == "/" else path.lstrip("/")
        file = (APP / "web" / name).resolve()
        if (
            not file.is_relative_to(APP / "web")
            or file.suffix not in {".html", ".css", ".js", ".svg"}
            or not file.is_file()
        ):
            return self.respond(404, {"error": "页面不存在。"})
        raw = file.read_bytes()
        self.send_headers(
            200,
            (mimetypes.guess_type(file.name)[0] or "text/plain") + "; charset=utf-8",
            len(raw),
        )
        self.wfile.write(raw)

    def read_body(self):
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 4 * 1024 * 1024:
            raise DemoError("请求大小无效。")
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise DemoError("请求格式无效。")
        body = strict_json(self.rfile.read(size).decode("utf-8"))
        if not isinstance(body, dict):
            raise DemoError("请求必须是对象。")
        return body

    def do_POST(self):
        try:
            self.post()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except SpeechError as error:
            self.fail(error.status, error.code, str(error), "dictation")
        except WorkspaceBusy as error:
            self.fail(409, "workspace_busy", str(error), "files")
        except (DemoError, ValueError, KeyError, OSError, TypeError) as error:
            self.respond(400, {"error": str(error)[:500]})

    def post(self):
        port = self.server.server_address[1]
        if not self.allowed_host() or self.headers.get("Origin") not in {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        }:
            return self.fail(403, "origin_denied", "请从本机网页操作。")
        if not self.authenticated():
            return self.fail(
                403, "authentication_required", "访问凭据已失效，需要重新连接。"
            )
        url = urlsplit(self.path)
        path = url.path
        if path == "/api/dictation":
            if self.headers.get("Content-Type") != "audio/wav":
                raise DemoError("听写只接受本机 PCM WAV。")
            return self.respond(
                200,
                self.server.speech.transcribe(
                    self.rfile,
                    int(self.headers.get("Content-Length", "0")),
                    self.headers.get("X-Dictation-ID"),
                ),
            )
        if path == "/api/upload":
            query = parse_qs(url.query)
            size = int(self.headers.get("Content-Length", "0"))
            item = self.server.store.upload(
                self.rfile, size, query.get("name", [""])[0], query.get("role", [""])[0]
            )
            return self.respond(200, item)
        body = self.read_body()
        if path == "/api/dictation/prepare":
            if body:
                raise DemoError("离线模型准备不接受录音或其他参数。")
            return self.respond(200, {"local_dictation": self.server.speech.prepare()})
        if path == "/api/dictation/cancel":
            if (
                set(body) != {"request_id"}
                or not isinstance(body["request_id"], str)
                or len(body["request_id"]) > 64
            ):
                raise DemoError("听写取消参数无效。")
            self.server.speech.cancel(body["request_id"])
            return self.respond(200, {"ok": True})
        if path == "/api/export-image":
            return self.respond(200, {"artifact": self.server.exports.export(body)})
        if path == "/api/files/remove":
            return self.respond(200, self.server.remove_file(body))
        if path == "/api/samples":
            return self.respond(200, self.server.samples())
        if path == "/api/analysis":
            return self.respond(
                200,
                self.server.analysis.start(
                    body.get("arguments"), body.get("label", "PCB 分析")
                ),
            )
        if path == "/api/analysis/cancel":
            return self.respond(200, self.server.analysis.cancel(body.get("job_id")))
        if path == "/api/selection":
            ids, holder = body.get("pcb_ids", []), body.get("holder_id")
            if not isinstance(ids, list) or len(ids) > 40:
                raise DemoError("选择无效。")
            with self.server.analysis.lock:
                for fid in ids:
                    self.server.store.resolve(fid, "pcb")
                if holder:
                    self.server.store.resolve(holder, "holder")
                if self.server.conversation:
                    self.server.conversation.selection = {
                        "pcb_ids": ids,
                        "holder_id": holder,
                    }
                self.server.selection = {"pcb_ids": ids, "holder_id": holder}
            return self.respond(200, {"ok": True})
        if path == "/api/chat/cancel":
            if not self.server.conversation:
                raise DemoError("Codex 对话未启用。")
            return self.respond(200, self.server.conversation.stop())
        if path == "/api/chat":
            if not self.server.conversation:
                raise DemoError("Codex 对话未启用。")
            self.send_headers(200, "text/event-stream; charset=utf-8")
            self.close_connection = True

            def emit(kind, data):
                try:
                    self.wfile.write(
                        (
                            "event: "
                            + kind
                            + "\ndata: "
                            + json.dumps(data, ensure_ascii=False)
                            + "\n\n"
                        ).encode()
                    )
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass  # A page refresh does not cancel the underlying turn.

            try:
                self.server.conversation.chat(body, emit)
            except Exception as error:  # noqa: BLE001 - SSE error boundary
                emit("error", {"message": str(error)[:500]})
            return
        return self.respond(404, {"error": "接口不存在。"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8890)
    parser.add_argument(
        "--executable",
        type=Path,
        default=REPO / "build/cpp/release/cpp/PCBUNIInspectorAgent",
    )
    parser.add_argument(
        "--runtime-root", type=Path, default=REPO / "build/local-web-demo/runs"
    )
    parser.add_argument("--open", action="store_true")
    parser.add_argument(
        "--without-codex", action="store_true", help="Native-only diagnostics"
    )
    args = parser.parse_args()
    root = args.runtime_root.resolve() / uuid.uuid4().hex
    server = DemoServer(
        args.port, args.executable, root, with_codex=not args.without_codex
    )
    address = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"PCB 分析演示：{address}\n文件保存于：{root}\n按 Ctrl+C 退出。", flush=True)

    def shutdown(*_args):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    if args.open:
        webbrowser.open(address)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.close_owned()


if __name__ == "__main__":
    main()
