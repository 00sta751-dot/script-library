#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_faction_parser.py — 共用派系解析器（第一刀 2026-06-05）

用途：topic_distributor + validate_script_batch 共用同一個 heading-based 派系 parse，
      不再各自 regex，消除「第5章/第8章矛盾」放水洞。

公開 API：
    load_l0_faction_names(sop_yaml=None) -> set[str]
    parse_faction_mix_from_headings(markdown_text, *, valid_schools=None, aliases=None) -> FactionParseResult
    normalize_to_100(ratios) -> dict[str, int]
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# UTF-8 輸出防亂碼（Windows cp950）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ─────────────────────────────────────
# L0 yaml 路徑（預設）
# ─────────────────────────────────────
_DEFAULT_SOP_YAML = Path(
    r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\L0_跨行業公版\_腳本生產SOP_v3.0.yaml"
)

# hardcoded fallback（對齊 validate_deploy 做法）
_HARDCODED_FALLBACK_SCHOOLS: frozenset[str] = frozenset({
    "直球派", "人間觀察派", "嗆辣派", "雙城合作派", "結構分析派",
    "老前輩權威派", "時事追擊派", "爆文公式派", "綜合派", "市場觀察派",
    "故事戲劇派", "自嘲反差派", "拆解派", "家人朋友模擬派",
})

# 進入派系 section 的語意關鍵字（任一命中即視為入口）
_ENTRY_KEYWORDS = re.compile(
    r"派系偏好|派系比例|主推派系|主推比例|適合.{0,6}派系"
)

# 百分比欄位 header 關鍵字（表格 header 行識別用）
_PCT_HEADER_KEYWORDS = re.compile(r"^[\s|]*(?:占比|佔比|建議比例|占比建議|適合|備註|理由|內容類型|派別|派系|合計)\s*[|\s]*$")

# 「provisional」標記語意（無正式比例，待後補）
_PROVISIONAL_KEYWORDS = re.compile(r"尚無.*批次|禁腦補|建議傾向|待算盤覆核|初步建議")

# 忽略欄位（計算用非派系名）
_IGNORED_NAMES: frozenset[str] = frozenset({"其他", "合計", "合計/其他", "不限", "小計"})


# ─────────────────────────────────────
# FactionParseResult dataclass
# ─────────────────────────────────────
@dataclass(frozen=True)
class FactionParseResult:
    canonical_ratios: dict[str, int]   # 只含 L0 14 標準名
    raw_ratios: dict[str, int]         # 原始表格名 -> %（含 unknown）
    unknown_ratios: dict[str, int]     # 有 % 但不在 L0、也沒 alias
    ignored_ratios: dict[str, int]     # 其他/合計/非派系（有%但被忽略）
    provisional: bool                  # 明標「尚無批次/待覆核/建議傾向」
    source: str                        # 第一刀固定回 "heading"
    warnings: tuple[str, ...]
    errors: tuple[str, ...]


# ─────────────────────────────────────
# load_l0_faction_names
# ─────────────────────────────────────
def load_l0_faction_names(sop_yaml: Optional[Path] = None) -> frozenset[str]:
    """
    讀 L0 _腳本生產SOP_v3.0.yaml schools.list[*].name。
    含 len>=10 合理性驗 + hardcoded fallback（對齊 validate_deploy 做法）。
    """
    target = sop_yaml or _DEFAULT_SOP_YAML
    try:
        import yaml as _yaml
        with open(target, encoding="utf-8") as f:
            data = _yaml.safe_load(f)
        names = [
            s["name"]
            for s in data.get("schools", {}).get("list", [])
            if isinstance(s.get("name"), str)
        ]
        if len(names) >= 10:
            return frozenset(names)
        # 合理性驗失敗（< 10 派）→ fallback
        return _HARDCODED_FALLBACK_SCHOOLS
    except Exception:
        return _HARDCODED_FALLBACK_SCHOOLS


# ─────────────────────────────────────
# 內部工具函式
# ─────────────────────────────────────
def _heading_level(line: str) -> int:
    """回傳 heading 層級（1-6），非 heading 回 0。"""
    m = re.match(r"^(#{1,6})\s", line)
    return len(m.group(1)) if m else 0


