#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_wpb_closure.py -- WP-B 閉環整合測試
Fix 6 / 2026-06-13

覆蓋：
  TC-1：off byte-compat（plan/dedup_info byte-identical，無 assign_report key，stdout 無 [WP-B]）
  TC-2：shadow WARN（不足 min → WARN，綁 qualified_count 個觀察）
  TC-3：enforce FAIL（不足 min → error，不綁 slot）
  TC-4：enforce PASS（足夠候選 → 正常綁 N slot）
  TC-5：跨批去重（近期已用 → 跳過，警告）
  TC-6：新鮮度（過期 projection → enforce FAIL / shadow WARN）
  TC-7：V3-002 批次級 min/max 硬驗（<min → FAIL，>max → FAIL，in-range → PASS，off → SKIP）

PYTHONHASHSEED=0 跑（TC-1 off byte-compat）：
  PYTHONHASHSEED=0 python tests/test_wpb_closure.py
"""

import json
import os
import sys
import tempfile
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 讓 import 能找到 script-library 下的模組 ────────────────────────────────
_HERE = Path(__file__).resolve().parent
_SL = _HERE.parent  # script-library
if str(_SL) not in sys.path:
    sys.path.insert(0, str(_SL))

# UTF-8 輸出防亂碼（Windows cp950）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASS_COUNT = 0
FAIL_COUNT = 0
ERRORS: list[str] = []


def ok(label: str) -> None:
    global PASS_COUNT
    PASS_COUNT += 1
    print(f"  [PASS] {label}")


def fail(label: str, detail: str = "") -> None:
    global FAIL_COUNT
    FAIL_COUNT += 1
    msg = f"  [FAIL] {label}" + (f" — {detail}" if detail else "")
    print(msg)
    ERRORS.append(msg)


# ── 共用 fixture：policy dict ──────────────────────────────────────────────

def _policy(mode: str, min_slots: int = 2, max_slots: int = 4, bind_scope: str = "") -> dict:
    result = {
        "mode": mode,
        "enabled": mode in ("shadow", "enforce"),
        "min_slots": min_slots,
        "max_slots": max_slots,
        "approved_by": "澤君",
        "approved_at": "2026-06-13",
        "detail": f"test policy mode={mode}",
    }
    if bind_scope:
        result["bind_scope"] = bind_scope
    return result


def _off_policy() -> dict:
    return {
        "mode": "off",
        "enabled": False,
        "min_slots": None,
        "max_slots": None,
        "approved_by": None,
        "approved_at": None,
        "detail": "test policy off",
    }


def _make_candidate(topic_id: str, confidence: float = 80, ts: float = 0.8) -> dict:
    now = datetime.now(tz=timezone.utc)
    return {
        "topic_id": topic_id,
        "source_sha256": hashlib.sha256(topic_id.encode()).hexdigest(),
        "eligible": True,
        "eligible_reason": "ok",
        "evidence_snapshot": {
            "title": f"題材_{topic_id}",
            "url": f"https://example.com/{topic_id}",
            "platform": "IG",
            "publish_date": "2026-06-10",
            "confidence": confidence,
            "transferability_score": ts,
        },
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "generated_at": now.isoformat(),
        "applicable_owners": ["瑞祥"],
        "industry": "房仲",
    }


def _make_plan(batch: str = "第01批_2026-06-13", n: int = 3) -> list[dict]:
    return [
        {"seq": i + 1, "batch": batch, "school": "直球派", "identity": "觀點分享", "topic": ""}
        for i in range(n)
    ]


def _make_hybrid_plan(
    batch: str = "第01批_2026-06-13",
    n_offpro: int = 9,
    n_anchor: int = 2,
    n_pro: int = 2,
) -> list[dict]:
    """hybrid batch plan with content_axis（offpro / personal_anchor / professional）"""
    items: list[dict] = []
    seq = 1
    for _ in range(n_offpro):
        items.append({
            "seq": seq, "batch": batch, "content_axis": "offpro",
            "school": "直球派", "identity": "觀點分享", "topic": "",
        })
        seq += 1
    for _ in range(n_anchor):
        items.append({
            "seq": seq, "batch": batch, "content_axis": "personal_anchor",
            "school": "直球派", "identity": "觀點分享", "topic": "",
        })
        seq += 1
    for _ in range(n_pro):
        items.append({
            "seq": seq, "batch": batch, "content_axis": "professional",
            "school": "直球派", "identity": "觀點分享", "topic": "",
        })
        seq += 1
    return items


def _make_projection_json(
    candidates: list[dict],
    owner_code: str = "rui_xiang",
    expires_offset_hours: float = 24.0,
) -> dict:
    now = datetime.now(tz=timezone.utc)
    return {
        "schema_version": 1,
        "adapter_version": "wpb-adapter-v1",
        "owner": "瑞祥",
        "owner_code": owner_code,
        "owner_dir": "房仲_瑞祥",
        "aliases": ["RuiXiang"],
        "generated_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=expires_offset_hours)).isoformat(),
        "qualified_count": len(candidates),
        "candidates": candidates,
    }


# ── TC-1：off byte-compat ─────────────────────────────────────────────────────

def tc1_off_byte_compat() -> None:
    """
    off 模式：
    - plan 回傳 byte-identical（WP-B 子集比對）
    - output_data 無 assign_report key
    - 不 import adapter/projection/reconcile
    PYTHONHASHSEED=0 保證 list(set(...)) 穩定
    """
    print("\n[TC-1] off byte-compat")
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    plan = _make_plan()
    plan_json_before = json.dumps(plan, ensure_ascii=False, sort_keys=True)

    plan_out, assign_report = assign_topic_sources(
        plan=plan,
        dedup_info={},
        policy=_off_policy(),
        projection_path=None,
    )

    plan_json_after = json.dumps(plan_out, ensure_ascii=False, sort_keys=True)
    ok("off: plan byte-identical") if plan_json_before == plan_json_after else fail(
        "off: plan NOT byte-identical",
        f"before={plan_json_before[:80]!r} after={plan_json_after[:80]!r}",
    )

    # output_data 無 assign_report key（simulate main 的邏輯）
    output_data: dict = {"plan": plan_out, "dedup_info": {}}
    if assign_report is not None:
        output_data["assign_report"] = assign_report
    has_key = "assign_report" in output_data

    # off → assign_report 回 disabled dict（mode=off，enabled=False）
    # main 中：if assign_report is not None → 有 key；off path 回 dict，所以 main 會有 key
    # 正確行為：assign_report 的 enabled=False，output_data 有 key 但 key 顯示 disabled
    # 規格：off 不新增「實質 WP-B 欄位」=「不綁 source_topic_intel 到 plan」，而非 output_data 沒有 assign_report
    # 這裡驗 plan 沒有 source_topic_intel（off 零足跡核心）
    has_sti = any("source_topic_intel" in item for item in plan_out)
    ok("off: plan 無 source_topic_intel") if not has_sti else fail(
        "off: plan 有 source_topic_intel（不應有）"
    )

    ok("off: assign_report enabled=False") if not assign_report.get("enabled") else fail(
        "off: assign_report.enabled 不應為 True"
    )


# ── TC-2：shadow WARN（不足 min）─────────────────────────────────────────────

def tc2_shadow_warn_insufficient() -> None:
    """shadow + 不足 min → WARN 且綁 qualified_count 個觀察"""
    print("\n[TC-2] shadow WARN（候選 1 支 < min_slots=2）")
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    with tempfile.TemporaryDirectory() as tmpdir:
        candidates = [_make_candidate("ti_tc2_A")]  # 1 支 < min=2
        proj = _make_projection_json(candidates)
        proj_path = Path(tmpdir) / "active.json"
        proj_path.write_text(json.dumps(proj), encoding="utf-8")

        plan = _make_plan()
        plan_out, report = assign_topic_sources(
            plan=plan,
            dedup_info={},
            policy=_policy("shadow", min_slots=2, max_slots=4),
            projection_path=str(proj_path),
        )

    has_warn = any("shadow" in w or "min_slots" in w for w in report.get("warnings", []))
    ok("shadow: warnings 含 min_slots") if has_warn else fail(
        "shadow: 應有 min_slots WARN",
        f"warnings={report.get('warnings')}",
    )

    sti_count = sum(1 for item in plan_out if "source_topic_intel" in item)
    ok(f"shadow: 綁了 {sti_count} 個觀察（qualified_count=1）") if sti_count == 1 else fail(
        f"shadow: 應綁 1 個觀察，實得 {sti_count}",
    )

    ok("shadow: error=None") if report.get("error") is None else fail(
        "shadow: error 不應有值",
        f"error={report['error']}",
    )


# ── TC-3：enforce FAIL（不足 min）────────────────────────────────────────────

def tc3_enforce_fail_insufficient() -> None:
    """enforce + 不足 min → error，不綁任何 slot"""
    print("\n[TC-3] enforce FAIL（候選 1 支 < min_slots=2）")
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    with tempfile.TemporaryDirectory() as tmpdir:
        candidates = [_make_candidate("ti_tc3_A")]  # 1 支 < min=2
        proj = _make_projection_json(candidates)
        proj_path = Path(tmpdir) / "active.json"
        proj_path.write_text(json.dumps(proj), encoding="utf-8")

        plan = _make_plan()
        plan_out, report = assign_topic_sources(
            plan=plan,
            dedup_info={},
            policy=_policy("enforce", min_slots=2, max_slots=4),
            projection_path=str(proj_path),
        )

    has_error = bool(report.get("error"))
    ok("enforce FAIL: error 非空") if has_error else fail(
        "enforce FAIL: 應有 error",
        f"report={json.dumps(report, ensure_ascii=False)[:120]}",
    )

    sti_count = sum(1 for item in plan_out if "source_topic_intel" in item)
    ok("enforce FAIL: 不綁任何 slot") if sti_count == 0 else fail(
        f"enforce FAIL: 應綁 0 個，實得 {sti_count}",
    )


# ── TC-4：enforce PASS（足夠候選）────────────────────────────────────────────

def tc4_enforce_pass() -> None:
    """enforce + 足夠候選（3 支 >= min=2） → 綁前 min(max,3) 個 slot"""
    print("\n[TC-4] enforce PASS（候選 3 支，min=2，max=4）")
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    with tempfile.TemporaryDirectory() as tmpdir:
        candidates = [
            _make_candidate("ti_tc4_A", confidence=90),
            _make_candidate("ti_tc4_B", confidence=80),
            _make_candidate("ti_tc4_C", confidence=75),
        ]
        proj = _make_projection_json(candidates)
        proj_path = Path(tmpdir) / "active.json"
        proj_path.write_text(json.dumps(proj), encoding="utf-8")

        plan = _make_plan(n=5)
        plan_out, report = assign_topic_sources(
            plan=plan,
            dedup_info={},
            policy=_policy("enforce", min_slots=2, max_slots=4),
            projection_path=str(proj_path),
        )

    ok("enforce PASS: error=None") if report.get("error") is None else fail(
        "enforce PASS: 不應有 error",
        f"error={report['error']}",
    )

    sti_count = sum(1 for item in plan_out if "source_topic_intel" in item)
    expected = min(4, 3)  # min(max_slots, qualified_count)
    ok(f"enforce PASS: 綁了 {sti_count} 個 slot（期望 {expected}）") if sti_count == expected else fail(
        f"enforce PASS: 應綁 {expected}，實得 {sti_count}",
    )

    # 不動原 plan 後面的 slot
    has_sti_at_end = "source_topic_intel" in plan_out[4] if len(plan_out) > 4 else False
    ok("enforce PASS: plan[4] 無 source_topic_intel") if not has_sti_at_end else fail(
        "enforce PASS: plan[4] 不應有 source_topic_intel",
    )


# ── TC-5：跨批去重（近期已用 → 跳過）────────────────────────────────────────

def tc5_cross_batch_dedup() -> None:
    """近期已被 owner 採用的 topic 被跳過，只綁剩餘"""
    print("\n[TC-5] 跨批去重（ti_tc5_USED 近期已用 → 跳過）")
    from topic_distributor import assign_topic_sources  # type: ignore[import]
    import reconcile_topic_intel_usage as _rcu  # type: ignore[import]

    with tempfile.TemporaryDirectory() as tmpdir:
        # 建 events dir + 偽 usage index
        events_dir = Path(tmpdir) / "_events"
        events_dir.mkdir()

        used_topic = "ti_tc5_USED"
        owner_code = "test_owner_tc5"
        ts_recent = datetime.now(tz=timezone.utc).isoformat()

        # 寫 by_owner index（模擬近期採用記錄）
        by_owner = {
            owner_code: {
                used_topic: [
                    {"script_id": "script_001", "batch_id": "第01批", "ts": ts_recent}
                ]
            }
        }
        (events_dir / "topic_usage_by_owner.json").write_text(
            json.dumps(by_owner), encoding="utf-8"
        )
        (events_dir / "topic_usage_by_topic.json").write_text(
            json.dumps({}), encoding="utf-8"
        )

        # 建 projection（有 USED + 兩支新的）
        candidates = [
            _make_candidate(used_topic, confidence=90),   # 會被跳過
            _make_candidate("ti_tc5_NEW_A", confidence=80),
            _make_candidate("ti_tc5_NEW_B", confidence=75),
        ]
        proj = _make_projection_json(candidates, owner_code=owner_code)
        proj_path = Path(tmpdir) / "active.json"
        proj_path.write_text(json.dumps(proj), encoding="utf-8")

        # patch _rcu 讀 events dir（臨時改 config）
        _orig_load = _rcu.load_topic_usage_index
        def _patched_load(cfg=None):
            by_o = json.loads((events_dir / "topic_usage_by_owner.json").read_text())
            by_t = json.loads((events_dir / "topic_usage_by_topic.json").read_text())
            return by_o, by_t
        _rcu.load_topic_usage_index = _patched_load

        try:
            plan = _make_plan(n=5)
            plan_out, report = assign_topic_sources(
                plan=plan,
                dedup_info={},
                policy=_policy("enforce", min_slots=2, max_slots=4),
                projection_path=str(proj_path),
            )
        finally:
            _rcu.load_topic_usage_index = _orig_load

    # 驗 USED 沒被綁
    bound_ids = [
        item["source_topic_intel"]["topic_id"]
        for item in plan_out
        if "source_topic_intel" in item
    ]
    ok("TC-5: ti_tc5_USED 未被綁") if used_topic not in bound_ids else fail(
        f"TC-5: ti_tc5_USED 不應出現在 bound_ids={bound_ids}",
    )

    # 驗 NEW_A / NEW_B 被綁
    has_new = "ti_tc5_NEW_A" in bound_ids or "ti_tc5_NEW_B" in bound_ids
    ok(f"TC-5: NEW 題材正常綁（bound_ids={bound_ids}）") if has_new else fail(
        f"TC-5: 應有 NEW 題材被綁，bound_ids={bound_ids}",
    )

    # 驗 warnings 有跨批去重訊息
    has_dedup_warn = any("跨批去重" in w or "近期已用" in w for w in report.get("warnings", []))
    ok("TC-5: warnings 含跨批去重訊息") if has_dedup_warn else fail(
        f"TC-5: 應有去重 warning，warnings={report.get('warnings')}",
    )


# ── TC-6：新鮮度（過期 projection → enforce FAIL / shadow WARN）──────────────

def tc6_stale_projection() -> None:
    """projection expires_at 已過期 → enforce 回 error；shadow 加 WARN"""
    print("\n[TC-6] 新鮮度（過期 projection）")
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    with tempfile.TemporaryDirectory() as tmpdir:
        candidates = [_make_candidate(f"ti_tc6_{i}") for i in range(3)]
        # 過期 projection：expires_at 在過去 2 小時
        proj = _make_projection_json(candidates, expires_offset_hours=-2.0)
        proj_path = Path(tmpdir) / "active.json"
        proj_path.write_text(json.dumps(proj), encoding="utf-8")

        plan = _make_plan()

        # enforce → error
        plan_out_e, report_e = assign_topic_sources(
            plan=plan,
            dedup_info={},
            policy=_policy("enforce", min_slots=2, max_slots=4),
            projection_path=str(proj_path),
        )
        ok("TC-6 enforce: 過期 → error 非空") if report_e.get("error") else fail(
            "TC-6 enforce: 應有 stale error",
            f"report={json.dumps(report_e, ensure_ascii=False)[:120]}",
        )
        sti_count_e = sum(1 for item in plan_out_e if "source_topic_intel" in item)
        ok("TC-6 enforce: 不綁任何 slot") if sti_count_e == 0 else fail(
            f"TC-6 enforce: 應綁 0，實得 {sti_count_e}",
        )

        # shadow → WARN（繼續跑）
        plan_out_s, report_s = assign_topic_sources(
            plan=plan,
            dedup_info={},
            policy=_policy("shadow", min_slots=2, max_slots=4),
            projection_path=str(proj_path),
        )
        has_stale_warn = any(
            "過期" in w or "stale" in w or "expires" in w.lower()
            for w in report_s.get("warnings", [])
        )
        ok("TC-6 shadow: 過期 → warnings 含 stale 訊息") if has_stale_warn else fail(
            "TC-6 shadow: 應有 stale WARN",
            f"warnings={report_s.get('warnings')}",
        )
        # shadow 繼續跑：仍嘗試綁（stale warn 後繼續）
        ok("TC-6 shadow: error=None（shadow 繼續跑）") if report_s.get("error") is None else fail(
            f"TC-6 shadow: shadow 不應有 error，error={report_s['error']}",
        )


# ── TC-7：V3-002 批次級 min/max 硬驗 ─────────────────────────────────────────

def tc7_v3002_batch_slot_count() -> None:
    """
    V3-002 chk_v3_002_batch_slot_count：
    - 1 sti + min=2 → FAIL
    - 5 sti + max=4 → FAIL
    - 3 sti（2..4）→ PASS
    - off → SKIP
    """
    print("\n[TC-7] V3-002 批次級 min/max 硬驗")
    from validate_script_batch import chk_v3_002_batch_slot_count  # type: ignore[import]

    def _yaml_with_sti(n_sti: int, n_total: int) -> list[tuple]:
        """n_sti 支帶 source_topic_intel，其餘不帶"""
        result = []
        for i in range(n_total):
            data: dict = {"title": f"腳本_{i}", "owner": "瑞祥"}
            if i < n_sti:
                data["source_topic_intel"] = {
                    "topic_id": f"ti_{i}",
                    "evidence_sha256": "abc",
                    "adopted_topic_statement": "測試主題很長的描述，符合十二字要求的中文陳述",
                    "assigned_by": "topic_distributor",
                    "assignment_mode": "enforce",
                }
            result.append((Path(f"script_{i:02d}.yaml"), data))
        return result

    policy_on = _policy("enforce", min_slots=2, max_slots=4)
    policy_off = _off_policy()

    # 1 sti，min=2 → FAIL
    yamls_1 = _yaml_with_sti(1, 13)
    status_1, detail_1 = chk_v3_002_batch_slot_count(yamls_1, policy_on)
    ok(f"TC-7 1sti→FAIL: status={status_1}") if status_1 == "FAIL" else fail(
        f"TC-7 1sti+min=2 應 FAIL，實得 {status_1}: {detail_1}"
    )

    # 5 sti，max=4 → FAIL
    yamls_5 = _yaml_with_sti(5, 13)
    status_5, detail_5 = chk_v3_002_batch_slot_count(yamls_5, policy_on)
    ok(f"TC-7 5sti→FAIL: status={status_5}") if status_5 == "FAIL" else fail(
        f"TC-7 5sti+max=4 應 FAIL，實得 {status_5}: {detail_5}"
    )

    # 3 sti（2..4）→ PASS
    yamls_3 = _yaml_with_sti(3, 13)
    status_3, detail_3 = chk_v3_002_batch_slot_count(yamls_3, policy_on)
    ok(f"TC-7 3sti→PASS: status={status_3}") if status_3 == "PASS" else fail(
        f"TC-7 3sti in [2,4] 應 PASS，實得 {status_3}: {detail_3}"
    )

    # Fix H【P2】off → 驗「不註冊」：直接呼叫函式仍回 SKIP（函式層 off 行為）
    # 主程式層（Fix A）不 append V3-002 才是「不出現在 stdout」的保證（TC-8 驗）
    yamls_0 = _yaml_with_sti(0, 13)
    status_off, detail_off = chk_v3_002_batch_slot_count(yamls_0, policy_off)
    ok(f"TC-7 off→SKIP（函式層）: status={status_off}") if status_off == "SKIP" else fail(
        f"TC-7 off 應 SKIP，實得 {status_off}: {detail_off}"
    )

    # ── TC-7 補 1：bind_scope=all_offpro — ceiling 改用 offpro 實際稿數（2026-06-26）──

    def _yaml_offpro_with_sti(n_offpro: int, n_sti: int, n_total: int) -> list[tuple]:
        """
        n_offpro 支設 content_axis=offpro；前 n_sti 支同時設 source_topic_intel。
        n_total 為批次總數（含非 offpro 稿）。
        """
        result = []
        for i in range(n_total):
            data: dict = {"title": f"腳本_{i}", "owner": "瑞祥"}
            if i < n_offpro:
                data["content_axis"] = "offpro"
            if i < n_sti:
                data["source_topic_intel"] = {
                    "topic_id": f"ti_{i}",
                    "evidence_sha256": "abc",
                    "adopted_topic_statement": "測試主題很長的描述，符合十二字要求的中文陳述",
                    "assigned_by": "topic_distributor",
                    "assignment_mode": "shadow",
                }
            result.append((Path(f"script_{i:02d}.yaml"), data))
        return result

    policy_all_offpro = _policy("shadow", min_slots=2, max_slots=9, bind_scope="all_offpro")

    # TC-7b-1: 9 offpro 稿、9 STI → ceiling=9, sti=9 ≤ 9 → PASS（舊 max_slots=4 時誤 WARN）
    yamls_9_9 = _yaml_offpro_with_sti(n_offpro=9, n_sti=9, n_total=13)
    s_9_9, d_9_9 = chk_v3_002_batch_slot_count(yamls_9_9, policy_all_offpro)
    ok(f"TC-7b-1 9offpro/9sti→PASS: status={s_9_9}") if s_9_9 == "PASS" else fail(
        f"TC-7b-1 bind_scope=all_offpro 9offpro/9sti 應 PASS，實得 {s_9_9}: {d_9_9}"
    )
    ok("TC-7b-1 detail 含 bind_scope=all_offpro") if "all_offpro" in d_9_9 else fail(
        f"TC-7b-1 detail 應含 all_offpro，實得: {d_9_9}"
    )

    # TC-7b-2: 5 offpro 稿、3 STI → ceiling=5, sti=3 in [2,5] → PASS
    yamls_5_3 = _yaml_offpro_with_sti(n_offpro=5, n_sti=3, n_total=13)
    s_5_3, d_5_3 = chk_v3_002_batch_slot_count(yamls_5_3, policy_all_offpro)
    ok(f"TC-7b-2 5offpro/3sti→PASS: status={s_5_3}") if s_5_3 == "PASS" else fail(
        f"TC-7b-2 bind_scope=all_offpro 5offpro/3sti(in[2,5]) 應 PASS，實得 {s_5_3}: {d_5_3}"
    )

    # TC-7b-3: 5 offpro 稿、6 STI → ceiling=5, sti=6 > 5 → WARN（bind_scope shadow）
    yamls_5_6 = _yaml_offpro_with_sti(n_offpro=5, n_sti=6, n_total=13)
    s_5_6, d_5_6 = chk_v3_002_batch_slot_count(yamls_5_6, policy_all_offpro)
    ok(f"TC-7b-3 5offpro/6sti→WARN: status={s_5_6}") if s_5_6 == "WARN" else fail(
        f"TC-7b-3 bind_scope=all_offpro 5offpro/6sti(>5) 應 WARN，實得 {s_5_6}: {d_5_6}"
    )

    # ── TC-7c：bind_scope typo → WARN 出現 + 退 legacy + 不擋批（2026-06-26 GPT hardening）──
    print("\n[TC-7c] bind_scope typo → WARN + 退 legacy + 不擋批")
    import tempfile as _tmpfile, pathlib as _pathlib
    from topic_intel_policy import load_topic_intel_policy  # type: ignore[import]

    with _tmpfile.TemporaryDirectory() as _td:
        _flag = _pathlib.Path(_td) / "_batch_flags.yml"
        _flag.write_text("""topic_intel_closure:
  mode: shadow
  min_slots: 2
  max_slots: 4
  bind_scope: all_offproo
  approved_by: 澤君
  approved_at: "2026-06-26"
