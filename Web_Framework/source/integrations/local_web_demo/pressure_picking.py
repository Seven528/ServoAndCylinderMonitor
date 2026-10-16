"""Read-only, presentation-bound pressure picking from retained native evidence."""

import json
import math
import threading

from .storage import DemoError

MAX_TARGETS = 4096
CONTACT_PAGE = 50


def finite_number(value):
    return type(value) in (int, float) and -1e12 < value < 1e12 and math.isfinite(value)


def component_transform(picking, heads):
    """Only accept the renderer's explicit transform, verified against head pixels."""
    transform = picking.get("scene_to_image")
    keys = ("scale_x", "scale_y", "translate_x", "translate_y")
    if not isinstance(transform, dict) or not all(
        finite_number(transform.get(k)) for k in keys
    ):
        return None
    sx, sy, tx, ty = (transform[k] for k in keys)
    if sx <= 0 or sy >= 0:
        return None
    for target, head in zip(picking["targets"], heads, strict=True):
        center = head.get("center", {})
        if not isinstance(center, dict) or not all(
            finite_number(center.get(k)) for k in ("x_mm", "y_mm")
        ):
            return None
        if (
            abs(center["x_mm"] * sx + tx - target["x_px"]) > 1e-6
            or abs(center["y_mm"] * sy + ty - target["y_px"]) > 1e-6
        ):
            return None
    return transform


def component_highlight(component, transform, width, height):
    """Project one complete physical-body bbox; never match instances by refdes."""
    cid, bounds = component.get("component_id"), component.get("bounds_mm")
    keys = ("min_x_mm", "min_y_mm", "max_x_mm", "max_y_mm")
    if (
        not transform
        or not isinstance(cid, str)
        or not cid
        or not isinstance(bounds, dict)
        or not all(finite_number(bounds.get(k)) for k in keys)
    ):
        return None
    x0, y0, x1, y1 = (bounds[k] for k in keys)
    if x1 <= x0 or y1 <= y0:
        return None
    left = max(0, x0 * transform["scale_x"] + transform["translate_x"])
    right = min(width, x1 * transform["scale_x"] + transform["translate_x"])
    top = max(0, y1 * transform["scale_y"] + transform["translate_y"])
    bottom = min(height, y0 * transform["scale_y"] + transform["translate_y"])
    if (
        not all(finite_number(v) for v in (left, right, top, bottom))
        or right <= left
        or bottom <= top
    ):
        return None
    return {
        "component_id": cid,
        "x_px": left,
        "y_px": top,
        "width_px": right - left,
        "height_px": bottom - top,
    }


