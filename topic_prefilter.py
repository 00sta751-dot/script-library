#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真題選題粗篩 advisory wrapper。

三種輸入模式只讀真實 title；good/uncertain/weak 映射成綠/黃/紅，
黃與紅都只發 WARN、不硬擋。分類器是封存 topic-prefilter-v2.0.0 的
決定論核心內化版，不 import 執行資料夾或網路服務。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")


REPORT_SCHEMA_VERSION = "topic_prefilter_advisory_v1"
BRIEF_SCHEMA_VERSION = "topic_prefilter_brief_v1"
CALIBRATION_SCHEMA_VERSION = "prefilter_calibration_set_v1"
CLASSIFIER_VERSION = "topic-prefilter-v2.0.0"

_PLACEHOLDER_RE = re.compile(r"\[編劇填\]|待填|TODO", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERDICT_VIEW = {
    "good": ("綠", "PASS"),
    "uncertain": ("黃", "WARN"),
    "weak": ("紅", "WARN"),
}


class PrefilterInputError(RuntimeError):
    """CLI、輸入資料或 verify 契約錯誤（exit 2）。"""


class PrefilterMutationError(RuntimeError):
    """clear-only provenance mutation 失敗（exit 3）。"""


@dataclass(frozen=True)
class NamedPattern:
    key: str
    label: str
    pattern: re.Pattern[str]


@dataclass
class LoadedItem:
    script_id: str
    owner: str
    title: str
    source_file: str
    input_sha256: str
    source_topic_intel: dict[str, Any] | None
    source_path: Path | None = None


@dataclass
class InputBundle:
    mode: str
    source: Path
    input_sha256: str
    items: list[LoadedItem]


def _patterns(rows: Sequence[tuple[str, str, str]]) -> tuple[NamedPattern, ...]:
    return tuple(
        NamedPattern(key, label, re.compile(pattern))
        for key, label, pattern in rows
    )


# 封存 v2 的可泛化情境語意群；不是題名白名單。
SCENE_PATTERNS = _patterns(
    (
        (
            "money_or_transaction",
            "金錢／交易的具體對象",
            r"錢|存款|預算|薪水|債|價格|定價|花費|花錢|存錢|省錢|"
            r"越省|提錢|屋主|房(?:子|屋)?|委託|買|賣|虧|窮",
        ),
        (
            "relationship_context",
            "關係與互動情境",
            r"感情|婚姻|伴侶|另一半|家人|朋友|同事|客戶|學員|孩子|"
            r"包容|怨氣|人品|開口|說還好|冷戰|分手|被看到",
        ),
        (
            "health_beauty_context",
            "健康／美容的明確困擾",
            r"健康|生病|睡眠|失眠|痘(?:疤|印)?|疤|皮膚|保養|美容(?:儀)?|"
            r"掉髮|過敏|疼痛",
        ),
        (
            "work_or_progress_context",
            "工作／進度的具體載體",
            r"工作|職場|離職|創業|生意|手藝|行事曆|清單|進度表|"
            r"順位|排第|截止|排程|做不久",
        ),
        (
            "felt_problem",
            "可辨識的心理痛點",
            r"焦慮|擔心|害怕|恐慌|壓力|後悔|怨氣|孤單|內耗|"
            r"怕(?:被|做|選|決定)|做決定|搞錯方向|被取消|被拒絕",
        ),
        (
            "habit_problem",
            "戒除／習慣的明確困境",
            r"戒不掉|改不掉|停不下來|意志力.{0,5}(?:戒|習慣)|"
            r"(?:戒|習慣).{0,5}意志力",
        ),
        (
            "social_comparison",
            "與他人的可辨識比較情境",
            r"(?:大家|別人|同齡人|朋友).{0,6}(?:看起來|都有|已經)|"
            r"跟(?:大家|別人|同齡人).{0,6}比",
        ),
        (
            "observable_interaction",
            "可觀察的互動動作",
            r"等(?:他|她|對方).{0,5}開口|誰.{0,4}提(?:錢|分手|離職)|"
            r"排.{0,4}順位|抄.{0,4}(?:表|作業)|買.{0,5}沒.{0,3}用",
        ),
        (
            "visibility_or_preparation",
            "等待準備／害怕曝光的心理情境",
            r"等.{0,5}準備|準備.{0,5}(?:好|被看到)|怕.{0,4}被看到|"
            r"不敢.{0,5}(?:發|說|露面|開始)",
        ),
        (
            "personal_tradeoff",
            "可辨識的個人代價",
            r"犧牲.{0,5}(?:健康|睡眠|家庭|關係)|"
            r"(?:健康|睡眠|家庭|關係).{0,5}犧牲",
        ),
    )
)


SLOGAN_PATTERNS = _patterns(
    (
        (
            "absolute_causality",
            "絕對因果式口號",
            r"(?:沒有|只要|唯有|必須|一定要).{1,14}[，,\s]*"
            r"(?:才|就)(?:能|會|知道|懂|是|有)",
        ),
        (
            "turning_point_metaphor",
            "轉折點隱喻式金句",
            r"(?:那|這)(?:一)?(?:刻|天|次|步|關).{0,8}[，,\s]*"
            r"(?:才是|就是|便是)",
        ),
        (
            "generic_challenge",
            "未綁定對象的激問式挑戰",
            r"(?:你|妳)(?:說|覺得|認為|以為|相信).{0,14}"
            r"(?:還是|其實|只是|根本)(?:你|妳)?.{1,14}$",
        ),
        (
            "subjectless_inspiration",
            "無主詞勵志祈使",
            r"^(?:別|不要|一定要|必須|學會|記得|試著).{0,12}"
            r"(?:相信|努力|堅持|勇敢|往前|做自己|別放棄)",
        ),
    )
)


ABSTRACT_TERMS = (
    "人生", "夢想", "努力", "堅持", "勇敢", "成長", "改變", "未來",
    "做自己", "成功", "選擇", "放棄", "奇蹟", "方向", "希望", "可能",
    "能力", "態度", "價值", "意義", "命運", "機會", "決心", "潛力", "信念",
)
OBJECTLESS_ACTIONS = (
    "堅持", "努力", "放棄", "改變", "成長", "做到", "相信", "勇敢",
    "成功", "失敗", "突破", "前進",
)
TARGETED_QUESTION_RE = re.compile(
    r"為什麼|怎麼(?:辦|做)?|第(?:幾|多少)|哪(?:個|裡|一)|誰|"
    r"多久|多少|該不該|要不要|有沒有|[?？]"
)
ALTERNATIVE_QUESTION_RE = re.compile(r"還是|或者是|抑或")
PERSON_RE = re.compile(r"你|妳|我|他|她|大家|別人|屋主|客戶|學員|家人|朋友")
SECOND_PERSON_RE = re.compile(r"你|妳")
FIRST_PERSON_RE = re.compile(r"我")
BALANCED_RE = re.compile(
    r"[，,\s](?:才是|就是|不是|其實|還是|有時不是)|"
    r"(?:不是.{1,10}[，,\s]*(?:而)?是)|"
    r"^(.{1,6})(?:，|,|\s)+\1"
)
SUBJECTLESS_IMPERATIVE_RE = re.compile(
    r"^(?:別|不要|先|記得|一定要|必須|學會|試著)"
)


def _normalise_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matched(
    patterns: Iterable[NamedPattern], title: str
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for item in patterns:
        found = item.pattern.search(title)
        if found:
            matches.append(
                {
                    "key": item.key,
                    "label": item.label,
                    "evidence": found.group(0),
                }
            )
    return matches


def _abstract_features(title: str) -> tuple[list[str], str]:
    compact = re.sub(r"[^\w\u3400-\u9fff]", "", title)
    if not compact:
        return [], "sparse"
    covered: set[int] = set()
    hits: list[str] = []
    for term in ABSTRACT_TERMS:
        positions = list(re.finditer(re.escape(term), compact))
        if not positions:
            continue
        hits.append(term)
        for match in positions:
            covered.update(range(match.start(), match.end()))
    ratio = len(covered) / len(compact)
    if ratio >= 0.30:
        band = "dense"
    elif ratio >= 0.15:
        band = "mixed"
    else:
        band = "sparse"
    return hits, band


def _unique_terms(title: str, candidates: Iterable[str]) -> list[str]:
    return [term for term in candidates if term in title]


def _reason_good(
    scene_matches: list[dict[str, str]], targeted_question: bool
) -> str:
    labels = list(dict.fromkeys(item["label"] for item in scene_matches))
    evidence = "、".join(f"「{label}」" for label in labels[:2])
    if targeted_question:
        return f"題目以明確提問連到{evidence}，對象與痛點可形成可想像的情境；保留。"
    return f"題目已綁定{evidence}，不是只靠抽象金句成立；保留。"


def _reason_weak(
    slogan_matches: list[dict[str, str]],
    abstract_band: str,
    objectless_actions: list[str],
) -> str:
    labels = list(dict.fromkeys(item["label"] for item in slogan_matches))
    structure = "、".join(f"「{label}」" for label in labels[:2]) or "「對仗金句」"
    missing = "核心動作沒有說明作用對象或發生情境"
    if abstract_band == "dense" and objectless_actions:
        return f"呈現{structure}，抽象語彙集中，且{missing}；擋修題目切角。"
    return f"呈現{structure}，但{missing}，觀眾難以想像痛點畫面；擋修題目切角。"


def classify_title(title: str) -> dict[str, Any]:
    """封存 v2 deterministic core；不讀 owner、gold label 或外部服務。"""
    title = _normalise_title(title)
    if not title:
        raise PrefilterInputError("題名不可空白")

    scene_matches = _matched(SCENE_PATTERNS, title)
    slogan_matches = _matched(SLOGAN_PATTERNS, title)
    abstract_terms, abstract_band = _abstract_features(title)
    objectless_actions = _unique_terms(title, OBJECTLESS_ACTIONS)
    targeted_question = bool(TARGETED_QUESTION_RE.search(title))
    alternative_question = bool(ALTERNATIVE_QUESTION_RE.search(title))
    second_person = bool(SECOND_PERSON_RE.search(title))
    first_person = bool(FIRST_PERSON_RE.search(title))
    has_person = bool(PERSON_RE.search(title))
    balanced = bool(BALANCED_RE.search(title))
    subjectless_imperative = (
        bool(SUBJECTLESS_IMPERATIVE_RE.search(title)) and not has_person
    )
    concrete_second_person = second_person and bool(scene_matches)

    if scene_matches:
        verdict = "good"
        reason = _reason_good(scene_matches, targeted_question)
        decision_rule = "scene_first_keep"
    elif slogan_matches or subjectless_imperative:
        verdict = "weak"
        reason = _reason_weak(
            slogan_matches, abstract_band, objectless_actions
        )
        decision_rule = "unbound_slogan_block"
    else:
        verdict = "uncertain"
        reason = (
            "題目尚未提供足以形成畫面的對象／情境，但口號結構證據也不足；"
            "送人工複核，不直接誤殺。"
        )
        decision_rule = "insufficient_evidence_warn"

    return {
        "verdict": verdict,
        "reason": reason,
        "decision_rule": decision_rule,
        "features": {
            "scene_signals": scene_matches,
            "slogan_structures": slogan_matches,
            "balanced_clause": balanced,
            "subjectless_imperative": subjectless_imperative,
            "abstract_terms": abstract_terms,
            "abstract_density_band": abstract_band,
            "objectless_actions": objectless_actions,
            "second_person": second_person,
            "second_person_with_concrete_scene": concrete_second_person,
            "first_person": first_person,
            "targeted_question": targeted_question,
            "alternative_question": alternative_question,
        },
    }


def _load_single_mapping(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        documents = [doc for doc in yaml.safe_load_all(text) if doc is not None]
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PrefilterInputError(f"{path}: YAML 讀取/解析失敗：{exc}") from exc
    if len(documents) != 1 or not isinstance(documents[0], dict):
        raise PrefilterInputError(f"{path}: 預期恰有一個非空 YAML mapping")
    return documents[0], raw


def _require_text(value: Any, field: str, source: str) -> str:
    if not isinstance(value, str):
        raise PrefilterInputError(f"{source}: {field} 必須是字串")
    text = _normalise_title(value)
    if not text:
        raise PrefilterInputError(f"{source}: {field} 不可空白")
    return text


def _validate_title(title: str, source: str) -> None:
    match = _PLACEHOLDER_RE.search(title)
    if match:
        raise PrefilterInputError(
            f"{source}: title 仍含 placeholder {match.group(0)!r}"
        )


def _normalise_provenance(value: Any, source: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise PrefilterInputError(
            f"{source}: source_topic_intel 必須是 mapping 或不存在"
        )
    try:
        _canonical_json_sha256(value)
    except PrefilterInputError as exc:
        raise PrefilterInputError(f"{source}: source_topic_intel 無法 canonicalize：{exc}") from exc
    return value


def _json_canonical_value(value: Any, stack: set[int] | None = None) -> Any:
    if stack is None:
        stack = set()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PrefilterInputError("canonical JSON 不接受 NaN/Infinity")
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        object_id = id(value)
        if object_id in stack:
            raise PrefilterInputError("canonical JSON 不接受循環 mapping alias")
        if any(not isinstance(key, str) for key in value):
            raise PrefilterInputError("canonical JSON mapping key 必須全為字串")
        stack.add(object_id)
        try:
            return {
                key: _json_canonical_value(item, stack)
                for key, item in value.items()
            }
        finally:
            stack.remove(object_id)
    if isinstance(value, (list, tuple)):
        object_id = id(value)
        if object_id in stack:
            raise PrefilterInputError("canonical JSON 不接受循環 sequence alias")
        stack.add(object_id)
        try:
            return [_json_canonical_value(item, stack) for item in value]
        finally:
            stack.remove(object_id)
    raise PrefilterInputError(
        f"canonical JSON 不支援型別：{type(value).__name__}"
    )


def _canonical_json_sha256(value: Any) -> str:
    try:
        canonical = json.dumps(
            _json_canonical_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise PrefilterInputError(f"canonical JSON 失敗：{exc}") from exc
    return _sha256_text(canonical)


def _aggregate_batch_sha(items: list[LoadedItem]) -> str:
    rows = [
        {
            "script_id": item.script_id,
            "source_file": item.source_file,
            "input_sha256": item.input_sha256,
        }
        for item in sorted(items, key=lambda row: row.script_id)
    ]
    return _canonical_json_sha256(rows)


def _load_batch_dir(path: Path) -> InputBundle:
    if not path.is_dir():
        raise PrefilterInputError(f"--batch-dir 不是目錄：{path}")
    paths = sorted(item for item in path.glob("script_*.yaml") if item.is_file())
    if not paths:
        raise PrefilterInputError(f"--batch-dir 找不到 script_*.yaml：{path}")

    items: list[LoadedItem] = []
    seen_ids: set[str] = set()
    for source_path in paths:
        document, raw = _load_single_mapping(source_path)
        script_id = _require_text(
            document.get("script_id"), "script_id", source_path.name
        )
        owner = _require_text(document.get("owner"), "owner", source_path.name)
        title = _require_text(document.get("title"), "title", source_path.name)
        _validate_title(title, source_path.name)
        if script_id in seen_ids:
            raise PrefilterInputError(f"script_id 重複：{script_id}")
        seen_ids.add(script_id)
        items.append(
            LoadedItem(
                script_id=script_id,
                owner=owner,
                title=title,
                source_file=source_path.name,
                input_sha256=_sha256_bytes(raw),
                source_topic_intel=_normalise_provenance(
                    document.get("source_topic_intel"), source_path.name
                ),
                source_path=source_path,
            )
        )
    return InputBundle(
        mode="batch_dir",
        source=path.resolve(),
        input_sha256=_aggregate_batch_sha(items),
        items=sorted(items, key=lambda row: row.script_id),
    )


def _load_brief(path: Path) -> InputBundle:
    document, raw = _load_single_mapping(path)
    if document.get("schema_version") != BRIEF_SCHEMA_VERSION:
        raise PrefilterInputError(
            f"{path.name}: schema_version 必須是 {BRIEF_SCHEMA_VERSION}"
        )
    records = document.get("items")
    if not isinstance(records, list) or not records:
        raise PrefilterInputError(f"{path.name}: items 必須是非空 list")

    items: list[LoadedItem] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(records, 1):
        source = f"{path.name} items[{index}]"
        if not isinstance(record, dict):
            raise PrefilterInputError(f"{source}: 必須是 mapping")
        script_id = _require_text(record.get("script_id"), "script_id", source)
        owner = _require_text(record.get("owner"), "owner", source)
        title = _require_text(record.get("title"), "title", source)
        _validate_title(title, source)
        if script_id in seen_ids:
            raise PrefilterInputError(f"script_id 重複：{script_id}")
        seen_ids.add(script_id)
        items.append(
            LoadedItem(
                script_id=script_id,
                owner=owner,
                title=title,
                source_file=path.name,
                input_sha256=_canonical_json_sha256(record),
                source_topic_intel=_normalise_provenance(
                    record.get("source_topic_intel"), source
                ),
            )
        )
    return InputBundle(
        mode="brief",
        source=path.resolve(),
        input_sha256=_sha256_bytes(raw),
        items=sorted(items, key=lambda row: row.script_id),
    )


def _load_calibration(path: Path) -> InputBundle:
    document, raw = _load_single_mapping(path)
    if document.get("schema_version") != CALIBRATION_SCHEMA_VERSION:
        raise PrefilterInputError(
            f"{path.name}: schema_version 必須是 {CALIBRATION_SCHEMA_VERSION}"
        )
    records = document.get("items")
    if not isinstance(records, list) or not records:
        raise PrefilterInputError(f"{path.name}: items 必須是非空 list")
    declared_count = document.get("item_count")
    if declared_count is not None and declared_count != len(records):
        raise PrefilterInputError(
            f"{path.name}: item_count={declared_count!r} 與 items={len(records)} 不符"
        )

    items: list[LoadedItem] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(records, 1):
        source = f"{path.name} items[{index}]"
        if not isinstance(record, dict):
            raise PrefilterInputError(f"{source}: 必須是 mapping")
        script_id = _require_text(record.get("script_id"), "script_id", source)
        owner = _require_text(record.get("owner"), "owner", source)
        title = _require_text(record.get("title"), "title", source)
        _validate_title(title, source)
        source_sha = str(record.get("source_sha256") or "").strip().casefold()
        if not _SHA256_RE.fullmatch(source_sha):
            raise PrefilterInputError(f"{source}: source_sha256 格式錯誤")
        if script_id in seen_ids:
            raise PrefilterInputError(f"script_id 重複：{script_id}")
        seen_ids.add(script_id)
        items.append(
            LoadedItem(
                script_id=script_id,
                owner=owner,
                title=title,
                source_file=str(record.get("fixture_file") or path.name),
                input_sha256=source_sha,
                source_topic_intel=None,
            )
        )
    return InputBundle(
        mode="calibration",
        source=path.resolve(),
        input_sha256=_sha256_bytes(raw),
        items=sorted(items, key=lambda row: row.script_id),
    )


def _load_input(args: argparse.Namespace) -> InputBundle:
    if args.batch_dir is not None:
        return _load_batch_dir(Path(args.batch_dir))
    if args.brief is not None:
        return _load_brief(Path(args.brief))
    return _load_calibration(Path(args.calibration))


def _provenance_fingerprint(value: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "present": value is not None,
        "sha256": _canonical_json_sha256(value) if value is not None else None,
    }


def _build_report(bundle: InputBundle) -> dict[str, Any]:
    report_items: list[dict[str, Any]] = []
    counts = {"green": 0, "yellow": 0, "red": 0, "warn": 0}
    for item in bundle.items:
        core = classify_title(item.title)
        flag, status = _VERDICT_VIEW[core["verdict"]]
        if flag == "綠":
            counts["green"] += 1
        elif flag == "黃":
            counts["yellow"] += 1
        else:
            counts["red"] += 1
        if status == "WARN":
            counts["warn"] += 1
        report_items.append(
            {
                "script_id": item.script_id,
                "owner": item.owner,
                "source_file": item.source_file,
                "input_sha256": item.input_sha256,
                "title": item.title,
                "title_sha256": _sha256_text(item.title),
                "verdict": core["verdict"],
                "flag": flag,
                "status": status,
                "blocking": False,
                "reason": core["reason"],
                "decision_rule": core["decision_rule"],
                "provenance_fingerprint": _provenance_fingerprint(
                    item.source_topic_intel
                ),
                "features": core["features"],
            }
        )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
        "blocking": False,
        "input": {
            "mode": bundle.mode,
            "source": str(bundle.source),
            "input_sha256": bundle.input_sha256,
            "item_count": len(bundle.items),
        },
        "summary": counts,
        "items": report_items,
    }


def _read_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PrefilterInputError(f"report 無法讀取：{path}: {exc}") from exc
    if not isinstance(report, dict):
        raise PrefilterInputError(f"report root 必須是 object：{path}")
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise PrefilterInputError(
            f"report schema_version 必須是 {REPORT_SCHEMA_VERSION}"
        )
    if report.get("classifier_version") != CLASSIFIER_VERSION:
        raise PrefilterInputError(
            f"report classifier_version 必須是 {CLASSIFIER_VERSION}"
        )
    if report.get("blocking") is not False:
        raise PrefilterInputError("report blocking 必須是 false")
    if not isinstance(report.get("items"), list):
        raise PrefilterInputError("report items 必須是 list")
    return report


def _report_items_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(report["items"], 1):
        if not isinstance(item, dict):
            raise PrefilterInputError(f"report items[{index}] 必須是 object")
        script_id = str(item.get("script_id") or "").strip()
        if not script_id or script_id in by_id:
            raise PrefilterInputError(
                f"report script_id 空白或重複：{script_id!r}"
            )
        title = item.get("title")
        title_hash = str(item.get("title_sha256") or "")
        if (
            not isinstance(title, str)
            or not _SHA256_RE.fullmatch(title_hash)
            or _sha256_text(_normalise_title(title)) != title_hash
        ):
            raise PrefilterInputError(
                f"report id={script_id!r} title/title_sha256 內部不一致"
            )
        by_id[script_id] = item
    return by_id


def _verify_report(bundle: InputBundle, report_path: Path) -> None:
    report = _read_report(report_path)
    expected = _report_items_by_id(report)
    current = {item.script_id: item for item in bundle.items}
    if set(expected) != set(current):
        raise PrefilterInputError(
            "--verify-report script_id 集合漂移，請回 3A："
            f"missing={sorted(set(expected) - set(current))}, "
            f"extra={sorted(set(current) - set(expected))}"
        )
    drift: list[str] = []
    for script_id in sorted(current):
        old_hash = str(expected[script_id].get("title_sha256") or "")
        new_hash = _sha256_text(current[script_id].title)
        if old_hash != new_hash:
            drift.append(script_id)
    if drift:
        raise PrefilterInputError(
            f"--verify-report title hash 漂移，請回 3A：{drift}"
        )


def _clear_block_bytes(
    source_path: Path, original: bytes
) -> tuple[bytes, bool]:
    had_bom = original.startswith(b"\xef\xbb\xbf")
    try:
        text = original.decode("utf-8-sig")
    except UnicodeError as exc:
        raise PrefilterMutationError(f"{source_path.name}: 非 UTF-8：{exc}") from exc
    try:
        original_documents = [
            doc for doc in yaml.safe_load_all(text) if doc is not None
        ]
    except yaml.YAMLError as exc:
        raise PrefilterMutationError(
            f"{source_path.name}: clear 前 YAML 無法解析：{exc}"
        ) from exc
    if (
        len(original_documents) != 1
        or not isinstance(original_documents[0], dict)
    ):
        raise PrefilterMutationError(
            f"{source_path.name}: clear 前不是單一 YAML mapping"
        )
    if "source_topic_intel" not in original_documents[0]:
        return original, False

    lines = text.splitlines(keepends=True)
    key_pattern = re.compile(
        r"^(?P<indent>[ \t]*)(?:source_topic_intel|"
        r"\"source_topic_intel\"|'source_topic_intel')\s*:"
    )
    matches: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        match = key_pattern.match(line.rstrip("\r\n"))
        if match:
            matches.append((index, len(match.group("indent"))))
    if not matches:
        raise PrefilterMutationError(
            f"{source_path.name}: parsed block 存在，但無法安全定位原文 span"
        )
    root_indent = min(indent for _index, indent in matches)
    starts = [index for index, indent in matches if indent == root_indent]
    if len(starts) != 1:
        raise PrefilterMutationError(
            f"{source_path.name}: source_topic_intel 頂層 block 不只一處"
        )

    start = starts[0]
    end = start + 1
    while end < len(lines):
        line = lines[end]
        body = line.rstrip("\r\n")
        stripped = body.lstrip(" \t")
        indent = len(body) - len(stripped)
        if stripped and indent > root_indent:
            end += 1
            continue
        if not stripped:
            lookahead = end + 1
            while lookahead < len(lines) and not lines[lookahead].strip():
                lookahead += 1
            if lookahead < len(lines):
                next_body = lines[lookahead].rstrip("\r\n")
                next_stripped = next_body.lstrip(" \t")
                next_indent = len(next_body) - len(next_stripped)
            else:
                next_indent = -1
            if next_indent > root_indent:
                end += 1
                continue
        if stripped.startswith("#") and indent > root_indent:
            end += 1
            continue
        break

    updated_text = "".join(lines[:start] + lines[end:])
    updated = (b"\xef\xbb\xbf" if had_bom else b"") + updated_text.encode("utf-8")
    try:
        documents = [
            doc
            for doc in yaml.safe_load_all(updated.decode("utf-8-sig"))
            if doc is not None
        ]
    except yaml.YAMLError as exc:
        raise PrefilterMutationError(
            f"{source_path.name}: clear 後 YAML 無法解析：{exc}"
        ) from exc
    if len(documents) != 1 or not isinstance(documents[0], dict):
        raise PrefilterMutationError(
            f"{source_path.name}: clear 後不是單一 YAML mapping"
        )
    if "source_topic_intel" in documents[0]:
        raise PrefilterMutationError(
            f"{source_path.name}: clear 後 source_topic_intel 仍存在"
        )
    return updated, True


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    temp_path = path.with_name(path.name + ".topic_prefilter.tmp")
    try:
        with temp_path.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _run_clear(
    bundle: InputBundle,
    previous_report_path: Path,
    script_ids: list[str],
) -> list[tuple[Path, bytes]]:
    try:
        previous = _read_report(previous_report_path)
        previous_by_id = _report_items_by_id(previous)
    except PrefilterInputError as exc:
        raise PrefilterMutationError(str(exc)) from exc

    current_by_id = {item.script_id: item for item in bundle.items}
    mutations: list[tuple[Path, bytes, bytes]] = []
    for script_id in script_ids:
        item = current_by_id.get(script_id)
        old = previous_by_id.get(script_id)
        if item is None or old is None:
            raise PrefilterMutationError(
                f"clear id={script_id!r} 不在目前 batch 或 previous report"
            )
        if old.get("verdict") != "weak" or old.get("flag") != "紅":
            raise PrefilterMutationError(
                f"clear id={script_id!r} 的 previous verdict 不是 weak/紅"
            )
        old_title_hash = str(old.get("title_sha256") or "")
        if not _SHA256_RE.fullmatch(old_title_hash):
            raise PrefilterMutationError(
                f"clear id={script_id!r} previous title_sha256 無效"
            )
        if _sha256_text(item.title) == old_title_hash:
            raise PrefilterMutationError(
                f"clear id={script_id!r} title 尚未換題，拒絕移除 provenance"
            )
        if item.source_path is None:
            raise PrefilterMutationError(f"clear id={script_id!r} 缺 source path")

        original = item.source_path.read_bytes()
        updated, changed = _clear_block_bytes(item.source_path, original)
        if not changed:
            continue  # block 原已不存在：成功 no-op
        previous_fp = old.get("provenance_fingerprint")
        current_fp = _provenance_fingerprint(item.source_topic_intel)
        if not isinstance(previous_fp, dict) or previous_fp != current_fp:
            raise PrefilterMutationError(
                f"clear id={script_id!r} provenance fingerprint 漂移，拒絕刪除"
            )
        mutations.append((item.source_path, original, updated))

    written: list[tuple[Path, bytes]] = []
    try:
        for source_path, original, updated in mutations:
            _write_bytes_atomic(source_path, updated)
            written.append((source_path, original))
    except Exception as exc:
        rollback_errors = _rollback_mutations(written)
        detail = f"provenance mutation 失敗：{exc}"
        if rollback_errors:
            detail += f"；rollback 失敗={rollback_errors}"
        raise PrefilterMutationError(detail) from exc
    return written


def _rollback_mutations(written: list[tuple[Path, bytes]]) -> list[str]:
    rollback_errors: list[str] = []
    for source_path, original in reversed(written):
        try:
            _write_bytes_atomic(source_path, original)
        except Exception as rollback_exc:
            rollback_errors.append(f"{source_path.name}: {rollback_exc}")
    return rollback_errors


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")
    _write_bytes_atomic(path, payload)


def _validate_cli(args: argparse.Namespace) -> None:
    clearing = bool(args.clear_source_topic_intel)
    verifying = args.verify_report is not None
    if clearing and verifying:
        raise PrefilterInputError("clear-only 與 --verify-report 不可同時使用")
    if clearing:
        if args.batch_dir is None:
            raise PrefilterInputError("clear-only 只接受 --batch-dir")
        if args.previous_report is None:
            raise PrefilterInputError("clear-only 必須提供 --previous-report")
        if args.output is None:
            raise PrefilterInputError("clear-only 必須提供 --output")
        if len(set(args.clear_source_topic_intel)) != len(
            args.clear_source_topic_intel
        ):
            raise PrefilterInputError("--clear-source-topic-intel 不可重複同一 ID")
    else:
        if args.previous_report is not None:
            raise PrefilterInputError(
                "--previous-report 只能搭配 --clear-source-topic-intel"
            )
        if verifying:
            if args.output is not None:
                raise PrefilterInputError(
                    "--verify-report 模式不接受 --output（只驗 title hash）"
                )
        elif args.output is None:
            raise PrefilterInputError("分類模式必須提供 --output")


def _validate_output_target(
    args: argparse.Namespace, bundle: InputBundle
) -> Path | None:
    if args.output is None:
        return None
    output_path = Path(args.output)
    output_resolved = output_path.resolve()
    if args.previous_report is not None and (
        output_resolved == Path(args.previous_report).resolve()
    ):
        raise PrefilterInputError("--output 不可覆寫 --previous-report")
    source_paths = {
        item.source_path.resolve()
        for item in bundle.items
        if item.source_path is not None
    }
    if bundle.source.is_file():
        source_paths.add(bundle.source.resolve())
    if output_resolved in source_paths:
        raise PrefilterInputError("--output 不可覆寫輸入檔")
    return output_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="真題選題粗篩 advisory（WARN 不硬擋）"
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--batch-dir")
    inputs.add_argument("--brief")
    inputs.add_argument("--calibration")
    parser.add_argument("--output")
    parser.add_argument("--verify-report")
    parser.add_argument("--previous-report")
    parser.add_argument(
        "--clear-source-topic-intel",
        action="append",
        default=[],
        metavar="SCRIPT_ID",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        _validate_cli(args)
        bundle = _load_input(args)
        output_path = _validate_output_target(args, bundle)
        if args.verify_report is not None:
            _verify_report(bundle, Path(args.verify_report))
            print(
                f"[topic-prefilter] verify PASS：{len(bundle.items)} 題 title hash 未漂"
            )
            return 0

        if args.clear_source_topic_intel:
            written = _run_clear(
                bundle,
                Path(args.previous_report),
                args.clear_source_topic_intel,
            )
            try:
                bundle = _load_batch_dir(Path(args.batch_dir))
                report = _build_report(bundle)
                assert output_path is not None
                _write_report(output_path, report)
            except Exception as exc:
                rollback_errors = _rollback_mutations(written)
                detail = f"clear 後 report transaction 失敗，已回滾 YAML：{exc}"
                if rollback_errors:
                    detail += f"；rollback 失敗={rollback_errors}"
                raise PrefilterMutationError(detail) from exc
            summary = report["summary"]
            print(
                "[topic-prefilter] advisory PASS："
                f"綠={summary['green']} 黃={summary['yellow']} "
                f"紅={summary['red']} WARN={summary['warn']} "
                f"blocking=false → {output_path}"
            )
            return 0

        report = _build_report(bundle)
        assert output_path is not None
        _write_report(output_path, report)
        summary = report["summary"]
        print(
            "[topic-prefilter] advisory PASS："
            f"綠={summary['green']} 黃={summary['yellow']} 紅={summary['red']} "
            f"WARN={summary['warn']} blocking=false → {output_path}"
        )
        return 0
    except PrefilterMutationError as exc:
        print(f"[topic-prefilter] MUTATION ERROR: {exc}", file=sys.stderr)
        return 3
    except PrefilterInputError as exc:
        print(f"[topic-prefilter] INPUT ERROR: {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        if args.clear_source_topic_intel:
            print(f"[topic-prefilter] MUTATION ERROR: {exc}", file=sys.stderr)
            return 3
        print(f"[topic-prefilter] INPUT ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
