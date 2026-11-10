"""Non-destructive silence edit plans in source time."""

import math


def _number(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError("Timeline values must be finite numbers")
    return float(value)


def validate_plan(plan):
    if plan.get("version") != 1 or not isinstance(plan.get("source"), str):
        raise ValueError("Unsupported plan or missing source")
    duration = _number(plan.get("source_duration"))
    segments = plan.get("segments")
    if duration <= 0 or not isinstance(segments, list) or not 1 <= len(segments) <= 500:
        raise ValueError("Plan must contain between 1 and 500 segments")
    previous = 0.0
    for segment in segments:
        start, end = _number(segment.get("start")), _number(segment.get("end"))
        if start < previous or end <= start or end > duration:
            raise ValueError(
                "Segments must be ordered, non-overlapping and inside the source"
            )
        previous = end
    return plan


def build_plan(source, info, silences, padding=0.12):
    duration = _number(info["duration"])
    padding = _number(padding)
    if duration <= 0 or padding < 0:
        raise ValueError("Duration must be positive and padding non-negative")
    intervals = []
    for silence in silences:
        start, end = _number(silence["start"]), _number(silence["end"])
        if not 0 <= start <= end <= duration:
            raise ValueError("Silence outside the source")
        intervals.append((start + padding, end - padding))
    cursor = 0.0
    segments = []
    for start, end in sorted(intervals):
        start, end = max(cursor, start), min(duration, end)
        if end <= start:
            continue
        if start > cursor:
            segments.append({"start": cursor, "end": start})
        cursor = end
    if cursor < duration:
        segments.append({"start": cursor, "end": duration})
    plan = {
        "version": 1,
        "source": str(source),
        "source_duration": duration,
        "status": "draft",
        "segments": segments,
        "output_duration": sum(s["end"] - s["start"] for s in segments),
    }
    return validate_plan(plan)
