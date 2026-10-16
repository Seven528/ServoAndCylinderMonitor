"""Repeatable headless and HTTP acceptance; all files belong to test temp roots."""

import io
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from integrations.local_web_demo.analysis import AnalysisService
from integrations.local_web_demo.conversation import Conversation
from integrations.local_web_demo.pressure_picking import PressurePicking
from integrations.local_web_demo.server import REPO, DemoServer
from integrations.local_web_demo.storage import MAX_UPLOAD, DemoError, FileStore
from integrations.local_web_demo.turn_scope import resolve_scope

EXE = REPO / "build/cpp/release/cpp/PCBUNIInspectorAgent"
FIXTURES = REPO / "cpp/tests/fixtures"


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = FileStore(Path(self.temp.name))

    def test_upload_is_stable_and_new_upload_does_not_overwrite(self):
        first = self.store.upload(io.BytesIO(b"123"), 3, "中文板.uni", "pcb")
        second = self.store.upload(io.BytesIO(b"456"), 3, "中文板.uni", "pcb")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.store.resolve(first["id"]).name, "中文板.uni")
        self.assertEqual(self.store.resolve(first["id"]).read_bytes(), b"123")
        self.assertEqual(
            self.store.native_arguments({"pcb_file_id": first["id"]})["pcb_path"],
            str(self.store.resolve(first["id"])),
        )

    def test_invalid_upload_and_path_access(self):
        for name, size, role in [
            ("../a.uni", 3, "pcb"),
            ("a.png", 3, "pcb"),
            ("a.uni", 0, "pcb"),
            ("a.uni", MAX_UPLOAD + 1, "pcb"),
            ("a.uni", 3, "other"),
        ]:
            with (
                self.subTest(name=name, size=size, role=role),
                self.assertRaises(DemoError),
            ):
                self.store.upload(io.BytesIO(b"123"), size, name, role)
        with self.assertRaises(DemoError):
            self.store.upload(io.BytesIO(b"1"), 3, "partial.uni", "pcb")
        self.assertFalse(list(self.store.inputs.glob("*/*.uni")))
        for request in (
            {"pcb_path": "/private/file.uni"},
            {"output_directory": "/tmp"},
            {"pcb_file_id": "unknown"},
            {"files": ["/tmp/a.uni"]},
        ):
            with self.assertRaises(DemoError):
                self.store.native_arguments(request)

    def test_report_paging_filter_and_no_arbitrary_artifact(self):
        path = self.store.outputs / "height.json"
        path.write_text(
            json.dumps(
                {
                    "summary": {"component_count": 3},
                    "components": [
                        {"refdes": "C1", "height_mm": 1, "matches_filter": False},
                        {"refdes": "C2", "height_mm": 3, "matches_filter": True},
                        {"refdes": "C3", "height_mm": 4, "matches_filter": True},
                    ],
                }
            )
        )
        artifact = self.store.register_artifact(
            {"path": str(path), "mime_type": "application/json"}
        )
        self.assertNotIn("path", artifact)
        value = self.store.report(artifact["id"], limit=1, matched=True)
        self.assertEqual(value["filtered_total"], 2)
        self.assertEqual(value["records"][0]["refdes"], "C2")
        self.assertEqual(value["next_offset"], 1)
        self.assertEqual(
            self.store.report(artifact["id"], refdes="C3")["filtered_total"], 1
        )
        with self.assertRaises(DemoError):
            self.store.report(artifact["id"], limit=51)
        with self.assertRaises(DemoError):
            self.store.register_artifact({"path": str(REPO / "README.md")})


