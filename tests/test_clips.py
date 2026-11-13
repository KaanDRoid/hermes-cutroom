"""Clip finder: sentences, sentence-bounded candidates and explained scores."""

import unittest

from clip_fixtures import talk

from cutroom import clips


def word(i, start, end, text, probability=0.9):
    return {
        "id": i,
        "start": start,
        "end": end,
        "text": text,
        "probability": probability,
    }


def sentence_text(words, sentence):
    return " ".join(w["text"] for w in words[sentence["first"] : sentence["last"] + 1])


class SentenceTests(unittest.TestCase):
    def test_punctuation_ends_sentences_but_not_abbreviations(self):
        words = [
            word(0, 0.0, 0.3, "Dr."),
            word(1, 0.4, 0.7, "Smith"),
            word(2, 0.8, 1.1, "arrived."),
            word(3, 1.6, 1.9, "Why"),
            word(4, 2.0, 2.3, "now?"),
            word(5, 2.9, 3.2, "Because"),
            word(6, 3.3, 3.6, "it"),
            word(7, 3.7, 4.0, "rained!"),
        ]
        found = clips.sentences(words)
        self.assertEqual(
            [sentence_text(words, s) for s in found],
            ["Dr. Smith arrived.", "Why now?", "Because it rained!"],
        )
        self.assertEqual([s["end_kind"] for s in found], ["stop", "question", "stop"])
        self.assertEqual(found[1]["first_id"], 3)
        self.assertEqual(found[1]["last_id"], 4)
        self.assertEqual(found[0]["start"], 0.0)
        self.assertEqual(found[2]["end"], 4.0)

    def test_text_without_punctuation_is_split_at_pauses(self):
        words, expected, _ = talk(minutes=2, punctuated=False)
        found = clips.sentences(words)
        self.assertEqual([(s["first"], s["last"]) for s in found], expected)
        self.assertTrue(all(s["end_kind"] == "pause" for s in found[:-1]))

    def test_a_long_pause_ends_a_sentence_even_without_a_full_stop(self):
        words = [
            word(0, 0.0, 0.3, "Look."),
            word(1, 0.5, 0.8, "the"),
            word(2, 0.9, 1.2, "river"),
            word(3, 4.0, 4.3, "came"),
            word(4, 4.4, 4.7, "back."),
        ]
        found = clips.sentences(words)
        self.assertEqual(
            [sentence_text(words, s) for s in found],
            ["Look.", "the river", "came back."],
        )
        self.assertEqual(found[1]["end_kind"], "pause")

    def test_very_long_runs_are_split_at_their_largest_pause(self):
        words, t = [], 0.0
        for i in range(120):
            gap = 0.9 if i == 70 else 0.1
            words.append(word(i, t, t + 0.3, "word"))
            t += 0.3 + gap
        words[-1]["text"] = "end."
        found = clips.sentences(words)
        self.assertGreaterEqual(len(found), 2)
        self.assertEqual(found[0]["last"], 70)
        self.assertTrue(
            all(s["end"] - s["start"] <= clips.MAX_SENTENCE_S for s in found)
        )


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.words, self.expected, self.duration = talk(minutes=12)
        self.result = clips.find_candidates(self.words, self.duration)
        self.candidates = self.result["candidates"]

    def test_a_ten_minute_talk_gives_at_least_five_sentence_bounded_candidates(self):
        self.assertGreaterEqual(len(self.candidates), 5)
        self.assertLessEqual(len(self.candidates), clips.DEFAULT_COUNT)
        starts = {first for first, _ in self.expected}
        ends = {last for _, last in self.expected}
        by_id = {w["id"]: w for w in self.words}
        for item in self.candidates:
            with self.subTest(item=item["id"]):
                self.assertIn(item["first_word_id"], starts)
                self.assertIn(item["last_word_id"], ends)
                self.assertGreaterEqual(item["duration"], clips.DEFAULT_MIN_S)
                self.assertLessEqual(item["duration"], clips.DEFAULT_MAX_S)
                self.assertAlmostEqual(item["duration"], item["end"] - item["start"])
                first = by_id[item["first_word_id"]]
                last = by_id[item["last_word_id"]]
                # Boundaries sit in the silence around the first and last word.
                self.assertLessEqual(item["start"], first["start"])
                self.assertGreaterEqual(item["end"], last["end"])
                before = by_id.get(item["first_word_id"] - 1)
                after = by_id.get(item["last_word_id"] + 1)
                if before:
                    self.assertGreaterEqual(item["start"], before["end"])
                if after:
                    self.assertLessEqual(item["end"], after["start"])
                self.assertTrue(item["text"].startswith(first["text"]))
                self.assertTrue(item["text"].endswith(last["text"]))
                self.assertTrue(0 <= item["score"] <= 100)
                self.assertIsInstance(item["score"], int)
                self.assertTrue(item["reasons"])
                for reason in item["reasons"]:
                    self.assertIsInstance(reason["text"], str)
                    self.assertIsInstance(reason["points"], int)

    def test_candidates_do_not_overlap_and_are_ranked_by_score(self):
        spans = sorted((c["start"], c["end"]) for c in self.candidates)
        for (_, end), (start, _) in zip(spans, spans[1:]):
            self.assertLessEqual(end, start)
        scores = [c["score"] for c in self.candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual([c["rank"] for c in self.candidates], list(range(1, 9)))
        self.assertEqual(len({c["id"] for c in self.candidates}), len(self.candidates))

    def test_candidates_spread_across_the_video(self):
        middles = [(c["start"] + c["end"]) / 2 for c in self.candidates]
        self.assertTrue(any(m < self.duration / 3 for m in middles))
        self.assertTrue(any(m > 2 * self.duration / 3 for m in middles))

    def test_punctuated_candidates_use_real_stops_and_never_cut_overlapping_words(self):
        words, _, duration = talk(minutes=12)
        # A long unpunctuated stretch in an otherwise punctuated transcript
        # must not be advertised as complete sentences.
        for w in words[200:500]:
            w["text"] = w["text"].rstrip(".!?")
        # A previous timestamp reaches into the next sentence.
        words[799]["end"] = words[803]["end"]
        found = clips.find_candidates(words, duration, count=8)
        sentences = clips.sentences(words)
        starts = {s["first_id"]: i for i, s in enumerate(sentences)}
        ends = {s["last_id"]: i for i, s in enumerate(sentences)}
        for c in found["candidates"]:
            i, j = starts[c["first_word_id"]], ends[c["last_word_id"]]
            self.assertNotEqual(sentences[j]["end_kind"], "pause")
            if i:
                self.assertNotEqual(sentences[i - 1]["end_kind"], "pause")
            for edge in (c["start"], c["end"]):
                self.assertFalse(any(w["start"] < edge < w["end"] for w in words))

    def test_results_are_deterministic(self):
        again = clips.find_candidates(self.words, self.duration)
        self.assertEqual(again, self.result)

    def test_settings_and_platform_defaults(self):
        self.assertEqual(self.result["settings"]["min_s"], 20)
        self.assertEqual(self.result["settings"]["max_s"], 90)
        self.assertEqual(self.result["mode"], "punctuation")
        shorts = clips.find_candidates(
            self.words, self.duration, platform="youtube_shorts", count=5
        )
        self.assertEqual(shorts["settings"]["max_s"], 60)
        self.assertEqual(len(shorts["candidates"]), 5)
        self.assertTrue(all(c["duration"] <= 60 for c in shorts["candidates"]))
        narrow = clips.find_candidates(self.words, self.duration, min_s=30, max_s=40)
        self.assertTrue(all(30 <= c["duration"] <= 40 for c in narrow["candidates"]))

    def test_bounds_are_validated(self):
        for bad in (
            {"min_s": 10},
            {"max_s": 120},
            {"min_s": 60, "max_s": 30},
            {"count": 0},
            {"count": 21},
            {"count": True},
            {"min_s": float("nan")},
            {"platform": "vine"},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                clips.find_candidates(self.words, self.duration, **bad)

    def test_short_or_empty_transcripts_give_no_candidates(self):
        self.assertEqual(clips.find_candidates([], 600)["candidates"], [])
        words, _, duration = talk(minutes=0.25)
        self.assertEqual(clips.find_candidates(words, duration)["candidates"], [])

    def test_without_punctuation_the_pauses_bound_the_candidates(self):
        words, expected, duration = talk(minutes=12, punctuated=False)
        result = clips.find_candidates(words, duration)
        self.assertEqual(result["mode"], "pauses")
        self.assertGreaterEqual(len(result["candidates"]), 5)
        starts = {first for first, _ in expected}
        ends = {last for _, last in expected}
        for item in result["candidates"]:
            self.assertIn(item["first_word_id"], starts)
            self.assertIn(item["last_word_id"], ends)


class ScoreTests(unittest.TestCase):
    def window(self, opener):
        """One block of about 36 s that starts with ``opener``."""
        texts = [opener] + ["The old maps showed streams that nobody remembered."] * 9
        words, t = [], 0.5
        for text in texts:
            for token in text.split():
                words.append(word(len(words), round(t, 3), round(t + 0.3, 3), token))
                t += 0.38
            t += 0.52
        return words, round(t + 0.5, 3)

    def score(self, opener, **options):
        words, duration = self.window(opener)
        item = clips.score_range(words, duration, 0, words[-1]["id"], **options)
        self.assertEqual(item["first_word_id"], 0)
        return item

    def test_question_opening_beats_a_dangling_connective(self):
        question = self.score("Why do cities flood every spring?")
        dangling = self.score("And the river came back.")
        self.assertGreater(question["score"], dangling["score"])
        self.assertIn("Opens with a question", [r["text"] for r in question["reasons"]])
        texts = [r["text"] for r in dangling["reasons"]]
        self.assertIn('Starts mid-thought: "And"', texts)
        penalty = next(r for r in dangling["reasons"] if r["text"].startswith("Starts"))
        self.assertLess(penalty["points"], 0)

    def test_hook_signals_are_explained(self):
        reasons = [
            r["text"] for r in self.score("You can fix 3 drains today.")["reasons"]
        ]
        self.assertIn("Speaks to the viewer", reasons)
        self.assertIn("Opens with a number", reasons)
        reasons = [r["text"] for r in self.score("It was raining.")["reasons"]]
        self.assertIn(
            'Opens with "It", which may point to something said earlier', reasons
        )

    def test_long_pauses_and_unclear_speech_lower_the_score(self):
        words, duration = self.window("Here is the simple truth about water.")
        clean = clips.score_range(words, duration, 0, words[-1]["id"])
        for item in words[20:]:
            item["start"] += 3.0
            item["end"] += 3.0
        for item in words:
            item["probability"] = 0.3
        slow = clips.score_range(words, duration + 3.0, 0, words[-1]["id"])
        self.assertLess(slow["score"], clean["score"])
        texts = " ".join(r["text"] for r in slow["reasons"])
        self.assertIn("long pause", texts)
        self.assertIn("hard to make out", texts)

    def test_face_samples_add_an_on_screen_reason(self):
        faces = [[t / 2, [[0.5, 0.4, 0.2, 0.3, 0.35, None]]] for t in range(80)]
        item = self.score("Here is the simple truth about water.", faces=faces)
        self.assertIn("Speaker on screen", [r["text"] for r in item["reasons"]])
        empty = [[t / 2, []] for t in range(80)]
        item = self.score("Here is the simple truth about water.", faces=empty)
        self.assertTrue(any("on screen only" in r["text"] for r in item["reasons"]))

    def test_quiet_cut_points_never_move_into_a_word(self):
        words, duration = self.window("Here is the simple truth about water.")
        step = 0.02
        levels = [-20.0] * int(duration / step + 2)
        levels[round((words[0]["start"] + 0.02) / step)] = -90.0
        levels[round((words[-1]["end"] - 0.02) / step)] = -90.0
        c = clips.score_range(
            words, duration, 0, words[-1]["id"], energy={"step": step, "db": levels}
        )
        self.assertLessEqual(c["start"], words[0]["start"])
        self.assertGreaterEqual(c["end"], words[-1]["end"])
        self.assertEqual(
            c["score"],
            max(0, min(100, clips.BASE_SCORE + sum(r["points"] for r in c["reasons"]))),
        )

    def test_cut_points_follow_the_quietest_moment_of_the_gap(self):
        words, duration = self.window("Here is the simple truth about water.")
        step = 0.02
        levels = [-20.0] * int(duration / step + 2)
        # A quiet spot 0.12 s before the first word, louder elsewhere in the gap.
        levels[int(round((words[0]["start"] - 0.12) / step))] = -70.0
        energy = {"step": step, "db": levels}
        item = clips.score_range(words, duration, 0, words[-1]["id"], energy=energy)
        self.assertAlmostEqual(item["start"], words[0]["start"] - 0.12, delta=0.011)
        result = clips.find_candidates(words, duration, count=1, energy=energy)
        self.assertTrue(result["energy"])
        self.assertFalse(clips.find_candidates(words, duration, count=1)["energy"])


class SnapTests(unittest.TestCase):
    def test_a_free_range_snaps_to_the_nearest_sentence_boundaries(self):
        words, expected, duration = talk(minutes=3)
        target_first, _ = expected[3]
        _, target_last = expected[9]
        start = words[target_first]["start"] + 0.9
        end = words[target_last]["end"] - 0.7
        snapped = clips.snap_range(words, duration, start, end)
        self.assertEqual(snapped["first_word_id"], target_first)
        self.assertEqual(snapped["last_word_id"], target_last)
        self.assertLessEqual(snapped["start"], words[target_first]["start"])
        self.assertGreaterEqual(snapped["end"], words[target_last]["end"])
        with self.assertRaises(ValueError):
            clips.snap_range(words, duration, 50.0, 40.0)
        with self.assertRaises(ValueError):
            clips.snap_range([], duration, 0.0, 30.0)


if __name__ == "__main__":
    unittest.main()
