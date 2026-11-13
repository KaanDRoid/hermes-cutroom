"""Delivery packages: an approved final, a cover, post text within limits and checksums."""

import importlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cutroom import packages
from cutroom.platforms import profile
from cutroom.project import file_digest
from cutroom.studio import _CHILD_PROCESSES, Studio


def ffmpeg(*arguments):
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", *arguments],
        capture_output=True,
        check=True,
        timeout=120,
    )


def video(path, size, duration=2, rate=25):
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={size}:rate={rate}:duration={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=330:sample_rate=48000:duration={duration}",
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
    )
    return path


def words(count=60, step=0.6):
    result = []
    for index in range(count):
        text = "ocean" if index % 3 else "Waves"
        if index % 10 == 9:
            text += "."
        start = 0.2 + index * step
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


class _Workspace(unittest.TestCase):
    """A project with a published final made by a fake final job (no render)."""

    @classmethod
    def setUpClass(cls):
        cls.media = Path(tempfile.mkdtemp(prefix="cutroom-f7-media-"))
        cls.portrait = video(cls.media / "portrait.mp4", "1080x1920", duration=2)
        cls.landscape = video(cls.media / "landscape.mp4", "1920x1080", duration=40)
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=1:duration=1",
            "-frames:v",
            "1",
            str(cls.media / "thumbnail.jpg"),
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.media, ignore_errors=True)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.studio = Studio(self.root / "workspace")

    def project(self, platform, source=None, changes=None, name="Ocean talk"):
        source = source or (self.landscape if platform == "youtube" else self.portrait)
        local = self.root / ("source-" + uuid.uuid4().hex[:6] + source.suffix)
        shutil.copyfile(source, local)
        project = self.studio.create(local, name=name)
        settings = {"platform": platform}
        settings.update((changes or {}).pop("settings", {}))
        return self.studio.update(
            project["id"], {"settings": settings, **(changes or {})}, 1
        )

    def approve(self, project_id):
        digest = self.studio.review(project_id)["digest"]
        return self.studio.approve(project_id, digest)

    def fake_final(self, project_id, extra=None):
        """Publish a final the way a completed final job does."""
        project = self.studio.get(project_id)
        job_id = uuid.uuid4().hex
        outputs = self.studio._job_path(job_id).parent / "outputs"
        outputs.mkdir(parents=True)
        youtube = self.studio.platform(project) == "youtube"
        final = outputs / "final.mp4"
        shutil.copyfile(self.landscape if youtube else self.portrait, final)
        artifacts = {"final": str(final)}
        if youtube:
            shutil.copyfile(self.media / "thumbnail.jpg", outputs / "thumbnail.jpg")
            (outputs / "captions.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nWaves ocean\n", encoding="utf-8"
            )
            (outputs / "chapters.txt").write_text("0:00 Intro\n", encoding="utf-8")
            artifacts.update(
                thumbnail=str(outputs / "thumbnail.jpg"),
                captions_srt=str(outputs / "captions.srt"),
                chapters=str(outputs / "chapters.txt"),
            )
        artifacts.update(extra or {})
        job = {
            "id": job_id,
            "project_id": project_id,
            "action": "final",
            "revision": project["revision"],
            "status": "completed",
            "result": {"artifacts": artifacts},
        }
        self.studio._write_job(job)
        with self.studio._lock():
            current = self.studio.get(project_id)
            self.studio._publish(
                current, job, artifacts, platform=self.studio.platform(current)
            )
            self.studio._write(current)
        return final

    def ready(self, platform, **kwargs):
        project = self.project(platform, **kwargs)
        self.approve(project["id"])
        final = self.fake_final(project["id"])
        return self.studio.get(project["id"]), final


