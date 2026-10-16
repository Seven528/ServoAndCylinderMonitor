"""Lazy, single-presentation vector exports using the existing native MCP cache."""

import threading
import uuid

from integrations.azure_agent.pcbuni_adapter.configuration import AdapterError
from integrations.azure_agent.pcbuni_adapter.results import project

from .storage import DemoError


def export_arguments(context):
    kind = context.get("kind", "")
    pcb, holder = context.get("pcb_file_id"), context.get("holder_file_id")
    side = context.get("side") or "side1"
    view = context.get("view_mode") or "single"
    surface = context.get("surface_view") or "full"
    if kind.startswith("holder_") and holder:
        return {
            "tasks": [
                {
                    "task_id": "export",
                    "kind": "holder_preview",
                    "holder_file_id": holder,
                }
            ]
        }
    if not pcb:
        raise DemoError("此结果缺少可追溯的 PCB 身份，不能导出矢量图。")
    if kind == "pressure2d":
        if not holder:
            raise DemoError("此干涉结果缺少 Holder 身份。")
        return {
            "holder_file_id": holder,
            "analysis": {
                "kind": kind,
                "pcbs": [
                    {
                        "pcb_file_id": pcb,
                        "sides": [{"side": side, "surface_views": [surface]}],
                    }
                ],
            },
        }
    if kind == "height_map":
        return {
            "pcb_file_id": pcb,
            "analysis": {
                "kind": kind,
                "jobs": [
                    {
                        "side": side,
                        "view_mode": view,
                        "surface_view": surface,
                        "filter": context.get("filter") or {"kind": "all"},
                    }
                ],
            },
        }
    if kind == "single_board_pressure":
        return {
            "pcb_file_id": pcb,
            "analysis": {"kind": kind, "side": side, "surface_view": surface},
        }
    if kind not in {"pcb_preview", "pcb_inspect"}:
        raise DemoError("此结果类型尚不支持网页矢量下载。")
    return {
        "pcb_file_id": pcb,
        "render_jobs": [{"view_mode": view, "surface_view": surface, "sides": [side]}],
    }


class ImageExports:
    def __init__(self, store, analysis):
        self.store, self.analysis = store, analysis
        self.completed = {}
        self.count = 0
        self.cancel = None
        self.last_cache = {}

    @property
    def formats(self):
        definition = self.analysis.transport.tool_definition or {}
        formats = (
            definition.get("inputSchema", {})
            .get("properties", {})
            .get("image_format", {})
            .get("enum", [])
        )
        return ["png", "jpg", "svg"] if "svg" in formats else ["png", "jpg"]

    def export(self, body):
        if set(body) != {"presentation_id", "format"} or body["format"] != "svg":
            raise DemoError("导出只接受当前结果 ID 和 svg 格式。")
        key = body["presentation_id"]
        if not isinstance(key, str) or len(key) > 300:
            raise DemoError("结果 ID 无效。")
        with self.analysis.lock:
            if self.analysis.active or self.analysis.exporting:
                raise DemoError("已有分析或导出正在运行，请稍后再下载。")
            if self.analysis.closed or "svg" not in self.formats:
                raise DemoError("当前原生程序未提供 SVG 导出，请更新并重启服务。")
            view = next(
                (
                    view
                    for job in self.analysis.jobs.values()
                    for view in job["presentations"]
                    if view["id"] == key
                ),
                None,
            )
            if not view or not view.get("image_id"):
                raise DemoError("找不到可导出的已有图像。")
            for field in ("pcb_file_id", "holder_file_id"):
                if view["context"].get(field):
                    self.store.require_original_source(view["context"][field])
            if key in self.completed:
                artifact = self.store.artifact(self.completed[key])
                if artifact["path"].is_file():
                    return self.store.public_artifact(artifact)
            if self.count >= 64:
                raise DemoError("本次会话矢量导出已达到 64 次上限。")
            self.analysis.exporting = True
            self.count += 1
            self.cancel = threading.Event()
        deadline = threading.Timer(90, self.cancel.set)
        try:
            deadline.start()
            request = self.store.native_arguments(export_arguments(view["context"]))
            root = self.store.outputs / ("export_" + uuid.uuid4().hex)
            root.mkdir()
            request.update(output_directory=str(root), image_format="svg")
            response = self.analysis.transport.call(request, cancel=self.cancel)
            self.last_cache = response.get("meta", {}).get("cache", {})
            value = project(response, self.store.outputs)
            images = [
                a
                for a in value["artifacts"]
                if a.get("status") == "ok" and a.get("mime_type") == "image/svg+xml"
            ]
            if len(images) != 1:
                messages = "; ".join(
                    d.get("message", "") for d in response.get("diagnostics", [])
                )
                raise DemoError(
                    "矢量导出未完成："
                    + (messages[:400] or response.get("status", "unknown"))
                )
            artifact = self.store.register_artifact(images[0], job_id=view["job_id"])
            if not artifact:
                raise DemoError("矢量文件没有成功发布。")
            self.completed[key] = artifact["id"]
            return artifact
        except AdapterError as error:
            raise DemoError(str(error)[:400]) from None
        finally:
            deadline.cancel()
            with self.analysis.lock:
                self.analysis.exporting = False
                self.cancel = None

    def close(self):
        with self.analysis.lock:
            if self.cancel:
                self.cancel.set()
