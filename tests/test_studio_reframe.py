"""Studio framing settings, render settings, derive rules, preflight and QA wiring."""

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom.childenv import child_env
from cutroom.media import probe
from cutroom.studio import _CHILD_PROCESSES, Studio


def probe_result(duration=4.0, width=1920, height=1080):
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "has_audio": True,
    }


FACES = [[i / 10, [[0.3, 0.4, 0.2, 0.3, 0.35, 0.1]]] for i in range(40)]


class _Case(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"unit source fixture")
        self.probe = patch("cutroom.studio.probe", return_value=probe_result())
        self.probe.start()
        self.addCleanup(self.probe.stop)
        self.studio = Studio(self.root / "workspace")
        self.project = self.studio.create(self.source, name="Talk")

    def settings(self, changes, project_id=None):
        project = self.studio.get(project_id or self.project["id"])
        return self.studio.update(
            project["id"], {"settings": changes}, project["revision"]
        )

    def with_analysis(self, analysis):
        project = self.studio.get(self.project["id"])
        project["analysis"] = analysis
        self.studio._write(project)
        return project


class FramingSettingsTests(_Case):
    def test_framing_and_keyframes_are_validated(self):
        updated = self.settings(
            {
                "platform": "instagram_reels",
                "framing": "face_track",
                "framing_keyframes": [{"time": 1, "x": 0.4}],
            }
        )
        self.assertEqual(updated["settings"]["framing"], "face_track")
        self.assertEqual(
            updated["settings"]["framing_keyframes"], [{"time": 1.0, "x": 0.4}]
        )
        revision = updated["revision"]
        for bad in (
            {"framing": "zoom"},
            {"framing": None},
            {"framing_keyframes": [{"time": 5, "x": 0.4}]},
            {"framing_keyframes": [{"time": 1, "x": 2}]},
            {"framing_keyframes": "0.5"},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.settings(bad)
        self.assertEqual(self.studio.get(self.project["id"])["revision"], revision)

    def test_projects_without_framing_render_exactly_as_before(self):
        legacy = self.studio.get(self.project["id"])
        before = json.dumps(self.studio._render_settings(legacy, "preview"))
        digest = self.studio._digest(legacy)
        fit = dict(legacy, settings={**legacy["settings"], "framing": "fit"})
        self.assertEqual(
            json.dumps(self.studio._render_settings(fit, "preview")), before
        )
        keyed = dict(
            legacy,
            settings={
                **legacy["settings"],
                "framing": "blur_fill",
                "framing_keyframes": [{"time": 1.0, "x": 0.4}],
            },
        )
        render = self.studio._render_settings(keyed, "preview")
        self.assertEqual(render["framing"], "blur_fill")
        self.assertNotIn("framing_keyframes", render)
        self.assertEqual(self.studio._digest(self.studio.get(legacy["id"])), digest)

    def test_crop_render_settings_carry_keyframes_and_face_track_inputs(self):
        self.with_analysis({"face_samples": FACES, "scene_cuts": [2.0], "frames": []})
        project = self.settings(
            {
                "platform": "instagram_reels",
                "framing": "face_track",
                "framing_keyframes": [{"time": 1, "x": 0.4}],
            }
        )
        render = self.studio._render_settings(project, "preview")
        self.assertEqual(render["framing"], "face_track")
        self.assertEqual(render["framing_keyframes"], [{"time": 1.0, "x": 0.4}])
        self.assertEqual(
            render["framing_analysis"], {"faces": FACES, "scene_cuts": [2.0]}
        )
        quality = self.studio._quality_settings(project, "preview")
        self.assertEqual(quality["framing"], "face_track")
        self.assertNotIn("framing_analysis", quality)
        self.assertNotIn("framing_keyframes", quality)
        centre = self.settings({"framing": "center_crop"})
        render = self.studio._render_settings(centre, "preview")
        self.assertNotIn("framing_analysis", render)
        self.assertEqual(render["framing_keyframes"], [{"time": 1.0, "x": 0.4}])

    def test_face_track_without_vision_is_refused_before_a_job(self):
        project = self.settings(
            {"platform": "instagram_reels", "framing": "face_track"}
        )
        for action in ("preview", "final"):
            with (
                self.subTest(action=action),
                self.assertRaisesRegex(ValueError, "[Vv]ision"),
            ):
                self.studio._preflight(project, action)
        with self.assertRaisesRegex(ValueError, "[Vv]ision"):
            self.studio.submit(project["id"], "preview")
        self.assertEqual(self.studio.jobs(project["id"]), [])
        # An analysis recorded before face boxes existed must be run again.
        self.with_analysis({"frames": [], "status": "ok"})
        with self.assertRaisesRegex(ValueError, "again"):
            self.studio._preflight(self.studio.get(project["id"]), "preview")
        self.with_analysis({"face_samples": [], "scene_cuts": [], "frames": []})
        self.assertIsNone(
            self.studio._preflight(self.studio.get(project["id"]), "preview")
        )

    def test_framing_and_face_analysis_are_part_of_the_reviewed_digest(self):
        project = self.with_analysis({"face_samples": FACES, "scene_cuts": []})
        digest = self.studio._digest(project)
        moved = json.loads(json.dumps(project))
        moved["analysis"]["face_samples"][0][1][0][0] = 0.31
        self.assertNotEqual(self.studio._digest(moved), digest)
        cut = json.loads(json.dumps(project))
        cut["analysis"]["scene_cuts"] = [1.0]
        self.assertNotEqual(self.studio._digest(cut), digest)
        framed = self.settings({"framing": "center_crop"})
        self.assertNotEqual(self.studio._digest(framed), digest)
        self.studio.approve(framed["id"], self.studio._digest(framed))
        keyed = self.settings({"framing_keyframes": [{"time": 0.5, "x": 0.5}]})
        self.assertNotIn("approval", keyed)

    def test_derive_keeps_framing_and_only_same_orientation_pins(self):
        parent = self.settings(
            {
                "platform": "instagram_reels",
                "framing": "face_track",
                "framing_keyframes": [{"time": 1, "x": 0.4}],
            }
        )
        shorts = self.studio.derive(parent["id"], "youtube_shorts")
        self.assertEqual(shorts["settings"]["framing"], "face_track")
        self.assertEqual(
            shorts["settings"]["framing_keyframes"], [{"time": 1.0, "x": 0.4}]
        )
        self.assertIsNone(shorts["analysis"])
        with self.assertRaisesRegex(ValueError, "[Vv]ision"):
            self.studio._preflight(shorts, "preview")
        youtube = self.studio.derive(parent["id"], "youtube")
        self.assertEqual(youtube["settings"]["framing"], "face_track")
        self.assertNotIn("framing_keyframes", youtube["settings"])

    def test_program_time_pins_are_revalidated_when_the_edit_is_shortened(self):
        project = self.settings(
            {"framing": "center_crop", "framing_keyframes": [{"time": 3, "x": 0.5}]}
        )
        with self.assertRaisesRegex(ValueError, "range"):
            self.studio.update(
                project["id"],
                {"segments": [{"start": 0, "end": 1}]},
                project["revision"],
            )


class VisionCompletionTests(_Case):
    def test_vision_completion_keeps_every_face_sample(self):
        project = self.studio.get(self.project["id"])
        record = {
            "id": "b" * 32,
            "project_id": project["id"],
            "action": "vision",
            "revision": project["revision"],
            "status": "running",
            "review_digest": self.studio._digest(project),
            "input_digests": {},
            "options": {},
        }
        self.studio._job_path(record["id"]).parent.mkdir(parents=True)
        self.studio._write_job(record)
        frames = [{"time": i / 30, "faces": []} for i in range(2500)]
        samples = [[i / 30, []] for i in range(2500)]
        with patch.object(self.studio, "_job_inputs", return_value={}):
            self.studio._complete_job(
                record,
                {"frames": frames, "face_samples": samples, "scene_cuts": []},
            )
        analysis = self.studio.get(project["id"])["analysis"]
        self.assertEqual(len(analysis["frames"]), 2000)
        self.assertEqual(len(analysis["face_samples"]), 2500)
        self.assertEqual(analysis["scene_cuts"], [])


class FramingJobsTests(unittest.TestCase):
    """A landscape source with a recorded face track renders a vertical crop."""

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
                "testsrc2=size=640x360:rate=30:duration=3",
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

    def test_face_track_preview_and_quality_report(self):
        project = self.studio.create(self.source, name="Talk")
        project["analysis"] = {
            "face_samples": [
                [i / 30, [[0.3 if i < 45 else 0.6, 0.4, 0.2, 0.3, 0.35, 0.1]]]
                for i in range(90)
            ],
            "scene_cuts": [],
            "frames": [],
        }
        self.studio._write(project)
        project = self.studio.update(
            project["id"],
            {
                "settings": {"platform": "instagram_reels", "framing": "face_track"},
                "segments": [{"start": 0.0, "end": 1.2}, {"start": 1.5, "end": 2.8}],
            },
            project["revision"],
        )
        job = self.run_job(project["id"], "preview")
        framing = job["result"]["framing"]
        self.assertEqual(framing["mode"], "face_track")
        self.assertTrue(job["result"]["upscaled"])
        info = probe(self.studio.artifact(project["id"], "preview"))
        self.assertEqual([info["width"], info["height"]], [1080, 1920])
        checks = {
            c["name"]: c for c in self.run_job(project["id"], "qa")["result"]["checks"]
        }
        for name in ("framing_face_safe_zone", "framing_smoothness", "framing_frames"):
            self.assertEqual(checks[name]["status"], "pass", checks[name])
        self.assertEqual(checks["platform_upscale"]["status"], "warning")
        self.assertEqual(checks["platform_upscale"]["detail"]["crop"], [202, 360])


if __name__ == "__main__":
    unittest.main()
