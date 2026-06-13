#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topic_intel_policy.py -- WP-B 選題情報池 policy loader（fail-closed）
WP-B Wave 1 Step 4 / 2026-06-13

職責：
  讀取批次 _batch_flags.yml 的 topic_intel_closure 區塊，
  決定本批 WP-B 模式（off / shadow / enforce）。

  fail-closed 設計（仿 load_fishing_policy validate_script_batch.py line 2224-2316）：
  - 無 flag 檔 → disabled（等同 mode=off）
  - mode=off → disabled
  - 任何不合法條件 → invalid（消費端 fail-closed：validator 加 V3-000-policy FAIL / assign 回 error；invalid ≠ off 靜默略過）
  - 有效設定 → 回 mode + 完整 policy dict

回傳 dict 欄位：
  mode        : "off" | "shadow" | "enforce" | "invalid" | "disabled"
  enabled     : bool（mode in shadow/enforce）
  min_slots   : int | None
  max_slots   : int | None
  approved_by : str | None
  approved_at : str | None
  detail      : str（說明）

規格 §9.4（規格來源）：
  無 flag 檔 與 mode=off 走同一 disabled 回傳
  topic_intel_closure:
    mode: enforce   # off | shadow | enforce
    min_slots: 2
    max_slots: 4
    approved_by: 澤君
    approved_at: "2026-06-13"

用法（lazy import 示範）：
  def some_fn(batch_dir):
      from topic_intel_policy import load_topic_intel_policy
      policy = load_topic_intel_policy(batch_dir)
      if not policy["enabled"]:
          return  # off / disabled / invalid → 不處理
