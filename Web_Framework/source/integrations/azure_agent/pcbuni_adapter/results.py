"""Bounded platform projection; a local file is never presented as an uploaded URL."""

from pathlib import Path

from .configuration import AdapterError


def failure(code: str, message: str) -> dict:
    return {
        "schema_version": "pcb-uni.platform.result.v1",
        "status": "error",
        "native_status": None,
        "code": code,
        "message": message,
        "retryable": False,
        "result_path": None,
        "artifacts": [],
        "tasks": [],
        "frontend_type": None,
        "frontend_path": None,
        "publication": {"status": "not_published", "urls_available": False},
    }


def project(response: dict, output_root: Path) -> dict:
    if (
        not isinstance(response, dict)
        or response.get("schema_version") != "pcb-uni.agent.response.v8"
        or response.get("operation") != "pcb_uni_inspect"
        or not isinstance(response.get("diagnostics"), list)
        or not isinstance(response.get("status"), str)
    ):
        raise AdapterError(
            "native_contract_mismatch", "工具响应格式不匹配；请核对所部署的运行程序。"
        )
    payload = response.get("result") or {}
    batch = payload if payload.get("kind") == "batch" else payload.get("batch", {})
    artifacts, tasks = [], []

    def artifact(value, task_id=None, unit_id=None):
        path = value.get("path")
        if path and (
            not Path(path).is_absolute()
            or not Path(path).resolve().is_relative_to(output_root)
        ):
            raise AdapterError(
                "artifact_path_denied", "原生输出路径超出配置的输出目录。"
            )
        item = dict(value)
        item.update(
            {
                "task_id": task_id,
                "unit_id": unit_id,
                "url": None,
                "location": "worker_local",
            }
        )
        return item

    for task in batch.get("tasks", []):
        units = []
        for unit in task.get("units", []):
            units.append(
                {
                    key: unit[key]
                    for key in (
                        "unit_id",
                        "status",
                        "analysis_status",
                        "artifact_status",
                        "statistics",
                        "diagnostics",
                        "cache",
                        "cache_calls",
                        "comparable",
                        "configuration",
                    )
                    if key in unit
                }
            )
            artifacts.extend(
                artifact(value, task["task_id"], unit["unit_id"])
                for value in unit.get("artifacts", [])
            )
        tasks.append(
            {
                "task_id": task["task_id"],
                "kind": task["kind"],
                "status": task["status"],
                "units": units,
            }
        )
    manifest = artifact(batch["manifest"]) if batch.get("manifest") else None
    succeeded = response["status"] == "ok"
    return {
        "schema_version": "pcb-uni.platform.result.v1",
        "status": "success" if succeeded else "error",
        "native_status": response["status"],
        "code": None if succeeded else response["status"],
        "retryable": False,
        "message": (
            "本地分析完成；文件尚未发布到平台。"
            if succeeded
            else "调用存在失败或停用项；请检查任务状态，已有成功文件保留。"
        ),
        "request_id": batch.get("request_id"),
        "result_path": manifest.get("path") if manifest else None,
        "manifest": manifest,
        "tasks": tasks,
        "artifacts": artifacts,
        "diagnostics": response["diagnostics"],
        "meta": response.get("meta", {}),
        "frontend_type": None,
        "frontend_path": None,
        "publication": {
            "status": "local_only" if manifest or artifacts else "not_published",
            "urls_available": False,
        },
    }
