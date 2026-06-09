#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_script_batch.py — 腳本批次品管員（v2 — 階段 3 升級 / 含 V2 schema 守門）
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

# ── 共用派系解析器（第一刀 2026-06-05）──
try:
    _FP_DIR = Path(__file__).resolve().parent
    if str(_FP_DIR) not in sys.path:
        sys.path.insert(0, str(_FP_DIR))
    from _faction_parser import (
        load_l0_faction_names as _load_l0_faction_names,
        parse_faction_mix_from_headings as _parse_faction_mix,
        FactionParseResult as _FactionParseResult,
    )
    _FACTION_PARSER_OK = True
except Exception as _fp_err:
    _FACTION_PARSER_OK = False
    _load_l0_faction_names = None  # type: ignore

# ── CTA/Content mix 解析器（P3 比例驗證器 2026-06-08）──
try:
    _MP_DIR = Path(__file__).resolve().parent
    if str(_MP_DIR) not in sys.path:
        sys.path.insert(0, str(_MP_DIR))
    from _mix_parser import (
        parse_mix_block as _parse_mix_block,
        normalize_to_count as _normalize_to_count,
        resolve_label as _resolve_label,
        get_label_from_yaml as _get_label_from_yaml,
        MixParseResult as _MixParseResult,
    )
    _MIX_PARSER_OK = True
except Exception as _mp_err:
    _MIX_PARSER_OK = False
    _parse_mix_block = None      # type: ignore
    _normalize_to_count = None   # type: ignore
    _resolve_label = None        # type: ignore
    _get_label_from_yaml = None  # type: ignore
    # ⚠️ 安全洞修正（P3 三審 2026-06-08）：
    # _parse_faction_mix 屬於 C-011（_faction_parser），完全獨立於 _mix_parser。
    # 禁止在此 except 覆寫 _parse_faction_mix — 否則 _mix_parser 壞掉會連累 C-011。

# ── 共用雙身份解析器（第二刀 2026-06-05）──
try:
    _FP_DIR2 = Path(__file__).resolve().parent
    if str(_FP_DIR2) not in sys.path:
        sys.path.insert(0, str(_FP_DIR2))
    from _identity_parser import (
        parse_identity_mix_from_headings as _parse_identity_mix,
        IdentityParseResult as _IdentityParseResult,
    )
    _IDENTITY_PARSER_OK = True
except Exception as _ip_err:
    _IDENTITY_PARSER_OK = False
    _parse_identity_mix = None  # type: ignore

# ── P1-③：從 validate_deploy 共用 FACTION_LEAK_WORDS（單一真理源）──
try:
    _VD_DIR = Path(__file__).resolve().parent
    if str(_VD_DIR) not in sys.path:
        sys.path.insert(0, str(_VD_DIR))
    from validate_deploy import FACTION_LEAK_WORDS as _FACTION_LEAK_WORDS
    _FACTION_IMPORT_OK = True
except Exception as _fe:
    # fallback：import 失敗時保留舊清單，守門不失效
    _FACTION_IMPORT_OK = False
    _FACTION_LEAK_WORDS = [
        "直球派", "嗆辣派", "市場觀察派", "人間觀察派", "故事戲劇派",
        "拆解派", "結構分析派", "自嘲反差派", "圖卡部", "老前輩權威派",
        "時事追擊派", "綜合派", "模板L_知識反差", "家人朋友模擬派",
        "直球情侶版", "純雞湯", "直球揭秘",
        "修平派", "Erika", "毒舌正能量", "釣魚部",
        "模板L", "模板A", "模板G",
        "字幕卡", "流量密碼",
    ]

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

# ── _sop_config：讀 L0 batch_spec + time_slots（B 段 2026-06-05）──
try:
    _SOP_CFG_DIR = Path(__file__).resolve().parent
    if str(_SOP_CFG_DIR) not in sys.path:
        sys.path.insert(0, str(_SOP_CFG_DIR))
    from _sop_config import (
        load_l0_batch_spec as _load_l0_batch_spec,
        load_l0_time_slots as _load_l0_time_slots,
        normalize_timestamp as _sop_ts_normalize,
    )
    _SOP_CONFIG_OK = True
except Exception as _sop_err:
    print(
        f"[WARN] validate_script_batch: _sop_config import failed ({_sop_err}); "
        f"using hardcoded SOP fallback",
        file=sys.stderr,
    )
    _SOP_CONFIG_OK = False

    # fallback 函式（回舊硬編值，守門不失效）
    def _load_l0_batch_spec():  # type: ignore
        return {
            "main_scripts": 13, "fishing_script": 1, "threads_posts": 7,
            "visual_aid_scripts": 0, "duration_seconds": 60, "title_max_chars": 15,
            "traffic_codes_min": 3, "actor_interaction_min": 2,
            "school_diversity_min": 3, "theme_diversity_min": 4, "cta_distribution": {},
        }

    def _load_l0_time_slots():  # type: ignore
        return (
            {"raw_slot": "0-3秒",   "timestamp": "0-3s",   "start":  0, "end":  3, "task": "Hook", "note": ""},
            {"raw_slot": "3-12秒",  "timestamp": "3-12s",  "start":  3, "end": 12, "task": "破題", "note": ""},
            {"raw_slot": "12-25秒", "timestamp": "12-25s", "start": 12, "end": 25, "task": "核心", "note": ""},
            {"raw_slot": "25-40秒", "timestamp": "25-40s", "start": 25, "end": 40, "task": "案例", "note": ""},
            {"raw_slot": "40-52秒", "timestamp": "40-52s", "start": 40, "end": 52, "task": "收束", "note": ""},
            {"raw_slot": "52-60秒", "timestamp": "52-60s", "start": 52, "end": 60, "task": "CTA",  "note": ""},
        )

    def _sop_ts_normalize(value: str) -> str:  # type: ignore
        import re as _re
        value = value.replace("–", "-").replace("—", "-").replace(" ", "")
        value = _re.sub(r"秒$", "s", value)
        if _re.match(r"^\d+-\d+$", value):
            value = value + "s"
        return value

