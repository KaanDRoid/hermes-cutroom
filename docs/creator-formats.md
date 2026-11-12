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
- Characters per caption line assume a full em per character, so narrow text wraps earlier than necessary. F1 measures glyph widths when Pillow is installed.
- The safe zone is one rectangle per profile. TikTok's action rail only covers the lower right of the frame, so the full-height 28 % right margin is conservative for titles near the top.
- Caption placement is clamped inside the safe zone. Animated caption styles and the one-frame timing check are covered in F1.

### Review fixes

An independent review of F0 found the following; each is fixed with a test written first (`artifacts/f0/fix-red.log`, `artifacts/f0/fix-green.log`) and the reviewer's probes were rerun (`artifacts/f0/fix-probes.log`).

- Captions with a small, brand-valid `subtitle_y` were drawn in the top unsafe band (TikTok `subtitle_y` 0.05: caption pixels at y 151–191, unsafe band 0–249). The caption band is now clamped at the top of the safe area as well as the bottom.
- A lower third with such values raised "No safe band is available"; it is now placed inside the safe area. Captions longer than two lines could overlap it; burned cues are now split into two-line events.
- A 29.97 fps render warned against Reels' 30 fps minimum; 30000/1001 now meets 30. Variable-rate video reports its slowest frame interval.
- QA did not flag upscaled output; `platform_upscale` now does, and the export's `upscaled` follows the fitted picture and the source's display rotation.
- Source links: the Reels length now cites the Help Center article that states 20 minutes and the 3-minute recommendation; dead AES and EBU links and redirected Google, Meta and TikTok links were replaced by their current addresses. Covers now record what the pages state (Reels 420×654, YouTube 3840×2160 and Shorts 2160×3840 thumbnails), and frames are marked as Cutroom's choice within each platform's rule.
- Deriving no longer carries a parent's 4K setting silently and stores the stripped name; a missing source or asset is reported as such (REST 422) instead of "Project not found".
- The Desktop overlay uses the platform recorded with the loaded render and appears only after the video metadata has loaded.

## F1 — Animated word captions

Status: implemented on `feat/f1-animated-captions`.

### What shipped

- **Settings.** Three new project settings, validated in Studio, the REST model and the `cutroom_project` tool schema (enum, pattern and range):
  - `caption_style`: `classic` (default), `highlight`, `pop` or `one_word`.
  - `caption_highlight_color`: `#RRGGBB`, default `#FFCC00`.
  - `caption_word_y`: one-word position in the safe area, 0 = top and 1 = bottom, default 0.8.

  In an update, `null` for the colour or the position removes the key so the default applies; `null` for the style is rejected. The settings are part of the review digest, so changing them revokes approval. `classic`, and projects without these keys, keep the same render settings and digest as before.
- **Words in program time.** `Studio._caption_words` maps kept transcript words to the edited timeline with `speech.remap_words`. Excluded words never appear, and the fragments of a word split by a cut are merged, so the word is shown once.
- **One event per caption state.** `cutroom/captions.py` writes an ASS script in which every state of a cue is its own event: a word event starts when its word starts, and pauses get a `gap` event. Timing is worked out in frames: the first frame that shows a word is the first frame at or after its timestamp. Cutroom does not use `\k` karaoke tags. Separate events render the same way in every libass build and can be checked from the script; cumulative `\k` durations are rounded to centiseconds and drift.
  - `highlight`: the whole cue is visible and the current word takes the highlight colour; pauses return to the base colour.
  - `pop`: the cue's layout is fixed from its first frame (future words are transparent). Each word scales in vertically from 82 % to 100 % over at most 90 ms, so a reveal never reflows the line.
  - `one_word`: only the current word, at twice the caption size (reduced to fit), centred horizontally in the safe area at `caption_word_y`.
