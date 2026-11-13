"""Absolute audio/video sync across frame-aligned cuts.

The source has a white frame every 30 frames and a click in the audio at a fixed
offset from it, with the video stream starting 7 ms after the audio (as in many
WebM and phone recordings). Every kept range must keep that offset exactly.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from cutroom import audio
from cutroom import postproduction as pp

FPS = 30000 / 1001
PERIOD = 30 / FPS
TOLERANCE = 0.0005  # seconds; well under one audio frame of any codec used here


def ffmpeg(*args, cwd=None):
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", *args],
        check=True,
        cwd=cwd,
        timeout=300,
    )


def flashes(path):
    path = Path(path)
    ffmpeg(
        "-copyts",
        "-i",
        path.name,
        "-vf",
        "signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG:file=yavg.txt",
        "-f",
        "null",
        "-",
        cwd=path.parent,
    )
    result, time = [], None
    for line in (path.parent / "yavg.txt").read_text(encoding="utf-8").splitlines():
        if "pts_time:" in line:
            time = float(line.split("pts_time:")[1].split()[0])
        elif "YAVG=" in line and time is not None and float(line.split("=")[1]) > 200:
            result.append(time)
    return result


def clicks(path):
    import numpy as np

    data = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
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
        timeout=300,
    ).stdout
    samples = np.abs(np.frombuffer(data, dtype=np.float32))
    found, last = [], -48000
    for index in np.flatnonzero(samples > samples.max() * 0.3):
        # Separate short bursts even when a cut puts two source clicks within
        # one video frame. A half-second refractory window hides the second one.
        if index - last > 480:
            found.append(index / 48000)
        last = index
    # Raw PCM has no timestamps; restore the first decoded sample's source PTS.
    # Stream start is not sufficient because it may include codec priming.
    decoded = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-read_intervals",
                "%+0.1",
                "-show_frames",
                "-show_entries",
                "frame=pts_time",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
    )["frames"]
    origin = float(decoded[0]["pts_time"])
    return [origin + timestamp for timestamp in found]


def offsets(path, expected=0.0):
    # A flash whose click would fall before the program start (or inside codec
    # start-up) has no click to pair with.
    heard = clicks(path)
    return [
        min(heard, key=lambda c: abs(c - flash)) - flash
        for flash in flashes(path)
        if flash + expected > 0.02
    ]


class AudioVideoSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import numpy  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("numpy is a dev dependency")
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        video, sound = root / "v.webm", root / "a.wav"
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x96:r=30000/1001:d=20,format=yuv420p,"
            "drawbox=c=white:t=fill:enable='eq(mod(n\\,30)\\,0)'",
            "-c:v",
            "libvpx-vp9",
            "-deadline",
            "realtime",
            "-cpu-used",
            "8",
            str(video),
        )
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc='if(lt(mod(t\\,{PERIOD:.9f})\\,0.003)\\,0.8*sin(2*PI*1000*t)\\,0)':s=48000:d=20",
            str(sound),
        )
        cls.source = root / "source.webm"
        ffmpeg(
            "-itsoffset",
            "0.007",
            "-i",
            str(video),
            "-i",
            str(sound),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-c:a",
            "libopus",
            str(cls.source),
        )
        cls.bed = root / "bed.wav"
        ffmpeg("-f", "lavfi", "-i", "sine=f=1500:r=48000:d=20", str(cls.bed))
        cls.root = root
        source_offsets = offsets(cls.source)
        cls.expected = sum(source_offsets) / len(source_offsets)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def check(
        self,
        name,
        settings,
        segments=None,
        minimum=13,
        source=None,
        expected=None,
        end_tolerance=0.001,
    ):
        expected = self.expected if expected is None else expected
        segments = segments or [
            {"start": 0.0, "end": 6.0},
            {"start": 7.0, "end": 13.0},
            {"start": 14.2, "end": 19.0},
        ]
        output = self.root / name
        pp.export_video(
            source or self.source,
            segments,
            output,
            {"preset": "preview", "timeout": 600, "normalize_audio": False, **settings},
        )
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
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            ).stdout
        )["streams"]
        durations = {
            stream["codec_type"]: float(stream["duration"]) for stream in streams
        }
        # The sound track ends with the last kept frame, not before it.
        self.assertLessEqual(
            abs(durations["audio"] - durations["video"]), end_tolerance, durations
        )
        found = offsets(output, expected)
        self.assertGreaterEqual(len(found), minimum, found)
        for offset in found:
            self.assertLessEqual(abs(offset - expected), TOLERANCE, (expected, found))

    def dropped_frames_source(self):
        """Ten frames lost mid-recording; the stream header still reads as CFR."""
        dropped = self.root / "dropped.webm"
        if not dropped.exists():
            ffmpeg(
                "-i",
                str(self.source),
                "-map",
                "0:v",
                "-map",
                "0:a",
                "-vf",
                "select='not(between(n\\,200\\,209))'",
                "-fps_mode",
                "passthrough",
                "-c:v",
                "libvpx-vp9",
                "-deadline",
                "realtime",
                "-cpu-used",
                "8",
                "-c:a",
                "copy",
                str(dropped),
            )
        return dropped

    def test_dropped_frames_keep_sync_after_the_gap(self):
        dropped = self.dropped_frames_source()
        video = next(
            s for s in pp._probe(dropped)["streams"] if s["codec_type"] == "video"
        )
        # The case that matters: frame counts cannot be derived from times here,
        # although the header looks like constant-rate video.
        self.assertEqual(video["r_frame_rate"], video["avg_frame_rate"])
        measured = offsets(dropped)
        expected = sum(measured) / len(measured)
        for value in measured:
            self.assertLessEqual(abs(value - expected), TOLERANCE, measured)
        self.check(
            "dropped-plain.mp4",
            {},
            source=dropped,
            minimum=12,
            expected=expected,
        )

    def test_many_cuts_on_unevenly_timed_video_do_not_drift(self):
        dropped = self.dropped_frames_source()
        measured = offsets(dropped)
        expected = sum(measured) / len(measured)
        segments = [
            {"start": round(0.37 + 1.43 * k, 3), "end": round(1.21 + 1.43 * k, 3)}
            for k in range(12)
        ]
        self.check(
            "dropped-many.mp4",
            {},
            segments,
            source=dropped,
            minimum=5,
            expected=expected,
        )

    def test_irregular_frame_times_stay_within_half_a_frame_without_drift(self):
        irregular = self.root / "irregular.mkv"
        if not irregular.exists():
            # Lost frames, then every third frame 8 ms late, as in many phone
            # recordings.
            ffmpeg(
                "-i",
                str(self.source),
                "-map",
                "0:v",
                "-map",
                "0:a",
                "-vf",
                "select='not(between(n\\,200\\,209))',"
                "setpts='PTS+if(eq(mod(N\\,3)\\,1)\\,0.008/TB\\,0)'",
                "-fps_mode",
                "passthrough",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "copy",
                str(irregular),
            )
        info = pp._probe(irregular)
        times = pp._video_frame_times(irregular, pp._timeline(info)[0])
        self.assertFalse(pp._evenly_spaced(times, "30000/1001"), "Time-based path")
        segments = [
            {"start": round(0.37 + 1.43 * k, 3), "end": round(1.21 + 1.43 * k, 3)}
            for k in range(12)
        ]
        output = self.root / "irregular-many.mp4"
        pp.export_video(
            irregular,
            segments,
            output,
            {"preset": "preview", "normalize_audio": False},
        )
        measured = offsets(irregular)
        expected = sum(measured) / len(measured)
        found = offsets(output, expected)
        self.assertGreaterEqual(len(found), 5, found)
        errors = [value - expected for value in found]
        # Bounded by half an output frame (plus the source's own lateness)...
        for error in errors:
            self.assertLessEqual(abs(error), 0.5 / FPS + 0.008 + TOLERANCE, errors)
        # ...and not growing with the number of cuts.
        half = len(errors) // 2
        early = sum(errors[:half]) / half
        late = sum(errors[half:]) / (len(errors) - half)
        self.assertLessEqual(abs(late - early), 0.5 / FPS, errors)

    def test_crops_on_dropped_frames_cover_every_output_frame(self):
        dropped = self.dropped_frames_source()
        settings = {
            "preset": "preview",
            "normalize_audio": False,
            "aspect": "portrait",
            "framing": "center_crop",
        }
        output = self.root / "dropped-crop.mp4"
        result = pp.export_video(
            dropped,
            [{"start": 5.2, "end": 9.4}, {"start": 11.0, "end": 14.0}],
            output,
            settings,
        )
        framing = result["framing"]
        # The kept range spans the lost frames: their slots repeat a frame.
        self.assertGreater(framing["output_frames"], framing["frames"])
        report = pp.quality_report(output, {**settings, "framing_report": framing})
        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(
            checks["framing_frames"]["status"], "pass", checks["framing_frames"]
        )
        streams = pp._probe(output)["streams"]
        durations = {s["codec_type"]: float(s["duration"]) for s in streams}
        self.assertLessEqual(
            abs(durations["audio"] - durations["video"]), 0.001, durations
        )

    def test_sound_that_starts_after_the_picture_keeps_sync_from_the_start(self):
        late = self.root / "late-sound.webm"
        if not late.exists():
            ffmpeg(
                "-i",
                str(self.source),
                "-itsoffset",
                "0.05",
                "-i",
                str(self.source),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c",
                "copy",
                str(late),
            )
        measured = offsets(late)
        expected = sum(measured) / len(measured)
        for value in measured:
            self.assertLessEqual(abs(value - expected), TOLERANCE, measured)
        for name, source in (("late", late), ("late-dropped", None)):
            if source is None:
                source = self.root / "late-dropped.webm"
                if not source.exists():
                    ffmpeg(
                        "-i",
                        str(self.dropped_frames_source()),
                        "-itsoffset",
                        "0.05",
                        "-i",
                        str(self.dropped_frames_source()),
                        "-map",
                        "0:v",
                        "-map",
                        "1:a",
                        "-c",
                        "copy",
                        str(source),
                    )
                measured = offsets(source)
                expected = sum(measured) / len(measured)
            with self.subTest(source=name):
                self.check(
                    f"{name}-start.mp4",
                    {},
                    [{"start": 0.0, "end": 6.0}, {"start": 7.0, "end": 13.0}],
                    source=source,
                    minimum=10,
                    expected=expected,
                )

    def test_transitions_refuse_sources_with_dropped_frames(self):
        dropped = self.dropped_frames_source()
        with self.assertRaisesRegex(ValueError, "constant-rate"):
            pp.export_video(
                dropped,
                [{"start": 0.0, "end": 6.0}, {"start": 7.0, "end": 13.0}],
                self.root / "dropped-crossfade.mp4",
                {
                    "preset": "preview",
                    "normalize_audio": False,
                    "pacing": {"transition": "crossfade"},
                },
            )

    def test_positive_starts_keep_sync_across_cuts_and_fragments(self):
        shifted = self.root / "positive.webm"
        ffmpeg(
            "-i",
            str(self.source),
            "-map",
            "0",
            "-c",
            "copy",
            "-output_ts_offset",
            "0.2",
            str(shifted),
        )
        for value in offsets(shifted):
            self.assertLessEqual(abs(value - self.expected), TOLERANCE)
        segments = [
            {"start": 0.0, "end": 0.004},  # dropped, but kept in cumulative budget
            {"start": 0.01, "end": 6.0},
            {"start": 7.0, "end": 7.004},
            {"start": 7.01, "end": 13.0},
            {"start": 14.2, "end": 19.0},
        ]
        for kind in ("cut", "crossfade", "dip"):
            with self.subTest(kind=kind):
                self.check(
                    f"positive-{kind}.mp4",
                    {"pacing": {"transition": kind}},
                    segments,
                    minimum=11,
                    source=shifted,
                )

    def test_short_ranges_before_a_transition_keep_exact_frame_count(self):
        segments = [
            {"start": 0.0, "end": 1 / FPS},
            {"start": 0.1, "end": 0.1 + 1 / FPS},
            {"start": 0.3, "end": 0.3 + 10 / FPS},
            {"start": 1.0, "end": 2.0},
        ]
        for kind in ("crossfade", "dip"):
            with self.subTest(kind=kind):
                output = self.root / f"short-{kind}.mp4"
                result = pp.export_video(
                    self.source,
                    segments,
                    output,
                    {
                        "preset": "preview",
                        "normalize_audio": False,
                        "pacing": {"transition": kind},
                    },
                )
                report = result["pacing"]
                self.assertEqual(report["frames"], 42)
                self.assertEqual(len(report["skipped_transitions"]), 1)
                streams = pp._probe(output)["streams"]
                video = next(s for s in streams if s["codec_type"] == "video")
                self.assertEqual(int(video["nb_frames"]), 42)

    def test_click_detector_keeps_distinct_bursts_near_a_cut(self):
        path = self.root / "near-clicks.wav"
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='if(between(t,0.1,0.103)+between(t,0.133,0.136),"
            "0.8*sin(2*PI*1000*t),0)':s=48000:d=0.3",
            str(path),
        )
        found = clicks(path)
        self.assertEqual(len(found), 2, found)
        for actual, expected in zip(found, (0.1, 0.133)):
            self.assertLessEqual(abs(actual - expected), 0.0001)

    def test_plain_render_keeps_the_source_offset_in_every_range(self):
        for name, settings in (
            ("plain.mp4", {}),
            ("plain-normalized.mp4", {"normalize_audio": True}),
        ):
            with self.subTest(name):
                self.check(name, settings)

    def test_mixed_render_keeps_the_source_offset_in_every_range(self):
        bed = audio.normalize_music(
            {"path": str(self.bed), "volume_db": -60, "duck": False}
        )
        self.check("mix.mp4", {"audio": {"music": bed}})

    def test_many_sub_frame_cuts_do_not_drift(self):
        # Twelve ranges with cut points between frames; any per-cut error would add up.
        segments = [
            {
                "start": round(index * 1.6 + 0.0123 * index, 6),
                "end": round(index * 1.6 + 0.0123 * index + 1.2, 6),
            }
            for index in range(12)
        ]
        bed = audio.normalize_music(
            {"path": str(self.bed), "volume_db": -60, "duck": False}
        )
        for name, settings in (
            ("many-plain.mp4", {}),
            ("many-mix.mp4", {"audio": {"music": bed}}),
        ):
            with self.subTest(name):
                self.check(name, settings, segments, minimum=10)

    def test_transitions_and_punch_ins_keep_the_source_offset(self):
        # Transitions are built from handles, so every kept frame stays where a
        # plain cut puts it and the sound is not shifted.
        for name, pacing in (
            ("crossfade.mp4", {"transition": "crossfade", "punch_in": "alternate"}),
            ("dip.mp4", {"transition": "dip", "transition_duration": 0.4}),
        ):
            with self.subTest(name):
                self.check(name, {"pacing": pacing}, minimum=11)

    def test_many_cuts_with_crossfades_do_not_drift(self):
        segments = [
            {
                "start": round(index * 1.6 + 0.0123 * index, 6),
                "end": round(index * 1.6 + 0.0123 * index + 1.2, 6),
            }
            for index in range(12)
        ]
        self.check(
            "many-crossfade.mp4",
            {"pacing": {"transition": "crossfade", "punch_in": "alternate"}},
            segments,
            minimum=9,
        )


if __name__ == "__main__":
    unittest.main()
