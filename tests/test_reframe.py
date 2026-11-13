"""Reframing: settings validation, crop geometry, smoothed paths, FFmpeg renders and QA."""

import json
import math
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom import postproduction as pp
from cutroom import reframe
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


def face(cx, cy=0.4, size=0.2, mouth=None, eye=None):
    """Compact face sample entry: centre, size, eye line and mouth opening."""
    return [cx, cy, size, size, cy - size * 0.15 if eye is None else eye, mouth]


def samples(duration, position, step=1 / FPS, faces_at=None):
    """Face samples every `step` seconds; `position(t)` gives the face centre x."""
    result, count = [], int(round(duration / step))
    for index in range(count):
        time = round(index * step, 6)
        if faces_at is not None:
            result.append([time, faces_at(time)])
            continue
        x = position(time)
        result.append([time, [] if x is None else [face(x)]])
    return result


def plan(faces=(), duration=4.0, mode="face_track", **extra):
    frames = [index / FPS for index in range(int(round(duration * FPS)))]
    return reframe.plan_path(
        mode=mode,
        source_size=(1920, 1080),
        crop_size=(608, 1080),
        frame_size=(1080, 1920),
        frames=frames,
        fps=FPS,
        faces=faces,
        **extra,
    )


def steps(values, resets=()):
    resets = set(resets)
    return [
        abs(b - a)
        for index, (a, b) in enumerate(zip(values, values[1:]), start=1)
        if index not in resets
    ]


