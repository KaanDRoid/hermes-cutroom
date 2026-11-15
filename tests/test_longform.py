"""Long-form YouTube delivery: chapters, thumbnail, sidecar SRT and end-screen space."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cutroom import longform
from cutroom.childenv import child_env
from cutroom.platforms import profile

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def run(arguments):
    return subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
        shell=False,
        env=child_env(python=False),
    )


def probe_json(path, *flags):
    return json.loads(
        run(["ffprobe", "-v", "error", *flags, "-of", "json", str(path)]).stdout
    )


def synthetic_video(path, width=1920, height=1080, seconds=40, rate=25):
    run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={width}x{height}:rate={rate}:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
    )
    return path


def gray(path):
    """Decoded luma of an image as a numpy array."""
    import numpy as np

    info = probe_json(path, "-show_streams")["streams"][0]
    raw = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=120,
    ).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(info["height"], info["width"])


def changed_region(first, second, threshold=40):
    """Bounding box (x0, y0, x1, y1) of pixels that differ clearly, or None."""
    import numpy as np

    difference = np.abs(gray(first).astype(int) - gray(second).astype(int)) > threshold
    rows, columns = np.where(difference)
    if not len(rows):
        return None
    return (
        int(columns.min()),
        int(rows.min()),
        int(columns.max()) + 1,
        int(rows.max()) + 1,
    )


TOPICS = [
    "coal plants burn coal and coal smoke fills the air near coal mines".split(),
    "ocean water warms and ocean ice melts while ocean levels rise".split(),
    "solar panels and solar farms turn sunlight into cheap solar power".split(),
]


def topic_words(per_topic=60.0, step=0.5, pause=2.0):
    """Three distinct topics; sentences of twelve words end with a period."""
    words, time = [], 0.0
    for index, topic in enumerate(TOPICS):
        if index:
            time += pause
        end = time + per_topic
        position = 0
        while time + step <= end:
            text = topic[position % len(topic)]
            position += 1
            if position % len(topic) == 0:
                text += "."
            words.append({"start": time, "end": time + step * 0.8, "text": text})
            time += step
    return words


class ChapterRuleTests(unittest.TestCase):
    def test_rules_come_from_the_sourced_profile(self):
        rules = profile("youtube")["chapters"]
        self.assertEqual(
            rules["source"], "https://support.google.com/youtube/answer/9884579"
        )
        self.assertEqual(rules["checked"], "2026-11-13")
        self.assertEqual(
            (rules["first_s"], rules["min_count"], rules["min_length_s"]), (0, 3, 10)
        )
        cover = profile("youtube")["cover"]
        self.assertEqual(cover["max_bytes"], 2_000_000)
        self.assertEqual(profile("youtube")["end_screen"]["min_video_s"], 25)

    def test_validation_normalises_shape_and_rejects_bad_entries(self):
        chapters = longform.validate_chapters(
            [
                {"start": 75.5, "title": "  Second part "},
                {"start": 0, "title": "Intro"},
            ]
        )
        self.assertEqual(
            chapters,
            [{"start": 0.0, "title": "Intro"}, {"start": 75.5, "title": "Second part"}],
        )
        self.assertIsNone(longform.validate_chapters(None))
        for bad in (
            "0:00 Intro",
            [{"start": -1, "title": "x"}],
            [{"start": float("nan"), "title": "x"}],
            [{"start": True, "title": "x"}],
            [{"start": 0, "title": ""}],
            [{"start": 0, "title": "x" * 101}],
            [{"start": 0, "title": "two\nlines"}],
            [{"start": 0, "title": "x", "extra": 1}],
            [{"start": 0, "title": "x"}] * 101,
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                longform.validate_chapters(bad)

    def test_problems_follow_youtube_rules_in_plain_words(self):
        good = [
            {"start": 0, "title": "Intro"},
            {"start": 10, "title": "Middle"},
            {"start": 20, "title": "End"},
        ]
        self.assertEqual(longform.chapter_problems(good, 30), [])
        self.assertEqual(longform.chapter_problems([], 30), [])
        problems = longform.chapter_problems(good[:2], 30)
        self.assertEqual(len(problems), 1)
        self.assertIn("at least three chapters", problems[0])
        late = [{"start": 3, "title": "Intro"}, *good[1:], {"start": 25, "title": "X"}]
        text = " ".join(longform.chapter_problems(late, 40))
        self.assertIn("first chapter must start at 0:00", text)
        self.assertIn("“End” (0:20) is 5 s long", text)
        short = longform.chapter_problems(good, 29.5)
        self.assertTrue(any("“End”" in item and "9 s" in item for item in short))
        after = longform.chapter_problems([*good, {"start": 50, "title": "Gone"}], 45)
        self.assertTrue(any("after the video ends" in item for item in after))

    def test_description_block_and_metadata_use_whole_seconds(self):
        chapters = [
            {"start": 0, "title": "Intro"},
            {"start": 65.9, "title": "How it works"},
            {"start": 600, "title": "Questions"},
        ]
        self.assertEqual(
            longform.description_block(chapters, 900),
            "0:00 Intro\n1:05 How it works\n10:00 Questions\n",
        )
        hours = [*chapters, {"start": 3725, "title": "Late"}]
        self.assertEqual(
            longform.description_block(hours, 4000).splitlines(),
            [
                "0:00:00 Intro",
                "0:01:05 How it works",
                "0:10:00 Questions",
                "1:02:05 Late",
            ],
        )
        meta = longform.ffmetadata(
            [{"start": 0, "title": "A=b;#c\\"}, {"start": 10, "title": "B"}], 20.5
        )
        self.assertTrue(meta.startswith(";FFMETADATA1\n"))
        self.assertIn("START=0\nEND=10000\ntitle=A\\=b\\;\\#c\\\\\n", meta)
        self.assertIn("START=10000\nEND=20500\ntitle=B\n", meta)

    def test_chapters_follow_cuts_and_report_moves(self):
        chapters = [
            {"start": 0, "title": "Intro"},
            {"start": 30, "title": "Coal"},
            {"start": 60, "title": "Ocean"},
        ]
        old = [{"start": 0, "end": 100}]
        # Remove source 10-20 s: later chapters move 10 s earlier.
        new = [{"start": 0, "end": 10}, {"start": 20, "end": 100}]
        moved, notes = longform.follow_edit(chapters, old, new)
        self.assertEqual([c["start"] for c in moved], [0, 20, 50])
        self.assertTrue(any("“Coal” moved from 0:30 to 0:20" in note for note in notes))
        # A chapter whose moment was cut starts where the edit resumes.
        new = [{"start": 0, "end": 25}, {"start": 40, "end": 100}]
        moved, _ = longform.follow_edit(chapters, old, new)
        self.assertEqual([c["start"] for c in moved], [0, 25, 45])
        # The first chapter stays at 0:00 even when earlier footage returns.
        moved, _ = longform.follow_edit(
            chapters, [{"start": 5, "end": 100}], [{"start": 0, "end": 100}]
        )
        self.assertEqual(moved[0]["start"], 0)
        self.assertEqual(moved[1]["start"], 35)
        # A cut that squeezes a chapter below 10 s is reported.
        new = [{"start": 0, "end": 35}, {"start": 57, "end": 100}]
        moved, notes = longform.follow_edit(chapters, old, new)
        self.assertTrue(
            any("needs at least 10 s" in note or "s long" in note for note in notes)
        )


class SuggestTests(unittest.TestCase):
    def test_suggestions_split_topics_at_sentence_starts(self):
        words = topic_words()
        duration = words[-1]["end"] + 1
        chapters = longform.suggest_chapters(words, duration)
        self.assertEqual(len(chapters), 3)
        self.assertEqual(chapters[0]["start"], 0)
        self.assertEqual(longform.chapter_problems(chapters, duration), [])
        starts = {round(w["start"], 3) for w in words}
        for chapter, boundary, word in zip(
            chapters[1:], (62.0, 124.0), ("ocean", "solar")
        ):
            with self.subTest(word=word):
                self.assertLessEqual(abs(chapter["start"] - boundary), 1.0)
                self.assertIn(word, chapter["title"].lower())
                self.assertIn(round(chapter["start_word"], 3), starts)
                self.assertTrue(chapter["reason"])
        self.assertIn("coal", chapters[0]["title"].lower())
        for chapter in chapters:
            self.assertLessEqual(len(chapter["title"]), 40)
            self.assertEqual(chapter["title"][0], chapter["title"][0].upper())

    def test_short_programs_get_no_suggestions_and_counts_scale(self):
        self.assertEqual(longform.suggest_chapters(topic_words(8, 0.5, 0.5), 25), [])
        self.assertEqual(longform.suggest_chapters([], 600), [])
        self.assertEqual(longform.target_count(300), 3)
        self.assertEqual(longform.target_count(1063), 7)
        self.assertLessEqual(longform.target_count(7200), 20)


class SubtitleTests(unittest.TestCase):
    def words(self):
        text = (
            "This is a fairly long opening sentence that keeps going for quite "
            "a while before it ends. Short one. Then another sentence follows here, "
            "with a comma in the middle of it."
        ).split()
        return [
            {"start": i * 0.4, "end": i * 0.4 + 0.3, "text": token}
            for i, token in enumerate(text)
        ]

    def test_cues_respect_line_length_lines_durations_and_order(self):
        cues = longform.srt_cues(self.words())
        self.assertGreater(len(cues), 2)
        previous = 0
        for cue in cues:
            self.assertLessEqual(len(cue["lines"]), 2)
            for line in cue["lines"]:
                self.assertLessEqual(len(line), 42)
            self.assertGreaterEqual(cue["start"], previous)
            self.assertGreater(cue["end"], cue["start"])
            self.assertLessEqual(cue["end"] - cue["start"], 7.0 + 1e-9)
            previous = cue["end"]
        # Sentence ends close a cue: "Short one." stands alone.
        self.assertIn(["Short one."], [cue["lines"] for cue in cues])
        # A short cue is lengthened toward 5/6 s, up to the start of the next cue.
        index = next(i for i, c in enumerate(cues) if c["lines"] == ["Short one."])
        short, following = cues[index], cues[index + 1]
        self.assertGreaterEqual(short["end"], short["word_end"])
        self.assertAlmostEqual(
            short["end"] - short["start"],
            min(5 / 6, following["start"] - short["start"]),
        )
        lonely = longform.srt_cues([{"start": 1.0, "end": 1.2, "text": "Yes."}])
        self.assertAlmostEqual(lonely[0]["end"] - lonely[0]["start"], 5 / 6)

    def test_srt_round_trip_and_timing(self):
        cues = longform.srt_cues(self.words())
        with tempfile.TemporaryDirectory() as temp:
            path = longform.write_srt(cues, Path(temp) / "captions.srt")
            text = Path(path).read_text(encoding="utf-8")
            self.assertTrue(text.startswith("1\n00:00:00,000 --> "))
            parsed = longform.parse_srt(text)
            self.assertEqual([c["lines"] for c in parsed], [c["lines"] for c in cues])
            for got, want in zip(parsed, cues):
                self.assertAlmostEqual(got["start"], want["start"], delta=0.0011)
            report = longform.subtitle_report(text, self.words(), 1 / 30)
            self.assertEqual(report["status"], "pass", report)
            shifted = text.replace("00:00:00,000 -->", "00:00:00,200 -->", 1)
            self.assertEqual(
                longform.subtitle_report(shifted, self.words(), 1 / 30)["status"],
                "fail",
            )
            with self.assertRaises(FileExistsError):
                longform.write_srt(cues, path)


class ThumbnailSizeTests(unittest.TestCase):
    def test_size_never_upscales_past_the_largest_fitting_tier(self):
        self.assertEqual(longform.thumbnail_size(3840, 2160)[:2], (3840, 2160))
        self.assertEqual(longform.thumbnail_size(1920, 1080)[:2], (1920, 1080))
        self.assertEqual(longform.thumbnail_size(2560, 1440)[:2], (1920, 1080))
        self.assertEqual(longform.thumbnail_size(1440, 1080)[:2], (1280, 720))
        width, height, factor = longform.thumbnail_size(640, 360)
        self.assertEqual((width, height), (1280, 720))
        self.assertAlmostEqual(factor, 2.0)
        self.assertEqual(longform.thumbnail_size(1920, 1080)[2], 1.0)

    def test_default_time_prefers_a_large_centred_face_inside_the_edit(self):
        samples = [
            [1.0, [[0.2, 0.4, 0.1, 0.2, 0.3, 0.0]]],
            [5.0, [[0.5, 0.4, 0.2, 0.35, 0.3, 0.05]]],
            [20.0, [[0.5, 0.4, 0.3, 0.5, 0.3, 0.0]]],
        ]
        segments = [{"start": 0, "end": 10}, {"start": 30, "end": 40}]
        self.assertEqual(
            longform.default_thumbnail_time({"face_samples": samples}, segments), 5.0
        )
        # A face turned to the camera wins over a larger face in profile.
        analysis = {
            "face_samples": [
                [2.0, [[0.5, 0.4, 0.2, 0.5, 0.3, 0.0]]],
                [6.0, [[0.5, 0.4, 0.2, 0.4, 0.3, 0.0]]],
            ],
            "frames": [
                {
                    "time": 2.0,
                    "faces": [{"box": [0.4, 0.15, 0.6, 0.65], "gaze_score": 0.2}],
                },
                {
                    "time": 6.0,
                    "faces": [{"box": [0.4, 0.2, 0.6, 0.6], "gaze_score": 0.9}],
                },
            ],
        }
        self.assertEqual(longform.default_thumbnail_time(analysis, segments), 6.0)
        self.assertEqual(
            longform.face_box_at(analysis, 6.4), [0.4, 0.2, 0.6, 0.6000000000000001]
        )
        self.assertIsNone(longform.face_box_at(analysis, 30))
        # Without faces the poster rule applies: 10 % into the program.
        self.assertAlmostEqual(longform.default_thumbnail_time(None, segments), 2.0)

    def test_time_mapping_between_program_and_source(self):
        segments = [{"start": 2, "end": 10}, {"start": 20, "end": 30}]
        self.assertEqual(longform.program_to_source(segments, 0), 2)
        self.assertEqual(longform.program_to_source(segments, 9), 21)
        self.assertEqual(longform.source_to_program(segments, 25), 13)
        self.assertEqual(longform.source_to_program(segments, 15), 8)
        self.assertEqual(longform.source_to_program(segments, 99), 18)


@unittest.skipUnless(FFMPEG, "FFmpeg is required")
class MediaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_thumbnail_is_16_9_jpeg_under_the_limit_with_text_in_safe_margins(self):
        source = synthetic_video(self.root / "big.mp4", 3840, 2160, seconds=2)
        plain = longform.make_thumbnail(source, 1.0, self.root / "plain.jpg")
        self.assertEqual((plain["width"], plain["height"]), (3840, 2160))
        self.assertLessEqual(plain["bytes"], 2_000_000)
        self.assertFalse(plain["upscaled"])
        titled = longform.make_thumbnail(
            source, 1.0, self.root / "titled.jpg", text="Climate change is simple"
        )
        info = probe_json(titled["output"], "-show_streams")["streams"][0]
        self.assertEqual((info["width"], info["height"]), (3840, 2160))
        self.assertEqual(info["codec_name"], "mjpeg")
        box = titled["text_box"]
        self.assertGreaterEqual(box["x0"], 0.05 * 3840 - 1)
        self.assertGreaterEqual(box["y0"], 0.05 * 2160 - 1)
        self.assertLessEqual(box["x1"], 0.95 * 3840 + 1)
        self.assertLessEqual(box["y1"], 0.95 * 2160 + 1)
        # Decoded pixels: the text changes the picture only inside its box.
        changed = changed_region(plain["output"], titled["output"])
        self.assertIsNotNone(changed)
        self.assertGreaterEqual(changed[0], box["x0"] - 8)
        self.assertGreaterEqual(changed[1], box["y0"] - 8)
        self.assertLessEqual(changed[2], box["x1"] + 8)
        self.assertLessEqual(changed[3], box["y1"] + 8)
        # Beside a face on the left, the title goes right, in the upper part.
        beside = longform.make_thumbnail(
            source,
            1.0,
            self.root / "beside.jpg",
            text="Climate change is simple",
            face=[0.05, 0.1, 0.45, 0.7],
        )
        side = beside["text_box"]
        self.assertFalse(side["overlaps_face"])
        self.assertGreaterEqual(side["x0"], 0.45 * 3840)
        self.assertLessEqual(side["y1"], 0.6 * 2160 + 1)
        self.assertEqual(side["lines"], ["Climate change", "is simple"])
        # A large central face pushes the title to the bottom.
        bottom = longform.make_thumbnail(
            source,
            1.0,
            self.root / "bottom.jpg",
            text="Simple",
            face=[0.3, 0.1, 0.7, 0.7],
        )["text_box"]
        self.assertEqual(bottom["region"], "bottom")
        self.assertFalse(bottom["overlaps_face"])
        self.assertLessEqual(bottom["y1"], 0.95 * 2160 + 1)
        small = synthetic_video(self.root / "small.mp4", 640, 360, seconds=2)
        upscaled = longform.make_thumbnail(small, 0.5, self.root / "small.jpg")
        self.assertEqual((upscaled["width"], upscaled["height"]), (1280, 720))
        self.assertTrue(upscaled["upscaled"])
        tight = longform.make_thumbnail(
            source, 1.0, self.root / "tight.jpg", max_bytes=150_000
        )
        self.assertLessEqual(tight["bytes"], 150_000)
        with self.assertRaises(FileExistsError):
            longform.make_thumbnail(source, 1.0, self.root / "plain.jpg")

    def test_delivery_embeds_chapters_and_writes_sidecars(self):
        video = synthetic_video(self.root / "final.mp4", 320, 180, seconds=40)
        source = synthetic_video(self.root / "source.mp4", 1920, 1080, seconds=40)
        chapters = [
            {"start": 0, "title": "Intro"},
            {"start": 12.4, "title": "Ocean ice"},
            {"start": 25, "title": "Solar power"},
        ]
        words = [
            {"start": 1.0 + i, "end": 1.6 + i, "text": f"word{i}."} for i in range(30)
        ]
        before = video.stat().st_size
        result = longform.deliver(
            video=str(video),
            output_dir=str(self.root),
            duration=40.0,
            chapters=chapters,
            words=words,
            subtitles=True,
            thumbnail={"source": str(source), "time": 3.0, "text": "Hello"},
        )
        self.assertTrue(result["chapters_embedded"])
        self.assertNotEqual(video.stat().st_size, before)
        listed = probe_json(video, "-show_chapters")["chapters"]
        self.assertEqual(
            [c["tags"]["title"] for c in listed], ["Intro", "Ocean ice", "Solar power"]
        )
        self.assertEqual([float(c["start_time"]) for c in listed], [0.0, 12.0, 25.0])
        self.assertEqual(
            Path(result["artifacts"]["chapters"]).read_text(encoding="utf-8"),
            "0:00 Intro\n0:12 Ocean ice\n0:25 Solar power\n",
        )
        self.assertTrue(Path(result["artifacts"]["captions_srt"]).is_file())
        self.assertTrue(Path(result["artifacts"]["captions_vtt"]).is_file())
        self.assertEqual(result["thumbnail"]["width"], 1920)
        # Streams are copied, not re-encoded.
        streams = probe_json(video, "-show_streams")["streams"]
        media = {
            s["codec_type"]: s["codec_name"]
            for s in streams
            if s["codec_type"] != "data"
        }
        self.assertEqual(media, {"video": "h264", "audio": "aac"})

        info = {"duration": 40.0, "width": 320, "height": 180}
        checks = []
        longform.quality_checks(
            lambda name, status, detail: checks.append((name, status, detail)),
            video,
            info,
            {
                "chapters": chapters,
                "duration": 40.0,
                "chapters_file": result["artifacts"]["chapters"],
                "subtitles_file": result["artifacts"]["captions_srt"],
                "words": words,
                "thumbnail": result["artifacts"]["thumbnail"],
                "end_screen_s": 10,
                "frame_interval": 1 / 25,
            },
        )
        status = {name: value for name, value, _ in checks}
        self.assertEqual(
            status,
            {
                "chapters": "pass",
                "subtitles_file": "pass",
                "thumbnail": "pass",
                "end_screen": "pass",
            },
            checks,
        )

    def test_quality_checks_report_problems(self):
        video = synthetic_video(self.root / "plain.mp4", 320, 180, seconds=20)
        bad = self.root / "bad.jpg"
        run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=gray:size=800x800",
                "-frames:v",
                "1",
                str(bad),
            ]
        )
        checks = []
        longform.quality_checks(
            lambda name, status, detail: checks.append((name, status, detail)),
            video,
            {"duration": 20.0, "width": 320, "height": 180},
            {
                "chapters": [{"start": 0, "title": "A"}, {"start": 12, "title": "B"}],
                "duration": 20.0,
                "thumbnail": str(bad),
                "end_screen_s": 20,
                "burned_captions": [{"start": 15.0, "end": 16.0, "text": "late"}],
                "title": "On screen",
            },
        )
        status = {name: value for name, value, _ in checks}
        self.assertEqual(status["chapters"], "fail")
        self.assertEqual(status["thumbnail"], "fail")
        self.assertEqual(status["end_screen"], "fail")
        detail = dict((name, d) for name, _, d in checks)["end_screen"]
        self.assertTrue(any("25 s" in item for item in detail["problems"]))
        self.assertTrue(any("caption" in item for item in detail["notes"]))
        self.assertTrue(any("title" in item for item in detail["notes"]))
        checks.clear()
        longform.quality_checks(
            lambda name, status, detail: checks.append((name, status, detail)),
            video,
            {"duration": 40.0, "width": 320, "height": 180},
            {
                "duration": 40.0,
                "end_screen_s": 10,
                "burned_captions": [{"start": 35.0, "end": 36.0, "text": "late"}],
            },
        )
        self.assertEqual(dict((n, s) for n, s, _ in checks)["end_screen"], "warning")
        self.assertEqual(dict((n, s) for n, s, _ in checks)["chapters"], "skip")


if __name__ == "__main__":
    unittest.main()
