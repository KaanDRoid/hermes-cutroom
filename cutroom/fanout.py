"""Feed each cut only its own part of a stream.

When every cut reads the input stream directly, FFmpeg copies the whole stream
to every cut's branch, and the render time grows with the square of the number
of cuts (557 cuts of a 17-minute talk did not finish within 15 minutes). Here
the stream goes through a tree of coarse trims instead: each node passes at
most ``BRANCH`` parts on, each part covers only its cuts plus a margin, and the
cuts keep their own exact trims. Time trims keep source timestamps, so cuts
by time are unchanged; cuts by frame number count frames from the start of
their part, so the caller subtracts the returned offset.
"""

BRANCH = 8
TIME_MARGIN_S = 0.5
VIDEO_MARGIN_FRAMES = 15


def cut_inputs(stream, spans, *, video, prefix, by_frame=None, branch=BRANCH):
    """Return graph lines and, per cut, the label to read and the frame offset.

    ``spans`` are ``(low, high)`` per cut: frame numbers (``high`` exclusive)
    when ``by_frame`` (the default for video), else seconds. Up to ``branch``
    cuts read ``stream`` directly as before.
    """
    by_frame = video if by_frame is None else by_frame
    if len(spans) <= branch:
        return [], [(stream, 0)] * len(spans)
    split, trim = ("split", "trim") if video else ("asplit", "atrim")
    lines, inputs, counter = [], [None] * len(spans), [0]

    def label(kind):
        counter[0] += 1
        return f"[{prefix}{kind}{counter[0]}]"

    def node(source, items, offset):
        if len(items) <= branch:
            outs = [label("c") for _ in items]
            lines.append(f"{source}{split}={len(items)}{''.join(outs)}")
            for out, index in zip(outs, items):
                inputs[index] = (out, offset)
            return
        size = -(-len(items) // branch)
        groups = [items[k : k + size] for k in range(0, len(items), size)]
        outs = [label("t") for _ in groups]
        lines.append(f"{source}{split}={len(groups)}{''.join(outs)}")
        for out, group in zip(outs, groups):
            low = min(spans[i][0] for i in group)
            high = max(spans[i][1] for i in group)
            part = label("p")
            if by_frame:
                start = max(offset, low - VIDEO_MARGIN_FRAMES)
                end = high + VIDEO_MARGIN_FRAMES
                lines.append(
                    f"{out}{trim}=start_frame={start - offset}:"
                    f"end_frame={end - offset}{part}"
                )
            else:
                start = max(0.0, low - TIME_MARGIN_S)
                lines.append(
                    f"{out}{trim}=start={start:.6f}:"
                    f"end={high + TIME_MARGIN_S:.6f}{part}"
                )
            node(part, group, start if by_frame else 0)

    node(stream, list(range(len(spans))), 0)
    return lines, inputs