- **Frame-exact edges.** libass treats a frame whose time equals an event edge as outside the event, and at 25, 30 and 60 fps many frames fall exactly on a centisecond. Every edge is therefore written as the last centisecond at least 1 ms before its frame and after the previous frame (`captions.frame_edge`). Above about 90 fps no such centisecond may exist, and the frame time is used.
- **Hard cases.**
  - Words whose first frame is the same share one caption state; its event is named after all of them (`w4_5`), and `one_word` shows them together.
  - A word shorter than one frame is still shown for one frame.
  - A caption group ends no later than the next group starts, so two groups never draw at once.
  - Words that start after the last frame are not drawn.
  - An unknown frame rate (`0/0`) counts as 30 fps.
  - Transcript words with control characters or lone surrogates are rejected when the transcript is saved.
- **Layout.** Events have at most two lines and stay inside the platform safe zone from F0's `platform_layout`, or inside the brand `safe_margin` for `custom` projects.
  - Line breaks use measured glyph advances of the brand font through Pillow, which comes with the `vision` and `dev` extras. Without Pillow, the full-em estimate from F0 applies. The measured width also wraps `classic` captions on platform projects.
  - **Size.** Animated styles never go below a readable size. The BBC Subtitle Guidelines give a line height of 3.9–4.5 % of the frame for 9:16 video and 7–8 % for 16:9; at a 1.2 line spacing, the font is at least 3.5 % of the frame height for vertical video (67 px at 1920) and 6.25 % for landscape and square (68 px at 1080). A larger brand subtitle size is kept, and `classic` keeps the brand size. The block is kept inside the safe area at that size.
  - An event that would not fit the width is shrunk. A single token wider than a line is not split; its event is shrunk until it fits, so a very long token (a URL) can become small.
  - Backslashes and braces in transcript text are replaced with look-alike characters, so transcript text cannot inject ASS tags.
- **Rendering.** The export burns the script with FFmpeg's `ass` filter. Studio publishes it as the `captions_ass` artifact beside the SRT/VTT sidecars and records its SHA-256 in the render job. QA of a preview or final reads the script from that render's own job and checks the hash, so a later preview cannot replace the script QA uses for a final. A render without an intact script (older renders) is checked against a script rebuilt for the video, and the report says `reconstructed`.
- **Long-form YouTube.** YouTube receives SRT/VTT sidecars, and burned captions are opt-in:
  - A `youtube` version created with `derive` starts with burned captions off.
  - Switching an existing project to `youtube` also turns them off, unless the same change turns them on.
  - In Desktop, choosing YouTube unticks **Burn timed captions**, and the person can tick it again.
- **QA for animated styles.**
  - `caption_timing` compares each word's event with the decoded frame timestamps. The first frame showing the word must not come before the word starts, and at most one frame interval (the median interval) after it. The first frame without the word may come at most one interval after the word ends; ending earlier is allowed when the next word starts first.
  - The check models libass: a frame counts as inside an event only when it comes more than 0.5 ms after the event start, and as outside it only when it comes more than 0.5 ms after the end. Words merged into one state are checked against that state. A word shorter than a frame passes when it is shown for exactly one frame. Events are matched to words by the word's original index, so a zero-length word does not shift the comparison.
  - A script whose `PlayResX`/`PlayResY` is not the video's frame size fails both `caption_timing` and `caption_bounds`.
  - `caption_bounds` checks the box of every event against the safe zone. The box comes from the ASS position plus measured glyph bounds, not from decoded pixels.
  - `classic` reports gain neither check.
- **Desktop.** Caption style buttons, plus fields for the highlight colour and the one-word position. A blank field sends `null`, which restores the default; it no longer fails validation or saves 0.

### How it was verified

