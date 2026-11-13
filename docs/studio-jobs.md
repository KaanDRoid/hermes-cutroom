# Studio background jobs

The public Studio facade (`cutroom.studio.Studio`) executes every editing action as a detached, revision-bound job: **`inspect`, `silence`, `transcribe`, `vision`, `segment`, `storyboard`, `preview`, `final`, `cover` and `qa`**. External adapters (`download`, `publish`, `obs`, `calendar`) are accepted names that still require explicit consent and are not wired into the Studio pipeline.

The same jobs are reachable from three surfaces: the Python facade, the plugin REST API (`dashboard/plugin_api.py`) used by the Desktop page, and the `cutroom_project` / `cutroom_job` agent tools. Approval exists only on the human surfaces (Desktop page and REST); no agent tool can approve.

## Action reference

| Action | Options | Requires | Publishes | Revision |
|---|---|---|---|---|
| `inspect` | none | source | job result only | unchanged |
| `silence` | `noise_db`, `min_duration`, `padding` | source | intersected `base_segments` | +1, approval removed |
| `transcribe` | `language` | `settings.whisper_model` for audio sources | `transcript` with review-only fillers | +1, approval removed |
| `vision` | `frame_step` | `settings.face_model` | `analysis` (frames capped at 2000 in the project; review-only intervals) | +1, approval removed |
| `segment` | none | `settings.segmentation_model`; optional `background` (file or `#RRGGBB`), `graphic`, `max_width` | `segmented` artifact and `segmentation` summary | +1, approval removed |
| `storyboard` | none | a transcript with words | `story` (three hooks; scenes once a hook is selected), `storyboard` and `caption` JSON artifacts | +1, approval removed |
| `preview` | none | current `segmented` artifact if `use_segmented` | `preview` MP4 plus `captions_srt` / `captions_vtt` when words remain, and `captions_ass` (the burned script) for animated caption styles; for YouTube also `chapters` (`chapters.txt`, chapters embedded in the MP4) and `thumbnail` | unchanged |
| `final` | none | current human approval; selected hook and current storyboard if a story exists; an edit no longer than the platform's hard limit; for YouTube, chapters that follow YouTube's rules | `final` MP4 plus caption sidecars (and the YouTube files, as for `preview`) | unchanged |
| `cover` | `time` | a current `final` (preferred) or `preview` | `cover` PNG | unchanged |
| `qa` | none | a current `final` (preferred) or `preview` | `quality` JSON report, with platform checks for platform projects | unchanged |

Unknown options are rejected before a job is created. Source, model and asset paths always come from the saved project settings, never from job options.

## Platform settings

Two project settings select a delivery profile from `cutroom/platforms.py`:

| Setting | Values | Effect |
|---|---|---|
| `platform` | `custom` (default), `instagram_reels`, `youtube_shorts`, `tiktok`, `youtube` | Non-custom profiles fix the frame, aspect (saved back into `settings.aspect`), loudness (−14 LUFS, −1 dBTP), safe zone and length limit |
| `final_resolution` | `"1080"` (default), `"2160"` | Final frame for platform projects: 1080×1920 or 2160×3840 vertical, 1920×1080 or 3840×2160 for `youtube`. Ignored for `custom` |

```python
project = studio.update(project["id"], {"settings": {
    "platform": "youtube_shorts",
    "final_resolution": "1080",
}}, project["revision"])
```

Like every edit, this bumps the revision and removes approval. Projects saved before these settings existed have neither key and load as `custom`; their render settings, digest and approval are unchanged.

For platform projects:

