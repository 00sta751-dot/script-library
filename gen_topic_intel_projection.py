#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_topic_intel_projection.py -- 選題情報池 per-owner projection cache 生成器
WP-B Wave 1 Step 3 / 2026-06-13

職責：
  - 掃 iter_cyborg_files()（multi-root，sha256 dedup）
  - 對每個業主產 topic_intel_projection_dir/by_owner/<owner_code>/active.json
  - 候選照 §9.1 排序 key 排序（防 golden drift）
  - 輸出 metadata：schema_version/owner/owner_dir/owner_code/aliases/
    source_pool_fingerprint/owner_projection_fingerprint/generated_at/expires_at/
    qualified_count/adapter_version/eligible_statuses

設計：
  - 自帶 _load_wpb_config（WP-B strict：sv>=3 + 3 新 key）
  - 不 import trend-daily（跨 repo 模式，仿 build_template_index.py）
  - 讀 owner_projection.generated.json 取業主 owner_code/industry/aliases
  - 候選過濾：applicable_owners 或 industry 命中
  - fingerprint：sha256(canonical JSON of sorted [(basename, sha256, mtime, size)] +
    owner_projection.json sha + 業主偏好.md sha + adapter_version + projection_schema_version)

用法：
  python gen_topic_intel_projection.py            # 產所有業主
  python gen_topic_intel_projection.py --owner 瑞祥
  python gen_topic_intel_projection.py --dry-run  # 印統計不寫檔
