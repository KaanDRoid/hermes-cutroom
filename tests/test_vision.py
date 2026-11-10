"""Vision tests; real-model acceptance uses only existing local assets."""

import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class FakeFrame:
    def __init__(self, width=1920, height=1080):
        self.shape = (height, width, 3)


class FakeCapture:
    def __init__(self, count=4, fps=25.0):
        self.count, self.fps, self.position, self.closed = count, fps, 0, False

    def isOpened(self):
        return True

    def get(self, key):
        return {1: self.fps, 2: self.count, 3: 0.0}.get(key, 0)

    def read(self):
        if self.position >= self.count:
            return False, None
        self.position += 1
        return True, FakeFrame()

    def release(self):
        self.closed = True


class FakeTask:
    def __init__(self, faces=None):
        self.calls, self.closed = [], False
        self.faces = faces or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def detect_for_video(self, image, timestamp):
        self.calls.append((image.shape, timestamp))
        return SimpleNamespace(face_landmarks=self.faces)


def fake_dependencies(capture, task):
    options = {}

    def create(**kwargs):
        options.update(kwargs)
        return kwargs

    cv = SimpleNamespace(
        VideoCapture=lambda _: capture,
        CAP_PROP_FPS=1,
        CAP_PROP_FRAME_COUNT=2,
        CAP_PROP_POS_MSEC=3,
        COLOR_BGR2RGB=4,
        INTER_AREA=5,
        resize=lambda frame, size, **kwargs: FakeFrame(*size),
        cvtColor=lambda frame, _: frame,
    )
    mp = SimpleNamespace(
        Image=lambda **kwargs: kwargs["data"],
        ImageFormat=SimpleNamespace(SRGB=1),
        tasks=SimpleNamespace(
            BaseOptions=lambda **kwargs: kwargs,
            vision=SimpleNamespace(
                RunningMode=SimpleNamespace(VIDEO="VIDEO"),
                FaceLandmarkerOptions=create,
                FaceLandmarker=SimpleNamespace(create_from_options=lambda _: task),
            ),
        ),
    )
    mp.tasks.BaseOptions.Delegate = SimpleNamespace(CPU="CPU")
    return (cv, mp, None), options


def landmarks():
    points = [SimpleNamespace(x=0.5, y=0.5, z=0.0) for _ in range(478)]
    for index, xy in {
        33: (0.25, 0.4),
        133: (0.4, 0.4),
        362: (0.6, 0.4),
        263: (0.75, 0.4),
        468: (0.325, 0.4),
        473: (0.675, 0.4),
        1: (0.5, 0.5),
        61: (0.4, 0.6),
        291: (0.6, 0.6),
        13: (0.5, 0.59),
        14: (0.5, 0.61),
    }.items():
        points[index] = SimpleNamespace(x=xy[0], y=xy[1], z=0.0)
    return points


class FaceGeometryTests(unittest.TestCase):
    def test_mouth_ratio_uses_pixel_geometry_and_gaze_is_only_proxy(self):
        vision = importlib.import_module("cutroom.vision")
        result = vision._face_metrics(landmarks(), 400, 200)
        self.assertAlmostEqual(result["mouth_open"], 0.05)
        self.assertGreater(result["gaze_score"], 0.9)
        self.assertTrue(result["acceptable"])
        self.assertTrue(result["review_only"])
        self.assertIn("proxy", result["gaze_method"])
        self.assertFalse(result["eye_contact_verified"])

    def test_missing_or_degenerate_landmarks_are_unknown_not_rejected(self):
        vision = importlib.import_module("cutroom.vision")
        for points in [[], landmarks()[:468], [SimpleNamespace(x=0.0, y=0.0)] * 478]:
            with self.subTest(count=len(points)):
                result = vision._face_metrics(points, 640, 480)
                self.assertIsNone(result["gaze_score"])
                self.assertIsNone(result["acceptable"])
        points = landmarks()
        points[468].x += 0.065
        points[473].x += 0.065
        self.assertLess(vision._face_metrics(points, 400, 200)["gaze_score"], 0.55)


