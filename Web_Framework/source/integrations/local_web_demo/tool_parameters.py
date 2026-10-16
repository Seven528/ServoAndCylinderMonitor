"""Native-schema-backed guidance and shape checks; never infer file authority."""

from __future__ import annotations

from jsonschema import Draft202012Validator

from .storage import DemoError


def analysis_branch(schema, kind):
    alternatives = schema.get("properties", {}).get("analysis", {}).get("oneOf", [])
    return _kind_branch(alternatives, kind)


def _kind_branch(alternatives, kind):
    return next(
        (
            item
            for item in alternatives
            if item.get("properties", {}).get("kind", {}).get("const") == kind
        ),
        None,
    )


def validate_analysis_arguments(arguments, schema):
    """Preflight known branches before allocating a job; native owns semantics."""

    def check(value, branch, prefix):
        if branch is None:
            return  # Unknown kinds/root constraints still go through native decoding.
        error = next(Draft202012Validator(branch).iter_errors(value), None)
        if error is None:
            return
        path = prefix + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in error.absolute_path
        )
        raise DemoError(
            f"分析参数格式错误（尚未执行）：{path}: {error.message[:300]}。"
            "请参照 parameter_help 修正，勿猜测字段结构。"
        )

    analysis = arguments.get("analysis")
    if isinstance(analysis, dict):
        check(analysis, analysis_branch(schema, analysis.get("kind")), "$.analysis")
    tasks = arguments.get("tasks")
    if isinstance(tasks, list):
        alternatives = (
            schema.get("properties", {})
            .get("tasks", {})
            .get("items", {})
            .get("oneOf", [])
        )
        for index, task in enumerate(tasks):
            if isinstance(task, dict):
                check(
                    task,
                    _kind_branch(alternatives, task.get("kind")),
                    f"$.tasks[{index}]",
                )


def pressure2d_help(schema, scope=None):
    branch = analysis_branch(schema, "pressure2d")
    if branch is None:
        return {"available": False}
    pcb_schema = branch["properties"]["pcbs"]["items"]
    side_schema = pcb_schema["properties"]["sides"]["items"]
    help_value = {
        "analysis_schema": branch,
        "rules": (
            "每个PCB只接受pcb_file_id和sides。sides是对象数组，不是字符串数组："
            "[{side:'side1',surface_views:['components']}]。surface_views为复数数组，"
            "位于每个side对象内。Pressure2D固定Panel，不接受view_mode或高度filter。"
            "不要套用预览/单板压棒的sides字符串数组或高度图的jobs结构。"
            "一个Holder和多个PCB可放在同一次analysis.pcbs中，无需为每个PCB重复工具调用。"
            "原生每次至多20个PCB-side单元及20张图片；表面只影响显示，不重复评分。"
        ),
        "example_usage": (
            "current_scope_example仅展示本轮已授权文件与当前图Side/Surface的正确参数；"
            "不会自动执行或扩大授权。仅在用户要求相应分析时使用；用户指定变化时按schema调整。"
        ),
    }
    if scope is None:
        return help_value
    context = (scope.active or {}).get("context", {}) or scope.view_defaults
    side, surface = context.get("side"), context.get("surface_view")
    props = side_schema["properties"]
    if (
        side not in props["side"]["enum"]
        or surface not in props["surface_views"]["items"]["enum"]
    ):
        return help_value  # Do not guess the parameters of an unready canvas.
    holders = [f["id"] for f in scope.files if f["role"] == "holder"]
    pcbs = [f["id"] for f in scope.files if f["role"] == "pcb"]
    if len(holders) == 1 and 1 <= len(pcbs) <= 20:
        help_value["current_scope_example"] = {
            "holder_file_id": holders[0],
            "analysis": {
                "kind": "pressure2d",
                "pcbs": [
                    {
                        "pcb_file_id": fid,
                        "sides": [{"side": side, "surface_views": [surface]}],
                    }
                    for fid in pcbs
                ],
            },
        }
    return help_value
