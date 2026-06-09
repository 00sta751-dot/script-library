#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_mix_parser.py — CTA / Content mix 解析器（P3 比例驗證器）2026-06-08

用途：validate_script_batch C-cta-mix / C-content-mix 使用。
      從 L2 偏好.md 的 ```kb-rule``` fenced block 解析 cta_mix / content_mix 宣告。

規格來源：_P3_ledger_v3_2026-06-08.md §C / §F / §H

公開 API：
    parse_mix_block(pref_text, category)  -> MixParseResult
    normalize_to_count(pcts, total=13)    -> list[int]   (largest-remainder)

注意：禁 import _faction_parser（保鏢 MODIFY-2：完全獨立，防交叉污染）
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Optional

import yaml as _yaml

# UTF-8 輸出防亂碼（Windows cp950）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ─────────────────────────────────────
# MixItem dataclass
# ─────────────────────────────────────
@dataclass
class MixItem:
    name: str
    target_pct: Optional[int]           # 百分比（content_mix 用）
    target_count: Optional[int]         # 件數（cta_mix 用，或 normalize_to_count 算出）
    range_min: Optional[int]            # range[0]
    range_max: Optional[int]            # range[1]
    aliases: list[str]                  # 別名清單（match 用）


# ─────────────────────────────────────
# MixParseResult dataclass（三態：宣告 / 缺欄 / provisional）
# ─────────────────────────────────────
@dataclass
class MixParseResult:
    found: bool                         # 找到 block
    category: str                       # cta_mix | content_mix
    enforcement: str                    # hard | advisory | none
    provisional: bool                   # decision_status=proposed OR provisional=true OR enforcement!=hard
    decision_status: str                # confirmed | proposed
    approval_status: str                # owner_signed | pending_owner
    effective_from: Optional[str]       # YYYY-MM-DD cutover 日期
    tolerance_count: int                # ±N 件容忍
    match_mode: str                     # alias | exact | contains
    missing_field_policy: str           # warn | fail
    unknown_label_policy: str           # warn_waiver | fail
    source_fields: list[list[str]]      # list-path（list of list）
    fallback_fields: list[list[str]]
    items: list[MixItem]
    warnings: list[str]
    errors: list[str]


# ─────────────────────────────────────
# 工具：從 yaml list-path 取 dict 值
# ─────────────────────────────────────
def _get_by_path(data: dict, path: list[str]):
    """從 dict 按 list-path 取值，取不到回 None。"""
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


