#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch taste-panel gate for hybrid short-video scripts.

MVP:
  python taste_panel_gate.py --batch <dir> [--rubric <path>] [--no-llm]

Real mode reuses the existing taste_panel.py reviewer/rubric. --no-llm mode
uses a local fixture file for CI.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


GATE_VERSION = "taste_panel_gate_v1"
DEFAULT_RUBRIC_DIR = Path(
    r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_腳本品質優化_2026-06\taste_panel"
)
DEFAULT_RUBRIC_PATH = DEFAULT_RUBRIC_DIR / "taste_panel_rubric_v1.yaml"
DEFAULT_MODEL_ID = "gpt-5.5"
HYBRID_BATCH_PROFILE = "hybrid_70_15_15"
BATCH_FLAGS_PROFILE_ERROR = "_batch_flags.yml 讀取/解析失敗，無法確認 batch_profile（fail-closed）"
# MVP=D1-D5 (existing rubric); D6_friend_close semantic = post-MVP,
# 交朋友 currently enforced deterministically by C-friend-close.
# To add D6: extend rubric (答案卷, needs 保鏢 + version bump).
REQUIRED_DIMS = ("D1", "D2", "D3", "D4", "D5")
PASS_THRESHOLD = 90
ALLOWED_VERDICTS = {"pass", "revise", "reject", "pending_review"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_yaml_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^---\s*\n", "", text, count=1)
    front = re.split(r"\n---\s*\n", text, maxsplit=1)[0]
    front = re.sub(r"\n---\s*$", "", front)
    data = yaml.safe_load(front) or {}
    return data if isinstance(data, dict) else {}


def list_yamls(batch_dir: Path) -> list[Path]:
    return sorted(
        p for p in batch_dir.glob("*.yaml")
        if ".bak" not in p.name and ".tmp" not in p.name
    )


def load_batch_flags_checked(batch_dir: Path) -> tuple[dict, Optional[str]]:
    flag_path = batch_dir / "_batch_flags.yml"
    if not flag_path.exists():
        return {}, None
    try:
        raw = yaml.safe_load(flag_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}, BATCH_FLAGS_PROFILE_ERROR
    if not isinstance(raw, dict):
        return {}, BATCH_FLAGS_PROFILE_ERROR
    return raw, None


def find_topic_plan(batch_dir: Path) -> Optional[Path]:
    for name in ("topic_plan.json", "_topic_plan.json"):
        path = batch_dir / name
        if path.exists():
            return path
    matches = sorted(batch_dir.glob("topic_plan*.json"))
    return matches[0] if matches else None


def topic_plan_declares_hybrid(batch_dir: Path) -> tuple[bool, Optional[str]]:
    path = find_topic_plan(batch_dir)
    if path is None:
        return False, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"topic_plan 讀取失敗: {e}"
    if not isinstance(data, dict):
        return False, "topic_plan 結構異常"
    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        return False, "topic_plan 結構異常"
    return meta.get("batch_profile") == HYBRID_BATCH_PROFILE, None


def hybrid_batch_state(batch_dir: Path) -> tuple[bool, Optional[str]]:
    yaml_has_hybrid = False
    for path in list_yamls(batch_dir):
        try:
            if load_yaml_frontmatter(path).get("content_axis"):
                yaml_has_hybrid = True
                break
        except Exception:
            continue
    flags, flags_error = load_batch_flags_checked(batch_dir)
    if flags_error:
        return False, flags_error
    flags_hybrid = flags.get("batch_profile") == HYBRID_BATCH_PROFILE
    plan_hybrid, plan_error = topic_plan_declares_hybrid(batch_dir)
    if plan_error:
        return False, plan_error
    declared_hybrid = flags_hybrid or plan_hybrid
    if declared_hybrid and not yaml_has_hybrid:
        return False, "declared hybrid but YAMLs not hybrid"
    return yaml_has_hybrid, None


def is_hybrid_batch(batch_dir: Path) -> bool:
    is_hybrid, _error = hybrid_batch_state(batch_dir)
    return is_hybrid


def scene_publish_text(data: dict) -> str:
    parts: list[str] = []
    scenes = data.get("scenes") or []
    if isinstance(scenes, list):
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            ts = scene.get("timestamp")
            if ts:
                parts.append(f"[{ts}]")
            for k, v in scene.items():
                if v is None or isinstance(v, (dict, list)):
                    continue
                key = str(k)
                if (
                    key == "timestamp"
                    or key.startswith("台詞")
                    or key in {"台詞", "dialogue", "subtitle", "caption", "CTA", "cta"}
                    or "台詞" in key
                ):
                    parts.append(str(v))
    for key in ("caption", "cta"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v)
        elif isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, str) and vv.strip():
                    parts.append(vv)
    return "\n".join(parts)


