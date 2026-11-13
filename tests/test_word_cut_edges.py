"""Removing a word cuts in the pause next to it, not inside a word.

Speech recognisers often stamp word edges a little off: the end of a removed
word can be stamped before its sound stops, and the start of a kept word after
its sound begins. Cutting at the stamps then leaves a fragment of the removed
word, or clips the start of a kept one.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from cutroom import speech
from cutroom.studio import Studio

STEP = 0.02
LOUD = -18.0
QUIET = -52.0


def levels(sounds, duration):
    """20 ms levels: loud inside each (start, end) sound, quiet elsewhere."""
    count = round(duration / STEP)
    return {
        "step": STEP,
        "db": [
            LOUD
            if any(start <= (k + 0.5) * STEP < end for start, end in sounds)
            else QUIET
            for k in range(count)
        ],
    }


def word(identifier, start, end, text="word"):
    return dict(id=identifier, start=start, end=end, text=text, probability=0.9)


class WordCutEdgeTests(unittest.TestCase):
    def test_tail_of_a_removed_word_stamped_short_is_not_left_behind(self):
        # The removed word sounds until 1.2 s but is stamped to end at 1.0 s.
        words = [word(0, 0.0, 0.5), word(1, 0.6, 1.0, "when"), word(2, 1.0, 1.5)]
        energy = levels([(0.0, 0.5), (0.6, 1.2), (1.3, 1.6)], 2.0)
        kept = speech.word_segments(words, [1], duration=2.0, energy=energy)
        self.assertEqual(len(kept), 2)
        self.assertGreaterEqual(kept[1]["start"], 1.2)
        self.assertLessEqual(kept[1]["start"], 1.3)
        self.assertEqual(kept[0], {"start": 0.0, "end": 0.54})

    def test_start_of_a_kept_word_stamped_late_is_kept(self):
        # The kept word starts sounding at 0.95 s; its stamp says 1.0 s.
        words = [word(0, 0.0, 0.5), word(1, 0.6, 1.0, "um"), word(2, 1.0, 1.5)]
        energy = levels([(0.0, 0.5), (0.6, 0.9), (0.95, 1.5)], 2.0)
        kept = speech.word_segments(words, [1], duration=2.0, energy=energy)
        self.assertLessEqual(kept[1]["start"], 0.95)
        self.assertGreaterEqual(kept[1]["start"], 0.9)

    def test_end_of_a_kept_word_running_into_a_removed_one_is_kept(self):
        # The kept word sounds until 0.66 s; the removed word is stamped from 0.5 s.
        words = [word(0, 0.0, 0.5), word(1, 0.5, 1.0, "um"), word(2, 1.1, 1.5)]
        energy = levels([(0.0, 0.66), (0.7, 1.0), (1.1, 1.5)], 2.0)
        kept = speech.word_segments(words, [1], duration=2.0, energy=energy)
        self.assertGreaterEqual(kept[0]["end"], 0.66)
        self.assertLessEqual(kept[0]["end"], 0.7)

    def test_edges_already_in_a_pause_do_not_move(self):
        words = [word(0, 0.0, 0.5), word(1, 0.6, 1.0, "um"), word(2, 1.0, 1.5)]
        energy = levels([(0.0, 0.45), (0.65, 0.9), (1.1, 1.5)], 2.0)
        self.assertEqual(
            speech.word_segments(words, [1], duration=2.0, energy=energy),
            speech.word_segments(words, [1], duration=2.0),
        )

    def test_without_levels_or_with_continuous_sound_the_stamps_are_used(self):
        words = [word(0, 0.0, 0.5), word(1, 0.6, 1.0, "um"), word(2, 1.0, 1.5)]
        plain = speech.word_segments(words, [1], duration=2.0)
        for energy in (None, {}, levels([(0.0, 2.0)], 2.0)):
            with self.subTest(energy=bool(energy)):
                self.assertEqual(
                    speech.word_segments(words, [1], duration=2.0, energy=energy),
                    plain,
                )

    def test_repeated_word_from_a_real_recording(self):
        # Word stamps and pause positions measured on a real interview:
        # "our father died when when I was two". The second "when" sounds
        # from 33.64 to 33.94 s, but is stamped 33.34-33.84 and "I" 33.84-33.90.
        words = [
            word(63, 30.12, 30.78, "our"),
            word(64, 30.78, 31.22, "father"),
            word(65, 31.22, 32.18, "died"),
            word(66, 32.18, 33.34, "when"),
            word(67, 33.34, 33.84, "when"),
            word(68, 33.84, 33.90, "I"),
            word(69, 33.90, 34.08, "was"),
            word(70, 34.08, 34.30, "two"),
        ]
        energy = levels(
            [
                (30.44, 30.62),
                (30.80, 31.16),
                (31.24, 31.62),
                (32.82, 33.10),
                (33.64, 33.94),
                (34.12, 34.50),
            ],
            35.0,
        )
        kept = speech.word_segments(words, [67], duration=35.0, energy=energy)
        self.assertEqual(len(kept), 2)
        self.assertGreaterEqual(kept[1]["start"], 33.94)
        self.assertLessEqual(kept[1]["start"], 34.12)
        # The first "when" (32.82-33.10) stays whole.
        self.assertGreaterEqual(kept[0]["end"], 33.10)


class StudioWordCutTests(unittest.TestCase):
    def test_studio_uses_the_sound_of_the_source_for_word_cuts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "speech.mp4"
            tone = (
                "0.3*sin(2*PI*440*t)"
                "*(lt(t\,0.5)+between(t\,0.6\,1.2)+between(t\,1.3\,1.6))"
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=160x90:rate=10:duration=2",
                    "-f",
                    "lavfi",
                    "-i",
                    f"aevalsrc={tone}:s=48000:d=2",
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(source),
                ],
                capture_output=True,
                check=True,
                timeout=30,
            )
            studio = Studio(root / "workspace")
            project = studio.create(source)
            words = [
                word(0, 0.0, 0.5, "First"),
                word(1, 0.6, 1.0, "when"),
                word(2, 1.0, 1.5, "last"),
            ]
            transcript = dict(
                language="en",
                words=words,
                text="First when last",
                engine="manual",
                status="ok",
            )
            project = studio.update(
                project["id"],
                {
                    "segments": [{"start": 0.0, "end": 2.0}],
                    "transcript": transcript,
                    "excluded_word_ids": [1],
                },
                project["revision"],
            )
            starts = [segment["start"] for segment in project["segments"]]
            self.assertEqual(len(starts), 2, project["segments"])
            self.assertGreaterEqual(starts[1], 1.18)
            self.assertLessEqual(starts[1], 1.3)


if __name__ == "__main__":
    unittest.main()
