"""Single-flight coordinator reusing the native MCP transport and result projection."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from integrations.azure_agent.pcbuni_adapter.configuration import (
    AdapterError,
    Configuration,
)
from integrations.azure_agent.pcbuni_adapter.results import project
from integrations.azure_agent.pcbuni_adapter.transports import McpTransport

from .presentation import project_presentations
from .storage import DemoError, FileStore, WorkspaceBusy

APP = Path(__file__).resolve().parent
FEATURES = json.loads((APP / "native.config.json").read_text())["features"]


def references_file(value, fid):
    if isinstance(value, list):
        return any(references_file(item, fid) for item in value)
    if isinstance(value, dict):
        return any(
            (key.endswith("_file_id") and child == fid)
            or (key == "file_ids" and isinstance(child, list) and fid in child)
            or references_file(child, fid)
            for key, child in value.items()
        )
    return False


class AnalysisService:
    def __init__(self, store: FileStore, executable: Path):
        self.store = store
        self.config = Configuration(
            "mcp",
            "local_trusted",
            executable.resolve(),
            APP / "native.config.json",
            (store.inputs,),
            store.outputs,
            600,
        )
        self.transport = McpTransport(self.config)
        self.lock = threading.RLock()
        self.jobs = {}
        self.active = None
        self.exporting = False
        self.closed = False
        self.error = None
        try:
            self.transport._start()
        except AdapterError as error:
            self.error = str(error)

    @property
    def single_board_surfaces(self):
        definition = self.transport.tool_definition or {}
        alternatives = (
            definition.get("inputSchema", {})
            .get("properties", {})
            .get("analysis", {})
            .get("oneOf", [])
        )
        single = next(
            (
                item
                for item in alternatives
                if item.get("properties", {}).get("kind", {}).get("const")
                == "single_board_pressure"
            ),
            {},
        )
        return single.get("properties", {}).get("surface_view", {}).get("enum", [])

    def start(self, arguments, label="PCB 分析"):
        if not isinstance(arguments, dict):
            raise DemoError("分析参数必须为对象。")
        if arguments.get("image_format", "png") != "png":
            raise DemoError("网页预览保持 PNG；需要矢量图请使用下载格式选择器。")
        arguments = json.loads(
            json.dumps(arguments, ensure_ascii=False, allow_nan=False)
        )
        with self.lock:
            if self.closed or self.error:
                raise DemoError(self.error or "服务正在关闭。")
            if self.active or self.exporting:
                raise DemoError("已有分析正在进行，请等待完成或取消。")
            if len(self.jobs) >= 64:
                raise DemoError(
                    "本轮已运行 64 次分析，请重启演示开始新会话；已有文件保留。"
                )
            # Resolve under the same admission lock as removal and export.
            native = self.store.native_arguments(arguments)
            jid = "j_" + uuid.uuid4().hex
            root = self.store.outputs / jid
            root.mkdir()
            native["output_directory"] = str(root)
            job = {
                "id": jid,
                "label": str(label)[:100],
                "status": "running",
                "stage": "准备分析",
                "arguments": arguments,
                "created": time.time(),
                "artifacts": [],
                "presentations": [],
                "tasks": [],
                "diagnostics": [],
                "meta": {},
                "cancel": threading.Event(),
                "done": threading.Event(),
                "root": root,
            }
            self.jobs[jid] = job
            self.active = jid
            worker = threading.Thread(
                target=self._run, args=(job, native), name="pcb-demo-analysis"
            )
            job["worker"] = worker
            worker.start()
            return self.public(job)

    def remove_file(self, fid):
        with self.lock:
            if self.active or self.exporting:
                raise WorkspaceBusy("分析或导出正在进行，请完成或取消后再删除文件。")
            if self.closed:
                raise DemoError("服务正在关闭，未删除文件。")
            item = self.store.remove(fid)
            withdrawn = []
            for job in self.jobs.values():
                views = job.get("presentations", [])
                removed = [v for v in views if references_file(v.get("context"), fid)]
                if removed or references_file(job.get("arguments"), fid):
                    ids = job.setdefault("removed_file_ids", [])
                    if fid not in ids:
                        ids.append(fid)
                    withdrawn.extend(v["id"] for v in removed)
                    job["presentations"] = [v for v in views if v not in removed]
            return {"file": item, "removed_presentation_ids": withdrawn}

    async def _progress(self, job, progress, total=None, message=None):
        with self.lock:
            job["progress"] = progress
            job["total"] = total
            if not job["cancel"].is_set():
                job["stage"] = message or "正在计算"

    def _collect(self, job, response):
        value = project(response, self.store.outputs)
        artifacts = []
        for item in value["artifacts"]:
            registered = self.store.register_artifact(
                item, item.get("task_id"), item.get("unit_id"), job["id"]
            )
            if registered:
                artifacts.append(registered)
        if value.get("manifest"):
            manifest = self.store.register_artifact(value["manifest"], job_id=job["id"])
            if manifest:
                artifacts.append(manifest)
        presentations = project_presentations(
            self.store, job["id"], response, artifacts
        )
        with self.lock:
            job.update(
                artifacts=artifacts,
                presentations=presentations,
                tasks=self.store.redact(value["tasks"]),
                diagnostics=value["diagnostics"],
                meta=value["meta"],
                native_status=value["native_status"],
            )

    def _cancelled_manifest(self, job):
        # Read only this request's bounded output directory, never historical outputs.
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            candidates = sorted(job["root"].glob("*/*manifest*.json"), reverse=True)
            for path in candidates[:64]:
                if path.stat().st_size > 1024 * 1024:
                    continue
                document = json.loads(path.read_text(encoding="utf-8"))
                if document.get("schema_version") != "pcb-uni.agent.batch-manifest.v1":
                    continue
                if document.get("status") not in {"running", "queued"}:
                    self._collect(
                        job,
                        {
                            "schema_version": "pcb-uni.agent.response.v8",
                            "operation": "pcb_uni_inspect",
                            "status": "cancelled",
                            "diagnostics": [],
                            "result": {
                                **document,
                                "kind": "batch",
                                "manifest": {
                                    "path": str(path),
                                    "role": "manifest",
                                    "mime_type": "application/json",
                                    "byte_count": path.stat().st_size,
                                    "status": "ok",
                                },
                            },
                        },
                    )
                    return
            time.sleep(0.1)
        raise DemoError("取消已发送，但尚未确认原生工作结束，请退出演示后重启。")

    def _run(self, job, native):
        try:

            async def progress(value, total=None, message=None):
                await self._progress(job, value, total, message)

            response = self.transport.call(
                native, progress=progress, cancel=job["cancel"]
            )
            self._collect(job, response)
            with self.lock:
                job["status"] = "succeeded" if response["status"] == "ok" else "failed"
                job["stage"] = (
                    "分析完成" if response["status"] == "ok" else "存在失败或停用项"
                )
        except AdapterError as error:
            if error.code == "call_not_started":
                with self.lock:
                    job.update(status="cancelled", stage="分析在提交前已取消")
            elif error.code == "call_cancelled":
                try:
                    self._cancelled_manifest(job)
                    with self.lock:
                        job.update(
                            status="cancelled", stage="分析已取消，已生成的文件保留"
                        )
                except Exception as failure:  # noqa: BLE001 - owned worker must record a terminal error
                    with self.lock:
                        self.error = str(failure)
                        job.update(status="failed", stage=str(failure))
            else:
                with self.lock:
                    job.update(
                        status="failed",
                        stage=str(error),
                        diagnostics=[{"code": error.code, "message": str(error)}],
                    )
        except Exception as error:  # noqa: BLE001 - contain failures at the worker boundary
            with self.lock:
                job.update(
                    status="failed",
                    stage="分析未完成",
                    diagnostics=[{"message": str(error)[:500]}],
                )
        finally:
            with self.lock:
                job["elapsed_ms"] = round((time.time() - job["created"]) * 1000)
                self.active = None
                job["done"].set()

    @staticmethod
    def public(job):
        value = {
            key: value
            for key, value in job.items()
            if key not in {"cancel", "done", "worker", "root"}
        }
        if job.get("removed_file_ids"):
            visible = {
                view.get(key)
                for view in job.get("presentations", [])
                for key in ("image_id", "report_id")
            }
            value["artifacts"] = [a for a in job["artifacts"] if a["id"] in visible]
            value[
                "tasks"
            ] = []  # Original batch evidence remains in the retained job/output.
        return value

    def snapshot(self):
        with self.lock:
            return {
                "active_job": self.active,
                "export_busy": self.exporting,
                "jobs": [
                    self.public(job)
                    for job in self.jobs.values()
                    if not job.get("removed_file_ids") or job.get("presentations")
                ],
                "features": FEATURES,
                "native_error": self.error,
            }

    def get(self, jid):
        with self.lock:
            if jid not in self.jobs:
                raise DemoError("分析任务不存在。")
            return self.public(self.jobs[jid])

    def wait(self, jid):
        with self.lock:
            event = self.jobs[jid]["done"]
        event.wait()
        return self.get(jid)

    def cancel(self, jid):
        with self.lock:
            if jid != self.active:
                return {"ok": True, "status": "already_finished"}
            self.jobs[jid]["cancel"].set()
            self.jobs[jid]["status"] = "cancelling"
            self.jobs[jid]["stage"] = "正在取消，等待当前安全步骤结束"
            return {"ok": True, "status": "cancelling"}

    def close(self):
        with self.lock:
            self.closed = True
            active = self.jobs.get(self.active)
            if active:
                active["cancel"].set()
        if active:
            active["worker"].join()
        self.transport.close()