- **RED before implementation:** `artifacts/f1/red.log`. RED logs for the fixes made during review: `blank-fields-red.log`, `null-reset-red.log`, `youtube-tick-red2.log`, `word-y-red.log`, `timing-red.log`, and for the second review `fix/red.log`, `fix/transcript-red.log` and `fix/size-red.log`.
- **GREEN:**
  - `artifacts/f1/fix/full3.log`: 307 Python tests OK, 14 skipped in a worktree without the local models and media.
  - Desktop checks 24/24.
  - The reviewer's decoded-pixel probe (`artifacts/f1/review/probe_timing.py`: 25 random sub-frame words, `one_word`, black sources) now finds 0 mismatches at 23.976, 25, 29.97, 30 and 60 fps and on a variable-rate source (`fix/pixel-probe-final.log`). Before the fix it found 16 at 25 fps, 4 at 30 and 5 at 60.
  - Ruff check and format clean.
- **`tests/test_captions.py`:**
  - Strict settings and glyph measurement narrower than a full em, with the em fallback when the font is missing.
  - Every word event starts within one frame of its timestamp, for each style.
  - At 23.976, 25, 29.97, 30 and 60 fps no event edge falls within 0.5 ms of a frame, and the timing report passes for every style; decoded pixels at 25 and 60 fps show each word from its first frame.
  - Same-frame words share one state, sub-frame words get one frame, groups never overlap, words past the end are skipped, `0/0` falls back to 30 fps, and lone surrogates are rejected.
  - Animated captions meet the BBC minimum size on Reels, TikTok and YouTube and stay inside the safe area; a larger brand size is kept.
  - A script made for another frame size fails QA.
  - Highlight colours only the current word. Pop reveals words with a scale-in. One-word shows a single, larger word, below the face area by default.
  - At most two lines inside the safe zone, and text kept literal.
  - Timing-report cases: shifted starts, late ends and zero-length words.
  - Decoded pixels show the highlight colour during its word and not before.
  - A caption-only render of every style keeps its pixels inside the safe zone.
  - QA adds `caption_timing` and `caption_bounds` for animated styles only.
- **`tests/test_studio_captions.py`:**
  - Validation, and `null` resets.
  - No defaults are added on load (the digest is unchanged) and classic render settings are unchanged.
  - Words are remapped after cuts and exclusions; a word split by a cut is shown once.
  - YouTube burn-in rules for derive and for switching platforms.
  - An end-to-end highlight preview publishes `captions_ass`, and QA checks it.
  - After preview → approve → final → preview, QA of the final uses the final's own script (`script_job` is the final's job).
- **`tests/test_caption_surfaces.py` and `tests/desktop-check.mjs`:** tool schema and REST strictness, `null` resets, the style picker, blank fields, and the YouTube untick.
- **Real footage.** The Sandra clip (Wikitongues / Elise Lieberman, CC BY-SA 4.0) with its real transcript, kept ranges 0–6 s and 8–14 s, rendered as a 1080×1920 Reels preview of 12.012 s in `highlight` and `one_word`:
  - All 24 words pass `caption_timing` with the script of the render itself. The largest start offset is 0.0334 s, one frame at 29.97 fps, for a word that starts just after a frame.
  - `caption_bounds` and `safe_zone` pass.
  - The test profile's project file is unchanged (hash compared before and after).
  - Frames and measurements: `artifacts/f1/evidence/`.

### Found and fixed during review

Each fix below has a test written first.

- A blank highlight-colour field in Desktop was sent as an empty string and rejected, and a blank position became 0 (the top edge). Blank fields now send `null`, and the backend restores the default.
- Switching an existing project to YouTube kept burned captions on. The backend now turns them off unless asked, and Desktop unticks the box.
- On real footage, a centred one-word caption sat on the speaker's face. The default `caption_word_y` moved from 0.5 to 0.8.
- The timing report compared a word with its neighbour's event when a zero-length word came first, and it did not check when a word's state ended. Both are fixed.
- A second, independent review rendered every rate and decoded the pixels:
  - At 25, 30 and 60 fps, an event edge that fell exactly on a frame time made the word appear or disappear one frame late, and QA still passed. Edges now sit at least 1 ms before their frame, and QA models the same rule.
  - QA read the most recently published `captions_ass`, so after a final and a later preview it checked the 4K final against the preview's 1080 script and passed. QA now reads the render's own script by hash and fails on a frame-size mismatch.
  - Words in the same frame, and words shorter than a frame, could get no event at all; overlapping groups drew on top of each other; `0/0` frame rates crashed; a lone surrogate crashed the script write. All are fixed with tests.
  - The docs claimed long tokens are split; they are shrunk, as now documented.
