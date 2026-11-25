"""Preview/Final renders draw the split explainer layout (pixel checks on real FFmpeg output)."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cutroom import layouts
from cutroom import postproduction as pp

BLUE = (32, 96, 192)


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=120)


def frame(path, at, width=1080, height=1920):
    data = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True, timeout=60,
    ).stdout
    assert len(data) == width * height * 3, len(data)
    return lambda x, y: tuple(data[(y * width + x) * 3:(y * width + x) * 3 + 3])


def near(colour, expected, slack=18):
    return all(abs(a - b) <= slack for a, b in zip(colour, expected))


def hex_rgb(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
class SplitRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"), prefix="layout-render-")
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "talk.mp4"
        ffmpeg(
            "-f", "lavfi", "-i", "color=c=0x2060C0:size=640x360:rate=30:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cls.source),
        )
        cls.picture = cls.root / "diagram.png"
        ffmpeg("-f", "lavfi", "-i", "color=c=0xE02020:size=400x300", "-frames:v", "1", str(cls.picture))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def render(self, layout, segments, name):
        output = self.root / name
        result = pp.export_video(
            self.source,
            segments,
            output,
            settings={"platform": "youtube_shorts", "preset": "preview", "aspect": "portrait", "timeout": 300, "layout": layouts.normalize_layout(layout, duration=3)},
        )
        return output, result

    def test_split_frame_has_paper_card_speaker_and_rounded_corners(self):
        output, result = self.render(
            {
                "layout": "split",
                "headline": {"l1": "CLIMATE CHANGE IS", "l2": "NOT COMPLICATED", "boxed": [1]},
                "panel": {"kind": "card", "type": "title", "text": "Hello"},
                "pictures": [{"start": 2.0, "end": 2.5, "item": {"kind": "card", "type": "number", "text": "15", "detail": "minutes"}}],
            },
            [{"start": 0, "end": 1.0}, {"start": 1.5, "end": 3.0}],
            "split.mp4",
        )
        self.assertEqual((result["width"], result["height"]), (1080, 1920))
        self.assertIn("layout", result["effects"])
        self.assertEqual(result["layout"]["layout"], "split")
        geo = layouts.geometry({"layout": "split"})
        panel, speaker = geo["panel"], geo["speaker"]
        pixel = frame(output, 0.5)
        paper = hex_rgb(layouts.PALETTE["paper_paper"])
        self.assertTrue(near(pixel(20, 20), paper), pixel(20, 20))
        self.assertTrue(near(pixel(panel["x"] + 30, panel["y"] + 30), (255, 255, 255)), pixel(panel["x"] + 30, panel["y"] + 30))
        self.assertTrue(near(pixel(540, speaker["y"] + speaker["h"] // 2), BLUE, 24), pixel(540, speaker["y"] + speaker["h"] // 2))
        self.assertTrue(near(pixel(speaker["x"] + 2, speaker["y"] + 2), paper), "Speaker card corners are rounded")
        ink = hex_rgb(layouts.PALETTE["paper_ink"])
        self.assertTrue(any(near(pixel(x, y), ink, 40) for y in range(300, 420, 3) for x in range(100, 980, 3)), "Headline line 1 is drawn")
        box = hex_rgb(layouts.PALETTE["box"])
        self.assertTrue(any(near(pixel(x, y), box, 30) for y in range(380, 520, 3) for x in range(100, 980, 3)), "A headline word sits in the yellow box")
        # Source 2.0-2.5 s is program 1.5-2.0 s after the cut: the number card replaces the title.
        later = frame(output, 1.75)
        centre = (540, panel["y"] + panel["h"] // 2 - 40)
        self.assertTrue(any(near(later(x, y), box, 30) for y in range(centre[1] - 120, centre[1] + 40, 4) for x in range(300, 780, 4)), "Timed number card shows")
        self.assertFalse(any(near(pixel(x, y), box, 30) for y in range(centre[1] - 120, centre[1] + 40, 4) for x in range(300, 780, 4)), "Not before its words")

    def test_a_local_picture_fills_the_top_panel(self):
        output, _ = self.render({"layout": "split", "background": "dark", "panel": {"kind": "file", "path": str(self.picture)}}, [{"start": 0, "end": 2}], "picture.mp4")
        geo = layouts.geometry({"layout": "split"})["panel"]
        pixel = frame(output, 1.0)
        self.assertTrue(near(pixel(540, geo["y"] + geo["h"] // 2), (224, 32, 32), 30), pixel(540, geo["y"] + geo["h"] // 2))
        self.assertTrue(near(pixel(20, 20), hex_rgb(layouts.PALETTE["dark_paper"])), pixel(20, 20))

    def test_picture_over_you_puts_the_card_on_the_full_frame_speaker(self):
        output, result = self.render({"layout": "over", "panel": {"kind": "card", "type": "quote", "text": "Short"}}, [{"start": 0, "end": 2}], "over.mp4")
        panel = layouts.geometry({"layout": "over"})["panel"]
        pixel = frame(output, 1.0)
        self.assertTrue(near(pixel(panel["x"] + 30, panel["y"] + 30), (255, 255, 255)), pixel(panel["x"] + 30, panel["y"] + 30))
        for point in ((20, 20), (540, 1700), (1060, 1900)):
            self.assertTrue(near(pixel(*point), BLUE, 24), (point, pixel(*point)))
        self.assertEqual(result["layout"]["layout"], "over")

    def test_a_panel_file_changed_after_it_was_chosen_is_refused(self):
        picture = self.root / "changing.png"
        ffmpeg("-f", "lavfi", "-i", "color=c=0x20E020:size=200x100", "-frames:v", "1", str(picture))
        layout = layouts.normalize_layout({"layout": "split", "panel": {"kind": "file", "path": str(picture)}}, duration=3)
        ffmpeg("-f", "lavfi", "-i", "color=c=0x2020E0:size=200x100", "-frames:v", "1", str(picture))
        with self.assertRaisesRegex(ValueError, "changed"):
            pp.export_video(self.source, [{"start": 0, "end": 1}], self.root / "changed.mp4",
                            settings={"platform": "youtube_shorts", "preset": "preview", "aspect": "portrait", "layout": layout})

    def test_speaker_crop_keeps_the_face_inside_without_empty_edges(self):
        crop = layouts.speaker_crop(1920, 1080, 1032, 726, face=(0.632, 0.33))
        self.assertLessEqual(crop["x"] + crop["w"], 1920)
        self.assertLessEqual(crop["y"] + crop["h"], 1080)
        self.assertGreaterEqual(min(crop["x"], crop["y"]), 0)
        self.assertAlmostEqual(crop["w"] / crop["h"], 1032 / 726, delta=0.02)
        self.assertTrue(crop["x"] < 0.632 * 1920 < crop["x"] + crop["w"])
        self.assertEqual(layouts.program_times([(0, 1), (1.5, 3)], 2.0, 2.5), [(1.5, 2.0)])
        self.assertEqual(layouts.program_times([(0, 1), (1.5, 3)], 0.5, 2.0), [(0.5, 1.0), (1.0, 1.5)])


class StudioPreviewTests(unittest.TestCase):
    """Studio job path: settings.layout -> preview job worker -> rendered file."""

    def test_a_preview_job_draws_the_saved_layout(self):
        import time

        from cutroom.studio import _CHILD_PROCESSES, Studio

        temporary = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"), prefix="layout-job-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source, picture = root / "talk.mp4", root / "diagram.png"
        ffmpeg("-f", "lavfi", "-i", "color=c=0x2060C0:size=640x360:rate=30:duration=3", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
               "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source))
        ffmpeg("-f", "lavfi", "-i", "color=c=0xE02020:size=400x300", "-frames:v", "1", str(picture))
        studio = Studio(root / "workspace")
        project = studio.create(source)
        project = studio.update(project["id"], {"settings": {"platform": "youtube_shorts", "layout": {"layout": "split", "panel": {"kind": "file", "path": str(picture)}}}}, project["revision"])
        job = studio.submit(project["id"], "preview", {})
        deadline = time.monotonic() + 300
        while studio.job(job["id"])["status"] not in {"completed", "failed", "cancelled"}:
            self.assertLess(time.monotonic(), deadline, "Preview job did not finish")
            time.sleep(0.1)
        process = _CHILD_PROCESSES.pop(job["id"], None)
        if process is not None:
            process.wait(timeout=60)
        finished = studio.job(job["id"])
        self.assertEqual(finished["status"], "completed", finished.get("error"))
        output = studio.get(project["id"])["artifacts"]["preview"]
        geo = layouts.geometry({"layout": "split"})["panel"]
        pixel = frame(output, 1.0)
        self.assertTrue(near(pixel(540, geo["y"] + geo["h"] // 2), (224, 32, 32), 30), pixel(540, geo["y"] + geo["h"] // 2))
        self.assertTrue(near(pixel(20, 20), hex_rgb(layouts.PALETTE["paper_paper"])), pixel(20, 20))


if __name__ == "__main__":
    unittest.main()
