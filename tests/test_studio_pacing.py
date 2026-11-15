"""Studio pacing settings, pause shortening, digest, REST/tool schema and QA wiring."""

import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom import pacing
from cutroom.childenv import child_env
from cutroom.studio import _CHILD_PROCESSES, Studio


def probe_result(duration=10.0, width=1920, height=1080):
    return {"duration": duration, "width": width, "height": height, "has_audio": True}


def word(identifier, start, end):
    return {
        "id": identifier,
        "start": start,
        "end": end,
        "text": f"w{identifier}",
        "probability": 0.9,
    }


TRANSCRIPT = {
    "language": "en",
    "text": "w0 w1 w2 w3",
    "engine": "test",
    "status": "ok",
    "words": [
        word(0, 0.5, 1.0),
        word(1, 3.5, 4.0),
        word(2, 4.2, 4.6),
        word(3, 7.0, 7.5),
    ],
}


class StudioPacingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"unit source fixture")
        probe = patch("cutroom.studio.probe", return_value=probe_result())
        probe.start()
        self.addCleanup(probe.stop)
        self.studio = Studio(self.root / "workspace")
        self.project = self.studio.create(self.source, name="Talk")

    def update(self, changes):
        project = self.studio.get(self.project["id"])
        return self.studio.update(project["id"], changes, project["revision"])

    def test_pacing_is_validated_normalised_and_removable(self):
        updated = self.update({"settings": {"pacing": {"punch_in": "alternate"}}})
        self.assertEqual(
            updated["settings"]["pacing"],
            pacing.validate_settings({"punch_in": "alternate"}),
        )
        revision = updated["revision"]
        for bad in (
            {"pacing": {"punch_in": "always"}},
            {"pacing": {"max_pause": 5}},
            {"pacing": "fast"},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.update({"settings": bad})
        self.assertEqual(self.studio.get(self.project["id"])["revision"], revision)
        removed = self.update({"settings": {"pacing": None}})
        self.assertNotIn("pacing", removed["settings"])

    def test_pacing_is_part_of_the_reviewed_digest(self):
        before = self.studio.review(self.project["id"])["digest"]
        self.update({"settings": {"pacing": {"transition": "dip"}}})
        after = self.studio.review(self.project["id"])["digest"]
        self.assertNotEqual(before, after)
        self.update({"settings": {"pacing": {"transition": "crossfade"}}})
        self.assertNotEqual(after, self.studio.review(self.project["id"])["digest"])

    def test_max_pause_shortens_program_pauses_and_can_be_undone(self):
        self.update({"transcript": TRANSCRIPT})
        original = self.studio.get(self.project["id"])["segments"]
        shortened = self.update({"settings": {"pacing": {"max_pause": 0.6}}})
        self.assertEqual(
            shortened["segments"],
            [
                {"start": 0.0, "end": 1.3},
                {"start": 3.2, "end": 4.9},
                {"start": 6.7, "end": 10.0},
            ],
        )
        self.assertEqual(shortened["base_segments"], original, "base edit untouched")
        # Captions follow the shortened program.
        words = self.studio._caption_words(shortened)
        self.assertAlmostEqual(words[1]["start"] - words[0]["end"], 0.6, places=6)
        # Excluding a word recomputes the pauses around the new gap.
        excluded = self.update({"excluded_word_ids": [2]})
        gaps = [
            b["start"] - a["end"]
            for a, b in zip(
                self.studio._caption_words(excluded),
                self.studio._caption_words(excluded)[1:],
            )
        ]
        self.assertTrue(all(gap <= 0.6 + 1e-6 for gap in gaps), gaps)
        restored = self.update(
            {"settings": {"pacing": {"max_pause": None}}, "excluded_word_ids": []}
        )
        self.assertEqual(restored["segments"], original)

    def test_render_and_quality_settings_carry_pacing(self):
        self.update({"transcript": TRANSCRIPT})
        project = self.update(
            {
                "settings": {
                    "pacing": {"punch_in": "alternate", "max_pause": 0.6},
                    "framing": "center_crop",
                }
            }
        )
        project["analysis"] = {
            "face_samples": [[0.0, [[0.4, 0.4, 0.2, 0.3, 0.35, 0.1]]]],
            "scene_cuts": [],
        }
        render = self.studio._render_settings(project, "preview")
        self.assertEqual(render["pacing"], project["settings"]["pacing"])
        self.assertEqual(
            render["pacing_analysis"]["faces"], project["analysis"]["face_samples"]
        )
        self.assertNotIn("framing_analysis", render, "center_crop keeps its F2 inputs")
        quality = self.studio._quality_settings(project, "preview")
        self.assertNotIn("pacing_analysis", quality)
        self.assertEqual(
            quality["pacing_words"],
            [[0.5, 1.0], [3.5, 4.0], [4.2, 4.6], [7.0, 7.5]],
        )
        legacy = self.studio._render_settings(
            {**project, "settings": {**project["settings"], "pacing": None}},
            "preview",
        )
        self.assertNotIn("pacing", legacy)

    def test_rest_model_and_tool_schema_accept_only_valid_pacing(self):
        from dashboard.plugin_api import UpdateProject

        UpdateProject(
            changes={"settings": {"pacing": {"punch_in": "alternate"}}}, revision=1
        )
        UpdateProject(changes={"settings": {"pacing": None}}, revision=1)
        with self.assertRaises(ValueError):
            UpdateProject(
                changes={"settings": {"pacing": {"punch_in": "x"}}}, revision=1
            )
        from cutroom.studio_tools import definitions

        project_tool = next(d for d in definitions() if d["name"] == "cutroom_project")
        settings = project_tool["parameters"]["properties"]["changes"]["properties"][
            "settings"
        ]
        schema = settings["properties"]["pacing"]
        self.assertEqual(schema["properties"]["punch_in"]["enum"], ["off", "alternate"])
        self.assertEqual(
            schema["properties"]["transition"]["enum"], ["cut", "crossfade", "dip"]
        )
        self.assertFalse(schema["additionalProperties"])


class StudioPacingRenderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "landscape.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=1280x720:rate=30:duration=4",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=330:sample_rate=48000:duration=4",
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
            env=child_env(python=False),
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

    def test_face_track_punch_ins_crossfade_and_quality_report(self):
        project = self.studio.create(self.source, name="Talk")
        project["analysis"] = {
            "face_samples": [
                [i / 30, [[0.35, 0.4, 0.2, 0.3, 0.35, 0.1]]] for i in range(0, 120, 3)
            ],
            "scene_cuts": [],
            "frames": [],
        }
        self.studio._write(project)
        project = self.studio.update(
            project["id"],
            {
                "settings": {
                    "platform": "instagram_reels",
                    "framing": "face_track",
                    "pacing": {
                        "punch_in": "alternate",
                        "transition": "crossfade",
                        "max_upscale": 4.0,
                    },
                },
                "segments": [
                    {"start": 0.0, "end": 1.0},
                    {"start": 1.5, "end": 2.5},
                    {"start": 3.0, "end": 3.9},
                ],
            },
            project["revision"],
        )
        job = self.run_job(project["id"], "preview")
        report = job["result"]["pacing"]
        self.assertEqual(len(report["transitions"]), 2)
        self.assertGreater(report["ranges"][1]["zoom"][0], 1.0)
        checks = {
            c["name"]: c for c in self.run_job(project["id"], "qa")["result"]["checks"]
        }
        for name in (
            "pacing_upscale",
            "pacing_face",
            "pacing_transitions",
            "framing_frames",
            "duration",
        ):
            self.assertEqual(checks[name]["status"], "pass", checks[name])


if __name__ == "__main__":
    unittest.main()