class FacePipelineTests(unittest.TestCase):
    def test_every_frame_no_face_is_unknown_with_exact_coverage(self):
        vision = importlib.import_module("cutroom.vision")
        capture, task = FakeCapture(), FakeTask()
        deps, options = fake_dependencies(capture, task)
        with tempfile.TemporaryDirectory() as directory:
            source, model = (
                Path(directory) / "source.mp4",
                Path(directory) / "face.task",
            )
            source.touch()
            model.touch()
            with patch.object(vision, "_dependencies", return_value=deps, create=True):
                result = vision.analyze_faces(source, model)
        self.assertEqual(result["frame_count"], 4)
        self.assertEqual(result["sampled_frames"], 4)
        self.assertEqual([f["frame"] for f in result["frames"]], [0, 1, 2, 3])
        self.assertEqual(result["status"], "no_face_detected")
        self.assertEqual(result["intervals"], [])
        self.assertTrue(result["coverage"]["complete"])
        self.assertEqual(result["coverage"]["mode"], "all_frames")
        self.assertTrue(all(f["acceptable"] is None for f in result["frames"]))
        self.assertTrue(all(f["gaze_score"] is None for f in result["frames"]))
        self.assertEqual([call[1] for call in task.calls], [0, 40, 80, 120])
        self.assertTrue(all(call[0][1] <= 640 for call in task.calls))
        self.assertEqual(options["running_mode"], "VIDEO")
        self.assertEqual(
            options["base_options"]["model_asset_path"], str(model.resolve())
        )
        self.assertEqual(options["base_options"]["delegate"], "CPU")
        self.assertTrue(capture.closed)
        self.assertTrue(task.closed)

    def test_low_gaze_is_review_interval_not_automatic_removal(self):
        vision = importlib.import_module("cutroom.vision")
        points = landmarks()
        points[1].x = 0.7
        capture, task = FakeCapture(count=5), FakeTask([points])
        deps, _ = fake_dependencies(capture, task)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video"
            source.touch()
            with patch.object(vision, "_dependencies", return_value=deps):
                result = vision.analyze_faces(
                    source, source, frame_step=2, max_frames=3
                )
        self.assertEqual(result["sampled_frames"], 2)
        self.assertEqual(result["frame_count"], 3)
        self.assertTrue(result["coverage"]["truncated"])
        self.assertFalse(result["coverage"]["complete"])
        self.assertEqual(result["coverage"]["mode"], "sampled")
        self.assertEqual(len(result["intervals"]), 2)
        self.assertEqual(result["intervals"][0]["start"], 0.0)
        self.assertAlmostEqual(result["intervals"][0]["end"], 0.04)
        self.assertEqual(result["intervals"][1]["start"], 0.08)
        self.assertTrue(all(i["review_only"] for i in result["intervals"]))
        self.assertTrue(
            all(i["reason"] == "low_gaze_proxy" for i in result["intervals"])
        )
        self.assertFalse(result["automatic_removal"])

    def test_face_processing_deadline_releases_capture_and_task(self):
        vision = importlib.import_module("cutroom.vision")
        capture, task = FakeCapture(), FakeTask()
        deps, _ = fake_dependencies(capture, task)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video"
            source.touch()
            with (
                patch.object(vision, "_dependencies", return_value=deps),
                patch.object(vision, "VISION_TIMEOUT", -1),
            ):
                with self.assertRaises(TimeoutError):
                    vision.analyze_faces(source, source)
        self.assertTrue(capture.closed)
        self.assertTrue(task.closed)

    def test_empty_decode_is_error_not_no_face_success(self):
        vision = importlib.import_module("cutroom.vision")
        capture, task = FakeCapture(count=0), FakeTask()
        deps, _ = fake_dependencies(capture, task)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video"
            source.touch()
            with patch.object(vision, "_dependencies", return_value=deps):
                with self.assertRaisesRegex(ValueError, "no decodable frames"):
                    vision.analyze_faces(source, source)
        self.assertTrue(capture.closed)

    def test_early_decoder_stop_does_not_claim_complete_coverage(self):
        vision = importlib.import_module("cutroom.vision")
        capture, task = FakeCapture(count=5), FakeTask()
        original_read = capture.read
        capture.read = lambda: (
            (False, None) if capture.position == 3 else original_read()
        )
        deps, _ = fake_dependencies(capture, task)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video"
            source.touch()
            with patch.object(vision, "_dependencies", return_value=deps):
                result = vision.analyze_faces(source, source)
        self.assertEqual(result["frame_count"], 3)
        self.assertFalse(result["coverage"]["complete"])
        self.assertTrue(result["coverage"]["decode_incomplete"])
        self.assertEqual(result["status"], "decode_incomplete")

    def test_invalid_limits_rejected_before_native_dependency_loading(self):
        vision = importlib.import_module("cutroom.vision")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video"
            source.touch()
            for kwargs in [
                {"frame_step": 0},
                {"frame_step": 1.5},
                {"frame_step": True},
                {"max_frames": 0},
                {"max_frames": False},
            ]:
                with self.subTest(kwargs=kwargs):
                    with patch.object(
                        vision,
                        "_dependencies",
                        side_effect=AssertionError("must validate first"),
                    ):
                        with self.assertRaises(ValueError):
                            vision.analyze_faces(source, source, **kwargs)


