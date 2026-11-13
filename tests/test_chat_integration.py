"""Chat surface: bundled skill, default tool set, media-bearing job results."""

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cutroom.hermes_plugin import register

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOOLS = {"cutroom_inspect", "cutroom_project", "cutroom_job"}
LEGACY_TOOLS = {"cutroom_draft", "cutroom_review", "cutroom_render"}


class Context:
    def __init__(self, config=None):
        self.tools = {}
        self.skills = {}
        self.config = config or {}

    def register_tool(self, **tool):
        self.tools[tool["name"]] = tool

    def register_skill(self, name, path, description=""):
        self.skills[name] = {"path": Path(path), "description": description}

    def get_config(self, key, default=None):
        return self.config.get(key, default)


class OldContext:
    """A host without skills or plugin settings."""

    def __init__(self):
        self.tools = {}

    def register_tool(self, **tool):
        self.tools[tool["name"]] = tool


def _manifest():
    text = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    tools, section = [], None
    for line in text.splitlines():
        if line and not line.startswith(" "):
            section = line.split(":", 1)[0]
            continue
        if section == "provides_tools" and line.strip().startswith("- "):
            tools.append(line.strip()[2:].strip())
    return text, tools


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("CUTROOM_LEGACY_TOOLS", None)

    def test_default_surface_hides_legacy_plan_tools(self):
        ctx = Context()
        register(ctx)
        self.assertEqual(set(ctx.tools), DEFAULT_TOOLS)

    def test_environment_opt_in_restores_legacy_tools(self):
        for value in ("1", "true", "yes", "on"):
            with self.subTest(value=value):
                os.environ["CUTROOM_LEGACY_TOOLS"] = value
                ctx = Context()
                register(ctx)
                self.assertEqual(set(ctx.tools), DEFAULT_TOOLS | LEGACY_TOOLS)
        for value in ("0", "", "false", "no"):
            with self.subTest(value=value):
                os.environ["CUTROOM_LEGACY_TOOLS"] = value
                ctx = Context()
                register(ctx)
                self.assertEqual(set(ctx.tools), DEFAULT_TOOLS)

    def test_plugin_setting_opt_in_restores_legacy_tools(self):
        ctx = Context({"legacy_tools": True})
        register(ctx)
        self.assertEqual(set(ctx.tools), DEFAULT_TOOLS | LEGACY_TOOLS)
        ctx = Context({"legacy_tools": False})
        register(ctx)
        self.assertEqual(set(ctx.tools), DEFAULT_TOOLS)

    def test_broken_config_reader_falls_back_to_default(self):
        ctx = Context()
        ctx.get_config = Mock(side_effect=RuntimeError("no settings"))
        register(ctx)
        self.assertEqual(set(ctx.tools), DEFAULT_TOOLS)

    def test_bundled_skill_is_registered(self):
        ctx = Context()
        register(ctx)
        self.assertEqual(set(ctx.skills), {"edit-video"})
        skill = ctx.skills["edit-video"]
        self.assertTrue(skill["path"].is_file())
        self.assertEqual(skill["path"].name, "SKILL.md")
        self.assertEqual(
            skill["path"].resolve(),
            (ROOT / "skills" / "edit-video" / "SKILL.md").resolve(),
        )
        self.assertTrue(skill["description"])

    def test_older_hosts_without_skills_or_settings_still_load(self):
        ctx = OldContext()
        register(ctx)
        self.assertEqual(set(ctx.tools), DEFAULT_TOOLS)

    def test_manifest_matches_default_registration(self):
        text, tools = _manifest()
        self.assertEqual(set(tools), DEFAULT_TOOLS)
        self.assertEqual(len(tools), len(set(tools)))
        self.assertIn("config_schema:", text)
        self.assertIn("legacy_tools:", text)


class SkillContentTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "skills" / "edit-video" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.lower = self.text.lower()

    def test_frontmatter(self):
        self.assertTrue(self.text.startswith("---\n"))
        head = self.text.split("---", 2)[1]
        self.assertIn("name: edit-video", head)
        self.assertIn("description:", head)

    def test_workflow_steps_are_in_order(self):
        markers = [
            "cutroom_project create",
            "transcribe",
            "excluded_word_ids",
            "caption_style",
            "framing",
            "preview",
            "qa",
            "MEDIA:",
            "Cutroom Studio",
            "final",
        ]
        positions = [self.text.find(marker) for marker in markers]
        self.assertNotIn(-1, positions, dict(zip(markers, positions)))
        self.assertEqual(positions, sorted(positions))

    def test_key_rules(self):
        for phrase in (
            "cutroom_job get",
            "instagram_reels",
            "youtube_shorts",
            "tiktok",
            "highlight",
            "blur_fill",
            "face_track",
            "vision",
            "derive",
            "3 min",
            "never claim",
            "ready with notes",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.lower)
        self.assertIn("upload", self.lower)
        self.assertIn("publish", self.lower)