- Size: on the real Reels preview the default 36 px captions were about half the BBC minimum. Animated styles now use at least 3.5 % of the frame height on vertical video.

### Open items

- Native Desktop check of the caption controls in the real Hermes window (F8 / A28).
- `caption_bounds` checks script geometry, not pixels. Pixel-level coverage exists in the synthetic render tests.
- A token wider than a line is shrunk rather than split.
- Above about 90 fps, two frames can share a centisecond; edges there fall back to the frame time and QA reports any resulting delay.
- Until F2, a landscape source in a vertical profile is letterboxed, so captions are placed over the fitted picture and the bars.

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

## F2 — Reframing

Status: implemented on `feat/f2-reframing`; not yet merged into `feat/creator-formats`.

### What shipped

- **Framing modes.** `settings.framing` is one of:
  - `fit` (default, the 0.1 behaviour): the whole picture, letterboxed.
  - `blur_fill`: the whole picture over a blurred, darkened copy of itself that fills the frame.
  - `center_crop`: a fixed crop of the target aspect from the centre of the source.
  - `face_track`: a crop that follows the speaker.
- **Crop size.** `reframe.crop_size` takes the largest even-sized crop of the target aspect that fits the source (608×1080 from a 1920×1080 source for 9:16). Nothing outside the crop is scaled into it.
- **Face samples.** Vision now records a face box and eye height for each analysed frame. The worker stores them compactly as `analysis.face_samples` (at most four faces per sample, 100,000 samples) together with `analysis.scene_cuts` from FFmpeg's `scdet` (threshold 10 % on a 160 px decode). When scene detection fails, `scene_cuts` is `null` and the render reports that only edit boundaries reset the crop.
- **Speaker choice.** In each sample the face with the largest area wins, weighted up to three times by how much its mouth opening changed since the previous sample. This is a geometric heuristic, not speaker diarisation.
- **Target.** The crop puts the face centre between the safe-zone side margins and the eyes one third of the way down the safe area, and keeps the face centre inside the safe area whenever the source edges allow it. The safe area is the stricter of the platform's zone and the brand's `safe_margin`.
- **Motion.** The crop follows the target with exponential smoothing (τ 0.18 s), a dead zone of 3.5 % of the crop width, a top speed of 1.2 crop widths per second and an acceleration limit of 2.5 crop widths per second², and it brakes before the target. It snaps without motion on the first frame, on every edit cut and on every scene cut inside a kept range.
- **Manual keyframes.** `settings.framing_keyframes` is a list of at most 100 `{time, x, y?}` pins in program time (the edited timeline), with `x`/`y` the crop centre as a fraction of the source. Between pins the crop eases (smoothstep). In `face_track` the tracked path is used before the first and after the last pin. Pins that would need more than the speed or acceleration limit are refused with "space them further apart" rather than producing a jump. A derived project for another orientation does not copy the pins.
- **Rendering.** `reframe.prepare_path` maps every decoded source frame that survives the edit to its output frame and plans the path; the crop is applied as a piecewise-linear FFmpeg expression in the output frame index (`path_expression`, at most 0.1 source pixel from the plan). Tracked or keyframed crops need constant-rate video and are refused for variable-rate sources with a message to conform them first. `face_track` needs a completed Vision job; renders refuse it otherwise.
- **QA.** For `center_crop` and `face_track`, Studio passes the render's crop path into QA, which adds:
  - `framing_frames`: the planned frame count equals the decoded frame count.
  - `framing_smoothness`: no frame-to-frame move above the speed limit, except on reset frames.
  - `framing_face_safe_zone`: at least 95 % of frames with a face keep the selected face centre inside the safe area of the planned (even-pixel) crop.
  - `platform_upscale` (from F0) also uses the crop, so a crop that enlarges source pixels is reported as a warning, never silently.