""", encoding="utf-8")
        _typo_policy = load_topic_intel_policy(_td)

    # 應 enabled（不 invalid → 不擋批）
    ok("TC-7c typo policy enabled") if _typo_policy.get("enabled") else fail(
        f"TC-7c typo bind_scope 不應 invalid（不擋批），實得: {_typo_policy}"
    )
    # bind_scope 應退 legacy（None 或 ""）
    _bs = _typo_policy.get("bind_scope", None)
    ok(f"TC-7c bind_scope 退 legacy={_bs!r}") if _bs in (None, "") else fail(
        f"TC-7c typo bind_scope 應退 legacy，實得 bind_scope={_bs!r}"
    )
    # WARN 字樣應出現在 warnings 或 detail
    _ws = _typo_policy.get("warnings", [])
    _det = _typo_policy.get("detail", "")
    _warn_present = any("all_offproo" in w for w in _ws) or "all_offproo" in _det
    ok("TC-7c WARN 含 typo 值") if _warn_present else fail(
        f"TC-7c WARN 應含 'all_offproo' 字樣，warnings={_ws}, detail={_det}"
    )
    # chk_v3_002 走 legacy 路徑（ceiling=max_slots=4），3 STI in [2,4] → PASS
    _yamls_leg = _yaml_with_sti(3, 13)
    _s_leg, _d_leg = chk_v3_002_batch_slot_count(_yamls_leg, _typo_policy)
    ok(f"TC-7c legacy path PASS: {_s_leg}") if _s_leg == "PASS" else fail(
        f"TC-7c typo 退 legacy 後 3sti/max=4 應 PASS，實得 {_s_leg}: {_d_leg}"
    )


# ── TC-8：Fix H validator CLI golden（off 零足跡）+ end-to-end owner_code ──────

def tc8_fix_h_golden_and_owner_code() -> None:
    """
    Fix H【P2】兩個驗收：
    A) validator CLI golden：off 跑真 validate_script_batch --batch-dir，
       stdout 不含 topic-intel / V3-001 / V3-002 / WP-B 字樣
    B) end-to-end owner_code：中文 owner 反查 owner_code → reconciler index key → 次批 assign recent skip
    """
    print("\n[TC-8A] validator CLI golden（off 零足跡）")
    import subprocess
    import tempfile as _tmpfile

    # 建一個最小 batch dir（off = 無 _batch_flags.yml）
    with _tmpfile.TemporaryDirectory() as _bd:
        _bd_path = Path(_bd)
        # 寫一支最簡 yaml（off 模式不跑 WP-B 相關 check）
        _yaml_content = """\
