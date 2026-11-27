"""The Studio player streams a fragmented copy of a render; the render itself stays a plain MP4."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom import postproduction as pp
from cutroom.media import stream_info, streaming_copy


def top_boxes(path):
    """Top-level MP4 box names in file order."""
    names, data, offset = [], Path(path).read_bytes(), 0
    while offset + 8 <= len(data):
        size = int.from_bytes(data[offset : offset + 4], "big")
        names.append(data[offset + 4 : offset + 8].decode("latin-1"))
        if size == 1:
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
        if size < 8:
            break
        offset += size
    return names


def frame_count(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    return int(json.loads(out.stdout)["streams"][0]["nb_read_frames"])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class StreamingPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"), prefix="streaming-")
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "talk.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=7",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=7", "-shortest",
             "-c:v", "libx264", "-preset", "ultrafast", "-g", "300", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cls.source)],
            check=True, timeout=120,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def render(self, preset):
        output = self.root / f"{preset}-{self.id().rsplit('.', 1)[-1]}.mp4"  # Exports never overwrite.
        pp.export_video(self.source, [{"start": 0, "end": 7}], output,
                        settings={"preset": preset, "aspect": "source", "timeout": 300, "normalize_audio": False})
        return output

    def keyframes(self, path):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey", "-show_entries", "frame=pts_time", "-of", "json", str(path)],
            check=True, capture_output=True, text=True, timeout=60,
        )
        return [float(frame["pts_time"]) for frame in json.loads(out.stdout)["frames"]]

    def test_preview_stays_plain_with_a_keyframe_every_two_seconds(self):
        # Plain MP4 keeps the edit list that lines sound up exactly; keyframes keep streaming pieces small.
        preview = self.render("preview")
        boxes = top_boxes(preview)
        self.assertNotIn("moof", boxes)
        self.assertLess(boxes.index("moov"), boxes.index("mdat"))
        times = self.keyframes(preview)
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertTrue(gaps and max(gaps) <= 2.05, gaps)
        self.assertFalse(stream_info(preview)["fragmented"])

    def test_the_streaming_copy_is_fragmented_cached_and_keeps_every_frame(self):
        preview = self.render("preview")
        cache = self.root / "cache"
        copy = streaming_copy(preview, cache, "a" * 64)
        boxes = top_boxes(copy)
        self.assertEqual(boxes[:2], ["ftyp", "moov"], boxes)
        self.assertGreaterEqual(boxes.count("moof"), 3, "Small pieces, so playback starts early")
        info = stream_info(copy)
        self.assertTrue(info["fragmented"])
        self.assertRegex(info["codecs"], r"^avc1\.[0-9a-f]{6},mp4a\.40\.2$")
        self.assertEqual(frame_count(copy), frame_count(preview), "A copy, not a new encode")
        with patch("cutroom.media._run") as run:
            self.assertEqual(streaming_copy(preview, cache, "a" * 64), copy)
            run.assert_not_called()
        for digest in "bcdef":
            streaming_copy(preview, cache, digest * 64)
        self.assertLessEqual(len(list(cache.glob("*.mp4"))), 4, "The cache stays small")
        self.assertFalse(list(cache.glob(".*")), "No half-written files are left")
        with self.assertRaises(ValueError):
            streaming_copy(preview, cache, "../escape")

    def test_final_stays_a_plain_mp4_for_upload(self):
        final = self.render("final")
        boxes = top_boxes(final)
        self.assertNotIn("moof", boxes)
        self.assertLess(boxes.index("moov"), boxes.index("mdat"), "Moov first, as before")
        self.assertFalse(stream_info(final)["fragmented"])


if __name__ == "__main__":
    unittest.main()
