"""Conversation shape recovery is deterministic and never grants file access."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from integrations.local_web_demo.conversation import Conversation
from integrations.local_web_demo.tool_parameters import (
    pressure2d_help,
    validate_analysis_arguments,
)
from integrations.local_web_demo.turn_scope import TurnScope


def native_schema_fixture():
    # The real-native integration test checks the serving schema separately.
    side = {
        "type": "object",
        "required": ["side"],
        "additionalProperties": False,
        "properties": {
            "side": {"enum": ["side1", "side2"]},
            "surface_views": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {
                    "enum": ["full", "components", "copper", "drawings", "mechanical"]
                },
            },
        },
    }
    pcbs = {
        "type": "array",
        "minItems": 1,
        "maxItems": 20,
        "items": {
            "type": "object",
            "required": ["pcb_path"],
            "additionalProperties": False,
            "properties": {
                "pcb_path": {"type": "string"},
                "sides": {"type": "array", "minItems": 1, "maxItems": 2, "items": side},
            },
        },
    }
    pressure = {
        "type": "object",
        "required": ["kind", "pcbs"],
        "additionalProperties": False,
        "properties": {"kind": {"const": "pressure2d"}, "pcbs": pcbs},
    }
    task = copy.deepcopy(pressure)
    task["required"] += ["task_id", "holder_path"]
    task["properties"].update(
        task_id={"type": "string"}, holder_path={"type": "string"}
    )
    return {
        "type": "object",
        "properties": {
            "analysis": {"oneOf": [pressure]},
            "tasks": {"type": "array", "items": {"oneOf": [task]}},
        },
    }


class ToolParameterTests(unittest.TestCase):
    def setUp(self):
        files = tuple(
            {"id": fid, "name": fid + ".uni", "role": role}
            for fid, role in (("P1", "pcb"), ("P2", "pcb"), ("H", "holder"))
        )
        self.scope = TurnScope(
            "batch",
            frozenset(f["id"] for f in files),
            {
                "context": {
                    "side": "side2",
                    "surface_view": "copper",
                    "view_mode": "panel",
                }
            },
            files,
        )
        self.analysis = SimpleNamespace(
            transport=SimpleNamespace(
                tool_definition={"inputSchema": native_schema_fixture()}
            ),
            start=Mock(return_value={"id": "test-job"}),
            wait=Mock(return_value={"id": "test-job", "status": "succeeded"}),
        )
        with patch(
            "integrations.local_web_demo.conversation.CodexBridge", return_value=None
        ):
            self.conversation = Conversation(Mock(), self.analysis)
        self.conversation.turn_scope = self.scope
        self.schema = self.conversation.argument_schema()
        self.example = self.conversation.parameter_help()["pressure2d"][
            "current_scope_example"
        ]

    def call(self, arguments):
        before = copy.deepcopy(arguments)
        result = self.conversation.handle("PCBUNIInspector", {"arguments": arguments})
        self.assertEqual(
            arguments, before, "Preflight must not normalize or mutate requests"
        )
        return result

    def test_scoped_example_preserves_ids_side_surface_and_file_id_schema(self):
        self.assertEqual(self.example["holder_file_id"], "H")
        pcbs = self.example["analysis"]["pcbs"]
        self.assertEqual([p["pcb_file_id"] for p in pcbs], ["P1", "P2"])
        self.assertTrue(
            all(
                p["sides"] == [{"side": "side2", "surface_views": ["copper"]}]
                for p in pcbs
            )
        )
        validate_analysis_arguments(self.example, self.schema)
        self.assertNotIn("pcb_path", str(self.example))
        self.assertIn("pcb_path", str(self.analysis.transport.tool_definition))

    def test_observed_flat_fields_and_string_retry_fail_before_job_with_repair_help(
        self,
    ):
        for pcb, path in (
            (
                {
                    "pcb_file_id": "P1",
                    "side": "side1",
                    "view_mode": "panel",
                    "surface_view": "components",
                },
                "$.analysis.pcbs[0]",
            ),
            ({"pcb_file_id": "P1", "sides": ["side1"]}, "$.analysis.pcbs[0].sides[0]"),
        ):
            with self.subTest(pcb=pcb):
                result = self.call(
                    {
                        "holder_file_id": "H",
                        "analysis": {"kind": "pressure2d", "pcbs": [pcb]},
                    }
                )
                self.assertFalse(result["ok"])
                self.assertIn(path, result["error"])
                self.assertIn("尚未执行", result["error"])
                self.assertEqual(
                    result["parameter_help"]["pressure2d"]["current_scope_example"],
                    self.example,
                )
        self.analysis.start.assert_not_called()
        self.analysis.wait.assert_not_called()
        self.assertFalse(self.scope.generated_job_ids)

    def test_corrected_example_executes_exactly_once_and_native_errors_still_get_help(
        self,
    ):
        self.assertTrue(self.call(self.example)["ok"])
        self.analysis.start.assert_called_once_with(
            self.example, "Holder–PCB 干涉 · Agent"
        )
        self.assertEqual(self.scope.generated_job_ids, {"test-job"})
        self.analysis.wait.return_value = {"id": "test-job-2", "status": "failed"}
        self.assertIn("pressure2d", self.call(self.example)["parameter_help"])

    def test_mixed_tasks_use_same_nested_side_contract(self):
        task = {
            "task_id": "pair",
            "kind": "pressure2d",
            "holder_file_id": "H",
            "pcbs": copy.deepcopy(self.example["analysis"]["pcbs"]),
        }
        validate_analysis_arguments({"tasks": [task]}, self.schema)
        task["pcbs"][1]["sides"] = ["side2"]
        result = self.call({"tasks": [task]})
        self.assertFalse(result["ok"])
        self.assertIn("$.tasks[0].pcbs[1].sides[0]", result["error"])
        self.analysis.start.assert_not_called()

    def test_invalid_side_surface_and_flat_filter_are_not_silently_rewritten(self):
        for value in (
            {"side": "side3"},
            {"side": "side1", "surface_views": "components"},
            {"side": "side1", "surface_views": []},
            {"side": "side1", "surface_views": ["invalid"]},
            {"side": "side1", "surface_views": ["full", "full"]},
            {"side": "side1", "filter": {"kind": "all"}},
        ):
            args = copy.deepcopy(self.example)
            args["analysis"]["pcbs"][0]["sides"] = [value]
            with self.subTest(value=value):
                self.assertFalse(self.call(args)["ok"])
        self.analysis.start.assert_not_called()

    def test_native_optional_defaults_remain_optional(self):
        for pcb in (
            {"pcb_file_id": "P1"},
            {"pcb_file_id": "P1", "sides": [{"side": "side1"}]},
        ):
            args = {
                "holder_file_id": "H",
                "analysis": {"kind": "pressure2d", "pcbs": [pcb]},
            }
            validate_analysis_arguments(args, self.schema)
            self.assertNotIn("surface_views", str(args))

    def test_canvas_example_never_uses_other_checked_files_or_grants_batch(self):
        files = (self.scope.files[0], self.scope.files[2])
        scope = TurnScope("canvas", frozenset(["P1", "H"]), self.scope.active, files)
        self.conversation.turn_scope = scope
        self.conversation.selection = {"pcb_ids": ["P1", "P2"], "holder_id": "H"}
        guidance = self.conversation.parameter_help()["pressure2d"]
        self.assertNotIn("P2", str(guidance))
        self.assertFalse(self.call(self.example)["ok"])
        self.analysis.start.assert_not_called()

    def test_no_example_without_authorized_holder_or_known_canvas_parameters(self):
        for files, active in (
            (self.scope.files[:2], self.scope.active),
            (self.scope.files, None),
            (
                self.scope.files,
                {"context": {"side": "invalid", "surface_view": "full"}},
            ),
        ):
            scope = TurnScope(
                "canvas", frozenset(f["id"] for f in files), active, files
            )
            self.assertNotIn(
                "current_scope_example", pressure2d_help(self.schema, scope)
            )
        self.assertNotIn("current_scope_example", pressure2d_help(self.schema))

    def test_invalid_root_and_missing_schema_return_controlled_errors(self):
        self.assertFalse(self.call([self.example])["ok"])
        self.analysis.transport.tool_definition = None
        result = self.call(self.example)
        self.assertFalse(result["ok"])
        self.assertFalse(result["parameter_help"]["pressure2d"]["available"])
        self.analysis.start.assert_not_called()
