"""Lightweight web result associations, derived from native units and real reports."""

from pathlib import Path


def _configurations(kind, config):
    analysis = config.get("analysis") or {}
    if kind == "height_map":
        return analysis.get("jobs") or [
            {
                "side": "side1",
                "view_mode": "single",
                "surface_view": "full",
                "filter": {"kind": "all"},
            }
        ]
    if kind == "single_board_pressure":
        return [
            {
                "side": analysis.get("side", "side1"),
                "view_mode": "single",
                "surface_view": analysis.get("surface_view", "full"),
            }
        ]
    if kind == "pressure2d":
        return [
            {
                "side": side.get("side", "side1"),
                "view_mode": "panel",
                "surface_view": surface,
                "pcb_path": pcb.get("pcb_path"),
            }
            for pcb in analysis.get("pcbs", [])
            for side in pcb.get(
                "sides", [{"side": "side1", "surface_views": ["components"]}]
            )
            for surface in side.get("surface_views", ["components"])
        ]
    if kind.startswith("holder_"):
        return [{"side": None, "view_mode": "panel", "surface_view": "full"}]
    return [
        {
            "side": side,
            "view_mode": job["view_mode"],
            "surface_view": job["surface_view"],
        }
        for job in config.get(
            "render_jobs",
            [{"view_mode": "single", "surface_view": "full", "sides": ["side1"]}],
        )
        for side in job["sides"]
    ]


def project_presentations(store, job_id, response, artifacts):
    """No filename inference, no owning model cache, no changes to native reports."""
    payload = response.get("result") or {}
    batch = payload if payload.get("kind") == "batch" else payload.get("batch", {})
    files = {str(store.resolve(item["id"])): item for item in store.listing()}
    rows = []
    for task in batch.get("tasks", []):
        kind = task["kind"]
        for unit in task.get("units", []):
            owned = [
                a
                for a in artifacts
                if a.get("task_id") == task["task_id"]
                and a.get("unit_id") == unit["unit_id"]
            ]
            images = [a for a in owned if a["mime_type"] == "image/png"]
            reports = [a for a in owned if a["mime_type"] == "application/json"]
            config = unit.get("configuration") or {}
            variants = _configurations(kind, config)
            sources = unit.get("sources") or {}
            report_metadata = []
            for report in reports:
                document = store.read_report(report["id"])
                body = (
                    document.get("result", document)
                    if report.get("role") == "source_summary"
                    else document
                )
                described = body.get("images", [])
                if body.get("image"):
                    described = [body["image"]]
                if body.get("rendering"):
                    described = body["rendering"].get("images", [])
                if kind.startswith("holder_") and body.get("holder"):
                    holder = body["holder"]
                    described = [holder["image"]] if holder.get("image") else described
                selection = body.get("selection", {})
                report_metadata.append(
                    {
                        "report_id": report["id"],
                        "selection": selection,
                        "summary": body.get("summary", unit.get("statistics", {})),
                        "images": described,
                        "pcb_path": (
                            body.get("pcb_source") or body.get("source") or {}
                        ).get("path"),
                        "holder_path": (body.get("holder_source") or {}).get("path"),
                    }
                )
                del document, body
            for index, image in enumerate(images or [None]):
                variant = dict(variants[index]) if index < len(variants) else {}
                match = None
                image_meta = {}
                if image:
                    image_path = store.artifact(image["id"])["path"]
                    for metadata in report_metadata:
                        found = next(
                            (
                                entry
                                for entry in metadata["images"]
                                if entry.get("path")
                                and Path(entry["path"]).resolve() == image_path
                            ),
                            None,
                        )
                        if found:
                            match, image_meta = metadata, found
                            break
                if match is None and len(report_metadata) == 1:
                    match = report_metadata[0]
                if match:
                    variant.update(match["selection"])
                for key in ("side", "view_mode", "surface_view"):
                    if key in image_meta:
                        variant[key] = image_meta[key]
                pcb_path = (
                    variant.get("pcb_path")
                    or config.get("pcb_path")
                    or sources.get("pcb_path")
                    or (match or {}).get("pcb_path")
                )
                holder_path = (
                    config.get("holder_path")
                    or sources.get("holder_path")
                    or (match or {}).get("holder_path")
                )
                if kind.startswith("holder_"):
                    holder_path = holder_path or pcb_path
                    pcb_path = None
                pcb, holder = files.get(pcb_path), files.get(holder_path)
                source = pcb or holder
                context = {
                    "kind": kind,
                    "pcb_file_id": pcb["id"] if pcb else None,
                    "holder_file_id": holder["id"] if holder else None,
                    "file_name": source["name"] if source else "来源未确认",
                    "holder_name": holder["name"] if holder else None,
                    **{
                        key: variant.get(key)
                        for key in ("side", "view_mode", "surface_view", "filter")
                    },
                }
                row = {
                    "id": f"{job_id}:{unit['unit_id']}:{index}",
                    "job_id": job_id,
                    "task_id": task["task_id"],
                    "unit_id": unit["unit_id"],
                    "context": context,
                    "image_id": image["id"] if image else None,
                    "report_id": match["report_id"] if match else None,
                    "statistics": store.redact(
                        match["summary"] if match else unit.get("statistics", {})
                    ),
                    "status": unit["status"],
                    "analysis_status": unit.get("analysis_status"),
                    "artifact_status": unit.get("artifact_status"),
                    "diagnostics": unit.get("diagnostics", []),
                }
                picking = image_meta.get("picking", {})
                if (
                    kind == "pressure2d"
                    and context["surface_view"] == "components"
                    and picking.get("schema_version") == "pcb-uni.pressure-picking.v1"
                    and picking.get("status") == "available"
                ):
                    row["picking_available"] = True
                rows.append(row)
    return rows
