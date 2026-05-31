#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_script_batch.py — 腳本批次品管員（20 件自動擋 / v2 — 階段 3 升級）
對齊 SOP _腳本生產SOP_v3.0.yaml §11 9 件 + §14 §15 + guardian 補 6 件 C-010 ~ C-015
v2 新增 5 件 V2-001 ~ V2-005（yaml schema 新欄位驗 + migration plan）

用法：
  python validate_script_batch.py --owner 阿奇 --batch-dir <絕對路徑>
  python validate_script_batch.py --owner 阿奇 --batch-dir <絕對路徑> --strict
  python validate_script_batch.py --batch-dir <路徑>  # owner 從 yaml frontmatter 自動偵測

PASS → exit 0 / FAIL → exit 1（--strict 模式 / 任一 FAIL）

建檔：2026-05-22 / 對齊 SOP §11 L1-001 ~ L1-009 + guardian 補 6 件 C-010 ~ C-015
v2 升級：2026-05-23 / 階段 3 新欄位驗 V2-001 ~ V2-005

=== Migration Plan（Codex R2 P0）===
  - 既有 65 部腳本 yaml：legacy_allowed_until: 2026-06-01 → V2 check 在過渡期 WARN 不 FAIL
  - 新批次（2026-06-01 後 / 或 yaml 缺 legacy_allowed_until）→ V2 check 硬 FAIL
  - 5 組 validator fixtures（見底部 __main__ 段）：
    F1 pass — 含全新欄位
    F2 missing_field — 缺 distribution_mode
    F3 legacy — 含 legacy_allowed_until: 2026-06-01 → WARN 不 FAIL
    F4 platform_variants — 含 platform_variants 驗格式
    F5 beauty_violation — 美容業 policy_alignment 缺 Meta D-2
