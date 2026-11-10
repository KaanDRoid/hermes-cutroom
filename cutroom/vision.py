"""Local CPU vision. Gaze values are review heuristics, never verified eye contact."""

import math
import os
import tempfile
from pathlib import Path
from time import monotonic

from . import media

VISION_TIMEOUT = 300


def _dependencies():
    """Load native CPU libraries only inside the dedicated vision interpreter."""
    try:
        import cv2
        import mediapipe as mp
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Vision requires local MediaPipe, OpenCV and NumPy in this interpreter"
        ) from exc
    return cv2, mp, np


def analyze_faces(source, face_model, frame_step=1, max_frames=100000):
    """Review local video frames using a CPU FaceLandmarker, never auto-cut."""
    deadline = monotonic() + VISION_TIMEOUT
    for name, value in (("frame_step", frame_step), ("max_frames", max_frames)):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    source, face_model = media._local_path(source), media._local_path(face_model)
    cv, mp, _ = _dependencies()
    capture = cv.VideoCapture(str(source))
    frames = []
    decoded = 0
    eof = False
    previous_time = -1.0
    previous_timestamp = -1
    try:
        if not capture.isOpened():
            raise ValueError("Cannot decode local video")
        fps = float(capture.get(cv.CAP_PROP_FPS))
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Video has no valid frame rate")
        reported_count = int(capture.get(cv.CAP_PROP_FRAME_COUNT))
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(face_model),
                delegate=mp.tasks.BaseOptions.Delegate.CPU,
            ),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_faces=4,
        )
        with mp.tasks.vision.FaceLandmarker.create_from_options(options) as task:
            while decoded < max_frames:
                if monotonic() > deadline:
                    raise TimeoutError("Face analysis processing deadline exceeded")
                ok, frame = capture.read()
                if not ok:
                    eof = True
                    break
                index = decoded
                decoded += 1
                raw_time = float(capture.get(cv.CAP_PROP_POS_MSEC)) / 1000
                time = (
                    raw_time
                    if math.isfinite(raw_time) and raw_time > previous_time
                    else index / fps
                )
                time = (
                    max(time, previous_time + 1 / fps)
                    if time <= previous_time
                    else time
                )
                previous_time = time
                if index % frame_step:
                    continue
                height, width = frame.shape[:2]
                if width > 640:
                    frame = cv.resize(
                        frame,
                        (640, max(1, round(height * 640 / width))),
                        interpolation=cv.INTER_AREA,
                    )
                height, width = frame.shape[:2]
                image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=cv.cvtColor(frame, cv.COLOR_BGR2RGB),
                )
                timestamp = max(previous_timestamp + 1, round(time * 1000))
                previous_timestamp = timestamp
                detected = task.detect_for_video(image, timestamp)
                faces = [
                    _face_metrics(points, width, height)
                    for points in detected.face_landmarks
                ]
                metrics = faces[0] if faces else _face_metrics([], width, height)
                frames.append(
                    {
                        "frame": index,
                        "time": time,
                        "timestamp_ms": timestamp,
                        "face_count": len(faces),
                        "faces": faces,
                        **metrics,
                        "inference_width": width,
                        "inference_height": height,
                    }
                )
    finally:
        capture.release()
    if not decoded:
        raise ValueError("Source contains no decodable frames")
    intervals = []
    for frame in frames:
        if frame["acceptable"] is False:
            start, end = frame["time"], frame["time"] + 1 / fps
            if (
                intervals
                and frame_step == 1
                and abs(intervals[-1]["end"] - start) < 1e-6
            ):
                intervals[-1]["end"] = end
            else:
                intervals.append(
                    {
                        "start": start,
                        "end": end,
                        "reason": "low_gaze_proxy",
                        "review_only": True,
                    }
                )
    decode_incomplete = eof and reported_count > 0 and decoded < reported_count
    return {
        "frames": frames,
        "intervals": intervals,
        "frame_count": decoded,
        "automatic_removal": False,
        "sampled_frames": len(frames),
        "frame_step": frame_step,
        "coverage": {
            "complete": eof and frame_step == 1 and not decode_incomplete,
            "mode": "all_frames" if frame_step == 1 else "sampled",
            "decoded_frames": decoded,
            "source_frame_count_reported": reported_count,
            "reached_eof": eof,
            "truncated": not eof,
            "decode_incomplete": decode_incomplete,
        },
        "status": "decode_incomplete"
        if decode_incomplete
        else ("ok" if any(f["face_count"] for f in frames) else "no_face_detected"),
        "engine": "MediaPipe FaceLandmarker CPU VIDEO",
        "limitations": [
            "Gaze is an uncertain iris/head-facing proxy, not authenticated eye contact.",
            "Glasses, occlusion, lighting and face orientation can make scores unreliable.",
            "Thresholds are review-only; no frames are automatically removed, including no-face frames.",
            "Mouth opening is a geometric ratio, not a speech or audio detector.",
            "At most four faces are returned; identity is not tracked across frames.",
        ],
    }


