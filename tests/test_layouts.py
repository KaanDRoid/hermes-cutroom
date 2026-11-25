"""Split explainer layout settings: palette, geometry and validation."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cutroom import layouts


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=60)


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
class PanelFileTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def test_a_picture_is_probed_and_recorded(self):
        picture = self.folder / "diagram.png"
        _ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=320x180", "-frames:v", "1", str(picture))
        item = layouts.normalize_item({"kind": "file", "path": str(picture)})
        self.assertEqual(item["kind"], "file")
        self.assertEqual(item["media"], "image")
        self.assertEqual((item["width"], item["height"]), (320, 180))
        self.assertEqual(item["name"], "diagram.png")
        self.assertEqual(len(item["sha256"]), 64)

    def test_a_screen_recording_is_probed_with_its_duration(self):
        video = self.folder / "screen.mp4"
        _ffmpeg("-f", "lavfi", "-i", "testsrc=s=640x360:d=2:r=10", "-pix_fmt", "yuv420p", str(video))
        item = layouts.normalize_item({"kind": "file", "path": str(video)})
        self.assertEqual(item["media"], "video")
        self.assertAlmostEqual(item["duration"], 2.0, delta=0.2)

    def test_relative_missing_and_non_media_files_are_refused(self):
        text = self.folder / "notes.txt"
        text.write_text("not a picture", encoding="utf-8")
        for spec in ({"kind": "file", "path": "diagram.png"}, {"kind": "file", "path": str(self.folder / "gone.png")}, {"kind": "file", "path": str(text)}):
            with self.assertRaises((ValueError, FileNotFoundError)):
                layouts.normalize_item(spec)


class LayoutTests(unittest.TestCase):
    def test_palette_holds_video_colours_only_as_hex(self):
        for name, value in layouts.PALETTE.items():
            self.assertRegex(value, r"^#[0-9A-F]{6}([0-9A-F]{2})?$", name)
        for background in layouts.BACKGROUNDS:
            self.assertIn(f"{background}_paper", layouts.PALETTE)
            self.assertIn(f"{background}_ink", layouts.PALETTE)

    def test_defaults_fill_a_full_frame_layout(self):
        value = layouts.normalize_layout({"layout": "full"}, duration=60)
        self.assertEqual(value["layout"], "full")
        self.assertEqual(value["divider"], 1170)
        self.assertEqual(value["pictures"], [])
        self.assertIsNone(value["panel"])
        self.assertIsNone(layouts.normalize_layout(None, duration=60))

    def test_unknown_or_out_of_range_values_are_refused(self):
        bad = [
            {"layout": "grid"},
            {"layout": "split", "background": "neon"},
            {"layout": "split", "speaker": "huge"},
            {"layout": "split", "divider": 900},
            {"layout": "split", "divider": True},
            {"layout": "split", "hold": "forever"},
            {"layout": "split", "colour": "red"},
            {"layout": "split", "headline": {"l1": "A" * 61, "l2": ""}},
            {"layout": "split", "headline": {"l1": "A\x07", "l2": ""}},
            {"layout": "split", "headline": {"l1": "ONE", "l2": "TWO", "boxed": [3]}},
            {"layout": "split", "panel": {"kind": "card", "type": "video_game", "text": "x"}},
            {"layout": "split", "panel": {"kind": "card", "type": "title", "text": ""}},
            {"layout": "split", "panel": {"kind": "url", "path": "https://example.com/a.png"}},
            {"layout": "split", "pictures": [{"start": 5, "end": 4, "item": {"kind": "card", "type": "title", "text": "x"}}]},
            {"layout": "split", "pictures": [{"start": 50, "end": 70, "item": {"kind": "card", "type": "title", "text": "x"}}]},
            {"layout": "split", "pictures": [
                {"start": 1, "end": 4, "item": {"kind": "card", "type": "title", "text": "a"}},
                {"start": 3, "end": 6, "item": {"kind": "card", "type": "title", "text": "b"}},
            ]},
            "split",
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                layouts.normalize_layout(value, duration=60)

    def test_cards_headline_and_timed_pictures_are_kept_in_order(self):
        value = layouts.normalize_layout(
            {
                "layout": "split",
                "background": "kraft",
                "speaker": "small",
                "divider": 1300,
                "hold": "opening",
                "headline": {"l1": "climate change is", "l2": "not complicated", "boxed": [1]},
                "panel": {"kind": "card", "type": "number", "text": "15 min", "detail": "to explain it"},
                "pictures": [
                    {"start": 20, "end": 24, "said": "later words", "item": {"kind": "card", "type": "quote", "text": "Later"}},
                    {"start": 3, "end": 6, "said": "early words", "item": {"kind": "card", "type": "bars", "text": "A: 1, B: 3"}},
                ],
            },
            duration=60,
        )
        self.assertEqual([item["start"] for item in value["pictures"]], [3, 20])
        self.assertEqual(value["panel"]["type"], "number")
        self.assertEqual(value["headline"]["boxed"], [1])

    def test_split_geometry_matches_the_studio_preview(self):
        geo = layouts.geometry({"layout": "split", "speaker": "wide", "divider": 1170})
        self.assertEqual(geo["panel"], {"x": 56, "y": 520, "w": 968, "h": 460})
        self.assertEqual(geo["speaker"], {"x": 24, "y": 1170, "w": 1032, "h": 726})
        self.assertEqual(geo["radius"], 40)
        self.assertEqual(geo["caption_y"], 1150)
        small = layouts.geometry({"layout": "split", "speaker": "small", "divider": 1170})
        self.assertEqual(small["speaker"], {"x": 270, "y": 1190, "w": 540, "h": 440})
        full = layouts.geometry({"layout": "split", "speaker": "full", "divider": 1420})
        self.assertEqual(full["speaker"], {"x": 0, "y": 1420, "w": 1080, "h": 500})
        self.assertEqual(full["radius"], 0)
        over = layouts.geometry({"layout": "over"})
        self.assertEqual(over["panel"], {"x": 80, "y": 300, "w": 920, "h": 440})

    def test_turkish_capitals_follow_the_language(self):
        self.assertEqual(layouts.upper("istanbul ışık", "tr"), "İSTANBUL IŞIK")
        self.assertEqual(layouts.upper("istanbul", "en"), "ISTANBUL")


class StudioLayoutTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch

        from cutroom.studio import Studio

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        source = root / "source.mp4"
        source.write_bytes(b"unit source fixture")
        probe = patch("cutroom.studio.probe", return_value={"duration": 30.0, "width": 1920, "height": 1080, "has_audio": True})
        probe.start()
        self.addCleanup(probe.stop)
        self.studio = Studio(root / "workspace")
        self.project = self.studio.create(source, name="Talk")

    def save(self, layout):
        project = self.studio.get(self.project["id"])
        return self.studio.update(project["id"], {"settings": {"platform": "youtube_shorts", "layout": layout}}, project["revision"])

    def test_a_layout_is_saved_normalized_and_can_be_reset(self):
        saved = self.save({"layout": "split", "panel": {"kind": "card", "type": "title", "text": "Hello"}})
        self.assertEqual(saved["settings"]["layout"]["layout"], "split")
        self.assertEqual(saved["settings"]["layout"]["divider"], layouts.DEFAULT_DIVIDER)
        self.assertEqual(self.save(None)["settings"].get("layout"), None)

    def test_pictures_after_the_source_and_landscape_layouts_are_refused(self):
        with self.assertRaises(ValueError):
            self.save({"layout": "split", "pictures": [{"start": 29, "end": 31, "item": {"kind": "card", "type": "title", "text": "x"}}]})
        project = self.studio.get(self.project["id"])
        with self.assertRaisesRegex(ValueError, "9:16"):
            self.studio.update(project["id"], {"settings": {"platform": "youtube", "layout": {"layout": "split"}}}, project["revision"])
        # Full frame is fine on any shape.
        self.studio.update(project["id"], {"settings": {"platform": "youtube", "layout": {"layout": "full"}}}, project["revision"])

    def test_switching_to_a_wide_platform_keeps_the_layout_for_later(self):
        saved = self.save({"layout": "split", "headline": {"l1": "ONE", "l2": "TWO"}})
        moved = self.studio.update(saved["id"], {"settings": {"platform": "youtube"}}, saved["revision"])
        self.assertEqual(moved["settings"]["layout"]["layout"], "full")
        self.assertEqual(moved["settings"]["layout"]["headline"]["l1"], "ONE")

    def test_preview_and_final_renders_receive_the_layout_and_the_face_centre(self):
        saved = self.save({"layout": "split", "headline": {"l1": "ONE", "l2": "TWO"}})
        saved = self.studio.update(saved["id"], {"settings": {"title": "Old title"}}, saved["revision"])
        project = self.studio.get(saved["id"])
        project["analysis"] = {"face_samples": [[1.0, [[0.6, 0.3, 0.1, 0.2]]], [2.0, [[0.62, 0.32, 0.1, 0.2]]]]}
        for preset in ("preview", "final"):
            render = self.studio._render_settings(project, preset)
            self.assertEqual(render["layout"]["layout"], "split")
            self.assertEqual(render["layout_face"], [0.62, 0.32])
            self.assertEqual(render["title"], "", "The headline replaces the burned title")
        project["settings"]["layout"]["layout"] = "full"
        render = self.studio._render_settings(project, "preview")
        self.assertNotIn("layout", render)
        self.assertEqual(render["title"], "Old title")

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
    def test_a_still_is_served_only_for_files_saved_in_the_layout(self):
        picture = Path(self.temporary.name) / "diagram.png"
        _ffmpeg("-f", "lavfi", "-i", "color=c=red:s=320x180", "-frames:v", "1", str(picture))
        saved = self.save({"layout": "split", "panel": {"kind": "file", "path": str(picture)}})
        digest = saved["settings"]["layout"]["panel"]["sha256"]
        still = self.studio.layout_still(saved["id"], digest)
        self.assertTrue(still["data_url"].startswith("data:image/jpeg;base64,/9j/"))
        with self.assertRaises(ValueError):
            self.studio.layout_still(saved["id"], "0" * 64)
        with self.assertRaises(ValueError):
            self.studio.layout_still(saved["id"], "../studio.json")


if __name__ == "__main__":
    unittest.main()