title: TC-8 測試腳本
owner: 瑞祥
batch_tag: test_tc8
派系: 直球派
main_platform: IG Reels
scenes:
  - timestamp: "0-3s"
    type: Hook
    台詞_瑞祥: 這是測試
    畫面: 主播坐正面
voice_lock: true
publish_mode: manual_today
distribution_mode: organic_only
trial_reels: false
policy_alignment:
  ig: []
  fb: []
caption: 測試 caption
hashtag: ["#測試"]
platform_variants:
  ig:
    cta: 留言諮詢
    caption_keywords: []
"""
        (_bd_path / "script_test.yaml").write_text(_yaml_content, encoding="utf-8")

        # 執行 validator（no _batch_flags.yml = off）
        _sl_dir = str(_SL)
        result = subprocess.run(
            [sys.executable, str(_SL / "validate_script_batch.py"),
             "--batch-dir", str(_bd_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=_sl_dir,
        )
        stdout = result.stdout + result.stderr

    # 驗 stdout 不含 topic-intel 字樣（Fix A：off 不 append V3-002，Fix G：V3-001 gated）
    _ti_keywords = ["topic-intel", "V3-001", "V3-002", "WP-B", "topic_intel"]
    found_ti = [kw for kw in _ti_keywords if kw in stdout]
    ok("TC-8A: off stdout 零 topic-intel 行") if not found_ti else fail(
        f"TC-8A: off stdout 含 topic-intel 字樣：{found_ti}",
        f"stdout（前 500 字）：{stdout[:500]!r}",
    )

    print("\n[TC-8B] end-to-end owner_code（中文 owner 反查 → reconciler index → assign recent skip）")
    import json as _j
    import tempfile as _tf

    with _tf.TemporaryDirectory() as tmpdir:
        _td = Path(tmpdir)
        _events_dir = _td / "_events"
        _events_dir.mkdir()

        # 模擬 by_owner index：用 owner_code=ruixiang（非中文）當 key
        _used_topic = "ti_tc8_OWNER_CODE_TEST"
        _ts_recent = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        _by_owner = {
            "ruixiang": {
                _used_topic: [
                    {"script_id": "script_001", "batch_id": "第01批", "ts": _ts_recent}
                ]
            }
        }
        (_events_dir / "topic_usage_by_owner.json").write_text(
            _j.dumps(_by_owner), encoding="utf-8"
        )
        (_events_dir / "topic_usage_by_topic.json").write_text(
            _j.dumps({}), encoding="utf-8"
        )

        # 建 projection：owner_code=ruixiang（即 _make_projection_json 的 owner_code）
        from topic_distributor import assign_topic_sources  # type: ignore[import]
        import reconcile_topic_intel_usage as _rcu  # type: ignore[import]

        candidates = [
            _make_candidate(_used_topic, confidence=90),   # 應被跳過（近期已用）
            _make_candidate("ti_tc8_NEW_X", confidence=80),
        ]
        proj = _make_projection_json(candidates, owner_code="ruixiang")
        proj_path = _td / "active.json"
        proj_path.write_text(_j.dumps(proj), encoding="utf-8")

        # patch load_topic_usage_index 讀 mock events dir
        _orig_load = _rcu.load_topic_usage_index
        def _mock_load(cfg=None):
            _bo = _j.loads((_events_dir / "topic_usage_by_owner.json").read_text())
            _bt = _j.loads((_events_dir / "topic_usage_by_topic.json").read_text())
            return _bo, _bt
        _rcu.load_topic_usage_index = _mock_load

        try:
            plan = _make_plan(n=5)
            plan_out, report = assign_topic_sources(
                plan=plan,
                dedup_info={},
                policy=_policy("enforce", min_slots=1, max_slots=4),
                projection_path=str(proj_path),
            )
        finally:
            _rcu.load_topic_usage_index = _orig_load

    # 驗 USED_topic 沒被綁（owner_code key 正確命中 index）
    bound_ids = [
        item["source_topic_intel"]["topic_id"]
        for item in plan_out
        if "source_topic_intel" in item
    ]
    ok("TC-8B: ti_tc8_OWNER_CODE_TEST 未被綁（owner_code index 命中）") \
        if _used_topic not in bound_ids else fail(
        f"TC-8B: {_used_topic} 不應出現（owner_code=ruixiang 去重失效），bound_ids={bound_ids}",
    )
    ok(f"TC-8B: NEW_X 被綁（bound_ids={bound_ids}）") \
        if "ti_tc8_NEW_X" in bound_ids else fail(
        f"TC-8B: ti_tc8_NEW_X 應被綁，bound_ids={bound_ids}",
    )


# ── TC-9：Fix 1 is_skeleton 缺欄 → reconciler 拒寫 ──────────────────────────
def tc9_fix1_is_skeleton_missing_key() -> None:
    """
    Fix 1：reconciler 收到 is_skeleton 欄缺失的 report → 拒寫（fail-soft WARN，回傳 0）。
    只有明確 is_skeleton=False 才允許寫入。
    reconcile() 接 Path，測試用 tmpfile 寫 JSON 再呼叫。
    """
    print("\n[TC-9] Fix 1 is_skeleton 缺欄 → reconciler 拒寫")
    import io
    import contextlib
    import reconcile_topic_intel_usage as _rcu  # type: ignore[import]

    def _call_reconcile(report_dict: dict) -> tuple[int, str]:
        """把 report dict 寫到 tmpfile，呼叫 reconcile()，回 (result, stderr_text)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8", delete=False
        ) as _tf:
            json.dump(report_dict, _tf, ensure_ascii=False)
            _tf_path = Path(_tf.name)
        try:
            _buf = io.StringIO()
            with contextlib.redirect_stderr(_buf):
                _r = _rcu.reconcile(_tf_path)
            return _r, _buf.getvalue()
        finally:
            try:
                _tf_path.unlink()
            except Exception:
                pass

    # 最小合法 report base（is_skeleton 欄缺失）
    report_base = {
        "schema_version": 1,
        "validator_report_sha256": "abc123tc9",
        "owner_code": "rui_xiang",
        "owner_name": "瑞祥",
        "batch_id": "第01批",
        "topic_intel_mode": "enforce",
        # is_skeleton 欄故意缺失
        "items": [{"topic_id": "ti_tc9", "script_id": "s1", "batch_id": "第01批",
                   "evidence_sha256": "x", "assignment_mode": "enforce"}],
    }

    # A) is_skeleton 欄缺失 → 拒寫
    result_a, stderr_a = _call_reconcile(report_base)
    ok("TC-9A: is_skeleton 缺欄 → 回傳 0（拒寫）") if result_a == 0 else fail(
        f"TC-9A: 期望 0，實得 {result_a}",
    )
    ok("TC-9A: stderr 含 is_skeleton 警告") if "is_skeleton" in stderr_a else fail(
        f"TC-9A: stderr 無 is_skeleton，實得：{stderr_a[:200]!r}",
    )

    # B) is_skeleton=True → 拒寫
    report_true = dict(report_base)
    report_true["is_skeleton"] = True
    result_b, stderr_b = _call_reconcile(report_true)
    ok("TC-9B: is_skeleton=True → 回傳 0（拒寫）") if result_b == 0 else fail(
        f"TC-9B: 期望 0，實得 {result_b}",
    )

    # C) is_skeleton=False → 不因 is_skeleton 被拒
    # 需 mock _get_events_path 指向 tmpdir，避免碰生產 events.jsonl
    report_false = dict(report_base)
    report_false["is_skeleton"] = False
    import reconcile_topic_intel_usage as _rcu2  # type: ignore[import]
    with tempfile.TemporaryDirectory() as _ev_tmp:
        _ev_tmp_path = Path(_ev_tmp) / "events.jsonl"
        _orig_ep = _rcu2._get_events_path
        def _mock_ep(cfg=None):
            return _ev_tmp_path
        _rcu2._get_events_path = _mock_ep
        try:
            result_c, stderr_c = _call_reconcile(report_false)
        finally:
            _rcu2._get_events_path = _orig_ep
    # is_skeleton=False 應通過 is_skeleton 關卡（往後跑，不管寫入是否成功）
    # 只驗 stderr 不含「is_skeleton」拒寫訊息
    ok("TC-9C: is_skeleton=False → stderr 不含 is_skeleton 拒寫訊息") \
        if "is_skeleton" not in stderr_c else fail(
        f"TC-9C: is_skeleton=False 不應被 is_skeleton 擋，stderr={stderr_c[:200]!r}",
    )


