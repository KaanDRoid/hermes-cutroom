"""Background music, speech ducking, voice clean-up and cut sound effects."""

import hashlib
import json
import math
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom import audio
from cutroom import postproduction as pp
from cutroom.studio import MissingAssetError, Studio

# Source: 12 s, speech-like tone bursts (200 + 400 Hz) 1.5 s on / 1.5 s off,
# plus optional hum and noise. The kept ranges below remove one pause.
SEGMENTS = [{"start": 0.0, "end": 2.5}, {"start": 6.0, "end": 12.0}]
PROGRAM = 8.5
# Speech in output time: source bursts [0,1.5) [6,7.5) [9,10.5) after the cut.
SPEECH = [(0.0, 1.5), (2.5, 4.0), (5.5, 7.0)]
PAUSES = [(1.5, 2.5), (4.0, 5.5), (7.0, 8.5)]


def ffmpeg(*args, cwd=None):
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=180,
        cwd=cwd,
    )


def make_source(path, *, noise=False, video=True):
    speech = (
        "sine=f=200:r=48000:d=12[a];sine=f=400:r=48000:d=12[b];"
        "[a][b]amix=inputs=2,volume='if(lt(mod(t,3),1.5),1,0)':eval=frame"
    )
    if noise:
        speech += (
            "[tones];sine=f=50:r=48000:d=12,volume=0.05[hum];"
            "anoisesrc=d=12:r=48000:c=pink:a=0.01[hiss];"
            "[tones][hum][hiss]amix=inputs=3:normalize=0"
        )
    args = []
    if video:
        args += ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=12"]
    args += ["-filter_complex", speech + "[speech]"]
    if video:
        args += ["-map", "0:v", "-c:v", "libx264", "-preset", "ultrafast"]
        args += ["-pix_fmt", "yuv420p"]
    args += ["-map", "[speech]", "-c:a", "aac", "-b:a", "192k", "-t", "12", str(path)]
    ffmpeg(*args)


def make_tone(path, frequency, duration, extra=None):
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"sine=f={frequency}:r=44100:d={duration}",
        *(extra or []),
        str(path),
    )


def band_levels(video, frequency, window=0.01, q=8):
    """Per-window RMS levels (dBFS) of one frequency band of the first audio stream."""
    with tempfile.TemporaryDirectory() as temp:
        samples = round(48000 * window)
        ffmpeg(
            "-i",
            str(video),
            "-map",
            "0:a:0",
            "-af",
            f"aresample=48000,bandpass=f={frequency}:width_type=q:w={q},"
            f"bandpass=f={frequency}:width_type=q:w={q},"
            f"asetnsamples=n={samples}:p=0,astats=metadata=1:reset=1,"
            "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=levels.txt",
            "-f",
            "null",
            "-",
            cwd=temp,
        )
        return audio.parse_levels(Path(temp) / "levels.txt")


def mean_db(levels, ranges, margin=0.15):
    values = [
        level
        for time, level in levels
        if any(
            start + margin <= time and time + 0.01 <= end - margin
            for start, end in ranges
        )
    ]
    energy = sum(10 ** (value / 10) for value in values) / len(values)
    return 10 * math.log10(energy)


def loudness(video):
    text = ffmpeg(
        "-i", str(video), "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"
    ).stderr
    integrated = float(text.rsplit("I:", 1)[1].split("LUFS")[0])
    peak = float(text.rsplit("Peak:", 1)[1].split("dBFS")[0])
    return integrated, peak


def stream_durations(video):
    data = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(video)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    return {s["codec_type"]: float(s["duration"]) for s in data["streams"]}


# The band-pass meter itself adds a few milliseconds before a burst crosses its
# threshold, and AAC frames shift a cut join by up to one 1024-sample frame. Sync
# is therefore checked against a plain render of the same edit, measured the same
# way: mixing must not move speech by more than one 10 ms meter window.
SYNC_TOLERANCE = 0.0105