def segment_person(
    source, segmentation_model, output, background=None, graphic=None, max_width=1280
):
    """Render every frame with a local selfie mask; outputs are opaque H.264 MP4."""
    deadline = monotonic() + VISION_TIMEOUT
    source = media._local_path(source)
    segmentation_model = media._local_path(segmentation_model)
    requested = Path(output).expanduser()
    output = media._local_path(requested, must_exist=False)
    if requested.is_symlink() or output.exists() or output.is_symlink():
        raise FileExistsError(f"Output already exists: {output}")
    if output.suffix.lower() != ".mp4":
        raise ValueError("Segmentation output must be an MP4 file")
    if type(max_width) is not int or max_width < 2:
        raise ValueError("max_width must be an integer of at least 2")
    for value, allow_color in ((background, True), (graphic, False)):
        if value is None:
            continue
        if allow_color and isinstance(value, str) and value.startswith("#"):
            if len(value) != 7 or any(
                c not in "0123456789abcdef" for c in value[1:].lower()
            ):
                raise ValueError("Background color must be #RRGGBB")
        else:
            media._local_path(value)
    metadata = media.probe(source)
    cv, mp, np = _dependencies()
    capture = cv.VideoCapture(str(source))
    writer = None
    decoded = detected_frames = 0
    fractions, mean_alphas = [], []
    directory = None
    try:
        if not capture.isOpened():
            raise ValueError("Cannot decode local video")
        fps = float(capture.get(cv.CAP_PROP_FPS))
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Video has no valid frame rate")
        width = min(metadata["width"], max_width)
        height = round(metadata["height"] * width / metadata["width"])
        width, height = max(2, width // 2 * 2), max(2, height // 2 * 2)
        background_layer = (
            _image_layer(background, width, height, cv, np)
            if background is not None
            else None
        )
        graphic_layer = (
            _image_layer(graphic, width, height, cv, np, graphic=True)
            if graphic is not None
            else None
        )
        directory = tempfile.TemporaryDirectory(
            prefix=".cutroom-vision-", dir=output.parent
        )
        silent = Path(directory.name) / "silent.mp4"
        encoded = Path(directory.name) / "encoded.mp4"
        writer = cv.VideoWriter(
            str(silent), cv.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
        )
        if not writer.isOpened():
            raise RuntimeError("Cannot open temporary video writer")
        options = mp.tasks.vision.ImageSegmenterOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(segmentation_model),
                delegate=mp.tasks.BaseOptions.Delegate.CPU,
            ),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            output_confidence_masks=True,
            output_category_mask=False,
        )
        with mp.tasks.vision.ImageSegmenter.create_from_options(options) as task:
            while True:
                if monotonic() > deadline:
                    raise TimeoutError("Segmentation processing deadline exceeded")
                ok, frame = capture.read()
                if not ok:
                    break
                frame = cv.resize(frame, (width, height), interpolation=cv.INTER_AREA)
                image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=cv.cvtColor(frame, cv.COLOR_BGR2RGB),
                )
                result = task.segment_for_video(image, round(decoded / fps * 1000))
                alpha = _person_mask(result, task.labels)
                if alpha.shape != (height, width):
                    alpha = cv.resize(
                        alpha, (width, height), interpolation=cv.INTER_LINEAR
                    )
                fraction = float(np.mean(alpha >= 0.5))
                fractions.append(fraction)
                mean_alphas.append(float(alpha.mean()))
                detected_frames += fraction >= 0.01
                writer.write(_composite(frame, alpha, background_layer, graphic_layer))
                decoded += 1
        writer.release()
        writer = None
        capture.release()
        if not decoded:
            raise ValueError("Source contains no decodable frames")
        media._run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-n",
                "-protocol_whitelist",
                "file",
                "-i",
                str(silent),
                *(
                    ["-protocol_whitelist", "file", "-i", str(source)]
                    if metadata["has_audio"]
                    else []
                ),
                "-map",
                "0:v:0",
                *(["-map", "1:a:0"] if metadata["has_audio"] else []),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-pix_fmt",
                "yuv420p",
                *(["-c:a", "aac"] if metadata["has_audio"] else ["-an"]),
                "-movflags",
                "+faststart",
                str(encoded),
            ]
        )
        rendered_metadata = media.probe(encoded)
        os.link(encoded, output)
        return {
            "output": str(output),
            **rendered_metadata,
            "status": "ok" if detected_frames else "no_person_detected",
            "engine": "MediaPipe ImageSegmenter CPU VIDEO (not SAM)",
            "compositing": {
                "layer_order": ["background", "graphic", "person"],
                "graphic_placement": "full-frame image stretched to output dimensions",
                "background_default": "original frame",
            },
            "segmentation": {
                "processed_frames": decoded,
                "written_frames": decoded,
                "person_detected_frames": detected_frames,
                "no_person_frames": decoded - detected_frames,
                "foreground_fraction_mean": sum(fractions) / decoded,
                "foreground_fraction_min": min(fractions),
                "foreground_fraction_max": max(fractions),
                "mean_alpha": sum(mean_alphas) / decoded,
                "confidence_threshold": 0.5,
                "minimum_person_fraction": 0.01,
                "fps": fps,
                "coverage": "all_decoded_frames",
            },
            "limitations": [
                "MediaPipe selfie segmentation is not SAM and may misclassify scenes without people.",
                "Soft masks are model estimates; hair, glasses and edges are not guaranteed accurate.",
                "No foreground is fabricated when the model produces an empty mask.",
                "MP4 is opaque; video is normalized to the decoder's constant frame rate.",
            ],
        }
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        if directory is not None:
            directory.cleanup()


