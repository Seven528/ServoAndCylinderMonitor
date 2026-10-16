"""Owned native process transports. No shell, silent fallback or automatic retry."""

import asyncio
import json
import os
import subprocess
import threading
from concurrent.futures import TimeoutError as FutureTimeout

from .configuration import AdapterError, Configuration, strict_json

MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class JsonCliTransport:
    def __init__(self, config: Configuration):
        self.config = config

    def call(self, arguments: dict) -> dict:
        request = (
            json.dumps(
                {"operation": "pcb_uni_inspect", "arguments": arguments},
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            self.config.command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=flags,
            shell=False,
        )
        output, errors = bytearray(), bytearray()
        overflow = threading.Event()

        def read(stream, destination, limit):
            try:
                while chunk := stream.read(65536):
                    if len(destination) + len(chunk) > limit:
                        overflow.set()
                        process.kill()
                        break
                    destination.extend(chunk)
            finally:
                stream.close()

        def write():
            try:
                process.stdin.write(request)
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                process.stdin.close()

        threads = [
            threading.Thread(
                target=read, args=(process.stdout, output, MAX_RESPONSE_BYTES)
            ),
            threading.Thread(target=read, args=(process.stderr, errors, 65536)),
            threading.Thread(target=write),
        ]
        for thread in threads:
            thread.start()
        try:
            process.wait(timeout=self.config.timeout_seconds)
        except subprocess.TimeoutExpired as error:
            process.kill()
            raise AdapterError(
                "transport_timeout",
                "本次调用超时；已结束本适配器的 CLI 子进程，可能已有文件，请勿自动重试。",
            ) from error
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            for thread in threads:
                thread.join()
        if overflow.is_set():
            raise AdapterError(
                "transport_output_limit", "原生进程输出超限，调用已停止。"
            )
        try:
            lines = output.decode("utf-8").splitlines()
            if len(lines) != 1:
                raise ValueError("expected exactly one JSON line")
            result = strict_json(lines[0])
            if (process.returncode == 0) != (result.get("status") == "ok"):
                raise ValueError("exit code/status mismatch")
            return result
        except (ValueError, AttributeError, RecursionError) as error:
            raise AdapterError(
                "invalid_native_response", "原生 CLI 输出无效；请检查部署版本。"
            ) from error

    def close(self):
        pass


class McpTransport:
    """One persistent SDK connection owned by one background event-loop task."""

    def __init__(self, config: Configuration):
        self.config = config
        self.ready = threading.Event()
        self.loop = None
        self.stop = None
        self.client = None
        self.failed = False
        self.thread = None
        self.tool_definition = None

    async def _lifetime(self):
        self.loop = asyncio.get_running_loop()
        self.stop = asyncio.Event()
        try:
            from mcp import Client, StdioServerParameters

            command = self.config.command()
            async with Client(
                StdioServerParameters(command=command[0], args=command[1:]),
                read_timeout_seconds=self.config.timeout_seconds,
            ) as client:
                listing = await client.list_tools()
                if (
                    len(listing.tools) != 1
                    or listing.tools[0].name != "pcb_uni_inspect"
                ):
                    raise ValueError("unexpected native MCP tools")
                self.client = client
                self.tool_definition = listing.tools[0].model_dump(by_alias=True)
                self.ready.set()
                await self.stop.wait()
        except asyncio.CancelledError:
            self.failed = True
        except Exception:  # noqa: BLE001 - SDK boundary sanitizes startup failures
            # Never echo raw SDK exceptions: they can include operator paths/credentials.
            self.failed = True
        finally:
            self.client = None
            self.ready.set()

    def _start(self):
        if self.thread is None:
            self.thread = threading.Thread(
                target=lambda: asyncio.run(self._lifetime()),
                name="pcbuni-mcp-connection",
                daemon=True,
            )
            self.thread.start()
            if not self.ready.wait(self.config.timeout_seconds):
                self.failed = True
        if self.failed or self.client is None:
            raise AdapterError(
                "mcp_connection_failed",
                "MCP 连接未就绪；请检查原生程序和版本，不会回退 CLI。",
            )

    async def _call(self, arguments, progress=None):
        options = {"progress_callback": progress} if progress else {}
        result = await self.client.call_tool("pcb_uni_inspect", arguments, **options)
        response = result.structured_content
        if not isinstance(response, dict):
            raise TypeError("native V8 structuredContent required")
        texts = [block.text for block in result.content if block.type == "text"]
        if len(texts) != 1 or strict_json(texts[0]) != response:
            raise ValueError("native text/structuredContent mismatch")
        if bool(result.is_error) != (response.get("status") != "ok"):
            raise ValueError("native isError/status mismatch")
        return response

    async def _cancellable_call(self, arguments, progress, cancel):
        # Cancel only this SDK request, never the connection or a shared builder.
        if cancel.is_set():
            raise AdapterError("call_not_started", "分析在提交前已取消。")
        acknowledged = asyncio.Event()

        async def on_progress(value, total=None, message=None):
            acknowledged.set()
            if progress:
                await progress(value, total, message)

        task = asyncio.create_task(self._call(arguments, on_progress))
        try:
            while not task.done():
                if cancel.is_set() and acknowledged.is_set():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    raise AdapterError(
                        "call_cancelled", "已请求取消；等待原生安全步骤结束。"
                    )
                await asyncio.wait({task}, timeout=0.1)
            return await task
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    def call(self, arguments, *, progress=None, cancel=None):
        self._start()
        operation = (
            self._cancellable_call(arguments, progress, cancel)
            if cancel is not None
            else self._call(arguments, progress)
        )
        future = asyncio.run_coroutine_threadsafe(operation, self.loop)
        try:
            return future.result(timeout=self.config.timeout_seconds)
        except FutureTimeout as error:
            future.cancel()
            self.failed = True
            raise AdapterError(
                "transport_timeout",
                "MCP 调用超时，已请求协作取消；可能已有文件，请勿自动重试。",
            ) from error
        except AdapterError:
            raise
        except Exception as error:
            self.failed = True
            raise AdapterError(
                "mcp_call_failed",
                "MCP 调用失败；结果可能不确定，不会自动重试或改走 CLI。",
            ) from error

    def close(self):
        if self.loop and self.stop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.stop.set)
        if self.thread:
            self.thread.join(timeout=self.config.timeout_seconds + 10)
            if self.thread.is_alive():
                raise AdapterError(
                    "shutdown_pending",
                    "MCP 连接仍在安全关闭；宿主应检查本适配器生命周期。",
                )
