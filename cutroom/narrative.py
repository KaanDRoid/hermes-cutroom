"""Deterministic, extractive story drafts grounded in timed source words."""

import copy

from .speech import _validate_segments, validate_transcript


def _source_spans(transcript, segments=None):
    validate_transcript(transcript)
    offsets, cursor = [], 0
    for word in transcript["words"]:
        start = transcript["text"].find(word["text"], cursor)
        if start < 0:
            raise ValueError("Transcript text must contain each timed word in order")
        cursor = start + len(word["text"])
        offsets.append((start, cursor))
    spans, first, active_segment = [], None, None
    for index, word in enumerate(transcript["words"]):
        segment_index = (
            next(
                (
                    i
                    for i, segment in enumerate(segments)
                    if segment["start"] <= word["start"] < word["end"] <= segment["end"]
                ),
                None,
            )
            if segments is not None
            else 0
        )
        if segment_index != active_segment and first is not None:
            spans.append((first, index))
            first = None
        active_segment = segment_index
        if segment_index is None:
            continue
        if first is None:
            first = index
        if (
            word["text"].rstrip().endswith((".", "?", "!", "。", "！", "？"))
            or index - first + 1 >= 12
        ):
            spans.append((first, index + 1))
            first = None
    if first is not None:
        spans.append((first, len(offsets)))
    return offsets, spans


def _excerpt(transcript, offsets, first, stop):
    words = transcript["words"][first:stop]
    char_start, char_end = offsets[first][0], offsets[stop - 1][1]
    return dict(
        text=transcript["text"][char_start:char_end],
        word_ids=[word["id"] for word in words],
        start=words[0]["start"],
        end=max(word["end"] for word in words),
        source_span=dict(char_start=char_start, char_end=char_end),
    )


def story_options(transcript, brief="", voice="neutral"):
    """Return opening/middle/closing excerpts, not model reasoning or quality scores."""
    if not isinstance(brief, str) or not isinstance(voice, str) or not voice.strip():
        raise ValueError("Brief and voice must be strings; voice must be non-empty")
    validate_transcript(transcript)
    words = transcript["words"]
    selected = transcript.get("segments")
    if selected is None:
        selected = (
            [dict(start=words[0]["start"], end=max(w["end"] for w in words))]
            if words and max(w["end"] for w in words) > words[0]["start"]
            else []
        )
    segments = copy.deepcopy(_validate_segments(selected))
    offsets, spans = _source_spans(transcript, segments)
    hooks = []
    if spans:
        seen = {}
        for index, position in enumerate((0, len(spans) // 2, len(spans) - 1), 1):
            first, stop = spans[position]
            hooks.append(
                dict(
                    id=index,
                    duplicate_of=seen.get(position),
                    status="draft",
                    **_excerpt(transcript, offsets, first, stop),
                )
            )
            seen.setdefault(position, index)
    else:
        hooks = [
            dict(
                id=index,
                text="",
                word_ids=[],
                start=None,
                end=None,
                source_span=None,
                duplicate_of=None,
                status="insufficient_source",
            )
            for index in range(1, 4)
        ]
    storyboard, offset = [], 0.0
    for index, segment in enumerate(segments):
        indices = [
            i
            for i, word in enumerate(words)
            if word["start"] < segment["end"] and word["end"] > segment["start"]
        ]
        runs = []
        for word_index in indices:
            if runs and runs[-1][1] == word_index:
                runs[-1] = (runs[-1][0], word_index + 1)
            else:
                runs.append((word_index, word_index + 1))
        excerpts = [_excerpt(transcript, offsets, first, stop) for first, stop in runs]
        length = segment["end"] - segment["start"]
        storyboard.append(
            dict(
                index=index,
                source_start=segment["start"],
                source_end=segment["end"],
                output_start=offset,
                output_end=offset + length,
                text=" … ".join(excerpt["text"] for excerpt in excerpts),
                word_ids=[words[i]["id"] for i in indices],
                source_spans=excerpts,
                source_span=excerpts[0]["source_span"] if len(excerpts) == 1 else None,
                visual="source_footage",
                status="draft" if indices else "no_timed_words",
            )
        )
        offset += length
    return dict(
        method="deterministic_extractive",
        status="draft" if spans else "insufficient_source",
        brief=brief,
        voice=voice,
        hooks=hooks,
        segments=segments,
        storyboard=storyboard,
    )


def publication_caption(transcript, brief="", voice="neutral"):
    """Return an editable source-quote draft; brief/voice are review metadata only."""
    story = story_options(transcript, brief=brief, voice=voice)
    offsets, spans = _source_spans(transcript, story["segments"])
    excerpts = [_excerpt(transcript, offsets, first, stop) for first, stop in spans]
    return dict(
        text="\n\n".join(excerpt["text"] for excerpt in excerpts),
        source_spans=excerpts,
        brief=brief,
        voice=voice,
        editable=True,
        requires_review=True,
        status="draft" if excerpts else "insufficient_source",
        method="deterministic_extractive",
    )
