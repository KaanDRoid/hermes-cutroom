"""Allowlisted engine entry point; no dynamic Python expressions."""

import json
import sys
from pathlib import Path


def execute(operation, arguments):
    if operation == "inspect":
        from .media import probe

        return probe(**arguments)
    if operation == "silence":
        from .media import detect_silences, probe
        from .plan import build_plan

        options = dict(arguments)
        source = options.pop("source")
        padding = options.pop("padding", 0.12)
        silences = detect_silences(source, **options)
        return build_plan(source, probe(source), silences, padding=padding)
    if operation == "transcribe":
        from .speech import transcribe

        return transcribe(**arguments)
    if operation == "vision":
        from .reframe import face_samples, scene_cuts
        from .vision import analyze_faces

        result = analyze_faces(**arguments)
        return {
            **result,
            "face_samples": face_samples(result["frames"]),
            "scene_cuts": scene_cuts(arguments["source"]),
        }
    if operation == "segment":
        from .vision import segment_person

        return segment_person(**arguments)
    if operation in {"preview", "final"}:
        from .postproduction import export_video

        return export_video(**arguments)
    if operation == "cover":
        from .postproduction import make_cover

        return make_cover(**arguments)
    if operation == "qa":
        from .postproduction import quality_report

        return quality_report(**arguments)
    raise ValueError("Unsupported engine operation: " + operation)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    request, result = map(Path, argv)
    if request.stat().st_size > 32_000_000 or result.exists():
        raise ValueError("Invalid worker request or existing result")
    try:
        data = json.loads(request.read_text(encoding="utf-8"))
        envelope = {"ok": True, "result": execute(data["operation"], data["arguments"])}
        code = 0
    except Exception as error:
        envelope = {"ok": False, "error": str(error), "type": type(error).__name__}
        code = 1
    temporary = result.with_suffix(".tmp")
    temporary.write_text(json.dumps(envelope, allow_nan=False), encoding="utf-8")
    temporary.replace(result)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
