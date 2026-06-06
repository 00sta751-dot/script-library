#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_identity_parser.py — 雙身份比例解析器（第二刀 2026-06-05）

用途：topic_distributor + validate_script_batch 共用同一個 heading-based 雙身份比例 parse，
      修 C-012 no-op 放水洞（TOC 假命中 + ## break 過早）。

公開 API：
    parse_identity_mix_from_headings(markdown_text) -> IdentityParseResult

注意：
- 不繼承 _faction_parser 派系語意/白名單（雙身份無 L0 schema 白名單）
- 內容類型名本身是值（無需白名單分流）
- normalize：抽取後 strip 全形/半形括號 + trim
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

# UTF-8 輸出防亂碼（Windows cp950）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ─────────────────────────────────────
# IdentityParseResult dataclass
# ─────────────────────────────────────
@dataclass(frozen=True)
class IdentityParseResult:
    ratios: dict      # 內容類型名（normalize 後）→ % （無白名單分流，名稱本身是值）
    source: str       # 固定回 "heading"
    warnings: tuple   # 警告訊息
    errors: tuple     # 錯誤訊息


# ─────────────────────────────────────
# 入口 heading 語意關鍵字
# ─────────────────────────────────────
_ENTRY_KEYWORDS = re.compile(r"雙身份比例|內容類型比例")

# 表格 header 跳過列（內容類型/建議比例/理由/--- 開頭）
_HEADER_CELLS = frozenset({"內容類型", "建議比例", "理由"})


def _normalize_label(name: str) -> str:
    """normalize：strip 全形/半形括號說明 + trim"""
    return re.sub(r"（[^）]*）|\([^)]*\)", "", name).strip()


# ─────────────────────────────────────
# 內部工具函式
# ─────────────────────────────────────
def _heading_level(line: str) -> int:
    """回傳 heading 層級（1-6），非 heading 回 0。"""
    m = re.match(r"^(#{1,6})\s", line)
    return len(m.group(1)) if m else 0


def _is_entry_heading(line: str) -> bool:
    """
    判斷此行是否為「雙身份比例 section 入口 heading」。
    條件：必須是實體 heading（^#{1,4}），且含語意入口關鍵字。
    排除 TOC 行（含 markdown link 語法 [文字](#...)）。
    """
    if not re.match(r"^#{1,4}\s", line):
        return False
    # 排除 TOC 行
    if re.search(r"\[.*\]\(#", line):
        return False
    return bool(_ENTRY_KEYWORDS.search(line))


def _is_separator_line(line: str) -> bool:
    """判斷是否為 markdown 表格分隔行（|---|---| 等）。"""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    return bool(re.match(r"^[\s|:\-]+$", stripped))


def _is_table_header(line: str) -> bool:
    """判斷此行是否為表格 header（跳過，不抽比例）。"""
    if not line.strip().startswith("|"):
        return False
    cells = [c.strip() for c in line.split("|") if c.strip()]
    for c in cells:
        if c in _HEADER_CELLS:
            return True
    return False


def _extract_table_row(line: str):
    """
    從表格行抽取 (原始名稱, 百分比)。
    格式：| 內容類型 | 建議比例 | 理由 |
    回傳 None 若無法抽取。
    """
    if not line.strip().startswith("|"):
        return None
    if _is_separator_line(line):
        return None

    cells = [c.strip() for c in line.split("|")]
    cells = [c for c in cells if c]  # 去空字串
    if len(cells) < 2:
        return None

    # 第一欄：名稱（去 markdown bold **...**）
    raw_name = re.sub(r"\*{1,2}", "", cells[0]).strip()
    if not raw_name:
        return None

    # 找百分比
    pct = None
    for cell in cells[1:]:
        m = re.search(r"(\d+)%", cell)
        if m:
            pct = int(m.group(1))
            break

    if pct is None:
        return None

    return (raw_name, pct)