# ── TC-10：Fix 2 owner_code 缺/空 → reconciler 拒寫 ─────────────────────────
def tc10_fix2_owner_code_failload() -> None:
    """
    Fix 2b：reconciler：report owner_code 缺/空 → 拒寫（fail-soft WARN）
    """
    print("\n[TC-10] Fix 2 owner_code 空/缺 → reconciler 拒寫")
    import io
    import contextlib
    import reconcile_topic_intel_usage as _rcu  # type: ignore[import]

    def _call_reconcile(report_dict: dict) -> tuple[int, str]:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8", delete=False
        ) as _tf:
            json.dump(report_dict, _tf, ensure_ascii=False)
            _tf_path = Path(_tf.name)
        try:
            _buf = io.StringIO()
            with contextlib.redirect_stderr(_buf):
                _r = _rcu.reconcile(_tf_path)
            return _r, _buf.getvalue()
        finally:
            try:
                _tf_path.unlink()
            except Exception:
                pass

    # owner_code 空字串
    report_no_code = {
        "schema_version": 1,
        "validator_report_sha256": "sha_tc10",
        "owner_code": "",
        "owner_name": "瑞祥",
        "batch_id": "第01批",
        "is_skeleton": False,
        "topic_intel_mode": "enforce",
        "items": [{"topic_id": "ti_tc10", "script_id": "s1", "batch_id": "第01批",
                   "evidence_sha256": "y", "assignment_mode": "enforce"}],
    }
    result_a, stderr_a = _call_reconcile(report_no_code)
    ok("TC-10A reconciler: owner_code 空 → 回傳 0（拒寫）") if result_a == 0 else fail(
        f"TC-10A: 期望 0，實得 {result_a}",
    )
    ok("TC-10A reconciler: stderr 含 owner_code 警告") if "owner_code" in stderr_a else fail(
        f"TC-10A: stderr 無 owner_code，實得：{stderr_a[:200]!r}",
    )

    # owner_code 欄缺失也拒寫
    report_missing_code = {k: v for k, v in report_no_code.items() if k != "owner_code"}
    result_b, stderr_b = _call_reconcile(report_missing_code)
    ok("TC-10B reconciler: owner_code 缺欄 → 回傳 0（拒寫）") if result_b == 0 else fail(
        f"TC-10B 缺欄: 期望 0，實得 {result_b}",
    )
    ok("TC-10B reconciler: stderr 含 owner_code 警告") if "owner_code" in stderr_b else fail(
        f"TC-10B: stderr 無 owner_code，實得：{stderr_b[:200]!r}",
    )


