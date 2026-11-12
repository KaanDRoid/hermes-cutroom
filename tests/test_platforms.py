"""Platform profiles, platform render geometry and per-platform quality checks."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cutroom import postproduction as pp

CHECKED = "2026-11-12"
SHORT_FORM = ("instagram_reels", "youtube_shorts", "tiktok")


def platforms():
    from cutroom import platforms as module

    return module


def numeric(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, dict):
        return any(numeric(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(numeric(item) for item in value)
    return False


def ffmpeg(*arguments, timeout=120):
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-n", *arguments],
        check=True,
        capture_output=True,
        timeout=timeout,
    )


class ProfileDataTests(unittest.TestCase):
    def test_profiles_cover_the_four_platforms_and_custom(self):
        module = platforms()
        self.assertEqual(
            set(module.PROFILES),
            {"custom", "instagram_reels", "youtube_shorts", "tiktok", "youtube"},
        )
        self.assertEqual(module.FINAL_RESOLUTIONS, ("1080", "2160"))
        for name in SHORT_FORM:
            entry = module.profile(name)
            self.assertEqual(entry["orientation"], "portrait")
            self.assertEqual(entry["frame"]["preview"], [1080, 1920])
            self.assertEqual(entry["frame"]["final"]["1080"], [1080, 1920])
            self.assertEqual(entry["frame"]["final"]["2160"], [2160, 3840])
            self.assertEqual(entry["frame"]["default_final"], "1080")
        youtube = module.profile("youtube")
        self.assertEqual(youtube["orientation"], "landscape")
        self.assertEqual(youtube["frame"]["final"]["1080"], [1920, 1080])
        self.assertEqual(youtube["frame"]["final"]["2160"], [3840, 2160])
        self.assertEqual(youtube["frame"]["default_final"], "1080")
        custom = module.profile("custom")
        self.assertIsNone(custom["frame"])
        self.assertIsNone(custom["safe_zone"])
        with self.assertRaises(ValueError):
            module.profile("vine")

    def test_limits_loudness_safe_zones_and_text(self):
        module = platforms()
        limits = {
            "youtube_shorts": 180,
            "instagram_reels": 1200,
            "tiktok": 3600,
            "youtube": None,
        }
        for name, limit in limits.items():
            entry = module.profile(name)
            self.assertEqual(entry["max_duration_s"]["value"], limit, name)
            self.assertEqual(entry["loudness"]["integrated_lufs"], -14, name)
            self.assertEqual(entry["loudness"]["true_peak_db"], -1, name)
            zone = entry["safe_zone"]
            for side in ("top", "bottom", "left", "right"):
                self.assertGreaterEqual(zone[side], 0.0, name)
                self.assertLess(zone[side], 0.5, name)
            self.assertLess(zone["top"] + zone["bottom"], 0.6, name)
            self.assertLess(zone["left"] + zone["right"], 0.6, name)
        reels = module.profile("instagram_reels")
        self.assertEqual(reels["recommended_max_s"]["value"], 180)
        self.assertEqual(reels["min_fps"]["value"], 30)
        self.assertEqual(
            {k: reels["safe_zone"][k] for k in ("top", "bottom", "left", "right")},
            {"top": 0.14, "bottom": 0.35, "left": 0.06, "right": 0.06},
        )
        self.assertEqual(reels["text"]["caption_chars"], 2200)
        self.assertEqual(reels["text"]["hashtags"], 30)
        for name in ("youtube", "youtube_shorts"):
            text = module.profile(name)["text"]
            self.assertEqual(text["title_chars"], 100)
            self.assertEqual(text["description_bytes"], 5000)
        self.assertEqual(module.profile("tiktok")["text"]["caption_chars"], 2200)
        self.assertEqual(module.profile("youtube")["cover"]["width"], 1280)
        self.assertEqual(module.profile("youtube")["cover"]["height"], 720)
        self.assertIn("end_screen", module.profile("youtube"))

    def test_every_numeric_specification_has_a_source_and_check_date(self):
        module = platforms()
        for name, entry in module.PROFILES.items():
            for key, block in entry.items():
                if not isinstance(block, dict) or not numeric(block):
                    continue
                with self.subTest(profile=name, spec=key):
                    self.assertTrue(
                        str(block.get("source", "")).startswith("https://"), block
                    )
                    self.assertEqual(block.get("checked"), CHECKED)

    def test_tool_and_api_platform_lists_match_the_profiles(self):
        from cutroom import studio_tools

        self.assertEqual(studio_tools.PLATFORMS, platforms().PLATFORMS)
        source = (
            Path(__file__).resolve().parents[1] / "dashboard" / "plugin_api.py"
        ).read_text(encoding="utf-8")
        for name in platforms().PLATFORMS:
            self.assertIn(f'"{name}"', source)

    def test_public_profiles_are_json_safe_copies(self):
        module = platforms()
        public = module.public_profiles()
        self.assertEqual(
            [item["name"] for item in public],
            ["custom", "instagram_reels", "youtube_shorts", "tiktok", "youtube"],
        )
        self.assertEqual(json.loads(json.dumps(public, allow_nan=False)), public)
        public[1]["safe_zone"]["top"] = 0.9
        self.assertEqual(module.profile("instagram_reels")["safe_zone"]["top"], 0.14)
        for item in public[1:]:
            self.assertIn("label", item)
            self.assertIn("short_label", item)


class PlatformGeometryTests(unittest.TestCase):
    info = dict(width=320, height=180, display_aspect_ratio=16 / 9)

    def test_platform_frames_override_aspect_and_preset(self):
        for name in SHORT_FORM:
            preview = pp._settings({"platform": name, "preset": "preview"})
            self.assertEqual(pp._dimensions(self.info, preview), (1080, 1920))
            final = pp._settings({"platform": name, "preset": "final"})
            self.assertEqual(pp._dimensions(self.info, final), (1080, 1920))
            uhd = pp._settings(
                {"platform": name, "preset": "final", "final_resolution": "2160"}
            )
            self.assertEqual(pp._dimensions(self.info, uhd), (2160, 3840))
        youtube = pp._settings({"platform": "youtube", "preset": "final"})
        self.assertEqual(pp._dimensions(self.info, youtube), (1920, 1080))
        custom = pp._settings({"platform": "custom", "preset": "final"})
        self.assertEqual(
            pp._dimensions(self.info, custom),
            pp._dimensions(self.info, pp._settings({"preset": "final"})),
        )
        for bad in ({"platform": "vine"}, {"final_resolution": "720"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pp._settings(bad)

    def test_profile_loudness_is_the_default_target(self):
        settings = pp._settings({"platform": "tiktok"})
        self.assertEqual(settings["loudness_lufs"], -14)
        self.assertEqual(settings["true_peak_db"], -1)
        self.assertEqual(pp._settings({})["loudness_lufs"], -16)

    def test_text_boxes_are_clamped_inside_every_safe_zone(self):
        module = platforms()
        for name in ("instagram_reels", "youtube_shorts", "tiktok", "youtube"):
            for brand in (
                {},
                {"title_y": 0.02 + 0.06, "subtitle_y": 0.9, "safe_margin": 0.02},
                {
                    "alignment": "right",
                    "title_size": 120,
                    "subtitle_size": 80,
                    "subtitle_y": 0.7,
                },
            ):
                settings = pp._settings(
                    {"platform": name, "brand": brand, "lower_third": "Speaker"}
                )
                width, height = pp._dimensions(self.info, settings)
                layout = pp.platform_layout(
                    settings,
                    width,
                    height,
                    title="A long platform title\nSecond line",
                    captions=True,
                )
                with self.subTest(profile=name, brand=brand):
                    self.assertEqual(
                        set(layout["boxes"]), {"title", "lower_third", "captions"}
                    )
                    zone = module.profile(name)["safe_zone"]
                    self.assertEqual(
                        pp.safe_zone_findings(layout["boxes"], zone, width, height), []
                    )

    def test_safe_zone_findings_report_a_box_in_the_unsafe_area(self):
        zone = platforms().profile("instagram_reels")["safe_zone"]
        boxes = {"title": {"x": 100, "y": 100, "w": 400, "h": 80}}
        findings = pp.safe_zone_findings(boxes, zone, 1080, 1920)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["box"], "title")
        self.assertIn("top", findings[0]["sides"])

    def test_custom_layout_is_not_platform_geometry(self):
        settings = pp._settings({})
        self.assertIsNone(pp.platform_layout(settings, 1920, 1080, title="Title"))


class PlatformQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(
            dir=os.environ.get("TMPDIR"), prefix="platforms-"
        )
        cls.root = Path(cls.temp.name)
        # A cheap 185-second video: 1 fps, tiny frame, no audio.
        cls.long = cls.root / "long.mp4"
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x114:rate=1:duration=185",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(cls.long),
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def checks(self, report):
        return {check["name"]: check for check in report["checks"]}

    def test_shorts_longer_than_three_minutes_fail_platform_duration(self):
        report = pp.quality_report(
            self.long, {"platform": "youtube_shorts", "preset": "preview"}
        )
        checks = self.checks(report)
        self.assertEqual(checks["platform_duration"]["status"], "fail")
        self.assertEqual(checks["platform_duration"]["detail"]["max_seconds"], 180)
        self.assertEqual(checks["platform_frame"]["status"], "fail")
        self.assertEqual(checks["platform_frame"]["detail"]["expected"], [1080, 1920])
        self.assertFalse(report["passed"])

    def test_reels_above_recommended_length_warn_and_low_fps_warns(self):
        checks = self.checks(
            pp.quality_report(
                self.long, {"platform": "instagram_reels", "preset": "preview"}
            )
        )
        self.assertEqual(checks["platform_duration"]["status"], "warning")
        self.assertEqual(checks["platform_fps"]["status"], "warning")
        self.assertEqual(checks["platform_fps"]["detail"]["min_fps"], 30)

    def test_youtube_has_no_hard_length_limit(self):
        checks = self.checks(
            pp.quality_report(self.long, {"platform": "youtube", "preset": "preview"})
        )
        self.assertEqual(checks["platform_duration"]["status"], "pass")
        self.assertIsNone(checks["platform_duration"]["detail"]["max_seconds"])

    def test_custom_reports_have_no_platform_checks(self):
        checks = self.checks(pp.quality_report(self.long, {"preset": "preview"}))
        self.assertFalse([name for name in checks if name.startswith("platform_")])
        self.assertNotIn("safe_zone", checks)


class PlatformRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(
            dir=os.environ.get("TMPDIR"), prefix="platform-render-"
        )
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "landscape.mp4"
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30:duration=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=3",
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(cls.source),
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_landscape_source_renders_exact_shorts_frame_and_passes_platform_qa(self):
        output = self.root / "shorts.mp4"
        settings = {
            "platform": "youtube_shorts",
            "preset": "preview",
            "aspect": "portrait",
            "title": "Shorts title",
            "timeout": 300,
        }
        captions = [{"start": 0.2, "end": 1.4, "text": "Inside the safe zone"}]
        result = pp.export_video(
            self.source,
            [{"start": 0, "end": 2.5}],
            output,
            settings=settings,
            captions=captions,
        )
        self.assertEqual((result["width"], result["height"]), (1080, 1920))
        self.assertEqual(result["platform"], "youtube_shorts")
        self.assertEqual(result["audio_normalization"]["target_lufs"], -14)
        report = pp.quality_report(
            output, {**settings, "expected_duration": 2.5}, captions=captions
        )
        checks = {check["name"]: check for check in report["checks"]}
        for name in (
            "platform_frame",
            "platform_duration",
            "platform_loudness",
            "safe_zone",
            "resolution",
        ):
            self.assertEqual(checks[name]["status"], "pass", checks[name])
        self.assertEqual(checks["platform_fps"]["status"], "skip")

    def test_burned_title_and_captions_stay_out_of_reels_unsafe_areas(self):
        black = self.root / "black.mp4"
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "color=black:size=320x180:rate=10:duration=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(black),
        )
        output = self.root / "reels-text.mp4"
        pp.export_video(
            black,
            [{"start": 0, "end": 1}],
            output,
            settings={
                "platform": "instagram_reels",
                "preset": "preview",
                "title": "TITLE WWW MMM\nSECOND LINE",
                "lower_third": "Lower third name",
                "brand": {"title_y": 0.08, "subtitle_y": 0.88, "safe_margin": 0.02},
            },
            captions=[{"start": 0, "end": 1, "text": "WWWW MMMM WWWW MMMM WWWW"}],
        )
        frame = self.root / "frame.pgm"
        ffmpeg(
            "-ss",
            "0.5",
            "-i",
            str(output),
            "-frames:v",
            "1",
            "-pix_fmt",
            "gray",
            "-f",
            "image2",
            "-c:v",
            "pgm",
            str(frame),
        )
        data = frame.read_bytes()
        header, offset = [], 0
        while len(header) < 4:
            end = data.index(b"\n", offset) if b"\n" in data[offset:] else len(data)
            header += data[offset:end].split()
            offset = end + 1
        width, height = int(header[1]), int(header[2])
        pixels = data[offset : offset + width * height]
        self.assertEqual((width, height), (1080, 1920))

        def bright(x0, y0, x1, y1):
            return sum(
                1
                for y in range(y0, y1)
                for value in pixels[y * width + x0 : y * width + x1]
                if value > 60
            )

        self.assertGreater(bright(0, 0, width, height), 500, "Text must be visible")
        zone = platforms().profile("instagram_reels")["safe_zone"]
        top = int(zone["top"] * height)
        bottom = int((1 - zone["bottom"]) * height)
        left = int(zone["left"] * width)
        right = int((1 - zone["right"]) * width)
        self.assertEqual(bright(0, 0, width, top), 0, "top unsafe band")
        self.assertEqual(bright(0, bottom, width, height), 0, "bottom unsafe band")
        self.assertEqual(bright(0, 0, left, height), 0, "left unsafe band")
        self.assertEqual(bright(right, 0, width, height), 0, "right unsafe band")


if __name__ == "__main__":
    unittest.main()
