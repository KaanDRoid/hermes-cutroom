"""Documented Hermes tools. Importing this module does not run media jobs."""

import json

from .plan import build_plan
from .project import file_digest, load_approved, save_draft, write_review


def inspect(source):
    from .media import probe

    return probe(source)


def draft(source, project_dir, noise_db=-35.0, min_duration=0.5, padding=0.12):
    from .media import _local_path, detect_silences, probe

    source = _local_path(source)
    source_digest = file_digest(source)
    info = probe(source)
    silences = detect_silences(source, noise_db=noise_db, min_duration=min_duration)
    plan = build_plan(source, info, silences, padding)
    path = save_draft(plan, project_dir, expected_source_sha256=source_digest)
    return dict(
        write_review(path),
        silences=silences,
        requires_approval=True,
        warning="Silence-based cuts only. Listen around every cut before approving.",
    )


def render_approved(plan_path):
    from pathlib import Path

    from .media import render

    plan_path = Path(plan_path).expanduser().resolve(strict=True)
    plan = load_approved(plan_path)
    output = plan_path.parent / "render.mp4"
    result = render(plan["source"], plan["segments"], output)
    return result


def _handler(function, keys):
    def handle(args, **kwargs):
        try:
            if not isinstance(args, dict):
                raise ValueError("Arguments must be an object")
            values = {key: args[key] for key in keys if key in args}
            return json.dumps(
                {"ok": True, "result": function(**values)}, allow_nan=False
            )
        except Exception as error:
            return json.dumps(
                {"ok": False, "error": str(error), "type": type(error).__name__}
            )

    return handle


def register(ctx):
    definitions = [
        (
            "cutroom_inspect",
            "Inspect a local video using ffprobe; no upload or modification.",
            inspect,
            {"source": {"type": "string", "description": "Absolute local video path"}},
            ["source"],
        ),
        (
            "cutroom_draft",
            "Analyze local audio silence and save a non-destructive plan plus HTML review. Does not render. This does not identify words, fillers or gaze.",
            draft,
            {
                "source": {"type": "string"},
                "project_dir": {
                    "type": "string",
                    "description": "New local project directory; must not exist",
                },
                "noise_db": {"type": "number", "default": -35},
                "min_duration": {"type": "number", "default": 0.5, "minimum": 0.05},
                "padding": {"type": "number", "default": 0.12, "minimum": 0},
            },
            ["source", "project_dir"],
        ),
        (
            "cutroom_review",
            "Regenerate review HTML and digest after manual plan edits. Show the review to the user; never approve on their behalf.",
            write_review,
            {"path": {"type": "string", "description": "Local plan.json path"}},
            ["path"],
        ),
        (
            "cutroom_render",
            "Render an already approved exact plan to project/render.mp4. Rejects changed source/plan and existing output. Never create approval receipts on the user behalf.",
            render_approved,
            {"plan_path": {"type": "string"}},
            ["plan_path"],
        ),
    ]
    for name, description, function, properties, required in definitions:
        schema = {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        }
        ctx.register_tool(
            name=name,
            toolset="cutroom",
            schema=schema,
            handler=_handler(function, properties),
            description=description,
        )
