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

## Clip finder and source-range projects

These are synchronous project actions, not background job names. They reuse
`cutroom_project`; the default remains three tools (`cutroom_inspect`,
`cutroom_project`, `cutroom_job`), with no new approval action.

```python
found = studio.find_clips(project["id"], min_s=20, max_s=60,
                          count=8, platform="youtube_shorts")
pick = found["candidates"][0]
clip = studio.create_clip(project["id"], "youtube_shorts",
                          candidate_id=pick["id"])
# Alternatively: start=137.4, end=165.1 (snapped to safe sentence boundaries).
# Then run preview and qa on clip["id"], and let the person review and approve.
```

- `find_clips(project_id, min_s=None, max_s=None, count=None, platform=None)`:
  minimum and maximum are finite 20–90 s, minimum ≤ maximum, count is 1–20
  (default 8). The default maximum is 60 s for Shorts, otherwise 90 s. The
  transcript must contain timed words. Candidates include source `start`, `end`,
  `duration`, `first_word_id`, `last_word_id`, `hook`, bounded `text`, rank,
  score 0–100 and reasons with signed points. `mode` distinguishes punctuation
  from inferred pause boundaries. Local sound analysis is optional and has a
  120 s timeout and a three-hour source cap; a missing or unmeasurable track
  falls back to word timings. Nothing is downloaded or sent out.
- Discovery rejects workloads above explicit budgets before scoring: 30,000
  words / 1,000,000 transcript characters, 4,096 characters per sentence,
  and 100,000 window visits. Invalid and too-short windows count too.
  Optional inputs are capped at 540,001 energy samples and 100,000 face
  samples. A cooperative 10 s search deadline is checked while windows are
  visited and scored; optional sound decoding has its separate timeout.
  Each window is scored once into a small tuple (score, times, sentence
  indices); text and reasons are built only for the picked clips. The score,
  tie-break and diversity rules are unchanged, and the picks are identical to
  the unbounded search. A three-hour recording of short sentences (about
  29,000 windows) finds 8 or 20 clips in under a second with a peak of about
  8 MiB of Python allocations. Dense timestamps may need a shorter transcript.
  This is an algorithmic bound, not an OS-enforced worker memory/CPU limit.
- Suggestions are saved as `clip_candidates` with a timed-word fingerprint.
  They do not change the revision or review digest. Replacing or correcting the
  transcript removes them; stale candidate IDs are refused.
- `create_clip(project_id, platform, candidate_id=None, start=None, end=None,
  name=None, final_resolution=None)`: supply either a candidate ID or both times,
  never both. Explicit times must be finite, ordered, inside the source and
  at most three hours; they snap to safe whole-sentence edges, must keep at
  least 20 s, and must fit the target platform's hard limit. They are a manual
  range selection, not limited by discovery's 90 s ceiling.
- The child records `derived_from.range: {start, end}` in **source time**.
  Cuts and exclusions are intersected with it, words outside it are dropped,
  original word IDs/timestamps are retained and fillers are recomputed. Story
  selections and program-time framing pins are cleared, as are chapters and a
  chosen thumbnail frame (they are in the parent's program time; the thumbnail
  text is kept); settings and brand are copied with the target profile. No analysis, render or approval is copied.
  A platform version derived from a clip keeps its range. Later edits, silence
  results and replacement transcripts cannot reopen the rest of the source.
- The existing segment renderer and word remapper make program time start at
  zero, keep A/V together and write captions only for this range. Each clip needs
  its own preview, QA, review and human approval.
- REST: `POST /projects/{id}/find-clips` accepts the discovery options;
  `POST /projects/{id}/clips` accepts the creation options and returns 201.
  Authentication and the existing request/exception rules apply. The same
  names are actions on `cutroom_project`. Chat results keep a 400-character
  excerpt per candidate plus the reasons, so a long talk does not flood chat.
- Desktop: **Find clips** appears in Edit for sources over three minutes, but
  not inside a clip. Each candidate has a start-frame poster, range, length,
  score, reasons, words, **Play** and **Make clip**. Play loads/seeks the original
  and stops at the range's end; Make clip uses the chosen platform and opens the
  new project without approving it. Pending edits are saved first.