class MediaCase(unittest.TestCase):
    def setUp(self):
        self.tools = importlib.import_module("cutroom.studio_tools")
        self.studio = Mock()
        patch.object(self.tools, "get_studio", return_value=self.studio).start()
        self.addCleanup(patch.stopall)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        outputs = Path(temporary.name).resolve() / "jobs" / "r1" / "outputs"
        outputs.mkdir(parents=True)
        self.preview = outputs / "preview.mp4"
        self.preview.write_bytes(b"\0" * 16)
        self.cover = outputs / "cover.png"
        self.cover.write_bytes(b"\0" * 16)
        self.project = {
            "id": "p",
            "name": "Talk",
            "revision": 4,
            "settings": {"platform": "instagram_reels"},
            "artifacts": {"preview": str(self.preview)},
            "artifact_lineage": {
                "preview": {"job_id": "r1", "platform": "instagram_reels"}
            },
        }
        self.studio.get.return_value = self.project
        self.studio.jobs.return_value = []
        self.studio.artifact.return_value = self.preview
        self.studio.review.return_value = {"digest": "d"}

    def render_job(self, **changes):
        job = {
            "id": "r1",
            "project_id": "p",
            "action": "preview",
            "status": "completed",
            "progress": 1.0,
            "revision": 4,
            "result": {
                "output": str(self.preview),
                "duration": 41.96,
                "width": 1080,
                "height": 1920,
                "platform": "instagram_reels",
                "artifacts": {"preview": str(self.preview)},
            },
        }
        job.update(changes)
        return job

    def qa_job(self, statuses, job_id="q1", upstream="r1", completed_at=10.0):
        return {
            "id": job_id,
            "project_id": "p",
            "action": "qa",
            "status": "completed",
            "completed_at": completed_at,
            "upstream": "preview",
            "upstream_identity": {"kind": "preview", "job_id": upstream},
            "result": {
                "checks": [
                    {"name": f"check_{index}", "status": status, "detail": {}}
                    for index, status in enumerate(statuses)
                ],
                "passed": all(status in ("pass", "skip") for status in statuses),
            },
        }

    def get_job(self, job):
        self.studio.job.return_value = job
        response = json.loads(
            self.tools.job_handler({"action": "get", "job_id": job["id"]})
        )
        self.assertTrue(response["ok"], response)
        return response["result"]


