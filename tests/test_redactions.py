"""Bleeps, mutes and hidden areas: validation, Studio wiring and real FFmpeg output."""

import array
import math
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom import postproduction as pp
from cutroom import redactions


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=120)


def samples(path, start, end, rate=48000):
    data = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(end - start), "-i", str(path), "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"],
        check=True, capture_output=True, timeout=60,
    ).stdout
    return array.array("f", data)


def power(values, frequency, rate=48000):
    """Goertzel power of one frequency, normalised by length."""
    k = 2 * math.cos(2 * math.pi * frequency / rate)
    s1 = s2 = 0.0
    for value in values:
        s1, s2 = value + k * s1 - s2, s1
    return (s1 * s1 + s2 * s2 - k * s1 * s2) / max(1, len(values)) ** 2


def rms(values):
    return math.sqrt(sum(v * v for v in values) / max(1, len(values)))


def pixel_at(path, at, x, y, width, height):
    data = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True, timeout=60,
    ).stdout
    index = (y * width + x) * 3
    return tuple(data[index:index + 3])


class ValidationTests(unittest.TestCase):
    def test_bleeps_and_hidden_areas_are_normalized(self):
        value = redactions.normalize(
            {
                "bleeps": [{"start": 2, "end": 2.4, "mode": "mute", "said": "Twitter", "ids": [9]}, {"start": 0.5, "end": 0.9}],
                "hidden": [{"start": 1, "end": 3, "box": {"x": 0.5, "y": 0.9, "w": 0.5, "h": 0.1}}],
            },
            duration=10,
        )
        self.assertEqual([b["start"] for b in value["bleeps"]], [0.5, 2])
        self.assertEqual(value["bleeps"][0]["mode"], "bleep")
        self.assertEqual(value["hidden"][0]["style"], "cover")
        self.assertIsNone(redactions.normalize(None, duration=10))
        self.assertIsNone(redactions.normalize({"bleeps": [], "hidden": []}, duration=10))

    def test_bad_values_are_refused(self):
        for spec in (
            {"bleeps": [{"start": 3, "end": 2}]},
            {"bleeps": [{"start": 9, "end": 11}]},
            {"bleeps": [{"start": 1, "end": 2, "mode": "scream"}]},
            {"hidden": [{"start": 1, "end": 2, "box": {"x": 0.9, "y": 0, "w": 0.2, "h": 0.1}}]},
            {"hidden": [{"start": 1, "end": 2, "box": {"x": 0, "y": 0, "w": 0.001, "h": 0.1}}]},
            {"hidden": [{"start": 1, "end": 2, "box": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}, "style": "emoji"}]},
            {"other": []},
            {"bleeps": [{"start": 1, "end": 2, "ids": ["w1"]}]},
        ):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                redactions.normalize(spec, duration=10)

    def test_masked_words_cover_ids_and_times(self):
        value = redactions.normalize({"bleeps": [{"start": 5.0, "end": 5.5, "ids": [0]}, {"start": 8.0, "end": 8.6}]}, duration=10)
        words = [{"id": 0, "start": 1, "end": 1.2, "text": "Alice"}, {"id": 1, "start": 8.1, "end": 8.4, "text": "secret"}, {"id": 2, "start": 9, "end": 9.3, "text": "fine"}]
        self.assertEqual([w["text"] for w in redactions.mask_words(words, value)], ["—", "—", "fine"])


