"""Bound clip search work before creating display records."""

import unittest
from unittest.mock import patch

from clip_fixtures import talk

from cutroom import clips


class SearchBudgetTests(unittest.TestCase):
    def test_dense_timestamp_search_rejects_before_scoring(self):
        words = [
            {"id": i, "start": i * 0.105, "end": i * 0.105 + 0.1, "text": f"w{i}."}
            for i in range(1000)
        ]
        # A throwing scorer makes this cheap even against the unbounded version.
        with patch.object(clips, "_evaluate", side_effect=AssertionError("scored")):
            with self.assertRaisesRegex(ValueError, "budget"):
                clips.find_candidates(words, 106, count=1)

    def test_count_one_only_materializes_the_selected_record(self):
        words, _, duration = talk(minutes=17)
        original = clips._evaluate
        records = []

        def observe(*args, **kwargs):
            result = original(*args, **kwargs)
            if isinstance(result, dict):
                records.append(result)
            return result

        with patch.object(clips, "_evaluate", side_effect=observe):
            result = clips.find_candidates(words, duration, count=1)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(len(records), 1)

    def test_normal_seventeen_minute_talk_keeps_diverse_results(self):
        words, _, duration = talk(minutes=17)
        result = clips.find_candidates(words, duration, count=8)["candidates"]
        self.assertEqual(len(result), 8)
        self.assertTrue(any(c["end"] < duration / 3 for c in result))
        self.assertTrue(any(c["start"] > 2 * duration / 3 for c in result))
        spans = sorted((c["start"], c["end"]) for c in result)
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])))

    def test_a_three_hour_recording_with_short_sentences_finds_eight_clips(self):
        # Ordinary podcast speech at the three-hour source limit must stay
        # within the budgets with the default eight clips, and each window is
        # scored once rather than once per pick.
        words, _, duration = talk(minutes=180)
        original = clips._evaluate
        scored = []

        def observe(*args, **kwargs):
            scored.append(args[1:3])
            return original(*args, **kwargs)

        with patch.object(clips, "_evaluate", side_effect=observe):
            result = clips.find_candidates(
                words, duration, count=8, platform="youtube_shorts"
            )
        self.assertEqual(len(result["candidates"]), 8)
        details = 8
        self.assertEqual(len(scored), len(set(scored)) + details)
        # The largest request is not refused either.
        most = clips.find_candidates(words, duration, count=20)["candidates"]
        self.assertEqual(len(most), 20)

    def test_eight_clips_cost_about_as_much_as_one(self):
        import time

        words, _, duration = talk(minutes=60)
        took = {}
        for count in (1, 8):
            started = time.perf_counter()
            clips.find_candidates(words, duration, count=count)
            took[count] = time.perf_counter() - started
        self.assertLess(took[8], took[1] * 2 + 0.5, took)
