"""Tests for local speech and timestamp-based text editing."""

import builtins
import copy
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom import speech


def word(identifier=0, start=0.1, end=0.5, text="Hello", probability=0.9):
    return dict(id=identifier, start=start, end=end, text=text, probability=probability)


def transcript(words=None):
    words = [word()] if words is None else words
    return dict(
        language="en",
        words=words,
        text=" ".join(str(w["text"]) for w in words),
        engine="faster-whisper",
        status="ok",
    )


class TranscriptTests(unittest.TestCase):
    def test_validation_is_pure_and_accepts_ordered_overlapping_words(self):
        data = transcript([word(), word(2, 0.4, 0.7, "world")])
        before = copy.deepcopy(data)
        self.assertEqual(speech.validate_transcript(data, duration=1), data)
        self.assertEqual(data, before)

    def test_validation_rejects_malformed_transcripts(self):
        invalid = [
            None,
            {},
            transcript([word(start=float("nan"))]),
            transcript([word(end=float("inf"))]),
            transcript([word(start=-1)]),
            transcript([word(end=0)]),
            transcript([word(probability=1.1)]),
            transcript([word(probability=True)]),
            transcript([word(identifier=True)]),
            transcript([word(identifier=-1)]),
            transcript([word(), word()]),
            transcript([word(), word(1, 0.05, 0.2)]),
            transcript([word(text="")]),
            transcript([word(text=4)]),
            transcript([word(text="bad\ud800")]),
            transcript([word(text="tab\there")]),
        ]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                speech.validate_transcript(data)
        for duration in (0.4, -1, float("inf"), True):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                speech.validate_transcript(transcript(), duration=duration)
        for changes in (
            {"language": 7},
            {"status": "invented"},
            {"engine": ""},
            {"status": "no_audio"},
            {"text": None},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                speech.validate_transcript({**transcript(), **changes})


class WordEditTests(unittest.TestCase):
    def test_segments_merge_padding_clip_duration_and_do_not_restore_excluded_audio(
        self,
    ):
        words = [
            word(0, 0, 0.3),
            word(1, 0.3, 0.5, "um"),
            word(2, 0.5, 0.8),
            word(3, 0.82, 1.0),
        ]
        before = copy.deepcopy(words)
        self.assertEqual(
            speech.word_segments(words, [1], padding=0.1, duration=1),
            [{"start": 0.0, "end": 0.3}, {"start": 0.5, "end": 1.0}],
        )
        self.assertEqual(
            speech.word_segments(words, padding=0.1, duration=1),
            [{"start": 0.0, "end": 1.0}],
        )
        self.assertEqual(speech.word_segments(words, [0, 1, 2, 3]), [])
        self.assertEqual(speech.word_segments([]), [])
        self.assertEqual(words, before)
        overlapping = [word(0, 0, 1), word(1, 0.5, 0.7), word(2, 0.8, 1.2)]
        self.assertEqual(
            speech.word_segments(overlapping, [1], padding=0),
            [{"start": 0.0, "end": 0.5}, {"start": 0.7, "end": 1.2}],
        )
        for kwargs in (
            {"padding": -0.1},
            {"padding": float("nan")},
            {"excluded_ids": [99]},
            {"excluded_ids": [True]},
            {"duration": 0.9},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                speech.word_segments(words, **kwargs)

    def test_remap_clips_half_open_boundaries_and_preserves_source_provenance(self):
        words = [
            word(5, 0, 0.5, "outside"),
            word(6, 0.5, 1.5, "İçerik"),
            word(8, 2, 4, "spanning"),
            word(9, 4, 4.5, "outside"),
        ]
        segments = [
            {"start": 0.5, "end": 1.25},
            {"start": 2.5, "end": 3},
            {"start": 3.5, "end": 4},
        ]
        before = copy.deepcopy(words)
        result = speech.remap_words(words, segments)
        self.assertEqual(
            [w["text"] for w in result], ["İçerik", "spanning", "spanning"]
        )
        self.assertEqual(
            [(w["start"], w["end"]) for w in result],
            [(0.0, 0.75), (0.75, 1.25), (1.25, 1.75)],
        )
        self.assertEqual([w["id"] for w in result], [0, 1, 2])
        self.assertEqual([w["source_id"] for w in result], [6, 8, 8])
        self.assertEqual((result[1]["source_start"], result[1]["source_end"]), (2, 4))
        self.assertEqual(
            (result[1]["kept_source_start"], result[1]["kept_source_end"]), (2.5, 3)
        )
        self.assertEqual(words, before)
        self.assertEqual(speech.remap_words(words, []), [])
        for invalid in (
            [{"start": 0, "end": 2}, {"start": 1, "end": 3}],
            [{"start": -1, "end": 1}],
            [{"start": 1, "end": 1}],
            [{"start": 0, "end": float("inf")}],
            None,
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                speech.remap_words(words, invalid)

    def test_filler_matches_are_unicode_language_aware_review_only(self):
        english = [
            word(0, 0, 0.2, "Um,"),
            word(1, 0.3, 0.5, "umbrella"),
            word(2, 0.6, 0.8, "you"),
            word(3, 0.8, 1, "know,"),
            word(4, 2, 2.1, "like"),
            word(5, 5, 5.2, "you"),
            word(6, 10, 10.2, "know"),
        ]
        before = copy.deepcopy(english)
        suggestions = speech.filler_suggestions(english)
        self.assertEqual([s["word_ids"] for s in suggestions], [[0], [2, 3], [4]])
        self.assertTrue(
            all(
                s["status"] == "suggestion" and s["requires_review"]
                for s in suggestions
            )
        )
        self.assertEqual(english, before)
        turkish = [
            word(0, 0, 0.2, "YANİ,"),
            word(1, 0.3, 0.5, "Şey…"),
            word(2, 0.6, 0.8, "ııı"),
            word(3, 0.9, 1, "bir"),
            word(4, 1, 1.2, "bakıma"),
            word(5, 1.3, 1.5, "şeytan"),
        ]
        self.assertEqual(
            [s["word_ids"] for s in speech.filler_suggestions(turkish, "tr")],
            [[0], [1], [2], [3, 4]],
        )
        self.assertEqual(speech.filler_suggestions(turkish, "de"), [])


class CaptionTests(unittest.TestCase):
    def test_cues_limit_word_count_and_duration_without_losing_unicode(self):
        words = [
            word(i, i * 0.5, i * 0.5 + 0.4, text)
            for i, text in enumerate(
                ["Merhaba", "İstanbul,", "nasılsın?", "Bugün", "güzel."]
            )
        ]
        before = copy.deepcopy(words)
        cues = speech.caption_cues(words, max_words=2, max_duration=1)
        self.assertEqual(
            [c["text"] for c in cues],
            ["Merhaba İstanbul,", "nasılsın? Bugün", "güzel."],
        )
        self.assertEqual([c["word_ids"] for c in cues], [[0, 1], [2, 3], [4]])
        self.assertEqual((cues[0]["start"], cues[0]["end"]), (0, 0.9))
        self.assertEqual(words, before)
        long = speech.caption_cues([word(0, 1, 8, "Uzun")], max_duration=3)
        self.assertEqual(
            [(c["start"], c["end"]) for c in long], [(1, 4), (4, 7), (7, 8)]
        )
        overlap = speech.caption_cues([word(0, 0, 0.8), word(1, 0.2, 0.4)], max_words=6)
        self.assertEqual(overlap[0]["end"], 0.8)
        self.assertEqual(speech.caption_cues([]), [])
        for kwargs in (
            {"max_words": 0},
            {"max_words": True},
            {"max_words": 1.5},
            {"max_duration": 0},
            {"max_duration": float("nan")},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                speech.caption_cues(words, **kwargs)

    def test_overlapping_long_words_still_produce_chronological_exportable_cues(self):
        words = [word(0, 0, 8, "long"), word(1, 1, 1.4, "overlap")]
        cues = speech.caption_cues(words, max_words=1, max_duration=3)
        self.assertEqual([cue["start"] for cue in cues], [0, 1, 3, 6])
        self.assertTrue(all(0 < cue["end"] - cue["start"] <= 3 for cue in cues))
        with tempfile.TemporaryDirectory() as directory:
            speech.write_subtitles(cues, Path(directory) / "overlap.vtt", format="vtt")

    def test_subtitles_export_srt_and_vtt_as_literal_unicode_without_overwrite(self):
        cues = [
            {
                "start": 0,
                "end": 1.2346,
                "text": "İyi <b>günler</b> & merhaba\n\n00:00:00 --> 00:00:01",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            for kind in ("srt", "vtt"):
                path = Path(directory) / ("captions." + kind)
                result = speech.write_subtitles(cues, path, format=kind)
                text = path.read_text(encoding="utf-8")
                self.assertEqual(result["path"], str(path.resolve()))
                self.assertIn("İyi &lt;b&gt;günler&lt;/b&gt; &amp; merhaba", text)
                self.assertNotIn("\n\n00:00:00 -->", text)
                self.assertIn("00:00:01" + (",235" if kind == "srt" else ".235"), text)
                self.assertEqual(text.startswith("WEBVTT\n\n"), kind == "vtt")
                with self.assertRaises(FileExistsError):
                    speech.write_subtitles(cues, path, format=kind)
                self.assertEqual(path.read_text(encoding="utf-8"), text)
            bad_path = Path(directory) / "bad.srt"
            for invalid in (
                [{"start": float("nan"), "end": 1, "text": "x"}],
                [{"start": 1, "end": 0, "text": "x"}],
                [{"start": 0, "end": 1, "text": ""}],
            ):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    speech.write_subtitles(invalid, bad_path)
                self.assertFalse(bad_path.exists())
            with self.assertRaises(ValueError):
                speech.write_subtitles(cues, bad_path, format="html")

    def test_ass_branding_escapes_override_and_event_injection_and_parses_in_ffmpeg(
        self,
    ):
        cues = [
            {
                "start": 3599.9996,
                "end": 3601,
                "text": "İyi {\\\\p1} günler\\\\N\nDialogue: 0,0:00:00.00,0:09:00.00,X",
            }
        ]
        brand = dict(
            font="Arial",
            subtitle_size=42,
            subtitle_color="#12ABEF",
            alignment="left",
            safe_margin=0.1,
            subtitle_y=0.8,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "captions.ass"
            speech.write_subtitles(cues, path, format="ass", brand=brand)
            text = path.read_text(encoding="utf-8")
            self.assertIn("Style: Default,Arial,42", text)
            self.assertIn("&H00EFAB12", text)
            self.assertIn("1:00:00.00", text)
            self.assertNotIn("{\\\\p1}", text)
            self.assertNotIn("\\\\N", text)
            self.assertEqual(
                len(
                    [line for line in text.splitlines() if line.startswith("Dialogue:")]
                ),
                1,
            )
            parsed = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=64x64:d=0.1",
                    "-vf",
                    "ass=captions.ass",
                    "-frames:v",
                    "1",
                    "-f",
                    "null",
                    "-",
                ],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            with self.assertRaises(FileExistsError):
                speech.write_subtitles(cues, path, format="ass")
            for invalid in (
                {"font": "Arial\n[Events]"},
                {"subtitle_color": "red,evil"},
                {"subtitle_size": float("nan")},
            ):
                target = Path(directory) / "invalid.ass"
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    speech.write_subtitles(cues, target, format="ass", brand=invalid)
                self.assertFalse(target.exists())


class TranscribeTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def test_actual_user_videos_without_audio_never_import_the_model(self):
        original_import = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name.split(".")[0] == "faster_whisper":
                raise AssertionError("A silent video must not load a model")
            return original_import(name, *args, **kwargs)

        for name in (
            "1416529-uhd_3840_2160_30fps.mp4",
            "4439224-uhd_2160_3840_25fps.mp4",
        ):
            source = self.root / "raw_vids" / name
            if not source.is_file():
                self.skipTest("Consented user video is not available locally")
            with (
                self.subTest(source=name),
                patch("builtins.__import__", side_effect=guarded),
            ):
                result = speech.transcribe(source, "missing-model")
                self.assertEqual(
                    result,
                    dict(
                        language=None,
                        words=[],
                        text="",
                        engine="faster-whisper",
                        status="no_audio",
                    ),
                )

    def test_audio_with_unavailable_or_remote_models_fails_before_import(self):
        source = self.root / "artifacts/reference/jfk.wav"
        if not source.is_file():
            self.skipTest("The official JFK reference audio is not present")
        with tempfile.TemporaryDirectory() as directory:
            for model in (
                "Systran/faster-whisper-tiny",
                "https://example.com/model",
                "//server/model",
                directory,
            ):
                with (
                    self.subTest(model=model),
                    patch(
                        "builtins.__import__", side_effect=AssertionError("No import")
                    ),
                ):
                    with self.assertRaises((ValueError, FileNotFoundError)):
                        speech.transcribe(source, model)

    @unittest.skipUnless(
        importlib.util.find_spec("faster_whisper"),
        "Optional faster-whisper is not installed",
    )
    def test_real_local_cpu_inference_on_official_jfk_reference_not_user_speech(self):
        source = self.root / "artifacts/reference/jfk.wav"
        model = self.root / "models/whisper-tiny"
        if not source.is_file() or not (model / "model.bin").is_file():
            self.skipTest("Optional local reference audio and model are not present")
        with patch(
            "socket.socket.connect",
            side_effect=AssertionError("Offline inference must not use a network"),
        ):
            result = speech.transcribe(source, model, language="en")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["language"], "en")
        self.assertIn("country", result["text"].casefold())
        self.assertGreater(len(result["words"]), 20)
        self.assertTrue(all(w["end"] <= 11.1 for w in result["words"]))
        speech.validate_transcript(result, duration=11.1)


if __name__ == "__main__":
    unittest.main()