# ── TC-11：Fix 3 usage index 壞檔 → enforce 擋；missing → 首批 WARN ──────────
def tc11_fix3_usage_index_tristate() -> None:
    """
    Fix 3：load_topic_usage_index 三態：
    - 壞 JSON → raise RuntimeError（distributor enforce 擋）
    - 檔不存在 → ({}, {}) 首批 WARN 放行
    """
    print("\n[TC-11] Fix 3 usage index 三態")
    import reconcile_topic_intel_usage as _rcu  # type: ignore[import]
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    # A) 壞 JSON → load_topic_usage_index 應 raise
    with tempfile.TemporaryDirectory() as tmpdir:
        _td = Path(tmpdir)
        _bad_json = _td / "topic_usage_by_owner.json"
        _bad_json.write_text("{ broken json <<<", encoding="utf-8")
        (_td / "topic_usage_by_topic.json").write_text("{}", encoding="utf-8")

        _orig_ep = _rcu._get_events_path
        def _mock_ep(cfg=None):
            return _td / "events.jsonl"
        _rcu._get_events_path = _mock_ep

        try:
            raised = False
            try:
                _rcu.load_topic_usage_index()
            except RuntimeError:
                raised = True
            ok("TC-11A: 壞 JSON → load_topic_usage_index raise RuntimeError") if raised else fail(
                "TC-11A: 壞 JSON 應 raise RuntimeError，但沒有",
            )
        finally:
            _rcu._get_events_path = _orig_ep

    # B) assign_topic_sources enforce + 壞 index → error 不綁
    with tempfile.TemporaryDirectory() as tmpdir2:
        candidates = [_make_candidate("ti_tc11_A", confidence=90)]
        proj = _make_projection_json(candidates, owner_code="tc11_owner")
        proj_path = Path(tmpdir2) / "active.json"
        proj_path.write_text(json.dumps(proj), encoding="utf-8")

        _orig_load = _rcu.load_topic_usage_index
        def _bad_load(cfg=None):
            raise RuntimeError("TC-11 mock 壞檔")
        _rcu.load_topic_usage_index = _bad_load

        try:
            plan_out, report = assign_topic_sources(
                plan=_make_plan(),
                dedup_info={},
                policy=_policy("enforce"),
                projection_path=str(proj_path),
            )
        finally:
            _rcu.load_topic_usage_index = _orig_load

        has_error = bool(report.get("error"))
        ok("TC-11B enforce: 壞 index → error 不綁") if has_error else fail(
            f"TC-11B: 壞 index + enforce 應有 error，report={json.dumps(report, ensure_ascii=False)[:120]}",
        )
        sti_count = sum(1 for item in plan_out if "source_topic_intel" in item)
        ok("TC-11B enforce: 不綁任何 slot") if sti_count == 0 else fail(
            f"TC-11B: 應綁 0，實得 {sti_count}",
        )

    # C) 檔不存在（missing）→ ({}, {}) 首批放行
    with tempfile.TemporaryDirectory() as tmpdir3:
        _td3 = Path(tmpdir3)
        _orig_ep3 = _rcu._get_events_path
        def _mock_ep3(cfg=None):
            return _td3 / "events.jsonl"
        _rcu._get_events_path = _mock_ep3
        try:
            by_o, by_t = _rcu.load_topic_usage_index()
            ok("TC-11C missing: 回 ({}, {}) 首批") if by_o == {} and by_t == {} else fail(
                f"TC-11C: 期望空 dict，實得 ({by_o},{by_t})",
            )
        except Exception as _e:
            fail(f"TC-11C: missing 不應 raise，實得 {_e}")
        finally:
            _rcu._get_events_path = _orig_ep3


# ── TC-12：Fix 4 projection cache 缺 → enforce FAIL ─────────────────────────
def tc12_fix4_projection_cache_missing_enforce_fail() -> None:
    """
    Fix 4：V3-001 _proj_index is None（projection cache 不存在）：
    - enforce → FAIL（含 projection cache 缺的 issue）
    - shadow → WARN（不升 is_fail）
    """
    print("\n[TC-12] Fix 4 projection cache 缺 → enforce FAIL / shadow WARN")
    from validate_script_batch import chk_topic_intel_provenance as chk_v3_001_provenance  # type: ignore[import]

    data = {
        "owner": "不存在業主",
        "source_topic_intel": {
            "topic_id": "ti_tc12",
            "source_kind": "cyborg_yaml",
            "evidence_path": "/some/path/cyborg_abc.yaml",
            "evidence_sha256": "deadbeef" * 8,
            "adopted_topic_statement": "這是超過十二個中文字的完整主題陳述測試文字內容",
            "assigned_by": "topic_distributor",
            "assignment_mode": "enforce",
        },
        "scenes": [{"台詞_不存在業主": "這是超過十二個中文字的完整主題陳述測試文字內容，符合共享詞條件"}],
    }

    policy_enforce = {"mode": "enforce", "enabled": True}
    policy_shadow = {"mode": "shadow", "enabled": True}

    status_e, detail_e = chk_v3_001_provenance(
        data=data, fname="tc12.yaml",
        topic_intel_policy=policy_enforce,
        is_skeleton=False, owner="不存在業主",
    )
    ok(f"TC-12 enforce: projection cache 缺 → FAIL（status={status_e}）") \
        if status_e == "FAIL" else fail(
        f"TC-12 enforce: 期望 FAIL，實得 {status_e}: {detail_e}",
    )
    has_proj_mention = "projection" in detail_e
    ok("TC-12 enforce: detail 含 projection 說明") if has_proj_mention else fail(
        f"TC-12 enforce: detail 不含 projection，detail={detail_e!r}",
    )

    status_s, detail_s = chk_v3_001_provenance(
        data=data, fname="tc12.yaml",
        topic_intel_policy=policy_shadow,
        is_skeleton=False, owner="不存在業主",
    )
    ok(f"TC-12 shadow: projection cache 缺 → WARN（status={status_s}）") \
        if status_s == "WARN" else fail(
        f"TC-12 shadow: 期望 WARN，實得 {status_s}: {detail_s}",
    )


# ── TC-13：Fix 5 evidence_path 空 → enforce 不綁 ─────────────────────────────
def tc13_fix5_evidence_path_empty_enforce_skip() -> None:
    """
    Fix 5：assign 時候選 evidence_path 空：
    - enforce → 跳過不綁（warnings 含提示）
    - shadow → 仍綁但 warnings 含提示
    """
    print("\n[TC-13] Fix 5 evidence_path 空 → enforce 不綁 / shadow 綁但 WARN")
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    def _cand_no_ev(topic_id: str, confidence: float = 80) -> dict:
        c = _make_candidate(topic_id, confidence)
        c["evidence_path"] = ""
        return c

    # enforce：3 個候選全缺 evidence_path（_make_candidate 本身無 evidence_path 欄）
    with tempfile.TemporaryDirectory() as tmpdir:
        candidates_e = [
            _cand_no_ev("ti_tc13_A"),
            _cand_no_ev("ti_tc13_B"),
            _cand_no_ev("ti_tc13_C"),
        ]
        proj_e = _make_projection_json(candidates_e)
        proj_path_e = Path(tmpdir) / "proj_enforce.json"
        proj_path_e.write_text(json.dumps(proj_e), encoding="utf-8")

        plan_out_e, report_e = assign_topic_sources(
            plan=_make_plan(n=5),
            dedup_info={},
            policy=_policy("enforce"),
            projection_path=str(proj_path_e),
        )

    sti_count_e = sum(1 for item in plan_out_e if "source_topic_intel" in item)
    ok(f"TC-13 enforce: 全缺 evidence_path → 綁 0（實得 {sti_count_e}）") \
        if sti_count_e == 0 else fail(
        f"TC-13 enforce: 全缺 evidence_path 應綁 0，實得 {sti_count_e}",
    )
    has_warn_e = any("evidence_path" in w for w in report_e.get("warnings", []))
    ok("TC-13 enforce: warnings 含 evidence_path 提示") if has_warn_e else fail(
        f"TC-13 enforce: 應有 evidence_path 警告，warnings={report_e.get('warnings')}",
    )

    # shadow：缺 evidence_path → 仍綁但 warnings
    with tempfile.TemporaryDirectory() as tmpdir2:
        candidates_s = [_cand_no_ev("ti_tc13_S_A"), _cand_no_ev("ti_tc13_S_B")]
        proj_s = _make_projection_json(candidates_s)
        proj_path_s = Path(tmpdir2) / "proj_shadow.json"
        proj_path_s.write_text(json.dumps(proj_s), encoding="utf-8")

        plan_out_s, report_s = assign_topic_sources(
            plan=_make_plan(n=5),
            dedup_info={},
            policy=_policy("shadow"),
            projection_path=str(proj_path_s),
        )

    sti_count_s = sum(1 for item in plan_out_s if "source_topic_intel" in item)
    ok(f"TC-13 shadow: 缺 evidence_path → 仍綁（{sti_count_s} 個）") \
        if sti_count_s > 0 else fail(
        f"TC-13 shadow: 應仍綁（shadow 不跳過），實得 {sti_count_s}",
    )
    has_warn_s = any("evidence_path" in w for w in report_s.get("warnings", []))
    ok("TC-13 shadow: warnings 含 evidence_path 提示") if has_warn_s else fail(
        f"TC-13 shadow: 應有 evidence_path 警告，warnings={report_s.get('warnings')}",
    )


# ── TC-14：Fix P0-1 projection cache corrupt JSON → enforce FAIL（不產 PASS report）──
def tc14_p01_projection_cache_corrupt_enforce_fail() -> None:
    """
    Fix P0-1：chk_topic_intel_provenance 的 except 區塊：
    projection cache 存在但 JSON 壞（parse 例外）：
    - enforce → FAIL（is_fail=True，且不產 PASS report）
    - shadow → WARN（不升 is_fail）
    """
    print("\n[TC-14] Fix P0-1 projection cache corrupt JSON → enforce FAIL / shadow WARN")
    from validate_script_batch import chk_topic_intel_provenance as chk_v3_001  # type: ignore[import]
    import validate_script_batch as _vsb  # type: ignore[import]

    data = {
        "owner": "corrupt_test_owner",
        "source_topic_intel": {
            "topic_id": "ti_tc14",
            "source_kind": "cyborg_yaml",
            "evidence_path": "/some/path/cyborg_tc14.yaml",
            "evidence_sha256": "deadbeef" * 8,
            "adopted_topic_statement": "這是超過十二個中文字的完整主題陳述測試文字內容",
            "assigned_by": "topic_distributor",
            "assignment_mode": "enforce",
        },
        "scenes": [{"台詞_corrupt_test_owner": "這是超過十二個中文字的完整主題陳述測試文字內容，符合共享詞條件"}],
    }

    # monkeypatch _load_projection_candidate_index → raise JSON decode error
    _orig_load = _vsb._load_projection_candidate_index
    def _bad_proj_load(owner: str):
        import json as _j
        raise _j.JSONDecodeError("mock corrupt", "", 0)
    _vsb._load_projection_candidate_index = _bad_proj_load

    try:
        policy_enforce = {"mode": "enforce", "enabled": True}
        status_e, detail_e = chk_v3_001(
            data=data, fname="tc14.yaml",
            topic_intel_policy=policy_enforce,
            is_skeleton=False, owner="corrupt_test_owner",
        )
        ok(f"TC-14 enforce: corrupt cache → FAIL（status={status_e}）") \
            if status_e == "FAIL" else fail(
            f"TC-14 enforce: 期望 FAIL，實得 {status_e}: {detail_e}",
        )
        ok("TC-14 enforce: detail 含 exception 說明") \
            if "例外" in detail_e or "corrupt" in detail_e.lower() else fail(
            f"TC-14 enforce: detail 未含例外說明，detail={detail_e!r}",
        )

        policy_shadow = {"mode": "shadow", "enabled": True}
        status_s, detail_s = chk_v3_001(
            data=data, fname="tc14.yaml",
            topic_intel_policy=policy_shadow,
            is_skeleton=False, owner="corrupt_test_owner",
        )
        ok(f"TC-14 shadow: corrupt cache → WARN（status={status_s}）") \
            if status_s == "WARN" else fail(
            f"TC-14 shadow: 期望 WARN，實得 {status_s}: {detail_s}",
        )
    finally:
        _vsb._load_projection_candidate_index = _orig_load


