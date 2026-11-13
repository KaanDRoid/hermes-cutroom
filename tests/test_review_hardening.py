"""Catalog review hardening: interpreter choice, child environment, legacy paths."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom.hermes_plugin import register
from cutroom.runtime import invoke_worker, runtime_python
from cutroom.studio import _CHILD_PROCESSES, Studio

SECRET = "sk-should-never-reach-children"


def make_video(path, audio=True):
    command = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-n",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=96x64:rate=10:duration=3",
    ]
    if audio:
        command += [
            "-f",
            "lavfi",
            "-i",
            r"aevalsrc=if(between(t\,1\,2)\,0\,0.25*sin(2*PI*440*t)):s=48000:d=3",
            "-c:a",
            "aac",
            "-shortest",
        ]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    subprocess.run(command + [str(path)], capture_output=True, check=True, timeout=30)
    return path


class _Captured(Exception):
    pass


def capture_popen(store):
    def fake(*args, **kwargs):
        store.append(kwargs.get("env"))
        raise _Captured()

    return fake


class InterpreterSelectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.studio = Studio(self.root / "studio")
        self.project = self.studio.create(str(make_video(self.root / "in.mp4")))
        self.fake = self.root / "repo" / ".venv" / "python.exe"
        self.fake.parent.mkdir(parents=True)
        self.fake.write_text("not an interpreter", encoding="utf-8")

    def test_project_settings_cannot_choose_the_interpreter(self):
        with self.assertRaisesRegex(ValueError, "Unsupported settings"):
            self.studio.update(
                self.project["id"],
                {"settings": {"runtime_python": str(self.fake)}},
                self.project["revision"],
            )

    def test_agent_tool_cannot_choose_the_interpreter(self):
        tools = {}

        class Ctx:
            def register_tool(self, **tool):
                tools[tool["name"]] = tool["handler"]

        register(Ctx())
        with patch.dict(os.environ, {"CUTROOM_WORKSPACE": str(self.root / "studio")}):
            with patch("cutroom.studio_tools.get_studio", return_value=self.studio):
                result = json.loads(
                    tools["cutroom_project"](
                        {
                            "action": "update",
                            "project_id": self.project["id"],
                            "changes": {"settings": {"runtime_python": str(self.fake)}},
                            "revision": self.project["revision"],
                        },
                        session_id="t",
                    )
                )
        self.assertFalse(result["ok"])
        self.assertNotIn(
            "runtime_python", self.studio.get(self.project["id"])["settings"]
        )

    def test_stored_legacy_interpreter_setting_is_never_executed(self):
        path = self.root / "studio" / "projects" / self.project["id"] / "studio.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["settings"]["runtime_python"] = str(self.fake)
        path.write_text(json.dumps(data), encoding="utf-8")
        loaded = self.studio.get(self.project["id"])
        self.assertNotIn("runtime_python", loaded["settings"])
        # A client echoing the full settings object back still saves.
        saved = self.studio.update(
            self.project["id"],
            {"settings": dict(loaded["settings"], title="Hello")},
            loaded["revision"],
        )
        self.assertNotIn("runtime_python", saved["settings"])
        data = json.loads(path.read_text(encoding="utf-8"))
        data["settings"]["runtime_python"] = str(self.fake)
        path.write_text(json.dumps(data), encoding="utf-8")
        with patch("subprocess.Popen") as detached:
            job = self.studio.submit(self.project["id"], "silence", {})
        detached.assert_called_once()
        _CHILD_PROCESSES.pop(job["id"], None)
        launched = []

        def record(*args, **kwargs):
            launched.append(args[0][0])
            raise _Captured()

        with patch("cutroom.runtime.subprocess.Popen", side_effect=record):
            with self.assertRaises(_Captured):
                self.studio._perform_job(self.studio.job(job["id"]))
        self.assertEqual(len(launched), 1)
        self.assertNotEqual(Path(launched[0]).resolve(), self.fake.resolve())
        self.assertEqual(launched[0], runtime_python())

    def test_runtime_takes_only_the_user_environment_or_bundled_interpreter(self):
        with patch.dict(os.environ, {"CUTROOM_PYTHON": sys.executable}):
            self.assertEqual(runtime_python(), str(Path(sys.executable).resolve()))
        self.assertNotIn("configured", runtime_python.__code__.co_varnames)
        self.assertNotIn("python", invoke_worker.__code__.co_varnames)


class ChildEnvironmentTests(unittest.TestCase):
    allowed = {
        "PATH",
        "PATHEXT",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "APPDATA",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "FONTCONFIG_FILE",
        "FONTCONFIG_PATH",
        "PYTHONPATH",
        "PYTHONIOENCODING",
        "CUTROOM_WORKSPACE",
        "CUTROOM_PYTHON",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "HF_HUB_OFFLINE",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN",
        "HF_HUB_DISABLE_TELEMETRY",
    }
    leaked = {
        "OPENROUTER_API_KEY": SECRET,
        "ANTHROPIC_API_KEY": SECRET,
        "GITHUB_TOKEN": SECRET,
        "HF_TOKEN": SECRET,
        "AWS_SECRET_ACCESS_KEY": SECRET,
        "UNRELATED_SETTING": "x",
    }

    def check(self, env):
        self.assertIsInstance(env, dict)
        self.assertLessEqual(
            set(env) - self.allowed, set(), sorted(set(env) - self.allowed)
        )
        self.assertNotIn(SECRET, json.dumps(env))
        self.assertIn("PATH", env)
        root = str(Path(__file__).resolve().parents[1])
        self.assertEqual(env["PYTHONPATH"].split(os.pathsep)[0], root)

    def test_model_worker_receives_a_minimal_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            seen = []
            with patch.dict(os.environ, self.leaked):
                with patch(
                    "cutroom.runtime.subprocess.Popen", side_effect=capture_popen(seen)
                ):
                    with self.assertRaises(_Captured):
                        invoke_worker("inspect", {"source": "x"}, Path(temporary) / "w")
            self.check(seen[0])
            self.assertEqual(seen[0]["HF_HUB_OFFLINE"], "1")
            self.assertEqual(seen[0]["OMP_NUM_THREADS"], "4")

    def test_job_supervisor_receives_a_minimal_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            studio = Studio(root / "studio")
            project = studio.create(str(make_video(root / "in.mp4")))
            seen = []
            with patch.dict(os.environ, self.leaked):
                with patch("subprocess.Popen", side_effect=capture_popen(seen)):
                    try:
                        studio.submit(project["id"], "silence", {})
                    except _Captured:
                        pass
            self.check(seen[0])

    def test_ffmpeg_and_tool_probes_receive_a_minimal_environment(self):
        from cutroom import media, postproduction, setup

        for label, call in (
            ("media", lambda: media._run(["ffmpeg", "-version"])),
            ("postproduction", lambda: postproduction._run(["ffmpeg", "-version"])),
            ("setup", lambda: setup._tool("ffmpeg")),
        ):
            with self.subTest(caller=label):
                seen = []

                def record(*args, **kwargs):
                    seen.append(kwargs.get("env"))
                    raise _Captured()

                with patch.dict(os.environ, self.leaked):
                    with patch("subprocess.run", side_effect=record):
                        try:
                            call()
                        except _Captured:
                            pass
                self.assertTrue(seen, label)
                self.assertIsInstance(seen[0], dict)
                self.assertLessEqual(set(seen[0]) - self.allowed, set())
                self.assertNotIn(SECRET, json.dumps(seen[0]))

    def test_integrations_forward_only_their_own_configuration(self):
        from cutroom import integrations

        seen = []

        def record(*args, **kwargs):
            seen.append(kwargs.get("env"))
            raise _Captured()

        extra = dict(
            self.leaked,
            RCLONE_CONFIG="C:/cfg/rclone.conf",
            HTTPS_PROXY="http://proxy:3128",
        )
        with patch.dict(os.environ, extra):
            with patch("subprocess.run", side_effect=record):
                with self.assertRaises(_Captured):
                    integrations._run(["rclone", "version"])
        env = seen[0]
        self.assertEqual(env["RCLONE_CONFIG"], "C:/cfg/rclone.conf")
        self.assertEqual(env["HTTPS_PROXY"], "http://proxy:3128")
        self.assertNotIn(SECRET, json.dumps(env))

    @unittest.skipUnless(os.name == "nt", "taskkill is Windows-only")
    def test_windows_tree_kill_uses_system_taskkill_and_minimal_environment(self):
        from cutroom import runtime

        seen = []

        class Running:
            pid = 4242

            def poll(self):
                return None

            def wait(self, timeout=None):
                return 1

        def record(command, **kwargs):
            seen.append((command, kwargs.get("env")))

        with patch.dict(os.environ, self.leaked):
            with patch("subprocess.run", side_effect=record):
                runtime._terminate(Running())
        command, env = seen[0]
        self.assertTrue(Path(command[0]).is_absolute())
        self.assertEqual(Path(command[0]).name.lower(), "taskkill.exe")
        self.assertLessEqual(set(env) - self.allowed, set())
        self.assertNotIn(SECRET, json.dumps(env))

    def test_real_worker_runs_with_the_minimal_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = make_video(root / "in.mp4", audio=False)
            with patch.dict(os.environ, self.leaked):
                result = invoke_worker("inspect", {"source": str(source)}, root / "w")
            self.assertEqual(result["width"], 96)


class LegacyToolConfinementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "workspace" / "studio"
        self.outside = self.root / "outside"
        self.outside.mkdir()
        self.source = make_video(self.root / "in.mp4")
        patcher = patch.dict(
            os.environ,
            {"CUTROOM_WORKSPACE": str(self.workspace), "CUTROOM_LEGACY_TOOLS": "1"},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tools = {}

        class Ctx:
            def register_tool(inner, **tool):
                self.tools[tool["name"]] = tool["handler"]

        register(Ctx())

    def call(self, name, args):
        return json.loads(self.tools[name](args, session_id="t"))

    def plans(self):
        return self.workspace / "plans"

    def test_draft_outside_the_workspace_is_refused_without_writes(self):
        for target in (
            self.outside / "project",
            "../../escape",
            str(self.plans() / ".." / ".." / "escape"),
        ):
            with self.subTest(target=target):
                result = self.call(
                    "cutroom_draft",
                    {"source": str(self.source), "project_dir": str(target)},
                )
                self.assertFalse(result["ok"])
                self.assertEqual(result["type"], "PermissionError")
        self.assertEqual(list(self.outside.iterdir()), [])
        self.assertFalse((self.root / "workspace" / "escape").exists())
        self.assertFalse((self.root / "escape").exists())

    def test_draft_by_name_lands_inside_the_workspace(self):
        result = self.call(
            "cutroom_draft", {"source": str(self.source), "project_dir": "talk"}
        )
        self.assertTrue(result["ok"], result)
        plan = Path(result["result"]["plan"])
        self.assertEqual(plan.parent, (self.plans() / "talk").resolve())
        self.assertTrue((plan.parent / "review.html").is_file())

    def test_review_and_render_refuse_plans_outside_the_workspace(self):
        from cutroom.hermes_plugin import draft
        from cutroom.project import approve_plan

        with patch.dict(os.environ, {"CUTROOM_WORKSPACE": str(self.outside / "w")}):
            created = draft(str(self.source), "foreign")
        plan = created["plan"]
        # Approved, so only confinement can stop the render.
        approve_plan(plan, created["digest"])
        review = Path(plan).parent / "review.html"
        before = review.read_bytes()
        for name, args in (
            ("cutroom_review", {"path": plan}),
            ("cutroom_render", {"plan_path": plan}),
        ):
            with self.subTest(tool=name):
                result = self.call(name, args)
                self.assertFalse(result["ok"])
                self.assertEqual(result["type"], "PermissionError")
        self.assertEqual(review.read_bytes(), before)
        self.assertFalse((Path(plan).parent / "render.mp4").exists())

    def test_symlinked_project_escaping_the_workspace_is_refused(self):
        self.plans().mkdir(parents=True)
        link = self.plans() / "linked"
        try:
            os.symlink(self.outside, link, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            import _winapi

            _winapi.CreateJunction(str(self.outside), str(link))
        result = self.call(
            "cutroom_draft", {"source": str(self.source), "project_dir": "linked/inner"}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["type"], "PermissionError")
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_review_refuses_to_overwrite_a_review_it_did_not_create(self):
        created = self.call(
            "cutroom_draft", {"source": str(self.source), "project_dir": "talk"}
        )
        plan = created["result"]["plan"]
        review = Path(plan).parent / "review.html"
        regenerated = self.call("cutroom_review", {"path": plan})
        self.assertTrue(regenerated["ok"], regenerated)
        review.write_text("<p>somebody else's page</p>", encoding="utf-8")
        refused = self.call("cutroom_review", {"path": plan})
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["type"], "FileExistsError")
        self.assertEqual(
            review.read_text(encoding="utf-8"), "<p>somebody else's page</p>"
        )

    def _draft_without_receipt(self):
        created = self.call(
            "cutroom_draft", {"source": str(self.source), "project_dir": "talk"}
        )
        directory = Path(created["result"]["plan"]).parent
        for receipt in directory.glob(".review*"):
            receipt.unlink()
        return directory

    def test_review_refuses_a_preexisting_foreign_review_without_a_receipt(self):
        from cutroom.project import write_review

        directory = self._draft_without_receipt()
        (directory / "review.html").write_text("<p>notes</p>", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            write_review(directory / "plan.json")
        self.assertEqual(
            (directory / "review.html").read_text(encoding="utf-8"), "<p>notes</p>"
        )

    def test_review_written_before_receipts_existed_can_be_regenerated(self):
        from cutroom.project import write_review

        directory = self._draft_without_receipt()
        write_review(directory / "plan.json")
        self.assertTrue((directory / ".review.sha256").is_file())

    def test_interrupted_review_swap_does_not_lock_the_review(self):
        from cutroom import project

        created = self.call(
            "cutroom_draft", {"source": str(self.source), "project_dir": "talk"}
        )
        plan = Path(created["result"]["plan"])
        real = project._replace
        calls = []

        def crash_after_page(target, data):
            calls.append(target.name)
            real(target, data)
            if target.name == "review.html":
                raise KeyboardInterrupt

        data = json.loads(plan.read_text(encoding="utf-8"))
        data["segments"] = data["segments"][:1]
        plan.write_text(json.dumps(data), encoding="utf-8")
        with patch.object(project, "_replace", side_effect=crash_after_page):
            with self.assertRaises(KeyboardInterrupt):
                project.write_review(plan)
        self.assertEqual(calls, [".review.sha256", "review.html"])
        regenerated = self.call("cutroom_review", {"path": str(plan)})
        self.assertTrue(regenerated["ok"], regenerated)

    def test_network_paths_are_refused_before_they_are_resolved(self):
        import os.path

        real = os.path.realpath
        seen = []

        def record(path, *args, **kwargs):
            seen.append(os.fspath(path))
            return real(path, *args, **kwargs)

        targets = (
            r"\\203.0.113.9\share\x",
            "//203.0.113.9/share/x",
            r"\\?\UNC\203.0.113.9\share\x",
        )
        with patch("os.path.realpath", side_effect=record):
            for target in targets:
                for name, args in (
                    (
                        "cutroom_draft",
                        {"source": str(self.source), "project_dir": target},
                    ),
                    ("cutroom_review", {"path": target + "\plan.json"}),
                    ("cutroom_render", {"plan_path": target + "/plan.json"}),
                ):
                    with self.subTest(tool=name, target=target):
                        result = self.call(name, args)
                        self.assertFalse(result["ok"])
                        self.assertEqual(result["type"], "PermissionError")
        self.assertFalse([path for path in seen if "203.0.113.9" in path], seen)

    def test_project_directory_is_rechecked_after_analysis(self):
        from cutroom import media

        self.plans().mkdir(parents=True)
        real = media.detect_silences

        def plant_link(*args, **kwargs):
            link = self.plans() / "talk"
            try:
                os.symlink(self.outside, link, target_is_directory=True)
            except OSError:
                if os.name != "nt":
                    raise
                import _winapi

                _winapi.CreateJunction(str(self.outside), str(link))
            return real(*args, **kwargs)

        with patch("cutroom.media.detect_silences", side_effect=plant_link):
            result = self.call(
                "cutroom_draft",
                {"source": str(self.source), "project_dir": "talk/inner"},
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["type"], "PermissionError")
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_user_run_cli_keeps_choosing_its_own_directory(self):
        from cutroom.cli import main

        target = self.outside / "cli-project"
        self.assertEqual(main(["draft", str(self.source), str(target)]), 0)
        self.assertTrue((target / "plan.json").is_file())
        self.assertTrue((target / "review.html").is_file())


if __name__ == "__main__":
    unittest.main()
