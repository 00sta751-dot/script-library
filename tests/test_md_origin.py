#!/usr/bin/env python3
"""md-origin 轉檔層 CLI 回歸測試。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


LIB = Path(__file__).resolve().parent.parent
VALIDATOR = LIB / "validate_script_batch.py"
GENERATOR = LIB / "gen_md_origin.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(batch_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(VALIDATOR),
            "--owner",
            "測試業主",
            "--batch-dir",
            str(batch_dir),
            "--strict",
        ],
        cwd=LIB,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


class MdOriginTests(unittest.TestCase):
    def test_complete_md_origin_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            md_dir = root / "md-source"
            batch_dir = root / "第05批_2026-09-04"
            md_dir.mkdir()
            batch_dir.mkdir()

            source = md_dir / "稿_n01_測試.md"
            source.write_text("# 可驗證的來源稿\n", encoding="utf-8")
            for name in ("caption_hashtag.md", "脆文_7篇.md", "_出貨檢查單_勾完.md"):
                (md_dir / name).write_text(f"# {name}\n", encoding="utf-8")

            yaml_path = batch_dir / "script_測試_05_01.yaml"
            yaml_path.write_text(
                """title: 可驗證的轉檔稿
scenes:
  - timestamp: 0-3s
    type: Hook
    台詞: 這是測試台詞
    藏鏡人: 這是測試接話
caption: 這是一段可驗證的貼文文字
hashtag:
  - '#測試'
""",
                encoding="utf-8",
            )

            generated = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(GENERATOR),
                    "--md-dir",
                    str(md_dir),
                    "--yaml-dir",
                    str(batch_dir),
                    "--nn-map",
                    "稿_n{NN}=script_測試_05_{NN}",
                ],
                cwd=LIB,
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(0, generated.returncode, generated.stdout + generated.stderr)
            self.assertTrue((batch_dir / "_md_origin.json").is_file())

            result = _run(batch_dir)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("md-origin 轉檔層", result.stdout)

    def test_same_batch_without_manifest_stays_retired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp) / "第05批_2026-09-04"
            batch_dir.mkdir()
            (batch_dir / "script_測試_05_01.yaml").write_text(
                "title: 沒有證明的手寫稿\n",
                encoding="utf-8",
            )

            result = _run(batch_dir)

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("退役", result.stdout)

    def test_forged_manifest_hash_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            md_dir = root / "md-source"
            batch_dir = root / "第05批_2026-09-04"
            md_dir.mkdir()
            batch_dir.mkdir()

            source = md_dir / "稿_n01_測試.md"
            source.write_text("# 真實來源稿\n", encoding="utf-8")
            for name in ("caption_hashtag.md", "脆文_7篇.md", "_出貨檢查單_勾完.md"):
                (md_dir / name).write_text(f"# {name}\n", encoding="utf-8")
            yaml_path = batch_dir / "script_測試_05_01.yaml"
            yaml_path.write_text(
                """title: 造假 hash 測試
scenes:
  - 台詞: 測試
    藏鏡人: 接話
caption: 這是一段測試文案
hashtag: ['#測試']
""",
                encoding="utf-8",
            )
            manifest = {
                "schema": "md_origin/v1",
                "source_md_dir": str(md_dir),
                "files": [
                    {
                        "md": source.name,
                        "sha256": "0" * 64,
                        "yaml": yaml_path.name,
                    }
                ],
                "aux": {
                    name: _sha256(md_dir / name)
                    for name in (
                        "caption_hashtag.md",
                        "脆文_7篇.md",
                        "_出貨檢查單_勾完.md",
                    )
                },
                "converted_at": "2026-09-04T19:00:00+08:00",
                "converter": "test_md_origin.py",
            }
            (batch_dir / "_md_origin.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            result = _run(batch_dir)

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("md-origin 證明無效", result.stdout)


if __name__ == "__main__":
    unittest.main()
