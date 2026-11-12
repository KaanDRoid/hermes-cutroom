"""Studio platform settings, render settings and derived sibling projects."""

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom.media import probe
from cutroom.studio import _CHILD_PROCESSES, Studio


def probe_result(duration=4.0, width=320, height=180):
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "has_audio": True,
    }


class _StudioCase(unittest.TestCase):
    duration = 4.0

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"unit source fixture")
        self.probe = patch(
            "cutroom.studio.probe", return_value=probe_result(self.duration)
        )
        self.probe.start()
        self.addCleanup(self.probe.stop)
        self.studio = Studio(self.root / "workspace")
        self.project = self.studio.create(self.source, name="Talk")

    def settings(self, changes):
        project = self.studio.get(self.project["id"])
        return self.studio.update(
            project["id"], {"settings": changes}, project["revision"]
        )


class PlatformSettingsTests(_StudioCase):
    def test_platform_and_final_resolution_are_validated(self):
        updated = self.settings({"platform": "tiktok", "final_resolution": "2160"})
        self.assertEqual(updated["settings"]["platform"], "tiktok")
        self.assertEqual(updated["settings"]["final_resolution"], "2160")
        self.assertEqual(updated["settings"]["aspect"], "portrait")
        updated = self.settings({"platform": "youtube", "aspect": "portrait"})
        self.assertEqual(updated["settings"]["aspect"], "landscape")
        updated = self.settings({"platform": "custom", "aspect": "square"})
        self.assertEqual(updated["settings"]["aspect"], "square")
        revision = updated["revision"]
        for bad in (
            {"platform": "vine"},
            {"platform": None},
            {"platform": 3},
            {"final_resolution": "720"},
            {"final_resolution": 2160},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.settings(bad)
        self.assertEqual(self.studio.get(self.project["id"])["revision"], revision)

    def test_existing_projects_without_platform_keys_load_as_custom(self):
        legacy = self.studio.get(self.project["id"])
        self.assertNotIn("platform", legacy["settings"])
        digest = self.studio.review(legacy["id"])["digest"]
        self.assertEqual(self.studio.review(legacy["id"])["digest"], digest)
        self.assertEqual(self.studio.platform(legacy), "custom")

    def test_custom_render_settings_are_unchanged(self):
        legacy = self.studio.get(self.project["id"])
        expected_preview = {
            "preset": "preview",
            "aspect": "source",
            "brand": {},
            "title": "",
            "normalize_audio": True,
            "timeout": 900,
        }
        self.assertEqual(
            json.dumps(self.studio._render_settings(legacy, "preview")),
            json.dumps(expected_preview),
        )
        rich = dict(
            legacy,
            settings={
                "aspect": "portrait",
                "title": "A fairly long title that wraps across lines",
                "brand": {"title_color": "#FFEEDD", "aspect": "portrait"},
                "captions": True,
                "normalize_audio": False,
            },
        )
        expected_final = {
            "preset": "final",
            "aspect": "portrait",
            "brand": {"title_color": "#FFEEDD"},
            "title": "A fairly long title that\nwraps across lines",
            "normalize_audio": False,
            "timeout": 3600,
        }
        self.assertEqual(
            json.dumps(self.studio._render_settings(rich, "final")),
            json.dumps(expected_final),
        )
        explicit = dict(
            rich,
            settings={
                **rich["settings"],
                "platform": "custom",
                "final_resolution": "1080",
            },
        )
        self.assertEqual(
            json.dumps(self.studio._render_settings(explicit, "final")),
            json.dumps(expected_final),
        )

    def test_platform_render_settings_use_profile_frame_and_loudness(self):
        project = self.settings({"platform": "youtube_shorts", "title": "Hello"})
        preview = self.studio._render_settings(project, "preview")
        self.assertEqual(preview["platform"], "youtube_shorts")
        self.assertEqual(preview["aspect"], "portrait")
        self.assertEqual(preview["final_resolution"], "1080")
        self.assertEqual(preview["loudness_lufs"], -14)
        self.assertEqual(preview["true_peak_db"], -1)
        project = self.settings({"final_resolution": "2160"})
        self.assertEqual(
            self.studio._render_settings(project, "final")["final_resolution"], "2160"
        )
        from cutroom import postproduction as pp

        settings = pp._settings(self.studio._render_settings(project, "final"))
        info = {"width": 320, "height": 180, "display_aspect_ratio": 16 / 9}
        self.assertEqual(pp._dimensions(info, settings), (2160, 3840))

    def test_quality_settings_keep_the_title_only_for_platform_layout(self):
        custom = self.studio._quality_settings(
            self.settings({"title": "Custom"}), "preview"
        )
        self.assertNotIn("title", custom)
        self.assertEqual(custom["expected_duration"], 4.0)
        platform = self.studio._quality_settings(
            self.settings({"platform": "instagram_reels"}), "preview"
        )
        self.assertEqual(platform["title"], "Custom")
        self.assertEqual(platform["platform"], "instagram_reels")


class LongShortsTests(_StudioCase):
    duration = 190.0

    def test_final_export_above_the_shorts_limit_is_rejected_before_a_job(self):
        project = self.settings({"platform": "youtube_shorts"})
        digest = self.studio.review(project["id"])["digest"]
        self.studio.approve(project["id"], digest)
        with self.assertRaisesRegex(ValueError, "180"):
            self.studio.submit(project["id"], "final")
        self.assertEqual(self.studio.jobs(project["id"]), [])
        trimmed = self.studio.update(
            project["id"], {"segments": [{"start": 0, "end": 179}]}, project["revision"]
        )
        self.assertIsNone(self.studio._platform_problem(trimmed))
        self.assertIsNotNone(self.studio._platform_problem(project))


class DeriveTests(_StudioCase):
    def prepare_parent(self):
        project = self.studio.update(
            self.project["id"],
            {
                "settings": {
                    "title": "Parent title",
                    "captions": True,
                    "brand": {"title_color": "#ABCDEF"},
                    "whisper_model": "C:/models/whisper",
                    "face_model": "C:/models/face.task",
                    "use_segmented": False,
                },
                "brief": "Explain the result",
                "voice": "direct",
                "segments": [{"start": 0.5, "end": 3.5}],
                "gaze_exclusions": [{"start": 1.0, "end": 1.2}],
            },
            1,
        )
        stored = self.studio.get(project["id"])
        stored["transcript"] = {
            "language": "en",
            "status": "ok",
            "text": "hello world",
            "words": [
                {"id": 0, "text": "hello", "start": 0.6, "end": 1.0},
                {"id": 1, "text": "world", "start": 2.0, "end": 2.4},
            ],
            "fillers": [],
        }
        stored["excluded_word_ids"] = [1]
        stored["story"] = {"hooks": [{"text": "hello"}], "selected_hook": 0}
        stored["selected_hook"] = 0
        output = self.root / "workspace" / "fake-preview.mp4"
        output.write_bytes(b"render")
        stored["artifacts"] = {"preview": str(output)}
        stored["artifact_lineage"] = {"preview": {"job_id": "x" * 32}}
        self.studio._write(stored)
        digest = self.studio.review(stored["id"])["digest"]
        return self.studio.approve(stored["id"], digest), digest

    def test_derive_copies_edits_but_not_artifacts_approval_or_jobs(self):
        parent, digest = self.prepare_parent()
        child = self.studio.derive(parent["id"], "instagram_reels")
        self.assertNotEqual(child["id"], parent["id"])
        self.assertEqual(child["revision"], 1)
        self.assertEqual(child["status"], "draft")
        self.assertNotIn("approval", child)
        self.assertEqual(child["artifacts"], {})
        self.assertFalse(child.get("artifact_lineage"))
        self.assertEqual(self.studio.jobs(child["id"]), [])
        self.assertEqual(
            child["derived_from"],
            {
                "project_id": parent["id"],
                "revision": parent["revision"],
                "digest": digest,
            },
        )
        for key in (
            "source",
            "source_sha256",
            "source_info",
            "transcript",
            "segments",
            "base_segments",
            "excluded_word_ids",
            "gaze_exclusions",
            "story",
            "selected_hook",
            "brief",
            "voice",
        ):
            self.assertEqual(child[key], parent[key], key)
        settings = child["settings"]
        self.assertEqual(settings["platform"], "instagram_reels")
        self.assertEqual(settings["aspect"], "portrait")
        for key in ("title", "captions", "brand", "whisper_model", "face_model"):
            self.assertEqual(settings[key], parent["settings"][key], key)
        self.assertIn("Reels", child["name"])
        # The sibling is independent: its digest and approval are its own.
        self.assertNotEqual(self.studio.review(child["id"])["digest"], digest)
        reloaded = self.studio.get(parent["id"])
        self.assertEqual(reloaded["approval"]["digest"], digest)
        self.assertEqual(reloaded["revision"], parent["revision"])
        with self.assertRaises(PermissionError):
            self.studio.submit(child["id"], "final")

    def test_four_platform_versions_from_one_source(self):
        parent, _ = self.prepare_parent()
        names = ["instagram_reels", "youtube_shorts", "tiktok", "youtube"]
        children = [self.studio.derive(parent["id"], name) for name in names]
        self.assertEqual(len({child["id"] for child in children}), 4)
        self.assertEqual([c["settings"]["platform"] for c in children], names)
        self.assertEqual(
            [c["settings"]["aspect"] for c in children],
            ["portrait", "portrait", "portrait", "landscape"],
        )
        self.assertEqual(len(self.studio.list()), 5)

    def test_derive_validates_platform_name_and_source(self):
        named = self.studio.derive(self.project["id"], "tiktok", name="Clip A")
        self.assertEqual(named["name"], "Clip A")
        for platform in ("vine", "", None, 3):
            with self.subTest(platform=platform), self.assertRaises(ValueError):
                self.studio.derive(self.project["id"], platform)
        for name in ("", "x" * 201, 5):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.studio.derive(self.project["id"], "tiktok", name=name)
        count = len(self.studio.list())
        self.source.write_bytes(b"changed source")
        with self.assertRaises(PermissionError):
            self.studio.derive(self.project["id"], "tiktok")
        self.assertEqual(len(self.studio.list()), count)

    def test_derived_segmented_layer_must_be_rebuilt(self):
        stored = self.studio.get(self.project["id"])
        stored["settings"]["use_segmented"] = True
        self.studio._write(stored)
        child = self.studio.derive(stored["id"], "youtube")
        self.assertNotIn("use_segmented", child["settings"])


class PlatformJobsTests(unittest.TestCase):
    """One landscape source, four derived versions, each checked by its own QA."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "landscape-talk.mp4"
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

    def test_four_derived_versions_pass_their_own_platform_quality_checks(self):
        parent = self.studio.create(self.source, name="Talk")
        parent = self.studio.update(
            parent["id"],
            {
                "settings": {"title": "Four platforms", "captions": True},
                "segments": [{"start": 0.0, "end": 2.5}],
                "transcript": {
                    "language": "en",
                    "engine": "synthetic-fixture",
                    "status": "ok",
                    "text": "One source four platforms",
                    "words": [
                        dict(id=0, start=0.2, end=0.6, text="One", probability=0.9),
                        dict(id=1, start=0.7, end=1.1, text="source", probability=0.9),
                        dict(id=2, start=1.3, end=1.7, text="four", probability=0.9),
                        dict(
                            id=3, start=1.8, end=2.3, text="platforms", probability=0.9
                        ),
                    ],
                },
            },
            parent["revision"],
        )
        expected = {
            "instagram_reels": [1080, 1920],
            "youtube_shorts": [1080, 1920],
            "tiktok": [1080, 1920],
            "youtube": [1920, 1080],
        }
        for platform, frame in expected.items():
            with self.subTest(platform=platform):
                child = self.studio.derive(parent["id"], platform)
                self.run_job(child["id"], "preview")
                preview = self.studio.artifact(child["id"], "preview")
                info = probe(preview)
                self.assertEqual([info["width"], info["height"]], frame)
                job = self.run_job(child["id"], "qa")
                checks = {check["name"]: check for check in job["result"]["checks"]}
                for name in (
                    "platform_frame",
                    "platform_duration",
                    "platform_loudness",
                    "safe_zone",
                ):
                    self.assertEqual(checks[name]["status"], "pass", checks[name])
                self.assertIn(checks["platform_fps"]["status"], {"pass", "skip"})
                self.assertEqual(checks["safe_zone"]["detail"]["findings"], [])
                self.assertEqual(
                    set(checks["safe_zone"]["detail"]["boxes"]), {"title", "captions"}
                )
        reloaded = self.studio.get(parent["id"])
        self.assertEqual(reloaded["revision"], parent["revision"])
        self.assertEqual(reloaded["artifacts"], {})


if __name__ == "__main__":
    unittest.main()
