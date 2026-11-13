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
   - Pacing (`settings.pacing`) is off by default. For a short-form talking
     head, suggest punch-ins and a 0.6 s pause limit, and ask before turning
     them on: `{"punch_in": "alternate", "max_pause": 0.6}`. Punch-ins zoom
     in on every other cut, centred on the face, and are lowered when they
     would enlarge the source more than `max_upscale` (default 2x).
     `max_pause` shortens silences between kept words, so the video gets
     shorter. `transition` can be `cut`, `crossfade` or `dip`; `push_in: true`
     adds a slow zoom on ranges of 4 s or more.
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

## Delivery packages

After the person approves and the final finishes, offer a local delivery package.
Use `cutroom_project post_text` to read the suggested copy, then save or pass
`post: {title, caption, hashtags: []}` with `cutroom_project package`. Upload
copy lives in `settings.post`; changing only that copy does not change video
approval. Read any limit errors in plain words. `packages` lists folders and
`verify_package` takes the project id and returned `package` folder name to
recheck every checksum. Share the folder path and files, and say: **Nothing
has been posted. Upload these files yourself.** Never claim a package was
posted or grant approval from chat.

## Clips from a long recording

For recordings longer than about three minutes, offer to find standalone clips.
After transcription, use `cutroom_project find_clips` with the target `platform`
(default 8 candidates; `min_s` and `max_s` stay within 20–90 s, Shorts defaults
to at most 60 s). Show the top candidates with times, scores and reasons, then
let the person pick. You may add your judgement about the topic, but clip
bounds must stay on the sentence boundaries returned by the tool. Use
`cutroom_project create_clip` with the chosen `candidate_id` and platform.
It opens a separate project limited to that source range, with its own preview,
QA and approval. Never turn a score into a promise that a clip will perform well.

## Long YouTube videos

For a `youtube` project (talks, tutorials, anything over a few minutes):

- **Chapters.** `cutroom_project get` returns `longform`: the program length,
  `chapters`, `chapter_problems` and, while there are none, a list of
  `suggested_chapters` made from the transcript. Show the suggested list as
  `0:00 Title` lines, say the titles are rough suggestions, and offer better
  titles in the speaker's own words. Let the person edit them, then save
  `settings.chapters` (`[{start, title}]`, start in seconds of the edited
  video). YouTube needs the first chapter at 0:00, at least three, each at
  least 10 s; read `chapter_problems` back in plain words. Chapters move with
  later cuts, and the update returns a note when one moved or broke a rule.
- **Thumbnail.** Each preview and final makes a 16:9 `thumbnail.jpg` (up to
  3840×2160, under 2 MB). `settings.thumbnail` takes `time` (seconds of the
  edited video; leave it out for a face-forward frame) and short `text`.
- **Subtitles.** A sentence-based `captions.srt` is written next to the video
  unless `settings.subtitles_file` is false. Burned captions stay off for
  YouTube unless the person asks.
- **End screen.** If the person plans a YouTube end screen, set
  `settings.end_screen_s` (5–20 s). QA warns when captions or a title show in
  those seconds.

Chapters, thumbnail and subtitles are part of the reviewed version: changing
them needs a new preview and a new approval in Cutroom Studio. Never say
that anything was approved.

## Other platforms

To make another version, call `cutroom_project derive` with the target
platform. The copy keeps the edit, starts unapproved and needs its own
preview, QA and approval.

## When something fails

If a job fails, report the error in one sentence, say what you will try (or
what the person can do), and do not retry the same job more than once
without asking. Never invent results or file paths.
