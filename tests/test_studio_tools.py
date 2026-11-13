import importlib
import json
import math
import unittest
from unittest.mock import Mock, patch


class _ToolCase(unittest.TestCase):
    def setUp(self):
        try:
            self.tools = importlib.import_module("cutroom.studio_tools")
        except ModuleNotFoundError:
            self.fail("Studio tool adapter is not implemented")
        self.studio = Mock()
        self.factory = patch.object(
            self.tools, "get_studio", return_value=self.studio
        ).start()
        self.addCleanup(patch.stopall)

    def assert_rejected_without_effect(self, handler, cases):
        for args in cases:
            with self.subTest(args=args):
                self.factory.reset_mock()
                self.studio.reset_mock()
                result = json.loads(handler(args, session_id="test"))
                self.assertFalse(result["ok"])
                self.assertIn("error", result)
                self.assertIn("type", result)
                self.factory.assert_not_called()
                self.assertEqual(self.studio.mock_calls, [])


class ProjectToolTests(_ToolCase):
    def invoke(self, args):
        return json.loads(self.tools.project_handler(args, session_id="test"))

    def test_project_routes_to_facade(self):
        cases = [
            (
                {"action": "create", "source": "C:/clips/video.mp4", "name": "Demo"},
                "create",
                {"source": "C:/clips/video.mp4", "name": "Demo"},
            ),
            (
                {"action": "create", "source": "C:/clips/video.mp4"},
                "create",
                {"source": "C:/clips/video.mp4"},
            ),
            ({"action": "review", "project_id": "p"}, "review", {"project_id": "p"}),
            (
                {
                    "action": "update",
                    "project_id": "p",
                    "changes": {"brief": "Edit"},
                    "revision": 1,
                },
                "update",
                {"project_id": "p", "changes": {"brief": "Edit"}, "revision": 1},
            ),
            (
                {"action": "derive", "project_id": "p", "platform": "tiktok"},
                "derive",
                {"project_id": "p", "platform": "tiktok"},
            ),
            (
                {
                    "action": "derive",
                    "project_id": "p",
                    "platform": "youtube",
                    "name": "Long form",
                },
                "derive",
                {"project_id": "p", "platform": "youtube", "name": "Long form"},
            ),
            (
                {
                    "action": "derive",
                    "project_id": "p",
                    "platform": "tiktok",
                    "final_resolution": "2160",
                },
                "derive",
                {"project_id": "p", "platform": "tiktok", "final_resolution": "2160"},
            ),
        ]
        for args, method, expected in cases:
            with self.subTest(args=args):
                self.studio.reset_mock()
                getattr(self.studio, method).return_value = {"routed": method}
                self.assertEqual(
                    self.invoke(args), {"ok": True, "result": {"routed": method}}
                )
                getattr(self.studio, method).assert_called_once_with(**expected)
                self.assertEqual(len(self.studio.mock_calls), 1)

    def test_every_allowed_change_key_is_forwarded(self):
        keys = (
            "settings",
            "brief",
            "voice",
            "excluded_word_ids",
            "gaze_exclusions",
            "selected_hook",
            "segments",
            "transcript",
            "name",
        )
        self.assertEqual(self.tools.PROJECT_CHANGES, frozenset(keys))
        for key in keys:
            with self.subTest(key=key):
                self.studio.reset_mock()
                self.studio.update.return_value = {"revision": 2}
                args = {
                    "action": "update",
                    "project_id": "p",
                    "changes": {key: {} if key == "settings" else "value"},
                    "revision": 3,
                }
                self.assertTrue(self.invoke(args)["ok"])
                self.studio.update.assert_called_once_with(
                    project_id="p",
                    changes={key: {} if key == "settings" else "value"},
                    revision=3,
                )

    def test_list_is_compact(self):
        self.studio.list.return_value = [
            {
                "id": "a" * 32,
                "name": "Demo",
                "revision": 4,
                "status": "draft",
                "source": "C:/clips/video.mp4",
                "artifacts": {"preview": "C:/x/preview.mp4", "cover": "C:/x/c.png"},
                "transcript": {"words": [{"id": "w1"}] * 500},
                "source_info": {"duration": 3.0},
            }
        ]
        result = self.invoke({"action": "list"})
        self.assertEqual(
            result,
            {
                "ok": True,
                "result": [
                    {
                        "id": "a" * 32,
                        "name": "Demo",
                        "revision": 4,
                        "status": "draft",
                        "source": "C:/clips/video.mp4",
                        "artifacts": ["cover", "preview"],
                    }
                ],
            },
        )
        self.studio.list.assert_called_once_with()

    def test_get_summarizes_transcript_words(self):
        words = [{"id": f"w{index}", "word": "x"} for index in range(120)]
        self.studio.get.return_value = {
            "id": "p",
            "revision": 2,
            "transcript": {"language": "en", "words": words},
        }
        result = self.invoke({"action": "get", "project_id": "p"})["result"]
        self.studio.get.assert_called_once_with(project_id="p")
        self.assertEqual(result["revision"], 2)
        transcript = result["transcript"]
        self.assertEqual(transcript["language"], "en")
        self.assertEqual(transcript["word_count"], 120)
        self.assertEqual(transcript["words"], words[:50])
        self.assertTrue(transcript["words_truncated"])

    def test_get_without_transcript_is_unchanged(self):
        self.studio.get.return_value = {"id": "p", "transcript": None}
        result = self.invoke({"action": "get", "project_id": "p"})
        self.assertEqual(result["result"], {"id": "p", "transcript": None})

    def test_review_summarizes_embedded_project(self):
        words = [{"id": f"w{index}"} for index in range(60)]
        self.studio.review.return_value = {
            "digest": "d" * 64,
            "notice": "Approve in Studio",
            "project": {"id": "p", "transcript": {"words": words}},
        }
        result = self.invoke({"action": "review", "project_id": "p"})["result"]
        self.assertEqual(result["digest"], "d" * 64)
        self.assertEqual(result["project"]["transcript"]["word_count"], 60)
        self.assertEqual(len(result["project"]["transcript"]["words"]), 50)

    def test_invalid_project_arguments_have_no_effect(self):
        cases = [
            None,
            [],
            "list",
            {},
            {"action": "invent"},
            {"action": "approve"},
            {"action": "confirm"},
            {"action": []},
            {"action": "LIST"},
            {"action": "list", "extra": 1},
            {"action": "list", "source": "x"},
            {"action": "get"},
            {"action": "get", "project_id": ""},
            {"action": "get", "project_id": 1},
            {"action": "get", "project_id": "p", "revision": 1},
            {"action": "create"},
            {"action": "create", "source": 1},
            {"action": "create", "source": ""},
            {"action": "create", "source": "x", "name": None},
            {"action": "create", "source": "x", "project_id": "p"},
            {"action": "review", "project_id": "p", "digest": "d"},
            {"action": "update", "project_id": "p", "changes": {"brief": "x"}},
            {"action": "update", "changes": {"brief": "x"}, "revision": 1},
            {"action": "derive", "project_id": "p"},
            {"action": "derive", "platform": "tiktok"},
            {"action": "derive", "project_id": "p", "platform": "vine"},
            {"action": "derive", "project_id": "p", "platform": 3},
            {"action": "derive", "project_id": "p", "platform": "tiktok", "name": ""},
            {
                "action": "derive",
                "project_id": "p",
                "platform": "tiktok",
                "final_resolution": "720",
            },
            {
                "action": "derive",
                "project_id": "p",
                "platform": "tiktok",
                "final_resolution": 2160,
            },
            {
                "action": "derive",
                "project_id": "p",
                "platform": "tiktok",
                "approval": {"digest": "d"},
            },
            {
                "action": "derive",
                "project_id": "p",
                "platform": "tiktok",
                "revision": 1,
            },
        ]
        for revision in (True, 0, -1, 1.2, "1", None):
            cases.append(
                {
                    "action": "update",
                    "project_id": "p",
                    "changes": {"brief": "x"},
                    "revision": revision,
                }
            )
        for changes in ({}, [], None, {"brief": math.nan}, {"brief": math.inf}):
            cases.append(
                {
                    "action": "update",
                    "project_id": "p",
                    "changes": changes,
                    "revision": 1,
                }
            )
        self.assert_rejected_without_effect(self.tools.project_handler, cases)

    def test_protected_changes_rejected_before_factory(self):
        fields = (
            "approval",
            "approved",
            "confirmed",
            "digest",
            "artifacts",
            "artifact_lineage",
            "source",
            "source_sha256",
            "source_info",
            "revision",
            "id",
            "status",
            "base_segments",
            "invented",
        )
        cases = [
            {
                "action": "update",
                "project_id": "p",
                "changes": {field: "forged"},
                "revision": 1,
            }
            for field in fields
        ]
        cases.append(
            {
                "action": "update",
                "project_id": "p",
                "changes": {"brief": "ok", "approval": {"digest": "d"}},
                "revision": 1,
            }
        )
        self.assert_rejected_without_effect(self.tools.project_handler, cases)

    def test_facade_errors_and_nonfinite_results_are_json_failures(self):
        self.studio.get.side_effect = PermissionError("Not allowed")
        result = self.invoke({"action": "get", "project_id": "p"})
        self.assertEqual(
            result, {"ok": False, "error": "Not allowed", "type": "PermissionError"}
        )
        self.studio.get.side_effect = None
        self.studio.get.return_value = {"value": math.nan}
        self.assertFalse(self.invoke({"action": "get", "project_id": "p"})["ok"])


