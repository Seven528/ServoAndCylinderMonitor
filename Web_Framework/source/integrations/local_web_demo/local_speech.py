"""One bounded macOS on-device transcription; no remote service or retained audio."""

import io
import json
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

from .storage import DemoError

MAX_AUDIO = 2 * 1024 * 1024


class SpeechError(DemoError):
    def __init__(self, code, message, status=503):
        super().__init__(message)
        self.code, self.status = code, status


def validate_wav(data):
    if not 44 < len(data) <= MAX_AUDIO:
        raise DemoError("录音超过大小限制。")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if (
                audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getframerate() != 16000
                or audio.getcomptype() != "NONE"
                or not 0 < audio.getnframes() <= 960000
            ):
                raise DemoError("需要 60 秒以内、16kHz 单声道 PCM 录音。")
            frames = audio.readframes(audio.getnframes())
            if len(frames) != audio.getnframes() * 2:
                raise DemoError("录音文件不完整。")
    except (wave.Error, EOFError) as error:
        raise DemoError("录音不是有效 WAV 文件。") from error


class LocalSpeech:
    def __init__(self, executable: Path):
        self.executable = executable
        self.lock = threading.RLock()
        self.current = None
        self.process = None
        self.cancelled = False
        self.capability = {"available": False, "engine": "macos-on-device"}
        self.probe()

    def probe(self):
        if self.executable.is_file():
            try:
                probe = subprocess.run(
                    [str(self.executable), "--probe"],
                    capture_output=True,
                    timeout=8,
                    check=False,
                )
                if probe.returncode == 0 and len(probe.stdout) <= 8192:
                    result = json.loads(probe.stdout)
                    if isinstance(result, dict):
                        self.capability.update(result)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass

    def _begin(self, request_id):
        with self.lock:
            if self.current:
                raise SpeechError(
                    "speech_busy", "已有本机语音操作正在进行，请稍候。", 409
                )
            self.current, self.cancelled = request_id, False

    def _finish(self):
        with self.lock:
            self.current = self.process = None

    def _invoke(self, arguments, timeout):
        with self.lock:
            if self.cancelled:
                raise SpeechError("speech_cancelled", "听写已取消。", 409)
            try:
                process = subprocess.Popen(
                    [str(self.executable), *arguments],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as error:
                raise SpeechError(
                    "speech_launch_failed",
                    "无法启动本机转写程序，请重新运行启动脚本。",
                    500,
                ) from error
            self.process = process
        try:
            raw, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise SpeechError(
                "speech_timeout", "本机语音操作超时，已停止；未启用在线识别。", 504
            ) from None
        with self.lock:
            if self.cancelled:
                raise SpeechError("speech_cancelled", "听写已取消。", 409)
        if process.returncode is not None and process.returncode < 0:
            raise SpeechError(
                "speech_process_crashed",
                "本机语音进程被系统终止；请查看本机语音诊断，不是网络或录音格式错误。",
                500,
            )
        if len(raw) > 64 * 1024:
            raise SpeechError("speech_result_limit", "本机转写结果超限。", 500)
        try:
            result = json.loads(raw)
        except ValueError:
            raise SpeechError(
                "speech_invalid_result", "本机语音进程未返回有效结果。", 500
            ) from None
        if not isinstance(result, dict):
            raise SpeechError(
                "speech_invalid_result", "本机语音返回的结果类型无效。", 500
            )
        if (
            process.returncode
            or result.get("status") != "ok"
            or result.get("on_device") is not True
        ):
            code = str(result.get("code") or "speech_engine_failed")[:64]
            status = (
                422
                if code in {"invalid_audio", "no_speech"}
                else 504
                if code == "local_timeout"
                else 503
            )
            raise SpeechError(
                code,
                str(result.get("message") or "本机识别失败，未启用云端回退。")[:400],
                status,
            )
        return result

    def prepare(self):
        if not self.capability.get("available"):
            raise SpeechError(
                "speech_unavailable", "本机语音接口不可用，需要 macOS 26 或更新版本。"
            )
        self._begin("prepare")
        try:
            self._invoke(["--prepare"], 250)
            self.probe()
            return dict(self.capability)
        finally:
            self._finish()

    def transcribe(self, stream, size, request_id):
        if not self.capability.get("available"):
            raise SpeechError(
                "speech_unavailable",
                "Mac 本机识别引擎未就绪，请使用启动脚本准备运行环境。",
            )
        if not self.capability.get("model_ready"):
            raise SpeechError(
                "local_model_unavailable", "请先在听写窗口准备中文离线模型。"
            )
        if (
            not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 64
            or any(c not in "0123456789abcdef-" for c in request_id)
        ):
            raise SpeechError("invalid_audio_request", "听写请求标识无效。", 422)
        if not 44 < size <= MAX_AUDIO:
            raise SpeechError("invalid_audio", "录音大小无效。", 422)
        self._begin(request_id)
        try:
            data = stream.read(size)
            if len(data) != size:
                raise SpeechError("invalid_audio", "录音上传到本机未完成。", 422)
            try:
                validate_wav(data)
            except DemoError as error:
                raise SpeechError("invalid_audio", str(error), 422) from error
            with tempfile.TemporaryDirectory(
                prefix="pcb-local-dictation-"
            ) as directory:
                path = Path(directory) / "audio.wav"
                path.write_bytes(data)
                result = self._invoke(["--transcribe", str(path)], 75)
                return {"text": str(result.get("text", ""))[:8000], "on_device": True}
        finally:
            self._finish()

    def cancel(self, request_id=None):
        with self.lock:
            if self.current and (request_id is None or request_id == self.current):
                self.cancelled = True
                if self.process and self.process.poll() is None:
                    self.process.terminate()
