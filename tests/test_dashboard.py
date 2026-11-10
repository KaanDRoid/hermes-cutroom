"""HTTP contract tests; no model or media runtime is required."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    FastAPI = TestClient = None

ROOT = Path(__file__).resolve().parents[1]


class FakeStudio:
    def __init__(self):
        self.projects = {}
        self.calls = []
        self.job_records = {}

    def submit(self, project_id, action, options=None):
        self.get(project_id)
        job = {
            "id": "j1",
            "project_id": project_id,
            "action": action,
            "status": "queued",
            "progress": 0,
            "error": None,
            "result": None,
        }
        self.calls.append((action, options))
        self.job_records["j1"] = job
        return job

    def jobs(self, project_id=None):
        return [
            j
            for j in self.job_records.values()
            if project_id is None or j["project_id"] == project_id
        ]

    def job(self, job_id):
        return self.job_records[job_id]

    def cancel(self, job_id):
        self.job_records[job_id]["status"] = "cancelled"
        return self.job_records[job_id]

    def artifact(self, project_id, kind):
        return Path(self.get(project_id)["artifacts"][kind])

    def review(self, project_id):
        return {"digest": "a" * 64, "project": self.get(project_id)}

    def approve(self, project_id, digest):
        self.calls.append(("approve", digest))
        return self.get(project_id)

    def create(self, source, name=None):
        project = {
            "id": "p1",
            "name": name or "Untitled",
            "source": source,
            "revision": 0,
            "settings": {},
            "artifacts": {},
        }
        self.projects["p1"] = project
        return project

    def list(self):
        return list(self.projects.values())

    def get(self, project_id):
        return self.projects[project_id]

    def update(self, project_id, changes, revision):
        project = self.get(project_id)
        if revision != project["revision"]:
            raise ValueError("Project revision changed; reload before saving")
        project.update(changes)
        project["revision"] += 1
        return project


@unittest.skipIf(
    TestClient is None, "FastAPI/httpx are optional dashboard dependencies"
)
class DashboardTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "dashboard" / "plugin_api.py"
        self.assertTrue(path.exists(), "The dashboard API must exist")
        spec = importlib.util.spec_from_file_location(
            "hermes_dashboard_plugin_cutroom_test", path
        )
        self.api = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.api
        spec.loader.exec_module(self.api)
        self.studio = FakeStudio()
        app = FastAPI()
        app.include_router(self.api.router)
        app.dependency_overrides[self.api.get_studio] = lambda: self.studio
        self.client = TestClient(app)

    def test_real_studio_artifact_names_and_explicit_legacy_aliases(self):
        from unittest.mock import patch

        from cutroom.studio import Studio

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "unit.mp4"
            source.write_bytes(b"unit source, not media")
            with patch(
                "cutroom.studio.probe",
                return_value={
                    "duration": 4.0,
                    "width": 320,
                    "height": 180,
                    "has_audio": False,
                },
            ):
                studio = Studio(root / "workspace")
                project = studio.create(source)
            directory = studio._directory(project["id"])
            contents = {
                "quality": ("quality.json", b'{"fixture":true}'),
                "captions_srt": (
                    "captions.srt",
                    b"1\n00:00:00,000 --> 00:00:01,000\nUnit fixture\n",
                ),
                "captions_vtt": ("captions.vtt", b"WEBVTT\n"),
                "captions_ass": ("captions.ass", b"[Script Info]\n"),
            }
            for kind, (filename, data) in contents.items():
                path = directory / filename
                path.write_bytes(data)
                project["artifacts"][kind] = str(path)
            studio._write(project)
            self.client.app.dependency_overrides[self.api.get_studio] = lambda: studio
            aliases = {
                "qa": "quality",
                "captions": "captions_srt",
                "subtitles": "captions_vtt",
            }
            for requested in [*contents, *aliases]:
                with self.subTest(kind=requested):
                    response = self.client.get(
                        f"/projects/{project['id']}/files/{requested}"
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(
                        response.content, contents[aliases.get(requested, requested)][1]
                    )

    def test_loader_imports_only_its_sibling_package_outside_sys_path(self):
        import shutil

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dashboard").mkdir()
            (root / "cutroom").mkdir()
            (root / "cutroom" / "__init__.py").write_text("", encoding="utf-8")
            (root / "cutroom" / "studio.py").write_text(
                "def get_studio():\n    return {'origin': __file__}\n", encoding="utf-8"
            )
            target = root / "dashboard" / "plugin_api.py"
            shutil.copyfile(ROOT / "dashboard" / "plugin_api.py", target)
            spec = importlib.util.spec_from_file_location(
                "hermes_dashboard_plugin_isolated", target
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            before = sys.path[:]
            spec.loader.exec_module(module)
            self.assertEqual(
                Path(module.get_studio()["origin"]), root / "cutroom" / "studio.py"
            )
            self.assertEqual(
                sys.path, before, "Loading must not mutate the host import path"
            )

    def test_allowlisted_file_routes_support_ranges_and_json_media_chunks(self):
        import base64
        import os

        self.studio.create("input.mp4")
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            path = Path(directory) / "preview.mp4"
            path.write_bytes(b"0123456789")
            self.studio.projects["p1"]["artifacts"]["preview"] = str(path)
            response = self.client.get(
                "/projects/p1/files/preview", headers={"Range": "bytes=2-5"}
            )
            self.assertEqual(response.status_code, 206, response.text)
            self.assertEqual(response.content, b"2345")
            self.assertEqual(response.headers["content-range"], "bytes 2-5/10")
            self.assertEqual(
                self.client.head("/projects/p1/files/preview").status_code, 200
            )
            self.assertEqual(
                self.client.get(
                    "/projects/p1/files/preview", headers={"Range": "bytes=90-100"}
                ).status_code,
                416,
            )
            self.assertEqual(
                self.client.get("/projects/p1/files/secret").status_code, 422
            )
            chunk = self.client.get("/projects/p1/media/preview?offset=2&length=4")
            self.assertEqual(chunk.status_code, 200, chunk.text)
            data = chunk.json()
            self.assertEqual(base64.b64decode(data["data"]), b"2345")
            self.assertEqual(
                (data["offset"], data["next_offset"], data["total"]), (2, 6, 10)
            )
            self.assertEqual(data["mime"], "video/mp4")
            self.assertEqual(
                self.client.get(
                    "/projects/p1/media/preview?length=2000000"
                ).status_code,
                422,
            )
            self.assertEqual(
                self.client.get("/projects/p1/media/preview?offset=20").status_code, 416
            )
            self.assertEqual(
                self.client.get(
                    "/projects/p1/media/preview?version=outdated"
                ).status_code,
                409,
            )
            self.assertEqual(
                self.client.get("/projects/p1/files/preview").headers[
                    "x-content-type-options"
                ],
                "nosniff",
            )

    def test_jobs_delegate_to_submit_with_cancel_and_explicit_remote_consent(self):
        self.studio.create("input.mp4")
        for action in (
            "transcribe",
            "vision",
            "segment",
            "storyboard",
            "preview",
            "final",
            "cover",
            "qa",
        ):
            response = self.client.post(
                "/projects/p1/jobs", json={"action": action, "options": {}}
            )
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(response.json()["action"], action)
        self.assertEqual(self.client.get("/jobs?project_id=p1").json()[0]["id"], "j1")
        self.assertEqual(self.client.get("/jobs/j1").json()["status"], "queued")
        self.assertEqual(
            self.client.post("/jobs/j1/cancel").json()["status"], "cancelled"
        )
        self.assertEqual(self.client.get("/jobs/missing").status_code, 404)
        self.assertEqual(self.client.get("/jobs?project_id=bad%5Cid").status_code, 422)
        for action in ("approve", "eval", "unknown"):
            self.assertEqual(
                self.client.post(
                    "/projects/p1/jobs", json={"action": action}
                ).status_code,
                422,
            )
        for action in ("download", "publish"):
            self.assertEqual(
                self.client.post(
                    "/projects/p1/jobs", json={"action": action}
                ).status_code,
                422,
            )
            response = self.client.post(
                "/projects/p1/jobs",
                json={"action": action, "options": {"confirmed": True}},
            )
            self.assertEqual(response.status_code, 202, response.text)

    def test_human_approval_requires_explicit_confirmation_and_current_exact_digest(
        self,
    ):
        self.studio.create("input.mp4")
        review = self.client.get("/projects/p1/review").json()
        self.assertEqual(review["digest"], "a" * 64)
        for body in (
            {"digest": "a" * 64},
            {"digest": "a" * 64, "confirmed": False},
            {"digest": "a" * 64, "confirmed": 1},
            {"digest": "bad", "confirmed": True},
        ):
            self.assertEqual(
                self.client.post("/projects/p1/approve", json=body).status_code, 422
            )
        response = self.client.post(
            "/projects/p1/approve", json={"digest": "b" * 64, "confirmed": True}
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotIn(("approve", "b" * 64), self.studio.calls)
        response = self.client.post(
            "/projects/p1/approve", json={"digest": review["digest"], "confirmed": True}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(("approve", "a" * 64), self.studio.calls)

    def test_editor_fields_follow_studio_contract(self):
        self.studio.create("input.mp4")
        for changes in (
            {"excluded_word_ids": ["w1"]},
            {"brief": "Explain the result", "voice": "direct"},
            {"selected_hook": 2},
            {"gaze_exclusions": [{"start": 1.0, "end": 2.0}]},
        ):
            response = self.client.patch(
                "/projects/p1",
                json={
                    "revision": self.studio.get("p1")["revision"],
                    "changes": changes,
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            for key, value in changes.items():
                self.assertEqual(response.json()[key], value)
        for changes in (
            {"selected_hook": True},
            {"selected_hook": 3},
            {"excluded_word_ids": "all"},
            {"brief": 10},
            {"gaze_exclusions": "all"},
        ):
            self.assertEqual(
                self.client.patch(
                    "/projects/p1", json={"revision": 4, "changes": changes}
                ).status_code,
                422,
            )

    def test_revision_checked_edits_and_protected_fields(self):
        self.studio.create("input.mp4")
        self.assertEqual(self.client.get("/projects/p1").json()["revision"], 0)
        response = self.client.patch(
            "/projects/p1",
            json={
                "revision": 0,
                "changes": {"settings": {"brand": {"title": "Hello"}}},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["revision"], 1)
        self.assertEqual(
            self.client.patch(
                "/projects/p1", json={"revision": 0, "changes": {"name": "Stale"}}
            ).status_code,
            409,
        )
        for changes in [
            {"approved": True},
            {"artifacts": {"source": "C:/secret"}},
            {"source": "other.mp4"},
            {"revision": 20},
        ]:
            self.assertEqual(
                self.client.patch(
                    "/projects/p1", json={"revision": 1, "changes": changes}
                ).status_code,
                422,
            )
        self.assertEqual(self.client.get("/projects/missing").status_code, 404)
        self.assertEqual(
            self.client.post(
                "/projects", json={"source": "x", "execute": "bad"}
            ).status_code,
            422,
        )
        self.assertEqual(self.client.get("/projects/bad%5Cid").status_code, 422)

    def test_create_and_list_projects(self):
        response = self.client.post(
            "/projects", json={"source": "C:/video/input.mp4", "name": "Demo"}
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["name"], "Demo")
        self.assertEqual(self.client.get("/projects").json(), [response.json()])


if __name__ == "__main__":
    unittest.main()