# UTF-8 輸出防亂碼（Windows cp950）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ── 業主偏好.md 路徑表（動態 lookup，不硬寫比例數字）──
L2_BASE = Path(r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\L2_業主層")

# Phase 2 FIX2：lazy proxy（import 不碰 generated.json；dir 已於上方 sibling import 加入 sys.path）
from _lazy_map import LazyMap

# ── Phase 2 Step 4：從 owner_projection.generated.json 載入 4 張 roster/path 表 ──
def _load_owner_projection() -> dict:
    """讀 sibling owner_projection.generated.json；缺/壞 fail-loud（不回硬表）。"""
    import json as _json
    _proj_path = Path(__file__).resolve().parent / "owner_projection.generated.json"
    if not _proj_path.exists():
        raise FileNotFoundError(
            f"[validate_script_batch] owner_projection.generated.json 不存在：{_proj_path}\n"
            "請先執行 gen_owner_projection_cache.py 產生 cache。"
        )
    try:
        with open(_proj_path, encoding="utf-8") as _f:
            _data = _json.load(_f)
    except Exception as _e:
        raise RuntimeError(
            f"[validate_script_batch] 讀 owner_projection.generated.json 失敗：{_e}"
        ) from _e
    if "owners" not in _data or not isinstance(_data["owners"], dict):
        raise ValueError(
            f"[validate_script_batch] owner_projection.generated.json 缺 'owners' key 或格式錯誤"
        )
    return _data["owners"]

_OWNER_PROJ = LazyMap(_load_owner_projection)  # Phase 2 FIX2：lazy——import 不載 JSON

# OWNER_PREF_PATHS：key 順序對齊原硬編（瑞祥/仲豪/昀臻/叭噗_小C/阿奇/溫蒂/詩婷）
OWNER_PREF_PATHS = LazyMap(lambda: {
    owner: Path(rec["l2_path"])
    for owner, rec in sorted(
        _OWNER_PROJ.items(),
        key=lambda x: ["瑞祥", "仲豪", "昀臻", "叭噗_小C", "阿奇", "溫蒂", "詩婷"].index(x[0])
        if x[0] in ["瑞祥", "仲豪", "昀臻", "叭噗_小C", "阿奇", "溫蒂", "詩婷"] else 99
    )
})

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
    """
    從偏好.md 雙身份比例抓 {身份類型: %}（heading-based，第二刀 2026-06-05）
    薄 wrapper 呼叫 _identity_parser。名稱已 normalize（括號 strip）。
    """
    if _IDENTITY_PARSER_OK and _parse_identity_mix is not None:
        result = _parse_identity_mix(pref_text)
        return dict(result.ratios)
    # fallback：_identity_parser 不可用，回空
    return {}

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
# check 函式集（逐一回傳 (PASS/FAIL/WARN, detail)）
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
    B 段 2026-06-05：expected_order 改讀 L0 time_slots（廢硬編）。
    """
    expected_order = [s["timestamp"] for s in _load_l0_time_slots()]
    expected_len = len(expected_order)

    # 嘗試用 canonical
    canonical_scenes = _get_canonical_scenes(data)
    if canonical_scenes is not None:
        if len(canonical_scenes) != expected_len:
            ts_list = [s.get('timestamp', '?') for s in canonical_scenes]
            return "FAIL", f"scenes 段數 = {len(canonical_scenes)}，需要 {expected_len} 段（實際：{ts_list}）"
        actual = [_ts_normalize(s.get('timestamp', '')) for s in canonical_scenes]
        for i, (exp, got) in enumerate(zip(expected_order, actual)):
            if got != exp:
                return "FAIL", f"scenes[{i}] timestamp = '{got}'，期望 '{exp}'（原始：{canonical_scenes[i].get('timestamp','')}）"
        return "PASS", "6 段時間軸齊全且順序正確（canonical 層驗）"

    # fallback：舊邏輯（structured frontmatter）
    scenes = get_scenes(data)
    if len(scenes) != expected_len:
        return "FAIL", f"scenes 段數 = {len(scenes)}，需要 {expected_len} 段（實際：{[s.get('timestamp','?') for s in scenes]}）"
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
    """L1-003：藏鏡人互動點 >= actor_interaction_min
    有 canonical 用 canonical（offscreen_interaction 欄位），沒有 fallback 舊邏輯。
    §14 P0：mirror 要吃 canonical，不是舊貪婪 regex。
    B 段 2026-06-05：min_count 改讀 L0 batch_spec（廢硬編）。
    """
    min_count = _load_l0_batch_spec()["actor_interaction_min"]

    # 嘗試用 canonical
    canonical_scenes = _get_canonical_scenes(data)
    if canonical_scenes is not None:
        count = sum(1 for s in canonical_scenes if s.get('offscreen_interaction'))
        if count < min_count:
            return "FAIL", f"藏鏡人互動點 = {count}，需要 >= {min_count}（canonical 層驗）"
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
    if count < min_count:
        return "FAIL", f"藏鏡人互動點 = {count}，需要 >= {min_count}"
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
    """L1-004：流量密碼 >= traffic_codes_min（以 schema_check 欄位 or 台詞關鍵詞代理）
    有 canonical 用 canonical（dialogue + subtitle + offscreen 全文），沒有 fallback 舊邏輯。
    B 段 2026-06-05：min_count 改讀 L0 batch_spec（廢硬編）。
    """
    min_count = _load_l0_batch_spec()["traffic_codes_min"]

    sc = data.get("schema_check", {})
    if isinstance(sc, dict):
        fd = sc.get("流量密碼數量") or sc.get("流量密碼")
        if fd:
            try:
                n = int(str(fd))
                if n >= min_count:
                    return "PASS", f"schema_check 流量密碼數量 = {n}"
                else:
                    return "FAIL", f"schema_check 流量密碼數量 = {n}，需 >= {min_count}"
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
        if hits >= min_count:
            return "PASS", f"流量密碼信號 >= {min_count}（偵測到 {hits} 個，含懸念+互動+反問，canonical 層驗）"
        return "FAIL", f"流量密碼信號偵測 = {hits}，低於 {min_count}（canonical 層驗，請確認台詞有反問/懸念/互動引導）"

    # fallback：舊邏輯
    text = get_all_text(data)
    hits = sum(1 for s in TRAFFIC_SIGNALS if s in text)
    if data.get("藏鏡人"):
        hits += 1
    cap = data.get("caption", "")
    if cap and ("？" in cap or "留言" in cap):
        hits += 1
    if hits >= min_count:
        return "PASS", f"流量密碼信號 >= {min_count}（偵測到 {hits} 個信號，含懸念+互動+反問）"
    return "FAIL", f"流量密碼信號偵測 = {hits}，低於 {min_count}（請確認台詞有反問/懸念/互動引導）"

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
    """L1-006：末段（L0 time_slots 最後一段）有 CTA 引導語（純雞湯除外）
    有 canonical 用 canonical（timestamp 正規化 + dialogue），沒有 fallback 舊邏輯。
    B 段 2026-06-05：cta_slot 改讀 L0 time_slots 末段（廢硬編 '52-60s'）。
    """
    cta_slot = _load_l0_time_slots()[-1]["timestamp"]

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
        if ts_norm != cta_slot:
            return "FAIL", f"最後一段 timestamp = '{last.get('timestamp','')}' (正規化: '{ts_norm}')，不是 '{cta_slot}'"
        role = last.get('role', '')
        if 'CTA' not in role and 'cta' not in role.lower():
            return "FAIL", f"最後一段 role = '{role}'，應含 CTA（canonical 層驗）"
        text = ' '.join(d.get('line', '') for d in last.get('dialogue', []))
        # 也從 subtitle 找
        text += ' ' + last.get('subtitle', '')
        if any(k in text for k in cta_keywords):
            return "PASS", f"{cta_slot} CTA 段存在，含引導語（canonical 層驗，{text[:40]}…）"
        return "FAIL", f"{cta_slot} CTA 段文字無引導語關鍵詞（canonical 層驗，{text[:60]}）"

    # fallback：舊邏輯
    scenes = get_scenes(data)
    last = scenes[-1] if scenes else {}
    ts = last.get("timestamp", "")
    if ts != cta_slot:
        return "FAIL", f"最後一段 timestamp = '{ts}'，不是 '{cta_slot}'"
    seg_type = last.get("type", "")
    if "CTA" not in seg_type and "cta" not in seg_type.lower():
        return "FAIL", f"最後一段 type = '{seg_type}'，應含 CTA"
    dialogue_parts = _get_all_dialogue(last)
    text = " ".join(dialogue_parts) if dialogue_parts else ""
    if any(k in text for k in cta_keywords):
        return "PASS", f"{cta_slot} CTA 段存在，含引導語（{text[:40]}…）"
    return "FAIL", f"{cta_slot} CTA 段文字無引導語關鍵詞（{text[:60]}）"

def chk_l1_007_title_len(data: dict, fname: str) -> tuple[str, str]:
    """L1-007：標題 <= title_max_chars 字
    B 段 2026-06-05：max_chars 改讀 L0 batch_spec（廢硬編 15）。
    """
    max_chars = _load_l0_batch_spec()["title_max_chars"]
    title = data.get("title", "")
    if not title:
        return "FAIL", "title 欄位空白"
    # 計算純中文+英文字數（不含空格/標點）
    chars = re.sub(r"[\s！，。？「」：、【】…—\-]+", "", title)
    n = len(chars)
    if n <= max_chars:
        return "PASS", f"標題 '{title}'，字數 = {n} <= {max_chars}"
    return "FAIL", f"標題 '{title}'，字數 = {n} > {max_chars}"

def chk_l1_008_batch_count(yamls: list[tuple[Path, dict]], batch_dir: Path) -> tuple[str, str]:
    """L1-008：批次數量剛好 = main_scripts（exact，此函式是 batch-level check）
    B 段 2026-06-05：由 13-14 區間改為 exact 13（澤君 2026-06-05 拍板）。
    """
    valid = [(f, d) for f, d in yamls if "__parse_error__" not in d and "__schema_error__" not in d]
    n = len(valid)
    expected = int(_load_l0_batch_spec()["main_scripts"])
    if n == expected:
        return "PASS", f"主腳本 yaml 數量 = {n}，符合 SOP exact {expected} 支"
    return "FAIL", f"主腳本 yaml 數量 = {n}，SOP 要求剛好 {expected} 支"

def chk_l1_009_派系_coverage(yamls: list[tuple[Path, dict]]) -> tuple[str, str]:
    """L1-009：派系覆蓋度 >= school_diversity_min 種
    支援 '派系' key（阿奇/叭噗格式）及 'faction' key（瑞祥 markdown 格式）。
    B 段 2026-06-05：min_count 改讀 L0 batch_spec（廢硬編）。
    """
    min_count = _load_l0_batch_spec()["school_diversity_min"]
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
    if n >= min_count:
        return "PASS", f"派系覆蓋 = {n} 種：{sorted(types)}"
    return "FAIL", f"派系覆蓋 = {n} 種（{sorted(types)}），需 >= {min_count} 種"

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
    """
    C-011：派系比例對齊業主偏好.md（±5% 容許）
    第一刀 2026-06-05：改用 _faction_parser，三態可審計（不新增 status）。
    | 情況 | 判定 | detail 前綴 |
    | canonical 完整、偏差 <=5% | PASS | — |
    | canonical vs 實際偏差 >5% | FAIL | — |
    | 有 % 但有 unknown（仲豪）| WARN | [WAIVED:UNKNOWN_ALIAS] + 列 unknown |
    | 無 % 且 provisional（詩婷）| WARN | [WAIVED:PROVISIONAL] |
    | 無 % 且非 provisional | FAIL | 找不到可驗證派系比例 |
    | 找不到偏好檔 | 維持現有流程 | — |
    """
    if not pref_text:
        return "WARN", f"找不到業主 '{owner}' 偏好.md，無法驗派系比例（路徑：{OWNER_PREF_PATHS.get(owner,'未知')}）"

    # ── 解析偏好檔 ──
    if _FACTION_PARSER_OK:
        # 第一刀：用 _faction_parser（支援第5章/第8章 + unknown 分流）
        _valid = _load_l0_faction_names()
        parsed: _FactionParseResult = _parse_faction_mix(pref_text, valid_schools=_valid)
        expected_canonical = dict(parsed.canonical_ratios)
        has_unknown = bool(parsed.unknown_ratios)
        is_provisional = parsed.provisional

        # provisional 無比例（御史/Codex 收口 2026-06-05：有 canonical 比例時不可被
        # 「建議傾向」字樣豁免——否則「真比例表＋一句建議傾向」會被誤 waive）
        if is_provisional and not expected_canonical:
            return "WARN", "[WAIVED:PROVISIONAL] 偏好.md 標記「建議傾向/尚無批次」且無可解析比例，派系比例待算盤覆核，跳過 C-011"

        # 有 unknown（仲豪型）但無 canonical
        if not expected_canonical and has_unknown:
            unknown_desc = ", ".join(f"{k}:{v}%" for k, v in parsed.unknown_ratios.items())
            return "WARN", f"[WAIVED:UNKNOWN_ALIAS] 偏好.md 含未知派系名（非 L0 14 標準名）：{unknown_desc}，待 Phase 2 補 alias，跳過 C-011"

        # 找不到任何比例（非 provisional、非 unknown）
        if not expected_canonical and not has_unknown:
            return "FAIL", "偏好.md 無法解析到可驗證的派系比例（非 provisional），C-011 FAIL"

    else:
        # fallback：舊版 parse_schema_distribution（只認 §8 / 第8章）
        expected_canonical = parse_schema_distribution(pref_text, "§8") or parse_schema_distribution(pref_text, "第 8 章")
        has_unknown = False
        is_provisional = False
        if not expected_canonical:
            return "WARN", "偏好.md 第 8 章無法解析到 XX% 格式的比例，跳過派系比例驗證（_faction_parser 不可用）"

    # ── 統計本批派系 ──
    actual_count: dict[str, int] = {}
    total = 0
    for _, d in yamls:
        if "__parse_error__" in d:
            continue
        派系 = d.get("派系", "") or d.get("faction", "") or d.get("template", "")
        m = re.match(r"([^\(（]+)", str(派系))
        if m:
            name = m.group(1).strip()
            actual_count[name] = actual_count.get(name, 0) + 1
            total += 1
    if total == 0:
        return "WARN", "批次無有效 yaml，無法計算派系比例"
    actual_pct = {k: round(v / total * 100) for k, v in actual_count.items()}

    # 有 unknown 但 canonical 非空（仲豪型：直球派36% + unknown 別名）→ WAIVED
    # 算盤 MODIFY 修（2026-06-05）：原訊息「僅驗 canonical 部分」是謊報——此處 early return，
    # 下方 tolerance 根本沒跑＝零驗證，訊息卻說「已驗」。誠實版：unknown 部分無對照表無法驗、
    # canonical 部分為避免「分母含 unknown 腳本」失真也暫不驗，整批比例驗證待 Phase 2 補 alias 後再做。
    if has_unknown and expected_canonical:
        unknown_desc = ", ".join(f"{k}:{v}%" for k, v in parsed.unknown_ratios.items())  # type: ignore[possibly-undefined]
        return "WARN", (
            f"[WAIVED:UNKNOWN_ALIAS] 偏好含非 L0 標準名：{unknown_desc}（canonical：{expected_canonical}）。"
            f"本批派系比例暫不驗（待 Phase 2 補 alias 對照表後驗全比例，非「已驗通過」）"
        )

    # ── 偏差計算 ──
    TOLERANCE = 5
    def _norm_key(s: str) -> str:
        mx = re.match(r"([^\(（]+)", s)
        return mx.group(1).strip() if mx else s.strip()
    normalized_expected = {_norm_key(k): v for k, v in expected_canonical.items()}
    over_tol = []
    for name, exp_pct in normalized_expected.items():
        act_pct = actual_pct.get(name, 0)
        diff = act_pct - exp_pct
        if abs(diff) > TOLERANCE:
            over_tol.append(f"{name} 預期 {exp_pct}% 實際 {act_pct}%（偏差 {diff:+d}%）")
    if over_tol:
        return "FAIL", f"C-011 派系比例超出 ±{TOLERANCE}%：" + "；".join(over_tol) + f"  （實際分佈：{actual_pct}）"
    return "PASS", f"C-011 派系比例對齊（±{TOLERANCE}% 內）：{actual_pct}（偏好參考：{normalized_expected}）"

def _parse_kb_owner_industries(pref_text: str) -> Optional[list]:
    """
    從偏好.md 解析 kb-owner fenced block 的 industries 欄位。
    解析成功回傳 list，失敗回傳 None。
    """
    m = re.search(r"```kb-owner\n(.*?)```", pref_text, re.DOTALL)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
        if not isinstance(data, dict):
            return None
        industries = data.get("industries")
        if industries is None:
            industry_id = data.get("industry_id")
            if industry_id:
                industries = [industry_id]
        if isinstance(industries, list):
            return industries
        return None
    except Exception:
        return None


def _normalize_identity_label(s: str) -> str:
    """normalize：strip 全形/半形括號 + trim（對齊 _identity_parser）"""
    return re.sub(r"（[^）]*）|\([^)]*\)", "", str(s)).strip()


def chk_c012_identity_ratio(yamls: list[tuple[Path, dict]], owner: str, pref_text: Optional[str]) -> tuple[str, str]:
    """
    C-012：雙身份比例對齊業主偏好.md（第二刀 2026-06-05）
    gate：讀 kb-owner industries 判斷雙行業（阿奇）vs 單行業（其餘6）。
    雙行業 required：解析不到比例 OR 批次無「雙身份分類」欄 → FAIL
    單行業：乾淨 skip → PASS
    kb-owner parse 失敗：fail-loud WARN
    """
    if not pref_text:
        return "WARN", f"找不到業主 '{owner}' 偏好.md，跳過雙身份比例驗證"

    # gate：讀 kb-owner industries 判斷雙行業
    industries = _parse_kb_owner_industries(pref_text)
    if industries is None:
        return "WARN", f"C-012 警告：業主 '{owner}' 偏好.md 無法解析 kb-owner block，無法判斷是否為雙行業業主"

    is_dual = len([i for i in industries if i]) > 1

    if not is_dual:
        # 單行業：乾淨 skip
        return "PASS", f"C-012 非雙身份業主（單行業 {industries}），C-012 不適用"

    # 雙行業 required
    expected = parse_identity_distribution(pref_text)
    if not expected:
        return "FAIL", f"C-012 FAIL：業主 '{owner}' 為雙行業（{industries}），但偏好.md 無法解析雙身份比例"

    # 統計批次 yaml 的「雙身份分類」欄（排 parse error）
    actual_count: dict[str, int] = {}
    total = 0
    for _, d in yamls:
        if "__parse_error__" in d:
            continue
        itype = d.get("雙身份分類", "")
        if itype:
            label = _normalize_identity_label(str(itype))
            actual_count[label] = actual_count.get(label, 0) + 1
            total += 1

    if total == 0:
        return "FAIL", f"C-012 FAIL：業主 '{owner}' 為雙行業（{industries}），但批次 yaml 全無「雙身份分類」欄"

    actual_pct = {k: round(v / total * 100) for k, v in actual_count.items()}

    # LABEL_MISMATCH 偵測（霸告 2026-06-05 修，類比第一刀仲豪 WAIVED:UNKNOWN_ALIAS）：
    # yaml「雙身份分類」標籤 vs 偏好類型名 normalize 後交集為空 = 命名體系不一致，非「比例錯」。
    # 阿奇 yaml 用實例標籤（胖奇熱狗堡/觀點分享/房仲副軸/個人生活）、偏好用類型名（餐飲/生活觀點個人故事/房仲/開箱），
    # 缺對照表時直接字串比對會讓所有 expected key act_pct=0 → 誤判巨大偏差 FAIL（行為惡化）。
    # 改 WAIVED 不誤擋（待 Phase 2 補 alias 對照表 + 澤君拍板比例；阿奇偏好標題現為「霸告建議—待澤君拍板」）。
    if not (set(expected.keys()) & set(actual_pct.keys())):
        # Codex 收口（2026-06-05）：LABEL_MISMATCH WAIVE 綁「偏好比例標 provisional（待拍板/建議）」，
        # 堵放水「雙行業全標錯但比例已定案」。阿奇偏好標「雙身份比例（霸告建議—待澤君拍板）」→ WAIVE；
        # 未來比例已定案仍命名不一致 → FAIL（逼對齊命名或補 alias 對照表）。
        _prov = bool(re.search(r"雙身份比例.{0,30}(待.{0,6}拍板|建議|尚無|初步|未定)", pref_text))
        _msg = (f"yaml「雙身份分類」標籤與偏好類型名命名不一致"
                f"（標籤={sorted(actual_pct.keys())} vs 偏好類型名={sorted(expected.keys())}）")
        if _prov:
            return "WARN", (f"[WAIVED:LABEL_MISMATCH] {_msg}，且偏好比例標 provisional（待拍板/建議），"
                            f"待 Phase 2 對照表 + 澤君拍板比例，本批暫不驗（非比例錯、非已驗通過）")
        return "FAIL", (f"C-012 FAIL：{_msg}，且偏好比例已定案（非 provisional）→ 須對齊命名或補 alias 對照表")

    # 對比（兩邊已 normalize，±5% 容許）
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

def chk_c013_dm_card(data: dict, fname: str, owner: str, fishing_policy: Optional[dict] = None) -> tuple[str, str]:
    """C-013：釣魚部腳本 dm_card 6 件齊（雙模式）

    fishing_policy 由 load_fishing_policy() 回傳，mode ∈ {off, opt_in, legacy, invalid}。
    - 無 fishing signals → PASS skip（任何 mode 都一樣）
    - off/invalid + 有信號 → FAIL（fail-closed；C-013B 也會在 batch-level 抓，這裡再 per-file 確認）
    - legacy → 舊 dm_card 6 件驗（dm_card 缺仍 FAIL，不趁 cutover 放水）
    - opt_in → dm_card 必須是 dict + 6 件齊
    """
    if fishing_policy is None:
        fishing_policy = {"mode": "off", "batch_date": None, "detail": "未傳入 policy，保守 off"}

    mode = fishing_policy.get("mode", "off")

    # 共用信號偵測（legacy 模式用舊 criteria 保零回歸；off/opt_in 用全偵測 fail-closed）
    signals = _fishing_signals(data, legacy=(mode == "legacy"))
    if not signals:
        return "PASS", "非釣魚部腳本（無釣魚信號），跳過 dm_card 驗證"

    # 有釣魚信號 → 按 mode 分路
    if mode in ("off", "invalid"):
        return "FAIL", (
            f"C-013：偵測到釣魚部信號但 mode={mode}（fail-closed）。"
            f"信號：{signals}。"
            f"Policy：{fishing_policy.get('detail','')}"
        )

    # legacy 或 opt_in：驗 dm_card 6 件
    dm = data.get("dm_card")

    # opt_in 模式：dm_card 必須是 dict
    if mode == "opt_in" and not isinstance(dm, dict):
        return "FAIL", (
            f"C-013 opt_in：dm_card 必須是 dict，但得到 {type(dm).__name__!r}（{dm!r}）"
        )

    # legacy/opt_in 驗 6 件（opt_in 只掃 dm_card dict、防關鍵字散在 caption/台詞放水；legacy 保留掃全包零回歸）
    ALL_TEXT = str(dm) if mode == "opt_in" else str(data)
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
        found_kw = any(k in ALL_TEXT for k in keywords)
        if not found_kw:
            missing.append(field)
    if missing:
        mode_label = "legacy" if mode == "legacy" else "opt_in"
        return "FAIL", f"釣魚部 dm_card 缺少欄位（{mode_label}）：{missing}"
    # opt-in 圖卡交付鏈驗證（保鏢硬條件2 / Codex must-fix）：opt_in 釣魚必須有圖片資產路徑非空，
    # 否則「validator 6 件驗過、但網站 build 找不到圖片 → 站上圖卡空白」。legacy 豁免、off 不適用（off 沒釣魚）。
    if mode == "opt_in":
        asset = ""
        if isinstance(dm, dict):
            asset = str(dm.get("asset_path") or dm.get("img") or "").strip()
        if not asset:
            asset = str(data.get("img") or "").strip()
        if not asset:
            return "FAIL", "釣魚部 opt_in：dm_card 6 件齊但缺圖片資產路徑（dm_card.asset_path / img 皆空）→ 網站圖卡會空白"
        return "PASS", f"釣魚部 dm_card 6 件齊 + 圖片資產路徑（mode=opt_in）"
    return "PASS", f"釣魚部 dm_card 6 件齊（mode={mode}）"

def chk_c013b_no_fishing_when_off(yamls: list, fishing_policy: Optional[dict] = None) -> tuple[str, str]:
    """C-013B：batch-level — off/invalid 模式整批掃釣魚信號，有命中→FAIL（fail-closed）。
    opt_in / legacy → PASS skip。
    掛在 C-014 後、V2-006 前（見 batch_checks 排列）。
    """
    if fishing_policy is None:
        fishing_policy = {"mode": "off", "batch_date": None, "detail": "未傳入 policy，保守 off"}

    mode = fishing_policy.get("mode", "off")

    if mode in ("opt_in", "legacy"):
        return "PASS", f"C-013B skip（mode={mode}，釣魚功能啟用或舊批豁免）"

    # off 或 invalid：掃全批
    hits = []
    for f, data in yamls:
        sigs = _fishing_signals(data)
        if sigs:
            hits.append(f"{f.name}: {sigs}")

    if hits:
        return "FAIL", (
            f"C-013B：mode={mode} 但偵測到釣魚信號（{len(hits)} 支）。"
            f"Policy：{fishing_policy.get('detail','')}。"
            f"命中：{hits}"
        )
    return "PASS", f"C-013B：無釣魚信號（mode={mode}）"


def chk_c014_card_style(yamls, batch_dir: Path, owner: str, batch_tag: str) -> tuple[str, str]:
    """C-014：知識型圖卡風格 18 選 1 推薦走過（B6 2026-06-05：知識圖卡改按需 — intent-aware）。
    判定邏輯：先看本批有沒有「知識圖卡意圖」（任一腳本填了非空「圖卡主題」）。
      - 無意圖 + 無風格選擇檔 → PASS 跳過（本批本來就不做知識圖卡，不 WARN-spam）。
      - 有意圖 + 無風格選擇檔 → WARN（要做知識圖卡卻沒走 18 選 1 推薦制，提醒補）。
      - 有風格選擇檔 → 驗風格 id。
    釣魚部 dm_card（①）不在此 check（走 C-013），其用 dm_card 欄位、非「圖卡主題」。"""
    # B6：本批是否有知識圖卡意圖（腳本填了非空「圖卡主題」；釣魚部用 dm_card 不填此欄）
    has_knowledge_card_intent = any(
        str((data or {}).get("圖卡主題") or "").strip()
        for _, data in (yamls or [])
    )
    # B6：無知識圖卡意圖 → 本批不做知識圖卡，直接 PASS-skip（先於 owner 目錄判斷，避免 owner 不在 map 時被 WARN-spam）
    if not has_knowledge_card_intent:
        return "PASS", "本批無知識圖卡意圖（無腳本填「圖卡主題」），按需跳過 C-014（B6 2026-06-05）"
    # 以下只在「本批確實要做知識圖卡」時才走：找風格選擇檔
    # 找業主核心檔資料夾（7 業主全列；缺漏業主走 OWNER_PREF_PATHS fallback）
    # Phase 2 Step 4：從 projection 產（key 順序對齊原硬編：瑞祥/仲豪/昀臻/叭噗_小C/阿奇/詩婷/溫蒂）
    owner_dir_map = {
        owner: L2_BASE / rec["owner_dir"] / "00_業主核心檔" / "source_overlay"
        for owner, rec in sorted(
            _OWNER_PROJ.items(),
            key=lambda x: ["瑞祥", "仲豪", "昀臻", "叭噗_小C", "阿奇", "詩婷", "溫蒂"].index(x[0])
            if x[0] in ["瑞祥", "仲豪", "昀臻", "叭噗_小C", "阿奇", "詩婷", "溫蒂"] else 99
        )
    }
    overlay_dir = owner_dir_map.get(owner)
    if not overlay_dir or not overlay_dir.exists():
        return "WARN", f"本批有知識圖卡意圖但找不到業主 source_overlay 資料夾（{overlay_dir}），無法驗風格選擇檔"
    # 抓批次編號（e.g. 第01批）
    batch_num_m = re.search(r"第(\d+)批", batch_tag)
    batch_num = batch_num_m.group(0) if batch_num_m else batch_tag
    # 找 _<業主>圖卡風格選擇_<批次>.md 或 _圖卡風格_*.md
    candidates = list(overlay_dir.glob(f"*圖卡風格*{batch_num}*.md"))
    if not candidates:
        candidates = list(overlay_dir.glob("*圖卡風格*.md"))
    if not candidates:
        return "WARN", f"本批有知識圖卡意圖（腳本填了「圖卡主題」）但找不到圖卡風格選擇檔（{overlay_dir}，批次 {batch_num}）— 要做知識圖卡請走 18 選 1 推薦制，建 _圖卡風格選擇_{batch_num}.md"
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


def _load_voice_lock_from_l2(owner: str) -> Optional[dict]:
    """從 L2 偏好.md 的 fenced yaml 區塊解析 owner_voice，回傳通用 shape dict 或 None。

    通用 shape（回傳給上層統一吃）：
      {
        'catchphrase': list[str],
        'signature_words': list[str],
        'banned_phrases': list[str],
      }

    叭噗_小C 特例：L2 偏好.md 用拆鍵
      bappu_catchphrase / xiaoc_catchphrase → 合併成 catchphrase list
      bappu_banned / xiaoc_banned → 合併成 banned_phrases list
    其餘 6 家：直接用通用鍵 catchphrase / signature_words / banned_phrases。

    回傳 None 情形：
      - L2 偏好.md 不存在或讀取失敗
      - fenced yaml 區塊不存在
      - owner_voice 區塊不存在
    """
    pref_path = OWNER_PREF_PATHS.get(owner)
    if not pref_path or not pref_path.exists():
        return None
    try:
        text = pref_path.read_text(encoding='utf-8')
    except Exception:
        return None

    # 抓 ```yaml ... ``` fenced 區塊，找含 voice_lock/owner_voice 的那個
    fence_re = re.compile(r'```yaml\s*\n(.*?)```', re.DOTALL)
    raw_voice: Optional[dict] = None
    for m in fence_re.finditer(text):
        block_text = m.group(1)
        if 'owner_voice' not in block_text and 'bappu_catchphrase' not in block_text:
            continue
        try:
            parsed = yaml.safe_load(block_text)
        except Exception:
            continue
        if not isinstance(parsed, dict):
            continue
        # owner_voice 是子鍵
        if 'owner_voice' in parsed:
            raw_voice = parsed['owner_voice']
            break
        # 叭噗：拆鍵直接在頂層
        if 'bappu_catchphrase' in parsed or 'bappu_banned' in parsed:
            raw_voice = parsed
            break

    if raw_voice is None:
        return None

    if owner == '叭噗_小C':
        # 拆鍵正規化 → 通用 shape
        bappu_cp  = raw_voice.get('bappu_catchphrase', []) or []
        xiaoc_cp  = raw_voice.get('xiaoc_catchphrase', []) or []
        bappu_ban = raw_voice.get('bappu_banned', []) or []
        xiaoc_ban = raw_voice.get('xiaoc_banned', []) or []
        return {
            'catchphrase':     list(bappu_cp) + list(xiaoc_cp),
            'signature_words': list(raw_voice.get('signature_words', []) or []),
            'banned_phrases':  list(bappu_ban) + list(xiaoc_ban),
        }
    else:
        return {
            'catchphrase':     list(raw_voice.get('catchphrase', []) or []),
            'signature_words': list(raw_voice.get('signature_words', []) or []),
            'banned_phrases':  list(raw_voice.get('banned_phrases', []) or []),
        }


def _get_owner_voice(data: dict, owner: str) -> Optional[dict]:
    """取 owner_voice，來源 precedence：
    1. 腳本 yaml 頂層 data['owner_voice']（若存在且有 banned_phrases 或 catchphrase 鍵）
    2. fallback：_load_voice_lock_from_l2(owner)
    回傳通用 shape dict 或 None。
    """
    ov = data.get('owner_voice')
    _has_common = isinstance(ov, dict) and (
        'banned_phrases' in ov or 'catchphrase' in ov or 'signature_words' in ov
    )
    # 叭噗_小C 純拆鍵頂層（只 bappu_/xiaoc_、無通用鍵）也算有頂層 voice；
    # 拆鍵 gate 僅限叭噗觸發 — 避免非叭噗業主誤帶拆鍵→gate 成立卻走通用空 return→誤阻 fallback L2 漏守門（Codex P1 連鎖）
    _has_bappu_split = (
        isinstance(ov, dict) and owner == '叭噗_小C' and (
            'bappu_catchphrase' in ov or 'xiaoc_catchphrase' in ov
            or 'bappu_banned' in ov or 'xiaoc_banned' in ov
        )
    )
    if _has_common or _has_bappu_split:
        if owner == '叭噗_小C':
            bappu_cp  = ov.get('bappu_catchphrase', ov.get('catchphrase', [])) or []
            xiaoc_cp  = ov.get('xiaoc_catchphrase', []) or []
            bappu_ban = ov.get('bappu_banned', ov.get('banned_phrases', [])) or []
            xiaoc_ban = ov.get('xiaoc_banned', []) or []
            return {
                'catchphrase':     list(bappu_cp) + list(xiaoc_cp),
                'signature_words': list(ov.get('signature_words', []) or []),
                'banned_phrases':  list(bappu_ban) + list(xiaoc_ban),
            }
        return {
            'catchphrase':     list(ov.get('catchphrase', []) or []),
            'signature_words': list(ov.get('signature_words', []) or []),
            'banned_phrases':  list(ov.get('banned_phrases', []) or []),
        }
    # fallback L2
    return _load_voice_lock_from_l2(owner)


def _normalize_voice_text(s: str) -> str:
    """正規化台詞文字，供 catchphrase / banned 比對用。
    步驟：unicode NFKC → 省略號統一 → 全/半形標點統一 → 去空白。
    """
    import unicodedata as _uc
    s = _uc.normalize('NFKC', s)
    s = re.sub(r'[…⋯]|\.\.\.', '___ELLIPSIS___', s)
    s = s.replace('？', '?').replace('，', ',').replace('！', '!').replace('。', '.')
    s = re.sub(r'\s+', '', s)
    return s


def _catchphrase_to_regex(phrase: str) -> re.Pattern:
    """把 catchphrase 轉成正規表達式，省略號當萬用符（非貪婪，最多 30 字）。"""
    import unicodedata as _uc
    norm = _uc.normalize('NFKC', str(phrase))
    norm = norm.replace('？', '?').replace('，', ',').replace('！', '!').replace('。', '.')
    parts = re.split(r'[…⋯]|\.\.\.', norm)
    escaped = [re.escape(p) for p in parts if p]  # 過濾空段（防純省略號/空 phrase）
    if not escaped:
        return re.compile(r'(?!)')  # 空 phrase → 永不匹配（防 match-all 假 PASS，御史 Codex 盲點2）
    pattern = r'.{0,30}?'.join(escaped)
    return re.compile(pattern, re.DOTALL)


def _extract_dialogue_lines(data: dict, owner: str) -> list[str]:
    """抽出一支 yaml 全文所有台詞行（含翠文）。"""
    lines_out = []
    scenes = data.get('scenes', [])
    if not isinstance(scenes, list):
        return []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        # 通用化：抓所有以「台詞」開頭的欄位（台詞 / 台詞_溫蒂 / 台詞_詩婷 / 台詞_叭噗 / 台詞_小C …）
        # + 字幕類通用欄位。涵蓋全 7 業主「台詞_<業主名>」格式（叭噗雙人兩行自然納入，免寫死特例）。
        for key, val in scene.items():
            if not val:
                continue
            # 收嚴：只認「台詞」或「台詞_<業主>」，排除「台詞備註/台詞數」等非台詞 key（御史 Codex 盲點1）
            if key == '台詞' or str(key).startswith('台詞_') or key in ('旁白', '字幕', '翠文', 'dialogue'):
                lines_out.append(str(val))
    return lines_out


def _extract_hook_dialogue_lines(data: dict, owner: str) -> list[str]:
    """只抽 Hook 段（scenes[0]，0-3s）的台詞行。"""
    scenes = data.get('scenes', [])
    if not isinstance(scenes, list) or not scenes:
        return []
    hook_scene = scenes[0]
    if not isinstance(hook_scene, dict):
        return []
    lines_out = []
    # 通用化：抓 Hook 段所有以「台詞」開頭的欄位 + 字幕類（涵蓋全 7 業主 台詞_<業主> 格式）
    for key, val in hook_scene.items():
        if not val:
            continue
        # 收嚴：只認「台詞」或「台詞_<業主>」，排除「台詞備註/台詞數」等非台詞 key（御史 Codex 盲點1）
        if key == '台詞' or str(key).startswith('台詞_') or key in ('旁白', '字幕', '翠文', 'dialogue'):
            lines_out.append(str(val))
    return lines_out


# ── FIX-1：chk_v2_001b — banned_phrases 禁語守門 ──
def chk_v2_001b_banned_phrases(data: dict, fname: str, owner: str = '') -> tuple[str, str]:
    """V2-001b：全文台詞不得出現業主聲音禁用語（banned_phrases）。

    來源 precedence：
    1. 腳本 yaml 頂層 data['owner_voice']['banned_phrases']
    2. fallback：L2 偏好.md fenced yaml owner_voice.banned_phrases
    3. 叭噗_小C：合併 bappu_banned + xiaoc_banned
    三者皆無 → SKIP（非無風險 PASS）

    legacy 判定：_is_v2025_legacy()（不用過期的 _is_legacy_yaml）。
    fname 需傳入「parent_dir/file」格式，讓 _extract_batch_date 能抓批次目錄日期。
    """
    if _is_v2025_legacy(data, fname):
        return "WARN", "legacy 批次（6/1 前）— banned_phrases 守門 WARN，新批次強制 FAIL"

    if not owner:
        return "SKIP", "未傳入 owner — banned_phrases 跳過"

    ov = _get_owner_voice(data, owner)
    if ov is None:
        return "WARN", f"owner_voice 無法從 yaml 或 L2 偏好.md 取得（{owner}）— banned_phrases 守門跳過"

    banned = ov.get('banned_phrases', [])
    if not banned:
        return "WARN", f"banned_phrases 清單空（{owner}）— 確認 L2 偏好.md 已填寫"

    all_lines = _extract_dialogue_lines(data, owner)
    if not all_lines:
        return "WARN", "找不到台詞欄位 — banned_phrases 守門跳過"

    hits = []
    for phrase in banned:
        p_norm = _normalize_voice_text(str(phrase))
        for line in all_lines:
            l_norm = _normalize_voice_text(line)
            if p_norm in l_norm:
                hits.append(f"「{phrase}」出現於：{line[:40]}")

    if hits:
        return "FAIL", "台詞命中 banned_phrases：" + "；".join(hits)
    return "PASS", f"全文台詞無 banned_phrases 命中（banned={len(banned)} 條）"


# ── FIX-2：chk_v2_001c — catchphrase 入 Hook 守門（首期 WARN） ──
def chk_v2_001c_catchphrase_in_hook(data: dict, fname: str, owner: str = '') -> tuple[str, str]:
    """V2-001c：Hook 段（scenes[0] 0-3s）應有業主 catchphrase/signature_words 語料。

    比對：Hook 段所有台詞行 × catchphrase + signature_words，任一命中即 PASS。
    叭噗_小C：台詞_叭噗 + 台詞_小C 兩行各別比。
    正規化：unicode NFKC + 省略號萬用 + 全/半形統一 + 去空白。

    上線策略：首期 WARN（不擋 commit）。
    門檻：觀察 3 批、誤擋率 < 10% 才升 FAIL。

    legacy：_is_v2025_legacy()。
    """
    if _is_v2025_legacy(data, fname):
        return "WARN", "legacy 批次（6/1 前）— catchphrase Hook 守門 WARN"

    if not owner:
        return "WARN", "未傳入 owner — catchphrase Hook 守門跳過"

    ov = _get_owner_voice(data, owner)
    if ov is None:
        return "WARN", f"owner_voice 無法取得（{owner}）— catchphrase Hook 守門跳過"

    catchphrases = ov.get('catchphrase', [])
    sig_words    = ov.get('signature_words', [])
    all_phrases  = list(catchphrases) + list(sig_words)

    if not all_phrases:
        return "WARN", f"catchphrase/signature_words 清單空（{owner}）— 確認 L2 偏好.md"

    hook_lines = _extract_hook_dialogue_lines(data, owner)
    if not hook_lines:
        return "WARN", "Hook 段找不到台詞行 — catchphrase 守門跳過"

    for phrase in all_phrases:
        try:
            pat = _catchphrase_to_regex(str(phrase))
        except Exception:
            continue
        for line in hook_lines:
            if pat.search(line):
                return "PASS", f"Hook 命中 catchphrase：「{phrase}」"

    return "WARN", (
        f"Hook 段未見 catchphrase/signature_words（{owner}）— "
        f"確認業主聲音是否有入 Hook（觀察 3 批後升 FAIL）"
    )


def chk_v2_001_voice_lock(data: dict, fname: str, owner: str = '') -> tuple[str, str]:
    """V2-001：voice_lock 欄位存在 + shape 驗（FIX-1c）。

    shape 驗邏輯（對齊 FIX-1c 契約）：
    - voice_lock 資料源頭以 L2 偏好.md 為準，腳本 yaml 頂層為選配快取。
    - 若 voice_lock:true → 嘗試從 L2 偏好.md 撈 owner_voice 三欄；
      撈不到才 WARN（不強制要求腳本 yaml 頂層有 owner_voice）。
    """
    has_field = 'voice_lock' in data
    if not has_field:
        if _is_legacy_yaml(data):
            return "WARN", f"缺 voice_lock（legacy yaml 過渡期，legacy_allowed_until: {data.get('legacy_allowed_until')}）"
        return "FAIL", "缺 voice_lock 欄位（新批次必須聲明 true/false）"

    val = data['voice_lock']
    # voice_lock: false 或未啟用 → 不驗 shape
    if not val:
        return "PASS", f"voice_lock = {val}（明確聲明不強制語料）"

    # voice_lock: true → 驗 shape（FIX-1c）
    if owner:
        ov = _get_owner_voice(data, owner)
        if ov is None:
            return "WARN", (
                f"voice_lock=true 但 owner_voice 無法從 yaml 或 L2 偏好.md 撈到"
                f"（owner={owner}）— 請補 L2 偏好.md §voice_lock yaml 欄位"
            )
        missing = [k for k in ('catchphrase', 'signature_words', 'banned_phrases') if not ov.get(k)]
        if missing:
            return "WARN", f"voice_lock=true，owner_voice 缺欄位：{missing}（owner={owner}）"
        return "PASS", f"voice_lock = {val}，owner_voice 三欄齊（owner={owner}）"

    return "PASS", f"voice_lock = {val}（明確聲明）"


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

# 強制位 keyword 對應表（V2-006）— 拆 BASE（3 件）+ FISHING_SLOT（1 件）
REQUIRED_SLOTS_BASE = {
    "毒舌正能量":   ["毒舌正能量", "毒舌"],
    "純雞湯":       ["純雞湯"],
    "專業位":       ["專業位", "知識", "教學", "教育型", "Erika 拆解派"],
}
REQUIRED_SLOTS_FISHING = {
    "釣魚部": ["釣魚", "fishing"],
}
# 向後相容（舊引用點暫留，以 BASE+FISHING 合集代替舊 4-key dict）
REQUIRED_SLOTS = {**REQUIRED_SLOTS_FISHING, **REQUIRED_SLOTS_BASE}

# 昀臻醫療效能禁用詞（V2-012 — 對齊第 09 批算盤報告 20 條）
BEAUTY_MED_WORDS = [
    "發炎", "抗發炎", "修復", "治療", "根治", "痊癒", "處方",
    "屏障修復", "痘疤修復", "一定壞", "至少三年", "眼尾平了",
    "活化", "再生", "醫美等級", "醫療級", "藥用", "復原", "癒合", "炎症"
]

# 虛構故事信號詞（V2-011 — 仲豪/阿奇）
FICTION_SIGNAL_WORDS = ["有個客戶說", "曾經有個案例", "我朋友的客戶", "聽說有個", "傳說中的"]


def chk_v2_006_required_slot(yamls: list[tuple[Path, dict]], fishing_policy: Optional[dict] = None) -> tuple[str, str]:
    """V2-006：強制位覆蓋驗（釣魚/毒舌/雞湯/專業位）— batch-level（雙模式）

    mode 決定強制位數量：
    - off     → 3 強制位（BASE：毒舌/純雞湯/專業位）；釣魚部 key 不建不驗
    - opt_in  → 4 強制位（BASE + 釣魚部）；釣魚部 exactly 1 支
    - legacy  → 4 強制位（BASE + 釣魚部）；不加 exactly 1 限制（防舊批回歸失敗）
    - invalid → FAIL（policy 本身有問題）

    Codex R1 盲點 4 修法：用 required_slot 欄位 / faction 含嗆辣派 ≠ 毒舌
    """
    if fishing_policy is None:
        fishing_policy = {"mode": "off", "batch_date": None, "detail": "未傳入 policy，保守 off"}

    mode = fishing_policy.get("mode", "off")

    if mode == "invalid":
        return "FAIL", f"V2-006：fishing_policy invalid → batch FAIL。{fishing_policy.get('detail','')}"

    valid = [(f, d) for f, d in yamls if "__parse_error__" not in d and "__schema_error__" not in d]

    # 按 mode 決定要驗的 slot 集合
    if mode == "off":
        slots_to_check = REQUIRED_SLOTS_BASE
    else:  # opt_in / legacy
        slots_to_check = {**REQUIRED_SLOTS_BASE, **REQUIRED_SLOTS_FISHING}

    # 動態建 found dict（只建納入驗證的 slot）
    found = {slot: [] for slot in slots_to_check}

    for f, data in valid:
        _raw_slot = str(data.get('required_slot', '') or data.get('強制位', ''))
        # 向後相容：舊 yaml 填 "Erika 拆解派" → 映射到新 key "專業位"
        _SLOT_ALIAS = {"Erika 拆解派": "專業位"}
        slot_field = _SLOT_ALIAS.get(_raw_slot, _raw_slot)
        type_field = str(data.get('type', ''))
        for slot, keywords in slots_to_check.items():
            if slot_field == slot:
                found[slot].append(f.name)
                continue
            for kw in keywords:
                if kw in type_field:
                    if f.name not in found[slot]:
                        found[slot].append(f.name)
                    break
        # is_fishing 輔助偵測（只在 釣魚部 在 found 時才 append）
        if "釣魚部" in found and data.get('is_fishing') and f.name not in found["釣魚部"]:
            found["釣魚部"].append(f.name)
        if data.get('is_chicken_soup') and f.name not in found["純雞湯"]:
            found["純雞湯"].append(f.name)

    missing = [s for s, files in found.items() if not files]
    req_count = len(slots_to_check)
    if missing:
        return "FAIL", f"{req_count} 強制位缺 {len(missing)} 件：{missing}（mode={mode}，建議 yaml 加 required_slot 欄位）"

    # opt_in 額外驗：釣魚信號 exactly 1 支（union：slot/type/is_fishing 找到 ∪ dm_card-only 信號）
    if mode == "opt_in":
        fishing_files = set(found.get("釣魚部", [])) | {
            f.name for f, data in valid if _fishing_signals(data, legacy=False)
        }
        if len(fishing_files) != 1:
            return "FAIL", f"V2-006 opt_in：釣魚信號應 exactly 1 支，實際 {len(fishing_files)} 支：{sorted(fishing_files)}"

    counts = {s: len(files) for s, files in found.items()}
    return "PASS", f"{req_count} 強制位齊備（mode={mode}）：{counts}"


def chk_v2_007_threads_seven(batch_dir: Path) -> tuple[str, str]:
    """V2-007：Threads 脆文 >= threads_posts 篇存在驗 — batch-level
    Glob *Threads*.md / *脆文*.md / threads_*.md，v2 優先。
    B 段 2026-06-05：expected 改讀 L0 batch_spec（廢硬編 7）。
    """
    expected = _load_l0_batch_spec()["threads_posts"]
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
    if count < expected:
        return "FAIL", f"{target.name} 只找到 {count} 篇脆文（要 ≥ {expected}）"
    return "PASS", f"{target.name} 找到 {count} 篇脆文（≥ {expected}）"


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
    """V2-012：美容業主醫療效能禁用詞驗 — per-file（昀臻 / 溫蒂 等美容業主）"""
    BEAUTY_OWNERS = {'昀臻', '溫蒂'}
    if owner not in BEAUTY_OWNERS:
        return "PASS", "(非美容業主，跳過)"
    all_text = get_all_text(data)
    hits = [w for w in BEAUTY_MED_WORDS if w in all_text]
    if hits:
        return "FAIL", f"{owner}台詞含醫療效能禁用詞：{hits[:5]}（對齊第 09 批算盤 20 條）"
    return "PASS", f"{owner}醫療詞驗 PASS"


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


# ════════════════════════════════════════════
# C-cta-mix / C-content-mix（P3 比例驗證器 2026-06-08）
# 規格來源：_P3_ledger_v3_2026-06-08.md §F / §H
# ════════════════════════════════════════════

import datetime as _cta_dt


def _parse_batch_date_str(batch_tag: str) -> Optional[_cta_dt.date]:
    """從 batch_tag 字串抓 YYYY-MM-DD 日期，用於 cutover gate。"""
    m = re.search(r"(\d{4})[_\-](\d{2})[_\-](\d{2})", batch_tag)
    if m:
        try:
            return _cta_dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def chk_c_cta_mix(
    yamls: list[tuple[Path, dict]],
    owner: str,
    pref_text: Optional[str],
    batch_tag: str = "",
) -> tuple[str, str]:
    """C-cta-mix（hard）— 批次 CTA 類型分佈 vs 業主 L2 cta_mix 宣告。

    規格（§F §H _P3_ledger_v3_2026-06-08.md）：
    - 讀業主偏好.md 的 ```kb-rule category: cta_mix``` block
    - 找不到 block → WARN graceful SKIP（非 crash 非 FAIL）
    - provisional=True / decision_status=proposed / enforcement!=hard → 降 advisory（WARN-surface 不 FAIL）
    - cutover gate：batch_date < effective_from → WARN-waiver（legacy 批次保護）
    - post-cutover 未知 label（aliases 無交集）→ FAIL（不放水）
    - 缺 source field → FAIL（hard + post-cutover + confirmed）
    - 比例超 tolerance_count → FAIL
    - _MIX_PARSER_OK=False → WARN 不 crash
    """
    if not _MIX_PARSER_OK or _parse_mix_block is None:
        return "WARN", "C-cta-mix：_mix_parser 不可用，CTA 比例驗證跳過"

    if not pref_text:
        return "WARN", f"C-cta-mix：找不到業主 '{owner}' 偏好.md，跳過"

    result = _parse_mix_block(pref_text, "cta_mix")

    # 找不到 block
    if not result.found:
        return "WARN", f"C-cta-mix：{result.warnings[0] if result.warnings else '無 cta_mix block，SKIP'}"

    # enforcement=none → SKIP
    if result.enforcement == "none":
        return "PASS", f"C-cta-mix：enforcement=none（阿奇由 C-012 管），SKIP"

    # 判斷 effective enforcement：provisional / proposed → 降 advisory
    is_hard = (
        result.enforcement == "hard"
        and not result.provisional
        and result.decision_status == "confirmed"
    )

    # cutover gate（§H-1）
    batch_date = _parse_batch_date_str(batch_tag)
    if result.effective_from:
        try:
            cutover_date = _cta_dt.date.fromisoformat(result.effective_from)
            if batch_date is not None and batch_date < cutover_date:
                return "WARN", (
                    f"C-cta-mix：batch_date {batch_date} < effective_from {cutover_date} → "
                    f"WARN-waiver（legacy 批次，CTA 比例驗證暫豁免）"
                )
        except ValueError:
            pass  # effective_from 格式錯 → 繼續驗

    if not result.items:
        msg = "C-cta-mix：cta_mix block 無 mix 項目，SKIP"
        return ("WARN", msg)

    # 統計批次 CTA label
    valid = [(f, d) for f, d in yamls if "__parse_error__" not in d and "__schema_error__" not in d]
    total = len(valid)
    if total == 0:
        return "WARN", "C-cta-mix：批次無有效 yaml，跳過"

    actual_count: dict[str, int] = {}
    missing_field_files: list[str] = []

    for f, data in valid:
        label = _get_label_from_yaml(data, result)
        if label is None or not str(label).strip():
            missing_field_files.append(f.name)
            continue
        canonical = _resolve_label(str(label).strip(), result.items)
        if canonical is None:
            # unknown label（§H-2）
            key = f"[UNKNOWN]{label}"
        else:
            key = canonical
        actual_count[key] = actual_count.get(key, 0) + 1

    # 缺 source field 處理（§H-2）
    if missing_field_files:
        msg = (
            f"C-cta-mix：{len(missing_field_files)} 支腳本缺 CTA 類型欄位"
            f"（{missing_field_files[:3]}{'...' if len(missing_field_files) > 3 else ''}）"
        )
        if is_hard:
            return "FAIL", msg
        return "WARN", msg + "（advisory/provisional，WARN）"

    # unknown label 處理（§H-2）
    unknown_labels = {k: v for k, v in actual_count.items() if k.startswith("[UNKNOWN]")}
    if unknown_labels:
        ul_desc = ", ".join(f"{k.replace('[UNKNOWN]','')}×{v}" for k, v in unknown_labels.items())
        msg = f"C-cta-mix：未知 CTA 標籤（aliases 無交集）：{ul_desc}"
        if is_hard:
            return "FAIL", msg + f"（confirmed hard post-cutover → FAIL）"
        return "WARN", msg + "（advisory/provisional → WARN-waiver）"

    # 比例偏差檢查（§H-3，count-based ±tolerance_count）
    tol = result.tolerance_count
    over_tol = []
    for item in result.items:
        expected = item.range_min, item.range_max
        if item.range_min is None or item.range_max is None:
            # 無 range：用 target_count ± tol
            tc = item.target_count or 0
            exp_lo, exp_hi = max(0, tc - tol), tc + tol
        else:
            exp_lo, exp_hi = item.range_min, item.range_max
        actual = actual_count.get(item.name, 0)
        if not (exp_lo <= actual <= exp_hi):
            over_tol.append(
                f"{item.name} 預期 [{exp_lo},{exp_hi}] 實際 {actual}"
            )

    if over_tol:
        msg = f"C-cta-mix 比例超出 ±{tol}：" + "；".join(over_tol) + f"  （實際：{dict(actual_count)}）"
        if is_hard:
            return "FAIL", msg
        return "WARN", msg + "（advisory/provisional → WARN-surface）"

    return "PASS", (
        f"C-cta-mix 對齊（±{tol} 內）：{dict(actual_count)}"
        f"{'（advisory）' if not is_hard else ''}"
    )


def chk_c_content_mix(
    yamls: list[tuple[Path, dict]],
    owner: str,
    pref_text: Optional[str],
    batch_tag: str = "",
) -> tuple[str, str]:
    """C-content-mix — 批次內容軸分佈 vs 業主 L2 content_mix 宣告。

    規格（§F §H _P3_ledger_v3_2026-06-08.md §D）：
    - 溫蒂：enforcement=hard（讀 `內容軸` 欄，可驗）
    - 阿奇：enforcement=none（mirrors C-012，**不讀雙身份分類**）→ SKIP
    - 其餘：advisory（parse + surface 印宣告 vs 實際，不 FAIL）
    - 找不到 block → WARN graceful SKIP
    - cutover / provisional / proposed 同 C-cta-mix 降 advisory
    """
    if not _MIX_PARSER_OK or _parse_mix_block is None:
        return "WARN", "C-content-mix：_mix_parser 不可用，內容軸比例驗證跳過"

    if not pref_text:
        return "WARN", f"C-content-mix：找不到業主 '{owner}' 偏好.md，跳過"

    result = _parse_mix_block(pref_text, "content_mix")

    # 找不到 block
    if not result.found:
        return "WARN", f"C-content-mix：{result.warnings[0] if result.warnings else '無 content_mix block，SKIP'}"

    # enforcement=none → SKIP（阿奇 C-012 管）
    if result.enforcement == "none":
        return "PASS", f"C-content-mix：enforcement=none（{owner} 由其他 check 管），SKIP"

    # 判斷 effective enforcement
    is_hard = (
        result.enforcement == "hard"
        and not result.provisional
        and result.decision_status == "confirmed"
    )

    # cutover gate
    batch_date = _parse_batch_date_str(batch_tag)
    if result.effective_from:
        try:
            cutover_date = _cta_dt.date.fromisoformat(result.effective_from)
            if batch_date is not None and batch_date < cutover_date:
                return "WARN", (
                    f"C-content-mix：batch_date {batch_date} < effective_from {cutover_date} → "
                    f"WARN-waiver（legacy 批次保護）"
                )
        except ValueError:
            pass

    if not result.items:
        return "WARN", "C-content-mix：content_mix block 無 mix 項目，SKIP"

    # 統計批次內容軸 label
    valid = [(f, d) for f, d in yamls if "__parse_error__" not in d and "__schema_error__" not in d]
    total = len(valid)
    if total == 0:
        return "WARN", "C-content-mix：批次無有效 yaml，跳過"

    actual_count: dict[str, int] = {}
    missing_field_files: list[str] = []

    for f, data in valid:
        label = _get_label_from_yaml(data, result)
        if label is None or not str(label).strip():
            missing_field_files.append(f.name)
            continue
        canonical = _resolve_label(str(label).strip(), result.items)
        if canonical is None:
            key = f"[UNKNOWN]{label}"
        else:
            key = canonical
        actual_count[key] = actual_count.get(key, 0) + 1

    # 缺 source field
    if missing_field_files:
        msg = (
            f"C-content-mix：{len(missing_field_files)} 支腳本缺內容軸欄位"
            f"（{missing_field_files[:3]}{'...' if len(missing_field_files) > 3 else ''}）"
        )
        if is_hard:
            return "FAIL", msg
        return "WARN", msg + "（advisory，WARN）"

    # unknown label
    unknown_labels = {k: v for k, v in actual_count.items() if k.startswith("[UNKNOWN]")}
    if unknown_labels:
        ul_desc = ", ".join(f"{k.replace('[UNKNOWN]','')}×{v}" for k, v in unknown_labels.items())
        msg = f"C-content-mix：未知內容軸標籤：{ul_desc}"
        if is_hard:
            return "FAIL", msg + "（confirmed hard → FAIL）"
        return "WARN", msg + "（advisory → WARN-waiver）"

    # 比例偏差（advisory 只 surface，不 FAIL）
    tol = result.tolerance_count
    over_tol = []
    for item in result.items:
        if item.range_min is not None and item.range_max is not None:
            exp_lo, exp_hi = item.range_min, item.range_max
        elif item.target_count is not None:
            exp_lo, exp_hi = max(0, item.target_count - tol), item.target_count + tol
        else:
            continue
        actual = actual_count.get(item.name, 0)
        if not (exp_lo <= actual <= exp_hi):
            over_tol.append(
                f"{item.name} 預期 [{exp_lo},{exp_hi}] 實際 {actual}"
            )

    if over_tol:
        msg = (
            f"C-content-mix 比例偏差：" + "；".join(over_tol)
            + f"  （實際：{dict(actual_count)}）"
        )
        if is_hard:
            return "FAIL", msg
        return "WARN", msg + "（advisory，WARN-surface）"

    return "PASS", (
        f"C-content-mix 對齊（±{tol} 內）：{dict(actual_count)}"
        f"{'（advisory）' if not is_hard else ''}"
    )


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

# 釣魚部下架 cutoff（2026-06-06 起新批預設 OFF）
_FISHING_CUTOFF = _dt.date(2026, 6, 6)


def _fishing_signals(data: dict, legacy: bool = False) -> list:
    """偵測 yaml 是否含有釣魚部相關信號，回傳信號描述清單（空 list = 無信號）。
    供 C-013、C-013B 共用（V2-006 不呼叫本函式，自行直接讀 required_slot/type/is_fishing）。

    legacy=True（霸告 2026-06-05 修零回歸）：只用「舊碼偵測過的 criteria」——
      title/template/pattern 含釣魚部 + dm_card dict + 釣魚部標記 + dm_card_配套，
      **排除新增的 type / required_slot / is_fishing 三欄**。
    用途：legacy 模式（6/6 前舊批）C-013 必須與舊碼逐字同結果，否則現役批（詩婷01/昀臻12
      用 required_slot/is_fishing 標釣魚、舊碼漏偵測）會被新偵測誤判 FAIL，違反澤君「舊批不回頭算帳」。
    off/opt_in（新批）用 legacy=False 全偵測 → fail-closed 不漏。
    """
    signals = []
    title    = str(data.get("title", ""))
    template = str(data.get("template", ""))
    pattern  = str(data.get("pattern", ""))
    type_    = str(data.get("type", ""))
    req_slot = str(data.get("required_slot", ""))

    if "釣魚部" in title:
        signals.append(f"title 含「釣魚部」")
    if "釣魚部" in template:
        signals.append(f"template 含「釣魚部」")
    if "釣魚部" in pattern:
        signals.append(f"pattern 含「釣魚部」")
    if not legacy:
        # ↓ 3 欄為新增偵測（舊碼未查）；legacy 排除以保舊批逐字零回歸
        if "fishing" in type_.lower() or "釣魚部" in type_:
            signals.append(f"type 含釣魚信號：{type_!r}")
        if "釣魚部" in req_slot or "fishing" in req_slot.lower():
            signals.append(f"required_slot 含釣魚信號：{req_slot!r}")
        if data.get("is_fishing"):
            signals.append("is_fishing=true")
    if isinstance(data.get("dm_card"), dict):
        signals.append("dm_card 欄位存在（dict）")
    if data.get("釣魚部標記"):
        signals.append("釣魚部標記 欄位存在")
    if data.get("dm_card_配套") or data.get("dm_card配套"):
        signals.append("dm_card_配套 欄位存在")
    return signals


def load_fishing_policy(batch_dir: "Path", yamls: list) -> dict:
    """讀取 _batch_flags.yml 決定釣魚部模式。

    回傳 dict:
      mode      ∈ {off, opt_in, legacy, invalid}
      batch_date: _dt.date | None
      detail    : 說明字串

    判定邏輯（§7）：
    - 無 flag 檔：batch_date < _FISHING_CUTOFF → legacy；否則 → off
    - enabled 非 boolean true → off/legacy（不可把 "true" 字串當真）
    - enabled:true 但 approved_by≠澤君 / approved_at 不可 parse 或 <cutoff / reason 空 → invalid
    - 完整有效 → opt_in

    batch_date：對批內每個 yaml 用 _extract_batch_date 取日期取 max；再 fallback 用目錄名抽。
    """
    # 計算 batch_date
    dates = []
    for f, data in yamls:
        d = _extract_batch_date(data, f"{batch_dir.name}/{f.name}")
        if d:
            dates.append(d)
    # fallback：直接從目錄名抽
    dir_date = _extract_batch_date({}, str(batch_dir.name))
    if dir_date:
        dates.append(dir_date)
    batch_date = max(dates) if dates else None

    # 讀旗標檔（必須 .yml，不用 .yaml 避免被 load_yamls glob 算成第 14 支）
    flag_path = batch_dir / "_batch_flags.yml"
    if not flag_path.exists():
        if batch_date is not None and batch_date < _FISHING_CUTOFF:
            return {"mode": "legacy", "batch_date": batch_date,
                    "detail": f"無旗標檔 + 批次日期 {batch_date} < {_FISHING_CUTOFF} → legacy"}
        else:
            return {"mode": "off", "batch_date": batch_date,
                    "detail": f"無旗標檔 + 批次日期 {batch_date or '未知'} ≥ {_FISHING_CUTOFF} → off（fail-closed）"}

    # 有旗標檔
    try:
        import yaml as _yaml_mod
        raw = _yaml_mod.safe_load(flag_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return {"mode": "invalid", "batch_date": batch_date,
                "detail": f"_batch_flags.yml 解析失敗：{e} → invalid（fail-closed）"}

    if not isinstance(raw, dict):
        return {"mode": "invalid", "batch_date": batch_date,
                "detail": f"_batch_flags.yml top-level 非 mapping（{type(raw).__name__}）→ invalid（fail-closed）"}

    fishing_cfg = raw.get("fishing_dm_card", {}) or {}
    if not isinstance(fishing_cfg, dict):
        return {"mode": "invalid", "batch_date": batch_date,
                "detail": f"_batch_flags.yml fishing_dm_card 非 mapping（{type(fishing_cfg).__name__}）→ invalid（fail-closed）"}
    enabled = fishing_cfg.get("enabled")

    # enabled 必須是 Python boolean True（不接受字串 "true"）
    if enabled is not True:
        # 有旗標但 enabled 非 true → 按日期決定 off/legacy
        if batch_date is not None and batch_date < _FISHING_CUTOFF:
            return {"mode": "legacy", "batch_date": batch_date,
                    "detail": f"_batch_flags.yml 存在但 enabled 非 boolean true（{enabled!r}）+ 舊批 → legacy"}
        else:
            return {"mode": "off", "batch_date": batch_date,
                    "detail": f"_batch_flags.yml 存在但 enabled 非 boolean true（{enabled!r}）→ off"}

    # enabled is True，驗三項條件
    approved_by  = fishing_cfg.get("approved_by", "")
    approved_at  = fishing_cfg.get("approved_at", "")
    reason       = fishing_cfg.get("reason", "")

    errors = []
    if approved_by != "澤君":
        errors.append(f"approved_by={approved_by!r}（需為「澤君」）")
    # 解析 approved_at
    approved_date = None
    try:
        approved_date = _extract_batch_date({"batch_date": str(approved_at)}, "")
    except Exception:
        pass
    if approved_date is None:
        errors.append(f"approved_at={approved_at!r} 無法解析日期")
    elif approved_date < _FISHING_CUTOFF:
        errors.append(f"approved_at={approved_date} < cutoff {_FISHING_CUTOFF}")
    if not str(reason).strip():
        errors.append("reason 為空")

    if errors:
        return {"mode": "invalid", "batch_date": batch_date,
                "detail": f"opt-in 條件不完整 → invalid：{'; '.join(errors)}"}

    return {"mode": "opt_in", "batch_date": batch_date,
            "detail": f"opt-in 有效（approved_by=澤君, approved_at={approved_date}, reason={reason!r}）"}


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


# ── 派系名洩漏關鍵詞清單（C-016）——單一真理源來自 validate_deploy.FACTION_LEAK_WORDS ──
# P1-③：已於頂部 import，_FACTION_LEAK_WORDS 指向 validate_deploy 共用清單（或 fallback）
# 此處不再維護本地清單，修改派系清單請至 validate_deploy.py FACTION_LEAK_WORDS

# owner → HTML 檔名
# Phase 2 Step 4：從 projection 產（key 順序對齊原硬編：瑞祥/仲豪/昀臻/阿奇/叭噗_小C/溫蒂/詩婷）
_OWNER_HTML_MAP = LazyMap(lambda: {
    owner: rec["html_file"]
    for owner, rec in sorted(
        _OWNER_PROJ.items(),
        key=lambda x: ["瑞祥", "仲豪", "昀臻", "阿奇", "叭噗_小C", "溫蒂", "詩婷"].index(x[0])
        if x[0] in ["瑞祥", "仲豪", "昀臻", "阿奇", "叭噗_小C", "溫蒂", "詩婷"] else 99
    )
})

def chk_c016_no_faction_leak_in_html(owner: str, lib_dir: Path) -> tuple[str, str]:
    """C-016：HTML 可見輸出層不得出現派系名等製作字眼（v3 修寬 2026-06-01）
    掃描範圍：
      A. <span> 可見文字（豁免：hashtag / cta-arrow / thread-label / st 等操作指引 class）
      C. data-cat="..." 屬性值
      D. data-tags="..." 屬性值
      E. HTML comment <!-- ... -->
      F. yaml body **派系**：/ **類型**：meta 行（未爆彈守門）
    不掃：
      - yaml 內部欄位（faction/派系 欄位合法，不在 HTML 裡）
      - data-hashtags（對外貼文 hashtag，由業主自定）
      - CTA 操作指引（.cta 容器）/ hashtag-pool / scene / timeline 容器
      - 豁免 span class：hashtag / cta-arrow / thread-label / pie / st 等
    若 HTML 不存在則 WARN（build 尚未跑）。
    """
    # 豁免的 span class（不掃這些 class 的 span）
    _EXEMPT_SPAN_CLASSES = {
        'hashtag', 'cta-arrow', 'pie', 'thread-hash', 'batch',
        'thread-label', 'roman', 'label', 'count', 'num', 'en',
        'thread-id', 'ptag', 'tag', 'nm',
        'st',           # 叭噗時間軸時間戳 span
        'platform',     # 平台標籤
        'po-time',      # 上傳時間
        'rule',         # 分隔線
        'group-label',  # kenny 群組 header 標題（UI 分組，非對外展示）
        'group-en',     # kenny 群組英文副標
        'group-count',  # kenny 群組計數
        'group-toggle', # kenny 群組展開箭頭
        'gn',           # bappu 群組名稱 span
        'gc',           # bappu 群組代碼
        'gx',           # bappu 群組計數
        'gy',           # bappu 群組展開箭頭
    }

    html_rel = _OWNER_HTML_MAP.get(owner)
    if not html_rel:
        return "WARN", f"C-016 未知業主 '{owner}'，無法定位 HTML 檔，跳過"

    html_path = lib_dir / html_rel
    if not html_path.exists():
        return "WARN", f"C-016 HTML 檔不存在（{html_rel}），build 尚未跑，跳過"

    try:
        html = html_path.read_text(encoding="utf-8")
    except Exception as e:
        return "WARN", f"C-016 HTML 讀取失敗：{e}"

    # 先把操作指引容器移除（腳本庫內部操作員用，不掃）
    html_no_cta = re.sub(r'<div[^>]+class="cta"[^>]*>.*?</div>', '', html, flags=re.DOTALL)
    html_no_cta = re.sub(r'<div[^>]+class="hashtag-pool"[^>]*>.*?</div>', '', html_no_cta, flags=re.DOTALL)
    html_no_cta = re.sub(r'<div[^>]+class="scene"[^>]*>.*?</div>', '', html_no_cta, flags=re.DOTALL)
    html_no_cta = re.sub(r'<div[^>]+class="timeline"[^>]*>.*?</div>', '', html_no_cta, flags=re.DOTALL)

    hits = []
    scanned = 0

    # A. <span> 可見文字（豁免特定 class）
    for m in re.finditer(r'<span([^>]*)>([^<]+)</span>', html_no_cta, re.IGNORECASE):
        attrs_str = m.group(1)
        text = m.group(2)
        text_stripped = text.strip()
        if not text_stripped:
            continue
        cls_m = re.search(r'class="([^"]*)"', attrs_str)
        span_classes = set(cls_m.group(1).split()) if cls_m else set()
        if span_classes & _EXEMPT_SPAN_CLASSES:
            continue
        scanned += 1
        for word in _FACTION_LEAK_WORDS:
            if word in text_stripped:
                hits.append(f"span文字「{text_stripped[:40]}」含製作字眼「{word}」")
                break

    # B. thread-label — 豁免（脆文操作員分類標籤，非對外展示層）
    thread_labels = re.findall(r'<div[^>]*class="[^"]*thread-label[^"]*"[^>]*>([^<]*)</div>', html, re.IGNORECASE)
    scanned += len(thread_labels)
    # (不報 FAIL — 豁免)

    # C. data-cat 屬性值
    data_cat_vals = re.findall(r'data-cat="([^"]*)"', html, re.IGNORECASE)
    scanned += len(data_cat_vals)
    for val in data_cat_vals:
        val_stripped = val.strip()
        if not val_stripped:
            continue
        for word in _FACTION_LEAK_WORDS:
            if word in val_stripped:
                hits.append(f"data-cat=\"{val_stripped[:40]}\"含製作字眼「{word}」")
                break

    # D. data-tags 屬性值
    data_tags_vals = re.findall(r'data-tags="([^"]*)"', html, re.IGNORECASE)
    scanned += len(data_tags_vals)
    for val in data_tags_vals:
        val_stripped = val.strip()
        if not val_stripped:
            continue
        for word in _FACTION_LEAK_WORDS:
            if word in val_stripped:
                hits.append(f"data-tags=\"{val_stripped[:40]}\"含製作字眼「{word}」")
                break

    # E. HTML comment（<!-- ... -->），排除 CSS 樣式塊中的 comment
    comment_vals = re.findall(r'<!--(.*?)-->', html, re.DOTALL)
    scanned += len(comment_vals)
    for inner in comment_vals:
        inner_stripped = inner.strip()
        for word in _FACTION_LEAK_WORDS:
            if word in inner_stripped:
                hits.append(f"comment 含製作字眼「{word}」：「{inner_stripped[:40]}」")
                break

    # F. yaml body **派系**：/ **類型**：meta 行掃描（未爆彈守門）
    # Phase 2 Step 4：從 projection 產（key 順序對齊原硬編：瑞祥/仲豪/昀臻/阿奇/叭噗_小C/溫蒂/詩婷）
    # ⚠️ 保留 lib_dir.parent.parent 構造方式（非 L2_BASE），確保路徑逐字對齊原硬編
    yaml_owner_dirs = {
        owner: lib_dir.parent.parent / "L2_業主層" / rec["owner_dir"] / "01_腳本生產"
        for owner, rec in sorted(
            _OWNER_PROJ.items(),
            key=lambda x: ["瑞祥", "仲豪", "昀臻", "阿奇", "叭噗_小C", "溫蒂", "詩婷"].index(x[0])
            if x[0] in ["瑞祥", "仲豪", "昀臻", "阿奇", "叭噗_小C", "溫蒂", "詩婷"] else 99
        )
    }
    yaml_dir = yaml_owner_dirs.get(owner)
    if yaml_dir and yaml_dir.exists():
        yaml_body_hits = []
        for yf in yaml_dir.rglob("script_*.yaml"):
            try:
                ycontent = yf.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for lno, line in enumerate(ycontent.splitlines(), 1):
                if re.match(r'^\s*\*\*[派類][系型]\*\*：', line):
                    yaml_body_hits.append(f"{yf.name}:{lno} → {line.strip()[:50]}")
        if yaml_body_hits:
            for yh in yaml_body_hits[:5]:
                hits.append(f"yaml body 含 **派系/類型** meta 行：{yh}")
            if len(yaml_body_hits) > 5:
                hits.append(f"（yaml body 還有 {len(yaml_body_hits)-5} 處）")
        scanned += len(yaml_body_hits)

    if hits:
        return "FAIL", f"C-016 HTML 可見層含製作字眼（共 {len(hits)} 處）：" + "；".join(hits[:5]) + (f"（還有 {len(hits)-5} 處）" if len(hits) > 5 else "")
    return "PASS", f"C-016 HTML 可見層無派系名洩漏（掃描 {scanned} 項，{html_rel}）"


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


def _is_skeleton_mode(yamls: list[tuple]) -> bool:
    """判斷整批是否為「骨架未填階段」。

    邏輯：批次內任一 yaml 的 title 欄位值為 '[編劇填]' 字樣（即 yaml_skeleton_generator.py
    產出的骨架尚未被編劇填寫），視為骨架模式。
    骨架模式下 V2-025/026 跳過（編劇尚未填範本引用，不應 FAIL），
    但已填編劇的真實批次（title 不是 placeholder）照常驗，不放水。

    閾值：批次內 >= 50% yaml 的 title 為 placeholder → 骨架模式。
    （防止真實批次裡混入少量未填骨架時誤判為骨架模式）
    """
    if not yamls:
        return False
    placeholder_count = 0
    valid_count = 0
    for _, data in yamls:
        if not isinstance(data, dict):
            continue
        if "__parse_error__" in data or "__schema_error__" in data:
            continue
        valid_count += 1
        title = str(data.get("title", "") or "")
        # _is_placeholder 定義在下方，此處直接判斷常見的骨架 placeholder
        token = re.split(r'[\s#]', title.strip())[0].lower() if title.strip() else ""
        if token in ('[編劇填]', 'pending', 'todo', '待填') or not title.strip():
            placeholder_count += 1
    if valid_count == 0:
        return False
    return (placeholder_count / valid_count) >= 0.5


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
def run_per_file_checks(f: Path, data: dict, owner: str, is_skeleton: bool = False, fishing_policy: Optional[dict] = None) -> list[tuple[str, str, str, str]]:
    """回傳 [(check_id, status, desc, detail), ...]
    v2 升級：加 V2-001 ~ V2-005（yaml schema 新欄位驗）
    is_skeleton：由 _is_skeleton_mode(yamls) 傳入，骨架階段跳過 V2-025/026
    fishing_policy：由 load_fishing_policy() 算出後傳入，讓 C-013 知道模式
    """
    if fishing_policy is None:
        fishing_policy = {"mode": "off", "batch_date": None, "detail": "未傳入 policy，保守 off"}
    # P1-1：傳入「批次目錄名/檔名」讓 _extract_batch_date 能從目錄名（如第34批_試水批_2026-05-23）抓日期
    _fname_with_dir = f"{f.parent.name}/{f.name}"
    results = []
    checks = [
        # per-file checks
        ("L1-001", chk_l1_001_schema(data, f.name)),
        ("L1-002", chk_l1_002_banned(data, f.name)),
        ("L1-003", chk_l1_003_mirror(data, f.name)),
        ("L1-004", chk_l1_004_traffic(data, f.name)),
        ("L1-005", chk_l1_005_number_source(data, f.name)),
        ("L1-006", chk_l1_006_cta(data, f.name)),
        ("L1-007", chk_l1_007_title_len(data, f.name)),
        ("C-010",  chk_c010_翠文_non_empty(data, f.name)),
        ("C-013",  chk_c013_dm_card(data, f.name, owner, fishing_policy)),
        ("C-015",  chk_c015_hashtag_caption(data, f.name)),
        # v2 新增 5 件（V2-001 ~ V2-005）
        ("V2-001",  chk_v2_001_voice_lock(data, f.name, owner)),
        ("V2-001b", chk_v2_001b_banned_phrases(data, _fname_with_dir, owner)),
        ("V2-001c", chk_v2_001c_catchphrase_in_hook(data, _fname_with_dir, owner)),
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
    ]
    # v4 新增 2 件（2026-05-31 爆款範本引用系統）
    # BUG-6/7 修（2026-06-05）：骨架階段（編劇未填）跳過 V2-025/026，
    # 避免骨架的 template_source_ids:[] + template_adaptation placeholder 系統性 FAIL。
    # 已填編劇的真實批次（is_skeleton=False）照常驗，不放水。
    if is_skeleton:
        checks.append(("V2-025", ("SKIP", "骨架階段跳過（編劇尚未填範本引用，等填完後再驗）")))
        checks.append(("V2-026", ("SKIP", "骨架階段跳過（編劇尚未填 template_adaptation，等填完後再驗）")))
    else:
        # P1-1：V2-025 改傳 _fname_with_dir 讓日期解析能吃批次目錄名
        checks.append(("V2-025", chk_v2_025_template_source_required(data, _fname_with_dir)))
        checks.append(("V2-026", chk_v2_026_template_adaptation_required(data, _fname_with_dir)))
    for cid, (status, detail) in checks:
        results.append((cid, status, f.name, detail))
    return results

# ────────────────────────────────────────────
# 主程式
# ────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="腳本批次品管員（含 V2 schema + voice_lock 守門）")
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
    print(f"  腳本批次品管員 v2.1（含 V2 schema + voice_lock 守門）")
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

    # ── 釣魚部 policy（雙模式）──
    fishing_policy = load_fishing_policy(batch_dir, valid_yamls)
    print(f"[INFO] 釣魚部模式：{fishing_policy['mode']}（{fishing_policy['detail']}）\n")

    all_results: list[tuple[str, str, str, str]] = []

    # ── Batch-level checks（L1-008 / L1-009 / C-011 / C-012 / C-014 + C-013B + v3 新 6 件）──
    batch_checks = [
        ("L1-008", chk_l1_008_batch_count(yamls, batch_dir)),
        ("L1-009", chk_l1_009_派系_coverage(valid_yamls)),
        ("C-011",  chk_c011_派系_ratio(valid_yamls, owner, pref_text)),
        ("C-012",  chk_c012_identity_ratio(valid_yamls, owner, pref_text)),
        ("C-014",  chk_c014_card_style(valid_yamls, batch_dir, owner, batch_tag)),
        # C-013B batch-level 釣魚掃描（off/invalid 時 fail-closed）
        ("C-013B", chk_c013b_no_fishing_when_off(valid_yamls, fishing_policy)),
        # v3 新增 6 件 batch checks（2026-05-23 三審修補）
        ("V2-006", chk_v2_006_required_slot(valid_yamls, fishing_policy)),
        ("V2-007", chk_v2_007_threads_seven(batch_dir)),
        ("V2-008", chk_v2_008_used_titles_dedup(valid_yamls, owner)),
        ("V2-009", chk_v2_009_auditor_report(batch_dir, owner)),
        ("V2-010", chk_v2_010_batch_summary(batch_dir)),
        ("V2-013", chk_v2_013_zhonghao_life_ratio(valid_yamls, owner)),
        # P3 比例驗證器（2026-06-08）
        ("C-cta-mix",     chk_c_cta_mix(valid_yamls, owner, pref_text, batch_tag)),
        ("C-content-mix", chk_c_content_mix(valid_yamls, owner, pref_text, batch_tag)),
    ]
    print(f"── 批次級 check（{len(batch_checks)} 件）──")
    for cid, (status, detail) in batch_checks:
        icon = "✅" if status == "PASS" else ("⚠️ " if status == "WARN" else "❌")
        print(f"  {icon} [{cid}] {status}: {detail}")
        all_results.append((cid, status, "batch", detail))
    print()

    # ── Per-file checks（件數動態，避免數字過時）──
    # BUG-6/7 修（2026-06-05）：偵測骨架模式，骨架階段跳過 V2-025/026
    _skeleton_mode = _is_skeleton_mode(valid_yamls)
    if _skeleton_mode:
        print("[INFO] 偵測到骨架模式（批次 >= 50% yaml 的 title 為 placeholder）— V2-025/026 本批跳過")
    _per_file_results_count: int = 0  # 第一支跑完後更新
    print("── 逐篇 check（per-file × 每篇）──")
    for f, data in valid_yamls:
        title = data.get("title", f.name)
        print(f"\n  [{f.name}] {title}")
        per_results = run_per_file_checks(f, data, owner, is_skeleton=_skeleton_mode, fishing_policy=fishing_policy)
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
            'legacy_allowed_until': '2026-12-31',  # 過渡期（2026-06-05 bump：原 6/1 已過期＝時間到期非第一刀問題，bump 讓 V2 legacy 測試回 WARN、--fixtures 全綠不遮蔽未來真迴歸）
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

        # ── 第一刀 chk_c011 三態整合 fixtures（算盤 MODIFY 補，2026-06-05）──
        # 鎖住 PASS/FAIL/WARN[WAIVED] 三態回歸 + 防「僅驗 canonical」謊報訊息復活。
        print("\n[F-C011a] chk_c011 仲豪型（含非 L0 標準派系名）→ WARN[WAIVED:UNKNOWN_ALIAS] 且不謊報")
        _c011_zh_pref = (
            "## 第 5 章：派系偏好\n\n### 5.2 主推比例\n\n"
            "| 派別 | 佔比 |\n|------|------|\n"
            "| **直球派** | 36% |\n| **揭秘型** | 27% |\n| **共鳴/痛點型** | 36% |\n"
        )
        _c011_zh_yamls = [(Path('zh1.yaml'), {'派系': '直球派'}), (Path('zh2.yaml'), {'派系': '揭秘型'})]
        _rc = chk_c011_派系_ratio(_c011_zh_yamls, '仲豪', _c011_zh_pref)
        fcheck('F-C011a 仲豪 → WARN', _rc[0] == 'WARN', _rc[1])
        fcheck('F-C011a detail 含 [WAIVED:UNKNOWN_ALIAS]', '[WAIVED:UNKNOWN_ALIAS]' in _rc[1], _rc[1])
        fcheck('F-C011a 不謊報（誠實標「暫不驗」、無「僅驗 canonical 部分」假訊息）',
               '暫不驗' in _rc[1] and '僅驗 canonical 部分' not in _rc[1], _rc[1])

        print("\n[F-C011b] chk_c011 詩婷型（建議傾向/尚無批次）→ WARN[WAIVED:PROVISIONAL]")
        _c011_st_pref = (
            "## 第 5 章：派系偏好\n\n"
            "> ⚠️ 詩婷尚無腳本批次，以下為「初步建議傾向」，禁腦補寫死比例。\n\n"
            "### 5.1 初步建議主推傾向\n\n"
            "| 派別 | 建議傾向 |\n|------|------|\n| **共鳴/痛點型** | 主力傾向 |\n"
        )
        _c011_st_yamls = [(Path('st1.yaml'), {'派系': '人間觀察派'})]
        _rc = chk_c011_派系_ratio(_c011_st_yamls, '詩婷', _c011_st_pref)
        fcheck('F-C011b 詩婷 → WARN', _rc[0] == 'WARN', _rc[1])
        fcheck('F-C011b detail 含 [WAIVED:PROVISIONAL]', '[WAIVED:PROVISIONAL]' in _rc[1], _rc[1])

        print("\n[F-C011c] chk_c011 瑞祥型（偏好50/30/20、批次全嗆辣派）→ FAIL（真驗證有跑、反證放水）")
        _c011_rx_pref = (
            "## 第 5 章：派系偏好\n\n### 5.2 主推派系\n\n"
            "| 派別 | 占比 |\n|------|------|\n"
            "| **嗆辣派** | 50% |\n| **人間觀察派** | 30% |\n| **市場觀察派** | 20% |\n"
        )
        _c011_rx_yamls = [(Path(f'rx{i}.yaml'), {'派系': '嗆辣派'}) for i in range(10)]
        _rc = chk_c011_派系_ratio(_c011_rx_yamls, '瑞祥', _c011_rx_pref)
        fcheck('F-C011c 瑞祥比例偏 → FAIL（證明真驗證有跑、非放水）', _rc[0] == 'FAIL', _rc[1])

        print("\n[F-C011d] chk_c011 有派系章節但無%、非 provisional → FAIL（反放水 backstop）")
        _c011_np_pref = (
            "## 第 5 章：派系偏好\n\n### 5.2 主推派系\n\n"
            "主推嗆辣派和人間觀察派，市場觀察派輔助。\n"
        )
        _c011_np_yamls = [(Path('np1.yaml'), {'派系': '嗆辣派'})]
        _rc = chk_c011_派系_ratio(_c011_np_yamls, '測試', _c011_np_pref)
        fcheck('F-C011d 無%非provisional → FAIL（反放水）', _rc[0] == 'FAIL', _rc[1])

        # ── 第二刀 chk_c012 雙身份三態整合 fixtures（算盤 MODIFY 補，2026-06-05）──
        # 鎖 gate(kb-owner industries)/LABEL_MISMATCH WAIVED/命名一致才驗/無欄 FAIL/單行業 skip 回歸
        _c012_dual_pref = (
            "```kb-owner\nowner_id: AQI\nowner_name: 阿奇\nindustries: [餐飲, 房仲]\n```\n\n"
            "## 第 3 章：雙身份比例（霸告建議—待澤君拍板）\n\n"
            "| 內容類型 | 建議比例 | 理由 |\n|---|---|---|\n"
            "| 生活 / 觀點 / 個人故事 | 50% | 主力 |\n"
            "| 餐飲（胖奇熱狗堡）| 30% | 主軸 |\n"
            "| 房仲 | 15% | 副業 |\n"
            "| 開箱 | 5% | 少量 |\n"
        )
        print("\n[F-C012a] chk_c012 雙行業命名不一致（標籤≠類型名）→ WARN[WAIVED:LABEL_MISMATCH]")
        _ya = [(Path(f'a{i}.yaml'), {'雙身份分類': '觀點分享（真人）'}) for i in range(7)] + \
              [(Path(f'b{i}.yaml'), {'雙身份分類': '胖奇熱狗堡（主軸）'}) for i in range(3)]
        _rc = chk_c012_identity_ratio(_ya, '阿奇', _c012_dual_pref)
        fcheck('F-C012a 命名不一致 → WARN', _rc[0] == 'WARN', _rc[1])
        fcheck('F-C012a detail 含 [WAIVED:LABEL_MISMATCH]', '[WAIVED:LABEL_MISMATCH]' in _rc[1], _rc[1])

        print("\n[F-C012b] chk_c012 雙行業命名一致+比例對齊 → PASS（證明命名一致時真驗）")
        _yb = [(Path(f'g{i}.yaml'), {'雙身份分類': '生活 / 觀點 / 個人故事'}) for i in range(10)] + \
              [(Path(f'r{i}.yaml'), {'雙身份分類': '餐飲（胖奇熱狗堡）'}) for i in range(6)] + \
              [(Path(f'h{i}.yaml'), {'雙身份分類': '房仲'}) for i in range(3)] + \
              [(Path('k0.yaml'), {'雙身份分類': '開箱'})]
        _rc = chk_c012_identity_ratio(_yb, '阿奇', _c012_dual_pref)
        fcheck('F-C012b 命名一致比例對 → PASS', _rc[0] == 'PASS', _rc[1])

        print("\n[F-C012c] chk_c012 雙行業命名一致+比例偏 → FAIL（證明真驗有跑、非放水）")
        _yc = [(Path(f'g{i}.yaml'), {'雙身份分類': '生活 / 觀點 / 個人故事'}) for i in range(10)]
        _rc = chk_c012_identity_ratio(_yc, '阿奇', _c012_dual_pref)
        fcheck('F-C012c 比例偏 → FAIL', _rc[0] == 'FAIL', _rc[1])

        print("\n[F-C012d] chk_c012 雙行業無「雙身份分類」欄 → FAIL（reqired backstop）")
        _yd = [(Path(f'x{i}.yaml'), {'title': 'no identity'}) for i in range(5)]
        _rc = chk_c012_identity_ratio(_yd, '阿奇', _c012_dual_pref)
        fcheck('F-C012d 無雙身份分類欄 → FAIL', _rc[0] == 'FAIL', _rc[1])

        print("\n[F-C012e] chk_c012 單行業 → PASS-不適用（不 WARN-spam）")
        _c012_single_pref = "```kb-owner\nowner_id: RUIXIANG\nowner_name: 瑞祥\nindustry_id: 房仲\n```\n\n## 第 3 章：人物設定\n"
        _rc = chk_c012_identity_ratio([(Path('s1.yaml'), {'雙身份分類': '房仲'})], '瑞祥', _c012_single_pref)
        fcheck('F-C012e 單行業 → PASS-不適用', _rc[0] == 'PASS' and '不適用' in _rc[1], _rc[1])

        print("\n[F-C012f] chk_c012 kb-owner 無法解析 → fail-loud WARN（不靜默當單行業）")
        _rc = chk_c012_identity_ratio([(Path('n1.yaml'), {'雙身份分類': '房仲'})], '未知', "## 第 3 章：人物設定\n沒有 kb-owner block\n")
        fcheck('F-C012f kb-owner 不可解析 → WARN', _rc[0] == 'WARN', _rc[1])

        print("\n[F-C012g] chk_c012 命名不一致 + 偏好比例已定案(非provisional) → FAIL（堵 Codex#2 放水全標錯）")
        _c012_g_pref = (
            "```kb-owner\nowner_id: XX\nowner_name: 測試\nindustries: [餐飲, 房仲]\n```\n\n"
            "## 第 3 章：雙身份比例\n\n"  # 無 provisional 標記（比例已定案）
            "| 內容類型 | 建議比例 | 理由 |\n|---|---|---|\n"
            "| 餐飲 | 60% | x |\n| 房仲 | 40% | y |\n"
        )
        _yg = [(Path(f'gg{i}.yaml'), {'雙身份分類': '亂標A'}) for i in range(6)] + \
              [(Path(f'hh{i}.yaml'), {'雙身份分類': '亂標B'}) for i in range(4)]
        _rc = chk_c012_identity_ratio(_yg, '測試', _c012_g_pref)
        fcheck('F-C012g 非provisional命名不一致 → FAIL', _rc[0] == 'FAIL', _rc[1])

        # ── F-FISH 系列：釣魚部雙模式 fixtures（5 組）──
        import tempfile as _tmpmod, os as _osmod

        def _make_fake_batch(yamls_data: list, flag_content: Optional[str] = None, dir_suffix: str = "") -> "Path":
            """建立暫存批次目錄，內含 yaml 檔（含日期的目錄名），可選加 _batch_flags.yml。"""
            tmp_dir = _tmpmod.mkdtemp(prefix=f"test_batch_{dir_suffix}_")
            tmp_path = Path(tmp_dir)
            for i, data in enumerate(yamls_data):
                import yaml as _yaml_inner
                (tmp_path / f"script_test_{i+1:02d}.yaml").write_text(
                    _yaml_inner.dump(data, allow_unicode=True), encoding="utf-8"
                )
            if flag_content is not None:
                (tmp_path / "_batch_flags.yml").write_text(flag_content, encoding="utf-8")
            return tmp_path

        # ── F-FISH1：off 模式（2026-06-07 無旗標）→ 無釣魚信號 → PASS ──
        print("\n[F-FISH1] off 模式（新批無旗標）+ 無釣魚信號 → C-013B PASS + V2-006 3強制位 PASS")
        _fish1_yamls = [
            {"title": "一般腳本_毒舌", "required_slot": "毒舌正能量"},
            {"title": "一般腳本_雞湯", "required_slot": "純雞湯"},
            {"title": "一般腳本_Erika", "required_slot": "Erika 拆解派"},
        ]
        _fish1_dir = _make_fake_batch(_fish1_yamls, flag_content=None, dir_suffix="fish1_2026-06-07")
        # rename 讓目錄名含日期（off 模式）
        _fish1_dir_dated = _fish1_dir.parent / f"第01批_2026-06-07"
        _fish1_dir.rename(_fish1_dir_dated)
        _fish1_dir = _fish1_dir_dated
        try:
            _f1_policy = load_fishing_policy(_fish1_dir, [(p, __import__('yaml').safe_load(p.read_text(encoding='utf-8'))) for p in sorted(_fish1_dir.glob("*.yaml"))])
            fcheck("F-FISH1 mode=off", _f1_policy["mode"] == "off", _f1_policy["detail"])
            # C-013B
            _f1_ydata = [(p, __import__('yaml').safe_load(p.read_text(encoding='utf-8'))) for p in sorted(_fish1_dir.glob("*.yaml"))]
            _r = chk_c013b_no_fishing_when_off(_f1_ydata, _f1_policy)
            fcheck("F-FISH1 C-013B PASS（無釣魚信號）", _r[0] == "PASS", _r[1])
            # V2-006 3 強制位
            _r2 = chk_v2_006_required_slot(_f1_ydata, _f1_policy)
            fcheck("F-FISH1 V2-006 3強制位 PASS", _r2[0] == "PASS", _r2[1])
        finally:
            import shutil as _shutil
            _shutil.rmtree(_fish1_dir, ignore_errors=True)

        # ── F-FISH2：off 模式（2026-06-07）+ 偷塞釣魚腳本 → C-013B FAIL + C-013 per-file FAIL ──
        print("\n[F-FISH2] off 模式（新批）+ 偷塞釣魚腳本 → C-013B FAIL + C-013 per-file FAIL（驗 C-013 真吃到 policy）")
        _fish2_yamls = [
            {"title": "一般腳本_毒舌", "required_slot": "毒舌正能量"},
            {"title": "一般腳本_雞湯", "required_slot": "純雞湯"},
            {"title": "一般腳本_Erika", "required_slot": "Erika 拆解派"},
            # 偷塞釣魚腳本（應 FAIL）
            {"title": "釣魚部測試", "required_slot": "釣魚部", "is_fishing": True,
             "dm_card": {"行業專業": "x", "在地優勢": "x", "痛點": "x", "解法": "x", "行動呼籲": "x", "LINE QR": "x"}},
        ]
        _fish2_dir = _make_fake_batch(_fish2_yamls, flag_content=None, dir_suffix="fish2")
        _fish2_dir_dated = _fish2_dir.parent / f"第02批_2026-06-07"
        _fish2_dir.rename(_fish2_dir_dated)
        _fish2_dir = _fish2_dir_dated
        try:
            import yaml as _yaml_fish2
            _f2_ydata = [(p, _yaml_fish2.safe_load(p.read_text(encoding='utf-8'))) for p in sorted(_fish2_dir.glob("*.yaml"))]
            _f2_policy = load_fishing_policy(_fish2_dir, _f2_ydata)
            fcheck("F-FISH2 mode=off", _f2_policy["mode"] == "off", _f2_policy["detail"])
            # C-013B batch-level 應 FAIL
            _r = chk_c013b_no_fishing_when_off(_f2_ydata, _f2_policy)
            fcheck("F-FISH2 C-013B FAIL（off 偷塞釣魚）", _r[0] == "FAIL", _r[1])
            # C-013 per-file 應 FAIL（驗三層真串通）
            _fishing_yaml_data = _fish2_yamls[3]  # 第 4 支釣魚腳本 data
            _r3 = chk_c013_dm_card(_fishing_yaml_data, "script_test_04.yaml", "瑞祥", _f2_policy)
            fcheck("F-FISH2 C-013 per-file FAIL（off + 釣魚信號，non-legacy 放水洞封堵）",
                   _r3[0] == "FAIL", _r3[1])
        finally:
            _shutil.rmtree(_fish2_dir, ignore_errors=True)

        # ── F-FISH3：opt_in 模式 + 1 釣魚腳本含完整 dm_card → PASS ──
        print("\n[F-FISH3] opt_in 模式 + 1 釣魚腳本含完整 dm_card → C-013 PASS + C-013B PASS + V2-006 4強制位 PASS")
        _flag3 = "fishing_dm_card:\n  enabled: true\n  approved_by: 澤君\n  approved_at: '2026-06-06'\n  reason: '特別測試 F-FISH3'\n"
        _fish3_yamls = [
            {"title": "毒舌腳本", "required_slot": "毒舌正能量"},
            {"title": "雞湯腳本", "required_slot": "純雞湯"},
            {"title": "Erika腳本", "required_slot": "Erika 拆解派"},
            {"title": "釣魚部測試", "required_slot": "釣魚部", "is_fishing": True,
             "dm_card": {"行業專業": "x", "在地優勢": "x", "痛點": "x", "解法": "x", "行動呼籲": "x", "LINE QR": "x",
                         "asset_path": "assets/dm_cards/test.png"}},
        ]
        _fish3_dir = _make_fake_batch(_fish3_yamls, flag_content=_flag3, dir_suffix="fish3")
        _fish3_dir_dated = _fish3_dir.parent / f"第03批_2026-06-06"
        _fish3_dir.rename(_fish3_dir_dated)
        _fish3_dir = _fish3_dir_dated
        try:
            import yaml as _yaml_fish3
            _f3_ydata = [(p, _yaml_fish3.safe_load(p.read_text(encoding='utf-8'))) for p in sorted(_fish3_dir.glob("*.yaml"))]
            _f3_policy = load_fishing_policy(_fish3_dir, _f3_ydata)
            fcheck("F-FISH3 mode=opt_in", _f3_policy["mode"] == "opt_in", _f3_policy["detail"])
            # C-013B opt_in → PASS skip
            _r = chk_c013b_no_fishing_when_off(_f3_ydata, _f3_policy)
            fcheck("F-FISH3 C-013B PASS（opt_in skip）", _r[0] == "PASS", _r[1])
            # V2-006 4 強制位
            _r2 = chk_v2_006_required_slot(_f3_ydata, _f3_policy)
            fcheck("F-FISH3 V2-006 4強制位 PASS", _r2[0] == "PASS", _r2[1])
            # C-013 per-file 釣魚腳本 PASS
            _r3 = chk_c013_dm_card(_fish3_yamls[3], "script_test_04.yaml", "瑞祥", _f3_policy)
            fcheck("F-FISH3 C-013 PASS（opt_in + dm_card 完整）", _r3[0] == "PASS", _r3[1])
        finally:
            _shutil.rmtree(_fish3_dir, ignore_errors=True)

        # ── F-FISH4：opt_in 模式 + 釣魚腳本缺 dm_card → FAIL ──
        print("\n[F-FISH4] opt_in 模式 + 釣魚腳本缺 dm_card → C-013 FAIL")
        _fish4_yaml_data = {
            "title": "釣魚部", "required_slot": "釣魚部", "is_fishing": True,
            # 故意不給 dm_card（缺 dm_card 欄位）
        }
        _f4_policy = {"mode": "opt_in", "batch_date": _dt.date(2026, 6, 6),
                      "detail": "opt_in 測試 F-FISH4"}
        _r = chk_c013_dm_card(_fish4_yaml_data, "f4.yaml", "瑞祥", _f4_policy)
        fcheck("F-FISH4 C-013 FAIL（opt_in 缺 dm_card dict）", _r[0] == "FAIL", _r[1])

        # ── F-FISH5：legacy 模式（2026-06-05 無旗標）+ 釣魚腳本含完整 dm_card → PASS（舊批豁免）──
        print("\n[F-FISH5] legacy 模式（2026-06-05 無旗標舊批）+ 釣魚腳本有完整 dm_card → C-013 PASS（dm_card 缺仍 FAIL）")
        # 測試 legacy PASS 路徑
        _fish5_yaml_ok = {
            "title": "釣魚部", "required_slot": "釣魚部", "is_fishing": True,
            "dm_card": {"行業專業": "x", "在地優勢": "x", "痛點": "x", "解法": "x", "行動呼籲": "x", "LINE QR": "x"},
        }
        _f5_policy = {"mode": "legacy", "batch_date": _dt.date(2026, 6, 5),
                      "detail": "無旗標 + 批次日期 2026-06-05 < 2026-06-06 → legacy"}
        _r = chk_c013_dm_card(_fish5_yaml_ok, "f5_ok.yaml", "瑞祥", _f5_policy)
        fcheck("F-FISH5a C-013 PASS（legacy + dm_card 完整）", _r[0] == "PASS", _r[1])
        # 驗 legacy dm_card 缺仍 FAIL（不趁 cutover 放水）
        _fish5_yaml_bad = {
            "title": "釣魚部", "required_slot": "釣魚部", "is_fishing": True,
            # 故意不給 dm_card
        }
        _r2 = chk_c013_dm_card(_fish5_yaml_bad, "f5_bad.yaml", "瑞祥", _f5_policy)
        fcheck("F-FISH5b C-013 FAIL（legacy + 缺 dm_card，不趁 cutover 放水）", _r2[0] == "FAIL", _r2[1])

        # ── F-FISH6（霸告 2026-06-05 修零回歸後鎖回歸）：legacy + 只有 required_slot/is_fishing
        #    （無 title釣魚部、無 dm_card dict）→ C-013 PASS skip。舊碼漏偵測這型（詩婷01/昀臻12 實際案例），
        #    legacy 必逐字保舊行為不誤判 FAIL；同一支在 off 新批必 FAIL（fail-closed 未放鬆）──
        print("\n[F-FISH6] legacy 只 required_slot/is_fishing（無 title釣魚部/dm_card）→ legacy PASS skip / off FAIL")
        _fish6_yaml = {
            "title": "首購族最常問我的三件事",  # 不含「釣魚部」
            "required_slot": "釣魚部", "is_fishing": True,
            # 無 dm_card dict、無 釣魚部標記
        }
        _f6_legacy = {"mode": "legacy", "batch_date": _dt.date(2026, 6, 1), "detail": "legacy 測試 F-FISH6"}
        _r6a = chk_c013_dm_card(_fish6_yaml, "f6.yaml", "詩婷", _f6_legacy)
        fcheck("F-FISH6a legacy 只 required_slot/is_fishing → C-013 PASS skip（零回歸鎖）", _r6a[0] == "PASS", _r6a[1])
        _f6_off = {"mode": "off", "batch_date": _dt.date(2026, 6, 10), "detail": "off 測試 F-FISH6"}
        _r6b = chk_c013_dm_card(_fish6_yaml, "f6.yaml", "詩婷", _f6_off)
        fcheck("F-FISH6b 同支在 off 新批 → C-013 FAIL（fail-closed 未放鬆）", _r6b[0] == "FAIL", _r6b[1])

        # ── F-FISH7（保鏢硬條件2 / Codex must-fix）：opt_in + dm_card 6 件齊但「缺圖片資產路徑」→ FAIL
        #    封「validator 6 件驗過、但網站圖卡空白」漏洞。有 asset_path → PASS ──
        print("\n[F-FISH7] opt_in + dm_card 6 件齊但缺 asset_path → C-013 FAIL（圖卡交付鏈）")
        _f7_policy = {"mode": "opt_in", "batch_date": _dt.date(2026, 6, 6), "detail": "opt_in 測試 F-FISH7"}
        _fish7_no_asset = {
            "title": "釣魚部測試", "required_slot": "釣魚部", "is_fishing": True,
            "dm_card": {"行業專業": "x", "在地優勢": "x", "痛點": "x", "解法": "x", "行動呼籲": "x", "LINE QR": "x"},
            # 故意不給 asset_path / img
        }
        _r7a = chk_c013_dm_card(_fish7_no_asset, "f7.yaml", "瑞祥", _f7_policy)
        fcheck("F-FISH7a opt_in 6件齊但無 asset_path → C-013 FAIL", _r7a[0] == "FAIL", _r7a[1])
        _fish7_with_asset = dict(_fish7_no_asset)
        _fish7_with_asset["dm_card"] = dict(_fish7_no_asset["dm_card"], asset_path="assets/dm_cards/x.png")
        _r7b = chk_c013_dm_card(_fish7_with_asset, "f7b.yaml", "瑞祥", _f7_policy)
        fcheck("F-FISH7b opt_in 6件齊 + asset_path → C-013 PASS", _r7b[0] == "PASS", _r7b[1])

        # ── F-FISH8a：_batch_flags.yml top-level 是 list → load_fishing_policy mode==invalid ──
        print("\n[F-FISH8a] _batch_flags.yml top-level 是 list（非 mapping）→ load_fishing_policy mode==invalid")
        _fish8a_dir = _make_fake_batch(
            [{"title": "一般腳本", "required_slot": "毒舌正能量"}],
            flag_content="- bad\n",
            dir_suffix="fish8a",
        )
        _fish8a_dir_dated = _fish8a_dir.parent / f"第08批_2026-06-08a"
        _fish8a_dir.rename(_fish8a_dir_dated)
        _fish8a_dir = _fish8a_dir_dated
        try:
            import yaml as _yaml_fish8a
            _f8a_ydata = [(p, _yaml_fish8a.safe_load(p.read_text(encoding='utf-8'))) for p in sorted(_fish8a_dir.glob("*.yaml"))]
            _f8a_policy = load_fishing_policy(_fish8a_dir, _f8a_ydata)
            fcheck("F-FISH8a top-level list → mode==invalid", _f8a_policy["mode"] == "invalid", _f8a_policy["detail"])
        finally:
            _shutil.rmtree(_fish8a_dir, ignore_errors=True)

        # ── F-FISH8b：fishing_dm_card: true（非 dict）→ mode==invalid ──
        print("\n[F-FISH8b] fishing_dm_card: true（非 dict）→ load_fishing_policy mode==invalid")
        _fish8b_dir = _make_fake_batch(
            [{"title": "一般腳本", "required_slot": "毒舌正能量"}],
            flag_content="fishing_dm_card: true\n",
            dir_suffix="fish8b",
        )
        _fish8b_dir_dated = _fish8b_dir.parent / f"第08批_2026-06-08b"
        _fish8b_dir.rename(_fish8b_dir_dated)
        _fish8b_dir = _fish8b_dir_dated
        try:
            import yaml as _yaml_fish8b
            _f8b_ydata = [(p, _yaml_fish8b.safe_load(p.read_text(encoding='utf-8'))) for p in sorted(_fish8b_dir.glob("*.yaml"))]
            _f8b_policy = load_fishing_policy(_fish8b_dir, _f8b_ydata)
            fcheck("F-FISH8b fishing_dm_card: true（非 dict）→ mode==invalid", _f8b_policy["mode"] == "invalid", _f8b_policy["detail"])
        finally:
            _shutil.rmtree(_fish8b_dir, ignore_errors=True)

        # ── F-FISH9：opt_in + 正式釣魚腳本 + dm_card-only 第二支 → V2-006 FAIL（union 釣魚信號 2 支）──
        #    另加 type:釣魚型 反例確保 union 含 type 信號
        print("\n[F-FISH9] opt_in + 正式釣魚(required_slot+is_fishing+dm_card) + dm_card-only 第二支 → V2-006 FAIL（union 2支）")
        _f9_flag = "fishing_dm_card:\n  enabled: true\n  approved_by: 澤君\n  approved_at: '2026-06-08'\n  reason: '測試 F-FISH9'\n"
        _fish9_yamls = [
            {"title": "毒舌腳本", "required_slot": "毒舌正能量"},
            {"title": "雞湯腳本", "required_slot": "純雞湯"},
            {"title": "Erika腳本", "required_slot": "Erika 拆解派"},
            # 正式釣魚支（slot + is_fishing + dm_card 全齊）
            {"title": "釣魚部正式", "required_slot": "釣魚部", "is_fishing": True,
             "dm_card": {"行業專業": "x", "在地優勢": "x", "痛點": "x", "解法": "x", "行動呼籲": "x", "LINE QR": "x",
                         "asset_path": "assets/dm_cards/real.png"}},
            # dm_card-only 第二支（無 required_slot/is_fishing，但 dm_card dict 存在 → _fishing_signals 偵測到）
            {"title": "普通腳本但夾帶dm_card",
             "dm_card": {"行業專業": "x", "在地優勢": "x", "痛點": "x", "解法": "x", "行動呼籲": "x", "LINE QR": "x",
                         "asset_path": "assets/dm_cards/extra.png"}},
            # type:釣魚型 反例（union 應含 type 信號）
            {"title": "釣魚型測試", "type": "釣魚型"},
        ]
        _fish9_dir = _make_fake_batch(_fish9_yamls, flag_content=_f9_flag, dir_suffix="fish9")
        _fish9_dir_dated = _fish9_dir.parent / f"第09批_2026-06-09"
        _fish9_dir.rename(_fish9_dir_dated)
        _fish9_dir = _fish9_dir_dated
        try:
            import yaml as _yaml_fish9
            _f9_ydata = [(p, _yaml_fish9.safe_load(p.read_text(encoding='utf-8'))) for p in sorted(_fish9_dir.glob("*.yaml"))]
            _f9_policy = load_fishing_policy(_fish9_dir, _f9_ydata)
            fcheck("F-FISH9 mode=opt_in", _f9_policy["mode"] == "opt_in", _f9_policy["detail"])
            _r9 = chk_v2_006_required_slot(_f9_ydata, _f9_policy)
            fcheck("F-FISH9 V2-006 FAIL（union 釣魚信號 > 1 支）", _r9[0] == "FAIL", _r9[1])
        finally:
            _shutil.rmtree(_fish9_dir, ignore_errors=True)

        # ── F-FISH10：opt_in 單檔，dm_card 只有 asset_path，但 caption 含六字關鍵字
        #    → chk_c013_dm_card FAIL（opt_in 只掃 dm_card dict，不再靠掃全包放水）──
        print("\n[F-FISH10] opt_in 只掃 dm_card dict — caption 含六字關鍵字仍 FAIL（反放水）")
        _f10_policy = {"mode": "opt_in", "batch_date": _dt.date(2026, 6, 8), "detail": "opt_in 測試 F-FISH10"}
        _fish10_yaml = {
            "title": "釣魚部測試", "required_slot": "釣魚部", "is_fishing": True,
            # dm_card 只有 asset_path，缺 6 件內容欄位
            "dm_card": {"asset_path": "assets/dm_cards/test.png"},
            # caption 包含 6 件關鍵字（舊碼掃全包會放水，新碼 opt_in 只掃 dm_card dict 應 FAIL）
            "caption": "行業專業 在地優勢 痛點 解法 行動呼籲 LINE QR",
        }
        _r10 = chk_c013_dm_card(_fish10_yaml, "f10.yaml", "瑞祥", _f10_policy)
        fcheck("F-FISH10 opt_in 只掃 dm_card → caption 放水封堵（FAIL）", _r10[0] == "FAIL", _r10[1])

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