class ValidationTests(unittest.TestCase):
    def test_framing_modes(self):
        for mode in ("fit", "blur_fill", "center_crop", "face_track"):
            self.assertEqual(reframe.validate_framing(mode), mode)
        for bad in ("crop", None, 1, "", "FIT"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                reframe.validate_framing(bad)

    def test_keyframes_are_strictly_validated(self):
        valid = reframe.validate_keyframes(
            [{"time": 0, "x": 0.25}, {"time": 1.5, "x": 1, "y": 0.4}], duration=4
        )
        self.assertEqual(
            valid, [{"time": 0.0, "x": 0.25}, {"time": 1.5, "x": 1.0, "y": 0.4}]
        )
        self.assertEqual(reframe.validate_keyframes([], duration=4), [])
        too_many = [{"time": i * 0.01, "x": 0.5} for i in range(101)]
        for bad in (
            None,
            {"time": 0, "x": 0.5},
            [{"time": 0}],
            [{"x": 0.5}],
            [{"time": 0, "x": 0.5, "z": 1}],
            [{"time": True, "x": 0.5}],
            [{"time": 0, "x": "0.5"}],
            [{"time": float("nan"), "x": 0.5}],
            [{"time": 0, "x": float("inf")}],
            [{"time": -0.1, "x": 0.5}],
            [{"time": 4.1, "x": 0.5}],
            [{"time": 0, "x": 1.01}],
            [{"time": 0, "x": -0.01}],
            [{"time": 0, "x": 0.5, "y": 2}],
            [{"time": 1, "x": 0.5}, {"time": 0.5, "x": 0.5}],
            [{"time": 1, "x": 0.5}, {"time": 1, "x": 0.6}],
            ["0,0.5"],
            too_many,
        ):
            with self.subTest(bad=str(bad)[:60]), self.assertRaises(ValueError):
                reframe.validate_keyframes(bad, duration=4)


class GeometryTests(unittest.TestCase):
    def test_landscape_to_vertical_crop_is_an_upscale(self):
        self.assertEqual(reframe.crop_size(1920, 1080, 1080, 1920), (608, 1080))
        content, factor = reframe.content_upscale(
            {"width": 1920, "height": 1080, "display_aspect_ratio": 16 / 9},
            1080,
            1920,
            "face_track",
        )
        self.assertEqual(content, [1080, 1920])
        self.assertAlmostEqual(factor, max(1080 / 608, 1920 / 1080))

    def test_vertical_to_landscape_crop_keeps_the_full_width(self):
        width, height = reframe.crop_size(2160, 3840, 1920, 1080)
        self.assertEqual(width, 2160)
        self.assertEqual(height % 2, 0)
        self.assertLess(abs(height * 16 / 9 - 2160), 4)
        _, factor = reframe.content_upscale(
            {"width": 2160, "height": 3840, "display_aspect_ratio": 0.5625},
            1920,
            1080,
            "center_crop",
        )
        self.assertLess(factor, 1)

    def test_fit_and_blur_fill_report_the_fitted_picture(self):
        source = {"width": 1920, "height": 1080, "display_aspect_ratio": 16 / 9}
        for mode in ("fit", "blur_fill"):
            content, factor = reframe.content_upscale(source, 1080, 1920, mode)
            self.assertEqual(content, [1080, 606])
            self.assertLess(factor, 1)


class PathTests(unittest.TestCase):
    limit = None

    def setUp(self):
        self.limit = reframe.TRACKING["max_speed"] * 608 / FPS

    def test_static_face_sits_in_the_safe_area_and_never_moves(self):
        result = plan(samples(4, lambda t: 0.3))
        self.assertEqual(max(steps(result["x"])), 0)
        crop_left = result["x"][0]
        self.assertAlmostEqual(crop_left + 304, 0.3 * 1920, delta=1)

    def test_small_offsets_inside_the_dead_zone_do_not_move_the_crop(self):
        jitter = 0.5 * reframe.TRACKING["dead_zone"] * 608 / 1920
        result = plan(samples(4, lambda t: 0.5 + jitter * math.sin(t * 9)))
        self.assertLess(max(steps(result["x"])), 0.5)

    def test_large_moves_respect_speed_and_acceleration_limits(self):
        result = plan(samples(6, lambda t: 0.25 if t < 1 else 0.75), duration=6)
        movement = steps(result["x"])
        self.assertLessEqual(max(movement), self.limit + 1e-6)
        self.assertEqual(result["max_step"][0], self.limit)
        velocity = [b - a for a, b in zip(result["x"], result["x"][1:])]
        acceleration = [abs(b - a) for a, b in zip(velocity, velocity[1:])]
        self.assertLessEqual(
            max(acceleration),
            reframe.TRACKING["max_acceleration"] * 608 / FPS / FPS + 1e-6,
        )
        self.assertAlmostEqual(result["x"][-1] + 304, 0.75 * 1920, delta=25)

    def test_scene_cuts_and_edit_cuts_reset_the_path(self):
        result = plan(samples(4, lambda t: 0.25 if t < 2 else 0.75), scene_cuts=[2.0])
        index = 60
        self.assertIn(index, result["resets"])
        self.assertAlmostEqual(result["x"][index - 1] + 304, 0.25 * 1920, delta=2)
        self.assertAlmostEqual(result["x"][index] + 304, 0.75 * 1920, delta=2)
        self.assertLessEqual(
            max(steps(result["x"], result["resets"])), self.limit + 1e-6
        )
        edited = plan(
            samples(4, lambda t: 0.25 if t < 2 else 0.75), edit_resets=[index]
        )
        self.assertIn(index, edited["resets"])
        self.assertAlmostEqual(edited["x"][index] + 304, 0.75 * 1920, delta=2)

    def test_lost_face_holds_and_no_face_falls_back_to_centre(self):
        result = plan(samples(4, lambda t: 0.3 if t < 1 else None))
        self.assertEqual(max(steps(result["x"])), 0)
        self.assertAlmostEqual(result["x"][-1] + 304, 0.3 * 1920, delta=1)
        empty = plan(samples(4, lambda t: None))
        self.assertEqual(set(empty["x"]), {(1920 - 608) / 2})
        self.assertEqual(empty["face_frames"], [])
        nothing = plan([])
        self.assertEqual(set(nothing["x"]), {(1920 - 608) / 2})

    def test_largest_face_wins_unless_a_smaller_face_is_talking(self):
        def quiet(t):
            return [face(0.2, size=0.3, mouth=0.02), face(0.8, size=0.15, mouth=0.02)]

        result = plan(samples(3, None, faces_at=quiet), duration=3)
        self.assertAlmostEqual(result["x"][-1] + 304, 0.2 * 1920, delta=2)

        def talking(t):
            frame = round(t * FPS)
            return [
                face(0.2, size=0.22, mouth=0.02),
                face(0.8, size=0.2, mouth=0.05 if frame % 2 else 0.35),
            ]

        result = plan(samples(3, None, faces_at=talking), duration=3)
        self.assertAlmostEqual(result["x"][-1] + 304, 0.8 * 1920, delta=25)

    def test_eyes_go_to_the_upper_third_of_the_safe_area_when_vertical_is_free(self):
        frames = [index / FPS for index in range(60)]
        result = reframe.plan_path(
            mode="face_track",
            source_size=(2160, 3840),
            crop_size=(2160, 1214),
            frame_size=(1920, 1080),
            frames=frames,
            fps=FPS,
            faces=samples(2, None, faces_at=lambda t: [face(0.5, 0.5, eye=0.45)]),
            zone={"top": 0.05, "bottom": 0.05, "left": 0.05, "right": 0.05},
        )
        eye_line = (0.45 * 3840 - result["y"][-1]) / 1214
        self.assertAlmostEqual(eye_line, 0.05 + 0.9 / 3, delta=0.01)

    def test_keyframes_pin_the_path_and_interpolate_smoothly(self):
        keys = [{"time": 0.5, "x": 0.3}, {"time": 3.5, "x": 0.6}]
        manual = plan(mode="center_crop", keyframes=keys, duration=5)
        self.assertAlmostEqual(manual["x"][0] + 304, 0.3 * 1920, delta=1)
        self.assertAlmostEqual(manual["x"][-1] + 304, 0.6 * 1920, delta=2)
        self.assertLessEqual(max(steps(manual["x"])), self.limit + 1e-6)
        middle = manual["x"][60] + 304
        self.assertTrue(0.3 * 1920 < middle < 0.6 * 1920)
        tracked = plan(
            samples(8, lambda t: 0.8),
            duration=8,
            keyframes=[{"time": 4.0, "x": 0.3}],
        )
        self.assertAlmostEqual(tracked["x"][4 * FPS] + 304, 0.3 * 1920, delta=3)
        self.assertAlmostEqual(tracked["x"][0] + 304, 0.8 * 1920, delta=3)
        self.assertLessEqual(max(steps(tracked["x"])), self.limit + 1e-6)

    def test_face_frames_report_where_the_face_lands(self):
        result = plan(samples(2, lambda t: 0.3), duration=2)
        self.assertEqual(len(result["face_frames"]), 60)
        index, fx, fy = result["face_frames"][0]
        self.assertEqual(index, 0)
        self.assertAlmostEqual(fx, 0.3 * 1920, delta=0.5)

    def test_impossible_pins_are_refused_instead_of_exceeding_motion_limits(self):
        with self.assertRaisesRegex(ValueError, "keyframes"):
            plan(
                mode="center_crop",
                keyframes=[{"time": 1, "x": 0.1}, {"time": 1.01, "x": 0.9}],
            )

    def test_manual_pins_cannot_exceed_acceleration_even_below_maximum_speed(self):
        with self.assertRaisesRegex(ValueError, "acceleration"):
            plan(
                mode="center_crop",
                keyframes=[{"time": 1, "x": 0.5}, {"time": 1.1, "x": 0.51}],
            )


class ExpressionTests(unittest.TestCase):
    def test_piecewise_expression_reproduces_the_path(self):
        values = [10.0] * 20 + [10.0 + i * 2.5 for i in range(30)] + [400.0] * 10
        expression, pieces = reframe.path_expression(values, resets=[50])
        self.assertLessEqual(pieces, 6)
        for index, value in enumerate(values):
            self.assertAlmostEqual(
                eval(
                    expression.replace("if(", "choose("),
                    {"__builtins__": {}},
                    {
                        "choose": lambda condition, a, b: a if condition else b,
                        "lt": lambda a, b: a < b,
                        "n": index,
                    },
                ),
                value,
                delta=0.3,
            )
        self.assertNotIn(";", expression)


def gradient_source(path, duration=3, audio=True):
    """640x360 source whose luma encodes the column: value = x * 255 / 639."""
    arguments = [
        "-f",
        "lavfi",
        "-i",
        f"color=black:size=640x360:rate={FPS}:duration={duration},"
        "format=gray,geq=lum='16+X*219/639',format=yuv420p",
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


def left_columns(video):
    """Mean luma of the left eight output columns of every frame."""
    raw = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            "crop=8:ih:0:0,scale=1:1:flags=area,format=gray",
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


def stream_durations(video):
    data = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,duration,start_time",
                "-of",
                "json",
                str(video),
            ],
            check=True,
            capture_output=True,
            env=child_env(python=False),
            timeout=60,
        ).stdout
    )
    return {
        s["codec_type"]: (float(s["start_time"]), float(s["duration"]))
        for s in data["streams"]
    }


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.source = cls.root / "gradient.mp4"
        gradient_source(cls.source)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def render(self, name, segments, **settings):
        output = self.root / name
        result = pp.export_video(
            self.source,
            segments,
            output,
            settings={"platform": "instagram_reels", "preset": "preview", **settings},
        )
        return output, result

    def test_face_track_render_follows_the_planned_path_with_exact_duration(self):
        faces = samples(3, lambda t: 0.25 if t < 1.4 else 0.75)
        segments = [{"start": 0.0, "end": 1.2}, {"start": 1.6, "end": 3.0}]
        output, result = self.render(
            "track.mp4",
            segments,
            framing="face_track",
            framing_analysis={"faces": faces, "scene_cuts": []},
        )
        report = result["framing"]
        self.assertEqual(result["fit"], "crop")
        self.assertEqual(report["mode"], "face_track")
        self.assertEqual(report["crop"], [202, 360])
        self.assertTrue(result["upscaled"])
        self.assertAlmostEqual(result["upscale_factor"], 1080 / 202)
        self.assertEqual(result["content_size"], [1080, 1920])
        self.assertEqual(report["frames"], 78)
        self.assertIn(36, report["resets"])
        measured = left_columns(output)
        self.assertEqual(len(measured), report["frames"])
        for index, (planned, value) in enumerate(zip(report["x"], measured)):
            rendered = (int(planned) // 2 * 2 + 0.75) * 255 / 639
            self.assertAlmostEqual(
                value, rendered, delta=6, msg=f"frame {index}: lossy luma tolerance"
            )
        durations = stream_durations(output)
        self.assertAlmostEqual(durations["video"][1], 78 / FPS, delta=0.5 / FPS)
        self.assertAlmostEqual(durations["audio"][1], durations["video"][1], delta=0.03)
        self.assertAlmostEqual(durations["audio"][0], durations["video"][0], delta=0.03)

    def test_center_crop_is_static_and_reports_its_upscale(self):
        output, result = self.render(
            "centre.mp4", [{"start": 0.0, "end": 1.0}], framing="center_crop"
        )
        self.assertEqual(result["framing"]["crop"], [202, 360])
        values = left_columns(output)
        expected = ((640 - 202) // 2 // 2 * 2 + 0.75) * 255 / 639
        self.assertTrue(all(abs(value - expected) <= 3 for value in values), values)
        self.assertTrue(result["upscaled"])
        self.assertIn("upscale", " ".join(result["framing"]["warnings"]))

    def test_keyframes_drive_a_centre_crop(self):
        output, result = self.render(
            "keys.mp4",
            [{"start": 0.0, "end": 3.0}],
            framing="center_crop",
            framing_keyframes=[{"time": 0.0, "x": 0.2}, {"time": 3.0, "x": 0.8}],
        )
        report = result["framing"]
        self.assertTrue(report["keyframed"])
        measured = left_columns(output)
        self.assertGreater(measured[-1], measured[0] + 60)
        for planned, value in zip(report["x"], measured):
            self.assertAlmostEqual(
                value, (int(planned) // 2 * 2 + 0.75) * 255 / 639, delta=6
            )

    def test_blur_fill_fills_the_bars_with_the_blurred_source(self):
        fit_output, fit = self.render("fit.mp4", [{"start": 0.0, "end": 0.5}])
        blur_output, blur = self.render(
            "blur.mp4", [{"start": 0.0, "end": 0.5}], framing="blur_fill"
        )
        self.assertEqual(fit["fit"], "pad")
        self.assertNotIn("framing", fit)
        self.assertEqual(blur["fit"], "blur_fill")
        self.assertEqual(blur["content_size"], fit["content_size"])

        def top_band(video):
            raw = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    "-vf",
                    "crop=iw:200:0:100,scale=1:1:flags=area,format=gray",
                    "-f",
                    "rawvideo",
                    "-",
                ],
                check=True,
                capture_output=True,
                env=child_env(python=False),
                timeout=60,
            ).stdout
            return raw[0]

        self.assertLess(top_band(fit_output), 20)
        self.assertGreater(top_band(blur_output), 60)

    def test_fit_render_graph_is_unchanged(self):
        captured = {}
        original = pp._render_graph

        def spy(arguments, *, cwd, timeout):
            if (Path(cwd) / "filters.txt").is_file():
                captured["graph"] = (Path(cwd) / "filters.txt").read_text(
                    encoding="utf-8"
                )
            return original(arguments, cwd=cwd, timeout=timeout)

        with patch.object(pp, "_render_graph", spy):
            self.render("plain.mp4", [{"start": 0.0, "end": 0.5}], framing="fit")
        self.assertIn(
            "[joined]scale=1080:606,setsar=1,pad=1080:1920", captured["graph"]
        )
        self.assertNotIn("crop", captured["graph"])


class QualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.source = cls.root / "gradient.mp4"
        gradient_source(cls.source, duration=2)
        cls.output = cls.root / "track.mp4"
        cls.result = pp.export_video(
            cls.source,
            [{"start": 0.0, "end": 2.0}],
            cls.output,
            settings={
                "platform": "instagram_reels",
                "preset": "preview",
                "framing": "face_track",
                "framing_analysis": {
                    "faces": samples(2, lambda t: 0.3 + 0.04 * t),
                    "scene_cuts": [],
                },
            },
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def checks(self, report=None, **extra):
        settings = {
            "platform": "instagram_reels",
            "preset": "preview",
            "framing": "face_track",
            "source_video": self.result["source_video"],
            "framing_report": report or self.result["framing"],
            **extra,
        }
        result = pp.quality_report(self.output, settings)
        return {check["name"]: check for check in result["checks"]}

    def test_face_safe_zone_smoothness_and_frame_count_pass(self):
        checks = self.checks()
        for name in ("framing_face_safe_zone", "framing_smoothness", "framing_frames"):
            self.assertEqual(checks[name]["status"], "pass", checks[name])
        detail = checks["framing_face_safe_zone"]["detail"]
        self.assertGreaterEqual(detail["inside_fraction"], 0.95)
        self.assertEqual(detail["required_fraction"], 0.95)
        upscale = checks["platform_upscale"]
        self.assertEqual(upscale["status"], "warning")
        self.assertAlmostEqual(upscale["detail"]["factor"], 1080 / 202)
        self.assertEqual(upscale["detail"]["crop"], [202, 360])

    def test_failures_are_reported(self):
        report = json.loads(json.dumps(self.result["framing"]))
        report["x"][10] += 200
        self.assertEqual(self.checks(report)["framing_smoothness"]["status"], "fail")
        report = json.loads(json.dumps(self.result["framing"]))
        report["face_frames"] = [[k, 5.0, 180.0] for k, _, _ in report["face_frames"]]
        self.assertEqual(
            self.checks(report)["framing_face_safe_zone"]["status"], "fail"
        )
        report = json.loads(json.dumps(self.result["framing"]))
        report["x"] = report["x"][:-3]
        report["frames"] -= 3
        report["face_frames"] = report["face_frames"][:-3]
        self.assertEqual(self.checks(report)["framing_frames"]["status"], "fail")

    def test_face_track_reports_without_faces_warn_instead_of_skipping(self):
        report = json.loads(json.dumps(self.result["framing"]))
        report["face_frames"] = []
        self.assertEqual(
            self.checks(report)["framing_face_safe_zone"]["status"], "warning"
        )
        report["mode"] = "center_crop"
        self.assertEqual(
            self.checks(report)["framing_face_safe_zone"]["status"], "skip"
        )

    def test_invalid_framing_settings_are_rejected(self):
        for bad in (
            {"framing": "zoom"},
            {"framing_keyframes": [{"time": -1, "x": 0.5}]},
            {"framing_analysis": {"faces": "x", "scene_cuts": []}},
            {"framing_analysis": {"faces": [], "scene_cuts": [float("nan")]}},
            {"framing_report": {"mode": "face_track", "x": "bad"}},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pp._settings(bad)


class VisionInputTests(unittest.TestCase):
    def test_face_metrics_carry_a_normalised_box_and_eye_line(self):
        from test_vision import landmarks

        from cutroom import vision

        result = vision._face_metrics(landmarks(), 400, 200)
        x0, y0, x1, y1 = result["box"]
        self.assertAlmostEqual(x0, 0.25)
        self.assertAlmostEqual(x1, 0.75)
        self.assertAlmostEqual(y0, 0.4)
        self.assertAlmostEqual(y1, 0.61)
        self.assertAlmostEqual(result["eye_y"], 0.4)
        self.assertIsNone(vision._face_metrics([], 400, 200)["box"])

    def test_face_samples_are_compact_and_keep_every_analysed_frame(self):
        frames = [
            {
                "time": index / 10,
                "faces": [
                    {"box": [0.1, 0.2, 0.3, 0.6], "eye_y": 0.3, "mouth_open": 0.1},
                    {"box": None, "eye_y": None, "mouth_open": None},
                ],
            }
            for index in range(2500)
        ]
        compact = reframe.face_samples(frames)
        self.assertEqual(len(compact), 2500)
        time, faces = compact[1]
        self.assertAlmostEqual(time, 0.1)
        self.assertEqual(len(faces), 1)
        self.assertEqual([round(v, 4) for v in faces[0][:5]], [0.2, 0.4, 0.2, 0.4, 0.3])
        self.assertAlmostEqual(faces[0][5], 0.1)

    def test_vision_worker_adds_framing_inputs(self):
        from cutroom import worker

        fake = {"frames": [{"time": 0.0, "faces": []}], "status": "no_face_detected"}
        with (
            patch("cutroom.vision.analyze_faces", return_value=fake),
            patch("cutroom.reframe.scene_cuts", return_value=[1.5]) as cuts,
        ):
            result = worker.execute("vision", {"source": "x.mp4", "face_model": "m"})
        cuts.assert_called_once()
        self.assertEqual(result["face_samples"], [[0.0, []]])
        self.assertEqual(result["scene_cuts"], [1.5])

    def test_scene_cuts_are_detected_with_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temporary:
            clip = Path(temporary) / "cut.mp4"
            ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=30:duration=2",
                "-f",
                "lavfi",
                "-i",
                "smptebars=size=320x180:rate=30:duration=2",
                "-filter_complex",
                "[0][1]concat=n=2:v=1[v]",
                "-map",
                "[v]",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                str(clip),
            )
            cuts = reframe.scene_cuts(clip)
            self.assertEqual(len(cuts), 1)
            self.assertAlmostEqual(cuts[0], 2.0, delta=0.05)
            self.assertIsNone(reframe.scene_cuts(Path(temporary) / "missing.mp4"))


_SANDRA = Path("C:/Users/Kaan/Videos/cutroom-test/sandra-wikitongues.webm")


@unittest.skipUnless(_SANDRA.is_file(), "local landscape talking-head clip absent")
class RealSourceTests(unittest.TestCase):
    def test_sandra_crop_window_and_upscale_are_reported(self):
        info = pp._probe(_SANDRA)
        source = pp._source_video(info)
        self.assertEqual([source["width"], source["height"]], [1920, 1080])
        content, factor = reframe.content_upscale(source, 1080, 1920, "face_track")
        self.assertAlmostEqual(factor, max(1080 / 608, 1920 / 1080))
        self.assertEqual(content, [1080, 1920])


if __name__ == "__main__":
    unittest.main()