class PressurePicking:
    def __init__(self, store, analysis):
        self.store, self.analysis = store, analysis
        self._reading = threading.Lock()

    def _view(self, presentation_id):
        if not isinstance(presentation_id, str) or not 1 <= len(presentation_id) <= 300:
            raise DemoError("压棒点选结果 ID 无效。")
        view = next(
            (
                v
                for j in self.analysis.snapshot()["jobs"]
                for v in j.get("presentations", [])
                if v["id"] == presentation_id
            ),
            None,
        )
        context = (view or {}).get("context", {})
        if (
            not view
            or view.get("status") != "succeeded"
            or (
                context.get("kind"),
                context.get("view_mode"),
                context.get("surface_view"),
            )
            != ("pressure2d", "panel", "components")
        ):
            raise DemoError("压棒点选仅支持已完成的干涉分析 Components 元件图。")
        for key, role in (("pcb_file_id", "pcb"), ("holder_file_id", "holder")):
            self.store.resolve(context.get(key), role)
        return view

    def read(self, presentation_id, head_index=None, offset=0):
        if not self._reading.acquire(blocking=False):
            raise DemoError("压棒数据正在读取，请稍后重新点选。")
        try:
            return self._read(presentation_id, head_index, offset)
        finally:
            self._reading.release()

    def _read(self, presentation_id, head_index=None, offset=0):
        if type(offset) is not int or offset < 0:
            raise DemoError("命中记录分页无效。")
        view = self._view(presentation_id)
        image = self.store.artifact(view.get("image_id"))
        if image.get("mime_type") != "image/png":
            raise DemoError("压棒点选需要当前 PNG 预览。")
        report = self.store.read_report(view.get("report_id"))
        selection = report.get("selection", {})
        if (
            report.get("schema_version") != "pcb-uni.agent.pressure2d.v1"
            or report.get("operation") != "pressure2d"
            or selection.get("side") != view["context"].get("side")
            or selection.get("view_mode") != "panel"
        ):
            raise DemoError("图片与干涉报告的类型或侧面不一致，未启用点选。")
        described = next(
            (
                entry
                for entry in report.get("images", [])
                if isinstance(entry, dict) and entry.get("path") == str(image["path"])
            ),
            None,
        )
        picking = (described or {}).get("picking", {})
        if (
            not isinstance(picking, dict)
            or picking.get("schema_version") != "pcb-uni.pressure-picking.v1"
            or picking.get("status") != "available"
        ):
            raise DemoError("该历史结果没有可用的压棒点选坐标，请重新运行干涉分析。")
        width, height = image.get("width_pixels"), image.get("height_pixels")
        if not all(type(v) is int and 1 <= v <= 100000 for v in (width, height)):
            raise DemoError("点选图片尺寸无效。")
        if (
            described.get("surface_view") != "components"
            or not image.get("sha256")
            or picking.get("image_sha256") != image["sha256"]
            or described.get("sha256") != image["sha256"]
            or (picking.get("width_px"), picking.get("height_px")) != (width, height)
            or (described.get("width_px"), described.get("height_px"))
            != (width, height)
        ):
            raise DemoError("压棒点选坐标不属于当前图片，未读取详情。")
        targets, heads = picking.get("targets"), report.get("pressure_heads")
        if (
            not isinstance(targets, list)
            or not isinstance(heads, list)
            or len(targets) != len(heads)
            or len(targets) > MAX_TARGETS
        ):
            raise DemoError("压棒点选记录数量无效或超过上限。")
        for index, target in enumerate(targets):
            if (
                not isinstance(target, dict)
                or not isinstance(heads[index], dict)
                or type(target.get("head_index")) is not int
                or target.get("head_index") != index
                or target.get("pressure_head_id")
                != heads[index].get("pressure_head_id")
            ):
                raise DemoError("压棒点选身份与报告不一致。")
            values = [target.get(k) for k in ("x_px", "y_px", "rx_px", "ry_px")]
            if not all(
                type(v) in (int, float) and -1e9 < v < 1e9 and math.isfinite(v)
                for v in values
            ) or not (
                0 <= values[0] <= width
                and 0 <= values[1] <= height
                and 0 < values[2] <= width
                and 0 < values[3] <= height
            ):
                raise DemoError("压棒点选坐标无效。")
        result = {
            "ok": True,
            "presentation_id": presentation_id,
            "image_id": view["image_id"],
            "report_id": view["report_id"],
        }
        if head_index is None:
            if offset:
                raise DemoError("点选坐标请求不接受分页。")
            result.update(width_px=width, height_px=height, targets=targets)
            maximum = 2 * 1024 * 1024
        else:
            if type(head_index) is not int or not 0 <= head_index < len(heads):
                raise DemoError("压棒索引不属于当前报告。")
            head = heads[head_index]
            contacts = head.get("contacts", [])
            nearby = head.get("nearest_components", [])
            if (
                not isinstance(contacts, list)
                or not isinstance(nearby, list)
                or not all(isinstance(c, dict) for c in contacts + nearby)
                or offset > len(contacts)
            ):
                raise DemoError("命中记录分页超出范围。")
            transform = component_transform(picking, heads)

            def projected(component, eligible=True):
                # Source report dictionaries stay immutable; highlight is web-only metadata.
                value = {k: v for k, v in component.items() if k != "highlight"}
                if eligible:
                    highlight = component_highlight(component, transform, width, height)
                    if highlight:
                        value["highlight"] = highlight
                return value

            page = [
                projected(c, c.get("role") == "component_body")
                for c in contacts[offset : offset + CONTACT_PAGE]
            ]
            identities = {
                c["component_id"]
                if isinstance(c.get("component_id"), str) and c["component_id"]
                else ("record", i)
                for i, c in enumerate(contacts)
                if c.get("role") == "component_body"
            }
            result.update(
                head_index=head_index,
                head={
                    k: v
                    for k, v in head.items()
                    if k not in {"contacts", "nearest_components"}
                },
                contacts=page,
                contacts_total=len(contacts),
                component_contacts_total=sum(
                    c.get("role") == "component_body" for c in contacts
                ),
                contact_components_total=len(identities),
                other_contacts_total=sum(
                    c.get("role") != "component_body" for c in contacts
                ),
                offset=offset,
                next_offset=offset + len(page)
                if offset + len(page) < len(contacts)
                else None,
                nearest_components=[projected(c) for c in nearby[:5]],
            )
            maximum = 64 * 1024
        current = self._view(presentation_id)
        if (current["image_id"], current["report_id"]) != (
            view["image_id"],
            view["report_id"],
        ):
            raise DemoError("结果已切换，请在当前图片上重新点选。")
        result = self.store.redact(result)
        if len(json.dumps(result, ensure_ascii=False).encode()) > maximum:
            raise DemoError("点选数据超过显示上限，请查询完整原生报告。")
        return result
