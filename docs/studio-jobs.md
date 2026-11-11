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
| `preview` | none | current `segmented` artifact if `use_segmented` | `preview` MP4 plus `captions_srt` / `captions_vtt` when words remain | unchanged |
| `final` | none | current human approval; selected hook and current storyboard if a story exists | `final` MP4 plus caption sidecars | unchanged |
| `cover` | `time` | a current `final` (preferred) or `preview` | `cover` PNG | unchanged |
| `qa` | none | a current `final` (preferred) or `preview` | `quality` JSON report | unchanged |

Unknown options are rejected before a job is created. Source, model and asset paths always come from the saved project settings, never from job options.

## Hook and storyboard flow

1. Run `storyboard` after transcription. It returns three source-quoted hook options (opening, middle and closing excerpts) and an empty storyboard with status `awaiting_hook_selection`. Duplicate excerpts are marked with `duplicate_of`.
2. The person picks a hook (`selected_hook` 0–2).
3. Run `storyboard` again. Scenes are built for the current cut and the chosen hook is recorded as `opening_hook`. When `settings.title` is empty, the opening hook becomes the on-screen title, wrapped to at most three lines for the target aspect.
4. `final` is refused while a story exists without a selected hook, or when the storyboard no longer matches the selected hook, the current cut, brief or voice.

Hooks and storyboards are deterministic excerpts of the transcript. Nothing is generated, paraphrased or invented, and footage is never reordered.

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

For media with an audio stream, first set an existing local model directory and, optionally, a dedicated runtime interpreter:

```python
project = studio.update(project["id"], {"settings": {
    "whisper_model": "/absolute/path/to/repo/models/whisper-tiny",
    # "runtime_python": "/absolute/path/to/repo/.venv/Scripts/python.exe",
}}, project["revision"])
job = studio.submit(project["id"], "transcribe", {"language": "en"})
# Poll job status as above, then reload the current project before editing.
```

The only job option is `language`: a lowercase two/three-letter code or `None` for detection. Source, model and runtime paths come from the project snapshot, not job-option overrides. Unknown language codes that match the format can still be rejected by the inference library.

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
