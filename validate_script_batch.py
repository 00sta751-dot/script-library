#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_script_batch.py — 腳本批次品管員（15 件自動擋）
對齊 SOP _腳本生產SOP_v3.0.yaml §11 9 件 + §14 §15 + guardian 補 6 件

用法：
  python validate_script_batch.py --owner 阿奇 --batch-dir <絕對路徑>
  python validate_script_batch.py --owner 阿奇 --batch-dir <絕對路徑> --strict
  python validate_script_batch.py --batch-dir <路徑>  # owner 從 yaml frontmatter 自動偵測

PASS → exit 0 / FAIL → exit 1（--strict 模式 / 任一 FAIL）

建檔：2026-05-22 / 對齊 SOP §11 L1-001 ~ L1-009 + guardian 補 6 件 C-010 ~ C-015
"""

import sys
import os
import re
import argparse
import yaml
from pathlib import Path
from typing import Any, Optional

# UTF-8 輸出防亂碼（Windows cp950）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ── 業主偏好.md 路徑表（動態 lookup，不硬寫比例數字）──
L2_BASE = Path(r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\L2_業主層")

OWNER_PREF_PATHS = {
    "瑞祥":     L2_BASE / "房仲_瑞祥"    / "00_業主核心檔" / "source_overlay" / "_瑞祥偏好.md",
    "仲豪":     L2_BASE / "房仲_仲豪"    / "00_業主核心檔" / "source_overlay" / "_仲豪偏好.md",
    "昀臻":     L2_BASE / "美容_昀臻"    / "00_業主核心檔" / "source_overlay" / "_昀臻偏好.md",
    "叭噗_小C": L2_BASE / "情侶_叭噗_小C" / "00_業主核心檔" / "source_overlay" / "_叭噗_小C偏好.md",
    "阿奇":     L2_BASE / "餐飲_阿奇"    / "00_業主核心檔" / "source_overlay" / "_阿奇偏好.md",
}

# ── 禁用詞（SOP §11 L1-002）──
BANNED_WORDS = ["應該", "大概", "可能", "差不多", "基本上", "我猜"]

# ── 翠文混入畫面描述的告警關鍵詞（C-010）──
SCENE_DESC_KEYWORDS = ["鏡頭", "角度", "構圖", "B-roll", "特寫", "俯拍", "仰拍", "推鏡", "拉鏡", "搖鏡"]

# ── 段落 timestamp 必要 type 清單（SOP §11 L1-001）──
EXPECTED_TYPES = {"Hook", "破題", "核心論述", "案例轉折", "收束金句", "CTA", "收尾（純雞湯無CTA）"}

# ────────────────────────────────────────────
# 讀 yaml（跳 .bak 檔）
# ────────────────────────────────────────────
def load_yamls(batch_dir: Path) -> list[tuple[Path, dict]]:
    results = []
    for f in sorted(batch_dir.glob("*.yaml")):
        if ".bak" in f.name:
            continue
        try:
            text = f.read_text(encoding="utf-8")
            # 移掉 --- frontmatter markers
            text = re.sub(r"^---\s*\n", "", text, count=1)
            text = re.sub(r"\n---\s*$", "", text)
            data = yaml.safe_load(text)
            # 修 3（P1）：空 YAML / None / list / scalar → 標 __schema_error__，嚴禁靜默 skip
            if data is None or data == "" or data == {}:
                results.append((f, {"__schema_error__": f"YAML 為空（None/empty）：{f.name}"}))
            elif not isinstance(data, dict):
                results.append((f, {"__schema_error__": f"YAML top-level 不是 dict（實際型別：{type(data).__name__}）：{f.name}"}))
            else:
                results.append((f, data))
        except Exception as e:
            results.append((f, {"__parse_error__": str(e)}))
    return results

# ────────────────────────────────────────────
# 讀業主偏好.md — 抓 §8 派系比例文字
# ────────────────────────────────────────────
def load_pref_md(owner: str) -> Optional[str]:
    path = OWNER_PREF_PATHS.get(owner)
    if path and path.exists():
        return path.read_text(encoding="utf-8")
    return None

def parse_schema_distribution(pref_text: str, section_header: str) -> dict[str, int]:
    """從偏好.md 段落裡抓 '派系名 XX%' 格式"""
    dist = {}
    in_section = False
    for line in pref_text.splitlines():
        if section_header in line:
            in_section = True
            continue
        if in_section:
            if line.startswith("##"):  # 遇到下一節 stop
                break
            m = re.search(r"([一-龥a-zA-Z（）_]+派)\s*[（(]?[^)）]*[)）]?\s*[｜|]?\s*建議比例[^|]*[|｜]\s*(\d+)%", line)
            if m:
                dist[m.group(1)] = int(m.group(2))
            # 也抓「主推（佔 50%）」這種表格行外的純文字
            m2 = re.search(r"([一-龥a-zA-Z（）_]+派)[^%\d]*?[佔占]*\s*(\d+)%", line)
            if m2:
                name = m2.group(1)
                if name not in dist:
                    dist[name] = int(m2.group(2))
    return dist

def parse_identity_distribution(pref_text: str) -> dict[str, int]:
    """從偏好.md 第 3 章雙身份比例抓 '身份類型 XX%'"""
    dist = {}
    in_section = False
    for line in pref_text.splitlines():
        if "第 3 章" in line or "雙身份比例" in line:
            in_section = True
            continue
        if in_section:
            if line.startswith("##"):
                break
            m = re.search(r"\|\s*([^|]+?)\s*\|\s*(\d+)%", line)
            if m:
                label = m.group(1).strip()
                if label and label != "內容類型" and label != "建議比例" and label != "理由":
                    dist[label] = int(m.group(2))
    return dist

# ────────────────────────────────────────────
# 取翠文欄位值（在 scenes 每段的 "翠文" key）
# ────────────────────────────────────────────
def get_scenes(data: dict) -> list[dict]:
    return data.get("scenes", []) or []

def get_field_text(data: dict, *keys) -> str:
    """遞迴取 nested key，回傳合併字串"""
    parts = []
    for k in keys:
        v = data.get(k)
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend([str(x) for x in v])
        elif isinstance(v, dict):
            parts.extend([str(x) for x in v.values()])
    return " ".join(parts)

def _get_all_dialogue(scene: dict) -> list[str]:
    """修 2（P1）：收集 scene 裡所有 '台詞_*' key 的值。
    相容 5 業主：台詞_瑞祥 / 台詞_仲豪 / 台詞_昀臻 / 台詞_叭噗 / 台詞_小C / 台詞_阿奇 等。
    同時也取無前綴的 '台詞' 欄位（老版相容）。
    """
    parts = []
    # 優先收集所有 台詞_* 欄位（5 業主皆適用）
    for k, v in scene.items():
        if k.startswith("台詞_") and v:
            parts.append(str(v))
    # 相容無前綴的舊式 '台詞' 欄位
    fallback = scene.get("台詞", "")
    if fallback and not parts:  # 只有在沒有 台詞_* 時才 fallback
        parts.append(str(fallback))
    return parts

def get_all_text(data: dict) -> str:
    """取腳本全文（台詞 + 翠文）— 使用 _get_all_dialogue 涵蓋 5 業主所有台詞欄位"""
    parts = []
    for scene in get_scenes(data):
        parts.extend(_get_all_dialogue(scene))
        cuiwen = scene.get("翠文", "")
        if cuiwen:
            parts.append(str(cuiwen))
    parts.append(data.get("title", ""))
    parts.append(data.get("caption", ""))
    return " ".join(parts)

# ────────────────────────────────────────────
# 15 件 check 函式（逐一回傳 (PASS/FAIL/WARN, detail)）
# ────────────────────────────────────────────

def chk_l1_001_schema(data: dict, fname: str) -> tuple[str, str]:
    """L1-001：schema 對齊 — 6 段時間軸完整且順序正確"""
    scenes = get_scenes(data)
    if len(scenes) != 6:
        return "FAIL", f"scenes 段數 = {len(scenes)}，需要 6 段（實際：{[s.get('timestamp','?') for s in scenes]}）"
    expected_order = ["0-3s", "3-12s", "12-25s", "25-40s", "40-52s", "52-60s"]
    actual = [s.get("timestamp", "") for s in scenes]
    for i, (exp, got) in enumerate(zip(expected_order, actual)):
        if got != exp:
            return "FAIL", f"scenes[{i}] timestamp = '{got}'，期望 '{exp}'"
    return "PASS", f"6 段時間軸齊全且順序正確"

def chk_l1_002_banned(data: dict, fname: str) -> tuple[str, str]:
    """L1-002：禁用詞 grep"""
    text = get_all_text(data)
    hits = [w for w in BANNED_WORDS if w in text]
    if hits:
        # 修 2（P1）：用 _get_all_dialogue 涵蓋 5 業主所有台詞欄位，不再只查 台詞_阿奇/台詞
        locs = []
        for scene in get_scenes(data):
            dialogue_parts = _get_all_dialogue(scene)
            cuiwen = str(scene.get("翠文", ""))
            all_parts = dialogue_parts + ([cuiwen] if cuiwen else [])
            for part in all_parts:
                for w in hits:
                    if w in part:
                        locs.append(f"{scene.get('timestamp','?')} 含「{w}」（節錄：{part[:20]}…）")
        return "FAIL", "禁用詞命中：" + "、".join(hits) + " — " + "；".join(locs[:5])
    return "PASS", "無禁用詞"

def chk_l1_003_mirror(data: dict, fname: str) -> tuple[str, str]:
    """L1-003：藏鏡人互動點 >= 2"""
    count = 0
    scenes = get_scenes(data)
    for scene in scenes:
        if scene.get("藏鏡人"):
            count += 1
    # 也看 data 頂層 藏鏡人 block
    top_mirror = data.get("藏鏡人", {})
    if isinstance(top_mirror, dict):
        top_count = sum(1 for k in top_mirror if k.startswith("位置"))
        if top_count > count:
            count = top_count
    if count < 2:
        return "FAIL", f"藏鏡人互動點 = {count}，需要 >= 2"
    return "PASS", f"藏鏡人互動點 = {count}"

def chk_l1_004_traffic(data: dict, fname: str) -> tuple[str, str]:
    """L1-004：流量密碼 >= 3（以 schema_check 欄位 or 台詞關鍵詞代理）"""
    sc = data.get("schema_check", {})
    if isinstance(sc, dict):
        # 如果 schema_check 有明確的 流量密碼 欄位
        fd = sc.get("流量密碼數量") or sc.get("流量密碼")
        if fd:
            try:
                n = int(str(fd))
                if n >= 3:
                    return "PASS", f"schema_check 流量密碼數量 = {n}"
                else:
                    return "FAIL", f"schema_check 流量密碼數量 = {n}，需 >= 3"
            except Exception:
                pass
    # 代理：用反問句 / 懸念語句 / 情緒觸發詞統計
    TRAFFIC_SIGNALS = ["？", "你也", "你有", "你曾", "你試", "為什麼", "你知道", "留言", "轉發",
                       "嗎", "嚇到", "沒想到", "顛覆", "原來", "不是", "竟然", "居然"]
    text = get_all_text(data)
    hits = sum(1 for s in TRAFFIC_SIGNALS if s in text)
    # 寬鬆：有懸念型藏鏡人 = +1 / 有 CTA 互動 = +1
    if data.get("藏鏡人"):
        hits += 1
    cap = data.get("caption", "")
    if cap and ("？" in cap or "留言" in cap):
        hits += 1
    if hits >= 3:
        return "PASS", f"流量密碼信號 >= 3（偵測到 {hits} 個信號，含懸念+互動+反問）"
    return "FAIL", f"流量密碼信號偵測 = {hits}，低於 3（請確認台詞有反問/懸念/互動引導）"

def chk_l1_005_number_source(data: dict, fname: str) -> tuple[str, str]:
    """L1-005：業務數字（% / 萬 / 元）必有來源標記"""
    text = get_all_text(data)
    # 找業務數字（%、萬、元、坪 等）
    NUMBER_PATTERNS = [r"\d+%", r"\d+萬", r"\d+元", r"\d+坪", r"\d+年", r"\d+月"]
    hits = []
    for pat in NUMBER_PATTERNS:
        hits.extend(re.findall(pat, text))
    if not hits:
        return "PASS", "無業務數字（無需來源標記）"
    # 看有沒有來源標記
    src_keywords = ["來源", "根據", "統計", "資料", "官方", "政府", "信義", "永慶", "591", "實價", "法規", "依據", "澤君提供", "需澤君確認"]
    has_source = any(k in text for k in src_keywords)
    sc = data.get("schema_check", {})
    # 9.5 年 / 40cm 等個人真實數字，偏好.md §5 標「已知」→ 允許
    # 規則：若唯一命中的數字是「年數/公分/個人經歷」→ WARN 不 FAIL
    personal_ok = set(re.findall(r"\d+\.?\d*(?:年|cm|公分|公里|歲)", text))
    non_personal = [h for h in hits if h not in personal_ok]
    if non_personal and not has_source:
        return "WARN", f"偵測到非個人類數字：{non_personal[:8]}，建議標來源（如 [來源：XXX] 或 [澤君提供]）"
    return "PASS", f"業務數字 {hits[:5]}{'...' if len(hits)>5 else ''}，已有來源標記或為個人經歷數字"

def chk_l1_006_cta(data: dict, fname: str) -> tuple[str, str]:
    """L1-006：52-60s 段落有 CTA 引導語（純雞湯除外）"""
    sc = data.get("schema_check", {})
    # 純雞湯豁免
    if data.get("純雞湯標記") or (isinstance(sc, dict) and (sc.get("純雞湯") or sc.get("無CTA"))):
        return "PASS", "純雞湯標記 = true，豁免 CTA 要求"
    scenes = get_scenes(data)
    last = scenes[-1] if scenes else {}
    ts = last.get("timestamp", "")
    if ts != "52-60s":
        return "FAIL", f"最後一段 timestamp = '{ts}'，不是 '52-60s'"
    seg_type = last.get("type", "")
    if "CTA" not in seg_type and "cta" not in seg_type.lower():
        return "FAIL", f"最後一段 type = '{seg_type}'，應含 CTA"
    # 修 2（P1）：用 _get_all_dialogue 涵蓋 5 業主所有台詞欄位
    dialogue_parts = _get_all_dialogue(last)
    text = " ".join(dialogue_parts) if dialogue_parts else ""
    cta_keywords = ["留言", "私訊", "追蹤", "訂閱", "IG", "FB", "TikTok", "電話", "LINE", "連結", "點",
                    "分享", "收藏", "告訴我", "找我", "我訊你",
                    "底下", "說說", "聊聊", "來問", "tag", "按讚", "一起", "你呢", "你是", "你有",
                    "評論", "互動", "問我", "歡迎", "歡迎來"]
    if any(k in text for k in cta_keywords):
        return "PASS", f"52-60s CTA 段存在，含引導語（{text[:40]}…）"
    return "FAIL", f"52-60s CTA 段文字無引導語關鍵詞（{text[:60]}）"

def chk_l1_007_title_len(data: dict, fname: str) -> tuple[str, str]:
    """L1-007：標題 <= 15 字"""
    title = data.get("title", "")
    if not title:
        return "FAIL", "title 欄位空白"
    # 計算純中文+英文字數（不含空格/標點）
    chars = re.sub(r"[\s！，。？「」：、【】…—\-]+", "", title)
    n = len(chars)
    if n <= 15:
        return "PASS", f"標題 '{title}'，字數 = {n} <= 15"
    return "FAIL", f"標題 '{title}'，字數 = {n} > 15"

def chk_l1_008_batch_count(yamls: list[tuple[Path, dict]], batch_dir: Path) -> tuple[str, str]:
    """L1-008：批次數量 13-14 主腳本（此函式是 batch-level check）"""
    valid = [(f, d) for f, d in yamls if "__parse_error__" not in d and "__schema_error__" not in d]
    n = len(valid)
    if 13 <= n <= 14:
        return "PASS", f"主腳本 yaml 數量 = {n}（範圍 13-14）"
    return "FAIL", f"主腳本 yaml 數量 = {n}，SOP 要求 13-14 支"

def chk_l1_009_派系_coverage(yamls: list[tuple[Path, dict]]) -> tuple[str, str]:
    """L1-009：派系覆蓋度 >= 3 種"""
    types = set()
    for _, d in yamls:
        if "__parse_error__" in d:
            continue
        派系 = d.get("派系", "") or d.get("template", "")
        if 派系:
            # 抓「（派N）」前的派系名
            m = re.match(r"([^\(（]+)", str(派系))
            if m:
                types.add(m.group(1).strip())
    n = len(types)
    if n >= 3:
        return "PASS", f"派系覆蓋 = {n} 種：{sorted(types)}"
    return "FAIL", f"派系覆蓋 = {n} 種（{sorted(types)}），需 >= 3 種"

def chk_c010_翠文_non_empty(data: dict, fname: str) -> tuple[str, str]:
    """C-010：翠文非空 + 非畫面描述（字幕 ≠ 畫面說明）"""
    scenes = get_scenes(data)
    fails = []
    warns = []
    for scene in scenes:
        ts = scene.get("timestamp", "?")
        cuiwen = scene.get("翠文", "")
        if not cuiwen or str(cuiwen).strip() == "":
            fails.append(f"{ts} 翠文空白")
            continue
        # 翠文裡混入畫面描述 keyword → WARN
        for kw in SCENE_DESC_KEYWORDS:
            if kw in str(cuiwen):
                warns.append(f"{ts} 翠文疑似含畫面描述 keyword「{kw}」（翠文={cuiwen[:30]}…）")
                break
    if fails:
        return "FAIL", "翠文空白：" + "；".join(fails)
    if warns:
        return "WARN", "翠文疑似混入畫面描述（字幕 ≠ 畫面說明）：" + "；".join(warns[:3])
    return "PASS", f"全 {len(scenes)} 段翠文非空，無畫面描述 keyword"

def chk_c011_派系_ratio(yamls: list[tuple[Path, dict]], owner: str, pref_text: Optional[str]) -> tuple[str, str]:
    """C-011：派系比例對齊業主偏好.md §8（±5% 容許）"""
    if not pref_text:
        return "WARN", f"找不到業主 '{owner}' 偏好.md，無法驗派系比例（路徑：{OWNER_PREF_PATHS.get(owner,'未知')}）"
    expected = parse_schema_distribution(pref_text, "§8") or parse_schema_distribution(pref_text, "第 8 章")
    if not expected:
        return "WARN", "偏好.md 第 8 章無法解析到 XX% 格式的比例，跳過派系比例驗證"
    # 統計本批派系
    actual_count: dict[str, int] = {}
    total = 0
    for _, d in yamls:
        if "__parse_error__" in d:
            continue
        派系 = d.get("派系", "") or d.get("template", "")
        m = re.match(r"([^\(（]+)", str(派系))
        if m:
            name = m.group(1).strip()
            actual_count[name] = actual_count.get(name, 0) + 1
            total += 1
    if total == 0:
        return "WARN", "批次無有效 yaml，無法計算派系比例"
    actual_pct = {k: round(v / total * 100) for k, v in actual_count.items()}
    # 找禁用派系命中
    BANNED_TEMPLATE_MARKERS = ["嗆辣派", "爆文公式派"]
    banned_hits = [k for k in actual_count if any(b in k for b in BANNED_TEMPLATE_MARKERS)]
    if banned_hits:
        return "FAIL", f"禁用派系出現在批次中：{banned_hits}"
    # 修 1（P0）：真實 expected vs actual 對比，abs(diff) > 5% → FAIL
    # key 正規化：expected key 有時帶括號如「故事戲劇派（派1）」，
    # 對齊 actual_count 的截取規則（re.match [^\(（]+）
    TOLERANCE = 5
    def _norm_key(s: str) -> str:
        mx = re.match(r"([^\(（]+)", s)
        return mx.group(1).strip() if mx else s.strip()
    normalized_expected = {_norm_key(k): v for k, v in expected.items()}
    over_tol = []
    for name, exp_pct in normalized_expected.items():
        act_pct = actual_pct.get(name, 0)
        diff = act_pct - exp_pct
        if abs(diff) > TOLERANCE:
            over_tol.append(f"{name} 預期 {exp_pct}% 實際 {act_pct}%（偏差 {diff:+d}%）")
    if over_tol:
        return "FAIL", f"C-011 派系比例超出 ±{TOLERANCE}%：" + "；".join(over_tol) + f"  （實際分佈：{actual_pct}）"
    return "PASS", f"C-011 派系比例對齊（±{TOLERANCE}% 內）：{actual_pct}（偏好參考：{normalized_expected}）"

def chk_c012_identity_ratio(yamls: list[tuple[Path, dict]], owner: str, pref_text: Optional[str]) -> tuple[str, str]:
    """C-012：雙身份比例對齊業主偏好.md §3"""
    if not pref_text:
        return "WARN", f"找不到業主 '{owner}' 偏好.md，跳過雙身份比例驗證"
    expected = parse_identity_distribution(pref_text)
    if not expected:
        return "WARN", "偏好.md 第 3 章無法解析比例，跳過雙身份比例驗證"
    actual_count: dict[str, int] = {}
    total = 0
    for _, d in yamls:
        if "__parse_error__" in d:
            continue
        itype = d.get("雙身份分類", "")
        if itype:
            label = re.sub(r"[（\(].*", "", str(itype)).strip()
            actual_count[label] = actual_count.get(label, 0) + 1
            total += 1
    if total == 0:
        return "WARN", "批次 yaml 無雙身份分類欄位，跳過驗證"
    actual_pct = {k: round(v / total * 100) for k, v in actual_count.items()}
    # 修 1（P0）：真實 expected vs actual 對比，abs(diff) > 5% → FAIL
    TOLERANCE = 5
    over_tol = []
    for name, exp_pct in expected.items():
        act_pct = actual_pct.get(name, 0)
        diff = act_pct - exp_pct
        if abs(diff) > TOLERANCE:
            over_tol.append(f"{name} 預期 {exp_pct}% 實際 {act_pct}%（偏差 {diff:+d}%）")
    if over_tol:
        return "FAIL", f"C-012 雙身份比例超出 ±{TOLERANCE}%：" + "；".join(over_tol) + f"  （實際分佈：{actual_pct}）"
    return "PASS", f"C-012 雙身份比例對齊（±{TOLERANCE}% 內）：{actual_pct}（偏好參考：{expected}）"

def chk_c013_dm_card(data: dict, fname: str, owner: str) -> tuple[str, str]:
    """C-013：釣魚部腳本 dm_card 6 件齊"""
    title = data.get("title", "")
    template = data.get("template", "")
    pattern = data.get("pattern", "")
    # 釣魚部偵測：必須有明確的釣魚部標記
    has_dm_card_field = isinstance(data.get("dm_card"), dict)  # dm_card 必須是字典型欄位
    has_fishing_marker = (data.get("釣魚部標記") or data.get("dm_card_配套") or
                          data.get("dm_card配套") or has_dm_card_field)
    is_dm = (("釣魚部" in title or "釣魚部" in template or "釣魚部" in pattern) or
             has_fishing_marker)
    if not is_dm:
        return "PASS", "非釣魚部腳本，跳過 dm_card 驗證"
    # 驗 6 件：行業專業 / 在地優勢 / 痛點 / 解法 / 行動呼籲 / LINE QR 連結
    sc = data.get("schema_check", {}) or {}
    dm = data.get("dm_card", {}) or {}
    # 把整個 data 轉成字串（含 dm_card 底下的 list / dict 全轉文字）做 keyword 比對
    ALL_TEXT = str(data)
    SIX_FIELDS = {
        "行業專業": ["行業專業", "專業", "問題標題", "怎麼做"],
        "在地優勢": ["在地優勢", "在地", "雷區"],
        "痛點":     ["痛點", "完整答案"],
        "解法":     ["解法", "解決", "怎麼做", "完整答案"],
        "行動呼籲": ["行動呼籲", "CTA聯絡", "CTA", "留言", "私訊", "cta"],
        "LINE QR": ["LINE QR", "line_qr", "line qr", "qr_verify", "must_have_qr"],
    }
    missing = []
    for field, keywords in SIX_FIELDS.items():
        found = any(k in ALL_TEXT for k in keywords)
        if not found:
            missing.append(field)
    if missing:
        return "FAIL", f"釣魚部 dm_card 缺少欄位：{missing}"
    return "PASS", "釣魚部 dm_card 6 件齊"

def chk_c014_card_style(batch_dir: Path, owner: str, batch_tag: str) -> tuple[str, str]:
    """C-014：圖卡風格 18 選 1 推薦走過"""
    # 找業主核心檔資料夾
    owner_dir_map = {
        "瑞祥":     L2_BASE / "房仲_瑞祥"    / "00_業主核心檔" / "source_overlay",
        "仲豪":     L2_BASE / "房仲_仲豪"    / "00_業主核心檔" / "source_overlay",
        "昀臻":     L2_BASE / "美容_昀臻"    / "00_業主核心檔" / "source_overlay",
        "叭噗_小C": L2_BASE / "情侶_叭噗_小C" / "00_業主核心檔" / "source_overlay",
        "阿奇":     L2_BASE / "餐飲_阿奇"    / "00_業主核心檔" / "source_overlay",
    }
    overlay_dir = owner_dir_map.get(owner)
    if not overlay_dir or not overlay_dir.exists():
        return "WARN", f"找不到業主 source_overlay 資料夾（{overlay_dir}），跳過圖卡風格驗證"
    # 抓批次編號（e.g. 第01批）
    batch_num_m = re.search(r"第(\d+)批", batch_tag)
    batch_num = batch_num_m.group(0) if batch_num_m else batch_tag
    # 找 _<業主>圖卡風格選擇_<批次>.md 或 _圖卡風格_*.md
    candidates = list(overlay_dir.glob(f"*圖卡風格*{batch_num}*.md"))
    if not candidates:
        candidates = list(overlay_dir.glob("*圖卡風格*.md"))
    if not candidates:
        return "WARN", f"找不到圖卡風格選擇檔（在 {overlay_dir}，批次 {batch_num}）— 請在 source_overlay 建立 _圖卡風格選擇_{batch_num}.md"
    # 驗內容含 style-N- 或 id: N
    for p in candidates:
        content = p.read_text(encoding="utf-8")
        if re.search(r"style-\d+-", content) or re.search(r"id:\s*\d+", content):
            return "PASS", f"圖卡風格選擇檔存在：{p.name}，含風格 id"
    return "WARN", f"圖卡風格選擇檔存在（{candidates[0].name}）但未偵測到 style-N- 格式的風格 id"

def chk_c015_hashtag_caption(data: dict, fname: str) -> tuple[str, str]:
    """C-015：hashtag 8-12 個 + caption 60-80 字"""
    fails = []
    hashtag = data.get("hashtag", [])
    if isinstance(hashtag, list):
        ht_count = len(hashtag)
    else:
        ht_count = len(str(hashtag).split())
    if not (8 <= ht_count <= 12):
        fails.append(f"hashtag 數量 = {ht_count}，需 8-12 個")
    caption = str(data.get("caption", "") or "")
    # caption 字數：純正文（排除 hashtag）
    cap_clean = re.sub(r"#[\S]+", "", caption).strip()
    cap_len = len(cap_clean)
    if not (60 <= cap_len <= 80):
        fails.append(f"caption 字數 = {cap_len}，需 60-80 字（純文 = '{cap_clean[:50]}…'）")
    if fails:
        return "FAIL", "；".join(fails)
    return "PASS", f"hashtag = {ht_count} 個，caption = {cap_len} 字"


# ────────────────────────────────────────────
# 跑單一 yaml 的 12 件 per-file checks
# ────────────────────────────────────────────
def run_per_file_checks(f: Path, data: dict, owner: str) -> list[tuple[str, str, str, str]]:
    """回傳 [(check_id, status, desc, detail), ...]"""
    results = []
    checks = [
        ("L1-001", chk_l1_001_schema(data, f.name)),
        ("L1-002", chk_l1_002_banned(data, f.name)),
        ("L1-003", chk_l1_003_mirror(data, f.name)),
        ("L1-004", chk_l1_004_traffic(data, f.name)),
        ("L1-005", chk_l1_005_number_source(data, f.name)),
        ("L1-006", chk_l1_006_cta(data, f.name)),
        ("L1-007", chk_l1_007_title_len(data, f.name)),
        ("C-010",  chk_c010_翠文_non_empty(data, f.name)),
        ("C-013",  chk_c013_dm_card(data, f.name, owner)),
        ("C-015",  chk_c015_hashtag_caption(data, f.name)),
    ]
    for cid, (status, detail) in checks:
        results.append((cid, status, f.name, detail))
    return results

# ────────────────────────────────────────────
# 主程式
# ────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="腳本批次品管員 — 15 件自動擋")
    parser.add_argument("--owner",     help="業主名（瑞祥/仲豪/昀臻/叭噗_小C/阿奇）")
    parser.add_argument("--batch-dir", required=True, help="第 N 批 yaml 資料夾絕對路徑")
    parser.add_argument("--strict",    action="store_true", help="任一 FAIL → exit 1（pre-commit 模式）")
    args = parser.parse_args()

    batch_dir = Path(args.batch_dir)
    if not batch_dir.exists():
        print(f"[ERROR] batch-dir 不存在：{batch_dir}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  腳本批次品管員 v1.0")
    print(f"  批次資料夾：{batch_dir}")
    print(f"{'='*60}\n")

    # 讀 yaml
    yamls = load_yamls(batch_dir)
    # 修 3（P1）：schema_error 也算失效檔，嚴禁靜默 skip
    valid_yamls = [(f, d) for f, d in yamls if "__parse_error__" not in d and "__schema_error__" not in d]
    parse_errors = [(f, d) for f, d in yamls if "__parse_error__" in d or "__schema_error__" in d]

    if parse_errors:
        for f, d in parse_errors:
            if "__parse_error__" in d:
                print(f"[PARSE ERROR] {f.name}: {d['__parse_error__']}")
            else:
                print(f"[SCHEMA ERROR] {f.name}: {d['__schema_error__']}")
        if args.strict:
            print(f"\n❌ strict 模式：{len(parse_errors)} 個 YAML 解析/schema 失敗 — 修正後再 commit")
            sys.exit(1)

    # 自動偵測 owner
    owner = args.owner
    if not owner and valid_yamls:
        owner = valid_yamls[0][1].get("owner", "未知")
    if not owner:
        owner = "未知"

    # 取批次 tag
    batch_tag = ""
    if valid_yamls:
        batch_tag = valid_yamls[0][1].get("batch_tag", batch_dir.name)

    print(f"業主：{owner}  /  批次：{batch_tag}  /  yaml 數量：{len(valid_yamls)}（含 .bak 已略）\n")

    pref_text = load_pref_md(owner)
    if not pref_text:
        print(f"[WARN] 找不到業主偏好.md（{OWNER_PREF_PATHS.get(owner,'未知路徑')}）— C-011/C-012 跳過\n")

    all_results: list[tuple[str, str, str, str]] = []

    # ── Batch-level checks（L1-008 / L1-009 / C-011 / C-012 / C-014）──
    batch_checks = [
        ("L1-008", chk_l1_008_batch_count(yamls, batch_dir)),
        ("L1-009", chk_l1_009_派系_coverage(valid_yamls)),
        ("C-011",  chk_c011_派系_ratio(valid_yamls, owner, pref_text)),
        ("C-012",  chk_c012_identity_ratio(valid_yamls, owner, pref_text)),
        ("C-014",  chk_c014_card_style(batch_dir, owner, batch_tag)),
    ]
    print("── 批次級 check（5 件）──")
    for cid, (status, detail) in batch_checks:
        icon = "✅" if status == "PASS" else ("⚠️ " if status == "WARN" else "❌")
        print(f"  {icon} [{cid}] {status}: {detail}")
        all_results.append((cid, status, "batch", detail))
    print()

    # ── Per-file checks（10 件 × N yaml）──
    print("── 逐篇 check（10 件 × 每篇）──")
    for f, data in valid_yamls:
        title = data.get("title", f.name)
        print(f"\n  [{f.name}] {title}")
        per_results = run_per_file_checks(f, data, owner)
        for cid, status, fname, detail in per_results:
            icon = "✅" if status == "PASS" else ("⚠️ " if status == "WARN" else "❌")
            print(f"    {icon} [{cid}] {status}: {detail}")
            all_results.append((cid, status, fname, detail))

    # ── 彙總 ──
    fail_count = sum(1 for _, s, _, _ in all_results if s == "FAIL")
    warn_count = sum(1 for _, s, _, _ in all_results if s == "WARN")
    pass_count = sum(1 for _, s, _, _ in all_results if s == "PASS")
    total = len(all_results)

    print(f"\n{'='*60}")
    print(f"  品管彙總：{pass_count} PASS / {warn_count} WARN / {fail_count} FAIL（共 {total} 件）")
    if fail_count == 0 and warn_count == 0:
        print("  ✅ 全數 PASS — 批次品管通過")
    elif fail_count == 0:
        print(f"  ⚠️  無 FAIL，{warn_count} 件 WARN（請確認 WARN 項目後再 commit）")
    else:
        print(f"  ❌ 有 {fail_count} 件 FAIL — 修完才能 commit")
        # 列出所有 FAIL
        print("\n  FAIL 清單：")
        for cid, status, fname, detail in all_results:
            if status == "FAIL":
                print(f"    ❌ [{cid}] {fname}: {detail}")
    print(f"{'='*60}\n")

    if args.strict and fail_count > 0:
        sys.exit(1)
    if not args.strict and fail_count > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
