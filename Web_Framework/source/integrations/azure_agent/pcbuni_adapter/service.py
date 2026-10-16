"""Single-owner bounded facade; native caches belong to its persistent MCP child."""

import threading
from pathlib import Path

from .configuration import AdapterError, Configuration
from .results import failure, project
from .transports import JsonCliTransport, McpTransport


class InspectorAdapter:
    def __init__(self, config_path: str | Path):
        self.config = Configuration.load(config_path)
        self.transport = (
            McpTransport(self.config)
            if self.config.transport == "mcp"
            else JsonCliTransport(self.config)
        )
        self.admission = threading.Lock()
        self.closed = False

    def invoke(self, arguments: dict, agent_id: str = "") -> dict:
        if not self.admission.acquire(blocking=False):
            return failure(
                "adapter_busy", "本适配器正在处理另一调用；未排队，也未开始本次分析。"
            )
        try:
            if self.closed:
                raise AdapterError(
                    "adapter_closed", "适配器已关闭，请由宿主重新创建实例。"
                )
            prepared = self.config.prepare(arguments, agent_id)
            return project(self.transport.call(prepared), self.config.output_root)
        except AdapterError as error:
            return failure(error.code, str(error))
        except Exception:  # noqa: BLE001 - tool boundary must not expose host exception data
            return failure(
                "adapter_internal_error",
                "适配器执行失败；结果可能不确定，请由部署人员检查，勿自动重试。",
            )
        finally:
            self.admission.release()

    def close(self):
        with self.admission:
            self.closed = True
            self.transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
