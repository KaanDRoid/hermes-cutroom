"""Documented Hermes tools. Importing this module does not run media jobs."""

import json
import os
from pathlib import Path

from .paths import inside, plans_root
from .plan import build_plan
from .project import file_digest, load_approved, save_draft, write_review


def inspect(source):
    from .media import probe

    return probe(source)


def _local_text(value, name):
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty name or workspace path")
    # Refuse network paths before anything resolves (and so contacts) them.
    if value[:2] in {"\\\\", "//", "\\/", "/\\"}:
        raise PermissionError(
            f"{name} must be a local path inside the Cutroom workspace"
        )
    return value


def _project_dir(project_dir):
    """A new plan directory, always inside the Cutroom workspace."""
    project_dir = _local_text(project_dir, "project_dir")
    base = plans_root()
    target = Path(project_dir).expanduser()
    if not target.is_absolute():
        target = base / target
    target = inside(target, base)
    if target == base:
        raise PermissionError("Choose a new directory inside the Cutroom workspace")
    base.mkdir(parents=True, exist_ok=True)
    # Re-resolve after creating the base so a link planted meanwhile still fails.
    return inside(target, base)


def _workspace_plan(path):
    path = _local_text(path, "plan path")
    return inside(Path(path).expanduser().resolve(strict=True), plans_root())


def draft_plan(
    source, project_dir, noise_db=-35.0, min_duration=0.5, padding=0.12, guard=None
):
    """Core draft for the user-run CLI; agent tools use the confined ``draft``.

    ``guard`` re-validates ``project_dir`` right before anything is written,
    because silence analysis can take a while.
    """
    from .media import _local_path, detect_silences, probe

    source = _local_path(source)
    source_digest = file_digest(source)
    info = probe(source)
    silences = detect_silences(source, noise_db=noise_db, min_duration=min_duration)
    plan = build_plan(source, info, silences, padding)
    if guard is not None:
        project_dir = guard(project_dir)
    path = save_draft(plan, project_dir, expected_source_sha256=source_digest)
    return dict(
        write_review(path),
        silences=silences,
        requires_approval=True,
        warning="Silence-based cuts only. Listen around every cut before approving.",
    )


def draft(source, project_dir, noise_db=-35.0, min_duration=0.5, padding=0.12):
    return draft_plan(
        source,
        _project_dir(project_dir),
        noise_db,
        min_duration,
        padding,
        guard=_project_dir,
    )


def review(path):
    return write_review(_workspace_plan(path))


def render_approved(plan_path):
    return render_plan(_workspace_plan(plan_path))


def render_plan(plan_path):
    """Core render for the user-run CLI; agent tools use ``render_approved``."""
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


LEGACY_TOOLS_ENV = "CUTROOM_LEGACY_TOOLS"
LEGACY_TOOLS_SETTING = "legacy_tools"
SKILL_NAME = "edit-video"
SKILL_DESCRIPTION = (
    "Edit a local video from chat: import, transcribe, cut, caption, frame, "
    "preview, check and hand over for approval in Cutroom Studio."
)
_TRUE = {"1", "true", "yes", "on"}


def _skill_path():
    return Path(__file__).resolve().parents[1] / "skills" / SKILL_NAME / "SKILL.md"


def legacy_tools_enabled(ctx=None):
    """The older plan tools are opt-in: env CUTROOM_LEGACY_TOOLS or plugin setting."""
    if os.environ.get(LEGACY_TOOLS_ENV, "").strip().lower() in _TRUE:
        return True
    reader = getattr(ctx, "get_config", None)
    if not callable(reader):
        return False
    try:
        value = reader(LEGACY_TOOLS_SETTING, False)
    except Exception:
        return False
    if isinstance(value, str):
        return value.strip().lower() in _TRUE
    return value is True


def _register_skill(ctx):
    register_skill = getattr(ctx, "register_skill", None)
    if not callable(register_skill):
        return  # Older hosts have no plugin skills; the tools still work.
    path = _skill_path()
    if path.is_file():
        register_skill(SKILL_NAME, path, description=SKILL_DESCRIPTION)


LEGACY = frozenset({"cutroom_draft", "cutroom_review", "cutroom_render"})


def register(ctx):
    _register_skill(ctx)
    legacy = legacy_tools_enabled(ctx)
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
            "Analyze local audio silence and save a non-destructive plan plus HTML review inside the Cutroom workspace. Does not render. This does not identify words, fillers or gaze.",
            draft,
            {
                "source": {"type": "string"},
                "project_dir": {
                    "type": "string",
                    "description": "New project name (or path) inside the Cutroom "
                    "workspace; must not exist. Paths outside it are refused.",
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
            review,
            {
                "path": {
                    "type": "string",
                    "description": "plan.json path inside the Cutroom workspace",
                }
            },
            ["path"],
        ),
        (
            "cutroom_render",
            "Render an already approved exact plan to project/render.mp4. Rejects changed source/plan and existing output. Never create approval receipts on the user behalf.",
            render_approved,
            {
                "plan_path": {
                    "type": "string",
                    "description": "Approved plan.json inside the Cutroom workspace",
                }
            },
            ["plan_path"],
        ),
    ]
    for name, description, function, properties, required in definitions:
        if name in LEGACY and not legacy:
            continue
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
    from .studio_tools import HANDLERS
    from .studio_tools import definitions as studio_definitions

    for schema in studio_definitions():
        ctx.register_tool(
            name=schema["name"],
            toolset="cutroom",
            schema=schema,
            handler=HANDLERS[schema["name"]],
            description=schema["description"],
        )