- **Surfaces.** Agent tool and REST settings accept `framing` and `framing_keyframes`. The Desktop page has a framing mode selector (Fit, Blur fill, Center crop, Face track), and for a loaded preview or final a horizontal crop-centre slider with **Add framing keyframe at** the current program time and a list of pins with remove buttons.

### How it was verified

- RED before implementation: `artifacts/f2/red.log`. GREEN: `artifacts/f2/green.log`, `artifacts/f2/focused-green.log`.
- `tests/test_reframe.py` (31 tests): validation limits; crop sizes; speaker choice; smoothing, dead zone, speed and acceleration limits and braking; resets on edit and scene cuts; keyframe easing and the refusal of keyframes that are too close; the FFmpeg expression against the plan; real FFmpeg renders of a moving synthetic face whose decoded crop follows the plan; and every QA check failing on a deliberately broken report.
- `tests/test_studio_reframe.py` (9 tests): settings validation, unchanged renders without framing, framing and face analysis in the reviewed digest, Vision results with every face sample, `face_track` refused before Vision, pins kept only for the same orientation and revalidated when the edit gets shorter, and an end-to-end preview with QA.
- `tests/desktop-check.mjs`: the framing selector and keyframe controls.
- Local gates: `artifacts/f2/full-docs.log` 299 Python tests OK, 14 skipped in a worktree without the local models and media; Desktop checks 21/21; Ruff clean.
- **Real footage** (`scripts/reframe_evidence.py`, `artifacts/f2/evidence-rerun/`): 15 s of the Sandra clip (1920×1080, 29.97 fps) reframed with `face_track` for Instagram Reels at 1080×1920.
  - Vision at frame step 5: 264 samples in 14.0 s; preview render 9.0 s; QA 4.8 s.
  - `framing_frames` 450 of 450, `framing_smoothness` largest move 8.1 source px per frame against a limit of 24.3, `framing_face_safe_zone` 415 of 415 face frames inside.
  - Independent check on the rendered output: MediaPipe on every fifth output frame found a face in 85 of 90 and the face centre inside the safe area in 83 of 85 (97.6 %).
  - Audio and video streams both 15.015 s from 0.
  - `platform_upscale` warns at 1.78×: the 608-pixel-wide crop is enlarged to 1080. That is expected for a 1080p landscape source and is reported.
  - Frames `face-track-00.png` … `face-track-14.png` and `blur-fill.png` were checked by eye (`artifacts/f2/f2-sheet.png`).

### Open items

- `framing_face_safe_zone` checks the planned path against the face found by Vision; it does not run face detection on the output. The real-footage run did that separately (97.6 %); a QA option for it is a candidate for F8.
- Desktop pins only the horizontal centre; `y` is accepted by the API and tools.
- Speaker choice is geometric. Two people of similar size who both talk can make the crop alternate; pins are the remedy for now.
- Variable-rate sources must be conformed before tracked or keyframed crops. The refusal has no dedicated test yet.
- Native Desktop acceptance (A28) and an independent review are still to come.

## Order and branches

F0 first, because every other package builds on profiles and derived projects. Then F1, F2 and F4 in parallel, then F3, F5, F6, F7 and F8. Each package is developed on its own branch and merged into `feat/creator-formats` through a pull request after the full test suite, the Desktop checks, ruff and an independent review pass. `feat/creator-formats` merges into `main` once, as 0.2.0.

## Test media

Raw media never enters the repository. The set covers a landscape talking head, a vertical phone recording, a talk longer than ten minutes, a two-speaker scene, a CC0 music track and non-English speech. Each file's licence and attribution are recorded in `docs/media-sources.md`.