# ─────────────────────────────────────
# parse_mix_block — 主 API
# ─────────────────────────────────────
def parse_mix_block(pref_text: str, category: str) -> MixParseResult:
    """
    從偏好.md 的 ```kb-rule``` fenced block 解析指定 category（cta_mix 或 content_mix）。

    三態回傳：
    1. found=True，enforcement=hard，provisional=False → 可驗
    2. found=True，provisional=True 或 enforcement!=hard → 降 advisory，只 WARN
    3. found=False → graceful WARN，不 crash，不 FAIL
    """
    warnings: list[str] = []
    errors: list[str] = []

    # 找所有 ```kb-rule ... ``` fenced block
    blocks = re.findall(r"```kb-rule\n(.*?)```", pref_text, re.DOTALL)

    matched_block: Optional[dict] = None
    for raw in blocks:
        try:
            data = _yaml.safe_load(raw)
            if not isinstance(data, dict):
                continue
            if data.get("category") == category:
                matched_block = data
                break
        except Exception:
            continue

    # 找不到 block → graceful skip
    if matched_block is None:
        return MixParseResult(
            found=False,
            category=category,
            enforcement="none",
            provisional=False,
            decision_status="",
            approval_status="",
            effective_from=None,
            tolerance_count=1,
            match_mode="alias",
            missing_field_policy="warn",
            unknown_label_policy="warn_waiver",
            source_fields=[],
            fallback_fields=[],
            items=[],
            warnings=[f"偏好.md 無 category={category} 的 kb-rule block，SKIP"],
            errors=[],
        )

    # 解析欄位
    enforcement = str(matched_block.get("enforcement", "advisory"))
    decision_status = str(matched_block.get("decision_status", "confirmed"))
    approval_status = str(matched_block.get("approval_status", "owner_signed"))
    # 防呆（P3 三審 2026-06-08 御史修）：明確解析 "false"/"0"/"" 字串為 False
    _raw_provisional = matched_block.get("provisional", False)
    if isinstance(_raw_provisional, str):
        provisional_flag = _raw_provisional.strip().lower() not in ("false", "0", "", "no")
    else:
        provisional_flag = bool(_raw_provisional)

    # 保鏢 MODIFY-1：讀結構化欄判斷是否降 advisory
    # decision_status=proposed OR provisional=true OR enforcement!=hard → 一律降 advisory
    is_provisional = (
        provisional_flag
        or decision_status == "proposed"
        or enforcement not in ("hard", "advisory", "none")
        or (enforcement != "hard" and enforcement != "none")
    )
    # 修正：enforcement=advisory 本來就不硬驗，enforcement=none 是 SKIP
    # provisional 判定：decision_status=proposed OR provisional:true → 降 advisory（即使 enforcement=hard 也降）
    is_provisional = provisional_flag or (decision_status == "proposed")

    effective_from = matched_block.get("effective_from")
    if effective_from is not None:
        effective_from = str(effective_from)

    tolerance_count = int(matched_block.get("tolerance_count", 1))
    match_mode = str(matched_block.get("match_mode", "alias"))
    missing_field_policy = str(matched_block.get("missing_field_policy", "warn"))
    unknown_label_policy = str(matched_block.get("unknown_label_policy", "warn_waiver"))

    # source_fields：list of list-path（§C schema）
    raw_sf = matched_block.get("source_fields", [])
    source_fields: list[list[str]] = []
    if isinstance(raw_sf, list):
        for sf in raw_sf:
            if isinstance(sf, list):
                source_fields.append([str(x) for x in sf])
            elif isinstance(sf, str):
                # 兼容舊式 dot-path 字串（拆成 list）
                source_fields.append(sf.split("."))

    raw_ff = matched_block.get("fallback_fields", [])
    fallback_fields: list[list[str]] = []
    if isinstance(raw_ff, list):
        for ff in raw_ff:
            if isinstance(ff, list):
                fallback_fields.append([str(x) for x in ff])
            elif isinstance(ff, str):
                fallback_fields.append(ff.split("."))

    # mix items
    raw_mix = matched_block.get("mix", [])
    items: list[MixItem] = []
    if isinstance(raw_mix, list):
        for entry in raw_mix:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", ""))
            if not name:
                continue
            target_pct = entry.get("target_pct")
            target_count = entry.get("target_count")
            raw_range = entry.get("range", [None, None])
            range_min = raw_range[0] if isinstance(raw_range, list) and len(raw_range) >= 1 else None
            range_max = raw_range[1] if isinstance(raw_range, list) and len(raw_range) >= 2 else None
            raw_aliases = entry.get("aliases", [])
            aliases = [str(a) for a in raw_aliases] if isinstance(raw_aliases, list) else []
            items.append(MixItem(
                name=name,
                target_pct=int(target_pct) if target_pct is not None else None,
                target_count=int(target_count) if target_count is not None else None,
                range_min=int(range_min) if range_min is not None else None,
                range_max=int(range_max) if range_max is not None else None,
                aliases=aliases,
            ))

    if not items:
        warnings.append(f"kb-rule category={category} 的 mix 清單為空或無法解析")

    return MixParseResult(
        found=True,
        category=category,
        enforcement=enforcement,
        provisional=is_provisional,
        decision_status=decision_status,
        approval_status=approval_status,
        effective_from=effective_from,
        tolerance_count=tolerance_count,
        match_mode=match_mode,
        missing_field_policy=missing_field_policy,
        unknown_label_policy=unknown_label_policy,
        source_fields=source_fields,
        fallback_fields=fallback_fields,
        items=items,
        warnings=warnings,
        errors=errors,
    )


