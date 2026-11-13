"""One authoritative frame selection feeds video, pacing, crops and audio."""

import unittest
from fractions import Fraction

from cutroom import pacing
from cutroom import postproduction as pp


class FrameTimelineTests(unittest.TestCase):
    def test_negative_start_keeps_exact_indices_counts_and_samples(self):
        info = {
            "duration": 20.027,
            "width": 160,
            "height": 96,
            "streams": [
                {"codec_type": "video", "start_time": "0.007"},
                {"codec_type": "audio", "start_time": "-0.007"},
            ],
        }
        origin = pp._timeline(info)[1]
        frames = pp._frame_aligned(
            [(0.0, 6.0), (7.0, 13.0), (14.2, 19.0)],
            "30000/1001",
            20.027,
            origin,
        )
        self.assertEqual(frames, [(0, 180), (209, 180), (425, 143)])
        edges = pp._frame_edges(frames, "30000/1001", origin)
        sound = pp._audio_ranges(frames, "30000/1001", origin)
        self.assertEqual([s[2] for s in sound], [288288, 288288, 229029])
        self.assertEqual(sound[1][:2], (6.987633, 12.993633))
        settings = pp._settings({"pacing": {"transition": "crossfade"}})
        report = pp._pacing_planner(
            info,
            edges,
            "30000/1001",
            settings,
            frames,
        )(None, None, None, None, cuts_only=True)
        self.assertEqual(
            [(r["source_first"], r["frames"]) for r in report["ranges"]],
            frames,
        )
        graph, _ = pacing.build_graph(
            report,
            rate="30000/1001",
            origin=origin,
            out_size=(160, 96),
        )
        self.assertIn("trim=start_frame=206:end_frame=392", graph[1])
        self.assertIn("setpts=N,fps=30000/1001", graph[1])

    def test_fragment_budget_is_preserved_at_multiple_origins_and_rates(self):
        ranges = [(0.0, 0.004), (0.01, 0.201), (0.3, 0.304), (0.31, 0.802), (1.0, 1.6)]
        for origin in (0.0, 0.007, 0.014, 0.207):
            for rate in ("24", "25", "30000/1001", "60"):
                with self.subTest(origin=origin, rate=rate):
                    fps = Fraction(rate)
                    frames = pp._frame_aligned(ranges, rate, 2.0, origin)
                    count = round(
                        sum(Fraction(str(b)) - Fraction(str(a)) for a, b in ranges)
                        * fps
                    )
                    self.assertEqual(sum(n for _, n in frames), count)
                    sound = pp._audio_ranges(frames, rate, origin, 44100)
                    self.assertEqual(
                        sum(s[2] for s in sound), round(count / fps * 44100)
                    )
                    for (first, n), (start, end, _) in zip(frames, sound):
                        self.assertEqual(
                            start, round(float(Fraction(str(origin)) + first / fps), 6)
                        )
                        self.assertEqual(
                            end,
                            round(float(Fraction(str(origin)) + (first + n) / fps), 6),
                        )

    def test_time_placed_rate_comes_from_frame_spacing_not_the_header(self):
        ntsc = [Fraction(n * 1001, 30000) for n in range(300) if not 100 <= n < 110]
        jitter = [
            Fraction(n * 1001, 30000) + (Fraction(8, 1000) if n % 3 == 1 else 0)
            for n in range(300)
        ]
        pal = [Fraction(n, 25) for n in range(250)]
        # WebM stores milliseconds: 29.97 fps spacing reads as 33, 34, 33 ms.
        webm = [
            Fraction(round(n * 1001 / 30), 1000)
            for n in range(600)
            if not 200 <= n < 210
        ]
        for header, times, expected in (
            ({"r_frame_rate": "120/1", "avg_frame_rate": "0/0"}, ntsc, "30000/1001"),
            (
                {"r_frame_rate": "90000/1", "avg_frame_rate": "0/0"},
                jitter,
                "30000/1001",
            ),
            ({"r_frame_rate": "50/1", "avg_frame_rate": "25/1"}, pal, "25/1"),
            ({"r_frame_rate": "30000/1001"}, webm, "30000/1001"),
        ):
            with self.subTest(header=header):
                self.assertEqual(pp._timed_rate(header, times), expected)
        # Without frame times the header is used when it is plausible.
        self.assertEqual(pp._timed_rate({"r_frame_rate": "24/1"}, None), "24/1")
        self.assertIsNone(pp._timed_rate({"r_frame_rate": "90000/1"}, None))
