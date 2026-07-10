#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Derive duplicated quote evidence from canonical scene dialogue.

G11 v1 stores quote evidence as ``{timestamp, dialogue_key}`` selectors.  This
module resolves those selectors into an in-memory view for consumers; source
YAML keeps the selectors so a later dialogue edit cannot silently leave copied
quote text behind.

CLI examples::

    python derive_quotes.py script_owner_01_01.yaml          # --check (default)
    python derive_quotes.py --batch-dir <batch> --check
    python derive_quotes.py --batch-dir <batch> --write      # update hash only

``--write`` changes only the top-level ``quote_source_hash`` line.  It never
safe-dumps or otherwise rewrites the YAML document.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable

import yaml


QUOTE_DERIVATION_VERSION = 1
_DIALOGUE_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_HASH_RE = re.compile(r"^quote_source_hash\s*:")
_TOP_LEVEL_VERSION_RE = re.compile(r"^quote_derivation_version\s*:")
_PLACEHOLDER_VALUES = {
    "[編劇填]",
    "[待填]",
    "待填",
    "todo",
    "tbd",
}


class QuoteDerivationError(ValueError):
    """A stable, user-facing quote-source contract violation."""

    def __init__(self, code: str, path: str, detail: str):
        self.code = code
        self.path = path
        self.detail = detail
        super().__init__(f"{code} at {path}: {detail}")


def _is_dialogue_key(key: Any) -> bool:
    key_s = unicodedata.normalize("NFC", str(key))
    return key_s == "台詞" or key_s.startswith("台詞_")


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in _PLACEHOLDER_VALUES


def collect_final_dialogue(data: dict[str, Any]) -> list[dict[str, str]]:
    """Collect canonical dialogue rows in scene order.

    Only ``台詞`` and ``台詞_*`` are publishable dialogue sources.  Scalar
    scene metadata such as ``type``, ``畫面``, ``翠文`` and ``藏鏡人`` is
    intentionally excluded.  Multiple dialogue keys in one scene are sorted
    by key so YAML mapping-order-only edits do not stale the source hash.
    """

    if not isinstance(data, dict):
        raise QuoteDerivationError("invalid_document", "$", "YAML root must be a mapping")

    scenes = data.get("scenes")
    if scenes is None:
        return []
    if not isinstance(scenes, list):
        raise QuoteDerivationError("invalid_scenes", "scenes", "must be a list")

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for scene_index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise QuoteDerivationError(
                "invalid_scene", f"scenes[{scene_index}]", "must be a mapping"
            )

        dialogue_items = sorted(
            (
                (unicodedata.normalize("NFC", str(key)), value)
                for key, value in scene.items()
                if _is_dialogue_key(key)
            ),
            key=lambda item: item[0],
        )
        if not dialogue_items:
            continue

        timestamp = scene.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp.strip():
            raise QuoteDerivationError(
                "missing_timestamp",
                f"scenes[{scene_index}].timestamp",
                "a scene with dialogue needs a non-empty canonical timestamp",
            )
        timestamp = unicodedata.normalize("NFC", timestamp.strip())

        for dialogue_key, value in dialogue_items:
            source_path = f"scenes[{scene_index}].{dialogue_key}"
            if not isinstance(value, str):
                raise QuoteDerivationError(
                    "invalid_dialogue", source_path, "dialogue must be a string"
                )
            selector_key = (timestamp, dialogue_key)
            if selector_key in seen:
                raise QuoteDerivationError(
                    "ambiguous_source",
                    source_path,
                    f"duplicate selector timestamp={timestamp!r}, dialogue_key={dialogue_key!r}",
                )
            seen.add(selector_key)
            rows.append(
                {
                    "timestamp": timestamp,
                    "dialogue_key": dialogue_key,
                    "text": value,
                }
            )
    return rows


