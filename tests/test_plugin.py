import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom.hermes_plugin import register

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {"cutroom_inspect", "cutroom_project", "cutroom_job"}
LEGACY = {"cutroom_draft", "cutroom_review", "cutroom_render"}

REGISTER_PROBE = r"""
import json, os, subprocess, sys
spawned = []
def record(self, *args, **kwargs):
    spawned.append(repr(args[:1]))
    raise RuntimeError("process spawn during register")
subprocess.Popen.__init__ = record
os.system = lambda *a: spawned.append("system")
class Ctx:
    def __init__(self):
        self.tools = []
    def register_tool(self, **tool):
        self.tools.append(tool["name"])
import cutroom.hermes_plugin as plugin
ctx = Ctx()
plugin.register(ctx)
heavy = ("cutroom.media", "cutroom.worker", "cutroom.job_worker",
    "cutroom.vision", "cutroom.speech")
print(json.dumps({
    "tools": sorted(ctx.tools),
    "studio_loaded": "cutroom.studio" in sys.modules,
    "heavy": sorted(m for m in heavy if m in sys.modules),
    "spawned": spawned,
}))
"""


class Context:
    def __init__(self):
        self.tools = {}

    def register_tool(self, **tool):
        self.tools[tool["name"]] = tool


class PluginTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"CUTROOM_LEGACY_TOOLS": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_tools_register_with_schemas_and_json_errors(self):
        ctx = Context()
        register(ctx)
        self.assertEqual(set(ctx.tools), TOOLS | LEGACY)
        for name, tool in ctx.tools.items():
            with self.subTest(tool=name):
                self.assertEqual(tool["toolset"], "cutroom")
                self.assertEqual(tool["schema"]["name"], name)
                self.assertFalse(tool["schema"]["parameters"]["additionalProperties"])
                self.assertEqual(tool["description"], tool["schema"]["description"])
                result = json.loads(tool["handler"]({}, session_id="test"))
                self.assertIn("error", result)
                self.assertFalse(result["ok"])

    def test_legacy_tool_schemas_are_unchanged(self):
        ctx = Context()
        register(ctx)
        required = {
            "cutroom_inspect": ["source"],
            "cutroom_draft": ["source", "project_dir"],
            "cutroom_review": ["path"],
            "cutroom_render": ["plan_path"],
        }
        for name, keys in required.items():
            with self.subTest(tool=name):
                parameters = ctx.tools[name]["schema"]["parameters"]
                self.assertEqual(parameters["required"], keys)

    def test_register_is_side_effect_free_in_fresh_interpreter(self):
        with tempfile.TemporaryDirectory() as workspace:
            cwd = Path(workspace) / "cwd"
            cwd.mkdir()
            env = {
                key: value
                for key, value in os.environ.items()
                if key != "CUTROOM_LEGACY_TOOLS"
            }
            env = dict(
                env,
                PYTHONPATH=str(ROOT),
                PYTHONDONTWRITEBYTECODE="1",
                CUTROOM_WORKSPACE=str(Path(workspace) / "studio"),
            )
            completed = subprocess.run(
                [sys.executable, "-c", REGISTER_PROBE],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(set(report["tools"]), TOOLS)
            self.assertFalse(report["studio_loaded"])
            self.assertEqual(report["heavy"], [])
            self.assertEqual(report["spawned"], [])
            entries = sorted(path.name for path in Path(workspace).iterdir())
            self.assertEqual(entries, ["cwd"])
            self.assertEqual(list(cwd.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
