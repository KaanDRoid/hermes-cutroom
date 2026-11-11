import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from cutroom import cli


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class SetupCliTests(unittest.TestCase):
    def test_doctor_prints_json(self):
        with patch("cutroom.setup.doctor", return_value={"ffmpeg": {}}) as doctor:
            code, out, _ = run(["doctor", "--models-dir", "C:/models"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"ffmpeg": {}})
        doctor.assert_called_once_with(models_dir="C:/models")
        with patch("cutroom.setup.doctor", return_value={}) as doctor:
            self.assertEqual(run(["doctor"])[0], 0)
        doctor.assert_called_once_with(models_dir=None)

    def test_setup_models_defaults_to_plan(self):
        plan = {"status": "planned"}
        with patch("cutroom.setup.setup_models", return_value=plan) as setup:
            code, out, _ = run(["setup-models", "C:/models"])
        self.assertEqual((code, json.loads(out)), (0, plan))
        setup.assert_called_once_with(
            "C:/models", models="face,person,speech", confirm_downloads=False
        )

    def test_setup_models_confirmed_and_failure_exit_code(self):
        with patch(
            "cutroom.setup.setup_models", return_value={"status": "failed"}
        ) as setup:
            code, out, _ = run(
                ["setup-models", "C:/m", "--models", "face", "--confirm-downloads"]
            )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out), {"status": "failed"})
        setup.assert_called_once_with("C:/m", models="face", confirm_downloads=True)

    def test_errors_are_json_on_stderr(self):
        with patch("cutroom.setup.setup_models", side_effect=ValueError("bad path")):
            code, _, err = run(["setup-models", "//server/share"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err), {"error": "bad path", "type": "ValueError"})

    def test_existing_commands_still_parse(self):
        with patch.object(cli, "inspect", return_value={"duration": 1.0}) as inspect:
            code, out, _ = run(["inspect", "C:/clip.mp4"])
        self.assertEqual((code, json.loads(out)), (0, {"duration": 1.0}))
        inspect.assert_called_once_with(source="C:/clip.mp4")
        for command in ("draft", "review", "approve", "render"):
            with self.subTest(command=command), redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    cli.main([command, "--help"])


if __name__ == "__main__":
    unittest.main()
