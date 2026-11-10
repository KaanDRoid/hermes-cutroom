import unittest

from cutroom.plan import build_plan, validate_plan


class PlanTests(unittest.TestCase):
    def test_silence_is_removed_with_speech_padding(self):
        plan = build_plan(
            "clip.mp4", {"duration": 10.0}, [{"start": 2.0, "end": 4.0}], padding=0.1
        )
        self.assertEqual(
            plan["segments"], [{"start": 0.0, "end": 2.1}, {"start": 3.9, "end": 10.0}]
        )
        self.assertAlmostEqual(plan["output_duration"], 8.2)
        self.assertEqual(plan["status"], "draft")

    def test_invalid_timelines_are_rejected(self):
        for segments in (
            [],
            [{"start": -1, "end": 2}],
            [{"start": 0, "end": float("nan")}],
            [{"start": 0, "end": 11}],
            [{"start": 0, "end": 4}, {"start": 3, "end": 5}],
        ):
            with self.subTest(segments=segments):
                with self.assertRaises(ValueError):
                    validate_plan(
                        {
                            "version": 1,
                            "source": "clip.mp4",
                            "source_duration": 10,
                            "segments": segments,
                        }
                    )

    def test_silence_inputs_are_bounded_and_order_independent(self):
        self.assertEqual(
            build_plan(
                "clip.mp4",
                {"duration": 5},
                [{"start": 3, "end": 4}, {"start": 1, "end": 2}],
                padding=0,
            )["segments"],
            [
                {"start": 0.0, "end": 1.0},
                {"start": 2.0, "end": 3.0},
                {"start": 4.0, "end": 5.0},
            ],
        )
        for padding in (-1, float("nan")):
            with self.assertRaises(ValueError):
                build_plan("clip.mp4", {"duration": 5}, [], padding=padding)
        with self.assertRaises(ValueError):
            build_plan("clip.mp4", {"duration": 5}, [{"start": 0, "end": 5}], padding=0)


if __name__ == "__main__":
    unittest.main()