"""

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# UTF-8 輸出防亂碼
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 路徑常數（跨 repo 不 import trend-daily）────────────────────────────────
_TI_CONFIG_PATH = Path(r"C:\Users\00sta\claude-state\topic_intel_paths.json")

# DEFAULTS（必須與 topic_intel_paths.py DEFAULTS 完全一致，鏡像驗等值）
_TI_DEFAULTS: dict = {
    "schema_version": 3,
    "active_root": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_選題情報池",
    "old_root": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\L0_跨行業公版\_趨勢報告",
    "legacy_root": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_選題情報池\_legacy_backlog",
    "quarantine_dir": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_選題情報池\_隔離待補",
    "old_quarantine_dir": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\L0_跨行業公版\_趨勢報告\_隔離待補",
    "collision_quarantine_dir": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_選題情報池\_collision_quarantine",
    "dissect_lib_root": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_選題情報池\_爆款拆解庫",
    "migration_lock": r"C:\Users\00sta\claude-state\flags\topic_intel_migration.lock",
    "topic_intel_projection_dir": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_選題情報池\_projections",
    "topic_intel_events_dir": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_選題情報池\_events",
    "topic_intel_events_file": "topic_intel_events.jsonl",
}

# sibling
_HERE = Path(__file__).resolve().parent
_OWNER_PROJECTION_PATH = _HERE / "owner_projection.generated.json"

# projection cache TTL（讀取端新鮮度）
_PROJECTION_TTL_HOURS = 24

# active candidate TTL / fixed ranker（封存自 stage1 trend_rank_v1）
_CANDIDATE_TTL_DAYS = 30
_TREND_RANKER_VERSION = "trend_rank_v1"
_TREND_RANK_FEATURE_WEIGHTS = {
    "freshness": 0.40,
    "viral_data_completeness": 0.25,
    "formula_completeness": 0.25,
    "platform_diversity": 0.10,
}
_TREND_RANK_VIRAL_FIELDS = ("view_count", "like_count", "comment_count")
_TREND_RANK_FORMULA_FIELDS = (
    "hook_structure",
    "narrative_arc",
    "audio_features",
    "editing_rhythm",
)

# WP-B strict 要求
_WPBD_REQUIRED_KEYS = frozenset([
    "topic_intel_projection_dir",
    "topic_intel_events_dir",
    "topic_intel_events_file",
])


def _load_wpb_config() -> dict:
    """
    WP-B strict loader：
    - sv >= 3 + 3 新 key 存在，否則 raise（不靜默 fallback）
    - env TOPIC_INTEL_CONFIG_PATH 優先（沙盒防禦）
    """
    _env_cfg = os.environ.get("TOPIC_INTEL_CONFIG_PATH", "").strip()
    cfg_path = Path(_env_cfg) if _env_cfg else _TI_CONFIG_PATH

    if not cfg_path.exists():
        raise FileNotFoundError(
            f"[gen-projection] WP-B strict: config 不存在 {cfg_path}"
        )
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(
            f"[gen-projection] WP-B strict: config 解析失敗 {cfg_path}: {e}"
        ) from e

    # 補缺 key（fail-open 對非 WP-B key）
    for k, v in _TI_DEFAULTS.items():
        if k not in raw:
            if k in _WPBD_REQUIRED_KEYS:
                raise KeyError(
                    f"[gen-projection] WP-B strict: config 缺必要 key={k!r}（schema_version 3 才有）"
                )
            raw[k] = v
            print(f"[gen-projection] WARN: config 缺 key={k}，補 DEFAULTS", file=sys.stderr)

    sv = raw.get("schema_version", 0)
    if not isinstance(sv, int) or sv < 3:
        raise KeyError(
            f"[gen-projection] WP-B strict: 需 schema_version>=3，實得 {sv!r}"
        )

    # 確認 3 新 key 存在
    missing = _WPBD_REQUIRED_KEYS - set(raw.keys())
    if missing:
        raise KeyError(
            f"[gen-projection] WP-B strict: 缺 WP-B 必要 key: {missing}"
        )

    return raw


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path: Path) -> Optional[str]:
    try:
        return _sha256_bytes(path.read_bytes())
    except Exception as e:
        print(f"[gen-projection] WARN: sha256 讀取失敗 {path}: {e}", file=sys.stderr)
        return None


def _get_scan_roots(cfg: dict) -> list[tuple[str, Path]]:
    """old -> legacy -> active（後掃優先）"""
    return [
        ("old", Path(cfg["old_root"])),
        ("legacy", Path(cfg["legacy_root"])),
        ("active", Path(cfg["active_root"])),
    ]


def _iter_cyborg_files(cfg: dict) -> tuple[list[tuple[Path, str]], list[Path]]:
    """
    仿 topic_intel_paths.iter_cyborg_files()（不 import trend-daily）
    回 ([(path, sha256), ...], collisions)
    同 basename sha256 一致 → 取 active；不一致 → collisions
    """
    scan_roots = _get_scan_roots(cfg)
    seen: dict[str, list[tuple[str, Path]]] = {}

    for tag, root in scan_roots:
        if not root.exists():
            continue
        for p in sorted(root.glob("cyborg_*.yaml")):
            bn = p.name
            seen.setdefault(bn, []).append((tag, p))

    files: list[tuple[Path, str]] = []
    collisions: list[Path] = []

    for bn, entries in seen.items():
        if len(entries) == 1:
            p = entries[0][1]
            sha = _sha256_file(p)
            if sha is None:
                collisions.append(p)
                continue
            files.append((p, sha))
            continue

        # 多 root 同 basename
        sha_entries: list[tuple[str, Path]] = []
        error = False
        for _tag, p in entries:
            sha = _sha256_file(p)
            if sha is None:
                error = True
                break
            sha_entries.append((sha, p))

        if error:
            for _tag, p in entries:
                collisions.append(p)
            continue

        sha_set = {s for s, _ in sha_entries}
        if len(sha_set) == 1:
            # 全同 → 取最後（active 最後進 seen）
            p = entries[-1][1]
            files.append((p, sha_entries[-1][0]))
        else:
            for _tag, p in entries:
                collisions.append(p)

    return files, collisions


def _load_owner_projection_json() -> dict:
    """讀 sibling owner_projection.generated.json（fail-loud）"""
    if not _OWNER_PROJECTION_PATH.exists():
        raise FileNotFoundError(
            f"[gen-projection] owner_projection.generated.json 不存在: {_OWNER_PROJECTION_PATH}"
        )
    try:
        return json.loads(_OWNER_PROJECTION_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(
            f"[gen-projection] owner_projection.generated.json 解析失敗: {e}"
        ) from e


def _owner_matches(proj: dict, applicable_owners: list, industry: str) -> bool:
    """
    業主是否命中：applicable_owners 包含業主名/id/code/alias（任一命中即 True），
    或 applicable_owners 為空時以 industry 命中業主的 industry_id/industries。

    alias 來源：proj["_aliases"]（runtime_aliases 逆查結果，由 main 在呼叫前注入）。
    例：叭噗_小C 的 _aliases = ["叭噗"]，candidate 若寫 applicable_owners: ["叭噗"] 亦能命中。
    """
    owner_name: str = proj.get("owner_name", "")
    owner_id: str = proj.get("owner_id", "")
    owner_code: str = proj.get("owner_code", "")
    owner_aliases: list = proj.get("_aliases", [])  # 修 6：runtime_aliases 逆查 aliases
    industries: list = proj.get("industries", [])
    industry_id: str = proj.get("industry_id", "")

    # applicable_owners 列表命中（名稱 or id or code or aliases 任一命中）
    # owner-leak fix：若列表非空但不含此業主 → 明確排除，不 fall-through 到 industry 比對
    # （industry-scope 只適用 applicable_owners 為空時）
    if applicable_owners:
        targets = {str(x).strip() for x in applicable_owners}
        if (
            owner_name in targets
            or owner_id in targets
            or owner_code in targets
            or any(str(a).strip() in targets for a in owner_aliases)
        ):
            return True
        # 明確 owner scope 但不含此業主（含 alias）→ 排除
        return False

    # applicable_owners 空 → industry-scope 候選：行業相符才放行
    if industry:
        if industry == industry_id or industry in industries:
            return True

    return False


def _compute_source_pool_fingerprint(
    file_entries: list[tuple[Path, str]],
    ordered_candidate_source_sha256: list[str],
    owner_proj_json_sha: str,
    pref_md_sha: Optional[str],
    adapter_version: str,
    projection_schema_version: int,
) -> str:
    """
    source_pool_fingerprint（規格 §8.6.2）：
    sha256(canonical JSON of source files + owner ordered candidate sha +
    owner_projection.json sha + 業主偏好.md sha + adapter/schema/ranker/TTL)
    """
    entries = []
    for p, sha in sorted(file_entries, key=lambda item: item[0].name):
        try:
            stat = p.stat()
            mtime = stat.st_mtime
            size = stat.st_size
        except Exception:
            mtime = 0.0
            size = 0
        entries.append((p.name, sha, mtime, size))

    canonical = json.dumps(
        {
            "files": entries,
            "owner_proj_sha": owner_proj_json_sha,
            "pref_md_sha": pref_md_sha or "",
            "adapter_version": adapter_version,
            "projection_schema_version": projection_schema_version,
            "ranker_version": _TREND_RANKER_VERSION,
            "ranker_feature_weights": _TREND_RANK_FEATURE_WEIGHTS,
            "candidate_ttl_days": _CANDIDATE_TTL_DAYS,
            "ordered_candidate_source_sha256": ordered_candidate_source_sha256,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return _sha256_bytes(canonical.encode("utf-8"))


def _load_cyborg_yaml(path: Path) -> Optional[dict]:
    """
    讀一支 cyborg yaml，移除 frontmatter --- 分隔符後 safe_load。
    仿 build_template_index.py line 336-340。
    失敗回 None。
    """
    import re as _re
    import yaml as _yaml_mod
    try:
        text = path.read_text(encoding="utf-8")
        # 移除開頭 --- 和結尾 ---（cyborg yaml frontmatter 格式）
        text = _re.sub(r"^---\s*\n", "", text, count=1)
        text = _re.sub(r"\n---\s*$", "", text)
        data = _yaml_mod.safe_load(text)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as e:
        print(f"[gen-projection] WARN: 讀取失敗 {path.name}: {e}", file=sys.stderr)
        return None


def _rank_numeric_present(value: Any) -> bool:
    """trend_rank_v1：bool 不算數字；只收有限、非負數值。"""
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _rank_nonempty(value: Any) -> bool:
    """trend_rank_v1：固定的非空判定。"""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return True


def _candidate_duplicate_key(raw: dict, source_sha256: str) -> str:
    """同影片 canonical key：platform+video_id，其次 URL，最後 source SHA。"""
    platform = str(raw.get("platform") or "UNKNOWN").strip().casefold() or "unknown"
    video_id = str(raw.get("video_id") or "").strip().casefold()
    if video_id:
        return f"platform_video:{platform}:{video_id}"
    source_url = str(raw.get("url") or "").strip().casefold()
    if source_url:
        return f"url:{source_url}"
    return f"sha256:{source_sha256}"


def _prepare_active_sources(
    file_entries: list[tuple[Path, str]],
    now_utc: Optional[datetime] = None,
) -> tuple[list[dict], dict]:
    """
    active candidate 唯一前處理：30d mtime TTL → 同影片去重 → trend_rank_v1。

    duplicate canonical 固定取最新 mtime；mtime 相同取 source SHA 字典序最小。
    排名固定為未四捨五入 score desc、mtime desc、source SHA asc。
    """
    if now_utc is None:
        now_utc = datetime.now(tz=timezone.utc)
    elif now_utc.tzinfo is None:
        raise ValueError("now_utc 必須含 timezone")
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    loaded: list[dict] = []
    parse_error_count = 0
    ttl_seconds = _CANDIDATE_TTL_DAYS * 86400.0

    for path, sha in file_entries:
        raw = _load_cyborg_yaml(path)
        if raw is None:
            parse_error_count += 1
            continue
        try:
            source_mtime = path.stat().st_mtime
        except OSError as exc:
            parse_error_count += 1
            print(
                f"[gen-projection] WARN: mtime 讀取失敗 {path.name}: {exc}",
                file=sys.stderr,
            )
            continue
        age_seconds = max(0.0, now_utc.timestamp() - source_mtime)
        loaded.append(
            {
                "path": path,
                "source_sha256": sha,
                "raw": raw,
                "source_mtime": source_mtime,
                "source_mtime_utc": datetime.fromtimestamp(
                    source_mtime, tz=timezone.utc
                ).isoformat(timespec="microseconds"),
                "age_seconds": age_seconds,
                "expired": age_seconds > ttl_seconds,
            }
        )

    nonexpired = [row for row in loaded if not row["expired"]]
    # trend_rank_v1 的 inverse-frequency 母體是成功載入的完整 pool；
    # TTL 僅決定 active eligibility，不改平台分母。
    platform_counts: Counter[str] = Counter(
        str(row["raw"].get("platform") or "UNKNOWN").strip() or "UNKNOWN"
        for row in loaded
    )
    min_platform_count = min(platform_counts.values()) if platform_counts else 0

    for row in nonexpired:
        raw = row["raw"]
        freshness = max(0.0, 1.0 - (row["age_seconds"] / ttl_seconds))
        supporting = raw.get("supporting_data")
        supporting = supporting if isinstance(supporting, dict) else {}
        viral_score = sum(
            _rank_numeric_present(supporting.get(field))
            for field in _TREND_RANK_VIRAL_FIELDS
        ) / len(_TREND_RANK_VIRAL_FIELDS)
        dissect = raw.get("dissect")
        dissect = dissect if isinstance(dissect, dict) else {}
        formula_score = sum(
            _rank_nonempty(dissect.get(field))
            for field in _TREND_RANK_FORMULA_FIELDS
        ) / len(_TREND_RANK_FORMULA_FIELDS)
        platform = str(raw.get("platform") or "UNKNOWN").strip() or "UNKNOWN"
        platform_score = (
            min_platform_count / platform_counts[platform]
            if min_platform_count and platform_counts[platform]
            else 0.0
        )
        feature_scores = {
            "freshness": freshness,
            "viral_data_completeness": viral_score,
            "formula_completeness": formula_score,
            "platform_diversity": platform_score,
        }
        row["rank_score_raw"] = sum(
            _TREND_RANK_FEATURE_WEIGHTS[name] * feature_scores[name]
            for name in _TREND_RANK_FEATURE_WEIGHTS
        )
        row["rank_score"] = round(row["rank_score_raw"], 6)
        row["rank_features"] = {
            name: round(value, 6) for name, value in feature_scores.items()
        }
        row["duplicate_key"] = _candidate_duplicate_key(
            raw, str(row["source_sha256"])
        )

    duplicate_groups: dict[str, list[dict]] = {}
    for row in nonexpired:
        duplicate_groups.setdefault(row["duplicate_key"], []).append(row)

    canonical_rows: list[dict] = []
    duplicate_count = 0
    for group in duplicate_groups.values():
        ordered = sorted(
            group,
            key=lambda row: (-float(row["source_mtime"]), str(row["source_sha256"])),
        )
        canonical_rows.append(ordered[0])
        duplicate_count += len(ordered) - 1

    canonical_rows.sort(
        key=lambda row: (
            -float(row["rank_score_raw"]),
            -float(row["source_mtime"]),
            str(row["source_sha256"]),
        )
    )
    for rank, row in enumerate(canonical_rows, 1):
        row["rank"] = rank

    stats = {
        "source_file_count": len(file_entries),
        "loaded_source_count": len(loaded),
        "parse_error_count": parse_error_count,
        "nonexpired_count": len(nonexpired),
        "expired_count": len(loaded) - len(nonexpired),
        "canonical_count": len(canonical_rows),
        "duplicate_count": duplicate_count,
        "platform_counts": dict(sorted(platform_counts.items())),
    }
    return canonical_rows, stats


def generate_owner_projection(
    owner_name: str,
    owner_rec: dict,
    prepared_rows: list[dict],
    source_pool_stats: dict,
    file_entries: list[tuple[Path, str]],
    owner_proj_json_sha: str,
    dry_run: bool = False,
    cfg: Optional[dict] = None,
) -> dict:
    """
    為一個業主產 active.json。
    回傳 summary dict（含 qualified_count, output_path, error）。
    """
    from topic_intel_adapter import (  # type: ignore[import]
        project_cyborg,
        ADAPTER_VERSION,
        PROJECTION_SCHEMA_VERSION,
    )

    owner_code: str = owner_rec.get("owner_code", owner_name)
    owner_dir: str = owner_rec.get("owner_dir", owner_name)
    industry_id: str = owner_rec.get("industry_id", "")
    industries: list = owner_rec.get("industries", [])
    l2_path: str = owner_rec.get("l2_path", "")

    # 業主偏好.md sha
    pref_sha: Optional[str] = None
    if l2_path:
        pref_path = Path(l2_path)
        if pref_path.exists():
            pref_sha = _sha256_file(pref_path)

    # aliases（runtime_aliases 逆查，Fix 3：用 _aliases 從 main 傳入）
    aliases: list[str] = list(owner_rec.get("_aliases", []))

    now_utc = datetime.now(tz=timezone.utc)
    generated_at = now_utc.isoformat()
    expires_at = (now_utc + timedelta(hours=_PROJECTION_TTL_HOURS)).isoformat()

    # 過濾 + 投影
    qualified: list[dict] = []
    excluded_owner_leak: int = 0  # applicable_owners 非空且不含此業主的排除數（owner-leak fix）

    for row in prepared_rows:
        path: Path = row["path"]
        sha = str(row["source_sha256"])
        raw: dict = row["raw"]

        # 先做 owner 過濾（eligible 前）
        applicable_owners = raw.get("applicable_owners") or []
        industry = str(raw.get("industry", "") or "")

        if not _owner_matches(
            owner_rec,
            applicable_owners,
            industry,
        ):
            # 計數 owner-leak 排除（applicable_owners 非空且不含此業主）
            if applicable_owners:
                excluded_owner_leak += 1
            continue

        # adapter 投影（eligibility check）
        proj = project_cyborg(raw, source_sha256=sha)
        if proj is None:
            continue

        # Fix G：把 canonical source path 存入 projection，assign 端填 evidence_path 用
        proj["evidence_path"] = str(path.resolve())
        proj["trend_rank"] = {
            "ranker_version": _TREND_RANKER_VERSION,
            "global_rank": row["rank"],
            "score": row["rank_score"],
            "source_mtime_utc": row["source_mtime_utc"],
        }

        qualified.append(proj)

    # fingerprint
    fingerprint = _compute_source_pool_fingerprint(
        file_entries=file_entries,
        ordered_candidate_source_sha256=[
            str(candidate.get("source_sha256", "")) for candidate in qualified
        ],
        owner_proj_json_sha=owner_proj_json_sha,
        pref_md_sha=pref_sha,
        adapter_version=ADAPTER_VERSION,
        projection_schema_version=PROJECTION_SCHEMA_VERSION,
    )

    # owner_projection_fingerprint（業主 record sha）
    op_fp = _sha256_bytes(
        json.dumps(owner_rec, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )

    output = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "ranker_version": _TREND_RANKER_VERSION,
        "candidate_ttl_days": _CANDIDATE_TTL_DAYS,
        "eligible_statuses": ["pending"],
        "owner": owner_name,
        "owner_code": owner_code,
        "owner_dir": owner_dir,
        "aliases": aliases,
        "source_pool_fingerprint": fingerprint,
        "owner_projection_fingerprint": op_fp,
        "generated_at": generated_at,
        "expires_at": expires_at,
        "qualified_count": len(qualified),
        "excluded_owner_leak_count": excluded_owner_leak,  # owner-leak fix 排除計數
        "source_file_count": source_pool_stats["source_file_count"],
        "loaded_source_count": source_pool_stats["loaded_source_count"],
        "expired_source_count": source_pool_stats["expired_count"],
        "duplicate_source_count": source_pool_stats["duplicate_count"],
        "prepared_source_count": source_pool_stats["canonical_count"],
        "source_parse_error_count": source_pool_stats["parse_error_count"],
        "source_collision_count": source_pool_stats.get("collision_count", 0),
        "candidates": qualified,
    }

    if cfg is None:
        cfg = _TI_DEFAULTS

    proj_dir_root = Path(cfg["topic_intel_projection_dir"])
    out_dir = proj_dir_root / "by_owner" / owner_code
    out_path = out_dir / "active.json"

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        fsize = out_path.stat().st_size
        print(
            f"  [{owner_name}] qualified={len(qualified)}, excluded_leak={excluded_owner_leak} → {out_path} ({fsize} bytes)"
        )
    else:
        print(f"  [{owner_name}] dry-run: qualified={len(qualified)}, excluded_leak={excluded_owner_leak}")

    return {
        "owner": owner_name,
        "owner_code": owner_code,
        "qualified_count": len(qualified),
        "excluded_owner_leak_count": excluded_owner_leak,
        "output_path": str(out_path) if not dry_run else None,
        "fingerprint": fingerprint,
        "error": None,
    }


def main():
    parser = argparse.ArgumentParser(
        description="選題情報池 per-owner projection cache 生成器 (WP-B Step 3)"
    )
    parser.add_argument(
        "--owner", help="只產指定業主（預設：全部現役業主）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="印統計不寫檔"
    )
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print("  gen_topic_intel_projection.py — WP-B Step 3")
    print(f"{'='*60}\n")

    # WP-B strict config
    try:
        cfg = _load_wpb_config()
    except Exception as e:
        print(f"[gen-projection] FATAL: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] config schema_version={cfg['schema_version']}")
    print(f"[OK] projection_dir={cfg['topic_intel_projection_dir']}")

    # 掃 cyborg files
    print("\n── 掃 cyborg_*.yaml（multi-root）──")
    file_entries, collisions = _iter_cyborg_files(cfg)
    if collisions:
        print(
            f"[WARN] {len(collisions)} 個 sha256 衝突檔跳過",
            file=sys.stderr,
        )
    print(f"[OK] {len(file_entries)} 支 cyborg yaml（dedup 後）")

    # 讀 owner_projection.generated.json
    try:
        owner_proj_json = _load_owner_projection_json()
    except Exception as e:
        print(f"[gen-projection] FATAL: {e}", file=sys.stderr)
        sys.exit(1)

    owners_dict: dict = owner_proj_json.get("owners", {})
    runtime_aliases: dict = owner_proj_json.get("runtime_aliases", {})

    owner_proj_json_bytes = _OWNER_PROJECTION_PATH.read_bytes()
    owner_proj_json_sha = _sha256_bytes(owner_proj_json_bytes)

    # active candidate 唯一入口：TTL → dedup → rank，完成後才做 per-owner projection。
    try:
        prepared_rows, source_pool_stats = _prepare_active_sources(file_entries)
    except Exception as e:
        print(f"[gen-projection] FATAL: active source 準備失敗: {e}", file=sys.stderr)
        sys.exit(1)
    source_pool_stats["collision_count"] = len(collisions)
    print(
        "[OK] active sources: "
        f"canonical={source_pool_stats['canonical_count']}, "
        f"expired={source_pool_stats['expired_count']}, "
        f"duplicate={source_pool_stats['duplicate_count']}, "
        f"parse_error={source_pool_stats['parse_error_count']}"
    )

    # 選目標業主
    if args.owner:
        # alias 解析
        canonical_owner = runtime_aliases.get(args.owner, args.owner)
        if canonical_owner not in owners_dict:
            print(
                f"[ERROR] 不認識業主：{args.owner!r}，可選：{list(owners_dict.keys())}",
                file=sys.stderr,
            )
            sys.exit(1)
        target_owners = {canonical_owner: owners_dict[canonical_owner]}
    else:
        target_owners = owners_dict

    print(f"\n── 產 {len(target_owners)} 業主 projection ──")
    results = []
    for owner_name, owner_rec in target_owners.items():
        # 補 aliases
        owner_aliases = [
            alias for alias, canon in runtime_aliases.items() if canon == owner_name
        ]
        owner_rec = dict(owner_rec)
        owner_rec["_aliases"] = owner_aliases
        try:
            r = generate_owner_projection(
                owner_name=owner_name,
                owner_rec=owner_rec,
                prepared_rows=prepared_rows,
                source_pool_stats=source_pool_stats,
                file_entries=file_entries,
                owner_proj_json_sha=owner_proj_json_sha,
                dry_run=args.dry_run,
                cfg=cfg,
            )
        except Exception as e:
            print(
                f"[gen-projection] ERROR owner={owner_name}: {e}", file=sys.stderr
            )
            r = {
                "owner": owner_name,
                "owner_code": owner_rec.get("owner_code", ""),
                "qualified_count": 0,
                "output_path": None,
                "fingerprint": "",
                "error": str(e),
            }
        results.append(r)

    # 摘要
    print(f"\n{'='*60}")
    total_q = sum(r["qualified_count"] for r in results)
    errors = [r for r in results if r["error"]]
    print(f"完成：{len(results)} 業主，總合格候選 {total_q} 支")
    if errors:
        print(f"[WARN] {len(errors)} 個業主失敗：{[r['owner'] for r in errors]}")
    print(f"{'='*60}\n")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
