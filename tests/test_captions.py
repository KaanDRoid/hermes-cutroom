"""Animated word captions: styles, measured layout, ASS timing and rendered pixels."""

import math
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from cutroom import platforms
from cutroom import postproduction as pp

try:
    from cutroom import captions
except ImportError:  # RED: the module does not exist yet
    captions = None

PLATFORMS = ("instagram_reels", "youtube_shorts", "tiktok", "youtube")
WORDS = [
    dict(start=0.5, end=0.9, text="ONE"),
    dict(start=1.0, end=1.4, text="TWO"),
    dict(start=1.5, end=2.4, text="THREE"),
]


def ffmpeg(*arguments, timeout=120):
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-n", *arguments],
        check=True,
        capture_output=True,
        timeout=timeout,
    )


def black_source(path, duration=3, size="320x180"):
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={size}:r=30:d={duration}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(path),
    )


def rgb_frames(video, crop):
    """Every decoded frame of a crop (x, y, w, h) as raw RGB bytes."""
    x, y, w, h = crop
    data = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            f"crop={w}:{h}:{x}:{y}",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=120,
    ).stdout
    size = w * h * 3
    return [data[i : i + size] for i in range(0, len(data) - size + 1, size)], w


def red_pixels(frame, width):
    """Count and mean x of strongly red pixels."""
    xs = [
        (index // 3) % width
        for index in range(0, len(frame), 3)
        if frame[index] > 150 and frame[index + 1] < 90 and frame[index + 2] < 90
    ]
    return len(xs), (sum(xs) / len(xs) if xs else None), xs


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


class _CaptionCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(captions, "cutroom.captions must exist")

    def build(self, style, words=WORDS, platform="instagram_reels", **extra):
        settings = pp._settings({"platform": platform, "caption_style": style, **extra})
        width, height = pp._dimensions(
            dict(width=320, height=180, display_aspect_ratio=16 / 9), settings
        )
        layout = pp.platform_layout(settings, width, height, captions=True)
        plan = captions.build(
            words,
            settings,
            width,
            height,
            layout,
            frame_rate="30/1",
            duration=3.0,
        )
        return settings, width, height, layout, plan


class SettingsTests(_CaptionCase):
    def test_styles_and_defaults(self):
        self.assertEqual(captions.STYLES, ("classic", "highlight", "pop", "one_word"))
        settings = pp._settings({})
        self.assertEqual(settings["caption_style"], "classic")
        self.assertRegex(settings["caption_highlight_color"], r"^#[0-9A-F]{6}$")
        self.assertNotEqual(
            settings["caption_highlight_color"], settings["brand"]["subtitle_color"]
        )
        self.assertTrue(0 <= settings["caption_word_y"] <= 1)

    def test_settings_are_strict(self):
        for bad in (
            {"caption_style": "karaoke"},
            {"caption_style": None},
            {"caption_style": 1},
            {"caption_highlight_color": "yellow"},
            {"caption_highlight_color": "#FFF"},
            {"caption_word_y": -0.1},
            {"caption_word_y": 1.5},
            {"caption_word_y": True},
            {"caption_word_y": math.nan},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pp._settings(bad)


class MeasurementTests(_CaptionCase):
    def test_glyph_measurement_is_narrower_than_a_full_em(self):
        measure = captions.Measurer(pp._font_path("Arial"))
        self.assertEqual(measure.method, "glyph")
        self.assertLess(measure("iiiiiiii", 40), 8 * 40 * 0.5)
        self.assertGreater(measure("WWWW", 40), measure("iiii", 40))
        # Linear in size.
        self.assertAlmostEqual(
            measure("Hello world", 80), 2 * measure("Hello world", 40), delta=1
        )

    def test_missing_font_falls_back_to_the_full_em_estimate(self):
        measure = captions.Measurer(None)
        self.assertEqual(measure.method, "em")
        self.assertEqual(measure("abcd", 30), 120)

    def test_classic_platform_cues_wrap_by_measured_width(self):
        settings = pp._settings({"platform": "instagram_reels"})
        layout = pp.platform_layout(settings, 1080, 1920, captions=True)
        band = layout["boxes"]["captions"]
        text = "little lilies fill a little hill in mild light " * 2
        cue = [dict(start=0, end=4, text=text.strip())]
        estimated = pp.platform_caption_cues(cue, layout)
        measure = captions.Measurer(pp._font_path("Arial"))
        measured = pp.platform_caption_cues(cue, layout, measure=measure)
        self.assertLess(len(measured), len(estimated))
        for event in measured:
            lines = event["text"].split("\n")
            self.assertLessEqual(len(lines), 2)
            for line in lines:
                self.assertLessEqual(measure(line, band["size"]), band["w"])
        self.assertEqual(
            " ".join(e["text"].replace("\n", " ") for e in measured), text.strip()
        )


class BuildTests(_CaptionCase):
    def word_events(self, plan):
        parsed = captions.parse_script(plan["script"])
        return {
            int(event["name"][1:]): event
            for event in parsed["events"]
            if event["name"].startswith("w")
        }

    def test_every_word_starts_within_one_frame_of_its_timestamp(self):
        for style in ("highlight", "pop", "one_word"):
            words = [
                dict(start=0.123 + i * 0.211, end=0.3 + i * 0.211, text=f"w{i}")
                for i in range(12)
            ]
            *_, plan = self.build(style, words)
            events = self.word_events(plan)
            with self.subTest(style=style):
                self.assertEqual(sorted(events), list(range(12)))
                for index, word in enumerate(words):
                    start = events[index]["start"]
                    first_frame = math.ceil(start * 30 - 1e-9) / 30
                    self.assertGreaterEqual(first_frame, word["start"] - 1e-9)
                    self.assertLess(first_frame - word["start"], 1 / 30)
                    self.assertGreater(events[index]["end"], start)

    def test_highlight_colours_only_the_current_word(self):
        *_, plan = self.build("highlight", caption_highlight_color="#FF0000")
        events = self.word_events(plan)
        for index, word in enumerate(WORDS):
            text = events[index]["text"]
            self.assertIn(r"\1c&H0000FF&}" + word["text"], text)
            self.assertEqual(text.count(r"\1c&H0000FF&"), 1)
            self.assertEqual(captions.plain_text(text).split(), ["ONE", "TWO", "THREE"])

    def test_pop_reveals_words_one_by_one_with_a_scale_in(self):
        *_, plan = self.build("pop")
        events = self.word_events(plan)
        first = events[0]["text"]
        self.assertRegex(first, r"\\fscy\d+\\t\(0,\d+,.*\\fscy100")
        self.assertRegex(first, r"\\alpha&HFF&.*TWO")
        last = events[2]["text"]
        self.assertNotRegex(last.split("THREE")[0], r"\\alpha&HFF&")

    def test_one_word_is_single_large_and_centred_in_the_safe_area(self):
        settings, width, height, layout, plan = self.build("one_word")
        parsed = captions.parse_script(plan["script"])
        safe = layout["safe"]
        band = layout["boxes"]["captions"]
        for event in parsed["events"]:
            self.assertEqual(len(captions.plain_text(event["text"]).split()), 1)
            x, y = map(
                float, re.search(r"\\pos\(([\d.]+),([\d.]+)\)", event["text"]).groups()
            )
            self.assertAlmostEqual(x, (safe["x0"] + safe["x1"]) / 2, delta=1)
            self.assertTrue(safe["y0"] <= y <= safe["y1"])
        self.assertGreater(parsed["styles"]["Word"]["size"], band["size"])

    def test_one_word_vertical_position_is_configurable(self):
        positions = []
        for value in (0.0, 1.0):
            *_, layout, plan = self.build("one_word", caption_word_y=value)
            event = captions.parse_script(plan["script"])["events"][0]
            positions.append(
                float(re.search(r"\\pos\([\d.]+,([\d.]+)\)", event["text"])[1])
            )
        self.assertLess(positions[0], positions[1])

    def test_one_word_defaults_below_the_face_area(self):
        # Talking heads keep the face in the upper part of the frame; a centred
        # word sat on the speaker's face in real footage. Default to the lower
        # fifth of the safe area.
        *_, layout, plan = self.build("one_word")
        safe = layout["safe"]
        y = float(
            re.search(
                r"\\pos\([\d.]+,([\d.]+)\)",
                captions.parse_script(plan["script"])["events"][0]["text"],
            )[1]
        )
        self.assertGreater(y, safe["y0"] + 0.7 * (safe["y1"] - safe["y0"]))
        self.assertLessEqual(y, safe["y1"])
        self.assertEqual(captions.DEFAULT_WORD_Y, 0.8)

    def test_at_most_two_lines_and_text_inside_the_safe_zone(self):
        words = [
            dict(start=0.1 + i * 0.3, end=0.35 + i * 0.3, text=text)
            for i, text in enumerate(
                "WWWWWWWW MMMMMMMM Extraordinarily WWWWWWWW MMMMMMMM "
                "Incomprehensibilities".split()
                * 2
            )
        ]
        for platform in PLATFORMS:
            for style in ("highlight", "pop", "one_word"):
                settings, width, height, layout, plan = self.build(
                    style, words, platform=platform
                )
                parsed = captions.parse_script(plan["script"])
                measure = captions.Measurer(pp._font_path("Arial"))
                boxes = captions.event_boxes(parsed, measure)
                zone = platforms.profile(platform)["safe_zone"]
                with self.subTest(platform=platform, style=style):
                    for event in parsed["events"]:
                        self.assertLessEqual(event["text"].count(r"\N"), 1)
                    self.assertEqual(
                        pp.safe_zone_findings(
                            {f"e{i}": box for i, box in enumerate(boxes)},
                            zone,
                            width,
                            height,
                        ),
                        [],
                    )
                    for box in boxes:
                        self.assertGreaterEqual(box["x"], layout["safe"]["x0"] - 1)
                        self.assertLessEqual(
                            box["x"] + box["w"], layout["safe"]["x1"] + 1
                        )

    def test_text_is_literal(self):
        words = [dict(start=0.2, end=0.6, text=r"{\pos(0,0)}hack\N")]
        for style in ("highlight", "pop", "one_word"):
            *_, plan = self.build(style, words)
            parsed = captions.parse_script(plan["script"])
            with self.subTest(style=style):
                self.assertNotIn(r"\pos(0,0)", plan["script"])
                self.assertIn("｛", captions.plain_text(parsed["events"][0]["text"]))

    def test_words_from_cues_spread_time_by_characters(self):
        words = captions.words_from_cues([dict(start=1, end=3, text="aa bbbb aa")])
        self.assertEqual([w["text"] for w in words], ["aa", "bbbb", "aa"])
        self.assertEqual(words[0]["start"], 1)
        self.assertAlmostEqual(words[-1]["end"], 3)
        self.assertLess(words[0]["end"], words[1]["start"] + 1e-9)


class TimingReportTests(_CaptionCase):
    def test_zero_duration_words_do_not_shift_timing_ids(self):
        words = [dict(start=0.1, end=0.1, text="zero"), *WORDS]
        *_, plan = self.build("highlight", words)
        report = captions.timing_report(
            captions.parse_script(plan["script"]), words, [i / 30 for i in range(90)]
        )
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(report["words_checked"], 3)

    def test_shifted_word_end_is_reported(self):
        *_, plan = self.build("one_word")
        shifted = plan["script"].replace("0:00:00.90,Word", "0:00:01.10,Word", 1)
        self.assertNotEqual(shifted, plan["script"])
        report = captions.timing_report(
            captions.parse_script(shifted), WORDS, [i / 30 for i in range(90)]
        )
        self.assertEqual(report["status"], "fail", report)

    def test_timing_report_passes_and_detects_a_shifted_event(self):
        *_, plan = self.build("highlight")
        frames = [n / 30 for n in range(90)]
        report = captions.timing_report(
            captions.parse_script(plan["script"]), WORDS, frames
        )
        self.assertEqual(report["status"], "pass", report)
        self.assertLessEqual(report["max_abs_error_seconds"], 1 / 30)
        shifted = plan["script"].replace(
            "Dialogue: 0,0:00:01.00,", "Dialogue: 0,0:00:01.10,", 1
        )
        self.assertNotEqual(shifted, plan["script"])
        report = captions.timing_report(captions.parse_script(shifted), WORDS, frames)
        self.assertEqual(report["status"], "fail", report)


class RenderTests(_CaptionCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "black.mp4"
        black_source(self.source)

    def test_highlight_colour_appears_during_its_word_and_not_before(self):
        settings = {
            "platform": "instagram_reels",
            "caption_style": "highlight",
            "caption_highlight_color": "#FF0000",
            "normalize_audio": False,
        }
        output = self.root / "highlight.mp4"
        result = pp.export_video(
            self.source,
            [{"start": 0, "end": 3}],
            output,
            settings,
            captions=[{"start": 0.5, "end": 2.5, "text": "ONE TWO THREE"}],
            caption_words=WORDS,
            caption_script=self.root / "highlight.ass",
        )
        self.assertEqual(result["caption_style"], "highlight")
        self.assertTrue((self.root / "highlight.ass").is_file())
        layout = result["safe_zone_layout"]
        band = layout["boxes"]["captions"]
        crop = (
            int(layout["safe"]["x0"]),
            int(band["y"]),
            int(layout["safe"]["x1"] - layout["safe"]["x0"]) // 2 * 2,
            int(band["h"]) // 2 * 2,
        )
        frames, width = rgb_frames(output, crop)
        self.assertEqual(len(frames), 90)
        counts = [red_pixels(frame, width) for frame in frames]
        red = [index for index, (count, _, _) in enumerate(counts) if count > 40]
        # Nothing is red before ONE starts; red starts on ONE's first frame.
        self.assertEqual(red[0], 15, counts[13:17])
        self.assertTrue(all(count == 0 for count, _, _ in counts[:15]))
        # TWO's pixels: red region during TWO, absent from it before 1.0 s.
        _, two_mean, two_xs = counts[35]
        _, one_mean, _ = counts[20]
        self.assertGreater(two_mean, one_mean)
        left, right = min(two_xs), max(two_xs)
        for index in range(0, 30):
            inside = [x for x in counts[index][2] if left <= x <= right]
            self.assertEqual(inside, [], f"TWO highlighted early at frame {index}")
        self.assertTrue(
            all(counts[i][0] > 40 and counts[i][1] > one_mean for i in range(30, 42))
        )
        # THREE takes over on its first frame (1.5 s = frame 45).
        _, three_mean, _ = counts[50]
        self.assertGreater(three_mean, two_mean)
        self.assertEqual(counts[44][0], 0, "No highlight in the pause before THREE")
        self.assertGreater(counts[45][1], two_mean + 1)

    def test_caption_only_render_keeps_every_style_inside_the_safe_zone(self):
        words = [
            dict(start=0.05 + i * 0.1, end=0.14 + i * 0.1, text=text)
            for i, text in enumerate(
                "WWWWWWW MMMMMMMM Extraordinary WWWWWWW MMMMMMMM Wondrous".split()
            )
        ]
        cue = [dict(start=0.05, end=0.95, text=" ".join(w["text"] for w in words))]
        for platform in ("instagram_reels", "tiktok", "youtube"):
            for style in ("highlight", "pop", "one_word"):
                output = self.root / f"{platform}-{style}.mp4"
                result = pp.export_video(
                    self.source,
                    [{"start": 0, "end": 1}],
                    output,
                    {
                        "platform": platform,
                        "caption_style": style,
                        "brand": {"safe_margin": 0.02, "subtitle_y": 0.02},
                    },
                    captions=cue,
                    caption_words=words,
                )
                width, height, pixels = gray_frame(
                    output, 0.6, self.root / f"{platform}-{style}.pgm"
                )
                zone = platforms.profile(platform)["safe_zone"]
                x0, y0 = int(width * zone["left"]), int(height * zone["top"])
                x1 = math.ceil(width * (1 - zone["right"]))
                y1 = math.ceil(height * (1 - zone["bottom"]))
                outside = [
                    (x, y)
                    for y in range(height)
                    for x in range(width)
                    if pixels[y * width + x] > 60
                    and not (x0 <= x < x1 and y0 <= y < y1)
                ]
                inside = sum(1 for value in pixels if value > 60)
                with self.subTest(platform=platform, style=style):
                    self.assertEqual(result["caption_style"], style)
                    self.assertGreater(inside, 200, "Captions were drawn")
                    self.assertEqual(outside[:5], [])


class QualityTests(_CaptionCase):
    def test_quality_report_checks_animated_timing_and_bounds(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / "black.mp4"
        black_source(source)
        settings = {"platform": "tiktok", "caption_style": "one_word"}
        cue = [{"start": 0.5, "end": 2.4, "text": "ONE TWO THREE"}]
        output = root / "word.mp4"
        script = root / "word.ass"
        pp.export_video(
            source,
            [{"start": 0, "end": 3}],
            output,
            settings,
            captions=cue,
            caption_words=WORDS,
            caption_script=script,
        )
        for path in (script, None):
            report = pp.quality_report(
                output,
                settings,
                captions=cue,
                caption_words=WORDS,
                caption_script=path,
            )
            checks = {check["name"]: check for check in report["checks"]}
            with self.subTest(script=path):
                self.assertEqual(
                    checks["caption_timing"]["status"], "pass", checks["caption_timing"]
                )
                detail = checks["caption_timing"]["detail"]
                self.assertEqual(detail["words_checked"], 3)
                self.assertLessEqual(detail["max_abs_error_seconds"], 1 / 30 + 1e-6)
                self.assertEqual(checks["caption_bounds"]["status"], "pass")
                self.assertEqual(checks["caption_bounds"]["detail"]["findings"], [])
        tampered = root / "tampered.ass"
        tampered.write_text(
            script.read_text(encoding="utf-8-sig").replace(
                "Dialogue: 0,0:00:01.00,", "Dialogue: 0,0:00:01.20,", 1
            ),
            encoding="utf-8",
        )
        report = pp.quality_report(
            output,
            settings,
            captions=cue,
            caption_words=WORDS,
            caption_script=tampered,
        )
        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["caption_timing"]["status"], "fail")

    def test_classic_reports_have_no_animated_checks(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        source = Path(temporary.name) / "black.mp4"
        black_source(source, duration=1)
        report = pp.quality_report(source, {"platform": "tiktok"})
        names = {check["name"] for check in report["checks"]}
        self.assertNotIn("caption_timing", names)
        self.assertNotIn("caption_bounds", names)


if __name__ == "__main__":
    unittest.main()
