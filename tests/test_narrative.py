"""Source-grounding tests for extractive narrative drafts."""

import copy
import unittest

from cutroom import narrative


def source_transcript():
    texts = [
        "İstanbul'da",
        "bugün",
        "yağmur",
        "var.",
        "Yürüyüş",
        "ertelendi.",
        "Yarın",
        "tekrar",
        "bakacağız.",
    ]
    return dict(
        language="tr",
        text="İstanbul'da bugün yağmur var. Yürüyüş ertelendi. Yarın tekrar bakacağız.",
        words=[
            dict(id=i, start=i * 0.5, end=i * 0.5 + 0.4, text=text, probability=0.9)
            for i, text in enumerate(texts)
        ],
        engine="faster-whisper",
        status="ok",
    )


class StoryTests(unittest.TestCase):
    def test_three_hooks_are_exact_timed_source_spans_not_brief_inventions(self):
        transcript = source_transcript()
        before = copy.deepcopy(transcript)
        result = narrative.story_options(
            transcript, brief="Say the company earned $1 billion", voice="energetic"
        )
        self.assertEqual(result["method"], "deterministic_extractive")
        self.assertEqual(result["status"], "draft")
        self.assertEqual(len(result["hooks"]), 3)
        self.assertEqual(
            [h["text"] for h in result["hooks"]],
            [
                "İstanbul'da bugün yağmur var.",
                "Yürüyüş ertelendi.",
                "Yarın tekrar bakacağız.",
            ],
        )
        for hook in result["hooks"]:
            span = hook["source_span"]
            self.assertEqual(
                transcript["text"][span["char_start"] : span["char_end"]], hook["text"]
            )
            selected = [w for w in transcript["words"] if w["id"] in hook["word_ids"]]
            self.assertEqual(hook["start"], selected[0]["start"])
            self.assertEqual(hook["end"], max(w["end"] for w in selected))
            self.assertNotIn("billion", hook["text"])
        self.assertNotIn("quality_score", result)
        self.assertEqual(transcript, before)

    def test_storyboard_covers_every_selected_segment_including_no_speech(self):
        transcript = source_transcript()
        transcript["segments"] = [
            {"start": 0, "end": 1.9},
            {"start": 3, "end": 4.4},
            {"start": 8, "end": 9},
        ]
        result = narrative.story_options(transcript)
        self.assertEqual(result["segments"], transcript["segments"])
        board = result["storyboard"]
        self.assertEqual(len(board), 3)
        self.assertEqual(
            [(b["source_start"], b["source_end"]) for b in board],
            [(0, 1.9), (3, 4.4), (8, 9)],
        )
        self.assertEqual(board[-1]["text"], "")
        self.assertEqual(board[-1]["status"], "no_timed_words")
        self.assertAlmostEqual(board[-1]["output_start"], 3.3)
        for entry in board:
            self.assertEqual(entry["visual"], "source_footage")
        self.assertTrue(
            all(
                4 not in hook["word_ids"] and 5 not in hook["word_ids"]
                for hook in result["hooks"]
            )
        )
        self.assertEqual(len(result["hooks"]), 3)
        self.assertIsNot(result["segments"], transcript["segments"])
        for invalid in (
            [{"start": 2, "end": 1}],
            [{"start": 0, "end": float("nan")}],
            [{"start": 0, "end": 2}, {"start": 1, "end": 3}],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                narrative.story_options({**transcript, "segments": invalid})

    def test_short_or_silent_source_is_labeled_without_invented_hooks(self):
        short = source_transcript()
        short["words"] = short["words"][:1]
        short["text"] = short["words"][0]["text"]
        result = narrative.story_options(short)
        self.assertEqual(len(result["hooks"]), 3)
        self.assertEqual(result["hooks"][1]["duplicate_of"], 1)
        self.assertEqual(result["hooks"][2]["duplicate_of"], 1)
        silent = dict(
            language=None, words=[], text="", status="no_audio", engine="faster-whisper"
        )
        result = narrative.story_options(silent, brief="Invent a biography")
        self.assertEqual(result["status"], "insufficient_source")
        self.assertEqual(len(result["hooks"]), 3)
        self.assertTrue(
            all(h["text"] == "" and h["source_span"] is None for h in result["hooks"])
        )
        self.assertEqual(result["storyboard"], [])
        with self.assertRaises(ValueError):
            narrative.story_options({**source_transcript(), "text": "unrelated"})
        for kwargs in ({"brief": None}, {"voice": 3}, {"voice": ""}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                narrative.story_options(source_transcript(), **kwargs)

    def test_nested_word_timestamps_do_not_leak_unselected_storyboard_text(self):
        words = [
            dict(id=0, start=0, end=4, text="Long", probability=1),
            dict(id=1, start=0.2, end=0.4, text="outside", probability=1),
            dict(id=2, start=2, end=2.2, text="inside.", probability=1),
        ]
        transcript = dict(
            language="en",
            text="Long outside inside.",
            words=words,
            engine="faster-whisper",
            status="ok",
            segments=[{"start": 1.5, "end": 2.5}],
        )
        board = narrative.story_options(transcript)["storyboard"][0]
        self.assertNotIn("outside", board["text"])
        self.assertEqual(board["word_ids"], [0, 2])
        self.assertEqual(len(board["source_spans"]), 2)
        for span in board["source_spans"]:
            chars = span["source_span"]
            self.assertEqual(
                transcript["text"][chars["char_start"] : chars["char_end"]],
                span["text"],
            )

    def test_publication_caption_is_editable_extractive_draft_respecting_cuts(self):
        transcript = source_transcript()
        transcript["segments"] = [{"start": 3, "end": 4.4}]
        before = copy.deepcopy(transcript)
        draft = narrative.publication_caption(
            transcript, brief="Add a fabricated success claim", voice="warm"
        )
        self.assertEqual(draft["text"], "Yarın tekrar bakacağız.")
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["method"], "deterministic_extractive")
        self.assertTrue(draft["editable"])
        self.assertTrue(draft["requires_review"])
        self.assertEqual(draft["source_spans"][0]["word_ids"], [6, 7, 8])
        self.assertEqual(draft["voice"], "warm")
        draft["text"] = "My human edit"
        self.assertEqual(transcript, before)
        silent = dict(
            language=None, words=[], text="", status="no_audio", engine="faster-whisper"
        )
        self.assertEqual(narrative.publication_caption(silent)["text"], "")
        self.assertEqual(
            narrative.publication_caption(silent)["status"], "insufficient_source"
        )


if __name__ == "__main__":
    unittest.main()