def sanitized_input(data: dict) -> dict:
    return {
        "script_id": data.get("script_id"),
        "content_axis": data.get("content_axis"),
        "lane": data.get("lane"),
        "topic_category": data.get("topic_category"),
        "final_text": scene_publish_text(data),
    }


def compute_hashes(path: Path, data: dict) -> tuple[str, str]:
    raw_hash = sha256_bytes(path.read_bytes())
    sanitized_hash = sha256_text(json.dumps(sanitized_input(data), ensure_ascii=False, sort_keys=True))
    return raw_hash, sanitized_hash


def prompt_template_hash(rubric: dict) -> str:
    prompts = rubric.get("prompts") if isinstance(rubric, dict) else {}
    if not isinstance(prompts, dict):
        prompts = {}
    return sha256_text("||".join(str(prompts.get(k, "")) for k in sorted(prompts)))


def load_rubric(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def rubric_required_dim_errors(rubric: dict) -> list[str]:
    dims = rubric.get("dimensions") if isinstance(rubric, dict) else None
    if not isinstance(dims, list):
        return ["rubric dimensions missing or not a list"]
    dim_ids = {
        str(item.get("id"))
        for item in dims
        if isinstance(item, dict) and item.get("id") is not None
    }
    missing = [dim for dim in REQUIRED_DIMS if dim not in dim_ids]
    return [f"rubric missing required dimensions: {', '.join(missing)}"] if missing else []


def load_fixture(batch_dir: Path) -> dict:
    fixture_path = batch_dir / "_taste_panel_no_llm_fixture.json"
    if not fixture_path.exists():
        return {}
    try:
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def cache_key(
    raw_hash: str,
    sanitized_hash: str,
    rubric_hash: str,
    prompt_hash: str,
    model_id: str,
    no_llm: bool,
) -> str:
    no_llm_discriminator = "nollm=1" if no_llm else "nollm=0"
    return sha256_text("|".join([
        raw_hash,
        sanitized_hash,
        rubric_hash,
        prompt_hash,
        GATE_VERSION,
        model_id,
        no_llm_discriminator,
    ]))


def verdict_from_scores(scores: dict, requested: str = "pass") -> str:
    if requested != "pass":
        return requested if requested in ALLOWED_VERDICTS else "pending_review"
    for dim in REQUIRED_DIMS:
        val = scores.get(dim)
        if not isinstance(val, (int, float)) or val < PASS_THRESHOLD:
            return "revise"
    return "pass"


def make_no_llm_report(
    path: Path,
    data: dict,
    fixture: dict,
    rubric_hash: str,
    prompt_hash: str,
    rubric_version: str,
    model_id: str,
) -> dict:
    script_id = str(data.get("script_id") or path.stem)
    overrides = fixture.get("overrides") if isinstance(fixture.get("overrides"), dict) else {}
    spec = overrides.get(script_id, {}) if isinstance(overrides, dict) else {}
    if not isinstance(spec, dict):
        spec = {}
    scores = dict(spec.get("scores") or fixture.get("default_scores") or {d: 95 for d in REQUIRED_DIMS})
    for dim in REQUIRED_DIMS:
        scores.setdefault(dim, 95)
    verdict = verdict_from_scores(scores, str(spec.get("verdict") or fixture.get("default_verdict") or "pass"))
    raw_hash, sanitized_hash = compute_hashes(path, data)
    if spec.get("stale_hash"):
        raw_hash = "stale-" + raw_hash[6:]
    ck = cache_key(raw_hash, sanitized_hash, rubric_hash, prompt_hash, model_id, no_llm=True)
    return {
        "schema_version": 1,
        "gate_version": GATE_VERSION,
        "script_id": script_id,
        "source_file": path.name,
        "content_axis": data.get("content_axis"),
        "lane": data.get("lane"),
        "verdict": verdict,
        "scores": scores,
        "dim_threshold": PASS_THRESHOLD,
        "required_dims": list(REQUIRED_DIMS),
        "blocking_reasons": list(spec.get("blocking_reasons") or ([] if verdict == "pass" else ["no-llm fixture non-pass"])),
        "raw_input_hash": raw_hash,
        "sanitized_input_hash": sanitized_hash,
        "rubric_hash": rubric_hash,
        "rubric_version": rubric_version,
        "prompt_template_hash": prompt_hash,
        "gate_cache_key": ck,
        "model_id": model_id,
        "mock_report": bool(spec.get("mock_report", False)),
        "no_llm_mode": True,
        "reviewed_at": datetime.now().isoformat(),
    }


def load_existing_taste_panel_module():
    panel_path = DEFAULT_RUBRIC_DIR / "taste_panel.py"
    spec = importlib.util.spec_from_file_location("existing_taste_panel", panel_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load taste_panel.py from {panel_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_real_report(
    path: Path,
    data: dict,
    rubric: dict,
    rubric_hash: str,
    prompt_hash: str,
    rubric_version: str,
    model_id: str,
) -> dict:
    try:
        tp = load_existing_taste_panel_module()
        raw = tp.review_script(path, rubric, mock=False)
        scores = dict(raw.get("scores") or {})
        verdict = raw.get("final_verdict", "pending_review")
        if verdict not in ALLOWED_VERDICTS:
            verdict = "pending_review"
        for dim in REQUIRED_DIMS:
            scores.setdefault(dim, None)
        if any(not isinstance(scores.get(d), (int, float)) or scores.get(d) < PASS_THRESHOLD for d in REQUIRED_DIMS):
            verdict = "revise"
        raw_hash, sanitized_hash = compute_hashes(path, data)
        return {
            "schema_version": 1,
            "gate_version": GATE_VERSION,
            "script_id": str(data.get("script_id") or path.stem),
            "source_file": path.name,
            "content_axis": data.get("content_axis"),
            "lane": data.get("lane"),
            "verdict": verdict,
            "scores": scores,
            "dim_threshold": PASS_THRESHOLD,
            "required_dims": list(REQUIRED_DIMS),
            "blocking_reasons": list(raw.get("blocking_reasons") or ([] if verdict == "pass" else ["taste_panel non-pass"])),
            "raw_input_hash": raw_hash,
            "sanitized_input_hash": sanitized_hash,
            "rubric_hash": rubric_hash,
            "rubric_version": rubric_version,
            "prompt_template_hash": prompt_hash,
            "gate_cache_key": cache_key(raw_hash, sanitized_hash, rubric_hash, prompt_hash, model_id, no_llm=False),
            "model_id": model_id,
            "mock_report": False,
            "no_llm_mode": False,
            "reviewed_at": datetime.now().isoformat(),
            "upstream_report": raw,
        }
    except Exception as e:
        raw_hash, sanitized_hash = compute_hashes(path, data)
        return {
            "schema_version": 1,
            "gate_version": GATE_VERSION,
            "script_id": str(data.get("script_id") or path.stem),
            "source_file": path.name,
            "content_axis": data.get("content_axis"),
            "lane": data.get("lane"),
            "verdict": "pending_review",
            "scores": {d: None for d in REQUIRED_DIMS},
            "dim_threshold": PASS_THRESHOLD,
            "required_dims": list(REQUIRED_DIMS),
            "blocking_reasons": [f"taste_panel error: {e}"],
            "raw_input_hash": raw_hash,
            "sanitized_input_hash": sanitized_hash,
            "rubric_hash": rubric_hash,
            "rubric_version": rubric_version,
            "prompt_template_hash": prompt_hash,
            "gate_cache_key": cache_key(raw_hash, sanitized_hash, rubric_hash, prompt_hash, model_id, no_llm=False),
            "model_id": model_id,
            "mock_report": False,
            "no_llm_mode": False,
            "reviewed_at": datetime.now().isoformat(),
        }


def validate_reports(batch_dir: Path, reports: list[dict], summary: Optional[dict], rubric_hash: str) -> list[str]:
    problems: list[str] = []
    panel_dir = batch_dir / ".taste_panel"
    if any(panel_dir.glob("*.tmp")):
        problems.append(".tmp leftover in .taste_panel")
    if summary is None:
        problems.append("summary missing")
    yamls = list_yamls(batch_dir)
    hybrid_yamls = [(p, load_yaml_frontmatter(p)) for p in yamls if load_yaml_frontmatter(p).get("content_axis")]
    if len(hybrid_yamls) != 13:
        problems.append(f"hybrid script count={len(hybrid_yamls)} expected=13")
    if len(reports) != len(hybrid_yamls):
        problems.append(f"report count={len(reports)} expected={len(hybrid_yamls)}")
    by_sid: dict[str, dict] = {}
    for rep in reports:
        sid = str(rep.get("script_id") or "")
        if not sid:
            problems.append("report missing script_id")
            continue
        if sid in by_sid:
            problems.append(f"dup script_id={sid}")
        by_sid[sid] = rep
        if rep.get("schema_version") != 1:
            problems.append(f"{sid}: schema invalid")
        if rep.get("rubric_hash") != rubric_hash:
            problems.append(f"{sid}: rubric_hash mismatch")
        if rep.get("mock_report"):
            problems.append(f"{sid}: mock report")
        if rep.get("verdict") != "pass":
            problems.append(f"{sid}: verdict={rep.get('verdict')}")
        scores = rep.get("scores") if isinstance(rep.get("scores"), dict) else {}
        for dim in REQUIRED_DIMS:
            val = scores.get(dim)
            if not isinstance(val, (int, float)) or val < PASS_THRESHOLD:
                problems.append(f"{sid}: {dim}={val} < {PASS_THRESHOLD}")
    for path, data in hybrid_yamls:
        sid = str(data.get("script_id") or path.stem)
        rep = by_sid.get(sid)
        if rep is None:
            problems.append(f"{sid}: missing report")
            continue
        raw_hash, sanitized_hash = compute_hashes(path, data)
        if rep.get("raw_input_hash") != raw_hash:
            problems.append(f"{sid}: stale raw_input_hash")
        if rep.get("sanitized_input_hash") != sanitized_hash:
            problems.append(f"{sid}: stale sanitized_input_hash")
    if summary:
        if summary.get("rubric_hash") != rubric_hash:
            problems.append("summary rubric_hash mismatch")
        if summary.get("gate_version") != GATE_VERSION:
            problems.append("summary gate_version mismatch")
        if summary.get("mock_report"):
            problems.append("summary mock report")
        if summary.get("overall_verdict") != "pass":
            problems.append(f"summary overall_verdict={summary.get('overall_verdict')}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Hybrid batch taste-panel gate")
    parser.add_argument("--batch", required=True, help="batch directory")
    parser.add_argument("--rubric", default=str(DEFAULT_RUBRIC_PATH), help="rubric yaml path")
    parser.add_argument("--no-llm", action="store_true", help="CI mode: use _taste_panel_no_llm_fixture.json")
    args = parser.parse_args()

    batch_dir = Path(args.batch)
    rubric_path = Path(args.rubric)
    if not batch_dir.exists():
        print(f"[ERROR] batch not found: {batch_dir}", file=sys.stderr)
        return 1
    hybrid_batch, hybrid_error = hybrid_batch_state(batch_dir)
    if hybrid_error:
        print(f"C-taste-panel FAIL — {hybrid_error}")
        return 1
    if not hybrid_batch:
        print("C-taste-panel N/A 非 hybrid 批")
        return 0
    if not rubric_path.exists():
        print(f"[ERROR] rubric not found: {rubric_path}", file=sys.stderr)
        return 1

    rubric_text = rubric_path.read_text(encoding="utf-8")
    rubric_hash = sha256_text(rubric_text)
    rubric = load_rubric(rubric_path)
    dim_errors = rubric_required_dim_errors(rubric)
    if dim_errors:
        print("[ERROR] " + "; ".join(dim_errors), file=sys.stderr)
        return 1
    rubric_version = str((rubric.get("meta") or {}).get("version", "unknown"))
    model_id = str((rubric.get("meta") or {}).get("model", DEFAULT_MODEL_ID))
    prompt_hash = prompt_template_hash(rubric)
    fixture = load_fixture(batch_dir) if args.no_llm else {}

    panel_dir = batch_dir / ".taste_panel"
    panel_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict] = []
    if not (args.no_llm and fixture.get("simulate_skip_reports")):
        for path in list_yamls(batch_dir):
            data = load_yaml_frontmatter(path)
            if not data.get("content_axis"):
                continue
            if args.no_llm:
                report = make_no_llm_report(path, data, fixture, rubric_hash, prompt_hash, rubric_version, model_id)
            else:
                report = make_real_report(path, data, rubric, rubric_hash, prompt_hash, rubric_version, model_id)
            reports.append(report)
            sid = report["script_id"]
            atomic_write_json(panel_dir / f"{sid}_taste_panel_report.json", report)

    verdict_counts: dict[str, int] = {}
    for rep in reports:
        v = str(rep.get("verdict"))
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
    summary = {
        "schema_version": 1,
        "gate_version": GATE_VERSION,
        "batch_dir": str(batch_dir),
        "rubric_path": str(rubric_path),
        "rubric_hash": rubric_hash,
        "rubric_version": rubric_version,
        "prompt_template_hash": prompt_hash,
        "model_id": model_id,
        "required_dims": list(REQUIRED_DIMS),
        "dim_threshold": PASS_THRESHOLD,
        "script_count": len(reports),
        "script_ids": [r.get("script_id") for r in reports],
        "verdict_counts": verdict_counts,
        "overall_verdict": "pass" if len(reports) == 13 and all(r.get("verdict") == "pass" for r in reports) else "reject",
        "mock_report": False,
        "no_llm_mode": bool(args.no_llm),
        "generated_at": datetime.now().isoformat(),
    }
    atomic_write_json(panel_dir / "_taste_panel_summary.json", summary)

    problems = validate_reports(batch_dir, reports, summary, rubric_hash)
    if problems:
        print("[taste_panel_gate] FAIL")
        for p in problems[:20]:
            print(f"  - {p}")
        return 1
    print("[taste_panel_gate] PASS all 13 scripts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
