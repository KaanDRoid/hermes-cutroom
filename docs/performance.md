# Performance

Measured on 2026-11-15 on a Windows 11 laptop (AMD Ryzen 7 260, 32 GB RAM, RTX 5060
Laptop GPU unused, FFmpeg 9.0.2, CPU only). Scripts: `artifacts/perf/` in the
development worktree; they are not shipped.

## A long talk with hundreds of cuts

Source: a 17.7-minute TEDx talk, 1920×1080 VP8 at 29.97 fps. Every seventh
word and every filler word removed: 443 words, 557 kept segments, 12.8 minutes
kept.

| Step | Time | Peak memory |
|---|---|---|
| Transcribe (whisper small, CPU int8) | 3 min 5 s (2,561 words) | 1.15 GB |
| Save the edit (443 removed words) | 1.6–2.8 s | |
| Review digest | 0.2–0.3 s | |
| Preview, 1920×1080 | 6 min 17 s | 0.6 GB worker, 0.5 GB FFmpeg |
| Final, 3840×2160 | 16 min 31 s | 0.6 GB worker, 0.4 GB FFmpeg |

Both renders: 23,008 frames, no gap longer than one frame, no repeated frame,
audio and video both 767.7 s, 0.01 s from the kept length.

Before 0.2.0 every cut read the whole input stream, so render time grew with
the square of the number of cuts; this talk's loudness pass did not finish in
15 minutes. Cuts now read only their part (`cutroom/fanout.py`); the output is
sample- and frame-identical to direct reads (tested). Audio cut graph alone:

| Cuts | 25 | 50 | 100 | 557 |
|---|---|---|---|---|
| Every cut reads the whole stream | 0.9 s | 2.4 s | 15.6 s | over 15 min |
| Each cut reads its part | 0.2 s | 0.5 s | 0.9 s | 20 s |

## Desktop editor with a long transcript

The Edit step with the same 2,561-word transcript (443 removed), rendered by
React 19 in headless Edge. Hermes Desktop's own components were plain HTML
stand-ins, so this measures Cutroom's rendering, not the native window.

| Action | This laptop | CPU slowed 4× |
|---|---|---|
| First render | 0.1 s | 0.6 s |
| Click a word | 16 ms | 30 ms |
| Remove a word | 17 ms (p95 26 ms) | 79 ms (p95 122 ms) |
| Playback update (about 4 per second) | 17 ms | 17 ms (p95 120 ms) |
| Scroll the transcript | 17 ms per frame | 19 ms per frame |

At normal speed every action fits in one 60 Hz frame. On a 4× slower CPU a
removal still answers within about 0.1 s; an occasional playback update can
take 0.12 s.