def _is_entry_heading(line: str) -> bool:
    """
    判斷此行是否為「派系 section 入口 heading」。
    條件：必須是實體 heading（^#{1,4}），且含語意入口關鍵字。
    不允許 TOC 行（[文字](#...)）。
    """
    if not re.match(r"^#{1,4}\s", line):
        return False
    # 排除 TOC 行（含 markdown link 語法）
    if re.search(r"\[.*\]\(#", line):
        return False
    if _ENTRY_KEYWORDS.search(line):
        return True
    return False


def _is_pct_table_header(line: str) -> bool:
    """判斷此行是否為表格 header（跳過，不抽比例）。"""
    cells = [c.strip() for c in line.split("|") if c.strip()]
    for c in cells:
        if re.search(r"占比|佔比|建議比例|占比建議|適合|備註|理由|內容類型|派別|派系|合計", c):
            return True
    return False


def _is_separator_line(line: str) -> bool:
    """判斷是否為 markdown 表格分隔行（|---|---| 等）。"""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    return bool(re.match(r"^[\s|:\-]+$", stripped))


def _extract_from_table_row(
    line: str,
    valid_schools: frozenset[str],
) -> Optional[tuple[str, int]]:
    """
    從表格行抽取 (名稱, 百分比)。
    不限「派」字尾——揭秘型/共鳴痛點型等全抓，標 unknown。
    百分比欄位：占比/佔比/建議比例 或 row 第一個 [0-9]+%。
    回傳 None 若無法抽取。
    """
    if not line.strip().startswith("|"):
        return None
    if _is_separator_line(line):
        return None

    cells = [c.strip() for c in line.split("|")]
    cells = [c for c in cells if c]  # 去掉空字串
    if len(cells) < 2:
        return None

    # 第一欄：名稱候選（去除 markdown bold **...**)
    raw_name = re.sub(r"\*{1,2}", "", cells[0]).strip()
    # 去除括號說明 (...)（）
    name = re.sub(r"[（(][^)）]*[)）]", "", raw_name).strip()
    if not name or name in ("派別", "派系", "合計", "內容類型", ""):
        return None

    # 找百分比：優先找有「%」且是純數字的欄位
    pct: Optional[int] = None
    for cell in cells[1:]:
        m = re.search(r"(\d+)%", cell)
        if m:
            pct = int(m.group(1))
            break

    if pct is None:
        return None

    return (name, pct)


def _extract_from_bullet_line(line: str) -> list[tuple[str, int]]:
    """
    從 bullet 格式行抽取多個 (名稱, 百分比) 對。
    支援阿奇型格式：
    - **主推（佔 50%）**：自嘲反差派 / 故事戲劇派 / 家人朋友模擬派
    - **替代（佔 30%）**：拆解派 / 人間觀察派
    - **少量加料（佔 20%）**：直球派 / 結構分析派
    每派均分 pct 後回傳 list。
    """
    results: list[tuple[str, int]] = []
    m = re.search(r"(?:主推|替代|少量[加料]?)[（\(]佔?\s*(\d+)%[)）].*?[:：]\s*(.+)", line)
    if m:
        pct = int(m.group(1))
        names_str = m.group(2)
        names = re.findall(r"([一-龥a-zA-Z（）_/／]+(?:派|型|系))", names_str)
        if names:
            per = pct // len(names)
            for n in names:
                clean = re.sub(r"[（(][^)）]*[)）]", "", n).strip()
                if clean:
                    results.append((clean, per))
    return results