class LimitTests(unittest.TestCase):
    def test_text_limits_are_sourced_and_dated(self):
        for name in ("instagram_reels", "youtube_shorts", "tiktok", "youtube"):
            text = profile(name)["text"]
            self.assertTrue(text["source"].startswith("https://"), name)
            self.assertEqual(text["checked"], "2026-11-13", name)
        reels = packages.post_limits("instagram_reels")
        self.assertEqual(reels["caption"]["max"], 2200)
        self.assertEqual(reels["caption"]["unit"], "characters")
        self.assertEqual(reels["hashtags"]["max"], 30)
        self.assertEqual(reels["mentions"]["max"], 20)
        tiktok = packages.post_limits("tiktok")
        self.assertEqual(tiktok["caption"], {"max": 2200, "unit": "utf16"})
        self.assertIsNone(tiktok["hashtags"])
        for name in ("youtube", "youtube_shorts"):
            limits = packages.post_limits(name)
            self.assertEqual(limits["title"]["max"], 100)
            self.assertTrue(limits["title"]["required"])
            self.assertEqual(limits["description"], {"max": 5000, "unit": "bytes"})
            self.assertEqual(limits["hashtags"]["max"], 60)
            self.assertIn("support.google.com", limits["hashtags"]["source"])
        with self.assertRaises(ValueError):
            packages.post_limits("custom")

    def test_counting_follows_each_platform_unit(self):
        post = {"title": "", "caption": "😀" * 1100, "hashtags": []}
        self.assertEqual(packages.check_post("tiktok", post)["problems"], [])
        post["caption"] += "😀"
        problems = packages.check_post("tiktok", post)["problems"]
        self.assertEqual(len(problems), 1)
        self.assertIn("2,202", problems[0])
        self.assertIn("2,200", problems[0])
        # Instagram counts characters, so the same text is within its limit.
        self.assertEqual(packages.check_post("instagram_reels", post)["problems"], [])

    def test_problems_name_the_field_and_the_limit_in_plain_words(self):
        caption = "x" * 2201
        problems = packages.check_post(
            "instagram_reels", {"caption": caption, "hashtags": []}
        )["problems"]
        self.assertTrue(any("caption" in p.lower() and "2,200" in p for p in problems))
        tags = [f"#tag{i}" for i in range(31)]
        problems = packages.check_post(
            "instagram_reels", {"caption": "Hi", "hashtags": tags}
        )["problems"]
        self.assertTrue(any("31 hashtags" in p and "30" in p for p in problems))
        mentions = " ".join(f"@user{i}" for i in range(21))
        problems = packages.check_post(
            "instagram_reels", {"caption": mentions, "hashtags": []}
        )["problems"]
        self.assertTrue(any("21" in p and "20" in p for p in problems))
        check = packages.check_post(
            "youtube", {"title": "t" * 101, "caption": "é" * 2501, "hashtags": []}
        )
        text = " ".join(check["problems"])
        self.assertIn("title", text.lower())
        self.assertIn("101", text)
        self.assertIn("5,002 bytes", text)
        self.assertEqual(check["fields"]["description"]["count"], 5002)
        problems = packages.check_post(
            "youtube_shorts", {"title": "A <b> title", "caption": "", "hashtags": []}
        )["problems"]
        self.assertTrue(any("<" in p for p in problems))
        problems = packages.check_post(
            "youtube", {"title": "  ", "caption": "", "hashtags": []}
        )["problems"]
        self.assertTrue(any("needs a title" in p for p in problems))
        many = [f"#t{i}" for i in range(61)]
        problems = packages.check_post(
            "youtube", {"title": "Talk", "caption": "", "hashtags": many}
        )["problems"]
        self.assertTrue(any("61 hashtags" in p for p in problems))

    def test_post_shape_is_validated_and_hashtags_normalised(self):
        post = packages.normalize_post(
            {
                "title": " Talk ",
                "caption": "Line\nTwo",
                "hashtags": ["ocean", "#Sea", "#sea"],
            }
        )
        self.assertEqual(post["hashtags"], ["#ocean", "#Sea"])
        self.assertEqual(post["title"], "Talk")
        for bad in (
            {"other": 1},
            {"hashtags": "ocean"},
            {"hashtags": ["two words"]},
            {"hashtags": ["#a<b"]},
            {"hashtags": ["#🚀"]},
            {"title": "Two\nlines"},
            {"caption": "bell\x07"},
            {"caption": "x" * 20001},
            {"hashtags": ["#a"] * 101},
            "text",
        ):
            with self.assertRaises(ValueError, msg=bad):
                packages.normalize_post(bad)

    def test_youtube_description_holds_caption_chapters_and_hashtags(self):
        text = packages.compose(
            "youtube",
            {"title": "Talk", "caption": "About waves.", "hashtags": ["#ocean"]},
            chapters_text="0:00 Intro\n0:12 Waves\n0:24 End\n",
        )
        self.assertEqual(text["title"], "Talk")
        self.assertEqual(
            text["description"],
            "About waves.\n\n0:00 Intro\n0:12 Waves\n0:24 End\n\n#ocean",
        )
        reels = packages.compose(
            "instagram_reels", {"caption": "Hi", "hashtags": ["#a", "#b"]}
        )
        self.assertEqual(reels, {"caption": "Hi\n\n#a #b"})


