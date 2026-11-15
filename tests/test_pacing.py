"""Pacing: settings, pause shortening, zoom and transition plans, renders and QA."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom import pacing
from cutroom import postproduction as pp
from cutroom.childenv import child_env

FPS = 30


def ffmpeg(*arguments, timeout=120):
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", *arguments],
        check=True,
        capture_output=True,
        env=child_env(python=False),
        timeout=timeout,
    )


def word(identifier, start, end, text="word"):
    return {
        "id": identifier,
        "start": start,
        "end": end,
        "text": text,
        "probability": 0.9,
    }


def program_pauses(segments, words):
    """Pauses between consecutive kept words on the program timeline."""
    from cutroom.speech import remap_words

    spans, last = [], None
    for item in remap_words(words, segments):
        if spans and item["source_id"] == last:
            spans[-1][1] = item["end"]
        else:
            spans.append([item["start"], item["end"]])
            last = item["source_id"]
    return [b[0] - a[1] for a, b in zip(spans, spans[1:])]


class SettingsTests(unittest.TestCase):
    def test_defaults_and_limits(self):
        self.assertIsNone(pacing.validate_settings(None))
        value = pacing.validate_settings({})
        self.assertEqual(
            value,
            {
                "punch_in": "off",
                "punch_in_zoom": 1.12,
                "max_upscale": 2.0,
                "push_in": False,
                "push_in_zoom": 1.06,
                "max_pause": None,
                "transition": "cut",
                "transition_duration": 0.2,
            },
        )
        self.assertFalse(pacing.video_active(value))
        self.assertTrue(pacing.video_active({**value, "punch_in": "alternate"}))
        self.assertTrue(pacing.video_active({**value, "transition": "dip"}))
        self.assertTrue(pacing.video_active({**value, "push_in": True}))
        self.assertFalse(pacing.video_active({**value, "max_pause": 0.5}))
        for bad in (
            [],
            {"zoom": 1.1},
            {"punch_in": "on"},
            {"punch_in_zoom": 1.31},
            {"punch_in_zoom": 1.04},
            {"punch_in_zoom": True},
            {"max_upscale": 0.9},
            {"push_in": "yes"},
            {"push_in_zoom": 1.2},
            {"max_pause": 0.1},
            {"max_pause": 2.5},
            {"max_pause": float("nan")},
            {"transition": "wipe"},
            {"transition_duration": 0.6},
            {"transition_duration": 0.0},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pacing.validate_settings(bad)

    def test_transition_frames_are_two_to_twelve(self):
        self.assertEqual(pacing.transition_frames(0.2, 30000 / 1001), 6)
        self.assertEqual(pacing.transition_frames(0.04, 24), 2)
        self.assertEqual(pacing.transition_frames(0.5, 60), 12)
        self.assertEqual(pacing.transition_frames(0.05, 30), 2)


class PauseTests(unittest.TestCase):
    def test_long_pause_inside_a_segment_is_shortened_around_its_middle(self):
        words = [word(0, 0.5, 1.0), word(1, 3.0, 3.5), word(2, 3.7, 4.0)]
        segments = [{"start": 0.0, "end": 5.0}]
        result = pacing.shorten_pauses(segments, words, 0.6)
        self.assertEqual(
            result, [{"start": 0.0, "end": 1.3}, {"start": 2.7, "end": 5.0}]
        )
        pauses = program_pauses(result, words)
        self.assertAlmostEqual(pauses[0], 0.6, places=6)
        self.assertAlmostEqual(pauses[1], 0.2, places=6, msg="short pause kept")
        # Leading and trailing silence are not between words and stay.
        self.assertEqual(result[0]["start"], 0.0)
        self.assertEqual(result[-1]["end"], 5.0)

    def test_pause_across_an_existing_cut_counts_program_time(self):
        # Kept tail of the first range (0.8 s) plus head of the second (0.9 s).
        words = [word(0, 0.2, 1.0), word(1, 6.0, 6.5)]
        segments = [{"start": 0.0, "end": 1.8}, {"start": 5.1, "end": 7.0}]
        result = pacing.shorten_pauses(segments, words, 0.5)
        pauses = program_pauses(result, words)
        self.assertAlmostEqual(pauses[0], 0.5, places=6)
        self.assertEqual(result[0], {"start": 0.0, "end": 1.25})
        self.assertEqual(result[1], {"start": 5.75, "end": 7.0})

    def test_excluded_words_are_not_pause_anchors_and_short_pauses_stay(self):
        # Word 1 is excluded: its removal already cut the source between 1.0 and 2.0.
        words = [word(0, 0.0, 1.0), word(2, 2.1, 2.5), word(3, 2.8, 3.0)]
        segments = [{"start": 0.0, "end": 1.04}, {"start": 2.06, "end": 3.0}]
        self.assertEqual(pacing.shorten_pauses(segments, words, 0.5), segments)
        self.assertEqual(pacing.shorten_pauses(segments, words, None), segments)

    def test_many_pauses_never_exceed_the_limit(self):
        words, time = [], 0.0
        for index in range(40):
            words.append(word(index, time, time + 0.3))
            time += 0.3 + (0.1 if index % 3 else 1.7)
        segments = [{"start": 0.0, "end": time}]
        result = pacing.shorten_pauses(segments, words, 0.4)
        self.assertEqual(len(result), 14)
        for pause in program_pauses(result, words):
            self.assertLessEqual(pause, 0.4 + 1e-6)
        for a, b in zip(result, result[1:]):
            self.assertLess(a["start"], a["end"])
            self.assertLessEqual(a["end"], b["start"])


def zoom_plan(**extra):
    settings = pacing.validate_settings(
        {"punch_in": "alternate", **extra.pop("settings", {})}
    )
    arguments = dict(
        counts=[60, 60, 60],
        firsts=[0, 90, 180],
        fps=30.0,
        last_frame=300,
        window=(608, 1080),
        base_upscale=1080 / 608,
        output_box=[0, 0, 1, 1],
        zone={"left": 0.06, "right": 0.06, "top": 0.14, "bottom": 0.35},
    )
    arguments.update(extra)
    return pacing.plan(settings, **arguments)


class PlanTests(unittest.TestCase):
    def test_punch_ins_alternate_on_edit_cuts_and_stay_under_the_limit(self):
        report = zoom_plan()
        zooms = [r["zoom"] for r in report["ranges"]]
        self.assertEqual(zooms[0], [1.0, 1.0])
        self.assertEqual(zooms[2], [1.0, 1.0])
        self.assertGreater(zooms[1][0], 1.1)
        self.assertEqual(report["cuts"], [60, 120])
        for item in report["ranges"]:
            self.assertLessEqual(item["upscale"], 2.0 + 1e-9)
        window = report["ranges"][1]["window"]
        self.assertTrue(all(value % 2 == 0 for value in window), window)
        # Centred on the window centre without faces.
        ox, oy, zw, zh = window
        self.assertAlmostEqual(ox + zw / 2, 304, delta=2)
        self.assertAlmostEqual(oy + zh / 2, 540, delta=2)

    def test_zoom_is_reduced_to_the_upscale_limit_and_reported(self):
        report = zoom_plan(base_upscale=1.9)
        item = report["ranges"][1]
        self.assertTrue(item["reduced"])
        self.assertLessEqual(item["upscale"], 2.0 + 1e-9)
        self.assertGreater(item["zoom"][0], 1.02)
        self.assertTrue(any("reduced" in w for w in report["warnings"]))
        skipped = zoom_plan(base_upscale=1.99)
        self.assertEqual(skipped["ranges"][1]["zoom"], [1.0, 1.0])
        self.assertTrue(any("skipped" in w for w in skipped["warnings"]))

    def test_punch_in_is_anchored_on_the_face(self):
        faces = [[index, 150.0, 400.0] for index in range(60, 120)]
        report = zoom_plan(faces=faces)
        item = report["ranges"][1]
        self.assertAlmostEqual(item["anchor"][0], 150, delta=0.5)
        ox, oy, zw, zh = item["window"]
        # The face keeps (within rounding) its place in the frame.
        self.assertAlmostEqual((150 - ox) / zw, 150 / 608, delta=0.005)
        self.assertAlmostEqual((400 - oy) / zh, 400 / 1080, delta=0.005)
        self.assertEqual(len(report["face_frames"]), 60)

    def test_push_in_only_on_long_ranges(self):
        report = zoom_plan(
            settings={"punch_in": "off", "push_in": True},
            counts=[150, 60],
            firsts=[0, 200],
        )
        self.assertEqual(report["ranges"][0]["zoom"], [1.0, 1.06])
        self.assertIsNone(report["ranges"][0]["window"])
        self.assertEqual(report["ranges"][1]["zoom"], [1.0, 1.0])
        self.assertLessEqual(report["ranges"][0]["upscale"], 2.0 + 1e-9)
        self.assertAlmostEqual(pacing.zoom_at(report["ranges"][0], 0), 1.0)
        self.assertAlmostEqual(pacing.zoom_at(report["ranges"][0], 149), 1.06)
        middle = pacing.zoom_at(report["ranges"][0], 75)
        self.assertTrue(1.02 < middle < 1.04, middle)

    def test_transitions_are_centred_on_each_cut_with_handles(self):
        report = zoom_plan(settings={"punch_in": "off", "transition": "crossfade"})
        self.assertEqual(report["transition_frames"], 6)
        self.assertEqual(
            report["transitions"],
            [
                {"frame": 60, "frames": 6, "before": 3, "after": 3},
                {"frame": 120, "frames": 6, "before": 3, "after": 3},
            ],
        )
        # A four-frame range cannot give three frames to both of its cuts.
        short = zoom_plan(
            settings={"punch_in": "off", "transition": "dip"},
            counts=[60, 4, 60],
            firsts=[0, 90, 120],
        )
        self.assertEqual(
            short["transitions"],
            [
                {"frame": 60, "frames": 6, "before": 4, "after": 2},
                {"frame": 64, "frames": 6, "before": 2, "after": 4},
            ],
        )


class QualityTests(unittest.TestCase):
    def run_checks(self, report, settings, words=None):
        checks = []

        def add(name, status, detail):
            checks.append({"name": name, "status": status, "detail": detail})

        pacing.quality_checks(add, report, settings, words)
        return {check["name"]: check for check in checks}

    def test_checks_pass_on_a_valid_plan_and_fail_on_broken_ones(self):
        settings = pacing.validate_settings(
            {"punch_in": "alternate", "transition": "crossfade"}
        )
        faces = [[index, 304.0, 450.0] for index in range(0, 180, 5)]
        report = zoom_plan(settings=settings, faces=faces)
        checks = self.run_checks(report, settings)
        for name in ("pacing_upscale", "pacing_face", "pacing_transitions"):
            self.assertEqual(checks[name]["status"], "pass", checks[name])
        self.assertNotIn("pacing_max_pause", checks)
        broken = json.loads(json.dumps(report))
        broken["ranges"][1]["window"] = [200, 360, 300, 540]
        checks = self.run_checks(broken, settings)
        self.assertEqual(checks["pacing_upscale"]["status"], "fail")
        broken = json.loads(json.dumps(report))
        broken["face_frames"] = [[index, 20.0, 450.0] for index in range(60, 120)]
        self.assertEqual(
            self.run_checks(broken, settings)["pacing_face"]["status"], "fail"
        )
        broken = json.loads(json.dumps(report))
        broken["transitions"].pop()
        self.assertEqual(
            self.run_checks(broken, settings)["pacing_transitions"]["status"], "fail"
        )

    def test_max_pause_is_measured_on_the_rendered_ranges(self):
        settings = pacing.validate_settings({"max_pause": 0.5})
        report = zoom_plan(settings=settings)
        report["source_ranges"] = [[0.0, 1.3], [2.7, 5.0]]
        words = [[0.5, 1.0], [3.0, 3.5]]
        check = self.run_checks(report, settings, words)["pacing_max_pause"]
        self.assertEqual(check["status"], "fail", check)
        self.assertAlmostEqual(check["detail"]["longest_pause_s"], 0.6, places=6)
        report["source_ranges"] = [[0.0, 1.25], [2.75, 5.0]]
        check = self.run_checks(report, settings, words)["pacing_max_pause"]
        self.assertEqual(check["status"], "pass", check)

    def test_report_validation_is_bounded(self):
        report = zoom_plan()
        pacing.validate_report(report)
        for key, value in (
            ("ranges", "x"),
            ("fps", 0),
            ("max_upscale", float("inf")),
            ("face_frames", [[0, 1]]),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                pacing.validate_report({**report, key: value})


def ramp_source(path, duration=4, audio=True):
    """640x360 source: luma encodes the column, and the top band encodes time."""
    arguments = [
        "-f",
        "lavfi",
        "-i",
        f"color=black:size=640x360:rate={FPS}:duration={duration},format=gray,"
        "geq=lum='if(lt(Y,40),16+N*219/119,16+X*219/639)',format=yuv420p",
    ]
    if audio:
        arguments += [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={duration}",
            "-c:a",
            "aac",
        ]
    ffmpeg(
        *arguments,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-qp",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-shortest",
        str(path),
    )


def gray_frames(path, width, height):
    data = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=120,
    ).stdout
    size = width * height
    return [data[i : i + size] for i in range(0, len(data), size)]


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.source = cls.root / "ramp.mp4"
        ramp_source(cls.source)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def render(self, name, settings, segments=None):
        output = self.root / name
        result = pp.export_video(
            self.source,
            segments or [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 3.0}],
            output,
            {"preset": "preview", "timeout": 300, "normalize_audio": False, **settings},
        )
        return output, result

    def columns(self, frame, width, row):
        """Source column seen at the left and right edges of one output row."""
        line = frame[row * width : (row + 1) * width]
        return [(value - 16) * 639 / 219 for value in (line[2], line[-3])]

    def test_center_crop_punch_in_zooms_the_second_range_only(self):
        output, result = self.render(
            "punch.mp4",
            {
                "aspect": "square",
                "framing": "center_crop",
                "pacing": {
                    "punch_in": "alternate",
                    "punch_in_zoom": 1.2,
                    "max_upscale": 4.0,
                },
            },
        )
        info = pp._probe(output)
        width, height = info["width"], info["height"]
        frames = gray_frames(output, width, height)
        self.assertEqual(len(frames), 60)
        report = result["pacing"]
        self.assertEqual(report["cuts"], [30])
        normal = self.columns(frames[10], width, height // 2)
        zoomed = self.columns(frames[45], width, height // 2)
        span_normal = normal[1] - normal[0]
        span_zoomed = zoomed[1] - zoomed[0]
        self.assertAlmostEqual(span_normal / span_zoomed, 1.2, delta=0.04)
        # Centred: the middle column is the same in both ranges.
        self.assertAlmostEqual(sum(normal) / 2, sum(zoomed) / 2, delta=6)
        self.assertLessEqual(max(r["upscale"] for r in report["ranges"]), 4.0)

    def test_crossfade_and_dip_keep_frames_length_and_sync_points(self):
        plain, _ = self.render("plain.mp4", {})
        cross, result = self.render(
            "cross.mp4", {"pacing": {"transition": "crossfade"}}
        )
        dip, _ = self.render("dip.mp4", {"pacing": {"transition": "dip"}})
        info = pp._probe(plain)
        width, height = info["width"], info["height"]
        plain_frames = gray_frames(plain, width, height)
        cross_frames = gray_frames(cross, width, height)
        dip_frames = gray_frames(dip, width, height)
        self.assertEqual(len(plain_frames), len(cross_frames), len(dip_frames))
        self.assertEqual(len(plain_frames), 60)

        def clock(frame):
            return frame[5 * width + width // 2]

        # Away from the cut every frame is the same source frame as without a transition.
        for index in list(range(0, 26)) + list(range(34, 60)):
            self.assertLessEqual(
                abs(clock(cross_frames[index]) - clock(plain_frames[index])), 3, index
            )
        # At the cut the crossfade blends both sides; the dip goes through black.
        a, b = clock(plain_frames[29]), clock(plain_frames[30])
        middle = clock(cross_frames[30])
        self.assertTrue(min(a, b) + 10 < middle < max(a, b) - 10, (a, middle, b))
        self.assertLess(min(clock(dip_frames[i]) for i in range(28, 32)), 40)
        self.assertEqual(
            result["pacing"]["transitions"],
            [{"frame": 30, "frames": 6, "before": 3, "after": 3}],
        )
        for path in (cross, dip):
            streams = json.loads(
                subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "stream=codec_type,duration",
                        "-of",
                        "json",
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=60,
                ).stdout
            )["streams"]
            durations = {s["codec_type"]: float(s["duration"]) for s in streams}
            self.assertAlmostEqual(durations["video"], 2.0, delta=0.001)
            self.assertLessEqual(abs(durations["audio"] - durations["video"]), 0.001)

    def test_variable_rate_sources_are_refused_for_video_pacing(self):
        original = pp._probe(self.source)
        for stream in original["streams"]:
            if stream.get("codec_type") == "video":
                stream["avg_frame_rate"] = "2997/100"
        with patch.object(pp, "_probe", return_value=original):
            with self.assertRaisesRegex(ValueError, "constant-rate"):
                self.render("vfr.mp4", {"pacing": {"punch_in": "alternate"}})

    def test_push_in_eases_in_fit_and_blur_fill_and_in_a_crop(self):
        for name, settings in (
            ("push-fit.mp4", {"aspect": "square"}),
            ("push-blur.mp4", {"aspect": "square", "framing": "blur_fill"}),
            ("push-crop.mp4", {"aspect": "square", "framing": "center_crop"}),
        ):
            with self.subTest(name):
                pacing_settings = {
                    "push_in": True,
                    "push_in_zoom": 1.15,
                    "max_upscale": 4.0,
                }
                output, result = self.render(
                    name,
                    {**settings, "pacing": pacing_settings},
                    [{"start": 0.0, "end": 4.0}],
                )
                item = result["pacing"]["ranges"][0]
                self.assertEqual(item["zoom"], [1.0, 1.15])
                info = pp._probe(output)
                width, height = info["width"], info["height"]
                frames = gray_frames(output, width, height)
                self.assertEqual(len(frames), 120)
                # The middle row is picture in every mode (fit keeps a centre band).
                row = height // 2
                first = self.columns(frames[0], width, row)
                last = self.columns(frames[-1], width, row)
                middle = self.columns(frames[60], width, row)
                ratio = (first[1] - first[0]) / (last[1] - last[0])
                self.assertAlmostEqual(ratio, 1.15, delta=0.04)
                halfway = (first[1] - first[0]) / (middle[1] - middle[0])
                self.assertTrue(1.05 < halfway < 1.1, halfway)
                self.assertAlmostEqual(sum(first) / 2, sum(last) / 2, delta=8)

    def test_caption_ending_with_the_edit_is_valid_within_one_frame(self):
        # Frame alignment can end the video up to half a frame before the edit.
        output, _ = self.render(
            "short.mp4", {}, [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 2.98}]
        )
        duration = pp._probe(output)["duration"]
        for end, status in ((duration + 0.02, "pass"), (duration + 0.2, "fail")):
            report = pp.quality_report(
                output,
                {"timeout": 300},
                captions=[{"start": 0.5, "end": end, "text": "Hello there"}],
            )
            check = next(c for c in report["checks"] if c["name"] == "captions")
            self.assertEqual(check["status"], status, check)

    def test_no_pacing_keeps_the_existing_graph(self):
        _, result = self.render("legacy.mp4", {})
        self.assertNotIn("pacing", result)


if __name__ == "__main__":
    unittest.main()
