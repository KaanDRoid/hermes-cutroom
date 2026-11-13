"""Regression tests for the F4 audio review: envelope cost, loop offset, short
music endings, delivered true peak, honest music QA and relative asset paths."""

import array
import os
import subprocess
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from cutroom import audio
from cutroom import postproduction as pp
from cutroom.studio import Studio

try:
    from .test_audio_mix import SEGMENTS, ffmpeg, loudness, make_source, make_tone
except ImportError:  # unittest discover -s tests imports modules top-level
    from test_audio_mix import SEGMENTS, ffmpeg, loudness, make_source, make_tone

RATE = 48000


def _numpy(case):
    try:
        import numpy as np
    except ImportError:
        case.skipTest("numpy is a dev dependency")
    return np


def _pcm(np, path):
    data = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1"]
        + ["-ar", "48000", "-"],
        capture_output=True,
        check=True,
        timeout=300,
    ).stdout
    return np.frombuffer(data, dtype=np.float32).astype(np.float64)


def _rms_db(np, samples, start, end):
    part = samples[int(start * RATE) : int(end * RATE)]
    return float(20 * np.log10(max(np.sqrt(np.mean(part**2)), 1e-9)))


def _dominant(np, samples, start, end):
    part = samples[int(start * RATE) : int(end * RATE)]
    spectrum = np.abs(np.fft.rfft(part * np.hanning(len(part))))
    return float(np.fft.rfftfreq(len(part), 1 / RATE)[np.argmax(spectrum)])


class _Case(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)


def _concat(chunks, typecode):
    result = array.array(typecode)
    for chunk in chunks:
        result.extend(chunk)
    return result


class DuckEnvelopeTests(_Case):
    # Sample-aligned speech windows, as the 50 ms level meter produces them;
    # they include a ramp before the program start, overlapping release/attack
    # ramps between close intervals, and an interval past the program end.
    INTERVALS = [
        (0.05, 0.5),
        (0.8, 1.6),
        (1.9, 2.0),
        (3.0, 4.2),
        (4.45, 5.0),
        (6.0, 6.05),
        (9.8, 10.2),
    ]

    def test_envelope_matches_the_reference_on_a_short_case(self):
        depth = 12.75
        count = 10 * RATE
        reference = audio.envelope_gain(self.INTERVALS, depth)
        gains = _concat(
            audio.envelope_chunks(self.INTERVALS, depth, count, typecode="d"), "d"
        )
        self.assertEqual(len(gains), count)
        worst = max(abs(gains[i] - reference(i / RATE)) for i in range(count))
        self.assertLessEqual(worst, 1e-6)
        samples = _concat(audio.envelope_chunks(self.INTERVALS, depth, count), "h")
        self.assertEqual(samples.tolist(), [round(32767 * g) for g in gains])
        # Unsorted input describes the same envelope.
        shuffled = list(reversed(self.INTERVALS))
        again = _concat(audio.envelope_chunks(shuffled, depth, count), "h")
        self.assertEqual(again, samples)

    def test_thirty_minute_program_with_750_intervals_is_fast(self):
        count = 1800 * RATE
        intervals = [(i * 2.4, i * 2.4 + 1.2) for i in range(750)]
        path = self.root / "envelope.wav"
        started = time.perf_counter()
        audio.write_envelope(
            path, intervals, 12.75, count, deadline=time.monotonic() + 60
        )
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 5, elapsed)
        reference = audio.envelope_gain(intervals, 12.75)
        with wave.open(str(path), "rb") as stream:
            self.assertEqual(stream.getnframes(), count)
            self.assertEqual(stream.getframerate(), RATE)
            for second in (0.0, 1.0, 1.29, 1.33, 1300.5, 1799.99):
                index = round(second * RATE)
                stream.setpos(index)
                value = array.array("h", stream.readframes(1))[0]
                self.assertEqual(value, round(32767 * reference(index / RATE)))

    def test_envelope_stops_at_the_deadline(self):
        intervals = [(i * 2.4, i * 2.4 + 1.2) for i in range(750)]
        with self.assertRaises(subprocess.TimeoutExpired):
            audio.write_envelope(
                self.root / "late.wav",
                intervals,
                12.75,
                1800 * RATE,
                deadline=time.monotonic() - 1,
            )

    def test_prepare_mix_with_many_speech_runs_stays_within_its_timeout(self):
        voice = self.root / "voice.wav"
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='0.1*sin(2*PI*1000*t)*lt(mod(t\\,2)\\,1.2)':s=48000:d=120",
            str(voice),
        )
        bed = self.root / "bed.wav"
        make_tone(bed, 100, 12)
        spec = audio.validate_settings({"music": {"path": str(bed), "duck_db": 12}})
        work = self.root / "work"
        work.mkdir()
        started = time.perf_counter()
        _, report = audio.prepare_mix(
            voice,
            ["[0:a:0]anull[audio]"],
            work,
            120.0,
            spec,
            [(0, 120)],
            has_audio=True,
            timeout=30,
        )
        self.assertLess(time.perf_counter() - started, 30)
        self.assertEqual(len(report["music"]["ducking"]["intervals"]), 60)
        self.assertGreaterEqual(report["music"]["ducking"]["depth_db"], 12)