# ─────────────────────────────────────
# normalize_to_count — 百分比轉件數（largest-remainder）
# ─────────────────────────────────────
def normalize_to_count(pcts: list[float | int], total: int = 13) -> list[int]:
    """
    將百分比列表轉換為件數（largest-remainder 算法）。

    算法（§H-3 Codex r4 定死）：
    1. raw_i = pct_i / 100 * total
    2. base_i = floor(raw_i)
    3. 剩餘名額 R = total - Σbase
    4. 按 remainder_i = raw_i - base_i 由大到小分配 +1，共 R 個；tie 依原始順序

    範例：溫蒂 30/30/20/20 → 美容4/營養4/成長3/生活2（=13）

    邊界防呆（P3 三審 2026-06-08 御史修）：
    - pcts 總和 = 0 → 回全零（不 crash）
    - pcts 總和 ≠ 100（如 90 / 110）→ 記 warning，best-effort 跑完不 crash
    - R > len(bases)（例：total 很大 + 全 0 pcts）→ clamp R，不 IndexError
    - R < 0（pcts 過大）→ 截斷到 total，不 crash
    """
    import math
    import warnings as _warnings

    if not pcts:
        return []

    pct_sum = sum(pcts)
    if pct_sum == 0:
        # 全 0 → 回全零，不 crash
        _warnings.warn(
            f"normalize_to_count: pcts 總和 = 0，回全零（best-effort）",
            stacklevel=2,
        )
        return [0] * len(pcts)

    if abs(pct_sum - 100) > 0.5:  # 容忍 float 誤差
        _warnings.warn(
            f"normalize_to_count: pcts 總和 = {pct_sum}（≠100），best-effort 跑完",
            stacklevel=2,
        )

    raws = [p / 100.0 * total for p in pcts]
    bases = [math.floor(r) for r in raws]
    remainders = [r - b for r, b in zip(raws, bases)]

    R = total - sum(bases)
    if R < 0:
        # 超過 total（罕見，強制截斷）
        return bases[:total] if len(bases) >= total else bases

    # clamp R：不可超過可分配的 slot 數（防 IndexError）
    R = min(R, len(bases))

    # 按 remainder 由大到小排序，tie 依原始 index（穩定排序）
    order = sorted(range(len(remainders)), key=lambda i: (-remainders[i], i))

    result = list(bases)
    for i in range(R):
        result[order[i]] += 1

    return result


# ─────────────────────────────────────
# resolve_label — 標籤解析（alias 對齊）
# ─────────────────────────────────────
def resolve_label(label: str, items: list[MixItem]) -> Optional[str]:
    """
    將 yaml 中的標籤對應到 mix item 的 canonical name。
    先精確比對 name，再比對 aliases，回傳 canonical name；找不到回 None。
    """
    label_norm = label.strip()
    for item in items:
        if item.name == label_norm:
            return item.name
        if label_norm in item.aliases:
            return item.name
    return None


# ─────────────────────────────────────
# get_label_from_yaml — 從 yaml dict 取欄位值
# ─────────────────────────────────────
def get_label_from_yaml(data: dict, result: MixParseResult) -> Optional[str]:
    """
    從 yaml data 按 source_fields（優先）+ fallback_fields 取 label 值。
    回傳第一個非空字串，找不到回 None。

    防呆（P3 三審 2026-06-08 Codex 修）：
    fallback_fields 命中 boolean True 時（如 is_chicken_soup: true），
    不能直接 str(True) = "True" 進 unknown — 必須對應到該 fallback 路徑所在 mix item 的
    canonical name。查法：path 的末段 key 若命中某 MixItem.aliases 或 MixItem.name，
    回傳該 canonical name；找不到才 fallback 回 "True"（讓呼叫端 unknown-label-policy 處理）。
    """
    all_paths = result.source_fields + result.fallback_fields
    for path in all_paths:
        val = _get_by_path(data, path)
        if val is None:
            continue
        # boolean True 特殊處理：嘗試對應 canonical name
        if isinstance(val, bool):
            if not val:
                # False = 未命中，跳過
                continue
            # True = 命中，以 path 末段 key 比對 aliases / name
            last_key = path[-1] if path else ""
            for item in result.items:
                if last_key == item.name or last_key in item.aliases:
                    return item.name
            # 找不到 alias → 回 last_key（讓呼叫端處理）
            return last_key if last_key else None
        # 一般字串/數字
        s = str(val).strip()
        if s:
            return s
    return None