# ─────────────────────────────────────
# parse_identity_mix_from_headings（主 API）
# ─────────────────────────────────────
def parse_identity_mix_from_headings(markdown_text: str) -> IdentityParseResult:
    """
    從 markdown 偏好.md 文字中，找「雙身份比例/內容類型比例」section，
    抽取表格行中的 名稱 + 百分比。

    規格（施作規格 §2 動1）：
    - 只認實體 heading ^#{1,4}\\s+（避免 TOC 假命中）
    - 入口語意：雙身份比例 / 內容類型比例
    - 章號（第3章等）只當參考、不依賴（heading-based，不靠章號）
    - 退出：進入 section 後，遇到同級或更高層 heading → 結束
    - 表格抽取：不限白名單（內容類型名本身是值）
    - normalize：strip 全形/半形括號 + trim（「餐飲（胖奇熱狗堡）」→「餐飲」）
    """
    lines = markdown_text.splitlines()
    warnings: list = []
    errors: list = []

    # --- 找入口 heading（第一個命中的實體 heading）---
    entry_line_idx = None
    entry_level = 0
    for i, line in enumerate(lines):
        if _is_entry_heading(line):
            entry_line_idx = i
            entry_level = _heading_level(line)
            break

    if entry_line_idx is None:
        return IdentityParseResult(
            ratios={},
            source="heading",
            warnings=tuple(["找不到雙身份比例/內容類型比例 section heading"]),
            errors=tuple(errors),
        )

    # --- 收集 section 內容（直到同級或更高層 heading）---
    section_lines: list = []
    for i in range(entry_line_idx + 1, len(lines)):
        line = lines[i]
        lvl = _heading_level(line)
        if lvl > 0 and lvl <= entry_level:
            # 遇到同級或更高層 heading → 結束 section
            break
        section_lines.append(line)

    # --- 抽表格行 ---
    raw_ratios: dict = {}
    header_skipped = False

    for line in section_lines:
        if _is_separator_line(line):
            continue
        if not header_skipped and _is_table_header(line):
            header_skipped = True
            continue

        result = _extract_table_row(line)
        if result is not None:
            raw_name, pct = result
            # normalize：strip 括號 + trim
            norm_name = _normalize_label(raw_name)
            if norm_name and norm_name not in raw_ratios:
                raw_ratios[norm_name] = pct

    return IdentityParseResult(
        ratios=dict(raw_ratios),
        source="heading",
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


# ─────────────────────────────────────
# __main__：unit fixtures 驗收
# ─────────────────────────────────────
if __name__ == "__main__":
    import sys

    # --- Fixture 1：阿奇偏好.md 格式（含全形括號描述，normalize 後去掉）---
    achi_md = """\
## 完整目錄

- [第 3 章：雙身份比例](#第-3-章雙身份比例)
- [第 4 章：禁區](#第-4-章禁區)

## 第 3 章：雙身份比例（霸告建議）

| 內容類型 | 建議比例 | 理由 |
|---|---|---|
| 生活 / 觀點 / 個人故事 | 50% | 主力 |
| 餐飲（胖奇熱狗堡）| 30% | 主軸事業 |
| 房仲 | 15% | 副業 |
| 開箱 | 5% | 少量 |

## 第 4 章：禁區
"""
    r1 = parse_identity_mix_from_headings(achi_md)
    expected_r1 = {
        "生活 / 觀點 / 個人故事": 50,
        "餐飲": 30,
        "房仲": 15,
        "開箱": 5,
    }
    ok1 = r1.ratios == expected_r1 and not r1.errors
    print(f"[{'OK' if ok1 else 'FAIL'}] Fixture 1 阿奇 normalize: ratios={r1.ratios}")
    if not ok1:
        print(f"  expected={expected_r1}")

    # --- Fixture 2：TOC 假命中（不進 section，回空）---
    toc_md = """\
# 目錄

- [第 3 章：雙身份比例](#第-3-章雙身份比例)
- [第 4 章：禁區](#第-4-章禁區)

## 第 4 章：禁區

一些禁區內容
"""
    r2 = parse_identity_mix_from_headings(toc_md)
    ok2 = r2.ratios == {} and len(r2.warnings) > 0
    print(f"[{'OK' if ok2 else 'FAIL'}] Fixture 2 TOC假命中: ratios={r2.ratios} warnings={r2.warnings}")

    # --- Fixture 3：下一章 heading 停止 ---
    stop_md = """\
## 第 3 章：雙身份比例

| 內容類型 | 建議比例 | 理由 |
|---|---|---|
| 生活 | 60% | 主力 |
| 餐飲 | 40% | 輔助 |

## 第 4 章：禁區

| 內容類型 | 建議比例 | 理由 |
|---|---|---|
| 禁區測試 | 5% | 不該被抓 |
"""
    r3 = parse_identity_mix_from_headings(stop_md)
    ok3 = r3.ratios == {"生活": 60, "餐飲": 40} and "禁區測試" not in r3.ratios
    print(f"[{'OK' if ok3 else 'FAIL'}] Fixture 3 下一章停止: ratios={r3.ratios}")

    # --- Fixture 4：無雙身份章（單行業偏好，只有人物設定）→ 回空 ---
    single_md = """\
## 第 3 章：人物設定

| 項目 | 設定 |
|---|---|
| 名字 | 瑞祥 |
| 職業 | 房仲 |
"""
    r4 = parse_identity_mix_from_headings(single_md)
    ok4 = r4.ratios == {}
    print(f"[{'OK' if ok4 else 'FAIL'}] Fixture 4 單行業無雙身份章: ratios={r4.ratios} warnings={r4.warnings}")

    # --- Fixture 5：內容類型比例 keyword 也認 ---
    alt_keyword_md = """\
## 第 3 章：內容類型比例

| 內容類型 | 建議比例 | 理由 |
|---|---|---|
| 教育 | 70% | 主力 |
| 生活 | 30% | 輔助 |
"""
    r5 = parse_identity_mix_from_headings(alt_keyword_md)
    ok5 = r5.ratios == {"教育": 70, "生活": 30}
    print(f"[{'OK' if ok5 else 'FAIL'}] Fixture 5 內容類型比例keyword: ratios={r5.ratios}")

    all_ok = all([ok1, ok2, ok3, ok4, ok5])
    print(f"\n=== {'ALL PASS' if all_ok else 'SOME FAIL'} ===")
    sys.exit(0 if all_ok else 1)
