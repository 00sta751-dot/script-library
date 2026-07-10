#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 1 G11 quote derivation regressions.

The three YAML fixtures are self-contained copies/synthetic reductions.  Tests
must never reach into L2 history or a Claude session log at runtime.
"""

from __future__ import annotations

import contextlib
import copy
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


HERE = Path(__file__).resolve().parent
LIB = HERE.parent
FIXTURES = HERE / "fixtures" / "quote_derivation"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

import derive_quotes as quotes  # noqa: E402
import gen_chxp_plain_table as chxp_table  # noqa: E402
import validate_script_batch as validator  # noqa: E402
import yaml_skeleton_generator as skeleton  # noqa: E402


def _load(name: str) -> dict:
    docs = [
        doc
        for doc in yaml.safe_load_all((FIXTURES / name).read_text(encoding="utf-8"))
        if doc is not None
    ]
    if len(docs) != 1 or not isinstance(docs[0], dict):
        raise AssertionError(f"fixture {name} must contain exactly one mapping document")
    return docs[0]


def _load_frontmatter_fixture(name: str) -> dict:
    matches = [
        data
        for path, data in validator.load_yamls(FIXTURES)
        if path.name == name
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one frontmatter fixture {name}, got {len(matches)}")
    return matches[0]


def _method(data: dict) -> dict:
    return data["script_method"]["chxp_v1"]


def _old_quote(data: dict):
    return _method(data)["four_materials"]["old_answer"]["quote"]


def _set_old_quote(data: dict, value) -> None:
    _method(data)["four_materials"]["old_answer"]["quote"] = value


def _result(results: list[tuple[str, str, str, str]], check_id: str):
    matches = [row for row in results if row[0] == check_id]
    if len(matches) != 1:
        raise AssertionError(f"expected one {check_id}, got {matches!r}")
    return matches[0]


def _run_per_file(data: dict, name: str = "script_quote_fixture.yaml"):
    return validator.run_per_file_checks(
        Path(name),
        data,
        str(data.get("owner") or "瑞祥"),
        fishing_policy={"mode": "off", "batch_date": None, "detail": "test"},
        topic_intel_policy={"mode": "off", "enabled": False, "detail": "test"},
    )


class DeriveQuoteTests(unittest.TestCase):
    def test_visual_scalar_cannot_fake_canonical_dialogue_pass(self) -> None:
        data = _load("valid_v1.yaml")
        rows = quotes.collect_final_dialogue(data)
        all_dialogue = "\n".join(row["text"] for row in rows)

        self.assertTrue(rows)
        self.assertTrue(
            all(row["dialogue_key"] == "台詞" or row["dialogue_key"].startswith("台詞_") for row in rows)
        )
        self.assertNotIn("畫面裡的假金句", all_dialogue)
        self.assertNotIn("這是非台詞欄，不能當 quote source", all_dialogue)
        self.assertFalse(
            validator._quote_in_scene(data, "畫面裡的假金句", ("3-12s",))
        )

        # Grandfather is deliberately version-aware: the identical legacy
        # structure retains its historical all-scalar haystack.
        legacy_shape = copy.deepcopy(data)
        legacy_shape.pop("quote_derivation_version")
        legacy_shape.pop("quote_source_hash")
        self.assertTrue(
            validator._quote_in_scene(
                legacy_shape, "畫面裡的假金句", ("3-12s",)
            )
        )

    def test_b43_replay_derives_fresh_quotes_and_passes_consumers(self) -> None:
        data = _load("b43_replay_v1.yaml")
        original = copy.deepcopy(data)
        view = quotes.derive_quote_view(data)
        close_dialogue = next(
            scene["台詞_瑞祥"]
            for scene in data["scenes"]
            if scene["timestamp"] == "40-52s"
        )

        self.assertEqual(data, original, "runtime derivation must not mutate source selectors")
        self.assertIsNot(view, data)
        self.assertIsInstance(
            _method(data)["four_materials"]["new_answer"]["quote"], dict
        )
        self.assertEqual(
            _method(view)["four_materials"]["new_answer"]["quote"],
            close_dialogue,
        )
        self.assertEqual(
            view["friend_close"]["evidence"]["core_answer_quote"],
            close_dialogue,
        )
        self.assertEqual(
            validator.chk_hybrid_method(view, "b43_replay.yaml")[0], "PASS"
        )
        self.assertEqual(
            validator.chk_hybrid_friend_close(view, "b43_replay.yaml")[0],
            "PASS",
        )

        # Replay the incident's pre-selector state: all evidence is fresh
        # except the historically stale new_answer scalar.  It must reproduce
        # the old C-method failure before demonstrating the derived PASS above.
        stale_legacy = copy.deepcopy(view)
        stale_legacy.pop("quote_derivation_version")
        stale_legacy.pop("quote_source_hash")
        stale_legacy["script_method"]["chxp_v1"]["four_materials"]["new_answer"][
            "quote"
        ] = data["fixture_source"]["legacy_stale_new_answer_quote"]
        status, detail = validator.chk_hybrid_method(
            stale_legacy, "b43_pre_selector.yaml"
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("new_answer.quote 未出現在最終台詞", detail)

    def test_b43_replay_passes_production_per_file_wiring(self) -> None:
        results = _run_per_file(_load("b43_replay_v1.yaml"), "script_b43_replay.yaml")

        for check_id in ("C-quote-source", "C-method", "C-friend-close"):
            with self.subTest(check_id=check_id):
                self.assertEqual(_result(results, check_id)[1], "PASS")

    def test_stale_hash_fails_through_production_per_file_wiring(self) -> None:
        data = _load("b43_replay_v1.yaml")
        data["quote_source_hash"] = "0" * 64

        results = _run_per_file(data, "script_b43_stale.yaml")
        quote_source = _result(results, "C-quote-source")
        self.assertEqual(quote_source[1], "FAIL")
        self.assertIn("stale_hash", quote_source[3])
        self.assertEqual(_result(results, "C-method")[1], "SKIP")
        self.assertEqual(_result(results, "C-friend-close")[1], "SKIP")

    def test_orphan_hash_fails_through_production_per_file_wiring(self) -> None:
        data = _load("b43_replay_v1.yaml")
        data.pop("quote_derivation_version")

        with self.assertRaises(quotes.QuoteDerivationError) as raised:
            quotes.derive_quote_view(data)
        self.assertEqual(raised.exception.code, "orphan_hash")
        self.assertEqual(raised.exception.path, "quote_source_hash")

        results = _run_per_file(data, "script_b43_orphan_hash.yaml")
        quote_source = _result(results, "C-quote-source")
        self.assertEqual(quote_source[1], "FAIL")
        self.assertIn("orphan_hash", quote_source[3])
        self.assertEqual(_result(results, "C-method")[1], "SKIP")
        self.assertEqual(_result(results, "C-friend-close")[1], "SKIP")

        source = (FIXTURES / "b43_replay_v1.yaml").read_text(encoding="utf-8")
        orphan_text = "".join(
            line
            for line in source.splitlines(keepends=True)
            if not line.startswith("quote_derivation_version:")
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "script_orphan_hash.yaml"
            path.write_text(orphan_text, encoding="utf-8", newline="")
            before = path.read_bytes()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                self.assertEqual(quotes.main([str(path)]), 1)
            self.assertIn("orphan_hash", stderr.getvalue())
            self.assertEqual(path.read_bytes(), before)

    def test_hash_bearing_skeleton_is_enforced_through_production_wiring(self) -> None:
        data = _load("b43_replay_v1.yaml")
        data["title"] = "[編劇填]"
        for scene in data["scenes"]:
            for key in list(scene):
                if key == "台詞" or key.startswith("台詞_"):
                    scene[key] = "[編劇填]"

        data.pop("quote_source_hash")
        clean_results = _run_per_file(data, "script_clean_skeleton.yaml")
        for check_id in ("C-quote-source", "C-method", "C-friend-close"):
            with self.subTest(clean_skeleton=check_id):
                self.assertEqual(_result(clean_results, check_id)[1], "SKIP")

        data["quote_source_hash"] = quotes.dialogue_sha256(data)
        enforced_results = _run_per_file(data, "script_hashed_skeleton.yaml")
        quote_source = _result(enforced_results, "C-quote-source")
        self.assertEqual(quote_source[1], "FAIL")
        self.assertIn("empty_source", quote_source[3])
        self.assertEqual(_result(enforced_results, "C-method")[1], "SKIP")
        self.assertEqual(_result(enforced_results, "C-friend-close")[1], "SKIP")

        offpro_status, offpro_detail = validator.chk_offpro_cta_policy(
            [(Path("script_hashed_skeleton.yaml"), data)]
        )
        expected_offpro_status = (
            "FAIL" if validator._OFFPRO_CTA_POLICY_ENFORCE else "WARN"
        )
        self.assertEqual(offpro_status, expected_offpro_status)
        self.assertIn("C-quote-source empty_source", offpro_detail)

    def test_degenerate_version_shell_is_not_a_clean_skeleton(self) -> None:
        data = {"quote_derivation_version": 1}

        self.assertFalse(validator._hybrid_file_is_skeleton(data))
        results = _run_per_file(data, "script_degenerate_shell.yaml")
        quote_source = _result(results, "C-quote-source")
        self.assertEqual(quote_source[1], "FAIL")
        self.assertNotIn("骨架階段跳過", quote_source[3])
        self.assertEqual(_result(results, "C-method")[1], "SKIP")
        self.assertEqual(_result(results, "C-friend-close")[1], "SKIP")

    def test_no_scenes_legacy_markdown_body_keeps_grandfathered_skip(self) -> None:
        name = "legacy_rux_pilot_01_no_scenes.yaml"
        data = _load_frontmatter_fixture(name)

        self.assertNotIn("quote_derivation_version", data)
        self.assertNotIn("scenes", data)
        self.assertIn("台詞：", data["_markdown_body"])
        self.assertTrue(validator._hybrid_file_is_skeleton(data))

        results = _run_per_file(data, name)
        self.assertNotIn("C-quote-source", [row[0] for row in results])
        for check_id in (
            "C-method",
            "C-friend-close",
            "C-professional-minimum",
        ):
            with self.subTest(check_id=check_id):
                self.assertEqual(_result(results, check_id)[1], "SKIP")

    def test_write_is_zero_diff_on_rerun_and_check_is_read_only(self) -> None:
        source = FIXTURES / "valid_v1.yaml"
        without_hash = "".join(
            line
            for line in source.read_text(encoding="utf-8").splitlines(keepends=True)
            if not line.startswith("quote_source_hash:")
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "script_quote_v1.yaml"
            path.write_text(without_hash, encoding="utf-8", newline="")

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(quotes.main(["--write", str(path)]), 0)
            first_write = path.read_bytes()
            loaded = next(
                doc
                for doc in yaml.safe_load_all(first_write.decode("utf-8"))
                if doc is not None
            )
            self.assertEqual(loaded["quote_source_hash"], quotes.dialogue_sha256(loaded))

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(quotes.main(["--write", str(path)]), 0)
            self.assertEqual(path.read_bytes(), first_write, "second --write must be byte-identical")

            before_check = path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(quotes.main([str(path)]), 0)
            self.assertEqual(path.read_bytes(), before_check, "default --check must not write")

    def test_atomic_writer_fsyncs_and_replaces_from_the_target_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "script_atomic.yaml"
            path.write_bytes(b"old")

            with patch.object(
                quotes.os, "fsync", wraps=quotes.os.fsync
            ) as fsync_spy, patch.object(
                quotes.os, "replace", wraps=quotes.os.replace
            ) as replace_spy:
                quotes._atomic_write_bytes(path, b"new")

            self.assertEqual(path.read_bytes(), b"new")
            fsync_spy.assert_called_once()
            replace_spy.assert_called_once()
            staged, target = replace_spy.call_args.args
            self.assertEqual(Path(staged).parent, path.parent)
            self.assertEqual(Path(target), path)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_atomic_writer_failure_keeps_destination_and_cleans_temp(self) -> None:
        for failure_point in ("fsync", "replace"):
            with self.subTest(failure_point=failure_point), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "script_atomic_failure.yaml"
                path.write_bytes(b"original")

                with patch.object(
                    quotes.os,
                    failure_point,
                    side_effect=OSError(f"simulated {failure_point} failure"),
                ):
                    with self.assertRaises(OSError):
                        quotes._atomic_write_bytes(path, b"replacement")

                self.assertEqual(path.read_bytes(), b"original")
                self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_batch_write_failure_reports_written_and_not_written_files(self) -> None:
        source = (FIXTURES / "valid_v1.yaml").read_text(encoding="utf-8")
        without_hash = "".join(
            line
            for line in source.splitlines(keepends=True)
            if not line.startswith("quote_source_hash:")
        )
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "script_01.yaml"
            second = Path(tmp) / "script_02.yaml"
            first.write_text(without_hash, encoding="utf-8", newline="")
            second.write_text(without_hash, encoding="utf-8", newline="")
            first_before = first.read_bytes()
            second_before = second.read_bytes()
            real_atomic_write = quotes._atomic_write_bytes

            def fail_second(path: Path, payload: bytes) -> None:
                if path == second:
                    raise OSError("simulated disk failure")
                real_atomic_write(path, payload)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.object(
                quotes, "_atomic_write_bytes", side_effect=fail_second
            ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(quotes.main(["--write", str(first), str(second)]), 1)

            self.assertNotEqual(first.read_bytes(), first_before)
            self.assertEqual(second.read_bytes(), second_before)
            self.assertIn("already written (1)", stderr.getvalue())
            self.assertIn(str(first), stderr.getvalue())
            self.assertIn("not written (1)", stderr.getvalue())
            self.assertIn(str(second), stderr.getvalue())
            self.assertIn("simulated disk failure", stderr.getvalue())

    def test_batch_write_validates_every_file_before_atomic_phase(self) -> None:
        source = (FIXTURES / "valid_v1.yaml").read_text(encoding="utf-8")
        without_hash = "".join(
            line
            for line in source.splitlines(keepends=True)
            if not line.startswith("quote_source_hash:")
        )
        invalid = without_hash.replace(
            'dialogue_key: "台詞_瑞祥"', 'dialogue_key: "藏鏡人"', 1
        )
        with tempfile.TemporaryDirectory() as tmp:
            valid_path = Path(tmp) / "script_01_valid.yaml"
            invalid_path = Path(tmp) / "script_02_invalid.yaml"
            valid_path.write_text(without_hash, encoding="utf-8", newline="")
            invalid_path.write_text(invalid, encoding="utf-8", newline="")
            valid_before = valid_path.read_bytes()
            invalid_before = invalid_path.read_bytes()

            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                self.assertEqual(
                    quotes.main(["--write", str(valid_path), str(invalid_path)]), 1
                )

            self.assertEqual(valid_path.read_bytes(), valid_before)
            self.assertEqual(invalid_path.read_bytes(), invalid_before)
            self.assertIn("no files written", stderr.getvalue())

    def test_missing_selector_fails_closed_with_diagnostic_path(self) -> None:
        cases = {
            "scalar": "人工抄寫的 stale quote",
            "missing_timestamp": {"dialogue_key": "台詞_瑞祥"},
            "missing_dialogue_key": {"timestamp": "3-12s"},
            "extra_key": {
                "timestamp": "3-12s",
                "dialogue_key": "台詞_瑞祥",
                "fallback": "台詞_藏鏡人",
            },
        }
        for label, selector in cases.items():
            with self.subTest(label=label):
                data = _load("valid_v1.yaml")
                _set_old_quote(data, selector)
                with self.assertRaises(quotes.QuoteDerivationError) as raised:
                    quotes.derive_quote_view(data, check_hash=False)
                self.assertEqual(raised.exception.code, "missing_selector")
                self.assertIn("old_answer.quote", raised.exception.path)

        data = _load("valid_v1.yaml")
        _set_old_quote(data, {"timestamp": "3-12s"})
        results = _run_per_file(data)
        self.assertEqual(_result(results, "C-quote-source")[1], "FAIL")
        self.assertEqual(_result(results, "C-method")[1], "SKIP")
        self.assertIn("missing_selector", _result(results, "C-quote-source")[3])

    def test_wrong_speaker_never_falls_back_to_another_dialogue(self) -> None:
        data = _load("valid_v1.yaml")
        _set_old_quote(
            data, {"timestamp": "3-12s", "dialogue_key": "藏鏡人"}
        )
        with self.assertRaises(quotes.QuoteDerivationError) as raised:
            quotes.derive_quote_view(data, check_hash=False)
        self.assertEqual(raised.exception.code, "wrong_speaker")

        data = _load("valid_v1.yaml")
        _set_old_quote(
            data, {"timestamp": "3-12s", "dialogue_key": "台詞_阿奇"}
        )
        with self.assertRaises(quotes.QuoteDerivationError) as raised:
            quotes.derive_quote_view(data, check_hash=False)
        self.assertEqual(raised.exception.code, "source_not_found")
        self.assertIn("台詞_阿奇", raised.exception.detail)

        # Multiple real speakers are allowed only when selected exactly.
        data = _load("valid_v1.yaml")
        _set_old_quote(
            data, {"timestamp": "0-3s", "dialogue_key": "台詞_藏鏡人"}
        )
        view = quotes.derive_quote_view(data, check_hash=False)
        self.assertEqual(_old_quote(view), "真的嗎？")

    def test_legacy_no_flag_keeps_historical_verdict_and_has_no_new_gate(self) -> None:
        path = FIXTURES / "legacy_yunzhen_14_12.yaml"
        data = _load(path.name)
        self.assertNotIn("quote_derivation_version", data)
        self.assertNotIn("quote_source_hash", data)

        view = quotes.derive_quote_view(data)
        self.assertEqual(view, data)
        self.assertIsNot(view, data)
        _method(view)["four_materials"]["old_answer"]["quote"] = "changed"
        self.assertNotEqual(view, data, "legacy return must still be a defensive deep copy")

        expected = {
            "C-method": validator.chk_hybrid_method(data, path.name),
            "C-friend-close": validator.chk_hybrid_friend_close(data, path.name),
            "C-professional-minimum": validator.chk_hybrid_professional_minimum(
                data, path.name
            ),
        }
        self.assertEqual({key: value[0] for key, value in expected.items()}, {
            "C-method": "PASS",
            "C-friend-close": "PASS",
            "C-professional-minimum": "PASS",
        })

        results = _run_per_file(data, path.name)
        self.assertNotIn("C-quote-source", [row[0] for row in results])
        for check_id, baseline in expected.items():
            row = _result(results, check_id)
            self.assertEqual((row[1], row[3]), baseline)

        before = path.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(quotes.main([str(path)]), 0)
        self.assertEqual(path.read_bytes(), before)

    def test_stale_hash_fails_closed_and_write_repairs_it(self) -> None:
        data = _load("valid_v1.yaml")
        data["quote_source_hash"] = "0" * 64
        with self.assertRaises(quotes.QuoteDerivationError) as raised:
            quotes.derive_quote_view(data)
        self.assertEqual(raised.exception.code, "stale_hash")
        self.assertEqual(raised.exception.path, "quote_source_hash")
        self.assertIsInstance(quotes.derive_quote_view(data, check_hash=False), dict)

        results = _run_per_file(data)
        self.assertEqual(_result(results, "C-quote-source")[1], "FAIL")
        self.assertIn("stale_hash", _result(results, "C-quote-source")[3])
        self.assertEqual(_result(results, "C-method")[1], "SKIP")

        source_text = (FIXTURES / "valid_v1.yaml").read_text(encoding="utf-8")
        correct = _load("valid_v1.yaml")["quote_source_hash"]
        stale_text = source_text.replace(correct, "0" * 64, 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "script_stale_hash.yaml"
            path.write_text(stale_text, encoding="utf-8", newline="")
            before = path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                self.assertEqual(quotes.main([str(path)]), 1)
            self.assertEqual(path.read_bytes(), before, "failed --check must not mutate")

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(quotes.main(["--write", str(path)]), 0)
                self.assertEqual(quotes.main([str(path)]), 0)

    def test_missing_or_malformed_hash_fails_closed(self) -> None:
        cases = {
            "missing": (None, "missing_hash"),
            "empty": ("", "missing_hash"),
            "short": ("abc", "invalid_hash"),
            "non_hex": ("g" * 64, "invalid_hash"),
        }
        for label, (value, expected_code) in cases.items():
            with self.subTest(label=label):
                data = _load("valid_v1.yaml")
                if value is None:
                    data.pop("quote_source_hash")
                else:
                    data["quote_source_hash"] = value
                with self.assertRaises(quotes.QuoteDerivationError) as raised:
                    quotes.derive_quote_view(data)
                self.assertEqual(raised.exception.code, expected_code)
                gate = _result(_run_per_file(data), "C-quote-source")
                self.assertEqual(gate[1], "FAIL")
                self.assertIn(expected_code, gate[3])

    def test_uppercase_hash_fails_closed_as_invalid_hash(self) -> None:
        data = _load("valid_v1.yaml")
        data["quote_source_hash"] = data["quote_source_hash"].upper()

        with self.assertRaises(quotes.QuoteDerivationError) as raised:
            quotes.derive_quote_view(data)
        self.assertEqual(raised.exception.code, "invalid_hash")
        gate = _result(_run_per_file(data), "C-quote-source")
        self.assertEqual(gate[1], "FAIL")
        self.assertIn("invalid_hash", gate[3])

    def test_frontmatter_markdown_is_parsed_and_body_is_never_rewritten(self) -> None:
        fixture_text = (FIXTURES / "valid_v1.yaml").read_text(encoding="utf-8")
        yaml_without_marker = fixture_text.split("\n", 1)[1]
        body = (
            "\n# 人讀內容\n"
            "**主推平台**：這不是 YAML，loader 不得解析它。\n"
            'quote_source_hash: "body-must-not-change"\n'
        )
        block_scalar = "fixture_notes: |\n  before\n  ---\n  after\n"
        frontmatter_doc = "---\n" + yaml_without_marker + block_scalar + "---\n" + body

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "script_frontmatter.md.yaml"
            path.write_bytes(frontmatter_doc.encode("utf-8"))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(quotes.main([str(path)]), 0)
            self.assertIn("---", quotes._load_yaml(path)["fixture_notes"])
            self.assertIn("after", quotes._load_yaml(path)["fixture_notes"])

            no_top_hash = "".join(
                line
                for line in frontmatter_doc.splitlines(keepends=True)
                if not line.startswith("quote_source_hash: \"482b")
            )
            path.write_bytes(no_top_hash.encode("utf-8"))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(quotes.main(["--write", str(path)]), 0)
            rewritten = path.read_text(encoding="utf-8")
            self.assertTrue(rewritten.endswith(body))
            self.assertEqual(rewritten.count('quote_source_hash: "body-must-not-change"'), 1)

            legacy = Path(tmp) / "script_legacy_frontmatter.yaml"
            legacy_text = "---\nscript_id: legacy\n---\n\n**Markdown body**\n"
            legacy.write_bytes(legacy_text.encode("utf-8"))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(quotes.main(["--write", str(legacy)]), 0)
            self.assertEqual(legacy.read_text(encoding="utf-8"), legacy_text)

    def test_hash_upsert_handles_bom_and_hash_characters_in_scalars(self) -> None:
        digest = "a" * 64

        bom_version = "\ufeffquote_derivation_version: 1\r\nscript_id: bom\r\n"
        rewritten = quotes._upsert_quote_source_hash(bom_version, digest)
        self.assertEqual(
            rewritten,
            "\ufeffquote_derivation_version: 1\r\n"
            f'quote_source_hash: "{digest}"\r\n'
            "script_id: bom\r\n",
        )

        bom_frontmatter = (
            "---\n"
            "\ufeffquote_derivation_version: 1\n"
            "script_id: bom-frontmatter\n"
            "---\n"
            "body\n"
        )
        rewritten = quotes._upsert_quote_source_hash(bom_frontmatter, digest)
        self.assertIn(
            "\ufeffquote_derivation_version: 1\n"
            f'quote_source_hash: "{digest}"\n',
            rewritten,
        )
        self.assertTrue(rewritten.endswith("---\nbody\n"))

        quoted_hash = (
            '\ufeffquote_source_hash: "old # scalar"  # keep # detail\n'
            "quote_derivation_version: 1\n"
        )
        rewritten = quotes._upsert_quote_source_hash(quoted_hash, digest)
        self.assertEqual(
            rewritten.splitlines()[0],
            f'\ufeffquote_source_hash: "{digest}"  # keep # detail',
        )

        no_comment = (
            'quote_source_hash: "old # scalar"\n'
            "quote_derivation_version: 1\n"
        )
        rewritten = quotes._upsert_quote_source_hash(no_comment, digest)
        self.assertEqual(rewritten.splitlines()[0], f'quote_source_hash: "{digest}"')

    def test_timestamp_and_dialogue_key_are_nfc_normalized_before_lookup(self) -> None:
        nfc_timestamp = "12-Caf\u00e9"
        nfd_timestamp = "12-Cafe\u0301"
        nfc_key = "台詞_Caf\u00e9"
        nfd_key = "台詞_Cafe\u0301"

        data = _load("valid_v1.yaml")
        data["scenes"].append(
            {"timestamp": nfc_timestamp, nfc_key: "NFC/NFD selector resolved"}
        )
        _set_old_quote(
            data, {"timestamp": nfd_timestamp, "dialogue_key": nfd_key}
        )
        view = quotes.derive_quote_view(data, check_hash=False)
        self.assertEqual(_old_quote(view), "NFC/NFD selector resolved")

        nfc_document = {
            "scenes": [{"timestamp": nfc_timestamp, nfc_key: "same text"}]
        }
        nfd_document = {
            "scenes": [{"timestamp": nfd_timestamp, nfd_key: "same text"}]
        }
        self.assertEqual(
            quotes.dialogue_sha256(nfc_document),
            quotes.dialogue_sha256(nfd_document),
        )

        duplicate_document = {
            "scenes": [
                {"timestamp": nfc_timestamp, nfc_key: "first"},
                {"timestamp": nfd_timestamp, nfd_key: "second"},
            ]
        }
        with self.assertRaises(quotes.QuoteDerivationError) as raised:
            quotes.collect_final_dialogue(duplicate_document)
        self.assertEqual(raised.exception.code, "ambiguous_source")

    def test_version_must_be_exact_integer_one(self) -> None:
        for invalid in (1.0, True, "1", 2):
            with self.subTest(version=invalid):
                data = _load("valid_v1.yaml")
                data["quote_derivation_version"] = invalid
                with self.assertRaises(quotes.QuoteDerivationError) as raised:
                    quotes.derive_quote_view(data)
                self.assertEqual(raised.exception.code, "unsupported_version")
                self.assertEqual(_result(_run_per_file(data), "C-quote-source")[1], "FAIL")

    def test_selected_dialogue_must_not_be_empty_or_placeholder(self) -> None:
        for source_text in ("", "   ", "[編劇填]", "TODO"):
            with self.subTest(source_text=source_text):
                data = _load("valid_v1.yaml")
                scene = next(s for s in data["scenes"] if s["timestamp"] == "3-12s")
                scene["台詞_瑞祥"] = source_text
                with self.assertRaises(quotes.QuoteDerivationError) as raised:
                    quotes.derive_quote_view(data, check_hash=False)
                self.assertEqual(raised.exception.code, "empty_source")
                self.assertIn("old_answer.quote", raised.exception.path)

    def test_dialogue_hash_scope_and_runtime_view_deep_copy(self) -> None:
        data = _load("valid_v1.yaml")
        baseline = quotes.dialogue_sha256(data)
        self.assertEqual(baseline, data["quote_source_hash"])
        self.assertRegex(baseline, r"^[0-9a-f]{64}$")

        metadata_only = copy.deepcopy(data)
        metadata_only["scenes"][1]["畫面"] = "完全不同的畫面"
        metadata_only["scenes"][1]["翠文"] = "完全不同的翠文"
        metadata_only["scenes"][0]["藏鏡人"] = "完全不同的非台詞欄"
        metadata_only["scenes"][0]["type"] = "不同 type"
        metadata_only["scenes"][0] = dict(
            reversed(list(metadata_only["scenes"][0].items()))
        )
        self.assertEqual(quotes.dialogue_sha256(metadata_only), baseline)

        dialogue_edit = copy.deepcopy(data)
        dialogue_edit["scenes"][1]["台詞_瑞祥"] += "這句是新改的。"
        self.assertNotEqual(quotes.dialogue_sha256(dialogue_edit), baseline)

        view = quotes.derive_quote_view(data)
        _method(view)["four_materials"]["old_answer"]["quote"] = "runtime mutation"
        self.assertIsInstance(_old_quote(data), dict)
        self.assertNotEqual(view, data)

    def test_skeleton_emits_ten_selectors_and_keeps_voice_asset_scalar(self) -> None:
        item = {
            "owner": "瑞祥",
            "batch": "99",
            "batch_tag": "第99批_測試",
            "script_id": "ruixiang_99_01",
            "seq": 1,
            "派系": "直球派",
            "雙身份": "生活日常",
            "direction": "測試方向",
            "content_axis": "offpro",
            "lane": "demand_first",
            "derived_flags": [],
            "topic_category": "人生",
        }
        with patch.object(skeleton, "OWNER_DIALOGUE_KEY", {"瑞祥": "台詞_瑞祥"}), patch.object(
            skeleton, "OWNER_PLATFORM", {"瑞祥": "FB Reels"}
        ), patch.object(
            skeleton,
            "_load_l0_batch_spec",
            return_value={
                "duration_seconds": 60,
                "title_max_chars": 15,
                "actor_interaction_min": 2,
            },
        ), patch.object(
            skeleton,
            "build_time_slots",
            return_value=copy.deepcopy(skeleton.HARDCODED_TIME_SLOTS),
        ):
            text = skeleton.build_yaml_skeleton(item)

        docs = [doc for doc in yaml.safe_load_all(text) if doc is not None]
        self.assertEqual(len(docs), 1)
        data = docs[0]
        self.assertEqual(data["quote_derivation_version"], 1)
        self.assertNotIn("quote_source_hash", data)
        self.assertIsInstance(data["voice_asset_quote"], str)

        method = data["script_method"]["chxp_v1"]
        selectors = [
            method["four_materials"]["old_answer"]["quote"],
            method["four_materials"]["new_answer"]["quote"],
            method["optimization"]["concrete_signals"][0]["quote"],
            method["optimization"]["hook_debts"][0]["opened_quote"],
            method["optimization"]["hook_debts"][0]["closed_quote"],
            method["packaging"]["hook_promise"],
            method["packaging"]["final_payoff"],
            data["friend_close"]["evidence"]["value_delivered_quote"],
            data["friend_close"]["evidence"]["core_answer_quote"],
            data["friend_close"]["evidence"]["cta_quote"],
        ]
        self.assertEqual(len(selectors), 10)
        for selector in selectors:
            self.assertEqual(set(selector), {"timestamp", "dialogue_key"})
            self.assertEqual(selector["timestamp"], "[編劇填]")
            self.assertEqual(selector["dialogue_key"], "台詞_瑞祥")

        skeleton_results = _run_per_file(data, "script_modern_skeleton.yaml")
        self.assertEqual(_result(skeleton_results, "C-quote-source")[1], "SKIP")
        self.assertEqual(_result(skeleton_results, "C-method")[1], "SKIP")
        self.assertEqual(_result(skeleton_results, "C-friend-close")[1], "SKIP")

        partial_draft = copy.deepcopy(data)
        partial_draft["title"] = "真標題已填"
        partial_results = _run_per_file(partial_draft, "script_partial_draft.yaml")
        self.assertEqual(_result(partial_results, "C-quote-source")[1], "FAIL")
        self.assertIn("missing_selector", _result(partial_results, "C-quote-source")[3])

    def test_chxp_table_uses_one_shared_derived_view_per_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            shutil.copyfile(
                FIXTURES / "b43_replay_v1.yaml", batch / "script_b43_replay.yaml"
            )
            with patch.object(
                chxp_table,
                "derive_quote_view",
                wraps=quotes.derive_quote_view,
            ) as derive_spy:
                markdown, script_count, with_chxp_count = chxp_table.build_table(batch)

        self.assertEqual((script_count, with_chxp_count), (1, 1))
        derive_spy.assert_called_once()
        self.assertIn(
            "省錢沒問題。問題是你省的是什麼。省未來比花掉現在貴多了。",
            markdown,
        )
        self.assertNotIn("dialogue_key", markdown)
        self.assertNotIn("{'timestamp'", markdown)


if __name__ == "__main__":
    unittest.main()