def _image_layer(value, width, height, cv, np, *, graphic=False):
    """Load only local raster images; background hex colors are RGB."""
    if not graphic and isinstance(value, str) and value.startswith("#"):
        if len(value) != 7:
            raise ValueError("Background color must be #RRGGBB")
        try:
            rgb = tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))
        except ValueError as exc:
            raise ValueError("Background color must be #RRGGBB") from exc
        return np.full((height, width, 3), rgb[::-1], dtype=np.uint8)
    path = media._local_path(value)
    image = cv.imread(str(path), cv.IMREAD_UNCHANGED)
    if image is None or image.dtype != np.uint8:
        raise ValueError("Image must be a readable 8-bit local raster")
    if image.ndim == 2:
        image = cv.cvtColor(image, cv.COLOR_GRAY2BGRA if graphic else cv.COLOR_GRAY2BGR)
    elif image.ndim == 3 and image.shape[2] == 3 and graphic:
        image = cv.cvtColor(image, cv.COLOR_BGR2BGRA)
    elif image.ndim == 3 and image.shape[2] == 4 and not graphic:
        image = np.rint(image[..., :3] * (image[..., 3:4] / 255)).astype(np.uint8)
    if image.ndim != 3 or image.shape[2] != (4 if graphic else 3):
        raise ValueError("Unsupported local image channels")
    return cv.resize(image, (width, height), interpolation=cv.INTER_LINEAR)


def _person_mask(result, labels):
    """Read labelled person confidence; never synthesize a foreground on failure."""
    import numpy as np

    masks = result.confidence_masks or []
    indices = [
        i
        for i, label in enumerate(labels)
        if label.lower() in {"person", "selfie", "foreground"}
    ]
    if len(indices) != 1 or len(masks) != len(labels):
        raise ValueError("A labelled selfie/person confidence mask is required")
    alpha = np.asarray(masks[indices[0]].numpy_view(), dtype=np.float32).copy()
    if alpha.ndim == 3 and alpha.shape[2] == 1:
        alpha = alpha[..., 0]
    if alpha.ndim != 2 or not alpha.size or not np.isfinite(alpha).all():
        raise ValueError("Invalid person confidence mask")
    return np.clip(alpha, 0, 1)


def _composite(frame, alpha, background=None, graphic=None):
    """Blend BGR layers: background, then BGRA graphic, then person."""
    import numpy as np

    behind = (frame if background is None else background).astype(np.float32)
    if graphic is not None:
        graphic_alpha = graphic[..., 3:4].astype(np.float32) / 255
        behind = graphic[..., :3].astype(np.float32) * graphic_alpha + behind * (
            1 - graphic_alpha
        )
    alpha = np.clip(alpha, 0, 1)[..., None]
    return np.clip(
        np.rint(frame.astype(np.float32) * alpha + behind * (1 - alpha)), 0, 255
    ).astype(np.uint8)


def _face_metrics(points, width, height):
    """Measure iris/head symmetry and mouth opening in pixel coordinates."""
    unknown = {
        "gaze_score": None,
        "mouth_open": None,
        "acceptable": None,
        "review_only": True,
        "gaze_method": "iris/head-facing geometric proxy",
        "eye_contact_verified": False,
    }
    if len(points) < 478 or width <= 0 or height <= 0:
        return unknown
    if any(not math.isfinite(p.x) or not math.isfinite(p.y) for p in points):
        return unknown

    def xy(index):
        point = points[index]
        return point.x * width, point.y * height

    def distance(a, b):
        return math.dist(xy(a), xy(b))

    mouth_width = distance(61, 291)
    mouth_open = distance(13, 14) / mouth_width if mouth_width > 1e-6 else None
    left = tuple((a + b) / 2 for a, b in zip(xy(33), xy(133)))
    right = tuple((a + b) / 2 for a, b in zip(xy(362), xy(263)))
    eye_span = math.dist(left, right)
    if min(eye_span, distance(33, 133), distance(362, 263), mouth_width) < 1e-6:
        return unknown
    center = tuple((a + b) / 2 for a, b in zip(left, right))
    head_offset = math.dist((xy(1)[0], center[1]), center) / max(eye_span, 1e-6)
    iris_offset = (
        math.dist(xy(468), left) / max(distance(33, 133), 1e-6)
        + math.dist(xy(473), right) / max(distance(362, 263), 1e-6)
    ) / 2
    score = max(0.0, min(1.0, 1 - 2 * head_offset - 2 * iris_offset))
    return {
        "gaze_score": score,
        "mouth_open": mouth_open,
        "acceptable": score >= 0.55,
        "review_only": True,
        "gaze_method": "iris/head-facing geometric proxy",
        "eye_contact_verified": False,
    }
