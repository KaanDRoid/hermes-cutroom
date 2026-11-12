# Creator formats plan

Status: in progress on `feat/creator-formats`. This document is the contract for the 0.2.0 work. Each work package updates its section with what shipped, how it was verified, and what is still open.

## Goal

Turn one source recording into platform-ready edits for Instagram Reels, YouTube Shorts, TikTok and regular YouTube, with a person reviewing and approving every final export.

Example: import a 12-minute landscape podcast. Cutroom proposes the five strongest standalone moments, and the person picks three. Each becomes a vertical edit with face-tracked framing, word-highlighted captions, punch-ins on jump cuts and ducked music, exported for Reels, Shorts and TikTok. The full podcast is exported for YouTube with chapters, a thumbnail and an SRT file. Every approved export is written to a per-platform delivery package.

## Platform profiles

These values live in one data module (`cutroom/platforms.py`). Each numeric entry records its source URL and the date it was checked, so a platform change is a one-place update. Checked 2026-11-12.

| | Instagram Reels | YouTube Shorts | TikTok | YouTube |
|---|---|---|---|---|
| Profile name | `instagram_reels` | `youtube_shorts` | `tiktok` | `youtube` |
| Platform frame rule | 1.91:1 to 9:16, at least 720 px | Square or vertical | 9:16 recommended, at least 540×960 | 16:9 standard |
| Cutroom frame (preview and default final) | 9:16, 1080×1920 | 9:16, 1080×1920 | 9:16, 1080×1920 | 16:9, 1920×1080 |
| Opt-in 4K final | 2160×3840 | 2160×3840 | 2160×3840 | 3840×2160 |
| Length | Hard limit 20 min; over 3 min warns (not recommended to new audiences) | **Hard limit 3 min**, otherwise it becomes a regular video | Hard limit 60 min (uploads) | No limit |
| Safe zone (top / bottom / left / right) | 14 % / 35 % / 6 % / 6 % | 15 % / 35 % / 5 % / 18 % | 13 % / 35 % / 12 % / 28 % | 5 % on every side; end screens can cover the last 5–20 s |
| Frame rate | Warns below 30 fps (29.97 counts as 30) | Source rate | Source rate | Source rate |
| Text (for later packaging) | Caption 2,200 characters, 30 hashtags | Title 100 characters, description 5,000 bytes | Caption 2,200 UTF-16 units | Title 100 characters, description 5,000 bytes |
| Cover | Recommended 420×654 (1:1.55) | Custom 9:16 thumbnail, recommended 2160×3840, at least 640 px high (YouTube Studio on a computer, verified accounts); otherwise a frame from the video | Frame chosen from the video | Custom 16:9 thumbnail, recommended 3840×2160, at least 640 px wide |

Loudness target for every profile: −14 LUFS integrated, −1 dBTP true peak.

Sources and choices:

