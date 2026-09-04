#!/usr/bin/env python3
"""YAML 出批線退役與 legacy-frozen 相容回歸測試。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


LIB = Path(__file__).resolve().parent.parent
VALIDATOR = LIB / "validate_script_batch.py"
NOTICE = "舊 yaml 線已於 2026-09-04 退役"
LEGACY_FROZEN_NOTICE = (
    "legacy-frozen: yaml 線 2026-09-04 退役，內容原樣保留、不再新增檢查"
)


def _run(batch_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--batch-dir",
            str(batch_dir),
            "--strict",
            *extra,
        ],
        cwd=LIB,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


class YamlRetirementTests(unittest.TestCase):
    def test_cli_parameters_are_still_available(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), "--help"],
            cwd=LIB,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        for option in (
            "--owner",
            "--batch-dir",
            "--topic-plan",
            "--strict",
            "--c016-all",
            "--stage",
        ):
            self.assertIn(option, result.stdout)

    def test_markdown_only_keeps_cli_callable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            (batch / "聊天體.md").write_text("# 現役聊天體\n", encoding="utf-8")
            result = _run(batch)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Markdown 稿 1 個", result.stdout)
        self.assertIn("不解析 Markdown 內容", result.stdout)
        self.assertNotIn("ImportError", result.stdout + result.stderr)

    def test_legacy_frozen_passes_and_new_yaml_fails(self) -> None:
        cases = (
            (
                "legacy-frozen",
                "script_01.yaml",
                "created: 2026-09-03\ncontent_axis: professional\ntitle: 既有稿\n",
                "batch_profile: hybrid_70_15_15\n",
                0,
                LEGACY_FROZEN_NOTICE,
                None,
            ),
            (
                "new-yaml-date-under-l2",
                "SCRIPT_01.YML",
                "日期: 2026-09-04\ntitle: 新稿\n",
                None,
                1,
                NOTICE,
                ("L2_業主層", "測試業主", "第99批_2026-09-04"),
            ),
            (
                "legacy-folder-date",
                "script_02.yaml",
                "title: 既有無日期稿\n",
                None,
                0,
                LEGACY_FROZEN_NOTICE,
                ("archive", "第03批_2026-07-31"),
            ),
            (
                "new-folder-date-under-l2",
                "script_03.yaml",
                "title: 新批無稿內日期\n",
                None,
                1,
                NOTICE,
                ("L2_業主層", "測試業主", "第99批_2026-09-04"),
            ),
            (
                "legacy-l2-existing-no-date",
                "script_04.yaml",
                "title: 既有 L2 無日期稿\n",
                None,
                0,
                LEGACY_FROZEN_NOTICE,
                ("L2_業主層", "測試業主", "既有批"),
            ),
            (
                "old-ancestor-does-not-freeze-undated-new-batch",
                "script_05.yaml",
                "title: 無批次日期的新稿\n",
                None,
                1,
                NOTICE,
                ("archive_2026-07-31", "undated-new-batch"),
            ),
            (
                "dotdot-cannot-spoof-l2-existing-batch",
                "script_06.yaml",
                "title: L2 外的新稿\n",
                None,
                1,
                NOTICE,
                ("L2_業主層", "..", "newbatch"),
            ),
            (
                "dotdot-cannot-hide-new-batch-date",
                "script_07.yaml",
                "title: 切線日新批\n",
                None,
                1,
                NOTICE,
                ("L2_業主層", "測試業主", "第99批_2026-09-04", "child", ".."),
            ),
        )
        for label, name, content, flags, expected_rc, expected_notice, relative_dir in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                batch = Path(tmp)
                if relative_dir is not None:
                    batch = batch.joinpath(*relative_dir)
                    if label == "dotdot-cannot-hide-new-batch-date":
                        batch.parent.mkdir(parents=True)
                    else:
                        batch.mkdir(parents=True)
                (batch / name).write_text(content, encoding="utf-8")
                if flags is not None:
                    (batch / "_batch_flags.yml").write_text(flags, encoding="utf-8")
                result = _run(batch)

            self.assertEqual(expected_rc, result.returncode, result.stdout + result.stderr)
            self.assertIn(expected_notice, result.stdout)

    def test_hybrid_flags_without_script_yaml_still_fail(self) -> None:
        for profile in ("hybrid_70_15_15", "9/2/2", "unknown_profile"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as tmp:
                batch = Path(tmp)
                (batch / "聊天體.md").write_text("# 稿\n", encoding="utf-8")
                (batch / "_batch_flags.yml").write_text(
                    f"batch_profile: {profile}\n", encoding="utf-8"
                )
                result = _run(batch)

            self.assertEqual(1, result.returncode)
            self.assertIn(NOTICE, result.stdout)

    def test_uppercase_flags_filename_is_still_inspected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            (batch / "聊天體.md").write_text("# 稿\n", encoding="utf-8")
            (batch / "_BATCH_FLAGS.YML").write_text(
                "batch_profile: hybrid_typo\n", encoding="utf-8"
            )
            result = _run(batch)

        self.assertEqual(1, result.returncode)
        self.assertIn(NOTICE, result.stdout)

    def test_uppercase_underscored_topic_plan_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            (batch / "聊天體.md").write_text("# 稿\n", encoding="utf-8")
            (batch / "_TOPIC_PLAN.JSON").write_text("{}\n", encoding="utf-8")
            result = _run(batch)

        self.assertEqual(1, result.returncode)
        self.assertIn(NOTICE, result.stdout)

    def test_topic_plan_argument_always_marks_retired_line(self) -> None:
        for topic_plan_args in (("--topic-plan", "missing.json"), ("--topic-plan=",)):
            with self.subTest(args=topic_plan_args), tempfile.TemporaryDirectory() as tmp:
                batch = Path(tmp)
                (batch / "聊天體.md").write_text("# 稿\n", encoding="utf-8")
                result = _run(batch, *topic_plan_args)

            self.assertEqual(1, result.returncode)
            self.assertIn(NOTICE, result.stdout)

    def test_taste_panel_artifact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            (batch / "聊天體.md").write_text("# 稿\n", encoding="utf-8")
            (batch / ".taste_panel").mkdir()
            result = _run(batch)

        self.assertEqual(1, result.returncode)
        self.assertIn(NOTICE, result.stdout)

    def test_nonhybrid_flags_and_backup_yaml_do_not_block_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            (batch / "聊天體.md").write_text("# 稿\n", encoding="utf-8")
            (batch / "_batch_flags.yml").write_text(
                "topic_intel_closure:\n  mode: off\n", encoding="utf-8"
            )
            (batch / "script_01.bak.yaml").write_text(
                "title: 備份\n", encoding="utf-8"
            )
            result = _run(batch)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_bak_substring_does_not_hide_script_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            (batch / "script.bakdoor.yaml").write_text(
                "title: 舊稿\n", encoding="utf-8"
            )
            result = _run(batch)

        self.assertEqual(1, result.returncode)
        self.assertIn(NOTICE, result.stdout)

    def test_batch_file_symlink_fails_closed(self) -> None:
        cases = (
            ("script-symlink", "script_old.yaml", "created: 2026-09-03\n"),
            ("legacy-plus-symlink", "聊天體.md", "舊線內容\n"),
        )
        for label, link_name, target_content in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                batch = Path(tmp)
                target = batch / "target.txt"
                target.write_text(target_content, encoding="utf-8")
                if label == "legacy-plus-symlink":
                    (batch / "script_01.yaml").write_text(
                        "created: 2026-09-03\n", encoding="utf-8"
                    )
                link = batch / link_name
                try:
                    link.symlink_to(target.name)
                except (NotImplementedError, OSError) as exc:
                    self.skipTest(f"此平台無法建立 symlink：{exc}")
                result = _run(batch)

            self.assertEqual(1, result.returncode)
            self.assertIn(NOTICE, result.stdout)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_batch = root / "real-batch"
            real_batch.mkdir()
            (real_batch / "script_01.yaml").write_text(
                "created: 2026-09-03\n", encoding="utf-8"
            )
            batch_link = root / "batch-link"
            try:
                batch_link.symlink_to(real_batch.name, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"此平台無法建立 directory symlink：{exc}")
            result = _run(batch_link)

        self.assertEqual(1, result.returncode)
        self.assertIn(NOTICE, result.stdout)

    def test_empty_directory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(Path(tmp))

        self.assertEqual(1, result.returncode)
        self.assertIn("找不到現役 Markdown 稿", result.stdout)

    def test_retired_check_functions_keep_signatures_and_fail(self) -> None:
        from validate_script_batch import (
            chk_taste_panel_completeness,
            chk_topic_lock_consistency,
        )

        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            topic_status, topic_detail = chk_topic_lock_consistency([], batch)
            taste_status, taste_detail = chk_taste_panel_completeness([], batch)

        self.assertEqual("FAIL", topic_status)
        self.assertEqual("FAIL", taste_status)
        self.assertIn(NOTICE, topic_detail)
        self.assertIn(NOTICE, taste_detail)


if __name__ == "__main__":
    unittest.main()