"""

import sys
import os
import re
import argparse
import yaml
from pathlib import Path
from typing import Any, Optional

# ── normalize_script_to_canonical（yaml_to_sc.py v3）──
# 接 canonical 讀腳本，供 V2-025/V2-026 使用
# 若 import 失敗（例如路徑問題），check 會自動 WARN 不 FAIL
try:
    _YAML_TO_SC_DIR = Path(__file__).parent
    if str(_YAML_TO_SC_DIR) not in sys.path:
        sys.path.insert(0, str(_YAML_TO_SC_DIR))
    from yaml_to_sc import normalize_script_to_canonical as _normalize_canonical
    _CANONICAL_AVAILABLE = True
except Exception as _e:
    _CANONICAL_AVAILABLE = False
    _normalize_canonical = None  # type: ignore

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
            # 移掉開頭 --- frontmatter marker
            text = re.sub(r"^---\s*\n", "", text, count=1)
            # 切第二個 --- 後的 markdown body（yaml-with-frontmatter 格式）
            parts = re.split(r"\n---\s*\n", text, maxsplit=1)
            frontmatter_text = parts[0]
            # 保留 markdown body（供 normalize_script_to_canonical 使用）
            md_body = parts[1].strip() if len(parts) > 1 else ""
            # 再 strip 結尾 ---
            frontmatter_text = re.sub(r"\n---\s*$", "", frontmatter_text)
            data = yaml.safe_load(frontmatter_text)
            # 修 3（P1）：空 YAML / None / list / scalar → 標 __schema_error__，嚴禁靜默 skip
            if data is None or data == "" or data == {}:
                results.append((f, {"__schema_error__": f"YAML 為空（None/empty）：{f.name}"}))
            elif not isinstance(data, dict):
                results.append((f, {"__schema_error__": f"YAML top-level 不是 dict（實際型別：{type(data).__name__}）：{f.name}"}))
            else:
                # 把 markdown body 存入 data（加法，不破壞現有欄位），供 canonical 層使用
                if md_body and '_markdown_body' not in data:
                    data['_markdown_body'] = md_body
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

def _ts_normalize(ts: str) -> str:
    """把 canonical 格式 timestamp 正規化為 '0-3s' 標準格式，供 L1-001 比對用。
    支援：'0-3s'（已是標準）/ '0-3秒'（markdown body 解析結果）。
    """
    # 移除空格，統一全形破折號
    ts = ts.strip().replace('–', '-').replace(' ', '')
    # '0-3秒' → '0-3s'
    ts = re.sub(r'秒.*$', 's', ts)
    return ts


def _get_canonical_scenes(data: dict) -> Optional[list]:
    """若 canonical 可用且能解析出 scenes，回傳 canonical scenes；否則 None。
    canonical scenes 每個元素有 timestamp / role / dialogue / subtitle /
    offscreen_interaction 等欄位。
    """
    if not _CANONICAL_AVAILABLE or _normalize_canonical is None:
        return None
    try:
        canonical = _normalize_canonical(data)
        scenes = canonical.get('scenes', [])
        if scenes:
            return scenes
    except Exception:
        pass
    return None


def chk_l1_001_schema(data: dict, fname: str) -> tuple[str, str]:
    """L1-001：schema 對齊 — 6 段時間軸完整且順序正確
    有 canonical 用 canonical（支援 markdown body 格式），沒有 fallback 舊邏輯。
    """
    expected_order = ["0-3s", "3-12s", "12-25s", "25-40s", "40-52s", "52-60s"]

    # 嘗試用 canonical
    canonical_scenes = _get_canonical_scenes(data)
    if canonical_scenes is not None:
        if len(canonical_scenes) != 6:
            ts_list = [s.get('timestamp', '?') for s in canonical_scenes]
            return "FAIL", f"scenes 段數 = {len(canonical_scenes)}，需要 6 段（實際：{ts_list}）"
        actual = [_ts_normalize(s.get('timestamp', '')) for s in canonical_scenes]
        for i, (exp, got) in enumerate(zip(expected_order, actual)):
            if got != exp:
                return "FAIL", f"scenes[{i}] timestamp = '{got}'，期望 '{exp}'（原始：{canonical_scenes[i].get('timestamp','')}）"
        return "PASS", "6 段時間軸齊全且順序正確（canonical 層驗）"

    # fallback：舊邏輯（structured frontmatter）
    scenes = get_scenes(data)
    if len(scenes) != 6:
        return "FAIL", f"scenes 段數 = {len(scenes)}，需要 6 段（實際：{[s.get('timestamp','?') for s in scenes]}）"
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
    """L1-003：藏鏡人互動點 >= 2
    有 canonical 用 canonical（offscreen_interaction 欄位），沒有 fallback 舊邏輯。
    §14 P0：mirror 要吃 canonical，不是舊貪婪 regex。
    """
    # 嘗試用 canonical
    canonical_scenes = _get_canonical_scenes(data)
    if canonical_scenes is not None:
        count = sum(1 for s in canonical_scenes if s.get('offscreen_interaction'))
        if count < 2:
            return "FAIL", f"藏鏡人互動點 = {count}，需要 >= 2（canonical 層驗）"
        return "PASS", f"藏鏡人互動點 = {count}（canonical 層驗）"

    # fallback：舊邏輯
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

def _canonical_all_text(canonical_scenes: list, caption: str = '') -> str:
    """從 canonical scenes 取全文（dialogue + subtitle + offscreen）供關鍵詞搜尋。"""
    parts = []
    for s in canonical_scenes:
        for d in s.get('dialogue', []):
            parts.append(d.get('line', ''))
        if s.get('subtitle'):
            parts.append(s['subtitle'])
        if s.get('offscreen_interaction'):
            parts.append(s['offscreen_interaction'])
    if caption:
        parts.append(caption)
    return ' '.join(parts)


def chk_l1_004_traffic(data: dict, fname: str) -> tuple[str, str]:
    """L1-004：流量密碼 >= 3（以 schema_check 欄位 or 台詞關鍵詞代理）
    有 canonical 用 canonical（dialogue + subtitle + offscreen 全文），沒有 fallback 舊邏輯。
    """
    sc = data.get("schema_check", {})
    if isinstance(sc, dict):
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

    TRAFFIC_SIGNALS = ["？", "你也", "你有", "你曾", "你試", "為什麼", "你知道", "留言", "轉發",
                       "嗎", "嚇到", "沒想到", "顛覆", "原來", "不是", "竟然", "居然"]

    # 嘗試用 canonical
    canonical_scenes = _get_canonical_scenes(data)
    if canonical_scenes is not None:
        cap = ''
        try:
            cap = _normalize_canonical(data).get('caption', '') if _normalize_canonical else ''
        except Exception:
            pass
        text = _canonical_all_text(canonical_scenes, cap)
        hits = sum(1 for s in TRAFFIC_SIGNALS if s in text)
        # 有藏鏡人 = +1
        if any(s.get('offscreen_interaction') for s in canonical_scenes):
            hits += 1
        if cap and ("？" in cap or "留言" in cap):
            hits += 1
        if hits >= 3:
            return "PASS", f"流量密碼信號 >= 3（偵測到 {hits} 個，含懸念+互動+反問，canonical 層驗）"
        return "FAIL", f"流量密碼信號偵測 = {hits}，低於 3（canonical 層驗，請確認台詞有反問/懸念/互動引導）"

    # fallback：舊邏輯
    text = get_all_text(data)
    hits = sum(1 for s in TRAFFIC_SIGNALS if s in text)
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
    """L1-006：52-60s 段落有 CTA 引導語（純雞湯除外）
    有 canonical 用 canonical（timestamp 正規化 + dialogue），沒有 fallback 舊邏輯。
    """
    sc = data.get("schema_check", {})
    # 純雞湯豁免
    if data.get("純雞湯標記") or (isinstance(sc, dict) and (sc.get("純雞湯") or sc.get("無CTA"))):
        return "PASS", "純雞湯標記 = true，豁免 CTA 要求"

    cta_keywords = ["留言", "私訊", "追蹤", "訂閱", "IG", "FB", "TikTok", "電話", "LINE", "連結", "點",
                    "分享", "收藏", "告訴我", "找我", "我訊你",
                    "底下", "說說", "聊聊", "來問", "tag", "按讚", "一起", "你呢", "你是", "你有",
                    "評論", "互動", "問我", "歡迎", "歡迎來"]

    # 嘗試用 canonical
    canonical_scenes = _get_canonical_scenes(data)
    if canonical_scenes is not None:
        if not canonical_scenes:
            return "FAIL", "canonical scenes 為空，找不到 CTA 段"
        last = canonical_scenes[-1]
        ts_norm = _ts_normalize(last.get('timestamp', ''))
        if ts_norm != '52-60s':
            return "FAIL", f"最後一段 timestamp = '{last.get('timestamp','')}' (正規化: '{ts_norm}')，不是 '52-60s'"
        role = last.get('role', '')
        if 'CTA' not in role and 'cta' not in role.lower():
            return "FAIL", f"最後一段 role = '{role}'，應含 CTA（canonical 層驗）"
        text = ' '.join(d.get('line', '') for d in last.get('dialogue', []))
        # 也從 subtitle 找
        text += ' ' + last.get('subtitle', '')
        if any(k in text for k in cta_keywords):
            return "PASS", f"52-60s CTA 段存在，含引導語（canonical 層驗，{text[:40]}…）"
        return "FAIL", f"52-60s CTA 段文字無引導語關鍵詞（canonical 層驗，{text[:60]}）"

    # fallback：舊邏輯
    scenes = get_scenes(data)
    last = scenes[-1] if scenes else {}
    ts = last.get("timestamp", "")
    if ts != "52-60s":
        return "FAIL", f"最後一段 timestamp = '{ts}'，不是 '52-60s'"
    seg_type = last.get("type", "")
    if "CTA" not in seg_type and "cta" not in seg_type.lower():
        return "FAIL", f"最後一段 type = '{seg_type}'，應含 CTA"
    dialogue_parts = _get_all_dialogue(last)
    text = " ".join(dialogue_parts) if dialogue_parts else ""
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
    """L1-009：派系覆蓋度 >= 3 種
    支援 '派系' key（阿奇/叭噗格式）及 'faction' key（瑞祥 markdown 格式）。
    """
    types = set()
    for _, d in yamls:
        if "__parse_error__" in d:
            continue
        # 同時讀 派系 / faction / template（按優先序）
        派系 = d.get("派系", "") or d.get("faction", "") or d.get("template", "")
        if 派系:
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
    """C-015：hashtag 8-12 個 + caption 60-80 字
    有 canonical 用 canonical（markdown body 的 ## Caption / ## Hashtag），
    沒有 fallback 直讀 frontmatter（叭噗/阿奇結構化格式）。
    """
    # 嘗試從 canonical 讀（含 markdown body 解析）
    hashtag = None
    caption = None
    if _CANONICAL_AVAILABLE and _normalize_canonical is not None:
        try:
            canonical = _normalize_canonical(data)
            ht_c = canonical.get('hashtag', [])
            cap_c = canonical.get('caption', '')
            if ht_c:  # canonical 讀到 hashtag 就用
                hashtag = ht_c
            if cap_c:  # canonical 讀到 caption 就用
                caption = cap_c
        except Exception:
            pass

    # fallback：直讀 frontmatter
    if hashtag is None:
        hashtag = data.get("hashtag", [])
    if caption is None:
        caption = str(data.get("caption", "") or "")

    fails = []
    if isinstance(hashtag, list):
        ht_count = len(hashtag)
    else:
        ht_count = len(str(hashtag).split())
    if not (8 <= ht_count <= 12):
        fails.append(f"hashtag 數量 = {ht_count}，需 8-12 個")

    caption_str = str(caption or "")
    cap_clean = re.sub(r"#[\S]+", "", caption_str).strip()
    cap_len = len(cap_clean)
    if not (60 <= cap_len <= 80):
        fails.append(f"caption 字數 = {cap_len}，需 60-80 字（純文 = '{cap_clean[:50]}…'）")
    if fails:
        return "FAIL", "；".join(fails)
    return "PASS", f"hashtag = {ht_count} 個，caption = {cap_len} 字"


# ────────────────────────────────────────────
# v2 新欄位 check 函式（V2-001 ~ V2-005）
# Migration Plan：
#   - yaml 有 legacy_allowed_until 欄位且日期 >= today → WARN（過渡期）
#   - yaml 無 legacy_allowed_until 或日期已過 → FAIL（新批次強制）
# ────────────────────────────────────────────

import datetime as _dt

def _is_legacy_yaml(data: dict) -> bool:
    """判斷是否為過渡期 legacy yaml（legacy_allowed_until >= today）"""
    val = data.get('legacy_allowed_until', '')
    if not val:
        return False
    try:
        cutoff = _dt.date.fromisoformat(str(val).strip())
        return _dt.date.today() <= cutoff
    except Exception:
        return False


def chk_v2_001_voice_lock(data: dict, fname: str) -> tuple[str, str]:
    """V2-001：voice_lock 欄位存在（明確聲明是否強制語料）"""
    has_field = 'voice_lock' in data
    if has_field:
        val = data['voice_lock']
        return "PASS", f"voice_lock = {val}（明確聲明）"
    if _is_legacy_yaml(data):
        return "WARN", f"缺 voice_lock（legacy yaml 過渡期，legacy_allowed_until: {data.get('legacy_allowed_until')}）"
    return "FAIL", "缺 voice_lock 欄位（新批次必須聲明 true/false）"


def chk_v2_002_policy_alignment(data: dict, fname: str, owner: str = '') -> tuple[str, str]:
    """V2-002：policy_alignment 非空 + 各平台 >= 1 條政策
    美容業（昀臻）額外驗 Meta D-2 合規標記存在。
    試點腳本無此欄位 → WARN（同 legacy 過渡期邏輯）。
    """
    pa = data.get('policy_alignment')
    if not pa:
        if _is_legacy_yaml(data):
            return "WARN", f"缺 policy_alignment（legacy 過渡期允許）"
        # policy_alignment 空：對非強制業主（非昀臻）降 WARN，不硬 FAIL
        if owner == '昀臻':
            return "FAIL", "缺 policy_alignment 欄位（昀臻美容業強制，應標記每平台 2026 演算法政策）"
        return "WARN", "缺 policy_alignment 欄位（建議標記每平台融入的 2026 演算法政策；試點/初版腳本允許空）"
    if not isinstance(pa, dict):
        return "FAIL", f"policy_alignment 格式錯誤（應是 dict，實際：{type(pa).__name__}）"
    # 至少一個平台有填
    filled = {k: v for k, v in pa.items() if v}
    if not filled:
        return "WARN", "policy_alignment 所有平台欄位空白（至少填 1 個平台的政策）"
    # 美容業額外驗 Meta D-2
    if owner == '昀臻':
        ig_policies = pa.get('ig') or pa.get('fb') or []
        if isinstance(ig_policies, list):
            has_d2 = any('D-2' in str(p) or '合規' in str(p) or '美容效果' in str(p) for p in ig_policies)
            if not has_d2:
                return "WARN", "昀臻（美容業）policy_alignment 建議包含 Meta D-2 合規標記（防美容效果宣稱違規）"
    return "PASS", f"policy_alignment 已填 {len(filled)} 個平台（{list(filled.keys())}）"


def chk_v2_003_publish_distribution_mode(data: dict, fname: str) -> tuple[str, str]:
    """V2-003：publish_mode + distribution_mode 存在且 enum 合法
    別名（§14 P1）：'manual' → 'manual_today'、'organic' → 'organic_only' 接受（降 WARN）。
    既有瑞祥第34批使用 manual/organic，不應 FAIL。
    """
    VALID_PUBLISH = {'manual_today', 'platform_scheduled', 'draft_only'}
    VALID_DIST    = {'organic_only', 'boost_candidate', 'paid_ad'}
    # 別名映射（接受舊格式，降 WARN）
    ALIAS_PUBLISH = {'manual': 'manual_today'}
    ALIAS_DIST    = {'organic': 'organic_only'}

    warns = []
    fails = []

    pm = data.get('publish_mode', '')
    dm = data.get('distribution_mode', '')

    if not pm:
        if _is_legacy_yaml(data):
            return "WARN", "缺 publish_mode + distribution_mode（legacy 過渡期允許）"
        fails.append("缺 publish_mode")
    elif pm in ALIAS_PUBLISH:
        warns.append(f"publish_mode '{pm}' 是別名，建議改為 '{ALIAS_PUBLISH[pm]}'")
    elif pm not in VALID_PUBLISH:
        fails.append(f"publish_mode '{pm}' 不合法（合法值：{sorted(VALID_PUBLISH)}）")

    if not dm:
        if not fails:
            if _is_legacy_yaml(data):
                return "WARN", "缺 distribution_mode（legacy 過渡期允許）"
        fails.append("缺 distribution_mode")
    elif dm in ALIAS_DIST:
        warns.append(f"distribution_mode '{dm}' 是別名，建議改為 '{ALIAS_DIST[dm]}'")
    elif dm not in VALID_DIST:
        fails.append(f"distribution_mode '{dm}' 不合法（合法值：{sorted(VALID_DIST)}）")

    if fails:
        return "FAIL", "；".join(fails)
    if warns:
        return "WARN", "；".join(warns)
    return "PASS", f"publish_mode={pm}，distribution_mode={dm}"


def chk_v2_004_platform_variants(data: dict, fname: str) -> tuple[str, str]:
    """V2-004：platform_variants 存在 + 至少 1 個平台有 cta 或 caption_keywords
    既有瑞祥格式 {ig_reels: true, fb_reels: true} 為 bool 格式 → 降 WARN（§14 P1）。
    """
    pv = data.get('platform_variants')
    if not pv:
        if _is_legacy_yaml(data):
            return "WARN", "缺 platform_variants（legacy 過渡期允許）"
        return "WARN", "缺 platform_variants（建議設定各平台特化 CTA / caption_keywords；試點/舊格式腳本允許空）"
    if not isinstance(pv, dict):
        return "FAIL", f"platform_variants 格式錯誤（應是 dict，實際：{type(pv).__name__}）"
    # 若全部 value 是 bool → 舊格式（瑞祥 {ig_reels: true}）→ WARN
    all_bool = all(isinstance(v, bool) for v in pv.values())
    if all_bool:
        enabled = [k for k, v in pv.items() if v]
        return "WARN", (
            f"platform_variants 是 bool 格式（啟用平台：{enabled}），"
            f"建議升級為 {{platform: {{cta, caption_keywords}}}} 格式"
        )
    # 至少 1 個平台有 cta 或 caption_keywords 或 reply_prompt
    valid_platforms = []
    for plat, cfg in pv.items():
        if not isinstance(cfg, dict):
            continue
        if cfg.get('cta') or cfg.get('caption_keywords') or cfg.get('reply_prompt'):
            valid_platforms.append(plat)
    if not valid_platforms:
        return "FAIL", "platform_variants 每個平台都空白（至少 1 個平台需填 cta / caption_keywords）"
    return "PASS", f"platform_variants 已填 {len(valid_platforms)} 個平台（{valid_platforms}）"


def chk_v2_005_trial_reels_consistency(data: dict, fname: str) -> tuple[str, str]:
    """V2-005：若 main_platform 含 IG，trial_reels 欄位應存在（一致性）"""
    mp = str(data.get('main_platform', ''))
    has_ig = 'IG' in mp or 'ig' in mp.lower()
    has_field = 'trial_reels' in data
    if not has_ig:
        return "PASS", "非 IG 主平台，trial_reels 非必要"
    if has_field:
        return "PASS", f"IG 主平台，trial_reels = {data['trial_reels']}"
    if _is_legacy_yaml(data):
        return "WARN", "IG 主平台建議補 trial_reels（legacy 過渡期允許缺）"
    return "WARN", "IG 主平台建議補 trial_reels（true=送 Trial Reels 測試流量 / false=直接推）"


# ════════════════════════════════════════════
# v3 新增 11 件 check（V2-006 ~ V2-016 + V2-007B）
# 對齊：2026-05-23 三審 16 盲點 + 業務員 9 批反向工程 + Codex×3 R3 Pareto 95% fallback
# ════════════════════════════════════════════

import difflib

# 4 強制位 keyword 對應表（V2-006）
REQUIRED_SLOTS = {
    "釣魚部":      ["釣魚", "fishing"],
    "毒舌正能量":  ["毒舌正能量", "毒舌"],
    "純雞湯":      ["純雞湯"],
    "Erika 拆解派": ["Erika", "拆解派", "教育型"],
}

# 昀臻醫療效能禁用詞（V2-012 — 對齊第 09 批算盤報告 20 條）
BEAUTY_MED_WORDS = [
    "發炎", "抗發炎", "修復", "治療", "根治", "痊癒", "處方",
    "屏障修復", "痘疤修復", "一定壞", "至少三年", "眼尾平了",
    "活化", "再生", "醫美等級", "醫療級", "藥用", "復原", "癒合", "炎症"
]

# 虛構故事信號詞（V2-011 — 仲豪/阿奇）
FICTION_SIGNAL_WORDS = ["有個客戶說", "曾經有個案例", "我朋友的客戶", "聽說有個", "傳說中的"]


def chk_v2_006_required_slot(yamls: list[tuple[Path, dict]]) -> tuple[str, str]:
    """V2-006：4 強制位覆蓋驗（釣魚/毒舌/雞湯/Erika）— batch-level
    Codex R1 盲點 4 修法：用 required_slot 欄位 / faction 含嗆辣派 ≠ 毒舌
    """
    valid = [(f, d) for f, d in yamls if "__parse_error__" not in d and "__schema_error__" not in d]
    found = {slot: [] for slot in REQUIRED_SLOTS}
    for f, data in valid:
        slot_field = str(data.get('required_slot', ''))
        type_field = str(data.get('type', ''))
        for slot, keywords in REQUIRED_SLOTS.items():
            if slot_field == slot:
                found[slot].append(f.name)
                continue
            for kw in keywords:
                if kw in type_field:
                    if f.name not in found[slot]:
                        found[slot].append(f.name)
                    break
        if data.get('is_fishing') and f.name not in found["釣魚部"]:
            found["釣魚部"].append(f.name)
        if data.get('is_chicken_soup') and f.name not in found["純雞湯"]:
            found["純雞湯"].append(f.name)
    missing = [s for s, files in found.items() if not files]
    if missing:
        return "FAIL", f"4 強制位缺 {len(missing)} 件：{missing}（建議 yaml 加 required_slot 欄位）"
    counts = {s: len(files) for s, files in found.items()}
    return "PASS", f"4 強制位齊備：{counts}"


def chk_v2_007_threads_seven(batch_dir: Path) -> tuple[str, str]:
    """V2-007：Threads 脆文 7 篇存在驗 — batch-level
    Glob *Threads*.md / *脆文*.md / threads_*.md，v2 優先
    """
    candidates = []
    for pattern in ['*Threads*.md', '*脆文*.md', 'threads_*.md']:
        candidates.extend(batch_dir.glob(pattern))
    candidates = sorted(set(candidates))
    if not candidates:
        return "FAIL", "批次目錄找不到 Threads 脆文檔（Glob: *Threads*.md / *脆文*.md / threads_*.md）"
    target = sorted(candidates, key=lambda p: ('v2' in p.name, p.stat().st_mtime), reverse=True)[0]
    try:
        text = target.read_text(encoding='utf-8')
    except Exception as e:
        return "FAIL", f"讀 {target.name} 失敗：{e}"
    threads_sections = re.findall(r'^## (?:Threads|脆文)\s*\d+', text, re.MULTILINE)
    count = len(threads_sections)
    if count < 7:
        return "FAIL", f"{target.name} 只找到 {count} 篇脆文（要 ≥ 7）"
    return "PASS", f"{target.name} 找到 {count} 篇脆文（≥ 7）"


def chk_v2_007b_standalone_threads(data: dict, fname: str) -> tuple[str, str]:
    """V2-007B：platform_variants.threads 衝突驗 — per-file
    standalone_threads_derivative=true 但 platform_variants.threads=false → WARN
    """
    pv = data.get('platform_variants', {})
    if not isinstance(pv, dict):
        return "PASS", "(no platform_variants)"
    threads_enabled = pv.get('threads')
    standalone = data.get('standalone_threads_derivative')
    if standalone and not threads_enabled:
        return "WARN", "standalone_threads_derivative=true 但 platform_variants.threads=false（建議改 threads=true）"
    return "PASS", f"threads={threads_enabled} / standalone={standalone}"


def chk_v2_008_used_titles_dedup(yamls: list[tuple[Path, dict]], owner: str) -> tuple[str, str]:
    """V2-008：已用題目去重驗 — batch-level
    fuzzy match ratio >= 0.65（Codex R1 surface 從 80% 降到 65% — 撞題實證）
    """
    pref_path = OWNER_PREF_PATHS.get(owner)
    if not pref_path:
        return "WARN", f"找不到 owner={owner} 的偏好路徑"
    used_titles_path = pref_path.parent / f"_{owner}已用題目.md"
    if not used_titles_path.exists():
        return "WARN", f"找不到 {used_titles_path.name}"
    used_text = used_titles_path.read_text(encoding='utf-8')
    used_titles = []
    for line in used_text.split('\n'):
        m = re.match(r'^-\s*#?\d*\s*\[[^\]]+\]\s*(.+?)$', line.strip())
        if m:
            used_titles.append(m.group(1).strip())
    if not used_titles:
        return "WARN", f"{used_titles_path.name} 沒抽到任何已用題目（解析錯）"
    valid = [(f, d) for f, d in yamls if "__parse_error__" not in d and "__schema_error__" not in d]
    hits = []
    THRESHOLD = 0.65
    for f, data in valid:
        title = str(data.get('title', '')).strip()
        if not title:
            continue
        for used in used_titles:
            ratio = difflib.SequenceMatcher(None, title, used).ratio()
            if ratio >= THRESHOLD:
                hits.append((f.name, title, used, round(ratio, 2)))
                break
    if hits:
        first = hits[0]
        return "FAIL", f"{len(hits)} 件撞題（fuzzy ≥ {THRESHOLD}）：{first[0]} '{first[1][:30]}' vs 已用 '{first[2][:30]}' ratio={first[3]}"
    return "PASS", f"已用題目 {len(used_titles)} 條，全 yaml 0 撞題（threshold={THRESHOLD}）"


def chk_v2_009_auditor_report(batch_dir: Path, owner: str) -> tuple[str, str]:
    """V2-009：算盤覆核報告存在驗 — batch-level
    WARN 若找不到 / owner=昀臻 升 FAIL（醫療詞強制算盤覆核）
    """
    candidates = []
    for pattern in ['*算盤*.md', '*覆核*.md', '*audit*.md']:
        candidates.extend(batch_dir.glob(pattern))
    if candidates:
        return "PASS", f"找到 {len(candidates)} 個算盤覆核報告"
    if owner == '昀臻':
        return "FAIL", "昀臻（美容業）無算盤覆核報告（醫療詞強制覆核）"
    return "WARN", "找不到算盤覆核報告（建議補 _算盤覆核報告.md）"


def chk_v2_010_batch_summary(batch_dir: Path) -> tuple[str, str]:
    """V2-010：批次摘要文件存在驗 — batch-level WARN"""
    candidates = []
    for pattern in ['*摘要*.md', '*README*.md', '*overview*.md', '_批次摘要*.md', '_總覽*.md']:
        candidates.extend(batch_dir.glob(pattern))
    if candidates:
        return "PASS", f"找到 {len(candidates)} 個摘要文件"
    return "WARN", "找不到批次摘要（建議補 _批次摘要.md）"


def chk_v2_011_no_fiction(data: dict, fname: str, owner: str) -> tuple[str, str]:
    """V2-011：禁虛構故事驗 — per-file（仲豪/阿奇 特化）"""
    if owner not in ('仲豪', '阿奇'):
        return "PASS", "(非仲豪/阿奇，跳過)"
    sc = data.get('schema_check', {})
    if isinstance(sc, dict):
        no_fiction = sc.get('禁虛構')
        if no_fiction is False:
            return "FAIL", f"{owner} schema_check.禁虛構=false（仲豪 §11.4 / 阿奇 強制 true）"
    all_text = get_all_text(data)
    hits = [w for w in FICTION_SIGNAL_WORDS if w in all_text]
    if hits:
        return "FAIL", f"{owner} 台詞含虛構信號詞：{hits}"
    return "PASS", f"{owner} 禁虛構驗 PASS"


def chk_v2_012_beauty_med_words(data: dict, fname: str, owner: str) -> tuple[str, str]:
    """V2-012：昀臻醫療效能禁用詞驗 — per-file（昀臻 特化）"""
    if owner != '昀臻':
        return "PASS", "(非昀臻，跳過)"
    all_text = get_all_text(data)
    hits = [w for w in BEAUTY_MED_WORDS if w in all_text]
    if hits:
        return "FAIL", f"昀臻台詞含醫療效能禁用詞：{hits[:5]}（對齊第 09 批算盤 20 條）"
    return "PASS", "昀臻醫療詞驗 PASS"


def chk_v2_013_zhonghao_life_ratio(yamls: list[tuple[Path, dict]], owner: str) -> tuple[str, str]:
    """V2-013：仲豪生活/房仲字數比驗 — batch-level（仲豪 特化）
    生活字數 / 房仲字數 >= 3.0 (76%+)
    """
    if owner != '仲豪':
        return "PASS", "(非仲豪，跳過)"
    valid = [(f, d) for f, d in yamls if "__parse_error__" not in d and "__schema_error__" not in d]
    life_chars = 0
    realty_chars = 0
    for f, data in valid:
        type_field = str(data.get('type', ''))
        all_text = get_all_text(data)
        char_count = len(all_text)
        if '生活' in type_field:
            life_chars += char_count
        elif '房仲' in type_field:
            realty_chars += char_count
    if realty_chars == 0:
        return "PASS", f"仲豪批次無房仲類腳本（生活字數 {life_chars}）"
    ratio = life_chars / realty_chars
    if ratio < 3.0:
        return "FAIL", f"仲豪生活/房仲字數比 {ratio:.2f} < 3.0（生活 {life_chars} / 房仲 {realty_chars}）"
    return "PASS", f"仲豪生活/房仲字數比 {ratio:.2f} >= 3.0"


def chk_v2_014_bappu_taboo(data: dict, fname: str, owner: str) -> tuple[str, str]:
    """V2-014：叭噗禁忌題材驗 — per-file（叭噗 特化）
    Codex R1 盲點 11 修法：用 schema_check 欄位（不 grep 上下文避誤殺）
    """
    if owner != '叭噗_小C':
        return "PASS", "(非叭噗，跳過)"
    sc = data.get('schema_check', {})
    if not isinstance(sc, dict):
        if _is_legacy_yaml(data):
            return "WARN", "叭噗 缺 schema_check（legacy 過渡期）"
        return "FAIL", "叭噗 缺 schema_check 欄位"
    fails = []
    for key in ['禁業配', '禁引流房仲', '禁媽媽題材']:
        if sc.get(key) is False:
            fails.append(f"{key}=false")
    if fails:
        return "FAIL", f"叭噗 schema_check 違規：{fails}"
    return "PASS", "叭噗禁忌題材 schema_check 驗 PASS"


def chk_v2_015_bappu_q1q2q3(data: dict, fname: str, owner: str) -> tuple[str, str]:
    """V2-015：叭噗知識反差三標準驗 — per-file（叭噗 特化）"""
    if owner != '叭噗_小C':
        return "PASS", "(非叭噗，跳過)"
    faction = str(data.get('faction', ''))
    if '知識反差' not in faction:
        return "PASS", "(非知識反差派系，跳過)"
    l2_check = data.get('L2_判斷標準') or data.get('l2_judgment')
    if not l2_check or not isinstance(l2_check, dict):
        return "FAIL", "叭噗知識反差派缺 L2_判斷標準"
    missing = [q for q in ['q1', 'q2', 'q3'] if not l2_check.get(q)]
    if missing:
        return "FAIL", f"叭噗知識反差 L2_判斷標準缺 {missing}"
    return "PASS", "叭噗知識反差 q1/q2/q3 全填"


def chk_v2_016_trial_observe_until(data: dict, fname: str, owner: str) -> tuple[str, str]:
    """V2-016：試水批 observe_until 存在驗 — per-file
    Codex R1 盲點 5 修法：owner=叭噗_小C AND batch_tag含試水 強制 / 其他業主 WARN
    """
    batch_tag = str(data.get('batch_tag', '') or data.get('batch_label', ''))
    if '試水' not in batch_tag:
        return "PASS", "(非試水批，跳過)"
    fails = [k for k in ['observe_until', 'review_kpi', 'override_reason'] if not data.get(k)]
    if not fails:
        return "PASS", "試水批 3 欄齊"
    if owner == '叭噗_小C':
        return "FAIL", f"叭噗試水批缺：{fails}"
    return "WARN", f"{owner} 試水批建議補：{fails}（限叭噗強制）"


# ════════════════════════════════════════════
# V2-025 / V2-026 — 爆款範本引用驗（§12.3 強制餵範本系統）
# V2-025：template_source_ids 必須存在且存在於 template_index.jsonl（FAIL）
# V2-026：template_adaptation 完整驗（WARN→2批後FAIL）
# ════════════════════════════════════════════

# template_index.jsonl 路徑（singleton 快取，避免每筆 yaml 都重複讀檔）
_TEMPLATE_INDEX_PATH = Path(__file__).parent / "template_index.jsonl"
_TEMPLATE_INDEX_CACHE: Optional[set] = None  # set of template_id

# 2026-06-01 新批強制日（V2-025 legacy 過渡截止）
_V2_025_CUTOFF = _dt.date(2026, 6, 1)

# P1-3：strict 模式旗標（由 main() 設定，讓 check fn 讀取）
_STRICT_MODE: bool = False


def _extract_batch_date(data: dict, fname: str = '') -> Optional[_dt.date]:
    """從 yaml 欄位或批次目錄名抓批次日期，供 V2-025 legacy 判斷。

    收集**所有**日期候選，取最大（最新）日期，防止複製舊 yaml 到新批目錄時
    舊 yaml 欄位日期繞過新批強制（P1 繞過洞修復）。

    支援多格式：YYYY-MM-DD、YYYY/MM/DD、YYYYMMDD、YYYY_MM_DD（P2 多格式修復）

    目錄名日期 >= 2026-06-01 時強制視為新批（雙重保護）：
    即使 yaml 欄位含舊日期，只要目錄名是新批，仍走強制路徑。
    """
    # P2：支援多格式 regex
    # 先嘗試 YYYY-MM-DD / YYYY/MM/DD / YYYY_MM_DD（分隔符版本）
    DATE_RE_SEP = re.compile(r'(\d{4})[-/_ ](\d{2})[-/_ ](\d{2})')
    # 再嘗試 YYYYMMDD（無分隔，需邊界避免誤吃流水號）
    DATE_RE_COMPACT = re.compile(r'(?<!\d)(\d{4})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)')

    def _try_parse(text: str) -> Optional[_dt.date]:
        s = str(text)
        # 分隔符版本優先
        m = DATE_RE_SEP.search(s)
        if m:
            try:
                return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
        # 緊湊版本（YYYYMMDD）
        m2 = DATE_RE_COMPACT.search(s)
        if m2:
            try:
                return _dt.date(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
            except ValueError:
                pass
        return None

    # P1 修復：收集所有候選，取最大值
    candidates: list[_dt.date] = []

    # yaml 欄位候選
    for key in ('batch_date', 'batch_tag', 'batch_label', 'generated_at', 'batch'):
        val = data.get(key)
        if val:
            d = _try_parse(val)
            if d:
                candidates.append(d)

    # fname 候選（run_per_file_checks 傳入 "批次目錄名/檔名"，目錄名含日期）
    if fname:
        d = _try_parse(fname)
        if d:
            candidates.append(d)

    if not candidates:
        return None

    # P1 修復核心：取最大（最新）日期，防止舊欄位日期蓋過新批目錄日期
    return max(candidates)


def _is_v2025_legacy(data: dict, fname: str = '') -> bool:
    """判斷是否為 V2-025 legacy 批次（批次日期 < 2026-06-01）。

    True  → 既有批次，V2-025 缺 template_source_ids 只 WARN（過渡期）
    False → 新批次或無法判斷，V2-025 缺 template_source_ids → FAIL（強制）
    """
    batch_date = _extract_batch_date(data, fname)
    if batch_date is None:
        return False  # 無法判斷 → 保守當新批 FAIL
    return batch_date < _V2_025_CUTOFF


def _load_template_index_ids() -> Optional[set]:
    """讀 template_index.jsonl 回傳 template_id set（快取）"""
    global _TEMPLATE_INDEX_CACHE
    if _TEMPLATE_INDEX_CACHE is not None:
        return _TEMPLATE_INDEX_CACHE
    if not _TEMPLATE_INDEX_PATH.exists():
        return None  # index 不存在 → WARN 不 FAIL
    ids = set()
    try:
        import json as _json
        with _TEMPLATE_INDEX_PATH.open(encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    card = _json.loads(line)
                    if 'template_id' in card:
                        ids.add(card['template_id'])
    except Exception:
        return None
    _TEMPLATE_INDEX_CACHE = ids
    return ids


def chk_v2_025_template_source_required(data: dict, fname: str) -> tuple[str, str]:
    """V2-025：template_source_ids 必填，且每個 id 存在於 template_index.jsonl（FAIL）

    腳本 yaml 必填 template_source_ids（list of template_id），
    且每個 id 必須對得到 template_index.jsonl 中的卡。
    template_index.jsonl 不存在 → WARN（建置期容忍）。

    例外：腳本 yaml 含 control_group: true → 豁免本檢查（對照組不套範本，無需 template_source_ids）。

    接 canonical：用 normalize_script_to_canonical 讀 template_sources（若已有），
    否則直接讀 data['template_source_ids']（未來格式）。
    """
    # 對照組豁免：control_group: true → 直接放行
    if data.get('control_group') is True:
        return "PASS", "[CONTROL] 對照組腳本，豁免範本來源檢查"

    # 嘗試從 canonical 層讀（§12.3 canonical 加 template_sources 欄位，當前尚未部署時 fallback 直讀）
    source_ids = None
    if _CANONICAL_AVAILABLE and _normalize_canonical is not None:
        try:
            canonical = _normalize_canonical(data)
            # canonical 目前版本還沒有 template_sources（§14 P2，待下批加），
            # 但保留此路徑供未來擴展；現在直接讀 data 層
            ts_from_canonical = canonical.get('template_sources')
            if ts_from_canonical and isinstance(ts_from_canonical, list):
                source_ids = ts_from_canonical
        except Exception:
            pass

    if source_ids is None:
        # 直讀 raw data（現在的欄位名）
        source_ids = data.get('template_source_ids')

    if not source_ids:
        # V2-025 legacy 過渡：批次日期 < 2026-06-01 → WARN；新批 → FAIL
        if _is_v2025_legacy(data, fname):
            return "WARN", (
                "[LEGACY] 既有批次過渡期豁免，2026-06-01 後新批強制填 template_source_ids"
            )
        return "FAIL", "缺 template_source_ids（必須填入 3-5 張範本卡 id，照 §12.3 強制餵範本系統）"

    if not isinstance(source_ids, list):
        return "FAIL", f"template_source_ids 格式錯誤（應是 list，實際：{type(source_ids).__name__}）"

    # P1-2：數量限制（非對照組必須 3-5 張，且無重複 id）
    # legacy 批次（batch_date < 2026-06-01）→ 數量/重複問題一律 WARN（過渡期不擋死既有業主）
    # 新批（>= 2026-06-01）→ FAIL（強制）
    unique_ids = list(dict.fromkeys(source_ids))  # 保序去重
    if len(unique_ids) != len(source_ids):
        dup = [tid for tid in source_ids if source_ids.count(tid) > 1]
        if _is_v2025_legacy(data, fname):
            return "WARN", (
                f"[LEGACY] template_source_ids 有重複 id（{list(set(dup))}）— "
                f"既有批次過渡期豁免，2026-06-01 後新批強制不得重複"
            )
        return "FAIL", (
            f"template_source_ids 有重複 id（{list(set(dup))}）— 每張範本只能引用一次"
        )
    if not (3 <= len(unique_ids) <= 5):
        if _is_v2025_legacy(data, fname):
            return "WARN", (
                f"[LEGACY] template_source_ids 需填 3-5 張（目前 {len(unique_ids)} 張）— "
                f"既有批次過渡期豁免，2026-06-01 後新批強制 3-5 張"
            )
        return "FAIL", (
            f"template_source_ids 需填 3-5 張（目前 {len(unique_ids)} 張）— "
            f"照 §12.3 強制餵 3-5 張範本卡"
        )

    # 驗每個 id 是否存在於 template_index.jsonl
    known_ids = _load_template_index_ids()
    if known_ids is None:
        # P1-3：strict 模式 + 新批（>= 2026-06-01）→ FAIL；其餘 WARN
        if _STRICT_MODE and not _is_v2025_legacy(data, fname):
            return "FAIL", (
                f"template_source_ids 已填（{source_ids}），但 template_index.jsonl 缺失或損壞 — "
                f"strict 模式新批必須先跑 build_template_index.py 建索引才能通過"
            )
        return "WARN", (
            f"template_source_ids 已填（{source_ids}），但 template_index.jsonl 不存在 — "
            f"請先跑 build_template_index.py 建索引（建立前暫 WARN）"
        )

    missing_ids = [tid for tid in source_ids if tid not in known_ids]
    if missing_ids:
        return "FAIL", (
            f"template_source_ids 有 {len(missing_ids)} 個 id 不存在於 template_index.jsonl："
            f"{missing_ids}（請確認 id 正確，或重跑 build_template_index.py 更新索引）"
        )

    return "PASS", f"template_source_ids 已填 {len(source_ids)} 張，全在索引中"


def _is_placeholder(val) -> bool:
    """判斷一個值是否為 skeleton 產生的 placeholder（未實際填寫）。

    placeholder 清單：'[編劇填]' / 'pending' / 'todo' / '待填' / 空字串 / 純空白。
    比對前先 strip + lower。
    另外：skeleton 產出的值常帶行內 comment（e.g. '[編劇填]  # 說明'），
    只要字串以 placeholder 關鍵字為「前半段」（空白/# 之前）即視為 placeholder。
    """
    if val is None:
        return True
    s = str(val).strip()
    if not s:
        return True
    # 取 comment 前的有效部份（以 '#' 或空白分割取第一段）
    token = re.split(r'[\s#]', s)[0].lower()
    return token in ('[編劇填]', 'pending', 'todo', '待填')


def chk_v2_026_template_adaptation_required(data: dict, fname: str) -> tuple[str, str]:
    """V2-026：template_adaptation 完整驗

    對齊 V2-025 cutoff 邏輯（_V2_025_CUTOFF = 2026-06-01）：
    - legacy 批次（批次日期 < 2026-06-01）：缺欄位 / placeholder / forbidden_copy_check 未過 → WARN
    - 非 legacy（新批次或無法判斷）：缺欄位 / placeholder / forbidden_copy_check 未過 → FAIL

    template_adaptation 欄位應包含：
      learned_structure：從範本學到的骨架邏輯（必填，不可為 placeholder）
      changed_context：換成業主情境的說明（必填，不可為 placeholder）
      forbidden_copy_check：需為 PASS / passed / true（不分大小寫）
    """
    is_legacy = _is_v2025_legacy(data, fname)

    def _make_result(has_issues: bool, issues: list[str]) -> tuple[str, str]:
        """根據 legacy 狀態決定 WARN 或 FAIL"""
        if not has_issues:
            return "PASS", "template_adaptation 已填 learned_structure + changed_context（forbidden_copy_check OK）"
        msg_base = "template_adaptation 未完整：" + "；".join(issues)
        if is_legacy:
            return "WARN", msg_base + "（legacy 批次過渡期）"
        return "FAIL", msg_base + "（新批次強制 — 2026-06-01 起必須完整填寫）"

    adapt = data.get('template_adaptation')

    if not adapt:
        issues = [
            "缺 template_adaptation（建議填 learned_structure + changed_context，"
            "說明從範本學到什麼 / 如何改成業主情境）"
        ]
        return _make_result(True, issues)

    if not isinstance(adapt, dict):
        issues = [f"template_adaptation 格式錯誤（應是 dict，實際：{type(adapt).__name__}）"]
        return _make_result(True, issues)

    # 檢查 learned_structure / changed_context：缺欄位 或 值為 placeholder → 視為 missing
    placeholder_fields = []
    missing_fields = []
    for k in ('learned_structure', 'changed_context'):
        v = adapt.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            missing_fields.append(k)
        elif _is_placeholder(v):
            placeholder_fields.append(k)

    issues = []
    if missing_fields:
        issues.append(
            f"缺欄位 {missing_fields}（learned_structure=從範本學到的結構邏輯 / "
            f"changed_context=換成業主情境的說明）"
        )
    if placeholder_fields:
        issues.append(
            f"{placeholder_fields} 仍為 skeleton placeholder（'[編劇填]'/'pending' 等），請實際填寫"
        )

    # 檢查 forbidden_copy_check：需為 PASS / passed / true
    fcc = adapt.get('forbidden_copy_check')
    if fcc is not None:
        fcc_ok = str(fcc).strip().lower() in ('pass', 'passed', 'true')
        if not fcc_ok:
            issues.append(
                f"forbidden_copy_check='{fcc}' 未過（需改為 PASS 後才算確認無直接複製）"
            )

    return _make_result(bool(issues), issues)


# ────────────────────────────────────────────
# 跑單一 yaml 的 12 件 per-file checks
# ────────────────────────────────────────────
def run_per_file_checks(f: Path, data: dict, owner: str) -> list[tuple[str, str, str, str]]:
    """回傳 [(check_id, status, desc, detail), ...]
    v2 升級：加 V2-001 ~ V2-005（yaml schema 新欄位驗）
    """
    # P1-1：傳入「批次目錄名/檔名」讓 _extract_batch_date 能從目錄名（如第34批_試水批_2026-05-23）抓日期
    _fname_with_dir = f"{f.parent.name}/{f.name}"
    results = []
    checks = [
        # 原 15 件
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
        # v2 新增 5 件（V2-001 ~ V2-005）
        ("V2-001", chk_v2_001_voice_lock(data, f.name)),
        ("V2-002", chk_v2_002_policy_alignment(data, f.name, owner)),
        ("V2-003", chk_v2_003_publish_distribution_mode(data, f.name)),
        ("V2-004", chk_v2_004_platform_variants(data, f.name)),
        ("V2-005", chk_v2_005_trial_reels_consistency(data, f.name)),
        # v3 新增 6 件（2026-05-23 三審修補）
        ("V2-007B", chk_v2_007b_standalone_threads(data, f.name)),
        ("V2-011",  chk_v2_011_no_fiction(data, f.name, owner)),
        ("V2-012",  chk_v2_012_beauty_med_words(data, f.name, owner)),
        ("V2-014",  chk_v2_014_bappu_taboo(data, f.name, owner)),
        ("V2-015",  chk_v2_015_bappu_q1q2q3(data, f.name, owner)),
        ("V2-016",  chk_v2_016_trial_observe_until(data, f.name, owner)),
        # v4 新增 2 件（2026-05-31 爆款範本引用系統）
        # P1-1：V2-025 改傳 _fname_with_dir 讓日期解析能吃批次目錄名
        ("V2-025",  chk_v2_025_template_source_required(data, _fname_with_dir)),
        ("V2-026",  chk_v2_026_template_adaptation_required(data, _fname_with_dir)),
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

    # P1-3：設模組旗標讓 check fn 知道是否 strict
    global _STRICT_MODE
    _STRICT_MODE = args.strict

    batch_dir = Path(args.batch_dir)
    if not batch_dir.exists():
        print(f"[ERROR] batch-dir 不存在：{batch_dir}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  腳本批次品管員 v2.0（20 件自動擋 — 含 V2 schema 升級）")
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

    # ── Batch-level checks（L1-008 / L1-009 / C-011 / C-012 / C-014 + v3 新 6 件）──
    batch_checks = [
        ("L1-008", chk_l1_008_batch_count(yamls, batch_dir)),
        ("L1-009", chk_l1_009_派系_coverage(valid_yamls)),
        ("C-011",  chk_c011_派系_ratio(valid_yamls, owner, pref_text)),
        ("C-012",  chk_c012_identity_ratio(valid_yamls, owner, pref_text)),
        ("C-014",  chk_c014_card_style(batch_dir, owner, batch_tag)),
        # v3 新增 6 件 batch checks（2026-05-23 三審修補）
        ("V2-006", chk_v2_006_required_slot(valid_yamls)),
        ("V2-007", chk_v2_007_threads_seven(batch_dir)),
        ("V2-008", chk_v2_008_used_titles_dedup(valid_yamls, owner)),
        ("V2-009", chk_v2_009_auditor_report(batch_dir, owner)),
        ("V2-010", chk_v2_010_batch_summary(batch_dir)),
        ("V2-013", chk_v2_013_zhonghao_life_ratio(valid_yamls, owner)),
    ]
    print("── 批次級 check（11 件）──")
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
    # 如果帶 --fixtures 參數跑 5 組 migration fixtures test（不需要 batch-dir）
    if "--fixtures" in sys.argv:
        # ── 5 組 fixtures test（Migration Plan 驗）──
        print("\n=== validate_script_batch.py V2 Fixtures Test（5 組）===\n")

        PASS_COUNT = 0
        FAIL_COUNT = 0

        def fcheck(label: str, condition: bool, detail: str = ''):
            global PASS_COUNT, FAIL_COUNT
            if condition:
                print(f"  [PASS] {label}")
                PASS_COUNT += 1
            else:
                print(f"  [FAIL] {label}{(' — ' + detail) if detail else ''}")
                FAIL_COUNT += 1

        # ── F1 pass：含全新欄位 → 全 PASS ──
        print("[F1] 含全新欄位 → V2 checks 全 PASS")
        f1 = {
            'title': 'F1測試',
            '派系': '直球派',
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_阿奇': '測試', '畫面': '測試'}],
            'caption': '測試 caption',
            'hashtag': ['#test'],
            'main_platform': 'IG Reels',
            'voice_lock': True,
            'policy_alignment': {'ig': ['DM Sends 優先', 'Trial Reels 開啟'], 'fb': ['當日上傳 +50%']},
            'trial_reels': True,
            'publish_mode': 'manual_today',
            'distribution_mode': 'organic_only',
            'platform_variants': {'ig': {'cta': '留言諮詢', 'caption_keywords': ['高雄']}, 'threads': {'reply_prompt': '你覺得呢？'}},
        }
        _f1_path = Path('/fake/f1.yaml')
        r1 = chk_v2_001_voice_lock(f1, 'f1.yaml')
        fcheck('F1 V2-001 PASS', r1[0] == 'PASS', r1[1])
        r2 = chk_v2_002_policy_alignment(f1, 'f1.yaml', '阿奇')
        fcheck('F1 V2-002 PASS', r2[0] == 'PASS', r2[1])
        r3 = chk_v2_003_publish_distribution_mode(f1, 'f1.yaml')
        fcheck('F1 V2-003 PASS', r3[0] == 'PASS', r3[1])
        r4 = chk_v2_004_platform_variants(f1, 'f1.yaml')
        fcheck('F1 V2-004 PASS', r4[0] == 'PASS', r4[1])
        r5 = chk_v2_005_trial_reels_consistency(f1, 'f1.yaml')
        fcheck('F1 V2-005 PASS', r5[0] == 'PASS', r5[1])

        # ── F2 missing_field：缺 distribution_mode → FAIL ──
        print("\n[F2] 缺 distribution_mode → V2-003 FAIL")
        f2 = dict(f1)
        del f2['distribution_mode']
        r = chk_v2_003_publish_distribution_mode(f2, 'f2.yaml')
        fcheck('F2 V2-003 FAIL', r[0] == 'FAIL', r[1])

        # ── F3 legacy：含 legacy_allowed_until → WARN 不 FAIL ──
        print("\n[F3] legacy yaml（legacy_allowed_until: 2026-06-01）→ V2 checks WARN 不 FAIL")
        f3 = {
            'title': 'F3 legacy',
            '派系': '直球派',
            'main_platform': 'IG Reels',
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_瑞祥': '測試', '畫面': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
            'legacy_allowed_until': '2026-06-01',  # 過渡期
        }
        r1 = chk_v2_001_voice_lock(f3, 'f3.yaml')
        fcheck('F3 V2-001 WARN（不 FAIL）', r1[0] == 'WARN', r1[1])
        r3 = chk_v2_003_publish_distribution_mode(f3, 'f3.yaml')
        fcheck('F3 V2-003 WARN（不 FAIL）', r3[0] == 'WARN', r3[1])
        r4 = chk_v2_004_platform_variants(f3, 'f3.yaml')
        fcheck('F3 V2-004 WARN（不 FAIL）', r4[0] == 'WARN', r4[1])

        # ── F4 platform_variants：含 platform_variants 驗格式 ──
        print("\n[F4] platform_variants 全空 dict → FAIL（不含任何 cta/keywords）")
        f4 = dict(f1)
        f4['platform_variants'] = {'ig': {}, 'fb': {}}  # 空 config
        r = chk_v2_004_platform_variants(f4, 'f4.yaml')
        fcheck('F4 V2-004 FAIL（全空）', r[0] == 'FAIL', r[1])

        # ── F5 beauty_violation：昀臻 policy_alignment 缺 Meta D-2 → WARN ──
        print("\n[F5] 昀臻 policy_alignment 缺 Meta D-2 → V2-002 WARN")
        f5 = dict(f1)
        f5['policy_alignment'] = {'ig': ['DM Sends 優先']}  # 缺 D-2
        r = chk_v2_002_policy_alignment(f5, 'f5.yaml', '昀臻')
        fcheck('F5 V2-002 WARN（美容業缺 D-2）', r[0] == 'WARN', r[1])

        # ── F6 V2-025：缺 template_source_ids → FAIL ──
        print("\n[F6] 缺 template_source_ids → V2-025 FAIL")
        f6_no_ids = {
            'title': 'F6 缺 template_source_ids',
            '派系': '直球派',
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_阿奇': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
        }
        r = chk_v2_025_template_source_required(f6_no_ids, 'f6.yaml')
        fcheck('F6 V2-025 FAIL（缺 template_source_ids）', r[0] == 'FAIL', r[1])

        # ── F7 V2-025：template_source_ids 填了但 index 不存在 → WARN ──
        print("\n[F7] template_source_ids 已填、index 不存在 → V2-025 WARN")
        # 暫時清除快取（測試隔離）
        import validate_script_batch as _self_mod
        _saved_cache = _self_mod._TEMPLATE_INDEX_CACHE
        _saved_path = _self_mod._TEMPLATE_INDEX_PATH
        # 指向不存在的路徑
        _self_mod._TEMPLATE_INDEX_PATH = Path('/nonexistent/template_index.jsonl')
        _self_mod._TEMPLATE_INDEX_CACHE = None

        f7_with_ids = {
            'title': 'F7 有 template_source_ids',
            '派系': '直球派',
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_阿奇': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
            # P1-2 修：補到 3 張（數量 OK）才能進到 index 不存在判斷
            'template_source_ids': ['tmpl_abc123', 'tmpl_def456', 'tmpl_ghi789'],
        }
        r = _self_mod.chk_v2_025_template_source_required(f7_with_ids, 'f7.yaml')
        fcheck('F7 V2-025 WARN（index 不存在）', r[0] == 'WARN', r[1])

        # 還原快取路徑
        _self_mod._TEMPLATE_INDEX_PATH = _saved_path
        _self_mod._TEMPLATE_INDEX_CACHE = _saved_cache

        # ── F8 V2-025：template_source_ids 有 id 不在 index → FAIL ──
        print("\n[F8] template_source_ids 有 id 不在 index → V2-025 FAIL")
        import json as _json_mod
        import tempfile, os as _os
        _tmp_dir = tempfile.mkdtemp()
        _tmp_index = Path(_tmp_dir) / "template_index.jsonl"
        # P1-2 修：index 建 3 張已知 id，F8/F9 data 補到 3 張以上才能進 index 驗
        _tmp_index.write_text(
            _json_mod.dumps({"template_id": "tmpl_known_001", "platform": "IG"}, ensure_ascii=False) + '\n' +
            _json_mod.dumps({"template_id": "tmpl_known_002", "platform": "IG"}, ensure_ascii=False) + '\n' +
            _json_mod.dumps({"template_id": "tmpl_known_003", "platform": "IG"}, ensure_ascii=False) + '\n',
            encoding='utf-8'
        )
        _self_mod._TEMPLATE_INDEX_PATH = _tmp_index
        _self_mod._TEMPLATE_INDEX_CACHE = None

        f8_bad_ids = {
            'title': 'F8 有無效 id',
            '派系': '直球派',
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_阿奇': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
            # P1-2 修：3 張（數量 OK），其中 1 張不在 index → FAIL
            'template_source_ids': ['tmpl_known_001', 'tmpl_known_002', 'tmpl_NOT_EXIST'],
        }
        r = _self_mod.chk_v2_025_template_source_required(f8_bad_ids, 'f8.yaml')
        fcheck('F8 V2-025 FAIL（有 id 不在 index）', r[0] == 'FAIL', r[1])

        # ── F9 V2-025：全部 id 都在 index → PASS ──
        print("\n[F9] template_source_ids 全在 index → V2-025 PASS")
        f9_good_ids = dict(f8_bad_ids)
        # P1-2 修：3 張全在 index → PASS
        f9_good_ids['template_source_ids'] = ['tmpl_known_001', 'tmpl_known_002', 'tmpl_known_003']
        r = _self_mod.chk_v2_025_template_source_required(f9_good_ids, 'f9.yaml')
        fcheck('F9 V2-025 PASS（全在 index）', r[0] == 'PASS', r[1])

        # 還原路徑 + 清理暫存
        _self_mod._TEMPLATE_INDEX_PATH = _saved_path
        _self_mod._TEMPLATE_INDEX_CACHE = _saved_cache
        try:
            _tmp_index.unlink()
            _os.rmdir(_tmp_dir)
        except Exception:
            pass

        # ── F10 V2-026：缺 template_adaptation，無日期 → 新批保守 FAIL ──
        print("\n[F10] 缺 template_adaptation，fname 無日期 → V2-026 FAIL（無日期=新批強制）")
        f10_no_adapt = {
            'title': 'F10 缺 adaptation',
            'template_source_ids': ['tmpl_abc'],
        }
        r = chk_v2_026_template_adaptation_required(f10_no_adapt, 'f10.yaml')
        fcheck('F10 V2-026 FAIL（無日期=新批強制）', r[0] == 'FAIL', r[1])

        # ── F10L V2-026 legacy：缺 template_adaptation，fname 含 < 6/1 日期 → WARN ──
        print("\n[F10L] 缺 template_adaptation，fname 含 2026-05-20（< 6/1）→ V2-026 WARN（legacy 過渡）")
        r = chk_v2_026_template_adaptation_required(f10_no_adapt, '第30批_2026-05-20/f10L.yaml')
        fcheck('F10L V2-026 WARN（legacy 過渡，fname 含 < 6/1 日期）', r[0] == 'WARN', r[1])

        # ── F11 V2-026：template_adaptation 缺 changed_context，無日期 → 新批保守 FAIL ──
        print("\n[F11] template_adaptation 缺 changed_context，fname 無日期 → V2-026 FAIL（無日期=新批強制）")
        f11_partial_adapt = {
            'title': 'F11 adaptation 不完整',
            'template_source_ids': ['tmpl_abc'],
            'template_adaptation': {
                'learned_structure': '反差 hook + 案例收束',
                # 缺 changed_context
            },
        }
        r = chk_v2_026_template_adaptation_required(f11_partial_adapt, 'f11.yaml')
        fcheck('F11 V2-026 FAIL（無日期=新批強制）', r[0] == 'FAIL', r[1])

        # ── F11L V2-026 legacy：缺 changed_context，fname 含 < 6/1 日期 → WARN ──
        print("\n[F11L] template_adaptation 缺 changed_context，fname 含 2026-05-20（< 6/1）→ V2-026 WARN（legacy 過渡）")
        r = chk_v2_026_template_adaptation_required(f11_partial_adapt, '第30批_2026-05-20/f11L.yaml')
        fcheck('F11L V2-026 WARN（legacy 過渡，fname 含 < 6/1 日期）', r[0] == 'WARN', r[1])

        # ── F12 V2-026：template_adaptation 完整 → PASS ──
        print("\n[F12] template_adaptation 完整 → V2-026 PASS")
        f12_full_adapt = {
            'title': 'F12 adaptation 完整',
            'template_source_ids': ['tmpl_abc'],
            'template_adaptation': {
                'learned_structure': '反差 hook：先說反常觀點，用案例說明',
                'changed_context': '把「帶看」換成「瑞祥帶看豐原日出段的故事」',
            },
        }
        r = chk_v2_026_template_adaptation_required(f12_full_adapt, 'f12.yaml')
        fcheck('F12 V2-026 PASS（完整 adaptation）', r[0] == 'PASS', r[1])

        # ── F13 V2-025：template_source_ids 是空 list → FAIL ──
        print("\n[F13] template_source_ids 空 list → V2-025 FAIL")
        f13_empty_ids = {
            'title': 'F13 空 list',
            'template_source_ids': [],
        }
        r = chk_v2_025_template_source_required(f13_empty_ids, 'f13.yaml')
        fcheck('F13 V2-025 FAIL（空 list）', r[0] == 'FAIL', r[1])

        # ── F14 V2-026：template_adaptation 是 str，無日期 → 新批保守 FAIL ──
        print("\n[F14] template_adaptation 是 str，fname 無日期 → V2-026 FAIL（無日期=新批強制）")
        f14_str_adapt = {
            'title': 'F14 adaptation str',
            'template_source_ids': ['tmpl_abc'],
            'template_adaptation': '隨便說一下',
        }
        r = chk_v2_026_template_adaptation_required(f14_str_adapt, 'f14.yaml')
        fcheck('F14 V2-026 FAIL（無日期=新批強制）', r[0] == 'FAIL', r[1])

        # ── F14L V2-026 legacy：adaptation 是 str，fname 含 < 6/1 日期 → WARN ──
        print("\n[F14L] template_adaptation 是 str，fname 含 2026-05-20（< 6/1）→ V2-026 WARN（legacy 過渡）")
        r = chk_v2_026_template_adaptation_required(f14_str_adapt, '第30批_2026-05-20/f14L.yaml')
        fcheck('F14L V2-026 WARN（legacy 過渡，fname 含 < 6/1 日期）', r[0] == 'WARN', r[1])

        # ── F14b V2-026：learned_structure 是 placeholder '[編劇填]'，無日期 → FAIL ──
        print("\n[F14b] learned_structure=[編劇填]（skeleton placeholder），fname 無日期 → V2-026 FAIL（無日期=新批強制）")
        f14b_placeholder = {
            'title': 'F14b adaptation placeholder',
            'template_source_ids': ['tmpl_abc'],
            'template_adaptation': {
                'learned_structure': '[編劇填]  # 從範本學到的結構，e.g. 反差 hook + 案例收束',
                'changed_context': '[編劇填]  # 把範本情境換成本批，e.g. 把帶看換成瑞祥帶看日出段',
                'forbidden_copy_check': 'pending',
            },
        }
        r = chk_v2_026_template_adaptation_required(f14b_placeholder, 'f14b.yaml')
        fcheck('F14b V2-026 FAIL（無日期=新批強制）且 placeholder 在訊息中',
               r[0] == 'FAIL' and 'placeholder' in r[1], r[1])

        # ── F14bL V2-026 legacy：placeholder，fname 含 < 6/1 日期 → WARN + placeholder 在訊息 ──
        print("\n[F14bL] learned_structure=[編劇填]（placeholder），fname 含 2026-05-20（< 6/1）→ V2-026 WARN（legacy 過渡）")
        r = chk_v2_026_template_adaptation_required(f14b_placeholder, '第30批_2026-05-20/f14bL.yaml')
        fcheck('F14bL V2-026 WARN（legacy 過渡）且 placeholder 在訊息中',
               r[0] == 'WARN' and 'placeholder' in r[1], r[1])

        # ── F14c V2-026：forbidden_copy_check=pending，無日期 → FAIL ──
        print("\n[F14c] forbidden_copy_check=pending，fname 無日期 → V2-026 FAIL（無日期=新批強制）")
        f14c_fcc_pending = {
            'title': 'F14c fcc pending',
            'template_source_ids': ['tmpl_abc'],
            'template_adaptation': {
                'learned_structure': '反差 hook：先說反常觀點，用案例說明',
                'changed_context': '把「帶看」換成「瑞祥帶看豐原日出段的故事」',
                'forbidden_copy_check': 'pending',
            },
        }
        r = chk_v2_026_template_adaptation_required(f14c_fcc_pending, 'f14c.yaml')
        fcheck('F14c V2-026 FAIL（無日期=新批強制）且 forbidden_copy_check 在訊息中',
               r[0] == 'FAIL' and 'forbidden_copy_check' in r[1], r[1])

        # ── F14cL V2-026 legacy：fcc=pending，fname 含 < 6/1 日期 → WARN + forbidden_copy_check 在訊息 ──
        print("\n[F14cL] forbidden_copy_check=pending，fname 含 2026-05-20（< 6/1）→ V2-026 WARN（legacy 過渡）")
        r = chk_v2_026_template_adaptation_required(f14c_fcc_pending, '第30批_2026-05-20/f14cL.yaml')
        fcheck('F14cL V2-026 WARN（legacy 過渡）且 forbidden_copy_check 在訊息中',
               r[0] == 'WARN' and 'forbidden_copy_check' in r[1], r[1])

        # ── F14d V2-026：真填 + forbidden_copy_check=PASS → PASS ──
        print("\n[F14d] 真填 + forbidden_copy_check=PASS → V2-026 PASS")
        f14d_full_with_fcc = {
            'title': 'F14d 完整含 fcc PASS',
            'template_source_ids': ['tmpl_abc'],
            'template_adaptation': {
                'learned_structure': '反差 hook：先說反常觀點，用案例說明',
                'changed_context': '把「帶看」換成「瑞祥帶看豐原日出段的故事」',
                'forbidden_copy_check': 'PASS',
            },
        }
        r = chk_v2_026_template_adaptation_required(f14d_full_with_fcc, 'f14d.yaml')
        fcheck('F14d V2-026 PASS（真填 + fcc=PASS）', r[0] == 'PASS', r[1])

        # ── F15 V2-025：control_group:true → 豁免 template_source_ids → PASS ──
        print("\n[F15] control_group:true（對照組）→ V2-025 豁免 PASS")
        f15_control = {
            'title': 'F15 對照組腳本',
            '派系': '直球派',
            'control_group': True,
            # 刻意不填 template_source_ids，驗豁免邏輯
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_阿奇': '測試對照組'}],
            'caption': '對照組測試',
            'hashtag': ['#test'],
        }
        r = chk_v2_025_template_source_required(f15_control, 'f15.yaml')
        fcheck('F15 V2-025 PASS（control_group:true 豁免）', r[0] == 'PASS' and '[CONTROL]' in r[1], r[1])

        # ── F16 V2-025 legacy：批次日期 < 2026-06-01 無 template_source_ids → WARN ──
        print("\n[F16] batch_label 含 2026-05-23（< 6/1）且無 template_source_ids → V2-025 WARN（legacy 過渡）")
        f16_legacy = {
            'title': 'F16 既有批次過渡',
            '派系': '直球派',
            'batch_label': '試水批_2026-05-23',  # < 2026-06-01
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_瑞祥': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
            # 刻意不填 template_source_ids，模擬既有批次
        }
        r = chk_v2_025_template_source_required(f16_legacy, 'f16.yaml')
        fcheck(
            'F16 V2-025 WARN（legacy 批次過渡期豁免）',
            r[0] == 'WARN' and '[LEGACY]' in r[1],
            r[1]
        )

        # ── F17 V2-025 新批：批次日期 >= 2026-06-01 無 template_source_ids → FAIL ──
        print("\n[F17] batch_date 含 2026-06-01（新批強制）且無 template_source_ids → V2-025 FAIL")
        f17_new_batch = {
            'title': 'F17 新批強制',
            '派系': '直球派',
            'batch_date': '2026-06-01',  # >= 2026-06-01 → 強制
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_瑞祥': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
            # 刻意不填 template_source_ids，驗新批強制 FAIL
        }
        r = chk_v2_025_template_source_required(f17_new_batch, 'f17.yaml')
        fcheck(
            'F17 V2-025 FAIL（新批 >= 2026-06-01 強制填 template_source_ids）',
            r[0] == 'FAIL',
            r[1]
        )

        # ── F18 P1-1：batch 欄位含日期（< 6/1）且無 template_source_ids → WARN（legacy） ──
        print("\n[F18] P1-1：yaml['batch'] 含日期 2026-05-31（< 6/1），無 template_source_ids → WARN（legacy）")
        f18_batch_field = {
            'title': 'F18 batch 欄位日期',
            '派系': '直球派',
            'batch': 'pilot_範本試點_2026-05-31',  # P1-1 新欄位
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_瑞祥': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
            # 刻意不填 template_source_ids，驗 batch 欄位日期被抓到 → legacy WARN
        }
        r = chk_v2_025_template_source_required(f18_batch_field, 'f18.yaml')
        fcheck(
            'F18 V2-025 WARN（batch 欄位日期 < 6/1 → legacy 過渡）',
            r[0] == 'WARN' and '[LEGACY]' in r[1],
            r[1]
        )

        # ── F19 P1-1：批次目錄名含日期（< 6/1）無 yaml 日期欄位 → WARN（legacy） ──
        print("\n[F19] P1-1：fname 含批次目錄 第34批_試水批_2026-05-23（< 6/1），無 template_source_ids → WARN（legacy）")
        f19_dir_date = {
            'title': 'F19 批次目錄日期',
            '派系': '直球派',
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_瑞祥': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
            # 無任何日期欄位，日期從 fname 的目錄段抓
        }
        # 模擬 run_per_file_checks 傳入的 "批次目錄名/檔名"
        r = chk_v2_025_template_source_required(f19_dir_date, '第34批_試水批_2026-05-23/script_rux_34_01.yaml')
        fcheck(
            'F19 V2-025 WARN（目錄名日期 < 6/1 → legacy 過渡）',
            r[0] == 'WARN' and '[LEGACY]' in r[1],
            r[1]
        )

        # ── F20 P1-2：template_source_ids 只有 1 張 → FAIL（數量不足） ──
        print("\n[F20] P1-2：template_source_ids 只有 1 張 → V2-025 FAIL（需 3-5 張）")
        f20_one_id = {
            'title': 'F20 一張',
            'template_source_ids': ['tmpl_x'],
        }
        r = chk_v2_025_template_source_required(f20_one_id, 'f20.yaml')
        fcheck('F20 V2-025 FAIL（只有 1 張）', r[0] == 'FAIL', r[1])

        # ── F21 P1-2：template_source_ids 有重複 id → FAIL ──
        print("\n[F21] P1-2：template_source_ids 重複 id → V2-025 FAIL")
        f21_dup_ids = {
            'title': 'F21 重複 id',
            'template_source_ids': ['tmpl_x', 'tmpl_x', 'tmpl_x'],
        }
        r = chk_v2_025_template_source_required(f21_dup_ids, 'f21.yaml')
        fcheck('F21 V2-025 FAIL（重複 id）', r[0] == 'FAIL', r[1])

        # ── F22 P1-2：template_source_ids 剛好 5 張不重複（需 index 不擋）→ 數量 PASS ──
        print("\n[F22] P1-2：template_source_ids 5 張不重複（index 不存在 → 數量過驗後 WARN）")
        import validate_script_batch as _self_mod22
        _saved_cache22 = _self_mod22._TEMPLATE_INDEX_CACHE
        _saved_path22 = _self_mod22._TEMPLATE_INDEX_PATH
        _self_mod22._TEMPLATE_INDEX_PATH = Path('/nonexistent/template_index.jsonl')
        _self_mod22._TEMPLATE_INDEX_CACHE = None
        f22_five_ids = {
            'title': 'F22 5 張不重複',
            'template_source_ids': ['tmpl_a', 'tmpl_b', 'tmpl_c', 'tmpl_d', 'tmpl_e'],
        }
        r = _self_mod22.chk_v2_025_template_source_required(f22_five_ids, 'f22.yaml')
        # 數量/重複驗過，index 不存在 → WARN（不因數量 FAIL）
        fcheck('F22 V2-025 WARN（5 張 OK，index 缺 → WARN 非 FAIL）', r[0] == 'WARN', r[1])
        _self_mod22._TEMPLATE_INDEX_PATH = _saved_path22
        _self_mod22._TEMPLATE_INDEX_CACHE = _saved_cache22

        # ── F23 P1-3：strict 模式 + 新批 + index 缺失 → FAIL ──
        print("\n[F23] P1-3：strict 模式 + 新批（>= 6/1）+ index 缺失 → V2-025 FAIL")
        import validate_script_batch as _self_mod23
        _saved_cache23 = _self_mod23._TEMPLATE_INDEX_CACHE
        _saved_path23 = _self_mod23._TEMPLATE_INDEX_PATH
        _saved_strict23 = _self_mod23._STRICT_MODE
        _self_mod23._TEMPLATE_INDEX_PATH = Path('/nonexistent/template_index.jsonl')
        _self_mod23._TEMPLATE_INDEX_CACHE = None
        _self_mod23._STRICT_MODE = True  # 模擬 --strict
        f23_strict_new = {
            'title': 'F23 strict 新批 index 缺',
            'batch_date': '2026-06-01',  # 新批
            'template_source_ids': ['tmpl_a', 'tmpl_b', 'tmpl_c'],  # 3 張數量 OK
        }
        r = _self_mod23.chk_v2_025_template_source_required(f23_strict_new, 'f23.yaml')
        fcheck('F23 V2-025 FAIL（strict + 新批 + index 缺）', r[0] == 'FAIL', r[1])
        _self_mod23._TEMPLATE_INDEX_PATH = _saved_path23
        _self_mod23._TEMPLATE_INDEX_CACHE = _saved_cache23
        _self_mod23._STRICT_MODE = _saved_strict23

        # ── F24 P1-2 legacy：legacy 批（< 6/1）+ 只 2 張 → WARN（不 FAIL） ──
        print("\n[F24] P1-2 legacy：batch_label 含 2026-05-31（< 6/1）+ 只 2 張 template_source_ids → V2-025 WARN（legacy 過渡，不 FAIL）")
        f24_legacy_two = {
            'title': 'F24 legacy 批 2 張',
            '派系': '直球派',
            'batch_label': '試點批_2026-05-31',  # < 2026-06-01
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_瑞祥': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
            'template_source_ids': ['tmpl_pilot_01', 'tmpl_pilot_02'],  # 只 2 張（< 3）
        }
        r = chk_v2_025_template_source_required(f24_legacy_two, 'f24.yaml')
        fcheck(
            'F24 V2-025 WARN（legacy 批 2 張，不 FAIL）',
            r[0] == 'WARN' and '[LEGACY]' in r[1],
            r[1]
        )

        # ── F25 P1-2 legacy：legacy 批（< 6/1）+ 重複 id → WARN（不 FAIL） ──
        print("\n[F25] P1-2 legacy：batch_label 含 2026-05-31（< 6/1）+ 重複 id → V2-025 WARN（legacy 過渡，不 FAIL）")
        f25_legacy_dup = {
            'title': 'F25 legacy 批重複 id',
            '派系': '直球派',
            'batch_label': '試點批_2026-05-31',  # < 2026-06-01
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_瑞祥': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
            'template_source_ids': ['tmpl_x', 'tmpl_x', 'tmpl_x'],  # 重複
        }
        r = chk_v2_025_template_source_required(f25_legacy_dup, 'f25.yaml')
        fcheck(
            'F25 V2-025 WARN（legacy 批重複 id，不 FAIL）',
            r[0] == 'WARN' and '[LEGACY]' in r[1],
            r[1]
        )

        # ── F26 P1 繞過洞：舊 yaml 日期（5/31）複製到 6/2 目錄 → 應 FAIL（取最大日期）──
        print("\n[F26] P1 繞過洞：yaml batch_label=2026-05-31 但目錄名含 2026-06-02 → V2-025 FAIL（不允許繞過）")
        f26_bypass = {
            'title': 'F26 舊 yaml 放新目錄',
            '派系': '直球派',
            'batch_label': '試水批_2026-05-31',  # 舊 yaml 欄位日期（< 6/1）
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_瑞祥': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
            # 刻意不填 template_source_ids，驗繞過洞是否堵住
        }
        # fname 帶新批目錄（6/2），取最大日期應為 2026-06-02 → 新批 FAIL
        r = chk_v2_025_template_source_required(f26_bypass, '第35批_2026-06-02/script_rux_35_01.yaml')
        fcheck(
            'F26 V2-025 FAIL（繞過洞堵住：目錄日期 6/2 > yaml 日期 5/31 → 新批強制）',
            r[0] == 'FAIL',
            r[1]
        )

        # ── F27 多格式：YYYY/MM/DD → 抓到 legacy 日期 → WARN ──
        print("\n[F27] P2 多格式 YYYY/MM/DD：batch_label 含 2026/05/31 → 抓到日期 → legacy WARN")
        f27_slash = {
            'title': 'F27 slash format',
            '派系': '直球派',
            'batch_label': '試水批_2026/05/31',  # YYYY/MM/DD 格式
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_瑞祥': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
        }
        # 驗 _extract_batch_date 能抓到日期
        d27 = _extract_batch_date(f27_slash, 'f27.yaml')
        fcheck(
            'F27 _extract_batch_date 抓到 2026/05/31（slash 格式）',
            d27 == _dt.date(2026, 5, 31),
            f"抓到：{d27}"
        )

        # ── F28 多格式：YYYYMMDD → 抓到 legacy 日期 → WARN ──
        print("\n[F28] P2 多格式 YYYYMMDD：batch_label 含 20260531 → 抓到日期 → legacy WARN")
        f28_compact = {
            'title': 'F28 compact format',
            '派系': '直球派',
            'batch_label': '試水批_20260531',  # YYYYMMDD 格式
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_瑞祥': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
        }
        d28 = _extract_batch_date(f28_compact, 'f28.yaml')
        fcheck(
            'F28 _extract_batch_date 抓到 20260531（compact 格式）',
            d28 == _dt.date(2026, 5, 31),
            f"抓到：{d28}"
        )

        # ── F29 多格式：YYYY_MM_DD → 抓到 legacy 日期 → WARN ──
        print("\n[F29] P2 多格式 YYYY_MM_DD：batch_label 含 2026_05_31 → 抓到日期 → legacy WARN")
        f29_underscore = {
            'title': 'F29 underscore format',
            '派系': '直球派',
            'batch_label': '試水批_2026_05_31',  # YYYY_MM_DD 格式
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_瑞祥': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
        }
        d29 = _extract_batch_date(f29_underscore, 'f29.yaml')
        fcheck(
            'F29 _extract_batch_date 抓到 2026_05_31（underscore 格式）',
            d29 == _dt.date(2026, 5, 31),
            f"抓到：{d29}"
        )

        # 總結
        total = PASS_COUNT + FAIL_COUNT
        print(f"\n=== Fixtures 結果：{PASS_COUNT}/{total} PASS ===")
        if FAIL_COUNT > 0:
            print(f"FAIL {FAIL_COUNT} 件")
            sys.exit(1)
        else:
            print("全部 PASS — V2 migration fixtures 通過")
            sys.exit(0)
    else:
        main()
