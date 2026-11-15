"""Studio clip finder: persisted candidates and clips as range-limited projects."""

import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from clip_fixtures import talk, transcript

from cutroom.media import probe
from cutroom.studio import _CHILD_PROCESSES, Studio


class _ClipCase(unittest.TestCase):
    minutes = 12

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "talk.mp4"
        self.source.write_bytes(b"unit source fixture")
        self.words, self.sentences, self.duration = talk(minutes=self.minutes)
        info = {"duration": self.duration, "width": 1920, "height": 1080}
        self.probe = patch(
            "cutroom.studio.probe", return_value={**info, "has_audio": True}
        )
        self.probe.start()
        self.addCleanup(self.probe.stop)
        self.studio = Studio(self.root / "workspace")
        project = self.studio.create(self.source, name="Talk")
        self.project = self.studio.update(
            project["id"], {"transcript": transcript(self.words)}, project["revision"]
        )


class FindClipsTests(_ClipCase):
    def test_find_clips_needs_words(self):
        bare = self.studio.create(self.source, name="Bare")
        with self.assertRaisesRegex(ValueError, "[Tt]ranscribe"):
            self.studio.find_clips(bare["id"])

    def test_candidates_are_stored_without_changing_the_revision_or_digest(self):
        before = self.studio.review(self.project["id"])["digest"]
        result = self.studio.find_clips(self.project["id"])
        self.assertGreaterEqual(len(result["candidates"]), 5)
        stored = self.studio.get(self.project["id"])
        self.assertEqual(stored["revision"], self.project["revision"])
        self.assertEqual(stored["clip_candidates"], result)
        self.assertEqual(self.studio.review(self.project["id"])["digest"], before)
        self.assertEqual(result["settings"]["max_s"], 90)
        shorts = self.studio.find_clips(
            self.project["id"], platform="youtube_shorts", count=5
        )
        self.assertEqual(len(shorts["candidates"]), 5)
        self.assertEqual(shorts["settings"]["max_s"], 60)
        self.assertEqual(
            self.studio.get(self.project["id"])["clip_candidates"]["settings"][
                "platform"
            ],
            "youtube_shorts",
        )

    def test_bounds_are_checked(self):
        for bad in ({"min_s": 5}, {"max_s": 400}, {"count": 99}, {"platform": "x"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.studio.find_clips(self.project["id"], **bad)

    def test_a_new_transcript_drops_stored_candidates(self):
        self.studio.find_clips(self.project["id"])
        project = self.studio.get(self.project["id"])
        changed = transcript([dict(w) for w in self.words])
        changed["words"][0]["text"] = "When"
        updated = self.studio.update(
            project["id"], {"transcript": changed}, project["revision"]
        )
        self.assertNotIn("clip_candidates", updated)
        # Other edits keep them: they are found from the words, not the cut.
        self.studio.find_clips(self.project["id"])
        project = self.studio.get(self.project["id"])
        updated = self.studio.update(
            project["id"], {"brief": "Short clips"}, project["revision"]
        )
        self.assertIn("clip_candidates", updated)


class CreateClipTests(_ClipCase):
    def test_a_candidate_becomes_a_derived_project_limited_to_its_range(self):
        parent = self.studio.get(self.project["id"])
        excluded = [self.words[5]["id"], self.words[600]["id"]]
        parent = self.studio.update(
            parent["id"],
            {"excluded_word_ids": excluded, "settings": {"framing": "blur_fill"}},
            parent["revision"],
        )
        found = self.studio.find_clips(parent["id"], platform="youtube_shorts")
        pick = found["candidates"][0]
        child = self.studio.create_clip(
            parent["id"], "youtube_shorts", candidate_id=pick["id"]
        )
        self.assertNotEqual(child["id"], parent["id"])
        self.assertEqual(child["revision"], 1)
        self.assertEqual(child["status"], "draft")
        self.assertNotIn("approval", child)
        self.assertNotIn("clip_candidates", child)
        self.assertEqual(child["settings"]["platform"], "youtube_shorts")
        self.assertEqual(child["settings"]["framing"], "blur_fill")
        self.assertEqual(
            child["derived_from"]["range"], {"start": pick["start"], "end": pick["end"]}
        )
        self.assertEqual(child["derived_from"]["project_id"], parent["id"])
        self.assertEqual(child["derived_from"]["candidate_id"], pick["id"])
        self.assertEqual(
            child["base_segments"], [{"start": pick["start"], "end": pick["end"]}]
        )
        for segment in child["segments"]:
            self.assertGreaterEqual(segment["start"], pick["start"])
            self.assertLessEqual(segment["end"], pick["end"])
        ids = [w["id"] for w in child["transcript"]["words"]]
        self.assertEqual(ids[0], pick["first_word_id"])
        self.assertEqual(ids[-1], pick["last_word_id"])
        self.assertTrue(set(child["excluded_word_ids"]) <= set(ids) and len(ids) > 10)
        for item in child["excluded_word_ids"]:
            self.assertIn(item, excluded)
        self.assertTrue(
            child["transcript"]["text"].startswith(
                child["transcript"]["words"][0]["text"]
            )
        )
        self.assertIn("clip", child["name"].lower())
        length = sum(s["end"] - s["start"] for s in child["segments"])
        self.assertLessEqual(length, 60.0)
        # The parent is untouched and keeps its candidates.
        after = self.studio.get(parent["id"])
        self.assertEqual(after["revision"], parent["revision"])
        self.assertIn("clip_candidates", after)
        # Captions only use words of the range.
        cues = self.studio._cues(child)
        self.assertTrue(cues)
        self.assertLessEqual(cues[-1]["end"], length + 1e-6)

    def test_a_clip_project_never_reaches_outside_its_range(self):
        found = self.studio.find_clips(self.project["id"])
        pick = found["candidates"][0]
        child = self.studio.create_clip(
            self.project["id"], "instagram_reels", candidate_id=pick["id"]
        )
        updated = self.studio.update(
            child["id"],
            {"segments": [{"start": 0.0, "end": self.duration}]},
            child["revision"],
        )
        self.assertEqual(
            updated["segments"], [{"start": pick["start"], "end": pick["end"]}]
        )
        replaced = self.studio.update(
            child["id"], {"transcript": transcript(self.words)}, updated["revision"]
        )
        words = replaced["transcript"]["words"]
        self.assertEqual(words[0]["id"], pick["first_word_id"])
        self.assertEqual(words[-1]["id"], pick["last_word_id"])
        with self.assertRaisesRegex(ValueError, "range"):
            self.studio.update(
                child["id"],
                {"segments": [{"start": self.duration - 1.0, "end": self.duration}]},
                replaced["revision"],
            )
        # A sibling of a clip keeps the clip's range.
        sibling = self.studio.derive(child["id"], "tiktok")
        self.assertEqual(
            sibling["derived_from"]["range"], child["derived_from"]["range"]
        )
        self.assertEqual(sibling["segments"], replaced["segments"])

    def test_a_clip_drops_long_form_times_of_its_parent(self):
        # Chapters and a chosen thumbnail frame are in the parent's program
        # time; inside a clip they would point at other footage.
        parent = self.studio.get(self.project["id"])
        parent = self.studio.update(
            parent["id"],
            {
                "settings": {
                    "platform": "youtube",
                    "chapters": [
                        {"start": 0, "title": "Opening"},
                        {"start": 200, "title": "Middle"},
                        {"start": 400, "title": "Close"},
                    ],
                    "thumbnail": {"time": 300, "text": "Talk"},
                    "end_screen_s": 10,
                }
            },
            parent["revision"],
        )
        self.assertEqual(len(parent["settings"]["chapters"]), 3)
        first, _ = self.sentences[10]
        _, last = self.sentences[18]
        child = self.studio.create_clip(
            parent["id"],
            "youtube",
            start=self.words[first]["start"],
            end=self.words[last]["end"],
        )
        self.assertNotIn("chapters", child["settings"])
        self.assertNotIn("time", child["settings"].get("thumbnail") or {})
        self.assertEqual(child["settings"]["thumbnail"]["text"], "Talk")
        self.assertEqual(child["settings"]["end_screen_s"], 10)
        summary = self.studio.longform_summary(child)
        self.assertEqual(summary["chapter_problems"], [])
        parent = self.studio.get(parent["id"])
        self.assertEqual(
            len(parent["settings"]["chapters"]), 3, "The parent keeps them"
        )

    def test_a_free_range_is_snapped_to_sentence_boundaries(self):
        first, _ = self.sentences[10]
        _, last = self.sentences[18]
        start = self.words[first]["start"] + 0.8
        end = self.words[last]["end"] - 0.6
        child = self.studio.create_clip(
            self.project["id"], "tiktok", start=start, end=end, name="My clip"
        )
        self.assertEqual(child["name"], "My clip")
        words = child["transcript"]["words"]
        self.assertEqual(words[0]["id"], first)
        self.assertEqual(words[-1]["id"], last)
        span = child["derived_from"]["range"]
        self.assertLessEqual(span["start"], self.words[first]["start"])
        self.assertGreaterEqual(span["end"], self.words[last]["end"])
        self.assertNotIn("candidate_id", child["derived_from"])

    def test_create_clip_arguments_are_checked(self):
        self.studio.find_clips(self.project["id"])
        for kwargs in (
            {},
            {"candidate_id": "clip-missing"},
            {"candidate_id": "x", "start": 1.0, "end": 30.0},
            {"start": 40.0, "end": 10.0},
            {"start": -1.0, "end": 30.0},
            {"start": 10.0, "end": self.duration + 100},
            {"start": 0.0, "end": float("inf")},
            {"start": 10.0, "end": 12.0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.studio.create_clip(self.project["id"], "youtube_shorts", **kwargs)
        with self.assertRaises(ValueError):
            self.studio.create_clip(self.project["id"], "vine", start=0.0, end=30.0)
        # A clip longer than the platform allows is refused before it exists.
        first, _ = self.sentences[0]
        _, last = self.sentences[-1]
        with self.assertRaisesRegex(ValueError, "allows at most"):
            self.studio.create_clip(
                self.project["id"],
                "youtube_shorts",
                start=self.words[first]["start"],
                end=self.words[last]["end"],
            )

    def test_a_clip_of_a_clip_does_not_reopen_padding_outside_its_parent(self):
        found = self.studio.find_clips(self.project["id"])
        pick = found["candidates"][0]
        span = {"start": pick["start"] + 0.05, "end": pick["end"] - 0.05}
        with patch("cutroom.clips.snap_range", return_value=span):
            parent = self.studio.create_clip(
                self.project["id"], "custom", start=span["start"], end=span["end"]
            )
        words = parent["transcript"]["words"]
        child = self.studio.create_clip(
            parent["id"], "custom", start=words[0]["start"], end=words[-1]["end"]
        )
        self.assertGreaterEqual(child["derived_from"]["range"]["start"], span["start"])
        self.assertLessEqual(child["derived_from"]["range"]["end"], span["end"])

    def test_stale_candidates_cannot_be_used(self):
        found = self.studio.find_clips(self.project["id"])
        project = self.studio.get(self.project["id"])
        changed = transcript([dict(w) for w in self.words])
        self.studio.update(project["id"], {"transcript": changed}, project["revision"])
        with self.assertRaisesRegex(ValueError, "[Ff]ind clips"):
            self.studio.create_clip(
                self.project["id"],
                "youtube_shorts",
                candidate_id=found["candidates"][0]["id"],
            )


def _ffmpeg(arguments, timeout=120):
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", *arguments],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=timeout,
    ).stdout


class ClipRenderTests(unittest.TestCase):
    """A clip renders only its range, in sync, from a flash-and-beep source."""

    period = 3.7

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "beeps.mp4"
        p = self.period
        _ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s=160x90:r=30:d=60,drawbox=c=white:t=fill:"
                f"enable='lt(mod(t\\,{p})\\,0.1)'",
                "-f",
                "lavfi",
                "-i",
                f"aevalsrc='if(lt(mod(t\\,{p})\\,0.1)\\,0.5*sin(2*PI*1000*t)\\,0)'"
                ":s=48000:d=60",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(self.source),
            ]
        )
        self.studio = Studio(self.root / "workspace")
        self.addCleanup(self.reap)

    def reap(self):
        for job_id, process in list(_CHILD_PROCESSES.items()):
            try:
                process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                process.kill()
            _CHILD_PROCESSES.pop(job_id, None)

    def run_job(self, project_id, action):
        job = self.studio.submit(project_id, action, {})
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            job = self.studio.job(job["id"])
            if job["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "completed", job)
        return job

    def test_the_render_holds_only_the_range_with_sound_and_picture_in_step(self):
        # Sentences between the beeps, so cut points fall in quiet gaps.
        words, t = [], 0.4
        while t < 57:
            for index in range(6):
                text = "word." if index == 5 else "word"
                words.append(
                    dict(
                        id=len(words),
                        start=round(t, 3),
                        end=round(t + 0.25, 3),
                        text=text,
                        probability=0.9,
                    )
                )
                t += 0.32
            t += 0.5
        project = self.studio.create(self.source, name="Beeps")
        project = self.studio.update(
            project["id"],
            {"transcript": transcript(words)},
            project["revision"],
        )
        found = self.studio.find_clips(project["id"], min_s=20, max_s=30)
        self.assertTrue(found["energy"], "The audio level was measured")
        pick = found["candidates"][0]
        child = self.studio.create_clip(
            project["id"], "custom", candidate_id=pick["id"]
        )
        self.run_job(child["id"], "preview")
        preview = self.studio.artifact(child["id"], "preview")
        length = pick["end"] - pick["start"]
        self.assertAlmostEqual(probe(preview)["duration"], length, delta=0.1)
        # Flash frames and beep onsets in the output.
        luma = _ffmpeg(
            ["-i", str(preview), "-vf", "scale=16:9,format=gray", "-f", "rawvideo", "-"]
        )
        frames = [luma[i : i + 144] for i in range(0, len(luma), 144)]
        flashes = [
            i / 30
            for i, frame in enumerate(frames)
            if sum(frame) / 144 > 128 and (i == 0 or sum(frames[i - 1]) / 144 <= 128)
        ]
        pcm = _ffmpeg(
            ["-i", str(preview), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
        )
        import array

        samples = array.array("h", pcm)
        window = 80
        loud = [
            max(abs(v) for v in samples[i : i + window]) > 3000
            for i in range(0, len(samples) - window, window)
        ]
        beeps = [
            i * window / 8000
            for i, value in enumerate(loud)
            if value and (i == 0 or not loud[i - 1])
        ]
        expected = [
            k * self.period - pick["start"]
            for k in range(1, 20)
            if pick["start"] + 0.05 < k * self.period < pick["end"] - 0.15
        ]
        self.assertGreaterEqual(len(expected), 4)
        self.assertEqual(len(flashes), len(expected), flashes)
        self.assertEqual(len(beeps), len(expected), beeps)
        for want, flash, beep in zip(expected, flashes, beeps):
            self.assertAlmostEqual(flash, want, delta=1 / 30 + 0.001)
            self.assertAlmostEqual(beep, want, delta=0.025)
            self.assertAlmostEqual(beep, flash, delta=1 / 30 + 0.02)


if __name__ == "__main__":
    unittest.main()
