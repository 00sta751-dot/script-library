#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reconcile_topic_intel_usage.py -- WP-B 選題情報池 reconciler
WP-B Wave 2 Step 8 / 2026-06-13

職責：
  吃 validate_script_batch.py 產的 _topic_intel_validator_report.json（PASS report）
  → append topic_intel_events.jsonl（冪等，fail-soft 不擋部署）

部署 SOP 位置（規格 §9.5）：
  build → validate_deploy PASS → reconcile_topic_intel_usage.py → git commit → push → 線上驗

  注意：projection 新鮮度由「出批前重生 projection」保證（python gen_topic_intel_projection.py）。
  assign_topic_sources 在 enforce 模式下會驗 projection 的 expires_at；
  projection 過期時須先重生才能繼續 assign。reconciler 本身不重生 projection。

冪等鍵：event_type + topic_id + script_id + batch_id + validator_report_sha256。
  同一份 report 重跑不重複寫入。

fail-soft 設計：
  寫失敗 → print WARN，exit 0（禁 exit 1，不擋部署）。
  report 缺 validator_report_sha256 → 拒寫（fail-soft）。

shadow 模式：
  assignment_mode == "shadow" → 只寫 _shadow/<batch_id>.json（不 append 正式 events.jsonl）。

used 查詢介面：
  - topic_usage_by_owner.json：{owner_code: {topic_id: [{script_id,batch_id,ts}]}}
  - topic_usage_by_topic.json：{topic_id: [{owner_code,script_id,batch_id,ts}]}
  - load_topic_usage_index() → (by_owner, by_topic)
  - is_recently_used(topic_id, owner_code, max_batches=6, max_days=45) → bool

用法：
  python reconcile_topic_intel_usage.py --report /path/to/_topic_intel_validator_report.json
  python reconcile_topic_intel_usage.py --batch-dir /path/to/batch_dir （自動找 report）
  python reconcile_topic_intel_usage.py --rebuild-index （只重建 index，不寫 events）
