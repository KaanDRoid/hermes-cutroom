"""Real end-to-end plugin workflow on an explicitly synthetic AV fixture."""

import hashlib
import json
import os
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cutroom.hermes_plugin import register
from cutroom.project import approve_plan


class ToolContext:
    def __init__(self):
        self.tools = {}

    def register_tool(self, **tool):
        self.tools[tool["name"]] = tool["handler"]


class WorkflowTests(unittest.TestCase):
    def test_native_handlers_draft_review_approve_render_real_media(self):
        root = (
            Path(__file__).resolve().parents[1]
            / "artifacts"
            / ("smoke-" + uuid.uuid4().hex[:8])
        )
        root.mkdir(parents=True)
        source = root / "synthetic-tone-silence-tone.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-n",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=25:duration=6",
                "-f",
                "lavfi",
                "-i",
                r"aevalsrc=if(between(t\,2\,4)\,0\,0.25*sin(2*PI*440*t)):s=48000:d=6",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(source),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=30,
        )
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        workspace = patch.dict(os.environ, {"CUTROOM_WORKSPACE": str(root / "studio")})
        workspace.start()
        self.addCleanup(workspace.stop)
        ctx = ToolContext()
        register(ctx)

        def call(name, args):
            return json.loads(ctx.tools[name](args, session_id="synthetic-smoke"))

        metadata = call("cutroom_inspect", {"source": str(source)})
        self.assertTrue(metadata["ok"], metadata)
        self.assertAlmostEqual(metadata["result"]["duration"], 6, delta=0.1)
        created = call(
            "cutroom_draft",
            {"source": str(source), "project_dir": "project"},
        )
        self.assertTrue(created["ok"], created)
        draft = created["result"]
        self.assertEqual(
            Path(draft["plan"]).parent,
            (root / "studio" / "plans" / "project").resolve(),
        )
        self.assertEqual(len(draft["segments"]), 2)
        self.assertAlmostEqual(draft["output_duration"], 4.24, delta=0.1)
        blocked = call("cutroom_render", {"plan_path": draft["plan"]})
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["type"], "PermissionError")
        review = call("cutroom_review", {"path": draft["plan"]})
        self.assertTrue(review["ok"], review)
        approve_plan(draft["plan"], review["result"]["digest"])
        rendered = call("cutroom_render", {"plan_path": draft["plan"]})
        self.assertTrue(rendered["ok"], rendered)
        actual = rendered["result"]
        self.assertTrue(Path(actual["output"]).is_file())
        self.assertAlmostEqual(actual["duration"], draft["output_duration"], delta=0.12)
        self.assertEqual((actual["width"], actual["height"]), (320, 180))
        self.assertTrue(actual["has_audio"])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)
        refused = call("cutroom_render", {"plan_path": draft["plan"]})
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["type"], "FileExistsError")
        report = {
            "fixture": "Synthetic color/motion pattern with tone-silence-tone; not human speech",
            "source": str(source),
            "source_sha256": original_hash,
            "draft": draft,
            "render": actual,
            "unapproved_render_blocked": True,
            "source_unchanged": True,
            "existing_output_blocked": True,
        }
        (root / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print("\nWorkflow artifacts: " + str(root))


if __name__ == "__main__":
    unittest.main()
