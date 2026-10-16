"""Session withdrawal preserves disk evidence and cannot race job admission."""

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
from unittest.mock import Mock, patch

from integrations.local_web_demo.analysis import AnalysisService
from integrations.local_web_demo.image_exports import ImageExports
from integrations.local_web_demo.server import DemoServer, Handler
from integrations.local_web_demo.storage import DemoError, FileStore, WorkspaceBusy
from integrations.local_web_demo.turn_scope import resolve_scope


class FileRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = FileStore(Path(self.temp.name))
        self.a, self.b, self.h = [
            self.store.upload(io.BytesIO(b"UNI"), 3, name, role)["id"]
            for name, role in (
                ("same.uni", "pcb"),
                ("same.uni", "pcb"),
                ("holder.uni", "holder"),
            )
        ]
        self.source = self.store.resolve(self.a)
        self.service = AnalysisService.__new__(AnalysisService)
        self.service.store = self.store
        self.service.lock = threading.RLock()
        self.service.active = None
        self.service.exporting = False
        self.service.closed = False
        self.service.error = None
        self.service.transport = SimpleNamespace(
            tool_definition={"inputSchema": {"properties": {}}}, call=Mock()
        )
        artifacts, views = [], []
        for fid in (self.a, self.b):
            path = self.store.outputs / (fid + ".json")
            path.write_text(json.dumps({"targets": [{"refdes": "U1"}]}))
            artifact = self.store.register_artifact(
                {"path": str(path), "mime_type": "application/json"}
            )
            artifacts.append(artifact)
            views.append(
                {
                    "id": "view-" + fid,
                    "job_id": "job",
                    "image_id": "img-" + fid,
                    "report_id": artifact["id"],
                    "status": "succeeded",
                    "context": {
                        "pcb_file_id": fid,
                        "holder_file_id": self.h,
                        "kind": "pressure2d",
                    },
                }
            )
        self.service.jobs = {
            "job": {
                "id": "job",
                "arguments": {
                    "holder_file_id": self.h,
                    "analysis": {
                        "kind": "pressure2d",
                        "pcbs": [{"pcb_file_id": fid} for fid in (self.a, self.b)],
                    },
                },
                "status": "succeeded",
                "presentations": views,
                "artifacts": artifacts,
                "tasks": [],
            }
        }
        self.original_reports = [
            self.store.artifact(a["id"])["path"] for a in artifacts
        ]
        self.server = SimpleNamespace(
            analysis=self.service,
            store=self.store,
            conversation=None,
            instance_id="test",
            selection={"pcb_ids": [self.a, self.b], "holder_id": self.h},
        )
        self.server.state = DemoServer.state.__get__(self.server)
        self.server.remove_file = DemoServer.remove_file.__get__(self.server)

    def test_same_name_removes_only_exact_identity_and_preserves_disk(self):
        result = self.server.remove_file({"file_id": self.a})
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["file_revision"], 1)
        self.assertEqual(
            result["state"]["selection"], {"pcb_ids": [self.b], "holder_id": self.h}
        )
        self.assertEqual({f["id"] for f in self.store.listing()}, {self.b, self.h})
        self.assertEqual(self.source.read_bytes(), b"UNI")
        self.assertTrue(all(path.is_file() for path in self.original_reports))
        with self.assertRaises(DemoError):
            self.store.resolve(self.a)
        with self.assertRaises(DemoError):
            self.store.require_original_source(self.a)
        self.assertTrue(self.store.resolve(self.b).is_file())
        again = self.server.remove_file({"file_id": self.a})
        self.assertEqual(again["state"]["file_revision"], 1)
        self.assertEqual(again["removed_presentation_ids"], [])
        new = self.store.upload(io.BytesIO(b"UNI"), 3, "same.uni", "pcb")
        self.assertNotIn(new["id"], [self.a, self.b])

    def test_partial_batch_keeps_other_unit_without_rewriting_executed_arguments(self):
        original = json.dumps(self.service.jobs["job"]["arguments"], sort_keys=True)
        snapshot = self.server.remove_file({"file_id": self.a})["state"]
        self.assertEqual(len(snapshot["jobs"]), 1)
        job = snapshot["jobs"][0]
        self.assertEqual(
            [v["context"]["pcb_file_id"] for v in job["presentations"]], [self.b]
        )
        self.assertEqual(
            [a["id"] for a in job["artifacts"]], [job["presentations"][0]["report_id"]]
        )
        self.assertEqual(json.dumps(job["arguments"], sort_keys=True), original)
        self.assertEqual(job["removed_file_ids"], [self.a])
        self.assertEqual(len(self.service.jobs["job"]["artifacts"]), 2)

    def test_holder_removal_withdraws_dependencies_not_unrelated_pcb_preview(self):
        preview = {
            "id": "preview",
            "arguments": {"pcb_file_id": self.b},
            "presentations": [
                {
                    "id": "pcb-only",
                    "context": {"pcb_file_id": self.b, "kind": "pcb_preview"},
                }
            ],
            "artifacts": [],
            "tasks": [],
        }
        self.service.jobs["preview"] = preview
        result = self.server.remove_file({"file_id": self.h})
        self.assertIsNone(result["state"]["selection"]["holder_id"])
        self.assertEqual([j["id"] for j in result["state"]["jobs"]], ["preview"])
        self.assertEqual(
            len(self.service.jobs), 2, "Cumulative job admission cap is retained"
        )

    def test_removed_view_cannot_authorize_report_analysis_or_svg(self):
        self.server.remove_file({"file_id": self.a})
        with self.assertRaises(DemoError):
            resolve_scope(
                {"presentation_id": "view-" + self.a},
                self.store,
                self.service.snapshot(),
                self.server.selection,
            )
        with self.assertRaises(DemoError):
            self.service.start({"pcb_file_id": self.a})
        self.service.transport.call.assert_not_called()
        self.service.transport.tool_definition["inputSchema"]["properties"][
            "image_format"
        ] = {"enum": ["png", "svg"]}
        with self.assertRaises(DemoError):
            ImageExports(self.store, self.service).export(
                {"presentation_id": "view-" + self.a, "format": "svg"}
            )
        scope = resolve_scope(
            {"presentation_id": "view-" + self.b},
            self.store,
            self.service.snapshot(),
            self.server.selection,
        )
        self.assertFalse(
            scope.report_views(
                self.service.snapshot(),
                self.store.public_artifact(
                    self.store.artifact(next(iter(self.store.artifacts)))
                )["id"],
            )
        )

    def test_busy_analysis_export_and_chat_leave_all_files_untouched(self):
        for field, value in (("active", "job"), ("exporting", True)):
            setattr(self.service, field, value)
            with self.assertRaises(WorkspaceBusy):
                self.server.remove_file({"file_id": self.a})
            setattr(self.service, field, None if field == "active" else False)
        chat = SimpleNamespace(lock=threading.Lock())
        self.server.conversation = chat
        chat.lock.acquire()
        with self.assertRaises(WorkspaceBusy):
            self.server.remove_file({"file_id": self.a})
        chat.lock.release()
        with self.assertRaises(DemoError):
            self.server.remove_file({"file_id": "unknown"})
        self.assertFalse(chat.lock.locked())
        self.assertEqual(len(self.store.listing()), 3)
        self.assertEqual(self.store.file_revision, 0)

    def test_job_path_resolution_and_removal_share_admission_lock(self):
        entered, release = threading.Event(), threading.Event()
        original = self.store.native_arguments
        results = []

        def resolving(value, depth=0):
            if depth == 0:
                entered.set()
                self.assertTrue(release.wait(5))
            return original(value, depth)

        def removing():
            try:
                self.server.remove_file({"file_id": self.a})
                results.append("removed")
            except WorkspaceBusy:
                results.append("busy")

        with (
            patch.object(self.store, "native_arguments", side_effect=resolving),
            patch.object(self.service, "_run"),
        ):
            starter = threading.Thread(
                target=self.service.start, args=({"pcb_file_id": self.a},)
            )
            starter.start()
            self.assertTrue(entered.wait(5))
            remover = threading.Thread(target=removing)
            remover.start()
            release.set()
            starter.join(5)
            remover.join(5)
            self.assertFalse(starter.is_alive() or remover.is_alive())
        self.assertEqual(results, ["busy"])
        self.assertTrue(self.store.resolve(self.a).is_file())

    def test_removed_uploads_still_count_toward_bounded_session_admission(self):
        for i in range(37):
            item = self.store.upload(io.BytesIO(b"UNI"), 3, f"bounded-{i}.uni", "pcb")
            self.store.remove(item["id"])
        with self.assertRaises(DemoError):
            self.store.upload(io.BytesIO(b"UNI"), 3, "too-many.uni", "pcb")

    def test_authenticated_http_contract_and_busy_status(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        for key in ("analysis", "store", "conversation", "instance_id", "selection"):
            setattr(server, key, getattr(self.server, key))
        server.state = DemoServer.state.__get__(server)
        server.remove_file = DemoServer.remove_file.__get__(server)
        server.token = "test-removal-token"
        server.http_error = Mock()
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def post(body, *, token=server.token, origin=base, route="files/remove"):
            request = urllib.request.Request(
                base + "/api/" + route,
                json.dumps(body).encode(),
                headers={
                    "Origin": origin,
                    "X-Demo-Token": token,
                    "Content-Type": "application/json",
                },
            )
            try:
                response = urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.status, json.load(response)

        try:
            self.assertEqual(post({"file_id": self.a}, token="")[0], 403)
            self.assertEqual(
                post({"file_id": self.a}, origin="https://foreign.invalid")[0], 403
            )
            for body in (
                {},
                {"file_id": "unknown"},
                {"file_id": self.a, "path": str(self.source)},
                {"file_id": [self.a]},
            ):
                self.assertEqual(post(body)[0], 400)
            self.service.exporting = True
            status, body = post({"file_id": self.a})
            self.assertEqual((status, body["code"]), (409, "workspace_busy"))
            self.service.exporting = False
            status, body = post({"file_id": self.a})
            self.assertEqual(status, 200)
            self.assertEqual(body["state"]["file_revision"], 1)
            self.assertEqual(body["state"]["selection"]["pcb_ids"], [self.b])
            self.assertEqual(post({"pcb_ids": [self.a]}, route="selection")[0], 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
