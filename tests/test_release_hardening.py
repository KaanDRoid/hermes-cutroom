"""Fixes from the 0.2.0 security review."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom import integrations
from cutroom.studio import Studio

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    FastAPI = TestClient = None

ROOT = Path(__file__).resolve().parents[1]
PROBE = {"duration": 4.0, "width": 320, "height": 180, "has_audio": False}


class StudioHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        source = root / "unit.mp4"
        source.write_bytes(b"unit fixture, not media")
        with patch("cutroom.studio.probe", return_value=PROBE):
            self.studio = Studio(root / "workspace")
            self.project = self.studio.create(source)

    def tearDown(self):
        self.temporary.cleanup()

    def test_actions_without_a_job_runner_are_refused_before_a_job_exists(self):
        for action in ("download", "publish", "obs", "calendar"):
            options = {"confirmed": True, "password": "pw-123"}
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.studio.submit(self.project["id"], action, options)
        self.assertEqual(self.studio.jobs(), [])
        jobs = Path(self.studio.root) / "jobs"
        written = [p for p in jobs.rglob("*.json")] if jobs.exists() else []
        self.assertEqual(written, [])

    def test_names_and_large_changes_are_bounded_for_every_caller(self):
        project_id, revision = self.project["id"], self.project["revision"]
        with self.assertRaises(ValueError):
            self.studio.update(project_id, {"name": "x" * 201}, revision)
        words = [
            {"id": i, "text": "w" * 20, "start": i * 0.001, "end": i * 0.001 + 0.0005}
            for i in range(60_000)
        ]
        changes = {"transcript": {"words": words}}
        self.assertGreater(len(json.dumps(changes)), 2_000_000)
        with self.assertRaisesRegex(ValueError, "(?i)too large"):
            self.studio.update(project_id, changes, revision)
        self.assertEqual(self.studio.get(project_id)["revision"], revision)


class UploadMessageTests(unittest.TestCase):
    def test_tokens_in_signed_urls_are_not_kept(self):
        text = integrations._upload_problem(
            'Failed to copy: Put "https://acct.blob.core.windows.net/c/f.mp4'
            '?sv=2020&sig=SECRET123": 403 Forbidden'
        )
        self.assertNotIn("SECRET123", text)
        self.assertIn("403 Forbidden", text)


@unittest.skipIf(
    TestClient is None, "FastAPI/httpx are optional dashboard dependencies"
)
class ObsRouteHardeningTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "dashboard" / "plugin_api.py"
        spec = importlib.util.spec_from_file_location("cutroom_api_hardening", path)
        self.api = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.api
        spec.loader.exec_module(self.api)

        class Fake:
            def obs(self, action, password=None, port=4455, confirmed=False):
                return {"action": action, "recording": False}

        app = FastAPI()
        app.include_router(self.api.router)
        app.dependency_overrides[self.api.get_studio] = lambda: Fake()
        self.client = TestClient(app)

    def test_a_rejected_password_is_never_sent_back(self):
        secret = "pw-" + "s" * 600
        for password in (secret, 12345678, ["pw-list"]):
            with self.subTest(password=str(password)[:10]):
                response = self.client.post(
                    "/obs", json={"action": "status", "password": password}
                )
                self.assertEqual(response.status_code, 422)
                self.assertNotIn(str(password)[:12], response.text)
                self.assertNotIn("12345678", response.text)
                self.assertNotIn("pw-list", response.text)


if __name__ == "__main__":
    unittest.main()
