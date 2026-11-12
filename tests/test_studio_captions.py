"""Studio caption-style settings, word remapping, derive rules and caption jobs."""

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom.studio import _CHILD_PROCESSES, Studio


def word(identifier, start, end, text):
    return dict(id=identifier, start=start, end=end, text=text, probability=0.9)


TRANSCRIPT = {
    "language": "en",
    "engine": "synthetic-fixture",
    "status": "ok",
    "text": "keep this drop that keep going",
    "words": [
        word(0, 0.2, 0.5, "keep"),
        word(1, 0.6, 0.9, "this"),
        word(2, 1.0, 1.3, "drop"),
        word(3, 1.4, 1.7, "that"),
        word(4, 2.0, 2.3, "keep"),
        word(5, 2.4, 2.8, "going"),
    ],
}


class _StudioCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"unit source fixture")
        probe = patch(
            "cutroom.studio.probe",
            return_value={
                "duration": 4.0,
                "width": 320,
                "height": 180,
                "has_audio": True,
            },
        )
        probe.start()
        self.addCleanup(probe.stop)
        self.studio = Studio(self.root / "workspace")
        self.project = self.studio.create(self.source, name="Talk")

    def settings(self, changes):
        project = self.studio.get(self.project["id"])
        return self.studio.update(
            project["id"], {"settings": changes}, project["revision"]
        )