def plain_render(source, root, name):
    output = root / name
    pp.export_video(source, SEGMENTS, output, {"preset": "preview", "timeout": 600})
    return output


def speech_onsets(video):
    levels = band_levels(video, 200)
    return onsets(levels, max(level for _, level in levels) - 20)


def assert_same_onsets(case, video, reference):
    found = speech_onsets(video)
    expected = speech_onsets(reference)
    case.assertEqual(len(found), len(expected), (found, expected))
    for a, b in zip(found, expected):
        case.assertLessEqual(abs(a - b), SYNC_TOLERANCE, (found, expected))


def onsets(levels, threshold):
    result, previous = [], None
    for time, level in levels:
        active = level > threshold
        if active and previous is False:
            result.append(time)
        previous = active
    return result


class _MediaCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)


class ValidationTests(_MediaCase):
    def setUp(self):
        super().setUp()
        self.music = self.root / "bed.wav"
        make_tone(self.music, 1500, 3)

    def test_music_defaults_hash_and_probe(self):
        music = audio.normalize_music({"path": str(self.music)})
        self.assertEqual(music["path"], str(self.music.resolve()))
        self.assertEqual(
            music["sha256"], hashlib.sha256(self.music.read_bytes()).hexdigest()
        )
        self.assertFalse(music["volume_db"] > 0)
        self.assertTrue(music["duck"])
        self.assertGreaterEqual(music["duck_db"], 12)
        self.assertTrue(music["loop"])
        self.assertEqual(music["start_offset"], 0)
        self.assertEqual(music["source_note"], "")
        self.assertAlmostEqual(music["duration"], 3, places=1)
        self.assertIn("wav", music["format"])
        self.assertIsNone(audio.normalize_music(None))
        # Values the server computed are recomputed, never trusted.
        again = audio.normalize_music({**music, "sha256": "0" * 64, "duration": 99})
        self.assertEqual(again, music)

    def test_music_path_and_values_are_validated(self):
        text = self.root / "notes.txt"
        text.write_text("not audio", encoding="utf-8")
        video_only = self.root / "silent.mp4"
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x64:rate=10:duration=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(video_only),
        )
        for path in (
            "//server/share/bed.wav",
            "\\\\server\\share\\bed.wav",
            "http://example.test/bed.mp3",
            "concat:a.wav|b.wav",
            str(self.root / "missing.wav"),
            str(text),
            str(video_only),
            "",
        ):
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                audio.normalize_music({"path": path})
        good = {"path": str(self.music)}
        for bad in (
            "bed.wav",
            [],
            {},
            {**good, "volume_db": 20},
            {**good, "volume_db": True},
            {**good, "volume_db": float("nan")},
            {**good, "duck_db": 1},
            {**good, "duck_db": 80},
            {**good, "fade_in": -1},
            {**good, "fade_out": 1000},
            {**good, "loop": "yes"},
            {**good, "duck": 1},
            {**good, "start_offset": -2},
            {**good, "start_offset": 3},  # at or beyond the end of the file
            {**good, "source_note": "x" * 2001},
            {**good, "source_note": "bad\x00note"},
            {**good, "url": "https://example.test"},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                audio.normalize_music(bad)
        with patch.object(audio, "MUSIC_MAX_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "larger"):
                audio.normalize_music(good)

    def test_sfx_and_voice_cleanup_are_validated(self):
        click = self.root / "click.wav"
        make_tone(click, 5000, 0.2)
        sfx = audio.normalize_cut_sfx({"path": str(click)})
        self.assertEqual(sfx["path"], str(click.resolve()))
        self.assertLessEqual(sfx["volume_db"], 0)
        self.assertEqual(len(sfx["sha256"]), 64)
        long = self.root / "long.wav"
        make_tone(long, 500, 12)
        for bad in (
            {"path": str(long)},
            {"path": str(click), "volume_db": 30},
            {"path": str(click), "extra": 1},
            {"path": "//server/click.wav"},
        ):
            with self.subTest(bad=bad), self.assertRaises((ValueError, OSError)):
                audio.normalize_cut_sfx(bad)
        for value in ("off", "light", "strong"):
            self.assertEqual(audio.validate_voice_cleanup(value), value)
        for bad in ("max", None, 1, True, "LIGHT"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                audio.validate_voice_cleanup(bad)

    def test_cleanup_presets_use_builtin_filters_only(self):
        self.assertEqual(audio.cleanup_filters("off"), [])
        light = ",".join(audio.cleanup_filters("light"))
        strong = ",".join(audio.cleanup_filters("strong"))
        for chain in (light, strong):
            self.assertIn("highpass=f=80", chain)
            self.assertIn("afftdn=", chain)
            self.assertIn("acompressor=", chain)
        self.assertIn("deesser", strong)
        self.assertNotIn("arnndn", light + strong)


class CleanupLatencyTests(unittest.TestCase):
    """The clean-up chain must not move audio by even one sample."""

    def test_cleanup_chain_has_no_delay(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy is a dev dependency")

        def render(chain):
            data = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "anoisesrc=d=4:r=48000:c=white:a=0.3:s=7,highpass=f=100,lowpass=f=8000",
                    "-af",
                    chain,
                    "-f",
                    "f32le",
                    "-ac",
                    "1",
                    "-ar",
                    "48000",
                    "-",
                ],
                capture_output=True,
                check=True,
                timeout=120,
            ).stdout
            return np.frombuffer(data, dtype=np.float32)

        reference = render("anull")
        for level in ("light", "strong"):
            with self.subTest(level=level):
                processed = render(",".join(audio.cleanup_filters(level)))
                self.assertEqual(len(processed), len(reference))
                middle = reference[48000:-48000]
                scores = [
                    float(
                        np.dot(
                            middle,
                            processed[48000 + lag : len(processed) - 48000 + lag],
                        )
                    )
                    for lag in range(-50, 2500)
                ]
                self.assertEqual(int(np.argmax(scores)) - 50, 0)


class SpeechDetectionTests(unittest.TestCase):
    def test_speech_intervals_follow_levels_with_hangover(self):
        levels = []
        for index in range(200):  # 10 s of 50 ms windows
            time = index * 0.05
            speaking = 1 <= time < 3 or 3.2 <= time < 4 or 6 <= time < 8
            levels.append((time, -20.0 if speaking else -70.0))
        intervals = audio.speech_intervals(levels, 0.05)
        # The 0.2 s gap is bridged; the 2 s pause is kept.
        self.assertEqual(len(intervals), 2)
        self.assertAlmostEqual(intervals[0][0], 1.0, places=2)
        self.assertAlmostEqual(intervals[0][1], 4.0, places=2)
        self.assertAlmostEqual(intervals[1][0], 6.0, places=2)
        self.assertEqual(audio.speech_intervals([(0, -120.0)] * 3, 0.05), [])

    def test_envelope_reaches_the_full_depth_before_speech(self):
        gain = audio.envelope_gain([(2.0, 3.0)], 15)
        self.assertAlmostEqual(gain(0.5), 1.0)
        self.assertAlmostEqual(20 * math.log10(gain(2.0)), -15, places=3)
        self.assertAlmostEqual(20 * math.log10(gain(2.9)), -15, places=3)
        self.assertGreater(gain(1.9), gain(2.0))
        self.assertAlmostEqual(gain(5.0), 1.0)


class MixRenderTests(_MediaCase):
    """Synthetic speech and music through the real FFmpeg export."""

    def setUp(self):
        super().setUp()
        self.source = self.root / "talk.mp4"
        make_source(self.source)
        self.music = self.root / "bed.wav"
        make_tone(self.music, 1500, 20)
        self.music_bytes = self.music.read_bytes()

    def export(self, name, audio_settings, platform="youtube_shorts", **extra):
        settings = {"preset": "preview", "timeout": 600, **extra}
        if platform:
            settings["platform"] = platform
        if audio_settings is not None:
            settings["audio"] = audio_settings
        output = self.root / name
        result = pp.export_video(self.source, SEGMENTS, output, settings)
        return output, result

    def music_spec(self, **values):
        return {"music": audio.normalize_music({"path": str(self.music), **values})}

    def test_music_ducks_under_speech_and_mix_meets_the_platform_target(self):
        output, result = self.export(
            "ducked.mp4", self.music_spec(fade_in=0.2, fade_out=0.2)
        )
        report = result["audio_mix"]["music"]
        self.assertTrue(report["present"])
        self.assertGreaterEqual(report["ducking"]["depth_db"], 12, report)
        self.assertGreaterEqual(report["ducking"]["speech_windows"], 10)
        self.assertGreaterEqual(report["ducking"]["pause_windows"], 10)
        # Independent measurement: the music band of the delivered file.
        levels = band_levels(output, 1500)
        depth = mean_db(levels, PAUSES) - mean_db(levels, SPEECH)
        self.assertGreaterEqual(depth, 12, depth)
        integrated, peak = loudness(output)
        self.assertLessEqual(abs(integrated - -14), 0.5, integrated)
        self.assertLessEqual(peak, -1 + 0.3)
        self.assertEqual(result["audio_normalization"]["target_lufs"], -14)
        self.assertEqual(
            result["audio_normalization"]["method"], "two-pass measured loudnorm"
        )
        durations = stream_durations(output)
        self.assertLessEqual(abs(durations["audio"] - PROGRAM), 1 / 30, durations)
        self.assertLessEqual(abs(durations["video"] - PROGRAM), 1 / 30, durations)
        # Mixing keeps speech exactly where the plain render of the edit has it.
        assert_same_onsets(self, output, plain_render(self.source, self.root, "p.mp4"))
        self.assertEqual(self.music.read_bytes(), self.music_bytes)
        # QA reports presence, measured depth and loudness against the target.
        qa = pp.quality_report(
            output,
            {
                "platform": "youtube_shorts",
                "preset": "preview",
                "audio_mix": result["audio_mix"],
            },
        )
        checks = {check["name"]: check for check in qa["checks"]}
        self.assertEqual(checks["music"]["status"], "pass", checks["music"])
        self.assertTrue(checks["music"]["detail"]["present"])
        self.assertGreaterEqual(checks["music"]["detail"]["depth_db"], 12)
        self.assertEqual(
            checks["mix_loudness"]["status"], "pass", checks["mix_loudness"]
        )
        self.assertLessEqual(checks["mix_loudness"]["detail"]["tolerance_lu"], 0.5)

    def test_loop_or_pad_to_program_length_with_fades(self):
        short = self.root / "short.wav"
        make_tone(short, 1500, 2)
        # Gated test tones leave codec residue in the music band without any music.
        plain = plain_render(self.source, self.root, "plain.mp4")
        floor = mean_db(band_levels(plain, 1500), [(6.0, 7.5)], margin=0)
        for loop in (True, False):
            with self.subTest(loop=loop):
                spec = {
                    "music": audio.normalize_music(
                        {
                            "path": str(short),
                            "loop": loop,
                            "duck": False,
                            "fade_in": 0.5,
                            "fade_out": 0.5,
                        }
                    )
                }
                output, result = self.export(f"loop-{loop}.mp4", spec, platform=None)
                levels = band_levels(output, 1500)
                late = mean_db(levels, [(6.0, 7.5)], margin=0)
                if loop:
                    self.assertGreater(late, -45, late)
                    self.assertGreater(late, floor + 30, (late, floor))
                else:
                    # Without looping, the music ends: nothing above the plain floor.
                    self.assertLessEqual(late, floor + 1, (late, floor))
                # Fades at both ends.
                first = [level for time, level in levels if time < 0.05]
                self.assertLess(
                    max(first), mean_db(levels, [(1.0, 1.4)], margin=0) - 10
                )
                self.assertLessEqual(
                    abs(stream_durations(output)["audio"] - PROGRAM), 1 / 30
                )
                self.assertIsNone(result["audio_mix"]["music"]["ducking"])

    def test_custom_mix_keeps_the_custom_loudness_target(self):
        output, result = self.export("custom.mp4", self.music_spec(), platform=None)
        integrated, _ = loudness(output)
        self.assertLessEqual(abs(integrated - -16), 0.5, integrated)
        self.assertEqual(result["audio_normalization"]["target_lufs"], -16)
        self.assertEqual(result["audio_normalization"]["true_peak_db"], -1.5)

    def test_without_audio_settings_the_graph_is_unchanged(self):
        scripts = []
        real = pp._render_graph

        def capture(arguments, *, cwd, timeout):
            script = arguments[arguments.index("-/filter_complex") + 1]
            scripts.append((Path(cwd) / script).read_text(encoding="utf-8"))
            return real(arguments, cwd=cwd, timeout=timeout)

        with patch.object(pp, "_render_graph", capture):
            _, result = self.export("plain.mp4", None, platform=None)
        self.assertNotIn("audio_mix", result)
        render = scripts[-1]
        self.assertIn("[audio]loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=", render)
        for word in ("amix", "afftdn", "amultiply", "highpass"):
            self.assertNotIn(word, "".join(scripts))
        self.assertIsNone(pp._settings({})["audio"])

    def test_cut_sound_effect_lands_on_each_cut(self):
        click = self.root / "click.wav"
        make_tone(click, 5000, 0.2)
        spec = {
            "cut_sfx": audio.normalize_cut_sfx({"path": str(click), "volume_db": -6})
        }
        output, result = self.export("sfx.mp4", spec, platform=None)
        self.assertEqual(result["audio_mix"]["cut_sfx"]["cuts"], [2.5])
        levels = band_levels(output, 5000)
        self.assertGreater(
            mean_db(levels, [(2.5, 2.7)], margin=0.02),
            mean_db(levels, [(0.5, 2.3), (3.0, 8.0)], margin=0) + 30,
        )
        self.assertLessEqual(abs(stream_durations(output)["audio"] - PROGRAM), 1 / 30)

    def test_qa_compares_ducking_with_the_requested_depth(self):
        output, _ = self.export("qa.mp4", None, platform=None)

        def status(depth, requested):
            mix = {
                "music": {
                    "present": True,
                    "ducking": {"depth_db": depth, "requested_db": requested},
                }
            }
            qa = pp.quality_report(output, {"preset": "preview", "audio_mix": mix})
            return {check["name"]: check for check in qa["checks"]}["music"]["status"]

        self.assertEqual(status(18.7, 18), "pass")
        self.assertEqual(status(17.6, 18), "pass")
        self.assertEqual(status(13.0, 18), "warning")
        self.assertEqual(status(11.9, 12), "warning")
        self.assertEqual(status(12.4, 12), "pass")

    def test_music_file_that_changed_after_review_is_refused(self):
        spec = self.music_spec()
        self.music.write_bytes(self.music_bytes[:-4000])
        with self.assertRaisesRegex(PermissionError, "Music file changed"):
            self.export("changed.mp4", spec)
        self.assertFalse((self.root / "changed.mp4").exists())


class TruePeakHeadroomTests(_MediaCase):
    """loudnorm only applies a linear gain when the gained true peak fits under the limit.

    Otherwise FFmpeg silently switches to dynamic mode, misses the target and the
    report must not claim a measured two-pass result.
    """

    def test_linear_gain_must_fit_under_the_true_peak_limit(self):
        settings = {"loudness_lufs": -14, "true_peak_db": -1}
        self.assertTrue(
            pp._linear_fits({"input_i": -24.0, "input_tp": -11.0}, settings)
        )
        self.assertFalse(
            pp._linear_fits({"input_i": -24.0, "input_tp": -10.9}, settings)
        )
        # Measured on a real voice clean-up mix: +9.4 dB would put the peak at +0.21 dBTP.
        self.assertFalse(
            pp._linear_fits({"input_i": -23.4, "input_tp": -9.19}, settings)
        )

    def make_peaky_source(self, path):
        # Quiet speech with short transients about 19 dB above its loudness, like
        # plosives: linear gain to -14 LUFS would push those peaks over -1 dBTP.
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30:duration=12",
            "-filter_complex",
            "sine=f=200:r=48000:d=12[a];sine=f=400:r=48000:d=12[b];"
            "[a][b]amix=inputs=2,volume='0.25*if(lt(mod(t,3),1.5),1,0)':eval=frame[s];"
            "sine=f=1000:r=48000:d=12,volume='if(lt(mod(t,1),0.004),0.9,0)':eval=frame[c];"
            "[s][c]amix=inputs=2:normalize=0[speech]",
            "-map",
            "0:v",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-map",
            "[speech]",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            "12",
            str(path),
        )

    def test_mix_without_peak_headroom_is_limited_then_gained_linearly(self):
        source = self.root / "peaky.mp4"
        self.make_peaky_source(source)
        output = self.root / "limited.mp4"
        # A nearly silent bed sends the program through the mix path unchanged.
        bed = self.root / "bed.wav"
        make_tone(bed, 1500, 20)
        mix = {
            "music": audio.normalize_music(
                {"path": str(bed), "volume_db": -60, "duck": False}
            )
        }
        result = pp.export_video(
            source,
            SEGMENTS,
            output,
            {
                "preset": "preview",
                "timeout": 600,
                "platform": "youtube_shorts",
                "audio": mix,
            },
        )
        self.assertEqual(
            result["audio_normalization"]["method"],
            "two-pass measured loudnorm (true-peak limited)",
        )
        integrated, peak = loudness(output)
        self.assertLessEqual(abs(integrated - -14), 0.5, integrated)
        self.assertLessEqual(peak, -1 + 0.3, peak)
        self.assertLessEqual(abs(stream_durations(output)["audio"] - PROGRAM), 1 / 30)
        # Limiting must not move speech.
        assert_same_onsets(self, output, plain_render(source, self.root, "plain.mp4"))

    def test_plain_render_reports_a_dynamic_fallback_honestly(self):
        source = self.root / "peaky.mp4"
        self.make_peaky_source(source)
        result = pp.export_video(
            source,
            SEGMENTS,
            self.root / "plain-peaky.mp4",
            {"preset": "preview", "timeout": 600, "platform": "youtube_shorts"},
        )
        self.assertEqual(
            result["audio_normalization"]["method"],
            "dynamic loudnorm (linear gain would exceed the true-peak limit)",
        )


class VoiceCleanupRenderTests(_MediaCase):
    def test_cleanup_lowers_hum_and_noise_and_keeps_sync(self):
        source = self.root / "noisy.mp4"
        make_source(source, noise=True)
        results, outputs = {}, {}
        for level in ("off", "light", "strong"):
            output = self.root / f"clean-{level}.mp4"
            settings = {"preset": "preview", "timeout": 600}
            if level != "off":
                settings["audio"] = {"voice_cleanup": level}
            result = pp.export_video(source, SEGMENTS, output, settings)
            outputs[level] = output
            if level != "off":
                self.assertEqual(result["audio_mix"]["voice_cleanup"], level)
            hum = mean_db(band_levels(output, 50, q=4), PAUSES)
            hiss = mean_db(band_levels(output, 6000, q=2), PAUSES)
            speech = band_levels(output, 200)
            results[level] = (hum, hiss, speech)
            self.assertLessEqual(
                abs(stream_durations(output)["audio"] - PROGRAM), 1 / 30
            )
        for level in ("light", "strong"):
            hum, hiss, speech = results[level]
            self.assertLess(hum, results["off"][0] - 10, (level, hum))
            self.assertLess(hiss, results["off"][1] - 3, (level, hiss))
            # The FFT denoiser's latency is compensated: no shift against "off".
            assert_same_onsets(self, outputs[level], outputs["off"])


def _probe(duration=12.0):
    return {"duration": duration, "width": 320, "height": 180, "has_audio": True}


class StudioAudioSettingsTests(_MediaCase):
    def setUp(self):
        super().setUp()
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"unit source fixture")
        probe = patch("cutroom.studio.probe", return_value=_probe())
        probe.start()
        self.addCleanup(probe.stop)
        self.music = self.root / "bed.wav"
        make_tone(self.music, 1500, 3)
        self.click = self.root / "click.wav"
        make_tone(self.click, 5000, 0.2)
        self.studio = Studio(self.root / "workspace")
        self.project = self.studio.create(self.source, name="Talk")

    def settings(self, changes):
        project = self.studio.get(self.project["id"])
        return self.studio.update(
            project["id"], {"settings": changes}, project["revision"]
        )

    def test_settings_are_validated_normalised_and_off_by_default(self):
        legacy = self.studio.get(self.project["id"])
        for key in ("music", "voice_cleanup", "cut_sfx"):
            self.assertNotIn(key, legacy["settings"])
        self.assertNotIn("audio", self.studio._render_settings(legacy, "preview"))
        updated = self.settings(
            {
                "music": {"path": str(self.music), "source_note": "CC0, own recording"},
                "voice_cleanup": "light",
                "cut_sfx": {"path": str(self.click)},
            }
        )
        music = updated["settings"]["music"]
        self.assertEqual(
            music["sha256"], hashlib.sha256(self.music.read_bytes()).hexdigest()
        )
        self.assertEqual(music["source_note"], "CC0, own recording")
        render = self.studio._render_settings(updated, "preview")["audio"]
        self.assertEqual(render["voice_cleanup"], "light")
        self.assertEqual(render["music"]["path"], music["path"])
        self.assertEqual(
            render["cut_sfx"]["sha256"], updated["settings"]["cut_sfx"]["sha256"]
        )
        revision = updated["revision"]
        for bad in (
            {"music": {"path": "//server/share/bed.wav"}},
            {"music": {"path": str(self.root / "missing.wav")}},
            {"music": {"path": str(self.music), "duck_db": 0}},
            {"voice_cleanup": "maximum"},
            {"cut_sfx": {"path": "https://example.test/click.wav"}},
            {"music": "C:/bed.wav"},
        ):
            with self.subTest(bad=bad), self.assertRaises((ValueError, OSError)):
                self.settings(bad)
        self.assertEqual(self.studio.get(self.project["id"])["revision"], revision)
        off = self.settings({"music": None, "voice_cleanup": "off", "cut_sfx": None})
        self.assertNotIn("music", off["settings"])
        self.assertNotIn("cut_sfx", off["settings"])
        self.assertNotIn("audio", self.studio._render_settings(off, "preview"))

    def test_music_and_sfx_files_are_part_of_the_digest(self):
        self.settings(
            {"music": {"path": str(self.music)}, "cut_sfx": {"path": str(self.click)}}
        )
        review = self.studio.review(self.project["id"])
        self.studio.approve(self.project["id"], review["digest"])
        self.assertEqual(
            self.studio.review(self.project["id"])["digest"], review["digest"]
        )
        original = self.music.read_bytes()
        self.music.write_bytes(original[:-200])
        changed = self.studio.review(self.project["id"])["digest"]
        self.assertNotEqual(changed, review["digest"])
        with self.assertRaises(PermissionError):
            self.studio.submit(self.project["id"], "final", {})
        with self.assertRaisesRegex(PermissionError, "Music file changed"):
            self.studio.submit(self.project["id"], "preview", {})
        self.music.write_bytes(original)
        self.assertEqual(
            self.studio.review(self.project["id"])["digest"], review["digest"]
        )
        self.click.write_bytes(self.click.read_bytes() + b"\0\0")
        self.assertNotEqual(
            self.studio.review(self.project["id"])["digest"], review["digest"]
        )
        with self.assertRaisesRegex(PermissionError, "Sound effect file changed"):
            self.studio.submit(self.project["id"], "preview", {})
        self.click.unlink()
        with self.assertRaises(MissingAssetError):
            self.studio.review(self.project["id"])

    def test_derive_copies_music_and_voice_settings(self):
        self.settings(
            {
                "music": {"path": str(self.music), "volume_db": -20, "duck_db": 18},
                "voice_cleanup": "strong",
                "cut_sfx": {"path": str(self.click), "volume_db": -9},
            }
        )
        parent = self.studio.get(self.project["id"])
        child = self.studio.derive(parent["id"], "tiktok")
        for key in ("music", "voice_cleanup", "cut_sfx"):
            self.assertEqual(child["settings"][key], parent["settings"][key])
        self.assertEqual(
            self.studio._render_settings(child, "preview")["audio"],
            self.studio._render_settings(parent, "preview")["audio"],
        )

    def test_agent_tool_may_set_a_music_path(self):
        from cutroom import studio_tools

        with patch.object(studio_tools, "get_studio", return_value=self.studio):
            result = json.loads(
                studio_tools.project_handler(
                    {
                        "action": "update",
                        "project_id": self.project["id"],
                        "revision": self.project["revision"],
                        "changes": {"settings": {"music": {"path": str(self.music)}}},
                    }
                )
            )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["status"], "draft")
        description = json.dumps(studio_tools.definitions())
        self.assertIn("settings.music", description)
        self.assertIn("hashed", description)