def dialogue_sha256(data: dict[str, Any]) -> str:
    """Return a deterministic SHA-256 of canonical final dialogue only."""

    canonical = json.dumps(
        collect_final_dialogue(data),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _missing_selector(path: str, detail: str = "quote selector is required") -> QuoteDerivationError:
    return QuoteDerivationError("missing_selector", path, detail)


def _mapping_at(parent: Any, key: str, path: str) -> dict[str, Any]:
    if not isinstance(parent, dict) or not isinstance(parent.get(key), dict):
        raise _missing_selector(path, "required parent mapping is missing")
    return parent[key]


def _list_at(parent: Any, key: str, path: str) -> list[Any]:
    if not isinstance(parent, dict) or not isinstance(parent.get(key), list) or not parent[key]:
        raise _missing_selector(path, "required non-empty selector list is missing")
    return parent[key]


def _quote_targets(view: dict[str, Any]) -> list[tuple[dict[str, Any], str, str]]:
    """Return every v1 quote slot as (parent, key, diagnostic path)."""

    script_method = _mapping_at(view, "script_method", "script_method")
    chxp = _mapping_at(script_method, "chxp_v1", "script_method.chxp_v1")
    four = _mapping_at(chxp, "four_materials", "script_method.chxp_v1.four_materials")
    old_answer = _mapping_at(
        four, "old_answer", "script_method.chxp_v1.four_materials.old_answer"
    )
    new_answer = _mapping_at(
        four, "new_answer", "script_method.chxp_v1.four_materials.new_answer"
    )
    optimization = _mapping_at(
        chxp, "optimization", "script_method.chxp_v1.optimization"
    )
    packaging = _mapping_at(chxp, "packaging", "script_method.chxp_v1.packaging")
    friend_close = _mapping_at(view, "friend_close", "friend_close")
    evidence = _mapping_at(friend_close, "evidence", "friend_close.evidence")

    targets: list[tuple[dict[str, Any], str, str]] = [
        (old_answer, "quote", "script_method.chxp_v1.four_materials.old_answer.quote"),
        (new_answer, "quote", "script_method.chxp_v1.four_materials.new_answer.quote"),
    ]

    signals = _list_at(
        optimization,
        "concrete_signals",
        "script_method.chxp_v1.optimization.concrete_signals",
    )
    for index, signal in enumerate(signals):
        path = f"script_method.chxp_v1.optimization.concrete_signals[{index}]"
        if not isinstance(signal, dict):
            raise _missing_selector(path, "selector item must be a mapping")
        targets.append((signal, "quote", f"{path}.quote"))

    debts = _list_at(
        optimization,
        "hook_debts",
        "script_method.chxp_v1.optimization.hook_debts",
    )
    for index, debt in enumerate(debts):
        path = f"script_method.chxp_v1.optimization.hook_debts[{index}]"
        if not isinstance(debt, dict):
            raise _missing_selector(path, "selector item must be a mapping")
        targets.extend(
            [
                (debt, "opened_quote", f"{path}.opened_quote"),
                (debt, "closed_quote", f"{path}.closed_quote"),
            ]
        )

    targets.extend(
        [
            (packaging, "hook_promise", "script_method.chxp_v1.packaging.hook_promise"),
            (packaging, "final_payoff", "script_method.chxp_v1.packaging.final_payoff"),
            (evidence, "value_delivered_quote", "friend_close.evidence.value_delivered_quote"),
            (evidence, "core_answer_quote", "friend_close.evidence.core_answer_quote"),
            (evidence, "cta_quote", "friend_close.evidence.cta_quote"),
        ]
    )
    return targets


def _resolve_selector(
    selector: Any,
    source_index: dict[tuple[str, str], str],
    path: str,
) -> str:
    if not isinstance(selector, dict):
        raise _missing_selector(path, "expected {timestamp, dialogue_key} mapping")
    if set(selector) != {"timestamp", "dialogue_key"}:
        raise _missing_selector(path, "selector keys must be exactly timestamp and dialogue_key")

    timestamp = selector.get("timestamp")
    dialogue_key = selector.get("dialogue_key")
    if not isinstance(timestamp, str) or not timestamp.strip() or _is_placeholder(timestamp):
        raise _missing_selector(f"{path}.timestamp", "non-placeholder timestamp is required")
    if not isinstance(dialogue_key, str) or not dialogue_key.strip() or _is_placeholder(dialogue_key):
        raise _missing_selector(f"{path}.dialogue_key", "non-placeholder dialogue_key is required")
    timestamp = unicodedata.normalize("NFC", timestamp.strip())
    dialogue_key = unicodedata.normalize("NFC", dialogue_key.strip())
    if not _is_dialogue_key(dialogue_key):
        raise QuoteDerivationError(
            "wrong_speaker",
            f"{path}.dialogue_key",
            f"{dialogue_key!r} is not 台詞 or 台詞_*",
        )

    source_key = (timestamp, dialogue_key)
    if source_key not in source_index:
        raise QuoteDerivationError(
            "source_not_found",
            path,
            f"no canonical dialogue for timestamp={timestamp!r}, dialogue_key={dialogue_key!r}",
        )
    source_text = source_index[source_key]
    if not source_text.strip() or _is_placeholder(source_text):
        raise QuoteDerivationError(
            "empty_source",
            path,
            f"canonical dialogue at timestamp={timestamp!r}, dialogue_key={dialogue_key!r} "
            "is empty or placeholder",
        )
    return source_text


def derive_quote_view(
    data: dict[str, Any],
    *,
    check_hash: bool = True,
) -> dict[str, Any]:
    """Return a deep-copied runtime view with every v1 selector resolved.

    A document without either quote-contract key is legacy and is returned
    unchanged in meaning (as a deep copy).  A hash without a version is an
    invalid half-downgrade, and any present but unsupported version fails
    closed.  ``check_hash=False`` exists only for the explicit ``--write`` path,
    which must be able to repair a missing/stale hash after all selectors have
    first validated.
    """

    if not isinstance(data, dict):
        raise QuoteDerivationError("invalid_document", "$", "YAML root must be a mapping")
    if "quote_derivation_version" not in data:
        if "quote_source_hash" in data:
            raise QuoteDerivationError(
                "orphan_hash",
                "quote_source_hash",
                "quote_source_hash requires quote_derivation_version",
            )
        return copy.deepcopy(data)

    version = data.get("quote_derivation_version")
    if type(version) is not int or version != QUOTE_DERIVATION_VERSION:
        raise QuoteDerivationError(
            "unsupported_version",
            "quote_derivation_version",
            f"expected integer {QUOTE_DERIVATION_VERSION}, got {version!r}",
        )

    dialogue_rows = collect_final_dialogue(data)
    source_index = {
        (row["timestamp"], row["dialogue_key"]): row["text"] for row in dialogue_rows
    }
    view = copy.deepcopy(data)
    for parent, key, path in _quote_targets(view):
        if key not in parent:
            raise _missing_selector(path)
        parent[key] = _resolve_selector(parent[key], source_index, path)

    if check_hash:
        stored_hash = data.get("quote_source_hash")
        if not isinstance(stored_hash, str) or not stored_hash.strip():
            raise QuoteDerivationError(
                "missing_hash", "quote_source_hash", "run derive_quotes.py --write"
            )
        stored_hash = stored_hash.strip()
        if not _DIALOGUE_HASH_RE.fullmatch(stored_hash):
            raise QuoteDerivationError(
                "invalid_hash", "quote_source_hash", "expected 64 lowercase hex characters"
            )
        actual_hash = dialogue_sha256(data)
        if not hmac.compare_digest(stored_hash, actual_hash):
            raise QuoteDerivationError(
                "stale_hash",
                "quote_source_hash",
                f"stored={stored_hash}, actual={actual_hash}; run --write after dialogue edits",
            )
    return view


def _frontmatter_bounds(text: str) -> tuple[int, int]:
    """Return the YAML slice for pure YAML or ``---`` frontmatter + body."""

    lines = text.splitlines(keepends=True)
    if not lines or not _is_frontmatter_marker(lines[0], allow_bom=True):
        return 0, len(text)

    offset = len(lines[0])
    for line in lines[1:]:
        if _is_frontmatter_marker(line):
            return len(lines[0]), offset
        offset += len(line)
    # A single leading YAML document marker is pure YAML, not frontmatter.
    return 0, len(text)


def _is_frontmatter_marker(line: str, *, allow_bom: bool = False) -> bool:
    """True only for a column-zero ``---`` line (trailing space allowed)."""

    content = line.rstrip("\r\n").rstrip(" \t")
    if allow_bom and content.startswith("\ufeff"):
        content = content[1:]
    return content == "---"


def _load_yaml_text(text: str, source: str) -> dict[str, Any]:
    start, end = _frontmatter_bounds(text)
    data = yaml.safe_load(text[start:end])
    if not isinstance(data, dict):
        raise QuoteDerivationError(
            "invalid_document", source, "expected one YAML/frontmatter mapping document"
        )
    return data


def _load_yaml(path: Path) -> dict[str, Any]:
    return _load_yaml_text(path.read_text(encoding="utf-8"), str(path))


def _script_paths(paths: Iterable[str], batch_dirs: Iterable[str]) -> list[Path]:
    candidates: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            candidates.extend(path.glob("script_*.yaml"))
        else:
            candidates.append(path)
    for raw in batch_dirs:
        candidates.extend(Path(raw).glob("script_*.yaml"))

    result: list[Path] = []
    seen: set[str] = set()
    for path in sorted(candidates, key=lambda p: str(p)):
        if ".bak" in path.name or ".tmp" in path.name:
            continue
        key = str(path.resolve())
        if key not in seen:
            result.append(path)
            seen.add(key)
    return result


def _upsert_quote_source_hash(text: str, digest: str) -> str:
    """Surgically replace/insert the top-level hash while preserving all else."""

    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    yaml_start_index = 0
    frontmatter_limit = len(lines)
    if lines and _is_frontmatter_marker(lines[0], allow_bom=True):
        yaml_start_index = 1
        for marker_index, marker_line in enumerate(lines[1:], start=1):
            if _is_frontmatter_marker(marker_line):
                frontmatter_limit = marker_index
                break
    version_index: int | None = None
    for index in range(yaml_start_index, frontmatter_limit):
        line = lines[index]
        content = line.rstrip("\r\n")
        bom = (
            "\ufeff"
            if index == yaml_start_index and content.startswith("\ufeff")
            else ""
        )
        scan_content = content[len(bom):]
        if _TOP_LEVEL_HASH_RE.match(scan_content):
            ending = line[len(content):]
            colon_index = scan_content.find(":")
            comment = _yaml_comment_suffix(scan_content, colon_index + 1)
            lines[index] = bom + f'quote_source_hash: "{digest}"{comment}' + ending
            return "".join(lines)
        if _TOP_LEVEL_VERSION_RE.match(scan_content):
            version_index = index

    if version_index is None:
        raise QuoteDerivationError(
            "missing_version", "quote_derivation_version", "cannot write hash for a legacy file"
        )
    version_content = lines[version_index].rstrip("\r\n")
    version_ending = lines[version_index][len(version_content):]
    hash_ending = newline
    if not version_ending:
        # If version was the final no-newline line, separate it from the new
        # hash while preserving the original no-newline EOF on the hash line.
        lines[version_index] += newline
        hash_ending = ""
    lines.insert(version_index + 1, f'quote_source_hash: "{digest}"{hash_ending}')
    return "".join(lines)


def _yaml_comment_suffix(content: str, value_start: int) -> str:
    """Return a real YAML comment (including its spacing), not ``#`` in a scalar."""

    in_single = False
    in_double = False
    escaped = False
    index = value_start
    while index < len(content):
        char = content[index]
        if in_double:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_double = False
        elif in_single:
            if char == "'":
                if index + 1 < len(content) and content[index + 1] == "'":
                    index += 1
                else:
                    in_single = False
        elif char == '"':
            in_double = True
        elif char == "'":
            in_single = True
        elif char == "#" and (index == value_start or content[index - 1].isspace()):
            suffix_start = index
            while suffix_start > value_start and content[suffix_start - 1] in " \t":
                suffix_start -= 1
            return content[suffix_start:]
        index += 1
    return ""


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Durably stage ``payload`` beside ``path`` and atomically replace it."""

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                # Preserve the original write/replace error.  The batch-level
                # diagnostic reports the target that was not replaced.
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate/refresh G11 quote selectors and canonical dialogue hash"
    )
    parser.add_argument("paths", nargs="*", help="script YAML file or batch directory")
    parser.add_argument(
        "--batch-dir", action="append", default=[], help="batch directory (repeatable)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate only (default)")
    mode.add_argument("--write", action="store_true", help="write quote_source_hash only")
    args = parser.parse_args(argv)

    targets = _script_paths(args.paths, args.batch_dir)
    if not targets:
        parser.error("provide at least one script YAML or --batch-dir containing script_*.yaml")

    prepared: list[tuple[Path, str, str]] = []
    errors: list[tuple[Path, str]] = []
    skipped: list[Path] = []
    for path in targets:
        try:
            if not path.is_file():
                raise QuoteDerivationError("missing_file", str(path), "file does not exist")
            data = _load_yaml(path)
            if (
                "quote_derivation_version" not in data
                and "quote_source_hash" not in data
            ):
                skipped.append(path)
                continue

            if args.write:
                derive_quote_view(data, check_hash=False)
                digest = dialogue_sha256(data)
                # read_text() performs universal-newline conversion; decode bytes
                # directly so a one-line hash refresh cannot normalize the file.
                old_text = path.read_bytes().decode("utf-8")
                new_text = _upsert_quote_source_hash(old_text, digest)
                # Verify the exact candidate before any file in this invocation is changed.
                candidate_data = _load_yaml_text(new_text, str(path))
                derive_quote_view(candidate_data, check_hash=True)
                prepared.append((path, old_text, new_text))
            else:
                derive_quote_view(data, check_hash=True)
                prepared.append((path, "", ""))
        except (OSError, UnicodeError, yaml.YAMLError, QuoteDerivationError) as exc:
            errors.append((path, str(exc)))

    if errors:
        for path, detail in errors:
            print(f"[FAIL] {path}: {detail}", file=sys.stderr)
        print(f"[FAIL] {len(errors)}/{len(targets)} file(s) invalid; no files written", file=sys.stderr)
        return 1

    changed = 0
    if args.write:
        changed_prepared = [
            (path, old_text, new_text)
            for path, old_text, new_text in prepared
            if new_text != old_text
        ]
        written: list[Path] = []
        unchanged = [path for path, old_text, new_text in prepared if new_text == old_text]
        for write_index, (path, old_text, new_text) in enumerate(changed_prepared):
            if new_text != old_text:
                try:
                    _atomic_write_bytes(path, new_text.encode("utf-8"))
                except OSError as exc:
                    not_written = [item[0] for item in changed_prepared[write_index:]]
                    print(f"[FAIL] {path}: atomic write failed: {exc}", file=sys.stderr)
                    print(
                        f"[FAIL] batch write incomplete; already written ({len(written)}): "
                        f"{', '.join(map(str, written)) or 'none'}",
                        file=sys.stderr,
                    )
                    print(
                        f"[FAIL] not written ({len(not_written)}): "
                        f"{', '.join(map(str, not_written)) or 'none'}",
                        file=sys.stderr,
                    )
                    print(
                        f"[INFO] unchanged/no write needed ({len(unchanged)}): "
                        f"{', '.join(map(str, unchanged)) or 'none'}",
                        file=sys.stderr,
                    )
                    return 1
                written.append(path)
                changed += 1
                print(f"[WRITE] {path}")
        for path in unchanged:
            print(f"[UNCHANGED] {path}")
        print(f"[OK] {len(prepared)} checked, {changed} hash line(s) changed, {len(skipped)} legacy skipped")
    else:
        for path, _, _ in prepared:
            print(f"[PASS] {path}")
        for path in skipped:
            print(f"[SKIP] {path}: legacy (no quote_derivation_version)")
        print(f"[OK] {len(prepared)} v1 checked, {len(skipped)} legacy skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