class CaptionSettingsTests(_StudioCase):
    def test_caption_settings_are_validated(self):
        updated = self.settings(
            {
                "caption_style": "highlight",
                "caption_highlight_color": "#00FF88",
                "caption_word_y": 0.4,
            }
        )
        self.assertEqual(updated["settings"]["caption_style"], "highlight")
        revision = updated["revision"]
        for bad in (
            {"caption_style": "karaoke"},
            {"caption_style": None},
            {"caption_highlight_color": "#00FF8"},
            {"caption_highlight_color": 7},
            {"caption_word_y": 2},
            {"caption_word_y": "0.5"},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.settings(bad)
        self.assertEqual(self.studio.get(self.project["id"])["revision"], revision)

    def test_null_optional_caption_fields_reset_to_defaults(self):
        updated = self.settings(
            {"caption_highlight_color": "#00FF88", "caption_word_y": 0.3}
        )
        self.assertEqual(updated["settings"]["caption_word_y"], 0.3)
        reset = self.settings({"caption_highlight_color": None, "caption_word_y": None})
        self.assertNotIn("caption_highlight_color", reset["settings"])
        self.assertNotIn("caption_word_y", reset["settings"])
        # The style itself is required: null is not a reset for it.
        with self.assertRaises(ValueError):
            self.settings({"caption_style": None})

    def test_loading_adds_no_caption_defaults(self):
        legacy = self.studio.get(self.project["id"])
        digest = self.studio.review(legacy["id"])["digest"]
        for key in ("caption_style", "caption_highlight_color", "caption_word_y"):
            self.assertNotIn(key, legacy["settings"])
        self.assertEqual(self.studio.review(legacy["id"])["digest"], digest)

    def test_classic_render_settings_are_unchanged(self):
        legacy = self.studio.get(self.project["id"])
        expected = json.dumps(self.studio._render_settings(legacy, "preview"))
        classic = dict(
            legacy,
            settings={
                **legacy["settings"],
                "caption_style": "classic",
                "caption_highlight_color": "#00FF88",
                "caption_word_y": 0.3,
            },
        )
        self.assertEqual(
            json.dumps(self.studio._render_settings(classic, "preview")), expected
        )
        animated = dict(
            legacy,
            settings={
                **legacy["settings"],
                "caption_style": "pop",
                "caption_highlight_color": "#00FF88",
            },
        )
        render = self.studio._render_settings(animated, "preview")
        self.assertEqual(render["caption_style"], "pop")
        self.assertEqual(render["caption_highlight_color"], "#00FF88")
        self.assertNotIn("caption_word_y", render)
        from cutroom import postproduction as pp

        self.assertEqual(pp._settings(render)["caption_style"], "pop")


class CaptionWordTests(_StudioCase):
    def test_words_are_remapped_after_cuts_and_exclusions(self):
        stored = self.studio.get(self.project["id"])
        stored["transcript"] = TRANSCRIPT
        stored["excluded_word_ids"] = [2]
        # Keep 0.0-0.95 and 1.35-3.0; "drop" is excluded and also cut.
        stored["segments"] = [
            {"start": 0.0, "end": 0.95},
            {"start": 1.35, "end": 3.0},
        ]
        words = self.studio._caption_words(stored)
        self.assertEqual(
            [w["text"] for w in words], ["keep", "this", "that", "keep", "going"]
        )
        self.assertNotIn("drop", [w["text"] for w in words])
        self.assertAlmostEqual(words[2]["start"], 0.95 + 0.05)
        self.assertAlmostEqual(words[4]["end"], 0.95 + 2.8 - 1.35)
        for item in words:
            self.assertEqual(set(item), {"start", "end", "text"})

    def test_a_word_split_by_a_cut_is_shown_once(self):
        stored = self.studio.get(self.project["id"])
        stored["transcript"] = TRANSCRIPT
        stored["segments"] = [
            {"start": 0.0, "end": 2.6},
            {"start": 2.7, "end": 4.0},
        ]
        words = self.studio._caption_words(stored)
        self.assertEqual([w["text"] for w in words].count("going"), 1)
        going = words[-1]
        self.assertAlmostEqual(going["start"], 2.4)
        self.assertAlmostEqual(going["end"], 2.6 + 0.1)


class DeriveCaptionTests(_StudioCase):
    def test_switching_to_youtube_disables_burn_in_unless_explicitly_enabled(self):
        self.settings({"captions": True})
        youtube = self.settings({"platform": "youtube"})
        self.assertIs(youtube["settings"]["captions"], False)
        enabled = self.settings({"captions": True})
        self.assertIs(enabled["settings"]["captions"], True)
        self.settings({"platform": "instagram_reels"})
        explicit = self.settings({"platform": "youtube", "captions": True})
        self.assertIs(explicit["settings"]["captions"], True)

    def test_youtube_versions_deliver_sidecar_captions_without_burn_in(self):
        parent = self.settings({"captions": True, "caption_style": "highlight"})
        youtube = self.studio.derive(parent["id"], "youtube")
        self.assertIs(youtube["settings"]["captions"], False)
        self.assertEqual(youtube["settings"]["caption_style"], "highlight")
        reels = self.studio.derive(parent["id"], "instagram_reels")
        self.assertIs(reels["settings"]["captions"], True)
        custom = self.studio.derive(parent["id"], "custom")
        self.assertIs(custom["settings"]["captions"], True)


class CaptionJobTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "talk.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=30:duration=3",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=330:sample_rate=48000:duration=3",
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
            ],
            capture_output=True,
            check=True,
            timeout=60,
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

    def test_highlight_preview_publishes_its_script_and_qa_checks_it(self):
        project = self.studio.create(self.source, name="Talk")
        project = self.studio.update(
            project["id"],
            {
                "settings": {
                    "platform": "instagram_reels",
                    "captions": True,
                    "caption_style": "highlight",
                },
                "segments": [{"start": 0.0, "end": 0.95}, {"start": 1.35, "end": 3.0}],
                "transcript": TRANSCRIPT,
                "excluded_word_ids": [2],
            },
            project["revision"],
        )
        job = self.run_job(project["id"], "preview")
        self.assertEqual(job["result"]["caption_style"], "highlight")
        script = self.studio.artifact(project["id"], "captions_ass")
        text = script.read_text(encoding="utf-8-sig")
        self.assertNotIn("drop", text)
        self.assertIn("going", text)
        qa = self.run_job(project["id"], "qa")
        checks = {check["name"]: check for check in qa["result"]["checks"]}
        timing = checks["caption_timing"]
        self.assertEqual(timing["status"], "pass", timing)
        self.assertEqual(timing["detail"]["words_checked"], 5)
        self.assertEqual(timing["detail"]["script"], "published")
        self.assertEqual(checks["caption_bounds"]["status"], "pass")
        self.assertEqual(checks["safe_zone"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
