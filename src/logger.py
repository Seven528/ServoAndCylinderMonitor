"""按日追加 UTF-8 日志，保留原有 Logger 调用接口。"""
import os
import sys
import time
import traceback
from contextlib import contextmanager
from uuid import uuid4
from datetime import datetime
from threading import RLock


class Logger:
    def __init__(self, log_dir):
        self.log_dir = log_dir
        self._lock = RLock()
        self.log_file = self.create_file()

    def _file_for(self, now):
        return os.path.join(self.log_dir, "logger", f"{now:%Y%m%d}.log")

    def create_file(self):
        """创建日志目录并返回当天路径；首次写入时才创建日志文件。"""
        try:
            os.makedirs(os.path.join(self.log_dir, "logger"), exist_ok=True)
            return self._file_for(datetime.now())
        except OSError as exc:
            raise OSError("Log file cannot be created.") from exc

    def update_log_file_if_needed(self):
        with self._lock:
            self.log_file = self._file_for(datetime.now())

    def write_log(self, log_type, module_name, error_message):
        message = str(error_message)
        if str(log_type).upper() in {"ERROR", "CRITICAL"}:
            # except 中的旧调用 write_log("ERROR", module, str(exc)) 同样记录堆栈。
            exc = error_message if isinstance(error_message, BaseException) else sys.exc_info()[1]
            if exc is not None and exc.__traceback__ is not None:
                message += "\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
            else:
                caller = sys._getframe(1)
                try:
                    message += f"\n  File \"{os.path.abspath(caller.f_code.co_filename)}\", line {caller.f_lineno}, in {caller.f_code.co_name}"
                finally:
                    del caller
        with self._lock:
            # 文件名与日志时间使用同一次取时，避免跨午夜时写入错误日期。
            now = datetime.now()
            self.log_file = self._file_for(now)
            info = "{} | {:>10} | <{:^25}>: {} \n".format(
                now.strftime("%Y-%m-%d %H:%M:%S"),
                log_type, module_name, message,
            )
            with open(self.log_file, "a", encoding="utf-8") as stream:
                stream.write(info)


    @contextmanager
    def run(self, script_path):
        """记录一次主程序运行；异常写入后继续抛出，保留调试和退出行为。"""
        script = os.path.abspath(os.fspath(script_path))
        module = os.path.basename(script)
        run_id = uuid4().hex[:12]
        context = f"run_id={run_id} | pid={os.getpid()} | script={script}"
        started = time.perf_counter()
        self.write_log("INFO", module, f"RUN_START | {context}")
        try:
            yield self
        except BaseException as exc:
            successful_exit = isinstance(exc, SystemExit) and exc.code in (None, 0)
            level = "INFO" if successful_exit else "ERROR"
            status = "success" if successful_exit else "failed"
            try:
                self.write_log(level, module,
                               f"RUN_END | status={status} | {context} | elapsed={time.perf_counter() - started:.3f}s")
            except Exception as log_error:
                # 写日志失败时不能覆盖导致本次运行失败的原始异常。
                print(f"无法写入运行结束日志：{log_error}", file=sys.stderr)
            raise
        else:
            self.write_log("INFO", module,
                           f"RUN_END | status=success | {context} | elapsed={time.perf_counter() - started:.3f}s")
