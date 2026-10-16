import io
import json
import subprocess
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from integrations.local_web_demo.local_speech import (
    LocalSpeech,
    SpeechError,
    validate_wav,
)
from integrations.local_web_demo.storage import DemoError


class LocalSpeechTests(unittest.TestCase):
    def test_process_failure_timeout_and_missing_model_have_distinct_codes(self):
        speech = LocalSpeech(Path("missing-test-speech-helper"))
        speech.capability.update(available=True, model_ready=False)
        with self.assertRaises(SpeechError) as missing:
            speech.transcribe(io.BytesIO(b"x" * 50), 50, "abc")
        self.assertEqual(
            (missing.exception.code, missing.exception.status),
            ("local_model_unavailable", 503),
        )
        cases = [
            (-6, b"", "speech_process_crashed", 500),
            (0, b"invalid json", "speech_invalid_result", 500),
            (
                1,
                b'{"code":"no_speech","message":"No speech","status":"error","on_device":true}',
                "no_speech",
                422,
            ),
            (0, b'{"status":"ok","on_device":false}', "speech_engine_failed", 503),
        ]
        for returncode, output, code, status in cases:
            process = Mock(returncode=returncode)
            process.communicate.return_value = (output, b"")
            with (
                patch(
                    "integrations.local_web_demo.local_speech.subprocess.Popen",
                    return_value=process,
                ),
                self.assertRaises(SpeechError) as raised,
            ):
                speech._invoke(["--transcribe", "test.wav"], 1)
            self.assertEqual(
                (raised.exception.code, raised.exception.status), (code, status)
            )
        process = Mock(returncode=-9)
        process.communicate.side_effect = [
            subprocess.TimeoutExpired("helper", 1),
            (b"", b""),
        ]
        with (
            patch(
                "integrations.local_web_demo.local_speech.subprocess.Popen",
                return_value=process,
            ),
            self.assertRaises(SpeechError) as timeout,
        ):
            speech._invoke(["--transcribe", "test.wav"], 1)
        self.assertEqual(timeout.exception.status, 504)
        process.kill.assert_called_once()

    def test_cancellation_is_owned_and_single_flight(self):
        speech = LocalSpeech(Path("missing-test-speech-helper"))
        speech._begin("abc")
        process = Mock()
        process.poll.return_value = None
        speech.process = process
        speech.cancel("other")
        process.terminate.assert_not_called()
        with self.assertRaises(SpeechError) as busy:
            speech._begin("def")
        self.assertEqual(busy.exception.status, 409)
        speech.cancel("abc")
        process.terminate.assert_called_once()
        speech._finish()
        self.assertIsNone(speech.process)

    def test_owned_temporary_audio_is_removed_after_success_or_failure(self):
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 160)
        data = output.getvalue()
        speech = LocalSpeech(Path("missing-test-speech-helper"))
        speech.capability["available"] = True
        speech.capability["model_ready"] = True
        captured = []

        def create_process(arguments, **_kwargs):
            self.assertEqual(arguments[1], "--transcribe")
            path = Path(arguments[2])
            self.assertEqual(path.read_bytes(), data)
            captured.append(path)
            process = Mock(returncode=0)
            process.communicate.return_value = (
                json.dumps(
                    {"status": "ok", "on_device": True, "text": "本机测试"}
                ).encode(),
                b"",
            )
            return process

        with patch(
            "integrations.local_web_demo.local_speech.subprocess.Popen",
            side_effect=create_process,
        ):
            self.assertEqual(
                speech.transcribe(io.BytesIO(data), len(data), "abc")["text"],
                "本机测试",
            )
        self.assertTrue(all(not path.exists() for path in captured))
        self.assertIsNone(speech.current)
        self.assertIsNone(speech.process)
        with (
            patch(
                "integrations.local_web_demo.local_speech.subprocess.Popen",
                side_effect=OSError("test failure"),
            ),
            self.assertRaises(SpeechError),
        ):
            speech.transcribe(io.BytesIO(data), len(data), "abc")
        self.assertIsNone(speech.current)

    def test_only_bounded_pcm_is_accepted(self):
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 16000)
        validate_wav(output.getvalue())
        for data in [
            b"",
            b"invalid" * 100,
            output.getvalue()[:-10],
            b"x" * (2 * 1024 * 1024 + 1),
        ]:
            with self.assertRaises(DemoError):
                validate_wav(data)

    def test_stereo_and_other_sample_rates_are_rejected(self):
        for channels, rate in [(2, 16000), (1, 48000)]:
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(channels)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes(b"\0\0" * 100 * channels)
            with self.assertRaises(DemoError):
                validate_wav(output.getvalue())