class PackageTests(_Workspace):
    def test_refuses_without_an_approved_current_final(self):
        project = self.project("instagram_reels")
        with self.assertRaisesRegex(PermissionError, "Approve"):
            self.studio.package(project["id"])
        self.approve(project["id"])
        with self.assertRaisesRegex(PermissionError, "final"):
            self.studio.package(project["id"])
        self.fake_final(project["id"])
        project = self.studio.update(project["id"], {"brief": "changed"}, 2)
        with self.assertRaisesRegex(PermissionError, "Approve"):
            self.studio.package(project["id"])
        directory = self.studio._directory(project["id"]) / "packages"
        self.assertFalse(directory.exists() and any(directory.iterdir()))

    def test_refuses_custom_projects(self):
        source = self.root / "plain.mp4"
        shutil.copyfile(self.portrait, source)
        project = self.studio.create(source)
        self.approve(project["id"])
        self.fake_final(project["id"])
        with self.assertRaisesRegex(ValueError, "platform"):
            self.studio.package(project["id"])

    def test_reels_package_has_video_cover_text_readme_and_manifest(self):
        project, final = self.ready("instagram_reels")
        before = (file_digest(final), final.stat().st_mtime_ns)
        result = self.studio.package(
            project["id"],
            post={"caption": "Waves all day.", "hashtags": ["ocean", "#sea"]},
        )
        directory = Path(result["directory"])
        packages_root = self.studio._directory(project["id"]) / "packages"
        self.assertEqual(directory.parent, packages_root)
        self.assertRegex(directory.name, r"^instagram_reels-\d{8}-\d{6}$")
        self.assertEqual(
            sorted(p.name for p in directory.iterdir()),
            ["README.txt", "cover.jpg", "manifest.json", "post.txt", "video.mp4"],
        )
        # The original final is neither moved nor changed.
        self.assertEqual((file_digest(final), final.stat().st_mtime_ns), before)
        self.assertEqual(file_digest(directory / "video.mp4"), before[0])
        self.assertTrue(os.path.samefile(directory / "video.mp4", final))
        self.assertEqual(result["video_link"], "hardlink")
        self.assertEqual(packages.jpeg_size(directory / "cover.jpg"), (1080, 1920))
        self.assertLess((directory / "cover.jpg").stat().st_size, 2_000_000)
        readme = (directory / "README.txt").read_text(encoding="utf-8")
        self.assertIn("Nothing has been posted. Upload these files yourself.", readme)
        post = (directory / "post.txt").read_text(encoding="utf-8")
        self.assertIn("Waves all day.\n\n#ocean #sea", post)
        self.assertIn("of 2,200 characters", post)
        manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
        current = self.studio.get(project["id"])
        self.assertEqual(manifest["platform"], "instagram_reels")
        self.assertIs(manifest["posted"], False)
        self.assertEqual(manifest["project"]["id"], project["id"])
        self.assertEqual(manifest["project"]["revision"], current["revision"])
        self.assertEqual(
            manifest["project"]["approval_digest"], current["approval"]["digest"]
        )
        self.assertEqual(
            manifest["cutroom_version"], importlib.import_module("cutroom").__version__
        )
        self.assertRegex(
            manifest["created_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$"
        )
        self.assertEqual(manifest["post"]["hashtags"], ["#ocean", "#sea"])
        self.assertEqual(
            manifest["cover"]["source"], profile("instagram_reels")["cover"]["source"]
        )
        listed = set(manifest["files"])
        self.assertEqual(listed, {"README.txt", "cover.jpg", "post.txt", "video.mp4"})
        for name, entry in manifest["files"].items():
            path = directory / name
            self.assertEqual(entry["size"], path.stat().st_size)
            self.assertEqual(entry["sha256"], file_digest(path))
        # Post text is kept with the project but is not part of the review.
        after = self.studio.get(project["id"])
        self.assertEqual(after["settings"]["post"]["caption"], "Waves all day.")
        self.assertEqual(after["revision"], project["revision"])
        self.assertEqual(after["approval"], project["approval"])
        self.assertEqual(
            self.studio.review(project["id"])["digest"], project["approval"]["digest"]
        )

    def test_vertical_covers_are_nine_by_sixteen_and_tiktok_names_the_frame(self):
        for platform in ("youtube_shorts", "tiktok"):
            project, _ = self.ready(platform)
            post = {"title": "Waves", "caption": "Hi", "hashtags": []}
            result = self.studio.package(project["id"], post=post, cover_time=1.0)
            directory = Path(result["directory"])
            self.assertEqual(packages.jpeg_size(directory / "cover.jpg"), (1080, 1920))
            text = (directory / "post.txt").read_text(encoding="utf-8")
            if platform == "tiktok":
                self.assertIn("0:01", text)
            else:
                self.assertIn("Title (5 of 100 characters)", text)

    def test_cover_time_must_be_inside_the_edit(self):
        project, _ = self.ready("tiktok")
        with self.assertRaisesRegex(ValueError, "Cover"):
            self.studio.package(project["id"], cover_time=99)

    def test_youtube_package_uses_the_final_thumbnail_srt_and_chapters(self):
        chapters = [
            {"start": 0, "title": "Intro"},
            {"start": 12, "title": "Waves"},
            {"start": 24, "title": "End"},
        ]
        project, _ = self.ready(
            "youtube",
            changes={"settings": {"chapters": chapters}, "transcript": words()},
        )
        result = self.studio.package(
            project["id"], post={"title": "Ocean talk", "caption": "About waves."}
        )
        directory = Path(result["directory"])
        self.assertEqual(
            sorted(p.name for p in directory.iterdir()),
            [
                "README.txt",
                "captions.srt",
                "manifest.json",
                "post.txt",
                "thumbnail.jpg",
                "video.mp4",
            ],
        )
        self.assertEqual(
            file_digest(directory / "thumbnail.jpg"),
            file_digest(self.studio.artifact(project["id"], "thumbnail")),
        )
        post = (directory / "post.txt").read_text(encoding="utf-8")
        self.assertIn("About waves.\n\n0:00 Intro\n0:12 Waves\n0:24 End", post)
        self.assertIn("Title (10 of 100 characters)", post)
        manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["cover"]["file"], "thumbnail.jpg")

    def test_text_over_a_hard_limit_is_refused_and_nothing_is_written(self):
        project, _ = self.ready("instagram_reels")
        with self.assertRaisesRegex(ValueError, "2,200"):
            self.studio.package(project["id"], post={"caption": "x" * 2300})
        directory = self.studio._directory(project["id"]) / "packages"
        self.assertFalse(directory.exists() and any(directory.iterdir()))
        # The refused text is not saved either.
        self.assertNotIn("post", self.studio.get(project["id"])["settings"])

    def test_routes_and_existing_tools_build_list_and_verify_the_same_package(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from cutroom import studio_tools
        from dashboard import plugin_api

        project, _ = self.ready("tiktok")
        app = FastAPI()
        app.include_router(plugin_api.router)
        app.dependency_overrides[plugin_api.get_studio] = lambda: self.studio
        with TestClient(app) as client:
            response = client.put(
                f"/projects/{project['id']}/post",
                json={"caption": "From REST", "hashtags": ["sea"]},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["post"]["hashtags"], ["#sea"])
            made = client.post(f"/projects/{project['id']}/packages", json={})
            self.assertEqual(made.status_code, 201, made.text)
            name = made.json()["name"]
            checked = client.post(f"/projects/{project['id']}/packages/{name}/verify")
            self.assertTrue(checked.json()["ok"], checked.text)
            self.assertEqual(
                len(client.get(f"/projects/{project['id']}/packages").json()), 1
            )
        with patch.object(studio_tools, "get_studio", return_value=self.studio):
            listed = json.loads(
                studio_tools.project_handler(
                    {"action": "packages", "project_id": project["id"]}
                )
            )
            self.assertEqual(listed["result"][0]["name"], name)
            checked = json.loads(
                studio_tools.project_handler(
                    {
                        "action": "verify_package",
                        "project_id": project["id"],
                        "package": name,
                    }
                )
            )
            self.assertTrue(checked["ok"], checked)
            made = json.loads(
                studio_tools.project_handler(
                    {
                        "action": "package",
                        "project_id": project["id"],
                        "post": {"caption": "From chat"},
                    }
                )
            )
            self.assertNotEqual(made["result"]["name"], name)

    def test_copy_fallback_and_changed_final_refusal(self):
        project, final = self.ready("tiktok")
        with patch("cutroom.packages.os.link", side_effect=OSError("different volume")):
            result = self.studio.package(project["id"])
        self.assertEqual(result["video_link"], "copy")
        self.assertFalse(
            os.path.samefile(final, Path(result["directory"]) / "video.mp4")
        )
        with final.open("ab") as stream:
            stream.write(b"x")
        with self.assertRaisesRegex(PermissionError, "changed"):
            self.studio.package(project["id"])

    def test_never_overwrites_an_earlier_package(self):
        project, _ = self.ready("tiktok")
        first = Path(self.studio.package(project["id"])["directory"])
        stamp = (first / "manifest.json").read_bytes()
        second = Path(self.studio.package(project["id"])["directory"])
        self.assertNotEqual(first, second)
        self.assertEqual((first / "manifest.json").read_bytes(), stamp)
        listed = self.studio.packages(project["id"])
        self.assertEqual([item["name"] for item in listed], [second.name, first.name])
        self.assertEqual(listed[0]["files"][0]["name"], "README.txt")

    def test_suggested_text_comes_from_the_project_without_saving_it(self):
        project = self.project(
            "instagram_reels",
            source=self.landscape,
            changes={"transcript": words(count=20)},
        )
        status = self.studio.post_text(project["id"])
        self.assertTrue(status["suggested"])
        self.assertEqual(status["post"]["title"], "Ocean talk")
        self.assertTrue(status["post"]["caption"].startswith("Waves ocean ocean"))
        self.assertLessEqual(len(status["post"]["caption"]), 300)
        self.assertEqual(status["post"]["hashtags"], [])
        self.assertEqual(status["problems"], [])
        self.assertEqual(status["limits"]["caption"]["max"], 2200)
        self.assertNotIn("post", self.studio.get(project["id"])["settings"])
        saved = self.studio.set_post(
            project["id"], {"caption": "Mine", "hashtags": ["#a"]}
        )
        self.assertFalse(saved["suggested"])
        self.assertEqual(saved["post"]["caption"], "Mine")
        after = self.studio.get(project["id"])
        self.assertEqual(after["revision"], project["revision"])

    def test_post_settings_leave_review_digest_and_revision_unchanged(self):
        project, _ = self.ready("tiktok")
        digest = self.studio.review(project["id"])["digest"]
        result = self.studio.update(
            project["id"],
            {"settings": {"post": {"caption": "New copy", "hashtags": []}}},
            project["revision"],
        )
        self.assertEqual(result["revision"], project["revision"])
        self.assertEqual(self.studio.review(project["id"])["digest"], digest)
        self.assertEqual(result["approval"], project["approval"])
        self.assertTrue(self.studio.package(project["id"]))

    def test_final_sidecar_tampering_is_refused_after_a_later_publication(self):
        project, _ = self.ready("youtube")
        final_record = self.studio.job(project["artifact_lineage"]["final"]["job_id"])
        thumbnail = Path(final_record["result"]["artifacts"]["thumbnail"])
        # A later publication no longer points its thumbnail at this final.
        original = project["artifact_lineage"]["final"]
        newer = self.fake_final(project["id"])
        project = self.studio.get(project["id"])
        with self.studio._lock():
            project["artifacts"]["final"] = final_record["result"]["artifacts"]["final"]
            project["artifact_lineage"]["final"] = original
            self.studio._write(project)
        thumbnail.write_bytes(b"changed")
        with self.assertRaisesRegex(PermissionError, "changed"):
            self.studio.package(project["id"])
        self.assertTrue(newer.exists())

    def test_paths_stay_inside_the_project_packages_folder(self):
        project, _ = self.ready("tiktok")
        for name in ("..", "../studio.json", "a/b", "tiktok-20260101-000000/../x"):
            with self.assertRaises(ValueError):
                self.studio.package_path(project["id"], name)
        with self.assertRaises(PermissionError):
            self.studio.verify_package(self.root)
        with self.assertRaises(PermissionError):
            self.studio.verify_package(self.studio._directory(project["id"]))


class VerifyTests(_Workspace):
    def test_verify_reports_changed_missing_and_extra_files(self):
        project, final = self.ready("instagram_reels")
        result = self.studio.package(project["id"], post={"caption": "Hi"})
        directory = Path(result["directory"])
        report = self.studio.verify_package(directory)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["checked"], 4)
        # A copy with one changed byte in the video.
        copy = directory.parent / (directory.name + "-copy")
        shutil.copytree(directory, copy)
        video_copy = copy / "video.mp4"
        data = bytearray(video_copy.read_bytes())
        data[len(data) // 2] ^= 0x01
        video_copy.write_bytes(bytes(data))
        (copy / "extra.txt").write_text("x", encoding="utf-8")
        (copy / "README.txt").unlink()
        report = self.studio.verify_package(copy)
        self.assertFalse(report["ok"])
        problems = {item["file"]: item["problem"] for item in report["problems"]}
        self.assertIn("checksum", problems["video.mp4"])
        self.assertIn("missing", problems["README.txt"])
        self.assertIn("not listed", problems["extra.txt"])
        # The original package and the final are untouched.
        self.assertTrue(self.studio.verify_package(directory)["ok"])
        self.assertEqual(file_digest(final), result["files"][-1]["sha256"])

    def test_manifest_entries_are_bounded_and_validated_without_reading_outside(self):
        project, _ = self.ready("tiktok")
        directory = Path(self.studio.package(project["id"])["directory"])
        path = directory / "manifest.json"
        original = json.loads(path.read_text("utf-8"))
        for bad in (
            {"../studio.json": {"size": 1, "sha256": "x"}},
            {"video.mp4": {"size": "not an integer", "sha256": "x"}},
            {},
        ):
            manifest = {**original, "files": bad}
            path.write_text(json.dumps(manifest), encoding="utf-8")
            report = self.studio.verify_package(directory)
            self.assertFalse(report["ok"])
            self.assertTrue(report["problems"])

    def test_unreadable_manifest_is_a_plain_problem(self):
        project, _ = self.ready("tiktok")
        directory = Path(self.studio.package(project["id"])["directory"])
        (directory / "manifest.json").write_text("{", encoding="utf-8")
        report = self.studio.verify_package(directory)
        self.assertFalse(report["ok"])
        self.assertEqual(report["problems"][0]["file"], "manifest.json")


class SurfaceTests(unittest.TestCase):
    def test_agent_tools_offer_packages_but_no_approval_or_posting(self):
        tools = importlib.import_module("cutroom.studio_tools")
        definitions = {item["name"]: item for item in tools.definitions()}
        self.assertEqual(set(definitions), {"cutroom_project", "cutroom_job"})
        project = definitions["cutroom_project"]
        actions = project["parameters"]["properties"]["action"]["enum"]
        for action in ("post_text", "package", "packages", "verify_package"):
            self.assertIn(action, actions)
        self.assertNotIn("approve", actions)
        self.assertIn("post", project["parameters"]["properties"])
        self.assertIn("never", project["description"].lower())
        self.assertIn("posted", project["description"].lower())

    def test_agent_tool_validates_package_arguments_before_studio(self):
        tools = importlib.import_module("cutroom.studio_tools")
        result = json.loads(
            tools.project_handler(
                {"action": "verify_package", "project_id": "a" * 32, "package": "../x"}
            )
        )
        self.assertIn("error", result)
        result = json.loads(
            tools.project_handler(
                {"action": "package", "project_id": "a" * 32, "post": {"bad": 1}}
            )
        )
        self.assertIn("error", result)
        with patch.object(tools, "get_studio") as factory:
            tools.project_handler(
                {"action": "verify_package", "project_id": "a" * 32, "package": "../x"}
            )
            tools.project_handler(
                {"action": "package", "project_id": "a" * 32, "post": {"bad": 1}}
            )
            factory.assert_not_called()

    def test_rest_routes_exist_with_strict_models(self):
        plugin_api = importlib.import_module("dashboard.plugin_api")
        routes = {
            (route.path, method)
            for route in plugin_api.router.routes
            for method in route.methods
        }
        for expected in (
            ("/projects/{project_id}/post", "GET"),
            ("/projects/{project_id}/post", "PUT"),
            ("/projects/{project_id}/packages", "GET"),
            ("/projects/{project_id}/packages", "POST"),
            ("/projects/{project_id}/packages/{name}/verify", "POST"),
        ):
            self.assertIn(expected, routes)
        with self.assertRaises(Exception):
            plugin_api.MakePackage(post={"title": "x"}, extra=1)
        with self.assertRaises(Exception):
            plugin_api.PostText(hashtags=["#a"] * 101)


class RealFinalTests(unittest.TestCase):
    """A real final render for Reels, approved the way the Studio page does, then packaged."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = video(self.root / "talk.mp4", "640x360", duration=3)
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

    def test_real_final_is_packaged_and_verified(self):
        project = self.studio.create(self.source, name="Real")
        project = self.studio.update(
            project["id"], {"settings": {"platform": "instagram_reels"}}, 1
        )
        self.studio.approve(project["id"], self.studio.review(project["id"])["digest"])
        self.run_job(project["id"], "final")
        result = self.studio.package(project["id"], post={"caption": "Real test"})
        directory = Path(result["directory"])
        self.assertTrue(self.studio.verify_package(directory)["ok"])
        self.assertEqual(packages.jpeg_size(directory / "cover.jpg"), (1080, 1920))
        self.assertEqual(
            file_digest(directory / "video.mp4"),
            file_digest(self.studio.artifact(project["id"], "final")),
        )


if __name__ == "__main__":
    unittest.main()
