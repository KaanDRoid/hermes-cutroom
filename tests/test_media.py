"""Real FFmpeg integration tests using explicitly synthetic test fixtures."""

import importlib.util
import math
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "cutroom" / "media.py"


def load_media():
    if not MODULE.exists():
        return None
    spec = importlib.util.spec_from_file_location("cutroom_media_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


media = load_media()


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="cutroom-test-fixture-")
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "synthetic-test-fixture.mkv"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-n",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=96x160:rate=20:duration=3",
                "-f",
                "lavfi",
                "-i",
                "aevalsrc=if(between(t\\,1\\,2)\\,0\\,0.3*sin(2*PI*440*t)):s=48000:d=3",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "pcm_s16le",
                str(cls.source),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_audio_only_input_is_a_clear_validation_error(self):
        audio = self.root / "audio-only-fixture.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-loglevel",
                "error",
                "-n",
                "-f",
                "lavfi",
                "-i",
                "sine=duration=0.5",
                str(audio),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        with self.assertRaisesRegex(ValueError, "video stream"):
            media.probe(audio)

    def test_detect_real_tone_silence_tone(self):
        self.assertTrue(
            hasattr(media, "detect_silences"), "silence detection is missing"
        )
        result = media.detect_silences(self.source)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["start"], 1.0, delta=0.03)
        self.assertAlmostEqual(result[0]["end"], 2.0, delta=0.03)
        trailing = media.detect_silences(self.source, noise_db=0)
        self.assertEqual(len(trailing), 1)
        self.assertEqual(trailing[0]["start"], 0.0)
        self.assertAlmostEqual(trailing[0]["end"], 3.0, delta=0.01)

    def test_render_real_concat(self):
        self.assertTrue(hasattr(media, "render"), "render is missing")
        output = self.root / "concat.mp4"
        result = media.render(
            self.source,
            [{"start": 0.0, "end": 0.7}, {"start": 2.0, "end": 2.6}],
            output,
        )
        self.assertEqual(Path(result["output"]), output)
        self.assertAlmostEqual(result["duration"], 1.3, delta=0.12)
        self.assertEqual((result["width"], result["height"]), (96, 160))
        self.assertTrue(result["has_audio"])
        self.assertEqual(
            {key: value for key, value in result.items() if key != "output"},
            media.probe(output),
        )
        self.assertFalse(list(self.root.glob(".cutroom-*")))

    def test_render_without_audio(self):
        source = self.root / "silent-test-fixture.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-loglevel",
                "error",
                "-n",
                "-i",
                str(self.source),
                "-an",
                "-c:v",
                "copy",
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        output = self.root / "silent-concat.mp4"
        result = media.render(
            source, [{"start": 0, "end": 0.5}, {"start": 2, "end": 2.5}], output
        )
        self.assertFalse(result["has_audio"])
        self.assertAlmostEqual(result["duration"], 1.0, delta=0.1)
        self.assertEqual((result["width"], result["height"]), (96, 160))
        self.assertEqual(media.detect_silences(source), [])

    def test_rejects_nonlocal_and_missing_inputs_before_launch(self):
        from unittest.mock import patch

        bad_paths = [
            "https://example.invalid/a.mp4",
            "file:movie.mp4",
            "pipe:0",
            "concat:a|b",
            r"\\\\server\share\video.mp4",
            "//server/share/a.mp4",
            r"\\\\?\C:\video.mp4",
            "",
            str(self.root / "missing.mp4"),
            str(self.root),
        ]
        with patch.object(
            media.subprocess,
            "run",
            side_effect=AssertionError("must reject before launch"),
        ):
            for source in bad_paths:
                with self.subTest(source=source):
                    with self.assertRaises((ValueError, FileNotFoundError)):
                        media.probe(source)

    def test_render_refuses_existing_or_nonlocal_output_before_launch(self):
        from unittest.mock import patch

        existing = self.root / "existing.mp4"
        existing.write_bytes(b"keep this output")
        original = self.source.read_bytes()
        for target in [
            existing,
            self.source,
            "https://example.invalid/out.mp4",
            "//server/share/out.mp4",
        ]:
            with self.subTest(target=target):
                with patch.object(
                    media.subprocess,
                    "run",
                    side_effect=AssertionError("must reject before launch"),
                ):
                    with self.assertRaises((ValueError, FileExistsError)):
                        media.render(self.source, [{"start": 0, "end": 1}], target)
        self.assertEqual(existing.read_bytes(), b"keep this output")
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse(list(self.root.glob(".cutroom-*")))

    def test_rejects_invalid_intervals_and_detector_numbers(self):
        bad_segments = [
            [],
            [{"start": -1, "end": 1}],
            [{"start": 1, "end": 1}],
            [{"start": 0, "end": float("nan")}],
            [{"start": 0, "end": float("inf")}],
            [{"start": 0, "end": 4}],
            [{"start": 2, "end": 2.5}, {"start": 1, "end": 1.5}],
            [{"start": "0;movie=http://invalid", "end": 1}],
            [{"end": 1}],
        ]
        for segments in bad_segments:
            with self.subTest(segments=segments):
                with self.assertRaises(ValueError):
                    media.render(self.source, segments, self.root / "invalid.mp4")
        for options in [
            {"noise_db": float("nan")},
            {"noise_db": float("inf")},
            {"min_duration": 0},
            {"min_duration": -1},
            {"min_duration": float("nan")},
        ]:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    media.detect_silences(self.source, **options)
        self.assertFalse((self.root / "invalid.mp4").exists())
        self.assertFalse(list(self.root.glob(".cutroom-*")))

    def test_probe_rejects_nonfinite_duration(self):
        import json
        from unittest.mock import patch

        for duration in ["nan", "inf", "0", "-1"]:
            data = {
                "format": {"duration": duration},
                "streams": [{"codec_type": "video", "width": 96, "height": 160}],
            }
            response = subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(data), stderr=""
            )
            with (
                self.subTest(duration=duration),
                patch.object(media.subprocess, "run", return_value=response),
            ):
                with self.assertRaises(ValueError):
                    media.probe(self.source)

    def test_subprocesses_are_bounded_noninteractive_and_local_only(self):
        from unittest.mock import patch

        real_run = subprocess.run
        with patch.object(media.subprocess, "run", wraps=real_run) as calls:
            media.detect_silences(self.source)
            media.render(
                self.source, [{"start": 0, "end": 0.2}], self.root / "guarded.mp4"
            )
        for call in calls.call_args_list:
            arguments = call.args[0]
            self.assertIs(call.kwargs["shell"], False)
            self.assertGreater(call.kwargs["timeout"], 0)
            self.assertTrue(math.isfinite(call.kwargs["timeout"]))
            self.assertEqual(call.kwargs["stdin"], subprocess.DEVNULL)
            self.assertIn("-protocol_whitelist", arguments)
            self.assertEqual(
                arguments[arguments.index("-protocol_whitelist") + 1], "file"
            )
            if arguments[0] == "ffmpeg":
                self.assertIn("-nostdin", arguments)
                if "-filter_complex" in arguments:
                    self.assertIn("-n", arguments)

    def test_render_cleans_intermediate_after_real_encoder_error(self):
        output = self.root / "unsupported.invalid-container"
        with self.assertRaises(subprocess.CalledProcessError):
            media.render(self.source, [{"start": 0, "end": 0.4}], output)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob(".cutroom-*")))

    def test_render_publication_race_does_not_overwrite(self):
        from unittest.mock import patch

        output = self.root / "race.mp4"
        real_link = os.link

        def competing_publication(source, destination):
            Path(destination).write_bytes(b"competing output")
            return real_link(source, destination)

        with patch.object(media.os, "link", side_effect=competing_publication):
            with self.assertRaises(FileExistsError):
                media.render(self.source, [{"start": 0, "end": 0.4}], output)
        self.assertEqual(output.read_bytes(), b"competing output")
        self.assertFalse(list(self.root.glob(".cutroom-*")))

    def test_render_checks_output_alias_before_resolving(self):
        from unittest.mock import patch

        output = self.root / "emulated-link.mp4"
        target = self.root / "emulated-target.mp4"
        real_local_path = media._local_path

        def resolve_alias(value, *, must_exist=True):
            if Path(value) == output:
                return target
            return real_local_path(value, must_exist=must_exist)

        with (
            patch.object(media, "_local_path", side_effect=resolve_alias),
            patch.object(
                Path,
                "is_symlink",
                autospec=True,
                side_effect=lambda path: path == output,
            ),
            patch.object(
                media.subprocess,
                "run",
                side_effect=AssertionError("Must reject before launching media tools"),
            ),
        ):
            with self.assertRaises(FileExistsError):
                media.render(self.source, [{"start": 0, "end": 0.4}], output)

    def test_render_refuses_a_dangling_output_symlink(self):
        output = self.root / "output-symlink.mp4"
        target = self.root / "redirected.mp4"
        try:
            output.symlink_to(target)
        except OSError as error:
            self.skipTest(f"Symlink creation unavailable: {error}")
        try:
            with self.assertRaises(FileExistsError):
                media.render(self.source, [{"start": 0, "end": 0.4}], output)
            self.assertFalse(target.exists())
        finally:
            output.unlink(missing_ok=True)
            target.unlink(missing_ok=True)

    def test_render_timeout_cleans_partial_output(self):
        from unittest.mock import patch

        real_run = subprocess.run

        def timeout_encoder(arguments, **kwargs):
            if arguments[0] == "ffmpeg":
                Path(arguments[-1]).write_bytes(b"partial encoded file")
                raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])
            return real_run(arguments, **kwargs)

        output = self.root / "timeout.mp4"
        with patch.object(media.subprocess, "run", side_effect=timeout_encoder):
            with self.assertRaises(subprocess.TimeoutExpired):
                media.render(self.source, [{"start": 0, "end": 0.4}], output)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob(".cutroom-*")))

    def test_probe_real_portrait_fixture(self):
        self.assertIsNotNone(media, "media module must implement probe")
        result = media.probe(self.source)
        self.assertAlmostEqual(result["duration"], 3.0, delta=0.1)
        self.assertEqual((result["width"], result["height"]), (96, 160))
        self.assertIs(result["has_audio"], True)
        self.assertTrue(math.isfinite(result["duration"]))


if __name__ == "__main__":
    unittest.main()
