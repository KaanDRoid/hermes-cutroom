import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cutroom import fanout
from cutroom import postproduction as pp


def ffmpeg(*arguments):
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", *arguments],
        check=True,
        capture_output=True,
        timeout=300,
    )


def make_source(path, seconds=40):
    ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=size=96x64:rate=25:duration={seconds}",
        "-f", "lavfi", "-i", f"anoisesrc=seed=7:sample_rate=48000:duration={seconds}",
        "-c:v", "libx264", "-g", "50", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(path),
    )  # fmt: skip


def cuts(count, seconds=40):
    step = seconds / count
    return [
        (round(i * step + 0.05, 3), round(i * step + step * 0.6, 3))
        for i in range(count)
    ]


class CutTreeEquivalenceTests(unittest.TestCase):
    """A tree of coarse trims gives exactly what direct reads give."""

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.source = cls.root / "source.mp4"
        make_source(cls.source)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def render(self, lines, label, fmt):
        script = self.root / "graph.txt"
        script.write_text(";\n".join(lines), encoding="utf-8")
        out = ffmpeg(
            "-i", str(self.source), "-/filter_complex", str(script),
            "-map", label, *fmt, "-",
        ).stdout  # fmt: skip
        if fmt[1] == "framemd5":
            out = b"\n".join(
                line for line in out.splitlines() if not line.startswith(b"#")
            )
        return hashlib.sha256(out).hexdigest(), len(out)

    def audio_graph(self, spans, branch):
        lines, inputs = fanout.cut_inputs(
            "[0:a:0]", spans, video=False, prefix="a", branch=branch
        )
        for i, ((start, end), (source, _)) in enumerate(zip(spans, inputs)):
            samples = round((end - start) * 48000)
            lines.append(
                f"{source}atrim=start={start}:end={end},asetpts=PTS-{start}/TB,"
                f"aresample=48000:async=1:first_pts=0,apad,"
                f"atrim=end_sample={samples}[a{i}]"
            )
        lines.append(
            "".join(f"[a{i}]" for i in range(len(spans)))
            + f"concat=n={len(spans)}:v=0:a=1[audio]"
        )
        return lines

    def video_graph(self, spans, branch):
        frames = [(round(a * 25), round(b * 25)) for a, b in spans]
        lines, inputs = fanout.cut_inputs(
            "[0:v:0]", frames, video=True, prefix="v", branch=branch
        )
        for i, ((first, stop), (source, offset)) in enumerate(zip(frames, inputs)):
            lines.append(
                f"{source}trim=start_frame={first - offset}:"
                f"end_frame={stop - offset},settb=1/25,setpts=N[v{i}]"
            )
        lines.append(
            "".join(f"[v{i}]" for i in range(len(frames)))
            + f"concat=n={len(frames)}:v=1:a=0[video]"
        )
        return lines

    def test_audio_is_sample_identical(self):
        spans = cuts(70)
        direct = self.render(self.audio_graph(spans, 1000), "[audio]", ["-f", "s16le"])
        tree = self.render(self.audio_graph(spans, 4), "[audio]", ["-f", "s16le"])
        self.assertEqual(direct, tree)

    def test_video_is_frame_identical(self):
        spans = cuts(70)
        direct = self.render(
            self.video_graph(spans, 1000), "[video]", ["-f", "framemd5"]
        )
        tree = self.render(self.video_graph(spans, 4), "[video]", ["-f", "framemd5"])
        self.assertEqual(direct, tree)

    def test_each_part_reads_the_stream_once(self):
        lines, inputs = fanout.cut_inputs(
            "[0:a:0]", cuts(70), video=False, prefix="a", branch=4
        )
        text = ";".join(lines)
        self.assertEqual(text.count("[0:a:0]"), 1)
        labels = [label for label, _ in inputs]
        self.assertEqual(len(set(labels)), 70)
        for label in labels:
            self.assertEqual(text.count(label), 1, label)

    def test_few_cuts_read_the_stream_directly(self):
        lines, inputs = fanout.cut_inputs(
            "[0:v:0]", [(0, 5), (9, 12)], video=True, prefix="v"
        )
        self.assertEqual(lines, [])
        self.assertEqual(inputs, [("[0:v:0]", 0), ("[0:v:0]", 0)])


class ManyCutsRenderTests(unittest.TestCase):
    def test_a_render_with_many_cuts_reads_each_input_stream_once(self):
        scripts = []
        real = pp._render_graph

        def capture(arguments, *, cwd, timeout):
            name = arguments[arguments.index("-/filter_complex") + 1]
            scripts.append((Path(cwd) / name).read_text(encoding="utf-8"))
            return real(arguments, cwd=cwd, timeout=timeout)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            make_source(source, seconds=30)
            segments = [{"start": a, "end": b} for a, b in cuts(60, seconds=30)]
            with mock.patch.object(pp, "_render_graph", side_effect=capture):
                result = pp.export_video(source, segments, root / "out.mp4")
            expected = sum(b - a for a, b in cuts(60, seconds=30))
            self.assertAlmostEqual(result["duration"], expected, delta=0.25)
        self.assertTrue(scripts)
        for script in scripts:
            self.assertLessEqual(script.count("[0:a:0]"), 1, script[:300])
            self.assertLessEqual(script.count("[0:v:0]"), 1, script[:300])

    def test_paced_renders_with_many_cuts_read_the_video_once(self):
        scripts = []
        real = pp._render_graph

        def capture(arguments, *, cwd, timeout):
            name = arguments[arguments.index("-/filter_complex") + 1]
            scripts.append((Path(cwd) / name).read_text(encoding="utf-8"))
            return real(arguments, cwd=cwd, timeout=timeout)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            make_source(source, seconds=30)
            segments = [{"start": a, "end": b} for a, b in cuts(40, seconds=30)]
            with mock.patch.object(pp, "_render_graph", side_effect=capture):
                result = pp.export_video(
                    source,
                    segments,
                    root / "paced.mp4",
                    {
                        "preset": "preview",
                        "normalize_audio": False,
                        "pacing": {"transition": "crossfade"},
                    },
                )
            self.assertGreater(result["duration"], 10)
        render = [script for script in scripts if "[joined]" in script]
        self.assertTrue(render)
        for script in render:
            self.assertEqual(script.count("[0:v:0]"), 1, script[:300])
            self.assertLessEqual(script.count("[0:a:0]"), 1, script[:300])

    def test_the_segment_tool_reads_each_stream_once(self):
        from cutroom import media

        seen = []
        real = media._run

        def capture(arguments, *args, **kwargs):
            if "-filter_complex" in arguments:
                seen.append(arguments[arguments.index("-filter_complex") + 1])
            return real(arguments, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            make_source(source, seconds=30)
            segments = [{"start": a, "end": b} for a, b in cuts(40, seconds=30)]
            with mock.patch.object(media, "_run", side_effect=capture):
                result = media.render(source, segments, root / "cut.mp4")
            expected = sum(b - a for a, b in cuts(40, seconds=30))
            self.assertAlmostEqual(result["duration"], expected, delta=0.5)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].count("[0:v:0]"), 1)
        self.assertEqual(seen[0].count("[0:a:0]"), 1)


if __name__ == "__main__":
    unittest.main()