@unittest.skipUnless(
    EXE.is_file(), "Build the current checkout's Release executable first"
)
class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FileStore(Path(self.temp.name))
        self.service = AnalysisService(self.store, EXE)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.service.close)
        self.assertIsNone(self.service.error)

    def upload(self, relative, role="pcb"):
        path = REPO / relative
        with path.open("rb") as stream:
            return self.store.upload(stream, path.stat().st_size, path.name, role)["id"]

    def run_job(self, arguments):
        job = self.service.start(arguments)
        self.assertTrue(self.service.jobs[job["id"]]["done"].wait(60))
        return self.service.get(job["id"])

    def test_preview_pressure_height_reports_and_cache(self):
        conversation = Conversation.__new__(Conversation)
        conversation.analysis = self.service
        self.assertIn(
            "above_2_0_mm", conversation.parameter_help()["height_filter_kinds"]
        )
        self.assertNotIn(
            "height_gt", conversation.parameter_help()["height_filter_kinds"]
        )
        native_tool = next(
            tool for tool in conversation.tools() if tool["name"] == "PCBUNIInspector"
        )
        self.assertIn(
            "pcb_file_id",
            native_tool["inputSchema"]["properties"]["arguments"]["properties"],
        )
        self.assertNotIn(
            "image_format",
            native_tool["inputSchema"]["properties"]["arguments"]["properties"],
        )
        pcb = self.upload("cpp/tests/fixtures/agent_single_board_pressure.uni")
        first = self.run_job({"pcb_file_id": pcb})
        self.assertEqual(first["status"], "succeeded", first)
        self.assertEqual(
            len([a for a in first["artifacts"] if a["mime_type"] == "image/png"]), 1
        )
        repeated = self.run_job({"pcb_file_id": pcb})
        self.assertEqual(repeated["meta"]["cache"]["canonical_model"], "hit")
        pressure = self.run_job(
            {
                "pcb_file_id": pcb,
                "analysis": {"kind": "single_board_pressure", "side": "side1"},
            }
        )
        self.assertEqual(pressure["status"], "succeeded", pressure)
        report = next(
            a
            for a in pressure["artifacts"]
            if a["role"] == "single_board_pressure_report"
        )
        records = self.store.report(report["id"])
        self.assertGreater(records["total"], 0)
        jobs = [
            {
                "side": "side1",
                "view_mode": "single",
                "surface_view": "full",
                "filter": {"kind": "all"},
            }
        ]
        height = self.run_job(
            {"pcb_file_id": pcb, "analysis": {"kind": "height_map", "jobs": jobs}}
        )
        self.assertEqual(height["status"], "succeeded", height)
        jobs[0]["filter"] = {"kind": "above_2_0_mm"}
        filtered = self.run_job(
            {"pcb_file_id": pcb, "analysis": {"kind": "height_map", "jobs": jobs}}
        )
        self.assertEqual(filtered["status"], "succeeded", filtered)
        self.assertEqual(filtered["meta"]["cache"]["height_catalog"], "hit")
        for artifact in first["artifacts"]:
            self.assertTrue(self.store.artifact(artifact["id"])["path"].exists())

    def test_mixed_failure_disabled_and_holder(self):
        pcb = self.upload("cpp/tests/fixtures/agent_single_board_pressure.uni")
        bad = self.store.upload(io.BytesIO(b"invalid"), 7, "bad.uni", "pcb")["id"]
        job = self.run_job(
            {
                "tasks": [
                    {"task_id": "good", "kind": "pcb_preview", "pcb_file_id": pcb},
                    {"task_id": "bad", "kind": "pcb_preview", "pcb_file_id": bad},
                ]
            }
        )
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["tasks"][0]["status"], "succeeded")
        self.assertTrue(job["artifacts"])
        disabled = self.run_job(
            {
                "analysis": {
                    "kind": "version_compare",
                    "pairing": "explicit",
                    "pairs": [{"baseline_file_id": pcb, "target_file_id": bad}],
                }
            }
        )
        self.assertEqual(disabled["status"], "failed")
        self.assertIn("feature_disabled", json.dumps(disabled))
        holder = self.upload("cpp/tests/fixtures/agent_holder_render.uni", "holder")
        preview = self.run_job(
            {
                "tasks": [
                    {
                        "task_id": "holder",
                        "kind": "holder_preview",
                        "holder_file_id": holder,
                    }
                ]
            }
        )
        self.assertEqual(preview["status"], "succeeded", preview)

    def test_cancel_retains_files_and_connection(self):
        pcb = self.upload("data/PCB_EP8000_1039N05842_v03_pnl.uni")
        jobs = [
            {
                "side": side,
                "view_mode": view,
                "surface_view": surface,
                "filter": {"kind": "all"},
            }
            for side in ("side1", "side2")
            for view in ("single", "panel")
            for surface in ("full", "components", "copper", "drawings", "mechanical")
        ]
        job = self.service.start(
            {"pcb_file_id": pcb, "analysis": {"kind": "height_map", "jobs": jobs}}
        )
        with self.assertRaises(DemoError):
            self.service.start({"pcb_file_id": pcb})
        deadline = time.monotonic() + 15
        while (
            self.service.get(job["id"]).get("progress") is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        self.service.cancel(job["id"])
        self.assertTrue(
            self.service.jobs[job["id"]]["done"].wait(30),
            "Cancellation did not reach a safe terminal manifest",
        )
        value = self.service.get(job["id"])
        self.assertEqual(value["status"], "cancelled", value)
        self.assertTrue(value["artifacts"], "The terminal manifest should be retained")
        after = self.run_job({"pcb_file_id": pcb})
        self.assertEqual(after["status"], "succeeded", after)
        self.assertFalse(self.service.transport.failed)

    def test_real_pressure_and_both_sides(self):
        pcb = self.upload("data/PCB_EP8000_1039N05842_v03_pnl.uni")
        holder = self.upload("data/Holder_EP8000_1039N06549_v01_pnl.uni", "holder")
        value = self.run_job(
            {
                "holder_file_id": holder,
                "analysis": {
                    "kind": "pressure2d",
                    "pcbs": [
                        {
                            "pcb_file_id": pcb,
                            "sides": [
                                {"side": side, "surface_views": ["components", "full"]}
                                for side in ("side1", "side2")
                            ],
                        }
                    ],
                },
            }
        )
        self.assertEqual(value["status"], "succeeded", value)
        self.assertEqual(
            len([a for a in value["artifacts"] if a["mime_type"] == "image/png"]), 4
        )
        reports = [a for a in value["artifacts"] if a["role"] == "pressure2d_report"]
        self.assertEqual(len(reports), 2)
        self.assertGreater(self.store.report(reports[0]["id"])["total"], 0)
        views = value["presentations"]
        self.assertEqual(len(views), 4)
        self.assertEqual(
            [v["context"]["side"] for v in views], ["side1", "side1", "side2", "side2"]
        )
        self.assertEqual(
            [v["context"]["surface_view"] for v in views],
            ["components", "full", "components", "full"],
        )
        self.assertEqual(views[0]["report_id"], views[1]["report_id"])
        self.assertNotEqual(views[0]["report_id"], views[2]["report_id"])
        self.assertTrue(all(v["context"]["pcb_file_id"] == pcb for v in views))

    def test_agent_four_pcb_pressure_batch_shape_recovery(self):
        # Isolated copies of a repository fixture, never the live browser inputs.
        source = REPO / "data/PCB_EP8000_1039N05842_v03_pnl.uni"
        pcbs = []
        for index in range(4):
            with source.open("rb") as stream:
                pcbs.append(
                    self.store.upload(
                        stream,
                        source.stat().st_size,
                        f"batch-fixture-{index}.uni",
                        "pcb",
                    )["id"]
                )
        holder = self.upload("data/Holder_EP8000_1039N06549_v01_pnl.uni", "holder")
        initial = self.run_job(
            {
                "pcb_file_id": pcbs[0],
                "render_jobs": [
                    {
                        "view_mode": "panel",
                        "surface_view": "components",
                        "sides": ["side1"],
                    }
                ],
            }
        )
        self.assertEqual(initial["status"], "succeeded", initial)
        with patch(
            "integrations.local_web_demo.conversation.CodexBridge", return_value=None
        ):
            conversation = Conversation(self.store, self.service)
        conversation.turn_scope = resolve_scope(
            {
                "presentation_id": initial["presentations"][0]["id"],
                "batch_confirmed": True,
                "batch_file_ids": [*pcbs, holder],
            },
            self.store,
            self.service.snapshot(),
            {"pcb_ids": pcbs, "holder_id": holder},
        )
        for fields in (
            {"side": "side1", "view_mode": "panel", "surface_view": "components"},
            {"sides": ["side1"]},
        ):
            failed = conversation.handle(
                "PCBUNIInspector",
                {
                    "arguments": {
                        "holder_file_id": holder,
                        "analysis": {
                            "kind": "pressure2d",
                            "pcbs": [{"pcb_file_id": fid, **fields} for fid in pcbs],
                        },
                    }
                },
            )
            self.assertFalse(failed["ok"])
            self.assertIn("$.analysis.pcbs[0]", failed["error"])
            self.assertEqual(
                len(self.service.jobs),
                1,
                "Invalid shapes must not allocate native jobs",
            )
        corrected = failed["parameter_help"]["pressure2d"]["current_scope_example"]
        result = conversation.handle("PCBUNIInspector", {"arguments": corrected})
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(self.service.jobs), 2)
        self.assertEqual(len(result["presentations"]), 4)
        requested_ids = [p["pcb_file_id"] for p in corrected["analysis"]["pcbs"]]
        self.assertCountEqual(requested_ids, pcbs)
        self.assertEqual(
            [v["context"]["pcb_file_id"] for v in result["presentations"]],
            requested_ids,
        )
        self.assertTrue(
            all(
                (
                    v["context"]["side"],
                    v["context"]["view_mode"],
                    v["context"]["surface_view"],
                )
                == ("side1", "panel", "components")
                for v in result["presentations"]
            )
        )
        reports = [v["report_id"] for v in result["presentations"]]
        self.assertEqual(len(set(reports)), 4)
        self.assertTrue(all(self.store.report(rid)["total"] > 0 for rid in reports))
        self.assertIsNone(self.service.active)
        self.assertFalse(self.service.transport.failed)

    def test_natural_upload_scope_runs_three_pcbs_with_only_requested_holder(self):
        pcbs = [
            self.upload("data/" + name)
            for name in (
                "PCB_EP8000_1039N05842_v03_pnl.uni",
                "PCB_EP8006_1039N07566_v01_pnl.uni",
                "PCB_EV8210_1039N05162_v05_pnl.uni",
            )
        ]
        h0 = self.upload("data/Holder_EP8000_1039N06549_v01_pnl.uni", "holder")
        h6 = self.upload("data/Holder_EP8006_1039N08223_v01_pnl.uni", "holder")
        initial = self.run_job(
            {
                "pcb_file_id": pcbs[0],
                "render_jobs": [
                    {
                        "view_mode": "panel",
                        "surface_view": "components",
                        "sides": ["side1"],
                    }
                ],
            }
        )
        self.assertEqual(initial["status"], "succeeded", initial)
        scope_value = {"presentation_id": initial["presentations"][0]["id"]}
        selection = {"pcb_ids": [pcbs[0]], "holder_id": h0}
        with patch(
            "integrations.local_web_demo.conversation.CodexBridge", return_value=None
        ):
            conversation = Conversation(self.store, self.service)
        conversation.turn_scope = resolve_scope(
            scope_value,
            self.store,
            self.service.snapshot(),
            selection,
            "使用EP8006 Holder对三份PCB Panel Side1分析压棒干涉",
        )
        self.assertEqual(conversation.turn_scope.file_ids, {*pcbs, h6})
        self.assertNotIn(h0, conversation.turn_scope.file_ids)
        arguments = conversation.context()["parameter_help"]["pressure2d"][
            "current_scope_example"
        ]
        self.assertEqual(arguments["holder_file_id"], h6)
        result = conversation.handle("PCBUNIInspector", {"arguments": arguments})
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["presentations"]), 3)
        self.assertCountEqual(
            [v["context"]["pcb_file_id"] for v in result["presentations"]], pcbs
        )
        self.assertTrue(
            all(v["context"]["holder_file_id"] == h6 for v in result["presentations"])
        )
        self.assertTrue(
            all(
                self.store.report(v["report_id"])["total"] > 0
                for v in result["presentations"]
            )
        )
        conversation.turn_scope = resolve_scope(
            scope_value, self.store, self.service.snapshot(), selection, "检查当前PCB"
        )
        before = len(self.service.jobs)
        denied = conversation.handle("PCBUNIInspector", {"arguments": arguments})
        self.assertFalse(denied["ok"])
        self.assertEqual(len(self.service.jobs), before)

    def test_remove_from_real_batch_preserves_remaining_report_and_original_files(self):
        a = self.upload("cpp/tests/fixtures/agent_single_board_pressure.uni")
        b = self.upload("cpp/tests/fixtures/agent_single_board_pressure.uni")
        source_a = self.store.resolve(a)
        result = self.run_job(
            {
                "tasks": [
                    {
                        "task_id": "pcb-" + str(i),
                        "kind": "single_board_pressure",
                        "pcb_file_id": fid,
                    }
                    for i, fid in enumerate((a, b))
                ]
            }
        )
        self.assertEqual(result["status"], "succeeded", result)
        output_paths = [
            self.store.artifact(item["id"])["path"] for item in result["artifacts"]
        ]
        self.service.remove_file(a)
        job = self.service.snapshot()["jobs"][0]
        self.assertEqual(len(job["presentations"]), 1)
        view = job["presentations"][0]
        self.assertEqual(view["context"]["pcb_file_id"], b)
        self.assertGreater(self.store.report(view["report_id"])["total"], 0)
        self.assertTrue(source_a.is_file())
        self.assertTrue(all(path.is_file() for path in output_paths))
        with self.assertRaises(DemoError):
            self.service.start({"pcb_file_id": a})
        self.assertEqual(len(self.service.jobs), 1)
        self.assertEqual(self.run_job({"pcb_file_id": b})["status"], "succeeded")

    def test_pressure_picking_real_both_sides_components_only_and_read_only(self):
        pcb = self.upload("data/PCB_EP8006_1039N07566_v01_pnl.uni")
        holder = self.upload("data/Holder_EP8000_1039N06549_v01_pnl.uni", "holder")
        result = self.run_job(
            {
                "holder_file_id": holder,
                "analysis": {
                    "kind": "pressure2d",
                    "pcbs": [
                        {
                            "pcb_file_id": pcb,
                            "sides": [
                                {"side": side, "surface_views": ["components", "full"]}
                                for side in ("side1", "side2")
                            ],
                        }
                    ],
                },
            }
        )
        self.assertEqual(result["status"], "succeeded", result)
        reader = PressurePicking(self.store, self.service)
        contacts_seen = False
        for view in result["presentations"]:
            if view["context"]["surface_view"] != "components":
                self.assertFalse(view.get("picking_available"))
                with self.assertRaises(DemoError):
                    reader.read(view["id"])
                continue
            self.assertTrue(view["picking_available"])
            picking = reader.read(view["id"])
            report = self.store.read_report(view["report_id"])
            self.assertEqual(
                len(picking["targets"]), report["summary"]["pressure_head_count"]
            )
            for index, head in enumerate(report["pressure_heads"]):
                target = picking["targets"][index]
                self.assertEqual(target["head_index"], index)
                self.assertEqual(target["pressure_head_id"], head["pressure_head_id"])
            hit = next(
                (i for i, h in enumerate(report["pressure_heads"]) if h["contacts"]), 0
            )
            detail = reader.read(view["id"], hit)
            self.assertEqual(
                [
                    {k: v for k, v in c.items() if k != "highlight"}
                    for c in detail["contacts"]
                ],
                report["pressure_heads"][hit]["contacts"][:50],
            )
            for contact in detail["contacts"]:
                if contact["role"] == "component_body":
                    contacts_seen = True
                    self.assertTrue(contact["component_id"])
                    self.assertTrue(contact["package"])
                    self.assertGreater(contact["component_source"]["start_line"], 0)
                    self.assertTrue(contact["bounds_mm"])
                    self.assertEqual(
                        contact["highlight"]["component_id"], contact["component_id"]
                    )
                    nearby = next(
                        (
                            n
                            for n in detail["nearest_components"]
                            if n["component_id"] == contact["component_id"]
                        ),
                        None,
                    )
                    if nearby:
                        self.assertEqual(contact["bounds_mm"], nearby["bounds_mm"])
                        self.assertEqual(contact["highlight"], nearby["highlight"])
        self.assertTrue(contacts_seen)
        self.assertEqual(
            len(self.service.jobs), 1, "Picking must never create another analysis"
        )


