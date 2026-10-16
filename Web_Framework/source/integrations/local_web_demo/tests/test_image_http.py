"""Real HTTP regression for cross-port credentials and missing artifacts."""

import base64
import contextlib
import http.cookiejar
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from integrations.local_web_demo.local_speech import SpeechError
from integrations.local_web_demo.server import DemoServer, Handler
from integrations.local_web_demo.storage import FileStore


class ImageHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.servers = []
        self.addCleanup(self.close)
        self.client = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def close(self):
        for server, thread in self.servers:
            server.shutdown()
            server.server_close()
            thread.join()

    def server(self, name):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.token = "test-token-" + name
        server.instance_id = name
        server.conversation = None
        server.analysis = SimpleNamespace(error=None)
        server.exports = SimpleNamespace(formats=["png", "jpg"])
        server.speech = SimpleNamespace(capability={"available": False})
        server._http_error_count = 0
        server._http_error_lock = threading.Lock()
        server.http_error = DemoServer.http_error.__get__(server)
        server.store = FileStore(Path(self.temp.name) / name)
        server.state = lambda: {"server_id": name}
        path = server.store.outputs / "one.png"
        path.write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jR7sAAAAASUVORK5CYII="
            )
        )
        artifact = server.store.register_artifact(
            {"path": str(path), "mime_type": "image/png"}
        )
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.servers.append((server, thread))
        return server, f"http://127.0.0.1:{server.server_address[1]}", artifact

    def get(self, url, headers=None):
        try:
            with self.client.open(
                urllib.request.Request(url, headers=headers or {})
            ) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.headers, error.read()

    def test_two_ports_never_share_credentials_or_set_cookie(self):
        a, base_a, image_a = self.server("a")
        b, base_b, _ = self.server("b")
        for base in (base_a, base_b, base_a):
            status, headers, _ = self.get(base + "/api/health")
            self.assertEqual(status, 200)
            self.assertIsNone(headers.get("Set-Cookie"))
            self.assertIn("blob:", headers["Content-Security-Policy"])
        status, _, data = self.get(
            base_a + image_a["url"],
            {"X-Demo-Token": a.token, "Cookie": "pcb_demo=" + b.token},
        )
        self.assertEqual(status, 200)
        self.assertTrue(data.startswith(b"\x89PNG"))
        with contextlib.redirect_stderr(io.StringIO()):
            status, _, data = self.get(
                base_a + image_a["url"], {"Cookie": "pcb_demo=" + a.token}
            )
            self.assertEqual(status, 403)
            self.assertEqual(json.loads(data)["code"], "authentication_required")
            status, _, _ = self.get(base_a + image_a["url"], {"X-Demo-Token": b.token})
            self.assertEqual(status, 403)

    def test_speech_errors_preserve_actionable_status_and_code(self):
        server, base, _ = self.server("speech")
        for code, status in [
            ("speech_process_crashed", 500),
            ("local_model_unavailable", 503),
            ("speech_timeout", 504),
            ("speech_busy", 409),
            ("invalid_audio", 422),
        ]:
            server.speech.transcribe = Mock(
                side_effect=SpeechError(code, "本机听写诊断", status)
            )
            request = urllib.request.Request(
                base + "/api/dictation",
                b"audio",
                headers={
                    "X-Demo-Token": server.token,
                    "Origin": base,
                    "Content-Type": "audio/wav",
                    "X-Dictation-ID": "abc",
                },
            )
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(urllib.error.HTTPError) as raised,
            ):
                self.client.open(request)
            with raised.exception as response:
                self.assertEqual(response.code, status)
                body = json.load(response)
                self.assertEqual(body["code"], code)
                self.assertEqual(body["error"], "本机听写诊断")

    def test_missing_files_are_classified_and_logs_are_bounded_and_redacted(self):
        server, base, image = self.server("missing")
        server.store.artifact(image["id"])["path"].unlink()
        logs = io.StringIO()
        with contextlib.redirect_stderr(logs):
            status, _, data = self.get(
                base + image["url"], {"X-Demo-Token": server.token}
            )
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(data)["code"], "artifact_missing")
            for _ in range(35):
                self.get(
                    base + "/api/artifacts/unknown", {"X-Demo-Token": server.token}
                )
        entries = logs.getvalue().splitlines()
        self.assertEqual(len(entries), 32)
        self.assertNotIn(server.token, logs.getvalue())
        self.assertNotIn(self.temp.name, logs.getvalue())
        self.assertTrue(
            all(json.loads(line)["resource"] == "artifact" for line in entries)
        )


if __name__ == "__main__":
    unittest.main()