# ─────────────────────────────────────
# __main__：unit fixtures 驗收
# ─────────────────────────────────────
if __name__ == "__main__":
    PASS_COUNT = 0
    FAIL_COUNT = 0

    def fcheck(label: str, condition: bool, detail: str = ""):
        global PASS_COUNT, FAIL_COUNT
        if condition:
            print(f"  [PASS] {label}")
            PASS_COUNT += 1
        else:
            print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))
            FAIL_COUNT += 1

    print("=== _mix_parser.py unit fixtures ===\n")

    # ── Fixture 1：normalize_to_count 溫蒂 30/30/20/20 → 4/4/3/2 ──
    print("[F1] normalize_to_count 溫蒂 30/30/20/20 → 美容4/營養4/成長3/生活2")
    f1_result = normalize_to_count([30, 30, 20, 20], total=13)
    fcheck("F1 normalize_to_count", f1_result == [4, 4, 3, 2], str(f1_result))

    # ── Fixture 2：normalize_to_count 總和 = 13 ──
    print("\n[F2] normalize_to_count 總和必 = 13")
    fcheck("F2 sum=13", sum(f1_result) == 13, f"sum={sum(f1_result)}")

    # ── Fixture 3：找不到 block → found=False，graceful WARN，不 crash ──
    print("\n[F3] 偏好.md 無 cta_mix block → graceful WARN")
    no_block_md = "# 業主偏好\n\n## 第 5 章：派系偏好\n\n沒有 kb-rule block。\n"
    f3 = parse_mix_block(no_block_md, "cta_mix")
    fcheck("F3 found=False", not f3.found, str(f3.warnings))
    fcheck("F3 有 WARN 訊息", len(f3.warnings) > 0, str(f3.warnings))
    fcheck("F3 errors 空", len(f3.errors) == 0, str(f3.errors))

    # ── Fixture 4：provisional=True → is_provisional=True ──
    print("\n[F4] provisional:true → MixParseResult.provisional=True（不得 hard-FAIL）")
    provisional_md = """\
## 業主偏好

```kb-rule
id: L2.TEST.CTA_MIX
category: cta_mix
enforcement: hard
provisional: true
decision_status: confirmed
tolerance_count: 1
effective_from: "2026-06-08"
mix:
  - {name: 個人化諮詢型, target_count: 11, range: [11, 12], aliases: [諮詢型]}
  - {name: 純雞湯, target_count: 1, range: [1, 1], aliases: [雞湯型]}
```
"""
    f4 = parse_mix_block(provisional_md, "cta_mix")
    fcheck("F4 found=True", f4.found)
    fcheck("F4 provisional=True（provisional:true 覆蓋 hard）", f4.provisional, f"provisional={f4.provisional}")

    # ── Fixture 5：decision_status=proposed → provisional=True ──
    print("\n[F5] decision_status=proposed → provisional=True")
    proposed_md = """\
## 業主偏好

```kb-rule
id: L2.TEST.CTA_MIX
category: cta_mix
enforcement: hard
provisional: false
decision_status: proposed
tolerance_count: 1
mix:
  - {name: 個人化諮詢型, target_count: 11, range: [11, 12], aliases: []}
```
"""
    f5 = parse_mix_block(proposed_md, "cta_mix")
    fcheck("F5 provisional=True（decision_status=proposed）", f5.provisional, f"provisional={f5.provisional}")

    # ── Fixture 6：enforcement=advisory → found=True，enforcement=advisory ──
    print("\n[F6] enforcement=advisory → found=True，enforcement='advisory'")
    advisory_md = """\
```kb-rule
id: L2.TEST.CONTENT_MIX
category: content_mix
enforcement: advisory
provisional: false
decision_status: confirmed
tolerance_count: 1
mix:
  - {name: 生活, target_pct: 70, range: [9, 10], aliases: []}
  - {name: 房仲商業, target_pct: 30, range: [3, 4], aliases: [房仲]}
```
"""
    f6 = parse_mix_block(advisory_md, "content_mix")
    fcheck("F6 found=True", f6.found)
    fcheck("F6 enforcement=advisory", f6.enforcement == "advisory", f"enforcement={f6.enforcement}")
    fcheck("F6 provisional=False（advisory 本身非 proposed）", not f6.provisional)

    # ── Fixture 7：cutover waiver — effective_from 解析 ──
    print("\n[F7] effective_from 欄位解析")
    cutover_md = """\
```kb-rule
id: L2.TEST.CTA_MIX
category: cta_mix
enforcement: hard
provisional: false
decision_status: confirmed
effective_from: "2026-06-08"
tolerance_count: 1
mix:
  - {name: 個人化諮詢型, target_count: 11, range: [11, 12], aliases: [諮詢型]}
```
"""
    f7 = parse_mix_block(cutover_md, "cta_mix")
    fcheck("F7 effective_from 解析", f7.effective_from == "2026-06-08", f"effective_from={f7.effective_from}")

    # ── Fixture 8：source_fields 解析（list of list-path）──
    print("\n[F8] source_fields list-path 解析")
    sf_md = """\
```kb-rule
id: L2.TEST.CTA_MIX
category: cta_mix
enforcement: hard
provisional: false
decision_status: confirmed
source_fields:
  - ["schema_check", "CTA類型"]
fallback_fields:
  - ["is_chicken_soup"]
tolerance_count: 1
mix:
  - {name: 個人化諮詢型, target_count: 11, range: [11, 12], aliases: []}
```
"""
    f8 = parse_mix_block(sf_md, "cta_mix")
    fcheck("F8 source_fields 非空", len(f8.source_fields) > 0)
    fcheck("F8 source_fields[0] = ['schema_check', 'CTA類型']",
           f8.source_fields[0] == ["schema_check", "CTA類型"], str(f8.source_fields))

    # ── Fixture 9：resolve_label alias 測試 ──
    print("\n[F9] resolve_label alias 對齊")
    items_9 = [
        MixItem(name="個人化諮詢型", target_pct=None, target_count=11,
                range_min=11, range_max=12, aliases=["諮詢型", "個人諮詢"]),
        MixItem(name="純雞湯", target_pct=None, target_count=1,
                range_min=1, range_max=1, aliases=["雞湯型"]),
    ]
    fcheck("F9 alias 諮詢型 → 個人化諮詢型",
           resolve_label("諮詢型", items_9) == "個人化諮詢型")
    fcheck("F9 alias 雞湯型 → 純雞湯",
           resolve_label("雞湯型", items_9) == "純雞湯")
    fcheck("F9 unknown label → None",
           resolve_label("釣魚型", items_9) is None)

    # ── Fixture 10：get_label_from_yaml path 讀取 ──
    print("\n[F10] get_label_from_yaml source_fields 讀取")
    yaml_data_10 = {
        "schema_check": {"CTA類型": "個人化諮詢型"},
        "is_chicken_soup": False,
    }
    # MixParseResult 最小版（只用 source_fields + fallback_fields）
    result_10 = MixParseResult(
        found=True, category="cta_mix", enforcement="hard",
        provisional=False, decision_status="confirmed", approval_status="owner_signed",
        effective_from=None, tolerance_count=1, match_mode="alias",
        missing_field_policy="warn", unknown_label_policy="warn_waiver",
        source_fields=[["schema_check", "CTA類型"]],
        fallback_fields=[["is_chicken_soup"]],
        items=[], warnings=[], errors=[],
    )
    label_10 = get_label_from_yaml(yaml_data_10, result_10)
    fcheck("F10 source_fields 讀到 CTA類型", label_10 == "個人化諮詢型", f"got={label_10!r}")

    # ── Fixture 11：溫蒂 content_mix hard + 內容軸欄位 ──
    print("\n[F11] 溫蒂 content_mix hard block + 內容軸欄讀取")
    wendi_md = """\
```kb-rule
id: L2.溫蒂.CONTENT_MIX
category: content_mix
enforcement: hard
provisional: false
decision_status: confirmed
source_fields:
  - ["內容軸"]
  - ["content_axis"]
  - ["schema_check", "內容軸"]
tolerance_count: 1
mix:
  - {name: 美容, target_pct: 30, target_count: 4, range: [3, 5], aliases: [美容保養]}
  - {name: 營養, target_pct: 30, target_count: 4, range: [3, 5], aliases: [營養飲食]}
  - {name: 成長, target_pct: 20, target_count: 3, range: [2, 4], aliases: [個人成長]}
  - {name: 生活, target_pct: 20, target_count: 2, range: [1, 3], aliases: [生活日常]}
```
"""
    f11 = parse_mix_block(wendi_md, "content_mix")
    fcheck("F11 溫蒂 content_mix found=True", f11.found)
    fcheck("F11 enforcement=hard", f11.enforcement == "hard", f"enforcement={f11.enforcement}")
    fcheck("F11 provisional=False", not f11.provisional)
    fcheck("F11 items 數量=4", len(f11.items) == 4, f"items={len(f11.items)}")
    fcheck("F11 source_fields 含 ['內容軸']", ["內容軸"] in f11.source_fields, str(f11.source_fields))

    wendi_yaml = {"內容軸": "美容"}
    label_11 = get_label_from_yaml(wendi_yaml, f11)
    fcheck("F11 從 yaml 讀到 內容軸=美容", label_11 == "美容", f"got={label_11!r}")

    # ── Fixture 12：normalize_to_count 邊界：全相等比例 ──
    print("\n[F12] normalize_to_count 邊界：4 等份 25/25/25/25 → total=13")
    f12_result = normalize_to_count([25, 25, 25, 25], total=13)
    fcheck("F12 sum=13", sum(f12_result) == 13, f"result={f12_result}")

    # ── Fixture 13：normalize_to_count 邊界：pcts 總和 = 90（不足 100）──
    print("\n[F13] normalize_to_count 邊界：pcts 總和 = 90，不應 crash")
    import warnings as _w
    try:
        with _w.catch_warnings(record=True) as _caught:
            _w.simplefilter("always")
            f13_result = normalize_to_count([30, 30, 20, 10], total=13)  # sum=90
        fcheck("F13 總和90 不 crash（有回傳 list）", isinstance(f13_result, list), str(f13_result))
        fcheck("F13 總和90 有 warning", any("90" in str(w.message) or "≠100" in str(w.message) for w in _caught),
               f"warnings={[str(w.message) for w in _caught]}")
    except Exception as e:
        fcheck("F13 總和90 不 crash", False, f"crashed: {e}")

    # ── Fixture 14：normalize_to_count 邊界：pcts 總和 = 110（超過 100）──
    print("\n[F14] normalize_to_count 邊界：pcts 總和 = 110，不應 crash")
    try:
        with _w.catch_warnings(record=True) as _caught14:
            _w.simplefilter("always")
            f14_result = normalize_to_count([30, 30, 30, 20], total=13)  # sum=110
        fcheck("F14 總和110 不 crash（有回傳 list）", isinstance(f14_result, list), str(f14_result))
    except Exception as e:
        fcheck("F14 總和110 不 crash", False, f"crashed: {e}")

    # ── Fixture 15：normalize_to_count 邊界：pcts 全 0（總和 = 0）──
    print("\n[F15] normalize_to_count 邊界：pcts 全 0，不應 crash，回全零")
    try:
        with _w.catch_warnings(record=True) as _caught15:
            _w.simplefilter("always")
            f15_result = normalize_to_count([0, 0, 0, 0], total=13)
        fcheck("F15 全0 不 crash（回 list）", isinstance(f15_result, list), str(f15_result))
        fcheck("F15 全0 結果全是 0", all(v == 0 for v in f15_result), str(f15_result))
    except Exception as e:
        fcheck("F15 全0 不 crash", False, f"crashed: {e}")

    # ── Fixture 16：provisional 字串 "false" 不誤判為 True ──
    print('\n[F16] provisional: "false"（字串）→ provisional=False（防 bool("false")==True）')
    str_false_md = """\
```kb-rule
id: L2.TEST.CTA_MIX
category: cta_mix
enforcement: hard
provisional: "false"
decision_status: confirmed
tolerance_count: 1
mix:
  - {name: 個人化諮詢型, target_count: 11, range: [11, 12], aliases: [諮詢型]}
```
"""
    f16 = parse_mix_block(str_false_md, "cta_mix")
    fcheck("F16 provisional 字串 'false' → False", not f16.provisional,
           f"provisional={f16.provisional}")

    # ── Fixture 17：provisional 字串 "true" 應為 True ──
    print('\n[F17] provisional: "true"（字串）→ provisional=True')
    str_true_md = """\
```kb-rule
id: L2.TEST.CTA_MIX
category: cta_mix
enforcement: hard
provisional: "true"
decision_status: confirmed
tolerance_count: 1
mix:
  - {name: 個人化諮詢型, target_count: 11, range: [11, 12], aliases: [諮詢型]}
```
"""
    f17 = parse_mix_block(str_true_md, "cta_mix")
    fcheck("F17 provisional 字串 'true' → True", f17.provisional,
           f"provisional={f17.provisional}")

    # ── Fixture 18：get_label_from_yaml boolean True → canonical name ──
    print("\n[F18] get_label_from_yaml：is_chicken_soup=True → canonical name '純雞湯'")
    items_18 = [
        MixItem(name="個人化諮詢型", target_pct=None, target_count=11,
                range_min=11, range_max=12, aliases=["諮詢型", "個人諮詢"]),
        MixItem(name="純雞湯", target_pct=None, target_count=1,
                range_min=1, range_max=1, aliases=["is_chicken_soup", "雞湯型"]),
    ]
    result_18 = MixParseResult(
        found=True, category="cta_mix", enforcement="hard",
        provisional=False, decision_status="confirmed", approval_status="owner_signed",
        effective_from=None, tolerance_count=1, match_mode="alias",
        missing_field_policy="warn", unknown_label_policy="warn_waiver",
        source_fields=[["schema_check", "CTA類型"]],
        fallback_fields=[["is_chicken_soup"]],
        items=items_18, warnings=[], errors=[],
    )
    # source_fields 無值（CTA類型 缺），fallback is_chicken_soup=True
    yaml_data_18 = {"is_chicken_soup": True}
    label_18 = get_label_from_yaml(yaml_data_18, result_18)
    fcheck("F18 bool True 命中 alias → canonical '純雞湯'", label_18 == "純雞湯",
           f"got={label_18!r}")

    # ── Fixture 19：get_label_from_yaml boolean False → skip，不回傳 "False" ──
    print("\n[F19] get_label_from_yaml：is_chicken_soup=False → None（不回 'False'）")
    yaml_data_19 = {"is_chicken_soup": False}
    label_19 = get_label_from_yaml(yaml_data_19, result_18)
    fcheck("F19 bool False → None（不誤入 unknown）", label_19 is None, f"got={label_19!r}")

    print(f"\n=== {'ALL PASS' if FAIL_COUNT == 0 else 'SOME FAIL'} ({PASS_COUNT} PASS / {FAIL_COUNT} FAIL) ===")
    sys.exit(0 if FAIL_COUNT == 0 else 1)