class RealFaceAcceptanceTests(unittest.TestCase):
    def test_local_woman_clip_real_cpu_every_frame(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "raw_vids/4439224-uhd_2160_3840_25fps.mp4"
        model = root / "models/face_landmarker.task"
        if (
            not source.is_file()
            or not model.is_file()
            or not importlib.util.find_spec("mediapipe")
        ):
            self.skipTest("Local consent clip, model or native dependencies are absent")
        vision = importlib.import_module("cutroom.vision")
        result = vision.analyze_faces(source, model)
        self.assertEqual(result["frame_count"], 264)
        self.assertEqual(result["sampled_frames"], 264)
        self.assertTrue(result["coverage"]["complete"])
        self.assertGreater(sum(f["face_count"] > 0 for f in result["frames"]), 200)
        self.assertTrue(all(f["inference_width"] <= 640 for f in result["frames"]))
        self.assertTrue(
            all(
                a["timestamp_ms"] < b["timestamp_ms"]
                for a, b in zip(result["frames"], result["frames"][1:])
            )
        )
        self.assertTrue(all(not f["eye_contact_verified"] for f in result["frames"]))
        print(
            "REAL_FACE",
            {
                "frames": result["frame_count"],
                "faces_present": sum(f["face_count"] > 0 for f in result["frames"]),
                "review_intervals": result["intervals"],
            },
        )

    def test_local_river_clip_no_face_is_not_removed(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "raw_vids/12511-239934660.mp4"
        model = root / "models/face_landmarker.task"
        if (
            not source.is_file()
            or not model.is_file()
            or not importlib.util.find_spec("mediapipe")
        ):
            self.skipTest("Local river clip, model or native dependencies are absent")
        result = importlib.import_module("cutroom.vision").analyze_faces(
            source, model, max_frames=12
        )
        self.assertEqual(result["status"], "no_face_detected")
        self.assertEqual(result["intervals"], [])
        self.assertTrue(all(f["acceptable"] is None for f in result["frames"]))


class CompositeTests(unittest.TestCase):
    def test_graphic_is_behind_soft_foreground_and_empty_mask_is_honest(self):
        if not importlib.util.find_spec("numpy"):
            self.skipTest("NumPy is absent")
        import numpy as np

        vision = importlib.import_module("cutroom.vision")
        frame = np.full((1, 3, 3), [10, 20, 30], dtype=np.uint8)
        background = np.full_like(frame, [100, 110, 120])
        graphic = np.full((1, 3, 4), [200, 210, 220, 255], dtype=np.uint8)
        alpha = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)
        composed = vision._composite(frame, alpha, background, graphic)
        np.testing.assert_array_equal(composed[0, 0], [200, 210, 220])
        np.testing.assert_array_equal(composed[0, 1], [105, 115, 125])
        np.testing.assert_array_equal(composed[0, 2], frame[0, 2])
        no_person = vision._composite(frame, np.zeros((1, 3)), background, graphic)
        np.testing.assert_array_equal(no_person, graphic[..., :3])
        transparent = graphic.copy()
        transparent[..., 3] = 0
        np.testing.assert_array_equal(
            vision._composite(frame, np.zeros((1, 3)), background, transparent),
            background,
        )
        np.testing.assert_array_equal(
            vision._composite(frame, np.zeros((1, 3)), None, None), frame
        )

    def test_confidence_mask_mapping_uses_person_label_and_preserves_empty_mask(self):
        if not importlib.util.find_spec("numpy"):
            self.skipTest("NumPy is absent")
        import numpy as np

        vision = importlib.import_module("cutroom.vision")
        empty = np.zeros((2, 3, 1), dtype=np.float32)
        image = SimpleNamespace(numpy_view=lambda: empty)
        result = SimpleNamespace(confidence_masks=[image])
        np.testing.assert_array_equal(
            vision._person_mask(result, ["selfie"]), empty[..., 0]
        )
        full = SimpleNamespace(numpy_view=lambda: np.ones((2, 3, 1), dtype=np.float32))
        result.confidence_masks = [full, image]
        np.testing.assert_array_equal(
            vision._person_mask(result, ["background", "person"]), empty[..., 0]
        )
        with self.assertRaises(ValueError):
            vision._person_mask(result, ["background", "unknown"])
        result.confidence_masks = []
        with self.assertRaises(ValueError):
            vision._person_mask(result, ["selfie"])


class SegmentationPipelineTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.model = self.root / "models/selfie_segmenter.tflite"
        if not self.model.is_file() or not importlib.util.find_spec("mediapipe"):
            self.skipTest("Local selfie model or native dependencies are absent")
        import cv2
        import numpy as np

        self.cv, self.np = cv2, np
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "source.mp4"
        self.output = Path(self.directory.name) / "output.mp4"
        writer = cv2.VideoWriter(
            str(self.source), cv2.VideoWriter_fourcc(*"mp4v"), 25, (64, 48)
        )
        self.assertTrue(writer.isOpened())
        for _ in range(4):
            writer.write(np.full((48, 64, 3), [255, 0, 0], dtype=np.uint8))
        writer.release()

    def test_empty_scene_processes_all_frames_and_publishes_real_h264_no_overwrite(
        self,
    ):
        vision = importlib.import_module("cutroom.vision")
        result = vision.segment_person(
            self.source, self.model, self.output, background="#112233"
        )
        self.assertTrue(self.output.is_file())
        self.assertEqual(result["status"], "no_person_detected")
        self.assertFalse(result["has_audio"])
        self.assertEqual(result["segmentation"]["processed_frames"], 4)
        self.assertEqual(result["segmentation"]["person_detected_frames"], 0)
        self.assertEqual(result["segmentation"]["no_person_frames"], 4)
        self.assertEqual(result["width"], 64)
        self.assertEqual(result["height"], 48)
        self.assertAlmostEqual(result["duration"], 0.16, places=2)
        self.assertIn("MediaPipe", result["engine"])
        cap = self.cv.VideoCapture(str(self.output))
        decoded = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            decoded.append(frame)
        cap.release()
        self.assertEqual(len(decoded), 4)
        self.np.testing.assert_allclose(decoded[0][24, 32], [51, 34, 17], atol=4)
        import json

        streams = json.loads(
            vision.media._run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-of",
                    "json",
                    str(self.output),
                ]
            ).stdout
        )["streams"]
        self.assertEqual(streams[0]["codec_name"], "h264")
        before = self.output.read_bytes()
        with self.assertRaises(FileExistsError):
            vision.segment_person(self.source, self.model, self.output)
        self.assertEqual(self.output.read_bytes(), before)
        self.assertEqual(
            {p.name for p in Path(self.directory.name).iterdir()},
            {"source.mp4", "output.mp4"},
        )

    def test_local_background_and_alpha_graphic_are_loaded_as_layers(self):
        vision = importlib.import_module("cutroom.vision")
        background = Path(self.directory.name) / "background.png"
        graphic = Path(self.directory.name) / "graphic.png"
        self.assertTrue(
            self.cv.imwrite(
                str(background),
                self.np.full((4, 4, 3), [100, 110, 120], dtype=self.np.uint8),
            )
        )
        self.assertTrue(
            self.cv.imwrite(
                str(graphic),
                self.np.full((4, 4, 4), [200, 210, 220, 128], dtype=self.np.uint8),
            )
        )
        result = vision.segment_person(
            self.source, self.model, self.output, background=background, graphic=graphic
        )
        self.assertEqual(result["status"], "no_person_detected")
        cap = self.cv.VideoCapture(str(self.output))
        ok, frame = cap.read()
        cap.release()
        self.assertTrue(ok)
        self.np.testing.assert_allclose(frame[24, 32], [150, 160, 170], atol=5)
        self.assertEqual(
            result["compositing"]["layer_order"], ["background", "graphic", "person"]
        )

    def test_synthetic_audio_is_preserved_without_changing_video_frame_count(self):
        vision = importlib.import_module("cutroom.vision")
        audible = Path(self.directory.name) / "synthetic-audio.mp4"
        vision.media._run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-n",
                "-i",
                str(self.source),
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=0.16",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                str(audible),
            ]
        )
        result = vision.segment_person(audible, self.model, self.output)
        self.assertTrue(result["has_audio"])
        self.assertEqual(result["segmentation"]["processed_frames"], 4)
        stats = vision.media._run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-i",
                str(self.output),
                "-vn",
                "-af",
                "astats",
                "-f",
                "null",
                "-",
            ]
        ).stderr
        self.assertIn("RMS level dB:", stats)
        self.assertNotIn("RMS level dB: -inf", stats)

    def test_processing_deadline_aborts_without_publishing_or_leaking_files(self):
        vision = importlib.import_module("cutroom.vision")
        with patch.object(vision, "VISION_TIMEOUT", -1, create=True):
            with self.assertRaises(TimeoutError):
                vision.segment_person(self.source, self.model, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(
            {p.name for p in Path(self.directory.name).iterdir()}, {"source.mp4"}
        )


class SegmentationValidationTests(unittest.TestCase):
    def test_invalid_width_and_nonlocal_images_fail_before_probing_or_loading(self):
        vision = importlib.import_module("cutroom.vision")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.touch()
            output = Path(directory) / "output.mp4"
            cases = [{"max_width": value} for value in (0, 1, True, 3.5)]
            cases += [
                {"background": "https://example.org/bg.png"},
                {"graphic": "https://example.org/graphic.png"},
                {"background": "#GG0000"},
                {"background": "#123"},
            ]
            for kwargs in cases:
                with (
                    self.subTest(kwargs=kwargs),
                    patch.object(
                        vision.media,
                        "probe",
                        side_effect=AssertionError("must validate first"),
                    ),
                ):
                    with self.assertRaises(ValueError):
                        vision.segment_person(source, source, output, **kwargs)
            self.assertFalse(output.exists())


class RealSegmentationAcceptanceTests(unittest.TestCase):
    def test_woman_all_264_frames_keep_subject_in_front_of_graphic(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "raw_vids/4439224-uhd_2160_3840_25fps.mp4"
        model = root / "models/selfie_segmenter.tflite"
        if (
            not source.is_file()
            or not model.is_file()
            or not importlib.util.find_spec("mediapipe")
        ):
            self.skipTest("Local consent clip, model or native dependencies are absent")
        import cv2
        import mediapipe as mp
        import numpy as np

        vision = importlib.import_module("cutroom.vision")
        with tempfile.TemporaryDirectory() as directory:
            graphic = Path(directory) / "behind.png"
            output = Path(directory) / "composite.mp4"
            self.assertTrue(
                cv2.imwrite(
                    str(graphic), np.full((8, 8, 4), [0, 255, 0, 255], dtype=np.uint8)
                )
            )
            result = vision.segment_person(
                source,
                model,
                output,
                background="#FF0000",
                graphic=graphic,
                max_width=320,
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["segmentation"]["processed_frames"], 264)
            self.assertEqual(result["segmentation"]["person_detected_frames"], 264)
            self.assertFalse(result["has_audio"])
            self.assertEqual((result["width"], result["height"]), (320, 568))
            self.assertAlmostEqual(result["duration"], 10.56, places=2)
            cap = cv2.VideoCapture(str(output))
            count, rendered_first = 0, None
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if rendered_first is None:
                    rendered_first = frame
                count += 1
            cap.release()
            self.assertEqual(count, 264)
            cap = cv2.VideoCapture(str(source))
            ok, original = cap.read()
            cap.release()
            self.assertTrue(ok)
            original = cv2.resize(original, (320, 568), interpolation=cv2.INTER_AREA)
            options = mp.tasks.vision.ImageSegmenterOptions(
                base_options=mp.tasks.BaseOptions(
                    model_asset_path=str(model),
                    delegate=mp.tasks.BaseOptions.Delegate.CPU,
                ),
                output_confidence_masks=True,
            )
            with mp.tasks.vision.ImageSegmenter.create_from_options(
                options
            ) as segmenter:
                detected = segmenter.segment(
                    mp.Image(
                        image_format=mp.ImageFormat.SRGB,
                        data=cv2.cvtColor(original, cv2.COLOR_BGR2RGB),
                    )
                )
                alpha = vision._person_mask(detected, segmenter.labels)
            foreground, background = alpha > 0.999, alpha < 0.001
            self.assertGreater(int(foreground.sum()), 1000)
            self.assertGreater(int(background.sum()), 1000)
            foreground_error = float(
                np.abs(rendered_first.astype(float) - original)[foreground].mean()
            )
            graphic_error = float(
                np.abs(rendered_first.astype(float) - [0, 255, 0])[background].mean()
            )
            self.assertLess(foreground_error, 8)
            self.assertLess(graphic_error, 5)
            print(
                "REAL_SEGMENTATION",
                {
                    **result["segmentation"],
                    "foreground_error": foreground_error,
                    "graphic_error": graphic_error,
                },
            )


if __name__ == "__main__":
    unittest.main()