@unittest.skipUnless(
    EXE.is_file(), "Build the current checkout's Release executable first"
)
class HttpTests(unittest.TestCase):
    def test_origin_upload_header_and_download(self):
        with tempfile.TemporaryDirectory() as temp:
            server = DemoServer(0, EXE, Path(temp), with_codex=False)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            base = "http://127.0.0.1:" + str(server.server_address[1])
            try:
                health = json.load(urllib.request.urlopen(base + "/api/health"))
                token = health["token"]
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(base + "/api/state")
                denied.exception.close()
                headers = {"X-Demo-Token": token, "Origin": base}
                source = (FIXTURES / "agent_single_board_pressure.uni").read_bytes()
                request = urllib.request.Request(
                    base + "/api/upload?name=uploaded.uni&role=pcb",
                    data=source,
                    headers=headers,
                )
                item = json.load(urllib.request.urlopen(request))
                headers["Content-Type"] = "application/json"
                request = urllib.request.Request(
                    base + "/api/analysis",
                    data=json.dumps(
                        {"arguments": {"pcb_file_id": item["id"]}}
                    ).encode(),
                    headers=headers,
                )
                job = json.load(urllib.request.urlopen(request))
                server.analysis.jobs[job["id"]]["done"].wait(30)
                job = server.analysis.get(job["id"])
                image = next(
                    a for a in job["artifacts"] if a["mime_type"] == "image/png"
                )
                request = urllib.request.Request(
                    base + image["url"], headers={"X-Demo-Token": token}
                )
                self.assertTrue(
                    urllib.request.urlopen(request)
                    .read()
                    .startswith(b"\x89PNG\r\n\x1a\n")
                )
                headers["Origin"] = "https://unrelated.example"
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(
                        urllib.request.Request(
                            base + "/api/analysis", data=b"{}", headers=headers
                        )
                    )
                denied.exception.close()
            finally:
                server.shutdown()
                thread.join()
                server.close_owned()


if __name__ == "__main__":
    unittest.main()
