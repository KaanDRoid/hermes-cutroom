"""Model-facing Studio adapters; importing and registering never opens a profile.

Human approval of a final export is deliberately absent from this surface: it
stays in Cutroom Studio (Desktop) and the local REST API only.
"""

import json

TRANSCRIPT_PREVIEW_WORDS = 50

PROJECT_CHANGES = frozenset(
    {
        "settings",
        "brief",
        "voice",
        "excluded_word_ids",
        "gaze_exclusions",
        "selected_hook",
        "segments",
        "transcript",
        "name",
    }
)
JOB_OPERATIONS = frozenset(
    {
        "inspect",
        "transcribe",
        "silence",
        "vision",
        "segment",
        "storyboard",
        "preview",
        "final",
        "cover",
        "qa",
    }
)
# action -> (allowed fields, required fields)
PROJECT_ACTIONS = {
    "create": ({"source", "name"}, {"source"}),
    "list": (set(), set()),
    "get": ({"project_id"}, {"project_id"}),
    "update": (
        {"project_id", "changes", "revision"},
        {"project_id", "changes", "revision"},
    ),
    "review": ({"project_id"}, {"project_id"}),
}
JOB_ACTIONS = {
    "submit": ({"project_id", "operation", "options"}, {"project_id", "operation"}),
    "list": ({"project_id"}, set()),
    "get": ({"job_id"}, {"job_id"}),
    "cancel": ({"job_id"}, {"job_id"}),
}
LIST_FIELDS = ("id", "name", "revision", "status", "source")
APPROVAL_NOTICE = (
    "Human approval of the exact reviewed digest is required before final job "
    "submission and is checked again on completion. Approval stays in Cutroom "
    "Studio (Desktop) or the local REST API. This tool cannot approve, and "
    "you must never claim that anything was approved; ask the user to review "
    "and approve it in Cutroom Studio."
)


def get_studio():
    """Resolve the current profile only when a validated handler is invoked."""
    from .studio import get_studio as factory

    return factory()


def _arguments(args, actions):
    if not isinstance(args, dict):
        raise ValueError("Arguments must be an object")
    action = args.get("action")
    if not isinstance(action, str) or action not in actions:
        raise ValueError("Unsupported action; expected one of: " + ", ".join(actions))
    allowed, required = actions[action]
    unknown = set(args) - allowed - {"action"}
    if unknown:
        raise ValueError(
            f"Unsupported arguments for {action}: " + ", ".join(sorted(unknown))
        )
    missing = required - set(args)
    if missing:
        raise ValueError(
            f"Missing required arguments for {action}: " + ", ".join(sorted(missing))
        )
    for field in ("source", "name", "project_id", "job_id", "operation"):
        if field in args and (
            not isinstance(args[field], str) or not args[field].strip()
        ):
            raise ValueError(field + " must be a nonempty string")
    json.dumps(args, allow_nan=False)
    return action


def _response(function):
    try:
        return json.dumps({"ok": True, "result": function()}, allow_nan=False)
    except Exception as error:
        return json.dumps(
            {"ok": False, "error": str(error), "type": type(error).__name__},
            allow_nan=False,
        )


def _summarize(project):
    """Replace the full word list with a count and a short preview."""
    if not isinstance(project, dict):
        return project
    transcript = project.get("transcript")
    if not isinstance(transcript, dict) or not isinstance(
        transcript.get("words"), list
    ):
        return project
    words = transcript["words"]
    summary = dict(
        transcript,
        words=words[:TRANSCRIPT_PREVIEW_WORDS],
        word_count=len(words),
        words_truncated=len(words) > TRANSCRIPT_PREVIEW_WORDS,
    )
    return dict(project, transcript=summary)


def _compact(project):
    result = {key: project.get(key) for key in LIST_FIELDS}
    result["artifacts"] = sorted(project.get("artifacts") or {})
    return result


def project_handler(args, **kwargs):
    """Validate the action-specific contract before resolving Studio."""

    def perform():
        action = _arguments(args, PROJECT_ACTIONS)
        if action == "update":
            changes = args["changes"]
            if not isinstance(changes, dict) or not changes:
                raise ValueError("changes must be a nonempty object")
            unsupported = set(changes) - PROJECT_CHANGES
            if unsupported:
                raise ValueError(
                    "Unsupported project changes: " + ", ".join(sorted(unsupported))
                )
            revision = args["revision"]
            if (
                isinstance(revision, bool)
                or not isinstance(revision, int)
                or revision < 1
            ):
                raise ValueError("revision must be a positive integer")
        values = {key: value for key, value in args.items() if key != "action"}
        result = getattr(get_studio(), action)(**values)
        if action == "list":
            return [_compact(project) for project in result]
        if action in ("get", "create", "update"):
            return _summarize(result)
        if action == "review" and isinstance(result, dict) and "project" in result:
            return dict(result, project=_summarize(result.get("project")))
        return result

    return _response(perform)


