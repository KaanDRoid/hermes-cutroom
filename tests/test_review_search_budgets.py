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
