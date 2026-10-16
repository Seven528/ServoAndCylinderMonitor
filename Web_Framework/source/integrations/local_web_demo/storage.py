"""Bounded in-memory identities for retained uploads, artifacts and report queries."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

MAX_UPLOAD = 64 * 1024 * 1024
MAX_REPORT = 32 * 1024 * 1024


class DemoError(ValueError):
    pass


class WorkspaceBusy(DemoError):
    pass


class FileStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.inputs = self.root / "inputs"
        self.outputs = self.root / "outputs"
        self.inputs.mkdir(parents=True, exist_ok=True)
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.files = {}
        self.artifacts = {}
        self.file_revision = 0
        self.lock = threading.RLock()

    def upload(self, stream, size, name, role):
        if role not in {"pcb", "holder"}:
            raise DemoError("请选择 PCB 或 Holder 文件类型。")
        if (
            not isinstance(name, str)
            or len(name) > 240
            or Path(name).name != name
            or "\\" in name
        ):
            raise DemoError("文件名无效。")
        if not name.lower().endswith(".uni") or not 0 < size <= MAX_UPLOAD:
            raise DemoError("请选择非空 UNI 文件，单文件上限为 64 MiB。")
        with self.lock:
            if len(self.files) >= 40:
                raise DemoError(
                    "本会话累计最多上传 40 个文件（含已移除文件），请重启开始新会话。"
                )
            fid = "f_" + uuid.uuid4().hex
            directory = self.inputs / fid
            directory.mkdir()
            path = directory / name
            try:
                with path.open("xb") as target:
                    remaining = size
                    while remaining:
                        chunk = stream.read(min(65536, remaining))
                        if not chunk:
                            raise DemoError("上传未完成，请重新选择文件。")
                        target.write(chunk)
                        remaining -= len(chunk)
            except BaseException:
                path.unlink(
                    missing_ok=True
                )  # Only this incomplete upload, never historical files.
                raise
            self.files[fid] = {
                "id": fid,
                "name": name,
                "role": role,
                "size": size,
                "path": path,
                "_source_mtime_ns": path.stat().st_mtime_ns,
            }
            return self.public_file(self.files[fid])

    @staticmethod
    def public_file(item):
        return {
            key: value
            for key, value in item.items()
            if key != "path" and not key.startswith("_")
        }

    def require_original_source(self, fid):
        with self.lock:
            item = self.files.get(fid)
            if not item or item.get("_removed"):
                raise DemoError("导出源文件未登记。")
            stat = item["path"].stat()
            if (
                stat.st_size != item["size"]
                or stat.st_mtime_ns != item["_source_mtime_ns"]
            ):
                raise DemoError(
                    "上传源文件已被外部修改，请重新上传并生成预览后再导出。"
                )

    def listing(self):
        with self.lock:
            return [
                self.public_file(item)
                for item in self.files.values()
                if not item.get("_removed")
            ]

    def remove(self, fid):
        """Withdraw an identity, retaining disk evidence and cumulative upload limits."""
        with self.lock:
            item = self.files.get(fid) if isinstance(fid, str) else None
            if item is None:
                raise DemoError("文件不属于当前会话，未删除。")
            if not item.get("_removed"):
                item["_removed"] = True
                self.file_revision += 1
            return self.public_file(item)

    def resolve(self, fid, role=None):
        with self.lock:
            item = self.files.get(fid) if isinstance(fid, str) else None
            if item is None or item.get("_removed") or (role and item["role"] != role):
                raise DemoError("文件未登记或类型不匹配，请使用当前页面中的文件。")
            return item["path"]

    def native_arguments(self, value, depth=0):
        if depth > 24:
            raise DemoError("请求嵌套过深。")
        if isinstance(value, dict):
            converted = {}
            for key, child in value.items():
                if key.endswith("_path") or key in {"output_directory", "files"}:
                    raise DemoError("请使用已上传文件的 ID，不接受本地路径。")
                if key in {
                    "pcb_file_id",
                    "holder_file_id",
                    "baseline_file_id",
                    "target_file_id",
                }:
                    role = "holder" if key == "holder_file_id" else "pcb"
                    converted[key.replace("_file_id", "_path")] = str(
                        self.resolve(child, role)
                    )
                else:
                    converted[key] = self.native_arguments(child, depth + 1)
            return converted
        if isinstance(value, list):
            return [self.native_arguments(item, depth + 1) for item in value]
        return value

    def register_artifact(self, item, task_id=None, unit_id=None, job_id=None):
        raw = item.get("path")
        if not raw:
            return None
        path = Path(raw).resolve()
        if not path.is_relative_to(self.outputs) or not path.is_file():
            raise DemoError("分析产物不存在或不属于本次演示目录。")
        if path.suffix not in {".png", ".json", ".svg"}:
            raise DemoError("不支持的产物类型。")
        if path.suffix == ".svg" and item.get("mime_type") != "image/svg+xml":
            raise DemoError("SVG 类型与产物元数据不一致。")
        with self.lock:
            for stored in self.artifacts.values():
                if stored["path"] == path:
                    return self.public_artifact(stored)
            aid = "a_" + uuid.uuid4().hex
            stored = {
                **item,
                "id": aid,
                "path": path,
                "name": path.name,
                "task_id": task_id,
                "unit_id": unit_id,
                "job_id": job_id,
            }
            self.artifacts[aid] = stored
            return self.public_artifact(stored)

    @staticmethod
    def public_artifact(item):
        result = {key: value for key, value in item.items() if key != "path"}
        result["url"] = "/api/artifacts/" + item["id"]
        return result

    def artifact(self, aid):
        with self.lock:
            if aid not in self.artifacts:
                raise DemoError("结果文件不存在于当前会话。")
            return dict(self.artifacts[aid])

    def redact(self, value):
        if isinstance(value, dict):
            return {
                key: self.redact(item)
                for key, item in value.items()
                if key not in {"path", "output_directory"} and not key.endswith("_path")
            }
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value

    def read_report(self, aid):
        item = self.artifact(aid)
        if item["path"].suffix != ".json" or item["path"].stat().st_size > MAX_REPORT:
            raise DemoError("请选择大小有效的 JSON 报告。")
        data = json.loads(item["path"].read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise DemoError("报告不是对象。")
        return data

    def report(self, aid, offset=0, limit=25, refdes=None, matched=None, result=None):
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise DemoError("分页参数无效，每次最多读取 50 条。")
        data = self.read_report(aid)
        section = next(
            (
                key
                for key in (
                    "components",
                    "targets",
                    "pressure_heads",
                    "changes",
                    "tasks",
                )
                if isinstance(data.get(key), list)
            ),
            None,
        )
        rows = data.get(section, []) if section else []
        total = len(rows)
        if refdes:
            needle = str(refdes).casefold()
            rows = [
                row
                for row in rows
                if needle in json.dumps(row, ensure_ascii=False).casefold()
            ]
        if matched is not None:
            rows = [
                row
                for row in rows
                if row.get("matches_filter", row.get("matches")) == matched
            ]
        if result:
            rows = [
                row
                for row in rows
                if result
                in {
                    row.get("result"),
                    row.get("grade"),
                    row.get("distance_band"),
                    row.get("clearance_band"),
                }
            ]
        selected = self.redact(rows[offset : offset + limit])
        while len(json.dumps(selected, ensure_ascii=False).encode()) > 48 * 1024:
            if len(selected) <= 1:
                raise DemoError("单条报告记录较大，请下载完整 JSON 查看。")
            selected.pop()
        summary = {
            key: self.redact(value)
            for key, value in data.items()
            if key
            not in {"components", "targets", "pressure_heads", "changes", "tasks"}
        }
        # Summary metadata can contain source diagnostics; keep the model response bounded.
        summary_truncated = (
            len(json.dumps(summary, ensure_ascii=False).encode()) > 16 * 1024
        )
        if summary_truncated:
            summary = {
                key: summary[key]
                for key in ("schema_version", "summary", "configuration", "parameters")
                if key in summary
            }
        return {
            "ok": True,
            "report_id": aid,
            "section": section,
            "summary": summary,
            "summary_truncated": summary_truncated,
            "total": total,
            "filtered_total": len(rows),
            "offset": offset,
            "records": selected,
            "next_offset": offset + len(selected)
            if offset + len(selected) < len(rows)
            else None,
        }