class MusicSegmentTests(_Case):
    def stem(self, music, program, name):
        work = self.root / name
        work.mkdir()
        spec = audio.validate_settings({"music": music})
        audio.prepare_mix(
            None, [], work, program, spec, [(0, program)], has_audio=False, timeout=120
        )
        return work / "music.wav"

    def test_loop_repeats_the_segment_from_the_start_offset(self):
        np = _numpy(self)
        two = self.root / "two-tone.wav"
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='0.3*sin(2*PI*if(lt(t\\,2)\\,200\\,800)*t)':s=48000:d=4",
            str(two),
        )
        music = dict(path=str(two), start_offset=2.0, loop=True, volume_db=0)
        samples = _pcm(np, self.stem({**music, "fade_in": 0, "fade_out": 0}, 10.0, "a"))
        self.assertEqual(len(samples), 10 * RATE)
        found = [round(_dominant(np, samples, s, s + 0.5)) for s in range(10)]
        self.assertEqual(found, [800] * 10)

    def test_short_music_without_loop_fades_out_where_it_ends(self):
        np = _numpy(self)
        short = self.root / "short.wav"
        ffmpeg("-f", "lavfi", "-i", "sine=f=300:r=48000:d=3", str(short))
        music = dict(path=str(short), loop=False, fade_in=0, fade_out=2, volume_db=0)
        samples = _pcm(np, self.stem(music, 10.0, "b"))
        self.assertEqual(len(samples), 10 * RATE)
        full = _rms_db(np, samples, 0.5, 1.0)
        # The fade runs 1 s .. 3 s and falls steadily to the end of the music.
        windows = [_rms_db(np, samples, 1.0 + i / 10, 1.1 + i / 10) for i in range(20)]
        for a, b in zip(windows, windows[1:]):
            self.assertLess(b, a + 0.01, windows)
        self.assertLess(windows[-1], full - 15, windows)
        self.assertLess(_rms_db(np, samples, 2.99, 3.0), full - 35)
        self.assertLess(_rms_db(np, samples, 3.0, 10.0), -100)

    def test_short_music_without_fade_still_avoids_a_click(self):
        np = _numpy(self)
        short = self.root / "short.wav"
        ffmpeg("-f", "lavfi", "-i", "sine=f=300:r=48000:d=4", str(short))
        music = dict(
            path=str(short),
            loop=False,
            fade_in=0,
            fade_out=0,
            volume_db=0,
            start_offset=1.0,
        )
        samples = _pcm(np, self.stem(music, 10.0, "c"))
        full = _rms_db(np, samples, 0.5, 1.0)
        # The music (3 s after the offset) ends at 3 s with a short fade.
        self.assertGreater(_rms_db(np, samples, 2.9, 2.95), full - 1)
        self.assertLess(_rms_db(np, samples, 2.998, 3.0), full - 15)
        self.assertLess(_rms_db(np, samples, 3.0, 10.0), -100)


