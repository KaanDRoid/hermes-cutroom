"""Local command-line review and rendering workflow."""

import argparse
import json
import sys

from .hermes_plugin import draft_plan, inspect, render_plan
from .project import approve_plan, write_review


def _doctor(models_dir=None):
    from . import setup

    return setup.doctor(models_dir=models_dir)


def _setup_models(directory, models, confirm_downloads):
    from . import setup

    return setup.setup_models(
        directory, models=models, confirm_downloads=confirm_downloads
    )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cutroom", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("inspect", help="Read local media metadata")
    scan.add_argument("source")
    create = commands.add_parser("draft", help="Suggest silence cuts without rendering")
    create.add_argument("source")
    create.add_argument("project_dir")
    create.add_argument("--noise-db", type=float, default=-35)
    create.add_argument("--min-duration", type=float, default=0.5)
    create.add_argument("--padding", type=float, default=0.12)
    review = commands.add_parser("review", help="Regenerate HTML and exact-plan digest")
    review.add_argument("path")
    approve = commands.add_parser(
        "approve", help="Confirm a reviewed plan digest locally"
    )
    approve.add_argument("path")
    approve.add_argument("--digest", required=True)
    render = commands.add_parser(
        "render", help="Render only a previously approved plan"
    )
    render.add_argument("plan_path")
    check = commands.add_parser(
        "doctor", help="Report local tools, runtime, packages and models"
    )
    check.add_argument("--models-dir", default=None)
    models = commands.add_parser(
        "setup-models", help="Plan or explicitly acquire pinned model files"
    )
    models.add_argument("directory")
    models.add_argument("--models", default="face,person,speech")
    models.add_argument("--confirm-downloads", action="store_true")
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    functions = {
        "doctor": _doctor,
        "setup-models": _setup_models,
        "inspect": inspect,
        "draft": draft_plan,
        "review": write_review,
        "approve": approve_plan,
        "render": render_plan,
    }
    try:
        result = functions[command](**args)
        print(json.dumps(result, indent=2, allow_nan=False))
        return (
            1 if command == "setup-models" and result.get("status") == "failed" else 0
        )
    except Exception as error:
        print(
            json.dumps({"error": str(error), "type": type(error).__name__}),
            file=sys.stderr,
        )
        return 1