"""

import json
import sys
import argparse
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# UTF-8 輸出防亂碼（Windows cp950）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 版本常數（對齊 adapter）────────────────────────────────────────────────────
EVENT_SCHEMA_VERSION = 1
SHADOW_REPORT_SCHEMA_VERSION = 1

# ── 設定來源（topic_intel_paths.json）─────────────────────────────────────────
_TI_CONFIG_PATH = Path(r"C:\Users\00sta\claude-state\topic_intel_paths.json")

_TI_DEFAULTS = {
    "topic_intel_events_dir": "",
    "topic_intel_events_file": "topic_intel_events.jsonl",
    "topic_intel_projection_dir": "",
}


def _load_ti_config() -> dict:
    """讀 topic_intel_paths.json（fail-soft：失敗回 DEFAULTS）"""
    if not _TI_CONFIG_PATH.exists():
        return dict(_TI_DEFAULTS)
    try:
        raw = json.loads(_TI_CONFIG_PATH.read_text(encoding="utf-8"))
        merged = dict(_TI_DEFAULTS)
        merged.update(raw)
        return merged
    except Exception as e:
        print(f"[WARN] reconciler: 讀 topic_intel_paths.json 失敗（{e}），使用 DEFAULTS", file=sys.stderr)
        return dict(_TI_DEFAULTS)


# ── events.jsonl 路徑解析 ─────────────────────────────────────────────────────

def _get_events_path(cfg: dict) -> Optional[Path]:
    """回 topic_intel_events.jsonl 的完整路徑；dir 為空 → None"""
    ev_dir = str(cfg.get("topic_intel_events_dir", "") or "").strip()
    ev_file = str(cfg.get("topic_intel_events_file", "topic_intel_events.jsonl") or "topic_intel_events.jsonl").strip()
    if not ev_dir:
        return None
    return Path(ev_dir) / ev_file


def _get_shadow_dir(cfg: dict) -> Optional[Path]:
    """回 _shadow/ 目錄；dir 為空 → None"""
    ev_dir = str(cfg.get("topic_intel_events_dir", "") or "").strip()
    if not ev_dir:
        return None
    return Path(ev_dir) / "_shadow"


# ── 冪等鍵計算 ────────────────────────────────────────────────────────────────

def _idempotent_key(event_type: str, topic_id: str, script_id: str, batch_id: str, validator_report_sha256: str) -> str:
    """SHA256(event_type+topic_id+script_id+batch_id+validator_report_sha256)"""
    raw = "\n".join([event_type, topic_id, script_id, batch_id, validator_report_sha256])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── 讀既有 events.jsonl 取冪等鍵集合 ─────────────────────────────────────────

def _load_existing_keys(events_path: Path) -> set:
    """讀 events.jsonl，回已存在的冪等鍵 set"""
    if not events_path.exists():
        return set()
    keys = set()
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                k = ev.get("_idempotent_key", "")
                if k:
                    keys.add(k)
            except json.JSONDecodeError:
                continue
    except Exception as e:
        print(f"[WARN] reconciler: 讀 events.jsonl 失敗（{e}），視為空", file=sys.stderr)
    return keys


# ── append events.jsonl（fail-soft）──────────────────────────────────────────

def _append_events(events_path: Path, new_events: list[dict]) -> int:
    """
    Append new_events 到 events_path（每行一個 JSON）。
    fail-soft：寫失敗 print WARN，回 0（不 raise）。
    回實際寫入筆數。
    """
    if not new_events:
        return 0
    try:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(ev, ensure_ascii=False) for ev in new_events]
        with events_path.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        return len(new_events)
    except Exception as e:
        print(f"[WARN] reconciler: append events.jsonl 失敗（{e}），繼續不擋部署", file=sys.stderr)
        return 0


# ── shadow 寫入（覆寫 _shadow/<batch_id>.json）───────────────────────────────

def _write_shadow_report(shadow_dir: Path, batch_id: str, shadow_data: dict) -> None:
    """寫 shadow report；fail-soft"""
    try:
        shadow_dir.mkdir(parents=True, exist_ok=True)
        safe_bid = batch_id.replace("/", "_").replace("\\", "_") or "unknown"
        shadow_path = shadow_dir / f"{safe_bid}.json"
        shadow_path.write_text(json.dumps(shadow_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[WP-B shadow] 寫入 shadow report：{shadow_path}")
    except Exception as e:
        print(f"[WARN] reconciler: shadow report 寫入失敗（{e}）", file=sys.stderr)


# ── 主邏輯 ────────────────────────────────────────────────────────────────────

def reconcile(report_path: Path) -> int:
    """
    吃 PASS report → append events.jsonl（冪等）。
    回寫入筆數（fail-soft：失敗回 0）。
    """
    # 讀 report
    if not report_path.exists():
        print(f"[ERROR] reconciler: report 不存在：{report_path}", file=sys.stderr)
        return 0
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] reconciler: report 解析失敗（{e}）", file=sys.stderr)
        return 0

    if not isinstance(report, dict):
        print(f"[ERROR] reconciler: report 非 dict", file=sys.stderr)
        return 0

    # 驗 validator_report_sha256（缺 → 拒寫 fail-soft）
    report_sha = report.get("validator_report_sha256", "")
    if not report_sha:
        print(f"[WARN] reconciler: report 缺 validator_report_sha256，拒寫 event（fail-soft）", file=sys.stderr)
        return 0

    # Fix 1【P0】is_skeleton：只有明確 False 才寫；True 或缺欄均拒寫（fail-soft WARN）
    if report.get("is_skeleton") is not False:
        print(f"[WARN] reconciler: report is_skeleton={report.get('is_skeleton')!r}（非明確 False），骨架批次不寫 events（fail-soft）", file=sys.stderr)
        return 0

    items = report.get("items", [])
    if not isinstance(items, list) or not items:
        print(f"[INFO] reconciler: report items 為空，無需寫入")
        return 0

    batch_id = str(report.get("batch_id", "unknown"))
    # Fix 2【P0】owner_code fail-loud：owner_code 缺/空 → 拒寫（evidence 不足，禁 fallback 中文 owner）
    owner_code = str(report.get("owner_code", "") or "").strip()
    if not owner_code:
        print(f"[WARN] reconciler: report owner_code 缺/空，拒寫 event（fail-soft；禁 fallback 到中文 owner）", file=sys.stderr)
        return 0
    owner_name = str(report.get("owner_name", "") or report.get("owner", "unknown"))
    topic_intel_mode = str(report.get("topic_intel_mode", "off"))

    # 設定
    cfg = _load_ti_config()
    events_path = _get_events_path(cfg)
    shadow_dir = _get_shadow_dir(cfg)

    # 判斷是否為 shadow 模式（根據 items 的 assignment_mode）
    # 批次所有 item 的 assignment_mode 統一，取第一項判斷
    first_mode = items[0].get("assignment_mode", "off") if items else topic_intel_mode
    is_shadow = (first_mode == "shadow")

    now_utc = datetime.now(tz=timezone.utc).isoformat()
    event_type = "topic_script_adopted"

    if is_shadow:
        # shadow：只寫 _shadow/<batch_id>.json，不 append 正式 events.jsonl
        if shadow_dir is None:
            print(f"[WARN] reconciler: shadow_dir 未設定（topic_intel_events_dir 為空），shadow report 無法寫入", file=sys.stderr)
            return 0
        shadow_data = {
            "schema_version": SHADOW_REPORT_SCHEMA_VERSION,
            "mode": "shadow",
            "batch_id": batch_id,
            "owner_code": owner_code,   # Fix C：owner_code 當 key
            "owner_name": owner_name,   # Fix C：中文名另存
            "generated_at": now_utc,
            "validator_report_sha256": report_sha,
            "items": items,
        }
        _write_shadow_report(shadow_dir, batch_id, shadow_data)
        print(f"[WP-B shadow] shadow 模式：{len(items)} 項寫 shadow，不寫正式 events.jsonl")
        return len(items)

    # enforce/其他：append 正式 events.jsonl
    if events_path is None:
        print(f"[WARN] reconciler: topic_intel_events_dir 未設定，無法寫 events.jsonl（fail-soft）", file=sys.stderr)
        return 0

    # 讀既有冪等鍵
    existing_keys = _load_existing_keys(events_path)

    new_events = []
    skipped = 0
    for item in items:
        topic_id = str(item.get("topic_id", "") or "")
        script_id = str(item.get("script_id", "") or "")
        ev_sha = str(item.get("evidence_sha256", "") or "")

        idem_key = _idempotent_key(event_type, topic_id, script_id, batch_id, report_sha)
        if idem_key in existing_keys:
            skipped += 1
            continue

        ev = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_type": event_type,
            "ts": now_utc,
            "topic_id": topic_id,
            "script_id": script_id,
            "batch_id": batch_id,
            "owner": owner_code,      # Fix C：events 用 owner_code 當 key（全鏈統一）
            "owner_name": owner_name, # Fix C：中文名另存
            "evidence_sha256": ev_sha,
            "assignment_mode": item.get("assignment_mode", topic_intel_mode),
            "validator_report_sha256": report_sha,
            "_idempotent_key": idem_key,
        }
        # 修 10a：把 topic_fidelity_flagged 帶進 events.jsonl（R5-3 shadow WARN 標記）
        # 讓下游 load_offered 能分辨乾淨採用 vs 疑似腦補採用
        if item.get("topic_fidelity_flagged"):
            ev["topic_fidelity_flagged"] = True
        new_events.append(ev)
        existing_keys.add(idem_key)  # 批內去重

    written = _append_events(events_path, new_events)
    if skipped:
        print(f"[WP-B] reconciler: {skipped} 項已存在（冪等跳過），{written} 項寫入 events.jsonl")
    else:
        print(f"[WP-B] reconciler: {written} 項寫入 events.jsonl：{events_path}")

    # 同步更新 index
    _rebuild_usage_index(cfg)

    return written


# ── used 查詢介面 ─────────────────────────────────────────────────────────────

def _rebuild_usage_index(cfg: dict) -> None:
    """
    從 events.jsonl 重建兩個 index JSON（fail-soft）。
    topic_usage_by_owner.json / topic_usage_by_topic.json
    """
    events_path = _get_events_path(cfg)
    if events_path is None or not events_path.exists():
        return
    by_owner: dict = {}
    by_topic: dict = {}
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event_type") != "topic_script_adopted":
                continue
            topic_id = ev.get("topic_id", "")
            owner = ev.get("owner", "")
            script_id = ev.get("script_id", "")
            batch_id = ev.get("batch_id", "")
            ts = ev.get("ts", "")

            entry = {"script_id": script_id, "batch_id": batch_id, "ts": ts}

            # by_owner
            if owner not in by_owner:
                by_owner[owner] = {}
            if topic_id not in by_owner[owner]:
                by_owner[owner][topic_id] = []
            by_owner[owner][topic_id].append(entry)

            # by_topic
            if topic_id not in by_topic:
                by_topic[topic_id] = []
            by_topic[topic_id].append({"owner_code": owner, **entry})

        # 寫 index
        events_dir = events_path.parent
        (events_dir / "topic_usage_by_owner.json").write_text(
            json.dumps(by_owner, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (events_dir / "topic_usage_by_topic.json").write_text(
            json.dumps(by_topic, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[WARN] reconciler: 重建 usage index 失敗（{e}）", file=sys.stderr)


def load_topic_usage_index(cfg: Optional[dict] = None) -> tuple[dict, dict]:
    """
    讀取 usage index。三態語意（Fix 3）：
      - 檔不存在（missing）→ 回 ({}, {})，視為首批 WARN 放行
      - 讀取/解析失敗（error）→ raise RuntimeError（呼叫端 try/except 可判斷 enforce 擋）
      - 正常 → 回 (by_owner, by_topic)
    """
    if cfg is None:
        cfg = _load_ti_config()
    events_path = _get_events_path(cfg)
    if events_path is None:
        return {}, {}
    events_dir = events_path.parent

    def _read(p: Path) -> dict:
        if not p.exists():
            # missing：視為首批，回空 dict（不 raise）
            return {}
        # 存在但讀取/解析失敗 → raise，讓呼叫端判斷 enforce 擋
        raw = p.read_text(encoding="utf-8")
        return json.loads(raw)

    try:
        by_owner = _read(events_dir / "topic_usage_by_owner.json")
        by_topic = _read(events_dir / "topic_usage_by_topic.json")
    except Exception as _e:
        raise RuntimeError(f"usage index 讀取/解析失敗（{_e}）") from _e

    return by_owner, by_topic


def is_recently_used_by_other_owner(
    topic_id: str,
    current_owner: str,
    current_industry: Optional[str] = None,
    max_days: int = 7,
    same_industry_only: bool = True,
    cfg: Optional[dict] = None,
) -> bool:
    """
    跨業主 7 天冷卻查詢（P0-A round 4 — 2026-06-14 industry-native）：
    topic_id 是否在 max_days 天內被「其他業主（不是 current_owner）」採用過。

    same_industry_only=True（預設）→ 只查同行業其他 owner（不同行業不算衝突）。
    失敗 → False（fail-soft，避免擋路）。

    設計：僅供 topic_distributor assign 前查、shadow WARN 不擋（enforce 屬 S3 gate）。
    """
    try:
        _, by_topic = load_topic_usage_index(cfg)
    except Exception:
        return False  # fail-soft

    topic_entries = by_topic.get(topic_id, [])
    if not topic_entries:
        return False

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_days)
    for entry in topic_entries:
        other_owner = entry.get("owner_code", "")
        if not other_owner or other_owner == current_owner:
            continue
        # 時間條件
        if entry.get("ts", "") < cutoff.isoformat():
            continue
        # same_industry_only：需確認 other_owner 與 current_owner 同行業
        # by_topic index 目前不存 industry → fail-soft 放行（不擋）
        # enforce 階段再補 industry 到 event schema
        if same_industry_only and current_industry:
            other_industry = entry.get("industry")
            if other_industry and other_industry != current_industry:
                continue  # 不同行業 → 不算冷卻衝突
        return True

    return False


def is_recently_used(
    topic_id: str,
    owner_code: str,
    max_batches: int = 6,
    max_days: int = 45,
    cfg: Optional[dict] = None,
) -> bool:
    """
    查詢 topic_id 是否被 owner_code 近期採用過（規格 §8.6.5：同 owner 最近 6 批/45 天）。
    任一條件命中 → True（「近期使用」）。
    失敗 → False（fail-soft）。
    """
    by_owner, _ = load_topic_usage_index(cfg)
    owner_usage = by_owner.get(owner_code, {})
    topic_entries = owner_usage.get(topic_id, [])
    if not topic_entries:
        return False

    # 時間條件：最近 max_days 天內
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_days)
    recent_by_time = [
        e for e in topic_entries
        if e.get("ts", "") >= cutoff.isoformat()
    ]
    if recent_by_time:
        return True

    # 批次條件：統計 owner 下所有 topic 的 batch_id 集合，取最近 max_batches 個
    all_batch_ids: list[str] = []
    for entries in owner_usage.values():
        for e in entries:
            bid = e.get("batch_id", "")
            if bid and bid not in all_batch_ids:
                all_batch_ids.append(bid)
    # 簡單按字串排序（batch_id 通常含日期前綴）
    all_batch_ids_sorted = sorted(set(all_batch_ids))
    recent_batches = set(all_batch_ids_sorted[-max_batches:]) if all_batch_ids_sorted else set()

    topic_batches = {e.get("batch_id", "") for e in topic_entries}
    if topic_batches & recent_batches:
        return True

    return False


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="WP-B reconciler：吃 validator PASS report → 寫 topic_intel_events.jsonl"
    )
    parser.add_argument("--report", help="validator PASS report 路徑（_topic_intel_validator_report.json）")
    parser.add_argument("--batch-dir", help="批次目錄路徑（自動找 _topic_intel_validator_report.json）")
    parser.add_argument("--rebuild-index", action="store_true", help="只重建 usage index（不寫 events）")
    args = parser.parse_args()

    cfg = _load_ti_config()

    if args.rebuild_index:
        print("[WP-B] 重建 topic usage index...")
        _rebuild_usage_index(cfg)
        print("[WP-B] 完成")
        sys.exit(0)

    # 決定 report_path
    report_path: Optional[Path] = None
    if args.report:
        report_path = Path(args.report)
    elif args.batch_dir:
        report_path = Path(args.batch_dir) / "_topic_intel_validator_report.json"
    else:
        parser.print_help()
        print("\n[ERROR] 必須提供 --report 或 --batch-dir", file=sys.stderr)
        sys.exit(1)

    written = reconcile(report_path)
    print(f"[WP-B] reconcile 完成：{written} 筆寫入")
    sys.exit(0)


if __name__ == "__main__":
    main()
