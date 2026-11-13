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
        if index - last > 24000:
            found.append(index / 48000)
        last = index
    return found


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

    def check(self, name, settings, segments=None, minimum=13):
        segments = segments or [
            {"start": 0.0, "end": 6.0},
            {"start": 7.0, "end": 13.0},
            {"start": 14.2, "end": 19.0},
        ]
        output = self.root / name
        pp.export_video(
            self.source,
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
            abs(durations["audio"] - durations["video"]), 0.001, durations
        )
        found = offsets(output, self.expected)
        self.assertGreaterEqual(len(found), minimum, found)
        for offset in found:
            self.assertLessEqual(
                abs(offset - self.expected), TOLERANCE, (self.expected, found)
            )

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
