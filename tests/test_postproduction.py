"""Postproduction tests: synthetic media only unless explicitly enabled."""

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "cutroom" / "postproduction.py"


def load_module():
    if not MODULE.exists():
        return None
    spec = importlib.util.spec_from_file_location("postproduction_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pp = load_module()


class FilterScriptCompatibilityTests(unittest.TestCase):
    def test_legacy_fallback_only_for_an_unsupported_modern_flag(self):
        from unittest.mock import patch

        arguments = ["ffmpeg", "-/filter_complex", "filters.txt", "output.mp4"]
        unsupported = subprocess.CalledProcessError(
            1, arguments, stderr="Unrecognized option '/filter_complex'."
        )
        success = subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")
        with patch.object(pp, "_run", side_effect=[unsupported, success]) as run:
            self.assertIs(
                pp._render_graph(arguments, cwd="fixture", timeout=7), success
            )
            self.assertEqual(run.call_args_list[1].args[0][1], "-filter_complex_script")
            self.assertEqual(run.call_args_list[1].kwargs["timeout"], 7)
            self.assertEqual(arguments[1], "-/filter_complex")
        encoder_failure = subprocess.CalledProcessError(
            1, arguments, stderr="Encoder failed"
        )
        with patch.object(pp, "_run", side_effect=encoder_failure) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                pp._render_graph(arguments, cwd="fixture", timeout=7)
            self.assertEqual(run.call_count, 1)


class LocalPathTests(unittest.TestCase):
    def test_resolved_network_path_is_rejected_before_target_filesystem_access(self):
        from unittest.mock import patch

        target = Path(r"\\review.invalid\share\render.mp4")
        for exists in (False, True):
            with (
                self.subTest(exists=exists),
                patch.object(Path, "resolve", return_value=target) as resolve,
                patch.object(
                    Path, "stat", side_effect=AssertionError("Target filesystem access")
                ) as stat,
                patch.object(
                    Path, "open", side_effect=AssertionError("Target filesystem access")
                ) as open_file,
            ):
                with self.assertRaisesRegex(ValueError, "local|Network"):
                    pp._path("C:/local-link/render.mp4", exists)
                resolve.assert_called_once_with()
                stat.assert_not_called()
                open_file.assert_not_called()


class BrandTests(unittest.TestCase):
    def test_validated_brand_persistence_and_correction(self):
        self.assertTrue(hasattr(pp, "default_brand"), "brand API is missing")
        brand = pp.default_brand()
        self.assertEqual(pp.validate_brand(brand), brand)
        with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as temp:
            path = Path(temp) / "brand.json"
            pp.save_brand(path, brand)
            self.assertEqual(pp.load_brand(path), brand)
            corrected = pp.persist_correction(
                path, {"title_color": "#12ABEF", "alignment": "left"}
            )
            self.assertEqual(corrected["title_color"], "#12ABEF")
            self.assertEqual(pp.load_brand(path)["alignment"], "left")
            before = path.read_bytes()
            for patch in (
                {"title_color": "red;movie=x"},
                {"font": "Arial:foo=1"},
                {"safe_margin": -1},
                {"title_y": 0.99},
                {"subtitle_y": float("nan")},
                {"title_size": 9000},
                {"alignment": "diagonal"},
                {"aspect": "crop"},
                {"preset": "secret"},
                {"unknown": True},
            ):
                with self.subTest(patch=patch), self.assertRaises(ValueError):
                    pp.persist_correction(path, patch)
                self.assertEqual(path.read_bytes(), before)


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(
            dir=os.environ["TMPDIR"], prefix="postproduction-"
        )
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "source woman's [fixture].mkv"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=96x160:rate=10:duration=1.2",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                str(cls.source),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_effects_are_visible_in_decoded_pixels_and_title_stays_safe(self):
        source = self.root / "effect-black.mkv"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-f",
                "lavfi",
                "-i",
                "color=black:size=96x160:rate=10:duration=0.6",
                "-c:v",
                "ffv1",
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )

        def rgb(video, at, crop):
            return subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-ss",
                    str(at),
                    "-i",
                    str(video),
                    "-vf",
                    crop,
                    "-frames:v",
                    "1",
                    "-pix_fmt",
                    "rgb24",
                    "-f",
                    "rawvideo",
                    "-",
                ],
                capture_output=True,
                check=True,
                timeout=30,
            ).stdout

        static = pp.export_video(
            source,
            [{"start": 0, "end": 0.6}],
            self.root / "static.mp4",
            {"aspect": "square", "title": "Visible title"},
        )
        fade = pp.export_video(
            source,
            [{"start": 0, "end": 0.6}],
            self.root / "fade.mp4",
            {"aspect": "square", "title": "Visible title", "title_animation": True},
        )
        first = rgb(fade["output"], 0, "crop=1080:200:0:80")
        last = rgb(fade["output"], 0.4, "crop=1080:200:0:80")
        visible = rgb(static["output"], 0, "crop=1080:200:0:80")
        self.assertGreater(sum(last), sum(first) + 10000)
        self.assertGreater(sum(visible), 10000)
        pixels = [
            (index // 3 % 1080, index // 3 // 1080 + 80)
            for index in range(0, len(visible), 3)
            if max(visible[index : index + 3]) > 100
        ]
        self.assertGreaterEqual(min(x for x, y in pixels), 85)
        self.assertLessEqual(max(x for x, y in pixels), 995)
        self.assertGreaterEqual(min(y for x, y in pixels), 85)
        captioned = pp.export_video(
            source,
            [{"start": 0, "end": 0.6}],
            self.root / "caption-effect.mp4",
            {"aspect": "square", "lower_third": "Speaker"},
            [{"start": 0, "end": 0.6, "text": "Visible caption"}],
        )
        self.assertGreater(
            sum(rgb(captioned["output"], 0.2, "crop=900:150:90:800")), 10000
        )
        self.assertGreater(
            sum(rgb(captioned["output"], 0.2, "crop=900:120:90:710")), 10000
        )

    def test_configured_timeout_applies_to_probe_and_render(self):
        from unittest.mock import patch

        original = pp.subprocess.run
        calls = []

        def record(args, **kwargs):
            calls.append((args[0], kwargs.get("timeout"), kwargs.get("shell")))
            return original(args, **kwargs)

        with patch.object(pp.subprocess, "run", record):
            pp.export_video(
                self.source,
                [{"start": 0, "end": 0.2}],
                self.root / "deadline.mp4",
                {"timeout": 17},
            )
        self.assertTrue(calls)
        self.assertTrue(
            all(timeout == 17 and shell is False for _, timeout, shell in calls), calls
        )

    def test_lower_third_respects_top_safe_margin_at_extreme_position(self):
        result = pp.export_video(
            self.source,
            [{"start": 0, "end": 0.2}],
            self.root / "safe-band.mp4",
            {
                "brand": {"safe_margin": 0.2, "title_y": 0.2, "subtitle_y": 0.2},
                "lower_third": "Speaker",
            },
        )
        self.assertGreaterEqual(result["lower_third_y"], 0.2)

    def test_caption_and_lower_third_have_separate_safe_bands(self):
        from unittest.mock import patch

        original = pp._run
        graphs = []

        def record(args, **kwargs):
            if args[0] == "ffmpeg":
                graphs.append(
                    (Path(kwargs["cwd"]) / "filters.txt").read_text(encoding="utf-8")
                )
            return original(args, **kwargs)

        with patch.object(pp, "_run", record):
            result = pp.export_video(
                self.source,
                [{"start": 0, "end": 0.3}],
                self.root / "bands.mp4",
                {"lower_third": "Speaker name"},
                [{"start": 0, "end": 0.3, "text": "Caption"}],
            )
        self.assertIn("lower_third_y", result)
        self.assertLess(
            result["lower_third_y"] + 0.09, pp.default_brand()["subtitle_y"]
        )
        self.assertIn("drawbox", graphs[0])

    def test_rejects_unsafe_brand_positions_and_invalid_render_inputs(self):
        # Bad values must never create a render target, even after source probing.
        output = self.root / "rejected.mp4"
        for settings in (
            {"aspect": "crop"},
            {"preset": "4k"},
            {"brand": {"font": "Arial';movie=x"}},
            {"brand": {"title_color": "#fff,split=2"}},
            {"timeout": float("nan")},
            {"loudness_lufs": float("inf")},
            {"title": "bad\x00text"},
            {"normalize_audio": "yes"},
            {"unknown": "value"},
        ):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                pp.export_video(
                    self.source, [{"start": 0, "end": 0.2}], output, settings
                )
        for segments in (
            [],
            [{"start": 0, "end": float("nan")}],
            [{"start": -0.1, "end": 0.2}],
            [{"start": 0, "end": 9}],
            [{"start": 1, "end": 0.2}],
            [{"start": 0, "end": 0.5}, {"start": 0.4, "end": 0.7}],
        ):
            with self.subTest(segments=segments), self.assertRaises(ValueError):
                pp.export_video(self.source, segments, output)
        for captions in (
            [{"start": 0, "end": 0.3, "text": "too late"}],
            [{"start": 0, "end": 0.1, "text": ""}],
            [{"start": 0, "end": float("nan"), "text": "bad"}],
        ):
            with self.subTest(captions=captions), self.assertRaises(ValueError):
                pp.export_video(
                    self.source, [{"start": 0, "end": 0.2}], output, captions=captions
                )
        for source in (
            "https://example.invalid/movie.mp4",
            "//server/share/movie.mp4",
            "pipe:0",
        ):
            with self.assertRaises(ValueError):
                pp.export_video(source, [{"start": 0, "end": 0.2}], output)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob(".postproduction-*")))

    def test_atomic_publication_loses_race_without_overwriting(self):
        from unittest.mock import patch

        output = self.root / "race.mp4"
        original = pp.os.link

        def race(source, destination):
            Path(destination).write_bytes(b"existing output from another writer")
            return original(source, destination)

        with patch.object(pp.os, "link", race), self.assertRaises(FileExistsError):
            pp.export_video(self.source, [{"start": 0, "end": 0.2}], output)
        self.assertEqual(output.read_bytes(), b"existing output from another writer")
        self.assertFalse(list(self.root.glob(".postproduction-*")))

    def test_failed_render_cleans_temp_and_never_publishes(self):
        from unittest.mock import patch

        original = pp._run
        output = self.root / "failed.mp4"

        def failed(args, **kwargs):
            if args[0] == "ffmpeg":
                self.assertIn("-/filter_complex", args)
                self.assertTrue((Path(kwargs["cwd"]) / "filters.txt").is_file())
                self.assertGreater(kwargs["timeout"], 0)
                raise subprocess.TimeoutExpired(args, kwargs["timeout"])
            return original(args, **kwargs)

        with (
            patch.object(pp, "_run", failed),
            self.assertRaises(subprocess.TimeoutExpired),
        ):
            pp.export_video(self.source, [{"start": 0, "end": 0.2}], output)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob(".postproduction-*")))

    def test_every_frame_timing_detects_unexpected_pts_gap(self):
        gap = self.root / "pts-gap.mkv"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=96x160:rate=10:duration=1.2",
                "-vf",
                "setpts='PTS+if(gte(N,5),0.5/TB,0)'",
                "-fps_mode",
                "passthrough",
                "-c:v",
                "ffv1",
                str(gap),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        checks = {c["name"]: c for c in pp.quality_report(gap)["checks"]}
        self.assertEqual(checks["frame_timing"]["status"], "warning")
        self.assertAlmostEqual(
            checks["frame_timing"]["detail"]["gaps"][0]["seconds"], 0.6, delta=0.01
        )
        self.assertEqual(checks["signalstats"]["detail"]["frames_scanned"], 12)

    def test_quality_checks_requested_output_resolution(self):
        report = pp.quality_report(
            self.source, {"preset": "final", "aspect": "portrait"}
        )
        checks = {c["name"]: c for c in report["checks"]}
        self.assertIn("resolution", checks)
        self.assertEqual(checks["resolution"]["status"], "fail")
        self.assertEqual(checks["resolution"]["detail"]["expected"], [2160, 3840])
        self.assertEqual(checks["resolution"]["detail"]["actual"], [96, 160])

    def test_quality_full_frame_scan_with_semantic_evidence(self):
        self.assertTrue(hasattr(pp, "quality_report"), "quality API is missing")
        black = self.root / "black.mkv"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-f",
                "lavfi",
                "-i",
                "color=black:size=96x160:rate=10:duration=1.2",
                "-c:v",
                "ffv1",
                str(black),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        report = pp.quality_report(
            black,
            {"freeze_min_duration": 0.3, "expected_duration": 2},
            [
                {
                    "start": 0,
                    "end": 0.1,
                    "text": "Far too many words for one tenth of a second",
                }
            ],
        )
        checks = {check["name"]: check for check in report["checks"]}
        self.assertFalse(report["passed"])
        self.assertEqual(checks["audio"]["status"], "skip")
        self.assertEqual(checks["duration"]["status"], "fail")
        self.assertEqual(checks["signalstats"]["detail"]["frames_scanned"], 12)
        self.assertEqual(
            checks["signalstats"]["detail"]["sampling"], "every decoded frame"
        )
        self.assertEqual(checks["black_frames"]["detail"]["intervals"][0]["start"], 0)
        self.assertGreater(
            checks["freeze_frames"]["detail"]["intervals"][0]["end"], 0.8
        )
        self.assertEqual(checks["captions"]["status"], "fail")
        self.assertIn("cps", checks["captions"]["detail"]["issues"][0])
        self.assertTrue(any("single-frame" in text for text in report["limitations"]))
        flash = self.root / "flash.mkv"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=96x160:rate=10:duration=1.2",
                "-vf",
                "drawbox=color=white:t=fill:enable='eq(n,5)'",
                "-c:v",
                "ffv1",
                str(flash),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        checks = {c["name"]: c for c in pp.quality_report(flash)["checks"]}
        self.assertAlmostEqual(
            checks["signalstats"]["detail"]["flash_candidates"][0]["time"], 0.5
        )
        self.assertEqual(checks["signalstats"]["detail"]["frames_scanned"], 12)

    def test_audio_quality_detects_clipping_silence_and_measures_lufs(self):
        self.assertTrue(hasattr(pp, "quality_report"))
        source = self.root / "clipped-with-gap.mkv"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=160x96:rate=10:duration=3",
                "-f",
                "lavfi",
                "-i",
                r"aevalsrc=if(between(t\,1\,2)\,0\,2*sin(2*PI*440*t)):s=48000:d=3",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "pcm_s16le",
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        checks = {c["name"]: c for c in pp.quality_report(source)["checks"]}
        self.assertIn("integrated_lufs", checks["audio"]["detail"])
        self.assertGreaterEqual(checks["audio"]["detail"]["max_volume_db"], -0.1)
        self.assertEqual(checks["audio_clipping"]["status"], "warning")
        interval = checks["audio_gaps"]["detail"]["intervals"][0]
        self.assertAlmostEqual(interval["start"], 1, delta=0.02)
        self.assertAlmostEqual(interval["end"], 2, delta=0.02)

    def test_real_audio_loudness_normalization(self):
        source = self.root / "tone.mkv"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=160x96:rate=5:duration=3",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=3",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "pcm_s16le",
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        result = pp.export_video(
            source,
            [{"start": 0, "end": 3}],
            self.root / "normalized.mp4",
            {"loudness_lufs": -16, "true_peak_db": -1.5},
        )
        self.assertEqual(result.get("audio_normalization", {}).get("target_lufs"), -16)
        measured = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-i",
                result["output"],
                "-vn",
                "-af",
                "ebur128=peak=true",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stderr
        import re

        integrated = float(re.findall(r"I:\s*([-\d.]+) LUFS", measured)[-1])
        self.assertAlmostEqual(integrated, -16, delta=1)

    def test_source_aspect_honors_display_rotation(self):
        source = self.root / "rotated.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-display_rotation",
                "90",
                "-i",
                str(self.source),
                "-c",
                "copy",
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        metadata = json.loads(
            subprocess.run(
                ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(source)],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        )
        self.assertTrue(
            any(
                abs(item.get("rotation", 0)) == 90
                for item in metadata["streams"][0].get("side_data_list", [])
            )
        )
        result = pp.export_video(
            source, [{"start": 0, "end": 0.2}], self.root / "rotated-render.mp4"
        )
        self.assertEqual((result["width"], result["height"]), (1920, 1152))

    def test_source_aspect_preserves_anamorphic_display_ratio(self):
        source = self.root / "anamorphic.mkv"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=96x160:rate=10:duration=0.2",
                "-vf",
                "setsar=2",
                "-c:v",
                "ffv1",
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        result = pp.export_video(
            source, [{"start": 0, "end": 0.2}], self.root / "anamorphic-render.mp4"
        )
        self.assertEqual((result["width"], result["height"]), (1920, 1600))
        cover = pp.make_cover(source, self.root / "anamorphic-cover.png")
        self.assertEqual((cover["width"], cover["height"]), (1920, 1600))

    def test_final_landscape_and_preview_square_resolution(self):
        final = pp.export_video(
            self.source,
            [{"start": 0, "end": 0.2}],
            self.root / "landscape-4k.mp4",
            {"preset": "final", "aspect": "landscape"},
        )
        self.assertEqual((final["width"], final["height"]), (3840, 2160))
        square = pp.export_video(
            self.source,
            [{"start": 0, "end": 0.2}],
            self.root / "square.mp4",
            {"aspect": "square"},
        )
        self.assertEqual((square["width"], square["height"]), (1080, 1080))

    @unittest.skipUnless(
        os.environ.get("CUTROOM_TEST_USER_MEDIA") == "1",
        "requires explicit consented media opt-in",
    )
    def test_consented_user_videos_preview_cover_and_full_frame_qa(self):
        raw = MODULE.parents[1] / "raw_vids"
        fixtures = [
            ("12511-239934660.mp4", (1920, 1080)),
            ("4439224-uhd_2160_3840_25fps.mp4", (1080, 1920)),
        ]
        evidence = []
        for index, (filename, dimensions) in enumerate(fixtures):
            source = raw / filename
            self.assertTrue(source.is_file(), filename)
            result = pp.export_video(
                source,
                [{"start": 0, "end": 0.24}],
                self.root / f"user-preview-{index}.mp4",
                {"title": "Local preview", "title_animation": True},
                [{"start": 0, "end": 0.24, "text": "Local"}],
            )
            self.assertEqual((result["width"], result["height"]), dimensions)
            self.assertFalse(result["has_audio"])
            self.assertFalse(result["upscaled"])
            cover = pp.make_cover(
                result["output"], self.root / f"user-cover-{index}.jpg", "Local cover"
            )
            self.assertEqual((cover["width"], cover["height"]), dimensions)
            report = pp.quality_report(
                result["output"], captions=[{"start": 0, "end": 0.24, "text": "Local"}]
            )
            checks = {c["name"]: c for c in report["checks"]}
            self.assertEqual(checks["decode"]["status"], "pass")
            self.assertEqual(checks["audio"]["status"], "skip")
            self.assertEqual(
                checks["signalstats"]["detail"]["frames_scanned"],
                checks["frame_timing"]["detail"]["frames"],
            )
            evidence.append(
                {
                    "source": filename,
                    "resolution": dimensions,
                    "noaudio": not result["has_audio"],
                    "upscaled": result["upscaled"],
                    "frames_scanned": checks["signalstats"]["detail"]["frames_scanned"],
                    "cover_codec": cover["codec"],
                    "qa_passed": report["passed"],
                }
            )
        print("CONSENTED_MEDIA_EVIDENCE=" + json.dumps(evidence))

    def test_final_portrait_and_real_safe_area_cover(self):
        self.assertTrue(hasattr(pp, "make_cover"), "cover API is missing")
        output = self.root / "final.mp4"
        result = pp.export_video(
            self.source,
            [{"start": 0, "end": 0.2}],
            output,
            {"preset": "final", "aspect": "portrait"},
        )
        self.assertEqual((result["width"], result["height"]), (2160, 3840))
        for extension, codec in (("jpg", "mjpeg"), ("png", "png")):
            cover = self.root / ("cover." + extension)
            report = pp.make_cover(
                output, cover, "Safe: '100%' [title]", {"aspect": "portrait"}, time=0.1
            )
            self.assertEqual((report["width"], report["height"]), (1080, 1920))
            self.assertEqual(report["codec"], codec)
            self.assertTrue(report["safe_area"])
            with self.assertRaises(FileExistsError):
                pp.make_cover(output, cover)
        with self.assertRaises(ValueError):
            pp.make_cover(output, self.root / "invalid.png", time=float("nan"))
        with self.assertRaises(ValueError):
            pp.make_cover(output, self.root / "outofbounds.png", time=2)

    def test_preview_cut_fit_titles_graphic_captions_and_nooverwrite(self):
        self.assertTrue(hasattr(pp, "export_video"), "export API is missing")
        output = self.root / "preview.mp4"
        result = pp.export_video(
            self.source,
            [{"start": 0, "end": 0.3}, {"start": 0.7, "end": 1}],
            output,
            {
                "aspect": "landscape",
                "title": "Hello: '100%' [safe]",
                "lower_third": "Local graphic",
                "title_animation": True,
            },
            [{"start": 0, "end": 0.5, "text": r"Caption {\\pos(0,0)} ; [literal]"}],
        )
        self.assertEqual((result["width"], result["height"]), (1920, 1080))
        self.assertAlmostEqual(result["duration"], 0.6, delta=0.11)
        self.assertFalse(result["has_audio"])
        self.assertTrue(result["upscaled"])
        self.assertEqual(result["fit"], "pad")
        self.assertEqual(result["captions_burned"], 1)
        self.assertIn("title_fade", result["effects"])
        before = output.read_bytes()
        with self.assertRaises(FileExistsError):
            pp.export_video(self.source, [{"start": 0, "end": 0.2}], output)
        self.assertEqual(output.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".postproduction-*")))
        # Padding keeps the entire portrait, rather than cropping the person.
        pixel = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(output),
                "-vf",
                "crop=2:2:0:0",
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        self.assertLess(max(pixel), 12)


if __name__ == "__main__":
    unittest.main()
