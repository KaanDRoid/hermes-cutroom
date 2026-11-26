# Changelog

## 0.3.0 — unreleased

Explainer layouts for vertical videos.

### Split explainer
- New Layout section in Style: Full frame, Split explainer and Picture over you
  (9:16 platforms). A headline at the top, a panel in the middle and the
  speaker in a rounded card below, on paper, grid, kraft or dark backgrounds.
- The panel shows a drawn card (title, number, quote, bar chart, app row,
  terminal) or a local picture or screen recording. Select words in Edit and
  choose Picture to change the panel while you say them.
- Preview and Final draw the layout; captions move between the panel and the
  speaker and stay inside the platform's safe zone. The player shows the same
  layout before rendering.
- Layouts are saved on the project, can be undone and can be set from chat.
- Headline capitals follow the video's language (Turkish i becomes İ).
- Each panel picture can say where it comes from (yours, a stock site or AI,
  with credit, link and license); the export package lists them in
  sources.txt and suggests the credits for the post text.
- Sound wave card for the top panel: the voice after cuts and bleeps, drawn
  in the render; useful for audio-only talks and podcasts.
- Headlines shrink to stay clear of the platform's side buttons; Review asks
  for a shorter headline when that makes it hard to read.

### Bleep and hide
- Select words in Edit, then Bleep (a 1 kHz tone) or Mute from the ⋯ menu;
  "everywhere" bleeps every time a word is said. Bleeped words are left out
  of burned captions and SRT/VTT files.
- Hide area: draw a box on the Original player for the selected words' time;
  a solid box, blur or pixelate. Boxes stay where they are drawn.
- Both apply to Preview and Final, including with cuts, punch-ins, music and
  the split layout, and can be set from chat.
- A thin strip in More tools shows pictures, hidden areas and bleeps in time.
  Drag a block to move it or an edge to change it; it keeps to whole words,
  timed pictures never overlap, and a click jumps the player there. Arrow
  keys move a focused block a word; Shift and arrows change its end.

### Studio
- The player stays dark in Hermes's dark theme too, and captions in the
  Studio player are drawn light on a dark outline in both themes, as they
  are in the video. The safe-area shading follows.
- Load video and player messages stay above the layout cards.
- A project whose video file is gone says so on the player at once, instead
  of a Load video button that never finishes.
- The player checks a video file in full once when it starts loading, not again
  for every 1 MiB piece; long originals start much sooner. Renders, exports
  and downloads still check the whole file every time.

## 0.2.0 — unreleased

Creator formats, a redesigned Studio and faster renders.

### Platform formats
- Profiles for Instagram Reels, YouTube Shorts, TikTok and YouTube with sourced,
  dated specifications, and quality checks per platform: frame, frame rate,
  length limit, loudness and safe-zone placement.
- Derived projects: one recording becomes a version per platform, each with its
  own settings and approval.

### Editing and style
- Animated word captions (highlight, pop, one word) shown from each word's
  exact frame, inside the platform's safe zone; SRT and VTT for long videos.
- Reframing for tall and square videos: blurred fill, centre crop or a crop that
  follows the speaker's face, with manual keyframes.
- Pacing: punch-ins on cuts, slow push-ins, a maximum pause and crossfade or dip
  transitions.
- Music you supply, lowered under speech; voice clean-up; platform loudness.
- Removed words are cut in the pause beside them, not inside a sound.

### Finding and delivering
- Clip finder: whole-sentence clips from long recordings with explained scores;
  a picked clip becomes its own project.
- Long-form YouTube: chapters, a 16:9 thumbnail, subtitles and end-screen space.
- Delivery packages: a folder per platform with video, cover, post text and a
  checksum manifest. Nothing is posted.
- Send to the cloud: copy an approved export to Google Drive or another rclone
  remote from Export, with progress, cancel and a check of the copy.
- Record with OBS: start and stop OBS Studio recording from the home page and
  edit the recording.

### Studio in Hermes Desktop
- Redesigned around four steps (Edit, Style, Sound, Export) with autosave, a
  player with live captions, poster frames and a chat card for finished videos.
- J, K and L playback keys; Browse opens subfolders.
- Plain-sentence errors, including the name of an unsupported setting after an
  update.
- New logo, app icon and brand guide (`docs/brand/`).

### Speech
- Recordings without speech (music, noise) give no words instead of invented
  ones; segments Whisper is unsure of are dropped; transcripts are repeatable.
- Model files are found in the Cutroom models folder when a project names none.

### Performance and fixes
- Every cut used to read the whole recording, so render time grew with the
  square of the number of cuts. Cuts now read only their part: 557 cuts of a
  17-minute talk render in about 6 minutes at 1080p (see
  `docs/performance.md`).
- Sound and picture stay in sync on FFmpeg 7.1, on recordings that lost frames
  and on sound that starts late.
- The chat gets three tools by default; the older plan-file tools are opt-in.
- Face track no longer pans slowly after a camera change the scene detector
  missed: when the face is found again far away after a gap, the crop moves to
  it at once; a new shot starts where its first face is.
- The original player shows the Face track crop, not the centre; a person can
  switch Original, Preview and Final while a video is loading.
- Review explains caption problems (what, where, how to fix) and the cloud
  list uses readable file names.

### Safety
- Try again repeats local jobs only, never a cloud copy and never with consent.
- In a chat on Telegram, Discord and similar services, finished renders are not
  shared automatically: the agent asks first, because sharing uploads the file
  there.
- An OBS request has one time budget; the OBS password never appears in an
  error; signed links in cloud errors lose their query string.
- Scrubbing or choosing a destination keeps an approval; a real edit clears it.

### Known limits
- `/obs` status takes any local port and its error tells a closed port from
  another failure, so a local program could use it to probe local ports.
- In a Hermes profile other than the one the gateway started with, plugin
  requests go through a separate plugin host; there, loading a video into the
  player measured about 0.8 MB/s (about 2.5 minutes for a 34 MB preview).

## 0.1.1

Catalog review fixes: interpreter selection, child process environment
allowlist, legacy tools confined to the workspace.