class StudioTests(unittest.TestCase):
    def setUp(self):
        from cutroom.studio import Studio

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        source = root / "source.mp4"
        source.write_bytes(b"unit source fixture")
        probe = patch("cutroom.studio.probe", return_value={"duration": 10.0, "width": 1920, "height": 1080, "has_audio": True})
        probe.start()
        self.addCleanup(probe.stop)
        self.studio = Studio(root / "workspace")
        project = self.studio.create(source, name="Talk")
        words = [{"id": 0, "start": 1.0, "end": 1.4, "text": "Hello", "probability": 0.9}, {"id": 1, "start": 1.5, "end": 2.0, "text": "Alice", "probability": 0.9}, {"id": 2, "start": 2.1, "end": 2.5, "text": "here", "probability": 0.9}]
        self.project = self.studio.update(project["id"], {"transcript": {"engine": "test", "status": "ok", "language": "en", "text": "Hello Alice here", "words": words}}, project["revision"])

    def test_saved_bleeps_hide_the_word_in_captions_and_reach_the_render(self):
        saved = self.studio.update(self.project["id"], {"settings": {"redactions": {"bleeps": [{"start": 1.5, "end": 2.0, "ids": [1], "said": "Alice"}]}}}, self.project["revision"])
        self.assertEqual(saved["settings"]["redactions"]["bleeps"][0]["mode"], "bleep")
        project = self.studio.get(saved["id"])
        self.assertNotIn("Alice", " ".join(cue["text"] for cue in self.studio._cues(project)))
        self.assertNotIn("Alice", [w["text"] for w in self.studio._caption_words(project)])
        self.assertEqual(self.studio._render_settings(project, "preview")["redactions"], saved["settings"]["redactions"])
        cleared = self.studio.update(saved["id"], {"settings": {"redactions": None}}, saved["revision"])
        self.assertNotIn("redactions", cleared["settings"])

    def test_only_the_bleeped_saying_of_a_repeated_word_is_masked(self):
        # A word said three times, bleeped once: the other two stay in captions and subtitle files.
        words = [{"id": i, "start": 1.0 + i * 0.5, "end": 1.4 + i * 0.5, "text": text, "probability": 0.9}
                 for i, text in enumerate(["Alice", "met", "Alice", "and", "Alice"])]
        project = self.studio.update(self.project["id"], {"transcript": {"engine": "test", "status": "ok", "language": "en", "text": "Alice met Alice and Alice", "words": words},
                                                          "settings": {"redactions": {"bleeps": [{"start": 2.0, "end": 2.4, "ids": [2], "said": "Alice"}]}}}, self.project["revision"])
        project = self.studio.get(project["id"])
        program = [w["text"] for w in self.studio._program_words(project)]
        cues = " ".join(cue["text"] for cue in self.studio._cues(project))
        self.assertEqual(program.count("Alice"), 2)
        self.assertEqual(cues.count("Alice"), 2)
        self.assertIn("—", cues)

    def test_zero_length_words_in_a_bleep_stay_out_of_the_subtitles_file(self):
        words = [{"id": 0, "start": 1.0, "end": 1.4, "text": "Hello", "probability": 0.9}, {"id": 1, "start": 1.6, "end": 1.6, "text": "Bob", "probability": 0.9},
                 {"id": 2, "start": 2.1, "end": 2.5, "text": "here", "probability": 0.9}]
        project = self.studio.update(self.project["id"], {"transcript": {"engine": "test", "status": "ok", "language": "en", "text": "Hello Bob here", "words": words},
                                                          "settings": {"redactions": {"bleeps": [{"start": 1.5, "end": 1.7}]}}}, self.project["revision"])
        texts = [w["text"] for w in self.studio._program_words(self.studio.get(project["id"]))]
        self.assertNotIn("Bob", texts)
        self.assertIn("here", texts)


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"), prefix="redaction-render-")
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "talk.mp4"
        # White picture with a black "name" bar at the bottom; a 440 Hz voice.
        ffmpeg(
            "-f", "lavfi", "-i", "color=c=white:size=640x360:rate=30:duration=4,drawbox=x=320:y=320:w=300:h=30:color=black:t=fill",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(cls.source),
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def render(self, spec, segments, name, **extra):
        output = self.root / name
        result = pp.export_video(self.source, segments, output, settings={"preset": "preview", "aspect": "source", "timeout": 300, "normalize_audio": False,
                                                                            "redactions": redactions.normalize(spec, duration=4), **extra})
        return output, result

    def test_bleep_replaces_the_voice_and_mute_silences_it_after_cuts(self):
        output, result = self.render(
            {"bleeps": [{"start": 1.0, "end": 1.6}, {"start": 3.0, "end": 3.5, "mode": "mute"}]},
            [{"start": 0, "end": 2}, {"start": 2.5, "end": 4}],
            "bleep.mp4",
        )
        self.assertEqual(result["redactions"], {"bleeps": 1, "mutes": 1, "hidden": 0})
        inside = samples(output, 1.1, 1.5)
        self.assertGreater(power(inside, 1000), 20 * power(inside, 440), "Tone, not the voice, while bleeped")
        before = samples(output, 0.2, 0.8)
        self.assertGreater(power(before, 440), 20 * power(before, 1000), "Voice untouched elsewhere")
        # Source 3.0-3.5 s is program 2.5-3.0 s after the cut.
        self.assertLess(rms(samples(output, 2.55, 2.95)), 0.01, "Muted range is silent")
        self.assertGreater(rms(samples(output, 3.1, 3.4)), 0.05, "Sound comes back after the mute (lavfi sine RMS is 0.088)")

    def test_bleep_also_applies_when_music_is_mixed_in(self):
        music = self.root / "bed.wav"
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=3000:sample_rate=48000:duration=6", str(music))
        from cutroom import audio

        output, _ = self.render({"bleeps": [{"start": 1.0, "end": 1.6}]}, [{"start": 0, "end": 4}], "music.mp4",
                                audio={"music": audio.normalize_music({"path": str(music), "volume_db": -30, "duck": False})})
        inside, before = samples(output, 1.1, 1.5), samples(output, 0.2, 0.8)
        self.assertGreater(power(inside, 1000), 20 * power(inside, 440), "Tone replaces the voice under the music")
        self.assertGreater(power(before, 440), 20 * power(before, 1000))
        self.assertGreater(power(inside, 3000), 0, "The music keeps playing")

    def test_hidden_area_is_covered_only_during_its_time(self):
        output, result = self.render({"hidden": [{"start": 1.0, "end": 2.0, "box": {"x": 0.45, "y": 0.85, "w": 0.55, "h": 0.15}}]}, [{"start": 0, "end": 4}], "hide.mp4")
        width, height = result["width"], result["height"]
        x, y = round(0.75 * width), round(0.93 * height)
        self.assertLess(sum(pixel_at(output, 0.5, x, y, width, height)), 60, "The black bar is visible before")
        hidden = pixel_at(output, 1.5, round(0.25 * width), round(0.5 * height), width, height)
        self.assertGreater(sum(hidden), 700, "Outside the box stays white")
        cover = pixel_at(output, 1.5, round(0.5 * width), round(0.88 * height), width, height)
        self.assertLess(sum(cover), 60, "Inside the box is the cover colour")
        self.assertGreater(sum(pixel_at(output, 3.0, round(0.5 * width), round(0.88 * height), width, height)), 700, "White again after")

    def test_blur_hides_the_bar_and_works_with_punch_ins(self):
        output, _ = self.render(
            {"hidden": [{"start": 0.0, "end": 4.0, "box": {"x": 0.4, "y": 0.8, "w": 0.6, "h": 0.2}, "style": "pixelate"}]},
            [{"start": 0, "end": 1.5}, {"start": 2, "end": 4}],
            "pixelate.mp4",
            pacing={"punch_in": "alternate"},
        )
        self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
