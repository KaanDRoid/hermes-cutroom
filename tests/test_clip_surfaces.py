"""Clip finder surfaces: agent tool actions, REST routes and the chat skill."""

import importlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    FastAPI = TestClient = None

ROOT = Path(__file__).resolve().parents[1]

CANDIDATE = {
    "id": "clip-12000-48000",
    "rank": 1,
    "start": 12.0,
    "end": 48.0,
    "duration": 36.0,
    "score": 77,
    "hook": "Why do cities flood?",
    "text": "Why do cities flood? " + "Water runs downhill. " * 60,
    "reasons": [{"text": "Opens with a question", "points": 12}],
    "first_word_id": 10,
    "last_word_id": 90,
}


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tools = importlib.import_module("cutroom.studio_tools")
        self.studio = Mock()
        self.factory = patch.object(
            self.tools, "get_studio", return_value=self.studio
        ).start()
        self.addCleanup(patch.stopall)

    def invoke(self, args):
        return json.loads(self.tools.project_handler(args, session_id="test"))

    def test_find_clips_routes_and_shortens_candidate_text(self):
        self.studio.find_clips.return_value = {
            "candidates": [CANDIDATE],
            "settings": {"min_s": 20, "max_s": 60, "count": 8},
            "mode": "punctuation",
        }
        result = self.invoke(
            {
                "action": "find_clips",
                "project_id": "p",
                "platform": "youtube_shorts",
                "max_s": 60,
                "count": 5,
            }
        )
        self.assertTrue(result["ok"], result)
        self.studio.find_clips.assert_called_once_with(
            project_id="p", platform="youtube_shorts", max_s=60, count=5
        )
        item = result["result"]["candidates"][0]
        self.assertEqual(item["id"], CANDIDATE["id"])
        self.assertEqual(item["reasons"], ["Opens with a question (+12)"])
        self.assertLessEqual(len(item["text"]), 400)
        self.assertNotIn("first_word_id", item)
        self.assertIn("note", result["result"])

    def test_create_clip_routes_to_studio(self):
        self.studio.create_clip.return_value = {"id": "c", "transcript": None}
        result = self.invoke(
            {
                "action": "create_clip",
                "project_id": "p",
                "platform": "instagram_reels",
                "candidate_id": "clip-1-2",
            }
        )
        self.assertTrue(result["ok"], result)
        self.studio.create_clip.assert_called_once_with(
            project_id="p", platform="instagram_reels", candidate_id="clip-1-2"
        )
        self.invoke(
            {
                "action": "create_clip",
                "project_id": "p",
                "platform": "tiktok",
                "start": 10.5,
                "end": 40,
            }
        )
        self.studio.create_clip.assert_called_with(
            project_id="p", platform="tiktok", start=10.5, end=40
        )

    def test_bad_arguments_never_reach_studio(self):
        for args in (
            {"action": "find_clips"},
            {"action": "find_clips", "project_id": "p", "count": "5"},
            {"action": "find_clips", "project_id": "p", "count": 50},
            {"action": "find_clips", "project_id": "p", "min_s": True},
            {"action": "find_clips", "project_id": "p", "max_s": 200},
            {"action": "find_clips", "project_id": "p", "platform": "vine"},
            {"action": "find_clips", "project_id": "p", "candidate_id": "x"},
            {"action": "create_clip", "project_id": "p"},
            {"action": "create_clip", "project_id": "p", "platform": "tiktok"},
            {
                "action": "create_clip",
                "project_id": "p",
                "platform": "tiktok",
                "start": 1.0,
            },
            {
                "action": "create_clip",
                "project_id": "p",
                "platform": "tiktok",
                "candidate_id": "x",
                "start": 1.0,
                "end": 30.0,
            },
            {
                "action": "create_clip",
                "project_id": "p",
                "platform": "tiktok",
                "start": "1",
                "end": 30.0,
            },
            {
                "action": "create_clip",
                "project_id": "p",
                "platform": "tiktok",
                "candidate_id": "",
            },
        ):
            with self.subTest(args=args):
                self.factory.reset_mock()
                self.studio.reset_mock()
                result = self.invoke(args)
                self.assertFalse(result["ok"], result)
                self.factory.assert_not_called()

    def test_no_new_default_tool(self):
        names = [item["name"] for item in self.tools.definitions()]
        self.assertEqual(names, ["cutroom_project", "cutroom_job"])
        description = self.tools.definitions()[0]["description"]
        self.assertIn("find_clips", description)
        self.assertIn("sentence", description)