class MediaResultTests(MediaCase):
    def test_completed_preview_carries_media(self):
        result = self.get_job(self.render_job())
        media = result["media"]
        self.assertEqual(
            media,
            {
                "path": str(self.preview),
                "kind": "preview",
                "project_id": "p",
                "project_name": "Talk",
                "platform": "instagram_reels",
                "duration": 41.96,
                "width": 1080,
                "height": 1920,
                "current": True,
                "qa": None,
                "approved": False,
            },
        )
        self.assertTrue(Path(media["path"]).is_absolute())
        self.assertIn("MEDIA:" + str(self.preview), result["display_hint"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["id"], "r1")

    def test_qa_counts_and_status(self):
        cases = [
            (["pass", "pass", "skip"], "pass", 2, 0, 0),
            (["pass", "warning", "pass"], "warning", 2, 0, 1),
            (["pass", "warning", "fail"], "fail", 1, 1, 1),
        ]
        for statuses, status, passed, failed, warnings in cases:
            with self.subTest(statuses=statuses):
                self.studio.jobs.return_value = [self.qa_job(statuses)]
                qa = self.get_job(self.render_job())["media"]["qa"]
                self.assertEqual(qa["status"], status)
                self.assertEqual(qa["passed"], passed)
                self.assertEqual(qa["failed"], failed)
                self.assertEqual(qa["warnings"], warnings)
                self.assertEqual(qa["total"], len(statuses))
                self.assertEqual(qa["job_id"], "q1")

    def test_warning_only_qa_is_not_reported_as_failed(self):
        """A reframed 1080p landscape source always warns about upscaling."""
        job = self.qa_job(["pass", "warning", "pass"])
        job["result"]["checks"][1]["name"] = "platform_upscale"
        self.assertFalse(job["result"]["passed"])
        self.studio.jobs.return_value = [job]
        qa = self.get_job(self.render_job())["media"]["qa"]
        self.assertEqual(qa["status"], "warning")
        self.assertEqual(qa["failed"], 0)
        self.assertEqual(qa["warning_checks"], ["platform_upscale"])
        self.assertEqual(qa["failed_checks"], [])

    def test_latest_matching_qa_wins(self):
        self.studio.jobs.return_value = [
            self.qa_job(["fail"], job_id="old", completed_at=5.0),
            self.qa_job(["pass"], job_id="new", completed_at=9.0),
            self.qa_job(["warning"], job_id="other", upstream="r0", completed_at=20.0),
            dict(self.qa_job(["fail"], job_id="running"), status="running"),
        ]
        qa = self.get_job(self.render_job())["media"]["qa"]
        self.assertEqual(qa["job_id"], "new")
        self.assertEqual(qa["status"], "pass")
        self.studio.jobs.assert_called_with(project_id="p")

    def test_approval_reflects_current_revision(self):
        self.project["approval"] = {"digest": "d", "revision": 4}
        self.assertTrue(self.get_job(self.render_job())["media"]["approved"])
        self.project["approval"] = {"digest": "d", "revision": 3}
        self.assertFalse(self.get_job(self.render_job())["media"]["approved"])

    def test_stale_render_is_marked_not_current(self):
        self.project["artifact_lineage"]["preview"]["job_id"] = "newer"
        media = self.get_job(self.render_job())["media"]
        self.assertFalse(media["current"])
        self.assertEqual(media["path"], str(self.preview))

    def test_final_and_cover_carry_media(self):
        final = self.render_job(action="final")
        final["result"]["artifacts"] = {"final": str(self.preview)}
        self.assertEqual(self.get_job(final)["media"]["kind"], "final")
        cover = {
            "id": "c1",
            "project_id": "p",
            "action": "cover",
            "status": "completed",
            "upstream": "preview",
            "upstream_identity": {"kind": "preview", "job_id": "r1"},
            "result": {
                "output": str(self.cover),
                "artifacts": {"cover": str(self.cover)},
            },
        }
        self.studio.jobs.return_value = [self.qa_job(["pass"])]
        media = self.get_job(cover)["media"]
        self.assertEqual(media["kind"], "cover")
        self.assertEqual(media["path"], str(self.cover))
        self.assertEqual(media["platform"], "instagram_reels")
        self.assertIsNone(media["duration"])
        self.assertEqual(media["qa"]["job_id"], "q1")

    def test_no_media_for_unfinished_or_other_jobs(self):
        cases = [
            self.render_job(status="running", result=None),
            self.render_job(status="failed", error="boom", result=None),
            self.render_job(action="transcribe"),
            self.render_job(action="qa"),
        ]
        relative = self.render_job()
        relative["result"]["artifacts"] = {"preview": "outputs/preview.mp4"}
        cases.append(relative)
        missing = self.render_job()
        missing["result"]["artifacts"] = {"preview": str(self.preview) + ".gone"}
        cases.append(missing)
        for job in cases:
            with self.subTest(job=job["action"] + "/" + job["status"]):
                result = self.get_job(job)
                self.assertNotIn("media", result)
                self.assertNotIn("display_hint", result)

    def test_media_lookup_errors_never_break_the_job_result(self):
        self.studio.get.side_effect = FileNotFoundError("project gone")
        result = self.get_job(self.render_job())
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("media", result)

    def test_nonfinite_numbers_are_dropped(self):
        job = self.render_job()
        job["result"]["duration"] = float("nan")
        self.studio.job.return_value = job
        response = json.loads(self.tools.job_handler({"action": "get", "job_id": "r1"}))
        self.assertTrue(response["ok"], response)
        self.assertIsNone(response["result"]["media"]["duration"])

    def test_submit_and_list_enrich_completed_renders(self):
        self.studio.submit.return_value = self.render_job()
        response = json.loads(
            self.tools.job_handler(
                {"action": "submit", "project_id": "p", "operation": "preview"}
            )
        )
        self.assertEqual(response["result"]["media"]["path"], str(self.preview))
        queued = self.render_job(status="queued", result=None)
        self.studio.submit.return_value = queued
        response = json.loads(
            self.tools.job_handler(
                {"action": "submit", "project_id": "p", "operation": "preview"}
            )
        )
        self.assertNotIn("media", response["result"])

    def test_project_get_summarises_current_media(self):
        self.studio.job.return_value = self.render_job()
        self.studio.jobs.return_value = [self.qa_job(["pass", "warning"])]
        response = json.loads(
            self.tools.project_handler({"action": "get", "project_id": "p"})
        )
        self.assertTrue(response["ok"], response)
        media = response["result"]["media"]
        self.assertEqual(set(media), {"preview"})
        self.assertEqual(media["preview"]["path"], str(self.preview))
        self.assertEqual(media["preview"]["qa"]["status"], "warning")
        self.studio.job.assert_called_with(job_id="r1")

    def test_project_get_without_renders_has_no_media(self):
        self.project["artifacts"] = {}
        self.project["artifact_lineage"] = {}
        response = json.loads(
            self.tools.project_handler({"action": "get", "project_id": "p"})
        )
        self.assertNotIn("media", response["result"])


class DescriptionTests(unittest.TestCase):
    def test_descriptions_state_order_and_human_approval(self):
        tools = importlib.import_module("cutroom.studio_tools")
        definitions = {item["name"]: item for item in tools.definitions()}
        job = definitions["cutroom_job"]["description"]
        project = definitions["cutroom_project"]["description"]
        for description in (job, project):
            self.assertIn("Cutroom Studio", description)
            self.assertIn("only a person", description.lower())
        order = ["create", "transcribe", "update", "preview", "qa", "final"]
        workflow = tools.WORKFLOW
        positions = [workflow.find(step) for step in order]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))
        self.assertIn(workflow, job)
        self.assertIn(workflow, project)
        self.assertIn("MEDIA:", job)
        self.assertIn("cutroom:edit-video", job)


if __name__ == "__main__":
    unittest.main()
