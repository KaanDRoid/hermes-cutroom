"""Explicit offline-safe setup and read-only doctor contracts."""

import hashlib
import importlib
import io
import os
import tempfile
import unittest
import urllib.request
import urllib.response
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

PAYLOAD = b"model-bytes" * 10
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
REVISION = "d90ca5fe260221311c53c58e660288d3deb8d356"
VERIFIED = {
    "face_landmarker.task": (
        "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
    ),
    "selfie_segmenter.tflite": (
        "191ac9529ae506ee0beefa6b2c945a172dab9d07d1e802a290a4e4038226658b"
    ),
    "whisper-tiny/config.json": (
        "a73a28cdfe1c43ccc7202fa333d1f89c202477271407ae9a7f19afa52039cac8"
    ),
    "whisper-tiny/model.bin": (
        "dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1"
    ),
    "whisper-tiny/tokenizer.json": (
        "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"
    ),
    "whisper-tiny/vocabulary.txt": (
        "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"
    ),
}


class Response(io.BytesIO):
    def __init__(self, data, url="https://example.test/model", length=None):
        super().__init__(data)
        self.url = url
        self.status = 200
        self.headers = {"Content-Length": str(len(data) if length is None else length)}

    def geturl(self):
        return self.url


def fake_assets(path="sub/model.bin", sha=PAYLOAD_SHA):
    return {
        "face": [{"path": path, "url": "https://example.test/model", "sha256": sha}]
    }


class SetupPlanTests(unittest.TestCase):
    def setUp(self):
        self.setup = importlib.import_module("cutroom.setup")

    def test_plan_has_pinned_assets_and_no_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "not-created"
            with patch("urllib.request.urlopen", side_effect=AssertionError("net")):
                result = self.setup.setup_models(target, models="face,person,speech")
            self.assertEqual(result["status"], "planned")
            self.assertFalse(target.exists())
            self.assertEqual(set(result["models"]), {"face", "person", "speech"})
            for model in result["models"].values():
                for asset in model["files"]:
                    self.assertTrue(asset["url"].startswith("https://"))
                    self.assertEqual(len(asset["sha256"]), 64)
                    self.assertNotIn("/latest/", asset["url"])
                    self.assertNotIn("/main/", asset["url"])

    def test_assets_match_verified_local_models_and_studio_names(self):
        assets = {
            asset["path"]: asset
            for files in self.setup.MODEL_ASSETS.values()
            for asset in files
        }
        self.assertEqual(
            {path: asset["sha256"] for path, asset in assets.items()}, VERIFIED
        )
        for path, asset in assets.items():
            if path.startswith("whisper-tiny/"):
                self.assertIn(
                    f"/Systran/faster-whisper-tiny/resolve/{REVISION}/", asset["url"]
                )
                self.assertTrue(asset["url"].endswith("/" + path.split("/")[1]))

    def test_invalid_input_rejected_without_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "no"
            for models in ("unknown", "face,unknown", "", None, ["face"], "face,face"):
                with (
                    self.subTest(models=models),
                    self.assertRaises((ValueError, TypeError)),
                ):
                    self.setup.setup_models(target, models=models)
            for consent in (1, "yes", None, [], {}):
                with self.subTest(consent=consent), self.assertRaises(TypeError):
                    self.setup.setup_models(target, confirm_downloads=consent)
            for destination in (
                "//server/share",
                r"\\server\share",
                "https://example.com/models",
                "smb://server/models",
                "",
                None,
            ):
                with (
                    self.subTest(destination=destination),
                    self.assertRaises((ValueError, TypeError)),
                ):
                    self.setup.setup_models(destination, confirm_downloads=True)
            self.assertFalse(target.exists())

    def test_resolved_network_destination_is_rejected(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(Path, "resolve", return_value=Path(r"\\server\share\models")),
            patch("urllib.request.urlopen") as urlopen,
        ):
            with self.assertRaises(ValueError):
                self.setup.setup_models(Path(tmp) / "x", confirm_downloads=True)
            urlopen.assert_not_called()


