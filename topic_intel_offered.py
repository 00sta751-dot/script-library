#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topic_intel_offered.py -- WP-C.2 選題情報池「offered」事件帳本 writer
潮汐 WP-C.2 / 2026-06-22 / 霸告出大腦 + Codex gpt-5.5 gauntlet + 保鏢 GO

職責：
  topic_distributor.assign_topic_sources 把候選綁進腳本 slot（offered）後，
  記一筆 topic_script_offered 事件 → 點亮兩 SLO（採用率 used/offered、情報品質率 offered/eligible）。
  與 reconcile_topic_intel_usage.py 的 adopted writer **tier 對稱**（enforce→正式 events.jsonl /
  shadow→_shadow/<batch>.offered.json）。

設計鐵律（topic_intel_offered 模組層硬規格）：
  1. **零 top-level 副作用**：top level 只有 import / 常數 / def。任何 selftest 走
     `if __name__ == "__main__"` guard。`import topic_intel_offered` 絕不執行 I/O、絕不 raise
     SystemExit、絕不印任何東西。（Codex R1 P1-5 / R2 P2）
  2. **lazy import**：reconciler 的 writer helper 全在 emit_offered_events() 函式內 import
     （不在 top level）——保 distributor 在 flag OFF 時「不 import 本模組就零足跡」、且本模組
     被 import 時也不連帶載 reconciler。
  3. **fail-soft 全程**：emit 內部 try/except 包到所有 import/JSON/path/write 失敗 → 回 error 欄、
     **不 raise、不 SystemExit**（絕不擋 build/部署，對齊 reconciler line 152）。
  4. **冪等 sequential-only**：_load_existing_keys + append 為 TOCTOU；builds 序列跑（一次一批），
     不支援並發 writer（明標限制、不假裝防併發）。
  5. **batch_id = batch_tag**（canonical join key，Codex R2 P0）：offered.batch_id 必用
     plan[idx]["batch_tag"]（≡ adopted 事件 batch_id 來源：validator 讀 yaml batch_tag →
     reconciler 寫 report.batch_id）。**不可用 _batch_code（compact「02」）**，否則 join 恆 0。

冪等鍵：sha256(event_type + topic_id + script_id + batch_id + owner_code)（含 event_type →
  與 adopted key 天然不撞；不含 validator_report_sha256，因 offer 發生於 build/validate 前）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── 常數（與 adapter/reconciler 對齊）─────────────────────────────────────────
OFFERED_EVENT_TYPE = "topic_script_offered"
OFFERED_SCHEMA_VERSION = 1


# ── 冪等鍵 ────────────────────────────────────────────────────────────────────

def _idempotent_key_offered(topic_id: str, script_id: str, batch_id: str, owner_code: str) -> str:
    """SHA256(event_type + topic_id + script_id + batch_id + owner_code)。
    含 event_type → 與 adopted 的 _idempotent_key 天然不撞（adopted 用
    'topic_script_adopted' 開頭、且含 validator_report_sha256）。"""
    raw = "\n".join([OFFERED_EVENT_TYPE, topic_id, script_id, batch_id, owner_code])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── shadow 安全檔名（Codex R2 P2-2：測 / \ 空 Unicode）────────────────────────

def _safe_batch_filename(batch_id: str) -> str:
    """把 batch_id 變安全檔名 stem（給 _shadow/<stem>.offered.json）。
    只留 [A-Za-z0-9_.一-鿿-]（含中文），其餘→_；strip 邊界 ._；空/全去除→'unknown'；
    不允許純 . / .. ；限長 120。"""
    out = re.sub(r"[^A-Za-z0-9_.一-鿿-]", "_", str(batch_id or "")).strip("._")
    if not out or out in (".", ".."):
        out = "unknown"
    return out[:120]


# ── 原子寫 shadow（Codex R2 P1-3：temp + os.replace，中斷不留半截）────────────