"""

from pathlib import Path
from typing import Optional, Union

# 合法 mode 值
_VALID_MODES = frozenset(["off", "shadow", "enforce"])

# min/max slots 合法範圍（規格 §9：2..4）
_MIN_SLOTS_LOWER = 2
_MAX_SLOTS_UPPER = 4


def _disabled(detail: str) -> dict:
    """回傳 disabled 狀態（無 flag 檔 與 mode=off 共用）"""
    return {
        "mode": "off",
        "enabled": False,
        "min_slots": None,
        "max_slots": None,
        "approved_by": None,
        "approved_at": None,
        "detail": detail,
    }


def _invalid(detail: str) -> dict:
    """回傳 invalid 狀態（fail-closed，行為同 disabled）"""
    return {
        "mode": "invalid",
        "enabled": False,
        "min_slots": None,
        "max_slots": None,
        "approved_by": None,
        "approved_at": None,
        "detail": f"[invalid] {detail}",
    }


def load_topic_intel_policy(
    batch_dir_or_flag_path: Union[str, Path, None],
) -> dict:
    """
    讀取 _batch_flags.yml 的 topic_intel_closure 區塊。

    參數：
      batch_dir_or_flag_path : 批次目錄路徑（讀 <dir>/_batch_flags.yml）
                               或 _batch_flags.yml 的直接路徑
                               或 None（直接回 disabled）

    回傳 policy dict（欄位見模組說明）。

    判定邏輯：
    1. 無參數 / None → disabled
    2. 找不到 _batch_flags.yml → disabled（規格 §9.4：與 mode=off 同 disabled）
    3. _batch_flags.yml 解析失敗 → invalid
    4. 無 topic_intel_closure 區塊 → disabled
    5. mode 非 string 或不在 {off, shadow, enforce} → invalid
    6. mode=off → disabled
    7. mode in {shadow, enforce}：驗 approved_by==澤君、approved_at 可 parse、
       min_slots/max_slots 合法（2..4，min<=max）→ 任何不合 → invalid
    8. 全部合法 → 回 mode + 完整 policy
    """
    # 1. 無參數
    if batch_dir_or_flag_path is None:
        return _disabled("未提供 batch_dir，WP-B topic_intel_closure 未啟用")

    p = Path(batch_dir_or_flag_path)

    # 決定 flag_path
    if p.is_dir():
        flag_path = p / "_batch_flags.yml"
    elif p.name == "_batch_flags.yml":
        flag_path = p
    elif p.is_file():
        # 傳了其他檔案路徑 → 試用其父目錄
        flag_path = p.parent / "_batch_flags.yml"
    else:
        # 路徑不存在或其他情況：視為 batch_dir 且 flag 不存在
        flag_path = p / "_batch_flags.yml"

    # 2. flag 檔不存在 → disabled
    if not flag_path.exists():
        return _disabled(
            f"無 _batch_flags.yml（{flag_path}），WP-B topic_intel_closure 未啟用"
        )

    # 3. 解析 yaml
    try:
        import yaml as _yaml_mod
        raw = _yaml_mod.safe_load(flag_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return _invalid(f"_batch_flags.yml 解析失敗：{e}")

    if not isinstance(raw, dict):
        return _invalid(
            f"_batch_flags.yml top-level 非 mapping（{type(raw).__name__}）"
        )

    # 4. topic_intel_closure 區塊
    closure_cfg = raw.get("topic_intel_closure")
    if closure_cfg is None:
        return _disabled(
            "無 topic_intel_closure 區塊，WP-B 未啟用"
        )
    if not isinstance(closure_cfg, dict):
        return _invalid(
            f"topic_intel_closure 非 mapping（{type(closure_cfg).__name__}）"
        )

    # 5. mode 驗證
    # 注意：YAML 1.1 把 "off" 解析成 Python False（布林），需先轉字串再比對
    mode_raw = closure_cfg.get("mode")
    if mode_raw is False or mode_raw is None:
        # YAML 1.1 off/false/no → False；統一視為 "off"
        mode = "off"
    elif mode_raw is True:
        return _invalid(
            "topic_intel_closure.mode=true 不合法（需字串 off/shadow/enforce）"
        )
    elif isinstance(mode_raw, str):
        mode = mode_raw.strip().lower()
    else:
        return _invalid(
            f"topic_intel_closure.mode 型別不合法（{type(mode_raw).__name__}: {mode_raw!r}）"
        )

    if mode not in _VALID_MODES:
        return _invalid(
            f"topic_intel_closure.mode={mode!r} 不合法（需 off/shadow/enforce）"
        )

    # 6. mode=off → disabled
    if mode == "off":
        return _disabled("topic_intel_closure.mode=off，WP-B 未啟用")

    # 7. mode in {shadow, enforce}：驗 approved_by / approved_at / min_slots / max_slots
    errors = []

    approved_by = closure_cfg.get("approved_by", "")
    if approved_by != "澤君":
        errors.append(f"approved_by={approved_by!r}（需為「澤君」）")

    approved_at = closure_cfg.get("approved_at", "")
    approved_at_str = str(approved_at).strip() if approved_at else ""
    if not approved_at_str:
        errors.append("approved_at 為空")
    else:
        # 簡單驗：能 parse 到 YYYY-MM-DD 格式
        import re as _re
        if not _re.match(r"^\d{4}-\d{2}-\d{2}", approved_at_str):
            errors.append(
                f"approved_at={approved_at_str!r} 無法解析日期（需 YYYY-MM-DD）"
            )

    min_slots_raw = closure_cfg.get("min_slots")
    max_slots_raw = closure_cfg.get("max_slots")

    try:
        min_slots = int(min_slots_raw)
    except (TypeError, ValueError):
        min_slots = None
        errors.append(f"min_slots={min_slots_raw!r} 非整數")

    try:
        max_slots = int(max_slots_raw)
    except (TypeError, ValueError):
        max_slots = None
        errors.append(f"max_slots={max_slots_raw!r} 非整數")

    if min_slots is not None and max_slots is not None:
        if min_slots < _MIN_SLOTS_LOWER:
            errors.append(
                f"min_slots={min_slots} 低於最小值 {_MIN_SLOTS_LOWER}"
            )
        if max_slots > _MAX_SLOTS_UPPER:
            errors.append(
                f"max_slots={max_slots} 高於最大值 {_MAX_SLOTS_UPPER}"
            )
        if min_slots > max_slots:
            errors.append(
                f"min_slots={min_slots} > max_slots={max_slots}"
            )

    if errors:
        return _invalid(
            f"topic_intel_closure 條件不完整：{'; '.join(errors)}"
        )

    # 8. 全部合法
    return {
        "mode": mode,
        "enabled": True,
        "min_slots": min_slots,
        "max_slots": max_slots,
        "approved_by": approved_by,
        "approved_at": approved_at_str,
        "detail": (
            f"WP-B enabled（mode={mode}, min={min_slots}, max={max_slots}, "
            f"approved_by={approved_by}, approved_at={approved_at_str}）"
        ),
    }


# ── 快速自測（python topic_intel_policy.py）─────────────────────────────────
if __name__ == "__main__":
    import tempfile, os, json

    def _write_flag(tmp_dir: str, content: str) -> str:
        p = os.path.join(tmp_dir, "_batch_flags.yml")
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return tmp_dir

    with tempfile.TemporaryDirectory() as tmpdir:
        # Case 1: 無 flag 檔 → disabled
        empty_dir = tempfile.mkdtemp()
        r1 = load_topic_intel_policy(empty_dir)
        assert r1["mode"] == "off" and not r1["enabled"], f"Case 1 failed: {r1}"
        print(f"Case 1 PASS: 無 flag 檔 → disabled, mode={r1['mode']}")

        # Case 2: None → disabled
        r2 = load_topic_intel_policy(None)
        assert r2["mode"] == "off" and not r2["enabled"], f"Case 2 failed: {r2}"
        print(f"Case 2 PASS: None → disabled")

        # Case 3: mode=off → disabled
        _write_flag(tmpdir, "topic_intel_closure:\n  mode: off\n")
        r3 = load_topic_intel_policy(tmpdir)
        assert r3["mode"] == "off" and not r3["enabled"], f"Case 3 failed: {r3}"
        print(f"Case 3 PASS: mode=off → disabled")

        # Case 4: enabled 非 boolean / approved_by 錯 → invalid
        _write_flag(tmpdir, """topic_intel_closure:
  mode: enforce
  min_slots: 2
  max_slots: 4
  approved_by: 錯人
  approved_at: "2026-06-13"
