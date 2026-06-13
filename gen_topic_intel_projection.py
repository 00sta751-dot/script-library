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
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

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

# projection TTL
_PROJECTION_TTL_HOURS = 24

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
    業主是否命中：applicable_owners 包含業主名/alias，
    或 industry 命中業主的 industry_id/industries。
    """
    owner_name: str = proj.get("owner_name", "")
    owner_id: str = proj.get("owner_id", "")
    owner_code: str = proj.get("owner_code", "")
    industries: list = proj.get("industries", [])
    industry_id: str = proj.get("industry_id", "")

    # applicable_owners 列表命中（名稱 or id or code）
    if applicable_owners:
        targets = {str(x).strip() for x in applicable_owners}
        if owner_name in targets or owner_id in targets or owner_code in targets:
            return True

    # industry 命中
    if industry:
        if industry == industry_id or industry in industries:
            return True

    return False


def _sort_key(proj: dict) -> tuple:
    """
    排序 key（規格 §9.1，deterministic）：
    (-confidence, -transferability_score, publish_date desc, discovery_date desc, topic_id asc, source_sha256 asc)
    publish/discovery_date desc = 負字串（str 排序降序近似）
    """
    ev = proj.get("evidence_snapshot", {})
    conf = ev.get("confidence", 0)
    ts = ev.get("transferability_score", 0)
    pub = str(ev.get("publish_date", "") or "")
    topic_id = str(proj.get("topic_id", "") or "")
    sha = str(proj.get("source_sha256", "") or "")

    # publish_date desc → 前置負號（str 降序：反轉字串比較）
    neg_pub = tuple(-ord(c) for c in pub) if pub else (0,)

    try:
        conf_f = -float(conf)
    except (TypeError, ValueError):
        conf_f = 0.0
    try:
        ts_f = -float(ts)
    except (TypeError, ValueError):
        ts_f = 0.0

    return (conf_f, ts_f, neg_pub, topic_id, sha)


def _compute_source_pool_fingerprint(
    file_entries: list[tuple[Path, str]],
    owner_proj_json_sha: str,
    pref_md_sha: Optional[str],
    adapter_version: str,
    projection_schema_version: int,
) -> str:
    """
    source_pool_fingerprint（規格 §8.6.2）：
    sha256(canonical JSON of sorted [(basename, sha256, mtime, size)] +
    owner_projection.json sha + 業主偏好.md sha + adapter_version + projection_schema_version)
    """
    entries = []
    for p, sha in sorted(file_entries, key=lambda x: x[0].name):
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


def generate_owner_projection(
    owner_name: str,
    owner_rec: dict,
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

    for path, sha in file_entries:
        raw = _load_cyborg_yaml(path)
        if raw is None:
            continue

        # 先做 owner 過濾（eligible 前）
        applicable_owners = raw.get("applicable_owners") or []
        industry = str(raw.get("industry", "") or "")

        if not _owner_matches(
            owner_rec,
            applicable_owners,
            industry,
        ):
            continue

        # adapter 投影（eligibility check）
        proj = project_cyborg(raw, source_sha256=sha)
        if proj is None:
            continue

        # Fix G：把 canonical source path 存入 projection，assign 端填 evidence_path 用
        proj["evidence_path"] = str(path.resolve())

        qualified.append(proj)

    # 排序（§9.1，防 golden drift）
    qualified.sort(key=_sort_key)

    # fingerprint
    fingerprint = _compute_source_pool_fingerprint(
        file_entries=file_entries,
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
            f"  [{owner_name}] qualified={len(qualified)} → {out_path} ({fsize} bytes)"
        )
    else:
        print(f"  [{owner_name}] dry-run: qualified={len(qualified)}")

    return {
        "owner": owner_name,
        "owner_code": owner_code,
        "qualified_count": len(qualified),
        "output_path": str(out_path) if not dry_run else None,
        "fingerprint": fingerprint,
        "error": None,
    }


def main():
    parser = argparse.ArgumentParser(
        description="選題情報池 per-owner projection cache 生成器 (WP-B Step 3)"
    )
    parser.add_argument(
        "--owner", help="只產指定業主（預設：全部 7 業主）"
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
