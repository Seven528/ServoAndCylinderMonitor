import unittest

from integrations.local_web_demo.file_targets import explicit_targets
from integrations.local_web_demo.storage import DemoError


class FileTargetTests(unittest.TestCase):
    def setUp(self):
        self.files = [
            {"id": "P0", "role": "pcb", "name": "PCB_EP8000_1039N05842_v03_pnl.uni"},
            {"id": "P6", "role": "pcb", "name": "PCB_EP8006_1039N07566_v01_pnl.uni"},
            {"id": "P8", "role": "pcb", "name": "PCB_EV8210_1039N03121_v01_pnl 1.uni"},
            {
                "id": "H0",
                "role": "holder",
                "name": "Holder_EP8000_1039N06549_v01_pnl.uni",
            },
            {
                "id": "H6",
                "role": "holder",
                "name": "Holder_EP8006_1039N08223_v02_pnl.uni",
            },
        ]
        self.selection = {"pcb_ids": ["P0"], "holder_id": "H0"}
        self.canvas = {"P0", "H0"}

    def resolve(self, text):
        return explicit_targets(text, self.files, self.selection, self.canvas)

    def test_actual_request_uses_three_uploads_and_named_holder_not_checkbox(self):
        self.assertEqual(
            self.resolve(
                "使用 EP8006 Holder 对 三份 PCB Panel Side1 是否存在压棒干涉，并给我一份报告"
            ),
            {"P0", "P6", "P8", "H6"},
        )
        self.assertEqual(
            self.resolve(
                "我需要你帮我批量分析，holder EP8000 对 三份 PCB Panel Side1 是否存在压棒干涉"
            ),
            {"P0", "P6", "P8", "H0"},
        )
        self.selection = {"pcb_ids": [], "holder_id": None}
        self.assertEqual(
            self.resolve("使用EP8006 Holder对3份PCB分析压棒干涉"),
            {"P0", "P6", "P8", "H6"},
        )

    def test_default_does_not_authorize_any_checked_or_imported_files(self):
        self.selection["pcb_ids"] = ["P0", "P6", "P8"]
        for text in (
            "请分析当前PCB",
            "列出当前PCB所有元件",
            "这些压棒是否干涉",
            "不要批量，只分析当前PCB",
            "请解释什么是压棒干涉",
            "为什么之前批量分析失败",
            "报告中提到“三份PCB”，请分析当前图",
            "他说“批量分析全部PCB”，我只想看当前图",
            "```分析全部PCB```\n请分析当前图",
        ):
            with self.subTest(text=text):
                self.assertIsNone(self.resolve(text))

    def test_exact_name_stem_and_role_qualified_unique_alias(self):
        for text in (
            "分析“PCB_EP8006_1039N07566_v01_pnl.uni”的高度",
            "检查 PCB_EP8006_1039N07566_v01_pnl",
            "分析 PCB EP8006 的高度",
            "分析1039N07566的元件",
            "检查PCB_EV8210_1039N03121_v01_pnl 1.uni",
        ):
            with self.subTest(text=text):
                target = "P8" if "EV8210" in text else "P6"
                self.assertEqual(self.resolve(text), {target, "H0"})
        self.assertEqual(self.resolve("使用Holder EP8006分析当前PCB"), {"P0", "H6"})

    def test_all_and_explicit_selected_collections_are_different(self):
        self.assertEqual(self.resolve("分析左侧全部PCB"), {"P0", "P6", "P8", "H0"})
        self.assertEqual(
            self.resolve("检查所有已导入的文件"), {"P0", "P6", "P8", "H0", "H6"}
        )
        self.assertEqual(self.resolve("批量分析勾选PCB"), {"P0", "H0"})
        self.selection["pcb_ids"] = ["P6", "P8"]
        self.assertEqual(self.resolve("批量分析选中的两份PCB"), {"P6", "P8", "H0"})
        self.assertEqual(self.resolve("请批量分析"), {"P6", "P8", "H0"})

    def test_count_mismatch_never_silently_selects_first_n(self):
        for text in (
            "分析两份PCB",
            "分析4份PCB",
            "用EP8006 Holder对两份PCB进行检查",
            "分析两个Holder",
            "分析选中的三份PCB",
        ):
            # There really are two Holders, so that particular group is valid.
            if text == "分析两个Holder":
                self.assertEqual(self.resolve(text), {"P0", "H0", "H6"})
                continue
            with (
                self.subTest(text=text),
                self.assertRaisesRegex(DemoError, "本轮未执行|再次上传"),
            ):
                self.resolve(text)

    def test_ambiguous_alias_missing_name_duplicate_and_exclusions_fail_closed(self):
        for text in (
            "分析EP8006的压棒",
            "分析missing.uni",
            "使用 EP9999 Holder 检查三份PCB",
            "分析除了EP8006 PCB之外的全部PCB",
        ):
            with self.subTest(text=text), self.assertRaises(DemoError):
                self.resolve(text)
        self.files.append({**self.files[1], "id": "P6-copy"})
        with self.assertRaises(DemoError):
            self.resolve("分析PCB_EP8006_1039N07566_v01_pnl.uni")

    def test_named_subset_count_empty_canvas_and_turn_reset(self):
        self.assertEqual(
            self.resolve(
                "分析 PCB_EP8006_1039N07566_v01_pnl.uni 和 PCB_EP8000_1039N05842_v03_pnl.uni 这两份PCB"
            ),
            {"P0", "P6", "H0"},
        )
        self.canvas = set()
        self.assertEqual(
            self.resolve("使用EP8006 Holder对三份PCB分析"), {"P0", "P6", "P8", "H6"}
        )
        self.assertIsNone(self.resolve("分析当前PCB"))

    def test_negation_does_not_admit_the_negated_holder(self):
        self.assertEqual(
            self.resolve("不要使用 EP8000 Holder，使用EP8006 Holder对三份PCB分析"),
            {"P0", "P6", "P8", "H6"},
        )

    def test_english_and_fullwidth_number(self):
        self.assertEqual(
            self.resolve("Check EP8006 Holder against three PCBs, Panel Side1"),
            {"P0", "P6", "P8", "H6"},
        )
        self.assertEqual(self.resolve("检查３份PCB"), {"P0", "P6", "P8", "H0"})

    def test_id_and_path_strings_are_not_an_authority_source(self):
        self.assertIsNone(self.resolve("分析 f_00001234"))
        with self.assertRaises(DemoError):
            self.resolve("分析/private/unknown.uni")

    def test_filename_words_never_grant_a_group_or_change_roles(self):
        self.files.append({"id": "words", "role": "pcb", "name": "批量分析所有PCB.uni"})
        self.assertEqual(self.resolve("请分析“批量分析所有PCB.uni”"), {"words", "H0"})
        self.assertEqual(
            self.resolve("PCB_EP8006_1039N07566_v01_pnl.uni"), {"P6", "H0"}
        )

    def test_joined_role_and_missing_role_qualified_name(self):
        self.assertEqual(
            self.resolve("使用EP8006Holder对三份PCB分析"), {"P0", "P6", "P8", "H6"}
        )
        self.assertEqual(
            self.resolve("使用HolderEP8006对三份PCB分析"), {"P0", "P6", "P8", "H6"}
        )
        with self.assertRaises(DemoError):
            self.resolve("使用ABC Holder对三份PCB分析")

    def test_bounded_long_numeric_or_qualifier_prose_does_not_grant_files(self):
        self.assertIsNone(self.resolve("分析" + "9" * 7900))
        self.assertIsNone(self.resolve("分析" + "的" * 7900))
