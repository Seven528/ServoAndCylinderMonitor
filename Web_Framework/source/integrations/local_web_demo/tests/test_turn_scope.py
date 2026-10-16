import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from integrations.local_web_demo.codex_bridge import DEFAULTS
from integrations.local_web_demo.conversation import Conversation
from integrations.local_web_demo.storage import DemoError, FileStore
from integrations.local_web_demo.turn_scope import resolve_scope


class FakeBridge:
    def __init__(self):
        self.started, self.released, self.contexts = [], [], []
        self.on_turn = None

    def validate(self, settings):
        return dict(settings)

    def start_thread(self, settings, instructions, tools):
        self.started.append(instructions)
        return "thread-" + str(len(self.started)), settings

    def release_thread(self, tid):
        if tid:
            self.released.append(tid)

    def run_turn(self, session, text, settings, handle, emit):
        context = handle("pcb_context", {})
        self.contexts.append(context)
        if self.on_turn:
            self.on_turn(handle)
        return {"text": context["scope"]["label"], "status": "completed"}


class TurnScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = FileStore(Path(self.temp.name))
        self.files = [
            self.store.upload(io.BytesIO(b"UNI"), 3, name + ".uni", "pcb")
            for name in ("A", "B", "C")
        ]
        self.holder = self.store.upload(io.BytesIO(b"UNI"), 3, "H.uni", "holder")
        self.ids = [f["id"] for f in self.files]
        self.selection = {"pcb_ids": list(self.ids), "holder_id": self.holder["id"]}
        self.views = [
            {
                "id": "view-" + str(i),
                "job_id": "batch",
                "report_id": "report-" + str(i),
                "image_id": "image-" + str(i),
                "status": "succeeded",
                "statistics": {"count": i},
                "context": {
                    "kind": "height_map",
                    "pcb_file_id": f["id"],
                    "holder_file_id": None,
                    "file_name": f["name"],
                    "side": "side2",
                    "view_mode": "panel",
                    "surface_view": "components",
                    "filter": {"kind": "all"},
                },
            }
            for i, f in enumerate(self.files)
        ]
        self.snapshot = {
            "features": {},
            "active_job": None,
            "jobs": [
                {
                    "id": "batch",
                    "label": "A+B+C",
                    "status": "succeeded",
                    "tasks": [{"foreign": "A.uni"}],
                    "presentations": self.views,
                    "artifacts": [{"id": "manifest", "name": "A+B+C"}]
                    + [
                        {"id": key + "-" + str(i), "name": f["name"]}
                        for i, f in enumerate(self.files)
                        for key in ("image", "report")
                    ],
                }
            ],
        }
        self.analysis = SimpleNamespace(
            snapshot=lambda: copy.deepcopy(self.snapshot),
            start=Mock(),
            wait=Mock(),
            transport=SimpleNamespace(
                tool_definition={"inputSchema": {"type": "object", "properties": {}}}
            ),
        )
        with patch("integrations.local_web_demo.conversation.CodexBridge", FakeBridge):
            self.conversation = Conversation(self.store, self.analysis)
        self.conversation.selection = self.selection

    def scope(self, message="", **extras):
        return resolve_scope(
            {"presentation_id": "view-1", **extras},
            self.store,
            self.snapshot,
            self.selection,
            message,
        )

    def test_three_checked_files_only_second_visible_is_exposed(self):
        scope = self.scope()
        self.assertEqual(scope.file_ids, {self.ids[1]})
        context = scope.context(self.snapshot)
        self.assertEqual([f["name"] for f in context["files"]], ["B.uni"])
        self.assertEqual(context["scope"]["active_presentation"]["image_id"], "image-1")
        serialized = json.dumps(context)
        self.assertNotIn("A.uni", serialized)
        self.assertNotIn("C.uni", serialized)
        self.assertNotIn("manifest", serialized)
        self.assertEqual(len(context["analyses"][0]["presentations"]), 1)
        self.assertEqual(len(context["analyses"][0]["artifacts"]), 2)

    def test_nested_other_file_or_path_is_rejected_before_execution(self):
        scope = self.scope()
        scope.check_arguments({"pcb_file_id": self.ids[1]})
        for arguments in (
            {"tasks": [{"pcb_file_id": self.ids[1]}, {"pcb_file_id": self.ids[0]}]},
            {"analysis": {"pcbs": [{"pcb_file_id": self.ids[0]}]}},
            {"file_ids": self.ids},
            {"pcb_path": "/private/not-authorized.uni"},
            {"scope": {"batch_confirmed": True}, "pcb_file_id": self.ids[2]},
        ):
            with self.assertRaises(DemoError):
                scope.check_arguments(arguments)

    def test_foreign_report_and_model_scope_expansion_never_execute(self):
        self.conversation.turn_scope = self.scope()
        self.store.report = Mock(return_value={"ok": True})
        result = self.conversation.handle(
            "PCBUNIInspector", {"arguments": {"pcb_file_id": self.ids[0]}}
        )
        self.assertFalse(result["ok"])
        self.analysis.start.assert_not_called()
        result = self.conversation.handle("pcb_report", {"report_id": "report-0"})
        self.assertFalse(result["ok"])
        self.store.report.assert_not_called()
        self.assertTrue(
            self.conversation.handle("pcb_report", {"report_id": "report-1"})["ok"]
        )

    def test_same_file_old_image_is_not_current_image_authority(self):
        scope = self.scope()
        older = copy.deepcopy(self.views[1])
        older.update(id="old-B", job_id="old", report_id="old-report-B")
        self.assertFalse(scope.allows_view(older))
        current_turn = copy.deepcopy(older)
        current_turn.update(id="new-B", job_id="current-turn-job")
        scope.generated_job_ids.add("current-turn-job")
        self.assertTrue(scope.allows_view(current_turn))
        current_turn["context"]["pcb_file_id"] = self.ids[0]
        self.assertFalse(scope.allows_view(current_turn))

    def test_scope_frozen_at_send_and_only_proven_companion_allowed(self):
        self.views[1]["context"]["holder_file_id"] = self.holder["id"]
        scope = self.scope()
        self.views[1]["context"]["side"] = "side1"
        self.selection["pcb_ids"] = [self.ids[0]]
        self.assertEqual(scope.active["context"]["side"], "side2")
        scope.check_arguments(
            {
                "holder_file_id": self.holder["id"],
                "analysis": {"pcbs": [{"pcb_file_id": self.ids[1]}]},
            }
        )
        self.assertEqual(scope.files[0]["name"], "B.uni")

    def test_stale_forged_and_ambiguous_empty_canvas_fail_closed(self):
        for value in (
            {},
            {"presentation_id": "stale"},
            {"file_id": self.ids[0]},
            {"presentation_id": "view-1", "context": {"file_id": self.ids[0]}},
            {"presentation_id": "view-1", "batch_file_ids": self.ids},
            {"presentation_id": "view-1", "batch_confirmed": "true"},
        ):
            with self.assertRaises(DemoError):
                resolve_scope(value, self.store, self.snapshot, self.selection)
        one = {"pcb_ids": [self.ids[1]], "holder_id": self.holder["id"]}
        with self.assertRaises(DemoError):
            resolve_scope({"presentation_id": None}, self.store, self.snapshot, one)

    def test_batch_requires_exact_confirmed_selection_not_a_sticky_grant(self):
        all_ids = [*self.ids, self.holder["id"]]
        batch = self.scope(batch_confirmed=True, batch_file_ids=all_ids)
        self.assertEqual(batch.mode, "batch")
        batch.check_arguments({"tasks": [{"pcb_file_id": fid} for fid in self.ids]})
        self.assertEqual(self.scope().file_ids, {self.ids[1]})
        with self.assertRaises(DemoError):
            self.scope(batch_confirmed=True, batch_file_ids=self.ids)

    def test_each_turn_gets_scope_and_thread_rotates_without_erasing_messages(self):
        for number, view in enumerate(("view-1", "view-1", "view-2")):
            self.conversation.chat(
                {
                    "request_id": str(number),
                    "message": "分析当前PCB",
                    "settings": DEFAULTS,
                    "scope": {"presentation_id": view},
                },
                lambda *_: None,
            )
        self.assertEqual(len(self.conversation.bridge.started), 2)
        self.assertEqual(self.conversation.bridge.released, ["thread-1"])
        self.assertEqual(len(self.conversation.messages), 6)
        self.assertEqual(
            self.conversation.messages[0]["scope"]["file_ids"], [self.ids[1]]
        )
        self.assertEqual(
            self.conversation.messages[-1]["scope"]["file_ids"], [self.ids[2]]
        )
        self.assertIsNone(self.conversation.turn_scope)

    def test_named_off_canvas_file_uses_host_ids_and_only_view_defaults(self):
        scope = self.scope(message="分析A.uni")
        self.assertEqual(scope.mode, "explicit")
        self.assertEqual(scope.file_ids, {self.ids[0]})
        self.assertIsNone(scope.active)
        self.assertEqual(scope.view_defaults["side"], "side2")
        self.assertNotIn("file_name", scope.view_defaults)
        scope.check_arguments({"pcb_file_id": self.ids[0]})
        with self.assertRaises(DemoError):
            scope.check_arguments({"pcb_file_id": self.ids[1]})
        self.assertTrue(scope.report_views(self.snapshot, "report-0"))
        self.assertFalse(scope.report_views(self.snapshot, "report-1"))

    def test_natural_count_resolves_imports_even_without_canvas_or_selection(self):
        self.selection = {"pcb_ids": [], "holder_id": None}
        scope = resolve_scope(
            {"presentation_id": None},
            self.store,
            self.snapshot,
            self.selection,
            "请用H.uni分析三份PCB Panel Side1的压棒干涉",
        )
        self.assertEqual(scope.file_ids, {*self.ids, self.holder["id"]})
        self.selection["pcb_ids"] = [self.ids[1]]
        self.assertEqual(scope.file_ids, {*self.ids, self.holder["id"]})
        self.store.upload(io.BytesIO(b"UNI"), 3, "D.uni", "pcb")
        self.assertEqual(len(scope.files), 4)
        with self.assertRaises(DemoError):
            self.scope(message="检查三份PCB")

    def test_natural_authorization_is_not_sticky_in_real_conversation_path(self):
        self.conversation.selection = {"pcb_ids": [], "holder_id": None}
        for index, message in enumerate(
            ("使用H.uni检查三份PCB", "检查当前PCB", "分析A.uni")
        ):
            self.conversation.chat(
                {
                    "request_id": f"natural-{index}",
                    "message": message,
                    "settings": DEFAULTS,
                    "scope": {"presentation_id": "view-1"},
                },
                lambda *_: None,
            )
        contexts = self.conversation.bridge.contexts
        self.assertEqual(
            set(contexts[0]["scope"]["file_ids"]), {*self.ids, self.holder["id"]}
        )
        self.assertEqual(contexts[1]["scope"]["file_ids"], [self.ids[1]])
        self.assertEqual(contexts[2]["scope"]["file_ids"], [self.ids[0]])
        self.assertEqual(len(self.conversation.bridge.started), 3)
        self.assertEqual(len(self.conversation.bridge.released), 2)

    def test_ambiguous_request_never_starts_model_or_partial_analysis(self):
        for message in ("分析两份PCB", "分析missing.uni"):
            with self.subTest(message=message), self.assertRaises(DemoError):
                self.conversation.chat(
                    {
                        "request_id": message,
                        "message": message,
                        "settings": DEFAULTS,
                        "scope": {"presentation_id": "view-1"},
                    },
                    lambda *_: None,
                )
        self.assertFalse(self.conversation.bridge.started)
        self.analysis.start.assert_not_called()
        self.assertFalse(self.conversation.lock.locked())

    def test_removed_explicit_target_does_not_fall_back_to_canvas(self):
        self.store.remove(self.ids[0])
        with self.assertRaises(DemoError):
            self.scope(message="分析A.uni")
