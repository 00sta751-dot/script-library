#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 1 G2：active source TTL / dedup / rank 回歸測試。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
LIB = HERE.parent
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

import gen_topic_intel_projection as projection  # noqa: E402
from topic_distributor import (  # noqa: E402
    _load_owner_content_profile,
    apply_hybrid_profile,
)


def _raw(video_id: str, *, topic_id: str = "", rich: bool = True) -> dict:
    data = {
        "status": "pending",
        "pipeline_status": "success",
        "platform": "IG",
        "video_id": video_id,
        "url": f"https://example.com/{video_id}",
        "title": f"題目 {video_id}",
        "discovery_date": "2026-07-10",
        "confidence": 90,
        "transferability_score": 0.9,
        "applicable_owners": ["測試業主"],
        "industry": "測試業",
        "transcript_preview": "逐字稿",
        "supporting_data": {},
        "dissect": {},
    }
    if topic_id:
        data["topic_id"] = topic_id
    if rich:
        data["supporting_data"] = {
            "view_count": 1,
            "like_count": 1,
            "comment_count": 1,
        }
        data["dissect"] = {
            "hook_structure": "hook",
            "narrative_arc": "arc",
            "audio_features": "audio",
            "editing_rhythm": "rhythm",
        }
    return data


def _write_source(
    root: Path,
    name: str,
    data: dict,
    mtime: datetime,
    source_sha256: str,
) -> tuple[Path, str]:
    path = root / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    ts = mtime.timestamp()
    os.utime(path, (ts, ts))
    return path, source_sha256


class Stage1ProjectionRankTests(unittest.TestCase):
    NOW = datetime(2026, 7, 10, 4, 0, tzinfo=timezone.utc)

    def test_ttl_boundary_is_inclusive_and_older_item_expires(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [
                _write_source(
                    root,
                    "boundary.yaml",
                    _raw("boundary"),
                    self.NOW - timedelta(days=30),
                    "a" * 64,
                ),
                _write_source(
                    root,
                    "expired.yaml",
                    _raw("expired"),
                    self.NOW - timedelta(days=30, seconds=1),
                    "b" * 64,
                ),
            ]
            prepared, stats = projection._prepare_active_sources(
                entries, now_utc=self.NOW
            )
            self.assertEqual([row["source_sha256"] for row in prepared], ["a" * 64])
            self.assertEqual(stats["expired_count"], 1)
            self.assertEqual(stats["canonical_count"], 1)

    def test_duplicate_uses_latest_mtime_then_sha_ascending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = self.NOW - timedelta(hours=1)
            entries = [
                _write_source(
                    root,
                    "old.yaml",
                    _raw("same-video"),
                    self.NOW - timedelta(days=1),
                    "0" * 64,
                ),
                _write_source(
                    root,
                    "latest_b.yaml",
                    _raw("same-video"),
                    latest,
                    "b" * 64,
                ),
                _write_source(
                    root,
                    "latest_c.yaml",
                    _raw("same-video"),
                    latest,
                    "c" * 64,
                ),
            ]
            prepared, stats = projection._prepare_active_sources(
                entries, now_utc=self.NOW
            )
            self.assertEqual(len(prepared), 1)
            self.assertEqual(prepared[0]["source_sha256"], "b" * 64)
            self.assertEqual(stats["duplicate_count"], 2)

    def test_rank_uses_fixed_features_and_duplicate_key_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mtime = self.NOW - timedelta(hours=1)
            entries = [
                _write_source(root, "rich.yaml", _raw("rich"), mtime, "d" * 64),
                _write_source(
                    root, "poor.yaml", _raw("poor", rich=False), mtime, "e" * 64
                ),
            ]
            prepared, _ = projection._prepare_active_sources(
                entries, now_utc=self.NOW
            )
            self.assertEqual(prepared[0]["source_sha256"], "d" * 64)
            self.assertGreater(prepared[0]["rank_score"], prepared[1]["rank_score"])

        self.assertEqual(
            projection._candidate_duplicate_key(
                {"platform": "IG", "video_id": " ABC "}, "f" * 64
            ),
            "platform_video:ig:abc",
        )
        self.assertEqual(
            projection._candidate_duplicate_key(
                {"url": " HTTPS://EXAMPLE.COM/V "}, "f" * 64
            ),
            "url:https://example.com/v",
        )
        self.assertEqual(
            projection._candidate_duplicate_key({}, "f" * 64),
            "sha256:" + "f" * 64,
        )

    def test_projection_v2_preserves_adapter_topic_id_and_fingerprint_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = _write_source(
                root,
                "canonical.yaml",
                _raw("canonical", topic_id="canonical_topic_id"),
                self.NOW - timedelta(hours=1),
                "1" * 64,
            )
            prepared, stats = projection._prepare_active_sources(
                [entry], now_utc=self.NOW
            )
            stats["collision_count"] = 0
            cfg = {"topic_intel_projection_dir": str(root / "projections")}
            projection.generate_owner_projection(
                owner_name="測試業主",
                owner_rec={
                    "owner_name": "測試業主",
                    "owner_id": "test-owner",
                    "owner_code": "test",
                    "owner_dir": "測試業主",
                    "industry_id": "測試業",
                    "industries": ["測試業"],
                    "_aliases": [],
                },
                prepared_rows=prepared,
                source_pool_stats=stats,
                file_entries=[entry],
                owner_proj_json_sha="2" * 64,
                cfg=cfg,
            )
            active = json.loads(
                (root / "projections" / "by_owner" / "test" / "active.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(active["schema_version"], 2)
            self.assertEqual(active["ranker_version"], "trend_rank_v1")
            self.assertEqual(active["expired_source_count"], 0)
            self.assertEqual(active["duplicate_source_count"], 0)
            self.assertEqual(active["candidates"][0]["topic_id"], "canonical_topic_id")
            self.assertEqual(active["candidates"][0]["schema_version"], 2)
            self.assertEqual(
                active["candidates"][0]["trend_rank"]["ranker_version"],
                "trend_rank_v1",
            )

            fp_a = projection._compute_source_pool_fingerprint(
                [entry], ["1" * 64], "2" * 64, None, "adapter", 2
            )
            fp_b = projection._compute_source_pool_fingerprint(
                [entry], ["3" * 64], "2" * 64, None, "adapter", 2
            )
            self.assertNotEqual(fp_a, fp_b)

    def test_wildcard_route_is_closure_only_without_changing_9_2_2(self) -> None:
        plan = [{"seq": index + 1} for index in range(13)]
        annotated, _, _ = apply_hybrid_profile(
            plan, _load_owner_content_profile()
        )
        axes = [item["content_axis"] for item in annotated]
        self.assertEqual(axes.count("offpro"), 9)
        self.assertEqual(axes.count("personal_anchor"), 2)
        self.assertEqual(axes.count("professional"), 2)
        wildcard = [item for item in annotated if item.get("wildcard")]
        self.assertEqual(len(wildcard), 1)
        self.assertIn("topic_intel_closure", wildcard[0]["wildcard_reason"])
        self.assertIn("closure-only", wildcard[0]["wildcard_reason"])


if __name__ == "__main__":
    unittest.main()
