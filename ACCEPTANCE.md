# Full workflow acceptance

A capability is complete only after its input, implementation, output and observed checks are linked. External-account integrations remain unverified until exercised with a connected account and explicit consent; adapters alone do not establish completion.

| ID | Capability | Acceptance |
|---|---|---|
| A01 | Local import and projects | Immutable source fingerprint, resumable project, no overwrite |
| A02 | Word transcription | Real local Whisper inference, timed words, explicit model setup, no-audio handling |
| A03 | Text and filler edits | Word selection maps to source ranges; filler suggestions require review |
| A04 | Face, gaze and mouth | Real landmark inference, frame/time scores, confidence limitations, no-face handling |
| A05 | Person background removal | Real segmentation mask and behind-subject composite, no-person handling |
| A06 | Hooks and script voice | Three editable hook/storyboard options derived from supplied transcript/brief; never invented factual claims |
| A07 | Brand persistence | Validated fonts/colors/safe areas/templates and saved corrections |
| A08 | Media references | Explicit download consent, safe URL/redirect checks, attribution records |
| A09 | Graphics and subtitles | Real timed captions and title/graphic layers, local render |
| A10 | Real screen recording | Explicit OBS start/stop adapter and actual recording path verification |
| A11 | Preview and final | Distinct approved 1080 preview and 4K final, no silent upscaling claim |
| A12 | Cover and caption | Actual image output plus editable publication caption |
| A13 | Pre/post render QA | Dimensions/duration/audio/safe area/text and every-frame anomaly scan with honest heuristic limits |
| A14 | Human checkpoints | Reviewed exact revision before final render/download/publish; no model-exposed approval shortcut |
| A15 | Desktop studio | Native SDK-only UI for import, progress, transcript edits, preview, explicit confirmation and export |
| A16 | Storage and calendar | Optional explicit-consent rclone upload and calendar/ICS outputs; live services separately verified |
| A17 | Recovery and portability | Job errors/cancellation, dependency diagnostics, tests, package and plugin validation |
| A18 | Demo and submission | Truthful under-90-second demo; catalog PR/form/publication require separate authorization |

### Creator formats (0.2.0)

Work packages and design decisions are in [docs/creator-formats.md](docs/creator-formats.md).

| ID | Capability | Acceptance |
|---|---|---|
| A19 | Platform profiles | Reels, Shorts, TikTok and YouTube profiles with sourced, dated specifications; per-profile QA for frame, frame rate, length limit, loudness and safe-zone placement |
| A20 | Derived projects | Sibling projects per platform or source range that copy edits but keep their own settings, digest and human approval |
| A21 | Animated captions | Word-timed highlight, pop and one-word styles inside the safe zone; sidecar subtitles for long-form |
| A22 | Reframing | Blurred fill, centre crop and smoothed face-tracked crop with manual keyframes; no silent upscaling |
| A23 | Pacing | Punch-ins on jump cuts, maximum pause and simple transitions |
| A24 | Music and voice | Person-supplied music with ducking under speech; voice clean-up presets; platform loudness |
| A25 | Clip finder | Sentence-bounded candidates with explained scores; picked clips become derived projects |
| A26 | Long-form YouTube | Valid chapters, a 16:9 thumbnail (YouTube recommends 3840×2160, at least 640 px wide), SRT, end-screen space |
| A27 | Delivery packages | Per-platform folder with video, cover and text within platform limits plus a checksum manifest; nothing is posted |
| A28 | Creator acceptance | Native Desktop run per platform on consented real footage, clean install and FFmpeg 7.1 check |

Status (F0 and F1, 2026-11-12):

- **A19 verified by automated tests on synthetic media.** Four sourced, dated profiles; a landscape test pattern renders at exactly 1080×1920 for Shorts and passes frame, length, loudness and safe-zone checks; one source produces four derived projects whose preview QA passes their own platform checks; a 185-second Shorts edit fails QA and a 190-second Shorts final is refused. Evidence: `tests/test_platforms.py`, `tests/test_studio_platforms.py`, [creator formats F0](docs/creator-formats.md#f0--platform-profiles-and-derived-projects). Native Desktop runs per platform belong to A28.
- **A20 pending.** Platform siblings with their own settings, digest and approval are implemented and tested; siblings limited to a source range arrive with F5.
- **A21 verified by automated tests and a real-footage preview.** Highlight, pop and one-word styles render from per-word ASS events inside the safe zone; every word starts and ends within one frame of its timestamp in the script of the render being checked, checked against decoded frame times and against decoded pixels at 23.976, 25, 29.97, 30 and 60 fps; captions meet the BBC reading size; long-form YouTube defaults to SRT/VTT sidecars. Evidence: `tests/test_captions.py`, `tests/test_studio_captions.py`, a 1080×1920 Reels preview of real speech in [creator formats F1](docs/creator-formats.md#f1--animated-word-captions). Native Desktop runs belong to A28.
- **A22 implemented, review fixes applied.** Blur fill, centre crop and face-tracked crop with smoothing, shot-aware cut resets and keyframes; crops are planned in square display pixels; crop upscaling is a QA warning with or without a platform profile, and low face coverage is a render and QA warning. Real footage: a still speaker (Sandra, 415 of 415 fresh face frames inside the safe area by plan, 83 of 85 by output detection) and a moving face (1280 px inset sweeping at 213 px/s: 304 of 304 by plan, 328 of 329 by detection on every output frame). Evidence: [creator formats F2](docs/creator-formats.md#f2--reframing). Native Desktop runs belong to A28.
- A23 pending.
- **A24 verified by automated tests and a real-footage preview.** Person-supplied music is hashed into the digest, ducked under detected speech by at least the requested depth (QA checks the rendered music stem; tests and the evidence script measure the delivered file), faded, and looped from its start offset or ended with a fade where shorter music ends. Voice clean-up keeps sample-exact sync. The mix meets −14 LUFS ±0.5 LU and the delivered file stays at or under −1 dBTP after encoding, limiting peaks when linear gain would not fit; QA warns above −1 dBTP. Audio paths must be absolute. Evidence: `tests/test_audio_mix.py`, `tests/test_audio_review_fixes.py`, `tests/test_av_sync.py`, and a Reels preview of real speech in [creator formats F4](docs/creator-formats.md#f4--music-cut-sounds-and-voice-clean-up). Native Desktop runs belong to A28.
- A25–A28 pending.

## Consented acceptance source

`raw_vids/1416529-uhd_3840_2160_30fps.mp4`: 3840×2160, 12.23 s at 30 fps, no audio stream, aerial coastline without people (Pexels, see `docs/media-sources.md`). This source cannot validate speech recognition, human gaze or person segmentation.

`raw_vids/4439224-uhd_2160_3840_25fps.mp4`: 2160×3840, 10.56 s, 264 frames at 25 fps, visible woman, no audio stream. Used for face/mouth estimates and person-layer compositing, not speech recognition. A separate attributed reference speech file is described in `docs/media-sources.md`.

Keep raw media, model caches and generated artifacts out of version control.