""")
        r4 = load_topic_intel_policy(tmpdir)
        assert r4["mode"] == "invalid" and not r4["enabled"], f"Case 4 failed: {r4}"
        assert "澤君" in r4["detail"], f"Case 4 detail: {r4['detail']}"
        print(f"Case 4 PASS: approved_by 錯 → invalid")

        # Case 5: min > max → invalid
        _write_flag(tmpdir, """topic_intel_closure:
  mode: shadow
  min_slots: 4
  max_slots: 2
  approved_by: 澤君
  approved_at: "2026-06-13"
""")
        r5 = load_topic_intel_policy(tmpdir)
        assert r5["mode"] == "invalid" and not r5["enabled"], f"Case 5 failed: {r5}"
        print(f"Case 5 PASS: min>max → invalid")

        # Case 6: 完整有效 enforce → enabled
        _write_flag(tmpdir, """topic_intel_closure:
  mode: enforce
  min_slots: 2
  max_slots: 4
  approved_by: 澤君
  approved_at: "2026-06-13"
""")
        r6 = load_topic_intel_policy(tmpdir)
        assert r6["mode"] == "enforce" and r6["enabled"], f"Case 6 failed: {r6}"
        assert r6["min_slots"] == 2 and r6["max_slots"] == 4, f"Case 6 slots: {r6}"
        print(f"Case 6 PASS: enforce 有效 → enabled, min={r6['min_slots']}, max={r6['max_slots']}")

        # Case 7: 完整有效 shadow → enabled
        _write_flag(tmpdir, """topic_intel_closure:
  mode: shadow
  min_slots: 2
  max_slots: 3
  approved_by: 澤君
  approved_at: "2026-06-13"
""")
        r7 = load_topic_intel_policy(tmpdir)
        assert r7["mode"] == "shadow" and r7["enabled"], f"Case 7 failed: {r7}"
        print(f"Case 7 PASS: shadow 有效 → enabled")

        # Case 8: 無 topic_intel_closure 區塊 → disabled
        _write_flag(tmpdir, "fishing_dm_card:\n  enabled: false\n")
        r8 = load_topic_intel_policy(tmpdir)
        assert r8["mode"] == "off" and not r8["enabled"], f"Case 8 failed: {r8}"
        print(f"Case 8 PASS: 無 topic_intel_closure 區塊 → disabled")

        # Case 9: min_slots 超上限 → invalid
        _write_flag(tmpdir, """topic_intel_closure:
  mode: enforce
  min_slots: 2
  max_slots: 10
  approved_by: 澤君
  approved_at: "2026-06-13"
""")
        r9 = load_topic_intel_policy(tmpdir)
        assert r9["mode"] == "invalid", f"Case 9 failed: {r9}"
        print(f"Case 9 PASS: max_slots=10 超上限 → invalid")

        import shutil
        shutil.rmtree(empty_dir, ignore_errors=True)

    print("\nAll cases PASS.")
