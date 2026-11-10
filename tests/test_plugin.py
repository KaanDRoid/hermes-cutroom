import json
import unittest

from cutroom.hermes_plugin import register


class Context:
    def __init__(self):
        self.tools = {}

    def register_tool(self, **tool):
        self.tools[tool["name"]] = tool


class PluginTests(unittest.TestCase):
    def test_tools_register_with_schemas_and_json_errors(self):
        ctx = Context()
        register(ctx)
        self.assertEqual(
            set(ctx.tools),
            {"cutroom_inspect", "cutroom_draft", "cutroom_review", "cutroom_render"},
        )
        for name, tool in ctx.tools.items():
            with self.subTest(tool=name):
                self.assertEqual(tool["toolset"], "cutroom")
                self.assertEqual(tool["schema"]["name"], name)
                result = json.loads(tool["handler"]({}, session_id="test"))
                self.assertIn("error", result)
                self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
