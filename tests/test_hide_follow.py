"""A hidden area can follow what is inside it (a face, a scrolling page), and says when it loses it."""

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom import postproduction as pp
from cutroom import redactions

HAS_CV = importlib.util.find_spec("cv2") is not None and importlib.util.find_spec("numpy") is not None
W, H = 640, 360


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=120)


def frame(path, at):
    data = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1", "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True, capture_output=True, timeout=60,
    ).stdout
    assert len(data) == W * H, len(data)  # Renders may be larger; they are read back at source size.
    return lambda x, y: data[y * W + x]


def bright(pixel, x0, y0, x1, y1):
    return sum(1 for y in range(y0, y1, 2) for x in range(x0, x1, 2) if pixel(x, y) > 200)


def square_x(t):
    return 100 + 100 * t  # Where the moving square's left edge is at t (see setUpClass).


class FollowSpecTests(unittest.TestCase):
    def test_follow_is_kept_only_when_asked_for(self):
        box = {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}
        spec = redactions.normalize({"hidden": [{"start": 0, "end": 1, "box": box, "follow": True},
                                                {"start": 1, "end": 2, "box": box}]}, duration=5)
        self.assertTrue(spec["hidden"][0]["follow"])
        self.assertNotIn("follow", spec["hidden"][1], "Older projects keep the same shape")
        with self.assertRaises(ValueError):
            redactions.normalize({"hidden": [{"start": 0, "end": 1, "box": box, "follow": "yes"}]}, duration=5)
        drawn = redactions.normalize({"hidden": [{"start": 1, "end": 3, "box": box, "follow": True, "at": 2.5}]}, duration=5)
        self.assertEqual(drawn["hidden"][0]["at"], 2.5, "The moment the box was drawn on")
        late = redactions.normalize({"hidden": [{"start": 1, "end": 3, "box": box, "at": 9}]}, duration=5)
        self.assertEqual(late["hidden"][0]["at"], 3, "Kept inside the range")
        with self.assertRaisesRegex(ValueError, "30 seconds"):
            redactions.normalize({"hidden": [{"start": 0, "end": 31, "box": box, "follow": True}]}, duration=60)
        with self.assertRaisesRegex(ValueError, "10 hidden areas"):
            redactions.normalize({"hidden": [{"start": i, "end": i + 1, "box": box, "follow": True} for i in range(11)]}, duration=60)

    def test_a_path_becomes_a_time_expression_that_hits_every_sample(self):
        times = [i / 30 for i in range(91)]
        values = [square_x(t) for t in times]
        expression = redactions.time_expression(times, values)
        self.assertLess(len(expression), 400, "A straight line needs few pieces")
        for t, value in zip(times, values):
            env = {"t": t}
            got = eval(expression.replace("if(", "_if(").replace("lt(", "_lt("), {"_if": lambda c, a, b: a if c else b, "_lt": lambda a, b: a < b}, env)
            self.assertAlmostEqual(got, value, delta=1.0)


