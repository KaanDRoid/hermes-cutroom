"""Caption-style settings on the agent tool and REST surfaces."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cutroom import studio_tools

ROOT = Path(__file__).resolve().parents[1]

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional dashboard dependencies
    FastAPI = TestClient = None


class ToolSchemaTests(unittest.TestCase):
    def test_settings_schema_declares_caption_enums(self):
        project = studio_tools.definitions()[0]
        settings = project["parameters"]["properties"]["changes"]["properties"][
            "settings"
        ]
        properties = settings["properties"]
        self.assertEqual(
            properties["caption_style"]["enum"],
            ["classic", "highlight", "pop", "one_word"],
        )
        self.assertEqual(
            properties["caption_highlight_color"]["pattern"], "^#[0-9A-Fa-f]{6}$"
        )
        self.assertEqual(properties["caption_word_y"]["minimum"], 0)
        self.assertEqual(properties["caption_word_y"]["maximum"], 1)

    def test_invalid_caption_settings_are_rejected_before_studio(self):
        factory = patch.object(studio_tools, "get_studio", return_value=Mock()).start()
        self.addCleanup(patch.stopall)
        for settings in (
            {"caption_style": "karaoke"},
            {"caption_style": None},
            {"caption_highlight_color": "red"},
            {"caption_word_y": 3},
            {"caption_word_y": True},
        ):
            with self.subTest(settings=settings):
                result = json.loads(
                    studio_tools.project_handler(
                        {
                            "action": "update",
                            "project_id": "p",
                            "changes": {"settings": settings},
                            "revision": 1,
                        }
                    )
                )
                self.assertFalse(result["ok"])
                factory.assert_not_called()
        studio = Mock()
        studio.update.return_value = {"id": "p"}
        factory.return_value = studio
        result = json.loads(
            studio_tools.project_handler(
                {
                    "action": "update",
                    "project_id": "p",
                    "changes": {"settings": {"caption_style": "one_word"}},
                    "revision": 1,
                }
            )
        )
        self.assertTrue(result["ok"], result)


@unittest.skipIf(
    TestClient is None, "FastAPI/httpx are optional dashboard dependencies"
)
class RestTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "dashboard" / "plugin_api.py"
        spec = importlib.util.spec_from_file_location(
            "hermes_dashboard_plugin_cutroom_caption_test", path
        )
        self.api = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.api
        spec.loader.exec_module(self.api)
        self.studio = Mock()
        self.studio.update.side_effect = lambda project_id, changes, revision: {
            "id": project_id,
            "revision": revision + 1,
            **changes,
        }
        app = FastAPI()
        app.include_router(self.api.router)
        app.dependency_overrides[self.api.get_studio] = lambda: self.studio
        self.client = TestClient(app)

    def patch(self, settings):
        return self.client.patch(
            "/projects/p1", json={"revision": 1, "changes": {"settings": settings}}
        )

    def test_caption_settings_are_strict(self):
        response = self.patch(
            {
                "caption_style": "highlight",
                "caption_highlight_color": "#112233",
                "caption_word_y": 0.6,
            }
        )
        self.assertEqual(response.status_code, 200, response.text)
        for settings in (
            {"caption_style": "karaoke"},
            {"caption_style": None},
            {"caption_highlight_color": "#12345"},
            {"caption_word_y": -1},
            {"caption_word_y": "0.5"},
        ):
            with self.subTest(settings=settings):
                self.studio.update.reset_mock()
                self.assertEqual(self.patch(settings).status_code, 422)
                self.studio.update.assert_not_called()

    def test_null_resets_optional_caption_fields(self):
        response = self.patch({"caption_highlight_color": None, "caption_word_y": None})
        self.assertEqual(response.status_code, 200, response.text)
        self.studio.update.assert_called_once()


if __name__ == "__main__":
    unittest.main()
