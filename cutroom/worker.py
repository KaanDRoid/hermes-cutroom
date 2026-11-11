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