class FakeStudio:
    def __init__(self):
        self.calls = []

    def find_clips(self, project_id, **options):
        if project_id != "p1":
            raise FileNotFoundError(project_id)
        self.calls.append(("find_clips", project_id, options))
        return {"candidates": [CANDIDATE], "settings": options}

    def create_clip(self, project_id, platform, **options):
        if options.get("candidate_id") == "clip-1-9":
            raise ValueError("Find clips again: the transcript changed")
        self.calls.append(("create_clip", project_id, platform, options))
        return {"id": "p2", "revision": 1, "derived_from": {"project_id": project_id}}


@unittest.skipIf(
    TestClient is None, "FastAPI/httpx are optional dashboard dependencies"
)
class RouteTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "dashboard" / "plugin_api.py"
        spec = importlib.util.spec_from_file_location(
            "hermes_dashboard_plugin_cutroom_clips_test", path
        )
        self.api = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.api
        spec.loader.exec_module(self.api)
        self.studio = FakeStudio()
        app = FastAPI()
        app.include_router(self.api.router)
        app.dependency_overrides[self.api.get_studio] = lambda: self.studio
        self.client = TestClient(app)

    def test_find_clips_route(self):
        response = self.client.post("/projects/p1/find-clips", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["candidates"][0]["id"], CANDIDATE["id"])
        response = self.client.post(
            "/projects/p1/find-clips",
            json={"min_s": 25, "max_s": 60, "count": 6, "platform": "tiktok"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.studio.calls[-1],
            (
                "find_clips",
                "p1",
                {"min_s": 25, "max_s": 60, "count": 6, "platform": "tiktok"},
            ),
        )
        for body in (
            {"min_s": 5},
            {"max_s": 91},
            {"count": 0},
            {"count": 21},
            {"platform": "vine"},
            {"count": "5"},
            {"extra": 1},
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.client.post("/projects/p1/find-clips", json=body).status_code,
                    422,
                )
        self.assertEqual(
            self.client.post("/projects/nope/find-clips", json={}).status_code, 404
        )

    def test_create_clip_route(self):
        response = self.client.post(
            "/projects/p1/clips",
            json={"platform": "youtube_shorts", "candidate_id": CANDIDATE["id"]},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["id"], "p2")
        response = self.client.post(
            "/projects/p1/clips",
            json={"platform": "tiktok", "start": 12.5, "end": 40.0, "name": "Mine"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(
            self.studio.calls[-1],
            (
                "create_clip",
                "p1",
                "tiktok",
                {"start": 12.5, "end": 40.0, "name": "Mine"},
            ),
        )
        for body in (
            {"platform": "tiktok"},
            {"platform": "tiktok", "start": 1.0},
            {"platform": "tiktok", "candidate_id": "a", "start": 1.0, "end": 9.0},
            {"platform": "vine", "candidate_id": "a"},
            {"platform": "tiktok", "candidate_id": ""},
            {"platform": "tiktok", "start": -1.0, "end": 9.0},
            {"platform": "tiktok", "candidate_id": "a", "approval": {}},
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.client.post("/projects/p1/clips", json=body).status_code, 422
                )
        response = self.client.post(
            "/projects/p1/clips",
            json={"platform": "tiktok", "candidate_id": "clip-1-9"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("Find clips", response.json()["detail"])


class SkillTests(unittest.TestCase):
    def test_the_skill_offers_clips_for_long_recordings(self):
        text = (ROOT / "skills" / "edit-video" / "SKILL.md").read_text(encoding="utf-8")
        lower = text.lower()
        for phrase in ("find_clips", "create_clip", "sentence boundaries", "reasons"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, lower)


if __name__ == "__main__":
    unittest.main()
