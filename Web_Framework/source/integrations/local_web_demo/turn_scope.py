"""Host-enforced, per-turn file authority derived from the visible canvas."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field

from .file_targets import explicit_targets
from .storage import DemoError


def source_ids(context):
    return {
        context[key] for key in ("pcb_file_id", "holder_file_id") if context.get(key)
    }


def views_in(snapshot):
    return [view for job in snapshot["jobs"] for view in job.get("presentations", [])]


@dataclass(frozen=True)
class TurnScope:
    mode: str
    file_ids: frozenset[str]
    active: dict | None
    files: tuple[dict, ...]
    generated_job_ids: set[str] = field(default_factory=set, compare=False)
    view_defaults: dict = field(default_factory=dict)

    @property
    def key(self):
        return json.dumps(
            [self.mode, sorted(self.file_ids), self.active, self.view_defaults],
            sort_keys=True,
        )

    @property
    def label(self):
        prefix = {"batch": "本轮批量", "explicit": "本轮指定"}.get(
            self.mode, "当前画布"
        )
        return prefix + " · " + " / ".join(item["name"] for item in self.files)

    def public(self):
        return {
            "mode": self.mode,
            "file_ids": sorted(self.file_ids),
            "active_presentation": copy.deepcopy(self.active),
            "view_defaults": copy.deepcopy(self.view_defaults),
            "label": self.label,
        }

    def allows_view(self, view):
        ids = source_ids(view.get("context", {}))
        if not ids or not ids.issubset(self.file_ids):
            return False
        return (
            self.mode in {"batch", "explicit"}
            or view["id"] == (self.active or {}).get("id")
            or view.get("job_id") in self.generated_job_ids
        )

    def check_arguments(self, arguments):
        found = set()

        def visit(value, depth=0):
            if depth > 24:
                raise DemoError("分析参数嵌套过深。")
            if isinstance(value, list):
                for child in value:
                    visit(child, depth + 1)
            elif isinstance(value, dict):
                for key, child in value.items():
                    if key.endswith("_path") or key in {"output_directory", "files"}:
                        raise DemoError("Agent 只能使用本轮允许的文件 ID。")
                    if key.endswith("_file_id"):
                        if not isinstance(child, str):
                            raise DemoError("文件 ID 无效。")
                        found.add(child)
                    elif key == "file_ids":
                        if not isinstance(child, list) or not all(
                            isinstance(x, str) for x in child
                        ):
                            raise DemoError("文件 ID 列表无效。")
                        found.update(child)
                    else:
                        visit(child, depth + 1)

        visit(arguments)
        if not found or not found.issubset(self.file_ids):
            raise DemoError(
                "超出本轮指定范围，未执行分析。只能使用 pcb_context 返回的文件 ID；"
                "其他文件须由用户在本轮消息中明确指定，工具不能自行扩大范围。"
            )

    def report_views(self, snapshot, report_id):
        return [
            view
            for view in views_in(snapshot)
            if view.get("report_id") == report_id and self.allows_view(view)
        ]

    def context(self, snapshot):
        jobs = []
        for job in snapshot["jobs"]:
            views = [
                copy.deepcopy(v)
                for v in job.get("presentations", [])
                if self.allows_view(v)
            ]
            if not views:
                continue
            artifact_ids = {
                v.get(key) for v in views for key in ("image_id", "report_id")
            }
            # Do not return whole batch tasks or manifests: they contain other files.
            jobs.append(
                {
                    "id": job["id"],
                    "status": job["status"],
                    "presentations": views,
                    "artifacts": [
                        a for a in job.get("artifacts", []) if a["id"] in artifact_ids
                    ],
                }
            )
        active_id = (self.active or {}).get("id")
        current = [
            j for j in jobs if any(v["id"] == active_id for v in j["presentations"])
        ]
        others = [j for j in jobs if j not in current]
        return {
            "scope": self.public(),
            "files": list(self.files),
            "selection": {
                "pcb_ids": [f["id"] for f in self.files if f["role"] == "pcb"],
                "holder_id": next(
                    (f["id"] for f in self.files if f["role"] == "holder"), None
                ),
            },
            "analyses": current + others[-5:],
        }


def resolve_scope(value, store, snapshot, selection, message=""):
    if not isinstance(value, dict) or set(value) - {
        "presentation_id",
        "batch_confirmed",
        "batch_file_ids",
    }:
        raise DemoError("缺少有效的主画布上下文，请刷新页面后重试。")
    if type(value.get("batch_confirmed", False)) is not bool:
        raise DemoError("批量确认无效。")
    active = None
    presentation_id = value.get("presentation_id")
    if presentation_id is not None:
        if not isinstance(presentation_id, str):
            raise DemoError("主画布结果 ID 无效。")
        view = next((v for v in views_in(snapshot) if v["id"] == presentation_id), None)
        if view is None:
            raise DemoError("主画布结果不属于当前会话，请重新选择结果。")
        active = {
            key: copy.deepcopy(view.get(key))
            for key in (
                "id",
                "context",
                "image_id",
                "report_id",
                "status",
                "statistics",
            )
        }
    files = store.listing()
    by_id = {item["id"]: item for item in files}
    defaults = {
        key: copy.deepcopy(active["context"][key])
        for key in ("side", "view_mode", "surface_view", "filter")
        if active and key in active["context"]
    }
    if value.get("batch_confirmed") is True:
        ids = value.get("batch_file_ids")
        if (
            not isinstance(ids, list)
            or not 1 <= len(ids) <= 40
            or not all(isinstance(x, str) for x in ids)
        ):
            raise DemoError("请明确确认本轮批量的文件清单。")
        selected = set(selection.get("pcb_ids", []))
        if selection.get("holder_id"):
            selected.add(selection["holder_id"])
        if set(ids) != selected or len(set(ids)) != len(ids):
            raise DemoError("勾选文件已变化，请重新确认本轮批量清单。")
        requested = explicit_targets(message, files, copy.deepcopy(selection), set(ids))
        if requested is not None and not requested.issubset(ids):
            raise DemoError(
                "消息指定的文件与本轮手动清单冲突，请直接发送明确的文件范围。"
            )
        allowed, mode = requested if requested is not None else set(ids), "batch"
    else:
        if value.get("batch_file_ids"):
            raise DemoError("未经用户确认，不能扩大本轮分析范围。")
        requested = explicit_targets(
            message,
            files,
            copy.deepcopy(selection),
            source_ids((active or {}).get("context", {})),
        )
        if requested is not None:
            allowed, mode = requested, "explicit"
        elif active:
            mode = "canvas"
            allowed = source_ids(active["context"])
        else:
            # Selection is never authority for an ordinary turn, even for one file.
            raise DemoError(
                "主图还没有可确认的结果。请显示目标文件，或在消息中明确指定已导入文件名/批量范围。"
            )
    if not allowed or not allowed.issubset(by_id):
        raise DemoError("主画布来源文件已不可用，请重新载入。")
    if active and not source_ids(active["context"]).issubset(allowed):
        active = None
    preferred = []
    if active:
        preferred = [
            active["context"].get(key) for key in ("pcb_file_id", "holder_file_id")
        ]
    ordered = [fid for fid in preferred if fid in allowed]
    ordered += sorted(allowed - set(ordered))
    return TurnScope(
        mode,
        frozenset(allowed),
        active,
        tuple(copy.deepcopy(by_id[fid]) for fid in ordered),
        view_defaults=defaults,
    )
