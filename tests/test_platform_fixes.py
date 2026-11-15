"""Platform layout, caption fitting, frame-rate, upscaling and source data checks."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cutroom import platforms
from cutroom import postproduction as pp

PLATFORMS = ("instagram_reels", "youtube_shorts", "tiktok", "youtube")
LONG_CUE = (
    "WWWW MMMM WWWW MMMM WWWW MMMM WWWW MMMM WWWW MMMM WWWW MMMM WWWW MMMM "
    "WWWW MMMM WWWW"
)


def ffmpeg(*arguments, timeout=120):
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-n", *arguments],
        check=True,
        capture_output=True,
        timeout=timeout,
    )


def encode(path, source, *extra):
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        source,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        *extra,
        str(path),
    )


def gray_frame(video, at, target):
    ffmpeg(
        "-ss",
        str(at),
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-pix_fmt",
        "gray",
        "-f",
        "image2",
        "-c:v",
        "pgm",
        str(target),
    )
    data = target.read_bytes()
    header, offset = [], 0
    while len(header) < 4:
        end = data.index(b"\n", offset)
        header += data[offset:end].split()
        offset = end + 1
    width, height = int(header[1]), int(header[2])
    return width, height, data[offset : offset + width * height]


def zone_box(name, width, height, margin):
    zone = platforms.profile(name)["safe_zone"]
    return (
        int(width * max(zone["left"], margin)),
        int(height * max(zone["top"], margin)),
        int(width * (1 - max(zone["right"], margin))),
        int(height * (1 - max(zone["bottom"], margin))),
    )


class CaptionBandTests(unittest.TestCase):
    info = dict(width=320, height=180, display_aspect_ratio=16 / 9)

    def layout(self, name, brand, lower_third="", captions=True):
        settings = pp._settings(
            {"platform": name, "brand": brand, "lower_third": lower_third}
        )
        width, height = pp._dimensions(self.info, settings)
        return (
            settings,
            width,
            height,
            pp.platform_layout(settings, width, height, captions=captions),
        )

    def test_caption_band_is_clamped_at_the_top_of_the_safe_zone(self):
        for name in PLATFORMS:
            for margin in (0.02, 0.08, 0.25):
                for size in (12, 36, 120):
                    brand = {
                        "safe_margin": margin,
                        "subtitle_y": margin,
                        "title_y": margin,
                        "subtitle_size": size,
                    }
                    _, width, height, layout = self.layout(name, brand)
                    with self.subTest(profile=name, margin=margin, size=size):
                        box = layout["boxes"]["captions"]
                        self.assertGreaterEqual(box["y"], layout["safe"]["y0"] - 1e-6)
                        self.assertLessEqual(
                            box["y"] + box["h"], layout["safe"]["y1"] + 1e-6
                        )
                        self.assertEqual(
                            pp.safe_zone_findings(
                                layout["boxes"],
                                platforms.profile(name)["safe_zone"],
                                width,
                                height,
                            ),
                            [],
                        )

    def test_lower_third_is_clamped_instead_of_rejected(self):
        for name in PLATFORMS:
            for captions in (False, True):
                for subtitle_y in (0.02, 0.05, 0.3, 0.9):
                    brand = {"safe_margin": 0.02, "subtitle_y": subtitle_y}
                    with self.subTest(
                        profile=name, captions=captions, subtitle_y=subtitle_y
                    ):
                        _, width, height, layout = self.layout(
                            name, brand, "Speaker Name", captions
                        )
                        boxes = layout["boxes"]
                        self.assertEqual(
                            pp.safe_zone_findings(
                                boxes,
                                platforms.profile(name)["safe_zone"],
                                width,
                                height,
                            ),
                            [],
                        )
                        if captions:
                            lower, band = boxes["lower_third"], boxes["captions"]
                            self.assertLessEqual(
                                lower["y"] + lower["h"], band["y"] + 1e-6
                            )

    def test_long_cues_are_split_into_events_of_at_most_two_lines(self):
        for name in PLATFORMS:
            settings, width, height, layout = self.layout(
                name, {"subtitle_size": 80, "safe_margin": 0.02}
            )
            cues = [
                {"start": 0.0, "end": 4.0, "text": LONG_CUE},
                {"start": 4.0, "end": 5.0, "text": "Short\nexplicit lines\nthree"},
            ]
            fitted = pp.platform_caption_cues(cues, layout)
            band = layout["boxes"]["captions"]
            per_line = band["chars_per_line"]
            with self.subTest(profile=name):
                self.assertGreaterEqual(per_line, 1)
                self.assertLessEqual(per_line * band["size"], band["w"] + 1e-6)
                self.assertGreater(len(fitted), 2)
                previous = 0.0
                for cue in fitted:
                    lines = cue["text"].split("\n")
                    self.assertLessEqual(len(lines), 2, cue)
                    self.assertTrue(all(len(line) <= per_line for line in lines))
                    self.assertGreaterEqual(cue["start"], previous - 1e-9)
                    self.assertGreater(cue["end"], cue["start"])
                    previous = cue["end"]
                words = " ".join(c["text"] for c in fitted).split()
                self.assertEqual(
                    "".join(words),
                    "".join((LONG_CUE + " Short explicit lines three").split()),
                )
                self.assertAlmostEqual(fitted[-1]["end"], 5.0)
                self.assertEqual(pp._captions(fitted, 5.0), fitted)


class CaptionRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(
            dir=os.environ.get("TMPDIR"), prefix="platform-fixes-"
        )
        cls.root = Path(cls.temp.name)
        cls.black = cls.root / "black.mp4"
        encode(cls.black, "color=black:size=320x180:rate=10:duration=2")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_top_positioned_long_captions_stay_inside_every_safe_zone(self):
        margin = 0.02
        for name in PLATFORMS:
            with self.subTest(profile=name):
                output = self.root / f"top-{name}.mp4"
                result = pp.export_video(
                    self.black,
                    [{"start": 0, "end": 2}],
                    output,
                    settings={
                        "platform": name,
                        "preset": "preview",
                        "lower_third": "Speaker Name",
                        "brand": {
                            "safe_margin": margin,
                            "subtitle_y": margin,
                            "subtitle_size": 60,
                        },
                    },
                    captions=[{"start": 0, "end": 2, "text": LONG_CUE}],
                )
                self.assertGreater(result["caption_events"], 1)
                for at in (0.25, 1.75):
                    width, height, pixels = gray_frame(
                        output, at, self.root / f"top-{name}-{at}.pgm"
                    )
                    rows = [
                        y
                        for y in range(height)
                        if max(pixels[y * width : (y + 1) * width]) > 60
                    ]
                    columns = [
                        x
                        for x in range(width)
                        if any(pixels[y * width + x] > 60 for y in rows[::2])
                    ]
                    self.assertTrue(rows, "Text must be visible")
                    left, top, right, bottom = zone_box(name, width, height, margin)
                    self.assertGreaterEqual(min(rows), top, (name, at, "top"))
                    self.assertLess(max(rows), bottom, (name, at, "bottom"))
                    self.assertGreaterEqual(min(columns), left, (name, at, "left"))
                    self.assertLess(max(columns), right, (name, at, "right"))
                    layout = result["safe_zone_layout"]["boxes"]
                    band = layout["captions"]
                    caption_rows = [
                        y
                        for y in rows
                        if band["y"] - 4 <= y <= band["y"] + band["h"] + 4
                    ]
                    groups = sum(
                        1
                        for index, y in enumerate(caption_rows)
                        if index == 0 or y - caption_rows[index - 1] > 1
                    )
                    self.assertLessEqual(groups, 2, (name, at, "caption lines"))


class FrameRateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(
            dir=os.environ.get("TMPDIR"), prefix="platform-fps-"
        )
        cls.root = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fps(self, path):
        report = pp.quality_report(
            path, {"platform": "instagram_reels", "preset": "preview"}
        )
        return next(c for c in report["checks"] if c["name"] == "platform_fps")

    def test_ntsc_rate_meets_a_thirty_fps_minimum(self):
        path = self.root / "ntsc.mp4"
        encode(path, "testsrc2=size=108x192:rate=30000/1001:duration=2")
        check = self.fps(path)
        self.assertEqual(check["status"], "pass", check)
        pal = self.root / "pal.mp4"
        encode(pal, "testsrc2=size=108x192:rate=25:duration=2")
        self.assertEqual(self.fps(pal)["status"], "warning")

    def test_variable_rate_reports_the_slowest_frame_interval(self):
        fast, slow = self.root / "fast.mp4", self.root / "slow.mp4"
        encode(
            fast,
            "testsrc2=size=108x192:rate=60:duration=1",
            "-video_track_timescale",
            "600",
        )
        encode(
            slow,
            "testsrc2=size=108x192:rate=10:duration=1",
            "-video_track_timescale",
            "600",
        )
        listing = self.root / "list.txt"
        listing.write_text(
            f"file '{fast.as_posix()}'\nfile '{slow.as_posix()}'\n", encoding="utf-8"
        )
        variable = self.root / "vfr.mp4"
        ffmpeg(
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(variable),
        )
        check = self.fps(variable)
        self.assertEqual(check["status"], "warning", check)
        self.assertTrue(check["detail"]["variable_frame_rate"])
        self.assertAlmostEqual(check["detail"]["min_instantaneous_fps"], 10, delta=0.5)
        self.assertGreater(check["detail"]["actual"], 30)


class UpscaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(
            dir=os.environ.get("TMPDIR"), prefix="platform-upscale-"
        )
        cls.root = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_source_video_uses_display_orientation(self):
        base = self.root / "base.mp4"
        encode(base, "testsrc2=size=320x180:rate=10:duration=1")
        rotated = self.root / "rotated.mp4"
        ffmpeg("-display_rotation", "90", "-i", str(base), "-c", "copy", str(rotated))
        info = pp._probe(rotated)
        source = pp._source_video(info)
        self.assertEqual((source["width"], source["height"]), (180, 320))
        self.assertAlmostEqual(source["display_aspect_ratio"], 180 / 320, places=3)
        output = self.root / "rot-reels.mp4"
        result = pp.export_video(
            rotated,
            [{"start": 0, "end": 1}],
            output,
            settings={"platform": "instagram_reels", "preset": "preview"},
        )
        self.assertEqual(result["source_video"], source)
        self.assertEqual(result["content_size"], [1080, 1920])
        self.assertAlmostEqual(result["upscale_factor"], 6.0, places=2)
        self.assertTrue(result["upscaled"])

    def test_upscale_factor_follows_the_fitted_content_not_the_frame(self):
        # A rotated 3000x1000 recording displays as 1000x3000; in a 3840x2160
        # frame its content is 720x2160, a downscale.
        source = {"width": 1000, "height": 3000, "display_aspect_ratio": 1 / 3}
        content, factor = pp._content_upscale(source, 3840, 2160)
        self.assertEqual(content, [720, 2160])
        self.assertLess(factor, 1)
        content, factor = pp._content_upscale(
            {"width": 1080, "height": 1920, "display_aspect_ratio": 0.5625}, 2160, 3840
        )
        self.assertEqual(content, [2160, 3840])
        self.assertAlmostEqual(factor, 2.0)

    def test_quality_report_flags_upscaled_platform_output(self):
        video = self.root / "small.mp4"
        encode(video, "testsrc2=size=108x192:rate=30:duration=1")
        settings = {
            "platform": "tiktok",
            "preset": "final",
            "final_resolution": "2160",
        }

        def check(extra):
            report = pp.quality_report(video, {**settings, **extra})
            return next(
                (c for c in report["checks"] if c["name"] == "platform_upscale"), None
            )

        low = check(
            {
                "source_video": {
                    "width": 54,
                    "height": 96,
                    "display_aspect_ratio": 0.5625,
                }
            }
        )
        self.assertEqual(low["status"], "warning", low)
        self.assertEqual(low["detail"]["source"], [54, 96])
        self.assertEqual(low["detail"]["content"], [108, 192])
        self.assertAlmostEqual(low["detail"]["factor"], 2.0)
        self.assertEqual(low["detail"]["final_resolution"], "2160")
        same = check(
            {
                "source_video": {
                    "width": 1080,
                    "height": 1920,
                    "display_aspect_ratio": 0.5625,
                }
            }
        )
        self.assertEqual(same["status"], "pass", same)
        self.assertEqual(check({})["status"], "skip")
        for bad in (
            {"width": 0, "height": 10, "display_aspect_ratio": 1},
            {"width": 10, "height": 10},
            {"width": True, "height": 10, "display_aspect_ratio": 1},
            [10, 10],
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pp._settings({"platform": "tiktok", "source_video": bad})


class SourceDataTests(unittest.TestCase):
    def urls(self):
        found = set()

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "source":
                        found.add(item)
                    walk(item)

        walk(platforms.PROFILES)
        return found

    def test_sources_point_at_pages_that_state_the_values(self):
        reels = platforms.profile("instagram_reels")
        length = "https://help.instagram.com/2720958398006062"
        self.assertEqual(reels["max_duration_s"]["source"], length)
        self.assertEqual(reels["recommended_max_s"]["source"], length)
        urls = self.urls()
        for stale in (
            "about.instagram.com",
            "www.aes.org/wp-content/uploads/2024",
            "tech.ebu.ch/publications",
            "support.tiktok.com",
            "ads.tiktok.com/help/",
            "developers.tiktok.com/doc/",
            "developers.google.com/youtube/v3/docs",
            "developers.facebook.com/docs/",
        ):
            self.assertFalse([u for u in urls if stale in u], stale)
        self.assertEqual(
            reels["loudness"]["source"],
            "https://aes.org/wp-content/uploads/2026/10/20210924_TD1008_v3.13.pdf",
        )
        self.assertEqual(
            platforms.profile("youtube")["safe_zone"]["source"],
            "https://tech.ebu.ch/docs/r/r095.pdf",
        )

    def test_covers_record_what_the_pages_say(self):
        reels = platforms.profile("instagram_reels")["cover"]
        self.assertEqual((reels["width"], reels["height"]), (420, 654))
        self.assertEqual(reels["ratio"], "1:1.55")
        youtube = platforms.profile("youtube")["cover"]
        self.assertEqual((youtube["width"], youtube["height"]), (3840, 2160))
        self.assertEqual(youtube["min_width"], 640)
        self.assertEqual(youtube["ratio"], "16:9")
        shorts = platforms.profile("youtube_shorts")["cover"]
        self.assertEqual((shorts["width"], shorts["height"]), (2160, 3840))
        self.assertEqual(shorts["min_height"], 640)
        self.assertEqual(shorts["ratio"], "9:16")
        tiktok = platforms.profile("tiktok")["cover"]
        self.assertNotIn("width", tiktok)

    def test_frames_are_marked_as_cutroom_choices_within_the_platform_rules(self):
        for name in PLATFORMS:
            frame = platforms.profile(name)["frame"]
            with self.subTest(profile=name):
                self.assertEqual(frame["chosen_by"], "cutroom")
                self.assertTrue(frame["platform_rule"])
        self.assertIn(
            "720", platforms.profile("instagram_reels")["frame"]["platform_rule"]
        )
        self.assertIn("540", platforms.profile("tiktok")["frame"]["platform_rule"])


if __name__ == "__main__":
    unittest.main()
