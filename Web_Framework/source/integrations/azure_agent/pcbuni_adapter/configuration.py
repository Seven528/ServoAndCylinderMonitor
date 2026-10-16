"""Operator-owned configuration and local test boundaries, never model policy."""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class AdapterError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def strict_json(value: str) -> Any:
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    def invalid_constant(_value):
        raise ValueError("non-finite JSON number")

    return json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)


@dataclass(frozen=True)
class Configuration:
    transport: str
    mode: str
    executable: Path
    native_config: Path | None
    input_roots: tuple[Path, ...]
    output_root: Path | None
    timeout_seconds: float

    @classmethod
    def load(cls, path: str | Path):
        try:
            config_path = Path(path).resolve(strict=True)
            with config_path.open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("configuration exceeds 64 KiB")
            data = strict_json(raw.decode("utf-8-sig"))
            allowed = {
                "schema_version",
                "transport",
                "mode",
                "executable",
                "native_config",
                "input_roots",
                "output_root",
                "timeout_seconds",
            }
            if not isinstance(data, dict) or set(data) - allowed:
                raise ValueError("unknown configuration field")
            if data.get("schema_version") != "pcb-uni.platform.config.v1":
                raise ValueError("unsupported configuration schema")
            transport, mode = data.get("transport"), data.get("mode", "platform")
            if transport not in {"mcp", "json_cli"} or mode not in {
                "platform",
                "local_trusted",
            }:
                raise ValueError("invalid transport or mode")

            def resolve(value):
                if not isinstance(value, str) or not value or "\x00" in value:
                    raise ValueError("expected nonempty filesystem path")
                supplied = Path(value)
                return (config_path.parent / supplied).resolve()

            executable = resolve(data["executable"])
            native_config = (
                resolve(data["native_config"]) if "native_config" in data else None
            )
            roots = data.get("input_roots", [])
            if not isinstance(roots, list):
                raise TypeError("input_roots must be an array")
            input_roots = tuple(resolve(root) for root in roots)
            output_root = (
                resolve(data["output_root"]) if "output_root" in data else None
            )
            timeout = data.get("timeout_seconds", 300)
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout)
                or not 1 <= timeout <= 3600
            ):
                raise ValueError("timeout_seconds must be between 1 and 3600")
            if mode == "local_trusted":
                if not executable.is_file() or (
                    native_config and not native_config.is_file()
                ):
                    raise ValueError("executable/native_config is not an existing file")
                if not input_roots or any(not root.is_dir() for root in input_roots):
                    raise ValueError("local_trusted requires existing input roots")
                if output_root is None or not output_root.is_dir():
                    raise ValueError("local_trusted requires an existing output root")
            return cls(
                transport,
                mode,
                executable,
                native_config,
                input_roots,
                output_root,
                float(timeout),
            )
        except (ValueError, OSError, KeyError, TypeError, RecursionError) as error:
            raise AdapterError(
                "configuration_error", "适配配置无效；请由部署人员检查配置和路径。"
            ) from error

    def command(self) -> list[str]:
        command = [
            str(self.executable),
            "--mcp" if self.transport == "mcp" else "--json",
        ]
        if self.native_config:
            command += ["--config", str(self.native_config)]
        return command

    def prepare(self, arguments: dict, agent_id: str = "") -> dict:
        if self.mode != "local_trusted":
            raise AdapterError(
                "integration_not_configured",
                "平台身份与附件绑定尚未接入；请联系部署人员，不要让模型猜测身份或路径。",
            )
        if not isinstance(agent_id, str) or len(agent_id) > 128:
            raise AdapterError(
                "invalid_agent_id", "agent_id 仅作可选路由提示，不是授权凭据。"
            )
        if not isinstance(arguments, dict):
            raise AdapterError(
                "invalid_arguments", "arguments 必须为原生工具请求对象。"
            )
        try:
            encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode("utf-8")) > 4 * 1024 * 1024 - 8192:
                raise ValueError("request exceeds bridge input limit")
            copy = strict_json(encoded)
        except (ValueError, TypeError, RecursionError) as error:
            raise AdapterError(
                "invalid_arguments", "请求不是有界、有限数值的 JSON。"
            ) from error
        if "output_directory" in copy:
            raise AdapterError(
                "output_policy", "输出目录由部署配置决定，工具参数不得覆盖。"
            )

        def local_path(value):
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise AdapterError(
                    "input_path_denied", "本地测试仅接受授权输入目录中的绝对文件路径。"
                )
            path = Path(value).resolve()
            if not any(path.is_relative_to(root) for root in self.input_roots):
                raise AdapterError(
                    "input_path_denied", "输入路径不属于部署人员配置的目录。"
                )
            # Native preflight preserves per-unit missing/parse failure isolation.
            return str(path)

        def walk(value, depth=0):
            if depth > 32:
                raise AdapterError("invalid_arguments", "请求嵌套层数超限。")
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {
                        "pcb_path",
                        "holder_path",
                        "baseline_path",
                        "target_path",
                    }:
                        value[key] = local_path(item)
                    elif key == "files":
                        if not isinstance(item, list):
                            raise AdapterError(
                                "invalid_arguments", "files 必须为明确的文件列表。"
                            )
                        value[key] = [local_path(path) for path in item]
                    else:
                        walk(item, depth + 1)
            elif isinstance(value, list):
                for item in value:
                    walk(item, depth + 1)

        try:
            walk(copy)
        except (OSError, ValueError, RecursionError) as error:
            raise AdapterError("input_path_denied", "输入路径无效。") from error
        copy["output_directory"] = str(self.output_root)
        if (
            len(json.dumps(copy, ensure_ascii=False).encode("utf-8"))
            > 4 * 1024 * 1024 - 512
        ):
            raise AdapterError(
                "invalid_arguments", "规范化后的请求超过原生输入大小限制。"
            )
        return copy
