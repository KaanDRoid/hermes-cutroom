"""Poster frames: one cached JPEG source frame per project for Desktop cards."""

import base64
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    FastAPI = TestClient = None

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def jpeg_size(data):
    """Width and height from the first JPEG start-of-frame marker."""
    index = 2
    while index < len(data):
        marker, length = data[index + 1], int.from_bytes(data[index + 2 : index + 4])
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[index + 5 : index + 7])
            width = int.from_bytes(data[index + 7 : index + 9])
            return width, height
        index += 2 + length
    raise AssertionError("No JPEG frame header")


@unittest.skipIf(
    TestClient is None, "FastAPI/httpx are optional dashboard dependencies"
)
class PosterTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "dashboard" / "plugin_api.py"
        spec = importlib.util.spec_from_file_location(
            "hermes_dashboard_plugin_cutroom_poster_test", path
        )
        self.api = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.api
        spec.loader.exec_module(self.api)
        self.module = self.api._module("studio")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        app = FastAPI()
        app.include_router(self.api.router)
        self.studio = None
        app.dependency_overrides[self.api.get_studio] = lambda: self.studio
        self.client = TestClient(app)

    def project(self, width=640, height=360, duration=2.0):
        source = self.root / "talk.mp4"
        if FFMPEG:
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"testsrc=size={width}x{height}:rate=10:duration={duration}",
                    "-pix_fmt",
                    "yuv420p",
                    "-y",
                    str(source),
                ],
                check=True,
                timeout=60,
            )
        else:
            source.write_bytes(b"not media")
        info = {
            "duration": duration,
            "width": width,
            "height": height,
            "has_audio": False,
        }
        with patch.object(self.module, "probe", return_value=info):
            self.studio = self.module.Studio(self.root / "workspace")
            return self.studio.create(source)

    @unittest.skipUnless(FFMPEG, "ffmpeg is needed to make a poster frame")
    def test_route_returns_a_bounded_jpeg_and_caches_it_by_source_hash(self):
        project = self.project(1280, 720)
        response = self.client.get(f"/projects/{project['id']}/poster")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["mime"], "image/jpeg")
        prefix = "data:image/jpeg;base64,"
        self.assertTrue(body["data_url"].startswith(prefix))
        data = base64.b64decode(body["data_url"][len(prefix) :])
        self.assertEqual(data[:2], b"\xff\xd8")
        self.assertEqual(jpeg_size(data), (480, 270), "Scaled to at most 480 px")
        self.assertAlmostEqual(body["time"], 0.6, places=3, msg="30 % of duration")
        cached = list((self.studio._directory(project["id"]) / "posters").glob("*.jpg"))
        self.assertEqual(len(cached), 1)
        self.assertTrue(cached[0].name.startswith(project["source_sha256"][:16]))
        # A second request reads the cache and never starts ffmpeg again.
        with patch.object(
            self.module, "poster_frame", side_effect=AssertionError("ffmpeg ran")
        ):
            again = self.client.get(f"/projects/{project['id']}/poster")
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["data_url"], body["data_url"])
        # Another position is another cache entry.
        later = self.client.get(f"/projects/{project['id']}/poster?at=0.9")
        self.assertEqual(later.status_code, 200, later.text)
        self.assertAlmostEqual(later.json()["time"], 1.8, places=3)

    @unittest.skipUnless(FFMPEG, "ffmpeg is needed to make a poster frame")
    def test_tall_sources_keep_their_shape(self):
        project = self.project(360, 640)
        body = self.client.get(f"/projects/{project['id']}/poster").json()
        data = base64.b64decode(body["data_url"].split(",", 1)[1])
        self.assertEqual(jpeg_size(data), (270, 480))

    def test_position_outside_the_video_is_refused(self):
        project = self.project()
        for value in ("-0.1", "1.5", "nan"):
            with self.subTest(at=value):
                response = self.client.get(
                    f"/projects/{project['id']}/poster?at={value}"
                )
                self.assertEqual(response.status_code, 422, response.text)
        with self.assertRaises(ValueError):
            self.studio.poster(project["id"], at=2)
        with self.assertRaises(ValueError):
            self.studio.poster(project["id"], at=True)

    def test_missing_source_is_a_clean_error(self):
        project = self.project()
        Path(project["source"]).unlink()
        with patch.object(
            self.module, "poster_frame", side_effect=AssertionError("ffmpeg ran")
        ):
            response = self.client.get(f"/projects/{project['id']}/poster")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("missing", response.json()["detail"].lower())
        self.assertIn("talk.mp4", response.json()["detail"])

    def test_unknown_project_is_not_found(self):
        self.project()
        response = self.client.get("/projects/" + "0" * 32 + "/poster")
        self.assertEqual(response.status_code, 404, response.text)

    def test_ffmpeg_failure_and_timeout_are_reported_without_a_cache_entry(self):
        project = self.project()
        directory = self.studio._directory(project["id"]) / "posters"
        failures = [
            subprocess.TimeoutExpired(["ffmpeg"], 30),
            subprocess.CalledProcessError(1, ["ffmpeg"], stderr="bad frame"),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch.object(self.module, "poster_frame", side_effect=failure):
                    response = self.client.get(f"/projects/{project['id']}/poster")
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn("poster", response.json()["detail"].lower())
                self.assertEqual(list(directory.glob("*")), [])


class PosterCommandTests(unittest.TestCase):
    def test_ffmpeg_runs_without_a_shell_with_a_finite_timeout_and_480_px_bound(self):
        from cutroom import media

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "in.mp4"
            source.write_bytes(b"x")
            with patch.object(media.subprocess, "run") as run:
                media.poster_frame(source, 1.25, Path(directory) / "out.jpg")
        arguments, options = run.call_args
        command = arguments[0]
        self.assertEqual(command[0], "ffmpeg")
        self.assertFalse(options.get("shell"))
        self.assertTrue(0 < options["timeout"] <= 120)
        self.assertIn("-frames:v", command)
        self.assertIn("1.250", command)
        self.assertTrue(any("480" in part for part in command))
        with self.assertRaises(ValueError):
            media.poster_frame(source, -1, Path(directory) / "out.jpg")


if __name__ == "__main__":
    unittest.main()
