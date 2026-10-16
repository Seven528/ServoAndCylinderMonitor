import copy
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from integrations.local_web_demo.pressure_picking import (
    PressurePicking,
    component_highlight,
)
from integrations.local_web_demo.server import Handler
from integrations.local_web_demo.storage import DemoError, FileStore


class PressurePickingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = FileStore(Path(self.temp.name))
        files = [
            self.store.upload(io.BytesIO(b"UNI"), 3, role + ".uni", role)
            for role in ("pcb", "holder")
        ]
        self.pcb, holder = [f["id"] for f in files]
        self.image_path = self.store.outputs / "image.png"
        self.image_path.write_bytes(b"test-image")
        image = self.store.register_artifact(
            {
                "path": str(self.image_path),
                "mime_type": "image/png",
                "width_pixels": 100,
                "height_pixels": 60,
                "sha256": "a" * 64,
            }
        )
        self.report_path = self.store.outputs / "report.json"
        self.report_path.write_text("{}")
        report = self.store.register_artifact(
            {"path": str(self.report_path), "mime_type": "application/json"}
        )
        self.view = {
            "id": "view",
            "image_id": image["id"],
            "report_id": report["id"],
            "status": "succeeded",
            "context": {
                "kind": "pressure2d",
                "view_mode": "panel",
                "surface_view": "components",
                "side": "side2",
                "pcb_file_id": self.pcb,
                "holder_file_id": holder,
            },
        }
        self.analysis = SimpleNamespace(
            snapshot=lambda: {"jobs": [{"presentations": [self.view]}]},
            transport=Mock(),
        )
        self.service = PressurePicking(self.store, self.analysis)
        heads = [
            {
                "pressure_head_id": "same-semantic-id",
                "refdes": "NDH1",
                "placement_index": n,
                "contacts": [
                    {
                        "role": "component_body",
                        "owner_name": "C" + str(i),
                        "component_id": f"part/{n}/{i}",
                        "source": {"start_line": 10 + i, "end_line": 10 + i},
                    }
                    for i in range(55 if n == 0 else 1)
                ],
                "nearest_components": [{"refdes": "nearby", "distance_mm": 2.0}],
            }
            for n in range(2)
        ]
        picking = {
            "schema_version": "pcb-uni.pressure-picking.v1",
            "status": "available",
            "image_sha256": "a" * 64,
            "width_px": 100,
            "height_px": 60,
            "targets": [
                {
                    "head_index": i,
                    "pressure_head_id": "same-semantic-id",
                    "refdes": "NDH1",
                    "x_px": 20 + i * 50,
                    "y_px": 20,
                    "rx_px": 3,
                    "ry_px": 3,
                }
                for i in range(2)
            ],
        }
        self.document = {
            "schema_version": "pcb-uni.agent.pressure2d.v1",
            "operation": "pressure2d",
            "selection": {"side": "side2", "view_mode": "panel"},
            "images": [
                {
                    "path": str(self.image_path),
                    "surface_view": "components",
                    "sha256": "a" * 64,
                    "width_px": 100,
                    "height_px": 60,
                    "picking": picking,
                }
            ],
            "pressure_heads": heads,
        }
        self.save()

    def save(self):
        self.report_path.write_text(json.dumps(self.document))

    def test_map_and_paginated_exact_head_preserve_same_refdes_instances(self):
        result = self.service.read("view")
        self.assertEqual(len(result["targets"]), 2)
        first = self.service.read("view", 0)
        self.assertEqual(first["component_contacts_total"], 55)
        self.assertEqual(first["other_contacts_total"], 0)
        self.assertEqual(
            (len(first["contacts"]), first["contacts_total"], first["next_offset"]),
            (50, 55, 50),
        )
        self.assertEqual(self.service.read("view", 0, 50)["next_offset"], None)
        self.assertEqual(self.service.read("view", 1)["head"]["placement_index"], 1)
        self.assertEqual(len(self.service.read("view", 1)["contacts"]), 1)
        self.assertEqual(first["nearest_components"][0]["refdes"], "nearby")
        self.analysis.transport.call.assert_not_called()
        self.assertNotIn(str(self.store.root), json.dumps(result))

    def test_all_other_modes_surfaces_and_unready_results_are_rejected(self):
        original = copy.deepcopy(self.view)
        for key, values in (
            ("kind", ["pcb_preview", "height_map", "single_board_pressure"]),
            ("surface_view", ["full", "copper", "drawings", "mechanical"]),
            ("view_mode", ["single"]),
        ):
            for value in values:
                self.view["context"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(DemoError):
                    self.service.read("view")
                self.view = copy.deepcopy(original)
        self.view["status"] = "failed"
        with self.assertRaises(DemoError):
            self.service.read("view")

    def test_foreign_stale_or_deleted_presentations_fail_closed(self):
        with self.assertRaises(DemoError):
            self.service.read("foreign")
        self.store.remove(self.pcb)
        with self.assertRaises(DemoError):
            self.service.read("view")

    def test_deletion_during_report_read_does_not_return_stale_data(self):
        def read(_):
            self.store.remove(self.pcb)
            return self.document

        with (
            patch.object(self.store, "read_report", side_effect=read),
            self.assertRaises(DemoError),
        ):
            self.service.read("view")

    def test_only_one_report_read_is_admitted_without_a_waiting_queue(self):
        self.service._reading.acquire()
        try:
            with self.assertRaises(DemoError):
                self.service.read("view")
        finally:
            self.service._reading.release()
        with self.assertRaises(DemoError):
            self.service.read("missing")
        self.assertEqual(len(self.service.read("view")["targets"]), 2)

    def test_missing_coordinates_side_hash_dimensions_and_target_binding_are_rejected(
        self,
    ):
        original = copy.deepcopy(self.document)
        mutations = [
            lambda d: d["images"][0].pop("picking"),
            lambda d: d["selection"].update(side="side1"),
            lambda d: d["images"][0].update(path="/foreign/image.png"),
            lambda d: d["images"][0]["picking"].update(image_sha256="b" * 64),
            lambda d: d["images"][0]["picking"].update(width_px=99),
            lambda d: d["images"][0]["picking"]["targets"][0].update(head_index=1),
            lambda d: d["images"][0]["picking"]["targets"][0].update(
                pressure_head_id="wrong"
            ),
            lambda d: d["images"][0]["picking"]["targets"][0].update(x_px=-1),
            lambda d: d["images"][0]["picking"]["targets"][0].update(rx_px=0),
            lambda d: d["images"][0]["picking"]["targets"][0].update(x_px=10**500),
        ]
        for mutation in mutations:
            self.document = copy.deepcopy(original)
            mutation(self.document)
            self.save()
            with self.assertRaises(DemoError):
                self.service.read("view")

    def test_offsets_indices_limits_and_payloads_are_bounded(self):
        for index, offset in ((-1, 0), (2, 0), (True, 0), (0, -1), (0, 56), (None, 1)):
            with self.subTest(index=index, offset=offset), self.assertRaises(DemoError):
                self.service.read("view", index, offset)
        self.document["pressure_heads"][0]["reason"] = "x" * 70000
        self.save()
        with self.assertRaises(DemoError):
            self.service.read("view", 0)
        self.document["pressure_heads"] = [{"pressure_head_id": "same"}] * 4097
        self.document["images"][0]["picking"]["targets"] = [
            self.document["images"][0]["picking"]["targets"][0]
        ] * 4097
        self.save()
        with self.assertRaises(DemoError):
            self.service.read("view")

    def test_http_is_authenticated_read_only_and_validates_query(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.token = "pressure-test-token"
        server.picking = self.service
        server.http_error = Mock()
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}/api/pressure-picking?"

        def get(query, authenticated=True):
            try:
                response = urllib.request.urlopen(
                    urllib.request.Request(
                        base + query,
                        headers={"X-Demo-Token": server.token} if authenticated else {},
                    ),
                    timeout=5,
                )
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.status, json.load(response)

        try:
            self.assertEqual(get("presentation_id=view", False)[0], 403)
            self.assertEqual(get("presentation_id=view")[0], 200)
            self.assertEqual(
                get("presentation_id=view&head_index=1")[1]["head"]["placement_index"],
                1,
            )
            for query in (
                "presentation_id=view&head_index=bad",
                "presentation_id=view&file_id=foreign",
                "presentation_id=view&presentation_id=other",
            ):
                self.assertEqual(get(query)[0], 400)
            self.analysis.transport.call.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def add_highlights(self):
        picking = self.document["images"][0]["picking"]
        picking["scene_to_image"] = {
            "scale_x": 2,
            "scale_y": -2,
            "translate_x": 0,
            "translate_y": 60,
        }
        for i, head in enumerate(self.document["pressure_heads"]):
            head["center"] = {"x_mm": 10 + i * 25, "y_mm": 20}
            for contact in head["contacts"]:
                contact["bounds_mm"] = {
                    "min_x_mm": 10 + i * 25,
                    "max_x_mm": 14 + i * 25,
                    "min_y_mm": 10,
                    "max_y_mm": 12,
                }
            head["nearest_components"] = [{**head["contacts"][0], "refdes": "C0"}]
        self.save()

    def test_contact_and_nearest_highlights_use_same_bound_image_transform(self):
        self.add_highlights()
        value = self.service.read("view", 0)
        expected = {
            "component_id": "part/0/0",
            "x_px": 20,
            "y_px": 36,
            "width_px": 8,
            "height_px": 4,
        }
        self.assertEqual(value["contacts"][0]["highlight"], expected)
        self.assertEqual(value["nearest_components"][0]["highlight"], expected)
        second = self.service.read("view", 1)["contacts"][0]["highlight"]
        self.assertEqual(second["x_px"], 70)
        self.assertNotEqual(second["component_id"], expected["component_id"])
        self.assertNotIn("highlight", self.document["pressure_heads"][0]["contacts"][0])
        self.analysis.transport.call.assert_not_called()

    def test_old_or_inconsistent_transform_disables_highlight_without_guessing(self):
        self.assertNotIn("highlight", self.service.read("view", 0)["contacts"][0])
        self.add_highlights()
        self.document["images"][0]["picking"]["scene_to_image"]["translate_x"] = 1
        self.save()
        self.assertNotIn("highlight", self.service.read("view", 0)["contacts"][0])
        self.assertNotIn(
            "highlight", self.service.read("view", 0)["nearest_components"][0]
        )

    def test_invalid_component_bounds_and_identity_never_generate_overlays(self):
        transform = {"scale_x": 2, "scale_y": -2, "translate_x": 0, "translate_y": 60}
        base = {
            "component_id": "component",
            "bounds_mm": {
                "min_x_mm": 10,
                "max_x_mm": 14,
                "min_y_mm": 10,
                "max_y_mm": 12,
            },
        }
        for change in (
            {"component_id": None},
            {"bounds_mm": None},
            {"bounds_mm": {**base["bounds_mm"], "min_x_mm": 20}},
            {"bounds_mm": {**base["bounds_mm"], "max_x_mm": 10**500}},
            {"bounds_mm": {**base["bounds_mm"], "min_y_mm": -90, "max_y_mm": -80}},
        ):
            self.assertIsNone(
                component_highlight({**base, **change}, transform, 100, 60)
            )
        clipped = component_highlight(
            {**base, "bounds_mm": {**base["bounds_mm"], "min_x_mm": -5}},
            transform,
            100,
            60,
        )
        self.assertEqual(clipped["x_px"], 0)

    def test_component_count_deduplicates_native_identity_not_equal_names(self):
        first = self.document["pressure_heads"][0]["contacts"][0]
        self.document["pressure_heads"][0]["contacts"] = [
            first,
            copy.deepcopy(first),
            {**first, "component_id": "another-placement"},
        ]
        self.save()
        value = self.service.read("view", 0)
        self.assertEqual(value["component_contacts_total"], 3)
        self.assertEqual(value["contact_components_total"], 2)