def _atomic_write_json(path: Path, data: dict) -> None:
    """原子寫 JSON：同目錄 temp 檔 → os.replace。失敗向上拋（由呼叫端 fail-soft 接）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    # suffix=.tmp（非 .json）→ 若 process 被 kill 留下殘檔，consumer 的 glob("*.json") 不會誤讀（Codex R4 P2-3）
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".__tmp_offered_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(tmp, str(path))
    except Exception:
        # 清 temp（best-effort），錯誤向上拋給 emit 的 fail-soft
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


# ── 從綁定 slots 萃取 offered items ──────────────────────────────────────────

def _collect_offered_items(plan: list, assign_report: dict) -> tuple[list, list, Optional[str], Optional[str]]:
    """
    從 assign_report['assigned_slots'] + plan 萃取 offered items。
    回 (items, warnings, batch_id, reject_reason)：
      - items：[{topic_id, script_id, batch_id, batch_code, evidence_sha256, slot_index}, ...]
      - warnings：skip 的原因
      - batch_id：本批 join key（batch_tag）
      - reject_reason：None=正常；"batch_tag_missing"/"batch_tag_inconsistent"=整批拒（呼叫端據此回精確 reason，Codex R5 P2）
    規則：
      - slot 越界 / 無 source_topic_intel / topic_id 空 → skip + warning
      - batch_id 取各綁定 slot 的 batch_tag；空 → 整批拒（reject_reason=batch_tag_missing）
      - 不同 slot batch_tag 不一致 → 整批拒（reject_reason=batch_tag_inconsistent）
    """
    warnings: list = []
    items: list = []
    assigned_slots = assign_report.get("assigned_slots") or []
    batch_id_seen: Optional[str] = None

    for idx in assigned_slots:
        if not isinstance(idx, int) or idx < 0 or idx >= len(plan):
            warnings.append(f"assigned_slot idx={idx!r} 越界（plan len={len(plan)}），skip")
            continue
        item = plan[idx]
        if not isinstance(item, dict):
            warnings.append(f"plan[{idx}] 非 dict，skip")
            continue
        sti = item.get("source_topic_intel")
        if not isinstance(sti, dict):
            warnings.append(f"plan[{idx}] 無 source_topic_intel，skip")
            continue
        topic_id = str(sti.get("topic_id", "") or "").strip()
        if not topic_id:
            warnings.append(f"plan[{idx}] source_topic_intel.topic_id 空，skip")
            continue
        # script_id 空：生產由 skeleton 必填、不應發生；warn 不擋（御史 R 條件③，pre-existing 低風險）
        if not str(item.get("script_id", "") or "").strip():
            warnings.append(f"plan[{idx}] script_id 空（生產異常，仍記但標警）")
        batch_tag = str(item.get("batch_tag", "") or "").strip()
        if not batch_tag:
            warnings.append(f"plan[{idx}] batch_tag 空（join key 缺）→ 整批拒寫")
            return [], warnings, None, "batch_tag_missing"
        if batch_id_seen is None:
            batch_id_seen = batch_tag
        elif batch_tag != batch_id_seen:
            warnings.append(
                f"plan[{idx}] batch_tag={batch_tag!r} 與前者 {batch_id_seen!r} 不一致 → 整批拒寫"
            )
            return [], warnings, None, "batch_tag_inconsistent"
        items.append({
            "topic_id": topic_id,
            "script_id": str(item.get("script_id", "") or ""),
            "batch_id": batch_tag,                                   # join key
            "batch_code": str(item.get("batch", "") or ""),         # 次要、可讀性
            "evidence_sha256": str(sti.get("evidence_sha256", "") or ""),
            "slot_index": idx,
        })

    return items, warnings, batch_id_seen, None


# ── 主 API ────────────────────────────────────────────────────────────────────

def emit_offered_events(
    plan: list,
    assign_report: dict,
    owner_code: str,
    owner_name: str,
    cfg: Optional[dict] = None,
) -> dict:
    """
    寫 topic_script_offered 事件（tier-match、冪等、fail-soft）。

    參數：
      plan          : assign_topic_sources 回傳的 plan（綁定 slot 有 source_topic_intel）
      assign_report : assign_topic_sources 回傳（取 mode / assigned_slots）
      owner_code    : _owner_code(owner)（distributor 已 fail-loud 保證非空）
      owner_name    : 中文名
      cfg           : 測試可注入 ti config dict；None → 讀 topic_intel_paths.json

    回傳 offered_report dict（永不 raise）：
      {enabled, mode, tier, written, skipped, items_count, shadow_path, events_path,
       error, warnings, detail}
    """
    warnings: list = []
    try:
        mode = (assign_report or {}).get("mode")
        # ── gate：只在 shadow/enforce 且 assign 無 error 才寫（Codex R1 P0-1）──
        # distributor 端已 gate（§2.2），此處模組層雙保險
        if mode not in ("shadow", "enforce"):
            return {
                "enabled": False, "mode": mode, "reason": "assign_not_emitted_mode",
                "written": 0, "skipped": 0, "items_count": 0,
                "error": None, "warnings": warnings,
                "detail": f"offered skip：mode={mode!r} 非 shadow/enforce",
            }
        if (assign_report or {}).get("error") is not None:
            return {
                "enabled": False, "mode": mode, "reason": "assign_had_error",
                "written": 0, "skipped": 0, "items_count": 0,
                "error": None, "warnings": warnings,
                "detail": f"offered skip：assign error 非 None（失敗的派工不記 offered）",
            }
        # owner_code 空 → 拒寫（與 reconciler「owner_code 缺則拒寫」同姿態；Codex R4 P2-2）
        if not str(owner_code or "").strip():
            return {
                "enabled": False, "mode": mode, "reason": "owner_code_missing",
                "written": 0, "skipped": 0, "items_count": 0,
                "error": None, "warnings": warnings,
                "detail": "offered skip：owner_code 空（evidence 不足、拒寫）",
            }

        # ── 萃取 items ──
        items, item_warnings, batch_id, reject_reason = _collect_offered_items(plan, assign_report)
        warnings.extend(item_warnings)

        # ── batch_tag 問題 → 整批拒（精確 reason，Codex R5 P2）──
        if reject_reason:
            return {
                "enabled": False, "mode": mode, "reason": reject_reason,
                "written": 0, "skipped": 0, "items_count": 0,
                "error": f"batch_tag 不可靠（{reject_reason}），拒寫（join key 必須可靠）",
                "warnings": warnings,
                "detail": f"offered reject：{reject_reason}",
            }
        # ── 空綁定保護（Codex R2 P1-1）：無 valid item → 不寫、回 no_assigned_slots ──
        if not items:
            return {
                "enabled": False, "mode": mode, "reason": "no_assigned_slots",
                "written": 0, "skipped": 0, "items_count": 0,
                "error": None, "warnings": warnings,
                "detail": "offered skip：無有效綁定 slot（不寫空檔）",
            }

        # ── lazy import reconciler infra（保 OFF 零 import；offered=producer 允許用 writer）──
        from reconcile_topic_intel_usage import (  # type: ignore[import]
            _load_ti_config, _get_events_path, _get_shadow_dir,
            _load_existing_keys, _append_events,
        )
        if cfg is None:
            cfg = _load_ti_config()

        now_utc = datetime.now(tz=timezone.utc).isoformat()

        if mode == "enforce":
            # ── 正式 events.jsonl（append + 冪等）──
            events_path = _get_events_path(cfg)
            if events_path is None:
                warnings.append("topic_intel_events_dir 未設定，無法寫正式 events.jsonl")
                return {
                    "enabled": True, "mode": mode, "tier": "formal",
                    "written": 0, "skipped": 0, "items_count": len(items),
                    "events_path": None, "shadow_path": None,
                    "error": "events_dir_unset", "warnings": warnings,
                    "detail": "offered enforce：events_dir 未設、未寫",
                }
            existing = _load_existing_keys(events_path)
            new_events: list = []
            skipped = 0
            for it in items:
                key = _idempotent_key_offered(
                    it["topic_id"], it["script_id"], it["batch_id"], owner_code
                )
                if key in existing:
                    skipped += 1
                    continue
                new_events.append({
                    "schema_version": OFFERED_SCHEMA_VERSION,
                    "event_type": OFFERED_EVENT_TYPE,
                    "ts": now_utc,
                    "topic_id": it["topic_id"],
                    "script_id": it["script_id"],
                    "batch_id": it["batch_id"],
                    "batch_code": it["batch_code"],
                    "owner": owner_code,
                    "owner_name": owner_name,
                    "evidence_sha256": it["evidence_sha256"],
                    "assignment_mode": mode,
                    "slot_index": it["slot_index"],
                    "_idempotent_key": key,
                })
                existing.add(key)  # 批內去重
            # offered 只 append，**不呼叫 _rebuild_usage_index**（去重 index 只收 adopted）
            written = _append_events(events_path, new_events)
            # _append_events fail-soft 回 0；若有 new_events 卻沒全寫 → 標 error（不假報成功，Codex R4 P1）
            _append_err = None
            if new_events and written != len(new_events):
                _append_err = "append_failed_or_partial"
                warnings.append(
                    f"[WARN] offered append 預期 {len(new_events)} 筆、實際 {written} 筆（寫入失敗/部分，fail-soft 不擋）"
                )
            return {
                "enabled": True, "mode": mode, "tier": "formal",
                "written": written, "skipped": skipped, "items_count": len(items),
                "events_path": str(events_path), "shadow_path": None,
                "error": _append_err, "warnings": warnings,
                "detail": f"offered enforce：{written}/{len(new_events)} 寫入 / {skipped} 冪等跳過 → {events_path}",
            }

        # ── shadow tier：_shadow/<batch>.offered.json（原子覆寫）──
        shadow_dir = _get_shadow_dir(cfg)
        if shadow_dir is None:
            warnings.append("topic_intel_events_dir 未設定，shadow offered 無法寫入")
            return {
                "enabled": True, "mode": mode, "tier": "shadow",
                "written": 0, "skipped": 0, "items_count": len(items),
                "events_path": None, "shadow_path": None,
                "error": "events_dir_unset", "warnings": warnings,
                "detail": "offered shadow：events_dir 未設、未寫",
            }
        shadow_path = Path(shadow_dir) / f"{_safe_batch_filename(batch_id)}.offered.json"
        shadow_data = {
            "schema_version": OFFERED_SCHEMA_VERSION,
            "event_type": OFFERED_EVENT_TYPE,
            "mode": "shadow",
            "batch_id": batch_id,
            "owner_code": owner_code,
            "owner_name": owner_name,
            "generated_at": now_utc,
            "items": [
                {
                    "topic_id": it["topic_id"],
                    "script_id": it["script_id"],
                    "batch_id": it["batch_id"],
                    "batch_code": it["batch_code"],
                    "owner": owner_code,
                    "evidence_sha256": it["evidence_sha256"],
                    "assignment_mode": mode,
                    "slot_index": it["slot_index"],
                }
                for it in items
            ],
        }
        _atomic_write_json(shadow_path, shadow_data)  # 覆寫=最新批狀態
        return {
            "enabled": True, "mode": mode, "tier": "shadow",
            "written": len(items), "skipped": 0, "items_count": len(items),
            "events_path": None, "shadow_path": str(shadow_path),
            "error": None, "warnings": warnings,
            "detail": f"offered shadow：{len(items)} 項寫 {shadow_path}（覆寫）",
        }

    except SystemExit as se:
        # 防呼叫端因 import 連帶 SystemExit 漏接（理論上本模組不觸發；縱深防禦）
        return {
            "enabled": False, "mode": (assign_report or {}).get("mode"),
            "written": 0, "skipped": 0, "items_count": 0,
            "error": f"SystemExit captured（fail-soft）：{se}", "warnings": warnings,
            "detail": "offered emit fail-soft（SystemExit）",
        }
    except Exception as e:  # noqa: BLE001 — fail-soft 鐵律：絕不擋部署
        return {
            "enabled": False, "mode": (assign_report or {}).get("mode"),
            "written": 0, "skipped": 0, "items_count": 0,
            "error": f"emit 例外（fail-soft）：{e}", "warnings": warnings,
            "detail": "offered emit fail-soft（Exception）",
        }


# ── selftest（deterministic、無外部依賴；走 __main__ guard，import 零副作用）──

def _selftest() -> int:
    import shutil
    fails: list = []

    def ck(name, cond, detail=""):
        print(f"[{'PASS' if cond else 'FAIL'}] {name}  {detail}")
        if not cond:
            fails.append(name)

    # T1: _safe_batch_filename 邊界
    ck("safe_filename 去 /", "/" not in _safe_batch_filename("第02批/x"))
    ck("safe_filename 去 \\", "\\" not in _safe_batch_filename("第02批\\x"))
    ck("safe_filename 空→unknown", _safe_batch_filename("") == "unknown")
    ck("safe_filename 純點→unknown", _safe_batch_filename("..") == "unknown")
    ck("safe_filename 保中文", "第02批" in _safe_batch_filename("第02批_2026-05-25"))

    # T2: 冪等鍵 — offered vs adopted 不撞（不同 event_type 前綴）
    k_off = _idempotent_key_offered("t1", "s1", "第01批", "rui_xiang")
    k_off2 = _idempotent_key_offered("t1", "s1", "第01批", "rui_xiang")
    ck("offered 冪等鍵 deterministic", k_off == k_off2)
    # adopted 鍵（模擬 reconciler 算法）必不同
    adopted_raw = "\n".join(["topic_script_adopted", "t1", "s1", "第01批", "abc123"])
    k_adopted = hashlib.sha256(adopted_raw.encode("utf-8")).hexdigest()
    ck("offered 鍵 ≠ adopted 鍵", k_off != k_adopted)

    # T3: gate — 非 shadow/enforce / error 非 None → 不寫
    r = emit_offered_events([], {"mode": "off"}, "oc", "中文")
    ck("mode=off → enabled False", r["enabled"] is False and r["reason"] == "assign_not_emitted_mode")
    r = emit_offered_events([], {"mode": "enforce", "error": "boom"}, "oc", "中文")
    ck("assign error → 不寫（Codex R1 P0-1）", r["enabled"] is False and r["reason"] == "assign_had_error")

    # T4: 空綁定保護（Codex R2 P1-1）
    r = emit_offered_events([], {"mode": "shadow", "error": None, "assigned_slots": []}, "oc", "中文")
    ck("空 assigned_slots → no_assigned_slots 不寫", r["enabled"] is False and r["reason"] == "no_assigned_slots")

    # T5: 用真 cfg（temp dir）測 enforce append + 冪等 + shadow tier-match + batch_id=batch_tag
    tmp = Path(tempfile.mkdtemp(prefix="_wpc2_offered_test_"))
    try:
        ev_dir = tmp / "_events"
        cfg = {"topic_intel_events_dir": str(ev_dir),
               "topic_intel_events_file": "topic_intel_events.jsonl",
               "topic_intel_projection_dir": ""}
        plan = [
            {"script_id": "rui_01_01", "batch": "01", "batch_tag": "第01批_2026-06-22",
             "source_topic_intel": {"topic_id": "tA", "evidence_sha256": "shaA"}},
            {"script_id": "rui_01_02", "batch": "01", "batch_tag": "第01批_2026-06-22",
             "source_topic_intel": {"topic_id": "tB", "evidence_sha256": "shaB"}},
        ]
        ar_enf = {"mode": "enforce", "error": None, "assigned_slots": [0, 1], "enabled": True}
        r1 = emit_offered_events(plan, ar_enf, "rui_xiang", "瑞祥", cfg=cfg)
        ck("enforce 寫 2 筆", r1["written"] == 2 and r1["tier"] == "formal", str(r1))
        # batch_id = batch_tag（非 batch_code「01」）
        ev_path = ev_dir / "topic_intel_events.jsonl"
        lines = [json.loads(l) for l in ev_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        ck("offered event batch_id == batch_tag（join key）",
           all(e["batch_id"] == "第01批_2026-06-22" for e in lines), str([e["batch_id"] for e in lines]))
        ck("offered event_type 正確", all(e["event_type"] == "topic_script_offered" for e in lines))
        ck("offered owner == owner_code", all(e["owner"] == "rui_xiang" for e in lines))
        # 冪等重跑 → 0 新增
        r2 = emit_offered_events(plan, ar_enf, "rui_xiang", "瑞祥", cfg=cfg)
        ck("enforce 冪等重跑 0 寫入 / 2 skip", r2["written"] == 0 and r2["skipped"] == 2, str(r2))

        # regression（Codex R1 P2-1）：offered append 後 _rebuild_usage_index 仍只收 adopted
        # 先塞一筆真 adopted，再 rebuild，驗 offered 不進 index
        adopted_ev = {
            "schema_version": 1, "event_type": "topic_script_adopted",
            "ts": "2026-06-22T00:00:00+00:00", "topic_id": "tA", "script_id": "rui_01_01",
            "batch_id": "第01批_2026-06-22", "owner": "rui_xiang", "owner_name": "瑞祥",
            "evidence_sha256": "shaA", "assignment_mode": "enforce",
            "validator_report_sha256": "rep1", "_idempotent_key": "adoptedkey1",
        }
        with ev_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(adopted_ev, ensure_ascii=False) + "\n")
        from reconcile_topic_intel_usage import _rebuild_usage_index, load_topic_usage_index
        _rebuild_usage_index(cfg)
        by_owner, by_topic = load_topic_usage_index(cfg)
        # by_topic 只該有 adopted 的 tA（offered 的 tA/tB 不進）；tB 純 offered 不該出現
        ck("rebuild index 只收 adopted（tB offered 不進 index）",
           "tB" not in by_topic and "tA" in by_topic, str(list(by_topic.keys())))
        ck("index tA 只 1 筆（adopted，非 offered 灌水）",
           len(by_topic.get("tA", [])) == 1, str(by_topic.get("tA")))

        # shadow tier：寫 _shadow/<batch>.offered.json、不碰 events.jsonl
        ev_sha_before = hashlib.sha256(ev_path.read_bytes()).hexdigest()
        ar_sh = {"mode": "shadow", "error": None, "assigned_slots": [0, 1], "enabled": True}
        r3 = emit_offered_events(plan, ar_sh, "rui_xiang", "瑞祥", cfg=cfg)
        shp = Path(r3["shadow_path"])
        ck("shadow 寫 .offered.json", shp.name == "第01批_2026-06-22.offered.json" and shp.exists(), str(r3))
        ck("shadow 不碰 events.jsonl",
           hashlib.sha256(ev_path.read_bytes()).hexdigest() == ev_sha_before)
        sd = json.loads(shp.read_text(encoding="utf-8"))
        ck("shadow 內容 2 items + batch_id=batch_tag",
           len(sd["items"]) == 2 and sd["batch_id"] == "第01批_2026-06-22")

        # batch_tag 空 → 整批拒（精確 reason，Codex R5 P2）
        plan_bad = [{"script_id": "x_01", "batch": "01", "batch_tag": "",
                     "source_topic_intel": {"topic_id": "tX"}}]
        r4 = emit_offered_events(plan_bad, {"mode": "enforce", "error": None, "assigned_slots": [0]},
                                 "oc", "中文", cfg=cfg)
        ck("batch_tag 空 → 拒寫 reason=batch_tag_missing",
           r4["enabled"] is False and r4["reason"] == "batch_tag_missing", str(r4))
        # batch_tag 不一致 → 整批拒
        plan_inc = [
            {"script_id": "i_01", "batch": "01", "batch_tag": "第10批_a", "source_topic_intel": {"topic_id": "tI1"}},
            {"script_id": "i_02", "batch": "01", "batch_tag": "第10批_b", "source_topic_intel": {"topic_id": "tI2"}},
        ]
        rInc = emit_offered_events(plan_inc, {"mode": "enforce", "error": None, "assigned_slots": [0, 1]},
                                   "oc", "中文", cfg=cfg)
        ck("batch_tag 不一致 → 拒寫 reason=batch_tag_inconsistent",
           rInc["enabled"] is False and rInc["reason"] == "batch_tag_inconsistent", str(rInc))

        # source_topic_intel 缺 → skip + 該筆不寫（其餘照寫）
        plan_mix = [
            {"script_id": "y_01", "batch": "01", "batch_tag": "第09批_x"},  # 無 sti → skip
            {"script_id": "y_02", "batch": "01", "batch_tag": "第09批_x",
             "source_topic_intel": {"topic_id": "tY", "evidence_sha256": "shaY"}},
        ]
        r5 = emit_offered_events(plan_mix, {"mode": "enforce", "error": None, "assigned_slots": [0, 1]},
                                 "oc", "中文", cfg=cfg)
        ck("source_topic_intel 缺 → skip 該筆、寫 1 筆", r5["written"] == 1, str(r5))

        # events_dir 未設 → WARN 回 0、不 crash
        r6 = emit_offered_events(plan, ar_enf, "rui_xiang", "瑞祥",
                                 cfg={"topic_intel_events_dir": "", "topic_intel_events_file": "x.jsonl"})
        ck("events_dir 未設 → enabled True 但 written 0 error", r6["written"] == 0 and r6["error"] == "events_dir_unset", str(r6))

        # P1（Codex R4）：append fail-soft 回 0 但有 new_events → error append_failed_or_partial（不假報成功）
        import reconcile_topic_intel_usage as _recmod
        _orig_ap = _recmod._append_events
        _recmod._append_events = lambda _p, _evs: 0  # 模擬權限/鎖/磁碟寫失敗
        try:
            plan_p1 = [{"script_id": "rui_01_99", "batch": "01", "batch_tag": "第01批_2026-06-22",
                        "source_topic_intel": {"topic_id": "tP1_new", "evidence_sha256": "shaP"}}]
            rP1 = emit_offered_events(plan_p1, {"mode": "enforce", "error": None, "assigned_slots": [0]},
                                      "rui_xiang", "瑞祥", cfg=cfg)
            ck("append 寫 0 但有 new_events → error append_failed_or_partial",
               rP1["error"] == "append_failed_or_partial", str(rP1))
        finally:
            _recmod._append_events = _orig_ap

        # P2-2（Codex R4）：owner_code 空 → 拒寫
        rOC = emit_offered_events(plan, ar_enf, "", "瑞祥", cfg=cfg)
        ck("owner_code 空 → owner_code_missing 拒寫",
           rOC["enabled"] is False and rOC["reason"] == "owner_code_missing", str(rOC))

        # ── Codex R7 fail-soft 失敗注入（封「fail-soft 完整」缺測，不過度宣稱）──
        # (a) shadow events_dir 未設 → error events_dir_unset、不 crash
        rSU = emit_offered_events(plan, ar_sh, "rui_xiang", "瑞祥",
                                  cfg={"topic_intel_events_dir": "", "topic_intel_events_file": "x.jsonl"})
        ck("shadow events_dir 未設 → error events_dir_unset、不 crash",
           rSU["error"] == "events_dir_unset" and rSU["written"] == 0, str(rSU))
        # (b) shadow 原子寫失敗（events_dir 指向「檔案」→ _shadow mkdir 失敗）→ fail-soft error、不 raise
        blocker = tmp / "blocker_is_a_file"
        blocker.write_text("x", encoding="utf-8")
        rAW = emit_offered_events(plan, ar_sh, "rui_xiang", "瑞祥",
                                  cfg={"topic_intel_events_dir": str(blocker), "topic_intel_events_file": "x.jsonl"})
        ck("shadow 原子寫失敗 → fail-soft（回 error、無例外逃逸）",
           rAW.get("error") and rAW["enabled"] is False, str(rAW))
        # (c) SystemExit 內部 → 被 except SystemExit 捕捉（縱深，非死碼）
        import sys as _sysm
        _selfmod = _sysm.modules[__name__]
        _orig_collect = _selfmod._collect_offered_items
        def _raise_se(*_a, **_k):
            raise SystemExit("simulated-inner-systemexit")
        _selfmod._collect_offered_items = _raise_se
        try:
            rSE = emit_offered_events(plan, ar_enf, "rui_xiang", "瑞祥", cfg=cfg)
            ck("內部 SystemExit → fail-soft 捕捉（不逃逸）",
               rSE["enabled"] is False and "SystemExit" in str(rSE.get("error", "")), str(rSE))
        finally:
            _selfmod._collect_offered_items = _orig_collect
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 50)
    if fails:
        print(f"[RESULT] FAIL — {len(fails)}: {fails}")
        return 1
    print("[RESULT] ALL PASS")
    return 0


if __name__ == "__main__":
    # UTF-8 輸出防 cp950 亂碼（只在直接執行時設，import 不碰）
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # sibling import（reconciler 在同目錄）
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(_selftest())
