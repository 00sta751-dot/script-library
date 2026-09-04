#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WP-B 選題情報綁定。

此模組只保留仍由 topic-intel 閉環測試與相容流程使用的純綁定函式；
舊 YAML 題目分配 CLI 已於 2026-09-04 退役。
"""

import os
from typing import Optional


def assign_topic_sources(
    plan: list[dict],
    dedup_info: dict,
    policy: Optional[dict],
    projection_path: Optional[str],
) -> tuple[list[dict], dict]:
    """
    WP-B：按 policy 把選題情報池候選綁進 plan 前 N 個 slot。

    flag-off / policy 未提供 / mode=off → 完全不 import adapter/projection、
    不讀池、回原 plan 零改動、assign_report 標 disabled。
    （lazy import 設計：import 寫在函式內、不在模組頂層）

    參數：
      plan            : distribute_topics() 回傳的 plan list
      dedup_info      : distribute_topics() 回傳的 dedup_info dict
      policy          : load_topic_intel_policy() 回傳的 policy dict；
                        None 視為 disabled
      projection_path : 業主 active.json 的絕對路徑字串；
                        None 且 policy enabled 時 → assign_report error

    回傳：
      (plan, assign_report)
      plan：加了 source_topic_intel 欄位（off 時不動）
      assign_report：dict{mode/enabled/selected_count/assigned_slots/error/warnings}

    規格 §9（r3）：
      - off/disabled → 完全不 import、回原 plan
      - on：讀 projection；按 §9.1 排序（projection 已排序，直接用）
      - in-batch reservation（§9.7 set 去重）
      - 不足 min + enforce → 不綁 + error
      - batch_id 單一來源 = plan[0]["batch"]；不一致 → error
    """
    # --- invalid policy 路徑（Fix P0-2）：有寫 topic_intel_closure 但設定不合法 ---
    # invalid ≠ off；invalid 要回 error（不綁）讓外層看到失敗狀態
    if policy is not None and policy.get("mode") == "invalid":
        _inv_detail = policy.get("detail", "topic_intel_closure 設定不合法")
        return plan, {
            "mode": "invalid",
            "enabled": False,
            "selected_count": 0,
            "assigned_slots": [],
            "error": f"topic_intel_closure 設定不合法（invalid），fail-closed 不綁：{_inv_detail}",
            "warnings": [],
            "detail": f"assign 拒絕：policy invalid",
        }

    # --- off 路徑（零足跡）---
    if policy is None or not policy.get("enabled", False):
        return plan, {
            "mode": "off",
            "enabled": False,
            "selected_count": 0,
            "assigned_slots": [],
            "error": None,
            "warnings": [],
            "detail": "WP-B assign disabled（policy off/None）",
        }

    # --- on 路徑（lazy import）---
    import json as _json  # noqa: PLC0415（lazy import）
    from pathlib import Path as _Path  # noqa: PLC0415

    mode = policy.get("mode", "off")
    min_slots: int = policy.get("min_slots") or 2
    max_slots: int = policy.get("max_slots") or 4
    # bind_scope="all_offpro" → 綁滿 plan 中所有 offpro slot；"" → legacy max_slots 行為
    bind_scope: str = str(policy.get("bind_scope", "") or "")

    warnings: list[str] = []
    assign_report_base: dict = {
        "mode": mode,
        "enabled": True,
        "min_slots": min_slots,
        "max_slots": max_slots,
    }
    # bind_scope 只在非空時加入（legacy 無此欄，不打破舊 assign_report byte-compat）
    if bind_scope:
        assign_report_base["bind_scope"] = bind_scope

    # batch_id 一致性（§9 r3 盲點1）
    batch_id: Optional[str] = None
    if plan:
        batch_id = plan[0].get("batch")
        inconsistent = [
            i for i, item in enumerate(plan)
            if item.get("batch") != batch_id
        ]
        if inconsistent:
            msg = (
                f"plan 內 batch 欄位不一致（plan[0]['batch']={batch_id!r}，"
                f"不一致 slot index: {inconsistent}）"
            )
            return plan, {
                **assign_report_base,
                "selected_count": 0,
                "assigned_slots": [],
                "error": msg,
                "warnings": warnings,
                "detail": f"assign error: {msg}",
            }

    # 讀 projection
    if not projection_path:
        msg = "projection_path 未提供，無法讀選題情報池 projection"
        return plan, {
            **assign_report_base,
            "selected_count": 0,
            "assigned_slots": [],
            "error": msg,
            "warnings": warnings,
            "detail": f"assign error: {msg}",
        }

    proj_file = _Path(projection_path)
    if not proj_file.exists():
        msg = f"projection 檔不存在：{projection_path}"
        return plan, {
            **assign_report_base,
            "selected_count": 0,
            "assigned_slots": [],
            "error": msg,
            "warnings": warnings,
            "detail": f"assign error: {msg}",
        }

    try:
        proj_data = _json.loads(proj_file.read_text(encoding="utf-8"))
    except Exception as e:
        msg = f"projection 讀取失敗：{e}"
        return plan, {
            **assign_report_base,
            "selected_count": 0,
            "assigned_slots": [],
            "error": msg,
            "warnings": warnings,
            "detail": f"assign error: {msg}",
        }

    # ── Fix 1a：新鮮度驗（expires_at TTL）──────────────────────────────────────
    # assign 只驗 expires_at；池變動新鮮度由「出批前重生 projection」保證。
    from datetime import datetime as _dt, timezone as _tz  # noqa: PLC0415
    _now_utc = _dt.now(tz=_tz.utc)

    proj_expires_at = proj_data.get("expires_at", "")
    # Fix D【P1】enforce 模式下，expires_at 缺失/空/parse 失敗 → error + 不綁；shadow → WARN
    _expires_at_ok = False
    _expires_at_err: str = ""
    if not proj_expires_at:
        _expires_at_err = "projection expires_at 缺失或空白，無法驗新鮮度"
    else:
        try:
            _exp = _dt.fromisoformat(proj_expires_at.replace("Z", "+00:00"))
            if _now_utc > _exp:
                _expires_at_err = (
                    f"projection expires_at={proj_expires_at} 已過期（stale），"
                    f"請先重生 projection（python gen_topic_intel_projection.py）"
                )
            else:
                _expires_at_ok = True
        except Exception as _exp_err:
            _expires_at_err = (
                f"expires_at 解析失敗（{proj_expires_at!r}）: {_exp_err}"
            )

    if not _expires_at_ok:
        if mode == "enforce":
            return plan, {
                **assign_report_base,
                "selected_count": 0,
                "assigned_slots": [],
                "error": _expires_at_err,
                "warnings": warnings,
                "detail": f"assign error（enforce expires_at）: {_expires_at_err}",
            }
        else:
            warnings.append(
                f"[WARN] {_expires_at_err}，shadow 本批不綁趨勢題"
            )
            return plan, {
                **assign_report_base,
                "selected_count": 0,
                "assigned_slots": [],
                "batch_id": batch_id,
                "error": None,
                "warnings": warnings,
                "detail": (
                    "assign skip（shadow stale projection，本批不綁趨勢題）: "
                    f"{_expires_at_err}"
                ),
            }

    # ── Fix 1b：跨批去重（is_recently_used）─────────────────────────────────────
    # lazy import reconcile_topic_intel_usage.is_recently_used
    # usage index 不存在/空 → fail-soft 不跳過（首批正常）
    _owner_code_for_dedup: str = ""
    try:
        # 從 projection metadata 取 owner_code（避免主動讀 config）
        _owner_code_for_dedup = str(proj_data.get("owner_code", "") or "")
    except Exception:
        pass

    # Fix E【P1】is_recently_used 三態：ok / used / error（index 存在但讀失敗 → enforce 擋）
    # 回傳 (is_used: bool, error_msg: str | None)
    def _is_recently_used_tristate(tid: str) -> tuple:
        """
        三態查詢（直接呼叫 is_recently_used + load_topic_usage_index，支援 monkeypatch）：
          (True, None)  → 近期已用
          (False, None) → 確認未用 / index 不存在（首批）
          (False, str)  → index 存在但讀取/解析失敗（error_msg 非空）
        """
        if not _owner_code_for_dedup:
            return (False, None)
        try:
            from reconcile_topic_intel_usage import (  # type: ignore[import]
                load_topic_usage_index as _load_idx,
                is_recently_used as _iru,
            )
            # 先嘗試讀 index（可被 monkeypatch 攔）
            try:
                _by_owner, _ = _load_idx()
            except Exception as _load_err:
                # index 讀失敗 → error 三態
                return (False, f"index 讀取失敗：{_load_err}")

            # index 不含此 owner → 首批（WARN 放行，不是 error）
            if _owner_code_for_dedup not in _by_owner:
                return (False, None)

            # owner 有記錄 → 呼叫完整查詢
            _result = _iru(tid, _owner_code_for_dedup)
            return (_result, None)
        except Exception as _e:
            # reconcile 模組 import 失敗 → fail-soft 放行（未部署場景）
            return (False, None)

    # 候選（projection 已按 §9.1 排序）
    candidates: list[dict] = proj_data.get("candidates", [])

    # Fix E：過濾使用三態查詢；index 存在但讀失敗 → enforce 擋
    filtered_candidates: list[dict] = []
    skipped_recently_used: list[str] = []
    _dedup_index_error: str = ""
    for _cand in candidates:
        _tid = _cand.get("topic_id", "")
        _used, _err = _is_recently_used_tristate(_tid)
        if _err and not _dedup_index_error:
            _dedup_index_error = _err  # 記第一個錯誤
        if _used:
            skipped_recently_used.append(_tid)
            continue
        filtered_candidates.append(_cand)

    # index 讀失敗處理（Fix E）
    if _dedup_index_error:
        _err_msg = f"跨批去重 index 讀取失敗（{_dedup_index_error}）"
        if mode == "enforce":
            return plan, {
                **assign_report_base,
                "selected_count": 0,
                "assigned_slots": [],
                "error": _err_msg,
                "warnings": warnings,
                "detail": f"assign error（enforce dedup index error）: {_err_msg}",
            }
        else:
            warnings.append(f"[WARN] {_err_msg}，shadow 繼續跑")

    if skipped_recently_used:
        warnings.append(
            f"跨批去重：跳過 {len(skipped_recently_used)} 支近期已用候選（owner={_owner_code_for_dedup}）"
        )

    # Fix P2：usage_index_state 三值（shadow/enforce 都記，供部署審查分辨「首批空」vs「路徑配錯」）
    if _dedup_index_error:
        _usage_index_state = "error"
    elif not _owner_code_for_dedup:
        _usage_index_state = "missing"
    else:
        _usage_index_state = "ok"
    assign_report_base["usage_index_state"] = _usage_index_state

    # P1-b round 5（御史 M2）跨業主 7 天冷卻 — flag gate TOPIC_INTEL_CROSS_OWNER_COOLDOWN
    # 預設關（免每 build 打 reconcile API）；開時 shadow WARN，S3 enforce 才擋
    _cross_owner_cooldown_enabled = os.environ.get('TOPIC_INTEL_CROSS_OWNER_COOLDOWN', '').strip() == '1'
    _cross_owner_warned: list[str] = []
    if _cross_owner_cooldown_enabled:
        try:
            from reconcile_topic_intel_usage import is_recently_used_by_other_owner as _iru_cross
            _current_industry = proj_data.get("industry_id") if isinstance(proj_data, dict) else None
            for _cand in filtered_candidates:
                _tid = _cand.get("topic_id", "")
                if not _tid:
                    continue
                try:
                    _cross_used = _iru_cross(
                        topic_id=_tid,
                        current_owner=_owner_code_for_dedup or "",
                        current_industry=_current_industry,
                        max_days=7,
                        same_industry_only=True,
                    )
                    if _cross_used:
                        _cross_owner_warned.append(_tid)
                except Exception:
                    pass  # fail-soft 不擋
        except ImportError:
            pass  # reconcile 未部署 → skip（非 blocker）

        if _cross_owner_warned:
            warnings.append(
                f"[WARN/industry-native] 跨業主 7 天冷卻：{len(_cross_owner_warned)} 支候選近 7 天被同行業其他業主採用過"
                f"（shadow 觀測、S3 enforce 才擋）: {_cross_owner_warned[:5]}"
            )

    qualified_count = len(filtered_candidates)

    # bind_scope=all_offpro → 只綁 offpro slot，以 plan 中 offpro 數量為上限
    # bind_scope="" (legacy) → 綁前 max_slots 個 slot，不看 content_axis（向後相容）
    if bind_scope == "all_offpro":
        eligible_slot_indices = [
            i for i, item in enumerate(plan)
            if item.get("content_axis") == "offpro"
        ]
        effective_max_slots = len(eligible_slot_indices)
        if effective_max_slots == 0:
            # 此批無 offpro slot → 無可綁定（不是候選不足）→ 清楚 WARN + 乾淨結束（§22.9 不擋批）
            warnings.append("[WARN] 此批無 off-pro slot，bind_scope=all_offpro 無可綁定，略過（不擋批）")
            return plan, {
                **assign_report_base,
                "selected_count": 0,
                "assigned_slots": [],
                "qualified_count": qualified_count,
                "batch_id": batch_id,
                "error": None,
                "warnings": warnings,
                "detail": "assign skip: bind_scope=all_offpro 但此批無 off-pro slot（不擋批）",
            }
    else:
        # legacy：全 slot 候補，effective_max_slots = max_slots
        eligible_slot_indices = list(range(len(plan)))
        effective_max_slots = max_slots

    # 計算 selected_count（用 effective_max_slots）
    if qualified_count < min_slots:
        selected_count = 0
    else:
        selected_count = min(effective_max_slots, qualified_count)

    # enforce 不足 min → 不綁 + error；shadow → 綁得到的就綁（§22.9 絕不擋批、絕不退題）
    if selected_count == 0:
        msg = (
            f"合格候選 {qualified_count} 支 < min_slots={min_slots}，"
            f"enforce 不綁（需補充選題情報池 pending 料）"
        )
        if mode == "shadow":
            # shadow：候選不足時綁 qualified_count 個觀察，絕不擋批（§22.9 紅線）
            selected_count = qualified_count
            warnings.append(f"shadow: 合格候選 {qualified_count} < min_slots={min_slots}，綁 {qualified_count} 個觀察")
        else:
            return plan, {
                **assign_report_base,
                "selected_count": 0,
                "assigned_slots": [],
                "error": msg,
                "warnings": warnings,
                "detail": f"assign error（enforce）: {msg}",
            }

    # in-batch reservation（§9.7）+ 跨批去重已在 filtered_candidates 完成
    reserved_topic_ids: set[str] = set()
    selected: list[dict] = []
    for candidate in filtered_candidates:
        if len(selected) >= selected_count:
            break
        tid = candidate.get("topic_id", "")
        if tid in reserved_topic_ids:
            continue
        selected.append(candidate)
        reserved_topic_ids.add(tid)

    # pool-thin WARN（bind_scope=all_offpro + 有候選但不足 offpro slot 數）§22.9 絕不擋批
    if bind_scope == "all_offpro" and 0 < len(selected) < len(eligible_slot_indices):
        warnings.append(
            f"[WARN] pool thin: 綁了 {len(selected)}/{len(eligible_slot_indices)} 個 off-pro slot，"
            f"剩 {len(eligible_slot_indices) - len(selected)} 個 slot 留給編劇走正常 off-pro（不擋批）"
        )

    # 綁進 eligible_slot_indices 的前 N 個 slot
    # bind_scope=all_offpro → eligible_slot_indices 只含 offpro 位置
    # legacy → eligible_slot_indices = [0,1,...,N-1]（與舊行為 byte-identical）
    assigned_slots: list[int] = []
    plan_copy = [dict(item) for item in plan]  # 不 mutate 原 plan

    for i, candidate in enumerate(selected):
        # 取目標 slot index
        if i >= len(eligible_slot_indices):
            warnings.append(
                f"eligible_slot_indices 長度 {len(eligible_slot_indices)} < selected {len(selected)}，截斷"
            )
            break
        target_slot = eligible_slot_indices[i]

        # Fix G：evidence_path 從 projection candidate 的 evidence_path 欄取 canonical path
        # gen_topic_intel_projection 在 qualified.append(proj) 前已填入 path.resolve()
        _ev_path_raw = candidate.get("evidence_path")  # None = 欄不存在（舊格式/fixture）
        _ev_path = str(_ev_path_raw or "").strip()
        # Fix P1（縱深）：欄存在但空字串 → enforce 跳過不綁；shadow WARN 仍綁
        # 欄不存在（None）= 舊格式候選，不觸發此檢查（沿用空路徑繼續綁）
        # 生產 projection 必填 evidence_path（gen_topic_intel_projection 保證填入 resolve() 值）
        if _ev_path_raw is not None and not _ev_path:
            _tid_for_warn = candidate.get("topic_id", "?")
            if mode == "enforce":
                warnings.append(
                    f"[WARN] 候選 topic_id={_tid_for_warn!r} evidence_path 空，enforce 跳過不綁"
                )
                continue  # 不綁這個候選，繼續下一個
            else:
                warnings.append(
                    f"[WARN] 候選 topic_id={_tid_for_warn!r} evidence_path 空，shadow 綁但標空路徑"
                )
        plan_copy[target_slot]["source_topic_intel"] = {
            "topic_id": candidate.get("topic_id", ""),
            "source_kind": "cyborg_yaml",
            "evidence_path": _ev_path,       # Fix G+Fix5：assign 端必填 canonical path
            "evidence_sha256": candidate.get("source_sha256", ""),
            "adopted_topic_statement": "",   # 編劇填
            "assigned_by": "topic_distributor",
            "assignment_mode": mode,
        }
        assigned_slots.append(target_slot)

    # Fix P1 縱深：assign loop 後若 enforce 且實際綁入數 < min_slots（evidence_path 空等情形跳過）→ error
    if mode == "enforce" and len(assigned_slots) < min_slots:
        _post_assign_err = (
            f"實際綁入 {len(assigned_slots)} 個 < min_slots={min_slots}，"
            f"enforce 不足（候選可能被 evidence_path 空等過濾跳過）"
        )
        return plan_copy, {
            **assign_report_base,
            "selected_count": len(selected),
            "assigned_slots": assigned_slots,
            "qualified_count": qualified_count,
            "batch_id": batch_id,
            "error": _post_assign_err,
            "warnings": warnings,
            "detail": f"assign error（post-loop enforce）: {_post_assign_err}",
        }

    return plan_copy, {
        **assign_report_base,
        "selected_count": len(selected),
        "assigned_slots": assigned_slots,
        "qualified_count": qualified_count,
        "batch_id": batch_id,
        "error": None,
        "warnings": warnings,
        "detail": (
            f"assign OK: mode={mode}, selected={len(selected)}/{qualified_count}, "
            f"slots={assigned_slots}"
        ),
    }
