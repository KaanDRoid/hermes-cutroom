"""Thumbnail previews have a bounded, serialized, project-local cache."""

import concurrent.futures
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom.studio import Studio


class ThumbnailCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / "source.mp4"
        source.write_bytes(b"unit source fixture")
        self.studio = Studio(self.root / "workspace")
        with patch("cutroom.studio.probe", return_value={"duration": 200}):
            self.project = self.studio.create(source)
        self.pid = self.project["id"]
        self.directory = self.studio._directory(self.pid) / "posters"

    @staticmethod
    def make(source, moment, output, **kwargs):
        Path(output).write_bytes(b"\xff\xd8" + b"x" * 30)
        return {"source_size": [1920, 1080]}

    def test_count_budget_evicts_old_pairs_and_preserves_foreign_files(self):
        self.directory.mkdir()
        foreign = self.directory / "poster-user.jpg"
        foreign.write_bytes(b"leave alone")
        with (
            patch("cutroom.studio.THUMBNAIL_CACHE_MAX_ENTRIES", 3, create=True),
            patch("cutroom.longform.make_thumbnail", side_effect=self.make),
        ):
            for i in range(8):
                self.studio.thumbnail_preview(self.pid, time=i, text=f"Title {i}")
        self.assertLessEqual(len(list(self.directory.glob("thumbnail-*.jpg"))), 3)
        self.assertLessEqual(len(list(self.directory.glob("thumbnail-*.json"))), 3)
        self.assertEqual(foreign.read_bytes(), b"leave alone")

    def test_byte_budget_bounds_total_jpeg_and_metadata_bytes(self):
        with (
            patch("cutroom.studio.THUMBNAIL_CACHE_MAX_BYTES", 130, create=True),
            patch("cutroom.longform.make_thumbnail", side_effect=self.make),
        ):
            for i in range(8):
                self.studio.thumbnail_preview(self.pid, time=i)
        self.assertLessEqual(
            sum(p.stat().st_size for p in self.directory.glob("thumbnail-*")), 130
        )

    def test_abandoned_thumbnail_temporary_is_removed_under_the_lock(self):
        self.directory.mkdir()
        abandoned = self.directory / (".thumbnail-" + "a" * 32 + ".jpg")
        abandoned.write_bytes(b"incomplete thumbnail")
        with patch("cutroom.longform.make_thumbnail", side_effect=self.make):
            self.studio.thumbnail_preview(self.pid, time=1)
        self.assertFalse(abandoned.exists())

    def test_recently_read_pair_survives_lru_pruning(self):
        with (
            patch("cutroom.studio.THUMBNAIL_CACHE_MAX_ENTRIES", 2),
            patch("cutroom.longform.make_thumbnail", side_effect=self.make) as make,
        ):
            self.studio.thumbnail_preview(self.pid, time=1)
            self.studio.thumbnail_preview(self.pid, time=2)
            self.studio.thumbnail_preview(self.pid, time=1)
            self.studio.thumbnail_preview(self.pid, time=3)
            self.studio.thumbnail_preview(self.pid, time=1)
            self.assertEqual(make.call_count, 3)
            self.studio.thumbnail_preview(self.pid, time=2)
            self.assertEqual(make.call_count, 4)

    def test_pruner_refuses_an_outside_cache_entry_without_unlinking(self):
        from cutroom.studio import _prune_thumbnail_cache

        self.directory.mkdir()
        outside = self.root / ("thumbnail-" + "a" * 24 + ".jpg")
        outside.write_bytes(b"not a cache entry")
        with patch.object(Path, "iterdir", return_value=iter([outside])):
            with self.assertRaises(PermissionError):
                _prune_thumbnail_cache(self.directory)
        self.assertEqual(outside.read_bytes(), b"not a cache entry")

    def test_concurrent_different_keys_stay_within_budget(self):
        with (
            patch("cutroom.studio.THUMBNAIL_CACHE_MAX_ENTRIES", 2),
            patch("cutroom.longform.make_thumbnail", side_effect=self.make),
        ):
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(
                    pool.map(
                        lambda i: self.studio.thumbnail_preview(self.pid, time=i),
                        range(8),
                    )
                )
        self.assertEqual(len(results), 8)
        self.assertLessEqual(len(list(self.directory.glob("thumbnail-*.jpg"))), 2)
        self.assertFalse(list(self.directory.glob(".*.jpg")))

    def test_concurrent_same_key_is_generated_only_once(self):
        def slow_make(*args, **kwargs):
            time.sleep(0.05)
            return self.make(*args, **kwargs)

        with patch("cutroom.longform.make_thumbnail", side_effect=slow_make) as make:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(
                    pool.map(
                        lambda _: self.studio.thumbnail_preview(self.pid, time=1),
                        range(4),
                    )
                )
        self.assertEqual(make.call_count, 1)
        self.assertEqual(len({r["data_url"] for r in results}), 1)