class SetupDownloadTests(unittest.TestCase):
    def setUp(self):
        self.setup = importlib.import_module("cutroom.setup")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "models"

    def run_setup(self, response, assets=None):
        with (
            patch.object(self.setup, "MODEL_ASSETS", assets or fake_assets()),
            patch(
                "urllib.request.OpenerDirector.open", side_effect=response
            ) as urlopen,
        ):
            result = self.setup.setup_models(
                self.root, models="face", confirm_downloads=True
            )
        return result, urlopen

    def files(self):
        if not self.root.exists():
            return []
        return sorted(
            str(path.relative_to(self.root)).replace(os.sep, "/")
            for path in self.root.rglob("*")
            if path.is_file()
        )

    def test_confirmed_download_verifies_and_installs(self):
        result, urlopen = self.run_setup(lambda *a, **k: Response(PAYLOAD))
        self.assertEqual(result["status"], "complete")
        entry = result["models"]["face"]["files"][0]
        self.assertEqual(entry["status"], "downloaded")
        self.assertEqual((self.root / "sub/model.bin").read_bytes(), PAYLOAD)
        self.assertEqual(self.files(), ["sub/model.bin"])
        self.assertEqual(urlopen.call_args.args[0], "https://example.test/model")
        self.assertGreater(urlopen.call_args.kwargs["timeout"], 0)

    def test_existing_matching_file_is_present_without_network(self):
        (self.root / "sub").mkdir(parents=True)
        (self.root / "sub/model.bin").write_bytes(PAYLOAD)
        result, urlopen = self.run_setup(AssertionError("net"))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["models"]["face"]["files"][0]["status"], "present")
        urlopen.assert_not_called()

    def test_existing_mismatching_file_is_error_and_untouched(self):
        (self.root / "sub").mkdir(parents=True)
        (self.root / "sub/model.bin").write_bytes(b"user data")
        result, urlopen = self.run_setup(AssertionError("net"))
        self.assertEqual(result["status"], "failed")
        entry = result["models"]["face"]["files"][0]
        self.assertEqual(entry["status"], "error")
        self.assertIn("sha256", entry["error"])
        self.assertEqual((self.root / "sub/model.bin").read_bytes(), b"user data")
        urlopen.assert_not_called()

    def test_failures_leave_no_partial_files(self):
        def broken(*args, **kwargs):
            response = Response(PAYLOAD)
            response.read = Mock(side_effect=[PAYLOAD[:5], OSError("reset")])
            return response

        cases = {
            "hash": lambda *a, **k: Response(b"tampered"),
            "network": OSError("offline"),
            "partial": broken,
            "redirect": lambda *a, **k: Response(PAYLOAD, url="http://evil.test/m"),
            "declared-size": lambda *a, **k: Response(PAYLOAD, length=300_000_000),
        }
        for name, response in cases.items():
            with self.subTest(case=name):
                result, _ = self.run_setup(response)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(
                    result["models"]["face"]["files"][0]["status"], "error"
                )
                self.assertEqual(self.files(), [])

    def test_https_downgrade_is_rejected_before_following_redirect(self):
        visited = []

        def redirect(handler, request):
            visited.append(request.full_url)
            headers = Message()
            headers["Location"] = (
                "https://example.test/hop"
                if len(visited) == 1
                else "http://example.test/insecure"
            )
            response = urllib.response.addinfourl(
                io.BytesIO(b""), headers, request.full_url, code=302
            )
            response.msg = "Found"
            return response

        with (
            patch.object(self.setup, "MODEL_ASSETS", fake_assets()),
            patch("urllib.request._opener", None),
            patch.object(urllib.request.HTTPSHandler, "https_open", redirect),
            patch.object(
                urllib.request.HTTPHandler,
                "http_open",
                side_effect=AssertionError("HTTP request must never happen"),
            ) as http,
        ):
            result = self.setup.setup_models(
                self.root, models="face", confirm_downloads=True
            )
        http.assert_not_called()
        self.assertEqual(
            visited, ["https://example.test/model", "https://example.test/hop"]
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("HTTPS", result["models"]["face"]["files"][0]["error"])
        self.assertEqual(self.files(), [])

    def test_streamed_size_cap_is_enforced(self):
        with patch.object(self.setup, "MAX_DOWNLOAD_BYTES", 10):
            result, _ = self.run_setup(lambda *a, **k: Response(PAYLOAD, length=0))
        self.assertEqual(result["status"], "failed")
        self.assertIn("200 MB", self.setup.SIZE_ERROR)
        self.assertEqual(self.files(), [])

    def test_non_https_asset_url_is_refused(self):
        assets = {
            "face": [{"path": "a.bin", "url": "http://x.test/a", "sha256": PAYLOAD_SHA}]
        }
        result, urlopen = self.run_setup(lambda *a, **k: Response(PAYLOAD), assets)
        self.assertEqual(result["status"], "failed")
        urlopen.assert_not_called()


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.setup = importlib.import_module("cutroom.setup")

    def test_doctor_reports_tools_runtime_packages_and_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sub").mkdir()
            (root / "sub/model.bin").write_bytes(PAYLOAD)
            assets = dict(
                fake_assets(),
                person=[
                    {
                        "path": "missing.tflite",
                        "url": "https://x.test/p",
                        "sha256": PAYLOAD_SHA,
                    }
                ],
                speech=[
                    {
                        "path": "sub/model.bin",
                        "url": "https://x.test/s",
                        "sha256": "0" * 64,
                    }
                ],
            )
            completed = Mock(
                returncode=0, stdout="ffmpeg version 7.1 Copyright\nmore\n"
            )
            with (
                patch.object(self.setup, "MODEL_ASSETS", assets),
                patch("shutil.which", side_effect=lambda name: f"C:/bin/{name}.exe"),
                patch("subprocess.run", return_value=completed) as run,
                patch(
                    "importlib.util.find_spec",
                    side_effect=lambda name: object() if name == "numpy" else None,
                ),
                patch(
                    "cutroom.runtime.runtime_python", return_value="C:/venv/python.exe"
                ),
                patch("urllib.request.urlopen", side_effect=AssertionError("net")),
            ):
                before = sorted(root.rglob("*"))
                report = self.setup.doctor(models_dir=root)
                self.assertEqual(sorted(root.rglob("*")), before)
        self.assertEqual(report["ffmpeg"]["path"], "C:/bin/ffmpeg.exe")
        self.assertEqual(report["ffmpeg"]["version"], "ffmpeg version 7.1 Copyright")
        self.assertEqual(report["ffprobe"]["path"], "C:/bin/ffprobe.exe")
        self.assertEqual(run.call_args.args[0][1:], ["-version"])
        self.assertEqual(report["runtime_python"]["path"], "C:/venv/python.exe")
        self.assertTrue(report["packages"]["numpy"])
        self.assertFalse(report["packages"]["mediapipe"])
        self.assertFalse(report["packages"]["faster_whisper"])
        face = report["models"]["face"]["files"][0]
        self.assertEqual(
            (face["exists"], face["size"], face["sha256_match"]),
            (True, len(PAYLOAD), True),
        )
        person = report["models"]["person"]["files"][0]
        self.assertEqual((person["exists"], person["sha256_match"]), (False, None))
        self.assertFalse(report["models"]["speech"]["files"][0]["sha256_match"])
        self.assertFalse(report["models"]["speech"]["ready"])
        self.assertTrue(report["models"]["face"]["ready"])

    def test_doctor_handles_missing_ffmpeg_and_runtime(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("shutil.which", return_value=None),
            patch("subprocess.run", side_effect=AssertionError("spawn")),
            patch(
                "cutroom.runtime.runtime_python", side_effect=FileNotFoundError("gone")
            ),
        ):
            report = self.setup.doctor(models_dir=Path(tmp) / "absent")
            self.assertFalse((Path(tmp) / "absent").exists())
        self.assertEqual(report["ffmpeg"], {"path": None, "version": None})
        self.assertIsNone(report["runtime_python"]["path"])
        self.assertIn("gone", report["runtime_python"]["error"])

    def test_doctor_rejects_network_models_dir(self):
        for value in ("//server/share", "https://example.com/m"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.setup.doctor(models_dir=value)


if __name__ == "__main__":
    unittest.main()
