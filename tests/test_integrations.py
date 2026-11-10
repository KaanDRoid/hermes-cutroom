"""Optional integration boundary tests; no connected account is exercised."""

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "cutroom" / "integrations.py"
spec = importlib.util.spec_from_file_location("integrations_under_test", MODULE)
integrations = None
if MODULE.exists():
    integrations = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(integrations)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            dir=Path.home() / "AppData/Local/hermes/cache/scratch"
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_capabilities_are_read_only_and_consent_precedes_every_effect(self):
        self.assertIsNotNone(integrations, "optional integrations are missing")
        with patch.object(
            integrations.subprocess, "run", side_effect=AssertionError("no launch")
        ):
            result = integrations.capability_report()
            for executable in ("ffmpeg", "ffprobe", "yt-dlp", "rclone", "obs64"):
                import sys

                sibling = Path(sys.executable).parent / (
                    executable + (".exe" if integrations.os.name == "nt" else "")
                )
                self.assertEqual(
                    result[executable]["available"],
                    shutil.which(executable) is not None or sibling.is_file(),
                )
                self.assertFalse(result[executable]["live_verified"])
            for name, args in (
                ("download_media", ("invalid", self.root / "download")),
                ("download_image", ("invalid", self.root / "image.png")),
                ("upload_rclone", (self.root / "missing", "invalid")),
                ("obs_record", ("start",)),
                ("obs_record", ("stop",)),
                ("publish_package", (self.root / "package", self.root / "missing")),
            ):
                for consent in (False, None, 1, "yes"):
                    with self.subTest(name=name, consent=consent):
                        with self.assertRaises(PermissionError):
                            getattr(integrations, name)(*args, confirmed=consent)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_executable_discovery_finds_the_current_venv_without_path_activation(self):
        import sys

        binary = self.root / (
            "yt-dlp.exe" if integrations.os.name == "nt" else "yt-dlp"
        )
        binary.write_bytes(b"discovery fixture")
        with (
            patch.object(integrations.shutil, "which", return_value=None),
            patch.object(sys, "executable", str(self.root / "python.exe")),
        ):
            self.assertEqual(
                integrations.capability_report()["yt-dlp"]["path"], str(binary)
            )

    def test_url_boundary_rejects_private_dns_and_untrusted_hosts_before_request(self):
        self.assertTrue(
            hasattr(integrations, "_public_destination"), "public URL guard missing"
        )
        import socket

        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch.object(
            integrations.socket, "getaddrinfo", return_value=public
        ) as dns:
            for url in (
                "http://youtube.com/a",
                "https://evil.invalid/a",
                "https://youtube.com.evil.invalid/a",
                "https://user:pass@youtube.com/a",
                "https://youtube.com:444/a",
                "https://127.0.0.1/a",
                "https://youtube.com/\r\nX:a",
                "https://youtube.com\\@evil.invalid/a",
            ):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    integrations._public_destination(url, integrations.MEDIA_HOSTS)
            self.assertEqual(dns.call_count, 0)
            self.assertEqual(
                integrations._public_destination(
                    "https://www.youtube.com/watch?v=abc", integrations.MEDIA_HOSTS
                )[1],
                "8.8.8.8",
            )
            dns.return_value = public + private
            with self.assertRaises(ValueError):
                integrations._public_destination(
                    "https://youtube.com/a", integrations.MEDIA_HOSTS
                )
        self.assertEqual(
            integrations._source_url(
                "https://youtube.com/watch?v=abc&token=secret#secret"
            ),
            "https://youtube.com/watch?v=abc",
        )

    def test_image_download_checks_every_redirect_and_limits_bytes_and_mime(self):
        import io
        from unittest.mock import MagicMock

        png = b"\x89PNG\r\n\x1a\n" + b"fixture bytes"

        def response(status=200, location=None, mime="image/png", data=png):
            value = MagicMock()
            value.status = status
            value.getheader.side_effect = lambda key, default=None: {
                "Location": location,
                "Content-Type": mime,
                "Content-Length": str(len(data)),
            }.get(key, default)
            value.read.side_effect = io.BytesIO(data).read
            return value

        self.assertTrue(
            hasattr(integrations, "_open_https"), "pinned HTTPS transport missing"
        )
        target = self.root / "logo.png"
        with patch.object(
            integrations, "_open_https", return_value=(MagicMock(), response())
        ):
            result = integrations.download_image(
                "https://images.pexels.com/photos/1/logo.png?token=secret",
                target,
                confirmed=True,
            )
        self.assertEqual(target.read_bytes(), png)
        self.assertNotIn("secret", str(result))
        self.assertEqual(result["bytes"], len(png))
        with patch.object(
            integrations,
            "_open_https",
            return_value=(MagicMock(), response(302, "http://127.0.0.1/private")),
        ) as transport:
            with self.assertRaises(ValueError):
                integrations.download_image(
                    "https://images.pexels.com/a.png",
                    self.root / "bad.png",
                    confirmed=True,
                )
            self.assertEqual(transport.call_count, 1)
        for value in (
            response(mime="text/html"),
            response(mime="image/svg+xml"),
            response(data=b"not an image"),
        ):
            with patch.object(
                integrations, "_open_https", return_value=(MagicMock(), value)
            ):
                with self.assertRaises(ValueError):
                    integrations.download_image(
                        "https://images.pexels.com/a.png",
                        self.root / "bad.png",
                        confirmed=True,
                    )
        with (
            patch.object(integrations, "IMAGE_MAX_BYTES", 10),
            patch.object(
                integrations, "_open_https", return_value=(MagicMock(), response())
            ),
        ):
            with self.assertRaises(ValueError):
                integrations.download_image(
                    "https://images.pexels.com/a.png",
                    self.root / "bad.png",
                    confirmed=True,
                )
        self.assertFalse((self.root / "bad.png").exists())
        self.assertFalse(list(self.root.glob(".cutroom-*")))

    def test_media_proxy_refuses_private_redirect_tunnels_without_upstream_connection(
        self,
    ):
        self.assertTrue(
            hasattr(integrations, "_restricted_proxy"), "media transport guard missing"
        )
        import socket
        from urllib.parse import urlsplit

        original_connect = socket.create_connection
        with integrations._restricted_proxy() as proxy:
            parsed = urlsplit(proxy)
            for request in (
                b"CONNECT 127.0.0.1:443 HTTP/1.1\r\n\r\n",
                b"CONNECT youtube.com.evil.invalid:443 HTTP/1.1\r\n\r\n",
                b"GET http://youtube.com/video HTTP/1.1\r\n\r\n",
            ):
                connection = original_connect((parsed.hostname, parsed.port), timeout=3)
                with (
                    connection,
                    patch.object(
                        integrations.socket,
                        "create_connection",
                        side_effect=AssertionError("upstream must not open"),
                    ),
                ):
                    connection.sendall(request)
                    self.assertIn(b"403", connection.recv(1024))

    def test_media_import_probes_real_media_and_saves_sanitized_attribution(self):
        import json
        import subprocess
        from unittest.mock import MagicMock

        fixture = self.root / "fixture.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=size=32x32:rate=2",
                "-t",
                "1",
                "-c:v",
                "libx264",
                "-n",
                str(fixture),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        original_run = integrations._run
        commands = []
        metadata = {
            "id": "abc",
            "title": "Fixture",
            "uploader": "Local test fixture author",
            "duration": 1,
            "url": "https://videos.pexels.com/fixture.mp4?token=secret",
            "protocol": "https",
        }

        def execute(argv, **kwargs):
            if argv[0] == "yt-dlp-test":
                commands.append(argv)
                if "--no-simulate" in argv:
                    template = argv[argv.index("--output") + 1]
                    shutil.copyfile(fixture, template.replace("%(ext)s", "mp4"))
                return MagicMock(stdout=json.dumps(metadata))
            return original_run(argv, **kwargs)

        original_which = shutil.which
        with (
            patch.object(
                integrations.shutil,
                "which",
                side_effect=lambda name: (
                    "yt-dlp-test" if name == "yt-dlp" else original_which(name)
                ),
            ),
            patch.object(integrations, "_run", side_effect=execute),
            patch.object(
                integrations,
                "_follow_https",
                return_value=(
                    MagicMock(),
                    MagicMock(status=200),
                    "https://www.youtube.com/watch?v=abc",
                ),
            ),
            patch.object(
                integrations.socket,
                "getaddrinfo",
                return_value=[(2, 1, 6, "", ("8.8.8.8", 443))],
            ),
        ):
            result = integrations.download_media(
                "https://www.youtube.com/watch?v=abc&token=secret",
                self.root / "import",
                confirmed=True,
            )
            self.assertTrue(result["media_verified"])
            self.assertTrue(Path(result["output"]).is_file())
            self.assertGreater(result["probe"]["duration"], 0)
            attribution = Path(result["attribution_path"]).read_text("utf-8")
            self.assertIn("Local test fixture author", attribution)
            self.assertNotIn("secret", attribution)
            self.assertEqual(len(commands), 2)
            self.assertIn("--no-overwrites", commands[1])
            self.assertIn("--proxy", commands[1])
            self.assertEqual(
                commands[1][commands[1].index("--use-extractors") + 1],
                "youtube,twitter",
            )
            metadata["_type"] = "playlist"
            with self.assertRaisesRegex(ValueError, "Playlist"):
                integrations.download_media(
                    "https://youtube.com/watch?v=abc",
                    self.root / "playlist",
                    confirmed=True,
                )
            self.assertFalse((self.root / "playlist").exists())
            metadata.pop("_type")
            fixture.write_bytes(b"not actual media")
            with self.assertRaises(RuntimeError):
                integrations.download_media(
                    "https://youtube.com/watch?v=abc",
                    self.root / "invalid",
                    confirmed=True,
                )
            self.assertFalse((self.root / "invalid").exists())
        self.assertFalse(list(self.root.glob(".cutroom-*")))
        with patch.object(
            integrations.subprocess,
            "run",
            side_effect=AssertionError("must not launch"),
        ):
            for url in (
                "https://youtube.com/playlist?list=abc",
                "https://youtube.com/watch?v=abc&list=def",
                "https://evil.invalid/a.mp4",
            ):
                with self.assertRaises(ValueError):
                    integrations.download_media(
                        url, self.root / "refused", confirmed=True
                    )

    def test_rclone_validates_argv_and_verifies_exact_uploaded_object(self):
        import hashlib
        import json
        import subprocess
        from unittest.mock import MagicMock

        local = self.root / "upload.mp4"
        local.write_bytes(b"local upload fixture")
        remote = "approved:deliveries/video.mp4"
        metadata = {
            "Name": "video.mp4",
            "IsDir": False,
            "Size": local.stat().st_size,
            "Hashes": {"MD5": hashlib.md5(local.read_bytes()).hexdigest()},
        }
        with (
            patch.object(integrations.shutil, "which", return_value="rclone.exe"),
            patch.object(integrations.subprocess, "run") as run,
        ):
            run.side_effect = [
                MagicMock(stdout=""),
                MagicMock(stdout=json.dumps(metadata)),
            ]
            result = integrations.upload_rclone(local, remote, confirmed=True)
            self.assertTrue(result["verified"])
            self.assertEqual(result["hash_verified"], ["MD5"])
            upload, verify = run.call_args_list
            self.assertIn("--immutable", upload.args[0])
            self.assertIn("--ignore-existing", upload.args[0])
            self.assertEqual(upload.args[0][-2:], [str(local), remote])
            self.assertEqual(verify.args[0][-1], remote)
            self.assertIn("--stat", verify.args[0])
            self.assertIn("--hash", verify.args[0])
            self.assertIs(upload.kwargs["shell"], False)
            self.assertLessEqual(upload.kwargs["timeout"], 300)
            for bad in (
                "--config=secret",
                ":http,url=https://evil:/x",
                "remote,token=secret:x",
                "remote:",
                "remote:../a",
                "remote:/absolute",
                "remote:a\n--flag",
                "C:/file",
                "remote:a\\b",
                "remote:a?token=secret",
            ):
                with self.subTest(remote=bad), self.assertRaises(ValueError):
                    integrations.upload_rclone(local, bad, confirmed=True)
            metadata["Size"] = 999
            run.side_effect = [
                MagicMock(stdout=""),
                MagicMock(stdout=json.dumps(metadata)),
            ]
            with self.assertRaisesRegex(RuntimeError, "verification"):
                integrations.upload_rclone(local, remote, confirmed=True)
            run.side_effect = subprocess.TimeoutExpired(["rclone", "secret"], 300)
            with self.assertRaisesRegex(RuntimeError, "timed out") as error:
                integrations.upload_rclone(local, remote, confirmed=True)
            self.assertNotIn("secret", str(error.exception))

    def test_rclone_without_comparable_hashes_reports_metadata_only(self):
        import json
        from unittest.mock import MagicMock

        local = self.root / "upload.mp4"
        local.write_bytes(b"local upload fixture")
        remote = "approved:deliveries/video.mp4"
        for hashes in (None, {}, {"DropboxHash": "unsupported"}, {"MD5": ""}):
            metadata = {
                "Name": "video.mp4",
                "IsDir": False,
                "Size": local.stat().st_size,
            }
            if hashes is not None:
                metadata["Hashes"] = hashes
            with (
                self.subTest(hashes=hashes),
                patch.object(integrations.shutil, "which", return_value="rclone.exe"),
                patch.object(
                    integrations.subprocess,
                    "run",
                    side_effect=[
                        MagicMock(stdout=""),
                        MagicMock(stdout=json.dumps(metadata)),
                    ],
                ) as run,
                patch.object(
                    integrations,
                    "_hash_file",
                    side_effect=AssertionError("No comparable remote hash"),
                ) as hash_file,
            ):
                result = integrations.upload_rclone(local, remote, confirmed=True)
                self.assertFalse(result["verified"])
                self.assertEqual(result["verification"], "metadata_only")
                self.assertEqual(result["hash_verified"], [])
                self.assertEqual(result["remote"], remote)
                self.assertEqual(result["size"], metadata["Size"])
                self.assertIn("--ignore-existing", run.call_args_list[0].args[0])
                self.assertEqual(run.call_count, 2)
                hash_file.assert_not_called()

    def test_rclone_rejects_matching_metadata_with_mismatched_supported_hash(self):
        import hashlib
        import json
        from unittest.mock import MagicMock

        local = self.root / "upload.mp4"
        local.write_bytes(b"local upload fixture")
        remote = "approved:deliveries/video.mp4"
        for name, algorithm in (
            ("MD5", "md5"),
            ("SHA-1", "sha1"),
            ("SHA-256", "sha256"),
        ):
            metadata = {
                "Name": "video.mp4",
                "IsDir": False,
                "Size": local.stat().st_size,
                "Hashes": {
                    name: hashlib.new(algorithm, b"different content").hexdigest()
                },
            }
            with (
                self.subTest(hash=name),
                patch.object(integrations.shutil, "which", return_value="rclone.exe"),
                patch.object(
                    integrations.subprocess,
                    "run",
                    side_effect=[
                        MagicMock(stdout=""),
                        MagicMock(stdout=json.dumps(metadata)),
                    ],
                ),
                self.assertRaisesRegex(RuntimeError, "verification failed"),
            ):
                integrations.upload_rclone(local, remote, confirmed=True)

    def test_obs_validates_before_import_and_calls_real_client_contract(self):
        import sys
        import types
        from unittest.mock import MagicMock

        for kwargs in (
            {"host": "192.168.1.2"},
            {"host": "evil.invalid"},
            {"port": True},
            {"port": 0},
            {"action": "toggle"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                integrations.obs_record(**({"action": "status"} | kwargs))
        recording = self.root / "recording.mkv"
        recording.write_bytes(b"OBS response path fixture")
        client = MagicMock()
        client.get_record_status.return_value = types.SimpleNamespace(
            output_active=True, output_paused=False, output_timecode="00:00:01.000"
        )
        client.stop_record.return_value = types.SimpleNamespace(
            output_path=str(recording)
        )
        sdk = types.SimpleNamespace(ReqClient=MagicMock(return_value=client))
        with patch.dict(sys.modules, {"obsws_python": sdk}):
            status = integrations.obs_record("status", password="secret")
            self.assertTrue(status["recording"])
            integrations.obs_record("start", password="secret", confirmed=True)
            self.assertEqual(client.start_record.call_count, 1)
            client.get_record_status.return_value.output_active = False
            stopped = integrations.obs_record("stop", password="secret", confirmed=True)
            self.assertEqual(stopped["output"], str(recording))
            self.assertTrue(stopped["file_verified"])
            password = sdk.ReqClient.call_args.kwargs["password"]
            self.assertNotIn("secret", str(password))
            self.assertEqual(password + "salt", "secretsalt")
            self.assertEqual(sdk.ReqClient.call_args.kwargs["timeout"], 5)
            client.stop_record.return_value.output_path = str(self.root / "missing.mkv")
            with self.assertRaises(FileNotFoundError):
                integrations.obs_record("stop", confirmed=True)
            client.get_record_status.return_value.output_active = False
            with self.assertRaises(RuntimeError):
                integrations.obs_record("start", confirmed=True)
            self.assertGreaterEqual(client.disconnect.call_count, 4)
            sdk.ReqClient.side_effect = RuntimeError("secret connection failure")
            with self.assertRaisesRegex(
                RuntimeError, "OBS connection or request failed"
            ):
                integrations.obs_record("status", password="secret")

    def test_local_package_copies_real_files_and_hashes_without_sharing(self):
        video = self.root / "video.mp4"
        video.write_bytes(b"explicit local package fixture")
        cover = self.root / "cover.png"
        cover.write_bytes(b"local image fixture")
        directory = self.root / "package"
        result = integrations.publish_package(
            directory, video, cover, "Caption\nline two", confirmed=True
        )
        import hashlib
        import json

        manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
        self.assertFalse(result["external_write"])
        self.assertEqual((directory / "video.mp4").read_bytes(), video.read_bytes())
        self.assertEqual(
            (directory / "caption.txt").read_text("utf-8"), "Caption\nline two"
        )
        self.assertEqual(
            manifest["files"]["video.mp4"]["sha256"],
            hashlib.sha256(video.read_bytes()).hexdigest(),
        )
        with self.assertRaises(FileExistsError):
            integrations.publish_package(directory, video, confirmed=True)
        for value in ("https://example.com/x", "//server/share/x", "pipe:0"):
            with self.assertRaises(ValueError):
                integrations.publish_package(self.root / "bad", value, confirmed=True)
        self.assertFalse((self.root / "bad").exists())

    def test_calendar_writes_real_utc_ics_without_content_line_injection(self):
        self.assertTrue(
            hasattr(integrations, "create_calendar_event"), "calendar adapter missing"
        )
        output = self.root / "reminder.ics"
        result = integrations.create_calendar_event(
            output,
            "Başlık,;\\\nBEGIN:VEVENT",
            "2026-12-01T13:00:00+03:00",
            "2026-12-01T14:00:00+03:00",
            description="ş" * 100 + "\r\nEND:VCALENDAR",
            url="https://www.youtube.com/watch?v=abc",
        )
        content = output.read_bytes()
        self.assertEqual(result["path"], str(output))
        self.assertFalse(result["external_write"])
        self.assertIn(b"DTSTART:20261201T100000Z\r\n", content)
        self.assertEqual(content.count(b"\r\nBEGIN:VEVENT\r\n"), 1)
        self.assertEqual(content.count(b"\r\nEND:VCALENDAR\r\n"), 1)
        self.assertIn("SUMMARY:Başlık\\,\\;\\\\\\nBEGIN:VEVENT".encode(), content)
        self.assertTrue(all(len(line) <= 75 for line in content.split(b"\r\n")))
        with self.assertRaises(FileExistsError):
            integrations.create_calendar_event(
                output, "x", "2026-12-01T13:00:00Z", "2026-12-01T14:00:00Z"
            )
        for start, end, url in (
            ("2026-12-01T13:00:00", "2026-12-01T14:00:00", ""),
            ("2026-12-01T14:00:00Z", "2026-12-01T13:00:00Z", ""),
            (
                "2026-12-01T13:00:00Z",
                "2026-12-01T14:00:00Z",
                "https://youtube.com/\r\nBEGIN:VEVENT",
            ),
            ("2026-12-01T13:00:00Z", "2026-12-01T14:00:00Z", "file:///secret"),
        ):
            with (
                self.subTest(start=start, end=end, url=url),
                self.assertRaises(ValueError),
            ):
                integrations.create_calendar_event(
                    self.root / "invalid.ics", "x", start, end, url=url
                )
        self.assertFalse((self.root / "invalid.ics").exists())


if __name__ == "__main__":
    unittest.main()
