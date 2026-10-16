import hashlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

from integrations.local_web_demo.analysis import AnalysisService
from integrations.local_web_demo.conversation import Conversation
from integrations.local_web_demo.presentation import project_presentations
from integrations.local_web_demo.storage import FileStore
from integrations.local_web_demo.turn_scope import resolve_scope

REPO = Path(__file__).resolve().parents[3]
EXE = REPO / "build/cpp/release/cpp/PCBUNIInspectorAgent"


class PresentationTests(unittest.TestCase):
    def test_association_uses_report_paths_not_image_names(self):
        with tempfile.TemporaryDirectory() as temp:
            store = FileStore(Path(temp))
            pcb = store.upload(io.BytesIO(b"x"), 1, "test.uni", "pcb")
            image = store.outputs / "misleading-side2-panel.png"
            image.write_bytes(b"png")
            report = store.outputs / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "source": {"path": str(store.resolve(pcb["id"]))},
                        "selection": {
                            "side": "side1",
                            "view_mode": "single",
                            "surface_view": "full",
                            "filter": {"kind": "above_2_0_mm"},
                        },
                        "summary": {"matching_count": 10},
                        "image": {"path": str(image)},
                    }
                )
            )
            artifacts = [
                store.register_artifact(
                    {"path": str(path), "mime_type": mime, "role": role},
                    "t",
                    "t/0",
                    "j",
                )
                for path, mime, role in [
                    (image, "image/png", "height_map"),
                    (report, "application/json", "height_map_report"),
                ]
            ]
            response = {
                "result": {
                    "kind": "batch",
                    "tasks": [
                        {
                            "task_id": "t",
                            "kind": "height_map",
                            "units": [
                                {
                                    "unit_id": "t/0",
                                    "status": "succeeded",
                                    "analysis_status": "succeeded",
                                    "configuration": {},
                                    "statistics": {},
                                }
                            ],
                        }
                    ],
                }
            }
            views = project_presentations(store, "j", response, artifacts)
            self.assertEqual(views[0]["context"]["side"], "side1")
            self.assertEqual(views[0]["context"]["view_mode"], "single")
            self.assertEqual(views[0]["statistics"]["matching_count"], 10)
            self.assertEqual(views[0]["context"]["pcb_file_id"], pcb["id"])
            self.assertEqual(views[0]["image_id"], artifacts[0]["id"])
            self.assertEqual(views[0]["report_id"], artifacts[1]["id"])

    @unittest.skipUnless(EXE.is_file(), "Build local Release first")
    def test_real_batch_associations_and_report_message_refs(self):
        with tempfile.TemporaryDirectory() as temp:
            store = FileStore(Path(temp))
            service = AnalysisService(store, EXE)
            try:
                ids = []
                source = REPO / "cpp/tests/fixtures/agent_single_board_pressure.uni"
                for name in ["A.uni", "B.uni"]:
                    with source.open("rb") as stream:
                        ids.append(
                            store.upload(stream, source.stat().st_size, name, "pcb")[
                                "id"
                            ]
                        )
                jobs = [
                    {
                        "side": side,
                        "view_mode": mode,
                        "surface_view": surface,
                        "filter": {"kind": "all"},
                    }
                    for side, mode, surface in [
                        ("side1", "single", "full"),
                        ("side2", "single", "components"),
                        ("side1", "panel", "full"),
                    ]
                ]
                tasks = [
                    {
                        "task_id": "board" + str(i),
                        "kind": "height_map",
                        "pcb_file_id": fid,
                        "jobs": jobs,
                    }
                    for i, fid in enumerate(ids)
                ]
                j = service.start({"tasks": tasks})
                value = service.wait(j["id"])
                self.assertEqual(value["status"], "succeeded", value)
                views = value["presentations"]
                self.assertEqual(len(views), 6)
                self.assertEqual(
                    [v["context"]["pcb_file_id"] for v in views],
                    [ids[0]] * 3 + [ids[1]] * 3,
                )
                self.assertEqual(
                    [v["context"]["side"] for v in views],
                    ["side1", "side2", "side1"] * 2,
                )
                self.assertEqual(
                    [v["context"]["view_mode"] for v in views],
                    ["single", "single", "panel"] * 2,
                )
                for v in views:
                    report = store.read_report(v["report_id"])
                    self.assertEqual(v["statistics"], report["summary"])
                    self.assertEqual(
                        v["context"]["filter"], report["selection"]["filter"]
                    )
                    image = store.artifact(v["image_id"])
                    encoded = image["path"].read_bytes()
                    self.assertEqual(len(encoded), image["byte_count"])
                    self.assertEqual(
                        hashlib.sha256(encoded).hexdigest(), image["sha256"]
                    )
                conversation = Conversation.__new__(Conversation)
                conversation.store = store
                conversation.analysis = service
                conversation.state_lock = threading.RLock()
                conversation.session = {
                    "assistant_id": "new",
                    "cancel": threading.Event(),
                }
                conversation.tool_history = []
                conversation.turn_scope = resolve_scope(
                    {"presentation_id": views[-1]["id"]},
                    store,
                    service.snapshot(),
                    {"pcb_ids": ids, "holder_id": None},
                )
                conversation.messages = [
                    {"id": "old", "text": "原来的消息"},
                    {"id": "new", "text": "当前消息"},
                ]
                count = len(service.jobs)
                result = conversation.handle(
                    "pcb_report", {"report_id": views[-1]["report_id"], "limit": 1}
                )
                self.assertTrue(result["ok"])
                self.assertEqual(len(service.jobs), count)
                self.assertNotIn("analysis_refs", conversation.messages[0])
                refs = conversation.messages[1]["analysis_refs"]
                self.assertEqual(refs[0]["presentation_id"], views[-1]["id"])
                self.assertEqual(refs[0]["context"]["pcb_file_id"], ids[1])
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
