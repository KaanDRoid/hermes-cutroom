# Reference media and local fixtures

## Speech sample

A separate 11-second speech recording is available in the official whisper.cpp repository:

- Repository: https://github.com/ggml-org/whisper.cpp
- Sample: https://github.com/ggml-org/whisper.cpp/blob/master/samples/jfk.wav
- Download: https://raw.githubusercontent.com/ggml-org/whisper.cpp/master/samples/jfk.wav
- Observed SHA-256: `59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e`
- Local location: `artifacts/reference/jfk.wav` (ignored).

```bash
mkdir -p artifacts/reference
curl -fL https://raw.githubusercontent.com/ggml-org/whisper.cpp/master/samples/jfk.wav -o artifacts/reference/jfk.wav
```

Verify the hash before using it as the reference fixture. The sample is downloaded separately, not bundled with this project. Upstream repository licensing does not automatically establish redistribution rights for every third-party media asset; review rights before shipping media in a release or demo.

This sample is used to test real local transcription. It is not the audio of either supplied user video. Do not attach it to those recordings and portray the result as their original speech.

## User-authorized local footage

Two recordings were provided for local acceptance:

| Local filename | Properties | Valid coverage |
|---|---|---|
| `1416529-uhd_3840_2160_30fps.mp4` | 3840×2160, 12.23 s, 30 fps, no audio, aerial coastline without people | Metadata, generic edits, graphics, covers, export and the no-face check |
| `4439224-uhd_2160_3840_25fps.mp4` | 2160×3840, 10.56 s, 264 frames, visible woman, no audio | Face/mouth metrics, person segmentation and portrait export |

They belong in ignored `raw_vids/` and are not distributed through GitHub. Permission for local testing is not permission to publish footage.

The landscape clip replaces an earlier local river clip that is no longer available. It is "Seawater" by Vincenzo Malagoli (https://www.pexels.com/@zenzazione/), Pexels video 1416529, under the Pexels License:

```bash
curl -fL https://videos.pexels.com/video-files/1416529/1416529-uhd_3840_2160_30fps.mp4 -o raw_vids/1416529-uhd_3840_2160_30fps.mp4
```

- Observed SHA-256: `30513f61352bba3dde774b2da791a2ab3db76e721c795164709899ee61e781eb`.

## Long talk for clip-finder acceptance

- **Title:** *Climate change is simple* — David Roberts at TEDxTheEvergreenStateCollege.
- **Publisher / attribution:** TEDx Talks, speaker David Roberts.
- **Source:** https://commons.wikimedia.org/wiki/File:Climate_change_is_simple_David_Roberts_at_TEDxTheEvergreenStateCollege.webm
- **Licence:** Creative Commons Attribution 3.0 (CC BY 3.0); credit the title,
  speaker and publisher, link the source and licence, and identify edits when
  distributing excerpts. Licence: https://creativecommons.org/licenses/by/3.0/
- **Observed SHA-1:** `d57f97f373fc8912b597c7d46174db5f74894994`.
- **Observed properties:** 1920×1080, 30000/1001 fps, VP8/Vorbis, 1063.221 s.
- **Local file:** `raw_vids/roberts-tedx.webm` (ignored, not bundled).
- **Use:** F5 sentence-boundary and clip-render acceptance and F6 chapters,
  subtitles file and thumbnail acceptance, with a local tiny Whisper model.
  F5 previews are excerpted, fitted to a vertical frame and captioned; the F6
  preview is the whole talk at 16:9. They are local evidence, not an
  endorsement or fact-check of the talk.

## Model assets

Local tested assets, not bundled:

- MediaPipe FaceLandmarker from the official Google model bucket. Observed SHA-256: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`.
- MediaPipe selfie segmenter from the official Google model bucket. Observed SHA-256: `191ac9529ae506ee0beefa6b2c945a172dab9d07d1e802a290a4e4038226658b`.
- `Systran/faster-whisper-tiny` local converted Whisper model.

Use explicit setup and offline inference. Model and fixture acquisition are not performed during plugin registration.