See [F5 verification and editorial limits](creator-formats.md#f5--clip-finder).

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
- Thumbnail previews retain at most 32 frame/title pairs and 32 MiB of JPEG
  plus JSON cache bytes per project. Least-recently-used pairs are pruned under
  a project-specific interprocess lock, which also deduplicates simultaneous
  generation and protects reads. Only generated cache names are removed;
  redirected cache paths are refused. Newly namespaced abandoned thumbnail
  temporaries are cleaned under that lock; unrelated poster files are untouched.
  There is no workspace-wide/global budget, and legacy anonymous temporary
  files are left alone because they may belong to a poster request.
- Subtitle sidecars reject a token that cannot fit losslessly in two 42-character
  lines rather than dropping its tail. Co-timed zero-length words share a cue;
  impossible co-timed text is rejected explicitly. The writer refuses an
  unrepresentable duration instead of silently skipping text. QA compares the
  delivered character stream directly against original transcript text in
  addition to cue/timing checks (layout whitespace is normalized).
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

When `cutroom_job get` (or `submit`, if the job is already complete) returns a completed `preview`, `final` or `cover` job, the result can carry `media`. Only a current, facade-validated publication gets a `display_hint`; historical files remain summaries without a handover hint. `cutroom_project get` adds `media` for linked `preview` and/or `final` renders, with currentness revalidated. Hermes Desktop reads these fields to draw the Cutroom card for the `MEDIA:` line; any other surface just plays the file.

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
- `current` requires this job's lineage, matching path and successful `Studio.artifact` validation (current digest, workspace containment and publication bytes). `approved` additionally requires human approval matching both the current revision and freshly computed review digest. Replacing reviewed music or tampering with published bytes makes both false and removes `display_hint`, even when the old file remains. A missing file or failed lookup clears any previously enriched media/hint fields.
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

### Where a removed word is cut

Recognisers stamp word edges up to a few hundred milliseconds off. Cutting at
the stamps can leave the tail of a removed word or clip the start of a kept
one. When the source has sound, `speech.word_segments` reads its 20 ms voice
levels (the same `clips.energy_profile` that clip search uses) and checks each
edge next to a removed word:

- An edge already in a pause stays where it is.
- An edge inside a sound gives that sound to the word whose stamp overlaps it
  most. A removed word's sound is cut away whole; a kept word's sound is kept
  whole.
- An edge never moves more than 0.35 s, and nothing moves inside continuous
  sound. Without levels (no audio, or a source over three hours) the stamps
  are used as before.

The Studio keeps the levels of the last four sources in memory, so only the
first edit of a source pays for measuring it (0.13 s for 44 s, 1.0 s for
17 minutes).

Measured on the Sandra interview (`tests/test_word_cut_edges.py` mirrors it):
the tiny model stamped "when" at 33.34–33.84 s while the sound ran on to
33.94 s. Cutting at the stamp left a fragment that a re-transcription heard as
"when he was"; the settled edge moves to 34.00 s, in the pause. The same
check also showed the limit of any edge rule: the small model hears "our
father died when I was two", with one "when". The tiny model's second "when"
was invented and its stamp covered "I was". Removing it removes those words,
so the Settings page now advises the small model for editing by words.

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

On FFmpeg 7.1, `export_video` could report a 0.1-second MP4 for a 0.2-second, 10-fps selection because the container dropped the last frame's duration, which made `test_final_portrait_and_real_safe_area_cover` fail with `Cover time must precede end of video`. Exports from constant-frame-rate sources (`r_frame_rate` equal to `avg_frame_rate`) now request a constant output timeline at the source rate (`-fps_mode cfr -r <rate>`). Variable-frame-rate sources keep their original timestamps. `test_constant_rate_sources_keep_every_frame_duration_in_exports` covers both branches.

The full suite now passes on FFmpeg 7.1.1 as well as 9.0.2. That run found and fixed transitions refused by `xfade` on 7.1, a 7 ms sound offset on WebM sources that start before zero, and sound placed early when it starts after the cut. Constant-rate output is now also checked against the real frame timestamps: sources with lost frames are placed by time. See [frame identity, lost frames and late sound](creator-formats.md#frame-identity-lost-frames-and-late-sound-pre-release-review).

## Local delivery packages (F7)

Packaging is a bounded, synchronous local facade operation after the render,
not an external `publish` job. `Studio.package(project_id, post=None,
cover_time=None)` requires a current approval digest and the same digest on the
published final; stale approval, changed bytes and a preview-only project are
refused. It creates a new `projects/<id>/packages/<platform>-<UTC timestamp>/`
folder, hard-linking or copying the final without modifying it. Do not edit a
linked video in place: it shares bytes with the final. A new copy is required
for later editing; the package README says so whenever the video is linked.

`settings.post` contains `{title, caption, hashtags: []}`. A **post-only** update
keeps the video revision, approval and artifacts; post text is not in the video
review digest. Combined video changes still invalidate approval. Every package
records exactly which fields and composed upload text were used. Captions,
hashtags and YouTube chapter lines are measured together, using sourced limits
in `platforms.py`; a broken limit refuses the package with a plain error.

REST:

- `GET /projects/{id}/post`: saved or locally suggested text, composed fields,
  counts, limits, chapter text and any problems. Nothing is saved.
- `PUT /projects/{id}/post`: validate/save upload copy without video approval.
- `POST /projects/{id}/packages`: body `{post?: {title, caption, hashtags},
  cover_time?: seconds}`; build a package, saving supplied text only on success.
- `GET /projects/{id}/packages`: list local package folders/files/sizes.
- `POST /projects/{id}/packages/{name}/verify`: re-hash that package; malformed
  manifests and missing, changed or unlisted files return a plain report.

`Studio.verify_package(path)` is restricted to project package folders inside
the workspace, including copied test packages. Paths, redirected directories,
manifest sizes/file counts and filenames are bounded. Payload SHA-256 values
and sizes are in `manifest.json`; a manifest cannot self-hash, and checksum
verification is not authentication if both a file and the manifest are edited.
The returned file list includes the manifest's separately computed size/hash.

Existing `cutroom_project` actions: `post_text(project_id, post?)`,
`package(project_id, post?, cover_time?)`, `packages(project_id)`, and
`verify_package(project_id, package)` (a returned folder name, not an arbitrary
path). No new default tool or approval action is exposed. Desktop Export offers
post fields with live counters, Make package, the selectable/copyable folder
path, files/sizes and Check package. No host folder-opening API was assumed
without its SDK documentation.

See [creator formats F7](creator-formats.md#f7--local-delivery-packages) for the
source table, cover-upload qualifications and real evidence. Nothing is posted.
Live media download, OBS and rclone remain pending owner consent and were not
connected or exercised here.
