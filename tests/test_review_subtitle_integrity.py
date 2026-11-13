"""Subtitle delivery must never silently discard transcript characters."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom import longform


class SubtitleIntegrityTests(unittest.TestCase):
    def test_unrepresentable_token_is_rejected_instead_of_truncated(self):
        token = "https://example.invalid/" + "a" * 100
        with self.assertRaisesRegex(ValueError, "Subtitle.*token"):
            longform.srt_cues([{"start": 0, "end": 2, "text": token}])

    def test_qa_checks_original_text_even_if_cue_generator_loses_text(self):
        words = [{"start": 0, "end": 2, "text": "Original transcript."}]
        lossy = [
            {
                "start": 0,
                "end": 2,
                "lines": ["Original"],
                "word_start": 0,
                "word_end": 2,
            }
        ]
        text = "1\n00:00:00,000 --> 00:00:02,000\nOriginal\n\n"
        with patch.object(longform, "srt_cues", return_value=lossy):
            report = longform.subtitle_report(text, words, 1 / 30)
        self.assertEqual(report["status"], "fail", report)
        self.assertTrue(any("transcript" in p for p in report["problems"]))

    def test_zero_duration_words_survive_both_delivery_formats(self):
        words = [
            {"start": 0, "end": 0, "text": "First."},
            {"start": 0, "end": 0, "text": "Second."},
            {"start": 1, "end": 1, "text": "Third."},
        ]
        cues = longform.srt_cues(words)
        with tempfile.TemporaryDirectory() as temp:
            for fmt in ("srt", "vtt"):
                path = Path(temp) / f"captions.{fmt}"
                longform.write_srt(cues, path, format=fmt)
                delivered = path.read_text(encoding="utf-8")
                for word in words:
                    self.assertIn(word["text"], delivered)
                if fmt == "srt":
                    self.assertEqual(
                        longform.subtitle_report(delivered, words, 1 / 30)["status"],
                        "pass",
                    )

    def test_writer_rejects_zero_duration_instead_of_silently_dropping_text(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "duration"):
                longform.write_srt(
                    [{"start": 0, "end": 0, "lines": ["Keep me"]}],
                    Path(temp) / "captions.srt",
                )
