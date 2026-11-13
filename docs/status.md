# Implementation status

## November 13 — F3 pacing (branch `feat/f3-pacing`)

- Added `settings.pacing`: alternating punch-ins on edit cuts, centred on the face and kept under a total enlargement limit (default 2×, zooms are reduced and reported rather than exceeding it); an optional eased push-in on long ranges; a maximum pause between kept words that rebuilds the segments; and crossfade or dip transitions built from handles so program length, captions and sync do not change. QA adds `pacing_upscale`, `pacing_face`, `pacing_transitions` and `pacing_max_pause`; Desktop gets a Pacing group in Style; the chat skill suggests pacing for talking heads and asks first. Details: [creator formats F3](creator-formats.md#f3--pacing).
- Fixed on the way: QA's `captions` check failed a caption that ended with the program when frame alignment made the video up to half a frame shorter than the edit.
- On real speech (Sandra clip, Reels preview with face tracking, punch-ins, 0.5 s pause limit and crossfades): longest pause 0.86 s → 0.50 s, zoom 1.12× for a total of 1.99×, the redetected face 1.125× taller in zoomed ranges and inside the safe area in every checked frame, audio and picture offsets 0 against a plain render, all pacing checks pass.
- Local gates: **456 Python tests OK** (14 skipped without local models and media), **49/49 Desktop tests**, Ruff check and format clean. Logs: `artifacts/f3/red.log`, `artifacts/f3/green.log`.
- Not yet done: push-in on real footage, and a native Desktop check of the new controls.

## November 13 — chat integration (branch `feat/chat-integration`)

- Bundled the `cutroom:edit-video` skill (`skills/edit-video/SKILL.md`): import, transcribe with progress, propose and apply cuts, platform, captions, framing and music, preview and QA, `MEDIA:` lines, plain QA wording (`warning` means ready with notes), approval only by the person in Cutroom Studio, final, derived versions and platform limits. Older hosts without plugin skills still load the tools.
- Completed `preview`, `final` and `cover` jobs from `cutroom_job` now carry a bounded `media` summary (path, kind, project, platform, duration, size, QA status from check statuses, approval) and a `display_hint`; `cutroom_project get` summarises the current preview and final. Details: [media summaries](studio-jobs.md#media-summaries-in-tool-results).
- Chat now gets `cutroom_inspect`, `cutroom_project` and `cutroom_job` by default. The older plan tools (`cutroom_draft`, `cutroom_review`, `cutroom_render`) stay in the CLI and are offered in chat only with the plugin setting `legacy_tools: true` or `CUTROOM_LEGACY_TOOLS=1`. `plugin.yaml` declares the default set and the setting.
- The `cutroom_project` and `cutroom_job` descriptions now state the step order and that only a person approves, in Cutroom Studio.
- Local gates without inherited `PYTHONPATH`: **398 Python tests OK** (14 skipped without local models and media), **27/27 Desktop tests**, Ruff check and format clean, `hermes plugins validate` passed (declared tools match registrations). Logs: `artifacts/chat/red.log`, `artifacts/chat/green.log`, `artifacts/chat/validate.log`.
- Not yet done: a native Desktop check of the card with a live chat session.

## November 12 — F1 animated captions (branch `feat/f1-animated-captions`)

- Added `caption_style` (`classic`, `highlight`, `pop`, `one_word`), `caption_highlight_color` and `caption_word_y`, with per-word ASS events timed in whole frames and a glyph-measured two-line layout inside the safe zone at no less than the BBC reading size. Studio publishes the burned script as the `captions_ass` artifact, QA adds `caption_timing` and `caption_bounds`, Desktop gets style controls, and YouTube delivery uses SRT/VTT sidecars first. Details: [creator formats F1](creator-formats.md#f1--animated-word-captions).
- A second review found words one frame late at 25, 30 and 60 fps, QA checking a final against a later preview's script, and lost same-frame words. All are fixed; a decoded-pixel probe finds 0 mismatches at 23.976, 25, 29.97, 30 and 60 fps and on variable-rate video.
- On real speech (Sandra clip, 1080×1920 Reels preview, 24 words) every word starts within one frame and stays inside the safe zone.
- Local gates: **307 Python tests OK** (14 skipped without local models and media), **24/24 Desktop tests**, Ruff clean.
- Not yet done: a native Desktop check of the caption controls, and reframing (F2) so landscape sources fill vertical frames.

## November 12 — F4 music, cut sounds and voice clean-up (branch `feat/f4-music-voice`)

- Added optional local music (ducking, fades, loop, offset, source note), a cut sound and voice clean-up presets. Files are hashed into the digest. When linear loudness gain would exceed the true-peak limit, Cutroom limits peaks first and labels the method honestly; every normalised export is measured after encoding and re-limited if it is over −1 dBTP. QA compares the render-stage ducking measurement with the request. Desktop gets audio controls. Details: [creator formats F4](creator-formats.md#f4--music-cut-sounds-and-voice-clean-up).
- Fixed in every constant-frame-rate export: audio ran half a frame plus the video start offset behind the picture, drifted about 0.4 ms per cut on millisecond-timestamped sources, and could end before the last frame. A flash/click test now holds sync within 0.5 ms across twelve cuts.
- On real speech (Sandra clip, 24 s Reels preview), the mix measured −14.1 LUFS and −1.3 dBTP, 15.75 dB of ducking measured on the delivered file by the evidence script (QA reports the render-stage stem figure, 15.95 dB), and sync within one sample. Re-run after the review fixes with the same figures (`artifacts/f4/evidence-fix/`).
- Review fixes on the same branch: a piecewise ducking envelope bounded by the render timeout (30 min with 750 speech runs in 0.14 s; the review measured about 4.5 s of CPU per program second at 300 runs), loops that repeat the segment from `start_offset`, short unlooped music that fades out where it ends, deliveries kept at or under −1 dBTP after encoding with QA warning above it, the `music` check labelled as render-stage evidence, and relative audio paths refused. Details: [creator formats F4, review fixes](creator-formats.md#review-fixes-1).
- Local gates: **297 Python tests OK** (14 skipped without local models and media), **22/22 Desktop tests**, Ruff check and format clean. Before the review fixes the suite had 285 tests.

## November 12 — F2 reframing (branch `feat/f2-reframing`)

- Added `blur_fill`, `center_crop` and `face_track` framing with smoothed, speed- and acceleration-limited crop paths, resets on edit and scene cuts, and manual keyframes in program time (`cutroom/reframe.py`).
- QA checks planned frames, smoothness, crop upscaling (`platform_upscale` on platform renders, `framing_upscale` otherwise), face coverage and the face inside the safe area, counting only frames with a fresh face sample.
- Review fixes on the same branch: resets use only samples of the new shot (look-ahead at scene cuts and edit starts), the tracker runs before and after pins with blended ramps, pinned pans cross cuts, crops are planned in square display pixels with even sizes, low face coverage warns, shortened edits drop late pins with a note, the expression limit is explained, and trim edges and frame planning share FFmpeg's filter timeline (a video start of 1.3 s no longer shifts the first segment). Details: [creator formats, F2 review fixes](creator-formats.md#review-fixes-1).
- On the Sandra clip (a still speaker) reframed for Reels, 415 of 415 fresh face frames are inside the safe area by plan and 83 of 85 by detection on the output. With the clip at 1280 px sliding across a 1920 px canvas, 304 of 304 by plan and 328 of 329 by detection on every output frame; at 960 px Vision found no face and the render and QA warned.
- Local gates: **317 Python tests OK** (14 skipped without local models and media), **21/21 Desktop tests**, Ruff clean. Logs: `artifacts/f2/fix/red.log`, `artifacts/f2/fix/green.log`.

## November 12 — F0 platform profiles (merged, pull request #12)

- Added sourced platform profiles (`cutroom/platforms.py`) for Instagram Reels, YouTube Shorts, TikTok and YouTube, the `platform` / `final_resolution` settings, safe-zone text placement, per-platform QA checks, derived sibling projects (`Studio.derive`, the `derive` tool action, `POST /projects/{id}/derive`, `GET /platforms`) and Desktop controls: platform and resolution selectors, a safe-zone overlay on loaded renders and **Create version for …** buttons. Details and open items: [creator formats](creator-formats.md#f0--platform-profiles-and-derived-projects).
- Review fixes on the same branch: captions and lower thirds clamped into the safe zone for every brand-valid position, burned cues split into two-line events, NTSC frame rates accepted and variable-rate video checked by its slowest frame interval, a `platform_upscale` QA check with rotation-aware source sizes, corrected and current source links, cover data as stated by the platforms, frames marked as Cutroom's choice, `derive` resetting the final resolution (optional `final_resolution`) and stripping names, missing files reported as REST 422, and a Desktop overlay that follows the render's recorded platform after its metadata loads. Details: [creator formats, review fixes](creator-formats.md#review-fixes).
- Local gates without inherited `PYTHONPATH`, FFmpeg 9: **259 Python tests OK** — 14 skipped on a checkout without the local models and consented media, 5 skipped with them (`models/` and `raw_vids/` present); **20/20 Desktop tests**; Ruff check and format clean. The skip count depends on the environment. Before the review fixes the suite had 242 tests (14 or 5 skipped likewise). Logs: `artifacts/f0/red.log`, `artifacts/f0/green.log`, `artifacts/f0/fix-red.log`, `artifacts/f0/fix-green.log`, reviewer probes `artifacts/f0/fix-probes.log`.
- Not yet done: native Desktop acceptance of the new controls, source-range derivation (F5) and the YouTube thumbnail (F6).

## November 11 native Desktop acceptance — import through approved final

- Opened the packaged Hermes Desktop application in a separate user-data instance and exercised the `cutroom-test` backend profile. This is real Electron/React, not the SDK fake. The test profile uses a local source clone and the existing development virtual environment; this is **not a clean dependency-install acceptance**. Hermes inventories the Desktop half at app level, while project/job data remain in the test profile.
- Exercised local import, CPU Whisper transcription (22 timed words), silence detection, manual source-range edits, timed-word exclusion and preview rendering through the actual Studio controls. The 11-second reference/test-pattern input produced an 8.8-second H.264/AAC, 1920×1080 preview. Both source and preview decoded and advanced in the native player.
- Native **Download preview** opened the Windows save dialog. The saved file's SHA-256 matches the published preview (`0ee0bc487fa9a3708cf97421994730f2fcdbd005e62e08c826d1367d05bd4c20`). Cover and QA jobs completed through the UI. That first QA run reported **13 passes and one audio-loudness warning** (-17.4 LUFS versus a -16 LUFS target with 1 LU tolerance).
- Root cause: single-pass dynamic `loudnorm` undershoots short, intermittent speech. Exports now run an audio-only measurement pass over the exact cut and apply linear two-pass `loudnorm`, falling back to single-pass only when FFmpeg cannot report finite measurements (for example silence). A burst-audio regression requires ±0.5 LU; the same reference cut now measures -15.5 LUFS with a -1.9 dBFS peak.
- Real React reconciliation exposed duplicate sibling keys: corrections/settings both used the revision number; caption IDs could also collide with manual-range indices. Namespaced the keys, added rejecting behavior to the fake renderer and regression coverage. **15/15 Desktop tests pass.** In the real window, revisions 6→7→8→9 retained exactly one corrections panel, one settings panel and 22 caption inputs.
- Re-ran the Python suite without inherited `PYTHONPATH`: **190 tests, 187 passed, 3 skipped** after the loudness fix.
- A second native run on a natural 44-second CC BY-SA talking-head clip (VP9/Opus, 29.97 fps, 12 kept ranges after silence detection and a stammer-word exclusion) exposed QA duration failure: 34.80 s rendered versus 34.59 s requested. Each trimmed range rounded to whole frames independently, the concat filter padded audio to match, and the loudness pass extended the audio tail. Exports now align CFR ranges to the frame grid from the running total (at most half a frame off) and trim normalized audio to the program length. The same cut renders 34.601 s video and 34.592 s audio. Suite after this fix: **191 tests, 188 passed, 3 skipped**. The preceding unsanitized run failed seven vision imports and skipped 14 tests because it loaded Pillow from the Hermes host environment; that failed run is preserved separately and is not a successful product gate.
- **Human approval and final export accepted natively.** On the Sandra project (revision 5, digest `c4f549d5…`), the person checked the confirmation and pressed **Approve reviewed digest** in the real window; the persisted approval matched that digest and **Run final** unlocked only then. The final rendered 3840×2160 H.264/AAC, 34.601 s; QA on the final passed every check (-15.9 LUFS, -1.5 dBTP). It decoded and played in the native player, and the Windows save dialog wrote a file whose SHA-256 matches the publication receipt (`c3a002d5a216d4da159813bf1be5fc5f614d8fdf5bdc15e4058bf575c9b2d22f`).
- Two more native findings were fixed on the way: unchecked checkboxes were drawn with a background-colored border, hiding the approval box (now outlined with a theme token), and hidden windows paused job polling so finished renders stayed listed as queued (now polls in the background only while work is active). Desktop tests: **17/17**.
- The earlier reference-speech project was left unapproved at revision 9; a conversational confirmation was never substituted for the Desktop action.
- Local evidence: `artifacts/desktop-acceptance/receipt.json`, screenshots, native-saved preview and RED/GREEN/parent test logs. This checkpoint does not imply a catalog-pin update, clean installation or external-service acceptance. GitHub Actions were not used.

## November 11 integration checkpoint — supersedes the historical snapshot below

- Studio now routes every editing job: inspect, transcribe, silence, vision, segment, storyboard, preview, final, cover and qa. Results are revision-bound; stale renders are unlinked and final export requires current human approval.
- Six agent tools are implemented, including `cutroom_project` and `cutroom_job`; no agent approval action is exposed.
- `cutroom doctor` and consent-gated `cutroom setup-models` are implemented. Six local model-file hashes match their pins.
- The public-facade harness produced a 2160×3840 reference final, cover and 14 passing QA checks, but it granted its own approval. This is **automated render evidence only, not human-approval acceptance**. Independent review rejected this harness behavior; its correction must stop at preview/review and resume only after separate human approval.
- Real portrait face analysis covered 264 frames; segmentation/compositing completed. Desktop SDK contract tests: 13 passed. Ruff checks pass.
- Integrated Python suite after review fixes: **189 tests, 186 passed, 3 skipped**, no failures (84.302 seconds). Independent re-review **passed**: automatic harness approval removed, publication hashes verified, downstream artifacts validated and derivatives bound to exact upstream identity. An earlier integrated run failed two dashboard alias fixture assertions; its stale QA fixture was updated to supply a valid render identity without weakening production validation. Native Desktop-window acceptance, fresh installation and external-service acceptance remain open. No live profile installation, repository visibility change or submission is authorized by this checkpoint.
- The older FFmpeg 7.1 duration/cover defect has a CFR-specific correction with a CFR/VFR regression; direct retest on 7.1 remains open (local FFmpeg is 9).

## Historical snapshot

Snapshot: November 10, 2026. The boundaries and counts below describe the earlier checkpoint, not the current integration.

## Working public core

The four registered Hermes tools and existing CLI support metadata inspection, silence-based draft plans, HTML review, exact-plan/source confirmation and real no-overwrite rendering.

## Advanced modules present

| Area | Observed boundary |
|---|---|
| Speech | Local CPU Whisper inference on the separately attributed JFK reference; timed words, exclusions, fillers, remapping and SRT/VTT/ASS exports |
| Narrative | Three extractive hook alternatives, selected-range storyboard and editable source-quote publication drafts; not personalized generative writing |
| Vision | Real MediaPipe face/mouth/head-facing inference on all 264 portrait frames; review-only heuristics |
| Segmentation | Actual local person-mask compositing, including graphics behind the subject; not SAM |
| Postproduction | Real preview/final dimension presets, title/lower-third/caption effects, covers, audio normalization and frame/signal/timing/audio checks |
| Integrations | Consent/validation and adapter-contract coverage; actual local ICS and publication-package writes; live OBS/cloud/calendar operations not accepted |
| Studio | Project persistence, revisions, digest review and background inspection; queued cancellation and facade reopening tests |
| REST | Strict request models, profile-aware sibling loading, bounded authenticated media chunks and facade artifact routes |
| Desktop | SDK route/sidebar/palette, import and editing forms, transcript/filler/hook/brand/vision controls; action/player/approval/job panels are not complete |

## Integration blockers

- The Studio and engine dispatchers execute `inspect`, `silence` and `transcribe`. Matching-revision publication preserves cuts and revokes approval; transcript replacement clears old word IDs while preserving their time-range cuts, recomputes filler suggestions and invalidates dependent artifact links. Transcription's audio-result application is contract-tested, not accepted with a real model through Studio yet. Other advanced module APIs are not a complete action pipeline. See [Studio jobs](studio-jobs.md) for current local evidence and an existing export-duration failure.
- Successful advanced results still need transactionally applied revision checks and artifact lineage.
- Running cancellation, caller-exit durability and crash recovery need complete integration tests.
- Native player/action/progress/review/approval controls need implementation and real Desktop acceptance.
- Native tooling/model acquisition needs a reproducible first-run setup flow.
- Graphic/voice/editorial functionality must be judged against the full accepted workflow, not the existence of helpers.
- External account/application operations require configuration, consent and read-back validation.
- No Marketplace entry, public demo or contest submission has been made.

## Verification

The transcription routing branch was tested locally with Python 3.11.15 and FFmpeg 7.1: **126 tests collected, 113 passed, 12 skipped, one pre-existing export/cover error**. Its six focused checks pass, including a real detached no-audio job and contract-tested audio-result application. All four Node Desktop contract tests and Ruff pass. Use `python scripts/check.py` to reproduce with generated files confined to `artifacts/`; see [Studio jobs](studio-jobs.md) for details. This is not a full-suite pass, real-model Studio acceptance or native Desktop acceptance. Extensive transcription testing is deferred to [the acceptance checklist](testing.md#deferred-transcription-acceptance).

### Original author checkpoint (different environment)

The original local Python 3.12 run reported **110 tests: 109 passed, 1 skipped, no failures**. This run enabled the consented-media preview/cover/QA test and exercised real local speech, face and segmentation models. The skipped check requires native Windows symlink-creation privileges; its controlled alias-resolution regression passes. Logs and media evidence remain local in `artifacts/`.

The earlier pre-fix run had two failures (display rotation and premature decoder-end coverage); both were reproduced and fixed. Additional regressions now cover manual-range preservation, canonical report/subtitle routes, resolved network-path rejection and metadata-only remote-upload verification. FFmpeg filter-script compatibility now selects the modern flag, with a narrowly tested legacy fallback.

Hermes Plugin Doctor passed. Catalog validation of a clean source-only checkout passed without warnings; the working-tree scan can additionally see ignored local model binaries, which are not part of the repository. GitHub Actions platform results must be read separately and are not implied by this local run.

Four Node Desktop contract tests pass. Ruff passes. Initial Linux CI exposed Windows-specific temporary-directory and default-font assumptions; the portability corrections retain the same assertions, prefer an installed approved font only for new defaults and never silently replace an explicitly selected family. Read the latest Actions run for platform results. These checks are not evidence of a complete native-user workflow.

See [remaining work](roadmap.md), [architecture](architecture.md) and [testing](testing.md) before claiming a feature is finished.
