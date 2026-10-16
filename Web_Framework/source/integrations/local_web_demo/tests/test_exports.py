import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from xml.etree import ElementTree

from jsonschema import Draft202012Validator

from integrations.local_web_demo.analysis import AnalysisService
from integrations.local_web_demo.image_exports import ImageExports, export_arguments
from integrations.local_web_demo.server import REPO
from integrations.local_web_demo.storage import DemoError, FileStore

EXE = REPO / "build/cpp/release/cpp/PCBUNIInspectorAgent"


class ExportTests(unittest.TestCase):
    @unittest.skipUnless(EXE.exists(), "native executable required")
    def test_single_board_surfaces_preserve_evaluation_and_vector_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            data = (
                REPO / "cpp/tests/fixtures/agent_single_board_pressure.uni"
            ).read_bytes()
            pcb = store.upload(io.BytesIO(data), len(data), "pressure.uni", "pcb")
            service = AnalysisService(store, EXE)
            exports = ImageExports(store, service)
            surfaces = ["full", "components", "copper", "drawings", "mechanical"]
            validator = Draft202012Validator(
                json.loads(
                    (REPO / "docs/schemas/agent-response-v8.schema.json").read_text()
                )
            )
            original_call = service.transport.call

            def checked_call(*args, **kwargs):
                response = original_call(*args, **kwargs)
                validator.validate(response)
                return response

            service.transport.call = checked_call
            try:
                self.assertEqual(service.single_board_surfaces, surfaces)
                for side in ("side1", "side2"):
                    reports = []
                    for surface in surfaces:
                        job = service.start(
                            {
                                "tasks": [
                                    {
                                        "task_id": "single",
                                        "kind": "single_board_pressure",
                                        "pcb_file_id": pcb["id"],
                                        "sides": [side],
                                        "surface_view": surface,
                                    }
                                ]
                            }
                        )
                        self.assertTrue(service.jobs[job["id"]]["done"].wait(30))
                        result = service.get(job["id"])
                        self.assertEqual(
                            result["status"], "succeeded", result.get("diagnostics")
                        )
                        self.assertEqual(len(result["presentations"]), 1)
                        view = result["presentations"][0]
                        self.assertEqual(view["context"]["surface_view"], surface)
                        self.assertEqual(view["context"]["side"], side)
                        reports.append(
                            store.artifact(view["report_id"])["path"].read_bytes()
                        )
                        svg = exports.export(
                            {"presentation_id": view["id"], "format": "svg"}
                        )
                        self.assertEqual(svg["mime_type"], "image/svg+xml")
                        self.assertIn("-" + surface + "-", svg["name"])
                        root = ElementTree.parse(
                            store.artifact(svg["id"])["path"]
                        ).getroot()
                        self.assertIsNone(
                            root.find(".//{http://www.w3.org/2000/svg}image")
                        )
                    self.assertTrue(all(raw == reports[0] for raw in reports))
                self.assertEqual(len(service.snapshot()["jobs"]), 10)
            finally:
                exports.close()
                service.close()

    def test_export_identity_uses_the_result_not_current_draft(self):
        value = export_arguments(
            {
                "kind": "pressure2d",
                "pcb_file_id": "pcb",
                "holder_file_id": "holder",
                "side": "side2",
                "surface_view": "full",
            }
        )
        self.assertEqual(
            value["analysis"]["pcbs"],
            [
                {
                    "pcb_file_id": "pcb",
                    "sides": [{"side": "side2", "surface_views": ["full"]}],
                }
            ],
        )
        with self.assertRaises(DemoError):
            export_arguments({"kind": "height_map"})

    @unittest.skipUnless(EXE.exists(), "native executable required")
    def test_true_svg_download_reuses_native_cache_and_keeps_png(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            data = (REPO / "cpp/tests/fixtures/height_map_filter.uni").read_bytes()
            pcb = store.upload(io.BytesIO(data), len(data), "height.uni", "pcb")
            service = AnalysisService(store, EXE)
            exports = ImageExports(store, service)
            validator = Draft202012Validator(
                json.loads(
                    (REPO / "docs/schemas/agent-response-v8.schema.json").read_text()
                )
            )
            original_call = service.transport.call

            def checked_call(*args, **kwargs):
                response = original_call(*args, **kwargs)
                validator.validate(response)
                return response

            service.transport.call = checked_call
            try:
                for arguments in [
                    {"pcb_file_id": pcb["id"]},
                    {"pcb_file_id": pcb["id"], "analysis": {"kind": "height_map"}},
                ]:
                    job = service.start(arguments)
                    deadline = time.monotonic() + 30
                    while (
                        service.snapshot()["active_job"] and time.monotonic() < deadline
                    ):
                        time.sleep(0.02)
                    result = next(
                        item
                        for item in service.snapshot()["jobs"]
                        if item["id"] == job["id"]
                    )
                    self.assertEqual(
                        result["status"], "succeeded", result.get("diagnostics")
                    )
                    view = result["presentations"][0]
                    png = store.artifact(view["image_id"])["path"]
                    original = png.read_bytes()
                    artifact = exports.export(
                        {"presentation_id": view["id"], "format": "svg"}
                    )
                    self.assertEqual(artifact["mime_type"], "image/svg+xml")
                    raw = store.artifact(artifact["id"])["path"].read_bytes()
                    root = ElementTree.fromstring(raw)
                    self.assertTrue(root.tag.endswith("svg"))
                    self.assertIsNone(root.find(".//{http://www.w3.org/2000/svg}image"))
                    self.assertGreater(
                        len(root.findall(".//{http://www.w3.org/2000/svg}path")), 0
                    )
                    self.assertEqual(png.read_bytes(), original)
                    self.assertEqual(
                        exports.export(
                            {"presentation_id": view["id"], "format": "svg"}
                        )["id"],
                        artifact["id"],
                    )
                    self.assertEqual(exports.last_cache.get("canonical_model"), "hit")
                self.assertEqual(len(service.snapshot()["jobs"]), 2)
                source = store.resolve(pcb["id"])
                source.write_bytes(data + b"\n")
                with self.assertRaisesRegex(DemoError, "外部修改"):
                    exports.export({"presentation_id": view["id"], "format": "svg"})
            finally:
                exports.close()
                service.close()
