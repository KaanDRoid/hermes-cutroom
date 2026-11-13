"""Reframing review fixes: stale samples at cuts, pins, SAR, coverage, QA, timelines."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_reframe import FPS, ffmpeg, plan, samples, steps

from cutroom import postproduction as pp
from cutroom import reframe
from cutroom.childenv import child_env

CENTRE = (1920 - 608) / 2


def collect(report, frames=None):
    checks = {}

    def add(name, status, detail):
        checks[name] = {"status": status, "detail": detail}

    reframe.quality_checks(add, report, report["frames"] if frames is None else frames)
    return checks


def gray(video, crop="crop=8:8:(iw-8)/2:(ih-8)/2"):
    """Mean luma of a small patch (default: the centre) of every decoded frame."""
    raw = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            f"{crop},scale=1:1:flags=area,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        env=child_env(python=False),
        timeout=120,
    ).stdout
    return list(raw)


class ScenecutLookAheadTests(unittest.TestCase):
    def test_cut_between_samples_uses_the_first_sample_of_the_new_shot(self):
        # Vision frame step 5: samples at frames 0, 5, ..., 50, 55, ...; cut at 52.
        faces = samples(4, lambda t: 0.25 if t < 52 / FPS else 0.75, step=5 / FPS)
        result = plan(faces, scene_cuts=[52 / FPS])
        self.assertIn(52, result["resets"])
        self.assertAlmostEqual(result["x"][51] + 304, 0.25 * 1920, delta=2)
        self.assertAlmostEqual(result["x"][52] + 304, 0.75 * 1920, delta=2)
        # No sample in the new shot yet: hold the centre, never the old shot.
        sparse = [s for s in faces if not 52 / FPS <= s[0] < 70 / FPS]
        held = plan(sparse, scene_cuts=[52 / FPS])
        self.assertAlmostEqual(held["x"][52] + 304, 0.75 * 1920, delta=2)
        empty = [[t, [] if 52 / FPS <= t < 70 / FPS else f] for t, f in faces]
        centred = plan(empty, scene_cuts=[52 / FPS])
        self.assertAlmostEqual(centred["x"][52], CENTRE, delta=1)
        self.assertAlmostEqual(centred["x"][60], CENTRE, delta=1)

    def test_edit_range_start_never_uses_a_sample_from_removed_content(self):
        timestamps = [i / 30 for i in range(120)]
        info = {
            "width": 1920,
            "height": 1080,
            "display_aspect_ratio": 16 / 9,
            "streams": [
                {
                    "codec_type": "video",
                    "r_frame_rate": "30/1",
                    "avg_frame_rate": "30/1",
                    "start_time": "0.000000",
                }
            ],
        }
        probe = json.dumps(
            {"frames": [{"best_effort_timestamp_time": f"{t:.6f}"} for t in timestamps]}
        )
        # Face at 0.25 until 2.03 s (removed content from 1.0 s), then 0.75.
        faces = samples(4, lambda t: 0.25 if t < 2.03 else 0.75, step=5 / FPS)
        settings = {
            "framing": "face_track",
            "framing_analysis": {"faces": faces, "scene_cuts": []},
            "platform": "instagram_reels",
            "brand": {"safe_margin": 0.05},
            "timeout": 60,
        }
        ranges = [(0.0, 31 / 30 - 1 / 60), (62 / 30 - 1 / 60, 4.0)]
        with patch.object(pp, "_run", return_value=SimpleNamespace(stdout=probe)):
            report = reframe.prepare_path(
                Path("x.mp4"), info, ranges, settings, 1080, 1920
            )
        boundary = report["resets"][1]
        self.assertEqual(boundary, 31)
        self.assertAlmostEqual(report["x"][boundary] + 304, 0.75 * 1920, delta=2)


class PinTests(unittest.TestCase):
    limit = reframe.TRACKING["max_speed"] * 608 / FPS

    def assert_limits(self, values, resets=(0,)):
        self.assertLessEqual(max(steps(values, resets)), self.limit + 1e-5)
        velocity = [b - a for a, b in zip(values, values[1:])]
        accel = [
            abs(b - a)
            for i, (a, b) in enumerate(zip(velocity, velocity[1:]), 2)
            if i not in resets and i - 1 not in resets
        ]
        self.assertLessEqual(
            max(accel), reframe.TRACKING["max_acceleration"] * 608 / FPS / FPS + 1e-4
        )

    def test_tracker_is_used_before_the_first_pin(self):
        moving = samples(6, lambda t: 0.2 + 0.1 * t)
        free = plan(moving, duration=6)
        pinned = plan(moving, duration=6, keyframes=[{"time": 5.0, "x": 0.5}])
        self.assertAlmostEqual(pinned["x"][0], free["x"][0], delta=1)
        self.assertAlmostEqual(pinned["x"][30], free["x"][30], delta=1)
        self.assertAlmostEqual(pinned["x"][150] + 304, 0.5 * 1920, delta=2)
        self.assert_limits(pinned["x"])

    def test_tracker_resumes_after_the_last_pin(self):
        moving = samples(6, lambda t: 0.2 + 0.1 * t)
        free = plan(moving, duration=6)
        pinned = plan(moving, duration=6, keyframes=[{"time": 0.0, "x": 0.2}])
        self.assertAlmostEqual(pinned["x"][-1], free["x"][-1], delta=1)
        self.assert_limits(pinned["x"])

    def test_a_single_feasible_pin_at_five_seconds_is_accepted(self):
        static = samples(6, lambda t: 0.8)
        pinned = plan(static, duration=6, keyframes=[{"time": 5.0, "x": 0.3}])
        self.assertAlmostEqual(pinned["x"][150] + 304, 0.3 * 1920, delta=2)
        self.assertAlmostEqual(pinned["x"][0] + 304, 0.8 * 1920, delta=2)
        self.assert_limits(pinned["x"])

    def test_pins_spanning_an_edit_cut_are_accepted(self):
        keys = [{"time": 0.0, "x": 0.2}, {"time": 6.0, "x": 0.8}]
        result = plan(mode="center_crop", keyframes=keys, duration=6, edit_resets=[90])
        self.assertIn(90, result["resets"])
        self.assert_limits(result["x"], resets=())
        tracked = plan(
            samples(6, lambda t: 0.5),
            duration=6,
            keyframes=keys,
            edit_resets=[90],
            scene_cuts=[4.0],
        )
        self.assertAlmostEqual(tracked["x"][90], result["x"][90], delta=1)

    def test_a_real_jump_across_a_cut_is_still_allowed(self):
        result = plan(
            samples(4, lambda t: 0.25 if t < 2 else 0.75),
            keyframes=[{"time": 3.5, "x": 0.75}],
            scene_cuts=[2.0],
        )
        self.assertAlmostEqual(result["x"][59] + 304, 0.25 * 1920, delta=2)


class CoverageTests(unittest.TestCase):
    def test_low_face_coverage_is_reported_and_warned(self):
        result = plan(samples(4, lambda t: 0.3 if t < 1 else None))
        coverage = result["face_coverage"]
        self.assertLess(coverage["fraction"], 0.5)
        self.assertEqual(
            coverage["fresh_frames"]
            + coverage["stale_frames"]
            + coverage["uncovered_frames"],
            result["frames"],
        )
        self.assertTrue(any("face" in w for w in result["warnings"]))
        checks = collect(result)
        self.assertEqual(checks["framing_face_coverage"]["status"], "warning")

    def test_face_track_without_faces_warns_instead_of_skipping(self):
        result = plan(samples(4, lambda t: None))
        checks = collect(result)
        self.assertEqual(checks["framing_face_safe_zone"]["status"], "warning")
        self.assertEqual(checks["framing_face_coverage"]["status"], "warning")
        self.assertEqual(result["face_coverage"]["fraction"], 0)

    def test_good_coverage_passes(self):
        result = plan(samples(4, lambda t: 0.3, step=5 / FPS))
        self.assertEqual(result["face_coverage"]["fraction"], 1)
        self.assertEqual(collect(result)["framing_face_coverage"]["status"], "pass")

    def test_safe_zone_counts_only_fresh_samples(self):
        # 12 samples at frame step 5 cover 0-2 s of a 30 s program.
        faces = samples(2, lambda t: 0.3, step=1 / 6)
        result = plan(faces, duration=30)
        fresh = result["face_coverage"]["fresh_frames"]
        self.assertLessEqual(fresh, 2 * FPS + 7)
        self.assertGreaterEqual(fresh, 2 * FPS)
        self.assertEqual(len(result["face_frames"]), fresh)
        detail = collect(result)["framing_face_safe_zone"]["detail"]
        self.assertEqual(detail["sampled_face_frames"], fresh)
        self.assertGreater(detail["stale_frames"], 800)
        self.assertIn("uncovered_frames", detail)


class UpscaleQaTests(unittest.TestCase):
    def test_framing_upscale_warns_without_a_platform_profile(self):
        result = plan(mode="center_crop")
        checks = collect(result)
        self.assertEqual(checks["framing_upscale"]["status"], "warning")
        self.assertAlmostEqual(
            checks["framing_upscale"]["detail"]["factor"], max(1080 / 608, 1920 / 1080)
        )
        small = reframe.plan_path(
            mode="center_crop",
            source_size=(3840, 2160),
            crop_size=(1216, 2160),
            frame_size=(1080, 1920),
            frames=[0, 1 / FPS],
            fps=FPS,
        )
        self.assertEqual(collect(small)["framing_upscale"]["status"], "pass")


class ExpressionCapTests(unittest.TestCase):
    def test_piece_cap_error_names_the_limit(self):
        values = [float(i % 2) * 10 for i in range(20500)]
        with self.assertRaisesRegex(ValueError, r"20000.*split") as caught:
            reframe.path_expression(values)
        self.assertIn("20500", str(caught.exception))
        self.assertEqual(reframe.MAX_PIECES, 20000)


class GeometryReviewTests(unittest.TestCase):
    def test_odd_sources_get_even_crops(self):
        width, height = reframe.crop_size(641, 361, 1080, 1920)
        self.assertEqual((width % 2, height % 2), (0, 0))
        width, height = reframe.crop_size(641, 361, 1920, 1080)
        self.assertEqual((width % 2, height % 2), (0, 0))

    def test_source_grid_is_reported_in_display_pixels(self):
        info = {
            "width": 480,
            "height": 360,
            "display_aspect_ratio": 16 / 9,
            "streams": [{"codec_type": "video", "sample_aspect_ratio": "4:3"}],
        }
        source = pp._source_video(info)
        self.assertEqual((source["width"], source["height"]), (640, 360))


class AnamorphicRenderTests(unittest.TestCase):
    def test_sar_four_thirds_crops_in_display_pixels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "anamorphic.mp4"
            # Storage 480x360 with SAR 4:3 displays as 640x360; luma encodes storage x.
            ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "color=black:size=480x360:rate=30:duration=1,"
                "format=gray,geq=lum='16+X*219/479',format=yuv420p,setsar=4/3",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-qp",
                "0",
                str(source),
            )
            output = root / "out.mp4"
            result = pp.export_video(
                source,
                [{"start": 0.0, "end": 1.0}],
                output,
                settings={
                    "preset": "preview",
                    "aspect": "portrait",
                    "framing": "center_crop",
                },
            )
            report = result["framing"]
            self.assertEqual(report["source"], [640, 360])
            self.assertEqual(report["crop"], [202, 360])
            self.assertAlmostEqual(
                result["upscale_factor"], max(1080 / 202, 1920 / 360)
            )
            # Display columns 219..420 are storage columns 164..315; decoded as
            # full-range gray, storage column c reads c * 255 / 479.
            left = gray(output, "crop=8:ih:0:0")
            right = gray(output, "crop=8:ih:iw-8:0")
            self.assertAlmostEqual(left[0], 165 * 255 / 479, delta=3)
            self.assertAlmostEqual(right[0], 315 * 255 / 479, delta=3)


class StartTimeTests(unittest.TestCase):
    def test_start_time_offset_keeps_trim_edges_and_frame_plan_on_one_timeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "offset.mp4"
            # Luma encodes the source frame number; the stream starts at 1.3 s.
            ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "color=black:size=320x180:rate=24000/1001:duration=5,"
                "format=gray,geq=lum='16+N*1.5',format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-qp",
                "0",
                "-output_ts_offset",
                "1.3",
                str(source),
            )
            info = pp._probe(source)
            self.assertAlmostEqual(
                float(info["streams"][0]["start_time"]), 1.3, delta=0.01
            )
            segments = [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 3.0}]
            for mode in ("fit", "center_crop"):
                output = root / f"{mode}.mp4"
                result = pp.export_video(
                    source,
                    segments,
                    output,
                    settings={
                        "preset": "preview",
                        "aspect": "portrait",
                        "framing": mode,
                    },
                )
                values = gray(output)
                frames = [round((v - 16) / 1.5) for v in values]
                self.assertEqual(frames[0], 0, mode)
                self.assertEqual(frames[24], 48, mode)
                if mode == "center_crop":
                    self.assertEqual(result["framing"]["frames"], len(values))
                    self.assertEqual(result["framing"]["resets"], [0, 24])


if __name__ == "__main__":
    unittest.main()