- **Frames are Cutroom's choice.** No cited page prescribes 1080×1920 or 1920×1080. Cutroom picks them inside each platform's rule (row "Platform frame rule"; Meta's Reels ads guide recommends 1440×2560 for ads), and each profile's `frame` records `chosen_by: "cutroom"` and the `platform_rule` it satisfies. 4K finals are opt-in.
- **Reels:** Instagram Help Center "Reel size & aspect ratios" (1.91:1 to 9:16, 720 px minimum, 30 fps minimum, 420×654 cover), the Instagram Help Center article on recording reels (`help.instagram.com/2720958398006062`: up to 20 minutes; reels over 3 minutes are not recommended to new audiences), Meta's Reels ads guide (safe zone), Instagram Graph API media reference (caption and hashtag limits). Both Help Center articles are rendered with JavaScript; the static HTML of the length article still carries an older "up to 3 minutes" description, while the rendered article states the values above (checked in a browser on 2026-11-12).
- **Shorts:** YouTube Help "Understand three-minute YouTube Shorts" (length), "Upload YouTube Shorts" (square or vertical), "Add custom thumbnails" (Shorts thumbnails). YouTube publishes no safe zone for ordinary Shorts. The profile uses Google Ads Help's vertical video safe zone (288 / 672 / 48 / 192 px on 1080×1920), which applies to vertical ads shown in Shorts and is stricter than measurements of the organic interface. Fractions are rounded up.
- **TikTok:** TikTok Support FAQ (60-minute uploads; the former `support.tiktok.com` "camera tools" address redirects there and the page is rendered with JavaScript). TikTok's In-Feed ads help page (9:16 at least 540×960) links a safe-zone template but prints no numbers; scaled to 1080×1920 the template keeps 240 px top, 660 px bottom, 120 px on each side and 300 px on the right from 840 px down. Cutroom models one rectangle, so the 300 px action rail is applied to the full height (28 %). The caption limit is the Content Posting API's 2,200 UTF-16 code units; TikTok publishes no in-app limit.
- **YouTube:** EBU R 95 graphics-safe margins (5 %, `tech.ebu.ch/docs/r/r095.pdf`), because YouTube publishes no overlay safe zone for regular videos; YouTube Help "Add end screens" (5–20 s), "Recommended upload encoding settings" (16:9, source frame rate), "Add custom thumbnails" (3840×2160 recommended, at least 640 px wide), YouTube Data API videos resource (title and description limits).
- **Loudness:** AES TD1008 (document page `aes.org/community/technical-council/technical-document-aestd1008/`, cited as the current PDF) recommends a −1 dBTP ceiling. None of the four platforms publishes an upload loudness requirement; −14 LUFS is Cutroom's delivery target, the common playback normalisation level.

## Design decisions

- **One project, one target.** A project renders for exactly one platform profile (or `custom`, the 0.1 behaviour). Other platforms are *derived* sibling projects that copy the transcript, cuts and brand, with their own settings, approval and digest. This keeps the existing per-revision human approval intact; approving a Reels edit never approves the YouTube edit.
- **Derivation is also how clips work.** A clip found in a long recording (F5) is a derived project limited to a source range.
- **Profiles set defaults, people override.** Choosing a profile sets aspect, resolution, loudness, safe zones and limits. Explicit settings still win, and QA reports every deviation.
- **No silent upscaling.** Short-form finals default to 1080×1920. 4K is opt-in, and a source below the output resolution is flagged in QA rather than called 4K: for platform projects the `platform_upscale` check warns when the fitted picture is larger than the source's pixel grid (display orientation), and every export result records `upscaled` and `upscale_factor`.
- **No direct posting in 0.2.** Delivery packages are local. Platform posting APIs need separate app review and OAuth and are a later, separate decision.
- **Music and sound effects come only from the person's own files.** Cutroom records a source/licence note but does not ship a library.
- **Everything stays inside the existing security rules:** project data never chooses an executable, children run with the minimal environment, agent tools write only inside the workspace, and there is no agent approval action.

## Work packages

| ID | Package | Acceptance |
|---|---|---|
| F0 | Platform profiles, derived projects, per-platform QA (duration limit, fps, frame, loudness, safe-zone placement) and a safe-zone overlay in the Desktop player | One source produces four derived projects; each passes its own profile QA; a 3:05 Shorts edit is rejected |
| F1 | Animated word captions: highlight, pop, one-word and classic styles; two lines max; always inside the safe zone; sidecar SRT/VTT for YouTube | Highlight timing within one frame of word timestamps; captions never leave the safe zone (measured on a caption-only render) |
| F2 | Reframing: letterbox, blurred fill, centre crop and face-tracked crop with smoothing, scene-cut resets and manual keyframes | Face inside the safe area in ≥ 95 % of frames on test clips; no jumps beyond the configured pan speed |
| F3 | Pacing: alternating punch-ins on jump cuts, optional slow push-in, maximum pause, cut/crossfade/dip transitions | Punch-ins stay centred on the face and never upscale beyond the configured limit |
| F4 | Audio: background music with fades and speech ducking, voice clean-up presets, optional sound effects | Music ≥ 12 dB lower under speech; output within ±0.5 LU of −14 LUFS |
| F5 | Clip finder: sentence-bounded 20–90 s candidates with explained scores; selected clips become derived projects | ≥ 5 candidates on a 10+ minute talk, each starting and ending on sentence boundaries |
| F6 | Long-form YouTube: chapters that follow YouTube's rules, a 16:9 thumbnail (YouTube recommends 3840×2160, at least 640 px wide), SRT, end-screen space | Chapters start at 00:00, at least three, each ≥ 10 s |
| F7 | Per-platform delivery packages plus the pending integrations (media download, OBS recording, rclone upload) wired into Studio as person-only actions and accepted against live services | Each integration exercised live with explicit consent and read-back verification |
| F8 | Security review, native Desktop acceptance per platform, clean installation, FFmpeg 7.1 compatibility, documentation and demo | Every new acceptance item (A19–A28) linked to evidence |
| F9 | Release 0.2.0 to `main` and a new catalog pin | Catalog validation on a clean checkout |

F7 and F8 also close the two items still open from 0.1: live acceptance of the optional integrations (A08, A10, A16) and the clean-install and portability parts of A17.

## F0 — Platform profiles and derived projects

Status: merged into `feat/creator-formats` (pull request #12).

### What shipped

- **Profiles module.** `cutroom/platforms.py` holds `PROFILES` for `custom`, `instagram_reels`, `youtube_shorts`, `tiktok` and `youtube`, with `profile(name)`, `public_profiles()` (JSON-safe copies for the API and Desktop) and `frame_size(name, preset, final_resolution)`. Every numeric specification carries `source` and `checked`; frames also carry `chosen_by: "cutroom"` and the `platform_rule` they satisfy.
- **Settings.** Projects accept `settings.platform` (default `custom`) and `settings.final_resolution` (`"1080"` or `"2160"`). Projects without the keys load as `custom`, and `custom` produces the same render settings as 0.1 (regression-tested byte for byte). Choosing a platform sets `settings.aspect` to the profile's orientation.
- **Platform renders.** A non-custom project renders at the profile's exact frame (preview at the profile preview size, final at the chosen resolution), with −14 LUFS / −1 dBTP loudness. Title, lower third and caption band are placed from one geometry function (`postproduction.platform_layout`) that keeps every box inside the safe zone, using the stricter of the profile zone and the brand's `safe_margin`. The two-line caption band is clamped at both edges of the safe area, and the lower third is moved (with the captions below it) rather than rejected; an error is raised only when the safe area is too short for both. Burned cues are split into events of at most two lines (`platform_caption_cues`: words wrapped at the band's characters per line using a full em per character, time shared by characters, no text dropped) and libass word wrapping is off for platform renders. Text on asymmetric zones is centred in the safe area, not in the frame. Covers use the same geometry.
- **Final export limit.** `final` is refused before a job exists when the edit is longer than the profile's hard limit (for example 185 s for Shorts). Previews are still allowed so the person can see and trim the edit.
- **Per-platform QA.** For platform projects, `quality_report` adds `platform_frame` (exact size), `platform_duration` (fail above the hard limit, warning above the recommended length), `platform_fps` (warning below the profile minimum, skip when there is none; NTSC 30000/1001 counts as 30; for variable-rate video the slowest frame interval is reported as `min_instantaneous_fps` and also warns when below the minimum), `platform_upscale` (warning when the fitted picture is larger than the source pixel grid in display orientation; Studio passes the render's `source_video` into the QA settings, and the check is skipped when it is absent), `platform_loudness` (warning outside ±1 LU of −14 LUFS or above −1 dBTP + 0.3 dB) and `safe_zone` (fail when a title, lower-third or caption box computed from the render geometry reaches into the unsafe margins). The checks use the existing report structure, so Desktop lists them with the others. Custom projects get no platform checks.
- **Derived projects.** `Studio.derive(project_id, platform, name=None, final_resolution=None)` creates a sibling from the same source. It copies the transcript, cuts (`base_segments`, `segments`, `excluded_word_ids`, `gaze_exclusions`), story and selected hook, brief, voice and all settings (brand, title, captions flag, model paths), then sets the platform and the target profile's default final resolution (a parent's `"2160"` is not carried over unless `final_resolution` asks for it; `custom` siblings have none). The stored name is stripped of surrounding whitespace. It does not copy artifacts, approval, job history, vision analysis or `use_segmented` (the person layer must be rebuilt for the sibling). The sibling starts at revision 1 as a draft and records `derived_from` (`project_id`, `revision`, `digest`). The source fingerprint is checked first.
- **Surfaces.** Agent tool action `cutroom_project derive` with optional `final_resolution` (no approval is copied or granted), `POST /projects/{id}/derive` (a missing source or asset file answers 422 with the file named, not 404), `GET /platforms`, and on the Desktop page a platform selector, a final-resolution selector, a profile summary, a **Show safe zone** toggle that shades the unsafe areas over a loaded preview or final (CSS boxes from the API's profile data, for the profile recorded in the render's lineage, drawn once the video metadata has loaded), and **Create version for Reels / Shorts / TikTok / YouTube** buttons that open the new project.
- **Room for source ranges.** `derive` builds the sibling in `_derived_project`; F5 can narrow the copied cuts there and add a range to `derived_from` without changing callers.

### How it was verified

- RED before implementation: `artifacts/f0/red.log` (28 failing or erroring Python tests, 3 failing Desktop tests).
- GREEN: `artifacts/f0/green.log` — full Python suite, Desktop checks and Ruff.
- `tests/test_platforms.py`: profile data and sources; platform frames for preview and both final resolutions; text boxes stay inside every safe zone for several brand settings; a real FFmpeg render of a 320×180 landscape source for `youtube_shorts` is exactly 1080×1920 and passes `platform_frame`, `platform_duration`, `platform_loudness` and `safe_zone`; a decoded Reels frame has no text pixels in any unsafe band; a 185-second low-resolution video fails `platform_duration` for Shorts and warns for Reels.
- `tests/test_studio_platforms.py`: settings validation, unchanged custom render settings, derive copy rules and independent approval, rejection of a 190-second Shorts final before a job is created, and an end-to-end run where one source produces four derived projects whose preview and QA jobs each pass their own platform checks.
- `tests/test_studio_tools.py`, `tests/test_dashboard.py`, `tests/desktop-check.mjs`: the derive action and route, the platform list, the selectors, derive buttons and safe-zone overlay.
- `tests/test_platform_fixes.py` (review fixes): caption band and lower third inside every safe zone for top-positioned brand values; long cues split into two-line events; decoded frames of all four profiles with `subtitle_y` equal to `safe_margin`, a lower third and a long cue have no text pixels outside the safe area and at most two caption lines; NTSC and variable-rate frame-rate checks; rotation-aware source size and `platform_upscale`; source and cover data.

### Open items

- Native Desktop acceptance of the selector, derive buttons and overlay in the real Hermes window (planned for F8 / A28).
- Source ranges for derived projects (F5).
- The YouTube profile's cover is still a frame at the video size; a 16:9 custom thumbnail is F6.
- `platform_upscale` needs the render's source size; reports for renders made before this field existed skip the check.
- Characters per caption line assume a full em per character, so narrow text wraps earlier than necessary; F1 replaces this with measured glyph widths.
- The safe zone is one rectangle per profile. TikTok's action rail only covers the lower right of the frame, so the full-height 28 % right margin is conservative for titles near the top.
- Caption placement is clamped inside the safe zone; animated caption styles and the one-frame timing target are F1.

### Review fixes

An independent review of F0 found the following; each is fixed with a test written first (`artifacts/f0/fix-red.log`, `artifacts/f0/fix-green.log`) and the reviewer's probes were rerun (`artifacts/f0/fix-probes.log`).

- Captions with a small, brand-valid `subtitle_y` were drawn in the top unsafe band (TikTok `subtitle_y` 0.05: caption pixels at y 151–191, unsafe band 0–249). The caption band is now clamped at the top of the safe area as well as the bottom.
- A lower third with such values raised "No safe band is available"; it is now placed inside the safe area. Captions longer than two lines could overlap it; burned cues are now split into two-line events.
- A 29.97 fps render warned against Reels' 30 fps minimum; 30000/1001 now meets 30. Variable-rate video reports its slowest frame interval.
- QA did not flag upscaled output; `platform_upscale` now does, and the export's `upscaled` follows the fitted picture and the source's display rotation.
- Source links: the Reels length now cites the Help Center article that states 20 minutes and the 3-minute recommendation; dead AES and EBU links and redirected Google, Meta and TikTok links were replaced by their current addresses. Covers now record what the pages state (Reels 420×654, YouTube 3840×2160 and Shorts 2160×3840 thumbnails), and frames are marked as Cutroom's choice within each platform's rule.
- Deriving no longer carries a parent's 4K setting silently and stores the stripped name; a missing source or asset is reported as such (REST 422) instead of "Project not found".
- The Desktop overlay uses the platform recorded with the loaded render and appears only after the video metadata has loaded.

## F4 — Music, cut sounds and voice clean-up

Status: implemented on `feat/f4-music-voice`.

### What shipped

- **Settings.** All three are optional and off by default. Projects without them keep the same render settings and digest.
  - `settings.music`: `path` (required), `volume_db` (−60 to 0, default −18), `fade_in` and `fade_out` (0–30 s, default 0.5), `duck` (default true), `duck_db` (12–36, default 12), `loop` (default true), `start_offset` (seconds into the file, default 0) and `source_note` (where the music came from, up to 2,000 characters).
  - `settings.cut_sfx`: `path` (a sound of at most 5 s) and `volume_db` (−60 to 0, default −12).
  - `settings.voice_cleanup`: `off`, `light` or `strong`.

  Studio, the REST model and the `cutroom_project` tool all apply the same rules, and `null` removes music or a cut sound.
- **Local files only.** An audio file must be a local regular file of at most 256 MiB, whose container FFprobe reads as an audio data format (WAV, MP3, FLAC, Ogg, AAC, MP4/M4A/MOV/3GP, Matroska/WebM or AIFF) with an audio stream. Music may be up to 24 h long.
  - Cutroom records the file's SHA-256, duration and format, and the file is part of the review digest, so replacing it revokes approval.
  - A render checks the hash again before and after mixing, and refuses a file that changed since it was saved ("select the file again").
  - Nothing is downloaded and no music library is shipped.
- **Voice clean-up.**
  - `light`: an 80 Hz high-pass, FFT noise reduction (12 dB, noise floor −25 dB) and gentle 2:1 compression.
  - `strong`: 18 dB noise reduction and a de-esser.
  - The FFT denoiser delays audio by 1,200 samples (25 ms) at 48 kHz. Cutroom pads and trims around it, so the cleaned voice stays on its frames.
- **Mix.** The cut, cleaned voice is rendered to 32-bit float PCM first.
  - **Speech detection.** Speech is found from 50 ms RMS windows above max(−50 dBFS, loudest − 30 dB), and gaps up to 0.25 s are bridged.
  - **Ducking.** The music gain reaches its full depth 0.15 s before speech and recovers over 0.25 s after it. The depth is `duck_db` plus a 0.75 dB guard.
  - **Music bed.** Music is looped or padded with silence to the program length, with fades at both ends.
  - **Cut sounds.** A cut sound is resampled to 48 kHz and placed on every cut in program time.
  - **Measurement.** The music stem is rendered separately and its level is measured on speech and pause plateaus, so the reported depth is measured, not configured.
- **Loudness.**
  - The mix is normalised in two passes to the profile target (−14 LUFS and −1 dBTP for platforms, −16 LUFS and −1.5 dBTP for `custom`).
  - FFmpeg's `loudnorm` applies a linear gain only if the gained true peak stays under the limit; otherwise it silently switches to dynamic mode and can miss the target. When the gain would not fit, Cutroom applies the gain itself, limits peaks at 0.3 dB under the limit with a 4× oversampled limiter (look-ahead compensated), measures again, and repeats at most three times.
  - The export result names the method: `two-pass measured loudnorm`, `two-pass measured loudnorm (true-peak limited)`, or `dynamic loudnorm (linear gain would exceed the true-peak limit)`. Plain renders without music now report a dynamic fallback too, instead of claiming a measured two-pass result.
- **QA.** `qa` adds two checks:
  - `music`: the measured ducking depth must be at least the requested depth minus 0.5 dB, and never below 12 dB.
  - `mix_loudness`: within ±0.5 LU of the target, and a true peak no more than 0.3 dB over the limit.
- **Desktop.** Settings has a "Music, cut sounds & voice" group: file paths, levels, fades, offset and a source note, switches for loop and ducking, and three voice clean-up buttons. A blank number uses the default. A blank path removes a saved sound, or sends nothing if there was none. Out-of-range numbers are refused before saving.

### Audio/video sync across cuts (all renders)

Measuring the mix against the plain export found an older timing error in every constant-frame-rate export, with or without music.

Frame-aligned ranges begin half a frame before their first kept frame, and `concat` also drops the video stream's start offset. Audio trimmed at those edges therefore played half a frame (16.7 ms at 29.97 fps), plus the start offset, behind the picture. In addition, the joint `concat` padded each audio range to the video's container timestamps. WebM rounds these to milliseconds, so the error added about 0.4 ms per cut. The normalised audio could also end 9.7 ms before the video.

Each audio range now:

- starts at its first kept frame's timestamp,
- lasts exactly as many samples as its frames, counted cumulatively so rounding cannot add up,
- and is joined separately from the video.

The plain and mixed paths share the same audio ranges. Variable-frame-rate sources keep the previous path.

### How it was verified

- **RED before each fix.** The logs are in `artifacts/f4/`:
  - `latency-red.log`: the denoiser shifted audio by 1,200 samples.
  - `headroom-red.log`: the loudness fallback was unlabelled and missed the target.
  - `qa-depth-red.log`: QA ignored the requested depth.
  - `av-sync-red.log`, `av-sync-many-red.log` and `av-duration-red.log`: the A/V offset, the per-cut drift and the short audio.
  - The Desktop removal path was checked by mutation (`desktop-mutation.log`).
- **GREEN.**
  - `artifacts/f4/full-4.log`: 284 Python tests OK, 14 skipped without local models and media.
  - Desktop checks 22/22, Ruff clean.
- **`tests/test_audio_mix.py`:**
  - Strict settings, hashing and refusal of changed files.
  - Speech detection and the ducking envelope.
  - Ducking depth measured on the delivered file, loudness, true peak and duration.
  - Loop and pad with fades.
  - The custom target is kept, and an unchanged graph when audio settings are absent.
  - Cut sounds on each cut, including a 44.1 kHz effect.
  - Hum and hiss reduction with no shift against the plain render.
  - Sample-exact denoiser latency.
  - True-peak limiting and labelling.
  - QA against the requested depth.
- **`tests/test_av_sync.py`.** A synthetic source with a flash every 30 frames, a click at a fixed offset, and video starting 7 ms after audio. Every flash/click pair keeps the source offset within 0.5 ms, and audio ends with the last frame, on these cases:
  - plain, normalised and mixed renders,
  - three ranges,
  - twelve ranges cut between frames.
- **Real footage.** `artifacts/f4/render_evidence.py`, `artifacts/f4/evidence/measurements.json`. The Sandra clip (Wikitongues / Elise Lieberman, CC BY-SA 4.0), kept ranges 0–12 s and 14–26 s, rendered as a 24 s Reels preview with music, a cut sound and `light` clean-up. The music bed and cut sound were generated for the test.
  - Loudness −14.1 LUFS, true peak −1.3 dBTP; `music`, `mix_loudness` and `duration` pass. Before the limiter fix, the same render measured −13.4 LUFS and the method said "two-pass" while FFmpeg had run in dynamic mode.
  - Ducking measured independently on the delivered file is 15.75 dB, against an identical render without ducking with the voice band as the gain reference. The request was 15 dB plus the 0.75 dB guard; the stem report says 15.95 dB.
  - The cut sound is 34.8 dB above the plain render in its band at the cut (12.012 s).
  - Voice offset against the plain render is 0 or −1 sample in both ranges, and audio and video lengths match to within one sample.
  - The source file is unchanged (hash compared before and after).

### Open items

- A native Desktop run of the new controls (F8 / A28).
- Ducking follows detected speech energy. Loud non-speech sound in the voice track also ducks the music.
- The limiter and its latency compensation use `alimiter` options available since FFmpeg 5.1. The FFmpeg 7.1 run in F8 will confirm them.
- A source whose peaks sit within 13 dB of its loudness cannot reach −14 LUFS at −1 dBTP without heavy limiting. After three attempts Cutroom falls back to dynamic loudness and QA reports `mix_loudness` as a warning.

## Order and branches

F0 first, because every other package builds on profiles and derived projects. Then F1, F2 and F4 in parallel, then F3, F5, F6, F7 and F8. Each package is developed on its own branch and merged into `feat/creator-formats` through a pull request after the full test suite, the Desktop checks, ruff and an independent review pass. `feat/creator-formats` merges into `main` once, as 0.2.0.

## Test media

Raw media never enters the repository. The set covers a landscape talking head, a vertical phone recording, a talk longer than ten minutes, a two-speaker scene, a CC0 music track and non-English speech. Each file's licence and attribution are recorded in `docs/media-sources.md`.