def job_handler(args, **kwargs):
    """Validate the job contract before resolving Studio."""

    def perform():
        action = _arguments(args, JOB_ACTIONS)
        studio_call = None
        if action == "submit":
            if args["operation"] not in JOB_OPERATIONS:
                raise ValueError(
                    "Unsupported operation; expected one of: "
                    + ", ".join(sorted(JOB_OPERATIONS))
                )
            options = args.get("options")
            if "options" in args and not isinstance(options, dict):
                raise ValueError("options must be an object")
            studio_call = (
                "submit",
                {
                    "project_id": args["project_id"],
                    "action": args["operation"],
                    "options": options,
                },
            )
        elif action == "list":
            studio_call = ("jobs", {"project_id": args.get("project_id")})
        elif action == "get":
            studio_call = ("job", {"job_id": args["job_id"]})
        else:
            studio_call = ("cancel", {"job_id": args["job_id"]})
        method, values = studio_call
        return getattr(get_studio(), method)(**values)

    return _response(perform)


def _string(description):
    return {"type": "string", "minLength": 1, "description": description}


def definitions():
    """Return the Hermes tool definitions without touching Studio."""
    changes = {
        "type": "object",
        "additionalProperties": False,
        "minProperties": 1,
        "description": "Editable project fields only (update). Approval, "
        "artifacts, source, revision and status cannot be changed here.",
        "properties": {
            "settings": {"type": "object", "description": "Render/model settings"},
            "brief": {"type": "string", "description": "Editorial brief"},
            "voice": {"type": "string", "description": "Narrative voice"},
            "excluded_word_ids": {
                "type": "array",
                "description": "Transcript word ids to cut",
            },
            "gaze_exclusions": {
                "type": "array",
                "description": "Time ranges excluded for gaze",
            },
            "selected_hook": {"description": "Chosen opening hook"},
            "segments": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Kept time ranges [{start, end}] in seconds",
            },
            "transcript": {
                "type": ["object", "null"],
                "description": "Corrected transcript",
            },
            "name": {"type": "string", "description": "Project display name"},
        },
    }
    project = {
        "name": "cutroom_project",
        "description": (
            "Manage Cutroom Studio projects. Actions: create(source, name?) imports "
            "a local video; list() returns compact rows (id, name, revision, status, "
            "source, artifact kinds); get(project_id) returns the project with the "
            f"transcript summarized to word_count plus the first "
            f"{TRANSCRIPT_PREVIEW_WORDS} words to protect context; "
            "update(project_id, changes, revision) applies editable fields with "
            "optimistic revision checking; review(project_id) returns the exact "
            "plan digest and notice for the human. " + APPROVAL_NOTICE
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "get", "update", "review"],
                    "description": "Operation to perform",
                },
                "source": _string("Absolute local video path (create)"),
                "name": _string("Optional project name (create)"),
                "project_id": _string("Project id (get, update, review)"),
                "changes": changes,
                "revision": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Current project revision (update)",
                },
            },
        },
    }
    job = {
        "name": "cutroom_job",
        "description": (
            "Run and track background Cutroom Studio jobs. Actions: "
            "submit(project_id, operation, options?) queues inspect, transcribe, "
            "silence, vision, segment, storyboard, preview, final, cover or qa; "
            "list(project_id?), get(job_id), cancel(job_id). " + APPROVAL_NOTICE
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["submit", "list", "get", "cancel"],
                    "description": "Operation to perform",
                },
                "project_id": _string("Project id (submit, optional filter for list)"),
                "job_id": _string("Job id (get, cancel)"),
                "operation": {
                    "type": "string",
                    "enum": sorted(JOB_OPERATIONS),
                    "description": "Studio pipeline step to queue (submit)",
                },
                "options": {
                    "type": "object",
                    "description": "Operation-specific options (submit)",
                },
            },
        },
    }
    return [project, job]


HANDLERS = {"cutroom_project": project_handler, "cutroom_job": job_handler}