class StudioAudioJobTests(unittest.TestCase):
    """A platform project with music renders, and QA reports the mix."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "talk.mp4"
        make_source(self.source)
        self.music = self.root / "bed.wav"
        make_tone(self.music, 1500, 20)
        self.studio = Studio(self.root / "workspace")

    def tearDown(self):
        from cutroom.studio import _CHILD_PROCESSES

        for job_id, process in list(_CHILD_PROCESSES.items()):
            try:
                process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                process.kill()
            _CHILD_PROCESSES.pop(job_id, None)

    def run_job(self, project_id, action):
        import time

        job = self.studio.submit(project_id, action, {})
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            job = self.studio.job(job["id"])
            if job["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "completed", job)
        return job

    def test_preview_and_qa_report_music_ducking_and_loudness(self):
        project = self.studio.create(self.source, name="Talk")
        project = self.studio.update(
            project["id"],
            {
                "settings": {
                    "platform": "youtube_shorts",
                    "music": {"path": str(self.music), "fade_in": 0.2, "fade_out": 0.2},
                    "voice_cleanup": "light",
                },
                "segments": SEGMENTS,
            },
            project["revision"],
        )
        preview = self.run_job(project["id"], "preview")
        self.assertGreaterEqual(
            preview["result"]["audio_mix"]["music"]["ducking"]["depth_db"], 12
        )
        qa = self.run_job(project["id"], "qa")
        checks = {check["name"]: check for check in qa["result"]["checks"]}
        self.assertEqual(checks["music"]["status"], "pass", checks["music"])
        self.assertEqual(
            checks["mix_loudness"]["status"], "pass", checks["mix_loudness"]
        )
        self.assertEqual(checks["platform_loudness"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
