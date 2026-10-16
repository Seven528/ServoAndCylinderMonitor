"""Official local brand artwork stays passive, proportional and locally served."""

import re
import unittest
from pathlib import Path
from xml.etree import ElementTree

WEB = Path(__file__).resolve().parents[1] / "web"
SVG = "{http://www.w3.org/2000/svg}"


class BrandAssetsTests(unittest.TestCase):
    def test_official_svg_geometry_and_local_only_content(self):
        allowed = {"svg", "g", "style", "path", "linearGradient", "stop"}
        roots = {}
        for name in ("bosch-logo", "bosch-supergraphic"):
            raw = (WEB / "assets" / f"{name}.svg").read_text(encoding="utf-8")
            self.assertLess(len(raw.encode()), 32 * 1024)
            root = ElementTree.fromstring(raw)
            self.assertEqual(root.tag, SVG + "svg")
            for element in root.iter():
                self.assertIn(element.tag.removeprefix(SVG), allowed)
                for key in element.attrib:
                    local = key.rsplit("}", 1)[-1].lower()
                    self.assertNotIn(local, {"href", "src"})
                    self.assertFalse(local.startswith("on"))
            for target in re.findall(r"url\(([^)]+)\)", raw):
                self.assertTrue(target.startswith("#"))
            roots[name] = root
        self.assertEqual(roots["bosch-logo"].get("viewBox"), "0 0 108 24")
        fills = {e.get("id"): e.get("fill") for e in roots["bosch-logo"]}
        self.assertEqual(fills["bosch-logo-text"], "#ea0016")
        self.assertEqual(fills["bosch-logo-anker"], "#000000")
        self.assertEqual(roots["bosch-supergraphic"].get("width"), "720")
        self.assertEqual(roots["bosch-supergraphic"].get("height"), "300")

    def test_brand_references_are_local_and_source_note_is_present(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        css = (WEB / "workbench-layout.css").read_text(encoding="utf-8")
        self.assertIn('src="assets/bosch-logo.svg"', html)
        self.assertIn('url("assets/bosch-supergraphic.svg")', css)
        self.assertNotRegex(html + css, r'(?:src=|url\()["\']?https?://')
        note = (WEB / "assets" / "BOSCH_ASSETS.md").read_text(encoding="utf-8")
        self.assertIn("Bosch-internal", note)
        self.assertIn("frok-bg.ui.bosch.tech", note)


if __name__ == "__main__":
    unittest.main()
