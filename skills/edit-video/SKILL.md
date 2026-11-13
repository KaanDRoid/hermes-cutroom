---
name: edit-video
description: Use when someone wants a local video edited, captioned or reformatted from chat. Runs the Cutroom workflow end to end.
---

# Edit a video with Cutroom

Use this when the person gives a local video and asks for a cut, captions, a
vertical version or a platform-ready export. Everything runs on this machine.
Never upload or publish anything; Cutroom only writes local files.

Keep answers short: one or two sentences per step, plain words, no JSON.

## Workflow

1. **Import.** Call `cutroom_project create` with the absolute local path
   (`source`) and an optional name. If the path is unclear, ask for it.
   For very long videos (over about 20 minutes), say how long it is and ask
   before starting long jobs.
2. **Transcribe.** `cutroom_job submit` with `operation: transcribe`. Poll
   `cutroom_job get` every few seconds and tell the person the stage and
   percent (for example "Transcribing, 40 %"). Do not wait silently.
3. **Propose cuts.** Read the transcript (`cutroom_project get`) and suggest
   cuts in plain words: long pauses, repeated takes, false starts, off-topic
   parts. Ask before cutting anything that changes the meaning. Apply the
   agreed cuts with `cutroom_project update` using `excluded_word_ids`
   (word-level) or `segments` (kept time ranges). Always pass the current
   `revision`.
4. **Choose the delivery.**
   - `settings.platform`: `instagram_reels`, `youtube_shorts`, `tiktok`,
     `youtube` or `custom`. YouTube Shorts allow at most 3 min; Reels are
     recommended under 3 min. If the cut is longer, say so and offer a
     shorter cut.
   - `settings.caption_style`: `highlight` is the default for short vertical
     videos; `classic`, `pop` and `one_word` are also available.
   - `settings.framing`: `blur_fill` is the safe default when a landscape
     video becomes vertical. `face_track` needs a `vision` job first; run it,
     then use `face_track` for talking heads.
   - Music: only from audio files the person supplies, as absolute paths in
     `settings.music`. Never search for or fetch music.
5. **Preview.** Submit `preview`, poll as above, then submit `qa` for it.
6. **Show it.** Put the preview on its own line as `MEDIA:<path>`, using
   `media.path` from the completed job exactly as returned.
7. **Explain QA.** Read `media.qa.status`:
   - `pass`: say it passed the checks.
   - `warning`: say it is ready with notes, and explain each note in plain
     words. Example: `platform_upscale` means the picture was enlarged from a
     smaller source and may look slightly softer.
   - `fail`: say it needs changes, explain what failed, and propose a fix.
   A `warning` is not a failure; do not call it one.
8. **Ask for changes.** Apply them with `cutroom_project update`, render a
   new preview and show it again.
9. **Approval.** Tell the person to open the project in Cutroom Studio,
   review it and approve it there. Only the person can approve. You cannot
   approve, and you must never claim that something was approved. Check
   `media.approved` or `cutroom_project get` if unsure.
10. **Final.** After the person approves, submit `final`, poll, run `qa`, and
    share the file with a line `MEDIA:<path>`. If the edit changed after
    approval, the final is refused: ask the person to review and approve the
    current version again.

## Other platforms

To make another version, call `cutroom_project derive` with the target
platform. The copy keeps the edit, starts unapproved and needs its own
preview, QA and approval.

## When something fails

If a job fails, report the error in one sentence, say what you will try (or
what the person can do), and do not retry the same job more than once
without asking. Never invent results or file paths.
