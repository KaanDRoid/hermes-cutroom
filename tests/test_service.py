"""Regression coverage for source identity and canonical project paths."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom.hermes_plugin import draft_plan as draft
from cutroom.hermes_plugin import render_plan as render_approved
from cutroom.project import approve_plan, save_draft, write_review


class ServiceTests(unittest.TestCase):
    def test_source_changed_during_analysis_cannot_become_a_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"original unit fixture, not media")

            def change_source(*args, **kwargs):
                source.write_bytes(b"replaced unit fixture, not media")
                return []

            with (
                patch("cutroom.media.probe", return_value={"duration": 4}),
                patch("cutroom.media.detect_silences", side_effect=change_source),
            ):
                with self.assertRaises(PermissionError):
                    draft(source, root / "project")
            self.assertFalse((root / "project").exists())

    def test_home_plan_path_keeps_output_beside_approved_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"unit source fixture, not video")
            path = save_draft(
                {
                    "version": 1,
                    "source": str(source),
                    "source_duration": 4,
                    "segments": [{"start": 0, "end": 2}],
                },
                root / "project",
            )
            approve_plan(path, write_review(path)["digest"])
            with (
                patch.dict(os.environ, {"USERPROFILE": str(root), "HOME": str(root)}),
                patch("cutroom.media.render", return_value={}) as renderer,
            ):
                render_approved("~/project/plan.json")
            self.assertEqual(renderer.call_args.args[2].parent, path.parent)


if __name__ == "__main__":
    unittest.main()