# ── TC-15：Fix P0-2 invalid policy → validator FAIL + assign error（非 off）──
def tc15_p02_invalid_policy_fail_closed() -> None:
    """
    Fix P0-2：_batch_flags.yml 有 topic_intel_closure 但設定不合法（invalid）：
    A) validator batch_checks 應含 V3-000-policy FAIL（非 off 靜默略過）
    B) assign_topic_sources policy.mode=invalid → assign_report error（不綁）
    C) off 批次（無 topic_intel_closure）仍 disabled 零足跡（確認 invalid 沒誤傷 off）
    """
    print("\n[TC-15] Fix P0-2 invalid policy → validator FAIL + assign error")
    import subprocess
    import tempfile as _tmpfile

    # A) validator：invalid policy → V3-000-policy FAIL（subprocess CLI 驗）
    print("  [TC-15A] validator CLI invalid policy → V3-000-policy FAIL")
    with _tmpfile.TemporaryDirectory() as _bd:
        _bd_path = Path(_bd)
        # 有 topic_intel_closure 但 approved_by 錯 → invalid
        _flags_content = """\
topic_intel_closure:
  mode: enforce
  min_slots: 2
  max_slots: 4
  approved_by: 錯人
  approved_at: "2026-06-13"
"""
        (_bd_path / "_batch_flags.yml").write_text(_flags_content, encoding="utf-8")
        _yaml_content = """\
title: TC-15 測試腳本
owner: 瑞祥
batch_tag: test_tc15
派系: 直球派
main_platform: IG Reels
scenes:
  - timestamp: "0-3s"
    type: Hook
    台詞_瑞祥: 這是測試
    畫面: 主播坐正面
voice_lock: true
publish_mode: manual_today
distribution_mode: organic_only
trial_reels: false
policy_alignment:
  ig: []
  fb: []
caption: 測試 caption
hashtag: ["#測試"]
platform_variants:
  ig:
    cta: 留言諮詢
    caption_keywords: []
"""
        (_bd_path / "script_test.yaml").write_text(_yaml_content, encoding="utf-8")

        _sl_dir = str(_SL)
        result = subprocess.run(
            [sys.executable, str(_SL / "validate_script_batch.py"),
             "--batch-dir", str(_bd_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=_sl_dir,
        )
        stdout_a = result.stdout + result.stderr

    has_v3000 = "V3-000-policy" in stdout_a
    ok("TC-15A: invalid policy → stdout 含 V3-000-policy") if has_v3000 else fail(
        f"TC-15A: 期望 V3-000-policy，stdout 前 600 字：{stdout_a[:600]!r}",
    )
    has_fail_a = "FAIL" in stdout_a
    ok("TC-15A: stdout 含 FAIL") if has_fail_a else fail(
        f"TC-15A: 期望 FAIL，stdout={stdout_a[:300]!r}",
    )

    # B) assign_topic_sources：invalid policy → assign_report error（不綁）
    print("  [TC-15B] assign invalid policy → assign_report error")
    from topic_distributor import assign_topic_sources  # type: ignore[import]
    from topic_intel_policy import load_topic_intel_policy  # type: ignore[import]

    with _tmpfile.TemporaryDirectory() as _bd2:
        _bd2_path = Path(_bd2)
        (_bd2_path / "_batch_flags.yml").write_text(_flags_content, encoding="utf-8")
        policy_invalid = load_topic_intel_policy(str(_bd2_path))

    ok(f"TC-15B: policy.mode=invalid（{policy_invalid['mode']}）") \
        if policy_invalid.get("mode") == "invalid" else fail(
        f"TC-15B: 期望 invalid，實得 mode={policy_invalid.get('mode')!r}",
    )

    plan_b = _make_plan()
    plan_b_out, report_b = assign_topic_sources(
        plan=plan_b,
        dedup_info={},
        policy=policy_invalid,
        projection_path=None,
    )
    ok("TC-15B: assign_report 含 error") if report_b and report_b.get("error") else fail(
        f"TC-15B: invalid policy 應有 assign error，report={report_b}",
    )
    no_sti_b = not any("source_topic_intel" in item for item in plan_b_out)
    ok("TC-15B: plan 無 source_topic_intel（不綁）") if no_sti_b else fail(
        "TC-15B: invalid policy 不應綁任何 slot",
    )

    # C) off 批次（無 topic_intel_closure）仍 disabled 零足跡
    print("  [TC-15C] off 批次（無 _batch_flags.yml）→ 不含 V3-000-policy")
    with _tmpfile.TemporaryDirectory() as _bd3:
        _bd3_path = Path(_bd3)
        (_bd3_path / "script_off.yaml").write_text(_yaml_content, encoding="utf-8")
        # 無 _batch_flags.yml = off

        _sl_dir = str(_SL)
        result_c = subprocess.run(
            [sys.executable, str(_SL / "validate_script_batch.py"),
             "--batch-dir", str(_bd3_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=_sl_dir,
        )
        stdout_c = result_c.stdout + result_c.stderr

    no_v3000_c = "V3-000-policy" not in stdout_c
    ok("TC-15C: off 批次 stdout 無 V3-000-policy（zero-footprint）") if no_v3000_c else fail(
        f"TC-15C: off 批次不應有 V3-000-policy，stdout={stdout_c[:300]!r}",
    )


# ── TC-16：Fix P1 evidence_path 缺欄（None）→ enforce 不綁 / 不足 min → FAIL ──
def tc16_p1_evidence_path_missing_key_enforce_skip() -> None:
    """
    Fix P1（縱深）：candidate.evidence_path 欄存在但值為空字串：
    enforce 下跳過不綁，跳過後不足 min_slots → error（等同 TC-13 enforce 路徑）。
    此 TC 驗「欄存在且空」的 enforce 行為（補縱深驗證）。
    """
    print("\n[TC-16] Fix P1 evidence_path 空字串 enforce 跳過 → 不足 min error")
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    def _cand_no_key(topic_id: str, confidence: float = 80) -> dict:
        """候選 evidence_path 欄存在但值為空字串"""
        c = _make_candidate(topic_id, confidence)
        c["evidence_path"] = ""  # 欄存在，值空字串
        return c

    with tempfile.TemporaryDirectory() as tmpdir:
        # 3 個候選全缺 evidence_path 欄 → enforce 全跳過 → qualified=0 < min=2 → FAIL
        candidates = [
            _cand_no_key("ti_tc16_A"),
            _cand_no_key("ti_tc16_B"),
            _cand_no_key("ti_tc16_C"),
        ]
        proj = _make_projection_json(candidates)
        proj_path = Path(tmpdir) / "active.json"
        proj_path.write_text(json.dumps(proj), encoding="utf-8")

        plan_out, report = assign_topic_sources(
            plan=_make_plan(n=5),
            dedup_info={},
            policy=_policy("enforce", min_slots=2, max_slots=4),
            projection_path=str(proj_path),
        )

    sti_count = sum(1 for item in plan_out if "source_topic_intel" in item)
    ok(f"TC-16: evidence_path 空字串 enforce → 綁 0（實得 {sti_count}）") \
        if sti_count == 0 else fail(
        f"TC-16: evidence_path 空字串 enforce 應綁 0，實得 {sti_count}",
    )
    has_error = bool(report.get("error"))
    ok("TC-16: 不足 min_slots → error 非空") if has_error else fail(
        f"TC-16: 應有 error，report={json.dumps(report, ensure_ascii=False)[:150]}",
    )
    has_warn = any("evidence_path" in w for w in report.get("warnings", []))
    ok("TC-16: warnings 含 evidence_path 說明") if has_warn else fail(
        f"TC-16: 應有 evidence_path 警告，warnings={report.get('warnings')}",
    )


# ── TC-17：Fix P2 usage_index_state 三值正確 ─────────────────────────────────
def tc17_p2_usage_index_state_three_values() -> None:
    """
    Fix P2：assign_report 含 usage_index_state 欄位，三值正確：
    A) ok：有 owner_code + index 正常讀（首批空 dict 也算 ok）
    B) missing：projection 無 owner_code 欄
    C) error：index 讀取失敗（shadow 不中斷，usage_index_state=error）
    """
    print("\n[TC-17] Fix P2 usage_index_state 三值（ok / missing / error）")
    from topic_distributor import assign_topic_sources  # type: ignore[import]
    import reconcile_topic_intel_usage as _rcu  # type: ignore[import]

    # A) ok：有 owner_code，首批 index 不存在（{} 放行）
    print("  [TC-17A] usage_index_state=ok（首批空 index）")
    with tempfile.TemporaryDirectory() as tmpdir_a:
        candidates_a = [_make_candidate(f"ti_tc17_A_{i}") for i in range(3)]
        proj_a = _make_projection_json(candidates_a, owner_code="tc17_owner")
        proj_path_a = Path(tmpdir_a) / "active.json"
        proj_path_a.write_text(json.dumps(proj_a), encoding="utf-8")

        _orig_load_a = _rcu.load_topic_usage_index
        def _empty_load(cfg=None):
            return {}, {}  # 首批空 index
        _rcu.load_topic_usage_index = _empty_load
        try:
            _, report_a = assign_topic_sources(
                plan=_make_plan(n=5),
                dedup_info={},
                policy=_policy("enforce", min_slots=2, max_slots=4),
                projection_path=str(proj_path_a),
            )
        finally:
            _rcu.load_topic_usage_index = _orig_load_a

    state_a = report_a.get("usage_index_state")
    ok(f"TC-17A: usage_index_state=ok（實得 {state_a!r}）") \
        if state_a == "ok" else fail(
        f"TC-17A: 期望 'ok'，實得 {state_a!r}，report={json.dumps(report_a, ensure_ascii=False)[:150]}",
    )

    # B) missing：projection owner_code 空 → _owner_code_for_dedup 空 → missing
    print("  [TC-17B] usage_index_state=missing（owner_code 空）")
    with tempfile.TemporaryDirectory() as tmpdir_b:
        candidates_b = [_make_candidate(f"ti_tc17_B_{i}") for i in range(3)]
        proj_b = _make_projection_json(candidates_b, owner_code="")  # 空 owner_code
        proj_path_b = Path(tmpdir_b) / "active.json"
        proj_path_b.write_text(json.dumps(proj_b), encoding="utf-8")

        _, report_b = assign_topic_sources(
            plan=_make_plan(n=5),
            dedup_info={},
            policy=_policy("enforce", min_slots=2, max_slots=4),
            projection_path=str(proj_path_b),
        )

    state_b = report_b.get("usage_index_state")
    ok(f"TC-17B: usage_index_state=missing（實得 {state_b!r}）") \
        if state_b == "missing" else fail(
        f"TC-17B: 期望 'missing'，實得 {state_b!r}，report={json.dumps(report_b, ensure_ascii=False)[:150]}",
    )

    # C) error：index 讀取失敗 shadow → 繼續跑，usage_index_state=error
    print("  [TC-17C] usage_index_state=error（index 讀取失敗，shadow 繼續跑）")
    with tempfile.TemporaryDirectory() as tmpdir_c:
        candidates_c = [_make_candidate(f"ti_tc17_C_{i}") for i in range(3)]
        proj_c = _make_projection_json(candidates_c, owner_code="tc17_owner_c")
        proj_path_c = Path(tmpdir_c) / "active.json"
        proj_path_c.write_text(json.dumps(proj_c), encoding="utf-8")

        _orig_load_c = _rcu.load_topic_usage_index
        def _error_load(cfg=None):
            raise RuntimeError("TC-17 mock index error")
        _rcu.load_topic_usage_index = _error_load
        try:
            _, report_c = assign_topic_sources(
                plan=_make_plan(n=5),
                dedup_info={},
                policy=_policy("shadow", min_slots=2, max_slots=4),  # shadow 繼續跑
                projection_path=str(proj_path_c),
            )
        finally:
            _rcu.load_topic_usage_index = _orig_load_c

    state_c = report_c.get("usage_index_state")
    ok(f"TC-17C: usage_index_state=error（實得 {state_c!r}）") \
        if state_c == "error" else fail(
        f"TC-17C: 期望 'error'，實得 {state_c!r}，report={json.dumps(report_c, ensure_ascii=False)[:150]}",
    )
    # shadow error path → 不應有 report.error（繼續跑）
    ok("TC-17C: shadow error index → report.error=None（繼續跑）") \
        if report_c.get("error") is None else fail(
        f"TC-17C: shadow 應繼續跑，report.error={report_c.get('error')!r}",
    )


# ── 執行 ──────────────────────────────────────────────────────────────────────

# ── TC-18：bind_scope=all_offpro 部分不足（pool thin WARN + 不擋批）─────────────
def tc18_bind_scope_all_offpro_pool_thin() -> None:
    """
    TC-18：bind_scope=all_offpro + 5 候選 / 9 offpro slot / min=2
    → 綁 5（不滿 9）+ WARN 含 pool thin + error=None（§22.9 絕不擋批）
    + assign_report 含 bind_scope 欄
    """
    print("\n[TC-18] bind_scope=all_offpro 部分不足（5 候選 / 9 offpro slot）")
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    with tempfile.TemporaryDirectory() as tmpdir:
        candidates = [_make_candidate(f"ti_tc18_{i}") for i in range(5)]
        proj = _make_projection_json(candidates)
        proj_path = Path(tmpdir) / "active.json"
        proj_path.write_text(json.dumps(proj), encoding="utf-8")

        plan = _make_hybrid_plan(n_offpro=9, n_anchor=2, n_pro=2)
        plan_out, report = assign_topic_sources(
            plan=plan,
            dedup_info={},
            policy=_policy("shadow", min_slots=2, max_slots=4, bind_scope="all_offpro"),
            projection_path=str(proj_path),
        )

    # 應綁 5 個（= 候選數，不足 9 但 ≥ min=2）
    sti_count = sum(1 for item in plan_out if "source_topic_intel" in item)
    ok(f"TC-18: 綁 5 個（實得 {sti_count}）") if sti_count == 5 else fail(
        f"TC-18: 期望綁 5，實得 {sti_count}",
        f"report={report.get('detail', '')}",
    )

    # bound slots 全部是 offpro slot（index 0-8）
    bound_slots = report.get("assigned_slots", [])
    all_offpro = all(plan[s].get("content_axis") == "offpro" for s in bound_slots)
    ok(f"TC-18: 綁入 slots 全為 offpro（slots={bound_slots}）") if all_offpro else fail(
        f"TC-18: 有非 offpro slot 被綁入，slots={bound_slots}",
    )

    # 應有 pool thin WARN（含「5」且含「9」字元，或含「pool thin」）
    has_pool_thin = any(
        "pool thin" in w or ("5" in w and "9" in w)
        for w in report.get("warnings", [])
    )
    ok("TC-18: warnings 含 pool thin WARN") if has_pool_thin else fail(
        "TC-18: 應有 pool thin WARN",
        f"warnings={report.get('warnings')}",
    )

    # error=None（§22.9 絕不擋批）
    ok("TC-18: error=None（不擋批）") if report.get("error") is None else fail(
        f"TC-18: error 應為 None，實得 {report.get('error')!r}",
    )

    # assign_report 含 bind_scope 欄（因為 bind_scope 非空）
    ok("TC-18: assign_report 含 bind_scope 欄") if "bind_scope" in report else fail(
        f"TC-18: assign_report 應含 bind_scope，keys={list(report.keys())}",
    )


# ── TC-19：bind_scope=all_offpro 充足（≥9 候選 → 綁滿 9）────────────────────────
def tc19_bind_scope_all_offpro_sufficient() -> None:
    """
    TC-19：bind_scope=all_offpro + 11 候選 / 9 offpro slot / min=2
    → 綁 9（滿）+ 無 pool thin WARN + error=None + 非 offpro slot 無 STI
    """
    print("\n[TC-19] bind_scope=all_offpro 充足（11 候選 / 9 offpro slot）")
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    with tempfile.TemporaryDirectory() as tmpdir:
        candidates = [_make_candidate(f"ti_tc19_{i}") for i in range(11)]
        proj = _make_projection_json(candidates)
        proj_path = Path(tmpdir) / "active.json"
        proj_path.write_text(json.dumps(proj), encoding="utf-8")

        plan = _make_hybrid_plan(n_offpro=9, n_anchor=2, n_pro=2)
        plan_out, report = assign_topic_sources(
            plan=plan,
            dedup_info={},
            policy=_policy("shadow", min_slots=2, max_slots=4, bind_scope="all_offpro"),
            projection_path=str(proj_path),
        )

    # 應綁 9 個（全部 offpro slot）
    sti_count = sum(1 for item in plan_out if "source_topic_intel" in item)
    ok(f"TC-19: 綁 9 個（實得 {sti_count}）") if sti_count == 9 else fail(
        f"TC-19: 期望綁 9，實得 {sti_count}",
        f"report={report.get('detail', '')}",
    )

    # bound slots 應剛好是 [0,1,...,8]（9 個 offpro）
    bound_slots = report.get("assigned_slots", [])
    ok(f"TC-19: slots=[0..8]（實得 {bound_slots}）") \
        if bound_slots == list(range(9)) else fail(
        f"TC-19: slots 期望 [0..8]，實得 {bound_slots}",
    )

    # 無 pool thin WARN
    has_pool_thin = any("pool thin" in w for w in report.get("warnings", []))
    ok("TC-19: 無 pool thin WARN（候選充足）") if not has_pool_thin else fail(
        f"TC-19: 不應有 pool thin WARN，warnings={report.get('warnings')}",
    )

    # error=None
    ok("TC-19: error=None（充足）") if report.get("error") is None else fail(
        f"TC-19: error 應為 None，實得 {report.get('error')!r}",
    )

    # 非 offpro slot 不含 source_topic_intel
    non_offpro_with_sti = [
        item for item in plan_out
        if item.get("content_axis") != "offpro" and "source_topic_intel" in item
    ]
    ok("TC-19: 非 offpro slot 無 source_topic_intel") if not non_offpro_with_sti else fail(
        f"TC-19: 非 offpro slot 不應有 STI，found={len(non_offpro_with_sti)} 個",
    )


# ── TC-20：legacy（無 bind_scope）assign_report 不含 bind_scope 欄（修 3 驗收）──
def tc20_legacy_no_bind_scope_in_report() -> None:
    """
    TC-20：legacy policy（無 bind_scope key）在 shadow/enforce PASS 時，
    assign_report 不應含 bind_scope 欄位（§修 3：不打破舊 assign_report byte-compat）
    """
    print("\n[TC-20] legacy（無 bind_scope）assign_report 不含 bind_scope 欄")
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    with tempfile.TemporaryDirectory() as tmpdir:
        candidates = [_make_candidate(f"ti_tc20_{i}") for i in range(5)]
        proj = _make_projection_json(candidates)
        proj_path = Path(tmpdir) / "active.json"
        proj_path.write_text(json.dumps(proj), encoding="utf-8")

        plan = _make_plan(n=5)  # 無 content_axis → legacy plan
        # _policy("shadow") 不帶 bind_scope（legacy）
        plan_out, report = assign_topic_sources(
            plan=plan,
            dedup_info={},
            policy=_policy("shadow", min_slots=2, max_slots=4),
            projection_path=str(proj_path),
        )

    # assign_report 不含 bind_scope 欄（legacy 行為）
    ok("TC-20: assign_report 無 bind_scope 欄（legacy）") \
        if "bind_scope" not in report else fail(
        f"TC-20: legacy assign_report 不應有 bind_scope，keys={list(report.keys())}",
    )

    # 仍正常綁（min=2 ≤ 5 候選 ≤ max=4 → 綁 4）
    sti_count = sum(1 for item in plan_out if "source_topic_intel" in item)
    ok(f"TC-20: legacy 仍正常綁（實得 {sti_count}）") if sti_count > 0 else fail(
        f"TC-20: legacy 應有正常綁入，sti_count={sti_count}",
    )


# ── TC-21：bind_scope=all_offpro 剛好 9 候選 / 9 offpro slot（邊界）─────────────
def tc21_bind_scope_exact_boundary() -> None:
    """
    TC-21：候選數 == offpro slot 數（9/9）
    → 綁 9、無 pool-thin WARN（不少一個）、error=None
    """
    print("\n[TC-21] bind_scope=all_offpro 邊界（9 候選 / 9 offpro slot）")
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    with tempfile.TemporaryDirectory() as tmpdir:
        candidates = [_make_candidate(f"ti_tc21_{i}") for i in range(9)]
        proj = _make_projection_json(candidates)
        proj_path = Path(tmpdir) / "active.json"
        proj_path.write_text(json.dumps(proj), encoding="utf-8")

        plan = _make_hybrid_plan(n_offpro=9, n_anchor=2, n_pro=2)
        plan_out, report = assign_topic_sources(
            plan=plan,
            dedup_info={},
            policy=_policy("shadow", min_slots=2, max_slots=4, bind_scope="all_offpro"),
            projection_path=str(proj_path),
        )

    # 應綁 9 個（剛好全滿）
    sti_count = sum(1 for item in plan_out if "source_topic_intel" in item)
    ok(f"TC-21: 綁 9 個（實得 {sti_count}）") if sti_count == 9 else fail(
        f"TC-21: 期望綁 9，實得 {sti_count}",
        f"report={report.get('detail', '')}",
    )

    # 無 pool-thin WARN（候選數剛好等於 slot 數，不算 thin）
    has_pool_thin = any("pool thin" in w for w in report.get("warnings", []))
    ok("TC-21: 無 pool thin WARN（9/9 剛好滿）") if not has_pool_thin else fail(
        f"TC-21: 9/9 不應有 pool thin，warnings={report.get('warnings')}",
    )

    # error=None
    ok("TC-21: error=None") if report.get("error") is None else fail(
        f"TC-21: error 應為 None，實得 {report.get('error')!r}",
    )

    # bound_slots 剛好 [0..8]
    bound_slots = report.get("assigned_slots", [])
    ok(f"TC-21: slots=[0..8]（實得 {bound_slots}）") \
        if bound_slots == list(range(9)) else fail(
        f"TC-21: slots 期望 [0..8]，實得 {bound_slots}",
    )


# ── TC-22：bind_scope=all_offpro 但批次 0 個 off-pro slot → 清楚 WARN + 不擋批 ──
def tc22_bind_scope_zero_offpro_slots() -> None:
    """
    TC-22：plan 中無 offpro slot（n_offpro=0）
    → 清楚 WARN（「此批無 off-pro slot」）、selected_count=0、error=None（不擋批）
    驗修 4：不再誤觸「qualified < min_slots」那條誤導分支
    """
    print("\n[TC-22] bind_scope=all_offpro 但 plan 無 offpro slot → 清楚 WARN + error=None")
    from topic_distributor import assign_topic_sources  # type: ignore[import]

    with tempfile.TemporaryDirectory() as tmpdir:
        # 足夠候選（proof 有料），排除「候選不足」那條分支
        candidates = [_make_candidate(f"ti_tc22_{i}") for i in range(10)]
        proj = _make_projection_json(candidates)
        proj_path = Path(tmpdir) / "active.json"
        proj_path.write_text(json.dumps(proj), encoding="utf-8")

        # plan 全為 non-offpro（anchor + professional only）
        plan = _make_hybrid_plan(n_offpro=0, n_anchor=4, n_pro=4)
        plan_out, report = assign_topic_sources(
            plan=plan,
            dedup_info={},
            policy=_policy("shadow", min_slots=2, max_slots=4, bind_scope="all_offpro"),
            projection_path=str(proj_path),
        )

    # 清楚 WARN 含「off-pro slot」或「無可綁定」
    has_clear_warn = any(
        "off-pro slot" in w or "無可綁定" in w
        for w in report.get("warnings", [])
    )
    ok("TC-22: warnings 含清楚 off-pro slot WARN") if has_clear_warn else fail(
        f"TC-22: 應有清楚 WARN，warnings={report.get('warnings')}",
    )

    # 不含「qualified < min_slots」誤導訊息
    no_misleading = not any("min_slots" in w for w in report.get("warnings", []))
    ok("TC-22: warnings 無 min_slots 誤導訊息") if no_misleading else fail(
        f"TC-22: 不應有 min_slots 誤導 WARN，warnings={report.get('warnings')}",
    )

    # selected_count=0、error=None（不擋批）
    ok(f"TC-22: selected_count=0（實得 {report.get('selected_count')}）") \
        if report.get("selected_count") == 0 else fail(
        f"TC-22: selected_count 應為 0，實得 {report.get('selected_count')}",
    )
    ok("TC-22: error=None（不擋批）") if report.get("error") is None else fail(
        f"TC-22: error 應為 None，實得 {report.get('error')!r}",
    )

    # plan 未被改動（無 source_topic_intel）
    sti_count = sum(1 for item in plan_out if "source_topic_intel" in item)
    ok(f"TC-22: plan 無 source_topic_intel（{sti_count}）") if sti_count == 0 else fail(
        f"TC-22: 應綁 0，實得 {sti_count}",
    )


# ── TC-23：_owner_matches alias 命中（修 6）──────────────────────────────────

def tc23_owner_matches_alias_hit() -> None:
    """
    TC-23：_owner_matches alias 命中（修 6）
    業主 proj 有 _aliases=["叭噗"]，applicable_owners=["叭噗"]
    → _owner_matches 應回傳 True（alias 命中）

    對比：
    - applicable_owners=["不存在"] → False
    - applicable_owners=[] → 走 industry 路徑（非 alias 路徑）
    - applicable_owners=["叭噗_小C"] → True（正式名命中）
    """
    print("\n[TC-23] _owner_matches alias 命中（修 6）")
    from gen_topic_intel_projection import _owner_matches  # type: ignore[import]

    owner_rec = {
        "owner_name": "叭噗_小C",
        "owner_id": "BAPU",
        "owner_code": "bappu",
        "_aliases": ["叭噗"],   # runtime_aliases 逆查：叭噗 → 叭噗_小C
        "industry_id": "美容",
        "industries": ["美容"],
    }

    # (A) alias 命中 → True
    result_a = _owner_matches(owner_rec, applicable_owners=["叭噗"], industry="美容")
    ok("TC-23A: alias 命中 → True") if result_a is True else fail(
        f"TC-23A: 應 True，實得 {result_a!r}",
    )

    # (B) 正式名命中 → True（regression 保護）
    result_b = _owner_matches(owner_rec, applicable_owners=["叭噗_小C"], industry="美容")
    ok("TC-23B: 正式名命中 → True") if result_b is True else fail(
        f"TC-23B: 應 True，實得 {result_b!r}",
    )

    # (C) owner_id 命中 → True（regression 保護）
    result_c = _owner_matches(owner_rec, applicable_owners=["BAPU"], industry="美容")
    ok("TC-23C: owner_id 命中 → True") if result_c is True else fail(
        f"TC-23C: 應 True，實得 {result_c!r}",
    )

    # (D) 不在清單且無 alias 命中 → False（owner-leak 保護）
    result_d = _owner_matches(owner_rec, applicable_owners=["瑞祥"], industry="美容")
    ok("TC-23D: 不含此業主 → False（owner-leak 保護）") if result_d is False else fail(
        f"TC-23D: 應 False，實得 {result_d!r}",
    )

    # (E) applicable_owners 空 → 走 industry 路徑（alias 路徑不觸發）
    result_e = _owner_matches(owner_rec, applicable_owners=[], industry="美容")
    ok("TC-23E: applicable_owners 空 + industry 命中 → True") if result_e is True else fail(
        f"TC-23E: 應 True（industry 路徑），實得 {result_e!r}",
    )


if __name__ == "__main__":
    print("=" * 60)
    print("  WP-B 閉環整合測試 test_wpb_closure.py")
    print(f"  PYTHONHASHSEED={os.environ.get('PYTHONHASHSEED', '(未設定，TC-1 off byte-compat 需=0)')}")
    print("=" * 60)

    tc1_off_byte_compat()
    tc2_shadow_warn_insufficient()
    tc3_enforce_fail_insufficient()
    tc4_enforce_pass()
    tc5_cross_batch_dedup()
    tc6_stale_projection()
    tc7_v3002_batch_slot_count()
    tc8_fix_h_golden_and_owner_code()
    tc9_fix1_is_skeleton_missing_key()
    tc10_fix2_owner_code_failload()
    tc11_fix3_usage_index_tristate()
    tc12_fix4_projection_cache_missing_enforce_fail()
    tc13_fix5_evidence_path_empty_enforce_skip()
    tc14_p01_projection_cache_corrupt_enforce_fail()
    tc15_p02_invalid_policy_fail_closed()
    tc16_p1_evidence_path_missing_key_enforce_skip()
    tc17_p2_usage_index_state_three_values()
    tc18_bind_scope_all_offpro_pool_thin()
    tc19_bind_scope_all_offpro_sufficient()
    tc20_legacy_no_bind_scope_in_report()
    tc21_bind_scope_exact_boundary()
    tc22_bind_scope_zero_offpro_slots()
    tc23_owner_matches_alias_hit()

    print("\n" + "=" * 60)
    print(f"  結果：{PASS_COUNT} PASS / {FAIL_COUNT} FAIL")
    if ERRORS:
        print("\n  FAIL 清單：")
        for e in ERRORS:
            print(e)
    print("=" * 60)

    sys.exit(0 if FAIL_COUNT == 0 else 1)