@unittest.skipUnless(shutil.which("ffmpeg") and HAS_CV, "FFmpeg and OpenCV are required")
class FollowRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"), prefix="hide-follow-")
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "moving.mp4"
        # A white square with a grey cross moves right 100 px a second on a dark, noisy wall; it is gone after 2.6 s.
        ffmpeg(
            "-f", "lavfi", "-i", f"color=c=0x202020:size={W}x{H}:rate=30:duration=3.5",
            "-f", "lavfi", "-i", "color=c=white:size=60x60:rate=30:duration=3.5",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3.5",
            "-filter_complex",
            # drawbox cannot move with time, so the square is an overlay.
            "[1]drawbox=x=26:y=0:w=8:h=60:color=gray:t=fill,drawbox=x=0:y=26:w=60:h=8:color=gray:t=fill[square];"
            "[0][square]overlay=x='100+100*t':y=140:enable='lt(t,2.6)':shortest=1[v]",
            "-map", "[v]", "-map", "2:a", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(cls.source),
        )
        cls.box = {"x": 92 / W, "y": 132 / H, "w": 76 / W, "h": 76 / H}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_the_tracker_follows_the_square_and_says_when_it_is_gone(self):
        from cutroom import tracking

        path = tracking.follow_box(self.source, self.box, 0.0, 3.4)
        for t, x in zip(path["times"], path["x"]):
            if t < 2.5:
                self.assertAlmostEqual(x * W, square_x(t) - 8, delta=5, msg=f"at {t:.2f} s")
        self.assertEqual(len(path["lost"]), 1, path["lost"])
        start, end = path["lost"][0]
        self.assertAlmostEqual(start, 2.6, delta=0.1)
        self.assertAlmostEqual(end, 3.4, delta=0.1)
        held = [x for t, x in zip(path["times"], path["x"]) if t > 2.7]
        self.assertTrue(held and max(held) - min(held) < 1e-9, "A lost box stays where it last was")

    def test_tracking_limit_marks_the_unread_tail_as_lost(self):
        from cutroom import tracking

        real = tracking._frames

        def short(*args):
            # A reader that stops after three frames, as a failing decoder would.
            times, data, size, rate = real(*args)
            return times[:3], data[: 3 * size[0] * size[1]], size, rate

        with patch.object(tracking, "_frames", short):
            path = tracking.follow_box(self.source, self.box, 0.0, 2.0)
        self.assertEqual(path["lost"], [[round(path["times"][-1], 3), 2.0]])

    def test_a_plain_area_cannot_be_followed(self):
        from cutroom import tracking

        flat = self.root / "flat.mp4"
        ffmpeg("-f", "lavfi", "-i", f"color=c=0x404040:size={W}x{H}:rate=30:duration=1", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(flat))
        path = tracking.follow_box(flat, self.box, 0.0, 1.0)
        self.assertEqual(path["lost"], [[0.0, 1.0]], "Nothing to follow: the whole span is flagged")

    def render(self, name, follow, style="cover"):
        output = self.root / name
        hidden = {"start": 0.0, "end": 3.4, "box": self.box, "style": style}
        if follow:
            hidden["follow"] = True
        result = pp.export_video(
            self.source, [{"start": 0.0, "end": 3.4}], output,
            settings={"preset": "preview", "aspect": "source", "timeout": 300, "normalize_audio": False,
                      "redactions": {"bleeps": [], "hidden": [hidden]}},
        )
        return output, result

    def difference(self, path, t):
        """Mean grey-level difference from the source inside the square at t."""
        a, b, x = frame(path, t), frame(self.source, t), int(square_x(t))
        points = [(px, py) for py in range(142, 198, 2) for px in range(x + 2, x + 58, 2)]
        return sum(abs(a(px, py) - b(px, py)) for px, py in points) / len(points)

    def test_a_followed_cover_box_hides_the_square_as_it_moves(self):
        still, _ = self.render("still.mp4", follow=False)
        self.assertLess(self.difference(still, 2.2), 12, "A box that stays put leaves the moved square visible")
        moving, result = self.render("moving-cover.mp4", follow=True)
        for t in (0.3, 1.2, 2.2):
            x = int(square_x(t))
            self.assertEqual(bright(frame(moving, t), x + 2, 142, x + 58, 198), 0, f"square shows at {t} s")
        report = result["redactions"]
        self.assertEqual(report["followed"], 1)
        self.assertEqual(len(report["lost"]), 1)
        self.assertAlmostEqual(report["lost"][0]["start"], 2.6, delta=0.1)

    def test_loss_covers_the_entire_source_frame(self):
        # A tracker can lose a target without it leaving the frame. Use the flat area as the seed.
        self.box = {"x": 0.01, "y": 0.01, "w": 0.08, "h": 0.08}
        moving, result = self.render("lost-cover.mp4", follow=True)
        pixel = frame(moving, 1.2)
        self.assertEqual(bright(pixel, 222, 142, 278, 198), 0)
        self.assertEqual(result["redactions"]["lost"][0]["start"], 0)

    def test_a_followed_pixelate_box_moves_too(self):
        moving, _ = self.render("moving-pixel.mp4", follow=True, style="pixelate")
        for t in (0.5, 2.0):
            self.assertGreater(self.difference(moving, t), 20, f"not pixelated at {t} s")


    def make(self, name, filters, duration=3.5):
        path = self.root / name
        ffmpeg(
            "-f", "lavfi", "-i", f"color=c=0x202020:size={W}x{H}:rate=30:duration={duration}",
            "-f", "lavfi", "-i", "color=c=white:size=60x60:rate=30:duration=4",
            "-filter_complex", filters,
            "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path),
        )
        return path

    def test_a_square_that_changes_width_never_shows(self):
        # A fixed-size box cannot cover something that grows; it must give up and cover everything.
        breathing = self.root / "breathing.mp4"
        ffmpeg(
            "-f", "lavfi", "-i", f"color=c=0x202020:size={W}x{H}:rate=25:duration=2",
            "-f", "lavfi", "-i", "color=c=white:size=60x60:rate=25:duration=2",
            "-filter_complex", "[1]drawbox=x=26:y=0:w=8:h=60:color=gray:t=fill,scale=w='trunc((60+40*sin(2*PI*t))/2)*2':h=60:eval=frame[sq];"
            "[0][sq]overlay=x='300-overlay_w/2':y=140:eval=frame:shortest=1[v]",
            "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(breathing),
        )
        box = {"x": 266 / W, "y": 136 / H, "w": 68 / W, "h": 68 / H}
        output = self.root / "breathing-cover.mp4"
        pp.export_video(breathing, [{"start": 0.0, "end": 2.0}], output,
                        settings={"preset": "preview", "aspect": "source", "timeout": 300, "normalize_audio": False,
                                  "redactions": {"bleeps": [], "hidden": [{"start": 0.0, "end": 2.0, "box": box, "style": "cover", "follow": True}]}})
        for index in range(0, 50, 2):
            t = index / 25 + 0.01
            self.assertEqual(bright(frame(output, t), 180, 130, 420, 210), 0, f"the square shows at {t:.2f} s")

    def test_a_box_drawn_mid_range_follows_back_to_the_start(self):
        from cutroom import tracking

        # Drawn at 1.5 s, where the square is at x = 250; it must be followed back to 0 s too.
        box = {"x": (square_x(1.5) - 8) / W, "y": 132 / H, "w": 76 / W, "h": 76 / H}
        path = tracking.follow_box(self.source, box, 0.0, 2.4, at=1.5)
        self.assertEqual(path["lost"], [])
        for t, x in zip(path["times"], path["x"]):
            self.assertAlmostEqual(x * W, square_x(t) - 8, delta=5, msg=f"at {t:.2f} s")

    def test_two_look_alikes_count_as_lost_not_as_followed(self):
        from cutroom import tracking

        # A twin appears 70 px to the right at 1 s: either could be the one to hide.
        twin = self.make("twin.mp4", "[1]drawbox=x=26:y=0:w=8:h=60:color=gray:t=fill,drawbox=x=0:y=26:w=60:h=8:color=gray:t=fill,split[s1][s2];"
                         "[0][s1]overlay=x='100+100*t':y=140:shortest=1[o];[o][s2]overlay=x='170+100*t':y=140:enable='gte(t,1)'[v]")
        path = tracking.follow_box(twin, self.box, 0.0, 2.0)
        self.assertTrue(path["lost"], "Look-alikes are not trusted")
        self.assertAlmostEqual(path["lost"][0][0], 1.0, delta=0.1)

    def test_a_cover_passing_over_counts_as_lost(self):
        from cutroom import tracking

        hidden = self.make("occluded.mp4", "[1]drawbox=x=26:y=0:w=8:h=60:color=gray:t=fill,drawbox=x=0:y=26:w=60:h=8:color=gray:t=fill[square];[0][square]overlay=x='100+100*t':y=140:shortest=1,"
                           "drawbox=x=0:y=120:w=640:h=110:color=black:t=fill:enable='between(t,1,1.3)'[v]")
        path = tracking.follow_box(hidden, self.box, 0.0, 2.0)
        self.assertEqual(len(path["lost"]), 1, path["lost"])
        start, end = path["lost"][0]
        self.assertAlmostEqual(start, 1.0, delta=0.07)
        self.assertAlmostEqual(end, 1.33, delta=0.07)

    def test_times_are_the_render_timeline_when_the_picture_starts_late(self):
        from cutroom import tracking

        # Sound starts at 0 and the picture at 0.3 s: the render places frames at 0.3 s onwards.
        late = self.root / "late.mp4"
        ffmpeg(
            "-f", "lavfi", "-i", f"color=c=0x202020:size={W}x{H}:rate=30:duration=3",
            "-f", "lavfi", "-i", "color=c=white:size=60x60:rate=30:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3.5",
            "-filter_complex", "[1]drawbox=x=26:y=0:w=8:h=60:color=gray:t=fill,drawbox=x=0:y=26:w=60:h=8:color=gray:t=fill[square];[0][square]overlay=x='100+100*t':y=140:shortest=1,setpts=PTS+0.3/TB[v]",
            "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(late),
        )
        path = tracking.follow_box(late, self.box, 0.0, 2.0)
        self.assertAlmostEqual(path["times"][0], 0.3, delta=0.02)
        for t, x in zip(path["times"], path["x"]):
            self.assertAlmostEqual(x * W, square_x(t - 0.3) - 8, delta=5, msg=f"at {t:.2f} s")

    def test_a_turned_phone_video_is_followed_and_covered_as_it_is_shown(self):
        from cutroom import tracking

        turned = self.root / "turned.mp4"
        ffmpeg("-display_rotation", "90", "-i", str(self.source), "-c", "copy", str(turned))

        def shown(path, t):
            # Shown upright the picture is H wide and W tall.
            data = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf", f"scale={H}:{W}",
                                   "-f", "rawvideo", "-pix_fmt", "gray", "-"], check=True, capture_output=True, timeout=60).stdout
            self.assertEqual(len(data), W * H)
            return lambda x, y: data[y * H + x]

        def square(pixel):
            points = [(x, y) for y in range(0, W, 2) for x in range(0, H, 2) if pixel(x, y) > 200]
            if not points:
                return None
            return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)

        x0, y0, x1, y1 = square(shown(turned, 0.0))
        box = {"x": (x0 - 8) / H, "y": (y0 - 8) / W, "w": (x1 - x0 + 16) / H, "h": (y1 - y0 + 16) / W}
        path = tracking.follow_box(turned, box, 0.0, 2.4)
        self.assertEqual(path["lost"], [])
        output = self.root / "turned-cover.mp4"
        pp.export_video(turned, [{"start": 0.0, "end": 2.4}], output,
                        settings={"preset": "preview", "aspect": "source", "timeout": 300, "normalize_audio": False,
                                  "redactions": {"bleeps": [], "hidden": [{"start": 0.0, "end": 2.4, "box": box, "style": "cover", "follow": True}]}})
        for t in (0.3, 1.2, 2.1):
            self.assertIsNotNone(square(shown(turned, t)), "The square is in the source")
            self.assertIsNone(square(shown(output, t)), f"The square shows in the render at {t} s")


if __name__ == "__main__":
    unittest.main()