# ─────────────────────────────────────
# parse_faction_mix_from_headings（主 API）
# ─────────────────────────────────────
def parse_faction_mix_from_headings(
    markdown_text: str,
    *,
    valid_schools: Optional[frozenset[str]] = None,
    aliases: Optional[dict[str, str]] = None,
) -> FactionParseResult:
    """
    從 markdown 偏好.md 文字中，找「派系偏好/比例」section，
    抽取表格行中的 名稱 + 百分比。

    規格（施作規格 §2）：
    - 只認實體 heading ^#{1,4}\\s+（避免 TOC）
    - 入口語意：派系偏好/派系比例/主推派系/主推比例/適合.*派系
    - 章號（§5/§8/第5章/第8章/5.x/8.x）只當輔助、不依賴
    - 退出：入口 ## 第5章 → 吃到下一個同級 ##；入口 ### 5.2 → 吃到下一個 ### 或更高層
    - 表格抽取不限「派」字尾：揭秘型/共鳴痛點型/純雞湯療癒型全抓，標 unknown
    - 百分比欄位：占比/佔比/建議比例 或 row 第一個 \\d+%
    """
    if valid_schools is None:
        valid_schools = load_l0_faction_names()
    if aliases is None:
        aliases = {}

    lines = markdown_text.splitlines()
    warnings: list[str] = []
    errors: list[str] = []

    # --- Section 掃描 ---
    # 找所有入口 heading，取第一個
    entry_line_idx: Optional[int] = None
    entry_level: int = 0
    for i, line in enumerate(lines):
        if _is_entry_heading(line):
            entry_line_idx = i
            entry_level = _heading_level(line)
            break

    if entry_line_idx is None:
        # 找不到入口 heading
        return FactionParseResult(
            canonical_ratios={},
            raw_ratios={},
            unknown_ratios={},
            ignored_ratios={},
            provisional=False,
            source="heading",
            warnings=tuple(warnings + ["找不到派系偏好/比例 section heading"]),
            errors=tuple(errors),
        )

    # 收集 section 內容（直到下一個同級或更高層 heading）
    section_lines: list[str] = []
    for i in range(entry_line_idx + 1, len(lines)):
        line = lines[i]
        lvl = _heading_level(line)
        if lvl > 0 and lvl <= entry_level:
            # 遇到同級或更高層 heading → 結束 section
            break
        section_lines.append(line)

    # 偵測 provisional keyword（只掃 section 內）。Codex P1-5 修（2026-06-05）：
    # 只記 keyword 是否出現，實際 provisional 判定移到「抽完比例後」（return 前）——
    # 有比例表（raw_ratios 非空）→ 不判 provisional（用比例）；無比例 + keyword 才 provisional。
    # 修因：偏好 section 常含禁區/慎用規則（禁腦補虛構客戶）或說明文字（初步建議傾向），
    # 這些非「比例未定」訊號，不該讓有比例表的業主被誤判 provisional 回空（仲豪/詩婷 2026-06-05 踩到）。
    _provisional_kw = any(_PROVISIONAL_KEYWORDS.search(l) for l in section_lines)

    # --- 在 section 內找子 heading，取「主推比例」相關的最佳子 section ---
    # 只找明確含「主推比例/主推派系/主推（比例）」的子 heading（不含「搭配偏好」等衍生 heading）
    sub_entry_idx: Optional[int] = None
    sub_entry_level: int = 0
    for i, line in enumerate(section_lines):
        lvl = _heading_level(line)
        # 只找明確含「主推比例/比例/主推（含%）」的子 heading，不含「主推派系/搭配偏好」
        if lvl > 0 and re.search(r"主推.{0,4}比例|^\#{1,4}\s+[\d.]*\s*(?:比例|派系比例|流派比例)", line):
            sub_entry_idx = i
            sub_entry_level = lvl
            break

    # 若找到明確「主推比例」子 heading，只在子 section 內抽表格
    if sub_entry_idx is not None:
        table_lines: list[str] = []
        for i in range(sub_entry_idx + 1, len(section_lines)):
            line = section_lines[i]
            lvl = _heading_level(line)
            if lvl > 0 and lvl <= sub_entry_level:
                break
            table_lines.append(line)
    else:
        # 整個 section 全部掃（昀臻「5.1 適合昀臻的派系」不含主推/比例關鍵字，走全掃）
        table_lines = section_lines

    # --- 抽表格行 + bullet line ---
    raw_ratios: dict[str, int] = {}
    skip_header_done = False

    for line in table_lines:
        if _is_separator_line(line):
            continue
        if not skip_header_done and _is_pct_table_header(line):
            skip_header_done = True
            continue

        # 表格行優先
        result = _extract_from_table_row(line, valid_schools)
        if result is not None:
            name, pct = result
            if name not in raw_ratios:
                raw_ratios[name] = pct
            continue

        # bullet 格式（阿奇型：主推（佔50%）：派A / 派B）
        bullet_results = _extract_from_bullet_line(line)
        for name, pct in bullet_results:
            if name not in raw_ratios:
                raw_ratios[name] = pct

    # --- 分流：canonical / unknown / ignored ---
    canonical_ratios: dict[str, int] = {}
    unknown_ratios: dict[str, int] = {}
    ignored_ratios: dict[str, int] = {}

    for name, pct in raw_ratios.items():
        # alias 解析
        resolved = aliases.get(name, name)
        if resolved in _IGNORED_NAMES or name in _IGNORED_NAMES:
            ignored_ratios[name] = pct
        elif resolved in valid_schools:
            canonical_ratios[resolved] = pct
        else:
            # 未知（不在 L0 也沒 alias）→ unknown，不靜默丟
            unknown_ratios[name] = pct

    # Codex P1-5 修：有比例表（raw_ratios 非空）→ 不 provisional（用比例）；無比例 + keyword 才 provisional
    provisional = _provisional_kw and not raw_ratios

    return FactionParseResult(
        canonical_ratios=canonical_ratios,
        raw_ratios=dict(raw_ratios),
        unknown_ratios=unknown_ratios,
        ignored_ratios=ignored_ratios,
        provisional=provisional,
        source="heading",
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


# ─────────────────────────────────────
# normalize_to_100
# ─────────────────────────────────────
def normalize_to_100(ratios: dict[str, int]) -> dict[str, int]:
    """
    將 ratios 正規化到總和 100%（四捨五入，誤差補給最大值）。
    輸入空 dict 回傳空 dict。
    """
    if not ratios:
        return {}
    total = sum(ratios.values())
    if total == 0:
        return dict(ratios)
    if total == 100:
        return dict(ratios)
    factor = 100 / total
    normalized = {k: max(1, round(v * factor)) for k, v in ratios.items()}
    diff = 100 - sum(normalized.values())
    if diff != 0:
        top_key = max(normalized, key=lambda k: normalized[k])
        normalized[top_key] = max(1, normalized[top_key] + diff)
    return normalized


# ─────────────────────────────────────
# __main__：unit fixtures 驗收
# ─────────────────────────────────────
if __name__ == "__main__":
    import json

    valid = load_l0_faction_names()
    print(f"[OK] load_l0_faction_names: {len(valid)} 派")

    # --- Fixture 1：瑞祥（第5章，3 標準派，有%）---
    ruixiang_md = """\
## 第 5 章：派系偏好

### 5.1 已驗證使用過的派系

從 13 批推算，瑞祥用過：直球派、人間觀察派...

### 5.2 主推派系（30 天衝刺）

| 派別 | 適合平台 | 占比 | 備註 |
|------|---------|------|------|
| **嗆辣派** | TikTok / Threads | 50% | 最強完播 |
| **人間觀察派** | IG / FB Reels | 30% | 共鳴度高 |
| **市場觀察派** | 全平台 | 20% | 學 Ryan Serhant |

### 5.3 禁用 / 慎用派系
"""
    r1 = parse_faction_mix_from_headings(ruixiang_md, valid_schools=valid)
    expected_r1 = {"嗆辣派": 50, "人間觀察派": 30, "市場觀察派": 20}
    ok1 = r1.canonical_ratios == expected_r1 and not r1.unknown_ratios and not r1.provisional
    print(f"[{'OK' if ok1 else 'FAIL'}] Fixture 瑞祥: canonical={r1.canonical_ratios} unknown={r1.unknown_ratios} provisional={r1.provisional}")

    # --- Fixture 2：昀臻（第5章，4 標準派，有%）---
    yun_md = """\
## 第 5 章：派系偏好

### 5.2 主推比例

| 派別 | 占比 |
|------|------|
| **人間觀察派** | 35% |
| **故事戲劇派** | 20% |
| **直球派** | 30% |
| **市場觀察派** | 15% |
"""
    r2 = parse_faction_mix_from_headings(yun_md, valid_schools=valid)
    expected_r2 = {"人間觀察派": 35, "故事戲劇派": 20, "直球派": 30, "市場觀察派": 15}
    ok2 = r2.canonical_ratios == expected_r2 and not r2.unknown_ratios
    print(f"[{'OK' if ok2 else 'FAIL'}] Fixture 昀臻: canonical={r2.canonical_ratios} unknown={r2.unknown_ratios}")

    # --- Fixture 3：仲豪（第5章，有 unknown，不得 normalize 成靜默通過）---
    zhonghao_md = """\
## 第 5 章：派系偏好

### 5.2 主推比例（算盤覆核版）

> ⚠️ 以下比例為算盤覆核確認值（36/27/36/1）

| 派別 | 佔比 | 備註 |
|------|------|------|
| **直球派**（教學揭秘）| 36% | 最強牌 |
| **揭秘型**（屋主問題反常識）| 27% | 過戶範本 |
| **共鳴/痛點型**（人間觀察）| 36% | 生活主力 |
| **其他**（純雞湯/生日等）| 1% | 強制位 |
"""
    r3 = parse_faction_mix_from_headings(zhonghao_md, valid_schools=valid)
    ok3 = (
        r3.canonical_ratios.get("直球派") == 36
        and "揭秘型" in r3.unknown_ratios
        and "共鳴/痛點型" in r3.unknown_ratios
        and "其他" in r3.ignored_ratios
        and not r3.provisional
    )
    print(f"[{'OK' if ok3 else 'FAIL'}] Fixture 仲豪: canonical={r3.canonical_ratios} unknown={r3.unknown_ratios} ignored={r3.ignored_ratios}")

    # --- Fixture 4：詩婷（provisional=True，無%）---
    shiting_md = """\
## 第 5 章：派系偏好

> ⚠️ 詩婷尚無腳本批次，以下為「初步建議傾向」，非算盤覆核確認值。
> 禁腦補寫死比例 — 第一批前一律標「建議傾向」。

### 5.1 初步建議主推傾向

| 派別 | 建議傾向 | 備註 |
|------|------|------|
| **共鳴/痛點型（人間觀察）** | 主力傾向 | 驗證 |
| **故事/成長型（真實日記）** | 主力傾向 | 方向A |
"""
    r4 = parse_faction_mix_from_headings(shiting_md, valid_schools=valid)
    ok4 = r4.provisional and len(r4.canonical_ratios) == 0
    print(f"[{'OK' if ok4 else 'FAIL'}] Fixture 詩婷: provisional={r4.provisional} canonical={r4.canonical_ratios}")

    # --- Fixture 5：TOC 假命中 → 不進 section ---
    toc_md = """\
# 目錄

- [第5章：派系偏好](#第5章派系偏好)
- [第6章：CTA](#第6章cta)

## 第 6 章：CTA
"""
    r5 = parse_faction_mix_from_headings(toc_md, valid_schools=valid)
    ok5 = len(r5.canonical_ratios) == 0 and len(r5.unknown_ratios) == 0
    print(f"[{'OK' if ok5 else 'FAIL'}] Fixture TOC假命中: canonical={r5.canonical_ratios} warnings={r5.warnings}")

    # --- Fixture 6：normalize_to_100 ---
    n1 = normalize_to_100({"嗆辣派": 36, "人間觀察派": 27, "市場觀察派": 36})
    total_n1 = sum(n1.values())
    ok6 = total_n1 == 100
    print(f"[{'OK' if ok6 else 'FAIL'}] normalize_to_100: {n1} total={total_n1}")

    all_ok = all([ok1, ok2, ok3, ok4, ok5, ok6])
    print(f"\n=== {'ALL PASS' if all_ok else 'SOME FAIL'} ===")
    sys.exit(0 if all_ok else 1)