class DeliveredTruePeakTests(_Case):
    def test_loud_crest_music_is_delivered_under_minus_one_dbtp(self):
        source = self.root / "talk.mp4"
        make_source(source)
        crest = self.root / "crest.wav"
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='0.95*sin(2*PI*60*t)*lt(mod(t\\,0.5)\\,0.02)"
            "+0.05*sin(2*PI*300*t)':s=48000:d=60",
            str(crest),
        )
        spec = audio.validate_settings(
            {"music": {"path": str(crest), "volume_db": 0, "duck_db": 15}}
        )
        output = self.root / "crest.mp4"
        result = pp.export_video(
            source,
            SEGMENTS,
            output,
            {
                "preset": "preview",
                "timeout": 600,
                "platform": "instagram_reels",
                "audio": spec,
            },
        )
        integrated, peak = loudness(output)
        self.assertLessEqual(peak, -1.0, (integrated, peak))
        self.assertLessEqual(abs(integrated - -14), 0.5, integrated)
        delivered = result["audio_normalization"]["delivered_true_peak_db"]
        self.assertLessEqual(delivered, -1.0)
        qa = pp.quality_report(
            output,
            {
                "platform": "instagram_reels",
                "preset": "preview",
                "audio_mix": result["audio_mix"],
            },
        )
        checks = {check["name"]: check for check in qa["checks"]}
        for name in ("audio_loudness", "platform_loudness", "mix_loudness"):
            self.assertEqual(checks[name]["status"], "pass", checks[name])
            self.assertEqual(checks[name]["detail"]["true_peak_dbfs"], peak)

    def test_qa_warns_when_the_true_peak_is_over_the_target(self):
        # About -14 LUFS of tone with sparse bursts reaching about -0.7 dBTP.
        video = self.root / "hot.mkv"
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30:duration=6",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='0.27*sin(2*PI*1000*t)"
            "+0.65*sin(2*PI*1000*t)*lt(mod(t\\,0.5)\\,0.003)':s=48000:d=6",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "pcm_s24le",
            "-shortest",
            str(video),
        )
        integrated, peak = loudness(video)
        self.assertLessEqual(abs(integrated - -14), 1, integrated)
        self.assertGreater(peak, -1.0, peak)
        self.assertLess(peak, -0.5, peak)
        qa = pp.quality_report(video, {"platform": "instagram_reels"})
        checks = {check["name"]: check for check in qa["checks"]}
        self.assertEqual(checks["audio_loudness"]["status"], "warning")
        self.assertEqual(checks["platform_loudness"]["status"], "warning")


class MusicQaLabelTests(_Case):
    def test_music_check_is_labelled_as_render_stage_evidence(self):
        video = self.root / "plain.mkv"
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:r=48000:d=2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-shortest",
            str(video),
        )
        mix = {
            "music": {"present": True, "ducking": {"depth_db": 15, "requested_db": 12}}
        }
        qa = pp.quality_report(video, {"preset": "preview", "audio_mix": mix})
        detail = {c["name"]: c for c in qa["checks"]}["music"]["detail"]
        self.assertEqual(detail["stage"], "render")
        self.assertIn("not measured on the delivered file", detail["method"])


class RelativeAssetPathTests(_Case):
    def setUp(self):
        super().setUp()
        self.music = self.root / "bed.wav"
        make_tone(self.music, 1500, 3)
        previous = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)

    def test_relative_music_and_sound_paths_are_refused(self):
        for normalize in (audio.normalize_music, audio.normalize_cut_sfx):
            for path in ("bed.wav", "./bed.wav", "sub/../bed.wav"):
                with self.subTest(normalize=normalize.__name__, path=path):
                    with self.assertRaisesRegex(ValueError, "absolute"):
                        normalize({"path": path})
        # The absolute path of the same file is accepted.
        self.assertTrue(audio.normalize_music({"path": str(self.music)})["sha256"])

    def test_studio_refuses_a_relative_music_path(self):
        source = self.root / "source.mp4"
        source.write_bytes(b"unit source fixture")
        probe = {"duration": 12.0, "width": 320, "height": 180, "has_audio": True}
        with patch("cutroom.studio.probe", return_value=probe):
            studio = Studio(self.root / "workspace")
            project = studio.create(source, name="Talk")
            with self.assertRaisesRegex(ValueError, "absolute"):
                studio.update(
                    project["id"],
                    {"settings": {"music": {"path": "bed.wav"}}},
                    project["revision"],
                )


if __name__ == "__main__":
    unittest.main()