- `preview` renders at the profile's preview frame (1080×1920, or 1920×1080 for `youtube`) and `final` at the chosen resolution. The source is fitted and padded, never cropped.
- The title, an optional lower third and the burned caption band are placed inside the profile's safe zone. Each margin is the larger of the profile margin and the brand's `safe_margin`; a title that does not fit is moved and then shrunk, and the caption band and lower third are clamped into the safe area whatever `subtitle_y` says. Burned cues are split into events of at most two lines (no text is dropped); the export result reports `captions_burned` (cues) and `caption_events` (burned events). The geometry is recorded in the export result as `safe_zone_layout`.
- Every export result records `source_video` (the source's pixel grid in display orientation), `content_size` (the fitted picture), `upscale_factor` and `upscaled`. The render's lineage records the `platform` it was made for, which the Desktop overlay uses.
- `final` is refused before a job is created when the kept ranges run longer than the profile's hard limit (Shorts 180 s, Reels 1,200 s, TikTok 3,600 s). `preview` still runs so the edit can be reviewed and trimmed.
- `qa` adds `platform_frame`, `platform_duration`, `platform_fps`, `platform_upscale`, `platform_loudness` and `safe_zone`. A warning (for example a Reels edit over three minutes, a 25 fps Reels render or a 320×180 source enlarged to 1080×1920) makes `passed` false, as for other checks. `platform_fps` accepts NTSC 30000/1001 as 30 fps and, for variable-rate video, also checks the slowest frame interval (`min_instantaneous_fps`). `platform_upscale` compares the fitted picture with the source size of the render, which Studio passes as `source_video` in the QA settings; it is skipped when that is unknown. The `safe_zone` check recomputes the text boxes from the render geometry; it does not inspect glyph pixels.

## Caption styles

Burned captions (`settings.captions: true`) use `settings.caption_style`:

| Style | What the viewer sees |
|---|---|
| `classic` (default) | Timed cues, unchanged from earlier versions |
| `highlight` | The whole cue, with the spoken word in `caption_highlight_color` (default `#FFCC00`) |
| `pop` | Words appear one by one with a short scale-in; the line layout is fixed from the first frame |
| `one_word` | Only the spoken word, larger, at `caption_word_y` in the safe area (0 top, 1 bottom, default 0.8 so it sits below a talking head's face) |

```python
project = studio.update(project["id"], {"settings": {
    "captions": True,
    "caption_style": "highlight",
    "caption_highlight_color": "#00E5FF",
}}, project["revision"])
```

- Words come from the transcript, mapped to the edited timeline. Excluded words never appear, and a word split by a cut is shown once.
- Each caption state is its own ASS event, timed in whole frames, with edges placed just before their frame so libass shows each word from its first frame. Words that start in the same frame share a state. At most two lines are shown, inside the platform safe zone (or the brand margin for `custom`), at no less than the BBC reading size (3.5 % of the frame height on vertical video, 6.25 % on landscape). Lines are measured with the brand font when Pillow is installed.
- `preview` and `final` publish the burned script as `captions_ass` and record its hash. `qa` reads the script of the render it checks (not the latest published one) and adds two checks; a script made for another frame size fails both:
  - `caption_timing`: each word's first frame comes no earlier than its start and at most one frame interval later, and its last frame no more than one interval after its end.
  - `caption_bounds`: every event box stays inside the safe zone.
- In an update, `null` resets `caption_highlight_color` or `caption_word_y` to its default.
- Long-form `youtube` projects get SRT/VTT sidecars, and burning captions in is opt-in:
  - Deriving a YouTube version, or switching a project to `youtube`, turns burned captions off unless the same change turns them on.
  - The Desktop form unticks **Burn timed captions** when YouTube is chosen.

## Music, cut sounds and voice clean-up

```python
project = studio.update(project["id"], {"settings": {
    "music": {"path": "C:/Music/own-track.wav", "volume_db": -18, "duck_db": 15,
              "source_note": "Recorded by the channel owner"},
    "cut_sfx": {"path": "C:/Music/click.wav", "volume_db": -12},
    "voice_cleanup": "light",
}}, project["revision"])
```

- Files must be local audio files of at most 256 MiB (cut sounds at most 5 s). Their SHA-256 becomes part of the digest. A render refuses a file that changed after it was saved; select it again.
- `null` removes music or a cut sound; `voice_cleanup: "off"` removes the clean-up setting.
- `preview` and `final` render the cut voice (cleaned if requested), duck the music under detected speech, place the cut sound on each cut, and normalise the mix to the profile target. The result gains `audio_mix` (what was mixed and the measured ducking depth). `audio_normalization.method` says whether the gain was linear, linear after true-peak limiting, or a dynamic fallback.
- `qa` on such a render adds `music` (measured depth against the requested depth) and `mix_loudness` (±0.5 LU, true peak).

## Pacing

```python
project = studio.update(project["id"], {"settings": {
    "pacing": {"punch_in": "alternate", "max_pause": 0.6, "transition": "crossfade"},
}}, project["revision"])
```

- Fields and defaults: `punch_in` `off`/`alternate` (off), `punch_in_zoom` 1.05–1.3 (1.12), `max_upscale` 1–4 (2, total enlargement of the source including framing), `push_in` (false), `push_in_zoom` 1.02–1.15 (1.06, on ranges of 4 s or more), `max_pause` `null` or 0.2–2 s, `transition` `cut`/`crossfade`/`dip` (cut), `transition_duration` 0.04–0.5 s (0.2, rendered as 2–12 frames). The stored value has every default filled in; `null` removes pacing.
- Punch-ins zoom every other kept range about the speaker's face (Vision face samples in any framing mode, else the centre), after the crop path and before captions. A zoom that would exceed `max_upscale` is reduced, or skipped below 1.02×, and the render says so.
- `max_pause` rebuilds `segments` from `base_segments`, word exclusions and gaze exclusions: pauses between kept words longer than the limit (in program time, across cuts too) lose their middle. `base_segments` is unchanged, so `max_pause: null` restores the pauses. The program gets shorter.
- Transitions are centred on each edit cut and built from handles outside the kept ranges, so program length, caption timing and A/V sync stay as with plain cuts; the sound gets a 10 ms fade on each side of the cut instead of an audio crossfade.
- Punch-ins, push-ins and transitions need constant-rate video; `max_pause` works on any source.
- `preview` and `final` results gain `pacing` (zoom per range, windows, anchors, total enlargement, cuts, transitions, warnings, rendered ranges). `qa` adds `pacing_upscale`, `pacing_face`, `pacing_transitions` and, with `max_pause`, `pacing_max_pause`.

## Long-form YouTube

```python
project = studio.update(project["id"], {"settings": {
    "chapters": [{"start": 0, "title": "Intro"}, {"start": 134, "title": "The atmosphere"},
                 {"start": 342, "title": "How warm is too warm"}],
    "thumbnail": {"text": "Climate change is simple"},  # "time" in program seconds; omit for automatic
    "end_screen_s": 20,
}}, project["revision"])
```

- Only YouTube projects use these settings. `chapters` (program seconds, sorted, titles up to 100 characters), `thumbnail` (`time`, `text`), `subtitles_file` (default true) and `end_screen_s` (5–20) are optional, part of the digest, and `null` removes each.
- `Studio.suggest_chapters(project_id)` / `POST /projects/{id}/chapters/suggest` returns suggestions with keywords and reasons; nothing is saved. `Studio.thumbnail_preview(project_id, time=None, text=None)` / `GET /projects/{id}/thumbnail-preview?time=&text=` returns a 1280×720 JPEG data URL and the size the export will make.
- Edits that change the cut move chapters with their footage and return notes; a final is refused while chapters break YouTube's rules (first at 0:00, at least three, each at least 10 s).
- `preview` and `final` results gain `longform` (`chapters_embedded`, `chapter_problems`, `subtitle_cues`, `thumbnail`). `qa` adds `chapters`, `subtitles_file`, `thumbnail` and, with `end_screen_s`, `end_screen`.
- `cutroom_project get` adds `longform` with the chapters, `chapter_problems`, the description text and, while there are none, `suggested_chapters`.

## Platform versions (derived projects)

`Studio.derive(project_id, platform, name=None, final_resolution=None)` creates a sibling project for another platform:

```python
reels = studio.derive(project["id"], "instagram_reels")
shorts = studio.derive(project["id"], "youtube_shorts", name="Talk – Shorts")
```

| Copied | Not copied |
|---|---|
| Source path, fingerprint and probe; transcript; `base_segments`, `segments`, `excluded_word_ids`, `gaze_exclusions`; `story` and `selected_hook`; `brief`, `voice`; settings (brand, title, captions and caption style, normalisation, graphic, background, model paths, frame step, width; a `youtube` sibling starts with burned captions off) | Artifacts and lineage, approval, job history, vision `analysis`, `use_segmented` (rebuild the person layer for the sibling) |

The sibling gets `settings.platform`, the profile's aspect, the profile's default `final_resolution` (`"1080"`; pass `final_resolution="2160"` to ask for 4K, a parent's 4K choice is not carried over; `custom` siblings get none), the stripped name, revision 1, status `draft` and `derived_from: {project_id, revision, digest}` naming the parent revision it was copied from. The source fingerprint is checked first. The parent is not modified. The sibling has its own digest, so the parent's approval never covers it. The same action is available as `cutroom_project` `derive(project_id, platform, name?, final_resolution?)`, as `POST /projects/{id}/derive` with `{"platform": ..., "name": ..., "final_resolution": ...}` (a missing source or asset file answers 422 naming the file), and as **Create version for …** buttons in Desktop. None of them approves anything. `GET /platforms` returns the profile data used by the Desktop selector and safe-zone overlay.

## Hook and storyboard flow

1. Run `storyboard` after transcription. It returns three source-quoted hook options (opening, middle and closing excerpts) and an empty storyboard with status `awaiting_hook_selection`. Duplicate excerpts are marked with `duplicate_of`.
2. The person picks a hook (`selected_hook` 0–2).
3. Run `storyboard` again. Scenes are built for the current cut and the chosen hook is recorded as `opening_hook`. When `settings.title` is empty, the opening hook becomes the on-screen title, wrapped to at most three lines for the target aspect.
4. `final` is refused while a story exists without a selected hook, or when the storyboard no longer matches the selected hook, the current cut, brief or voice.

Hooks and storyboards are deterministic excerpts of the transcript. Nothing is generated, paraphrased or invented, and footage is never reordered.

## Media summaries in tool results

When `cutroom_job get` (or `submit`, if the job is already complete) returns a completed `preview`, `final` or `cover` job, the result also carries `media` and `display_hint`. `cutroom_project get` adds `media` with the current `preview` and/or `final` summary when those renders exist. Hermes Desktop reads these fields to draw the Cutroom card for the `MEDIA:` line; any other surface just plays the file.

```json
{
  "media": {
    "path": "C:\\Users\\you\\AppData\\Local\\hermes\\plugins\\cutroom\\jobs\\<job id>\\outputs\\preview.mp4",
    "kind": "preview",
    "project_id": "<project id>",
    "project_name": "talk",
    "platform": "instagram_reels",
    "duration": 41.96,
    "width": 1080,
    "height": 1920,
    "current": true,
    "qa": {
      "job_id": "<qa job id>",
      "status": "warning",
      "passed": 13,
      "failed": 0,
      "warnings": 1,
      "total": 14,
      "failed_checks": [],
      "warning_checks": ["platform_upscale"]
    },
    "approved": false
  },
  "display_hint": "Show it to the person with a line: MEDIA:C:\\Users\\you\\...\\preview.mp4"
}
```

- `path` is the absolute file path exactly as published; `media` is omitted when the file is missing or the path is not absolute. No file contents are included.
- `qa` comes from the latest completed `qa` job for that same render (for a cover, the render it was taken from), or is `null` when none exists. `status` is computed from the check statuses: `fail` if any check failed, otherwise `warning` if any check warned, otherwise `pass`. Skipped checks count only in `total`. The report's own `passed` flag is `false` on warnings, so do not use it for the summary: a `warning` result is ready with notes.
- `approved` is true only when the project's human approval matches its current revision. `current` says whether this job's render is still the project's published one.
- Lookup problems never hide the job: the result is returned without `media`. Non-finite numbers become `null`.

## Artifact lineage and staleness

Every published file must live in its job's own `jobs/<id>/outputs/` directory. Its lineage records the job, SHA-256, size, modification time and the review digest it was rendered for (`segmented` records a fingerprint of the source, segmentation model, background, graphic and width instead).

- Any edit that changes the review digest unlinks the dependent renders (`preview`, `final`, `cover`, captions, `quality`, `storyboard`, `caption`). Files are kept on disk; links are removed.
- `Studio.artifact()` refuses stale links and files whose size or modification time changed after publication.
- A job whose project, source, approval or input files changed while it ran fails without publishing, and its unpublished outputs are deleted.
- `cover` and `qa` record whether they used the `final` or the `preview`.

## End-to-end acceptance harness

`scripts/acceptance.py` runs reference speech over a synthetic test pattern through transcribe → silence → storyboard → choose hook → storyboard → vision → preview. It then stops with `awaiting_human_review`, workspace, project ID and digest. The harness never grants approval. After separate human approval in Desktop/REST, resume with `--workspace <workspace> --project-id <id>` to run final → cover → qa. Missing or stale approval is rejected before final submission. Historical automated-approval renders are render evidence only, not human-approval acceptance.

## Silence selection

```python
import time
from cutroom.studio import Studio

studio = Studio("/absolute/path/to/new-workspace")
project = studio.create("/absolute/path/to/local-recording.mp4")
job = studio.submit(project["id"], "silence", {
    "noise_db": -35.0,
    "min_duration": 0.5,
    "padding": 0.12,
})
while job["status"] not in {"completed", "failed", "cancelled"}:
    time.sleep(0.1)
    job = studio.job(job["id"])
if job["status"] != "completed":
    raise RuntimeError(job["error"])
project = studio.get(project["id"])
print(project["revision"], project["segments"])
```

The job runs FFmpeg through the isolated engine runtime. Only the three options above are accepted. Values must be finite numbers (not booleans); minimum duration must be positive and padding non-negative. Defaults match the core draft workflow. Job options cannot substitute a different source.

On success, detected keep ranges are intersected with existing manual base ranges; existing timed-word and gaze exclusions are reapplied. No manually removed footage is restored. The resulting selection must remain nonempty and pass plan validation. A no-audio source retains its current selection. A successful job increments the project revision, resets its status to `draft`, removes approval and records `applied_revision` in the job. The job's `result` is the detected full-source plan, **not** the final intersection with the project's other selections; read the project for the applied ranges.

Source identity, project revision, asset digest and cancellation are checked under the workspace state lock before execution and again before publication. Stale, cancelled or invalid results do not change the selection. Source media is never written. Cancellation is forwarded to the isolated runtime. A controlled launcher test exercises real worker/FFmpeg subtree termination while leaving an unrelated process alive; complete running-action cancellation still needs facade acceptance. A separate subprocess test proves a queued silence job survives its submitter exiting.

## Transcription and text editing

For media with an audio stream, first set an existing local model directory. Model workers run under `CUTROOM_PYTHON` when that environment variable is set, otherwise the plugin's bundled `.venv`; the interpreter is not a project setting.

```python
project = studio.update(project["id"], {"settings": {
    "whisper_model": "/absolute/path/to/repo/models/whisper-tiny",
}}, project["revision"])
job = studio.submit(project["id"], "transcribe", {"language": "en"})
# Poll job status as above, then reload the current project before editing.
```

The only job option is `language`: a lowercase two/three-letter code or `None` for detection. Source and model paths come from the project snapshot, not job-option overrides. Earlier projects that stored `runtime_python` keep loading; the value is ignored and dropped. Unknown language codes that match the format can still be rejected by the inference library.

Required local assets are `config.json`, `model.bin` and `tokenizer.json`. Present optional `vocabulary.txt`, `vocabulary.json` and `preprocessor_config.json` are validated too. Recognized model files are fingerprinted at submission and checked again before execution and before publication. Missing, empty, escaped or changed model assets fail closed; no download is attempted. A no-audio video requires no model and completes with an empty `no_audio` transcript.

On success, the validated transcript is saved in the project with review-only `transcript.fillers`, the revision advances and approval is removed. The raw inference transcript remains in the job result, and `applied_revision` links it to the project. Neither first transcription nor retranscription automatically removes filler candidates.

### Replacement policy

Both a new `transcribe` job and a direct `Studio.update(..., {"transcript": ...}, revision)` use the same replacement policy:

- Preserve existing word-derived cuts as source-time `base_segments` before clearing old `excluded_word_ids`. Reused numeric IDs never silently exclude different words, and old removals are not silently restored.
- Keep gaze exclusions separate and reversible. Manual/silence base ranges remain authoritative.
- Recompute filler suggestions for the new words. An explicitly supplied `excluded_word_ids` field in the same direct update refers to the new transcript.
- Clear old story/hook selection and links to transcript-dependent preview/final/cover/subtitle/quality/storyboard/caption/package artifacts. Files are not deleted. This is targeted invalidation, not a full artifact-lineage implementation.
- Record `transcript_update.preserved_word_cuts` and `cleared_word_ids` in successful transcription jobs. To restore baked word cuts later, explicitly edit the base ranges via `segments`; merely rechecking a new word cannot restore them.

The resulting selection must remain valid and nonempty before anything is written. Stale, cancelled, changed-model or invalid results leave the previous project intact.

## Limits

- Real-model routing is accepted on the attributed reference speech and the consented portrait clip; it is not a claim of editorial quality across languages, accents or long recordings.
- Applying project state and completing a job are separate atomic JSON replacements under one lock, **not** a crash-atomic multi-file transaction. Recovery from a crash between those writes remains a P1 task.
- Synthetic tone/silence fixtures prove mechanics, not editorial quality on human speech.

## Local verification

With Python 3.11.15 and FFmpeg 7.1 on Windows:

```bash
python -m unittest discover -s tests -p test_studio_silence.py -v
```

Nine silence tests pass, covering real isolated detection, persisted background application, option rejection, stale queued work, no-audio media, manual/word/gaze selection preservation, empty-intersection rollback, deterministic publication races and real submitter-process exit. The race test mocks inference and launch; the separate runtime test substitutes a controlled launcher but uses a real worker/FFmpeg subtree.

For all local quality gates, run `python scripts/check.py` with the development interpreter. It sets `TMPDIR`, `TEMP`, `TMP` and Python's temporary directory to `artifacts/tmp`, and writes raw Python/Node/Ruff logs plus an exact `summary.json` under `artifacts/checks/<run-id>/`. A failed or skipped check is not disguised as a pass.

Six focused transcription checks pass: worker dispatch, bad-option/missing-model rejection, validated persistence and filler generation, safe job/direct replacement, invalid/stale/model-change/cancellation rejection, and a real no-audio detached job. Audio transcript application is contract-tested using clearly labeled fixtures, not a real Whisper model.

The transcription branch's local suite collected **126 tests: 113 passed, 12 skipped and one existing error**. Ruff and all four Node Desktop contract tests pass; no new native Desktop acceptance or branch CI result is implied. Skips include missing native models/consented media and unavailable Windows symlink privileges. Extensive transcription acceptance is deliberately deferred; see [the pending checklist](testing.md#deferred-transcription-acceptance).

### Export duration on FFmpeg 7.1 (resolved)

On FFmpeg 7.1, `export_video` could report a 0.1-second MP4 for a 0.2-second, 10-fps selection because the container dropped the last frame's duration, which made `test_final_portrait_and_real_safe_area_cover` fail with `Cover time must precede end of video`. Exports from constant-frame-rate sources (`r_frame_rate` equal to `avg_frame_rate`) now request a constant output timeline at the source rate (`-fps_mode cfr -r <rate>`). Variable-frame-rate sources keep their original timestamps. `test_constant_rate_sources_keep_every_frame_duration_in_exports` covers both branches; FFmpeg 9.0 did not reproduce the original defect, so confirm on 7.1 when available.