class JobToolTests(_ToolCase):
    def invoke(self, args):
        return json.loads(self.tools.job_handler(args, session_id="test"))

    def test_job_actions_route_to_facade(self):
        cases = [
            (
                {"action": "submit", "project_id": "p", "operation": "transcribe"},
                "submit",
                {"project_id": "p", "action": "transcribe", "options": None},
            ),
            (
                {
                    "action": "submit",
                    "project_id": "p",
                    "operation": "final",
                    "options": {"quality": "high"},
                },
                "submit",
                {"project_id": "p", "action": "final", "options": {"quality": "high"}},
            ),
            ({"action": "list"}, "jobs", {"project_id": None}),
            ({"action": "list", "project_id": "p"}, "jobs", {"project_id": "p"}),
            ({"action": "get", "job_id": "j"}, "job", {"job_id": "j"}),
            ({"action": "cancel", "job_id": "j"}, "cancel", {"job_id": "j"}),
        ]
        for args, method, expected in cases:
            with self.subTest(args=args):
                self.studio.reset_mock()
                getattr(self.studio, method).return_value = {"id": "j"}
                self.assertEqual(self.invoke(args), {"ok": True, "result": {"id": "j"}})
                getattr(self.studio, method).assert_called_once_with(**expected)
                self.assertEqual(len(self.studio.mock_calls), 1)

    def test_every_allowed_operation_submits(self):
        operations = (
            "inspect",
            "transcribe",
            "silence",
            "vision",
            "segment",
            "storyboard",
            "preview",
            "final",
            "cover",
            "qa",
        )
        self.assertEqual(self.tools.JOB_OPERATIONS, frozenset(operations))
        for operation in operations:
            with self.subTest(operation=operation):
                self.studio.reset_mock()
                self.studio.submit.return_value = {"id": "j"}
                args = {"action": "submit", "project_id": "p", "operation": operation}
                self.assertTrue(self.invoke(args)["ok"])

    def test_invalid_job_arguments_have_no_effect(self):
        cases = [
            None,
            {},
            {"action": "approve"},
            {"action": "confirm", "job_id": "j"},
            {"action": "run"},
            {"action": "submit", "project_id": "p"},
            {"action": "submit", "operation": "final"},
            {"action": "submit", "project_id": "p", "operation": "FINAL"},
            {
                "action": "submit",
                "project_id": "p",
                "operation": "final",
                "job_id": "j",
            },
            {"action": "submit", "project_id": "p", "operation": "qa", "options": []},
            {
                "action": "submit",
                "project_id": "p",
                "operation": "qa",
                "options": {"x": math.nan},
            },
            {"action": "get"},
            {"action": "get", "job_id": ""},
            {"action": "get", "job_id": "j", "project_id": "p"},
            {"action": "cancel"},
            {"action": "cancel", "job_id": 7},
            {"action": "list", "job_id": "j"},
            {"action": "list", "project_id": ""},
        ]
        for operation in ("download", "publish", "obs", "calendar", "approve", ""):
            cases.append(
                {"action": "submit", "project_id": "p", "operation": operation}
            )
        self.assert_rejected_without_effect(self.tools.job_handler, cases)

    def test_job_errors_are_json_failures(self):
        self.studio.cancel.side_effect = FileNotFoundError("Unknown job")
        self.assertEqual(
            self.invoke({"action": "cancel", "job_id": "j"}),
            {"ok": False, "error": "Unknown job", "type": "FileNotFoundError"},
        )


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.tools = importlib.import_module("cutroom.studio_tools")

    def test_schemas_are_strict_and_have_no_approval_surface(self):
        definitions = {item["name"]: item for item in self.tools.definitions()}
        self.assertEqual(set(definitions), {"cutroom_project", "cutroom_job"})
        project = definitions["cutroom_project"]["parameters"]
        job = definitions["cutroom_job"]["parameters"]
        for parameters in (project, job):
            self.assertFalse(parameters["additionalProperties"])
            self.assertEqual(parameters["required"], ["action"])
        self.assertEqual(
            project["properties"]["action"]["enum"],
            [
                "create",
                "list",
                "get",
                "update",
                "review",
                "derive",
                "find_clips",
                "create_clip",
            ],
        )
        self.assertEqual(
            set(project["properties"]),
            {
                "action",
                "source",
                "name",
                "project_id",
                "changes",
                "revision",
                "platform",
                "final_resolution",
                "min_s",
                "max_s",
                "count",
                "candidate_id",
                "start",
                "end",
            },
        )
        self.assertEqual(
            project["properties"]["platform"]["enum"],
            ["custom", "instagram_reels", "youtube_shorts", "tiktok", "youtube"],
        )
        self.assertEqual(
            sorted(project["properties"]["changes"]["properties"]),
            sorted(self.tools.PROJECT_CHANGES),
        )
        self.assertFalse(project["properties"]["changes"]["additionalProperties"])
        self.assertEqual(
            job["properties"]["action"]["enum"], ["submit", "list", "get", "cancel"]
        )
        self.assertEqual(
            set(job["properties"]),
            {"action", "project_id", "job_id", "operation", "options"},
        )
        self.assertEqual(
            set(job["properties"]["operation"]["enum"]), self.tools.JOB_OPERATIONS
        )
        text = json.dumps(definitions).lower()
        for forbidden in ('"approve"', '"confirm"', "download", "publish", '"obs"'):
            self.assertNotIn(forbidden, text)
        for definition in definitions.values():
            description = definition["description"].lower()
            self.assertIn("cutroom studio", description)
            self.assertIn("never claim", description)
        self.assertIn("50", definitions["cutroom_project"]["description"])


if __name__ == "__main__":
    unittest.main()
