"""Studio wiring for long-form YouTube: settings, chapters after edits, jobs and QA."""

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom.studio import _CHILD_PROCESSES, Studio


def probe_result(duration=200.0, width=1920, height=1080):
    return {"duration": duration, "width": width, "height": height, "has_audio": True}


def words(count=300, step=0.6, topics=("coal", "ocean", "solar")):
    """Three topics, one after another, with a sentence end every ten words."""
    result = []
    per = count // len(topics)
    for index in range(count):
        topic = topics[min(index // per, len(topics) - 1)]
        text = f"{topic}" if index % 3 else f"{topic}s"
        if index % 10 == 9:
            text += "."
        start = 0.5 + index * step
        result.append(
            {
                "id": index,
                "start": round(start, 3),
                "end": round(start + step * 0.8, 3),
                "text": text,
                "probability": 0.9,
            }
        )
    return {
        "language": "en",
        "engine": "synthetic-fixture",
        "status": "ok",
        "text": " ".join(w["text"] for w in result),
        "words": result,
    }


CHAPTERS = [
    {"start": 0, "title": "Intro"},
    {"start": 60, "title": "Oceans"},
    {"start": 120, "title": "Solar"},
]


class _Case(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "talk.mp4"
        self.source.write_bytes(b"unit source fixture")
        probe = patch("cutroom.studio.probe", return_value=probe_result())
        probe.start()
        self.addCleanup(probe.stop)
        self.studio = Studio(self.root / "workspace")
        self.project = self.studio.create(self.source, name="Talk")

    def update(self, changes):
        project = self.studio.get(self.project["id"])
        return self.studio.update(project["id"], changes, project["revision"])


class LongformSettingsTests(_Case):
    def test_settings_are_validated_normalised_and_removable(self):
        updated = self.update(
            {
                "settings": {
                    "platform": "youtube",
                    "chapters": list(reversed(CHAPTERS)),
                    "thumbnail": {"time": 12.5, "text": " Climate "},
                    "subtitles_file": False,
                    "end_screen_s": 20,
                }
            }
        )
        settings = updated["settings"]
        self.assertEqual(settings["chapters"], CHAPTERS)
        self.assertEqual(settings["thumbnail"], {"time": 12.5, "text": "Climate"})
        self.assertIs(settings["subtitles_file"], False)
        self.assertEqual(settings["end_screen_s"], 20)
        revision = updated["revision"]
        for bad in (
            {"chapters": [{"start": "0", "title": "x"}]},
            {"thumbnail": {"time": -1}},
            {"thumbnail": {"text": "x" * 101}},
            {"thumbnail": {"frame": 1}},
            {"subtitles_file": "yes"},
            {"end_screen_s": 4},
            {"end_screen_s": 21},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.update({"settings": bad})
        self.assertEqual(self.studio.get(self.project["id"])["revision"], revision)
        removed = self.update(
            {
                "settings": {
                    "chapters": None,
                    "thumbnail": None,
                    "subtitles_file": None,
                    "end_screen_s": None,
                }
            }
        )
        for key in ("chapters", "thumbnail", "subtitles_file", "end_screen_s"):
            self.assertNotIn(key, removed["settings"])

    def test_settings_are_part_of_the_reviewed_digest_and_absent_by_default(self):
        self.update({"settings": {"platform": "youtube"}})
        project = self.studio.get(self.project["id"])
        for key in ("chapters", "thumbnail", "subtitles_file", "end_screen_s"):
            self.assertNotIn(key, project["settings"])
        before = self.studio.review(self.project["id"])["digest"]
        self.update({"settings": {"chapters": CHAPTERS}})
        middle = self.studio.review(self.project["id"])["digest"]
        self.assertNotEqual(before, middle)
        self.update({"settings": {"thumbnail": {"text": "New"}}})
        self.assertNotEqual(middle, self.studio.review(self.project["id"])["digest"])

    def test_chapters_follow_cuts_with_plain_notes(self):
        self.update({"settings": {"platform": "youtube", "chapters": CHAPTERS}})
        updated = self.update(
            {"segments": [{"start": 0, "end": 30}, {"start": 40, "end": 200}]}
        )
        self.assertEqual(
            [c["start"] for c in updated["settings"]["chapters"]], [0, 50, 110]
        )
        self.assertTrue(
            any("“Oceans” moved from 1:00 to 0:50" in n for n in updated["notes"])
        )
        # Removing the words around a chapter start moves it to where the edit resumes.
        self.update({"segments": [{"start": 0, "end": 200}]})
        self.update({"settings": {"chapters": CHAPTERS}})
        squeezed = self.update(
            {"segments": [{"start": 0, "end": 55}, {"start": 64, "end": 200}]}
        )
        self.assertEqual(
            [c["start"] for c in squeezed["settings"]["chapters"]], [0, 55, 111]
        )
        # A cut that leaves a chapter too short is reported in plain words.
        self.update({"segments": [{"start": 0, "end": 200}]})
        self.update({"settings": {"chapters": CHAPTERS}})
        short = self.update(
            {"segments": [{"start": 0, "end": 65}, {"start": 116, "end": 200}]}
        )
        self.assertTrue(
            any("at least 10 s" in n for n in short["notes"]), short.get("notes")
        )

    def test_final_export_is_refused_while_chapters_break_youtube_rules(self):
        self.update({"settings": {"platform": "youtube", "chapters": CHAPTERS[:2]}})
        project = self.studio.get(self.project["id"])
        self.studio.approve(project["id"], self.studio.review(project["id"])["digest"])
        with self.assertRaisesRegex(ValueError, "at least three chapters"):
            self.studio.submit(project["id"], "final")
        self.assertEqual(self.studio.jobs(project["id"]), [])

    def test_suggestions_and_summary_for_the_chat(self):
        self.update({"settings": {"platform": "youtube"}, "transcript": words()})
        suggestion = self.studio.suggest_chapters(self.project["id"])
        self.assertGreaterEqual(len(suggestion["chapters"]), 3)
        self.assertEqual(suggestion["chapters"][0]["start"], 0)
        self.assertEqual(suggestion["problems"], [])
        self.assertIn(
            "ocean", " ".join(c["title"].lower() for c in suggestion["chapters"])
        )
        # Suggesting never saves.
        self.assertNotIn("chapters", self.studio.get(self.project["id"])["settings"])
        summary = self.studio.longform_summary(self.studio.get(self.project["id"]))
        self.assertEqual(summary["chapters"], [])
        self.assertTrue(summary["suggested_chapters"])
        self.update({"settings": {"chapters": CHAPTERS[:2]}})
        summary = self.studio.longform_summary(self.studio.get(self.project["id"]))
        self.assertIn("at least three chapters", " ".join(summary["chapter_problems"]))
        self.assertEqual(summary["description"], "0:00 Intro\n1:00 Oceans\n")
        self.assertNotIn("suggested_chapters", summary)

    def test_subtitle_words_keep_zero_length_words_and_drop_cut_ones(self):
        transcript = {
            "language": "en",
            "engine": "synthetic-fixture",
            "status": "ok",
            "text": "I said you know this",
            "words": [
                {"id": 0, "start": 1.0, "end": 1.0, "text": "I", "probability": 0.9},
                {"id": 1, "start": 1.0, "end": 1.4, "text": "said", "probability": 0.9},
                {"id": 2, "start": 2.0, "end": 2.0, "text": "you", "probability": 0.9},
                {"id": 3, "start": 2.0, "end": 2.3, "text": "know", "probability": 0.9},
                {"id": 4, "start": 5.0, "end": 5.0, "text": "gone", "probability": 0.9},
                {
                    "id": 5,
                    "start": 7.0,
                    "end": 7.5,
                    "text": "this.",
                    "probability": 0.9,
                },
            ],
        }
        self.update(
            {
                "settings": {"platform": "youtube"},
                "transcript": transcript,
                "segments": [{"start": 0, "end": 4}, {"start": 6, "end": 10}],
            }
        )
        words = self.studio._program_words(self.studio.get(self.project["id"]))
        self.assertEqual(
            [w["text"] for w in words], ["I", "said", "you", "know", "this."]
        )
        self.assertEqual(words[-1]["start"], 5.0)

    def test_chat_tool_get_includes_the_long_form_summary_only_for_youtube(self):
        from cutroom import studio_tools

        with patch.object(studio_tools, "get_studio", return_value=self.studio):
            plain = json.loads(
                studio_tools.project_handler(
                    {"action": "get", "project_id": self.project["id"]}
                )
            )
            self.assertNotIn("longform", plain["result"])
            self.update({"settings": {"platform": "youtube", "chapters": CHAPTERS}})
            result = json.loads(
                studio_tools.project_handler(
                    {"action": "get", "project_id": self.project["id"]}
                )
            )["result"]
        self.assertEqual(result["longform"]["chapter_problems"], [])
        self.assertIn("0:00 Intro", result["longform"]["description"])
        schema = studio_tools.definitions()[0]["parameters"]["properties"]["changes"]
        settings = schema["properties"]["settings"]["properties"]
        for key in ("chapters", "thumbnail", "subtitles_file", "end_screen_s"):
            self.assertIn(key, settings)
        self.assertEqual(settings["end_screen_s"]["minimum"], 5)
        self.assertEqual(settings["end_screen_s"]["maximum"], 20)
        self.assertEqual(len(studio_tools.definitions()), 2)


class LongformRestTests(_Case):
    def test_rest_model_accepts_the_settings_and_exposes_routes(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:  # pragma: no cover - dev extra
            self.skipTest("fastapi is not installed")
        import importlib.util
        import sys

        from fastapi import FastAPI

        path = Path(__file__).resolve().parents[1] / "dashboard" / "plugin_api.py"
        spec = importlib.util.spec_from_file_location(
            "hermes_dashboard_plugin_cutroom_longform_test", path
        )
        plugin_api = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = plugin_api
        spec.loader.exec_module(plugin_api)
        app = FastAPI()
        app.include_router(plugin_api.router)
        app.dependency_overrides[plugin_api.get_studio] = lambda: self.studio
        client = TestClient(app)
        project = self.studio.get(self.project["id"])
        response = client.patch(
            f"/projects/{project['id']}",
            json={
                "changes": {
                    "settings": {
                        "platform": "youtube",
                        "chapters": CHAPTERS,
                        "end_screen_s": 10,
                    },
                    "transcript": words(),
                },
                "revision": project["revision"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        suggested = client.post(f"/projects/{project['id']}/chapters/suggest")
        self.assertEqual(suggested.status_code, 200, suggested.text)
        self.assertGreaterEqual(len(suggested.json()["chapters"]), 3)
        bad = client.patch(
            f"/projects/{project['id']}",
            json={
                "changes": {"settings": {"end_screen_s": 30}},
                "revision": response.json()["revision"],
            },
        )
        self.assertEqual(bad.status_code, 422)
        self.assertIn("thumbnail", plugin_api.ArtifactKind.__args__)
        self.assertIn("chapters", plugin_api.ArtifactKind.__args__)
        self.assertEqual(plugin_api.MEDIA_TYPES[".txt"], "text/plain")


class LongformJobTests(unittest.TestCase):
    """A real YouTube preview with chapters, SRT, thumbnail and end-screen QA."""

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
                "testsrc2=size=640x360:rate=25:duration=40",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=330:sample_rate=48000:duration=40",
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
            timeout=120,
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

    def test_youtube_preview_publishes_chapters_srt_and_thumbnail_and_qa_checks_them(
        self,
    ):
        project = self.studio.create(self.source, name="Talk")
        transcript = words(count=60, step=0.6)
        project = self.studio.update(
            project["id"],
            {
                "settings": {
                    "platform": "youtube",
                    "chapters": [
                        {"start": 0, "title": "Intro"},
                        {"start": 12, "title": "Oceans"},
                        {"start": 24, "title": "Solar"},
                    ],
                    "thumbnail": {"time": 5, "text": "Simple"},
                    "end_screen_s": 10,
                },
                "transcript": transcript,
                "segments": [{"start": 0, "end": 18}, {"start": 20, "end": 40}],
            },
            project["revision"],
        )
        self.assertEqual(
            [c["start"] for c in project["settings"]["chapters"]], [0, 12, 24]
        )
        preview = self.run_job(project["id"], "preview")
        artifacts = preview["result"]["artifacts"]
        for kind in (
            "preview",
            "chapters",
            "captions_srt",
            "captions_vtt",
            "thumbnail",
        ):
            self.assertIn(kind, artifacts)
            self.assertTrue(Path(self.studio.artifact(project["id"], kind)).is_file())
        listed = json.loads(
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_chapters",
                    "-of",
                    "json",
                    str(self.studio.artifact(project["id"], "preview")),
                ],
                capture_output=True,
                check=True,
                timeout=60,
                text=True,
            ).stdout
        )["chapters"]
        self.assertEqual(
            [c["tags"]["title"] for c in listed], ["Intro", "Oceans", "Solar"]
        )
        thumbnail = preview["result"]["longform"]["thumbnail"]
        # 640x360 is enlarged to the 1280x720 minimum, and the result says so.
        self.assertEqual((thumbnail["width"], thumbnail["height"]), (1280, 720))
        self.assertTrue(thumbnail["upscaled"])
        qa = self.run_job(project["id"], "qa")
        checks = {check["name"]: check for check in qa["result"]["checks"]}
        for name in ("chapters", "subtitles_file", "thumbnail", "end_screen"):
            self.assertIn(checks[name]["status"], {"pass", "warning"}, checks[name])
        self.assertEqual(checks["chapters"]["status"], "pass")
        self.assertEqual(checks["subtitles_file"]["status"], "pass")
        self.assertEqual(checks["end_screen"]["status"], "pass")
        self.assertEqual(checks["thumbnail"]["status"], "warning")  # upscaled
        preview_data = self.studio.thumbnail_preview(project["id"])
        self.assertTrue(preview_data["data_url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(preview_data["text"], "Simple")
        self.assertEqual(preview_data["time"], 5)
        auto = self.studio.thumbnail_preview(project["id"], time=1.5, text="")
        self.assertEqual(auto["time"], 1.5)
        with self.assertRaises(ValueError):
            self.studio.thumbnail_preview(project["id"], time=99)


if __name__ == "__main__":
    unittest.main()
