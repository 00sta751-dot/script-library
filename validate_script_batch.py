#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_script_batch.py — 腳本批次品管員（v2 — 階段 3 升級 / 含 V2 schema 守門；現役 2026-06-23 enforce-flip：5 旗標 True、§21/§22 機械化、off-pro enforce、202 fixtures）
對齊 SOP _腳本生產SOP_v3.0.yaml（§11 圖卡批次段 2026-07-14 退役 tombstone）+ §15 + guardian 補件 C-010 ~ C-015（C-014 已退役、ID 保留）+ R-CARD-001（2026-07-14 起擋新批圖卡欄）
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
import json
import hashlib
import yaml
from pathlib import Path
from typing import Any, Optional

from derive_quotes import QuoteDerivationError, derive_quote_view, dialogue_sha256
from taste_panel_relative import (
    STATUS_HUMAN,
    STATUS_PASS,
    STATUS_REJECT,
    compute_deploy_decision,
    is_offpro_report,
    is_relative_enabled,
)

# L0 §1.1.8：Q1-Q8 是批次主題配額；不得與 schema_check 的標題型 T1-T6
# 或已退役的 content_axis 9/2/2 混用。
TOPIC_TYPE_VALUES = ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8")
TOPIC_TYPE_TARGET_COUNTS = {
    "Q1": 2, "Q2": 2, "Q3": 2, "Q4": 2,
    "Q5": 2, "Q6": 2, "Q7": 1, "Q8": 1,
}
ORIGIN_SOURCE_VALUES = {
    "source_1_comment", "source_2_reference", "source_3_owner",
    "source_4_created", "aux",
}

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
        load_l0_batch_spec_sources as _load_l0_batch_spec_sources,
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

    # fallback 函式（回硬編值，守門不失效）
    # ⚠ 本字典必須與現役 `L0_跨行業公版/_腳本生產SOP_v3.0.yaml` 的 batch_spec 逐鍵同步（保鏢 r4）。
    #    SOP 改值而此處沒跟 → 只有 _sop_config import 失敗時才會暴露（沉默坑）。改 SOP 請一併改這裡。
    #    例外兩鍵（刻意與 SOP yaml 字面不同，非漏同步）：
    #      - fishing_script：SOP yaml 已無此鍵（釣魚部下架 2026-06-05），0 = 主路徑 _sop_config 缺鍵時的同值 fallback。
    #      - cta_distribution：SOP yaml 值為 {owner_defined/source/chicken_soup_min}，但該處自註
    #        「現役消費者(topic_distributor/validate/_sop_config) 預設讀 {}、不吃此值」，故與 _sop_config
    #        的 _FALLBACK_BATCH_SPEC 一致保持 {}。
    def _load_l0_batch_spec():  # type: ignore
        return {
            "main_scripts": 14, "fishing_script": 0, "threads_posts": 7,  # 14＝2026-08-26 拍板（TG22401），同步 SOP yaml batch_spec
            "threads_max_codepoints": 200, "threads_length_effective_from": "2026-07-13",
            "duration_seconds": 60, "title_max_chars": 15,
            "traffic_codes_min": 3, "actor_interaction_min": 1,  # r4：2→1，同步 SOP §batch_spec（舊值 2 已退場，L0 §9.8）
            "school_diversity_min": 3, "theme_diversity_min": 4, "cta_distribution": {},
        }

    def _load_l0_batch_spec_sources():  # type: ignore
        return {
            key: "fallback:validate_script_batch(import_error)"
            for key in _load_l0_batch_spec()
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
L2_BASE = Path(r"/Users/chenzejun/Documents/Claude/Projects/短影音系統/L2_業主層")

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


def chk_l1_001_schema(data: dict, fname: str, expected_slots: Optional[list] = None) -> tuple[str, str]:
    """L1-001：schema 對齊 — N 段時間軸完整且順序正確
    有 canonical 用 canonical（支援 markdown body 格式），沒有 fallback 舊邏輯。
    B 段 2026-06-05：expected_order 改讀 L0 time_slots（廢硬編）。
    W4-K12（2026-07-16 Delta C）：expected_slots 選填 — None＝原 L0 60s 全域路徑逐字零變
    （含 PASS 字面「6 段時間軸齊全且順序正確」原樣保留）；有值（來自批級 time_axis 宣告，
    list of {"timestamp": str, ...}）＝改用宣告軸驗，PASS/FAIL detail 段數字面改實際 N。
    """
    if expected_slots is None:
        expected_order = [s["timestamp"] for s in _load_l0_time_slots()]
    else:
        expected_order = [s["timestamp"] for s in expected_slots]
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
        if expected_slots is None:
            return "PASS", "6 段時間軸齊全且順序正確（canonical 層驗）"
        return "PASS", f"{expected_len} 段時間軸齊全且順序正確（canonical 層驗）"

    # fallback：舊邏輯（structured frontmatter）
    scenes = get_scenes(data)
    if len(scenes) != expected_len:
        return "FAIL", f"scenes 段數 = {len(scenes)}，需要 {expected_len} 段（實際：{[s.get('timestamp','?') for s in scenes]}）"
    actual = [s.get("timestamp", "") for s in scenes]
    for i, (exp, got) in enumerate(zip(expected_order, actual)):
        if got != exp:
            return "FAIL", f"scenes[{i}] timestamp = '{got}'，期望 '{exp}'"
    if expected_slots is None:
        return "PASS", f"6 段時間軸齊全且順序正確"
    return "PASS", f"{expected_len} 段時間軸齊全且順序正確"

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

# ════════════════════════════════════════════
# L1-003 藏鏡人｜長度感知配額 + 業主接球 + S0-S2 酸度（cxp-fullimport-s r2，2026-08-12）
# 舊法真刪：「每支 >= actor_interaction_min（2）、上不封頂」硬配額已廢
#   （源：站 0 診斷 §3 假說 1「限制互撞」支持 + 得標定稿 §5 長度感知配額）。
# 新法：時長 → 建議點數上限；下限固定 1（結構級，FAIL）；超上限＝品質級（WARN，不擋批）。
# ════════════════════════════════════════════

# 長度感知配額表（得標定稿 §5，澤君 TG19759/19761/19763 + TG19765 拍板）
#   d <= 25s → 1 點；26-70s → 2 點；> 70s → 3 點。上限＝建議值，非硬閘。
#   ⚠️ 本表共四處落地，改一處要四處同步：①L0 §9.4 表（正本）
#      ②SOP yaml batch_spec.actor_interaction_quota
#      ③本檔 _MIRROR_QUOTA_TABLE ④yaml_skeleton_generator._MIRROR_QUOTA_TABLE
_MIRROR_QUOTA_TABLE = ((25, 2), (70, 3))   # TG19773 各檔 +1（舊 (25,1),(70,2)）
_MIRROR_QUOTA_LONG = 4                     # TG19773 +1（舊 3）
_MIRROR_MIN = 1  # 結構下限：一支至少 1 個藏鏡人（低於此＝FAIL，取代舊 >=2）

# 業主接球欄 enforce 旗標（shadow → enforce 慣例，同本檔 _S22_ENFORCE 等）：
#   False = shadow（缺接球欄只 WARN）。翻 True 需①全業主現役批遷移完成②主持人/澤君拍板。
#   理由：得標定稿 §5 要求「每點必有業主接球」，但現役 130+ 支生產稿無此欄，
#   直接 enforce 會讓既有批全紅＝把品質規則當硬閘用（違施工工單【禁止事項】）。
#
# ⚠️ T1（cxp-enforce-t1 r1，2026-08-13）起本旗標**降為 legacy 預設值**：
#   真正的判準改成「批次世代」——見 _resolve_enforce_generation()。
#   新格式批（帶 topic_lock 世代）→ enforce=True（缺接球＝FAIL）；
#   舊稿批 → 沿用本旗標（False＝WARN，grandfather 不追溯）。
#   本旗標仍保留：①單檔直呼/外部 caller 不傳世代時的預設 ②全域一次翻死的總開關。
_MIRROR_REPLY_ENFORCE = False


# ════════════════════════════════════════════════════════════════════
# T1 世代判準（cxp-enforce-t1；r1 2026-08-13 建立／**r2 2026-08-13 大修**）
#   源＝得標定稿【霸告】「新批生效＋舊稿 grandfather」＋【愛馬仕】「現成 enum 翻 FAIL
#   ＋『整欄缺只 WARN』逆向誘因洞首修」＋【Codex 終審 r1 兩阻擋項】。
#
# 🔴 r2 修正一（Codex 阻擋項 1／F1）：**世代判準只有這一個函式**。
#   C-TOPIC-LOCK（W1）不再自行重算世代，改呼叫本函式（見 chk_topic_lock_consistency）；
#   主流程每批算一次、同一組 (bool, reason) 同時餵三閘與 C-TOPIC-LOCK。
#   壞 JSON plan 這類異常兩邊行為必須一致——由「同一份回傳值」保證，不靠兩處寫法巧合相同。
#
# 🔴 r2 修正二（Codex 阻擋項 2／F2）：**防自降級**。
#   r1 只看 topic_lock 是否存在 → 把新稿的 topic_lock 欄刪掉就能自降成 grandfather。
#   r2 改為**明列 allowlist 制**（得標骨架原文要求）：
#     批次目錄在 legacy_batch_allowlist.yaml 內 ＝ legacy（今日為界盤點的現役既有批）；
#     **不在 allowlist ＝ new 世代**，缺 topic_lock／缺欄一律 FAIL。刪欄不再能逃鎖。
#   allowlist 檔案缺失／壞格式／schema 不符 ＝ **fail-closed：全部當 new**（不是全部放行）。
#
# 判準優先序（**由嚴到寬，正向訊號永遠勝過 allowlist**）：
#   ① 批內任一稿帶 topic_lock（dict）           → NEW（已遷移批，即使誤列 allowlist 也算新）
#   ② topic_plan 存在但讀不動／結構壞           → NEW（fail-closed；壞檔不得換 grandfather）
#   ③ topic_plan 帶 topic_lock_hash             → NEW
#   ④ 批次目錄命中 legacy allowlist 且 allowlist 本身健康 → LEGACY（唯一的舊稿路徑）
#   ⑤ 其餘（含 batch_dir 不明、allowlist 壞掉） → NEW（fail-closed）
#
# **零誤殺契約（T1d／r2 實測背書）**：allowlist 內的現役舊批走本函式必回 False，
#   三閘對舊批的 PASS/WARN/FAIL 三數與 T1 施工前逐字相同（新增的 enforce 件在舊批一律
#   SKIP 明標，只動 SKIP 數）。誤殺任何一支舊稿＝立即停手回滾（工單【失敗處理】）。
#
# 過渡件說明：梯 2 的 batch_manifest 上線後，本 allowlist 轉為過渡件（見 yaml 檔頭註解）。
# ════════════════════════════════════════════════════════════════════

# 專案根（用來把 allowlist 內的相對路徑解析成絕對路徑）：
#   validate_script_batch.py → script-library → _部署系統 → L4_工具腳本 → 短影音系統
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LEGACY_ALLOWLIST_PATH = Path(__file__).resolve().parent / "legacy_batch_allowlist.yaml"

# 快取：(frozenset[str] 已解析絕對路徑, error_or_None)
_LEGACY_ALLOWLIST_CACHE: Optional[tuple[frozenset, Optional[str]]] = None


class _DuplicateKeyError(yaml.YAMLError):
    """allowlist YAML 內出現重複鍵（見 _NoDupSafeLoader）。"""


class _NoDupSafeLoader(yaml.SafeLoader):
    """SafeLoader ＋ **拒絕重複鍵**（Codex r2 阻擋項：allowlist 重複鍵旁路）。

    PyYAML 預設對 `legacy_batches: []` 後面再寫一次 `legacy_batches: [...]`
    是**默默採最後一鍵**——攻擊者只要在檔尾補一個同名鍵，就能把整包批次
    塞進 allowlist 拿到 grandfather（實測：0/33 new、33/33 legacy）。
    這裡在 construct_mapping 階段對**任一層級**的 mapping 檢查鍵重複，
    命中即拋 _DuplicateKeyError → 呼叫端當格式異常 → fail-closed 全部當 new
    （與語法錯誤／型別錯誤同一條路）。
    """

    def construct_mapping(self, node, deep=False):  # type: ignore[override]
        if isinstance(node, yaml.MappingNode):
            seen = set()
            for key_node, _ in node.value:
                try:
                    key = self.construct_object(key_node, deep=deep)
                except Exception:
                    key = getattr(key_node, "value", None)
                try:
                    hash(key)
                    hashable = key
                except TypeError:  # 不可雜湊的鍵（極罕見）→ 用文字面比對
                    hashable = repr(key)
                if hashable in seen:
                    raise _DuplicateKeyError(f"重複鍵 {key!r}（{node.start_mark}）")
                seen.add(hashable)
        return super().construct_mapping(node, deep=deep)


def _load_legacy_batch_allowlist(force_reload: bool = False) -> tuple[frozenset, Optional[str]]:
    """讀 legacy_batch_allowlist.yaml → (已解析絕對路徑集合, 錯誤訊息或 None)。

    **fail-closed 契約**：檔案不存在／YAML 壞／**任一層級重複鍵**／schema 不符
    → 回 (空集合, 錯誤訊息)，呼叫端據此把**所有**批次當 new 世代（不是全部放行）。
    schema：頂層 dict，必含 legacy_batches: list[str]（相對專案根或絕對路徑）。
    """
    global _LEGACY_ALLOWLIST_CACHE
    if _LEGACY_ALLOWLIST_CACHE is not None and not force_reload:
        return _LEGACY_ALLOWLIST_CACHE
    result: tuple[frozenset, Optional[str]]
    try:
        if not _LEGACY_ALLOWLIST_PATH.exists():
            result = (frozenset(), f"legacy allowlist 檔案不存在（{_LEGACY_ALLOWLIST_PATH.name}）")
        else:
            raw = yaml.load(  # noqa: S506 — 自訂 SafeLoader 子類，未放寬安全性
                _LEGACY_ALLOWLIST_PATH.read_text(encoding="utf-8"),
                Loader=_NoDupSafeLoader,
            )
            if not isinstance(raw, dict):
                result = (frozenset(), "legacy allowlist 頂層結構非 dict")
            elif not isinstance(raw.get("legacy_batches"), list):
                result = (frozenset(), "legacy allowlist 缺 legacy_batches 清單（或型別非 list）")
            else:
                entries = raw["legacy_batches"]
                bad = [e for e in entries if not isinstance(e, str) or not e.strip()]
                if bad:
                    result = (frozenset(), f"legacy allowlist 有 {len(bad)} 筆非字串/空白項")
                else:
                    resolved = set()
                    for e in entries:
                        p = Path(e.strip())
                        if not p.is_absolute():
                            p = _PROJECT_ROOT / p
                        resolved.add(str(p.resolve()))
                    result = (frozenset(resolved), None)
    except Exception as e:  # 讀檔/解析任何異常 → fail-closed
        result = (frozenset(), f"legacy allowlist 讀取異常（{type(e).__name__}: {e}）")
    _LEGACY_ALLOWLIST_CACHE = result
    return result


def _resolve_enforce_generation(
    batch_dir: Optional[Path],
    valid_yamls: list[tuple],
    topic_plan_arg: Optional[str] = None,
) -> tuple[bool, str]:
    """回 (is_new_generation, 判定理由)。**全系統唯一的世代真源**（F1）。

    True＝new 世代（T1 三閘 enforce、C-TOPIC-LOCK 逐欄驗）；
    False＝legacy 世代（僅限命中 allowlist 的現役既有批 → 三閘 SKIP／C-TOPIC-LOCK SKIP）。
    """
    # ① 稿內 topic_lock ＝ 已遷移的正向訊號，勝過 allowlist
    try:
        locked = [
            f for f, d in valid_yamls
            if isinstance(d, dict) and isinstance(d.get("topic_lock"), dict)
        ]
    except Exception as e:
        return True, (
            f"new 世代（fail-closed）— 稿件世代掃描異常（{type(e).__name__}）；"
            f"異常不得換 grandfather"
        )
    if locked:
        return True, (
            f"new 世代（{len(locked)}/{len(valid_yamls)} 支帶 topic_lock 欄）"
            f"— T1 三閘 enforce：零件庫三欄／流量密碼整欄／藏鏡人接球缺欄＝FAIL"
        )

    # ②③ topic_plan：壞檔 fail-closed 當 new；帶 lock hash 也是 new
    if batch_dir is not None:
        try:
            plan_path = _find_topic_plan(batch_dir, topic_plan_arg)
            plan_data, plan_error = _load_topic_plan_checked(plan_path)
            if plan_error:
                return True, (
                    f"new 世代（fail-closed）— topic_plan 存在但讀不動／結構壞："
                    f"{plan_error}；壞檔不得換 grandfather"
                )
            if plan_data.get("topic_lock_hash"):
                return True, (
                    "new 世代（topic_plan 帶 topic_lock_hash）"
                    "— T1 三閘 enforce：零件庫三欄／流量密碼整欄／藏鏡人接球缺欄＝FAIL"
                )
        except Exception as e:
            return True, (
                f"new 世代（fail-closed）— topic_plan 世代判定異常（{type(e).__name__}）"
            )

    # ④ legacy allowlist（唯一的舊稿路徑）
    allow, allow_error = _load_legacy_batch_allowlist()
    if allow_error:
        return True, (
            f"new 世代（fail-closed）— {allow_error}；"
            f"allowlist 不可信時一律當新世代驗，不得整批放行"
        )
    if batch_dir is None:
        return True, (
            "new 世代（fail-closed）— 未提供批次目錄，無法比對 legacy allowlist；"
            "判不出來一律當新世代驗"
        )
    try:
        key = str(Path(batch_dir).resolve())
    except Exception as e:
        return True, f"new 世代（fail-closed）— 批次路徑解析異常（{type(e).__name__}）"
    if key in allow:
        return False, (
            "legacy 世代（批次目錄明列於 legacy_batch_allowlist.yaml，"
            "2026-08-13 盤點的現役既有批）— T1 三閘 grandfather 不追溯"
        )

    # ⑤ 其餘一律 new（**防自降級**：刪 topic_lock 欄不再能逃鎖）
    return True, (
        "new 世代（批次不在 legacy_batch_allowlist.yaml）— 未列管批次一律驗；"
        "刪除 topic_lock 欄不能自降為 grandfather（Codex r1 阻擋項 2）"
    )


# T1 三閘對 legacy 批的 SKIP 明標（**不得**改成靜默略過：SKIP 要看得見才叫 grandfather）
_T1_SKIP_LEGACY = (
    "legacy 世代 grandfather — 僅 legacy_batch_allowlist.yaml 明列的現役既有批走此路徑；"
    "未列管批次一律當 new 世代 enforce"
)

# 酸度分級合法值（得標定稿 §5；S0 中性替問 / S1 直球點破 / S2 嘴賤最大檔）
_SOURNESS_LEVELS = ("S0", "S1", "S2")

# 藏鏡人接球欄的可能鍵名（canonical 英文 / 生產中文）
_MIRROR_REPLY_KEYS = ("offscreen_reply", "藏鏡人接球", "業主接球", "接球")
_MIRROR_SOURNESS_KEYS = ("offscreen_sourness", "藏鏡人酸度", "酸度")


def _mirror_quota_for_duration(duration_seconds: Optional[int]) -> int:
    """時長 → 藏鏡人建議點數上限（L0 §9.4 新配額表）。時長不明＝回 60s 檔（2）。"""
    if not isinstance(duration_seconds, int) or duration_seconds <= 0:
        duration_seconds = 60
    for upper, quota in _MIRROR_QUOTA_TABLE:
        if duration_seconds <= upper:
            return quota
    return _MIRROR_QUOTA_LONG


def _resolve_script_duration(data: dict, duration_seconds: Optional[int] = None) -> int:
    """取本支時長：①呼叫端傳入（批級 time_axis 宣告）②yaml duration/duration_seconds
    ③L0 batch_spec 預設。純讀值不 normalize，解析不出就回 L0 預設。"""
    if isinstance(duration_seconds, int) and duration_seconds > 0:
        return duration_seconds
    for key in ("duration_seconds", "duration"):
        v = data.get(key)
        if type(v) is int and v > 0:
            return v
        if isinstance(v, str):
            m = re.match(r"^\s*(\d{1,4})\s*s?\s*$", v)
            if m:
                n = int(m.group(1))
                if n > 0:
                    return n
    try:
        return int(_load_l0_batch_spec().get("duration_seconds", 60))
    except Exception:
        return 60


def _collect_mirror_points(data: dict) -> tuple[list, str]:
    """收本支所有藏鏡人點 → ([scene_or_block, ...], 來源層標記)。
    canonical 優先（offscreen_interaction），否則 fallback 中文鍵/頂層 block。

    r6 P7（Codex 阻擋項 3）：canonical scene 不帶「藏鏡人接球／藏鏡人酸度」欄
    （yaml_to_sc 正規化只保留 offscreen_interaction），若直接回 canonical dict，
    新骨架會被誤判「接球酸度全缺」。改為：canonical 決定**哪些段有藏鏡人**，
    回傳時把同 slot 的 raw scene 欄位合併回去（raw 有才合併），
    使接球/酸度欄讀得到、同時保有 canonical 對 markdown 稿的解析力。
    **同一支只算一套來源**（canonical 命中就不再累加 scene 層/頂層 block）。
    """
    canonical_scenes = _get_canonical_scenes(data)
    if canonical_scenes is not None:
        raw_scenes = get_scenes(data)
        merged: list = []
        for cs in canonical_scenes:
            if not isinstance(cs, dict) or not cs.get("offscreen_interaction"):
                continue
            point = dict(cs)
            slot = cs.get("slot")
            if isinstance(slot, int) and isinstance(raw_scenes, list) and 1 <= slot <= len(raw_scenes):
                raw = raw_scenes[slot - 1]
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        point.setdefault(k, v)
            merged.append(point)
        return merged, "canonical 層"
    points = [s for s in get_scenes(data) if isinstance(s, dict) and s.get("藏鏡人")]
    if points:
        return points, "scene 層"
    top_mirror = data.get("藏鏡人", {})
    if isinstance(top_mirror, dict):
        return [v for k, v in top_mirror.items() if str(k).startswith("位置")], "頂層 block"
    return [], "無"


def chk_l1_003_mirror(
    data: dict,
    fname: str,
    duration_seconds: Optional[int] = None,
    enforce_generation: Optional[bool] = None,
) -> tuple[str, str]:
    """L1-003：藏鏡人＝長度感知配額 + 每點業主接球 + S0-S2 酸度（2026-08-12 改版）

    判定分層（口語/品質一律 WARN、結構才 FAIL）：
      - 點數 < 1                → FAIL（結構：沒有藏鏡人）
      - 點數 > 時長配額上限      → WARN（品質：擠爆 60 秒＝卡卡根因，站 0 診斷假說 1）
      - 缺業主接球欄            → 新格式批 FAIL／舊稿批 WARN（T1c，見下）
      - 酸度欄缺                → 新格式批 FAIL／舊稿批 WARN（T1c）
      - 酸度值非法              → 新格式批 FAIL／舊稿批 WARN（T1c）
      - 宣告 >= 2 點卻無任何 S2  → WARN（r6 P9；全篇溫吞，建議至少一句點破）
      - S2 > 2 點               → WARN（r6 P9；嘴賤過量，建議降檔）

    **T1c（cxp-enforce-t1 r1，2026-08-13）世代分流**：
      enforce_generation=True（新格式批，帶 topic_lock 世代）→ 缺接球／缺酸度／酸度值非法＝FAIL；
      False（舊稿批）→ 沿用 shadow WARN，351 支歷史稿零誤殺；
      None（外部 caller／單檔直呼未傳）→ 退回模組全域 _MIRROR_REPLY_ENFORCE，**行為與 T1 前逐字相同**。
      「S2 數量建議」（>= 2 點無 S2／S2 > 2）**永遠 WARN**，新批也不升 FAIL——
      那是品質建議不是結構契約（工單 T1c 明列）。

    ⚠️ **L2 業主酸度天花板的機械比對＝未實作（r6 P9 據實記載）**。
       本檢查不讀 L2 偏好檔的天花板宣告、不做「本支酸度 <= 該業主天花板」比對；
       天花板目前**由人工把關**（編劇/算盤覆核時對照 L2 業主檔的「藏鏡人酸度天花板」一行）。
       機械化待 precedence sheet 承接天花板欄後再接（backlog，非本輪範圍）。
       ——本段為現況陳述，不得被引用為「已有天花板硬閘」。

    duration_seconds：呼叫端可傳批級 time_axis 宣告時長；不傳＝從 yaml/L0 推。
    """
    enforce = _MIRROR_REPLY_ENFORCE if enforce_generation is None else bool(enforce_generation)
    dur = _resolve_script_duration(data, duration_seconds)
    quota = _mirror_quota_for_duration(dur)
    points, layer = _collect_mirror_points(data)
    count = len(points)

    if count < _MIRROR_MIN:
        return "FAIL", (
            f"藏鏡人互動點 = {count}，需要 >= {_MIRROR_MIN}（{layer}驗；"
            f"L0 §9.4 長度感知配額：{dur}s → 建議 {quota} 點）"
        )

    warns: list[str] = []
    if count > quota:
        warns.append(
            f"藏鏡人 {count} 點 > {dur}s 建議配額 {quota} 點"
            f"（L0 §9.4；擠爆版型＝結構痕跡外露主因，建議減點或改長版型）"
        )

    # 每點接球欄 + 酸度欄（欄位級檢查；點的內容不做關鍵詞計數）
    missing_reply, missing_sour, bad_sour = 0, 0, []
    sour_levels: list = []
    for p in points:
        if not isinstance(p, dict):
            # 頂層 block 的字串點：無法帶接球/酸度欄 → 一律計入缺欄
            missing_reply += 1
            missing_sour += 1
            continue
        if not any(str(p.get(k, "")).strip() for k in _MIRROR_REPLY_KEYS):
            missing_reply += 1
        sour = ""
        for k in _MIRROR_SOURNESS_KEYS:
            if str(p.get(k, "")).strip():
                sour = str(p[k]).strip().upper()
                break
        if not sour:
            missing_sour += 1
        elif sour not in _SOURNESS_LEVELS:
            bad_sour.append(sour)
        else:
            sour_levels.append(sour)

    # ── T1c 世代分流：新格式批的欄位級缺漏＝結構違規（FAIL），舊稿沿用 WARN ──
    hard: list[str] = []   # 新格式批：升 FAIL 的項
    if missing_reply:
        msg = (f"{missing_reply}/{count} 個藏鏡人點缺業主接球欄"
               f"（{'/'.join(_MIRROR_REPLY_KEYS[:2])}；L0 §9.4「每點必附接球」）")
        if enforce:
            hard.append(msg)
        else:
            warns.append(msg + "［shadow：舊稿世代 grandfather，遷移完成前不擋批］")
    if missing_sour:
        msg = f"{missing_sour}/{count} 個點缺酸度欄（S0/S1/S2；L0 §9.7）"
        if enforce:
            hard.append(msg)
        else:
            warns.append(msg)
    if bad_sour:
        msg = f"酸度值非法 {bad_sour[:3]}（合法＝{'/'.join(_SOURNESS_LEVELS)}）"
        if enforce:
            hard.append(msg)
        else:
            warns.append(msg)

    # ── 酸度分佈 WARN（r6 P9，Codex 阻擋項 4）──
    # 一律 WARN，永不 FAIL（工單【禁止事項】：品質類不升 FAIL）：
    #   ①宣告點 >= 2 時全無 S2 → 全篇溫吞、沒有一句真的點破（得標定稿 §5 偏離記錄：
    #     「S2 每支至少 1」已弱化為「>= 2 點時建議」）
    #   ②S2 > 2 → 嘴賤過量，超出多數業主可接受範圍
    # 天花板（L2 業主檔）機械比對**未實作**，見本 docstring 說明。
    s2_count = sour_levels.count("S2")
    if len(sour_levels) >= 2 and s2_count == 0:
        warns.append(
            f"宣告 {len(sour_levels)} 點酸度但無任何 S2（全 {'/'.join(sorted(set(sour_levels))) or '—'}）"
            f"— 建議至少一句真的點破（L0 §9.7；>= 2 點時建議，非硬規則）"
        )
    if s2_count > 2:
        warns.append(f"S2 共 {s2_count} 點 > 2 — 嘴賤過量，建議降檔（L0 §9.7 寫作鐵則，WARN 不擋批）")

    if hard:
        # T1c：新格式批的欄位級缺漏＝FAIL（品質類 warns 一併列出供編劇一次補完）
        tail = ("；另有品質提示：" + "；".join(warns)) if warns else ""
        return "FAIL", (
            f"藏鏡人 {count} 點（{layer}驗，{dur}s/配額{quota}）— 新格式批必填欄缺漏："
            + "；".join(hard) + tail
        )
    if warns:
        return "WARN", f"藏鏡人 {count} 點（{layer}驗，{dur}s/配額{quota}）— " + "；".join(warns)
    return "PASS", f"藏鏡人 {count} 點（{layer}驗，{dur}s/配額{quota}），接球欄與酸度欄齊備"

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


# ════════════════════════════════════════════
# L1-004 流量密碼｜實質欄位驗證（cxp-fullimport-s r2，2026-08-12）
# 舊法真刪：TRAFFIC_SIGNALS 關鍵詞代理計數（「？」「你也」「留言」…）全數移除。
#   退場依據＝站 0 診斷 §4 相關性檢定。**母體與盲讀數是兩個不同的數字，勿混用**：
#     ①母體＝瑞祥 50 份現役稿（訊號命中數的統計來源）；
#     ②實際人工盲讀＝其中 24 稿（高訊號組 12 支／低訊號組 12 支，兩組各取 12 配對比較）。
#   結果：高訊號組平均卡點 0.83 < 低訊號組 0.92 —— 代理指標與人工卡感無正相關，且「你也」命中 0、
#   「留言」命中 2，訊號實由問號單獨主導。決定：指標不採用，改驗編劇宣告的實質元素。
#   ⚠️ 24 稿＝小樣本、不具統計顯著性，且母體僅瑞祥一家。此證據足以「撤掉無依據的舊代理」，
#      但不得反向用於宣稱新指標有效、也不得當硬閘門檻引用。
# 新法：只認 L0 §1.5 十五元素的具名宣告（schema_check.流量密碼 清單 / 頂層 流量密碼）。
#   宣告齊全 → PASS；宣告不足 → FAIL（實質欄位不足，非猜測）；完全未宣告 → WARN 要求補填
#   （不再用關鍵詞猜台詞，也不因此擋批）。
# ════════════════════════════════════════════

# L0 §1.5 流量密碼 15 元素（白名單；行業層可加特化別名，見 L1）
_TRAFFIC_ELEMENTS = (
    "真實感", "揭露", "共鳴", "反差", "金錢", "數字", "恐懼", "緊迫感",
    "代入感", "情緒", "故事", "世代衝突", "知識落差", "預言感", "地域話題",
)

# L0 §1.5.2 可選元素（陳修平流量密碼導入 2026-08-12）：**不計數、不設配額**
# （L0 :294 白紙黑字「不是必填、不計數、不設配額」）。宣告了也不算進 §1.5 門檻，
# 但也不當成 unknown 警告——它們是合法宣告，只是不計數。
_TRAFFIC_OPTIONAL_ELEMENTS = ("隨機", "盲盒", "貼金", "互動吐槽點", "吐槽點")


def _classify_traffic_elements(elements: list) -> tuple[list, list, list]:
    """把編劇宣告的流量密碼分三類 →（白名單命中 canonical 名（去重、保序）, 可選元素（不計數）, 未知）。

    命中判定與舊版一致（startswith 或子字串），但**改以 canonical 元素名去重**：
    重複宣告同一元素（例：三個「真實感」）只算 1 個，避免灌水過門檻。
    """
    known: list = []
    optional: list = []
    unknown: list = []
    for e in elements:
        s = str(e).strip()
        if not s:
            continue
        canon = next((k for k in _TRAFFIC_ELEMENTS if s.startswith(k) or k in s), None)
        if canon is not None:
            if canon not in known:
                known.append(canon)
            continue
        if any(k in s for k in _TRAFFIC_OPTIONAL_ELEMENTS):
            if s not in optional:
                optional.append(s)
            continue
        unknown.append(s)
    return known, optional, unknown


def _extract_traffic_declaration(data: dict) -> tuple[list, Optional[int], str]:
    """取編劇宣告的流量密碼 →（元素名 list, 純數字宣告, 來源欄位）。
    支援：schema_check.流量密碼 / schema_check.流量密碼元素 / 頂層 流量密碼 /
          schema_check.流量密碼數量（legacy 純數字宣告，仍收但提示改列名）。"""
    sc = data.get("schema_check") if isinstance(data.get("schema_check"), dict) else {}
    for holder, label in ((sc, "schema_check"), (data, "頂層")):
        for key in ("流量密碼", "流量密碼元素", "traffic_codes"):
            v = holder.get(key)
            if isinstance(v, list) and v:
                return [str(x).strip() for x in v if str(x).strip()], None, f"{label}.{key}"
            if isinstance(v, str) and v.strip():
                parts = [p.strip() for p in re.split(r"[、,，/／|]", v) if p.strip()]
                if parts:
                    return parts, None, f"{label}.{key}"
    for holder, label in ((sc, "schema_check"), (data, "頂層")):
        v = holder.get("流量密碼數量")
        if v not in (None, ""):
            try:
                return [], int(str(v)), f"{label}.流量密碼數量"
            except Exception:
                pass
    return [], None, ""


def chk_l1_004_traffic(
    data: dict,
    fname: str,
    enforce_generation: Optional[bool] = None,
) -> tuple[str, str]:
    """L1-004：流量密碼 >= traffic_codes_min（實質欄位；2026-08-12 廢關鍵詞代理計數）

    門檻＝**白名單命中數（去重）**（r6 修）：只有對上 L0 §1.5 十五元素的宣告才計數，
    同一元素重複宣告只算 1；垃圾字串不計數（另列 WARN）；
    L0 §1.5.2 可選三元素（隨機盲盒／貼金／互動吐槽點）依 L0 :294 **不計數**（也不算未知）。

    **T1b（cxp-enforce-t1 r1，2026-08-13）逆向誘因洞首修**：
      舊行為＝「宣告不足＝FAIL、整欄不宣告＝WARN」——填了被抓、不填免查，
      編劇的最佳策略變成「不要填」（reward hacking）。本輪封掉：
        enforce_generation=True（新格式批）→ 整欄未宣告＝FAIL（與宣告不足同級）；
        False（舊稿批）→ 維持 WARN，130+ 支無此欄的現役稿零誤殺；
        None（外部 caller 未傳）→ 退回 _MIRROR_REPLY_ENFORCE 全域預設（T1 前行為逐字不變）。
      **白名單計數 FAIL 的既有邏輯一個字都沒動**（工單 T1b 明令）：
      有宣告時的 known < min → 照舊 FAIL、legacy 純數字宣告 < min → 照舊 FAIL。
    """
    enforce = _MIRROR_REPLY_ENFORCE if enforce_generation is None else bool(enforce_generation)
    min_count = _load_l0_batch_spec()["traffic_codes_min"]
    elements, legacy_n, src = _extract_traffic_declaration(data)

    if elements:
        known, optional, unknown = _classify_traffic_elements(elements)
        n = len(known)
        opt_note = f"；可選元素（不計數，L0 §1.5.2）：{optional[:4]}" if optional else ""
        unk_note = f"；未對上 L0 §1.5 元素名（不計數）：{unknown[:4]}（行業特化別名請於 L1 登錄）" if unknown else ""
        if n < min_count:
            return "FAIL", (f"流量密碼白名單命中 {n} 個（去重後：{known}；{src} 原宣告 {len(elements)} 項），"
                            f"需 >= {min_count}（L0 §1.5 十五元素具名宣告）{opt_note}{unk_note}")
        status = "WARN" if unknown else "PASS"
        return status, (f"流量密碼白名單命中 {n} 個（去重：{known[:6]}，{src}）>= {min_count}"
                        f"{opt_note}{unk_note}")

    if legacy_n is not None:
        if legacy_n < min_count:
            return "FAIL", f"{src} = {legacy_n}，需 >= {min_count}"
        return "WARN", (f"{src} = {legacy_n}（>= {min_count} 通過），但只給數字未列元素名 — "
                        f"建議改填 schema_check.流量密碼: [元素名, ...]（L0 §1.5）")

    # ── 整欄未宣告（T1b：封「不填就免查」旁路）──
    _base = (f"未宣告流量密碼實質欄位（schema_check.流量密碼 清單）— "
             f"2026-08-12 起關鍵詞代理計數已廢（站 0 診斷 §4：無相關性），"
             f"請由編劇具名宣告 >= {min_count} 個 L0 §1.5 元素")
    if enforce:
        return "FAIL", (_base + "［T1b：新格式批整欄缺＝FAIL，"
                                "與『宣告不足』同級——不填不再等於免查］")
    return "WARN", (_base + "［舊稿世代 grandfather：整欄缺仍只 WARN］")

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

def chk_l1_006_cta(data: dict, fname: str, cta_slot: Optional[str] = None) -> tuple[str, str]:
    """L1-006：末段（L0 time_slots 最後一段）有 CTA 引導語（純雞湯除外）
    有 canonical 用 canonical（timestamp 正規化 + dialogue），沒有 fallback 舊邏輯。
    B 段 2026-06-05：cta_slot 改讀 L0 time_slots 末段（廢硬編 '52-60s'）。
    W4-K12（2026-07-16 Delta D）：cta_slot 選填 — None＝原 L0 60s 全域末段逐字零變；
    有值（來自批級 time_axis 宣告末段 timestamp）＝改用宣告末段驗（N>=2 下限保證末段≠首段，
    CTA-last 語義沿用）。
    """
    if cta_slot is None:
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

def _is_topic_type_grandfather(yamls: list[tuple[Path, dict]]) -> bool:
    """唯一舊批判準：所有有效 YAML 都沒有 topic_type 欄。"""
    valid = [
        data for _, data in yamls
        if isinstance(data, dict) and "__parse_error__" not in data and "__schema_error__" not in data
    ]
    return bool(valid) and all("topic_type" not in data for data in valid)


def _expected_main_scripts_for_batch(yamls: list[tuple[Path, dict]]) -> int:
    return 13 if _is_topic_type_grandfather(yamls) else int(_load_l0_batch_spec()["main_scripts"])


def chk_r_type_001_topic_type_quota(yamls: list[tuple[Path, dict]]) -> tuple[str, str]:
    """R-TYPE-001：新批 topic_type 必填且 Q1-Q8 配額精確。

    Grandfather 判準是批級、不可讓單檔自行降級：全批都沒有欄位才是舊批 SKIP；
    只要混入新欄，任何缺欄都 FAIL。
    """
    valid = [(f, d) for f, d in yamls if isinstance(d, dict) and "__parse_error__" not in d and "__schema_error__" not in d]
    if not valid:
        return "FAIL", "R-TYPE-001：無有效 YAML，無法驗 topic_type 配額"
    if _is_topic_type_grandfather(valid):
        return "SKIP", "R-TYPE-001：舊批 grandfather（全批 YAML 均無 topic_type 欄）"

    missing = [f.name for f, data in valid if "topic_type" not in data]
    if missing:
        return "FAIL", f"R-TYPE-001：混合批 topic_type 缺欄：{missing}"

    values = {topic_type: 0 for topic_type in TOPIC_TYPE_VALUES}
    invalid: list[str] = []
    for f, data in valid:
        topic_type = data.get("topic_type")
        if not isinstance(topic_type, str) or topic_type not in TOPIC_TYPE_VALUES:
            invalid.append(f"{f.name}={topic_type!r}")
            continue
        values[topic_type] += 1

    problems = []
    if invalid:
        problems.append("非法 topic_type：" + "; ".join(invalid))
    for topic_type, expected in TOPIC_TYPE_TARGET_COUNTS.items():
        if values[topic_type] != expected:
            problems.append(f"{topic_type}={values[topic_type]} expected={expected}")
    if problems:
        return "FAIL", "R-TYPE-001：" + "；".join(problems)
    return "PASS", "R-TYPE-001：Q1-Q6 各 2、Q7/Q8 各 1（14 支）"


def chk_r_src_001_origin_source(yamls: list[tuple[Path, dict]]) -> tuple[str, str]:
    """R-SRC-001：來源欄是過渡選填；填了才驗 enum 與 source_4 上限。"""
    valid = [(f, d) for f, d in yamls if isinstance(d, dict) and "__parse_error__" not in d and "__schema_error__" not in d]
    has_field = any("origin_source" in data for _, data in valid)
    if not has_field:
        return "SKIP", "R-SRC-001：全批未填 origin_source（過渡期）"
    supplied = [(f, data.get("origin_source")) for f, data in valid if "origin_source" in data]
    invalid = [
        f"{f.name}={value!r}"
        for f, value in supplied
        if not isinstance(value, str) or (value.strip() and value not in ORIGIN_SOURCE_VALUES)
    ]
    filled = [(f, value) for f, value in supplied if isinstance(value, str) and value.strip()]
    source_4_count = sum(1 for _, value in filled if value == "source_4_created")
    problems = []
    if invalid:
        problems.append("非法 origin_source：" + "; ".join(invalid))
    if source_4_count > 2:
        problems.append(f"source_4_created={source_4_count} expected_max=2")
    if problems:
        return "FAIL", "R-SRC-001：" + "；".join(problems)
    return "PASS", f"R-SRC-001：已填 {len(filled)}/{len(valid)} 支，source_4_created={source_4_count}/2"


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

CONCRETE_KNOWLEDGE_SCHOOLS = {"拆解派", "結構分析派", "老前輩權威派", "直球派", "市場觀察派", "時事追擊派"}
_CONCRETE_SIGNAL_RE = re.compile(
    r"[0-9０-９]+|[一二三四五六七八九十百千]+[年月天週個成倍折坪元萬]|今天|昨天|上週|上個月|去年|那天|當時"
)

def chk_c017_concreteness(data: dict, fname: str) -> tuple[str, str]:
    """C-017：具體化密度（WARN-only — 2026-06-11 課程導入 W3）
    知識型骨架（主推派系屬 CONCRETE_KNOWLEDGE_SCHOOLS）逐篇驗主體段具體化信號
    （數字/時間/具體量詞）< 2 → WARN。雞湯/感性/共鳴型豁免（非知識派系一律 PASS）。
    分類欄位填錯防護：欄位缺/型別錯/解析異常 → 一律豁免不誤傷（永不 FAIL，fail-open）。
    對齊 L0 §1.2.1 優化「具體化」+ scripter.md §20 自檢 17 條。"""
    try:
        school = str(data.get("主推派系", "") or data.get("派系", "") or "").strip()
        cta_type = ""
        sc = data.get("schema_check")
        if isinstance(sc, dict):
            cta_type = str(sc.get("CTA類型", "") or "")
        if "雞湯" in cta_type:
            return "PASS", f"純雞湯 CTA 豁免具體化密度（主推={school or '未填'}）"
        if school not in CONCRETE_KNOWLEDGE_SCHOOLS:
            return "PASS", f"非知識型骨架（主推={school or '未填'}），具體化密度豁免"
        scenes = get_scenes(data)
        if not isinstance(scenes, list) or not scenes:
            return "PASS", "C-017 防護：無 scenes 可解析，豁免不誤傷"
        body_text = ""
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            ts = str(scene.get("timestamp", "") or scene.get("時間", ""))
            if ("12-25" in ts) or ("25-40" in ts):
                for k, v in scene.items():
                    # 排除非內容欄位（timestamp 自帶數字會假性灌分 — F23a 抓到的 bug）
                    if str(k) in ("timestamp", "時間", "type"):
                        continue
                    if isinstance(v, str):
                        body_text += v
        if not body_text.strip():
            return "PASS", "C-017 防護：主體段尚未填台詞（骨架階段），豁免"
        hits = _CONCRETE_SIGNAL_RE.findall(body_text)
        if len(hits) < 2:
            return "WARN", f"知識型腳本主體段具體化信號僅 {len(hits)} 個（<2）— 建議加數字/時間/人事物細節（L0 §1.2.1「一具體就深刻」）"
        return "PASS", f"具體化信號 {len(hits)} 個（≥2）"
    except Exception as e:  # fail-open：WARN 級品質提示不可炸 validator
        return "PASS", f"C-017 防護：解析異常豁免（{type(e).__name__}）"


# ════════════════════════════════════════════
# 「寫給唸」advisory 二件（C-018 小六度 / C-019 關我屁事）
#   cxp-fullimport-s r2，2026-08-12；骨架抄 chk_c017（WARN-only + fail-open）。
#   🔴 紅線（得標定稿 §2、工單【禁止事項】）：口語/品質檢測**永不升硬閘**，只回 PASS/WARN。
#   🔴 未校準數字（句長門檻等）一律標「待業主盲讀校準，不得當硬閘引用」——
#      站 0 診斷 §7 已測：陳修平逐字稿句長 P50=16 字、瑞祥稿 P50=26 字；
#      但母體只有瑞祥一家（跨業主 FAIL·資料不足），故本二件的數字全為 advisory 觸發線，
#      非門檻，改動不需 re-bless。
# ════════════════════════════════════════════

# 待業主盲讀校準（不得當硬閘引用）：句長 advisory 觸發線
_C018_SENTENCE_LEN_HINT = 26   # 站 0 §7 瑞祥稿現況中位數；超過＝提示短句化
_C018_LONG_RATIO_HINT = 0.5    # 超過一半句子過長才提示，避免逐句嘮叨
# 待業主盲讀校準（不得當硬閘引用）：一句一資訊 — 單句資訊標記數
_C018_INFO_MARK_HINT = 4       # 站 0 §7：逐字稿 5.10／瑞祥 3.25，皆為壓縮度 proxy 非品質
_C018_SENT_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")
_C018_INFO_MARK_RE = re.compile(r"[，、（）()：:；;]")

# C-019「關我屁事」：與觀眾無關的自我本位開場（陳修平公式：反例「我們成立於 1973 年」）
_C019_SELF_CENTERED_RE = re.compile(
    r"(我們(成立|創立|創辦|公司|團隊|品牌)|本公司|敝公司|創立於|成立於|"
    r"大家好[，,]?我(是|叫)|今天很開心|榮獲|獲頒|通過.{0,6}認證)"
)


def _c018_body_sentences(data: dict) -> list:
    """取可播稿體句子（排除 timestamp/type 等非內容欄，同 C-017 防假性計分做法）。

    r6 P8（Codex 阻擋項 5）：**canonical 優先**。舊法只讀 raw `scenes`，
    現役 42 份 markdown 時間軸稿（`_markdown_body`，無 scenes 鍵）一律回空 list，
    導致 C-018／C-019 靜默回「無可播稿體句」PASS＝檢查根本沒執行到內容。
    新法：先走與其他 chk 同源的 canonical markdown 正規化（_get_canonical_scenes），
    取 dialogue.line + offscreen_interaction（可播內容），
    **不取 subtitle／visual**（字幕與畫面描述非唸出來的稿體，與舊法排除「翠文/畫面/字幕卡」一致）。
    canonical 不可用時 fallback 舊 raw scenes 路徑（逐字不變）。
    """
    out: list[str] = []

    canonical_scenes = _get_canonical_scenes(data)
    if canonical_scenes is not None:
        for sc in canonical_scenes:
            if not isinstance(sc, dict):
                continue
            for d in sc.get("dialogue", []) or []:
                line = d.get("line", "") if isinstance(d, dict) else str(d)
                if line and str(line).strip():
                    out.extend(s.strip() for s in _C018_SENT_SPLIT_RE.split(str(line)) if s.strip())
            mirror = sc.get("offscreen_interaction", "")
            if mirror and str(mirror).strip():
                out.extend(s.strip() for s in _C018_SENT_SPLIT_RE.split(str(mirror)) if s.strip())
        if out:
            return out
        # canonical 解析得到 scenes 但無任何可播句 → 落回 raw 路徑再試（不誤傷）

    scenes = get_scenes(data)
    if not isinstance(scenes, list):
        return out
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        for k, v in scene.items():
            if str(k) in ("timestamp", "時間", "type", "翠文", "畫面", "字幕卡"):
                continue
            if isinstance(v, str) and v.strip():
                out.extend(s.strip() for s in _C018_SENT_SPLIT_RE.split(v) if s.strip())
    return out


def chk_c018_readability(data: dict, fname: str) -> tuple[str, str]:
    """C-018：小六度／寫給唸（WARN-only，永不 FAIL — 得標定稿 §2 紅線）

    三個 advisory 訊號（全部只提示、不擋批）：
      ①長句比例（觸發線 {_C018_SENTENCE_LEN_HINT} 字，待業主盲讀校準）
      ②一句多資訊（單句標點資訊標記 >= {_C018_INFO_MARK_HINT}，待校準）
      ③稿體混入自檢/報告層文字（診斷 §5 卡點「過修污染」：稿體只留可播內容）
    分類欄位缺/型別錯/解析異常 → 一律 PASS（fail-open，同 C-017）。
    """
    try:
        sents = _c018_body_sentences(data)
        if not sents:
            return "PASS", "C-018 防護：無可播稿體句可解析，豁免不誤傷"
        long_sents = [s for s in sents if len(s) > _C018_SENTENCE_LEN_HINT]
        dense_sents = [s for s in sents if len(_C018_INFO_MARK_RE.findall(s)) >= _C018_INFO_MARK_HINT]
        report_leak = [s for s in sents if re.search(r"(採納|沒採納|硬約束|自檢|redline|upgrade_report|修訂說明)", s)]

        hints = []
        if sents and len(long_sents) / len(sents) > _C018_LONG_RATIO_HINT:
            hints.append(
                f"長句 {len(long_sents)}/{len(sents)} 句 > {_C018_SENTENCE_LEN_HINT} 字"
                f"（例：{long_sents[0][:24]}…）— 建議短句化、寫給唸"
            )
        if dense_sents:
            hints.append(
                f"{len(dense_sents)} 句單句資訊密度高（標記 >= {_C018_INFO_MARK_HINT}）"
                f"（例：{dense_sents[0][:24]}…）— 建議一句一資訊"
            )
        if report_leak:
            hints.append(
                f"稿體疑混入自檢/報告層文字 {len(report_leak)} 句"
                f"（例：{report_leak[0][:24]}…）— 稿體只留可播內容，自檢移 upgrade_report"
            )
        if hints:
            return "WARN", ("C-018 小六度 advisory（WARN-only，數字待業主盲讀校準、"
                            "不得當硬閘引用）：" + "；".join(hints))
        return "PASS", f"C-018：{len(sents)} 句，句長與資訊密度在 advisory 線內"
    except Exception as e:
        return "PASS", f"C-018 防護：解析異常豁免（{type(e).__name__}）"


# ════════════════════════════════════════════
# C-PARTS-001：零件庫機器契約三欄（r9 Q7，2026-08-13）
#   源＝得標定稿 §1「五項導入不新開雙正本」：標題六型／開頭四型／結尾三型
#   原本只有 L0 文檔敘述，yaml 無欄位＝機器讀不到、驗不了。
#   骨架機 schema_check 已補三欄（標題型／開頭軸／結尾型），本件驗它。
#   **WARN-only 永不 FAIL**（骨架抄 chk_c017/chk_c018）：130+ 現役稿無此三欄，
#   直上 FAIL＝把品質規則變硬閘、既有批次全打紅，違「不得當硬閘」紅線。
#   要翻硬閘的條件＝全業主遷移完成＋主持人/澤君拍板（同 _MIRROR_REPLY_ENFORCE）。
# ════════════════════════════════════════════
_PARTS_ENUMS = {
    "標題型": ({"T1", "T2", "T3", "T4", "T5", "T6"}, "L0 §11.0.4 標題六型"),
    "開頭軸": ({"O1", "O2", "O3", "O4"}, "L0 §11.0.5 開頭四型（一選一互斥）"),
    "結尾型": ({"E1", "E2", "E3"}, "L0 §13.6 結尾三型正本（反轉＝payoff 技法，非第四型）"),
}
# 值判定（r11 T2，2026-08-13）：**精確匹配集合**，不再做「取開頭 token」的寬鬆抽取。
#   舊法漏洞：_PARTS_CODE_RE = r"^\s*([TOE]\s*[0-9])" 只吃**一位數**，
#     "T10" → 抽出 "T1" 判合法（實際上 T10 根本不存在）；
#     "E1/E2" → 抽出 "E1" 判合法（複合值＝沒有一選一，等於沒宣告）；
#     "O40" → 抽出 "O4" 判合法。三者皆是「非法值被洗成合法」。
#   新法：str 值 strip＋去內部空白＋轉大寫後**必須與 enum 全等**，否則 WARN 非法枚舉。
#     非 str 型別（bool／數字／dict／list／None）一律非法。
#     仍**不做語意猜測**：不接受 "T3 解答式" 這類帶說明文字的值——欄位是機器契約欄，
#     說明文字請寫在別的欄位或註解（此為 r9 相對 r11 的口徑收緊，見下方 fixtures 註記）。
_PARTS_WS_RE = re.compile(r"\s+")


def _parts_normalize_code(value) -> Optional[str]:
    """欄值正規化為 enum 比對用 token；非 str 或空值回 None（r11 T2 精確匹配）。"""
    if not isinstance(value, str):
        return None          # bool／int／dict／list／None 皆非法（不做 str() 救援）
    s = _PARTS_WS_RE.sub("", value).strip().upper()
    return s or None


def _parts_scan(sc: dict) -> tuple[list[str], list[str], list[str]]:
    """掃 schema_check 三欄 → (missing, bad, ok)。**訊息字串為 C-PARTS-001／002 共用真源**
    （T1a 抽出；抽出前後 C-PARTS-001 的 detail 文案逐字相同，見 F-CXP-T1-A* fixtures）。"""
    missing: list[str] = []
    bad: list[str] = []
    ok: list[str] = []
    for field, (allowed, ref) in _PARTS_ENUMS.items():
        if field not in sc:
            missing.append(f"{field}（缺欄；{ref}）")
            continue
        raw = sc.get(field)
        # placeholder 判定：既有 _is_placeholder，另補骨架機產的 "[編劇填 T1-T6]" 樣式
        _rs = str(raw).strip() if raw is not None else ""
        if (_is_placeholder(raw) or not _rs
                or (_rs.startswith("[") and _rs.endswith("]"))
                or "編劇填" in _rs):
            missing.append(f"{field}（未填／仍是 placeholder；{ref}）")
            continue
        code = _parts_normalize_code(raw)
        if code is None or code not in allowed:
            bad.append(f"{field}={str(raw)[:16]!r} 非法枚舉（須與合法值全等：{'/'.join(sorted(allowed))}；{ref}）")
            continue
        ok.append(f"{field}={code}")
    return missing, bad, ok


def chk_parts_002_component_enums_enforce(
    data: dict,
    fname: str,
    enforce_generation: Optional[bool] = None,
) -> tuple[str, str]:
    """C-PARTS-002（T1a，cxp-enforce-t1 r1 2026-08-13）：零件庫三欄**新格式批硬閘**

    源＝得標定稿【愛馬仕】「現成 enum 翻 FAIL」＋【霸告】「新批生效＋舊稿 grandfather」。
    判定（**只在新格式批生效**）：
      - 三欄齊全且皆為合法 enum（T1-T6／O1-O4／E1-E3，精確匹配）→ PASS
      - 任一欄缺／仍是 placeholder／非法 enum → FAIL
      - 整塊 schema_check 缺或型別錯 → FAIL（新格式批不得用「整塊不填」換免查——
        這正是 T1b 同一個逆向誘因洞，零件庫欄同步封）
    舊稿批（enforce_generation 非 True）→ **SKIP 明標**，三欄仍由 C-PARTS-001 出 WARN。
    解析異常 → FAIL 並附例外類型（新批 fail-closed；舊批走不到這裡）。
    """
    if not enforce_generation:
        return "SKIP", f"C-PARTS-002 SKIP — {_T1_SKIP_LEGACY}；本批三欄由 C-PARTS-001 advisory 承接"
    try:
        sc = data.get("schema_check")
        if not isinstance(sc, dict):
            return "FAIL", (
                "C-PARTS-002 FAIL — 新格式批缺整塊 schema_check（或型別錯），"
                "零件庫三欄（標題型／開頭軸／結尾型）無從驗證；"
                "整塊不填不得換免查（同 T1b 逆向誘因洞）"
            )
        missing, bad, ok = _parts_scan(sc)
        problems = missing + bad
        if problems:
            return "FAIL", (
                "C-PARTS-002 FAIL — 新格式批零件庫三欄未達機器契約："
                + "；".join(problems)
                + (f"（已齊：{', '.join(ok)}）" if ok else "")
            )
        return "PASS", f"C-PARTS-002 PASS — 新格式批三欄合法（{', '.join(ok)}）"
    except Exception as e:
        return "FAIL", f"C-PARTS-002 FAIL — 解析異常（{type(e).__name__}），新格式批 fail-closed"


# ════════════════════════════════════════════════════════════════════
# 梯 2（cxp-enforce-t2 r1 2026-08-13／r3 2026-08-14）：chxp registry／receipt／
#   **17 招分層入口已配置**（用語照 Codex 終審更正：不是「17 招全補」——
#   人工三條 021/022/109 尚未有人執行、#058 走 BLOCKED 獨立入口尚未建流程、
#   receipt 五條也只驗「有沒有申報」，不抓「該用卻沒申報」）
# ════════════════════════════════════════════════════════════════════
# 得標定稿骨架＝Codex R1；嫁接件＝【愛馬仕】版本緩衝＋C-quote-source 範式、
# 【龍蝦】兩段式判定＋conditional 機器重算、【霸告】registry owner 落人＋梯次施工。
#
# 🔴 澤君 TG19810 紅線：**不得鎖死寫法**。本段全部檢查只驗三件事——
#    ①選了哪個型（enum 命中）②該型要求的欄位在不在 ③證據指標解不解得回稿內位置。
#    **零語意品質判斷**：不判方法用得好不好、內容有沒有趣、文字自不自然。
#    規則本體寫在 chxp_method_registry.yaml，validator 端是泛用執行器——
#    改一條方法＝改 yaml＋bump 版本，不必改這支程式。
#
# 世代分流（沿用 T1 的 _resolve_enforce_generation 單一真源，不另立）：
#    new 世代（enforce_generation=True）→ 照驗、缺＝FAIL
#    legacy 世代 → 一律 SKIP 明標（grandfather；零誤殺契約由 Y5 五批對照背書）
# ════════════════════════════════════════════════════════════════════

try:
    import chxp_registry as _chxp  # type: ignore[import]
    _CHXP_OK = True
except Exception as _chxp_e:  # pragma: no cover - 部署缺檔時
    _chxp = None  # type: ignore[assignment]
    _CHXP_OK = False
    print(f"[validate_script_batch] WARN: chxp_registry 未載入（{type(_chxp_e).__name__}: {_chxp_e}）—— "
          f"C-CXP-* 系列將對新世代批 fail-closed 打 FAIL", file=sys.stderr)

# 梯 2 SKIP 明標（與 _T1_SKIP_LEGACY 同樣「看得見才叫 grandfather」）
_T2_SKIP_LEGACY = (
    "legacy 世代 grandfather — 僅 legacy_batch_allowlist.yaml 明列的現役既有批走此路徑；"
    "未列管批次一律當 new 世代 enforce"
)


def _chxp_registry_or_error() -> tuple[Optional[dict], Optional[str]]:
    """取 registry；模組缺席也走同一條 fail-closed 路（回錯誤字串）。"""
    if not _CHXP_OK or _chxp is None:
        return None, "chxp_registry 模組未載入（部署缺檔或 import 失敗）"
    return _chxp.load_registry()


def chk_cxp_receipt(
    data: dict,
    fname: str,
    enforce_generation: Optional[bool] = None,
    is_skeleton_file: bool = False,
) -> tuple[str, str]:
    """C-CXP-RECEIPT（per-file）：每支稿的「用了哪幾招」收據**結構驗**。

    得標定稿：骨架機產 `chxp_receipt:` 欄，applicable_ids **由機器重算**
    （registry conditional 規則），used 由編劇填 method_id ＋ 證據指標。
    本檢查只驗結構（**不判用得好不好** — 工單 Y3 明令）：
      ① 新世代批必須有 chxp_receipt 欄（缺＝FAIL；不填不得換免查）
      ② **used 鍵必須存在**（r3／H2①：缺鍵＝FAIL，不再默默轉成空陣列；
         顯式 `used: []` 允許，但仍須通過 ③ 的 always 申報）
      ②b **BLOCKED／人工／excluded 條目在 used 出現＝單獨 FAIL**（r4／J1）：
         在其他欄位檢查之前先跑並直接 return，**不依賴其他欄位一起失敗**；
         身分以**程式端常數**為準，registry 被變造也擋得住。
      ③ **registry_version 對照「實際載入的 registry 版本」**（r4／J2）：
         一致＝PASS／相鄰一版＝**WARN（本檢查回 WARN，不吞成 PASS）**／
         其餘（缺、非字串、格式非法、family 不同、差兩版以上）＝FAIL
      ④ **11 條 always-applicable 必須交代**（r3／H2③）：每條要嘛在 used
         具名（帶可解回證據），要嘛在 `waiver` 欄具名說明；漏一條＝FAIL。
         **只驗有無申報，不判品質**。
      ⑤ used[].method_id 必須是 registry 內的合法 id（未知 id＝FAIL）
      ⑥ **applicable_ids 若含未知 id ＝FAIL**（r3／H2④：r1 把稿內自填值
         純當留痕，導致 `applicable_ids: ["999"]` 照樣 PASS）
      ⑦ used[].evidence_ref 必須能解回稿內位置（path:/quote:）
      ⑧ **source_artifact_hashes / receipt_hash 欄**（r3／H2⑤）：骨架機產，
         validator 驗**存在與格式**；receipt_hash 若與本稿重算值不符＝
         收據過期（新鮮度 FAIL）。
    另：稿內 applicable_ids 若與機器重算結果不符 → 判定仍以機器重算為準。
    骨架階段（本支 title 仍是 placeholder）→ SKIP。legacy 世代 → SKIP 明標。
    """
    if not enforce_generation:
        return "SKIP", f"{fname}: C-CXP-RECEIPT SKIP — {_T2_SKIP_LEGACY}"
    reg, err = _chxp_registry_or_error()
    if err or reg is None:
        return "FAIL", f"{fname}: C-CXP-RECEIPT FAIL — registry 不可用：{err}（新世代批 fail-closed）"
    try:
        receipt = data.get("chxp_receipt")
        if is_skeleton_file:
            return "SKIP", (f"{fname}: C-CXP-RECEIPT 骨架階段跳過（title 仍為 placeholder，"
                            f"編劇尚未填 used）；填完即 fail-closed")
        if not isinstance(receipt, dict):
            return "FAIL", (
                f"{fname}: C-CXP-RECEIPT FAIL — 新世代批缺 chxp_receipt 欄（或型別非 mapping）；"
                f"每支稿必須留「用了哪幾招」收據，整欄不填不得換免查"
            )
        valid_ids = {m["id"] for m in reg.get("methods", []) if isinstance(m.get("id"), str)}
        layer_of = {m["id"]: m.get("layer") for m in reg.get("methods", []) if isinstance(m.get("id"), str)}
        mode_of = {m["id"]: m.get("mode") for m in reg.get("methods", []) if isinstance(m.get("id"), str)}
        computed = _chxp.compute_applicable_ids(data, reg)  # type: ignore[union-attr]
        problems: list[str] = []
        warns: list[str] = []

        # ── H2① used 鍵必須存在（缺鍵 ≠ 顯式空列表）──
        if "used" not in receipt:
            return "FAIL", (
                f"{fname}: C-CXP-RECEIPT FAIL — chxp_receipt 缺 used 鍵；"
                f"缺鍵不等於「沒用任何方法」，要宣告沒用請顯式寫 `used: []`"
                f"（仍須在 waiver 交代 11 條 always 條目）"
            )
        used = receipt.get("used")
        if not isinstance(used, list):
            return "FAIL", f"{fname}: C-CXP-RECEIPT FAIL — chxp_receipt.used 型別非 list（得到 {type(used).__name__}）"

        # ── H2②／r4-J2 registry_version 對照**實際載入的 registry 版本** ──
        #    r3 是拿 receipt 版本跟「程式端期望常數」比，Codex 判定「沒有對實際
        #    載入的 registry 版本建立關聯」。現在 match=PASS／前一版=WARN／其他=FAIL，
        #    且 **WARN 不被吞掉**（見下方回傳段：底層 WARN → 本檢查回 WARN）。
        rv_status, rv_detail = _chxp.check_receipt_registry_version(  # type: ignore[union-attr]
            receipt.get("registry_version"),
            receipt.get("previous_registry_version"),
            reg,
        )
        if rv_status == "FAIL":
            problems.append(f"registry_version 非法或超出 grace：{rv_detail}")
        elif rv_status == "WARN":
            warns.append(rv_detail)

        # ── r4／J1 #058（BLOCKED）／人工層／excluded 的**單獨 receipt 路徑硬擋** ──
        #    🔴 Codex r3 判定：r3 的 BLOCKED 檢查藏在 used 迴圈裡，跟其他欄位
        #    共用同一個 problems 清單——修復 probe 是因為「缺版本、waiver、hash」
        #    才 FAIL，**沒有真正驗到 #058**；而且判定依據是 registry 的 layer 欄，
        #    把 #058 的 layer 改成 none 就一起消失。現在改成：
        #      ① **在所有其他欄位檢查之前先跑**，命中即 return FAIL（單因即紅）
        #      ② 身分來源＝**程式端常數**（_EXPECTED_BLOCKED_IDS／_EXPECTED_MANUAL_IDS），
        #         registry 被變造也擋得住；registry 的 layer／mode 只是額外補刀
        _blocked_const = set(getattr(_chxp, "_EXPECTED_BLOCKED_IDS", ("058",)))
        _manual_const = set(getattr(_chxp, "_EXPECTED_MANUAL_IDS", ("021", "022", "109")))
        _hard_block: list[str] = []
        for i, item in enumerate(used, 1):
            if not isinstance(item, dict):
                continue
            mid = item.get("method_id")
            if not isinstance(mid, str):
                continue
            mid = mid.strip()
            if mid in _blocked_const or layer_of.get(mid) == "blocked_entry":
                _hard_block.append(
                    f"used[{i}] #{mid} 屬 BLOCKED 獨立入口（未走該入口不得宣稱已做）——"
                    f"不得用腳本 receipt 冒稱完成"
                )
            elif mid in _manual_const or layer_of.get(mid) == "manual":
                _hard_block.append(
                    f"used[{i}] #{mid} 屬人工清單層（系統零自動對外）——"
                    f"請改在 chxp_manual_checklist_template.md 由人簽收，不在腳本 receipt 宣稱"
                )
            elif mode_of.get(mid) == "excluded":
                _hard_block.append(
                    f"used[{i}] #{mid} 屬 excluded（正典明列「刻意不做」）——"
                    f"不納入腳本系統的條目不得在 receipt 宣稱使用"
                )
        if _hard_block:
            return "FAIL", (
                f"{fname}: C-CXP-RECEIPT FAIL — " + "；".join(_hard_block[:5])
                + (f"（另 {len(_hard_block) - 5} 項）" if len(_hard_block) > 5 else "")
                + "｜**本項單獨成立即 FAIL**，不依賴其他欄位是否合規"
                  "（身分以程式端常數為準，registry 被改也擋得住）"
            )

        # ── H2④ applicable_ids 含未知 id ＝FAIL ──
        declared = receipt.get("applicable_ids")
        drift = ""
        if declared is not None:
            if not isinstance(declared, list):
                problems.append(f"applicable_ids 型別非 list（得到 {type(declared).__name__}）")
            else:
                d = sorted({str(x).strip() for x in declared if str(x).strip()})
                unknown_decl = [x for x in d if x not in valid_ids]
                if unknown_decl:
                    problems.append(
                        f"applicable_ids 含未知 method_id {unknown_decl[:5]}（不在 registry）"
                    )
                if d != computed:
                    drift = (f"；[稿內 applicable_ids 與機器重算不符——**以機器重算為準**，"
                             f"稿內 {len(d)} 項 vs 機器 {len(computed)} 項]")

        # ── H2⑤ source_artifact_hashes / receipt_hash 欄（存在＋格式＋新鮮度）──
        sah = receipt.get("source_artifact_hashes")
        if sah is None:
            problems.append("缺 source_artifact_hashes 欄（骨架機產；沒有來源檔就填空 mapping {}）")
        elif not isinstance(sah, dict):
            problems.append(f"source_artifact_hashes 型別非 mapping（得到 {type(sah).__name__}）")
        else:
            bad_h = [f"{k}={v!r}" for k, v in sah.items()
                     if not (isinstance(v, str) and re.fullmatch(r"[0-9a-fA-F]{64}", v.strip()))]
            if bad_h:
                problems.append(f"source_artifact_hashes 值非 sha256 格式：{bad_h[:3]}")
        rh = receipt.get("receipt_hash")
        if rh is None or (isinstance(rh, str) and not rh.strip()):
            problems.append("缺 receipt_hash 欄（骨架機產；新鮮度錨，內容改了要重算）")
        elif not isinstance(rh, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", rh.strip()):
            problems.append(f"receipt_hash 非 sha256 格式（得到 {str(rh)[:24]!r}）")
        else:
            fresh = _chxp.compute_receipt_hash(data)  # type: ignore[union-attr]
            if rh.strip().lower() != fresh:
                problems.append(
                    f"receipt_hash 與本稿重算值不符（收據={rh.strip()[:12]}…，"
                    f"重算={fresh[:12]}…）——稿件改過但收據未更新＝**收據過期**"
                )

        ok_items: list[str] = []
        used_ids: set[str] = set()
        for i, item in enumerate(used, 1):
            if not isinstance(item, dict):
                problems.append(f"used[{i}] 非 mapping")
                continue
            mid = item.get("method_id")
            if not isinstance(mid, str) or not mid.strip():
                problems.append(f"used[{i}] 缺 method_id")
                continue
            mid = mid.strip()
            if mid not in valid_ids:
                problems.append(f"used[{i}] method_id={mid!r} 不在 registry（未知 ID）")
                continue
            # 註：BLOCKED／人工／excluded 身分已在上方 r4／J1 段**單因硬擋**並提前 return，
            #     跑到這裡的 mid 一定不是那三類，不需重複判定。
            ref = item.get("evidence_ref")
            resolved, why = _chxp.resolve_evidence_ref(data, ref)  # type: ignore[union-attr]
            if not resolved:
                problems.append(f"used[{i}] #{mid} 證據指標不成立：{why}")
                continue
            used_ids.add(mid)
            ok_items.append(f"#{mid}")

        # ── H2③ 11 條 always-applicable 必須在 used 出現或 waiver 交代 ──
        always_ids = _chxp.always_applicable_ids(reg)  # type: ignore[union-attr]
        waiver = receipt.get("waiver")
        waived: set[str] = set()
        if isinstance(waiver, dict):
            waived = {str(k).strip() for k, v in waiver.items() if _chxp._is_filled(v)}  # type: ignore[union-attr]
        elif isinstance(waiver, list):
            for w in waiver:
                if isinstance(w, dict):
                    wid = str(w.get("method_id", "")).strip()
                    if wid and _chxp._is_filled(w.get("reason")):  # type: ignore[union-attr]
                        waived.add(wid)
        unaccounted = [i for i in always_ids if i not in used_ids and i not in waived]
        if unaccounted:
            problems.append(
                f"{len(unaccounted)} 條 always-applicable 未交代（{unaccounted[:8]}）——"
                f"這 {len(always_ids)} 條一律適用，每條都要嘛在 used 具名＋給證據，"
                f"要嘛在 waiver 具名寫明本支為何沒用；**只驗有無申報，不判品質**"
            )

        if problems:
            return "FAIL", (
                f"{fname}: C-CXP-RECEIPT FAIL — " + "；".join(problems[:6])
                + (f"（另 {len(problems) - 6} 項）" if len(problems) > 6 else "")
                + f"｜機器重算適用 {len(computed)} 項{drift}"
            )
        _ok_body = (
            f"used {len(ok_items)} 項（{', '.join(ok_items[:8])}）"
            f"皆為合法 method_id 且證據指標可解回；{len(always_ids)} 條 always 全數交代"
            f"（used {len(used_ids & set(always_ids))}／waiver {len(waived & set(always_ids))}）；"
            f"hash 欄合法且新鮮；機器重算適用 {len(computed)} 項"
            f"（本件只驗結構，不判用得好不好）{drift}"
        )
        # ── r4／J2 WARN-grace 語意：**底層 WARN 不得被吞成 PASS** ──
        #    Codex r3 判定：合規 receipt 填 v2/previous=v1 時底層是 WARN，
        #    但 chk_cxp_receipt 只處理 FAIL，一律回 PASS。現在照實傳遞。
        if warns:
            return "WARN", (
                f"{fname}: C-CXP-RECEIPT WARN — " + "；".join(warns[:3])
                + f"｜其餘結構檢查通過：{_ok_body}"
            )
        return "PASS", f"{fname}: C-CXP-RECEIPT PASS — {_ok_body}；registry_version 與現役正典一致"
    except Exception as e:
        return "FAIL", f"{fname}: C-CXP-RECEIPT FAIL — 解析異常（{type(e).__name__}: {e}），新世代批 fail-closed"


def _chxp_gate_result(
    data: dict,
    fname: str,
    method: dict,
    enforce_generation: Optional[bool],
    is_skeleton_file: bool = False,
) -> tuple[str, str]:
    """單一 registry gate 的**泛用執行器**（規則來自 registry，程式不硬編方法內容）。

    兩段式（龍蝦嫁接件）＋r3 三態（H3）：
      第一段 trigger — MISS（沒選）→ SKIP（不適用，不當缺失）
                       MALFORMED（選型欄型別錯）→ **FAIL**（不是 SKIP）
                       HIT → 進第二段
      第二段 結構   — enum 值合法／require_fields 齊（空值／placeholder／
                      只含空元素的 list 都算沒填）／證據指標解得回／
                      （#103 這類 char_count 型）字數落在區間內
    legacy 世代 → SKIP 明標。骨架階段 → SKIP（編劇未填）。

    🔴 r3 修因（Codex 終審阻擋 3）：r1 的第一段只有 True/False 兩態，
       `used: "true"`（字串）被判「沒選」→ SKIP＝**結構性 fail-open**；
       且 `sources: [null]/[""]/["[編劇填]"]` 因 `len(v)>0` 被當有填。
       兩者都是型別與空值檢查，不涉語意品質，K0 不豁免。
    """
    gate = method.get("gate") or {}
    cid = gate.get("check_id", f"C-CXP-{method.get('id')}")
    if not enforce_generation:
        return "SKIP", f"{fname}: {cid} SKIP — {_T2_SKIP_LEGACY}"
    # ── r4／J3：**執行前先驗這條 gate 規則本身**（registry 端 schema）──
    #    Codex r3 新問題：`require_fields: []` 讓「缺段落安排的稿」照樣 gate PASS。
    #    COVERAGE 會擋住整批，但**單支檢查也不得回報 PASS**——規則壞掉時
    #    這個閘什麼都沒驗到，回 PASS 等於謊報。新世代批一律 fail-closed。
    try:
        _schema_problems = _chxp._validate_gate_schema(gate, method.get("id"))  # type: ignore[union-attr]
    except Exception:  # 防禦：舊版 chxp_registry 不吃第二個參數
        _schema_problems = []
    if _schema_problems:
        return "FAIL", (
            f"{fname}: {cid} FAIL — **registry 的本條 gate 規則不合法**："
            + "；".join(_schema_problems[:3])
            + "；規則壞掉時本閘等於什麼都沒驗，不得回報 PASS（新世代批 fail-closed）"
        )
    try:
        state, why = _chxp.gate_trigger_state(data, gate)  # type: ignore[union-attr]
        if state == "MISS":
            return "SKIP", f"{fname}: {cid} SKIP — 未選此型／不適用（{why}）"
        if state == "MALFORMED":
            if is_skeleton_file:
                return "SKIP", f"{fname}: {cid} 骨架階段跳過（title 仍為 placeholder）；填完即 fail-closed"
            return "FAIL", (
                f"{fname}: {cid} FAIL — 選型欄型別非法：{why}；"
                f"**填錯型別不等於沒選**，不得因此免驗（純型別檢查，不判內容好壞）"
            )
        if is_skeleton_file:
            return "SKIP", f"{fname}: {cid} 骨架階段跳過（title 仍為 placeholder）；填完即 fail-closed"
        # 選了但值不在 enum → 直接 FAIL（選錯型 ≠ 沒選）
        trig = gate.get("trigger") or {}
        if trig.get("kind") == "enum":
            val = _chxp.get_field(data, trig.get("field", ""))  # type: ignore[union-attr]
            allowed = trig.get("enum") or []
            if not (isinstance(val, str) and val.strip() in allowed):
                return "FAIL", (
                    f"{fname}: {cid} FAIL — {trig.get('field')} = {val!r} 不是合法選項"
                    f"（合法：{allowed}）；選型必須用 enum 值，不接受自由文字"
                )
        problems: list[str] = []
        # ── 字數型（#103）──
        if gate.get("kind") == "char_count":
            rng = gate.get("char_count") or {}
            lo, hi = rng.get("min"), rng.get("max")
            body = _chxp.script_body_text(data)  # type: ignore[union-attr]
            n = _chxp.count_chinese_chars(body)  # type: ignore[union-attr]
            if not (isinstance(lo, int) and isinstance(hi, int)):
                return "FAIL", f"{fname}: {cid} FAIL — registry char_count 區間設定非法（{rng!r}）"
            if n < lo or n > hi:
                return "FAIL", (
                    f"{fname}: {cid} FAIL — 60 秒稿本文中文字數 {n}，需 {lo}-{hi}"
                    f"（{why}）；純字數區間，不判文字品質"
                )
            return "PASS", f"{fname}: {cid} PASS — 60 秒稿本文 {n} 字，落在 {lo}-{hi}"
        # ── 必填欄位型 ──
        for fld in gate.get("require_fields") or []:
            val = _chxp.get_field(data, fld)  # type: ignore[union-attr]
            if not _chxp._is_filled(val):  # type: ignore[union-attr]
                problems.append(f"缺必填欄 {fld}（或仍是 placeholder／空值）")
        # ── 證據指標型（要在 receipt 內具名列出本條並帶可解回的 evidence_ref）──
        if gate.get("require_evidence"):
            mid = method.get("id")
            receipt = data.get("chxp_receipt")
            used = (receipt or {}).get("used") if isinstance(receipt, dict) else None
            entry = None
            if isinstance(used, list):
                for it in used:
                    if isinstance(it, dict) and str(it.get("method_id", "")).strip() == mid:
                        entry = it
                        break
            if entry is None:
                problems.append(f"選了本型卻未在 chxp_receipt.used 具名列出 #{mid}（宣告未留收據）")
            else:
                resolved, ewhy = _chxp.resolve_evidence_ref(data, entry.get("evidence_ref"))  # type: ignore[union-attr]
                if not resolved:
                    problems.append(f"#{mid} 證據指標不成立：{ewhy}")
        if problems:
            return "FAIL", (
                f"{fname}: {cid} FAIL — 已選型（{why}）但結構不成立："
                + "；".join(problems[:5])
                + "（只驗欄位與證據，不判內容好壞）"
            )
        return "PASS", f"{fname}: {cid} PASS — 已選型（{why}）且結構欄位齊、證據可解回"
    except Exception as e:
        return "FAIL", f"{fname}: {cid} FAIL — 解析異常（{type(e).__name__}: {e}），新世代批 fail-closed"


def chxp_gate_checks(
    data: dict,
    fname: str,
    enforce_generation: Optional[bool] = None,
    is_skeleton_file: bool = False,
) -> list[tuple[str, tuple[str, str]]]:
    """回傳所有 registry gate 的檢查結果 [(check_id, (status, detail)), ...]。

    🔴 註冊策略：**無條件註冊**（不論 new/legacy 都出現在報表，legacy 為 SKIP 明標）。
       理由同 T1「SKIP 要看得見才叫 grandfather」——靜默略過看不出有沒有被跳過。
    registry 不可用時：new 世代回單一 FAIL 件（不假裝八個閘都跑過），legacy 回 SKIP。
    """
    reg, err = _chxp_registry_or_error()
    if err or reg is None:
        if not enforce_generation:
            return [("C-CXP-GATES", ("SKIP", f"{fname}: C-CXP-GATES SKIP — {_T2_SKIP_LEGACY}"))]
        return [("C-CXP-GATES", ("FAIL", (
            f"{fname}: C-CXP-GATES FAIL — registry 不可用：{err}；"
            f"八個方法硬閘無從執行，新世代批 fail-closed（不得當作通過）")))]
    out: list[tuple[str, tuple[str, str]]] = []
    for m in _chxp.iter_gates(reg):  # type: ignore[union-attr]
        cid = (m.get("gate") or {}).get("check_id", f"C-CXP-{m.get('id')}")
        out.append((cid, _chxp_gate_result(data, fname, m, enforce_generation, is_skeleton_file)))
    return out


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

# C-014 retired (W2-C撤收 2026-07-14) — ID reserved, 勿重編其他 check

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

# 強制位 keyword 對應表（V2-006）— 2026-08-26 拍板（TG22396-22401）：毒舌正能量/專業位強制位廢止
# （superseded by L0 §1.1 Q1-Q8 配額制），僅存純雞湯 ≥1（CTA 維度，L0 §1.10）。工程票＝80_驗收案卷/改公版_8類型14支_20260826/
REQUIRED_SLOTS_BASE = {
    "純雞湯":       ["純雞湯"],
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


_V2007_THREADS_HEADING_RE = re.compile(
    r'^##(?!#)\s*(?:Threads|脆文)\s*(\d+).*$'
)
_V2007_H2_RE = re.compile(r'^##(?!#)')
_V2007_SUBJECT_RE = re.compile(r'^主題\s*[：:]')
_V2007_HASHTAG_ONLY_RE = re.compile(
    r'^(?:[#＃][^\s#＃]+)(?:\s+[#＃][^\s#＃]+)*$'
)


def _v2007_count_threads_sections(text: str) -> list[dict]:
    """依 D10 frozen primitive 回傳每篇 heading/section/codepoints。"""
    sections: list[dict] = []
    current: Optional[dict] = None
    normalized = text.replace('\r\n', '\n').replace('\r', '\n')
    for raw_line in normalized.split('\n'):
        heading_match = _V2007_THREADS_HEADING_RE.match(raw_line)
        if heading_match:
            if current is not None:
                sections.append(current)
            current = {
                "section": heading_match.group(1),
                "heading": raw_line,
                "codepoints": 0,
            }
            continue
        if _V2007_H2_RE.match(raw_line):
            if current is not None:
                sections.append(current)
                current = None
            continue
        if current is None:
            continue
        line = raw_line.strip()
        if not line or _V2007_SUBJECT_RE.match(line):
            continue
        if _V2007_HASHTAG_ONLY_RE.fullmatch(line):
            continue
        current["codepoints"] += len(line)
    if current is not None:
        sections.append(current)
    return sections


def _v2007_batch_date(batch_dir: Path, yamls: Optional[list] = None):
    """批次目錄名＋批內 YAML 日期欄取最大；None 由 caller 視為 enforce。"""
    dates = []
    dir_date = _parse_batch_date_str(batch_dir.name)
    if dir_date is not None:
        dates.append(dir_date)
    for f, data in yamls or []:
        if isinstance(data, dict):
            for key in ('batch_date', 'batch_tag', 'batch_label', 'generated_at', 'batch'):
                raw = data.get(key)
                parsed = _parse_batch_date_str(str(raw)) if raw else None
                if parsed is not None:
                    dates.append(parsed)
    return max(dates) if dates else None


def _v2007_select_threads_target(batch_dir: Path) -> tuple[Optional[Path], list[Path]]:
    """沿用 V2-007 既有 glob 與 v2/mtime precedence，回傳 selected target。"""
    candidates = []
    for pattern in ['*Threads*.md', '*脆文*.md', 'threads_*.md']:
        candidates.extend(batch_dir.glob(pattern))
    candidates = sorted(set(candidates))
    if not candidates:
        return None, candidates
    target = sorted(
        candidates,
        key=lambda p: ('v2' in p.name, p.stat().st_mtime),
        reverse=True,
    )[0]
    return target, candidates


def chk_v2_007_threads_seven(
    batch_dir: Path,
    yamls: Optional[list] = None,
) -> tuple[str, str]:
    """V2-007：Threads 篇數＋每篇正文 Unicode code points hard gate。"""
    spec = _load_l0_batch_spec()
    sources = _load_l0_batch_spec_sources()
    expected = int(spec["threads_posts"])
    limit = int(spec["threads_max_codepoints"])
    cutover_raw = str(spec["threads_length_effective_from"])
    limit_source = sources.get("threads_max_codepoints", "unknown")
    cutover_source = sources.get("threads_length_effective_from", "unknown")
    policy = (
        f"limit={limit}(source={limit_source}); "
        f"cutover={cutover_raw}(source={cutover_source})"
    )
    try:
        cutover = _cta_dt.date.fromisoformat(cutover_raw)
    except (TypeError, ValueError):
        return "FAIL", f"V2-007 設定錯誤：cutover 非 ISO date；{policy}"

    batch_date = _v2007_batch_date(batch_dir, yamls)
    legacy = batch_date is not None and batch_date < cutover
    generation = "legacy" if legacy else "enforce"
    date_detail = batch_date.isoformat() if batch_date is not None else "unknown"
    context = f"{policy}; batch_date={date_detail}; generation={generation}"

    target, candidates = _v2007_select_threads_target(batch_dir)
    if target is None:
        return "FAIL", (
            "批次目錄找不到 Threads 脆文檔"
            "（Glob: *Threads*.md / *脆文*.md / threads_*.md）；"
            f"{context}"
        )
    try:
        text = target.read_text(encoding='utf-8-sig')
    except Exception as e:
        return "FAIL", f"讀 {target.name} 失敗：{e}；{context}"

    sections = _v2007_count_threads_sections(text)
    count = len(sections)
    counts = ", ".join(
        f"{section['section']}:{section['codepoints']}" for section in sections
    )
    violations = [section for section in sections if section["codepoints"] > limit]
    violation_detail = ", ".join(
        f"{target.name}#Threads {section['section']}={section['codepoints']}>{limit}"
        for section in violations
    )

    if count < expected:
        extra = f"；另有超標：{violation_detail}" if violations else ""
        return "FAIL", (
            f"{target.name} 只找到 {count} 篇脆文（要 ≥ {expected}）{extra}；"
            f"counts=[{counts}]；{context}"
        )
    if violations and not legacy:
        return "FAIL", (
            f"Threads 正文超標：{violation_detail}；counts=[{counts}]；{context}"
        )
    if violations:
        return "WARN", (
            f"legacy Threads 正文超標：{violation_detail}；counts=[{counts}]；{context}"
        )
    return "PASS", (
        f"{target.name} 找到 {count} 篇脆文（≥ {expected}），"
        f"逐篇均 ≤ {limit}；counts=[{counts}]；{context}"
    )


def _v2008_dialogue_text(data: dict) -> str:
    """V2-008 v2 helper：腳本全文台詞串接（拍板 2026-06-11：雷同判定只看台詞內容）"""
    parts = []
    for scene in get_scenes(data):
        parts.extend(_get_all_dialogue(scene))
    return "".join(str(p) for p in parts)


def _v2008_content_dup_hits(cur: list, others: list, threshold: float = 0.85) -> list:
    """V2-008 v2 helper：全文雷同互比（長度差 >30% 預過濾省時）。cur/others = [(label, text)]"""
    hits = []
    for i, (la, ta) in enumerate(cur):
        if not ta:
            continue
        for lb, tb in list(cur[i + 1:]) + list(others):
            if not tb:
                continue
            if min(len(ta), len(tb)) / max(len(ta), len(tb), 1) < 0.7:
                continue
            r = difflib.SequenceMatcher(None, ta, tb).ratio()
            if r >= threshold:
                hits.append((la, lb, round(r, 2)))
    return hits


_V2008_EMPTY_SENTINEL = "（空白 — 第一批生產後開始填）"
_V2008_DASH_TITLE_RE = re.compile(r'^-\s*#?\d*\s*\[[^\]]+\]\s*(.+?)$')
_V2008_NUMBERED_TITLE_RE = re.compile(r'^\s*(\d+)\s*[.．]\s+(.+?)\s*$')
_V2008_BATCH_HEADING_RE = re.compile(
    r'^(?:初始\s*批|第\s*(?:[0-9０-９]+|[〇零一二三四五六七八九十百兩]+)\s*批).*$'
)
_V2008_NON_DATA_BATCH_MENTION_RE = re.compile(r'^(?:待確認事項|下批可寫題材)(?:\s|[（(]|$)')
_V2008_APPROVED_TABLE_SCHEMAS = {
    ('#', 'script_id', '題目', '類型', '派系'),
    ('#', '標題', '核心切角', '戲路', '備註'),
    ('#', '標題', '派系', '備註'),
}


def _v2008_split_md_table_row(line: str) -> Optional[list[str]]:
    """切 markdown table row；只把未 escape 的 pipe 當 delimiter。"""
    stripped = line.strip()
    if not (stripped.startswith('|') and stripped.endswith('|')):
        return None
    cells: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in stripped[1:-1]:
        if escaped:
            if ch == '|':
                buf.append('|')
            else:
                buf.extend(('\\', ch))
            escaped = False
        elif ch == '\\':
            escaped = True
        elif ch == '|':
            cells.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if escaped:
        buf.append('\\')
    cells.append(''.join(buf).strip())
    return cells


def _v2008_is_table_separator(cells: Optional[list[str]], width: int) -> bool:
    return bool(
        cells is not None
        and len(cells) == width
        and all(re.fullmatch(r':?-{3,}:?', cell) for cell in cells)
    )


def _v2008_clean_numbered_title(raw_title: str) -> tuple[str, Optional[str]]:
    """換題行只收新題；精確移除換題 audit suffix，不碰一般內容括號。"""
    title = raw_title.strip()
    if title.startswith('~~'):
        if title.count('→') != 1:
            return '', 'malformed_replacement'
        replacement = re.fullmatch(r'~~(.+?)~~\s*→\s*(.+)', title)
        if not replacement:
            return '', 'malformed_replacement'
        title = replacement.group(2).strip()
        title = re.sub(
            r'\s*[（(]\s*\d{4}-\d{2}-\d{2}[^）)]*換題\s*[）)].*$',
            '',
            title,
        ).strip()
    else:
        title = re.sub(
            r'\s*\[(?:R\d+\s*換題[:：]|原\s*R\d+[^\]]*已廢棄)[^\]]*\]\s*$',
            '',
            title,
        ).strip()
    if not title:
        return '', 'empty_title'
    return title, None


def _v2008_parse_used_titles(raw_text: str) -> dict:
    """解析 raw 已用題目 canonical；grammar 以批次 section 為隔離單位。"""
    lines = raw_text.splitlines()
    section_by_line: list[Optional[str]] = []
    section_lines: dict[str, int] = {}
    h2_batch: Optional[str] = None
    h3_batch: Optional[str] = None
    suspected_h2: Optional[tuple[int, str]] = None
    suspected_h3: Optional[tuple[int, str]] = None
    suspected_by_line: list[Optional[tuple[int, str]]] = []
    suspected_immediate: set[tuple[int, str]] = set()

    for line_no, line in enumerate(lines, 1):
        heading = re.match(r'^(#{2,3})\s*(.*?)\s*$', line.strip())
        if heading:
            level = len(heading.group(1))
            heading_text = heading.group(2)
            is_batch = bool(_V2008_BATCH_HEADING_RE.match(heading_text))
            if level == 2:
                h2_batch = f"L{line_no}:{heading_text}" if is_batch else None
                h3_batch = None
                suspected_h2 = (line_no, heading_text) if not is_batch and '批' in heading_text else None
                if suspected_h2 and not _V2008_NON_DATA_BATCH_MENTION_RE.match(heading_text):
                    suspected_immediate.add(suspected_h2)
                suspected_h3 = None
                if h2_batch:
                    section_lines[h2_batch] = line_no
            else:
                h3_batch = f"L{line_no}:{heading_text}" if is_batch else None
                suspected_h3 = (line_no, heading_text) if not is_batch and '批' in heading_text else None
                if suspected_h3 and not _V2008_NON_DATA_BATCH_MENTION_RE.match(heading_text):
                    suspected_immediate.add(suspected_h3)
                if h3_batch:
                    section_lines[h3_batch] = line_no
        suspected = suspected_h3 or suspected_h2
        suspected_by_line.append(suspected)
        section_by_line.append(None if suspected else (h3_batch or h2_batch))

    titles: list[str] = []
    rejected_rows: list[dict] = []
    table_schemas: list[str] = []
    formats_by_section: dict[str, set[str]] = {}
    candidate_rows = 0
    candidate_rows_anywhere = 0
    suspected_rejected: set[tuple[int, str]] = set()

    for line in lines:
        stripped = line.strip()
        table_cells = _v2008_split_md_table_row(line)
        table_title_columns = (
            [cell for cell in table_cells if cell in {'題目', '標題'}]
            if table_cells is not None and table_cells and table_cells[0] == '#'
            else []
        )
        if (
            _V2008_DASH_TITLE_RE.match(stripped)
            or re.match(r'^-\s*#?\d*\s*\[', stripped)
            or _V2008_NUMBERED_TITLE_RE.match(stripped)
            or re.match(r'^\s*\d+\s*[.．]', stripped)
            or table_title_columns
        ):
            candidate_rows_anywhere += 1

    def add_format(section: str, grammar: str) -> None:
        formats_by_section.setdefault(section, set()).add(grammar)

    def reject(line_no: int, reason: str, section: Optional[str] = None) -> None:
        rejected_rows.append({"line": line_no, "reason": reason, "section": section})

    for suspected in sorted(suspected_immediate):
        if suspected not in suspected_rejected:
            reject(suspected[0], 'suspected_batch_header', None)
            suspected_rejected.add(suspected)

    i = 0
    while i < len(lines):
        line_no = i + 1
        stripped = lines[i].strip()
        section = section_by_line[i]
        suspected = suspected_by_line[i]
        table_cells = _v2008_split_md_table_row(lines[i])
        title_columns = (
            [n for n, cell in enumerate(table_cells) if cell in {'題目', '標題'}]
            if table_cells is not None and table_cells and table_cells[0] == '#'
            else []
        )
        dash_candidate = bool(
            _V2008_DASH_TITLE_RE.match(stripped)
            or re.match(r'^-\s*#?\d*\s*\[', stripped)
        )
        numbered_candidate = bool(
            _V2008_NUMBERED_TITLE_RE.match(stripped)
            or re.match(r'^\s*\d+\s*[.．]', stripped)
        )

        if suspected is not None and (title_columns or dash_candidate or numbered_candidate):
            candidate_rows += 1
            if suspected not in suspected_rejected:
                reject(suspected[0], 'suspected_batch_header', None)
                suspected_rejected.add(suspected)
            i += 1
            continue

        if table_cells is not None and table_cells and table_cells[0] == '#':
            if not title_columns:
                i += 1
                continue
            if section is None:
                candidate_rows += 1
                reject(line_no, 'title_table_outside_batch', None)
                i += 1
                continue
            if len(title_columns) != 1:
                candidate_rows += 1
                reject(line_no, 'unsupported_title_table_schema', section)
                i += 1
                continue

            add_format(section, 'table')
            candidate_rows += 1
            title_index = title_columns[0]
            schema = '|'.join(table_cells)
            separator = _v2008_split_md_table_row(lines[i + 1]) if i + 1 < len(lines) else None
            if not _v2008_is_table_separator(separator, len(table_cells)):
                reject(line_no, 'table_missing_or_bad_separator', section)
                i += 1
                continue
            if tuple(table_cells) not in _V2008_APPROVED_TABLE_SCHEMAS:
                reject(line_no, 'unapproved_title_table', section)
                i += 1
                continue

            table_schemas.append(schema)
            data_rows = 0
            j = i + 2
            while j < len(lines):
                data_cells = _v2008_split_md_table_row(lines[j])
                if data_cells is None:
                    break
                data_line_no = j + 1
                candidate_rows += 1
                if len(data_cells) != len(table_cells):
                    reject(data_line_no, 'table_column_count_mismatch', section)
                elif not re.fullmatch(r'\d+', data_cells[0]):
                    reject(data_line_no, 'table_row_number_not_decimal', section)
                elif not data_cells[title_index].strip():
                    reject(data_line_no, 'empty_title', section)
                else:
                    titles.append(data_cells[title_index].strip())
                    data_rows += 1
                j += 1
            if data_rows == 0:
                reject(line_no, 'title_table_has_no_data_rows', section)
            i = j
            continue

        if section is not None:
            dash = _V2008_DASH_TITLE_RE.match(stripped)
            if dash:
                add_format(section, 'dash-bracket')
                candidate_rows += 1
                titles.append(dash.group(1).strip())
                i += 1
                continue
            if re.match(r'^-\s*#?\d*\s*\[', stripped):
                add_format(section, 'dash-bracket')
                candidate_rows += 1
                reject(line_no, 'malformed_dash_bracket', section)
                i += 1
                continue

            numbered = _V2008_NUMBERED_TITLE_RE.match(stripped)
            if numbered:
                add_format(section, 'numbered-plain')
                candidate_rows += 1
                title, error = _v2008_clean_numbered_title(numbered.group(2))
                if error:
                    reject(line_no, error, section)
                else:
                    titles.append(title)
                i += 1
                continue
            if re.match(r'^\s*\d+\s*[.．]', stripped):
                add_format(section, 'numbered-plain')
                candidate_rows += 1
                reject(line_no, 'malformed_numbered_title', section)
                i += 1
                continue
        i += 1

    for section, grammars in formats_by_section.items():
        if len(grammars) > 1:
            reject(section_lines.get(section, 1), 'mixed_grammars_in_batch', section)

    sentinel_lines = [
        line_no for line_no, line in enumerate(lines, 1)
        if line.strip() == _V2008_EMPTY_SENTINEL
    ]
    empty_template = False
    if sentinel_lines:
        if len(sentinel_lines) == 1 and not titles and candidate_rows_anywhere == 0 and not rejected_rows:
            empty_template = True
        else:
            reject(sentinel_lines[0], 'stale_or_ambiguous_empty_sentinel', None)

    if not titles and not empty_template:
        reject(1, 'empty_without_sentinel' if not raw_text.strip() else 'nonempty_zero_titles', None)

    section_formats = {
        section: sorted(grammars)
        for section, grammars in formats_by_section.items()
    }
    all_formats = sorted({grammar for grammars in formats_by_section.values() for grammar in grammars})
    if empty_template:
        parser_format = 'explicit-empty'
    elif not all_formats:
        parser_format = 'invalid'
    elif len(all_formats) == 1:
        parser_format = all_formats[0]
    else:
        parser_format = 'multi-section'
    return {
        "titles": titles,
        "format": parser_format,
        "parsed_rows": len(titles),
        "rejected_rows": rejected_rows,
        "empty_template": empty_template,
        "table_schemas": table_schemas,
        "formats_by_section": section_formats,
        "candidate_rows": candidate_rows,
        "candidate_rows_anywhere": candidate_rows_anywhere,
    }


def _v2008_canonical_display(path: Path) -> str:
    """canonical provenance 採 project-root-relative；外部 fixture 只留穩定 basename。"""
    project_root = Path(__file__).resolve().parents[3]
    try:
        return path.resolve().relative_to(project_root).as_posix()
    except (OSError, ValueError):
        return f"<external>/{path.name}"


def _v2008_load_used_titles(owner: str) -> dict:
    """由唯一 canonical raw 載入題目；owner unresolved 僅明示 skip，不造假 0 撞。"""
    try:
        pref_path = OWNER_PREF_PATHS.get(owner)
    except Exception as exc:
        return {
            "titles": [], "format": "unavailable", "parsed_rows": 0,
            "rejected_rows": [{"line": 0, "reason": f"owner_mapping_error:{type(exc).__name__}", "section": None}],
            "empty_template": False, "table_schemas": [], "formats_by_section": {},
            "candidate_rows": 0, "canonical": "unresolved", "owner_unresolved": False,
        }
    if pref_path is None:
        return {
            "titles": [], "format": "skipped", "parsed_rows": None,
            "rejected_rows": [], "empty_template": False, "table_schemas": [],
            "formats_by_section": {}, "candidate_rows": 0, "canonical": "unresolved",
            "owner_unresolved": True,
        }

    used_titles_path = pref_path.parent / f"_{owner}已用題目.md"
    canonical = _v2008_canonical_display(used_titles_path)
    if not used_titles_path.exists():
        return {
            "titles": [], "format": "unavailable", "parsed_rows": 0,
            "rejected_rows": [{"line": 0, "reason": "canonical_missing", "section": None}],
            "empty_template": False, "table_schemas": [], "formats_by_section": {},
            "candidate_rows": 0, "canonical": canonical, "owner_unresolved": False,
        }
    try:
        used_text = used_titles_path.read_text(encoding='utf-8')
    except Exception as exc:
        return {
            "titles": [], "format": "unavailable", "parsed_rows": 0,
            "rejected_rows": [{"line": 0, "reason": f"canonical_unreadable:{type(exc).__name__}", "section": None}],
            "empty_template": False, "table_schemas": [], "formats_by_section": {},
            "candidate_rows": 0, "canonical": canonical, "owner_unresolved": False,
        }
    result = _v2008_parse_used_titles(used_text)
    result["canonical"] = canonical
    result["owner_unresolved"] = False
    return result


def _v2008_parser_detail(result: dict) -> str:
    if result.get("owner_unresolved"):
        return "title_arm=skipped(owner_unresolved); parsed=NA"
    formats = result.get("formats_by_section") or {}
    formats_text = ','.join(
        f"{section}={'+'.join(grammars)}" for section, grammars in formats.items()
    ) or '-'
    return (
        f"canonical={result.get('canonical', 'unknown')};parser={result.get('format', 'invalid')};"
        f"parsed={result.get('parsed_rows', 0)};rejected={len(result.get('rejected_rows', []))};"
        f"empty_template={str(bool(result.get('empty_template'))).lower()};"
        f"formats_by_section={formats_text}"
    )


def chk_v2_008_used_titles_dedup(yamls: list[tuple[Path, dict]], owner: str) -> tuple[str, str]:
    """V2-008 v2（2026-06-11 澤君拍板 TG 9755：同題開放——可以講一樣的東西，但腳本全文內容不得雷同）
    A) 標題 fuzzy ≥0.65 對已用題目 → WARN（原 FAIL 降級；同題請換切角/講法；canonical=raw `_<業主>已用題目.md`、W2-D22——derived 附錄退出讀取契約）
    B) 全文台詞雷同 ratio ≥0.85 → FAIL：批內互比 + 對全業主歷史批次 script_*.yaml 互比
       （跨業主複製同樣禁止 — 保鏢 R1-hard 2026-06-11；排除當前批次目錄防自比假炸；
        歷史單檔讀取失敗跳過 fail-open、真雷同 fail-closed）
    """
    valid = [(f, d) for f, d in yamls if "__parse_error__" not in d and "__schema_error__" not in d]
    # ── A) 標題同題 → WARN ──
    title_hits = []
    title_parse = _v2008_load_used_titles(owner)
    used_titles = list(title_parse.get("titles", []))
    parser_rejected = title_parse.get("rejected_rows", [])
    parser_fault = bool(parser_rejected) and not title_parse.get("owner_unresolved")
    parser_detail = _v2008_parser_detail(title_parse)
    THRESHOLD_TITLE = 0.65
    for f, data in valid:
        title = str(data.get('title', '')).strip()
        if not title:
            continue
        for used in used_titles:
            ratio = difflib.SequenceMatcher(None, title, used).ratio()
            if ratio >= THRESHOLD_TITLE:
                title_hits.append((f.name, title, used, round(ratio, 2)))
                break
    # ── B) 全文台詞雷同 → FAIL ──
    cur = [(f.name, _v2008_dialogue_text(d)) for f, d in valid]
    others = []
    try:
        cur_dir = valid[0][0].parent.resolve() if valid else None
        if cur_dir is not None:
            l2_root = None
            for p in cur_dir.parents:
                if p.name == "L2_業主層":
                    l2_root = p
                    break
            if l2_root is not None:
                for pat in ("*/01_腳本生產/*/script_*.yaml", "*/01_腳本批次/*/script_*.yaml"):
                    for hist in l2_root.glob(pat):
                        try:
                            if hist.parent.resolve() == cur_dir:
                                continue  # 排除當前批次自比（防重驗已上線批假炸）
                            # 批次 yaml 為 frontmatter 多段格式（--- 分隔）— 照主 loader 同法取 frontmatter 段
                            _raw = hist.read_text(encoding='utf-8', errors='replace')
                            _txt = re.sub(r"^---\s*\n", "", _raw, count=1)
                            _fm = re.split(r"\n---\s*\n", _txt, maxsplit=1)[0]
                            _fm = re.sub(r"\n---\s*$", "", _fm)
                            hd = yaml.safe_load(_fm)
                            if isinstance(hd, dict):
                                others.append((f"{hist.parent.parent.parent.name}/{hist.parent.name}/{hist.name}", _v2008_dialogue_text(hd)))
                        except Exception:
                            continue  # 單檔壞掉跳過（fail-open 於 IO）
    except Exception:
        pass
    dup_hits = _v2008_content_dup_hits(cur, others, 0.85)
    if dup_hits:
        a, b, r = dup_hits[0]
        detail = f"{len(dup_hits)} 對全文台詞雷同（ratio ≥ 0.85；2026-06-11 拍板：同題可、全文雷同禁）：{a} vs {b} ratio={r}；{parser_detail}"
        if parser_fault:
            first_fault = parser_rejected[0]
            detail += f"；parser-integrity FAIL: L{first_fault.get('line')} {first_fault.get('reason')}"
        return "FAIL", detail
    if parser_fault:
        first_fault = parser_rejected[0]
        return "FAIL", (
            f"已用題目 parser-integrity FAIL: L{first_fault.get('line')} {first_fault.get('reason')}；"
            f"{parser_detail}；全文對批內+歷史 {len(others)} 支 0 雷同"
        )
    if title_parse.get("owner_unresolved"):
        return "PASS", f"{parser_detail}；全文對批內+歷史 {len(others)} 支 0 雷同（content-dup ≥0.85 擋）"
    if title_hits:
        first = title_hits[0]
        return "WARN", f"{len(title_hits)} 件標題同題（fuzzy ≥ {THRESHOLD_TITLE}；2026-06-11 拍板開放同題——請確認已換切角/講法）：{first[0]} '{first[1][:30]}' vs 已用 '{first[2][:30]}' ratio={first[3]}；{parser_detail}；全文對歷史 {len(others)} 支 0 雷同"
    if title_parse.get("empty_template"):
        return "PASS", f"已用題目明示空殼；{parser_detail}；全文對批內+歷史 {len(others)} 支 0 雷同（content-dup ≥0.85 擋）"
    return "PASS", f"已用題目 {len(used_titles)} 條標題 0 撞；{parser_detail}；全文對批內+歷史 {len(others)} 支 0 雷同（content-dup ≥0.85 擋；同題開放 2026-06-11 拍板）"


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


def chk_v2_012b_threads_med_words(batch_dir: Path, owner: str) -> tuple[str, str]:
    """V2-012B：美容業主獨立脆文（threads md）醫療效能禁用詞驗 — batch-level。

    背景：V2-012（per-file）只掃 yaml 台詞；昀臻14批脆文 04「發炎」機器綠燈、算盤人工抓到（P0）。
    → 擴掃批次目錄的獨立脆文 md（threads_*.md / *脆文*.md / *Threads*.md）。
    純加嚴：新增一道掃描，不放寬任何既有檢查。掃「全部」候選脆文檔（非只最新），任一命中即 FAIL。
    """
    BEAUTY_OWNERS = {'昀臻', '溫蒂'}
    if owner not in BEAUTY_OWNERS:
        return "PASS", "(非美容業主，跳過)"
    candidates = []
    for pattern in ['threads_*.md', '*脆文*.md', '*Threads*.md']:
        candidates.extend(batch_dir.glob(pattern))
    candidates = sorted(set(candidates))
    if not candidates:
        return "WARN", f"{owner}：批次目錄找不到 threads/脆文 md 可掃醫療詞（V2-007 另驗存在性）"
    all_hits = []
    scanned = []
    for md in candidates:
        try:
            text = md.read_text(encoding='utf-8')
        except Exception as e:
            return "FAIL", f"{owner} 讀脆文 {md.name} 失敗：{e}（fail-closed）"
        scanned.append(md.name)
        hits = sorted({w for w in BEAUTY_MED_WORDS if w in text})
        if hits:
            all_hits.append((md.name, hits))
    if all_hits:
        detail = "; ".join(f"{n} 含 {h[:5]}" for n, h in all_hits)
        return "FAIL", f"{owner}脆文含醫療效能禁用詞（對齊第 09 批算盤 20 條）：{detail}"
    return "PASS", f"{owner}脆文醫療詞驗 PASS（掃 {len(scanned)} 檔：{scanned}）"


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

    Codex R2 P0.2 修（2026-06-24）：C-cta-mix scoping —
    - hybrid 批（任何稿有 content_axis 欄位）只驗 content_axis=="professional" 的稿
    - content_axis∈{offpro,personal_anchor} 排除（脫鉤業主本業成交配比）
    - legacy 批（無 content_axis 欄位的稿）行為完全不變
    """
    if not _MIX_PARSER_OK or _parse_mix_block is None:
        return "WARN", "C-cta-mix：_mix_parser 不可用，CTA 比例驗證跳過"

    # Codex R2 P0.2：hybrid 批 scoping — 只驗 professional 稿，排除 offpro/personal_anchor
    # 放在 pref_text check 之前：offpro-only 批直接 PASS N/A，不需要讀偏好.md
    _OFFPRO_AXES = {"offpro", "personal_anchor"}
    _has_hybrid = any(
        isinstance(d, dict) and str(d.get("content_axis", "") or "").strip()
        for _, d in yamls
    )
    if _has_hybrid:
        yamls_for_mix = [
            (f, d) for f, d in yamls
            if not (isinstance(d, dict) and str(d.get("content_axis", "") or "").strip().lower() in _OFFPRO_AXES)
        ]
        if not yamls_for_mix:
            return "PASS", "C-cta-mix：hybrid 批無 professional 稿，CTA mix 驗證 N/A（off-pro 脫鉤）"
        # hybrid 批 professional 子集太小（< 5）→ cta_mix 配比無意義，降 WARN-surface
        if len(yamls_for_mix) < 5:
            return "WARN", (
                f"C-cta-mix：hybrid 批 professional 子集僅 {len(yamls_for_mix)} 支（< 5），"
                f"業主 cta_mix 配比以全批 13 支為基準、不適用於 professional 子集 → WARN-surface"
            )
        yamls = yamls_for_mix

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

# ════════════════════════════════════════════
# §21 腳本品質公式 check 常數（2026-06-17 機器化 §21 落地）
# 對齊 scripter.md §21 v1.2（§21.1 破套路 / §21.2 CTA 多樣 / §21.6 整稿閘報告 / §21.7 誠實天花板）
# ════════════════════════════════════════════
# 生效日 = 上線日 2026-06-17 + 7 天 WARN 窗（涵蓋 shadow 觀察期）：
#   batch_date < _S21_EFFECTIVE_FROM  → §21 全部 check 回 WARN-waiver（不 FAIL）
#   batch_date >= 該日 且非 legacy    → C-21.1 / C-21.2 / C-21.7 走 FAIL 路徑
# C-21.6 另受 _S21_6_REPORT_ENFORCE 控（見下）；2026-06-23 已翻 True（enforce）。
_S21_EFFECTIVE_FROM = _dt.date(2026, 6, 24)

# C-21.6 整稿閘報告存在性。2026-06-23 enforce DONE（澤君拍「直接上線」、霸告翻 True）。
# 高規格批附 _quality_gate_report.md / 一般批標 quality_gate.exempt（見下值行 + runbook §8）。
_S21_6_REPORT_ENFORCE = True  # 6/24 enforce flip（霸告 2026-06-23，澤君拍「直接上線」；高規格批附 _quality_gate_report.md、一般批 _batch_flags.yml 標 quality_gate.exempt）

# C-21.1 破套路門檻：一批 N 支裡 >= 此數同一 exact 骨架型 → 觸發
# （計算口徑 Codex 三審 P1-1 釘死：13 支 ≥7 同 exact 骨架才「改」）
_S21_1_SAME_SKELETON_THRESHOLD = 7

# C-21.2 CTA 真多樣門檻（Codex 三審 P2-1）：
#   一批至少 _S21_2_MIN_DISTINCT 種不同 cta_effect，
#   單一最大類別 <= _S21_2_MAX_SINGLE / 13。
_S21_2_MIN_DISTINCT = 3
_S21_2_MAX_SINGLE = 6

# ════════════════════════════════════════════
# §22 選題公式 check 常數（2026-06-17 機器化 §22 落地）
# 對齊 scripter.md §22（§22.4 一般化偵測 7 訊號可機械子集）
# ════════════════════════════════════════════
# 生效日 = 上線日 2026-06-17 + 7 天 WARN 窗（與 §21 同步、涵蓋 shadow 觀察期）。
# 誠實定位（照計劃 + §22.4）：C-22 仍「只擋低級空泛、不判好題」——
#   2026-06-23 翻 enforce（FAIL）後語義級「好不好」仍留 GPT/真人（proof_removed_judge advisory）。
# _S22_EFFECTIVE_FROM 為「過渡窗」標示。
_S22_EFFECTIVE_FROM = _dt.date(2026, 6, 24)
# C-22 enforce 開關：2026-06-23 翻 True（澤君拍「直接上線」、14 真實批零誤擋、batch-ratio 0.9 backstop 保好批）。
_S22_ENFORCE = True  # 6/24 enforce flip（霸告 2026-06-23；14 真實批 enforce-sim 零誤擋、batch-ratio 0.9 backstop 保護口語故事批）
# C-22b anchor_first 機械閘 enforce 開關：2026-06-23 翻 True（只對 proof_mode=anchor_first 稿觸發、現生產 0 支）。
# anchor_first 三必填（anchor_ref / anchor_cost / because_bridge）缺任一 → 現 FAIL。
ANCHOR_FIRST_ENFORCE = True  # 6/24 enforce flip（霸告 2026-06-23；只對 proof_mode=anchor_first 稿觸發、現生產 0 支、零誤擋）
# C-offpro-placeholder：台詞占位符守門。2026-06-23 翻 True（off-pro 稿→FAIL、本業稿→WARN，見值行）。
_OFFPRO_PLACEHOLDER_ENFORCE = True  # 6/24 enforce flip（霸告 2026-06-23；全稿偵測占位符，off-pro 稿→FAIL、本業稿→WARN〔避 FP：本業批偶帶 [需確認] 待補，瑞祥36×4〕；Codex R1 P0-2 修）
# C-offpro-leak：off-pro 立場 lane 本業詞守門。2026-06-23 翻 True（§8#8 硬化後，見值行）。
_OFFPRO_LEAK_ENFORCE = True  # 6/24 enforce flip（霸告 2026-06-23；§8#8 掃全 publish 欄+去混淆硬化後翻，保鏢 condition 已補）
_HYBRID_PLAN_LOCK_ENFORCE = True
_HYBRID_METHOD_ENFORCE = True
_HYBRID_FRIEND_CLOSE_ENFORCE = True
_HYBRID_PROFESSIONAL_ENFORCE = True
# K11（2026-07-16）：professional lane proof_mode 誤填觀察態旗標。False＝WARN 觀察
# （chk_hybrid_plan_lock prof_signals 合流／chk_d20_proof_mode_enum LANE_MISMATCH）；
# 存量 WARN 實跑證據落檔後翻 True（另令）。
_D20_PROFESSIONAL_LANE_ENFORCE = True
_TASTE_PANEL_ENFORCE = True
# TEXT_CEILING ACK（澤君 2026-06-24 拍板啟用）：純文字稿（true_material_source=="none" AND
# score_type∈{"script","angle"}）若 5 維全≥80 但有維度 <90 → TEXT_CEILING WARN（非 FAIL）。
# 任一維 <80 或 generic 退件 → 仍 hard FAIL（不放水）。
# 關閉：_TEXT_CEILING_ACK_ENABLE = False
_TEXT_CEILING_ACK_ENABLE: bool = True
_TEXT_CEILING_FLOOR: int = 80  # 純文字稿黃燈門檻；低於此值仍 FAIL
# C-22-OFFPRO-ANGLE：off-pro 寫稿前角度守門（2026-06-24 建，Phase 0 shadow）。
# 投影 §22.3/22.4/22.9/22.9.1 反一般化欄位，只對 off-pro 立場稿跑。
# Codex R1 P0-5 修（2026-06-24）：由單一 bool 改為「依錯誤碼分級」，空集合=Phase 0 全 WARN。
# Phase 2 集合={001,002,004,007,009,011,012,014}；Phase 3 集合={001-014 全部} — 由澤君拍板啟用。
# 006 NO_BEHAVIOR_DELTA 永遠 WARN（不受此集合影響）。
_C22_OFFPRO_ANGLE_ENFORCE_CODES: set[str] = set()  # 空=Phase 0 全 shadow WARN；澤君拍板加碼
# 向後相容：_C22_OFFPRO_ANGLE_ENFORCE 保留為唯讀屬性供舊單元測試參照（等效 bool(集合非空)）
_C22_OFFPRO_ANGLE_ENFORCE: bool = bool(_C22_OFFPRO_ANGLE_ENFORCE_CODES)
# C-22 一般化偵測門檻：一支題目「非一般訊號」數 < 此數 → 偏一般（WARN）。
# 2026-06-17 P1 調 3→2（御史/算盤/Codex 一致退回）：
#   原 3 對「口語第一人稱故事題」太苛——這類好題（如「我打電話，偷偷希望對方不接」）
#   天然只有 1 個第一人稱訊號、不堆數字/地名/代價詞，永遠湊不到 3 → 好批 100% 誤 WARN、無鑑別力。
#   降到 2 後：「第一人稱 + 1 個其他訊號」即達標（瑞祥38 好批偏一般率 100%→62%）；
#   而真空泛題（買房要注意什麼/房貸怎麼選 …）多數 0 訊號，MIN=2 下仍 100% 偏一般 → 仍正確 WARN。
#   ⚠️ 誠實邊界：規則對「純口語故事題」的 recall 有天花板（楷甯首批極致口語故事 MIN=2 仍 85% 偏一般），
#      靠搭配 batch ratio=0.9 才讓楷甯批次層 PASS；真正「題目好不好」語義級判斷留 GPT/真人，
#      C-22 只擋「整批低級空泛、幾乎零訊號」那種。
_S22_MIN_SIGNALS = 2

# === Codex 第 2 輪 precision 修（2026-06-17）：達標須「total >= MIN 且 hard >= 1」 ===
# P1 為救 recall 把 first_person 詞庫 13→41 + 門檻 3→2，但 precision 變沒牙：弱詞可湊數繞過。
#   繞過例：「客戶問我，房貸怎麼選」= ③客戶(身份) + ⑦問我(倒裝第一人稱) = 2 訊號 → 誤判不一般。
#   根因 1：純弱訊號（身份泛詞 / 時效 / 弱第一人稱）湊到 2 就清關，但這類是「泛 FAQ 殼」非業主真經歷。
#   根因 2：`客戶` 在 identity 詞庫(③) + `客戶問我` 又算第一人稱(⑦) → 同一句雙計分。
# 修法（Codex 指定）：
#   (a) 訊號分 hard / weak 兩類；單題達標改 `total >= _S22_MIN_SIGNALS 且 hard_count >= 1`。
#       hard = 具體數字 / 地名在地 / 反直覺 / 受眾真代價 / 強第一人稱經歷 / 綁業主名。
#       weak = 純身份泛詞(客戶/客人/上班族…) / 時效 / 弱第一人稱(我跟/我看/問我/找我…)。
#   (b) first_person 拆強/弱兩庫（見 _s22_count_signals）；弱第一人稱只算 weak。
#   (c) 防 `客戶問我` 雙計分：身份詞 ③ 與弱第一人稱 ⑦ 都是 weak，且 _s22_count_signals 以
#       hits dict 去重（同一語義訊號只算一格），純弱訊號湊不出 hard。
_S22_MIN_HARD_SIGNALS = 1
# 批次第二層 backstop：若「裸偏一般 + 只靠弱訊號過關（達標但 hard=0... 但達標規則已要求 hard>=1，
#   故此處實指：表面達標靠 weak 為主、hard 僅 1）」的題占比 >= 此比例 → 仍 WARN（即使表面 distinct 夠）。
# 對齊 Codex 指定修法第 3 條：防「整批套弱訊號殼 → 表面 PASS」。
#   定義「弱過關題」＝該支達標(total>=MIN 且 hard>=1)但 weak_count > hard_count（靠弱訊號撐多樣）。
#   若 (偏一般 + 弱過關) 占比 >= 此值 → WARN。
_S22_BATCH_WEAK_PASS_RATIO = 0.9
# 一批「偏一般」支數 >= 此比例（向上取整）才把 batch 判 WARN（單支偶發不擾民）。
# 2026-06-17 P2-a 調 0.5→0.9（御史/Codex 建議的治標，搭配 MIN=2；實測敏感度後選 0.9 不選 0.8）：
#   敏感度實測（MIN=2 固定，三批偏一般率）：
#     瑞祥38(好) 62%｜楷甯01(好) 85%｜空泛批(該WARN) 100%
#     ratio=0.8 → 瑞祥PASS / 楷甯誤WARN / 空泛WARN
#     ratio=0.9 → 瑞祥PASS / 楷甯PASS / 空泛WARN  ← 採此：兩好批都救回、空泛批仍正確擋住
#     ratio=1.0 → 太鬆（整批全偏一般才 WARN，一支漏網就放行）→ 不採
#   0.9 = 九成以上題目偏一般才提醒。好批裡只要 ≥10% 題目規則抓到 ≥2 訊號就放行；
#   全空泛批（100% 偏一般）仍穩穩 >= 90% → 正確 WARN。鑑別力：好批 PASS、真垃圾 WARN。
#   ⚠️ 誠實邊界：WARN 是「規則層提醒」不是「題目判死」，規則對口語故事題 recall 有上限，
#      真正「題目好不好」的語義判斷靠 GPT/真人；C-22 只擋「整批低級空泛、幾乎零訊號」那種。
_S22_BATCH_WARN_RATIO = 0.9

# §22.4 一般化偵測 7 訊號的「可機械子集」（純 regex/詞庫，不碰 LLM）。
# 計「非一般訊號」數：命中越多 = 越不一般。<_S22_MIN_SIGNALS → 偏一般。
# 訊號方向：①具體數字 ②地名/在地 ③身份描述 ④時效 ⑤反直覺 ⑥受眾真代價 ⑦綁業主/第一人稱經歷
#   （§22.4 原文訊號①「去掉業主名還成立」是反向＝一般；此處轉成正向「有綁業主/第一人稱」計分）

# ① 具體數字（阿拉伯/全形數字 或 中文數字+業務量詞）
_S22_NUM_RE = re.compile(r"[0-9０-９]|[一二三四五六七八九十百千兩]+\s*[年月天週次組件成倍折坪萬元位個人房樓家口口]")
# ② 地名 / 在地詞（高雄常見行政區 + 在地泛詞）
_S22_PLACE_WORDS = [
    "高雄", "台南", "臺南", "台北", "臺北", "台中", "臺中", "新北", "桃園", "屏東", "嘉義",
    "左營", "鳳山", "三民", "苓雅", "前鎮", "楠梓", "鼓山", "前金", "鹽埕", "新興", "小港",
    "岡山", "橋頭", "仁武", "鳥松", "大社", "美術館", "巨蛋", "亞灣", "農16", "農十六",
    "在地", "本地", "這一區", "這區", "我們這邊", "這附近",
]
# ③ 身份描述詞（存款X萬 / 剛XX的人 / 做X年 / 第一次 …，靠句型詞）
_S22_IDENTITY_WORDS = [
    "存款", "月薪", "年薪", "首購", "第一次", "剛出社會", "剛結婚", "新婚", "新手",
    "單親", "退休", "斜槓", "上班族", "小資", "夫妻", "自營", "創業", "換屋", "包租",
    "做了", "入行", "從業", "經手", "服務過", "帶看過", "客人", "客戶",
]
# ④ 時效詞（本月 / 本週 / 今年 / 最近 / 剛 / 2026 …）
_S22_TIME_WORDS = [
    "本月", "這個月", "本週", "這週", "今年", "去年", "最近", "近期", "上個月", "上週",
    "剛剛", "今天", "昨天", "現在", "目前", "當前", "2025", "2026", "下半年", "上半年",
    "升息", "降息", "新制", "新規", "新政策", "剛上路", "剛公布",
]
# ⑤ 反直覺詞（其實 / 沒人告訴你 / 大家都說…但 / 我犯過的錯 / 不是…而是 …）
_S22_COUNTER_WORDS = [
    "其實", "沒人告訴你", "沒人會說", "大家都說", "大家以為", "你以為", "別再", "別以為",
    "不是", "而是", "真相", "誤會", "誤解", "搞錯", "我犯過", "踩過的雷", "踩過坑",
    "顛覆", "反過來", "錯了", "迷思", "騙局", "盲點",
]
# ⑥ 受眾真代價詞（多賠 / 少付 / 被坑 / 後悔 / 錯過 / 多花 …）
_S22_COST_WORDS = [
    "多賠", "少賺", "少付", "多付", "多花", "白花", "被坑", "被騙", "後悔", "錯過",
    "踩雷", "吃虧", "賠", "虧", "省下", "省了", "多繳", "白做", "白買", "買貴", "賣便宜",
    "損失", "代價", "風險", "陷阱",
]


# C-21.2 P2-B（Codex 第 2 輪退回修；Codex 第 3 輪 P1 放寬到剛好）：
# validator 自有的 CTA「效果」canonical 詞彙。
# 對齊 scripter.md §21.2 line 572（個人化諮詢 / 互動問句留言回答 / 分享引導 / 無強CTA）
# + L0 §1.10 CTA 類型表（個人化諮詢型 / 招生課程 / 純雞湯無CTA）。
# 用途：計 distinct 多樣性前，把逐支 CTA 標籤 canonical 化；**無法解析到 canonical 的標籤
# 不計入多樣性 + 出 WARN 列出**（防 garbage 標籤 foo×5/bar×4/baz×4 灌水充多樣）。
# 機制（與 L2 cta_mix alias 互補）：先試 L2 cta_mix items（_resolve_label），再試本表；
# 兩者皆 None → unresolvable（不計 + WARN）。
# key = canonical 效果名，value = 該效果的 alias 字面（含 L0/L2 常見寫法）。
#
# === Codex 第 3 輪 P1 修正（2026-06-17） ===
# 問題：上輪 P2-B canonical 表只認 5 bucket、漏掉大量**真實在用**的合法 CTA 標籤
#   （釣魚型 / 私訊型 / 私域引流型 / 追蹤型 / 收藏型 / 二選一互動型 / 留言互動型 …），
#   且不認帶括號變體（釣魚型（…）），導致合法批被誤 FAIL。
# 修法：① grep 全 7 業主真實 schema_check.CTA類型 值 + L2 cta_mix aliases + 骨架機推薦，
#   EXHAUSTIVE 補全成可解析；② 加括號正規化（剝 （...）/(...)後比 base 標籤），
#   讓「釣魚型（留言「幕後」…）」歸到「釣魚型」。
# 不回退 garbage filter：foo/bar/baz 等真正解析不到任何 base 標籤的仍 None（不計 + WARN）。
_S21_CTA_EFFECT_CANONICAL: dict[str, list[str]] = {
    # 個人化諮詢（私訊我幫你看一下 / 一對一）
    "個人化諮詢": [
        "個人化諮詢型", "個人化諮詢", "諮詢型", "個人諮詢", "私訊諮詢", "一對一諮詢",
        "雙身份CTA", "引留言", "引分享",
    ],
    # 互動問句（留言互動 / 二選一 / 軟互動）
    "互動問句": [
        "互動留言型", "互動問句", "互動型", "留言互動", "留言互動型", "留言回答",
        "提問互動", "二選一互動型", "互動留言",
    ],
    # 分享引導（轉發 / tag / 收藏）
    "分享引導": [
        "分享引導型", "分享引導", "分享型", "轉發引導", "tag引導", "標記引導", "收藏型",
    ],
    # 追蹤引導（請追蹤 / 限動追蹤）
    "追蹤引導": [
        "追蹤型", "追蹤引導", "追蹤引導型", "請追蹤",
    ],
    # 釣魚（留言關鍵字 → 私訊解答圖卡 / 私訊引流 / 私域引流）
    "釣魚引流": [
        "釣魚型", "釣魚部", "私訊型", "私訊引流型", "私域引流型", "私訊引流", "私域引流",
    ],
    # 招生課程（B2B / +1 型）
    "招生課程": [
        "招生型", "招生課程", "課程型", "報名引導", "B2B招生", "B2B招生型",
        "招生課程B2B", "+1型",
    ],
    # 無強 CTA（純雞湯 / 語錄金句 / 故事支）
    "無強CTA": [
        "無強CTA", "無強 CTA", "無CTA", "純雞湯", "純雞湯無CTA", "雞湯型",
        "故事支", "語錄金句", "無", "無（純雞湯強制）",
    ],
}


def _s21_strip_paren_suffix(s: str) -> str:
    """剝掉標籤尾端的括號註解，回 base 標籤。
    支援全形（…）與半形(...)，剝完再 strip。
    e.g. 「釣魚型（留言「幕後」→ 私訊解答圖卡）」 → 「釣魚型」；
         「純雞湯（無CTA）」 → 「純雞湯」；「追蹤型（IG 限動）」 → 「追蹤型」。
    無括號則原樣回傳。只剝第一個出現的開括號之後全部（含巢狀，因 base 標籤一律在最前）。
    """
    if not s:
        return s
    # 找最早出現的全形「（」或半形「(」，從那裡截斷
    idx_full = s.find("（")
    idx_half = s.find("(")
    idxs = [i for i in (idx_full, idx_half) if i >= 0]
    if not idxs:
        return s.strip()
    cut = min(idxs)
    return s[:cut].strip()


def _s21_canonical_cta_effect(raw_label: str) -> Optional[str]:
    """C-21.2 P2-B / Codex 第 3 輪 P1：把單一 CTA 標籤對應到 validator 自有 canonical 效果名；
    無法解析回 None。
    比對順序：① 精確比對 canonical name 與 alias（strip 後）→ ② 剝括號取 base 標籤再比對一次。
    第 2 步讓「釣魚型（…）」「純雞湯（無CTA）」等帶註解的合法標籤歸到對應 base，
    同時 garbage（foo/bar/baz，剝括號後仍不在表）仍回 None（不放水）。
    """
    s = (raw_label or "").strip()
    if not s:
        return None

    def _lookup(token: str) -> Optional[str]:
        for canon, aliases in _S21_CTA_EFFECT_CANONICAL.items():
            if token == canon or token in aliases:
                return canon
        return None

    # ① 原樣比對
    hit = _lookup(s)
    if hit is not None:
        return hit
    # ② 剝括號後比 base 標籤（避免帶註解變體解析不到）
    base = _s21_strip_paren_suffix(s)
    if base and base != s:
        hit = _lookup(base)
        if hit is not None:
            return hit
    return None


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


def _rcard_all_dates_max(data: dict, fname: str = '') -> Optional[_dt.date]:
    """R-CARD-001 專用日期判別（修訂⑪·r7-B1）：對每個候選字串窮舉**所有**日期取全域最大。

    與 _extract_batch_date 差異：後者每字串只取第一個日期（.search），多日期字串
    （如「…2026-07-13_rev2026-07-14…」）會漏掉較新日期 — r7 攻角實證繞過案例。
    V2-025 沿用 _extract_batch_date 舊行為不受影響（變更面隔離）。
    已知邊界（誠實揭露）：日期仍為 yaml/路徑自報值＝防呆非防偽；不可變 legacy
    清單防偽版列 W3。
    """
    RE_SEP = re.compile(r'(\d{4})[-/_ ](\d{2})[-/_ ](\d{2})')
    RE_COMPACT = re.compile(r'(?<!\d)(\d{4})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)')
    candidates: list[_dt.date] = []
    sources = [data.get(k) for k in ('batch_date', 'batch_tag', 'batch_label', 'generated_at', 'batch')]
    if fname:
        sources.append(fname)
    for val in sources:
        if not val:
            continue
        s = str(val)
        for m in RE_SEP.finditer(s):
            try:
                candidates.append(_dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            except ValueError:
                pass
        for m in RE_COMPACT.finditer(s):
            try:
                candidates.append(_dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            except ValueError:
                pass
    return max(candidates) if candidates else None


_R_CARD_001_EFFECTIVE_FROM = _dt.date(2026, 7, 14)
_R_CARD_001_RETIRED_FIELDS = ("圖卡主題", "visual_aid", "visual_aid_scripts")


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
        # R3 Fix 4（2026-06-24）：改用 _is_placeholder 統一判定（含 [填：…] 格式）
        # _is_placeholder 定義在下方，_is_skeleton_mode 呼叫時 _is_placeholder 已被 Python 載入（同模組）
        if not title.strip() or _is_placeholder(title):
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

    Codex 第 3 輪 P2（2026-06-17）防呆：骨架機未引號的 `title: [編劇填]` 會被 YAML 解析成
    list ['編劇填']（骨架機 line 222/224 現有引號，本支為手寫/舊骨架雙保險）。
    一般 str(["編劇填"]) = "['編劇填']" 首 token 非 '[編劇填]' → 過去誤判「已填」。
    修法（對齊 _s21_get_skeleton_type 對 pattern 的 list 處理）：list 型值 →
    任一元素本身判定為 placeholder（含「編劇填」字樣）即視為 placeholder。
    """
    if val is None:
        return True
    # list 型（YAML 把未引號 [編劇填] 解析成 list）：任一元素是 placeholder → True
    if isinstance(val, list):
        if not val:
            return True
        for elem in val:
            es = str(elem).strip()
            if not es:
                continue
            etoken = re.split(r'[\s#]', es)[0].lower()
            if etoken in ('[編劇填]', '編劇填', 'pending', 'todo', '待填'):
                return True
        return False
    s = str(val).strip()
    if not s:
        return True
    # 取 comment 前的有效部份（以 '#' 或空白分割取第一段）
    token = re.split(r'[\s#]', s)[0].lower()
    if token in ('[編劇填]', 'pending', 'todo', '待填'):
        return True
    # Codex R2 P0.1（2026-06-24）：skeleton 產出的中括號佔位格式，例如 [填：...] / [填:...] / [完稿後填]
    # 只要字串以 [填 開頭（全型冒號/半型冒號/空白/右括號任何跟隨）→ placeholder
    if re.match(r'^\[填', s):
        return True
    return False


# ────────────────────────────────────────────
# WP-B V3-001 provenance check（topic_intel 選題情報池來源驗）
# ────────────────────────────────────────────

def _normalize_and_tokenize(text: str) -> set:
    """
    正規化 + 分詞 → token set（供 shared_content_tokens 計算）。

    正規化順序（規格 §9.2）：
    1. Unicode NFKC
    2. 英文轉小寫
    3. 全形→半形（由 NFKC 完成）
    4. 移除 URL
    5. 移除所有標點 / 符號 / emoji
    6. 阿拉伯數字保留；百分號移除但數字保留
    7. 空白壓成單一空白
    8. 中文連續字串切 2-gram + 3-gram
    9. 英文 / 數字連續字串切 word token
    10. 移除 STOPLIST
    11. token 去重（回 set）
    """
    import unicodedata
    import re as _re

    # 1+2+3: NFKC + lower（全形半形由 NFKC 完成）
    s = unicodedata.normalize("NFKC", text).lower()

    # 4: 移除 URL
    s = _re.sub(r"https?://\S+|www\.\S+", " ", s)

    # 5+6: 移除標點/符號/emoji，保留中文、英數、空白
    # 百分號移除（符號類），但數字已保留（先移標點後才動數字）
    # 用 category：保留 letter / number，其餘移除（含 emoji）
    def _keep_char(c: str) -> str:
        cat = unicodedata.category(c)
        if cat.startswith("L"):   # Letter
            return c
        if cat.startswith("N"):   # Number
            return c
        if c in " \t\n":          # 空白
            return " "
        return " "                # 標點/符號/emoji → 空格

    s = "".join(_keep_char(c) for c in s)

    # 7: 空白壓成單一
    s = _re.sub(r"\s+", " ", s).strip()

    # 切分 token
    tokens: set = set()

    # 逐段掃：連續中文 vs 其他（英數）
    segments = _re.split(r"(\s+)", s)
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        # 判斷是否純中文
        cjk_chars = [c for c in seg if "一" <= c <= "鿿"]
        non_cjk = [c for c in seg if c not in cjk_chars and c.strip()]

        if cjk_chars:
            # 8: 中文 2-gram + 3-gram
            cjk_str = "".join(cjk_chars)
            for n in (2, 3):
                for i in range(len(cjk_str) - n + 1):
                    tokens.add(cjk_str[i:i+n])

        if non_cjk:
            # 9: 英數 word token（連續非空白字元）
            for word in _re.findall(r"[a-z0-9]+", seg):
                tokens.add(word)

    # 10: 移除 STOPLIST
    try:
        from topic_intel_adapter import STOPLIST as _STOPLIST
    except ImportError:
        _STOPLIST = set()
    tokens -= _STOPLIST

    return tokens


def _count_chinese_chars(text: str) -> int:
    """計算字串中的中文字數（Unicode CJK 基本漢字區塊）"""
    return sum(1 for c in text if "一" <= c <= "鿿")


def _extract_script_body_text(data: dict) -> str:
    """
    從 yaml data 提取比對用文字：title + Hook 段台詞 + 第 2-5 段主體台詞。
    台詞欄位名由業主偏好決定（常見：台詞/口白/旁白/文案），此處直接掃 scenes 所有字串值。
    """
    parts = []

    # title
    title = str(data.get("title", "") or "")
    if title:
        parts.append(title)

    # scenes
    scenes = data.get("scenes") or []
    if not isinstance(scenes, list):
        scenes = []

    seg_idx = 0
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        seg_idx += 1
        seg_type = str(scene.get("type", "") or "").strip()
        # 取 Hook 段 + 第 2-5 段主體
        is_hook = (seg_type == "Hook" or seg_idx == 1)
        is_body = (2 <= seg_idx <= 5)
        if not (is_hook or is_body):
            continue
        # 掃所有字串值欄位（台詞欄位名不固定）
        for k, v in scene.items():
            if k in ("timestamp", "type") or not isinstance(v, str):
                continue
            v_stripped = v.strip()
            if v_stripped and not v_stripped.startswith("#") and not _is_placeholder(v_stripped):
                parts.append(v_stripped)

    return " ".join(parts)


def _load_projection_candidate_index(owner: str) -> Optional[dict]:
    """
    Fix G：載入 owner 對應的 projection active.json，
    回傳 {topic_id: source_sha256} 索引（用於 provenance 比對）。
    檔不存在回 None（首批 / 尚未生成 projection）。
    解析失敗 raise（呼叫端捕捉後記 WARN）。
    """
    import json as _j
    _op_path = Path(__file__).resolve().parent / "owner_projection.generated.json"
    if not _op_path.exists():
        return None
    _op = _j.loads(_op_path.read_text(encoding="utf-8"))
    _owner_info = _op.get("owners", {}).get(owner, {})
    _owner_code = str(_owner_info.get("owner_code", "") or "")
    if not _owner_code:
        return None
    _cfg_path = Path(r"/Users/chenzejun/claude-state/topic_intel_paths.json")
    if not _cfg_path.exists():
        return None
    _cfg = _j.loads(_cfg_path.read_text(encoding="utf-8"))
    _proj_dir = _cfg.get("topic_intel_projection_dir", "")
    if not _proj_dir:
        return None
    _active = Path(_proj_dir) / "by_owner" / _owner_code / "active.json"
    if not _active.exists():
        return None
    _proj_data = _j.loads(_active.read_text(encoding="utf-8"))
    return {
        str(c.get("topic_id", "")): str(c.get("source_sha256", ""))
        for c in _proj_data.get("candidates", [])
        if c.get("topic_id")
    }


# ── AI 語意閘（R5-3b）v2 ──────────────────────────────────────────────────────
# Gemini Flash 做題目同一性 shadow 判定（§22.9：只比題目，不比角度）
# env flag: TOPIC_INTEL_AI_GATE=1 才真打 API；預設 skip（不污染、不擋批）
# 呼叫法對齊 vision_judge.py（google-genai SDK）
# v2 硬化：timeout / confidence 門檻 / 巢狀 JSON / few-shot / 2-judge / 厚 evidence / full cache key

_AI_GATE_MODEL = "gemini-2.5-flash"          # 預設模型（2.0-flash free tier 429；2.5-flash 有配額）
_AI_GATE_PROMPT_VERSION = "v2"               # 改 prompt 時 bump → 舊 cache 自動失效
_AI_GATE_TIMEOUT_SEC = 15                    # 硬化 1：per-call timeout（秒）
_AI_GATE_CONF_THRESHOLD = 85                 # 硬化 2：different_topic 需 >= 此信心才 flag

_TOPIC_INTEL_AI_GATE_CACHE: dict = {}  # 跨呼叫同 process 快取 {cache_key: result_dict}

# 硬化 4：few-shot + 2 鐵律。主要 judge prompt。
_TOPIC_INTEL_AI_GATE_PROMPT_TEMPLATE = """\
你是短影音「題目同一性」審核員。

【§22.9 設計約束 — 鐵律不可修改】
1. 腳本本來就該有自己的角度；same_topic_new_angle = 合格放行。
2. 只有當腳本講的是「根本不同的題目/核心痛點」才回 different_topic。
3. 只比「題目同一性」，絕對不比「角度一致性」。

【鐵律 A】same_topic_new_angle 與 different_topic 之間不確定 -> 一律選 same_topic_new_angle。
【鐵律 B】只有 evidence 痛點與腳本痛點「互不相關」才回 different_topic。

【few-shot 範例】
---
範例 1（同題新角度 -> same_topic_new_angle）
evidence：買房頭期款存不到，年輕人月薪三萬怎麼存？
腳本：你知道為什麼有人月薪三萬能買房、有人月薪六萬還在租屋？三個理財習慣的差距。
verdict: {{"verdict":"same_topic_new_angle","reason":"同樣買房存款痛點，切入習慣新角度","confidence":90}}
---
範例 2（同題不同用詞 -> same_topic）
evidence：殺價議價率 Top10，桃園大園 22.5%
腳本：跟建商談房價，這三句話能讓你多省 10%。
verdict: {{"verdict":"same_topic","reason":"同樣是與建商談價的痛點","confidence":95}}
---
範例 3（根本不同題 -> different_topic）
evidence：殺價議價率 Top10，桃園大園 22.5%
腳本：帶你看台南最新個案，三房兩廳採光超好。
verdict: {{"verdict":"different_topic","reason":"議價率 vs 個案介紹，痛點互不相關","confidence":93}}
---
範例 4（evidence 不足 -> insufficient_evidence）
evidence：（標題為空，逐字稿為空）
腳本：今天講預售屋陷阱。
verdict: {{"verdict":"insufficient_evidence","reason":"evidence 無可比較文字","confidence":80}}
---

【evidence（爆款出處摘要）】
{evidence_text}

【腳本 body（前段，用於題目判斷）】
{script_body}

請判斷：腳本的核心題目/痛點 與 evidence 的核心題目/痛點 是否為同一件事。

回 JSON（只回 JSON，不加說明）：
{{
  "verdict": "same_topic" | "same_topic_new_angle" | "different_topic" | "insufficient_evidence",
  "reason": "<20字以內說明，聚焦題目差異，不提角度>",
  "confidence": <int, 0-100>
}}
"""

# 硬化 5：第 2 個 judge（更寬鬆版本，用於 2-judge 共識）
_TOPIC_INTEL_AI_GATE_PROMPT_LENIENT = """\
你是短影音「題目同一性」審核員。你的職責是保護腳本不被誤判。

【鐵律（不可修改）】
- same_topic_new_angle = 合格放行；腳本換角度是正常的。
- 只有 evidence 核心痛點 與 腳本核心痛點「根本不同、互不相關」才回 different_topic。
- 不確定時 -> 選 same_topic_new_angle（保護腳本不被誤殺）。
- 只比「是否同一個問題/痛點」，絕對不比角度一致性。

【evidence（爆款出處）】
{evidence_text}

【腳本 body】
{script_body}

回 JSON：
{{
  "verdict": "same_topic" | "same_topic_new_angle" | "different_topic" | "insufficient_evidence",
  "reason": "<15字>",
  "confidence": <0-100>
}}
"""


def _genai_client_factory(api_key: str):
    """
    Gemini client 工廠（獨立函數讓測試可 mock patch）。
    對齊 vision_judge.py 的 google-genai SDK 呼叫法。
    """
    from google import genai as _genai  # noqa: F401
    return _genai.Client(api_key=api_key)


def _extract_verdict_from_parsed(parsed: object) -> str:
    """硬化 3：Robust verdict 抽取（向後相容：只回 verdict 字串）。
    內部委託 _extract_fields_from_parsed，確保 verdict 和 confidence 從同一層抽。
    """
    return _extract_fields_from_parsed(parsed).get("verdict", "insufficient_evidence")


def _extract_fields_from_parsed(parsed: object) -> dict:
    """硬化 3 defect-2 fix：從巢狀 JSON 同層一次抽出 verdict + confidence + reason。

    舊寫法：_extract_verdict_from_parsed 只抽 verdict，confidence 在 _single_judge_call
    讀 top-level parsed.get("confidence")。巢狀 {{"result":{{"verdict":"different_topic",
    "confidence":92}}}} → verdict 抽到但 confidence 讀 top-level=None=0 → 被誤降級。
    修：verdict/confidence/reason 從同一個子 dict 一起抽。
    """
    _VALID = ("same_topic", "same_topic_new_angle", "different_topic", "insufficient_evidence")

    def _from_dict(d: dict):
        v = str(d.get("verdict", ""))
        if v in _VALID:
            c_raw = d.get("confidence")
            return {
                "verdict": v,
                "confidence": int(c_raw) if c_raw is not None else 0,
                "reason": str(d.get("reason", "")),
            }
        return None

    if not isinstance(parsed, dict):
        return {}
    # top-level 優先
    r = _from_dict(parsed)
    if r:
        return r
    # known nested keys
    for key in ("result", "output", "response", "data", "answer", "classification"):
        nested = parsed.get(key)
        if isinstance(nested, dict):
            r = _from_dict(nested)
            if r:
                return r
    # 任意巢狀
    for v in parsed.values():
        if isinstance(v, dict):
            r = _from_dict(v)
            if r:
                return r
    return {}


def _parse_ai_gate_response(text: str) -> dict:
    """硬化 3：Robust JSON 解析，支援 markdown fence / 巢狀 / 文字夾 JSON。"""
    import json as _j
    import re as _re
    text = text.strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = _re.sub(r"^```(?:json)?\s*", "", text)
        text = _re.sub(r"\s*```$", "", text)
        text = text.strip()
    try:
        parsed = _j.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except _j.JSONDecodeError:
        pass
    match = _re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            parsed = _j.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except _j.JSONDecodeError:
            pass
    return {}


def _single_judge_call(client, prompt: str, timeout_sec: int) -> dict:
    """硬化 1：帶 timeout 的單次 Gemini 呼叫，逾時或例外 -> api_unavailable。
    使用 daemon=True thread + queue.Queue，逾時後立即回傳，背景 thread 在進程退出時
    自動清除，不會因 shutdown(wait=False) 累積卡著的背景 thread（defect 3 緩解）。
    """
    import threading as _threading
    import queue as _queue

    _rq: _queue.Queue = _queue.Queue(maxsize=1)

    def _do_call():
        try:
            from google.genai import types as _gtypes
            resp = client.models.generate_content(
                model=_AI_GATE_MODEL,
                contents=[prompt],
                config=_gtypes.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            _rq.put(("ok", resp.text or ""))
        except Exception as _e:
            _rq.put(("err", str(_e)))

    _t = _threading.Thread(target=_do_call, daemon=True)
    _t.start()
    try:
        status, val = _rq.get(timeout=timeout_sec)
    except _queue.Empty:
        return {"verdict": "api_unavailable", "note": f"Gemini 呼叫逾時（>{timeout_sec}s）"}

    if status == "err":
        return {"verdict": "api_unavailable", "note": f"API 呼叫失敗：{val}"}

    raw_text = val
    parsed = _parse_ai_gate_response(raw_text)
    if not parsed:
        return {"verdict": "api_unavailable", "note": f"Gemini 回傳無法解析：{raw_text[:100]}"}

    # defect 2 fix：用 _extract_fields_from_parsed 從同層一次抽 verdict+confidence+reason
    fields = _extract_fields_from_parsed(parsed)
    if not fields:
        return {"verdict": "insufficient_evidence",
                "reason": "無法從回應抽出有效 verdict", "confidence": 0}
    return fields


def _consensus_verdict(judge_results: list) -> dict:
    """
    硬化 5 defect-1 fix：2-judge 共識，§22.9 最寬鬆者勝。

    舊邏輯：valid = [過濾 api_unavailable]，再判 all(valid==different_topic) → flag。
    缺陷：judge1=api_unavailable + judge2=different_topic → valid=[judge2] → 單 judge 就 flag，
    違反「只有兩個 judge 各自真的回了 verdict 且皆 different_topic」的要求。

    新邏輯（priority 順序）：
    1. 任一 judge 說 same_topic / same_topic_new_angle → 放行
    2. 任一 judge 是 api_unavailable / insufficient_evidence → 降 insufficient_evidence（不 flag）
       （不確定性傳染：一個 judge 不確定 = 整體不確定）
    3. 全部 judge 均回 different_topic → avg_conf → 交給 caller 做 conf 門檻判定
    4. 其他混合 → insufficient_evidence
    """
    if not judge_results:
        return {"verdict": "api_unavailable", "note": "無 judge 結果"}

    # Step 1：任一放行 → 放行（最高優先，§22.9 最寬鬆者勝）
    _PASS = ("same_topic", "same_topic_new_angle")
    for r in judge_results:
        if r.get("verdict") in _PASS:
            return r

    # Step 2：任一不可用/不確定 → 降 insufficient_evidence（不 flag）
    _UNCERTAIN = ("api_unavailable", "insufficient_evidence")
    for r in judge_results:
        if r.get("verdict") in _UNCERTAIN:
            note = r.get("note") or r.get("reason") or "judge 不可用或不確定"
            return {"verdict": "insufficient_evidence",
                    "reason": f"某 judge 不可用或不確定（{note}），採寬鬆判定（§22.9）",
                    "confidence": 0}

    # Step 3：全部 judge 均確認 different_topic → 計 avg_conf 交 caller 處理
    if all(r.get("verdict") == "different_topic" for r in judge_results):
        confs = [r.get("confidence", 0) for r in judge_results]
        avg_conf = int(sum(confs) / len(confs)) if confs else 0
        return dict(judge_results[0], confidence=avg_conf)

    # Step 4：其他混合
    return {"verdict": "insufficient_evidence", "reason": "judges 不一致，採寬鬆判定", "confidence": 0}


def _call_topic_intel_ai_gate(
    evidence_text: str,
    script_body: str,
    cache_key: str,
) -> dict:
    """
    2-judge Gemini Flash 題目同一性判斷。

    回傳 {"verdict": str, "reason": str, "confidence": int}
    API 不可用/逾時/回傳爛 -> {"verdict": "api_unavailable", "note": str}

    硬化清單：
    - 硬化 1: per-call timeout
    - 硬化 2: different_topic 需 confidence >= _AI_GATE_CONF_THRESHOLD
    - 硬化 3: robust nested/non-JSON parsing
    - 硬化 4: few-shot prompt + 2 鐵律
    - 硬化 5: 2-judge consensus（§22.9 最寬鬆者勝）
    caller 只需拿 verdict 決定是否 shadow_warn（never crash、never block batch）。
    """
    import os as _os_ag

    if cache_key in _TOPIC_INTEL_AI_GATE_CACHE:
        return _TOPIC_INTEL_AI_GATE_CACHE[cache_key]

    api_key = _os_ag.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        result = {"verdict": "api_unavailable", "note": "GOOGLE_API_KEY 未設"}
        _TOPIC_INTEL_AI_GATE_CACHE[cache_key] = result
        return result

    try:
        _client = _genai_client_factory(api_key)
    except ImportError:
        result = {"verdict": "api_unavailable", "note": "google-genai 未安裝（pip install google-genai）"}
        _TOPIC_INTEL_AI_GATE_CACHE[cache_key] = result
        return result

    ev_text = evidence_text[:1500].strip() or "（無 evidence 文字）"
    sc_text = script_body[:1500].strip() or "（無腳本文字）"

    # 硬化 5：2 judges（primary few-shot + lenient）
    _p1 = _TOPIC_INTEL_AI_GATE_PROMPT_TEMPLATE.format(evidence_text=ev_text, script_body=sc_text)
    _p2 = _TOPIC_INTEL_AI_GATE_PROMPT_LENIENT.format(evidence_text=ev_text, script_body=sc_text)

    judge1 = _single_judge_call(_client, _p1, _AI_GATE_TIMEOUT_SEC)
    judge2 = _single_judge_call(_client, _p2, _AI_GATE_TIMEOUT_SEC)

    result = _consensus_verdict([judge1, judge2])

    # 硬化 2：different_topic 需信心 >= 門檻，否則降為 insufficient_evidence
    if result.get("verdict") == "different_topic":
        conf = result.get("confidence", 0)
        if conf < _AI_GATE_CONF_THRESHOLD:
            result = dict(result, verdict="insufficient_evidence",
                          reason=f"confidence={conf} < {_AI_GATE_CONF_THRESHOLD}，採寬鬆判定")

    _TOPIC_INTEL_AI_GATE_CACHE[cache_key] = result
    return result
# ── AI 語意閘 v2 end ──────────────────────────────────────────────────────────


def chk_topic_intel_provenance(
    data: dict,
    fname: str,
    topic_intel_policy: dict,
    is_skeleton: bool,
    owner: str = "",
) -> tuple[str, str]:
    """
    V3-001：選題情報池來源驗（WP-B provenance check）—— per-file 層。

    驗欄位：
      1. evidence_sha256 非空。
      2. Fix G：evidence_path 非空（assign 端必填 canonical path）。
      3. adopted_topic_statement 中文字數 >= 12。
      4. shared_content_tokens >= 5（adopted_topic_statement ↔ 腳本台詞）。
      5. Fix G：topic_id + evidence_sha256 在 owner projection cache 中命中（防假 id）。

    policy disabled / off → SKIP（零足跡）。
    is_skeleton=True → SKIP。
    shadow=WARN / enforce=FAIL。
    """
    mode = topic_intel_policy.get("mode", "off") if topic_intel_policy else "off"
    enabled = topic_intel_policy.get("enabled", False) if topic_intel_policy else False

    if not enabled:
        return "SKIP", f"V3-001 WP-B policy off/disabled（{mode}），跳過 provenance check"

    if is_skeleton:
        return "SKIP", "V3-001 骨架階段跳過（adopted_topic_statement 尚未填，等編劇填完後再驗）"

    sti = data.get("source_topic_intel")
    if not sti or not isinstance(sti, dict):
        return "SKIP", "V3-001 此腳本無 source_topic_intel（未被 WP-B assign 綁 slot）"

    issues = []
    is_fail = False
    shadow_warns: list = []  # R5 新增補強項（一律 shadow WARN，不升 enforce）

    # 1. evidence_sha256 非空
    sha = str(sti.get("evidence_sha256", "") or "").strip()
    if not sha:
        issues.append("evidence_sha256 為空")
        is_fail = True

    # 2. Fix G：evidence_path 非空
    ev_path = str(sti.get("evidence_path", "") or "").strip()
    if not ev_path:
        issues.append("evidence_path 為空（assign 端必填 canonical resolved path）")
        is_fail = True

    # R5-2：真指紋 — evidence_path 檔案存在 + 重算 sha256 比對（shadow WARN）
    # （不升 enforce；檔不存在或 sha 不符 → 只 WARN，讓批次繼續但留警示）
    if ev_path:
        try:
            _ev_file = Path(ev_path)
            if not _ev_file.exists():
                shadow_warns.append(
                    f"evidence_path 指向的檔案不存在（{ev_path!r}）"
                )
            else:
                # 修 11：全檔 sha — 對齊 gen_topic_intel_projection.py 全檔 sha256（cap 只用於文本解析）
                # 修 8：一次 read 拆兩用，避免雙次 IO
                _ev_bytes_full = _ev_file.read_bytes()
                _EV_TEXT_CAP = 1_048_576  # 僅文本解析（YAML parse）cap 防大檔 OOM，不影響 sha
                _ev_bytes = _ev_bytes_full[:_EV_TEXT_CAP]
                if sha:
                    _recomputed_sha = hashlib.sha256(_ev_bytes_full).hexdigest()  # 全檔 sha（修 11）
                    if _recomputed_sha != sha:
                        shadow_warns.append(
                            f"evidence_path 重算 sha256 不符 evidence_sha256"
                            f"（檔={_recomputed_sha[:8]}…, 記錄={sha[:8]}…，指紋失真）"
                        )

                # R5-3：真比對 — 腳本 ↔ evidence 題目同一性（§22.9：只驗題目，絕不限角度）
                # evidence 訊號：title + transcript_preview + dissect.hook_structure.first_3_sec_text
                # 修 8：加 hook_structure 補弱訊號（adapter 允許無 transcript 但有 hook_struct 的候選）
                # 修 9：shadow 啟發式偵測，寬鬆門檻有誤判空間（§22.9 角度自由）
                try:
                    import re as _re_ev
                    import yaml as _yaml_ev
                    _ev_raw = _ev_bytes.decode("utf-8", errors="replace")
                    _ev_raw = _re_ev.sub(r"^---\s*\n", "", _ev_raw, count=1)
                    _ev_raw = _re_ev.sub(r"\n---\s*$", "", _ev_raw)
                    _ev_data = _yaml_ev.safe_load(_ev_raw) or {}
                    _ev_title = str(_ev_data.get("title", "") or "")
                    _ev_transcript = str(_ev_data.get("transcript_preview", "") or "")
                    # 修 8：補 dissect.hook_structure.first_3_sec_text
                    _ev_hook_text = ""
                    _ev_dissect = _ev_data.get("dissect") or {}
                    if isinstance(_ev_dissect, dict):
                        _ev_hook_struct = _ev_dissect.get("hook_structure") or {}
                        if isinstance(_ev_hook_struct, dict):
                            _ev_hook_text = str(_ev_hook_struct.get("first_3_sec_text", "") or "")
                    _ev_topic_text = f"{_ev_title} {_ev_transcript} {_ev_hook_text}"
                    _ev_tokens = _normalize_and_tokenize(_ev_topic_text)
                    _body_text_ev = _extract_script_body_text(data)
                    _body_tokens_ev = _normalize_and_tokenize(_body_text_ev)
                    _TOPIC_SHARED_THRESHOLD = 2  # 寬鬆門檻（§22.9 角度自由、有誤判空間）
                    if _ev_tokens:
                        _topic_shared = _ev_tokens & _body_tokens_ev
                        if len(_topic_shared) < _TOPIC_SHARED_THRESHOLD:
                            shadow_warns.append(
                                f"腳本與爆款出處題目疑似不同"
                                f"（共享詞 {len(_topic_shared)} < {_TOPIC_SHARED_THRESHOLD}；"
                                f"交集：{sorted(_topic_shared)[:3]}）"
                                f"【shadow 啟發式偵測，有誤判空間；§22.9 不限角度】"
                            )
                except Exception as _ev_parse_err:
                    shadow_warns.append(
                        f"evidence 真比對讀取/解析失敗（略過此檢查）：{_ev_parse_err}"
                    )

                # R5-3b：AI 語意閘（題目同一性 shadow 判定）
                # keyword 閘（R5-3）= 快篩；AI 閘 = 權威 shadow 判定（兩者並存）
                # §22.9 鐵律已嵌入 _TOPIC_INTEL_AI_GATE_PROMPT_TEMPLATE
                # 需 TOPIC_INTEL_AI_GATE=1 + GOOGLE_API_KEY；預設 skip（不污染、不擋批）
                try:
                    import os as _os_aig
                    import hashlib as _hashlib_aig
                    _AI_GATE_ENABLED = _os_aig.environ.get("TOPIC_INTEL_AI_GATE", "0") == "1"
                    if _AI_GATE_ENABLED:
                        _body_for_ai = _extract_script_body_text(data)
                        _body_sha = _hashlib_aig.sha256(
                            _body_for_ai.encode("utf-8", errors="replace")
                        ).hexdigest()
                        # 硬化 7：full cache key（evidence sha + body sha + model + prompt_version）
                        _ev_sha_key = sha if sha else "nosha"
                        _ai_cache_key = f"{_ev_sha_key}:{_body_sha}:{_AI_GATE_MODEL}:{_AI_GATE_PROMPT_VERSION}"
                        # 硬化 6：厚 evidence — R5-3 解析結果 + narrative_arc + 痛點 dissect
                        try:
                            # R5-3 已解析成功：_ev_topic_text 含 title+transcript+hook
                            _ai_ev_text = _ev_topic_text  # noqa: F821
                            # 補 narrative_arc（讓 AI 看到更完整痛點敘事）
                            try:
                                _ev_arc = str(_ev_data.get("dissect", {}).get("narrative_arc", "") or "")  # noqa: F821
                                if _ev_arc:
                                    _ai_ev_text = f"{_ai_ev_text}\n[痛點敘事] {_ev_arc[:500]}"
                            except Exception:
                                pass
                        except NameError:
                            # R5-3 解析失敗 → 從 bytes 重新提取
                            import re as _re_aig2
                            import yaml as _yaml_aig2
                            _raw2 = _ev_bytes.decode("utf-8", errors="replace")
                            _raw2 = _re_aig2.sub(r"^---\s*\n", "", _raw2, count=1)
                            _d2 = _yaml_aig2.safe_load(_raw2) or {}
                            _ai_ev_text = (
                                f"{_d2.get('title', '')} "
                                f"{_d2.get('transcript_preview', '')} "
                                f"{str((_d2.get('dissect') or {}).get('narrative_arc', ''))}"
                            )
                        _ai_result = _call_topic_intel_ai_gate(
                            evidence_text=_ai_ev_text,
                            script_body=_body_for_ai,
                            cache_key=_ai_cache_key,
                        )
                        _ai_verdict = _ai_result.get("verdict", "api_unavailable")
                        _ai_reason = _ai_result.get("reason", "")
                        _ai_conf = _ai_result.get("confidence", 0)
                        if _ai_verdict == "different_topic":
                            # 重用修 10 flag 鏈：消息含「題目疑似不同」→ 現有 _r5_3_flagged_fnames 邏輯同時捕捉
                            shadow_warns.append(
                                f"【AI語意閘】腳本與爆款出處題目疑似不同"
                                f"（verdict=different_topic, confidence={_ai_conf}；{_ai_reason}）"
                                f"【shadow advisory；§22.9 不限角度；絕不擋批】"
                            )
                        elif _ai_verdict == "insufficient_evidence":
                            shadow_warns.append(
                                f"【AI語意閘】evidence 資訊不足，無法判定（confidence={_ai_conf}）；AI 閘略過"
                            )
                        elif _ai_verdict == "api_unavailable":
                            shadow_warns.append(
                                f"【AI語意閘】暫不可用，skip（{_ai_result.get('note', '')}）"
                            )
                        # same_topic / same_topic_new_angle → 通過，不加 warn（§22.9 合格放行）
                    # _AI_GATE_ENABLED=False → 靜默 skip
                except Exception as _ai_gate_err:
                    shadow_warns.append(
                        f"【AI語意閘】執行例外（skip，不擋批）：{_ai_gate_err}"
                    )
        except Exception as _ev_outer_err:
            shadow_warns.append(f"evidence_path 指紋/比對檢查例外（略過）：{_ev_outer_err}")

    # 3. adopted_topic_statement 驗
    adopted = str(sti.get("adopted_topic_statement", "") or "").strip()
    if not adopted or _is_placeholder(adopted):
        issues.append("adopted_topic_statement 尚未填寫（仍為 placeholder）")
        is_fail = True
    else:
        zh_count = _count_chinese_chars(adopted)
        if zh_count < 12:
            issues.append(f"adopted_topic_statement 中文字數 {zh_count} < 12（需 >=12）")
            is_fail = True

        body_text = _extract_script_body_text(data)
        adopted_tokens = _normalize_and_tokenize(adopted)
        body_tokens = _normalize_and_tokenize(body_text)
        shared = adopted_tokens & body_tokens
        if len(shared) < 5:
            issues.append(
                f"題材關鍵詞交集 {len(shared)} < 5（交集詞：{sorted(shared)[:5]}）"
            )
            is_fail = True

    # 4. Fix G：projection cache 比對（驗真來源）
    # R5-1：topic_id 必須非空（shadow WARN）— 堵空 topic_id 繞過 projection 比對
    topic_id = str(sti.get("topic_id", "") or "")
    if not topic_id:
        shadow_warns.append(
            "topic_id 為空，無法驗真來源（防繞過 projection 比對）"
        )
    elif sha:
        try:
            _proj_index = _load_projection_candidate_index(owner) if owner else None
            if _proj_index is not None:
                _proj_sha = _proj_index.get(topic_id)
                if _proj_sha is None:
                    issues.append(
                        f"topic_id={topic_id!r} 不在 owner={owner!r} projection cache 中（未投影或已失效）"
                    )
                    is_fail = True
                elif _proj_sha != sha:
                    issues.append(
                        f"evidence_sha256 與 projection cache 不符（yaml={sha!r}, proj={_proj_sha!r}）"
                    )
                    is_fail = True
            # Fix 4：_proj_index is None（projection cache 缺）→ enforce FAIL，shadow WARN
            if _proj_index is None:
                _proj_miss_msg = f"projection cache 不存在（owner={owner!r}）；enforce 模式須 cache 在場才可驗真來源"
                issues.append(_proj_miss_msg)
                if mode == "enforce":
                    is_fail = True
        except Exception as _proj_err:
            # projection 讀取出現例外 → enforce fail-closed；shadow WARN（環境問題）
            issues.append(f"projection cache 讀取出現例外：{_proj_err}")
            if mode == "enforce":
                is_fail = True

    # 結果彙整（shadow_warns 一律不升 enforce FAIL）
    _all_issues = issues + [f"[補強] {w}" for w in shadow_warns]

    if not _all_issues:
        adopted_tokens = _normalize_and_tokenize(adopted)
        body_text = _extract_script_body_text(data)
        body_tokens = _normalize_and_tokenize(body_text)
        shared_count = len(adopted_tokens & body_tokens)
        zh_count = _count_chinese_chars(adopted)
        return "PASS", (
            f"V3-001 provenance OK: topic_id={topic_id!r}, "
            f"zh={zh_count}>=12, shared_tokens={shared_count}>=5, proj=matched"
        )

    if mode == "enforce" and is_fail:
        return "FAIL", f"V3-001 provenance FAIL（enforce）：{'；'.join(_all_issues)}"
    return "WARN", f"V3-001 provenance WARN（{mode}）：{'；'.join(_all_issues)}"


def chk_v3_002_batch_slot_count(
    valid_yamls: list[tuple],
    topic_intel_policy: dict,
) -> tuple[str, str]:
    """
    V3-002：批次級 source_topic_intel 總數 min/max 硬驗。

    policy disabled / off / invalid → SKIP（零足跡，不讀 yaml）。
    policy enabled（shadow/enforce）：
      統計整批有 source_topic_intel 的 yaml 數量。
      < min_slots → FAIL / WARN
      > ceiling → FAIL / WARN（ceiling 定義見下）
      in [min_slots, ceiling] → PASS

    ceiling 規則（2026-06-26）：
      bind_scope == "all_offpro"：ceiling = 批次中 content_axis=="offpro" 的稿數
        （即全部 offpro 稿都應綁；用 offpro 實際數而非 max_slots，避免假 WARN）
      其他：ceiling = max_slots（規格 §9 原行為）

    shadow → WARN；enforce → FAIL（批次結構問題，非單篇）。
    """
    if not topic_intel_policy or not topic_intel_policy.get("enabled", False):
        # off / disabled / invalid → 零足跡 SKIP
        return "SKIP", "V3-002 WP-B policy off/disabled，跳過批次 slot 數驗"

    mode = topic_intel_policy.get("mode", "off")
    min_slots = topic_intel_policy.get("min_slots") or 2
    max_slots = topic_intel_policy.get("max_slots") or 4
    bind_scope = str(topic_intel_policy.get("bind_scope", "") or "").strip()

    # 統計有 source_topic_intel 的 yaml 數量（skeleton 也驗 —— assign 後已應存在 block）
    sti_count = sum(
        1 for _, data in valid_yamls
        if isinstance(data.get("source_topic_intel"), dict)
    )
    total = len(valid_yamls)

    # ceiling 決策：bind_scope=all_offpro 時用 offpro 稿實際數（2026-06-26）
    if bind_scope == "all_offpro":
        offpro_count = sum(
            1 for _, data in valid_yamls
            if str(data.get("content_axis", "") or "").strip().lower() == "offpro"
        )
        ceiling = offpro_count
        ceiling_label = f"offpro 稿數={offpro_count}（bind_scope=all_offpro）"
    else:
        ceiling = max_slots
        ceiling_label = f"max_slots={max_slots}"

    # Fix F【P1】shadow=WARN / enforce=FAIL（shadow 觀察期不被擋死）
    _v3002_severity = "FAIL" if mode == "enforce" else "WARN"

    if sti_count < min_slots:
        return _v3002_severity, (
            f"V3-002 批次 source_topic_intel 總數 {sti_count}/{total} < min_slots={min_slots}（{mode}）"
        )
    if sti_count > ceiling:
        return _v3002_severity, (
            f"V3-002 批次 source_topic_intel 總數 {sti_count}/{total} > {ceiling_label}（{mode}）"
        )
    return "PASS", (
        f"V3-002 批次 source_topic_intel 總數 {sti_count}/{total}（min={min_slots}, ceiling={ceiling_label}, mode={mode}）"
    )


def chk_v3_001b_topic_id_unique(
    valid_yamls: list[tuple],
    topic_intel_policy: dict,
) -> tuple[str, str]:
    """
    V3-001b：批次唯一性 — 同一批次內同一 topic_id 不重複掛（R5 Fix 4）。

    policy disabled / off → SKIP（零足跡）。
    policy enabled（shadow/enforce）：
      掃整批 source_topic_intel.topic_id，找重複。
      有重複 → shadow=WARN / enforce=WARN（皆 shadow 程度，不升 enforce FAIL）。
      無重複 → PASS。
    """
    if not topic_intel_policy or not topic_intel_policy.get("enabled", False):
        return "SKIP", "V3-001b WP-B policy off/disabled，跳過批次 topic_id 唯一驗"

    mode = topic_intel_policy.get("mode", "off")
    seen: dict = {}     # topic_id → 第一次出現的 fname
    duplicates: list = []

    for f, data in valid_yamls:
        sti = data.get("source_topic_intel") if isinstance(data, dict) else None
        if not isinstance(sti, dict):
            continue
        tid = str(sti.get("topic_id", "") or "").strip()
        if not tid:
            continue
        fname = getattr(f, "name", str(f))
        if tid in seen:
            duplicates.append(f"{fname!r}（重複 topic_id={tid!r}，首次在 {seen[tid]!r}）")
        else:
            seen[tid] = fname

    if not duplicates:
        return "PASS", (
            f"V3-001b 批次 topic_id 唯一（{len(seen)} 個各不重複，mode={mode}）"
        )

    dup_list = "；".join(duplicates[:5])
    suffix = f"（共 {len(duplicates)} 筆重複）" if len(duplicates) > 5 else ""
    return "WARN", (
        f"V3-001b 批次內 topic_id 重複（shadow WARN，不擋批）：{dup_list}{suffix}"
    )


# ════════════════════════════════════════════
# §21 腳本品質公式 check（2026-06-17 機器化 §21 落地）
# 對齊 scripter.md §21 v1.2 — validator 內零 LLM、純結構性機驗
# ════════════════════════════════════════════

def _s21_batch_date(yamls: list[tuple[Path, dict]]) -> Optional[_dt.date]:
    """取批次日期（批內取最大值，沿用 _extract_batch_date 逐支邏輯）。
    回傳 None = 無法判斷日期（保守：當作過渡期/WARN）。"""
    dates: list[_dt.date] = []
    for f, data in yamls:
        if not isinstance(data, dict):
            continue
        if "__parse_error__" in data or "__schema_error__" in data:
            continue
        d = _extract_batch_date(data, f"{f.parent.name}/{f.name}")
        if d:
            dates.append(d)
    return max(dates) if dates else None


def _s21_in_warn_window(batch_date: Optional[_dt.date], has_legacy_marker: bool = False) -> bool:
    """§21 過渡期判定（P1-C，Codex 第 2 輪退回修，fail-open → fail-closed）：

    - 明確解析到的 batch_date < _S21_EFFECTIVE_FROM → True（過渡期 WARN-waiver）
    - 有明確 legacy 標記（legacy_allowed_until >= today）→ True（WARN-waiver）
    - batch_date is None / 無法解析 → **False（post-cutover / enforce 側，FAIL 路徑）**

    根因（原碼）：batch_date is None 時回 True → post-cutover 一個沒日期的資料夾 + yaml 無
    batch_date → §21 違規一律降 WARN，逃過 FAIL。與既有 fail-closed 慣例（V2-025
    _is_v2025_legacy：batch_date is None → return False 當新批 FAIL）相反。

    修法：對齊 V2-025 fail-closed——None / 無法解析當 post-cutover（enforce 側），
    除非有明確 legacy 標記（legacy_allowed_until）。真實既有批都有資料夾名/batch_tag 日期、
    不受影響；只有真的沒日期的才落 enforce 側＝正確 fail-closed。
    """
    if batch_date is not None and batch_date < _S21_EFFECTIVE_FROM:
        return True
    if has_legacy_marker:
        return True
    return False


def _s21_get_skeleton_type(data: dict) -> Optional[str]:
    """取單支「骨架型」。復用既有 `pattern` 欄（骨架機 line 224 已輸出
    `pattern: [編劇填] # e.g. 創業故事型/觀點分享型`，語義 = 結構/骨架型，不另立新欄）。
    placeholder / 空 → 回 None（由呼叫端判 skeleton SKIP）。

    防呆：骨架機未引號的 `pattern: [編劇填]` 會被 YAML 解析成 list ['編劇填']，
    一般 _is_placeholder（只認 str/None）抓不到 → 此處 list 取首元素再判 placeholder。
    """
    val = data.get("pattern")
    if val is None:
        return None
    # list（YAML 把骨架機未引號的 `pattern: [編劇填]` 解析成 list ['編劇填']）→ 視為骨架未填。
    # 骨架機真實填好的 pattern 一律是字串（e.g. 創業故事型）；只有未填的 placeholder 會變 list，
    # 故 list 型 pattern 一律當 placeholder（回 None → 由呼叫端 SKIP）。
    if isinstance(val, list):
        return None
    if _is_placeholder(val):
        return None
    # 取行內 comment 前的有效部份（pattern 欄值含 '#' 註解時切掉）
    s = str(val).split("#")[0].strip()
    # 額外保險：骨架機 bare token「編劇填」（去括號後）也當 placeholder
    if s in ("編劇填", "[編劇填]", "pending", "todo", "待填"):
        return None
    return s or None


def _s21_raw_cta_mix_enforcement_is_hard(pref_text: Optional[str]) -> bool:
    """C-21.2 P1-A（Codex 第 2 輪退回修）：直接從 raw pref_text 的 cta_mix kb-rule
    區塊原文判定是否「明寫 enforcement: hard」——**不信 _mix_parser 的 default 值**。

    根因：_mix_parser line 138-140 對缺值 default 成 decision_status=confirmed /
    approval_status=owner_signed。原 _s21_2_l2_hard_cta_mix 用「confirmed/owner_signed
    任一」判 hard → 一個只寫 enforcement:advisory（沒寫 decision_status/approval_status）
    的軟塊，被 default 充成 confirmed/owner_signed → 誤判硬性 → 誤 defer → 13/13 同一種
    CTA 的偷懶批被誤放行（重開 §21.2 要堵的洞）。

    修法：只認該業主 cta_mix kb-rule 區塊原文裡**明寫的** `enforcement: hard`
    （不靠 parser default、不認 confirmed/owner_signed 充數）。
    advisory / proposed / 沒寫 / 只靠 default → 一律 not-hard（不 defer）。
    """
    if not pref_text:
        return False
    # 找所有 ```kb-rule ... ``` block，定位 category: cta_mix 的那塊，讀其原文 enforcement 行
    blocks = re.findall(r"```kb-rule\n(.*?)```", pref_text, re.DOTALL)
    for raw in blocks:
        # 判斷此 block 是否 category: cta_mix（原文 line 比對，不用 yaml load 以免被旁的解析影響）
        m_cat = re.search(r"^\s*category\s*:\s*([^\s#]+)", raw, re.MULTILINE)
        if not m_cat or m_cat.group(1).strip() != "cta_mix":
            continue
        # 在這塊 cta_mix 原文裡找明寫的 enforcement 行
        m_enf = re.search(r"^\s*enforcement\s*:\s*([^\s#]+)", raw, re.MULTILINE)
        if m_enf and m_enf.group(1).strip().strip('"').strip("'") == "hard":
            return True
        # 找到 cta_mix block 但沒明寫 enforcement: hard → not hard（不繼續找別的 cta_mix block）
        return False
    return False


def _s21_2_l2_hard_cta_mix(pref_text: Optional[str]):
    """C-21.2 P1-1 / P1-A：偵測 L2 是否宣告「硬性 cta_mix」。

    回傳 MixParseResult（found=True 且**原文明寫 enforcement: hard**）或 None。

    **P1-A（Codex 第 2 輪退回修）**：硬性「只認 raw pref_text cta_mix 區塊原文裡明寫的
    `enforcement: hard`」——不信 _mix_parser 對缺值 default 成 confirmed/owner_signed 的值。
    advisory / proposed / 沒寫 / 只靠 default 的 confirmed/owner_signed → 一律 not-hard、不 defer，
    照套 ≥3 種 + ≤6/13 多樣性規則。瑞祥原文有明寫 enforcement: hard → 仍正確 defer。

    對齊 scripter.md §21.2 line 573「L2 有 cta_mix 時話術配比以 L2 為準」+
    派工 P1-A：瑞祥 L2 cta_mix 業主本人明寫 enforcement:hard 簽核「個人化諮詢型 92%／12 支」
    的集中是刻意，多樣性配比歸 C-cta-mix；但軟塊不能靠 parser default 蒙混 defer。
    """
    if not _MIX_PARSER_OK or _parse_mix_block is None:
        return None
    if not pref_text:
        return None
    # P1-A：先用 raw 原文判 enforcement: hard（不信 parser default）
    if not _s21_raw_cta_mix_enforcement_is_hard(pref_text):
        return None
    try:
        result = _parse_mix_block(pref_text, "cta_mix")
    except Exception:
        return None
    if not result.found:
        return None
    return result


def chk_c21_2_cta_diversity(
    yamls: list[tuple[Path, dict]],
    owner: str,
    pref_text: Optional[str] = None,
    batch_tag: str = "",
) -> tuple[str, str]:
    """C-21.2 CTA 真多樣（batch-level）— 批內 cta_effect ≥_S21_2_MIN_DISTINCT 種 + 單一最大 ≤_S21_2_MAX_SINGLE/13。

    對齊 scripter.md §21.2（Codex 三審 P2-1 + 派工 P1-1/P1-2）：
    - cta_effect 來源 = 復用既有逐支 CTA 類別欄 `schema_check.CTA類型`（與 C-cta-mix 同源，
      由 L2 cta_mix block source_fields 宣告 [["schema_check","CTA類型"]]；編劇不另填第二個欄）。
    - 與 C-cta-mix **正交、不重複計**：C-cta-mix 驗「vs L2 cta_mix 配比」；C-21.2 驗「種類多樣性」。
    - **P1-1（L2 owner-signed 硬性 cta_mix 優先）**：若 L2 宣告硬性 cta_mix
      （enforcement:hard / decision_status:confirmed / approval_status:owner_signed 任一）→
      C-21.2 不對「單一 ≤6/13」FAIL，回 PASS+註記「多樣性配比歸 C-cta-mix」（業主簽核的集中是刻意）。
      只有 L2 沒宣告硬性 cta_mix（無 cta_mix / soft / proposed）→ 才套 ≥3 種 + ≤6/13 多樣性規則。
    - **P1-2（alias 正規化）**：計算 distinct 種類前先用 _resolve_label 把
      「諮詢型／個人化諮詢型／個人諮詢」等正規化到 canonical label（與 C-cta-mix 同套 alias map），
      避免同義不同字面被當不同種類灌水多樣性或誤殺。
    - 缺欄 / 骨架階段 → SKIP（>50% 支取不到 CTA 類別）。
    - 過渡期（batch_date < _S21_EFFECTIVE_FROM）→ WARN-waiver。
    """
    valid = [(f, d) for f, d in yamls if "__parse_error__" not in d and "__schema_error__" not in d]
    if not valid:
        return "WARN", "C-21.2：批次無有效 yaml，跳過"

    batch_date = _s21_batch_date(valid)
    # P1-C：legacy 標記 = 批內任一 yaml 有 legacy_allowed_until >= today
    _legacy = any(_is_legacy_yaml(d) for _, d in valid)
    in_warn = _s21_in_warn_window(batch_date, has_legacy_marker=_legacy)

    # P1-1：L2 宣告硬性 cta_mix → defer 給 C-cta-mix（業主簽核的集中是刻意，多樣性不在此擋）
    l2_hard = _s21_2_l2_hard_cta_mix(pref_text)
    if l2_hard is not None:
        return "PASS", (
            f"C-21.2：L2 owner-signed/confirmed 硬性 cta_mix 優先"
            f"（enforcement={getattr(l2_hard, 'enforcement', '')}, "
            f"decision_status={getattr(l2_hard, 'decision_status', '')}, "
            f"approval_status={getattr(l2_hard, 'approval_status', '')}）"
            f"，多樣性配比歸 C-cta-mix，C-21.2 不擋集中"
        )

    # P1-2：alias 正規化用的 cta_mix items（即使非硬性也可有 items 供 _resolve_label canonical）
    _norm_items = None
    if _MIX_PARSER_OK and _parse_mix_block is not None and pref_text:
        try:
            _soft_result = _parse_mix_block(pref_text, "cta_mix")
            if _soft_result.found and _soft_result.items:
                _norm_items = _soft_result.items
        except Exception:
            _norm_items = None

    # 逐支讀 CTA 類別 = schema_check.CTA類型（與 C-cta-mix 共用欄位、不另立）
    # P2-B（Codex 第 2 輪退回修）：只認可解析到 canonical 的標籤計 distinct；
    # 無法解析的 garbage 標籤（foo×5/bar×4/baz×4）不計入多樣性 + 收集出 WARN，防灌水充多樣。
    cta_counts: dict[str, int] = {}
    missing = 0
    unresolved: dict[str, int] = {}   # P2-B：無法解析到 canonical 的 raw 標籤 → 計數供 WARN
    for f, d in valid:
        sc = d.get("schema_check")
        label = None
        if isinstance(sc, dict):
            label = sc.get("CTA類型")
        if label is None or _is_placeholder(label) or not str(label).strip():
            missing += 1
            continue
        raw_label = str(label).split("#")[0].strip()
        # P1-2 + P2-B 兩段 canonical：① L2 cta_mix items（_resolve_label）② validator 自有效果詞彙。
        canon = None
        if _norm_items is not None and _resolve_label is not None:
            canon = _resolve_label(raw_label, _norm_items)
        if canon is None:
            canon = _s21_canonical_cta_effect(raw_label)
        if canon is None:
            # P2-B：無法解析 → 不計入多樣性，收集供 WARN（提示編劇用正規類別）
            unresolved[raw_label] = unresolved.get(raw_label, 0) + 1
            continue
        cta_counts[canon] = cta_counts.get(canon, 0) + 1

    # 骨架階段 SKIP：>50% 支缺 CTA 類別欄（缺欄；unresolved 不算缺欄，另走 WARN）
    if (missing / len(valid)) > 0.5:
        return "SKIP", (
            f"C-21.2：>50% 支缺 CTA 類別欄（schema_check.CTA類型 placeholder/空，{missing}/{len(valid)}）"
            f"— 骨架階段跳過，等編劇填完再驗"
        )

    distinct = len(cta_counts)
    max_label, max_n = ("", 0)
    if cta_counts:
        max_label, max_n = max(cta_counts.items(), key=lambda kv: kv[1])
    detail = dict(sorted(cta_counts.items(), key=lambda kv: -kv[1]))

    # P2-B：unresolved garbage 標籤註記（不計多樣性，提示編劇用正規類別）
    unresolved_note = ""
    if unresolved:
        unresolved_note = (
            f"；⚠ {sum(unresolved.values())} 支 CTA 標籤無法解析到正規效果類別、不計入多樣性"
            f"（{dict(sorted(unresolved.items(), key=lambda kv: -kv[1]))}）"
            f"，請改用正規類別（個人化諮詢/互動問句/分享引導/招生課程/無強CTA 或 L2 cta_mix 宣告的別名）"
        )

    problems = []
    if distinct < _S21_2_MIN_DISTINCT:
        problems.append(f"只有 {distinct} 種 cta_effect（需 ≥{_S21_2_MIN_DISTINCT} 種）")
    if max_n > _S21_2_MAX_SINGLE:
        problems.append(f"單一最大類別「{max_label}」{max_n} 支（需 ≤{_S21_2_MAX_SINGLE}/13）")

    if problems:
        msg = "C-21.2 CTA 多樣不足：" + "；".join(problems) + f"（分佈 {detail}）" + unresolved_note
        if in_warn:
            return "WARN", msg + f"（過渡期 batch_date={batch_date} < {_S21_EFFECTIVE_FROM}，WARN-waiver）"
        return "FAIL", msg

    # 多樣性達標但有 garbage 標籤 → WARN 提示（不擋，但要編劇看見）
    if unresolved:
        return "WARN", (
            f"C-21.2 CTA 多樣達標（{distinct} 種 / 單一最大 {max_n}，分佈 {detail}）"
            + unresolved_note
        )

    return "PASS", f"C-21.2 CTA 多樣 PASS：{distinct} 種 / 單一最大 {max_n}（分佈 {detail}）"


def _w3d5_batch_max_date(yamls: list[tuple[Path, dict]]) -> Optional[_dt.date]:
    """W3 Δ5 新閘共用（R-CTA-002 / R-QGR-001）：批次級 cutover 判別，取批內逐支
    _rcard_all_dates_max 之最大值——與 R-CARD-001 per-file 同一天窗函式（修訂⑪·r7-B1
    窮舉多日期字串取全域最大），只是在此聚合成批級供 batch-level checks 用。
    """
    dates: list[_dt.date] = []
    for f, d in yamls:
        if not isinstance(d, dict):
            continue
        dd = _rcard_all_dates_max(d, f"{f.parent.name}/{f.name}")
        if dd is not None:
            dates.append(dd)
    return max(dates) if dates else None


def chk_r_cta_001_cta_fields_complete(
    data: dict,
    fname: str,
    is_skeleton: bool = False,
) -> tuple[str, str]:
    """R-CTA-001（W3 Δ5 補閘，D24 P4）— per-file：新批（cutover ≥2026-07-14）已填完稿
    （非骨架 stub）缺 pattern 欄或缺/空 cta_effect 欄（schema_check.CTA類型，與 C-21.2
    同源、不另立新欄）→ FAIL（C-21.2/C-21.1 原僅批級 >50% 缺才 SKIP，單支缺欄靜默排除
    不擋；本規則補單支硬閘）。

    is_skeleton 判別沿用 C-21.7 呼叫端邏輯（_is_placeholder(data.get("title"))，見
    vsb run_per_file_checks 內 C-21.7 註冊行）——骨架階段（is_skeleton=True）→ SKIP。
    cutover：沿用 R-CARD-001 同款單支日期判別（_rcard_all_dates_max）；歷史批次不溯及。
    """
    batch_date = _rcard_all_dates_max(data, fname)
    if batch_date is not None and batch_date < _R_CARD_001_EFFECTIVE_FROM:
        return "SKIP", (
            f"R-CTA-001 legacy skip：歷史批次不溯及（batch_date={batch_date} "
            f"< {_R_CARD_001_EFFECTIVE_FROM}）"
        )

    if is_skeleton:
        return "SKIP", "R-CTA-001：骨架階段（is_skeleton=True），等編劇填完再驗"

    missing = []
    pattern_type = _s21_get_skeleton_type(data)
    if pattern_type is None:
        missing.append("pattern 欄缺/placeholder")

    sc = data.get("schema_check")
    cta_label = sc.get("CTA類型") if isinstance(sc, dict) else None
    if cta_label is None or _is_placeholder(cta_label) or not str(cta_label).strip():
        missing.append("cta_effect 欄缺/空（schema_check.CTA類型）")

    if missing:
        return "FAIL", "R-CTA-001：已填完稿卻缺欄——" + "；".join(missing)

    return "PASS", (
        f"R-CTA-001 PASS：pattern={pattern_type!r} / "
        f"CTA類型={str(cta_label).split('#')[0].strip()!r}"
    )


def _s21_6_batch_exempt(batch_dir: Path) -> tuple[str, str]:
    """C-21.6 P1-4：讀**批次級** _batch_flags.yml 的 quality_gate 段判豁免。

    回傳 (state, detail)：
      state ∈ {"exempt"（有效豁免）, "exempt_no_reason"（標 exempt 但缺 reason）, "none"（無豁免）}

    對齊既有 fishing_dm_card / topic_intel_closure 同檔同機制（_batch_flags.yml）：
      quality_gate:
        exempt: true
        reason: "B 級批，非高規格無需整稿閘"
    - exempt 須 boolean True（不認字串 "true"）+ 須有 reason。
    - **不再認單支 yaml 的 quality_gate_exempt**（派工 P1-4：改 batch-level 旗標）。
    - 檔不存在 / 解析失敗 / 段缺 → none（fail-closed：無豁免 = 須有報告）。
    """
    flag_path = batch_dir / "_batch_flags.yml"
    if not flag_path.exists():
        return "none", "無 _batch_flags.yml → 無 quality_gate 豁免"
    try:
        import yaml as _yaml_mod
        raw = _yaml_mod.safe_load(flag_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return "none", f"_batch_flags.yml 解析失敗（{e}）→ 無豁免（fail-closed）"
    if not isinstance(raw, dict):
        return "none", "_batch_flags.yml top-level 非 mapping → 無豁免（fail-closed）"
    qg = raw.get("quality_gate", {}) or {}
    if not isinstance(qg, dict):
        return "none", f"_batch_flags.yml quality_gate 非 mapping（{type(qg).__name__}）→ 無豁免（fail-closed）"
    if qg.get("exempt") is not True:
        return "none", f"_batch_flags.yml quality_gate.exempt 非 boolean true（{qg.get('exempt')!r}）→ 無豁免"
    raw_reason = qg.get("reason", "")
    if not isinstance(raw_reason, str):
        # Codex R4 P1：reason 非字串（list/dict）被 str() 成非空字串 → 誤過豁免；fail-closed
        return "none", f"_batch_flags.yml quality_gate.reason 非字串（{type(raw_reason).__name__}）→ 無豁免（fail-closed）"
    reason = raw_reason.strip()
    if not reason:
        return "exempt_no_reason", "_batch_flags.yml quality_gate.exempt=true 但 reason 為空"
    return "exempt", f"_batch_flags.yml quality_gate 豁免有效（reason={reason!r}）"


def chk_c21_6_quality_gate_report(
    yamls: list[tuple[Path, dict]],
    batch_dir: Path,
) -> tuple[str, str]:
    """C-21.6 整稿閘報告存在（batch-level）— 批次資料夾須有 _quality_gate_report.md（且 bytes>0）。

    對齊 scripter.md §21.6（Codex 三審 P1-2 + 派工 P1-4）：
    - **P1-4①豁免改 batch-level 旗標**：讀 _batch_flags.yml 的 quality_gate 段
      （與 fishing_dm_card / topic_intel_closure 同檔同機制），exempt: true 且須有 reason →
      豁免 PASS。**不再認單支 yaml 的 quality_gate_exempt**。
    - **P1-4②報告須 bytes>0**：_quality_gate_report.md 須存在「且非空」（0 bytes 不算 PASS）。
    - 2026-06-23 翻 enforce（_S21_6_REPORT_ENFORCE=True）：缺報告/無效 exempt → FAIL（高規格批附報告、一般批標 exempt）。
    - 過渡期同樣 WARN（與 enforce 旗標雙重保護）。
    """
    # P1-4①：批次級豁免偵測（_batch_flags.yml quality_gate 段）
    ex_state, ex_detail = _s21_6_batch_exempt(batch_dir)
    if ex_state == "exempt":
        return "PASS", f"C-21.6：批次豁免整稿閘報告（{ex_detail}）"
    if ex_state == "exempt_no_reason":
        # Codex R1 P0：原 early-return WARN 會讓「exempt:true 但無 reason」繞過 enforce（豁免不成立卻放行）。
        # 修：shadow（_S21_6_REPORT_ENFORCE=False）→ WARN 提醒；enforce（=True）→ 豁免不成立、不 early-return，
        #     fall through 檢查 _quality_gate_report.md（有有效報告仍 PASS、缺/空 → FAIL，fail-closed）。
        if not _S21_6_REPORT_ENFORCE:
            return "WARN", f"C-21.6：{ex_detail} — 豁免須補 reason 才成立，請於 _batch_flags.yml quality_gate.reason 補理由"

    report = batch_dir / "_quality_gate_report.md"
    if report.is_file():  # Codex R4 P2：非檔（目錄/symlink）→ 不算有效報告（POSIX 目錄 stat size 非 0 會誤 PASS）
        try:
            sz = report.stat().st_size
        except Exception:
            sz = -1
        # P1-4②：0 bytes（或讀不到 size）→ 不算 PASS
        if sz > 0:
            return "PASS", f"C-21.6：找到整稿閘報告 _quality_gate_report.md（{sz} bytes）"
        # 報告存在但空 → 視同缺報告
        msg_empty = (
            f"C-21.6：整稿閘報告 _quality_gate_report.md 存在但為空（{sz} bytes）— 不算有效報告"
            "（須附逐支 R10-R20 命中 / R14·R15 hard fail / 例外清單 / GPT 打分 + prompt log）"
        )
        if _S21_6_REPORT_ENFORCE:
            return "FAIL", msg_empty
        return "WARN", msg_empty + "（_S21_6_REPORT_ENFORCE=False 時 WARN；現已 2026-06-23 enforce-live，此 branch 為 rollback 備用）"

    # 缺報告且非豁免
    msg = (
        "C-21.6：批次缺整稿閘報告 _quality_gate_report.md（高規格批次須附逐支 R10-R20 命中"
        "/ R14·R15 hard fail / 例外清單 / GPT 打分 + prompt log）；如非 S 級批請於 _batch_flags.yml "
        "標 quality_gate: {exempt: true, reason: ...}"
    )
    if _S21_6_REPORT_ENFORCE:
        return "FAIL", msg
    return "WARN", msg + "（_S21_6_REPORT_ENFORCE=False 時 WARN；現已 2026-06-23 enforce-live，此 branch 為 rollback 備用）"


def chk_c21_7_honest_ceiling(data: dict, fname: str, is_skeleton: bool = False) -> tuple[str, str]:
    """C-21.7 誠實天花板欄位（per-file）— score_type / true_material_source / claim_allowed 三欄。

    對齊 scripter.md §21.7（Codex 三審 P1-3 + 派工 P1-3 反向漏洞修補）：
    - score_type enum：angle / script / finished_video
    - true_material_source enum：none / transcript / video（transcript/video 須帶路徑）
    - claim_allowed：須填（非 placeholder）
    - 規則：true_material_source == none 時，腳本「整個 yaml 序列化全文」（含 caption / 收束 /
      claim_allowed / 任何自由欄位）禁出現「成片 90」「成片90」字樣
      （grep；只准「角度/腳本估分 X、成片待真語料」）。
    - **P1-3 反向漏洞修補**：分清「骨架階段」vs「已填完腳本」——
        · is_skeleton=True（整批骨架未填，由 _is_skeleton_mode 判定）+ 三欄全缺/placeholder → SKIP（合法）。
        · is_skeleton=False（已填完腳本）+ 三欄全缺（含整批不填）→ **FAIL**（過渡期 WARN）；
          誠實 gate 生效後，編劇整批不填不得反而過。
      只缺部分欄 / 非法值 → 照常驗（不論骨架）。
    - 過渡期（batch_date < _S21_EFFECTIVE_FROM，逐支 _extract_batch_date）→ WARN-waiver。
    """
    score_type = data.get("score_type")
    tms = data.get("true_material_source")
    claim = data.get("claim_allowed")

    # 骨架階段 / 缺欄判定
    def _missing(v):
        return v is None or _is_placeholder(v)

    all_missing = _missing(score_type) and _missing(tms) and _missing(claim)

    batch_date = _extract_batch_date(data, fname)
    # P1-C：legacy 標記 = 該支有 legacy_allowed_until >= today
    in_warn = _s21_in_warn_window(batch_date, has_legacy_marker=_is_legacy_yaml(data))

    if all_missing:
        # P1-3：只有「真骨架階段」才合法 SKIP；已填完腳本三欄全缺 → FAIL（誠實 gate 不放水）
        if is_skeleton:
            return "SKIP", "C-21.7：誠實天花板三欄全缺/placeholder（骨架階段 is_skeleton=True），跳過"
        msg = (
            "C-21.7 誠實天花板：已填完腳本（非骨架階段）卻三欄全缺"
            "（score_type / true_material_source / claim_allowed）— 誠實 gate 生效後必填，不得整批不填繞過"
        )
        if in_warn:
            return "WARN", msg + f"（過渡期 batch_date={batch_date} < {_S21_EFFECTIVE_FROM}，WARN-waiver）"
        return "FAIL", msg

    fails = []

    # score_type enum
    ST_ENUM = {"angle", "script", "finished_video"}
    st_val = None if _missing(score_type) else str(score_type).split("#")[0].strip()
    if st_val is None:
        fails.append("缺 score_type（enum: angle/script/finished_video）")
    elif st_val not in ST_ENUM:
        fails.append(f"score_type 非法值「{st_val}」（須為 angle/script/finished_video）")

    # true_material_source enum + 路徑
    TMS_ENUM = {"none", "transcript", "video"}
    tms_val = None if _missing(tms) else str(tms).split("#")[0].strip()
    if tms_val is None:
        fails.append("缺 true_material_source（enum: none/transcript/video）")
    elif tms_val not in TMS_ENUM:
        fails.append(f"true_material_source 非法值「{tms_val}」（須為 none/transcript/video）")
    elif tms_val in {"transcript", "video"}:
        # 須帶路徑：接受 true_material_path 欄位，或值內含路徑樣態
        path_val = str(data.get("true_material_path", "") or "").strip()
        inline_has_path = bool(re.search(r"[\\/].+", str(tms))) or bool(re.search(r"\.(txt|md|mp4|mov|srt|vtt)", str(tms), re.I))
        if not path_val and not inline_has_path:
            fails.append(f"true_material_source={tms_val} 須帶路徑（true_material_path 欄或值內路徑）")

    # claim_allowed 須填
    if _missing(claim):
        fails.append("缺 claim_allowed（須填本支允許的宣稱，e.g. 角度到位、成片估分X待真語料）")

    # 「成片 90」禁字（true_material_source == none 時）
    if tms_val == "none":
        # 順手硬化②：掃「整個 yaml 序列化全文」（不只列舉欄位），防自由欄位漏網。
        # 先取 get_all_text（台詞/翠文/title/caption），再疊整個 dict 的 YAML dump 全文。
        full_text = get_all_text(data)
        try:
            import yaml as _yaml_dump_mod
            serialized = _yaml_dump_mod.safe_dump(data, allow_unicode=True, default_flow_style=False)
        except Exception:
            # dump 失敗（含不可序列化值）→ fallback 字串化整個 dict（仍涵蓋自由欄位）
            serialized = repr(data)
        scan_text = full_text + " " + serialized
        # 容忍空白：成片 90 / 成片90
        if re.search(r"成片\s*90", scan_text):
            fails.append("true_material_source=none 卻出現「成片 90」字樣（無真語料禁謊報成片 90，只准「角度/腳本估分 X、成片待真語料」）")

    if fails:
        msg = "C-21.7 誠實天花板：" + "；".join(fails)
        if in_warn:
            return "WARN", msg + f"（過渡期 batch_date={batch_date} < {_S21_EFFECTIVE_FROM}，WARN-waiver）"
        return "FAIL", msg

    return "PASS", f"C-21.7 誠實天花板 PASS：score_type={st_val} / true_material_source={tms_val}"


# ════════════════════════════════════════════
# §22 選題公式 — C-22 一般化偵測（batch-level，純規則 shadow WARN）
# ════════════════════════════════════════════

def _s22_topic_text(data: dict) -> str:
    """取單支「題目/標題/角度」文字供一般化偵測。
    優先序：title（主）+ non_obvious_claim（§22 新欄）+ topic plan 留的 direction 註解。
    direction 在骨架機是註解行（# direction: ...），yaml 解析吃不到 → 此處只取 yaml 欄位。
    回合併字串（去掉行內 # 註解尾）。"""
    parts: list[str] = []
    for key in ("title", "non_obvious_claim", "topic", "direction", "adopted_topic_statement"):
        v = data.get(key)
        if isinstance(v, str):
            parts.append(v.split("#")[0])
        elif isinstance(v, list):
            parts.extend(str(x).split("#")[0] for x in v)
    # source_topic_intel.adopted_topic_statement（WP-B）也納入
    sti = data.get("source_topic_intel")
    if isinstance(sti, dict):
        a = sti.get("adopted_topic_statement")
        if isinstance(a, str):
            parts.append(a.split("#")[0])
    return " ".join(parts)


# ⑦ 綁業主/第一人稱經歷詞庫 — Codex 第 2 輪 precision 修：拆強/弱兩庫（2026-06-17）。
#   原版（P1）一庫到底、弱詞（我跟/我看/問我…）也算「不一般」→ 弱詞湊數可繞過。
#   修法：強詞（綁真經歷、難偽造）算 hard；弱詞（泛敘述殼，泛 FAQ 也會用）算 weak。
#   強：我經手/我服務/我帶看/我入行/我遇過/我被/我打電話/我陪/我接到/我犯/我踩/我勸/我教…
#   弱：我跟/我看/我建議/我問/我幫/我聽/我跑/我發現/問我/找我/告訴我/罵我/謝我…（綁不出真經歷）
_S22_FP_HARD = [
    # 原版保留中「綁真經歷」的
    "我經手", "我服務", "我帶看", "我入行", "我有個客", "我遇過", "我的客", "我們店", "我老闆",
    # 強動詞（真做過/真發生在我身上）
    "我就這樣", "我都先", "我都問", "我都會", "我被", "我打電話",
    "我最常", "我學到", "我先問", "我遇到", "我會先",
    "我犯", "我踩", "我接到", "我跑", "我陪", "我勸", "我教",
]
_S22_FP_WEAK = [
    # 泛敘述殼（泛 FAQ / 任何人都能套）→ 弱訊號，不得單獨清關
    "我自己", "我當", "我做", "我這", "我老實", "我為什麼", "我看", "我幫",
    "我建議", "我聽", "我跟", "我發現", "我問",
    # 倒裝第一人稱（受詞在前）：問我/告訴我/找我… 泛 FAQ 高頻 → 弱
    "問我", "告訴我", "找我", "罵我", "教我", "謝我",
]


def _s22_count_signals(topic_text: str, owner: str) -> tuple[int, int, dict[str, bool]]:
    """算單支題目的「非一般訊號」（純 regex/詞庫，零 LLM）。
    回 (total 命中數, hard_count 硬訊號數, 逐訊號命中表)。

    7 訊號分 hard / weak 兩類（Codex 第 2 輪 precision 修，2026-06-17）：
      hard（具體可信、難偽造）：①具體數字 ②地名/在地 ⑤反直覺 ⑥受眾真代價 ⑦-強 強第一人稱/綁業主名
      weak（泛敘述殼、易湊）：③身份泛詞(客戶/客人/上班族…) ④時效 ⑦-弱 弱第一人稱(我跟/問我…)
    達標規則（caller 用）：total >= _S22_MIN_SIGNALS 且 hard_count >= _S22_MIN_HARD_SIGNALS。
      → 純弱訊號湊數（hard=0）一律判偏一般，補上 P1 留的 precision 洞。
    防雙計分（Codex 點名）：「客戶問我」= ③身份(weak) + ⑦弱第一人稱(weak)，兩者都歸 weak、
      且合併成「單一弱訊號」計（_weak_soft），避免同一語義靠 weak 算成 2 個訊號達標。
    對齊 scripter.md §22.4（原文訊號①「去掉業主名還成立」反向轉正向計分）。
    """
    t = topic_text or ""
    hits: dict[str, bool] = {}
    owner_token = str(owner or "").split("_")[-1].strip()  # 「房仲_瑞祥」→「瑞祥」；「叭噗_小C」→「小C」

    # ── hard 訊號 ──
    hits["數字"] = bool(_S22_NUM_RE.search(t))                          # ①
    hits["地名在地"] = any(w in t for w in _S22_PLACE_WORDS)            # ②
    hits["反直覺"] = any(w in t for w in _S22_COUNTER_WORDS)            # ⑤
    hits["受眾真代價"] = any(w in t for w in _S22_COST_WORDS)          # ⑥
    # ⑦-強：綁業主名 或 強第一人稱經歷（hard）
    hits["綁業主第一人稱_強"] = (bool(owner_token) and owner_token in t) or any(w in t for w in _S22_FP_HARD)

    hard_count = sum(1 for k in ("數字", "地名在地", "反直覺", "受眾真代價", "綁業主第一人稱_強") if hits[k])

    # ── weak 訊號（防雙計分：身份③ + 弱第一人稱⑦-弱 合併為「單一弱訊號」）──
    weak_identity = any(w in t for w in _S22_IDENTITY_WORDS)            # ③ 身份泛詞
    weak_fp = any(w in t for w in _S22_FP_WEAK)                         # ⑦-弱 弱第一人稱
    hits["身份描述"] = weak_identity
    hits["弱第一人稱"] = weak_fp
    # 身份 + 弱第一人稱 = 同一類「泛敘述殼」→ 合併只算 1 個弱訊號（防「客戶問我」雙計）
    weak_soft = 1 if (weak_identity or weak_fp) else 0
    hits["時效"] = any(w in t for w in _S22_TIME_WORDS)                 # ④ 時效（獨立弱訊號）
    weak_count = weak_soft + (1 if hits["時效"] else 0)

    total = hard_count + weak_count
    return total, hard_count, hits


def chk_c22b_anchor_first(
    data: dict,
    fname: str,
    yamls: list[tuple[Path, dict]],
    owner: str = "",
) -> tuple[str, str]:
    """C-22b anchor_first 機械閘（Cluster A v1.1，2026-06-20）—
    只有 proof_mode == anchor_first 的支才跑，其他直接 PASS。
    全程受 ANCHOR_FIRST_ENFORCE 控（False=WARN-only rollback 備用，True=FAIL；2026-06-23 已翻 True enforce-live）。
    誠實邊界：空泛詞偵測是 presence-only 啟發，語義判斷留 D1 抽審/人工。"""
    if data.get("proof_mode") != "anchor_first":
        return "PASS", f"{fname}: C-22b 非 anchor_first，跳過"

    severity = "FAIL" if ANCHOR_FIRST_ENFORCE else "WARN"
    problems: list[str] = []

    def _present(v: Any) -> bool:
        # 非純量（list/dict）視為未填——anchor 三欄必須是字串真料，不接受結構值（防 `anchor_ref: []` 偽充填）。
        if v is None or isinstance(v, (list, dict)):
            return False
        return str(v).strip() != ""

    def _norm_ref(v: Any) -> str:
        # dedup 正規化：路徑分隔 \ vs /、Windows 大小寫不敏感 → 抹平；
        # 但保留 §章節差異（不同章節＝不同真料點，本就該分開計，不抹）。
        return str(v).strip().replace("\\", "/").lower()

    anchor_ref = data.get("anchor_ref")
    anchor_cost = data.get("anchor_cost")
    because_bridge = data.get("because_bridge")

    # 1. anchor_ref 存在 + 不指向退役拼接本（最重要的確定性閘）
    if not _present(anchor_ref):
        problems.append("anchor_ref 缺填或空白（anchor_first 必填）")
    else:
        anchor_ref_s = str(anchor_ref).strip()
        # 退役拼接本檔名＝ _<業主>完整公版.generated.md：業主名插在 `_` 與「完整公版」之間，
        # 故不可用 endswith("_完整公版...")（會整批漏判）。改偵測 .generated.md 衍生標記
        # （substring：對路徑前綴 / §章節後綴都穩）。anchor 來源只能手寫 L0/L1/L2，
        # 不得指向任何 generated 衍生檔（含拼接本 / 小抄 / projection）。
        if ".generated.md" in anchor_ref_s.lower():
            problems.append(
                "anchor_ref 指向退役拼接本（.generated.md），禁用；"
                "請改指向 L2 偏好.md §9.5 voice_lock 或 L0/L1 真料段落"
            )
        # 防套路（same-batch）：同一 anchor_ref 同批 > 2 支（正規化後比對，見 _norm_ref）
        cur_ref_norm = _norm_ref(anchor_ref_s)
        same_batch = 0
        for _bf, _bd in yamls:
            if not isinstance(_bd, dict):
                continue
            if _bd.get("proof_mode") != "anchor_first":
                continue
            _br = _bd.get("anchor_ref")
            if _present(_br) and _norm_ref(_br) == cur_ref_norm:
                same_batch += 1
        if same_batch > 2:
            problems.append("同批 anchor_ref 重複 > 2 支（套路化風險）")

    # 2. anchor_cost 存在 + 非純空泛詞（presence-only 啟發）
    if not _present(anchor_cost):
        problems.append("anchor_cost 缺填")
    else:
        cost_s = str(anchor_cost).strip()
        VAPID_COST_WORDS = ["很努力", "很辛苦", "低谷", "成長", "堅持", "努力過", "撐過來"]
        if len(cost_s) < 20 and any(w in cost_s for w in VAPID_COST_WORDS):
            problems.append(
                "anchor_cost 疑似空泛詞，請填具體代價"
                "（例：戶頭剩三萬、第一次被屋主罵當場愣住）"
            )

    # 3. because_bridge 存在 + 含因果結構訊號
    if not _present(because_bridge):
        problems.append("because_bridge 缺填（因果橋必填）")
    else:
        bridge_s = str(because_bridge).strip()
        BRIDGE_SIGNALS = ["因為", "所以", "才懂", "那次", "讓我", "先看"]
        if not any(sig in bridge_s for sig in BRIDGE_SIGNALS):
            problems.append("because_bridge 缺因果結構（需含『因為…所以…』或等效句型）")

    # TODO(C-22b near-3-batch)：跨批 anchor_pool_exhausted（同 anchor_ref 近 3 批累計 > 4）
    #   需 owner 層跨批 anchor 歷史來源，現 validator 只有當批 yamls。
    #   薄料業主（< 3 批）本就只跑 same-batch ≤2、近批規則暫停，此 TODO 不影響薄料 pilot。
    #   待跨批歷史來源接上再補；補上時輸出訊息須含 token「anchor_pool_exhausted」供 D1 觸發。

    if problems:
        return severity, f"{fname}: " + "；".join(problems)
    return "PASS", f"{fname}: C-22b anchor_first 機械閘 PASS"


# ── chk_anchor_registry_ref（平行 shadow check，2026-06-20）──
# 說明：
#   - proof_mode == anchor_first 且 anchor_ref 形如 registry id（<owner>_aNN）時，
#     載入對應 owner 的 anchor registry，驗 id 存在 + owner match + anchor_first ∈ usable_for。
#   - 非 registry id 格式（free-text）→ 不干擾，走原 chk_c22b 路徑（向後相容）。
#   - 全 WARN-only（ANCHOR_FIRST_ENFORCE 不動）。
#   - chk_c22b_anchor_first 本體一字不改。
import re as _re_anchor

# registry id 格式：<owner>_aNN（英數底線開頭，_aNN 結尾）
_REGISTRY_ID_PAT = _re_anchor.compile(r'^[a-zA-Z0-9_]+_a\d+$')

# L2 業主層根目錄（anchor registry 搜尋起點）
_L2_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "L2_業主層"

# sandbox registry 根目錄（fallback）
_SANDBOX_ROOT = Path(__file__).resolve().parent.parent / "sandbox"


def _load_owner_registry(owner: str) -> Optional[dict]:
    """
    搜尋 anchor registry，以 yaml 內 owner_id 欄位匹配（不靠檔名）。
    理由：registry 檔名用業主中文名（如 _楷甯_anchor_registry.yaml），
          anchor_ref 用英文 owner_id（如 kaining），兩者不同。
    搜尋順序：L2_業主層 → sandbox。回 None = 找不到。
    """
    import yaml as _yaml_inner

    def _search_dir(root: Path) -> Optional[dict]:
        if not root.exists():
            return None
        for candidate in root.rglob("*_anchor_registry.yaml"):
            # 只找 derived/ 子目錄內的
            if "derived" not in candidate.parts:
                continue
            try:
                content = candidate.read_text(encoding="utf-8", errors="replace")
                data = _yaml_inner.safe_load(content)
                if isinstance(data, dict) and data.get("owner_id") == owner:
                    return data
            except Exception:
                pass
        return None

    result = _search_dir(_L2_ROOT)
    if result is not None:
        return result
    return _search_dir(_SANDBOX_ROOT)


def _find_owner_id_by_display(owner_display: str) -> Optional[str]:
    """
    透過中文業主顯示名（如「楷甯」）找對應的英文 owner_id。
    策略：在 L2_業主層 下掃所有 *_anchor_registry.yaml，
    找目錄名含 owner_display 字串的，取其 yaml 內 owner_id 欄位。
    回 None = 找不到（業主尚無 registry，或中文名對不上）。
    用途：chk_anchor_registry_ref 跨業主污染偵測——
    將本稿 owner（中文）解析成英文 owner_id，再與 ref_owner 比對。
    """
    import yaml as _yaml_inner

    if not owner_display or not _L2_ROOT.exists():
        return None

    for candidate in _L2_ROOT.rglob("*_anchor_registry.yaml"):
        if "derived" not in candidate.parts:
            continue
        # 目錄名含 owner_display（例：「房仲_楷甯」含「楷甯」）
        dir_names = [p.name for p in candidate.parents]
        if not any(owner_display in d for d in dir_names):
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
            data = _yaml_inner.safe_load(content)
            if isinstance(data, dict) and data.get("owner_id"):
                return str(data["owner_id"])
        except Exception:
            pass
    return None


def chk_anchor_registry_ref(
    data: dict,
    fname: str,
    owner: str = "",
) -> tuple[str, str]:
    """
    平行 shadow check（WARN-only）：
    proof_mode == anchor_first 且 anchor_ref 形如 registry id（<owner>_aNN）→
    載 registry 驗 id 存在 + owner match + anchor_first ∈ usable_for。

    非 registry id 格式的 free-text anchor_ref → 直接 PASS（不干擾 chk_c22b）。
    """
    if data.get("proof_mode") != "anchor_first":
        return "PASS", f"{fname}: chk_anchor_registry_ref 非 anchor_first，跳過"

    anchor_ref = data.get("anchor_ref", "")
    if not anchor_ref or not isinstance(anchor_ref, str):
        # anchor_ref 缺失由 chk_c22b 負責，這裡不重複
        return "PASS", f"{fname}: chk_anchor_registry_ref anchor_ref 缺失，由 C-22b 負責"

    anchor_ref_s = anchor_ref.strip()

    # 判斷是否為 registry id 格式
    if not _REGISTRY_ID_PAT.match(anchor_ref_s):
        # free-text → 不干擾，走原 chk_c22b
        return "PASS", f"{fname}: chk_anchor_registry_ref anchor_ref 為 free-text（非 registry id），走原 C-22b 路徑"

    # registry id 格式 → 取 owner 部分（去掉 _aNN 後綴）
    m = _re_anchor.match(r'^([a-zA-Z0-9_]+)_a\d+$', anchor_ref_s)
    if not m:
        return "WARN", f"{fname}: chk_anchor_registry_ref anchor_ref registry id 解析失敗（{anchor_ref_s!r}）"

    ref_owner = m.group(1)  # e.g. "kaining"

    # ── 跨業主污染偵測 + owner_unresolved fail-closed（2026-06-20 修 3）──
    # 本稿 owner（中文）→ 解析英文 owner_id → 比對 ref_owner。
    # 若本稿業主有 registry（有英文 owner_id）且 ref_owner ≠ 本稿 owner_id
    # → WARN 跨業主 anchor 污染（不載入別業主 registry 當合法素材）。
    # 若本稿 owner 解析不到（owner_id is None，尚無 registry 或名稱不符）
    # → WARN owner_unresolved，不放行 registry-id anchor（fail-closed 安全底座）。
    # owner 參數為中文業主名（如「楷甯」），_find_owner_id_by_display 透過目錄名比對轉英文 id。
    if owner:
        script_owner_id = _find_owner_id_by_display(owner)
        if script_owner_id is None:
            # fail-closed：本稿 owner 解析不到 → 不採信 registry-id anchor
            return "WARN", (
                f"{fname}: chk_anchor_registry_ref owner_unresolved — "
                f"本稿 owner={owner!r} 解析不到 owner_id（尚無 anchor registry 或名稱不符）；"
                f"anchor_ref={anchor_ref_s!r} 為 registry-id 格式，不放行（fail-closed）。"
                f"請建立 owner registry 或改用 free-text anchor_ref。"
            )
        if script_owner_id != ref_owner:
            return "WARN", (
                f"{fname}: chk_anchor_registry_ref 跨業主 anchor 污染 — "
                f"anchor_ref owner={ref_owner!r} 不等於本稿 owner={owner!r}（owner_id={script_owner_id!r}）；"
                f"anchor_ref={anchor_ref_s!r}。不載入別業主 registry 當合法素材。"
            )

    # 驗 anchor_ref 的 registry 存在
    registry = _load_owner_registry(ref_owner)
    if registry is None:
        return "WARN", (
            f"{fname}: chk_anchor_registry_ref needs_owner_material — "
            f"找不到 owner={ref_owner!r} 的 anchor registry；"
            f"anchor_ref={anchor_ref_s!r}"
        )

    # 從 registry 建 id → anchor 快查
    anchors = registry.get("anchors", [])
    if not isinstance(anchors, list):
        return "WARN", f"{fname}: chk_anchor_registry_ref registry anchors 格式錯誤（owner={ref_owner}）"

    anchor_map = {
        str(a.get("anchor_id", "")): a
        for a in anchors
        if isinstance(a, dict)
    }

    if anchor_ref_s not in anchor_map:
        return "WARN", (
            f"{fname}: chk_anchor_registry_ref needs_owner_material — "
            f"anchor_id {anchor_ref_s!r} 在 registry 中不存在（owner={ref_owner}，"
            f"現有 id: {sorted(anchor_map.keys())}）"
        )

    anchor_entry = anchor_map[anchor_ref_s]

    # 驗 owner match（registry 內的 owner_id）
    entry_owner_id = anchor_entry.get("owner_id", "")
    if entry_owner_id and entry_owner_id != ref_owner:
        return "WARN", (
            f"{fname}: chk_anchor_registry_ref anchor owner_id 不一致 — "
            f"anchor.owner_id={entry_owner_id!r} 但 anchor_ref prefix={ref_owner!r}"
        )

    # 驗 anchor_first ∈ usable_for
    usable_for = anchor_entry.get("usable_for", [])
    if not isinstance(usable_for, list):
        usable_for = [usable_for] if usable_for else []
    if "anchor_first" not in usable_for:
        return "WARN", (
            f"{fname}: chk_anchor_registry_ref anchor_id {anchor_ref_s!r} 的 usable_for "
            f"不含 anchor_first（usable_for={usable_for}）；不適合作 anchor_first 素材"
        )

    return "PASS", (
        f"{fname}: chk_anchor_registry_ref PASS — "
        f"anchor_id={anchor_ref_s!r} 存在，owner={ref_owner!r}，anchor_first ∈ usable_for"
    )


def _s22_batch_date(yamls: list[tuple[Path, dict]]) -> Optional[_dt.date]:
    """取批次日期（批內取最大值，沿用 _extract_batch_date 逐支邏輯）。
    回 None = 無法判斷日期。與 _s21_batch_date 同邏輯、獨立命名避免耦合。"""
    dates: list[_dt.date] = []
    for f, data in yamls:
        if not isinstance(data, dict):
            continue
        if "__parse_error__" in data or "__schema_error__" in data:
            continue
        d = _extract_batch_date(data, f"{f.parent.name}/{f.name}")
        if d:
            dates.append(d)
    return max(dates) if dates else None


# ── C-offpro-placeholder（2026-06-21；2026-06-23 enforce flip）──
# 台詞占位符守門：台詞欄含 [需確認]/[需提供]/[需XX確認] → off-pro 稿 FAIL、本業稿 WARN。
# 豁免：只掃台詞欄位（台詞 / 台詞_*），不掃 source_ref/claim_ledger/metadata。
# 2026-06-23 翻 enforce（_OFFPRO_PLACEHOLDER_ENFORCE=True）：severity off-pro-aware（見 chk_offpro_placeholder）。
import re as _re_placeholder
_PLACEHOLDER_PAT = _re_placeholder.compile(r'\[需[^\]]*(?:確認|提供)[^\]]*\]')


def _is_offpro_marker(data: dict) -> bool:
    """目標5（2026-06-22）：off-pro 立場稿偵測單一真理源（防 4 處偵測式漂移）。
    🔁 PARITY（Codex R6）：規則須與 taste_panel.derive_gate_context 的 is_offpro **完全一致**
       （lane=="stance" OR proof_mode=="voice_first"，皆 strip/lower）；跨 process 無法共用 import，
       靠 _目標5_verify_unit.py 的 parity 測 + 本註解守。改一邊必改另一邊 + 跑 parity 測。
    偵測 = lane=="stance"（結構標記、目標4 lane 權威、向後相容）
         OR proof_mode=="voice_first"（目標5 正式第 4 型 proof_mode）。
    OR 語意 fail-safe：任一標記在即認 off-pro；皆無 → 非 off-pro、走較嚴舊路徑（不錯放）。
    normalize 大小寫/空白。本業稿無 lane 也無 voice_first → False（byte 不變保證）。
    ⚠️ shadow：本 helper 只供 off-pro WARN-only check 分流；不參與任何 enforce 放行判斷
       （provenance/gate_profile 簽章驗證留 6/24 enforce flip，見 目標5 設計 §8）。
    """
    lane = str(data.get("lane", "") or "").strip().lower()
    proof_mode = str(data.get("proof_mode", "") or "").strip().lower()
    return lane == "stance" or proof_mode == "voice_first"


# ── C-offpro-leak（2026-06-21；目標5 2026-06-22 改用 _is_offpro_marker 收斂偵測）──
# off-pro 本業詞守門：off-pro 立場稿（lane=stance / proof_mode=voice_first）台詞含高度本業詞 → WARN。
# off-pro-aware：非 off-pro 直接 PASS 跳過，防誤殺本業稿。
# 詞庫精縮（高度本業 + 低誤殺，禁收泛用中性詞如「客人/業務」）。
_OFFPRO_LEAK_WORDS: dict[str, list[str]] = {
    "房仲": ["成交", "屋主", "帶看", "陌生開發", "陌生電話", "簽約", "買房"],
    "美容": ["膚況", "做臉", "療程", "醫美"],
}
# 合併全詞庫供掃描（不分業主 — 都是本業詞，off-pro 稿不應出現）
_ALL_LEAK_WORDS: list[str] = sum(_OFFPRO_LEAK_WORDS.values(), [])

# ── §8#8 enforce 前置硬化（2026-06-23，保鏢 GO-with-condition 條件；Codex R1/R2 修）──
# 翻 _OFFPRO_LEAK_ENFORCE=True 前必補：①掃所有 publish-visible 欄（原只掃台詞＝洩漏點，遞迴跳內部欄）
#   ②去混淆 normalize（NFKC 全半形/相容字 + 去零寬字元；**刻意保留一般空白避 cross-word FP**，
#     如「完成 交流」不誤判含「成交」；零寬無合法用途、放心去）。可見空白拆字靠人工複審。
import unicodedata as _ud_offpro


def _deobfuscate(text: str) -> str:
    """去混淆：NFKC（全形→半形/相容字）+ 去零寬字元；**刻意保留一般空白避 cross-word FP**
    （「完成 交流」不誤判含「成交」；零寬無合法用途、放心去）。供本業詞比對前 normalize。"""
    if not text:
        return ""
    norm = _ud_offpro.normalize("NFKC", str(text))
    return re.sub(r"[​‌‍﻿]+", "", norm)


# 詞庫預先去混淆（與待掃文字同口徑比對）
_ALL_LEAK_WORDS_NORM: list[tuple[str, str]] = [(_deobfuscate(w), w) for w in _ALL_LEAK_WORDS]


# §8#8（Codex R2 P1 + R4 P2）：遞迴收葉值時跳過非 publish 內部欄（避 FP：asset_path/url/reason/note/hash/id/thumbnail/utm…）。
_OFFPRO_LEAF_SKIP_EXACT = {
    "asset_path", "path", "url", "uri", "link", "href", "img", "image", "id", "uuid",
    "sha256", "hash", "reason", "note", "internal_note", "disabled_reason", "debug",
    "metadata", "meta", "source", "source_ref", "schema_version", "version",
    "thumbnail", "cover", "tracking", "utm", "utm_source", "utm_campaign", "utm_medium",
}
_OFFPRO_LEAF_SKIP_SUFFIX = ("_path", "_url", "_uri", "_id", "_ref", "_note", "_reason",
                            "_hash", "_sha", "_at", "_ts", "_thumbnail", "_cover")

# 巢狀超深 fail-closed 哨兵（Codex R4 P2）
_OFFPRO_NEST_OVERFLOW = "\x00__offpro_nest_overflow__\x00"
# 整個值像 URL/檔案路徑/asset → 非 publish copy、跳過不掃（Codex R4 P2，防 thumbnail/asset 路徑含本業詞誤判）
_OFFPRO_ASSET_VALUE_RE = re.compile(
    r"^\s*(?:https?://|//|/|\./|\.\./|[A-Za-z]:[\\/]|assets?[\\/]|[\w./\\-]+\.(?:png|jpe?g|gif|webp|svg|mp4|mov|pdf|ico|json|ya?ml|css|js))\s*$",
    re.IGNORECASE,
)


def _skip_offpro_leaf_key(k) -> bool:
    kl = str(k).lower()
    return kl in _OFFPRO_LEAF_SKIP_EXACT or kl.endswith(_OFFPRO_LEAF_SKIP_SUFFIX)


def _is_offpro_asset_value(s: str) -> bool:
    """整個值像 URL/檔案路徑/asset → 非 publish copy、跳過（避免 thumbnail/asset 路徑含本業詞誤判）。"""
    return bool(_OFFPRO_ASSET_VALUE_RE.match(s))


def _collect_str_leaves(obj, prefix, out, _depth=0, _seen=None) -> None:
    """§8#8（Codex R1 P1-2 + R2 P1）：遞迴收 obj 內 publish str 葉值 → out.append((path, text))。
    防巢狀藏本業詞（dm_card.body.text / platform_variants.ig.cta）。
    R2 收嚴：①跳過非 publish 內部欄（_skip_offpro_leaf_key：asset_path/url/reason/note/hash…）
            ②depth guard（max 20）+ cycle guard（seen id）防 YAML anchor 自參照 → RecursionError。"""
    if _depth > 40:
        # Codex R4 P2：超深巢狀 fail-closed — append 哨兵讓 chk_offpro_leak 對 off-pro 標 hit（無法完整掃描）
        out.append((f"{prefix}.<overflow>", _OFFPRO_NEST_OVERFLOW))
        return
    if _seen is None:
        _seen = set()
    if isinstance(obj, (dict, list, tuple)):
        _oid = id(obj)
        if _oid in _seen:
            return
        _seen.add(_oid)
    if isinstance(obj, str):
        if obj and not _is_offpro_asset_value(obj):
            out.append((prefix, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if _skip_offpro_leaf_key(k):
                continue
            _collect_str_leaves(v, f"{prefix}.{k}", out, _depth + 1, _seen)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _collect_str_leaves(v, f"{prefix}[{i}]", out, _depth + 1, _seen)


# off-pro 稿 scene 級 publish-visible 文字欄（Codex R1 P1-1 擴充，原只台詞/翠文；算盤覆核補中文鍵 藏鏡人）。
# 刻意不含「畫面」（拍攝指示非公開字幕、非 publish-visible）。
# 🔴 藏鏡人＝公開 hook 字幕（生產 130/172 支用），原漏（whitelist 只有英文 offscreen_interaction＝0 生產用）→ 算盤抓到補。
_OFFPRO_SCENE_TEXT_KEYS = ("台詞", "翠文", "字幕", "旁白", "藏鏡人", "dialogue", "subtitle", "offscreen_interaction")


def _offpro_publish_fields(data: dict) -> list[tuple[str, str]]:
    """§8#8（Codex R1 P1 擴充 + 算盤覆核補 藏鏡人/cta）：收 off-pro 稿主要 publish-visible 欄 → [(label, raw), ...]。
    scene：台詞_* / 翠文 / 字幕 / 旁白 / 藏鏡人 / dialogue / subtitle / offscreen_interaction；
    top：title / 標題 / caption / 收束 / 結尾 / hashtag(s)；
    巢狀（遞迴 str 葉值，跳內部欄）：dm_card / platform_variants / cta。
    off-pro 立場稿任一公開欄都不該出現本業詞 → 掃主要 publish 欄。
    刻意排除：畫面（拍攝指示）/ source_ref / claim_ledger / metadata / score_type 等非 publish 欄。"""
    out: list[tuple[str, str]] = []
    _scenes = data.get("scenes") or []
    if not isinstance(_scenes, list):
        _scenes = []
    for scene in _scenes:
        if not isinstance(scene, dict):
            continue
        for key, val in scene.items():
            if not val:
                continue
            ks = str(key)
            # Codex R2 P1：收嚴 — 只認 台詞_<業主> + 明確 publish 文字欄；排除 台詞備註/台詞數 等內部欄
            if ks.startswith("台詞_") or ks in _OFFPRO_SCENE_TEXT_KEYS:
                out.append((ks, str(val)))
    for key in ("title", "標題", "caption", "收束", "結尾"):
        v = data.get(key)
        if v:
            out.append((key, str(v)))
    for key in ("hashtag", "hashtags"):
        v = data.get(key)
        if isinstance(v, list):
            joined = " ".join(str(x) for x in v if x)
            if joined:
                out.append((key, joined))
        elif v:
            out.append((key, str(v)))
    # 巢狀結構遞迴收 str 葉值（dm_card 巢狀 dict / platform_variants 各平台 / top-level cta.message·keyword）
    for nested_key in ("dm_card", "platform_variants", "cta"):
        nv = data.get(nested_key)
        if nv is not None:
            _collect_str_leaves(nv, nested_key, out)
    return out


def _should_check_offpro_leak(data: dict) -> bool:
    # R4 Fix 2（2026-06-24）：content_axis lower-normalize（對齊其他四處）
    axis = str(data.get("content_axis", "") or "").strip().lower()
    if axis in {"offpro", "personal_anchor"}:
        return True
    if axis == "professional":
        return False
    return _is_offpro_marker(data)


# ── C-22-OFFPRO-ANGLE：off-pro 寫稿前角度守門（2026-06-24 建；Phase 0 shadow）──
# 投影 §22.3/§22.4/§22.9/§22.9.1 反一般化欄位成 validator 可讀的 c22_offpro_angle_stub。
# 只對 off-pro 立場稿觸發（_is_offpro_marker：lane=stance / proof_mode=voice_first）；
# 其他稿直接 PASS 跳過，不影響本業/demand_first/anchor_first。
# 10 個錯誤碼：001-010（各自偵測、可多項命中、串接進 message）。
# _C22_OFFPRO_ANGLE_ENFORCE=False（Phase 0）：所有 FAIL 降 WARN；=True 後照錯誤碼定義。
# 006 NO_BEHAVIOR_DELTA 永遠 WARN（不受 enforce flag 影響，pilot 後才升 FAIL）。

# 溫共識詞庫（seed；TODO：可由 config 擴充）
_C22_OFFPRO_SOFT_CONSENSUS: list[str] = [
    "被看見", "先看人", "情緒在場", "做自己", "愛要看行動",
    "活在當下", "慢慢來就好", "好好愛自己", "真誠最重要", "陪伴最重要",
    "初心", "正能量", "換位思考", "珍惜當下", "勇敢做自己",
]

# 對比標記（任一出現代表有取捨，003 不因溫共識詞單獨命中而 FAIL）
_C22_OFFPRO_CONTRAST_MARKERS: list[str] = [
    "不是", "而是", "不看", "與其", "不如", "寧可", "真正的", "才是", "不在",
]

# 寬泛詞集（007 audience_decision_moment 太寬泛判斷）
# Codex R1 P1 修（2026-06-24）：加 任何人/所有的人/大眾/上班族；不加「…的人」泛 pattern 避誤殺具體受眾。
# Codex R2 P2 修（2026-06-24）：加 所有上班族/每個正在努力的人/正在努力的人（明確泛詞，不加可誤殺具體受眾的 pattern）。
_C22_OFFPRO_BROAD_AUDIENCE: set[str] = {
    "大家", "人人", "每個人", "所有人", "所有的人", "年輕人", "觀眾",
    "現代人", "這個世代", "我們", "你們", "社會大眾",
    "任何人", "大眾", "上班族",
    "所有上班族", "每個正在努力的人", "正在努力的人",
}


def _c22_normalize(text: str) -> str:
    """正規化：strip + 去全形空白。字串比較用此結果。"""
    if not text:
        return ""
    return str(text).strip().replace("　", "").strip()


def _should_check_c22_offpro_angle(data: dict) -> bool:
    """Codex R1 P0 修（2026-06-24）：off-pro 角度守門的精確觸發 gate。
    ⚠️  **不要動 _is_offpro_marker**（parity 綁 taste_panel）。
        本 gate 比 _is_offpro_marker 更窄：排除 anchor/demand_first/proof_first
        這些 proof_mode，以及 content_axis 非 offpro 的稿（legacy/professional 不套角度檢查）。

    觸發規則：
      1. content_axis == "offpro"（或 content_axis 不存在時不排除）
      2. lane 不在 {"anchor","anchor_first"}
      3. proof_mode 不在 {"anchor_first","demand_first","proof_first"}
      4. lane=="voice_first" 或 lane=="stance" 或 proof_mode=="voice_first"
         → 至少命中其一才觸發（避免 legacy 稿誤套）

    修正 P0.1 proof_mode 繞過 + P1 content_axis 誤套 legacy/professional 問題。
    W2-D20（2026-07-13）：排除清單移除 "professional"——它是 lane 值非 proof_mode
    （proof_mode=professional 已被 D20-proof-mode-enum 前置硬 FAIL）。
    """
    axis = str(data.get("content_axis", "") or "").strip().lower()
    lane = str(data.get("lane", "") or "").strip().lower()
    proof = str(data.get("proof_mode", "") or "").strip().lower()

    # content_axis 明確是非 offpro 業務稿（professional / personal_anchor / 本業類）→ 不套
    if axis and axis not in ("offpro",):
        return False
    # lane 是 anchor 型 → 不套
    if lane in ("anchor", "anchor_first"):
        return False
    # proof_mode 明確是非 voice_first 型 → 不套
    if proof in ("anchor_first", "demand_first", "proof_first"):
        return False
    # 至少要命中一個 off-pro 立場訊號才觸發
    return lane in ("voice_first", "stance") or proof == "voice_first"


# ── D20 proof_mode 四型白名單（W2-D20 2026-07-13；決策卡=state\decision_cards\W2-D20\card.md）──
_D20_PROOF_MODE_CANONICAL = ("proof_first", "demand_first", "anchor_first", "voice_first")

# ── K11（2026-07-16）：lane → proof_mode derive-lock 映射，提升為 module-level 常數
# （原為 chk_hybrid_plan_lock 函式內區域 dict；同 dict 同值＝行為零變的單檔內重構）。
# 補回 "professional": "proof_first"（撤刻意排除）——本業稿 proof_mode 現由此表統一鎖
# proof_first，供 chk_hybrid_plan_lock derive-lock 消費段與 fixtures 直接斷言真常數。
_LANE_TO_PROOF = {
    "voice_first": "voice_first",
    "stance": "voice_first",
    "demand_first": "demand_first",
    "anchor_first": "anchor_first",
    "professional": "proof_first",  # K11：撤刻意排除，professional lane 統一鎖 proof_first
}


def _is_hybrid_batch(batch_dir: Path, yamls: list[tuple]) -> bool:
    """D20 批次級世代偵測（照 _is_skeleton_mode 同模式，批級算一次傳入 per-file checks）。
    hybrid_batch=True 條件：批次夾存在 topic_plan.json，或批內任一 yaml 有
    proof_mode / lane / content_axis 任一鍵。全批零標記＝hybrid schema 世代前的純 legacy 批，
    D20-proof-mode-enum 回 not-applicable（legacy_pre_hybrid_batch）。
    批級偵測讓單檔 serializer 誤刪鍵不會把該檔變豁免（兄弟檔＋topic_plan.json 仍標記全批）。
    """
    try:
        if (batch_dir / "topic_plan.json").exists():
            return True
    except OSError:
        pass
    for _, data in yamls:
        if not isinstance(data, dict):
            continue
        if any(k in data for k in ("proof_mode", "lane", "content_axis")):
            return True
    return False


def _d20_resolve_proof_mode(data: dict) -> tuple[str, str]:
    """D20 純函式 resolver：回 (verdict, detail_core)；verdict ∈ PASS / DERIVED / FAIL / LANE_MISMATCH
    （K11 2026-07-16 新增 LANE_MISMATCH：professional lane 但 proof_mode≠proof_first）。
    零 normalize：不 strip、不 lower——canonical 值由 allocator/skeleton 機器寫入，
    出現空白/大小寫變體＝上游壞掉，該擋。derive 僅限「鍵整個缺」且 lane 精確 == professional
    （產有效值 proof_first、只驗不回寫）；null / 空字串 / 非字串型別永不 derive。
    """
    if "proof_mode" not in data:
        if data.get("lane") == "professional":
            return "DERIVED", "effective=proof_first; source=lane-derived"
        return "FAIL", "proof_mode 鍵缺且 lane≠professional（四型白名單缺值硬 FAIL）"
    val = data["proof_mode"]
    if not isinstance(val, str):
        return "FAIL", f"proof_mode 非字串型別（{type(val).__name__}）— 四型白名單外硬 FAIL"
    if val in _D20_PROOF_MODE_CANONICAL:
        # K11：白名單內但 lane=professional 且值≠proof_first → LANE_MISMATCH（不是 PASS）
        if data.get("lane") == "professional" and val != "proof_first":
            return "LANE_MISMATCH", (
                f"proof_mode={val} 與 lane=professional 不符; expected=proof_first（K11）"
            )
        return "PASS", f"proof_mode={val}"
    return "FAIL", (
        f"proof_mode={val!r} 不在四型白名單 {list(_D20_PROOF_MODE_CANONICAL)}"
        "（未知值硬 FAIL；professional 是 lane 值、對應 proof_mode=proof_first）"
    )


def _c22_code_severity(code: str) -> str:
    """依 _C22_OFFPRO_ANGLE_ENFORCE_CODES 判斷單碼 severity。
    006 永遠 WARN；其餘：code 在集合內 → FAIL，否則 WARN（Phase 0 空集合=全 WARN）。
    """
    if code == "006":
        return "WARN"
    return "FAIL" if code in _C22_OFFPRO_ANGLE_ENFORCE_CODES else "WARN"


def _c22_collect_script_text(data: dict) -> str:
    """從 scenes 收集台詞欄（台詞 / 台詞_*）全文，供 stub binding 比對。
    不依賴外部 helper（_all_scene_text 不存在），直接遍歷 scenes。
    """
    parts: list[str] = []
    scenes = data.get("scenes") or []
    if not isinstance(scenes, list):
        return ""
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        for key, val in scene.items():
            if key != "台詞" and not str(key).startswith("台詞_"):
                continue
            if val:
                parts.append(str(val))
    return " ".join(parts)


def chk_c22_offpro_angle(data: dict, fname: str) -> tuple[str, str]:
    """C-22-OFFPRO-ANGLE：off-pro 寫稿前角度守門（2026-06-24 建；Phase 0 shadow）。
    Codex R1 P0/P1 修（2026-06-24）：
      - 改用 _should_check_c22_offpro_angle gate（精確觸發，排除 anchor/demand/professional）
      - 11 欄全驗（新增 011 MISSING_TOPIC / 012 MISSING_CONCRETE_SCENE / 013 MISSING_TIMELINESS）
      - 所有字串欄用 _is_placeholder 偵測，placeholder 視同缺欄
      - 014 SHARP_CLAIM_NOT_IN_SCRIPT：sharp_claim 須是台詞的子字串
      - phase-based enforce：_C22_OFFPRO_ANGLE_ENFORCE_CODES 集合決定哪些碼 FAIL
      - 010 加 bool 型別守門 + >5 值非法
      - 008 改為 substring echo（rebuttal 包含 sharp_claim 也 FAIL）
      - 006 NO_BEHAVIOR_DELTA 永遠 WARN（不受 enforce 集合影響）
    """
    if not _should_check_c22_offpro_angle(data):
        return ("PASS", f"{fname}: C-22-OFFPRO-ANGLE 非 off-pro 立場稿，N/A")

    stub = data.get("c22_offpro_angle_stub")
    errors: list[str] = []  # 命中的 "[碼] 說明" 串
    error_codes: list[str] = []  # 對應碼，決定 severity

    # ── 001 MISSING_STUB：stub 缺 / 非 dict ──
    if not stub or not isinstance(stub, dict):
        errors.append("[001] c22_offpro_angle_stub 缺或非 dict")
        error_codes.append("001")
        sev = _c22_code_severity("001")
        return (sev, f"{fname}: C-22-OFFPRO-ANGLE {sev}（shadow）— {'; '.join(errors)}")

    def _missing_or_placeholder(key: str) -> bool:
        """欄位不存在 / 空白 / _is_placeholder / 非 scalar → True。
        Codex R2 P2 修（2026-06-24）：list/dict 值視為非法缺欄（不 str() 當有效）。
        """
        v = stub.get(key)
        if v is None:
            return True
        # list/dict 非 scalar → 視為缺欄（防 YAML anchor 或手寫錯誤混入）
        if isinstance(v, (list, dict)):
            return True
        if _is_placeholder(v):
            return True
        return not bool(_c22_normalize(str(v)))

    # ── 011 MISSING_TOPIC ──
    if _missing_or_placeholder("topic"):
        errors.append("[011] topic 空白或 placeholder")
        error_codes.append("011")

    # ── 012 MISSING_CONCRETE_SCENE ──
    if _missing_or_placeholder("concrete_scene"):
        errors.append("[012] concrete_scene 空白或 placeholder")
        error_codes.append("012")

    # ── 013 MISSING_TIMELINESS ──
    if _missing_or_placeholder("timeliness_or_context"):
        errors.append("[013] timeliness_or_context 空白或 placeholder")
        error_codes.append("013")

    # ── 002 GENERIC_TAKE_MISSING ──
    generic_take_raw = stub.get("generic_take", "")
    if _missing_or_placeholder("generic_take"):
        errors.append("[002] generic_take 空白或 placeholder")
        error_codes.append("002")
        generic_take = ""
    else:
        generic_take = _c22_normalize(str(generic_take_raw))

    # ── 003 CLAIM_NOT_NON_OBVIOUS ──
    sharp_claim_raw = stub.get("sharp_claim", "")
    if _missing_or_placeholder("sharp_claim"):
        errors.append("[003] sharp_claim 空白或 placeholder")
        error_codes.append("003")
        sharp_claim = ""
    elif generic_take and _c22_normalize(str(sharp_claim_raw)) == generic_take:
        errors.append("[003] sharp_claim 正規化後 == generic_take（原文照抄）")
        error_codes.append("003")
        sharp_claim = _c22_normalize(str(sharp_claim_raw))
    else:
        sharp_claim = _c22_normalize(str(sharp_claim_raw))
        # 003 保守版（P1 修 9）：溫共識詞庫命中 AND 無對比標記
        # 若去掉對比標記後 sharp_claim 仍被溫共識詞主導 → FAIL；
        # 保守：只在沒有任何對比標記時才判；有對比就認為有取捨
        hit_consensus = any(w in sharp_claim for w in _C22_OFFPRO_SOFT_CONSENSUS)
        has_contrast = any(m in sharp_claim for m in _C22_OFFPRO_CONTRAST_MARKERS)
        if hit_consensus and not has_contrast:
            matched = [w for w in _C22_OFFPRO_SOFT_CONSENSUS if w in sharp_claim]
            errors.append(f"[003] sharp_claim 命中溫共識（{'/'.join(matched[:3])}）且無對比標記")
            error_codes.append("003")

    # ── 004 NO_REJECTED_BELIEF ──
    if _missing_or_placeholder("rejected_common_belief"):
        errors.append("[004] rejected_common_belief 空白或 placeholder")
        error_codes.append("004")

    # ── 005 NO_COST ──
    if _missing_or_placeholder("tradeoff_or_cost"):
        errors.append("[005] tradeoff_or_cost 空白或 placeholder")
        error_codes.append("005")

    # ── 006 NO_BEHAVIOR_DELTA（永遠 WARN，不受 enforce codes）──
    if _missing_or_placeholder("behavior_delta"):
        errors.append("[006] behavior_delta 空白或 placeholder（永遠 WARN）")
        error_codes.append("006")

    # ── 007 AUDIENCE_TOO_BROAD ──
    audience_raw = stub.get("audience_decision_moment", "")
    if _missing_or_placeholder("audience_decision_moment"):
        errors.append("[007] audience_decision_moment 空白或 placeholder")
        error_codes.append("007")
    else:
        audience = _c22_normalize(str(audience_raw))
        if audience in _C22_OFFPRO_BROAD_AUDIENCE:
            errors.append(f"[007] audience_decision_moment 寬泛詞「{audience}」")
            error_codes.append("007")

    # ── 008 NO_REAL_REBUTTAL（P1 修 7：substring echo 也 FAIL）──
    rebuttal_raw = stub.get("opposing_rebuttal", "")
    if _missing_or_placeholder("opposing_rebuttal"):
        errors.append("[008] opposing_rebuttal 空白或 placeholder")
        error_codes.append("008")
    else:
        rebuttal = _c22_normalize(str(rebuttal_raw))
        if sharp_claim and rebuttal == sharp_claim:
            errors.append("[008] opposing_rebuttal 正規化後 == sharp_claim（完全回聲）")
            error_codes.append("008")
        elif sharp_claim and len(sharp_claim) >= 4 and sharp_claim in rebuttal:
            errors.append(f"[008] opposing_rebuttal 包含 sharp_claim 為子字串（trivial echo）")
            error_codes.append("008")
        # Codex R2 P2 修（2026-06-24）：雙向子字串 — sharp_claim 是 rebuttal 的子字串也算回聲
        elif sharp_claim and len(rebuttal) >= 4 and rebuttal in sharp_claim:
            errors.append(f"[008] sharp_claim 包含 opposing_rebuttal 為子字串（reverse echo）")
            error_codes.append("008")

    # ── 009 TITLE_NO_GAP ──
    title_gap_raw = stub.get("title_gap", "")
    if _missing_or_placeholder("title_gap"):
        errors.append("[009] title_gap 空白或 placeholder")
        error_codes.append("009")
    else:
        title_gap = _c22_normalize(str(title_gap_raw))
        topic_norm = _c22_normalize(str(stub.get("topic", "") or ""))
        title_norm = _c22_normalize(str(data.get("title", "") or ""))
        if topic_norm and title_gap == topic_norm:
            errors.append("[009] title_gap 正規化後 == topic（只是重述 topic）")
            error_codes.append("009")
        elif title_norm and title_gap == title_norm:
            errors.append("[009] title_gap 正規化後 == yaml title（只是重述 title）")
            error_codes.append("009")

    # ── 010 VOICE_REMOVED_LT4（P1 修 8：加 bool 守門 + >5 非法）──
    vr = stub.get("voice_removed")
    if not vr or not isinstance(vr, dict):
        errors.append("[010] voice_removed 缺或非 dict")
        error_codes.append("010")
    else:
        for sub_key in ("concreteness", "stance_sharpness", "replacement_loss"):
            val = vr.get(sub_key)
            if val is None:
                errors.append(f"[010] voice_removed.{sub_key} 缺")
                error_codes.append("010")
            elif isinstance(val, bool):
                # bool 是 int 子類，須先排除（True/False 不算有效整數評分）
                errors.append(f"[010] voice_removed.{sub_key}=bool（{val}），應為 int 0-5")
                error_codes.append("010")
            elif not isinstance(val, int):
                errors.append(f"[010] voice_removed.{sub_key} 非 int（{type(val).__name__}）")
                error_codes.append("010")
            elif val < 0 or val > 5:
                errors.append(f"[010] voice_removed.{sub_key}={val} 值非法（應 0-5）")
                error_codes.append("010")
            elif val < 4:
                errors.append(f"[010] voice_removed.{sub_key}={val} < 4")
                error_codes.append("010")

    # ── 014 SHARP_CLAIM_NOT_IN_SCRIPT（P0 修 4：stub binding）──
    # sharp_claim 須出現在台詞中（否則角度沒進台詞、一張自證的表無法保證落地）
    # Codex R2 P1.4 修（2026-06-24）：補 new_answer.quote path —
    #   stub.new_answer.quote（若存在）正規化後 == sharp_claim → 亦視為落地 PASS
    # 僅在 sharp_claim 有實際值（非 placeholder/空）時才驗
    if sharp_claim and len(sharp_claim) >= 4:
        script_text = _c22_collect_script_text(data)
        # R3 Fix 2（2026-06-24）：014 binding — sharp_claim 必須直接出現在最終台詞中。
        # 移除 new_answer.quote substitution path（quote 只是 source annotation，不可替代台詞落地）。
        # 若 script_text 空（骨架 / 尚未填台詞）→ 不觸發 014，讓骨架正常通過。
        _in_script = script_text and sharp_claim in _c22_normalize(script_text)
        if script_text and not _in_script:
            errors.append(f"[014] sharp_claim 未出現在台詞中（角度沒落地 — 請將核心主張嵌入台詞）")
            error_codes.append("014")

    # ── 收斂最終 status ──
    if not errors:
        return ("PASS", f"{fname}: C-22-OFFPRO-ANGLE PASS（角度 stub 齊、無 generic 訊號）")

    # 決定最終 severity：取所有命中碼中最嚴的
    # 006 永遠 WARN；其餘碼若在 ENFORCE_CODES 集合 → FAIL
    unique_codes = list(dict.fromkeys(error_codes))  # 去重保序
    severities = [_c22_code_severity(c) for c in unique_codes]
    final_status = "FAIL" if "FAIL" in severities else "WARN"

    return (final_status,
            f"{fname}: C-22-OFFPRO-ANGLE {final_status}（shadow）— {'; '.join(errors)}")


HYBRID_BATCH_PROFILE = "hybrid_70_15_15"
_HYBRID_PROF_TYPES = {
    "seller_preparation",
    "pricing",
    "market_basic",
    "transaction_risk",
    "contract_tax_loan_basic",
    "viewing_listing_logic",
    # 美容業擴充（2026-07-07 保鏢 GO-cond 快審過；來源＝昀臻第14批編劇需求註解，非霸告獨創；
    # 水平加值不改檢查邏輯 — 產業通用、禁業主 hardcode 紅線不變）
    "skin_condition_basic",
    "product_usage_logic",
    "treatment_expectation",
    "daily_care_routine",
    "service_selection_logic",
    "pricing_value_basic",
}
_OFFPRO_CTA_SCOPES = {"none", "self_check", "discussion_prompt", "save_share", "auxiliary_asset"}
_PRO_CTA_SCOPES = {"none", "self_check", "save_share", "soft_consultation", "auxiliary_asset"}
# Codex R2 P0.2 修（2026-06-24）：off-pro CTA policy enforce flag
# 預設 False（shadow WARN-only）；澤君拍板後改 True。
# 通用、無業主 hardcode；L2 只能縮緊不能放寬此脫鉤成交紅線。
_OFFPRO_CTA_POLICY_ENFORCE: bool = False
_HYBRID_CAUSAL_WORDS = ("因為", "所以", "因此", "才會", "導致", "讓", "如果", "就")
_HYBRID_STRAWMAN_WORDS = ("大家都說", "一般人以為")
_HYBRID_WITHHELD_WORDS = ("私訊", "LINE", "line", "加賴", "諮詢", "PDF", "清單", "名單", "表單", "領取", "下載")
_HYBRID_PRESSURE_WORDS = ("立刻", "馬上", "限時", "現在就", "趕快", "只到今天")
_HYBRID_WORK_WORDS = tuple(_ALL_LEAK_WORDS) + ("客戶", "帶看", "成交", "委託", "簽約", "貸款", "行情")
_OFFPRO_CTA_HARD_BLOCK_RE = re.compile(
    r"私訊|私信|傳訊|DM|dm|敲我|加\s*(?:LINE|line|賴)|(?:^|[^A-Za-z])LINE(?:$|[^A-Za-z])|"
    r"(?:^|[^A-Za-z])line(?:$|[^A-Za-z])|預約|諮詢|咨詢|問我|找我聊|領答案|拿答案|"
    r"領取答案|索取答案|LINE\s*(?:清單|名單|列表|表單|群)",
    re.IGNORECASE,
)
_OFFPRO_CTA_HARD_BLOCK_TERMS = (
    "私訊", "私我", "密我", "賴我", "加賴", "小盒子", "DM", "dm", "inbox",
    "direct message", "敲我", "傳訊", "私聊", "諮詢", "預約", "LINE", "line",
    "加LINE", "加line", "consultation", "consult", "schedule a consult",
    "schedule a call", "book a consult", "message me", "contact me", "book a call",
    "call me", "dm me", "pm me", "text me", "whatsapp", "wechat", "加微信",
)


def _offpro_cta_norm(text: str) -> str:
    text = _deobfuscate(text or "").lower()
    return "".join(ch for ch in text if re.match(r"[a-z0-9\u3400-\u9fff\uf900-\ufaff]", ch))


def _offpro_cta_hard_blocked(text: str) -> bool:
    compact = _offpro_cta_norm(text)
    if not compact:
        return False
    for term in _OFFPRO_CTA_HARD_BLOCK_TERMS:
        token = _offpro_cta_norm(term)
        if token and token in compact:
            return True
    return False


_CTA_ACTION_LEXICON: dict[str, tuple[str, ...]] = {
    "comment": ("留言", "留個言", "回覆", "回我", "告訴我", "comment"),
    "dm": ("私訊", "私信", "傳訊", "敲我", "DM", "dm", "LINE", "line", "加賴"),
    "share": ("分享", "分享給", "傳給", "發給", "丟給", "轉發", "轉傳", "share"),
    "save": ("收藏", "收藏起來", "存下來", "存起來", "保存", "截圖", "截圖下來", "save"),
    "follow": ("追蹤", "訂閱", "follow"),
    "like": ("按讚", "點讚", "like"),
    "tag": ("tag", "Tag", "標記", "標記給", "@"),
    "link": ("點連結", "點鏈結", "連結", "link", "bio"),
    "claim": ("領取", "下載", "索取", "拿清單", "拿檔案"),
    "do": ("照做", "試做", "做一次", "跟著做", "明天做", "今天做"),
}
_CTA_ACTION_LEXICON["share"] = tuple(dict.fromkeys(
    _CTA_ACTION_LEXICON["share"] + ("轉寄", "傳送", "寄給", "轉發", "分享給")
))
_CTA_ACTION_LEXICON["save"] = tuple(dict.fromkeys(
    _CTA_ACTION_LEXICON["save"] + ("備份", "存起來", "存下來")
))
_IDENTITY_BRIDGE_RULES_CACHE: dict | None = None


def _hybrid_na(fname: str, check_id: str) -> tuple[str, str]:
    return "PASS", f"{fname}: {check_id} N/A 非 hybrid 批"


def _is_hybrid_script(data: dict) -> bool:
    return bool(str(data.get("content_axis", "") or "").strip())


def _present(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        s = v.strip()
        return bool(s) and not _is_placeholder(s) and s != "[編劇填]"
    if isinstance(v, (list, tuple, dict)):
        return bool(v)
    return True


def _as_text(v: Any) -> str:
    return "" if v is None else str(v)


def _scene_texts(data: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    scenes = data.get("scenes") or []
    if not isinstance(scenes, list):
        return out
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        ts = str(scene.get("timestamp", "") or "")
        parts = []
        # G11 grandfather：v1/任何顯式版本只認 canonical dialogue；無旗標
        # legacy 保留舊 all-scalar haystack，否則昀臻 14_12 等已封存批會
        # 因歷史 quote 只落在翠文而改 verdict。新檔由 skeleton 強制 v1。
        versioned_quote_contract = "quote_derivation_version" in data
        for k, v in scene.items():
            if k == "timestamp" or v is None or isinstance(v, (dict, list)):
                continue
            key_s = str(k)
            if versioned_quote_contract and key_s != "台詞" and not key_s.startswith("台詞_"):
                continue
            parts.append(str(v))
        out.append((ts, "\n".join(parts)))
    return out


def _all_scene_text(data: dict) -> str:
    return "\n".join(text for _, text in _scene_texts(data))


def _scene_text_for_ranges(data: dict, ranges: tuple[str, ...]) -> str:
    chunks = []
    for ts, text in _scene_texts(data):
        if ts in ranges:
            chunks.append(text)
    return "\n".join(chunks)


def _final_cta_scene_text(data: dict) -> str:
    texts = _scene_texts(data)
    if not texts:
        return ""
    cta_chunks = [text for ts, text in texts if "52-60" in ts or "CTA" in ts.upper()]
    if cta_chunks:
        return "\n".join(cta_chunks)
    return texts[-1][1]


def _quote_in_scene(data: dict, quote: Any, ranges: tuple[str, ...] | None = None) -> bool:
    q = _as_text(quote).strip()
    if not _present(q):
        return False
    haystack = _scene_text_for_ranges(data, ranges) if ranges else _all_scene_text(data)
    return q in haystack


def _hybrid_file_is_skeleton(data: dict) -> bool:
    """True when this script has no filled scene dialogue yet."""
    versioned_quote_contract = "quote_derivation_version" in data
    scenes = data.get("scenes") or []
    if not isinstance(scenes, list):
        # Grandfather: pre-G11 legacy files (including markdown-body scripts)
        # treated a missing/non-list scenes field as an untouched skeleton.
        return not versioned_quote_contract
    saw_dialogue_field = False
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        for key, value in scene.items():
            key_s = str(key)
            if key_s != "台詞" and not key_s.startswith("台詞_"):
                continue
            saw_dialogue_field = True
            if not _is_placeholder(value):
                return False
    # G11 P2-1 only tightens versioned files: a v1 shell with no dialogue
    # fields must be enforced.  Unversioned legacy keeps the old True result.
    return saw_dialogue_field if versioned_quote_contract else True


def _count_cta_actions(text: str) -> tuple[int, list[str]]:
    hits: list[str] = []
    for action, words in _CTA_ACTION_LEXICON.items():
        if any(w and w in text for w in words):
            hits.append(action)
    return len(hits), hits


def _identity_bridge_config_path() -> Path:
    base = Path(__file__).resolve().parent
    for rel in ("configs/offpro_identity_bridge_rules.yaml", "offpro_identity_bridge_rules.yaml"):
        p = base / rel
        if p.exists():
            return p
    return base / "offpro_identity_bridge_rules.yaml"


def _flatten_str_list(v: Any) -> list[str]:
    out: list[str] = []
    if isinstance(v, str):
        s = v.strip()
        if s:
            out.append(s)
    elif isinstance(v, list):
        for item in v:
            out.extend(_flatten_str_list(item))
    elif isinstance(v, dict):
        for item in v.values():
            out.extend(_flatten_str_list(item))
    return out


def _load_identity_bridge_rules() -> dict:
    global _IDENTITY_BRIDGE_RULES_CACHE
    if _IDENTITY_BRIDGE_RULES_CACHE is not None:
        return _IDENTITY_BRIDGE_RULES_CACHE
    path = _identity_bridge_config_path()
    if not path.exists():
        _IDENTITY_BRIDGE_RULES_CACHE = {
            "path": str(path),
            "load_error": "identity_bridge 規則檔讀取失敗，fail-closed",
        }
        return _IDENTITY_BRIDGE_RULES_CACHE
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        _IDENTITY_BRIDGE_RULES_CACHE = {
            "path": str(path),
            "load_error": f"identity_bridge 規則檔讀取失敗，fail-closed: {e}",
        }
        return _IDENTITY_BRIDGE_RULES_CACHE
    if not isinstance(raw, dict):
        _IDENTITY_BRIDGE_RULES_CACHE = {
            "path": str(path),
            "load_error": "identity_bridge 規則檔讀取失敗，fail-closed",
        }
        return _IDENTITY_BRIDGE_RULES_CACHE
    cfg = raw
    bridge = cfg.get("identity_bridge") if isinstance(cfg.get("identity_bridge"), dict) else {}
    max_distance = bridge.get("max_cooccurrence_distance_chars", 20) if isinstance(bridge, dict) else 20
    try:
        max_distance = int(max_distance)
    except (TypeError, ValueError):
        max_distance = 20
    hard_words = _flatten_str_list(cfg.get("offpro_business_leak_words"))
    identity_terms = _flatten_str_list(bridge.get("identity_terms") if isinstance(bridge, dict) else [])
    proof_terms = _flatten_str_list(bridge.get("professional_proof_terms") if isinstance(bridge, dict) else [])
    allowed_lanes = _flatten_str_list(bridge.get("allowed_lanes") if isinstance(bridge, dict) else [])
    _IDENTITY_BRIDGE_RULES_CACHE = {
        "path": str(path),
        "hard_words": sorted(set(hard_words)),
        "identity_terms": sorted(set(identity_terms)),
        "proof_terms": sorted(set(proof_terms)),
        "allowed_lanes": sorted(set(allowed_lanes or ["voice_first"])),
        "max_distance": max_distance,
    }
    return _IDENTITY_BRIDGE_RULES_CACHE


def _terms_cooccur_near(text: str, left_terms: list[str], right_terms: list[str], distance: int) -> tuple[str, str] | None:
    for left in left_terms:
        if not left:
            continue
        start = text.find(left)
        while start >= 0:
            window_start = max(0, start - distance)
            window_end = min(len(text), start + len(left) + distance)
            window = text[window_start:window_end]
            for right in right_terms:
                if right and right in window:
                    return left, right
            start = text.find(left, start + 1)
    return None


def _time_start(v: Any) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", _as_text(v))
    return float(m.group(0)) if m else None


def _hybrid_severity(flag: bool) -> str:
    return "FAIL" if flag else "WARN"


def _signal_type_ok(signal: dict) -> bool:
    quote = _as_text(signal.get("quote")).strip()
    typ = _as_text(signal.get("type")).strip().lower()
    if not _present(quote) or not _present(typ):
        return False
    if typ == "number":
        return bool(re.search(r"\d|%|％|一|二|三|四|五|六|七|八|九|十", quote))
    if typ == "place":
        return any(w in quote for w in ("在", "到", "店", "公司", "家", "路", "街", "現場"))
    if typ == "time":
        return bool(re.search(r"\d|秒|分|小時|天|週|月|年|早上|晚上|昨天|今天|明天", quote))
    if typ == "person":
        return any(w in quote for w in ("我", "你", "他", "她", "朋友", "同事", "家人", "客人", "客戶"))
    if typ in {"object", "sensory"}:
        return len(quote) >= 2
    return False


def _find_topic_plan(batch_dir: Path, explicit: Optional[str] = None) -> Optional[Path]:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    for name in ("topic_plan.json", "_topic_plan.json"):
        p = batch_dir / name
        if p.exists():
            return p
    matches = sorted(batch_dir.glob("topic_plan*.json"))
    return matches[0] if matches else None


# ════════════════════════════════════════════════════════════════════
# W1（cxp-gapfix-w1／2026-08-13）：C-TOPIC-LOCK — 題目鎖正式檢查（production check）
# 規格＝Codex 洞 02：正式清單無 C-TOPIC-LOCK，只有 --fixtures 內的 helper；
#   龍蝦堵法表 P0-3：「完全不經 distributor／骨架，直接手寫完整 yaml」。
# 判準（世代分流，明標 SKIP 不打紅歷史稿）：
#   🔴 T1 r2（2026-08-13）修正：世代**不再由本函式自行重算**，一律呼叫
#      _resolve_enforce_generation()（全系統唯一真源，F1／Codex 阻擋項 1）。
#      → 壞 JSON plan 等異常時，本檢查與 T1 三閘必然同判（同一份回傳值），不會分岔。
#   legacy 世代（命中 legacy_batch_allowlist.yaml 且無任何正向新世代訊號）
#     → SKIP（grandfather，明標理由）
#   new 世代（帶 topic_lock／plan 帶 topic_lock_hash／plan 壞損／不在 allowlist）
#     → 逐支比對：稿 topic_lock 各欄必須與 plan 對應槽逐欄相等；
#        plan 若帶 topic_lock_hash → 重算比對（防事後手改 plan）；
#        稿有鎖但 plan 無該 script_id／plan 缺席／plan 壞損 → FAIL（手寫 yaml 偷跳）。
# ════════════════════════════════════════════════════════════════════

_TOPIC_LOCK_SKIP_LEGACY = (
    "C-TOPIC-LOCK SKIP — legacy 世代（批次明列於 legacy_batch_allowlist.yaml，"
    "且無 topic_lock／topic_lock_hash 等新世代訊號）；grandfather 不追溯，未列管批次一律驗"
)


def _script_lock_of(data: dict) -> Optional[dict]:
    lock = data.get("topic_lock") if isinstance(data, dict) else None
    return lock if isinstance(lock, dict) else None


def chk_topic_lock_consistency(
    valid_yamls: list[tuple],
    batch_dir: Path,
    topic_plan_arg: Optional[str] = None,
    enforce_generation: Optional[bool] = None,
    generation_reason: str = "",
) -> tuple[str, str]:
    """C-TOPIC-LOCK（W1）：稿件 topic_lock ↔ topic_plan 逐欄一致性＋lock hash 驗。

    T1 r2（F1）：世代由 _resolve_enforce_generation() 單一真源決定。
    呼叫端（主流程）每批算一次後把結果傳進來；未傳（單元測試／外部 caller）
    則本函式**自己呼叫同一個 resolver**——仍然只有一套判準，不是第二份實作。
    """
    if enforce_generation is None:
        enforce_generation, generation_reason = _resolve_enforce_generation(
            batch_dir, valid_yamls, topic_plan_arg
        )
    # ── 世代判定（單一真源）──
    if not enforce_generation:
        return "SKIP", f"{_TOPIC_LOCK_SKIP_LEGACY}；世代判定：{generation_reason}"

    try:
        from topic_distributor import (  # type: ignore[import]
            TOPIC_LOCK_HASH_FIELDS as _LOCK_FIELDS,
            topic_lock_hash as _lock_hash,
            topic_lock_status as _lock_status,
        )
    except Exception as e:
        return "FAIL", f"C-TOPIC-LOCK FAIL — 題目鎖判準 import 失敗（fail-closed）：{e}"

    plan_path = _find_topic_plan(batch_dir, topic_plan_arg)
    plan_data, plan_error = _load_topic_plan_checked(plan_path)
    if plan_error:
        return "FAIL", f"C-TOPIC-LOCK FAIL — {plan_error}"
    plan = plan_data.get("plan") if isinstance(plan_data.get("plan"), list) else []
    declared_hash = plan_data.get("topic_lock_hash")

    locked_scripts = [
        (f, d) for f, d in valid_yamls
        if isinstance(d, dict) and _script_lock_of(d) is not None
    ]

    problems: list[str] = []

    # 🔴 T1 r2（F2 防自降級）：new 世代批**整批零支帶 topic_lock** ＝ FAIL。
    #   r1 時這種批會被判成舊稿而整個 SKIP —— 那正是 Codex 阻擋項 2 的攻擊路徑
    #   （把稿內 topic_lock 刪掉 → 三閘 SKIP、C-TOPIC-LOCK 也 SKIP）。
    #   r2 起：只要世代不是 allowlist 內的 legacy 批，缺鎖就是缺鎖，不得靜默放行。
    if not locked_scripts:
        return "FAIL", (
            "C-TOPIC-LOCK FAIL — new 世代批但 "
            f"{len(valid_yamls)} 支稿全數無 topic_lock 欄（題目層未經過／或鎖被刪除）；"
            f"legacy 豁免只認 legacy_batch_allowlist.yaml 明列的批次。世代判定：{generation_reason}"
        )

    # plan 端 hash 完整性（plan 宣告了就必須算得回來）
    if declared_hash is not None:
        if not isinstance(declared_hash, str) or not declared_hash.strip():
            problems.append(f"plan topic_lock_hash 型別/內容非法（{type(declared_hash).__name__}）")
        else:
            recomputed = _lock_hash(plan)
            if recomputed != declared_hash:
                problems.append(
                    f"plan topic_lock_hash 不符（宣告 {declared_hash[:16]}…／重算 {recomputed[:16]}…）"
                    f"＝plan 的題目鎖在產出後被改過"
                )

    # 新格式但 plan 缺席＝手寫 yaml 偷跳
    if locked_scripts and not plan_path:
        return "FAIL", (
            f"C-TOPIC-LOCK FAIL — {len(locked_scripts)} 支帶 topic_lock 但批次無 topic_plan.json"
            f"（無來源鏈；手寫 yaml 不得繞過題目層）"
        )

    plan_by_id = {
        str(item.get("script_id", "") or ""): item
        for item in plan
        if isinstance(item, dict)
    }

    for f, data in locked_scripts:
        sid = str(data.get("script_id", "") or f.stem)
        lock = _script_lock_of(data) or {}
        item = plan_by_id.get(sid)
        if item is None:
            problems.append(f"{f.name}: script_id={sid!r} 不在 topic_plan 的 plan 清單中（題未經題目層分配）")
            continue
        plan_lock = item.get("topic_lock")
        plan_lock = plan_lock if isinstance(plan_lock, dict) else {}
        # 逐欄比對（正規化後字串比對，list 逐元素）
        for field in _LOCK_FIELDS:
            sv, pv = lock.get(field), plan_lock.get(field)
            sv_n = [str(x) for x in sv] if isinstance(sv, (list, tuple)) else ("" if sv is None else str(sv))
            pv_n = [str(x) for x in pv] if isinstance(pv, (list, tuple)) else ("" if pv is None else str(pv))
            if sv_n != pv_n:
                problems.append(
                    f"{f.name}: topic_lock.{field} 與 plan 不符（稿={str(sv)[:24]!r}／plan={str(pv)[:24]!r}）"
                )
        # 稿自身鎖完整性（缺欄＝沒真鎖）
        ok, missing = _lock_status({"direction": item.get("direction", ""), "topic_lock": lock})
        if not ok:
            problems.append(f"{f.name}: topic_lock 欄不完整 — {'；'.join(missing[:3])}")

    # plan 已鎖但稿沒帶鎖（新格式批不得混入無鎖稿）
    if declared_hash is not None:
        unlocked_files = [
            f.name for f, d in valid_yamls
            if isinstance(d, dict) and _script_lock_of(d) is None
        ]
        if unlocked_files:
            problems.append(
                f"plan 已宣告 topic_lock_hash（新格式批）但 {len(unlocked_files)} 支稿無 topic_lock 欄："
                f"{'、'.join(unlocked_files[:5])}"
            )

    if problems:
        return "FAIL", f"C-TOPIC-LOCK FAIL — {'; '.join(problems[:12])}"
    return "PASS", (
        f"C-TOPIC-LOCK PASS — {len(locked_scripts)} 支鎖題與 plan 逐欄相符"
        f"{'；lock hash 相符' if declared_hash else '（plan 未宣告 lock hash）'}"
    )


# ════════════════════════════════════════════════════════════════════
# W4（cxp-gapfix-w1／2026-08-13）：C-TOPIC-ID-EQ — topic_id 單一真源
# 規格＝Codex 洞 15：generator 同時寫 topic_lock.topic_id 與
#   source_topic_intel.topic_id，validator V3-001 只驗後者且僅政策開啟時執行
#   → 兩處可以不一致（鎖 A、provenance B）。
# 判準：兩處**都在場**才比對（新格式）→ 不等即 FAIL；
#   任一缺席＝舊稿／未啟用 WP-B → SKIP 明標。
# ════════════════════════════════════════════════════════════════════

_BATCH_FLAGS_BATCH_PROFILE_ERROR = "_batch_flags.yml 讀取/解析失敗，無法確認 batch_profile（fail-closed）"


def _load_batch_flags_checked(batch_dir: Path) -> tuple[dict, Optional[str]]:
    """W5（cxp-gapfix-w1／Codex 洞 08）：改呼叫 topic_intel_policy 的 canonical loader。

    原實作 `yaml.safe_load(...) or {}` 會把 falsy 檔內容（false／0／null／空檔／[]）
    洗成 {}，令後面的 isinstance(raw, dict) 永遠通過 → hybrid/taste/time_axis 等閘
    被靜默關掉。canonical loader 不做 `or {}`，檔案存在但非 mapping 一律回 error。
    回傳型別與錯誤語義維持不變（error 非 None → 呼叫端既有 fail-closed 分支照舊）。
    """
    try:
        from topic_intel_policy import load_batch_flags_strict as _lbfs  # type: ignore[import]
    except Exception:
        # loader 不可得＝環境異常，fail-closed（不退回舊寬鬆行為）
        return {}, _BATCH_FLAGS_BATCH_PROFILE_ERROR
    raw, error = _lbfs(batch_dir)
    if error:
        return {}, f"{_BATCH_FLAGS_BATCH_PROFILE_ERROR}｜{error}"
    return raw, None


def _load_batch_flags(batch_dir: Path) -> dict:
    raw, _error = _load_batch_flags_checked(batch_dir)
    return raw


def _batch_flags_declares_hybrid(batch_dir: Path) -> bool:
    return _load_batch_flags(batch_dir).get("batch_profile") == HYBRID_BATCH_PROFILE


# ────────────────────────────────────────────
# W4-K12（2026-07-16）：per-batch time_axis 選填參數化（60 秒預設保留、fail-closed）
# 規格＝state/decision_cards/W4/K12_diff_packet_20260716.md Delta A/B（切前盲審 r8 GO）
# ────────────────────────────────────────────
_TIME_AXIS_REQUIRED_KEYS = {"duration_seconds", "time_slots", "approved_by", "approved_at", "approved_digest"}
_TIME_AXIS_SLOT_RE = re.compile(r"(0|[1-9][0-9]{0,3})-(0|[1-9][0-9]{0,3})s", re.ASCII)


def _time_axis_canonical_digest(batch_key: str, duration_seconds: int, time_slots: list) -> str:
    """approved_digest 正典計算：sha256(canonical_json({batch,duration_seconds,time_slots}))[:16]
    （Delta A ⑧；batch_key＝「業主/01_腳本生產/批次」三級目錄名，封跨業主同名批 replay）。
    """
    canonical = json.dumps(
        {"batch": batch_key, "duration_seconds": duration_seconds, "time_slots": time_slots},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _resolve_time_axis_from_raw(raw: Any, batch_key: str) -> tuple[Optional[dict], Optional[str]]:
    """Delta A ②-⑧ 核心驗證邏輯（batch_key 由呼叫端算好；供 _resolve_batch_time_axis 與
    fixtures 共用純函式，不碰檔案系統）。任一失敗＝(None, "time_axis 宣告非法—<原因>")；
    禁 fallback 禁 normalize。回傳 (axis, None) 時 axis = {"duration_seconds": int,
    "time_slots": [{"timestamp": str, "start": int, "end": int}, ...]}。
    """
    # ② 值為 null／非 mapping
    if raw is None or not isinstance(raw, dict):
        return None, "time_axis 宣告非法—time_axis 必須是 mapping（非 null/list/str）"

    # ③ 恰五鍵（缺任一或有未知鍵 → error）
    keys = set(raw.keys())
    if keys != _TIME_AXIS_REQUIRED_KEYS:
        missing = _TIME_AXIS_REQUIRED_KEYS - keys
        unknown = keys - _TIME_AXIS_REQUIRED_KEYS
        # 出貨審 r1 P0 修：raw 鍵混型時（YAML 允許非字串鍵，如 `7: x`）unknown 集合若同時
        # 含 str 與 int 等不可比對型別，裸 sorted() 會拋 TypeError（'<' not supported between
        # instances of 'int' and 'str'），讓 fail-closed 失控炸主流程。key=str 統一轉字串比較。
        parts = []
        if missing:
            parts.append(f"缺鍵 {sorted(missing, key=str)}")
        if unknown:
            parts.append(f"未知鍵 {sorted(unknown, key=str)}")
        return None, f"time_axis 宣告非法—恰五鍵檢查未過（{'；'.join(parts)}）"

    # ④ duration_seconds：type(x) is int（排除 bool）且 0 < x <= 3600
    duration = raw["duration_seconds"]
    if type(duration) is not int or not (0 < duration <= 3600):
        return None, "time_axis 宣告非法—duration_seconds 型別非 int 或超出 (0, 3600] 範圍"

    # ⑤ time_slots：type is list、2 <= N <= 24、元素 type is str
    slots = raw["time_slots"]
    if type(slots) is not list or not (2 <= len(slots) <= 24):
        return None, "time_axis 宣告非法—time_slots 型別非 list 或段數不在 2~24 範圍"
    if not all(type(s) is str for s in slots):
        return None, "time_axis 宣告非法—time_slots 元素型別非 str"

    # ⑥ 每段 fullmatch（封 Unicode 數字/前導零/尾隨空白換行/超長位數）
    parsed: list = []
    for s in slots:
        m = _TIME_AXIS_SLOT_RE.fullmatch(s)
        if not m:
            return None, f"time_axis 宣告非法—time_slots 段格式錯誤：{s!r}"
        parsed.append((int(m.group(1)), int(m.group(2))))

    # ⑦ 區間數學：首段 start==0／每段 end>start／嚴格接續／末段 end==duration
    if parsed[0][0] != 0:
        return None, f"time_axis 宣告非法—首段未從 0 開始：{slots[0]!r}"
    for (start, end), raw_s in zip(parsed, slots):
        if end <= start:
            return None, f"time_axis 宣告非法—段落零長或逆序：{raw_s!r}"
    for (s1, e1), (s2, e2) in zip(parsed, parsed[1:]):
        if e1 != s2:
            return None, f"time_axis 宣告非法—時間軸不連續：{e1} != {s2}"
    if parsed[-1][1] != duration:
        return None, f"time_axis 宣告非法—末段 end({parsed[-1][1]}) != duration_seconds({duration})"

    # ⑧ 授權三欄（機器閘，非密碼學核准證明——宣稱邊界見 packet Delta A ⑧）
    approved_by = raw["approved_by"]
    if type(approved_by) is not str or approved_by != "澤君":
        return None, "time_axis 宣告非法—approved_by 必須恰為「澤君」"

    approved_at = raw["approved_at"]
    if type(approved_at) is not str:
        return None, "time_axis 宣告非法—approved_at 型別非 str（YAML 無引號日期會被解析成 date 物件）"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", approved_at):
        return None, "time_axis 宣告非法—approved_at 格式非 YYYY-MM-DD"
    try:
        approved_date = _dt.datetime.strptime(approved_at, "%Y-%m-%d").date()
    except ValueError:
        return None, "time_axis 宣告非法—approved_at 非真實日期"
    if approved_date > _dt.date.today():
        return None, "time_axis 宣告非法—approved_at 為未來日期"

    approved_digest = raw["approved_digest"]
    if type(approved_digest) is not str:
        return None, "time_axis 宣告非法—approved_digest 型別非 str"
    expected_digest = _time_axis_canonical_digest(batch_key, duration, slots)
    if approved_digest != expected_digest:
        return None, "time_axis 宣告非法—宣告內容與核准摘要不符"

    axis = {
        "duration_seconds": duration,
        "time_slots": [{"timestamp": s, "start": a, "end": b} for s, (a, b) in zip(slots, parsed)],
    }
    return axis, None


def _resolve_batch_time_axis(batch_dir: Path) -> tuple[Optional[dict], Optional[str]]:
    """Delta A ①：per-batch time_axis 選填宣告解析入口，fail-closed。
    (None, None)＝鍵整個缺席 → 下游一律走原全域 60s 路徑（逐字零變）；
    (axis_dict, None)＝宣告合法；(None, "time_axis 宣告非法—…")＝宣告非法（禁 fallback/normalize）。
    _batch_flags.yml 整檔解析失敗（含 top-level falsy 經既有 `_load_batch_flags_checked`
    的 `or {}` 吞成空 dict）由既有閘（C-plan-lock 等）處理，本刀不新增行為、time_axis 視同缺席。
    """
    flags, flags_error = _load_batch_flags_checked(batch_dir)
    if flags_error:
        return None, None
    if "time_axis" not in flags:
        return None, None
    resolved = batch_dir.resolve()
    batch_key = "/".join(p.name for p in [resolved.parent.parent, resolved.parent, resolved])
    return _resolve_time_axis_from_raw(flags["time_axis"], batch_key)


def chk_l1_000_time_axis(axis: Optional[dict], error: Optional[str]) -> Optional[tuple[str, str]]:
    """L1-000-time-axis（Delta B）：批級 time_axis 宣告驗，呼叫端先跑一次
    _resolve_batch_time_axis(batch_dir) 取得 (axis, error) 再傳入本函式判定。
    回傳 None＝缺省（鍵缺席）、呼叫端不得註冊本 check（all_results 無此列＝零註冊）。
    """
    if axis is None and error is None:
        return None
    if error is not None:
        return "FAIL", error
    n = len(axis["time_slots"])
    return "PASS", f"time_axis 宣告合法（declared {n} 段 / duration={axis['duration_seconds']}s）"


def _load_topic_plan_checked(plan_path: Optional[Path]) -> tuple[dict, Optional[str]]:
    if not plan_path:
        return {}, None
    try:
        plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {}, f"topic_plan 讀取失敗: {e}"
    if not isinstance(plan_data, dict):
        return {}, "topic_plan 結構異常"
    meta = plan_data.get("meta") or {}
    if not isinstance(meta, dict):
        return {}, "topic_plan 結構異常"
    plan = plan_data.get("plan")
    if plan is not None:
        if not isinstance(plan, list) or any(not isinstance(item, dict) for item in plan):
            return {}, "topic_plan 結構異常"
    return plan_data, None


def _topic_plan_declares_hybrid(plan_data: dict) -> bool:
    meta = plan_data.get("meta") or {}
    return isinstance(meta, dict) and meta.get("batch_profile") == HYBRID_BATCH_PROFILE


def _declared_hybrid_not_built(
    declared_hybrid: bool,
    yaml_hybrid_count: int,
    plan_path: Optional[Path],
    plan: list[dict],
    expected_main: int,
) -> bool:
    if not declared_hybrid:
        return False
    return not plan_path or yaml_hybrid_count != expected_main or len(plan) != expected_main


def _plan_lock_hash(plan: list[dict]) -> str:
    pairs = [
        {
            "script_id": item.get("script_id", ""),
            "content_axis": item.get("content_axis", ""),
            "lane": item.get("lane", ""),
            "derived_flags": sorted(str(x) for x in (item.get("derived_flags") or [])),
            "proof_mode": item.get("proof_mode", ""),  # R3 Fix 1（2026-06-24）：proof_mode 納入 hash
        }
        for item in plan
    ]
    raw = json.dumps(pairs, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _count_key(items: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        v = item.get(key)
        if isinstance(v, str) and v:
            out[v] = out.get(v, 0) + 1
    return out


def chk_taste_panel_completeness(
    yamls: list[tuple[Path, dict]],
    batch_dir: Path,
    topic_plan_arg: Optional[str] = None,
) -> tuple[str, str]:
    hybrid_yamls = [(f, d) for f, d in yamls if isinstance(d, dict) and _is_hybrid_script(d)]
    yaml_has_hybrid = bool(hybrid_yamls)
    flags_data, flags_error = _load_batch_flags_checked(batch_dir)
    if flags_error:
        return "FAIL", f"C-taste-panel FAIL — {flags_error}"
    flags_hybrid = flags_data.get("batch_profile") == HYBRID_BATCH_PROFILE
    plan_path = _find_topic_plan(batch_dir, topic_plan_arg)
    plan_data, plan_error = _load_topic_plan_checked(plan_path)
    severity = _hybrid_severity(_TASTE_PANEL_ENFORCE)
    if plan_error:
        return severity, f"C-taste-panel FAIL — {plan_error}"
    plan_hybrid = _topic_plan_declares_hybrid(plan_data)
    declared_hybrid = flags_hybrid or plan_hybrid
    if not yaml_has_hybrid and not declared_hybrid:
        return "PASS", "C-taste-panel N/A 非 hybrid 批"
    plan = plan_data.get("plan") if isinstance(plan_data.get("plan"), list) else []
    expected_main = _expected_main_scripts_for_batch(yamls)
    if _declared_hybrid_not_built(declared_hybrid, len(hybrid_yamls), plan_path, plan, expected_main):
        return severity, "C-taste-panel FAIL — 宣告 hybrid 但腳本/計畫非 hybrid（declared-but-not-built）"

    try:
        import taste_panel_gate as _tpg  # local gate helper
    except Exception as e:
        return severity, f"C-taste-panel FAIL — taste_panel_gate import failed: {e}"

    panel_dir = batch_dir / ".taste_panel"
    problems: list[str] = []
    if not panel_dir.exists():
        return severity, "C-taste-panel FAIL — missing .taste_panel directory"
    if list(panel_dir.glob("*.tmp")):
        problems.append(".tmp leftover")

    rubric_path = _tpg.DEFAULT_RUBRIC_PATH
    if not rubric_path.exists():
        problems.append(f"rubric missing: {rubric_path}")
        rubric_hash = ""
        prompt_hash = ""
        rubric_model_id = _tpg.DEFAULT_MODEL_ID
    else:
        rubric_text = rubric_path.read_text(encoding="utf-8")
        rubric_hash = _tpg.sha256_text(rubric_text)
        try:
            rubric = yaml.safe_load(rubric_text) or {}
            rubric = rubric if isinstance(rubric, dict) else {}
            prompt_hash = _tpg.prompt_template_hash(rubric)
            rubric_model_id = str((rubric.get("meta") or {}).get("model", _tpg.DEFAULT_MODEL_ID))
        except Exception as e:
            prompt_hash = ""
            rubric_model_id = _tpg.DEFAULT_MODEL_ID
            problems.append(f"rubric parse error: {e}")

    summary_path = panel_dir / "_taste_panel_summary.json"
    summary = None
    if not summary_path.exists():
        problems.append("summary missing")
    else:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as e:
            problems.append(f"summary parse error: {e}")

    _expected_main = expected_main
    if len(hybrid_yamls) != _expected_main:
        problems.append(f"hybrid yaml count={len(hybrid_yamls)} expected={_expected_main}")

    report_files = sorted(panel_dir.glob("*_taste_panel_report.json"))
    if len(report_files) != _expected_main:
        problems.append(f"report count={len(report_files)} expected={_expected_main}")
    reports: list[dict] = []
    for rp in report_files:
        try:
            rep = json.loads(rp.read_text(encoding="utf-8"))
            if not isinstance(rep, dict):
                problems.append(f"{rp.name}: schema invalid")
                continue
            reports.append(rep)
        except Exception as e:
            problems.append(f"{rp.name}: parse error {e}")

    # TEXT_CEILING ACK（2026-06-24）：建立 yaml-by-sid 索引，供 per-report 判斷時 lookup
    yaml_by_sid: dict[str, dict] = {
        str(d.get("script_id") or f.stem): d
        for f, d in hybrid_yamls
        if isinstance(d, dict)
    }
    # text_ceiling_warns：純文字稿 5 維全≥80 但有維度 <90 的支（WARN 非 FAIL）
    text_ceiling_warns: list[str] = []

    by_sid: dict[str, dict] = {}
    for rep in reports:
        sid = str(rep.get("script_id") or "")
        if not sid:
            problems.append("report missing script_id")
            continue
        if sid in by_sid:
            problems.append(f"dup script_id={sid}")
        by_sid[sid] = rep
        if rep.get("schema_version") != 1:
            problems.append(f"{sid}: schema invalid")
        if rep.get("gate_version") != _tpg.GATE_VERSION:
            problems.append(f"{sid}: gate_version mismatch")
        if rep.get("rubric_hash") != rubric_hash:
            problems.append(f"{sid}: rubric_hash mismatch")
        if not rep.get("model_id"):
            problems.append(f"{sid}: model_id missing")
        elif str(rep.get("model_id")) != rubric_model_id:
            problems.append(f"{sid}: model_id mismatch expected={rubric_model_id} got={rep.get('model_id')}")
        if not rep.get("prompt_template_hash"):
            problems.append(f"{sid}: prompt_template_hash missing")
        elif rep.get("prompt_template_hash") != prompt_hash:
            problems.append(f"{sid}: prompt_template_hash mismatch")
        # This binds report fields together, but it is not a secret signature:
        # a determined forger who computes all fields can still fabricate a report.
        expected_gate_cache_key = _tpg.cache_key(
            str(rep.get("raw_input_hash") or ""),
            str(rep.get("sanitized_input_hash") or ""),
            rubric_hash,
            prompt_hash,
            str(rep.get("model_id") or ""),
            no_llm=False,
        )
        if rep.get("gate_cache_key") != expected_gate_cache_key:
            problems.append(f"{sid}: gate_cache_key mismatch")
        if rep.get("mock_report"):
            problems.append(f"{sid}: mock report")
        if rep.get("no_llm_mode") is True:
            problems.append(f"{sid}: taste_panel report is --no-llm (not a real GPT review)")

        # ── 評分閘：relative 模式 vs 原邏輯 ──
        scores = rep.get("scores") if isinstance(rep.get("scores"), dict) else {}

        if is_relative_enabled():
            # execution 失敗（評審未跑完：GPT 沒回完 / schema fail）→ execution FAIL、非內容 REJECT
            # （分類清楚、不把「評審沒跑完」污染成「內容垃圾」；不進 deploy_decision 內容分類器）。
            if str(rep.get("verdict") or "") == "pending_review":
                problems.append(f"{sid}: C-taste-panel 評審未跑完（verdict=pending_review·execution incomplete·非內容品質問題）")
                continue
            # relative ON：TEXT_CEILING hard-gate 退出；改走 deploy_decision
            def _is_offpro_report_vsb(r: dict) -> bool:
                # 委派 helper 單一真理源（gate/validate 共用、防漂移）。
                return is_offpro_report(r)

            # 一律從 report 當前 scores+verdict 重算 deploy_decision（純函式、確定性）；
            # 不信任 report 內 stored deploy_decision（防 stale：score/verdict 改後決策未同步、generic 高分稿漏網）。
            decision = compute_deploy_decision(
                scores, _is_offpro_report_vsb(rep), True, legacy_verdict=rep.get("verdict")
            )
            if decision.get("status") == STATUS_REJECT:
                problems.append(
                    f"{sid}: deploy_decision=REJECT verdict={rep.get('verdict')} reasons={decision.get('reject_reasons')}"
                )
            elif decision.get("status") == STATUS_HUMAN:
                # HUMAN_REVIEW = WARN（非硬擋·放行）：borderline 稿照樣上線、但明確標記建議人工複審。
                # 命名與行為一致（GPT 上線後驗證 round1）：這是「通過·borderline·建議複審」、非「擋住待審」。
                text_ceiling_warns.append(
                    f"{sid}: 通過(borderline·建議人工複審·非硬擋) avg={decision.get('avg')} "
                    f"deploy_index={decision.get('deploy_index')} weakest={decision.get('weakest_dim')}"
                )
            # STATUS_PASS → 不加任何 problem

        else:
            # ── TEXT_CEILING ACK：verdict / score 判斷（2026-06-24）──（原邏輯不動）
            yaml_data = yaml_by_sid.get(sid, {})
            _tms = str(yaml_data.get("true_material_source", "") or "").strip().lower()
            _st = str(yaml_data.get("score_type", "") or "").strip().lower()
            _is_text_only = _tms == "none" and _st in {"script", "angle"}

            # generic 退件（reject_generic verdict）→ 永遠 hard FAIL，不走黃燈
            _verdict = str(rep.get("verdict") or "")
            _is_generic_reject = _verdict == "reject_generic"

            if _TEXT_CEILING_ACK_ENABLE and _is_text_only and not _is_generic_reject:
                # 純文字稿路徑：依各維度值決定黃燈 / hard FAIL
                _dim_vals: dict[str, float | None] = {}
                for dim in _tpg.REQUIRED_DIMS:
                    val = scores.get(dim)
                    _dim_vals[dim] = val if isinstance(val, (int, float)) else None

                _below_floor = [d for d, v in _dim_vals.items() if v is None or v < _TEXT_CEILING_FLOOR]
                _below_90 = [d for d, v in _dim_vals.items() if v is None or v < _tpg.PASS_THRESHOLD]

                if _below_floor:
                    # 任一維 < 80 → hard FAIL（稿太弱，要 rework）
                    if _verdict != "pass":
                        problems.append(f"{sid}: verdict={_verdict}")
                    for dim in _below_floor:
                        problems.append(f"{sid}: {dim}={_dim_vals[dim]} < {_TEXT_CEILING_FLOOR}（純文字弱維，需 rework）")
                elif _below_90:
                    # 全維≥80 但有維度 <90 → TEXT_CEILING 黃燈 WARN
                    dim_strs = ", ".join(f"{d}={_dim_vals[d]}" for d in _below_90)
                    text_ceiling_warns.append(
                        f"{sid}: TEXT_CEILING 純文字交付（各維≥{_TEXT_CEILING_FLOOR}·未達成片90·需口播）{dim_strs}"
                    )
                # else: 全維≥90 → PASS（fall-through，不加任何 problem）
            else:
                # 成片稿 or TEXT_CEILING 未啟用 or generic_reject → 原邏輯不變
                if _verdict != "pass":
                    problems.append(f"{sid}: verdict={_verdict}")
                for dim in _tpg.REQUIRED_DIMS:
                    val = scores.get(dim)
                    if not isinstance(val, (int, float)) or val < _tpg.PASS_THRESHOLD:
                        problems.append(f"{sid}: {dim}={val} < {_tpg.PASS_THRESHOLD}")

    for f, data in hybrid_yamls:
        sid = str(data.get("script_id") or f.stem)
        rep = by_sid.get(sid)
        if rep is None:
            problems.append(f"{sid}: missing report")
            continue
        try:
            raw_hash, sanitized_hash = _tpg.compute_hashes(f, data)
        except Exception as e:
            problems.append(f"{sid}: hash recompute failed {e}")
            continue
        if rep.get("raw_input_hash") != raw_hash:
            problems.append(f"{sid}: stale raw_input_hash")
        if rep.get("sanitized_input_hash") != sanitized_hash:
            problems.append(f"{sid}: stale sanitized_input_hash")

    if summary:
        if summary.get("rubric_hash") != rubric_hash:
            problems.append("summary rubric_hash mismatch")
        if summary.get("gate_version") != _tpg.GATE_VERSION:
            problems.append("summary gate_version mismatch")
        if not summary.get("model_id"):
            problems.append("summary model_id missing")
        elif str(summary.get("model_id")) != rubric_model_id:
            problems.append(f"summary model_id mismatch expected={rubric_model_id} got={summary.get('model_id')}")
        if not summary.get("prompt_template_hash"):
            problems.append("summary prompt_template_hash missing")
        elif summary.get("prompt_template_hash") != prompt_hash:
            problems.append("summary prompt_template_hash mismatch")
        if summary.get("mock_report"):
            problems.append("summary mock report")
        if summary.get("no_llm_mode") is True:
            problems.append("summary taste_panel report is --no-llm (not a real GPT review)")
        # relative ON：不信 gate stored summary verdict（切換前 legacy 模式算的）；validate 已用當下 flag
        # 重算每支 deploy_decision 為權威。integrity summary 檢查（mock/no_llm/hash/gate_version）仍照跑。
        if not is_relative_enabled() and summary.get("overall_verdict") != "pass":
            problems.append(f"summary overall_verdict={summary.get('overall_verdict')}")
        summary_ids = summary.get("script_ids") if isinstance(summary.get("script_ids"), list) else []
        expected_ids = [str(d.get("script_id") or f.stem) for f, d in hybrid_yamls]
        if sorted(summary_ids) != sorted(expected_ids):
            problems.append("summary script_ids mismatch")

    # ── TEXT_CEILING ACK 彙總（2026-06-24）──
    if problems:
        # hard FAIL 優先：不管有多少黃燈，只要有 FAIL 就回 FAIL
        fail_msg = f"C-taste-panel FAIL — {'; '.join(problems[:20])}"
        if text_ceiling_warns:
            tc_note = f"（另有 {len(text_ceiling_warns)} 支 TEXT_CEILING 純文字黃燈）"
            fail_msg += " " + tc_note
        return severity, fail_msg
    if text_ceiling_warns:
        # 無 hard FAIL，但有純文字黃燈 → batch WARN（誠實，非假象 PASS）
        n_tc = len(text_ceiling_warns)
        n_pass = len(hybrid_yamls) - n_tc
        warn_detail = "; ".join(text_ceiling_warns[:10])
        return "WARN", (
            f"C-taste-panel WARN（TEXT_CEILING）— "
            f"純文字交付：{n_tc} 支達純文字好稿門檻(各維≥{_TEXT_CEILING_FLOOR})·未達成片90·需口播；"
            f"{n_pass} 支 PASS — {warn_detail}"
        )
    return "PASS", f"C-taste-panel PASS — {len(report_files)} reports, all pass, hashes fresh"


# ── --stage 旗標（cxp-gapfix-w1c r1，2026-08-13）──
# skill b 項（shortform-new-batch）已寫死順序：
#   validate --stage pre-panel → taste_panel_gate → validate --strict（final）
# 理由＝新批順序死鎖：C-taste-panel 對「尚無 .taste_panel 報告的 hybrid 新批」必然 FAIL，
# 先跑 --strict 會 FAIL 即停、永遠跑不到評審團那步。
# pre-panel＝只跳 C-taste-panel（明標 SKIP「panel 後補驗」），其餘檢查照常；final＝現行為準。
STAGE_CHOICES = ("pre-panel", "final")
_TASTE_PANEL_PRE_PANEL_SKIP = "C-taste-panel SKIP — pre-panel 階段跳過，panel 後補驗（跑完 taste_panel_gate 再以 --stage final 收驗）"


# ────────────────────────────────────────────
# 跑單一 yaml 的 12 件 per-file checks
# ────────────────────────────────────────────
def run_per_file_checks(
    f: Path,
    data: dict,
    owner: str,
    is_skeleton: bool = False,
    fishing_policy: Optional[dict] = None,
    topic_intel_policy: Optional[dict] = None,
    hybrid_batch: bool = True,
    time_axis: Optional[dict] = None,
    time_axis_error: Optional[str] = None,
    enforce_generation: Optional[bool] = None,
) -> list[tuple[str, str, str, str]]:
    """回傳 [(check_id, status, desc, detail), ...]
    v2 升級：加 V2-001 ~ V2-005（yaml schema 新欄位驗）
    is_skeleton：由 _is_skeleton_mode(yamls) 傳入，骨架階段跳過 V2-025/026
    fishing_policy：由 load_fishing_policy() 算出後傳入，讓 C-013 知道模式
    topic_intel_policy：由 load_topic_intel_policy() 算出後傳入，讓 V3-001 知道模式（off=SKIP）
    hybrid_batch：由 _is_hybrid_batch(batch_dir, yamls) 傳入（W2-D20）；預設 True=fail-closed
    （單檔直呼/harness matrix 語境一律全嚴），只有主流程判定純 legacy 批才傳 False。
    time_axis / time_axis_error：由 main() 對整批呼叫一次 _resolve_batch_time_axis(batch_dir)
    算出後傳入（W4-K12 2026-07-16 Delta D）。兩者皆 None＝缺省，L1-001/L1-006 走原全域路徑
    逐字零變（外部 caller 不傳＝行為零變）；time_axis_error 非 None＝在求值前攔截，L1-001/
    L1-006 直接回 FAIL「time_axis 非法、時間軸無法驗」，絕不落入 None→L0 全域路徑；
    time_axis 有值（且 error 為 None）＝改用宣告軸驗。兩者互斥由 resolver 回傳結構保證。
    """
    if fishing_policy is None:
        fishing_policy = {"mode": "off", "batch_date": None, "detail": "未傳入 policy，保守 off"}
    if topic_intel_policy is None:
        topic_intel_policy = {"mode": "off", "enabled": False, "detail": "未傳入 topic_intel_policy"}
    # P1-1：傳入「批次目錄名/檔名」讓 _extract_batch_date 能從目錄名（如第34批_試水批_2026-05-23）抓日期
    _fname_with_dir = f"{f.parent.name}/{f.name}"
    # G11 runtime view：legacy 無旗標完全不註冊新 check；任何顯式版本
    # 都 fail-closed。consumer 不得在 derive 失敗後回退去讀 selector dict。
    _quote_view: dict | None = data
    _quote_source_result: tuple[str, str] | None = None
    if "quote_derivation_version" in data or "quote_source_hash" in data:
        _quote_version = data.get("quote_derivation_version")
        _quote_true_skeleton = (
            type(_quote_version) is int
            and _quote_version == 1
            and "quote_source_hash" not in data
            and isinstance(data.get("title"), str)
            and _is_placeholder(data["title"])
            and _hybrid_file_is_skeleton(data)
        )
        if _quote_true_skeleton:
            _quote_source_result = (
                "SKIP",
                f"{f.name}: C-quote-source 骨架階段跳過；填入真 title/台詞後即 fail-closed",
            )
        else:
            try:
                _quote_view = derive_quote_view(data)
                _quote_source_result = (
                    "PASS",
                    f"{f.name}: C-quote-source PASS — dialogue_sha256={dialogue_sha256(data)}",
                )
            except QuoteDerivationError as _quote_err:
                _quote_view = None
                _quote_source_result = (
                    "FAIL",
                    f"{f.name}: C-quote-source FAIL — {_quote_err}",
                )
    # W4-K12（2026-07-16 Delta D）：time_axis_error 在求值前攔截，絕不落入 chk_l1_001_schema/
    # chk_l1_006_cta 的 None→L0 全域路徑；time_axis 有值改用宣告軸驗；兩者皆 None 原路徑零變。
    if time_axis_error is not None:
        _l1001_result = ("FAIL", "time_axis 非法、時間軸無法驗")
        _l1006_result = ("FAIL", "time_axis 非法、時間軸無法驗")
    elif time_axis is not None:
        _l1001_result = chk_l1_001_schema(data, f.name, expected_slots=time_axis["time_slots"])
        _l1006_result = chk_l1_006_cta(data, f.name, cta_slot=time_axis["time_slots"][-1]["timestamp"])
    else:
        _l1001_result = chk_l1_001_schema(data, f.name)
        _l1006_result = chk_l1_006_cta(data, f.name)

    # 藏鏡人長度感知配額用的本支時長（cxp r2）：批級 time_axis 宣告優先，否則交給
    # chk_l1_003_mirror 自己從 yaml/L0 推（傳 None＝不覆寫）。
    _mirror_duration = None
    if time_axis_error is None and time_axis is not None:
        _ta_dur = time_axis.get("duration_seconds")
        if type(_ta_dur) is int and _ta_dur > 0:
            _mirror_duration = _ta_dur

    results = []
    checks = [
        # per-file checks
        ("L1-001", _l1001_result),
        ("L1-002", chk_l1_002_banned(data, f.name)),
        ("L1-003", chk_l1_003_mirror(data, f.name, duration_seconds=_mirror_duration,
                                     enforce_generation=enforce_generation)),
        ("L1-004", chk_l1_004_traffic(data, f.name, enforce_generation=enforce_generation)),
        # 【p4exec1 殺單 #56 KEEP-CANDIDATE｜零開火但保留】L1-005 業務數字必有來源標記。
        # 對映憲法 §2 不捏造數字（L1.FZ.REALDATA, overridable:false）＝安全/法規類。
        # 零開火＝三批無未標來源數字，非規則無效。替代物：active_rules.yaml L1／L2。
        ("L1-005", chk_l1_005_number_source(data, f.name)),
        ("L1-006", _l1006_result),
        ("L1-007", chk_l1_007_title_len(data, f.name)),
        ("C-015",  chk_c015_hashtag_caption(data, f.name)),
        ("C-017",  chk_c017_concreteness(data, f.name)),
        # 寫給唸 advisory 二件（cxp r2 2026-08-12；WARN-only 永不 FAIL — 得標定稿 §2 紅線）
        ("C-018",  chk_c018_readability(data, f.name)),
        # 零件庫三欄硬閘（T1a cxp-enforce-t1 2026-08-13）：新格式批缺欄/非法 enum＝FAIL；
        # 舊稿批 SKIP 明標（grandfather），三欄仍由上面的 C-PARTS-001 出 WARN。
        ("C-PARTS-002", chk_parts_002_component_enums_enforce(
            data, f.name, enforce_generation=enforce_generation)),
        # §21 誠實天花板（per-file，2026-06-17 機器化 §21 落地；P1-3：傳 is_skeleton 區分骨架/已填完）
        # P1-B（Codex 第 2 輪退回修）：C-21.7 skeleton 判定改**逐檔自身**，不用批次全域 bool。
        # 根因：混合批（7 支 title placeholder + 6 支已填但缺誠實欄）→ 批次全域 _is_skeleton_mode=True
        # 會把那 6 支已填的也當骨架 SKIP，違反 spec「已填缺欄必 FAIL」。
        # 修法：某支只有「它自己的 title 是 placeholder」時才算骨架階段；title 已填（真標題）
        # 但誠實欄缺 → FAIL（過渡 WARN）。
        ("C-21.7", chk_c21_7_honest_ceiling(data, _fname_with_dir, _is_placeholder(data.get("title")))),
        ("R-CTA-001", chk_r_cta_001_cta_fields_complete(data, _fname_with_dir, _is_placeholder(data.get("title")))),
        # v2 新增 5 件（V2-001 ~ V2-005）
        ("V2-001",  chk_v2_001_voice_lock(data, f.name, owner)),
        ("V2-001b", chk_v2_001b_banned_phrases(data, _fname_with_dir, owner)),
        ("V2-001c", chk_v2_001c_catchphrase_in_hook(data, _fname_with_dir, owner)),
        ("V2-002", chk_v2_002_policy_alignment(data, f.name, owner)),
        ("V2-003", chk_v2_003_publish_distribution_mode(data, f.name)),
        ("V2-004", chk_v2_004_platform_variants(data, f.name)),
        ("V2-005", chk_v2_005_trial_reels_consistency(data, f.name)),
        # 【p4exec1 殺單 #66 KEEP-CANDIDATE｜安全/法規類零開火但保留】醫師法 §28 刑事紅線
        # （L1.BEAUTY.DOCTOR_LAW）。零開火＝三批無美容業主稿件，非證明規則無效。
        ("V2-012",  chk_v2_012_beauty_med_words(data, f.name, owner)),
    ]
    # v4 新增 2 件（2026-05-31 爆款範本引用系統）
    # BUG-6/7 修（2026-06-05）：骨架階段（編劇未填）跳過 V2-025/026，
    # 避免骨架的 template_source_ids:[] + template_adaptation placeholder 系統性 FAIL。
    # 已填編劇的真實批次（is_skeleton=False）照常驗，不放水。
    if is_skeleton:
        checks.append(("V2-025", ("SKIP", "骨架階段跳過（編劇尚未填範本引用，等填完後再驗）")))
    else:
        # P1-1：V2-025 改傳 _fname_with_dir 讓日期解析能吃批次目錄名
        checks.append(("V2-025", chk_v2_025_template_source_required(data, _fname_with_dir)))

    # WP-B V3-001：topic_intel provenance（off 時函式自己回 SKIP，零足跡；policy on 才訂冊）
    if topic_intel_policy.get("enabled"):
        checks.append(("V3-001", chk_topic_intel_provenance(
            data, _fname_with_dir, topic_intel_policy, is_skeleton, owner=owner
        )))

    checks.append(("C-22-OFFPRO-ANGLE",   chk_c22_offpro_angle(data, f.name)))

    # ── 梯 2（cxp-enforce-t2 r1 2026-08-13）：chxp receipt ＋ 8 個方法硬閘 ──
    # 世代分流沿用同一份 enforce_generation（T1 F1 單一真源，不另立判準）。
    # 骨架階段判定＝**逐檔自身** title placeholder（同 C-21.7 P1-B 教訓：
    # 不用批次全域 bool，否則混合批會把已填完的稿一起放過）。
    _t2_file_skeleton = _is_placeholder(data.get("title"))
    checks.append(("C-CXP-RECEIPT", chk_cxp_receipt(
        data, f.name, enforce_generation=enforce_generation,
        is_skeleton_file=_t2_file_skeleton)))
    for _cxp_cid, _cxp_res in chxp_gate_checks(
        data, f.name, enforce_generation=enforce_generation,
        is_skeleton_file=_t2_file_skeleton,
    ):
        checks.append((_cxp_cid, _cxp_res))

    for cid, (status, detail) in checks:
        results.append((cid, status, f.name, detail))
    return results


def run_c016_all(lib_dir):
    """B-1（2026-06-15 WP2）：對 owner_projection 內所有 owner 的公開 HTML 跑 C-016 派系名洩漏掃描。
    取代 pre-commit Part 3.5 hardcoded 7-業主清單（漏新業主、楷甯被跳過導致派系名洩漏 production 的根因）。
    owner 清單 = _OWNER_HTML_MAP.keys()（projection-derived，新業主登記後自動納入）。
    WARN（HTML 缺失/讀取失敗/未知業主）對 projection-listed owner 視為 FAIL（防 silent-skip class）。
    """
    owners = list(_OWNER_HTML_MAP.keys())
    print(f"[C-016-ALL] 掃描 projection {len(owners)} 業主公開 HTML 派系名洩漏")
    failed = False
    for owner in owners:
        status, msg = chk_c016_no_faction_leak_in_html(owner, lib_dir)
        print(f"  {owner}: {status}: {msg}")
        if status != "PASS":
            failed = True
    if failed:
        print("❌ C-016-ALL：有業主派系名洩漏、HTML 缺失或讀取失敗（WARN 亦視為 FAIL）")
    else:
        print(f"✅ C-016-ALL：{len(owners)} 業主公開 HTML 全無派系名洩漏")
    return 1 if failed else 0


# ────────────────────────────────────────────
# 主程式
# ────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="腳本批次品管員（含 V2 schema + voice_lock 守門）")
    parser.add_argument("--owner",     help="業主名（以 owner_projection.generated.json 為準，不傳則從首個 yaml 的 owner 欄自動偵測）")
    parser.add_argument("--batch-dir", required=False, help="第 N 批 yaml 資料夾絕對路徑（--c016-all 模式不需）")
    parser.add_argument("--topic-plan", help="hybrid topic_plan.json path for C-plan-lock")
    parser.add_argument("--strict",    action="store_true", help="任一 FAIL → exit 1（pre-commit 模式）")
    parser.add_argument("--c016-all",  action="store_true", help="B-1：掃描 owner_projection 全業主公開 HTML 的 C-016 派系名洩漏（取代 pre-commit hardcoded 清單）")
    parser.add_argument(
        "--stage",
        choices=list(STAGE_CHOICES),
        default="final",
        help=(
            "驗證階段：pre-panel＝評審團前跑，跳過 C-taste-panel（明標 SKIP、panel 後補驗），其餘檢查照常；"
            "final（預設）＝現行為，全部件照驗"
        ),
    )
    args = parser.parse_args()

    # B-1（WP2）：C-016 全業主掃描模式（projection-derived，新業主自動納入；不需 --batch-dir）
    if args.c016_all:
        sys.exit(run_c016_all(Path(__file__).resolve().parent))

    if not args.batch_dir:
        parser.error("--batch-dir 為必填（除非使用 --c016-all）")

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

    # ── WP-B topic_intel policy（off 時零足跡：不 import、不讀、不印 topic-intel 行）──
    _topic_intel_policy: dict = {"mode": "off", "enabled": False, "detail": "WP-B not loaded"}
    try:
        from topic_intel_policy import load_topic_intel_policy as _load_ti_policy  # type: ignore[import]
        _topic_intel_policy = _load_ti_policy(batch_dir)
    except ImportError:
        pass  # topic_intel_policy.py 未部署 → 保持 disabled
    if _topic_intel_policy.get("enabled"):
        print(f"[INFO] WP-B 選題情報模式：{_topic_intel_policy['mode']}（{_topic_intel_policy.get('detail','')}）\n")
    elif _topic_intel_policy.get("mode") == "invalid":
        # Fix P0-2：invalid policy（有寫 topic_intel_closure 但設定不合法）→ fail-closed
        # 只有「無 _batch_flags.yml」或明確 mode=off 才 disabled 零足跡；invalid ≠ off
        print(f"[ERROR] WP-B topic_intel_closure 設定不合法（invalid），fail-closed 擋批：{_topic_intel_policy.get('detail','')}\n")

    all_results: list[tuple[str, str, str, str]] = []

    # ── W4-K12（2026-07-16）：批次 time_axis 選填宣告，每批 resolve 恰一次（Delta B 收刀驗證）──
    _time_axis, _time_axis_error = _resolve_batch_time_axis(batch_dir)
    _l1000_result = chk_l1_000_time_axis(_time_axis, _time_axis_error)

    # ── T1 世代判定（cxp-enforce-t1；r2 2026-08-13 提前到 batch checks 之前）──
    # 🔴 F1（Codex 阻擋項 1）：全批**算一次**，同一份 (bool, reason) 同時餵
    #   C-TOPIC-LOCK（batch check）與 T1 三閘（per-file checks）——不可能分岔。
    #   [INFO] 印在原本位置（per-file 段前），保持輸出格式不變。
    _enforce_generation, _enforce_reason = _resolve_enforce_generation(
        batch_dir, valid_yamls, args.topic_plan
    )

    # ── Batch-level checks（L1-008 / L1-009 / C-011 / C-012 / C-014[RETIRED] + C-013B + v3 新 6 件）──
    batch_checks = [
        # 【p4exec1 殺單 #62 KEEP-CANDIDATE｜零開火但保留】對映憲法 §15 Q1-Q8 配額
        # （澤君 TG22396/22399/22401 全業主永久制）。零開火＝三批皆 2026-08-26 前舊批
        # grandfather SKIP。替代物：active_rules.yaml candidates（新批上線後升 active）。
        ("R-TYPE-001", chk_r_type_001_topic_type_quota(yamls)),
        # 【p4exec1 殺單 #61 KEEP-CANDIDATE｜零開火但保留】對映憲法 §8 三源制＋源④配額
        # （澤君 TG22317）。零開火因 schema 尚無 origin_source 欄（全批 SKIP）＝欄位未落地，
        # 非規則無效。替代物：active_rules.yaml candidates（補欄後升 active，立一退一）。
        ("R-SRC-001", chk_r_src_001_origin_source(yamls)),
        ("L1-009", chk_l1_009_派系_coverage(valid_yamls)),
        ("C-011",  chk_c011_派系_ratio(valid_yamls, owner, pref_text)),
        ("C-012",  chk_c012_identity_ratio(valid_yamls, owner, pref_text)),
        # C-014 retired (W2-C撤收 2026-07-14) — ID reserved, 勿重編其他 check
        # v3 新增 6 件 batch checks（2026-05-23 三審修補）
        ("V2-006", chk_v2_006_required_slot(valid_yamls, fishing_policy)),
        # 【p4exec1 殺單 #63 KEEP-CANDIDATE｜零開火但保留】對映憲法 §14「14 部＋7 篇脆文
        # 缺一不放行」（澤君 TG22401）；刪除＝該鐵則失去唯一機驗落點。待澤君裁（ask_zejun Q3）。
        ("V2-007", chk_v2_007_threads_seven(batch_dir, valid_yamls)),
        ("V2-008", chk_v2_008_used_titles_dedup(valid_yamls, owner)),
        ("V2-009", chk_v2_009_auditor_report(batch_dir, owner)),
        ("V2-010", chk_v2_010_batch_summary(batch_dir)),
        # V2-012B（2026-07-07 W2 品管工單）：美容業主獨立脆文 md 醫療詞掃描（V2-012 per-file 只掃 yaml）
        # 【p4exec1 殺單 #67 KEEP-CANDIDATE｜安全/法規類零開火但保留】同 V2-012；此件正為補
        # 「昀臻14批脆文『發炎』機器綠燈、算盤人工才抓到」而建。
        ("V2-012B", chk_v2_012b_threads_med_words(batch_dir, owner)),
        # P3 比例驗證器（2026-06-08）
        ("C-cta-mix",     chk_c_cta_mix(valid_yamls, owner, pref_text, batch_tag)),
        ("C-content-mix", chk_c_content_mix(valid_yamls, owner, pref_text, batch_tag)),
        # §21 腳本品質公式 batch-level（2026-06-17 機器化 §21 落地）
        ("C-21.2", chk_c21_2_cta_diversity(valid_yamls, owner, pref_text, batch_tag)),
        ("C-21.6", chk_c21_6_quality_gate_report(valid_yamls, batch_dir)),
        # W1（cxp-gapfix-w1 2026-08-13）：題目鎖正式檢查（Codex 洞 02／龍蝦 P0-3）
        # T1 r2：世代由上方單一 resolver 傳入（F1），legacy 世代 SKIP 明標、
        # new 世代逐欄比對＋lock hash 驗＋整批缺鎖 FAIL（F2 防自降級）。
        ("C-TOPIC-LOCK", chk_topic_lock_consistency(
            valid_yamls, batch_dir, args.topic_plan,
            enforce_generation=_enforce_generation, generation_reason=_enforce_reason)),
    ]
    # W4-K12：L1-000-time-axis 缺省零註冊（None＝鍵缺席，不 append，all_results 無此列）
    if _l1000_result is not None:
        batch_checks.append(("L1-000-time-axis", _l1000_result))
    # Fix A【P0】V3-002 gated：只有 policy enabled 才 append，off 時完全不註冊（零足跡）
    # off → 不 append V3-002 → batch_checks 件數、len 印出維持原值；無 SKIP 行
    # Fix P0-2：invalid → fail-closed，加 V3-000-policy FAIL（invalid ≠ off）
    if _topic_intel_policy.get("mode") == "invalid":
        batch_checks.append((
            "V3-000-policy",
            ("FAIL", f"topic_intel_closure 設定不合法（invalid），fail-closed 擋批：{_topic_intel_policy.get('detail','')}"),
        ))
    elif _topic_intel_policy.get("enabled"):
        batch_checks.append(
            ("V3-002", chk_v3_002_batch_slot_count(valid_yamls, _topic_intel_policy))
        )
        # R5 Fix 4：批次唯一 topic_id（shadow WARN，不升 enforce）
        batch_checks.append(
            ("V3-001b", chk_v3_001b_topic_id_unique(valid_yamls, _topic_intel_policy))
        )
    # C-22b anchor_first 機械閘（Cluster A v1.1；2026-06-23 已翻 enforce-live）—
    # 只對 proof_mode == anchor_first 的支跑；無此類支則零 append（零足跡，沿用 V3-002 off 邏輯）。
    for _c22b_f, _c22b_data in valid_yamls:
        if isinstance(_c22b_data, dict) and _c22b_data.get("proof_mode") == "anchor_first":
            batch_checks.append((
                "C-22b anchor_first 機械閘",
                chk_c22b_anchor_first(_c22b_data, _c22b_f.name, valid_yamls, owner),
            ))
    # chk_anchor_registry_ref（平行 shadow check，2026-06-20）—
    # 只對 proof_mode == anchor_first 且 anchor_ref 形如 registry id 的支跑；
    # free-text anchor_ref → PASS（不干擾 chk_c22b）。零足跡設計，WARN-only。
    for _arf, _ard in valid_yamls:
        if isinstance(_ard, dict) and _ard.get("proof_mode") == "anchor_first":
            batch_checks.append((
                "chk_anchor_registry_ref",
                chk_anchor_registry_ref(_ard, _arf.name, owner),
            ))
    print(f"── 批次級 check（{len(batch_checks)} 件）──")
    for cid, (status, detail) in batch_checks:
        icon = "✅" if status == "PASS" else ("⚠️ " if status == "WARN" else ("➖" if status == "SKIP" else "❌"))
        print(f"  {icon} [{cid}] {status}: {detail}")
        all_results.append((cid, status, "batch", detail))
    print()

    # ── Per-file checks（件數動態，避免數字過時）──
    # BUG-6/7 修（2026-06-05）：偵測骨架模式，骨架階段跳過 V2-025/026
    _skeleton_mode = _is_skeleton_mode(valid_yamls)
    if _skeleton_mode:
        print("[INFO] 偵測到骨架模式（批次 >= 50% yaml 的 title 為 placeholder）— V2-025/026 本批跳過")
    # D20（W2-D20 2026-07-13）：批次級世代偵測，純 legacy 批 D20 記 legacy_pre_hybrid_batch
    _hybrid_batch = _is_hybrid_batch(batch_dir, valid_yamls)
    if not _hybrid_batch:
        print("[INFO] D20：全批無 hybrid 標記（純 legacy 批）— D20-proof-mode-enum 記 legacy_pre_hybrid_batch")
    # T1（cxp-enforce-t1；r2 2026-08-13）：世代判定已在 batch checks 之前算過**恰一次**
    # （F1 單一真源），此處只印結果，不重算。
    print(f"[INFO] T1 世代判定：{'new 世代（enforce）' if _enforce_generation else 'legacy 世代（grandfather）'}"
          f" — {_enforce_reason}")
    _per_file_results_count: int = 0  # 第一支跑完後更新
    print("── 逐篇 check（per-file × 每篇）──")
    for f, data in valid_yamls:
        title = data.get("title", f.name)
        print(f"\n  [{f.name}] {title}")
        per_results = run_per_file_checks(
            f, data, owner,
            is_skeleton=_skeleton_mode,
            fishing_policy=fishing_policy,
            topic_intel_policy=_topic_intel_policy,
            hybrid_batch=_hybrid_batch,
            time_axis=_time_axis,
            time_axis_error=_time_axis_error,
            enforce_generation=_enforce_generation,
        )
        for cid, status, fname, detail in per_results:
            icon = "✅" if status == "PASS" else ("⚠️ " if status == "WARN" else ("➖" if status == "SKIP" else "❌"))
            print(f"    {icon} [{cid}] {status}: {detail}")
            all_results.append((cid, status, fname, detail))

    # ── 彙總 ──
    fail_count = sum(1 for _, s, _, _ in all_results if s == "FAIL")
    warn_count = sum(1 for _, s, _, _ in all_results if s == "WARN")
    pass_count = sum(1 for _, s, _, _ in all_results if s == "PASS")
    skip_count = sum(1 for _, s, _, _ in all_results if s == "SKIP")
    total = len(all_results)

    print(f"\n{'='*60}")
    print(f"  品管彙總：{pass_count} PASS / {warn_count} WARN / {fail_count} FAIL / {skip_count} SKIP（共 {total} 件）")
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

    # ── WP-B PASS report（machine-readable，供 reconciler 吃）──
    # Fix B【P0】條件：policy enabled + 非骨架 + 無 FAIL；骨架不產 PASS report 防 reconciler 提前記 used
    # off 時零足跡不輸出任何 topic-intel 報告
    if _topic_intel_policy.get("enabled") and not _skeleton_mode and fail_count == 0:
        import hashlib as _hashlib
        import datetime as _datetime

        # 收集所有 V3-001 PASS 的 topic_intel 資料
        # 修 7（R5 帳本失真 bug）：被 R5-3「題目疑似不同」WARN 的項標 topic_fidelity_flagged=True
        # R5-3b（AI語意閘）也使用「題目疑似不同」短語 → 同一條件同時捕捉 keyword + AI 兩道閘的 flag
        # 修 10 後實際鏈：validator 標 flag → reconciler 帶入 events.jsonl（修 10a）
        #                → load_offered 拆 offered_by_batch_clean（修 10b）
        #                → compute_slos 在 adoption_rate["clean"] 呈報乾淨採用率
        # （選標記而非排除：shadow WARN 哲學，透明稽核，flag 由下游 observability 分開呈報）
        _r5_3_flagged_fnames: set = {
            fname
            for cid, status, fname, detail in all_results
            if cid == "V3-001" and status == "WARN" and "題目疑似不同" in detail
        }

        v3_pass_items = []
        batch_id_from_yaml = valid_yamls[0][1].get("batch_tag", batch_dir.name) if valid_yamls else batch_dir.name
        for f, data in valid_yamls:
            sti = data.get("source_topic_intel")
            if not sti or not isinstance(sti, dict):
                continue
            script_id = data.get("script_id", f.stem)
            _item: dict = {
                "topic_id": sti.get("topic_id", ""),
                "script_id": script_id,
                "batch_id": batch_id_from_yaml,
                "evidence_sha256": sti.get("evidence_sha256", ""),
                "assignment_mode": sti.get("assignment_mode", _topic_intel_policy.get("mode", "off")),
            }
            if f.name in _r5_3_flagged_fnames:
                _item["topic_fidelity_flagged"] = True  # R5-3 shadow WARN；下游 adoption_rate 跳過此項
            v3_pass_items.append(_item)

        # Fix C【P0】反查 owner_code（全鏈統一用 owner_code 當 key）
        _owner_code_for_report: str = ""
        try:
            _op_path = Path(__file__).resolve().parent / "owner_projection.generated.json"
            if _op_path.exists():
                _op_data = json.loads(_op_path.read_text(encoding="utf-8"))
                _op_owners = _op_data.get("owners", {})
                _owner_info = _op_owners.get(owner, {})
                _owner_code_for_report = str(_owner_info.get("owner_code", "") or "")
        except Exception:
            pass

        # Fix 2b【P0】owner_code 反查空 → enforce 視為缺證據，不產 report
        if v3_pass_items and not _owner_code_for_report:
            print(
                f"[WP-B] WARN: owner_code 反查失敗（owner={owner!r}），"
                "enforce 視為缺 owner_code 證據，不產 PASS report（fail-loud）",
                file=sys.stderr,
            )
            v3_pass_items = []  # 清空，跳過下方 report 產出

        if v3_pass_items:
            report_body = {
                "schema_version": 1,
                "generated_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
                "batch_dir": str(batch_dir),
                "owner": owner,
                "owner_code": _owner_code_for_report,  # Fix C+Fix2b：全鏈統一用 owner_code 當 key
                "owner_name": owner,                   # Fix C：中文名另存，供顯示
                "is_skeleton": False,                  # Fix B：骨架不產此 report，故必然 False
                "batch_id": batch_id_from_yaml,
                "topic_intel_mode": _topic_intel_policy.get("mode"),
                "items": v3_pass_items,
            }
            # validator_report_sha256（reconciler 用冪等鍵）
            _report_canonical = json.dumps(report_body, ensure_ascii=False, sort_keys=True)
            _report_sha = _hashlib.sha256(_report_canonical.encode("utf-8")).hexdigest()
            report_body["validator_report_sha256"] = _report_sha

            _report_path = batch_dir / "_topic_intel_validator_report.json"
            try:
                _report_path.write_text(
                    json.dumps(report_body, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"[WP-B] PASS report 已輸出：{_report_path}（{len(v3_pass_items)} 項）")
                print(f"[WP-B] validator_report_sha256: {_report_sha}")
            except Exception as _re:
                print(f"[WP-B] WARN: PASS report 寫入失敗（{_re}），繼續不擋部署")

    if args.strict and fail_count > 0:
        sys.exit(1)
    if not args.strict and fail_count > 0:
        sys.exit(1)
    sys.exit(0)


# ════════════════════════════════════════════
# 選題候選粗篩（件 A shadow，2026-06-26）
# ════════════════════════════════════════════
# 用 C-22 同把尺（_s22_count_signals）對題目候選字串做紅黃綠粗篩。
# 紅＝零訊號且含 FAQ 句型詞（明顯通用）；黃＝零訊號且無 FAQ；綠＝≥1 訊號。
# shadow only：不硬擋出批、不改既有 C-22 邏輯。
# ════════════════════════════════════════════

_PREFILTER_FAQ_PATTERNS: list[str] = [
    "怎麼", "如何", "要注意", "哪個好", "可不可以", "應不應該",
    "對嗎", "好嗎", "值不值", "有什麼", "有哪些",
]


def run_topic_prefilter(
    topics: list[str],
    owner: str = "",
) -> list[dict]:
    """選題候選粗篩（shadow only，件 A 2026-06-26）。

    輸入題目候選字串清單，回每題的紅黃綠標記 + 訊號明細。
    用既有 _s22_count_signals() 同把尺，不另開平行系統。

    判準（v1）：
    - 紅（明顯通用）：total=0 AND 含 _PREFILTER_FAQ_PATTERNS 任一詞
    - 黃（零訊號非 FAQ）：total=0 AND 無 FAQ 詞（off-pro 立場題短情感金句）
    - 綠（有具體訊號）：total >= 1

    誠實定位：
    - 不參與評分，不預測 D1/D3/D4/D5
    - 只擋 FAQ 型明顯通用題；對 off-pro 立場題寬容（黃不擋出批）
    - 不替代 batch-level C-22 check（C-22 照跑不退場）
    """
    results: list[dict] = []
    for t in topics:
        t_s = str(t).strip() if t else ""
        total, hard, hits = _s22_count_signals(t_s, owner)
        is_faq = any(w in t_s for w in _PREFILTER_FAQ_PATTERNS)
        if total == 0 and is_faq:
            flag = "紅"
            reason = "零訊號+FAQ句型（明顯通用，建議換角度）"
        elif total == 0:
            flag = "黃"
            reason = "零訊號、無FAQ句型（off-pro立場題範圍，請確認角度不空泛）"
        else:
            hit_keys = [k for k, v in hits.items() if v]
            flag = "綠"
            reason = f"訊號 total={total} hard={hard}（命中：{hit_keys}）"
        results.append({
            "topic": t_s,
            "flag": flag,
            "total": total,
            "hard": hard,
            "hits": hits,
            "reason": reason,
        })
    return results


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

        # 6/24 enforce flip（2026-06-23）：以下 check 由 shadow(WARN) 翻 enforce(FAIL)；
        # 測試期望隨 flag 走 → rollback（flag→False）自動回 WARN、測試不破（非硬編 regime）。
        _EXP_S216 = "FAIL" if _S21_6_REPORT_ENFORCE else "WARN"
        _EXP_S22 = "FAIL" if _S22_ENFORCE else "WARN"
        _EXP_ANCHOR = "FAIL" if ANCHOR_FIRST_ENFORCE else "WARN"
        _EXP_LEAK = "FAIL" if _OFFPRO_LEAK_ENFORCE else "WARN"
        _EXP_HYBRID_PLAN = "FAIL" if _HYBRID_PLAN_LOCK_ENFORCE else "WARN"
        _EXP_HYBRID_METHOD = "FAIL" if _HYBRID_METHOD_ENFORCE else "WARN"
        _EXP_HYBRID_FRIEND = "FAIL" if _HYBRID_FRIEND_CLOSE_ENFORCE else "WARN"
        _EXP_HYBRID_PRO = "FAIL" if _HYBRID_PROFESSIONAL_ENFORCE else "WARN"
        _EXP_TASTE = "FAIL" if _TASTE_PANEL_ENFORCE else "WARN"

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

        # ── F10L V2-026 legacy：缺 template_adaptation，fname 含 < 6/1 日期 → WARN ──

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

        # ── F11L V2-026 legacy：缺 changed_context，fname 含 < 6/1 日期 → WARN ──

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

        # ── F14L V2-026 legacy：adaptation 是 str，fname 含 < 6/1 日期 → WARN ──

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

        # ── F14bL V2-026 legacy：placeholder，fname 含 < 6/1 日期 → WARN + placeholder 在訊息 ──

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

        # ── F14cL V2-026 legacy：fcc=pending，fname 含 < 6/1 日期 → WARN + forbidden_copy_check 在訊息 ──

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
            # C-013 per-file 應 FAIL（驗三層真串通）
            _fishing_yaml_data = _fish2_yamls[3]  # 第 4 支釣魚腳本 data
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
            # V2-006 4 強制位
            _r2 = chk_v2_006_required_slot(_f3_ydata, _f3_policy)
            fcheck("F-FISH3 V2-006 4強制位 PASS", _r2[0] == "PASS", _r2[1])
            # C-013 per-file 釣魚腳本 PASS
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

        # ── F-FISH5：legacy 模式（2026-06-05 無旗標）+ 釣魚腳本含完整 dm_card → PASS（舊批豁免）──
        print("\n[F-FISH5] legacy 模式（2026-06-05 無旗標舊批）+ 釣魚腳本有完整 dm_card → C-013 PASS（dm_card 缺仍 FAIL）")
        # 測試 legacy PASS 路徑
        _fish5_yaml_ok = {
            "title": "釣魚部", "required_slot": "釣魚部", "is_fishing": True,
            "dm_card": {"行業專業": "x", "在地優勢": "x", "痛點": "x", "解法": "x", "行動呼籲": "x", "LINE QR": "x"},
        }
        _f5_policy = {"mode": "legacy", "batch_date": _dt.date(2026, 6, 5),
                      "detail": "無旗標 + 批次日期 2026-06-05 < 2026-06-06 → legacy"}
        # 驗 legacy dm_card 缺仍 FAIL（不趁 cutover 放水）
        _fish5_yaml_bad = {
            "title": "釣魚部", "required_slot": "釣魚部", "is_fishing": True,
            # 故意不給 dm_card
        }

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
        _f6_off = {"mode": "off", "batch_date": _dt.date(2026, 6, 10), "detail": "off 測試 F-FISH6"}

        # ── F-FISH7（保鏢硬條件2 / Codex must-fix）：opt_in + dm_card 6 件齊但「缺圖片資產路徑」→ FAIL
        #    封「validator 6 件驗過、但網站圖卡空白」漏洞。有 asset_path → PASS ──
        print("\n[F-FISH7] opt_in + dm_card 6 件齊但缺 asset_path → C-013 FAIL（圖卡交付鏈）")
        _f7_policy = {"mode": "opt_in", "batch_date": _dt.date(2026, 6, 6), "detail": "opt_in 測試 F-FISH7"}
        _fish7_no_asset = {
            "title": "釣魚部測試", "required_slot": "釣魚部", "is_fishing": True,
            "dm_card": {"行業專業": "x", "在地優勢": "x", "痛點": "x", "解法": "x", "行動呼籲": "x", "LINE QR": "x"},
            # 故意不給 asset_path / img
        }
        _fish7_with_asset = dict(_fish7_no_asset)
        _fish7_with_asset["dm_card"] = dict(_fish7_no_asset["dm_card"], asset_path="assets/dm_cards/x.png")

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

        # ── F23 C-017 具體化密度（2026-06-11 課程導入 W3 — 含分類欄位填錯負向案例）──
        print("\n[F23] C-017 具體化密度 WARN-only + 分類欄位填錯防護")
        # F23a：知識型（拆解派）主體段無具體信號 → WARN
        _f23a = {
            "主推派系": "拆解派",
            "scenes": [
                {"timestamp": "0-3s", "台詞_測": "你知道嗎"},
                {"timestamp": "12-25s", "台詞_測": "這件事其實有方法可以處理，重點是觀念要對"},
                {"timestamp": "25-40s", "台詞_測": "把心態調整好，事情自然就會順"},
            ],
        }
        _r23a = chk_c017_concreteness(_f23a, "f23a.yaml")
        fcheck("F23a 知識型無具體信號 → WARN", _r23a[0] == "WARN", _r23a[1])
        # F23b：知識型主體段有數字/時間 → PASS
        _f23b = {
            "主推派系": "拆解派",
            "scenes": [
                {"timestamp": "12-25s", "台詞_測": "上個月一位客戶多付了 80 萬，因為他不知道這 3 件事"},
            ],
        }
        _r23b = chk_c017_concreteness(_f23b, "f23b.yaml")
        fcheck("F23b 知識型具體信號 ≥2 → PASS", _r23b[0] == "PASS", _r23b[1])
        # F23c：雞湯/感性型 → 豁免 PASS（不轟炸）
        _f23c = {
            "主推派系": "人間觀察派",
            "schema_check": {"CTA類型": "純雞湯"},
            "scenes": [{"timestamp": "12-25s", "台詞_測": "慢慢來，比較快"}],
        }
        _r23c = chk_c017_concreteness(_f23c, "f23c.yaml")
        fcheck("F23c 雞湯型豁免 → PASS", _r23c[0] == "PASS", _r23c[1])
        # F23d：分類欄位填錯（schema_check 是字串非 dict、派系亂填）→ 豁免不誤傷（御史 M6 負向案例）
        _f23d = {
            "主推派系": "不存在的派",
            "schema_check": "我填錯了不是dict",
            "scenes": [{"timestamp": "12-25s", "台詞_測": "隨便"}],
        }
        _r23d = chk_c017_concreteness(_f23d, "f23d.yaml")
        fcheck("F23d 分類欄位填錯 → 豁免 PASS 不誤傷", _r23d[0] == "PASS", _r23d[1])
        # F23e：scenes 整個壞型別 → fail-open PASS（永不炸 validator）
        _f23e = {"主推派系": "拆解派", "scenes": "不是list"}
        _r23e = chk_c017_concreteness(_f23e, "f23e.yaml")
        fcheck("F23e scenes 壞型別 → fail-open PASS", _r23e[0] == "PASS", _r23e[1])
        # F23f（Codex r6 P2）：非知識型骨架（非雞湯 CTA）→ PASS 且訊息走「非知識型骨架」分支
        _f23f = {
            "主推派系": "人間觀察派",
            "schema_check": {"CTA類型": "個人化諮詢型"},
            "scenes": [{"timestamp": "12-25s", "台詞_測": "隨便講講"}],
        }
        _r23f = chk_c017_concreteness(_f23f, "f23f.yaml")
        fcheck("F23f 非知識型訊息分支 → PASS 含「非知識型骨架」", _r23f[0] == "PASS" and "非知識型骨架" in _r23f[1], _r23f[1])

        # ── F24 V2-008 v2 同題開放（2026-06-11 澤君拍板 TG 9755）──
        print("\n[F24] V2-008 v2 同題開放：標題同題 WARN / 全文雷同 FAIL")
        _f24_used = ["頭期款不夠怎麼辦"]
        _f24_hit = difflib.SequenceMatcher(None, "頭期款不夠怎麼辦", _f24_used[0]).ratio() >= 0.65
        _f24_dup_a = _v2008_content_dup_hits([("a.yaml", "今天講頭期款，重點是自備款比例和銀行眼中的還款能力，這兩件先弄懂"), ("b.yaml", "頭期款這題我用另一個角度講：先看你家庭現金流，再回推能扛的月付")], [], 0.85)
        fcheck("F24a 同題異文 → 標題命中但全文 0 雷同（WARN 級非 FAIL）", _f24_hit and not _f24_dup_a, f"title_hit={_f24_hit} dup={_f24_dup_a}")
        _f24_txt = "今天講頭期款，重點是自備款比例和銀行眼中的還款能力，這兩件先弄懂，最後記得問問不用錢"
        _f24_dup_b = _v2008_content_dup_hits([("a.yaml", _f24_txt), ("b.yaml", _f24_txt)], [], 0.85)
        fcheck("F24b 批內全文一模一樣 → 雷同 FAIL 級", len(_f24_dup_b) == 1 and _f24_dup_b[0][2] >= 0.85, str(_f24_dup_b))
        _f24_dup_c = _v2008_content_dup_hits([("new.yaml", _f24_txt)], [("房仲_仲豪/第12批/script_x.yaml", _f24_txt)], 0.85)
        fcheck("F24c 跨業主歷史全文雷同 → FAIL 級（R1-hard）", len(_f24_dup_c) == 1, str(_f24_dup_c))
        fcheck("F24d 長度差 >30% 預過濾不誤殺", _v2008_content_dup_hits([("a", "短句")], [("b", _f24_txt)], 0.85) == [], "prefilter ok")

        # ── F-21 §21 腳本品質公式 check（2026-06-17 機器化 §21）──
        print("\n[F-21] §21 腳本品質公式：破套路 / CTA 多樣 / 誠實天花板 / 過渡期 WARN")
        import datetime as _f21_dt
        _POST = "2026-06-25"   # >= _S21_EFFECTIVE_FROM(2026-06-24) → FAIL 路徑
        _PRE = "2026-06-20"    # < _S21_EFFECTIVE_FROM → WARN-waiver

        def _mk(seq, pattern, cta, date_str, **extra):
            """造一支 §21 測試 yaml（含 batch_date + pattern + schema_check.CTA類型 + title 已填）"""
            d = {
                "title": f"已填標題{seq}",
                "batch_date": date_str,
                "pattern": pattern,
                "schema_check": {"CTA類型": cta},
            }
            d.update(extra)
            return (Path(f"f21_{seq:02d}.yaml"), d)

        # F-21a：破套路觸發（post-cutover，13 支 7 支同骨架 → FAIL）
        print("[F-21a] C-21.1 破套路：7/13 同骨架 post-cutover → FAIL")
        _f21a = [_mk(i, "創業故事型", "互動留言型", _POST) for i in range(1, 8)]   # 7 支同
        _f21a += [_mk(i, f"骨架{i}", f"CTA{i}", _POST) for i in range(8, 14)]       # 6 支各異

        # F-21a2：未觸發（最多 6 支同 < 7）→ PASS
        print("[F-21a2] C-21.1 破套路：最多 6/13 同骨架 → PASS")
        _f21a2 = [_mk(i, "創業故事型", "互動留言型", _POST) for i in range(1, 7)]  # 6 支同
        _f21a2 += [_mk(i, f"骨架{i}", f"CTA{i}", _POST) for i in range(7, 14)]      # 7 支各異

        # F-21a3：系列批（series_id+episode）→ WARN（豁免主公式但提醒人工查）
        print("[F-21a3] C-21.1 系列批 series_id+episode → WARN 提醒")
        _f21a3 = [_mk(i, "PREP型", "互動留言型", _POST, series_id="總督", episode=i) for i in range(1, 14)]

        # F-21b：CTA 不足 3 種（post-cutover）→ FAIL
        print("[F-21b] C-21.2 CTA 只 2 種 post-cutover → FAIL")
        _f21b = [_mk(i, f"骨架{i}", "互動留言型", _POST) for i in range(1, 8)]       # 7 支同 CTA
        _f21b += [_mk(i, f"骨架{i}", "個人化諮詢型", _POST) for i in range(8, 14)]   # 6 支同 CTA（只 2 種）
        _r21b = chk_c21_2_cta_diversity(_f21b, "測試業主")
        fcheck("F-21b CTA <3 種 → FAIL", _r21b[0] == "FAIL", _r21b[1])

        # F-21b2：CTA 單一最大 > 6（post-cutover）→ FAIL（即使 3 種）
        print("[F-21b2] C-21.2 CTA 3 種但單一最大 7 支 → FAIL")
        _f21b2 = [_mk(i, f"骨架{i}", "互動留言型", _POST) for i in range(1, 8)]       # 7 支（>6）
        _f21b2 += [_mk(8, "骨架8", "個人化諮詢型", _POST)]
        _f21b2 += [_mk(i, f"骨架{i}", "分享引導型", _POST) for i in range(9, 14)]
        _r21b2 = chk_c21_2_cta_diversity(_f21b2, "測試業主")
        fcheck("F-21b2 CTA 單一最大 >6 → FAIL", _r21b2[0] == "FAIL", _r21b2[1])

        # F-21b3：CTA 3 種 + 單一最大 ≤6（post-cutover）→ PASS
        print("[F-21b3] C-21.2 CTA 3 種 + 單一 ≤6 → PASS")
        _f21b3 = [_mk(i, f"骨架{i}", "互動留言型", _POST) for i in range(1, 6)]       # 5 支
        _f21b3 += [_mk(i, f"骨架{i}", "個人化諮詢型", _POST) for i in range(6, 11)]   # 5 支
        _f21b3 += [_mk(i, f"骨架{i}", "分享引導型", _POST) for i in range(11, 14)]    # 3 支
        _r21b3 = chk_c21_2_cta_diversity(_f21b3, "測試業主")
        fcheck("F-21b3 CTA 多樣達標 → PASS", _r21b3[0] == "PASS", _r21b3[1])

        # F-21c：誠實天花板缺欄（post-cutover）→ FAIL
        print("[F-21c] C-21.7 缺 true_material_source post-cutover → FAIL")
        _f21c = {"title": "已填", "batch_date": _POST, "score_type": "angle", "claim_allowed": "角度到位"}
        _r21c = chk_c21_7_honest_ceiling(_f21c, "f21c.yaml")
        fcheck("F-21c 缺誠實欄位 → FAIL", _r21c[0] == "FAIL", _r21c[1])

        # F-21c2：true_material_source=none 卻寫「成片 90」（post-cutover）→ FAIL
        print("[F-21c2] C-21.7 none 卻寫「成片 90」→ FAIL")
        _f21c2 = {
            "title": "已填", "batch_date": _POST,
            "score_type": "script", "true_material_source": "none",
            "claim_allowed": "角度到位，成片 90 穩過",  # 違規：none 卻講成片 90
        }
        _r21c2 = chk_c21_7_honest_ceiling(_f21c2, "f21c2.yaml")
        fcheck("F-21c2 none + 成片90 → FAIL", _r21c2[0] == "FAIL", _r21c2[1])

        # F-21c3：誠實欄位齊全合法（post-cutover）→ PASS
        print("[F-21c3] C-21.7 三欄齊全合法 → PASS")
        _f21c3 = {
            "title": "已填", "batch_date": _POST,
            "score_type": "angle", "true_material_source": "none",
            "claim_allowed": "角度到位、成片估分 88 待真語料",
        }
        _r21c3 = chk_c21_7_honest_ceiling(_f21c3, "f21c3.yaml")
        fcheck("F-21c3 誠實欄位合法 → PASS", _r21c3[0] == "PASS", _r21c3[1])

        # F-21c4：三欄全缺（骨架階段 is_skeleton=True）→ SKIP（P1-3：須明示骨架階段才 SKIP）
        print("[F-21c4] C-21.7 三欄全缺骨架階段（is_skeleton=True）→ SKIP")
        _f21c4 = {"title": "[編劇填]", "batch_date": _POST}
        _r21c4 = chk_c21_7_honest_ceiling(_f21c4, "f21c4.yaml", is_skeleton=True)
        fcheck("F-21c4 三欄全缺骨架階段 → SKIP", _r21c4[0] == "SKIP", _r21c4[1])

        # F-21d：legacy/過渡期（batch_date < 2026-06-24）→ WARN 不 FAIL
        print("[F-21d] §21 過渡期 batch_date < 2026-06-24 → WARN-waiver")
        _f21d_break = [_mk(i, "創業故事型", "互動留言型", _PRE) for i in range(1, 14)]  # 13 支全同 = 必觸發
        _f21d_cta = [_mk(i, f"骨架{i}", "互動留言型", _PRE) for i in range(1, 14)]  # 全同 CTA = 必觸發
        _r21d_2 = chk_c21_2_cta_diversity(_f21d_cta, "測試業主")
        fcheck("F-21d C-21.2 過渡期觸發 → WARN（非 FAIL）", _r21d_2[0] == "WARN", _r21d_2[1])
        _f21d_honest = {"title": "已填", "batch_date": _PRE, "score_type": "angle"}  # 缺欄但過渡期
        _r21d_3 = chk_c21_7_honest_ceiling(_f21d_honest, "f21d.yaml")
        fcheck("F-21d C-21.7 過渡期缺欄 → WARN（非 FAIL）", _r21d_3[0] == "WARN", _r21d_3[1])

        # F-21e：C-21.1 骨架階段（>50% 缺 pattern，字串 placeholder）→ SKIP
        print("[F-21e] C-21.1 >50% 缺 pattern → SKIP")
        _f21e = [(_p, {"title": "[編劇填]", "batch_date": _POST, "pattern": "[編劇填]", "schema_check": {"CTA類型": "[編劇填]"}}) for _p in [Path(f"f21e_{i}.yaml") for i in range(1, 14)]]
        _r21e2 = chk_c21_2_cta_diversity(_f21e, "測試業主")
        fcheck("F-21e2 C-21.2 骨架階段 → SKIP", _r21e2[0] == "SKIP", _r21e2[1])

        # F-21e3：骨架機未引號 pattern: [編劇填] → YAML 解析成 list ['編劇填']
        #   （這是骨架機真實輸出樣態，list 一律當 placeholder，否則純骨架批會誤觸發 C-21.1）
        print("[F-21e3] C-21.1 pattern 被 YAML 解析成 list ['編劇填'] → SKIP（防純骨架誤觸發）")
        _f21e3 = [(Path(f"f21e3_{i}.yaml"), {"title": "[編劇填]", "batch_date": _POST, "pattern": ["編劇填"], "schema_check": {"CTA類型": "[編劇填]"}}) for i in range(1, 14)]

        # F-21f：C-21.6 整稿閘報告 — 缺報告（_S21_6_REPORT_ENFORCE=True：enforce 下 FAIL、flag-aware fixture）
        print("[F-21f] C-21.6 缺整稿閘報告 → WARN-only / 豁免 → PASS")
        import tempfile as _f21_tmp
        with _f21_tmp.TemporaryDirectory() as _td:
            _tdp = Path(_td)
            _r21f = chk_c21_6_quality_gate_report([(Path("x.yaml"), {"title": "已填"})], _tdp)
            fcheck(f"F-21f 缺報告 → {_EXP_S216}（enforce）", _r21f[0] == _EXP_S216, _r21f[1])
            # 有報告 → PASS
            (_tdp / "_quality_gate_report.md").write_text("R10-R20 報告", encoding="utf-8")
            _r21f2 = chk_c21_6_quality_gate_report([(Path("x.yaml"), {"title": "已填"})], _tdp)
            fcheck("F-21f2 有報告 → PASS", _r21f2[0] == "PASS", _r21f2[1])
        # F-21f3：P1-4 — 單支 yaml quality_gate_exempt 不再被認（須走 batch flag）
        print("[F-21f3] C-21.6 P1-4：單支 yaml exempt 不再認 → 走缺報告 WARN（非 PASS）")
        with _f21_tmp.TemporaryDirectory() as _td3:
            _tdp3 = Path(_td3)
            _r21f3 = chk_c21_6_quality_gate_report(
                [(Path("x.yaml"), {"title": "已填", "quality_gate_exempt": True, "quality_gate_exempt_reason": "B 級批"})],
                _tdp3,
            )
            fcheck(f"F-21f3 單支 yaml exempt 不再豁免 → {_EXP_S216}（缺報告）", _r21f3[0] == _EXP_S216, _r21f3[1])

        # ── 派工 P1 修正子步新 fixtures（2026-06-17 御史/Codex 退回修） ──
        print("\n[F-21 P1] 派工 4 P1 修正驗證")

        # ① P1-1：owner-signed 硬性 cta_mix 集中 → C-21.2 PASS（defer 給 C-cta-mix）
        print("[F-21-P1-1] C-21.2：L2 owner-signed 硬 cta_mix 集中 → PASS/defer（不擋集中）")
        _pref_hard = (
            "## cta\n```kb-rule\n"
            "category: cta_mix\nenforcement: hard\ndecision_status: confirmed\n"
            "approval_status: owner_signed\neffective_from: 2026-06-01\ntolerance_count: 1\n"
            "source_fields:\n  - [schema_check, CTA類型]\n"
            "mix:\n  - name: 個人化諮詢型\n    target_count: 12\n    aliases: [諮詢型, 個人諮詢]\n"
            "  - name: 互動留言型\n    target_count: 1\n    aliases: [互動型]\n"
            "```\n"
        )
        # 12 支同 CTA（集中）+ 1 支互動 → 若無 L2 hard 會 FAIL（單一 12>6），有 hard 應 PASS
        _f21p1 = [_mk(i, f"骨架{i}", "個人化諮詢型", _POST) for i in range(1, 13)]
        _f21p1 += [_mk(13, "骨架13", "互動留言型", _POST)]
        _r21p1 = chk_c21_2_cta_diversity(_f21p1, "瑞祥", pref_text=_pref_hard, batch_tag="2026-06-25")
        fcheck("F-21-P1-1 owner-signed 硬 cta_mix 集中 → PASS（defer）", _r21p1[0] == "PASS", _r21p1[1])

        # ② P1-1 反向：無 L2 cta_mix + 只 2 種 → C-21.2 FAIL
        print("[F-21-P1-2neg] C-21.2：無 L2 cta_mix + 只 2 種 → FAIL")
        _f21p2 = [_mk(i, f"骨架{i}", "互動留言型", _POST) for i in range(1, 8)]
        _f21p2 += [_mk(i, f"骨架{i}", "個人化諮詢型", _POST) for i in range(8, 14)]
        _r21p2 = chk_c21_2_cta_diversity(_f21p2, "測試業主", pref_text=None, batch_tag="2026-06-25")
        fcheck("F-21-P1-2neg 無 L2 cta_mix + 2 種 → FAIL", _r21p2[0] == "FAIL", _r21p2[1])

        # ③ P1-2：alias「諮詢型/個人化諮詢型」正規化後算 1 種
        print("[F-21-P1-2alias] C-21.2：諮詢型/個人化諮詢型 alias 正規化 → 算同 1 種")
        # soft cta_mix（非硬性，但有 items 供 alias 正規化）：諮詢型 與 個人化諮詢型 為同 canonical
        _pref_soft = (
            "## cta\n```kb-rule\n"
            "category: cta_mix\nenforcement: advisory\ndecision_status: proposed\n"
            "approval_status: pending_owner\ntolerance_count: 1\n"
            "source_fields:\n  - [schema_check, CTA類型]\n"
            "mix:\n  - name: 個人化諮詢型\n    target_count: 7\n    aliases: [諮詢型, 個人諮詢]\n"
            "  - name: 互動留言型\n    target_count: 6\n    aliases: [互動型]\n"
            "```\n"
        )
        # 7 支「諮詢型」+ 6 支「個人化諮詢型」→ 正規化後同 canonical = 1 種（distinct=1 < 3 → FAIL）
        # 證明 alias 被正規化算 1 種（否則會被誤算 2 種）
        _f21p3 = [_mk(i, f"骨架{i}", "諮詢型", _POST) for i in range(1, 8)]
        _f21p3 += [_mk(i, f"骨架{i}", "個人化諮詢型", _POST) for i in range(8, 14)]
        _r21p3 = chk_c21_2_cta_diversity(_f21p3, "測試業主", pref_text=_pref_soft, batch_tag="2026-06-25")
        # 正規化後 distinct=1（同 canonical），<3 種 → FAIL；detail 應只見 1 個 canonical key
        _p3_ok = (_r21p3[0] == "FAIL") and ("個人化諮詢型" in _r21p3[1]) and ("只有 1 種" in _r21p3[1])
        fcheck("F-21-P1-2alias 諮詢型 alias 正規化算 1 種 → distinct=1 FAIL", _p3_ok, _r21p3[1])

        # ④ P1-3：已填完整批缺三誠實欄（is_skeleton=False）→ FAIL
        print("[F-21-P1-3a] C-21.7：已填完腳本三欄全缺 → FAIL（誠實 gate 不放水）")
        _f21p4 = {"title": "已填完整標題", "batch_date": _POST}  # 三誠實欄全缺
        _r21p4 = chk_c21_7_honest_ceiling(_f21p4, "f21p4.yaml", is_skeleton=False)
        fcheck("F-21-P1-3a 已填完缺三欄 → FAIL", _r21p4[0] == "FAIL", _r21p4[1])

        # ⑤ P1-3：骨架階段缺三欄（is_skeleton=True）→ SKIP
        print("[F-21-P1-3b] C-21.7：骨架階段三欄全缺 → SKIP（合法）")
        _f21p5 = {"title": "[編劇填]", "batch_date": _POST}
        _r21p5 = chk_c21_7_honest_ceiling(_f21p5, "f21p5.yaml", is_skeleton=True)
        fcheck("F-21-P1-3b 骨架階段缺三欄 → SKIP", _r21p5[0] == "SKIP", _r21p5[1])

        # ⑤b P1-3 過渡期：已填完缺三欄但 batch_date<生效日 → WARN（非 FAIL）
        print("[F-21-P1-3c] C-21.7：已填完缺三欄但過渡期 → WARN")
        _f21p5c = {"title": "已填完", "batch_date": _PRE}
        _r21p5c = chk_c21_7_honest_ceiling(_f21p5c, "f21p5c.yaml", is_skeleton=False)
        fcheck("F-21-P1-3c 已填完缺三欄過渡期 → WARN", _r21p5c[0] == "WARN", _r21p5c[1])

        # ⑥ P1-4：report 0 bytes → 不算 PASS（WARN-only 現階段）
        print("[F-21-P1-4a] C-21.6：報告 0 bytes → 不算 PASS（WARN）")
        with _f21_tmp.TemporaryDirectory() as _td6:
            _tdp6 = Path(_td6)
            (_tdp6 / "_quality_gate_report.md").write_text("", encoding="utf-8")  # 0 bytes
            _r21p6 = chk_c21_6_quality_gate_report([(Path("x.yaml"), {"title": "已填"})], _tdp6)
            fcheck(f"F-21-P1-4a 0 bytes 報告 → {_EXP_S216}（非 PASS）", _r21p6[0] == _EXP_S216, _r21p6[1])
            # 對照：非空報告 → PASS
            (_tdp6 / "_quality_gate_report.md").write_text("R10-R20 逐支命中表 + GPT 打分", encoding="utf-8")
            _r21p6b = chk_c21_6_quality_gate_report([(Path("x.yaml"), {"title": "已填"})], _tdp6)
            fcheck("F-21-P1-4a2 非空報告 → PASS", _r21p6b[0] == "PASS", _r21p6b[1])

        # ⑦ P1-4：exempt 走 batch flag（_batch_flags.yml quality_gate）
        print("[F-21-P1-4b] C-21.6：batch flag quality_gate.exempt+reason → PASS")
        with _f21_tmp.TemporaryDirectory() as _td7:
            _tdp7 = Path(_td7)
            (_tdp7 / "_batch_flags.yml").write_text(
                "quality_gate:\n  exempt: true\n  reason: \"B 級批，非高規格無需整稿閘\"\n",
                encoding="utf-8",
            )
            _r21p7 = chk_c21_6_quality_gate_report([(Path("x.yaml"), {"title": "已填"})], _tdp7)
            fcheck("F-21-P1-4b batch flag exempt+reason → PASS", _r21p7[0] == "PASS", _r21p7[1])
            # exempt 但缺 reason → 豁免不成立（Codex R1 P0：shadow WARN / enforce fall-through 缺報告 FAIL）
            (_tdp7 / "_batch_flags.yml").write_text(
                "quality_gate:\n  exempt: true\n",
                encoding="utf-8",
            )
            _r21p7b = chk_c21_6_quality_gate_report([(Path("x.yaml"), {"title": "已填"})], _tdp7)
            fcheck(f"F-21-P1-4b2 batch flag exempt 缺 reason → {_EXP_S216}（enforce: 豁免不成立、fall-through 缺報告 FAIL；Codex R1 P0）", _r21p7b[0] == _EXP_S216, _r21p7b[1])
            # exempt 非 boolean true（字串 "true"）→ 不豁免（缺報告 WARN）
            (_tdp7 / "_batch_flags.yml").write_text(
                "quality_gate:\n  exempt: \"true\"\n  reason: \"x\"\n",
                encoding="utf-8",
            )
            _r21p7c = chk_c21_6_quality_gate_report([(Path("x.yaml"), {"title": "已填"})], _tdp7)
            fcheck(f"F-21-P1-4b3 exempt 字串 'true' 不認 → {_EXP_S216}", _r21p7c[0] == _EXP_S216, _r21p7c[1])
            # Codex R4 P1：reason 非字串（list）被 str() 成非空 → 不得誤過豁免（fail-closed）
            (_tdp7 / "_batch_flags.yml").write_text(
                "quality_gate:\n  exempt: true\n  reason:\n    - B級批\n",
                encoding="utf-8",
            )
            _r21p7d = chk_c21_6_quality_gate_report([(Path("x.yaml"), {"title": "已填"})], _tdp7)
            fcheck(f"F-21-P1-4b4 exempt reason 非字串（list）→ {_EXP_S216}（fail-closed 不誤豁免）", _r21p7d[0] == _EXP_S216, _r21p7d[1])

        # ⑧ P1-3 順手硬化②：C-21.7 成片90 掃整 yaml 序列化全文（自由欄位漏網防護）
        print("[F-21-P1-3d] C-21.7：成片90 藏自由欄位 → grep 整 yaml 全文抓到 FAIL")
        _f21p8 = {
            "title": "已填", "batch_date": _POST,
            "score_type": "script", "true_material_source": "none",
            "claim_allowed": "角度到位",
            "自由備註欄": "這支其實成片90 沒問題",  # 藏在非列舉欄位
        }
        _r21p8 = chk_c21_7_honest_ceiling(_f21p8, "f21p8.yaml", is_skeleton=False)
        fcheck("F-21-P1-3d 成片90 藏自由欄位 → FAIL", _r21p8[0] == "FAIL", _r21p8[1])

        # ══════════════════════════════════════════════════════════════
        # [F-21 R2] Codex 第 2 輪對抗驗退回的 5 修正（P1-A/B/C + P2-A 註解 + P2-B）
        # ══════════════════════════════════════════════════════════════
        print("\n[F-21 R2] Codex 第 2 輪退回 5 修正驗證")

        # ── R2-1（P1-A）：軟性 advisory cta_mix（沒寫 decision_status/approval_status，靠 parser
        #    default 充 confirmed/owner_signed）+ 13/13 同種 → C-21.2 FAIL（不誤 defer）──
        print("[F-21-R2-1] P1-A：軟塊靠 default 充 confirmed/owner_signed → 不 defer → 13/13 同種 FAIL")
        _pref_soft_default = (
            "## cta\n```kb-rule\n"
            "category: cta_mix\nenforcement: advisory\n"   # 只寫 advisory，沒寫 decision_status/approval_status
            "source_fields:\n  - [schema_check, CTA類型]\n"
            "mix:\n  - name: 個人化諮詢型\n    target_count: 13\n    aliases: [諮詢型, 個人諮詢]\n"
            "```\n"
        )
        # 確認 parser 對此軟塊確實 default 成 confirmed/owner_signed（這正是 P1-A 根因）
        _r2_1_parsed = _parse_mix_block(_pref_soft_default, "cta_mix")
        fcheck(
            "F-21-R2-1a parser 對軟塊缺值確實 default 成 confirmed/owner_signed（根因確證）",
            _r2_1_parsed.decision_status == "confirmed" and _r2_1_parsed.approval_status == "owner_signed",
            f"decision_status={_r2_1_parsed.decision_status} approval_status={_r2_1_parsed.approval_status}",
        )
        # 但 _s21_2_l2_hard_cta_mix 不該因 default 值 defer（只認原文 enforcement: hard）
        fcheck(
            "F-21-R2-1b 軟塊不被當硬性 defer（_s21_2_l2_hard_cta_mix 回 None）",
            _s21_2_l2_hard_cta_mix(_pref_soft_default) is None,
            f"_s21_2_l2_hard_cta_mix={_s21_2_l2_hard_cta_mix(_pref_soft_default)!r}",
        )
        # 端到端：13 支同 CTA + 軟塊 → C-21.2 FAIL（修前會被誤 defer 成 PASS）
        _f21r2_1 = [_mk(i, f"骨架{i}", "個人化諮詢型", _POST) for i in range(1, 14)]
        _r21r2_1 = chk_c21_2_cta_diversity(_f21r2_1, "測試業主", pref_text=_pref_soft_default, batch_tag="2026-06-25")
        fcheck("F-21-R2-1c 軟塊 13/13 同種 → C-21.2 FAIL（不誤放行）", _r21r2_1[0] == "FAIL", _r21r2_1[1])

        # ── R2-2（P1-A 正向）：明寫 enforcement: hard → 仍正確 defer PASS ──
        print("[F-21-R2-2] P1-A 正向：明寫 enforcement: hard 集中 → 仍 defer PASS")
        # 復用前面 _pref_hard（明寫 enforcement: hard）；12 支諮詢 + 1 互動（集中）
        _f21r2_2 = [_mk(i, f"骨架{i}", "個人化諮詢型", _POST) for i in range(1, 13)]
        _f21r2_2 += [_mk(13, "骨架13", "互動留言型", _POST)]
        _r21r2_2 = chk_c21_2_cta_diversity(_f21r2_2, "瑞祥", pref_text=_pref_hard, batch_tag="2026-06-25")
        fcheck("F-21-R2-2 明寫 enforcement:hard 集中 → defer PASS", _r21r2_2[0] == "PASS", _r21r2_2[1])

        # ── R2-3（P1-B）：混合批 per-file skeleton——7 支 title placeholder + 6 支已填但缺誠實欄。
        #    那 6 支已填的不該因批次全域 skeleton 被當骨架 SKIP，須走 FAIL（post-cutover）──
        print("[F-21-R2-3] P1-B：混合批 per-file skeleton——已填缺誠實欄支 → FAIL（非批次全域 SKIP）")
        # 已填腳本（真標題）+ 缺誠實三欄 → _is_placeholder(title)=False → 非骨架 → FAIL
        _f21r2_3_filled = {"title": "已填完整真標題", "batch_date": _POST}
        _r2_3_filled = chk_c21_7_honest_ceiling(
            _f21r2_3_filled, "f21r2_3_filled.yaml", _is_placeholder(_f21r2_3_filled.get("title"))
        )
        fcheck(
            "F-21-R2-3a 混合批中『title 已填+缺誠實欄』支 → FAIL（per-file 不被批次 skeleton SKIP）",
            _r2_3_filled[0] == "FAIL",
            _r2_3_filled[1],
        )
        # 同批的骨架支（title placeholder）+ 缺三欄 → per-file skeleton=True → SKIP（合法）
        _f21r2_3_skel = {"title": "[編劇填]", "batch_date": _POST}
        _r2_3_skel = chk_c21_7_honest_ceiling(
            _f21r2_3_skel, "f21r2_3_skel.yaml", _is_placeholder(_f21r2_3_skel.get("title"))
        )
        fcheck(
            "F-21-R2-3b 同批骨架支（title placeholder）缺三欄 → SKIP（per-file 正確判骨架）",
            _r2_3_skel[0] == "SKIP",
            _r2_3_skel[1],
        )

        # ── R2-4（P1-C）：None 日期 post-cutover → fail-closed enforce 側（FAIL/不 waive）──
        print("[F-21-R2-4] P1-C：無法解析日期 → fail-closed enforce 側（None → FAIL，不再降 WARN）")
        # _s21_in_warn_window(None) 應回 False（enforce 側），有 legacy marker 才回 True
        fcheck("F-21-R2-4a _s21_in_warn_window(None) → False（fail-closed）",
               _s21_in_warn_window(None) is False, str(_s21_in_warn_window(None)))
        fcheck("F-21-R2-4b _s21_in_warn_window(None, legacy=True) → True（明確 legacy 才豁免）",
               _s21_in_warn_window(None, has_legacy_marker=True) is True,
               str(_s21_in_warn_window(None, has_legacy_marker=True)))
        # 端到端：C-21.7 已填完缺三欄 + 無 batch_date（無法解析）→ FAIL（修前 None→WARN 逃過）
        _f21r2_4 = {"title": "已填完真標題"}   # 無 batch_date，檔名也無日期
        _r21r2_4 = chk_c21_7_honest_ceiling(_f21r2_4, "no_date.yaml", is_skeleton=False)
        fcheck("F-21-R2-4c 無日期已填缺三欄 → FAIL（enforce 側，不再 WARN 逃過）",
               _r21r2_4[0] == "FAIL", _r21r2_4[1])
        # 但有明確 legacy_allowed_until（未過期）→ WARN-waiver（不誤傷 legacy）
        _f21r2_4b = {"title": "已填完真標題", "legacy_allowed_until": "2026-12-31"}
        _r21r2_4b = chk_c21_7_honest_ceiling(_f21r2_4b, "legacy.yaml", is_skeleton=False)
        fcheck("F-21-R2-4d 無日期但有 legacy_allowed_until → WARN（legacy 不誤傷）",
               _r21r2_4b[0] == "WARN", _r21r2_4b[1])

        # ── R2-5（P2-B）：garbage CTA 標籤不計多樣性 + WARN 列出 ──
        print("[F-21-R2-5] P2-B：無法解析的 garbage CTA 標籤不計多樣性 + WARN")
        # foo×5 / bar×4 / baz×4 全是無法解析的標籤 → distinct(canonical)=0、unresolved=13 → 不灌水成多樣
        _f21r2_5 = [_mk(i, f"骨架{i}", "foo", _POST) for i in range(1, 6)]
        _f21r2_5 += [_mk(i, f"骨架{i}", "bar", _POST) for i in range(6, 10)]
        _f21r2_5 += [_mk(i, f"骨架{i}", "baz", _POST) for i in range(10, 14)]
        _r21r2_5 = chk_c21_2_cta_diversity(_f21r2_5, "測試業主", pref_text=None, batch_tag="2026-06-25")
        # garbage 不計 → distinct=0 < 3 → FAIL，且訊息含「無法解析」+ garbage 標籤
        _r2_5_ok = (_r21r2_5[0] == "FAIL") and ("無法解析" in _r21r2_5[1]) and ("foo" in _r21r2_5[1]) and ("只有 0 種" in _r21r2_5[1])
        fcheck("F-21-R2-5a garbage 標籤不計多樣性 → distinct=0 FAIL + WARN 列出", _r2_5_ok, _r21r2_5[1])
        # 對照：正規標籤 3 種（個人化諮詢/互動問句/分享引導）+ 1 支 garbage → 多樣達標但 WARN garbage
        _f21r2_5b = [_mk(i, f"骨架{i}", "個人化諮詢型", _POST) for i in range(1, 6)]
        _f21r2_5b += [_mk(i, f"骨架{i}", "互動留言型", _POST) for i in range(6, 10)]
        _f21r2_5b += [_mk(i, f"骨架{i}", "分享引導型", _POST) for i in range(10, 13)]
        _f21r2_5b += [_mk(13, "骨架13", "亂填標籤xyz", _POST)]
        _r21r2_5b = chk_c21_2_cta_diversity(_f21r2_5b, "測試業主", pref_text=None, batch_tag="2026-06-25")
        _r2_5b_ok = (_r21r2_5b[0] == "WARN") and ("無法解析" in _r21r2_5b[1]) and ("亂填標籤xyz" in _r21r2_5b[1])
        fcheck("F-21-R2-5b 正規 3 種達標 + 1 garbage → WARN（多樣達標但提示 garbage）", _r2_5b_ok, _r21r2_5b[1])
        # 對照：正規 3 種乾淨無 garbage → PASS（確認沒誤把乾淨批降 WARN）
        _f21r2_5c = [_mk(i, f"骨架{i}", "個人化諮詢型", _POST) for i in range(1, 6)]
        _f21r2_5c += [_mk(i, f"骨架{i}", "互動留言型", _POST) for i in range(6, 11)]
        _f21r2_5c += [_mk(i, f"骨架{i}", "分享引導型", _POST) for i in range(11, 14)]
        _r21r2_5c = chk_c21_2_cta_diversity(_f21r2_5c, "測試業主", pref_text=None, batch_tag="2026-06-25")
        fcheck("F-21-R2-5c 正規 3 種乾淨無 garbage → PASS（不誤降 WARN）", _r21r2_5c[0] == "PASS", _r21r2_5c[1])

        # ══════════════════════════════════════════════════════════════
        # [F-21 R3] Codex 第 3 輪退回 2 修正（P1 真實 CTA 標籤放寬 + P2 list title 防呆）
        # ══════════════════════════════════════════════════════════════
        print("\n[F-21 R3] Codex 第 3 輪退回 2 修正驗證")

        # ── R3-1（P1）：真實合法批 5×諮詢 + 4×互動留言 + 4×釣魚型 → PASS（distinct=3）──
        # 修前「釣魚型」不在 canonical 表 → 解析不到 → distinct 只算 2 → 誤 FAIL。
        print("[F-21-R3-1] P1：5×個人化諮詢型 + 4×互動留言型 + 4×釣魚型 → PASS（distinct=3）")
        _f21r3_1 = [_mk(i, f"骨架{i}", "個人化諮詢型", _POST) for i in range(1, 6)]   # 5
        _f21r3_1 += [_mk(i, f"骨架{i}", "互動留言型", _POST) for i in range(6, 10)]    # 4
        _f21r3_1 += [_mk(i, f"骨架{i}", "釣魚型", _POST) for i in range(10, 14)]       # 4
        _r21r3_1 = chk_c21_2_cta_diversity(_f21r3_1, "測試業主", pref_text=None, batch_tag="2026-06-25")
        _r3_1_ok = (_r21r3_1[0] == "PASS") and ("3 種" in _r21r3_1[1])
        fcheck("F-21-R3-1 真實合法批 5諮詢+4互動+4釣魚 → distinct=3 PASS", _r3_1_ok, _r21r3_1[1])

        # ── R3-2（P1）：帶括號變體標籤正規化──
        # 「釣魚型（留言「幕後」→ 私訊解答圖卡）」「純雞湯（無CTA）」「追蹤型（IG 限動）」
        #   各剝括號歸到 base → 釣魚引流 / 無強CTA / 追蹤引導 = 3 種 distinct
        print("[F-21-R3-2] P1：帶括號真實標籤剝括號正規化 → 計入 distinct")
        # 單元層先證 _s21_canonical_cta_effect 對帶括號標籤的歸類
        _paren_cases = [
            ("釣魚型（留言「幕後」→ 私訊解答圖卡）", "釣魚引流"),
            ("純雞湯（無CTA）", "無強CTA"),
            ("純雞湯（無商業CTA）", "無強CTA"),
            ("追蹤型（IG 限動）", "追蹤引導"),
            ("私域引流型（餐車限動）", "釣魚引流"),
            ("私訊引流型（首購）", "釣魚引流"),
            ("留言互動型（軟互動，非引流）", "互動問句"),
            ("無（純雞湯強制）", "無強CTA"),
            ("二選一互動型", "互動問句"),
            ("收藏型", "分享引導"),
            ("私訊型", "釣魚引流"),
        ]
        _paren_all_ok = True
        _paren_detail = []
        for _raw, _exp in _paren_cases:
            _got = _s21_canonical_cta_effect(_raw)
            _paren_detail.append(f"{_raw}→{_got}(期望{_exp})")
            if _got != _exp:
                _paren_all_ok = False
        fcheck("F-21-R3-2a 11 個真實帶括號/真實標籤剝括號歸正確 base", _paren_all_ok, " | ".join(_paren_detail))
        # 端到端：4×釣魚型（…）+ 4×純雞湯（無CTA）+ 5×個人化諮詢型 → distinct=3 PASS
        _f21r3_2 = [_mk(i, f"骨架{i}", "個人化諮詢型", _POST) for i in range(1, 6)]                 # 5
        _f21r3_2 += [_mk(i, f"骨架{i}", "釣魚型（留言「幕後」→ 私訊解答圖卡）", _POST) for i in range(6, 10)]  # 4
        _f21r3_2 += [_mk(i, f"骨架{i}", "純雞湯（無CTA）", _POST) for i in range(10, 14)]          # 4
        _r21r3_2 = chk_c21_2_cta_diversity(_f21r3_2, "測試業主", pref_text=None, batch_tag="2026-06-25")
        fcheck("F-21-R3-2b 帶括號真實標籤批 → distinct=3 PASS", _r21r3_2[0] == "PASS" and "3 種" in _r21r3_2[1], _r21r3_2[1])

        # ── R3-3（P1 不放水）：foo/bar/baz garbage 剝括號後仍 garbage → 不計 + WARN + FAIL ──
        print("[F-21-R3-3] P1 不放水：foo/bar/baz（含帶括號 garbage）剝括號後仍不在表 → 不計 + FAIL")
        _f21r3_3 = [_mk(i, f"骨架{i}", "foo（亂填）", _POST) for i in range(1, 6)]
        _f21r3_3 += [_mk(i, f"骨架{i}", "bar", _POST) for i in range(6, 10)]
        _f21r3_3 += [_mk(i, f"骨架{i}", "baz（垃圾）", _POST) for i in range(10, 14)]
        _r21r3_3 = chk_c21_2_cta_diversity(_f21r3_3, "測試業主", pref_text=None, batch_tag="2026-06-25")
        _r3_3_ok = (_r21r3_3[0] == "FAIL") and ("無法解析" in _r21r3_3[1]) and ("只有 0 種" in _r21r3_3[1])
        fcheck("F-21-R3-3 garbage（含帶括號）剝括號仍 garbage → distinct=0 FAIL + WARN", _r3_3_ok, _r21r3_3[1])

        # ── R3-4（P2）：list 型未引號 title placeholder → _is_placeholder=True → C-21.7 SKIP ──
        print("[F-21-R3-4] P2：未引號 title: [編劇填] 解析成 list → _is_placeholder=True → C-21.7 SKIP")
        # 單元層：_is_placeholder 對各種值的判定
        _ph_cases = [
            (["編劇填"], True),               # 骨架機未引號 title 被 YAML 解析成 list
            (["[編劇填]"], True),             # list 含 [編劇填]
            (["編劇填", "說明"], True),        # list 任一元素含編劇填
            ([], True),                       # 空 list
            (["真實標題"], False),            # list 但元素是真標題 → 非 placeholder
            (None, True),
            ("", True),
            ("[編劇填]", True),
            ("[編劇填]  # 說明", True),
            ("已填真標題", False),
            ("pending", True),
            ("待填", True),
        ]
        _ph_all_ok = True
        _ph_detail = []
        for _v, _exp in _ph_cases:
            _got = _is_placeholder(_v)
            _ph_detail.append(f"{_v!r}→{_got}(期望{_exp})")
            if _got != _exp:
                _ph_all_ok = False
        fcheck("F-21-R3-4a _is_placeholder 對 list/None/str 各態判定正確（含 list 防呆）", _ph_all_ok, " | ".join(_ph_detail))
        # 端到端：未引號 list title + 缺三誠實欄 → 走 skeleton SKIP（不誤 FAIL）
        _f21r3_4 = {"title": ["編劇填"], "batch_date": _POST}
        _r21r3_4 = chk_c21_7_honest_ceiling(_f21r3_4, "f21r3_4.yaml", is_skeleton=_is_placeholder(_f21r3_4.get("title")))
        fcheck("F-21-R3-4b 未引號 list title 骨架支缺三欄 → SKIP（非誤 FAIL）", _r21r3_4[0] == "SKIP", _r21r3_4[1])
        # 對照：list 型真標題（已填）+ 缺三欄 → 非骨架 → FAIL（不放水）
        _f21r3_4c = {"title": ["真實已填標題"], "batch_date": _POST}
        _r21r3_4c = chk_c21_7_honest_ceiling(_f21r3_4c, "f21r3_4c.yaml", is_skeleton=_is_placeholder(_f21r3_4c.get("title")))
        fcheck("F-21-R3-4c list 型真標題已填缺三欄 → FAIL（不誤放水）", _r21r3_4c[0] == "FAIL", _r21r3_4c[1])

        # ══════════════════════════════════════════════════════════════
        # [F-22] §22 選題公式 — C-22 一般化偵測（2026-06-17 機器化 §22；2026-06-23 已翻 enforce-live）
        # ══════════════════════════════════════════════════════════════
        print("\n[F-22] §22 選題一般化偵測：偏一般 WARN / 不一般 PASS / 骨架 SKIP / 過渡標示")

        def _mk22(seq, title, date_str=_POST, owner="瑞祥", **extra):
            """造一支 §22 測試 yaml（title 已填 + batch_date）。"""
            d = {"title": title, "batch_date": date_str}
            d.update(extra)
            return (Path(f"f22_{seq:02d}.yaml"), d)

        # ── F-22-S：單支訊號計分單元測試（純規則正確性）──
        # 2026-06-17 Codex 第 2 輪 precision 修：_s22_count_signals 回 (total, hard, hits)。
        print("[F-22-S] 單支訊號計分：hard/weak 分類 + 7 訊號逐一驗")
        # 一般題目（誰都能講）：0-1 訊號 < MIN_SIGNALS（偏一般）
        _n0, _hd0, _h0 = _s22_count_signals("買房要注意什麼", "瑞祥")
        fcheck(f"F-22-Sa 「買房要注意什麼」→ 訊號 < {_S22_MIN_SIGNALS}（偏一般）", _n0 < _S22_MIN_SIGNALS, f"n={_n0} hard={_hd0} hits={[k for k,v in _h0.items() if v]}")
        # 不一般題目（綁業主真料+數字+代價）：>= 3 訊號 且 hard >= 1
        _n1, _hd1, _h1 = _s22_count_signals("我經手 37 組首購，多賠 80 萬的不是利率，是誤判了這件事", "瑞祥")
        fcheck("F-22-Sb 「我經手37組首購多賠80萬」→ 訊號 >= 3 且 hard >= 1（不一般）", _n1 >= 3 and _hd1 >= 1, f"n={_n1} hard={_hd1} hits={[k for k,v in _h1.items() if v]}")
        # 在地對比題（誠實：純規則只抓到「數字+地名」2 訊號；「差距大到不敢信」的語義代價規則抓不到
        #   → C-22 定位「只擋低級空泛、不判好題」，語義級留 GPT/真人。此處驗「規則確實抓到數字+地名」）
        _n2, _hd2, _h2 = _s22_count_signals("800 萬在高雄 vs 台南差距大到不敢信", "瑞祥")
        fcheck("F-22-Sc 「800萬高雄vs台南」→ 命中數字+地名 hard 訊號（語義代價規則抓不到，誠實定位）",
               _h2["數字"] and _h2["地名在地"] and _hd2 >= 2, f"n={_n2} hard={_hd2} hits={[k for k,v in _h2.items() if v]}")
        # 顯式代價詞才命中「受眾真代價」訊號（規則邊界）
        _n2b, _hd2b, _h2b = _s22_count_signals("800 萬在高雄買貴了 50 萬，多賠在這個盲點", "瑞祥")
        fcheck("F-22-Sc2 顯式「買貴/多賠」→ 命中受眾真代價 hard 訊號 → 訊號 >= 3",
               _h2b["受眾真代價"] and _n2b >= 3, f"n={_n2b} hard={_hd2b} hits={[k for k,v in _h2b.items() if v]}")
        # 反直覺題
        _n3, _hd3, _h3 = _s22_count_signals("其實大家都搞錯了，痘痘反覆不是保養品問題", "昀臻")
        fcheck("F-22-Sd 反直覺題「其實大家都搞錯」→ 命中反直覺 hard 訊號", _h3["反直覺"], f"n={_n3} hard={_hd3} hits={[k for k,v in _h3.items() if v]}")
        # 業主名綁定訊號（去業主名仍成立=一般 → 反向：有綁業主=hard 訊號）
        _n4, _hd4, _h4 = _s22_count_signals("瑞祥帶看那天遇到的怪事", "瑞祥")
        fcheck("F-22-Se 含業主名「瑞祥」→ 命中綁業主(強) hard 訊號", _h4["綁業主第一人稱_強"] and _hd4 >= 1, f"n={_n4} hard={_hd4} hits={[k for k,v in _h4.items() if v]}")

        # ── F-22-Sf：第一人稱強/弱拆庫（2026-06-17 Codex 第 2 輪 precision 修）──
        # 強第一人稱（綁真經歷）→ 命中 hard key「綁業主第一人稱_強」；
        # 弱第一人稱（泛敘述殼）→ 命中 weak key「弱第一人稱」、不算 hard。
        print("[F-22-Sf] 第一人稱強/弱拆庫：強→hard、弱→weak")
        _fp_hard_samples = [
            "戶頭只剩3萬，我就這樣進了房仲",       # 我就這樣（強）
            "屋主問能不能賣，我都先問這一句",       # 我都先（強）
            "行政轉房仲，第一年我被屋主罵了",       # 我被（強）
            "我打電話，偷偷希望對方不接",           # 我打電話（強）
            "簽約那天，我最常看的是屋主的臉",       # 我最常（強）
            "陪屋主整理那天，我學到一件事",         # 我學到（強）
        ]
        _fph_ok, _fph_miss = True, []
        for _t in _fp_hard_samples:
            _hn, _hhd, _hh = _s22_count_signals(_t, "瑞祥")
            if not _hh["綁業主第一人稱_強"]:
                _fph_ok = False
                _fph_miss.append(_t)
        fcheck("F-22-Sf1 強第一人稱句型 6/6 命中 hard 訊號「綁業主第一人稱_強」",
               _fph_ok, f"漏抓={_fph_miss}" if _fph_miss else "全部命中 hard")
        _fp_weak_samples = [
            "我跟其他房仲哪裡不一樣",               # 我跟（弱）
            "你問鼓山適合哪種人住，我老實說",       # 我老實（弱）
            "屋主委託前最常問我這一個問題",         # 問我倒裝（弱）
            "美術館特區屋主最常問我的事",           # 問我倒裝（弱）
        ]
        _fpw_ok, _fpw_bad = True, []
        for _t in _fp_weak_samples:
            _hn, _hhd, _hh = _s22_count_signals(_t, "瑞祥")
            # 弱第一人稱詞應命中弱 key、不命中強 key（除非該句另含地名/業主名等其他 hard）
            if not _hh["弱第一人稱"]:
                _fpw_ok = False
                _fpw_bad.append((_t, "未命中弱 key"))
        fcheck("F-22-Sf2 弱第一人稱句型 4/4 命中 weak 訊號「弱第一人稱」（泛敘述殼）",
               _fpw_ok, f"異常={_fpw_bad}" if _fpw_bad else "全部命中 weak")

        # ── F-22-Sg：詞庫擴充未過度放寬（反向 backstop）——真空泛題仍 0-1 訊號、< MIN_SIGNALS ──
        # 防「為讓好批好看亂塞詞 → 什麼都 PASS」：純空泛題不含第一人稱/數字/地名 → 仍偏一般。
        print("[F-22-Sg] 詞庫擴充未過度放寬：真空泛題仍偏一般（< MIN_SIGNALS）")
        _junk_samples = ["買房要注意什麼", "房貸怎麼選", "保養三步驟你做對了嗎", "理財觀念", "看屋技巧分享"]
        _junk_ok = True
        _junk_bad = []
        for _t in _junk_samples:
            _jn, _jhd, _jh = _s22_count_signals(_t, "瑞祥")
            if _jn >= _S22_MIN_SIGNALS and _jhd >= _S22_MIN_HARD_SIGNALS:  # 空泛題不該達標
                _junk_ok = False
                _junk_bad.append((_t, _jn, _jhd, [k for k, v in _jh.items() if v]))
        fcheck(f"F-22-Sg 真空泛題（5 支）仍未達標（total<{_S22_MIN_SIGNALS} 或 hard<{_S22_MIN_HARD_SIGNALS}）",
               _junk_ok, f"誤達標={_junk_bad}" if _junk_bad else "全部仍偏一般（正確）")

        # ── F-22-Sh：Codex 第 2 輪 precision bait（單題）——弱詞湊數應仍偏一般 ──
        # 繞過例 1+2：弱身份+弱第一人稱湊到 total>=2 但 hard=0 → 達標規則擋住（偏一般）。
        print("[F-22-Sh] precision bait（單題）：弱詞湊數 hard=0 → 仍偏一般")
        _bait_singles = [
            "客戶問我，房貸怎麼選",          # ③客戶(weak) + ⑦問我(weak) → 雙計分本應 2、修後合併=1弱、hard=0
            "客戶問我，買房要注意什麼",      # 同上
            "我跟你說，今年買房要注意什麼",  # ⑦我跟(weak) + ④今年(weak) → total=2 但 hard=0
            "客戶問我，首購要準備什麼",      # ③客戶+首購(weak) + ⑦問我(weak) → hard=0
        ]
        _bait_ok, _bait_bad = True, []
        for _t in _bait_singles:
            _bn, _bhd, _bh = _s22_count_signals(_t, "瑞祥")
            _meets = (_bn >= _S22_MIN_SIGNALS) and (_bhd >= _S22_MIN_HARD_SIGNALS)
            if _meets:  # 弱詞 bait 不該達標
                _bait_bad.append((_t, _bn, _bhd, [k for k, v in _bh.items() if v]))
                _bait_ok = False
        fcheck("F-22-Sh 弱詞湊數 bait（4 支）hard=0 → 全部仍偏一般（precision 洞補上）",
               _bait_ok, f"漏網={_bait_bad}" if _bait_bad else "全部正確擋住（hard<1）")

        # ── F-22-Si：防雙計分（Codex 點名）——「客戶問我」身份③+弱第一人稱⑦合併算 1 弱 ──
        print("[F-22-Si] 防雙計分：「客戶問我，房貸怎麼選」total 應 = 1（弱合併）非 2")
        _dc_n, _dc_hd, _dc_h = _s22_count_signals("客戶問我，房貸怎麼選", "瑞祥")
        fcheck("F-22-Si 「客戶問我，房貸怎麼選」→ total=1（身份+弱第一人稱合併）、hard=0",
               _dc_n == 1 and _dc_hd == 0, f"total={_dc_n} hard={_dc_hd} hits={[k for k,v in _dc_h.items() if v]}")

        # ── F-22a：批內多數偏一般（post-cutover）→ WARN（shadow 不 FAIL）──
        print("[F-22a] C-22 批內多數偏一般 → WARN（shadow 不 FAIL）")
        _f22a = [_mk22(i, t) for i, t in enumerate([
            "買房要注意什麼", "保養三步驟你做對了嗎", "現在是買房好時機嗎", "痘痘肌怎麼改善",
            "租屋要看什麼", "房貸怎麼選", "首購要準備什麼", "看屋技巧分享",
            "存錢方法分享", "理財觀念", "裝潢注意事項", "驗屋要點", "家具怎麼挑",
        ], 1)]

        # ── F-22b：批內多數不一般（post-cutover）→ PASS ──
        print("[F-22b] C-22 批內多數不一般 → PASS")
        _f22b = [_mk22(i, t) for i, t in enumerate([
            "我經手 37 組首購，多賠 80 萬的不是利率",
            "800 萬在高雄 vs 台南差距大到不敢信",
            "其實升息那年我幫客人省下 30 萬",
            "今年新制上路，首購族最容易踩的坑",
            "左營這區 3 年漲了 2 成，但有個盲點沒人說",
            "我帶看過 100 間，最後悔的客人都犯這個錯",
            "存款 200 萬該買房還是租？我算給你看",
            "鳳山這間貴了 50 萬，差在這個你看不到的地方",
            "其實仲介不會主動告訴你的 3 件事",
            "去年買貴的客人，問題都出在誤判了利率",
            "高雄美術館特區，800 萬的真相",
            "我入行 8 年，看過最扯的買房後悔故事",
            "新婚夫妻第一次買房，多花了 40 萬冤枉錢",
        ], 1)]

        # ── F-22c：骨架階段（>50% title placeholder）→ SKIP ──
        print("[F-22c] C-22 骨架階段 >50% title placeholder → SKIP")
        _f22c = [(_p, {"title": "[編劇填]", "batch_date": _POST}) for _p in [Path(f"f22c_{i}.yaml") for i in range(1, 14)]]

        # ── F-22d：過渡期（batch_date < 2026-06-24）→ WARN 且 detail 帶過渡標示 ──
        print("[F-22d] C-22 過渡期 batch_date < 2026-06-24 → WARN + 過渡標示")
        _f22d = [_mk22(i, t, date_str=_PRE) for i, t in enumerate([
            "買房要注意什麼", "保養三步驟", "現在是買房好時機嗎", "痘痘怎麼改善",
            "租屋要看什麼", "房貸怎麼選", "首購準備", "看屋技巧",
            "存錢方法", "理財觀念", "裝潢注意", "驗屋要點", "家具怎麼挑",
        ], 1)]

        # ── F-22e：邊界 — 空批 → WARN（不炸）──

        # ── F-22f：邊界 — 混合批（部分 placeholder + 部分已填）不算骨架（<50% placeholder）──
        print("[F-22f] C-22 邊界：混合批 <50% placeholder → 仍統計已填支（不 SKIP）")
        # 5 支 placeholder + 8 支已填一般題目 → placeholder 占 5/13 < 50% → 不 SKIP；只統計 8 支已填
        _f22f = [(Path(f"f22f_ph{i}.yaml"), {"title": "[編劇填]", "batch_date": _POST}) for i in range(1, 6)]
        _f22f += [_mk22(i, t) for i, t in enumerate([
            "買房要注意什麼", "租屋要看什麼", "房貸怎麼選", "首購準備",
            "看屋技巧", "存錢方法", "理財觀念", "裝潢注意",
        ], 1)]

        # ── F-22g：邊界 — list 型未引號 title placeholder → 視 placeholder（不誤統計）──
        print("[F-22g] C-22 邊界：list 型 title ['編劇填'] → 視 placeholder")
        _f22g = [(Path(f"f22g_{i}.yaml"), {"title": ["編劇填"], "batch_date": _POST}) for i in range(1, 14)]

        # ── F-22h：正交性 — C-22 看題目、C-017 看主體段，兩者不重複計（同一支不同維度）──
        print("[F-22h] C-22 與 C-017 正交：C-22 看 title、C-017 看 scenes 主體段")
        # 構一支：title 一般（C-22 視角偏一般）但主體段具體（C-017 視角夠具體）
        _f22h_data = {
            "title": "保養要注意什麼",   # 題目一般
            "batch_date": _POST,
            "主推派系": "拆解派",
            "scenes": [
                {"timestamp": "12-25s", "台詞_昀臻": "我做美容 8 年，這 3 個步驟 90% 的人第 2 步就錯了"},
                {"timestamp": "25-40s", "台詞_昀臻": "去年有個客人花了 5 萬買產品，問題根本不在臉上"},
            ],
            "schema_check": {"CTA類型": "個人化諮詢型"},
        }
        # C-22 單支訊號：title「保養要注意什麼」應 < MIN_SIGNALS（偏一般）
        _h_n, _h_hd, _h_hits = _s22_count_signals(_s22_topic_text(_f22h_data), "昀臻")
        # C-017 主體段：含「8 年/3 個/90%/第 2/5 萬」具體信號 >= 2 → PASS
        _c017_r = chk_c017_concreteness(_f22h_data, "f22h.yaml")
        fcheck(
            f"F-22h C-22 視角 title 偏一般（訊號<{_S22_MIN_SIGNALS}）但 C-017 視角主體段具體（PASS）→ 兩維度正交不重複",
            _h_n < _S22_MIN_SIGNALS and _c017_r[0] == "PASS",
            f"C-22單支訊號={_h_n}({[k for k,v in _h_hits.items() if v]}) | C-017={_c017_r[0]}:{_c017_r[1]}",
        )

        # ── F-22i：占比剛好 == 門檻（0.9）→ WARN（>= 門檻觸發）──
        # 2026-06-17 P2-a 重構：門檻 0.5→0.9 後，原「6/12=0.5 == 門檻」case 失效（0.5 < 0.9 → PASS）。
        # 改驗新邊界：9 偏一般 + 1 不一般 = 10 支 → 偏一般占 9/10 = 0.9 == 門檻 → WARN（>= 觸發）。
        print(f"[F-22i] C-22 邊界：占比剛好 == 門檻（{_S22_BATCH_WARN_RATIO:.0%}）→ WARN（>= 門檻）")
        _f22i = [_mk22(i, t) for i, t in enumerate([
            "買房要注意什麼", "租屋要看什麼", "房貸怎麼選", "首購準備", "看屋技巧",
            "存錢方法", "理財觀念", "裝潢注意", "驗屋要點",
        ], 1)]  # 9 支純空泛（訊號 0-1，MIN=2 下偏一般）
        _f22i += [_mk22(100, "我經手 37 組首購，多賠 80 萬都因為這個")]  # 1 支不一般（數字+代價+第一人稱 >= 2）

        # ── F-22i2：占比剛好低於門檻（0.8 < 0.9）→ PASS（門檻下緣）──
        # 8 偏一般 + 2 不一般 = 10 支 → 偏一般占 8/10 = 0.8 < 0.9 → PASS。
        print(f"[F-22i2] C-22 邊界：占比低於門檻（80% < {_S22_BATCH_WARN_RATIO:.0%}）→ PASS")
        _f22i2 = [_mk22(i, t) for i, t in enumerate([
            "買房要注意什麼", "租屋要看什麼", "房貸怎麼選", "首購準備",
            "看屋技巧", "存錢方法", "理財觀念", "裝潢注意",
        ], 1)]  # 8 支純空泛
        _f22i2 += [_mk22(100 + i, t) for i, t in enumerate([
            "我經手 37 組首購，多賠 80 萬都因為這個", "其實升息那年我幫客人省下 30 萬，在左營",
        ], 1)]  # 2 支不一般

        # ── F-22j：少數偏一般（占比 < 門檻）→ PASS（單支偶發不擾民）──
        print("[F-22j] C-22 少數偏一般（占比 < 門檻）→ PASS")
        # 4 一般（訊號 0）+ 9 不一般（每句實算訊號 >= 2，見上方 helper 驗算）= 13 支
        # → 偏一般占 4/13 = 0.31 < 門檻 0.9 → PASS
        _f22j = [_mk22(i, t) for i, t in enumerate([
            "買房要注意什麼", "租屋要看什麼", "房貸怎麼選", "看屋技巧",
        ], 1)]
        _f22j += [_mk22(100 + i, t) for i, t in enumerate([
            "我經手 37 組首購，多賠 80 萬都因為這個",       # 4
            "其實升息那年我幫客人省下 30 萬",               # 5
            "左營 3 年漲 2 成，但有個盲點沒人說",            # 3
            "我帶看 100 間，最後悔的客人都犯這錯",           # 4
            "我入行 8 年，看過最扯的後悔故事",               # 4
            "今年首購多花 40 萬，其實是誤判了利率",          # 5
            "存款 200 萬的客人後悔了，我算給你看差 50 萬",   # 3
            "鳳山這間買貴 60 萬，其實差在這個盲點",          # 4
            "高雄美術館特區 800 萬，多賠的客人都踩這雷",      # 4
        ], 1)]

        # ══════════════════════════════════════════════════════════════
        # [F-22-bait] Codex 第 2 輪 precision 退回修 — 批次級 bait（弱詞殼繞過）
        # 上輪救 recall 後 precision 變沒牙，Codex 親推抓到弱詞湊數可整批繞過。修後應 WARN。
        # ══════════════════════════════════════════════════════════════
        print("\n[F-22-bait] Codex 第 2 輪 precision 退回修：批次級弱詞殼 bait → WARN")

        # ── bait-1：11 支裸空泛 + 2 支弱訊號 bait → WARN（Codex 指定）──
        # 修前：2 支弱 bait 各靠「客戶+問我」湊 2 訊號 → 達標 → 11/13=84.6% < 90% → 誤 PASS。
        # 修後：弱 bait hard=0 → 不達標 → 偏一般 13/13=100% >= 90% → WARN。
        print("[F-22-bait1] 11 裸空泛 + 2 弱訊號 bait → WARN（弱 bait 不再湊數達標）")
        _bait1 = [_mk22(i, t) for i, t in enumerate([
            "買房要注意什麼", "租屋要看什麼", "房貸怎麼選", "首購準備", "看屋技巧",
            "存錢方法", "理財觀念", "裝潢注意", "驗屋要點", "家具怎麼挑", "貸款流程",
        ], 1)]  # 11 裸空泛
        _bait1 += [
            _mk22(100, "我跟你說，今年買房要注意什麼"),   # 弱 bait：我跟(weak)+今年(weak) hard=0
            _mk22(101, "客戶問我，首購要準備什麼"),       # 弱 bait：客戶(weak)+問我(weak) hard=0
        ]

        # ── bait-2：13 支「客戶問我 + 泛 FAQ」→ WARN（Codex 指定）──
        # 整批套「客戶+問我」弱詞殼，表面 distinct（題目各異）但全 hard=0 → 100% 偏一般 → WARN。
        print("[F-22-bait2] 13 支「客戶問我 + 泛 FAQ」殼 → WARN（整批 hard=0）")
        _bait2 = [_mk22(i, t) for i, t in enumerate([
            "客戶問我，房貸怎麼選", "客戶問我，買房要注意什麼", "客戶問我，首購要準備什麼",
            "客戶問我，租屋要看什麼", "客戶問我，看屋有什麼技巧", "客戶問我，驗屋要看什麼",
            "客戶問我，裝潢要注意什麼", "客戶問我，貸款流程怎麼跑", "客戶問我，存錢有什麼方法",
            "客戶問我，理財觀念要怎麼建立", "客戶問我，家具要怎麼挑", "客戶問我，怎麼跟銀行談",
            "客戶問我，什麼時候進場好",
        ], 1)]

        # ── bait-3（backstop 專測）：弱過關第二層 — 全批達標但靠弱訊號為主 → WARN ──
        # 構：每支都有 1 hard（地名）但 weak（身份+時效）更多 → total>=2、hard>=1 達標但 weak>hard。
        #   單支不偏一般，但「弱過關」占比 >= 90% → 第二層 backstop 觸發 WARN。
        print("[F-22-bait3] backstop 第二層：全批達標但 weak>hard（弱過關）→ WARN")
        _bait3 = [_mk22(i, t) for i, t in enumerate([
            "高雄的客戶今年都在問這個", "左營的客戶最近都來問", "鳳山客戶這個月問最多",
            "三民客戶上週都在問", "苓雅的客戶今年最常問", "前鎮客戶最近問爆",
            "楠梓客戶這週都來問", "鼓山的客戶今年問不停", "岡山客戶上個月問最多",
            "橋頭的客戶最近都在問", "仁武客戶今年都來問", "鳥松客戶這個月問爆",
            "大社的客戶上週問最多",
        ], 1)]  # 每支：地名(hard 1) + 客戶(weak) + 時效(weak) = total 3 / hard 1 → weak>hard 弱過關

        # ── golden-rx38：瑞祥38 風格好批（強第一人稱+數字+代價）→ PASS（recall 沒退）──
        # 模擬瑞祥38 好題型樣本，驗 precision 修後好批仍 PASS（不為 bait 把好批弄回 WARN）。
        print("[F-22-golden-rx38] 瑞祥38 風格好批（強第一人稱故事題）→ PASS")
        _gold_rx = [_mk22(i, t) for i, t in enumerate([
            "我經手 37 組首購，多賠 80 萬的不是利率",          # 強FP+數字+代價 hard3
            "我打電話那天，偷偷希望屋主不接",                  # 強FP(我打電話)
            "我入行 8 年，看過最扯的買房後悔故事",            # 強FP+數字+代價(後悔)
            "其實升息那年我幫客人省下 30 萬",                  # 反直覺+數字+代價(省)
            "左營 3 年漲 2 成，但有個盲點沒人說",              # 地名+數字+反直覺
            "我帶看 100 間，最後悔的客人都犯這個錯",          # 強FP+數字+代價(後悔)
            "今年首購多花 40 萬，其實是誤判了利率",            # 時效+數字+代價+反直覺
            "鳳山這間買貴 60 萬，差在這個你看不到的地方",      # 地名+數字+代價
            "我被屋主罵過一次，從此改掉這個習慣",              # 強FP(我被)
            "存款 200 萬該買房還是租？我算給你看差 50 萬",      # 數字(hard)+身份(weak)
            "高雄美術館特區 800 萬的真相，多賠的都踩這雷",      # 地名+數字+代價+反直覺
            "我犯過的最大錯，害客人多繳 20 萬",                # 強FP(我犯)+數字+代價
            "新婚夫妻第一次買房，多花 40 萬冤枉錢",            # 身份(weak)+數字(hard)+代價(hard)
        ], 1)]
        # 逐句分數一併印出供檢核（誠實攤每句 total/hard）。
        _gold_detail = []
        for _f, _d in _gold_rx:
            _t = _s22_topic_text(_d)
            _gt, _gh, _ghh = _s22_count_signals(_t, "瑞祥")
            _gold_detail.append(f"{_d['title'][:14]}…(t{_gt}/h{_gh})")

        # ── golden-kn01：楷甯01 口語故事好批（強第一人稱撐 hard）→ PASS ──
        # 楷甯01 是口語第一人稱故事題（規則 recall 有上限），靠強第一人稱 hard 撐。
        print("[F-22-golden-kn01] 楷甯01 口語故事好批 → PASS（強第一人稱撐 hard）")
        _gold_kn = [_mk22(i, t, owner="楷甯") for i, t in enumerate([
            "我經手過的客戶裡，最後悔的那一個",            # 強FP+代價(後悔)
            "我入行第一年，被客戶教了一課",                # 強FP(我入行)+身份(weak)
            "我都先問客戶這一句，再決定接不接",            # 強FP(我都先)+身份(weak)
            "我打電話給屋主，心裡其實很掙扎",              # 強FP(我打電話)+反直覺(其實)
            "我帶看那次差點出事，3 個細節沒注意",          # 強FP(我帶看)+數字
            "我被客戶罵到不敢接電話那段日子",              # 強FP(我被)+身份(weak)
            "我學到的第一課，其實是別急著成交",            # 強FP(我學到)+反直覺(其實)
            "我陪客戶看了 30 間，他才說出真話",            # 強FP(我陪)+數字
            "我犯過一個錯，害客戶多等了 3 個月",            # 強FP(我犯)+數字+代價(多)
            "我接到那通電話，3 秒內就愣住",                # 強FP(我接到)+數字
            "我跑了 5 趟銀行，才搞懂這件事",               # 強FP(我跑)+數字
            "我帶看 100 間後，才發現的盲點",               # 強FP(我帶看)+數字+反直覺?
            "我經手過上百組客戶，最常卡在這一步",          # 強FP(我經手)+數字
        ], 1)]
        _kn_detail = []
        for _f, _d in _gold_kn:
            _t = _s22_topic_text(_d)
            _kt, _kh, _khh = _s22_count_signals(_t, "楷甯")
            _kn_detail.append(f"{_d['title'][:12]}…(t{_kt}/h{_kh})")

        # ── 純空泛批 backstop 確認（沒牙反向驗）：買房要注意什麼… → WARN ──
        print("[F-22-junkbatch] 純空泛批（無 hard）→ WARN（沒牙 backstop 確認）")
        _junkbatch = [_mk22(i, t) for i, t in enumerate([
            "買房要注意什麼", "房貸怎麼選", "租屋要看什麼", "看屋技巧分享", "存錢方法",
            "理財觀念", "裝潢注意事項", "驗屋要點", "家具怎麼挑", "貸款流程介紹",
            "保養三步驟", "防曬怎麼挑", "卸妝要注意什麼",
        ], 1)]

        # ── F-C22B：C-22b anchor_first 機械閘（批次 2 / Cluster A v1.1；2026-06-23 已翻 enforce-live）──
        # 注意：與既有 F-22a/F-22b（C-22 批次級一般化）不同 check，獨立命名 F-C22B 避免混淆。
        print("[F-C22B] anchor_first 三必填 + 退役拼接本 BLOCK + 防套路（C-22b 機械閘）")
        _af_ok = {"proof_mode": "anchor_first",
                  "anchor_ref": "楷甯偏好.md §9.5 voice_lock #1",
                  "anchor_cost": "第一次被屋主罵當場愣住，打電話給澤君問是否要道歉",
                  "because_bridge": "因為被罵還撐下來，所以遇到要不要趁低點買我先看心理準備不是利率"}
        _rb = chk_c22b_anchor_first({**_af_ok, "anchor_ref": ""}, "f.yaml", [], "楷甯")
        fcheck(f"F-C22B-1 anchor_ref 缺 → {_EXP_ANCHOR}", _rb[0] == _EXP_ANCHOR and "anchor_ref 缺填" in _rb[1], _rb[1])
        _rb = chk_c22b_anchor_first({**_af_ok, "anchor_ref": "_楷甯完整公版.generated.md"}, "f.yaml", [], "楷甯")
        fcheck(f"F-C22B-2 退役拼接本 .generated.md → {_EXP_ANCHOR}（上一輪真 bug 迴歸鎖）", _rb[0] == _EXP_ANCHOR and "退役拼接本" in _rb[1], _rb[1])
        _rb = chk_c22b_anchor_first({**_af_ok, "anchor_ref": "_楷甯完整公版.GENERATED.MD"}, "f.yaml", [], "楷甯")
        fcheck(f"F-C22B-3 .GENERATED.MD 大小寫變體 → {_EXP_ANCHOR}", _rb[0] == _EXP_ANCHOR and "退役拼接本" in _rb[1], _rb[1])
        _rb = chk_c22b_anchor_first(dict(_af_ok), "f.yaml", [], "楷甯")
        fcheck("F-C22B-4 三必填齊 → PASS", _rb[0] == "PASS", _rb[1])
        _rb = chk_c22b_anchor_first({"proof_mode": "proof_first"}, "f.yaml", [], "楷甯")
        fcheck("F-C22B-5 proof_first → 跳過 PASS（非 anchor_first 零干擾）", _rb[0] == "PASS" and "跳過" in _rb[1], _rb[1])
        _rb = chk_c22b_anchor_first({**_af_ok, "anchor_cost": "很努力"}, "f.yaml", [], "楷甯")
        fcheck(f"F-C22B-6 空泛 anchor_cost → {_EXP_ANCHOR}", _rb[0] == _EXP_ANCHOR and "空泛詞" in _rb[1], _rb[1])
        _af_batch = [(Path(f"s{_i}.yaml"), dict(_af_ok)) for _i in range(3)]
        _rb = chk_c22b_anchor_first(dict(_af_ok), "s0.yaml", _af_batch, "楷甯")
        fcheck(f"F-C22B-7 同 anchor_ref 同批 >2 → {_EXP_ANCHOR}（防套路）", _rb[0] == _EXP_ANCHOR and "同批 anchor_ref 重複" in _rb[1], _rb[1])

        # ── F-OFFPRO：目標5 voice_first 偵測收斂 + chk_offpro_leak off-pro-aware（2026-06-23 已翻 enforce-live）──
        # 目標5（2026-06-22）：_is_offpro_marker 單一真理源（lane=stance OR proof_mode=voice_first）+ 向後相容 + byte 不變。
        print("[F-OFFPRO] 目標5 voice_first 偵測：_is_offpro_marker + chk_offpro_leak off-pro-aware")
        fcheck("F-OFFPRO-1 lane=stance → off-pro（向後相容舊標記）",
               _is_offpro_marker({"lane": "stance"}) is True, "lane=stance")
        fcheck("F-OFFPRO-2 proof_mode=voice_first → off-pro（目標5 正式第 4 型）",
               _is_offpro_marker({"proof_mode": "voice_first"}) is True, "proof_mode=voice_first")
        fcheck("F-OFFPRO-3 both（lane=stance + voice_first）→ off-pro",
               _is_offpro_marker({"lane": "stance", "proof_mode": "voice_first"}) is True, "both")
        fcheck("F-OFFPRO-4 本業稿無標記 → 非 off-pro（byte 不變保證）",
               _is_offpro_marker({"proof_mode": "proof_first"}) is False
               and _is_offpro_marker({}) is False, "本業/空")
        fcheck("F-OFFPRO-5 大小寫/空白 normalize（' Stance '/'VOICE_FIRST'→off-pro）",
               _is_offpro_marker({"lane": " Stance "}) is True
               and _is_offpro_marker({"proof_mode": "VOICE_FIRST"}) is True, "normalize")

        # ── Codex R1 修正驗證（2026-06-23）：§8#8 擴欄+去混淆 / placeholder off-pro-aware ──
        print("[F-R1FIX] Codex R1 修正：§8#8 擴欄+去混淆 / placeholder off-pro-aware")
        _ph_off = "FAIL" if _OFFPRO_PLACEHOLDER_ENFORCE else "WARN"
        # ── Codex R2 收嚴驗證 ──
        _cyc = {"x": "ok"}; _cyc["self"] = _cyc
        try:
            _ok_cyc = True
        except RecursionError:
            _ok_cyc = False
        fcheck("F-R2-3 §8#8 dm_card 自參照（cycle）→ 不 RecursionError（cycle guard）",
               _ok_cyc, "cycle guard")
        # ── Codex R4 紅隊修驗證 ──
        # ── 算盤覆核補：藏鏡人（中文鍵，生產 130/172 用）+ top-level cta 洩漏偵測 ──
        print("[F-HYBRID] off-pro hybrid deterministic gates")

        def _hybrid_base(axis: str = "offpro") -> dict:
            d = {
                "script_id": "fx_01_01",
                "content_axis": axis,
                "lane": "voice_first" if axis == "offpro" else ("anchor_first" if axis == "personal_anchor" else "professional"),
                "derived_flags": [],
                "topic_category": "人生",
                "cta_offer_scope": "save_share",
                "scenes": [
                    {"timestamp": "0-3s", "台詞": "今天先講一個問題：焦慮不是因為你不努力。"},
                    {"timestamp": "3-12s", "台詞": "我昨天看到三個人都卡在同一個選擇。"},
                    {"timestamp": "12-25s", "台詞": "以前我也以為先撐過去就好。"},
                    {"timestamp": "25-40s", "台詞": "但真正的原因是選項太大。"},
                    {"timestamp": "40-52s", "台詞": "答案是先把選擇變小，因為你才看得到代價。"},
                    {"timestamp": "52-60s", "台詞": "你可以先存下來，今晚自己檢查一次。"},
                ],
                "script_method": {"chxp_v1": {
                    "four_materials": {
                        "problem_scene": "選項太大",
                        "old_answer": {
                            "quote": "先撐過去就好",
                            "believer_profile": "怕麻煩的人",
                            "why_reasonable": "因為短期看起來省力",
                            "weakness": "沒有降低選擇成本",
                        },
                        "new_answer": {"quote": "先把選擇變小"},
                        "answer_expansion": "把選項縮到兩個再比",
                    },
                    "assembly": {"story_vehicle": "捷運站觀察"},
                    "optimization": {
                        "concrete_signals": [
                            {"quote": "我昨天看到三個人都卡在同一個選擇", "type": "number"}
                        ],
                        "hook_debts": [
                            {"opened_at": "0-3s", "opened_quote": "焦慮不是因為你不努力", "closed_at": "40-52s", "closed_quote": "先把選擇變小"}
                        ],
                        "barriers_removed": ["因為選項太大，所以人會停住"],
                    },
                    "packaging": {
                        "hook_promise": "焦慮不是因為你不努力",
                        "final_payoff": "先把選擇變小",
                        "cta_type": "save_share",
                    },
                }},
                "friend_close": {"evidence": {
                    "value_delivered_quote": "先把選擇變小",
                    "core_answer_quote": "先把選擇變小",
                    "cta_quote": "先存下來",
                    "cta_action_count": 1,
                    "cta_offer_scope": "save_share",
                    "viewer_value_delivered": True,
                    "one_action_only": True,
                    "no_withheld_core_answer": True,
                    "pressure_free": True,
                }},
            }
            if axis == "professional":
                d["lane"] = "professional"
                d["topic_category"] = "professional"
                d["cta_offer_scope"] = "soft_consultation"
                d["professional_topic_type"] = "pricing"
                d["actionable_steps"] = ["先列三個可比價格"]
                d["core_answer"] = "先列三個可比價格"
                d["scenes"][4]["台詞"] = "核心答案是先列三個可比價格，因為你才知道差距。"
                d["scenes"][5]["台詞"] = "需要我看你的情況，再私訊我。"
                d["script_method"]["chxp_v1"]["optimization"]["concrete_signals"] = [
                    {"quote": "三個可比價格", "type": "number"},
                    {"quote": "現場看到價格差距", "type": "place"},
                    {"quote": "今天先列表", "type": "time"},
                ]
                d["script_method"]["chxp_v1"]["packaging"]["final_payoff"] = "先列三個可比價格"
                d["friend_close"]["evidence"] = {
                    "value_delivered_quote": "先列三個可比價格",
                    "core_answer_quote": "先列三個可比價格",
                    "cta_quote": "私訊我",
                    "cta_action_count": 1,
                    "cta_offer_scope": "soft_consultation",
                }
            return d

        def _hybrid_plan(axis_counts=(9, 2, 2), prof_extra=False, news_count=0) -> list[dict]:
            axes = ["offpro"] * axis_counts[0] + ["personal_anchor"] * axis_counts[1] + ["professional"] * axis_counts[2]
            lanes = ["voice_first"] * 7 + ["demand_first"] * 2 + ["anchor_first"] * 2 + ["professional"] * 2
            cats = ["人生", "金錢", "感情", "熱門", "人生", "金錢", "感情", "人生", "金錢"]
            if news_count:
                cats = ["時事"] * news_count + cats[news_count:]
            plan = []
            for i, axis in enumerate(axes):
                flags = []
                if i == 0:
                    flags = ["identity_bridge"]
                if i == 1:
                    flags = ["pure_emotion"]
                if i == 2:
                    flags = ["wildcard"]
                cat = cats[i] if axis == "offpro" and i < len(cats) else ("personal_story" if axis == "personal_anchor" else "professional")
                plan.append({"seq": i + 1, "script_id": f"fx_01_{i+1:02d}", "content_axis": axis, "lane": lanes[i] if i < len(lanes) else "professional", "derived_flags": flags, "topic_category": cat})
            if prof_extra and len(plan) >= 3:
                plan[2]["content_axis"] = "professional"
            return plan


        _old_plan = _hybrid_plan()
        _new_plan = [dict(x) for x in _old_plan]
        _new_plan[0]["lane"] = "demand_first"
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as _td:
            _bdir = Path(_td)
            (_bdir / "_batch_flags.yml").write_text(f"batch_profile: {HYBRID_BATCH_PROFILE}\n", encoding="utf-8")
            _bare = [(Path("bare.yaml"), {"script_id": "bare_01", "scenes": [{"timestamp": "0-3s", "台詞": "bare"}]})]
            _rt = chk_taste_panel_completeness(_bare, _bdir)
            fcheck(f"F-HYBRID-5e2 declared hybrid bare YAML C-taste → {_EXP_TASTE}",
                   _rt[0] == _EXP_TASTE and "declared-but-not-built" in _rt[1], _rt[1])
        with _tempfile.TemporaryDirectory() as _td:
            _bdir = Path(_td)
            (_bdir / "_batch_flags.yml").write_text("batch_profile: [hybrid_70_15_15\n", encoding="utf-8")
            _bare = [(Path("bare.yaml"), {"script_id": "bare_01", "scenes": [{"timestamp": "0-3s", "台詞": "bare"}]})]
            _rt = chk_taste_panel_completeness(_bare, _bdir)
            fcheck("F-HYBRID-5e4 broken _batch_flags fail-closed → C-taste-panel FAIL",
                   _rt[0] == "FAIL" and "_batch_flags.yml 讀取/解析失敗" in _rt[1] and "fail-closed" in _rt[1], _rt[1])
        with _tempfile.TemporaryDirectory() as _td:
            _bdir = Path(_td)
            (_bdir / "topic_plan.json").write_text("[]", encoding="utf-8")
            _rt = chk_taste_panel_completeness([], _bdir)
            fcheck(f"F-HYBRID-5g malformed topic_plan C-taste clean FAIL → {_EXP_TASTE}",
                   _rt[0] == _EXP_TASTE and "topic_plan 結構異常" in _rt[1], _rt[1])

        _d = _hybrid_base("offpro")
        _leak = _hybrid_base("offpro"); _leak["caption"] = "這支賣房成交很快"
        _bad = _hybrid_base("professional"); _bad["professional_topic_type"] = "chicken_soup"
        _bad = _hybrid_base("professional"); _bad["friend_close"]["evidence"]["core_answer_quote"] = ""; _bad["friend_close"]["evidence"]["cta_quote"] = "私訊我拿答案"
        _bad["scenes"][5]["台詞"] = "私訊我拿答案"
        _bad = _hybrid_base("offpro"); _bad["script_method"]["chxp_v1"]["four_materials"]["old_answer"]["quote"] = ""
        _bad = _hybrid_base("offpro"); _bad["script_method"]["chxp_v1"]["four_materials"]["old_answer"]["quote"] = "大家都說撐過去就好"
        _bad = _hybrid_base("offpro"); _bad["script_method"]["chxp_v1"]["optimization"]["hook_debts"][0]["closed_at"] = "0-3s"
        _bad = _hybrid_base("offpro")
        _bad["script_method"]["chxp_v1"]["optimization"]["hook_debts"][0]["opened_quote"] = "台詞裡沒有的開坑"
        _bad["script_method"]["chxp_v1"]["optimization"]["hook_debts"][0]["closed_quote"] = "台詞裡沒有的收束"
        _bad = _hybrid_base("offpro")
        _bad["script_method"]["chxp_v1"]["optimization"]["hook_debts"][0]["opened_quote"] = _scene_texts(_bad)[1][1]
        _bad = _hybrid_base("offpro"); _bad["script_method"]["chxp_v1"]["optimization"]["barriers_removed"] = ["拿掉一個選項"]
        _bad = _hybrid_base("offpro"); _bad["friend_close"]["evidence"]["core_answer_quote"] = ""; _bad["friend_close"]["evidence"]["cta_quote"] = "私訊我拿答案"; _bad["scenes"][5]["台詞"] = "私訊我拿答案"
        _bad = _hybrid_base("offpro")
        _bad["scenes"][4]["台詞"] = "你可以先存下來。"
        _bad["scenes"][5]["台詞"] = "答案是先把選擇變小。"
        _bad["friend_close"]["evidence"]["core_answer_quote"] = "先把選擇變小"
        _bad["friend_close"]["evidence"]["cta_quote"] = "先存下來"
        _bad = _hybrid_base("offpro")
        _bad["friend_close"]["evidence"]["cta_quote"] = "截圖下來，傳給朋友，明天照做一次"
        _bad["friend_close"]["evidence"]["cta_action_count"] = 1
        _bad["scenes"][5]["台詞"] = "截圖下來，傳給朋友，明天照做一次。"
        _bad = _hybrid_base("offpro")
        _bad["friend_close"]["evidence"]["cta_quote"] = "收藏，轉寄給朋友"
        _bad["friend_close"]["evidence"]["cta_action_count"] = 1
        _bad["scenes"][5]["台詞"] = "收藏，轉寄給朋友"
        _bad = _hybrid_base("offpro")
        _bad["friend_close"]["evidence"]["cta_quote"] = "私訊我"
        _bad["friend_close"]["evidence"]["cta_action_count"] = 1
        _bad["scenes"][5]["台詞"] = "核心答案是先把選擇變小。私訊我。"
        for _term in ("Book a consultation", "D.M me", "call me", "加微信"):
            _bad = _hybrid_base("offpro")
            _bad["friend_close"]["evidence"]["cta_quote"] = _term
            _bad["friend_close"]["evidence"]["cta_action_count"] = 1
            _bad["scenes"][5]["台詞"] = f"核心講完了，{_term}"
        _bad = _hybrid_base("offpro")
        _bad["script_method"]["chxp_v1"]["four_materials"]["old_answer"]["quote"] = "台詞沒有講的漂亮話"
        for _term in ("密我", "小盒子"):
            _bad = _hybrid_base("offpro")
            _bad["friend_close"]["evidence"]["cta_quote"] = f"{_term}拿清單"
            _bad["friend_close"]["evidence"]["cta_action_count"] = 1
            _bad["scenes"][5]["台詞"] = f"這個答案可以先存下來，{_term}拿清單"
        _bad = _hybrid_base("offpro")
        _bad["script_method"]["chxp_v1"]["four_materials"]["old_answer"]["quote"] = "台詞裡沒有這句話"
        _bad = _hybrid_base("offpro")
        _bad["derived_flags"] = ["identity_bridge"]
        _bad["scenes"][2]["台詞"] = "我以前用房仲專業去證明自己，才發現那不是朋友會說的話。"
        _bad = _hybrid_base("offpro")
        _bad["derived_flags"] = ["identity_bridge"]
        _bad["lane"] = "demand_first"
        import tempfile as _tempfile
        _old_identity_cache = _IDENTITY_BRIDGE_RULES_CACHE
        _old_identity_path_fn = _identity_bridge_config_path
        try:
            with _tempfile.TemporaryDirectory() as _td:
                _broken_path = Path(_td) / "offpro_identity_bridge_rules.yaml"
                _broken_path.write_text("identity_bridge: [broken\n", encoding="utf-8")
                globals()["_IDENTITY_BRIDGE_RULES_CACHE"] = None
                globals()["_identity_bridge_config_path"] = lambda: _broken_path
                _bad = _hybrid_base("offpro")
                _bad["derived_flags"] = ["identity_bridge"]
        finally:
            globals()["_IDENTITY_BRIDGE_RULES_CACHE"] = _old_identity_cache
            globals()["_identity_bridge_config_path"] = _old_identity_path_fn

        import copy as _copy
        _skel = _copy.deepcopy(_hybrid_base("offpro"))
        _skel["title"] = "[編劇填]"
        _skel["derived_flags"] = ["identity_bridge"]
        for _scene in _skel["scenes"]:
            _scene["台詞"] = "[編劇填]"
        _skel["script_method"] = {"chxp_v1": {}}
        _skel["friend_close"] = {"evidence": {}}

        _filled_bad = _copy.deepcopy(_hybrid_base("offpro"))
        _filled_bad["title"] = "[編劇填]"
        _filled_bad["script_method"] = {"chxp_v1": {}}
        _batch_yamls = []
        for _i in range(13):
            _d = _copy.deepcopy(_hybrid_base("offpro"))
            _d["title"] = "[編劇填]" if _i < 7 else f"real title {_i}"
            _batch_yamls.append((Path(f"hybrid_{_i:02d}.yaml"), _d))
        _batch_yamls[0] = (Path("hybrid_filled_bad.yaml"), _filled_bad)
        _batch_skeleton = _is_skeleton_mode(_batch_yamls)

        print("[F-TASTE] C-taste-panel completeness gate")
        def _make_taste_batch(fixture: dict | None = None, exempt: bool = False):
            import tempfile as _tempfile
            import subprocess as _subprocess
            tdir = Path(_tempfile.mkdtemp())
            axes = ["offpro"] * 9 + ["personal_anchor"] * 2 + ["professional"] * 2
            lanes = ["voice_first"] * 7 + ["demand_first"] * 2 + ["anchor_first"] * 2 + ["professional"] * 2
            for i, axis in enumerate(axes, start=1):
                sid = f"tp_01_{i:02d}"
                data = {
                    "script_id": sid,
                    "owner": "fixture",
                    "batch": "01",
                    "content_axis": axis,
                    "lane": lanes[i - 1],
                    "topic_category": "人生" if axis == "offpro" else axis,
                    "scenes": [
                        {"timestamp": "0-3s", "台詞": "先給你答案"},
                        {"timestamp": "52-60s", "台詞": "存起來"},
                    ],
                    "caption": "fixture caption",
                }
                (tdir / f"script_{sid}.yaml").write_text("---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n", encoding="utf-8")
            if fixture is not None:
                (tdir / "_taste_panel_no_llm_fixture.json").write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
            if exempt:
                (tdir / "_batch_flags.yml").write_text("quality_gate:\n  exempt: true\n  reason: fixture\n", encoding="utf-8")
            cp = _subprocess.run([sys.executable, "taste_panel_gate.py", "--batch", str(tdir), "--no-llm"], cwd=Path(__file__).resolve().parent, text=True, capture_output=True, encoding="utf-8", errors="replace")
            ydata = load_yamls(tdir)
            valid = [(p, d) for p, d in ydata if isinstance(d, dict) and "__parse_error__" not in d]
            return tdir, cp, valid

        def _rewrite_taste_reports_as_real(panel_dir: Path):
            import taste_panel_gate as _tpg
            summary_path = panel_dir / "_taste_panel_summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["no_llm_mode"] = False
            summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
            for rp in sorted(panel_dir.glob("*_taste_panel_report.json")):
                rep = json.loads(rp.read_text(encoding="utf-8"))
                rep["no_llm_mode"] = False
                rep["gate_cache_key"] = _tpg.cache_key(
                    str(rep.get("raw_input_hash") or ""),
                    str(rep.get("sanitized_input_hash") or ""),
                    str(rep.get("rubric_hash") or ""),
                    str(rep.get("prompt_template_hash") or ""),
                    str(rep.get("model_id") or ""),
                    no_llm=False,
                )
                rp.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")

        _tdir, _cp, _valid = _make_taste_batch()
        _r = chk_taste_panel_completeness(_valid, _tdir)
        fcheck(f"F-TASTE-1 all-pass no-llm gate rc0 but C rejects → {_EXP_TASTE}", _cp.returncode == 0 and _r[0] == _EXP_TASTE and "--no-llm" in _r[1], f"gate_rc={_cp.returncode}; {_r[1]}; {_cp.stdout[-200:]}")
        _tdir, _cp, _valid = _make_taste_batch()
        _rewrite_taste_reports_as_real(_tdir / ".taste_panel")
        _r = chk_taste_panel_completeness(_valid, _tdir)
        fcheck("F-TASTE-REAL-SIM no_llm=False + false-key report accepted",
               _cp.returncode == 0 and _r[0] == "PASS", f"gate_rc={_cp.returncode}; {_r[1]}")
        _tdir, _cp, _valid = _make_taste_batch()
        _rewrite_taste_reports_as_real(_tdir / ".taste_panel")
        _panel = _tdir / ".taste_panel"
        _rp = sorted(_panel.glob("*_taste_panel_report.json"))[0]
        _rep = json.loads(_rp.read_text(encoding="utf-8"))
        _rep["model_id"] = "forged-model"
        import taste_panel_gate as _tpg
        _rep["gate_cache_key"] = _tpg.cache_key(
            str(_rep.get("raw_input_hash") or ""),
            str(_rep.get("sanitized_input_hash") or ""),
            str(_rep.get("rubric_hash") or ""),
            str(_rep.get("prompt_template_hash") or ""),
            str(_rep.get("model_id") or ""),
            no_llm=False,
        )
        _rp.write_text(json.dumps(_rep, ensure_ascii=False), encoding="utf-8")
        _r = chk_taste_panel_completeness(_valid, _tdir)
        fcheck(f"F-TASTE-1b model_id mismatch → {_EXP_TASTE}",
               _r[0] == _EXP_TASTE and "model_id mismatch" in _r[1], _r[1])
        _tdir, _cp, _valid = _make_taste_batch()
        _rewrite_taste_reports_as_real(_tdir / ".taste_panel")
        _panel = _tdir / ".taste_panel"
        _summary_path = _panel / "_taste_panel_summary.json"
        _summary = json.loads(_summary_path.read_text(encoding="utf-8"))
        _summary["model_id"] = "forged-summary-model"
        _summary_path.write_text(json.dumps(_summary, ensure_ascii=False), encoding="utf-8")
        _r = chk_taste_panel_completeness(_valid, _tdir)
        fcheck(f"F-TASTE-1c summary model_id mismatch → {_EXP_TASTE}",
               _r[0] == _EXP_TASTE and "summary model_id mismatch" in _r[1], _r[1])
        _fixture_nonpass = {"overrides": {"tp_01_03": {"verdict": "revise", "scores": {"D1": 80, "D2": 95, "D3": 95, "D4": 95, "D5": 95}}}}
        _tdir, _cp, _valid = _make_taste_batch(_fixture_nonpass)
        _r = chk_taste_panel_completeness(_valid, _tdir)
        fcheck(f"F-TASTE-2 non-pass report → {_EXP_TASTE}", _cp.returncode == 1 and _r[0] == _EXP_TASTE and "verdict" in _r[1], f"gate_rc={_cp.returncode}; {_r[1]}")
        _fixture_stale = {"overrides": {"tp_01_04": {"stale_hash": True}}}
        _tdir, _cp, _valid = _make_taste_batch(_fixture_stale)
        _rewrite_taste_reports_as_real(_tdir / ".taste_panel")
        _r = chk_taste_panel_completeness(_valid, _tdir)
        fcheck(f"F-TASTE-3 stale taste_panel report → {_EXP_TASTE}", _cp.returncode == 1 and _r[0] == _EXP_TASTE and "stale" in _r[1], f"gate_rc={_cp.returncode}; {_r[1]}")
        _tdir, _cp, _valid = _make_taste_batch(exempt=True)
        (_tdir / ".taste_panel" / "_taste_panel_summary.json").unlink()
        _r = chk_taste_panel_completeness(_valid, _tdir)
        fcheck(f"F-TASTE-4 quality_gate.exempt 不跳 taste_panel → {_EXP_TASTE}", _r[0] == _EXP_TASTE and "summary missing" in _r[1], _r[1])
        _tdir, _cp, _valid = _make_taste_batch()
        _panel = _tdir / ".taste_panel"
        _summary_path = _panel / "_taste_panel_summary.json"
        _summary = json.loads(_summary_path.read_text(encoding="utf-8"))
        _summary["no_llm_mode"] = False
        _summary_path.write_text(json.dumps(_summary, ensure_ascii=False), encoding="utf-8")
        for _rp in sorted(_panel.glob("*_taste_panel_report.json")):
            _rep = json.loads(_rp.read_text(encoding="utf-8"))
            _rep["no_llm_mode"] = False
            _rp.write_text(json.dumps(_rep, ensure_ascii=False), encoding="utf-8")
        _r = chk_taste_panel_completeness(_valid, _tdir)
        fcheck(f"F-TASTE-FLIP no-llm true-key flipped false -> {_EXP_TASTE}",
               _r[0] == _EXP_TASTE and "gate_cache_key mismatch" in _r[1], _r[1])

        # ── F-STAGE-1：--stage pre-panel 跳 C-taste-panel、final 照舊（cxp-gapfix-w1c r1）──
        print("[F-STAGE-1] --stage pre-panel → C-taste-panel SKIP（明標 panel 後補驗）；final → 原判準")
        _fixture_stage = {"overrides": {"tp_01_03": {"verdict": "revise", "scores": {"D1": 80, "D2": 95, "D3": 95, "D4": 95, "D5": 95}}}}
        _tdir, _cp, _valid = _make_taste_batch(_fixture_stage)
        _r_direct = chk_taste_panel_completeness(_valid, _tdir)

        # ── F-TEXT-CEILING：TEXT_CEILING ACK adversarial fixtures（2026-06-24）──
        print("[F-TEXT-CEILING] TEXT_CEILING ACK 黃燈/硬擋驗收")

        def _patch_yaml_fields(tdir: Path, sid: str, **extra_fields):
            """把 extra_fields 寫進對應 yaml（供 TEXT_CEILING 測試用）。
            yaml 格式：---\nfrontmatter\n---\n，只讀第一個 document。
            回傳 (Path, patched_dict) 供 caller rehash；找不到回 None。"""
            import re as _re
            for _yp in tdir.glob("*.yaml"):
                _raw = _yp.read_text(encoding="utf-8")
                # 取兩個 --- 之間的 frontmatter
                _m = _re.match(r"^---\s*\n(.*?)\n---\s*\n?", _raw, _re.DOTALL)
                if _m:
                    _front = _m.group(1)
                else:
                    _front = _raw
                _d = yaml.safe_load(_front) or {}
                if str(_d.get("script_id")) == sid:
                    _d.update(extra_fields)
                    _yp.write_text("---\n" + yaml.safe_dump(_d, allow_unicode=True, sort_keys=False) + "---\n", encoding="utf-8")
                    return _yp, _d
            return None

        def _rehash_report_for_patched_yaml(panel_dir: Path, sid: str, yaml_path: Path, yaml_data: dict):
            """yaml 被 patch 後，更新對應 report 的 raw/sanitized hash + gate_cache_key。"""
            import taste_panel_gate as _tpg3
            for _rp in panel_dir.glob("*_taste_panel_report.json"):
                _rep = json.loads(_rp.read_text(encoding="utf-8"))
                if str(_rep.get("script_id")) == sid:
                    _new_raw, _new_san = _tpg3.compute_hashes(yaml_path, yaml_data)
                    _rep["raw_input_hash"] = _new_raw
                    _rep["sanitized_input_hash"] = _new_san
                    _rep["stale_raw_input_hash"] = False
                    _rep["stale_sanitized_input_hash"] = False
                    _rep["gate_cache_key"] = _tpg3.cache_key(
                        _new_raw, _new_san,
                        str(_rep.get("rubric_hash") or ""),
                        str(_rep.get("prompt_template_hash") or ""),
                        str(_rep.get("model_id") or ""),
                        no_llm=bool(_rep.get("no_llm_mode")),
                    )
                    _rp.write_text(json.dumps(_rep, ensure_ascii=False), encoding="utf-8")
                    return True
            return False

        def _patch_report_scores(panel_dir: Path, sid: str, scores: dict, verdict: str = "revise"):
            """直接修改 report JSON 的 scores 和 verdict（bypass no-llm gate，供白盒測試）。"""
            import taste_panel_gate as _tpg2
            for _rp in panel_dir.glob("*_taste_panel_report.json"):
                _rep = json.loads(_rp.read_text(encoding="utf-8"))
                if str(_rep.get("script_id")) == sid:
                    _rep["scores"] = {**_rep.get("scores", {}), **scores}
                    _rep["verdict"] = verdict
                    # 重算 gate_cache_key（保留目前 no_llm_mode，不強制 True）
                    _rep["gate_cache_key"] = _tpg2.cache_key(
                        str(_rep.get("raw_input_hash") or ""),
                        str(_rep.get("sanitized_input_hash") or ""),
                        str(_rep.get("rubric_hash") or ""),
                        str(_rep.get("prompt_template_hash") or ""),
                        str(_rep.get("model_id") or ""),
                        no_llm=bool(_rep.get("no_llm_mode")),
                    )
                    _rp.write_text(json.dumps(_rep, ensure_ascii=False), encoding="utf-8")
                    return True
            return False

        def _make_tc_batch_with_patch(sid: str, yaml_extra: dict, report_scores: dict, report_verdict: str):
            """TEXT_CEILING 測試共用流程：建 batch → rewrite real → patch yaml → rehash → patch scores → load。"""
            _td, _cp, _ = _make_taste_batch()
            _panel = _td / ".taste_panel"
            _rewrite_taste_reports_as_real(_panel)
            _yp_data = _patch_yaml_fields(_td, sid, **yaml_extra)
            if _yp_data:
                _ypath, _ydata = _yp_data
                _rehash_report_for_patched_yaml(_panel, sid, _ypath, _ydata)
            _patch_report_scores(_panel, sid, report_scores, report_verdict)
            _valid = [(p, d) for p, d in load_yamls(_td) if isinstance(d, dict) and "__parse_error__" not in d]
            return _valid, _td

        # F-TEXT-CEILING-1：純文字稿 5 維 80-89（各維≥80、有維<90）→ TEXT_CEILING WARN
        _sid_tc = "tp_01_01"
        _valid_tc1, _tdir_tc1 = _make_tc_batch_with_patch(
            _sid_tc,
            yaml_extra={"true_material_source": "none", "score_type": "script"},
            report_scores={"D1": 82, "D2": 85, "D3": 88, "D4": 86, "D5": 84},
            report_verdict="revise",
        )
        _r_tc1 = chk_taste_panel_completeness(_valid_tc1, _tdir_tc1)
        fcheck("F-TEXT-CEILING-1 純文字稿 5 維 80-89 → TEXT_CEILING WARN（非 FAIL）",
               _r_tc1[0] == "WARN" and "TEXT_CEILING" in _r_tc1[1], _r_tc1[1])

        # F-TEXT-CEILING-2：純文字稿但某維 <80 → hard FAIL（稿太弱不轉黃燈）
        _valid_tc2, _tdir_tc2 = _make_tc_batch_with_patch(
            _sid_tc,
            yaml_extra={"true_material_source": "none", "score_type": "angle"},
            report_scores={"D1": 82, "D2": 75, "D3": 88, "D4": 86, "D5": 84},
            report_verdict="revise",
        )
        _r_tc2 = chk_taste_panel_completeness(_valid_tc2, _tdir_tc2)
        fcheck("F-TEXT-CEILING-2 純文字稿某維 <80（D2=75）→ hard FAIL（不轉黃燈）",
               _r_tc2[0] == _EXP_TASTE and "純文字弱維" in _r_tc2[1], _r_tc2[1])

        # F-TEXT-CEILING-3：generic 退件純文字稿（verdict=reject_generic）→ hard FAIL（不轉黃燈）
        _valid_tc3, _tdir_tc3 = _make_tc_batch_with_patch(
            _sid_tc,
            yaml_extra={"true_material_source": "none", "score_type": "script"},
            report_scores={"D1": 82, "D2": 85, "D3": 88, "D4": 86, "D5": 84},
            report_verdict="reject_generic",
        )
        _r_tc3 = chk_taste_panel_completeness(_valid_tc3, _tdir_tc3)
        fcheck("F-TEXT-CEILING-3 generic 退件純文字稿 → hard FAIL（不轉黃燈）",
               _r_tc3[0] == _EXP_TASTE and ("verdict=reject_generic" in _r_tc3[1] or "verdict" in _r_tc3[1]), _r_tc3[1])

        # F-TEXT-CEILING-4：成片稿（true_material_source!="none"）有維度 <90 → 原邏輯 hard FAIL（不走黃燈）
        _valid_tc4, _tdir_tc4 = _make_tc_batch_with_patch(
            _sid_tc,
            yaml_extra={"true_material_source": "real_footage", "score_type": "finished_video"},
            report_scores={"D1": 85, "D2": 92, "D3": 93, "D4": 91, "D5": 90},
            report_verdict="revise",
        )
        _r_tc4 = chk_taste_panel_completeness(_valid_tc4, _tdir_tc4)
        fcheck("F-TEXT-CEILING-4 成片稿有維度 <90 → hard FAIL（原邏輯不變）",
               _r_tc4[0] == _EXP_TASTE and "D1=85" in _r_tc4[1], _r_tc4[1])

        # F-TEXT-CEILING-5：純文字稿 5 維全≥90 → PASS（正常路徑，黃燈不擋）
        _valid_tc5, _tdir_tc5 = _make_tc_batch_with_patch(
            _sid_tc,
            yaml_extra={"true_material_source": "none", "score_type": "script"},
            report_scores={"D1": 91, "D2": 92, "D3": 93, "D4": 91, "D5": 90},
            report_verdict="pass",
        )
        _r_tc5 = chk_taste_panel_completeness(_valid_tc5, _tdir_tc5)
        fcheck("F-TEXT-CEILING-5 純文字稿 5 維全≥90 → PASS",
               _r_tc5[0] == "PASS", _r_tc5[1])

        # ── F-C22-ANGLE：chk_c22_offpro_angle 單元測試（2026-06-24）──
        # Phase 0 shadow（_C22_OFFPRO_ANGLE_ENFORCE=False），所有 FAIL 降 WARN
        print("[F-C22-ANGLE] C-22-OFFPRO-ANGLE 角度守門 per-script 單元測試")

        def _mk_stub(**kwargs) -> dict:
            """產一個合規 stub（11 欄齊 + voice_removed 全 5），可 override 任意欄。"""
            base = {
                "topic": "決定總是慢半拍",
                "generic_take": "大家都說要衝就要衝",
                "sharp_claim": "不是你太慢，是你在等對方先開口——那才是真的沒底",
                "rejected_common_belief": "果斷的人行動快",
                "tradeoff_or_cost": "等待的代價是機會窗口縮短、對方讀成你不在意",
                "behavior_delta": "下次當你想等的時候，先問自己：我在等時機還是等對方？",
                "audience_decision_moment": "考慮要不要先開口的那個晚上",
                "opposing_rebuttal": "等是一種尊重，讓對方有空間思考",
                "concrete_scene": "捷運站等人那次，一直滑手機但沒傳出去那則訊息",
                "timeliness_or_context": "在大家都說慢慢來的現在，沉默卻是最貴的代價",
                "title_gap": "你以為在等時機，其實在等它消失",
                "voice_removed": {"concreteness": 5, "stance_sharpness": 5, "replacement_loss": 5},
            }
            base.update(kwargs)
            return base

        def _mk_angle_data(stub=None, lane="voice_first", proof_mode="voice_first", **extra) -> dict:
            d = {"lane": lane, "proof_mode": proof_mode, "title": "決定總是慢半拍"}
            if stub is not None:
                d["c22_offpro_angle_stub"] = stub
            d.update(extra)
            return d

        _EXP_ANG = "WARN"  # Phase 0 shadow：所有 FAIL 降 WARN

        # F-C22-ANGLE-0：非 off-pro 稿 → PASS N/A 跳過
        _r = chk_c22_offpro_angle({"proof_mode": "proof_first"}, "f0.yaml")
        fcheck("F-C22-ANGLE-0 非 off-pro → PASS N/A（不誤殺本業稿）",
               _r[0] == "PASS" and "N/A" in _r[1], _r[1])

        # F-C22-ANGLE-001：MISSING_STUB（stub 缺）
        _r = chk_c22_offpro_angle(_mk_angle_data(), "f001.yaml")
        fcheck(f"F-C22-ANGLE-001 stub 缺 → {_EXP_ANG}（shadow 降 WARN）",
               _r[0] == _EXP_ANG and "001" in _r[1], _r[1])

        # F-C22-ANGLE-001b：stub 非 dict
        _r = chk_c22_offpro_angle(_mk_angle_data(stub="not_a_dict"), "f001b.yaml")
        fcheck(f"F-C22-ANGLE-001b stub 非 dict → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "001" in _r[1], _r[1])

        # F-C22-ANGLE-002：GENERIC_TAKE_MISSING
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(generic_take="")), "f002.yaml")
        fcheck(f"F-C22-ANGLE-002 generic_take 空白 → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "002" in _r[1], _r[1])

        # F-C22-ANGLE-003a：sharp_claim 空白
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(sharp_claim="")), "f003a.yaml")
        fcheck(f"F-C22-ANGLE-003a sharp_claim 空白 → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "003" in _r[1], _r[1])

        # F-C22-ANGLE-003b：sharp_claim == generic_take
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            generic_take="大家都說要衝就要衝", sharp_claim="大家都說要衝就要衝")), "f003b.yaml")
        fcheck(f"F-C22-ANGLE-003b sharp_claim == generic_take → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "003" in _r[1], _r[1])

        # F-C22-ANGLE-003c：命中溫共識詞庫 AND 無對比標記 → FAIL（降 WARN）
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            sharp_claim="好好愛自己，先看人再做決定")), "f003c.yaml")
        fcheck(f"F-C22-ANGLE-003c 命中溫共識詞+無對比標記 → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "003" in _r[1], _r[1])

        # F-C22-ANGLE-003d：命中溫共識詞庫 BUT 有對比標記 → 不觸發 003
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            sharp_claim="不是好好愛自己，而是先確認自己的底線")), "contrast_guard.yaml")
        fcheck("F-C22-ANGLE-003d 溫共識+有對比標記 → PASS（對比標記保護，003 不命中）",
               _r[0] == "PASS", _r[1])

        # F-C22-ANGLE-004：NO_REJECTED_BELIEF
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(rejected_common_belief="")), "f004.yaml")
        fcheck(f"F-C22-ANGLE-004 rejected_common_belief 空白 → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "004" in _r[1], _r[1])

        # F-C22-ANGLE-005：NO_COST
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(tradeoff_or_cost="")), "f005.yaml")
        fcheck(f"F-C22-ANGLE-005 tradeoff_or_cost 空白 → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "005" in _r[1], _r[1])

        # F-C22-ANGLE-006：NO_BEHAVIOR_DELTA（永遠 WARN，不受 enforce flag）
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(behavior_delta="")), "f006.yaml")
        fcheck("F-C22-ANGLE-006 behavior_delta 空白 → WARN（永遠 WARN，不受 enforce flag）",
               _r[0] == "WARN" and "006" in _r[1], _r[1])

        # F-C22-ANGLE-007a：AUDIENCE_TOO_BROAD（空白）
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(audience_decision_moment="")), "f007a.yaml")
        fcheck(f"F-C22-ANGLE-007a audience_decision_moment 空白 → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "007" in _r[1], _r[1])

        # F-C22-ANGLE-007b：audience 在寬泛詞集
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(audience_decision_moment="大家")), "f007b.yaml")
        fcheck(f"F-C22-ANGLE-007b audience_decision_moment='大家'（寬泛詞）→ {_EXP_ANG}",
               _r[0] == _EXP_ANG and "007" in _r[1], _r[1])

        # F-C22-ANGLE-008a：NO_REAL_REBUTTAL（空白）
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(opposing_rebuttal="")), "f008a.yaml")
        fcheck(f"F-C22-ANGLE-008a opposing_rebuttal 空白 → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "008" in _r[1], _r[1])

        # F-C22-ANGLE-008b：opposing_rebuttal == sharp_claim（回聲）
        _sc = "不是你太慢，是你在等對方先開口"
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(sharp_claim=_sc, opposing_rebuttal=_sc)), "f008b.yaml")
        fcheck(f"F-C22-ANGLE-008b opposing_rebuttal == sharp_claim（回聲）→ {_EXP_ANG}",
               _r[0] == _EXP_ANG and "008" in _r[1], _r[1])

        # F-C22-ANGLE-009a：TITLE_NO_GAP（空白）
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(title_gap="")), "f009a.yaml")
        fcheck(f"F-C22-ANGLE-009a title_gap 空白 → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "009" in _r[1], _r[1])

        # F-C22-ANGLE-009b：title_gap == topic
        _r = chk_c22_offpro_angle(_mk_angle_data(
            stub=_mk_stub(topic="決定總是慢半拍", title_gap="決定總是慢半拍")), "f009b.yaml")
        fcheck(f"F-C22-ANGLE-009b title_gap == topic → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "009" in _r[1], _r[1])

        # F-C22-ANGLE-009c：title_gap == yaml title
        _r = chk_c22_offpro_angle(
            {"lane": "voice_first", "proof_mode": "voice_first",
             "title": "決定總是慢半拍",
             "c22_offpro_angle_stub": _mk_stub(title_gap="決定總是慢半拍")}, "f009c.yaml")
        fcheck(f"F-C22-ANGLE-009c title_gap == yaml title → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "009" in _r[1], _r[1])

        # F-C22-ANGLE-010a：VOICE_REMOVED_LT4（缺 voice_removed）
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(voice_removed=None)), "f010a.yaml")
        fcheck(f"F-C22-ANGLE-010a voice_removed 缺 → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "010" in _r[1], _r[1])

        # F-C22-ANGLE-010b：子項值 < 4
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            voice_removed={"concreteness": 3, "stance_sharpness": 5, "replacement_loss": 5})), "f010b.yaml")
        fcheck(f"F-C22-ANGLE-010b voice_removed.concreteness=3 < 4 → {_EXP_ANG}",
               _r[0] == _EXP_ANG and "010" in _r[1], _r[1])

        # F-C22-ANGLE-PASS：11 欄齊 + voice_removed 全 ≥4 + 有對比標記 sharp_claim → PASS
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub()), "f_pass.yaml")
        fcheck("F-C22-ANGLE-PASS 11 欄齊+voice_removed≥4+有對比標記 sharp_claim → PASS",
               _r[0] == "PASS" and "PASS" in _r[1], _r[1])

        # F-C22-ANGLE-SHADOW：shadow 模式下 FAIL 降 WARN（enforce=False 時多個 FAIL 碼 → WARN）
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            generic_take="", rejected_common_belief="", tradeoff_or_cost="")), "f_shadow.yaml")
        fcheck("F-C22-ANGLE-SHADOW shadow 模式（enforce=False）多個 FAIL 碼 → WARN（非 FAIL）",
               _r[0] == "WARN" and "002" in _r[1] and "004" in _r[1] and "005" in _r[1], _r[1])

        # ── Codex R1 修 adversarial fixtures（2026-06-24）──

        # F-C22-ANGLE-R1-GATE-DEMAND：proof_mode=demand_first → N/A（新 gate 排除）
        _r = chk_c22_offpro_angle({"proof_mode": "demand_first", "content_axis": "offpro"}, "r1_demand.yaml")
        fcheck("F-C22-ANGLE-R1-GATE-DEMAND proof_mode=demand_first → PASS N/A（新 gate 排除）",
               _r[0] == "PASS" and "N/A" in _r[1], _r[1])

        # F-C22-ANGLE-R1-GATE-PROFESSIONAL：proof_mode=professional → N/A
        _r = chk_c22_offpro_angle({"proof_mode": "professional", "content_axis": "offpro"}, "r1_pro.yaml")
        fcheck("F-C22-ANGLE-R1-GATE-PROFESSIONAL proof_mode=professional → PASS N/A",
               _r[0] == "PASS" and "N/A" in _r[1], _r[1])

        # F-C22-ANGLE-R1-GATE-ANCHOR：lane=anchor_first → N/A
        _r = chk_c22_offpro_angle({"lane": "anchor_first", "content_axis": "offpro"}, "r1_anchor.yaml")
        fcheck("F-C22-ANGLE-R1-GATE-ANCHOR lane=anchor_first → PASS N/A",
               _r[0] == "PASS" and "N/A" in _r[1], _r[1])

        # F-C22-ANGLE-R1-GATE-LANE-VOICEFIRST-NO-PROOF：lane=voice_first 但 proof_mode 漏填 → 新 gate 應觸發
        _r = chk_c22_offpro_angle({"lane": "voice_first"}, "r1_lane_noproof.yaml")
        fcheck("F-C22-ANGLE-R1-GATE-LANE-VOICEFIRST proof_mode 漏填+lane=voice_first → 觸發（001 stub 缺）",
               _r[0] == _EXP_ANG and "001" in _r[1], _r[1])

        # F-C22-ANGLE-R1-PH-STUB：placeholder stub → FAIL(降 WARN)
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            generic_take="[編劇填]", sharp_claim="[編劇填]")), "r1_ph_stub.yaml")
        fcheck(f"F-C22-ANGLE-R1-PH-STUB placeholder 值視同缺欄 → {_EXP_ANG}（002/003）",
               _r[0] == _EXP_ANG and ("002" in _r[1] or "003" in _r[1]), _r[1])

        # F-C22-ANGLE-R1-MISSING-TOPIC：topic 空白 → 011
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(topic="")), "r1_no_topic.yaml")
        fcheck(f"F-C22-ANGLE-R1-MISSING-TOPIC topic 空白 → {_EXP_ANG}（011）",
               _r[0] == _EXP_ANG and "011" in _r[1], _r[1])

        # F-C22-ANGLE-R1-MISSING-SCENE：concrete_scene 空白 → 012
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(concrete_scene="")), "r1_no_scene.yaml")
        fcheck(f"F-C22-ANGLE-R1-MISSING-SCENE concrete_scene 空白 → {_EXP_ANG}（012）",
               _r[0] == _EXP_ANG and "012" in _r[1], _r[1])

        # F-C22-ANGLE-R1-MISSING-TIME：timeliness_or_context 空白 → 013
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(timeliness_or_context="")), "r1_no_time.yaml")
        fcheck(f"F-C22-ANGLE-R1-MISSING-TIME timeliness_or_context 空白 → {_EXP_ANG}（013）",
               _r[0] == _EXP_ANG and "013" in _r[1], _r[1])

        # F-C22-ANGLE-R1-010-BOOL：voice_removed 子項=True（bool）→ FAIL（降 WARN）
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            voice_removed={"concreteness": True, "stance_sharpness": 5, "replacement_loss": 5})), "r1_vr_bool.yaml")
        fcheck(f"F-C22-ANGLE-R1-010-BOOL voice_removed.concreteness=True(bool) → {_EXP_ANG}（010）",
               _r[0] == _EXP_ANG and "010" in _r[1], _r[1])

        # F-C22-ANGLE-R1-010-OVERLIMIT：voice_removed 子項=999 → FAIL（降 WARN）
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            voice_removed={"concreteness": 999, "stance_sharpness": 5, "replacement_loss": 5})), "r1_vr_999.yaml")
        fcheck(f"F-C22-ANGLE-R1-010-OVERLIMIT voice_removed.concreteness=999 → {_EXP_ANG}（010）",
               _r[0] == _EXP_ANG and "010" in _r[1], _r[1])

        # F-C22-ANGLE-R1-008-SUBSTRING：opposing_rebuttal 包含 sharp_claim 為子字串 → FAIL（降 WARN）
        _sc2 = "不是等對方開口，是自己先表態"
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            sharp_claim=_sc2,
            opposing_rebuttal=f"我不認同：{_sc2}，這樣反而失去尊重")), "r1_008_substr.yaml")
        fcheck(f"F-C22-ANGLE-R1-008-SUBSTRING rebuttal 包含 sharp_claim 子字串 → {_EXP_ANG}（008）",
               _r[0] == _EXP_ANG and "008" in _r[1], _r[1])

        # F-C22-ANGLE-R1-014-BINDING：sharp_claim 不在台詞中 → FAIL（降 WARN）
        _claim = "不是等對方開口，是你在等機會消失"
        _r = chk_c22_offpro_angle({
            "lane": "voice_first", "proof_mode": "voice_first",
            "c22_offpro_angle_stub": _mk_stub(sharp_claim=_claim),
            "scenes": [{"台詞": "今天我打了通電話，電話通了，但我什麼都沒說。"}]
        }, "r1_014_binding.yaml")
        fcheck(f"F-C22-ANGLE-R1-014-BINDING sharp_claim 不在台詞 → {_EXP_ANG}（014）",
               _r[0] == _EXP_ANG and "014" in _r[1], _r[1])

        # F-C22-ANGLE-R1-BINDING-PASS：sharp_claim 在台詞中 → 014 不觸發
        _claim2 = "不是等對方開口，是你在等機會消失"
        _r = chk_c22_offpro_angle({
            "lane": "voice_first", "proof_mode": "voice_first",
            "c22_offpro_angle_stub": _mk_stub(sharp_claim=_claim2),
            "scenes": [{"台詞": f"我問自己：{_claim2}，所以那次我先開口了。"}]
        }, "r1_binding_ok.yaml")
        fcheck("F-C22-ANGLE-R1-BINDING-PASS sharp_claim 在台詞 → 014 不觸發（PASS）",
               _r[0] == "PASS" and "014" not in _r[1], _r[1])

        # F-C22-ANGLE-R1-007-NEW-BROAD：新增寬泛詞（任何人/所有的人/上班族）→ FAIL（降 WARN）
        for _broad in ("任何人", "所有的人", "上班族"):
            _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(audience_decision_moment=_broad)), f"r1_007_{_broad}.yaml")
            fcheck(f"F-C22-ANGLE-R1-007-{_broad} 新擴充寬泛詞 → {_EXP_ANG}（007）",
                   _r[0] == _EXP_ANG and "007" in _r[1], _r[1])

        # F-C22-ANGLE-R1-007-SPECIFIC：具體受眾不誤殺
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(audience_decision_moment="考慮要不要先開口的那個晚上")), "r1_audience_specific.yaml")
        fcheck("F-C22-ANGLE-R1-007-SPECIFIC 具體受眾不誤殺（007 不命中）",
               "007" not in _r[1], _r[1])

        # F-C22-ANGLE-R1-NOSKELETON-BINDING：骨架稿（無 scenes）→ 014 不觸發（不誤殺骨架）
        _r = chk_c22_offpro_angle({
            "lane": "voice_first", "proof_mode": "voice_first",
            "c22_offpro_angle_stub": _mk_stub(sharp_claim="不是等對方開口，是你在等機會消失"),
        }, "r1_skeleton_no_scenes.yaml")
        fcheck("F-C22-ANGLE-R1-NOSKELETON-BINDING 骨架無 scenes → 014 不觸發",
               "014" not in _r[1], _r[1])

        # ── Codex R2 fixtures（2026-06-24）──

        # F-C22-R2-PLACEHOLDER：skeleton [填：...] 格式被 _is_placeholder 認出 → 視同缺欄
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            generic_take="[填：同行都能講的通用觀點，作對照用]",
            sharp_claim="[填：一句同行講不出的尖主張]"
        )), "r2_ph_bracket.yaml")
        fcheck(f"F-C22-R2-PLACEHOLDER [填：...] 格式被認出為 placeholder → {_EXP_ANG}（002/003）",
               _r[0] == _EXP_ANG and ("002" in _r[1] or "003" in _r[1]), _r[1])

        # F-C22-R2-PLACEHOLDER-PASS：已填寫的值不誤判為 placeholder
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            generic_take="大家都說要等感覺對了再開口",
            sharp_claim="不是等感覺，是等你先認輸"
        )), "r2_ph_not_placeholder.yaml")
        fcheck("F-C22-R2-PLACEHOLDER-PASS 已填寫的值不誤判 placeholder → PASS",
               _r[0] == "PASS", _r[1])

        # F-C22-R2-SCALAR-FAIL：stub 字串欄是 list → 視為缺欄 FAIL（降 WARN）
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            generic_take=["大家都說", "要衝就衝"]
        )), "r2_scalar_list.yaml")
        fcheck(f"F-C22-R2-SCALAR-FAIL generic_take=list → {_EXP_ANG}（002）",
               _r[0] == _EXP_ANG and "002" in _r[1], _r[1])

        # F-C22-R2-014-QUOTE-PATH：R3 Fix 2（2026-06-24）行為更新
        # sharp_claim == new_answer.quote 但不在台詞 → 014 觸發（quote 不可替代台詞落地）
        # 舊 R2 預期：PASS（quote 可替代）→ R3 後：014 WARN
        _claim_q = "不是在等感覺，是在等你先開口"
        _r = chk_c22_offpro_angle({
            "lane": "voice_first", "proof_mode": "voice_first",
            "c22_offpro_angle_stub": _mk_stub(
                sharp_claim=_claim_q,
                new_answer={"quote": _claim_q, "source": "2026-06-24訪談"},
            ),
            "scenes": [{"台詞": "今天我打了一通電話，電話通了，但我什麼都沒說。"}],
        }, "r2_quote_path.yaml")
        fcheck("F-C22-R2-014-QUOTE-PATH sharp_claim==new_answer.quote 但不在台詞 → 014 觸發（R3：quote 不替代台詞）",
               "[014]" in _r[1], _r[1])

        # F-C22-R2-008-REVERSE-ECHO：sharp_claim 包含 rebuttal 為子字串（反向 echo）→ WARN
        # rebuttal 需 >= 4 字（保護短詞誤殺）
        _reb_short = "等待才是尊重"  # 6 字，作為 sharp_claim 的子句
        _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            sharp_claim=f"不是你太慢——{_reb_short}，讓機會窗口縮短",
            opposing_rebuttal=_reb_short,
        )), "r2_rev_echo.yaml")
        fcheck(f"F-C22-R2-008-REVERSE-ECHO sharp_claim 包含 rebuttal 子字串（>=4 字）→ {_EXP_ANG}（008）",
               _r[0] == _EXP_ANG and "[008]" in _r[1], _r[1])

        # F-C22-R2-007-NEW-BROAD-2：新增寬泛詞（所有上班族/每個正在努力的人）→ WARN
        for _broad2 in ("所有上班族", "每個正在努力的人", "正在努力的人"):
            _r = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
                audience_decision_moment=_broad2
            )), f"r2_007_{_broad2}.yaml")
            fcheck(f"F-C22-R2-007-{_broad2} R2 新寬泛詞 → {_EXP_ANG}（007）",
                   _r[0] == _EXP_ANG and "007" in _r[1], _r[1])

        # F-C22-R2-PLAN-LOCK-PROOF：proof_mode derive-lock 推導邏輯輕量單元測試
        # K11（2026-07-16）：斷言真模組常數 _LANE_TO_PROOF（非本地快照）——professional
        # 已補回 proof_first，Delta A 漏改或回退時本 fixture 必紅（根治自證）。
        _r_pm_vf = _LANE_TO_PROOF.get("voice_first") == "voice_first"
        _r_pm_pro_lock = _LANE_TO_PROOF.get("professional") == "proof_first"  # K11：professional 在表且鎖 proof_first
        _r_pm_mismatch = _LANE_TO_PROOF.get("voice_first") != "demand_first"
        fcheck("F-C22-R2-PLAN-LOCK-PROOF voice_first→voice_first 推導正確",
               _r_pm_vf, f"voice_first→{_LANE_TO_PROOF.get('voice_first')}")
        fcheck("F-C22-R2-PLAN-LOCK-PROOF-PRO-LOCK professional 在 _LANE_TO_PROOF 且鎖 proof_first（K11）",
               _r_pm_pro_lock, f"professional→{_LANE_TO_PROOF.get('professional')}")
        fcheck("F-C22-R2-PLAN-LOCK-PROOF-MISMATCH voice_first vs demand_first 應偵測到不符",
               _r_pm_mismatch, "mismatch check")

        # F-C22-R2-CTA-MIX-SCOPE：hybrid 批排除 offpro 稿 — offpro 被排除後 yamls 空 → PASS N/A
        _offpro_only = [(Path("s1.yaml"), {"content_axis": "offpro", "schema_check": {"CTA類型": "諮詢"}})]
        _r_ctamix = chk_c_cta_mix(_offpro_only, "瑞祥", None, "")
        fcheck("F-C22-R2-CTA-MIX-SCOPE offpro-only yamls → PASS N/A（off-pro 排除，不驗業主 mix）",
               _r_ctamix[0] == "PASS" and ("N/A" in _r_ctamix[1] or "偏好.md" in _r_ctamix[1]), _r_ctamix[1])

        # F-C22-R2-OFFPRO-CTA-POLICY-LEGAL：合法 scope（none/self_check）→ PASS
        _legal_offpro = [
            (Path("s1.yaml"), {"content_axis": "offpro", "cta_offer_scope": "none"}),
            (Path("s2.yaml"), {"content_axis": "offpro", "cta_offer_scope": "self_check"}),
            (Path("s3.yaml"), {"content_axis": "offpro", "cta_offer_scope": "save_share"}),
        ]

        # F-C22-R2-OFFPRO-CTA-POLICY-BLOCKED：含私訊/LINE → WARN（shadow）
        _blocked_offpro = [
            (Path("s1.yaml"), {"content_axis": "offpro", "cta_offer_scope": "none",
                               "scenes": [{"台詞": "有需要可以私訊我喔"}]}),
        ]

        # F-C22-R2-OFFPRO-CTA-POLICY-NA：非 offpro 批 → PASS N/A
        _non_offpro = [(Path("s1.yaml"), {"content_axis": "professional"})]

        # ── R3 fixtures（2026-06-24）──

        # Fix 1：plan_lock_hash 含 proof_mode，且 lane-derived 永遠權威
        # K11：LANE_TO_PROOF 表含 professional（lane-derived = proof_first → 鎖，非 skip）
        # R4 Fix 3（2026-06-24）：清掉死斷言 or True
        # 真實測試：有 proof_mode 欄的 plan 和沒有 proof_mode 的 plan 給出不同 hash
        _h_with_pm = _plan_lock_hash([{"script_id": "x", "content_axis": "offpro",
                                        "lane": "voice_first", "derived_flags": [],
                                        "proof_mode": "voice_first"}])
        _h_without_pm = _plan_lock_hash([{"script_id": "x", "content_axis": "offpro",
                                           "lane": "voice_first", "derived_flags": []}])
        # 無 proof_mode 欄時 item.get("proof_mode", "") → ""，有欄時 → "voice_first"，hash 應不同
        fcheck("F-R3-PLAN-LOCK-HASH-PROOF_MODE proof_mode 納入 hash（有無 proof_mode → hash 不同）",
               _h_with_pm != _h_without_pm, f"with={_h_with_pm[:8]} without={_h_without_pm[:8]}")
        _h1 = _plan_lock_hash([{"script_id": "x", "content_axis": "offpro", "lane": "voice_first",
                                 "derived_flags": [], "proof_mode": "voice_first"}])
        _h2 = _plan_lock_hash([{"script_id": "x", "content_axis": "offpro", "lane": "voice_first",
                                 "derived_flags": [], "proof_mode": "demand_first"}])
        fcheck("F-R3-PLAN-LOCK-HASH-PROOF_MODE proof_mode 不同 → hash 不同",
               _h1 != _h2, f"h1={_h1[:8]} h2={_h2[:8]}")

        fcheck("F-R3-PLAN-LOCK-LANE-AUTHORITATIVE-PRO-LOCK lane-derived professional=proof_first → 鎖（K11 撤排除）",
               _LANE_TO_PROOF.get("professional") == "proof_first", f"pro→{_LANE_TO_PROOF.get('professional')}")

        _offpro_map_ok = (
            _LANE_TO_PROOF.get("voice_first") == "voice_first"
            and _LANE_TO_PROOF.get("stance") == "voice_first"
            and _LANE_TO_PROOF.get("demand_first") == "demand_first"
            and _LANE_TO_PROOF.get("anchor_first") == "anchor_first"
        )
        fcheck("F-R3-PLAN-LOCK-LANE-AUTHORITATIVE-OFFPRO-MAP 四 off-pro lane 映射逐鍵等值（K11 零變基線）",
               _offpro_map_ok,
               f"voice_first={_LANE_TO_PROOF.get('voice_first')} stance={_LANE_TO_PROOF.get('stance')} "
               f"demand_first={_LANE_TO_PROOF.get('demand_first')} anchor_first={_LANE_TO_PROOF.get('anchor_first')}")

        # ── 威脅模型邊界（K11 出貨審 r8 裁定）──
        # 本 guard（含下方 L1-L3）防護對象＝意外與工具錯誤級回歸（誤刪鍵/誤改值/
        # 誤加 shadow/誤重綁）；**同檔惡意編輯不在 scope**——惡意編輯者可同時改掉
        # fixtures 本身，該類威脅由 git commit 審查鏈＋W4 SHA 卡外部錨定防護。

        # F-K11-IMPORT-EXACT-MAP（K11 出貨審 r6 建、r8 改活物件求值）：fresh 子進程
        # import 本模組（只在 __name__=="__main__" 才跑的 main block 不執行），在
        # 子進程「內部」對活的 _LANE_TO_PROOF 物件求值四個布林（不把物件序列化
        # 運回母端比對——JSON 只運回布林結果）：
        #   ok_map          ＝內容等於正典五鍵字面
        #   ok_container    ＝type(...) is dict（exact，subclass 不算）
        #   ok_value_types  ＝逐鍵逐值 type(k) is str and type(v) is str（exact str，
        #                     str 子類覆寫 __eq__ 塞值＝封 AlwaysStr 類反例）
        #   ok_get          ＝.get('professional') API 語義正確
        # 母端只驗證四布林皆 True＋輸出可解析 JSON。
        import subprocess as _subprocess_k11

        _script_dir_k11 = str(Path(__file__).resolve().parent)
        _import_probe_src_k11 = (
            "import sys, json\n"
            f"sys.path.insert(0, {_script_dir_k11!r})\n"
            "import validate_script_batch as V\n"
            "_canon = {\n"
            "    'anchor_first': 'anchor_first',\n"
            "    'demand_first': 'demand_first',\n"
            "    'professional': 'proof_first',\n"
            "    'stance': 'voice_first',\n"
            "    'voice_first': 'voice_first',\n"
            "}\n"
            "ok_map = (V._LANE_TO_PROOF == _canon)\n"
            "ok_container = type(V._LANE_TO_PROOF) is dict\n"
            "ok_value_types = all(\n"
            "    type(k) is str and type(v) is str\n"
            "    for k, v in V._LANE_TO_PROOF.items()\n"
            ")\n"
            "ok_get = (V._LANE_TO_PROOF.get('professional') == 'proof_first')\n"
            "result = {\n"
            "    'ok_map': ok_map,\n"
            "    'ok_container': ok_container,\n"
            "    'ok_value_types': ok_value_types,\n"
            "    'ok_get': ok_get,\n"
            "}\n"
            "print(json.dumps(result, sort_keys=True))\n"
        )
        try:
            _import_probe_cp_k11 = _subprocess_k11.run(
                [sys.executable, "-c", _import_probe_src_k11],
                capture_output=True, text=True, timeout=120,
            )
            _import_probe_parsed_k11 = json.loads(_import_probe_cp_k11.stdout.strip())
            _import_probe_ok_k11 = (
                _import_probe_cp_k11.returncode == 0
                and _import_probe_parsed_k11.get("ok_map") is True
                and _import_probe_parsed_k11.get("ok_container") is True
                and _import_probe_parsed_k11.get("ok_value_types") is True
                and _import_probe_parsed_k11.get("ok_get") is True
            )
            _import_probe_detail_k11 = (
                f"rc={_import_probe_cp_k11.returncode} "
                f"parsed={_import_probe_parsed_k11!r} "
                f"stderr={_import_probe_cp_k11.stderr.strip()[-300:]!r}"
            )
        except Exception as exc:
            _import_probe_ok_k11 = False
            _import_probe_detail_k11 = f"subprocess 失敗/超時：{type(exc).__name__}: {exc}"
        fcheck("F-K11-IMPORT-EXACT-MAP fresh 子進程內對活物件求值四布林皆真：ok_map（內容等於正典）＋"
               "ok_container（type is dict、非 subclass）＋ok_value_types（逐鍵逐值 exact str、封 "
               "AlwaysStr 覆寫 __eq__ 類）＋ok_get（.get('professional') API 語義正確）",
               _import_probe_ok_k11, _import_probe_detail_k11)

        # ── Delta E fixture ③（r4 防 local shadow 繞過；r2 symtable 法；r3 雙軌合一；
        # r4 AST 軌改 binding-context 判定；r5 出貨審裁定＝guard 邏輯零改、只改
        # 契約宣稱與註解；r6 出貨審裁定＝新增 F-K11-IMPORT-EXACT-MAP 收斂 L1 真防線）──
        #
        # 防線分層（K11 出貨審 r6 裁定）：
        # L1 真防線＝F-K11-IMPORT-EXACT-MAP（fresh 子進程內對活物件求值 import 終值/
        #    容器型別/值型別/.get 四布林，ok_map∧ok_container∧ok_value_types∧ok_get
        #    皆真才綠；任何 module-scope 重綁或 dict/str subclass 偽裝若四布林任一
        #    為假必紅）＋PRO-LOCK 逐鍵內容斷言。
        # L2 shadow 防線＝symtable 巢狀 scope 零綁定（is_assigned/parameter/namespace/imported）——
        #    唯一能讓「chk 用表 ≠ 模組常數」的路徑，已完備封死。
        # L3 輔助啟發式＝module-scope Store-ctx 計數（抓常見重複定義；已知不計 match pattern/
        #    外層運算式 walrus 等罕見構式——該類由 L1 兜底，不宣稱完備）。
        import ast as _ast_k11
        import symtable as _symtable_k11

        _SCOPE_BOUNDARY_TYPES_K11 = (
            _ast_k11.FunctionDef,
            _ast_k11.AsyncFunctionDef,
            _ast_k11.ClassDef,
            _ast_k11.Lambda,
            _ast_k11.ListComp,
            _ast_k11.SetComp,
            _ast_k11.DictComp,
            _ast_k11.GeneratorExp,
        )

        def _walk_module_scope_count_k11(node, target_name: str) -> int:
            # 具名 scope 節點：名字本身綁在外層 scope（要計），但不進入其內部
            # （body/args 等歸 symtable 軌管；decorator/default 內 walrus 綁 module
            # scope＝由 L1 import 終值探針兜底，非本 L3 計數軌職責）。
            if isinstance(node, (_ast_k11.FunctionDef, _ast_k11.AsyncFunctionDef, _ast_k11.ClassDef)):
                return 1 if node.name == target_name else 0
            # 無名 scope 節點（lambda／推導式）：整個子樹不進入。
            if isinstance(node, _SCOPE_BOUNDARY_TYPES_K11):
                return 0

            count = 0
            if isinstance(node, _ast_k11.Name):
                if node.id == target_name and isinstance(node.ctx, (_ast_k11.Store, _ast_k11.Del)):
                    count += 1
            elif isinstance(node, (_ast_k11.Import, _ast_k11.ImportFrom)):
                for alias in node.names:
                    bound = alias.asname if alias.asname else alias.name.split(".")[0]
                    if bound == target_name:
                        count += 1
            elif isinstance(node, _ast_k11.ExceptHandler):
                if node.name == target_name:
                    count += 1

            for child in _ast_k11.iter_child_nodes(node):
                count += _walk_module_scope_count_k11(child, target_name)
            return count

        def _count_module_level_lane_bindings_k11(module_node) -> int:
            return _walk_module_scope_count_k11(module_node, "_LANE_TO_PROOF")

        def _lane_bound_in_table_k11(table) -> bool:
            try:
                sym = table.lookup("_LANE_TO_PROOF")
            except KeyError:
                return False
            return bool(
                sym.is_assigned() or sym.is_parameter() or sym.is_namespace() or sym.is_imported()
            )

        def _lane_bound_in_any_nested_k11(table) -> bool:
            for child in table.get_children():
                if _lane_bound_in_table_k11(child) or _lane_bound_in_any_nested_k11(child):
                    return True
            return False

        _self_src_k11 = Path(__file__).read_text(encoding="utf-8")
        _module_ast_tree_k11 = _ast_k11.parse(_self_src_k11, filename=str(Path(__file__)))
        _module_ast_count_k11 = _count_module_level_lane_bindings_k11(_module_ast_tree_k11)
        _module_table_k11 = _symtable_k11.symtable(_self_src_k11, str(Path(__file__)), "exec")
        _module_bound_k11 = _lane_bound_in_table_k11(_module_table_k11)
        _nested_bound_k11 = _lane_bound_in_any_nested_k11(_module_table_k11)
        _lane_ast_ok_k11 = (
            _module_ast_count_k11 == 1
            and _module_bound_k11
            and not _nested_bound_k11
        )
        fcheck("F-K11-AST-SHADOW-GUARD _LANE_TO_PROOF 防線三層：L1＝F-K11-IMPORT-EXACT-MAP（import 終值/"
               "容器型別/值型別/.get 活物件四布林）＋PRO-LOCK 逐鍵＋L2＝symtable 巢狀 scope 零綁定"
               "（shadow 完備防線）＋L3＝module-scope 綁定計數啟發式（>1 必紅；=1 不宣稱構式完備）",
               _lane_ast_ok_k11,
               f"module_ast_count={_module_ast_count_k11} module_bound={_module_bound_k11} nested_bound={_nested_bound_k11}")

        # Fix 2：014 binding — sharp_claim 不在台詞 → WARN（不靠 new_answer.quote 繞過）
        _claim_r3 = "原來不開口才是真正的尊重"
        _r_014_no_script = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            sharp_claim=_claim_r3,
            new_answer={"quote": _claim_r3, "source": "訪談"},
        )), "r3_014_no_script.yaml")
        fcheck("F-R3-014-BINDING new_answer.quote==sharp_claim 但台詞空 → 014 不觸發（骨架跳過）",
               "[014]" not in _r_014_no_script[1], _r_014_no_script[1])

        # sharp_claim 在 new_answer.quote 但不在台詞 → 014 WARN（quote 不可替代台詞）
        _r_014_in_quote_only = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            sharp_claim=_claim_r3,
            new_answer={"quote": _claim_r3, "source": "訪談"},
        ), scenes=[{"台詞": "台詞裡完全沒有那句話，只有別的內容。"}]), "r3_014_quote_only.yaml")
        fcheck("F-R3-014-BINDING sharp_claim 只在 new_answer.quote 不在台詞 → 014 觸發 WARN",
               "[014]" in _r_014_in_quote_only[1], _r_014_in_quote_only[1])

        # sharp_claim 直接在台詞 → PASS（正常路徑）
        _r_014_in_script = chk_c22_offpro_angle(_mk_angle_data(stub=_mk_stub(
            sharp_claim=_claim_r3,
            new_answer={"quote": _claim_r3, "source": "訪談"},
        ), scenes=[{"台詞": f"今天我想跟你說：{_claim_r3}，這是我的核心觀點。"}]), "r3_014_in_script.yaml")
        fcheck("F-R3-014-BINDING sharp_claim 在台詞 → PASS",
               "[014]" not in _r_014_in_script[1], _r_014_in_script[1])

        # Fix 3：C-offpro-cta-policy 掃 top-level cta / caption
        _blocked_cta_field = [
            (Path("s1.yaml"), {"content_axis": "offpro", "cta_offer_scope": "none",
                               "cta": "有興趣可以私訊我"}),
        ]

        _blocked_caption = [
            (Path("s1.yaml"), {"content_axis": "offpro", "cta_offer_scope": "none",
                               "caption": "LINE 我拿資料"}),
        ]

        # platform_variants.*.cta 含私訊 → WARN
        _blocked_pv = [
            (Path("s1.yaml"), {"content_axis": "offpro", "cta_offer_scope": "none",
                               "platform_variants": {"IG": {"cta": "可以私訊我喔"}}}),
        ]

        # script_method 欄仍不掃（false-positive 防護）
        _safe_script_method = [
            (Path("s1.yaml"), {"content_axis": "offpro", "cta_offer_scope": "self_check",
                               "script_method": {"chxp_v1": {"four_materials": {"old_answer": {"why_reasonable": "感情諮詢書籍鼓勵開口"}}}}
                               }),
            (Path("s2.yaml"), {"content_axis": "offpro", "cta_offer_scope": "save_share"}),
            (Path("s3.yaml"), {"content_axis": "offpro", "cta_offer_scope": "discussion_prompt"}),
        ]

        # Fix 4：_is_skeleton_mode 吃 _is_placeholder — [填：...] title 算 skeleton
        _skel_fill_yamls = [
            (None, {"title": "[填：請填寫標題]", "content_axis": "offpro"}),
            (None, {"title": "[填：第二支]", "content_axis": "offpro"}),
        ]
        fcheck("F-R3-SKELETON-MODE-FILL-TITLE [填：...] title → is_skeleton=True",
               _is_skeleton_mode(_skel_fill_yamls), f"count={sum(1 for _,d in _skel_fill_yamls if isinstance(d,dict))}")

        # 一般已填 title 不算 skeleton
        _real_yamls = [
            (None, {"title": "我不說話不代表我同意", "content_axis": "offpro"}),
        ]
        fcheck("F-R3-SKELETON-MODE-REAL-TITLE 真實標題 → is_skeleton=False",
               not _is_skeleton_mode(_real_yamls), "real title")

        # Fix 5：per-script offpro CTA scope 缺填 → WARN（per-script）
        _missing_scope = [
            (Path("s1.yaml"), {"content_axis": "offpro"}),  # 無 cta_offer_scope
        ]

        # Fix 6：content_axis lower-normalize — "Professional"（首字大寫）不誤殺
        _upper_axis = {"content_axis": "Professional", "lane": "professional"}
        _c_axis_norm = str(_upper_axis.get("content_axis", "") or "").strip().lower()
        fcheck("F-R3-CONTENT-AXIS-LOWER 'Professional' lower-normalize → 'professional'",
               _c_axis_norm == "professional", f"normalized={_c_axis_norm!r}")

        # ── R4 fixtures（2026-06-24）──

        # Fix 1：top-level cta dict 掃 message / keyword
        _blocked_cta_msg = [
            (Path("s1.yaml"), {"content_axis": "offpro", "cta_offer_scope": "none",
                               "cta": {"message": "有問題可以私訊我"}}),
        ]

        _blocked_cta_kw = [
            (Path("s1.yaml"), {"content_axis": "offpro", "cta_offer_scope": "none",
                               "cta": {"keyword": "LINE 我"}}),
        ]

        # Fix 2：_should_check_offpro_leak lower-normalize — "Offpro"（首字大寫）正確觸發
        _r_leak_upper = _should_check_offpro_leak({"content_axis": "Offpro"})
        fcheck("F-R4-LEAK-LOWER 'Offpro' lower-normalize → True（觸發洩漏檢查）",
               _r_leak_upper is True, f"result={_r_leak_upper}")

        _r_leak_pro = _should_check_offpro_leak({"content_axis": "Professional"})
        fcheck("F-R4-LEAK-LOWER 'Professional' lower-normalize → False（不觸發）",
               _r_leak_pro is False, f"result={_r_leak_pro}")

        # Fix 3：死斷言 or True 已清，驗 hash 確實因 proof_mode 有無而不同（已在 R3 Fix 1 段驗）

        # ── end F-C22-ANGLE ──

        # ── F-V2-012B：美容業主脆文 md 醫療詞掃描（2026-07-07 W2 品管工單）──
        print("[F-V2-012B] 美容脆文 md 醫療詞掃描驗收")
        import tempfile as _tf_med

        def _make_threads_dir(threads_body: str | None, owner_for_name: str = "test"):
            _d = Path(_tf_med.mkdtemp())
            if threads_body is not None:
                (_d / "threads_test_14.md").write_text(threads_body, encoding="utf-8")
            return _d

        _clean_threads = (
            "## Threads 01\n主題：把自己排第一\n\n"
            "清單永遠補不完，先把自己那條寫上去。\n\n#自我對話 #生活觀察\n"
        )
        _dirty_threads = (
            "## Threads 01\n主題：痘疤保養\n\n"
            "很多人痘疤反覆，其實是沒分清波動期，這時候更要抗發炎、加強修復。\n\n#護膚\n"
        )
        # (a) 乾淨脆文 + 昀臻 → PASS
        _d_clean = _make_threads_dir(_clean_threads)
        _r_med_a = chk_v2_012b_threads_med_words(_d_clean, "昀臻")
        fcheck("F-V2-012B-a 乾淨脆文 md + 昀臻 → PASS",
               _r_med_a[0] == "PASS", _r_med_a[1])
        # (b) 含醫療詞脆文 + 昀臻 → FAIL（發炎/修復 命中）
        _d_dirty = _make_threads_dir(_dirty_threads)
        _r_med_b = chk_v2_012b_threads_med_words(_d_dirty, "昀臻")
        fcheck("F-V2-012B-b 含『發炎/修復』脆文 md + 昀臻 → FAIL",
               _r_med_b[0] == "FAIL" and ("發炎" in _r_med_b[1] or "修復" in _r_med_b[1]), _r_med_b[1])
        # (c) 含醫療詞脆文 + 非美容業主（仲豪）→ PASS 跳過（不誤殺其他行業）
        _r_med_c = chk_v2_012b_threads_med_words(_d_dirty, "仲豪")
        fcheck("F-V2-012B-c 含醫療詞脆文 + 非美容業主 → PASS 跳過",
               _r_med_c[0] == "PASS" and "跳過" in _r_med_c[1], _r_med_c[1])
        # (d) 美容業主但無脆文 md → WARN（V2-007 另驗存在性）
        _d_empty = _make_threads_dir(None)
        _r_med_d = chk_v2_012b_threads_med_words(_d_empty, "溫蒂")
        fcheck("F-V2-012B-d 美容業主無脆文 md → WARN（非誤 PASS）",
               _r_med_d[0] == "WARN", _r_med_d[1])

        # ── F-V2-008-F1：raw canonical 多格式 parser／沉默盲區 fixtures ──
        print("[F-V2-008-F1] 已用題目 parser／loader／狀態優先級驗收")
        import tempfile as _tf_v2008

        _v2008_fixture_root = (
            Path(__file__).resolve().parent / "fixtures_v2008_titleparse"
        )
        _v2008_matrix_path = _v2008_fixture_root / "matrix.json"
        _v2008_manifest_path = _v2008_fixture_root / "manifest.json"
        try:
            _v2008_matrix = json.loads(_v2008_matrix_path.read_text(encoding="utf-8"))
            _v2008_manifest = json.loads(_v2008_manifest_path.read_text(encoding="utf-8"))
            fcheck("F-V2-008-F1-00 matrix/manifest JSON 可解析", True)
        except Exception as _v2008_fixture_error:
            _v2008_matrix = {"parser_cases": [], "loader_cases": [], "integration_cases": [], "similarity_cases": []}
            _v2008_manifest = {"matrix": {}, "files": [], "case_ids": []}
            fcheck("F-V2-008-F1-00 matrix/manifest JSON 可解析", False, str(_v2008_fixture_error))

        _matrix_sha = hashlib.sha256(_v2008_matrix_path.read_bytes()).hexdigest() if _v2008_matrix_path.exists() else "missing"
        fcheck(
            "F-V2-008-F1-01 matrix SHA 鎖",
            _matrix_sha == _v2008_manifest.get("matrix", {}).get("sha256"),
            _matrix_sha,
        )
        _manifest_file_ok = True
        _manifest_file_detail = []
        for _entry in _v2008_manifest.get("files", []):
            _fixture_path = _v2008_fixture_root / _entry.get("path", "")
            _actual_sha = hashlib.sha256(_fixture_path.read_bytes()).hexdigest() if _fixture_path.is_file() else "missing"
            if _actual_sha != _entry.get("sha256"):
                _manifest_file_ok = False
                _manifest_file_detail.append(f"{_entry.get('path')}={_actual_sha}")
        fcheck("F-V2-008-F1-02 case file SHA 全鎖", _manifest_file_ok, ";".join(_manifest_file_detail))

        _matrix_case_ids = [
            case["case_id"]
            for group in ("parser_cases", "loader_cases", "integration_cases", "similarity_cases")
            for case in _v2008_matrix.get(group, [])
        ]
        fcheck(
            "F-V2-008-F1-03 case IDs 完整且唯一",
            len(_matrix_case_ids) == len(set(_matrix_case_ids))
            and _matrix_case_ids == _v2008_manifest.get("case_ids", []),
            repr(_matrix_case_ids),
        )

        _v2008_raw_by_case = {}
        for _case in _v2008_matrix.get("parser_cases", []):
            _raw = (_v2008_fixture_root / _case["path"]).read_text(encoding="utf-8")
            _v2008_raw_by_case[_case["case_id"]] = _raw
            _actual = _v2008_parse_used_titles(_raw)
            _expected = _case["expected"]
            _actual_reasons = [row["reason"] for row in _actual["rejected_rows"]]
            _absent_ok = all(title not in _actual["titles"] for title in _expected.get("absent_titles", []))
            _case_ok = bool(
                _actual["format"] == _expected["format"]
                and _actual["parsed_rows"] == _expected["parsed_rows"]
                and _actual["titles"] == _expected["titles"]
                and _actual["empty_template"] is _expected["empty_template"]
                and _actual_reasons == _expected["rejected_reasons"]
                and _absent_ok
            )
            fcheck(
                f"F-V2-008-F1-P {_case['case_id']} exact",
                _case_ok,
                json.dumps({"actual": _actual, "expected": _expected}, ensure_ascii=False, sort_keys=True),
            )
            _crlf = _raw.replace("\n", "\r\n")
            _no_terminal_newline = _raw.rstrip("\r\n")
            _crlf_result = _v2008_parse_used_titles(_crlf)
            _noeol_result = _v2008_parse_used_titles(_no_terminal_newline)
            fcheck(
                f"F-V2-008-F1-EOL {_case['case_id']}",
                _crlf_result["titles"] == _actual["titles"]
                and _noeol_result["titles"] == _actual["titles"]
                and [r["reason"] for r in _crlf_result["rejected_rows"]] == _actual_reasons
                and [r["reason"] for r in _noeol_result["rejected_rows"]] == _actual_reasons,
            )

        for _case in _v2008_matrix.get("similarity_cases", []):
            _ratio = difflib.SequenceMatcher(None, _case["left"], _case["right"]).ratio()
            fcheck(
                f"F-V2-008-F1-RATIO {_case['case_id']}",
                (_ratio >= 0.65) is _case["expected_hit"],
                str(_ratio),
            )

        _v2008_original_owner_paths = OWNER_PREF_PATHS
        try:
            for _case in _v2008_matrix.get("loader_cases", []):
                _owner = "V2008FixtureOwner"
                with _tf_v2008.TemporaryDirectory() as _td:
                    _root = Path(_td)
                    if _case["mode"] == "unresolved":
                        OWNER_PREF_PATHS = {}
                    else:
                        OWNER_PREF_PATHS = {_owner: _root / "_fixture_pref.md"}
                        if _case["mode"] == "directory":
                            (_root / f"_{_owner}已用題目.md").mkdir()
                    _status, _detail = chk_v2_008_used_titles_dedup([], _owner)
                    _loader_ok = _status == _case["expected_status"] and _case["detail_contains"] in _detail
                    if _case.get("detail_excludes"):
                        _loader_ok = _loader_ok and _case["detail_excludes"] not in _detail
                    fcheck(f"F-V2-008-F1-L {_case['case_id']}", _loader_ok, f"{_status} {_detail}")

            for _case in _v2008_matrix.get("integration_cases", []):
                _owner = "V2008FixtureOwner"
                with _tf_v2008.TemporaryDirectory() as _td:
                    _root = Path(_td)
                    OWNER_PREF_PATHS = {_owner: _root / "_fixture_pref.md"}
                    if _case.get("loader_mode") != "missing":
                        (_root / f"_{_owner}已用題目.md").write_text(
                            _v2008_raw_by_case[_case["raw_case"]], encoding="utf-8"
                        )
                    _yamls = [
                        (
                            _root / "batch" / f"script_{idx + 1:02d}.yaml",
                            {"title": title, "scenes": [{"台詞": _case["dialogues"][idx]}]},
                        )
                        for idx, title in enumerate(_case["titles"])
                    ]
                    _status, _detail = chk_v2_008_used_titles_dedup(_yamls, _owner)
                    _integration_ok = _status == _case["expected_status"]
                    if _case.get("detail_contains"):
                        _integration_ok = _integration_ok and _case["detail_contains"] in _detail
                    if _case.get("detail_contains_all"):
                        _integration_ok = _integration_ok and all(
                            needle in _detail for needle in _case["detail_contains_all"]
                        )
                    fcheck(f"F-V2-008-F1-I {_case['case_id']}", _integration_ok, f"{_status} {_detail}")
        finally:
            OWNER_PREF_PATHS = _v2008_original_owner_paths

        # ── F-RCARD：退役批次圖卡欄位 fixtures（W2-C撤收 2026-07-14）──


        # ── F-K12：time_axis 選填參數化 fixtures（W4-K12 2026-07-16）──
        # 真值表 48 執行單位中屬「沙盤直呼 fixtures」的部分：P02-P04/N01-N31/C01/D01a。
        # P01（35 批 differential）/D01b（CLI byte-diff）/M01-M03（mutation）/R01（spike/
        # hermetic/F-CUTOVER/selftest）歸霸告紅綠 harness 親跑，不在此列。
        print("\n[F-K12] time_axis 選填參數化（duration_seconds/time_slots 批級宣告，60s 預設保留）")

        _k12_batch_key = "K12Fixture業主/01_腳本生產/K12Fixture批"
        _k12_today = _dt.date.today().isoformat()
        _k12_future = (_dt.date.today() + _dt.timedelta(days=1)).isoformat()

        def _k12_good_raw(duration=90, slots=None, batch_key=None):
            if slots is None:
                slots = ["0-15s", "15-30s", "30-45s", "45-60s", "60-75s", "75-90s"]
            bk = batch_key if batch_key is not None else _k12_batch_key
            return {
                "duration_seconds": duration,
                "time_slots": slots,
                "approved_by": "澤君",
                "approved_at": _k12_today,
                "approved_digest": _time_axis_canonical_digest(bk, duration, slots),
            }

        def _k12_mutate(recompute_digest=True, **overrides):
            """霸告令（紅綠回饋 2026-07-16）：mutation 反證要求 N 案「只違反被測那一條」，
            預設在套用 duration_seconds/time_slots 變異後，用同公式/同 batch_key 重算
            approved_digest，避免⑧ digest 關卡把⑦區間數學／④~⑥型別/格式檢查的失敗訊號
            遮蔽（若⑦等檢查被 mutation 拔除，digest 仍會獨立擋下 → 反證無效）。
            digest 專屬案（N31a 漂移／N31b replay）才需要 approved_digest 刻意不匹配，
            顯式傳 recompute_digest=False 或直接覆寫 approved_digest（覆寫時不重算）。
            """
            raw = dict(_k12_good_raw())
            raw.update(overrides)
            if recompute_digest and "approved_digest" not in overrides:
                raw["approved_digest"] = _time_axis_canonical_digest(
                    _k12_batch_key, raw["duration_seconds"], raw["time_slots"]
                )
            return raw

        # ── 合法基線自檢（先確認 mutation 前的基線本身合法，否則後面全案無意義）──
        _k12_good_axis, _k12_good_err = _resolve_time_axis_from_raw(_k12_good_raw(), _k12_batch_key)
        fcheck("F-K12-GOOD-BASELINE 未變異的合法宣告 → resolve 成功",
               _k12_good_axis is not None and _k12_good_err is None,
               f"axis={_k12_good_axis} err={_k12_good_err}")

        # ── P02-P04：合法宣告軸（沙盤直呼 chk_l1_001_schema/chk_l1_006_cta/chk_l1_000_time_axis）──
        # P02：90s 合法軸 7 段（N≠6，測段數硬鎖殘留，r2 殘掃）
        _k12_p02_slots = ["0-13s", "13-26s", "26-39s", "39-52s", "52-65s", "65-78s", "78-90s"]
        _k12_p02_raw = _k12_good_raw(duration=90, slots=_k12_p02_slots)
        _k12_p02_axis, _k12_p02_err = _resolve_time_axis_from_raw(_k12_p02_raw, _k12_batch_key)
        fcheck("F-K12-P02 90s/7段宣告合法 → resolve 成功、無 error",
               _k12_p02_axis is not None and _k12_p02_err is None,
               f"axis={_k12_p02_axis} err={_k12_p02_err}")
        if _k12_p02_axis is not None:
            _k12_p02_l1000 = chk_l1_000_time_axis(_k12_p02_axis, _k12_p02_err)
            fcheck("F-K12-P02 L1-000 PASS、detail 含 declared 7 段",
                   _k12_p02_l1000 is not None and _k12_p02_l1000[0] == "PASS"
                   and "7" in _k12_p02_l1000[1],
                   str(_k12_p02_l1000))
            _k12_p02_data = {"scenes": [
                {"timestamp": ts, "type": ("CTA" if i == len(_k12_p02_slots) - 1 else "一般"),
                 "台詞_阿奇": ("留言告訴我你的想法" if i == len(_k12_p02_slots) - 1 else f"第{i}段測試台詞")}
                for i, ts in enumerate(_k12_p02_slots)
            ]}
            _k12_p02_l1001 = chk_l1_001_schema(_k12_p02_data, "p02.yaml", expected_slots=_k12_p02_axis["time_slots"])
            fcheck("F-K12-P02 L1-001 PASS、detail 段數=7",
                   _k12_p02_l1001[0] == "PASS" and "7" in _k12_p02_l1001[1], str(_k12_p02_l1001))
            _k12_p02_l1006 = chk_l1_006_cta(_k12_p02_data, "p02.yaml",
                                             cta_slot=_k12_p02_axis["time_slots"][-1]["timestamp"])
            fcheck("F-K12-P02 L1-006 PASS（末段 CTA 含引導語）", _k12_p02_l1006[0] == "PASS", str(_k12_p02_l1006))

        # P03：60s 標準軸（顯式六段、五鍵齊）— 判定與缺省批同，L1-000 多一列＝申報差異
        _k12_p03_slots = [s["timestamp"] for s in _load_l0_time_slots()]
        _k12_p03_raw = _k12_good_raw(duration=60, slots=_k12_p03_slots)
        _k12_p03_axis, _k12_p03_err = _resolve_time_axis_from_raw(_k12_p03_raw, _k12_batch_key)
        fcheck("F-K12-P03 60s 標準六段宣告合法 → resolve 成功",
               _k12_p03_axis is not None and _k12_p03_err is None,
               f"axis={_k12_p03_axis} err={_k12_p03_err}")
        if _k12_p03_axis is not None:
            _k12_p03_data = {"scenes": [{"timestamp": ts, "type": "一般", "台詞_阿奇": "測試"}
                                          for ts in _k12_p03_slots]}
            _k12_p03_l1001_declared = chk_l1_001_schema(_k12_p03_data, "p03.yaml",
                                                          expected_slots=_k12_p03_axis["time_slots"])
            _k12_p03_l1001_default = chk_l1_001_schema(_k12_p03_data, "p03.yaml")
            fcheck("F-K12-P03 L1-001 宣告分支與缺省分支判定同（PASS/PASS，60s 六段數值相同）",
                   _k12_p03_l1001_declared[0] == "PASS" and _k12_p03_l1001_default[0] == "PASS",
                   f"declared={_k12_p03_l1001_declared} default={_k12_p03_l1001_default}")

        # P04：合法上界正例 N=24、duration=3600
        _k12_p04_slots = [f"{i*150}-{(i+1)*150}s" for i in range(24)]
        _k12_p04_raw = _k12_good_raw(duration=3600, slots=_k12_p04_slots)
        _k12_p04_axis, _k12_p04_err = _resolve_time_axis_from_raw(_k12_p04_raw, _k12_batch_key)
        fcheck("F-K12-P04 N=24/duration=3600 上界正例 → resolve 成功",
               _k12_p04_axis is not None and _k12_p04_err is None, f"err={_k12_p04_err}")

        # ── N01-N31：非法宣告（fail-closed，逐案斷言 FAIL + 訊息前綴 + 分支專屬 reason substring）──
        # 霸告紅綠回饋（2026-07-16）：分支 substring 釘死「被測的是哪一條檢查」——若 mutation 反證
        # 拔掉某條檢查後 detail 仍含指定 substring，代表反證沒有命中該檢查（已被別條檢查或⑧digest
        # 遮蔽）；substring 消失才代表該條檢查是唯一擋下這案的原因，反證才有鑑別力。
        _k12_n_cases = []  # (case_id, raw_value, batch_key_override_or_None, expected_substring_or_None)

        _k12_n_cases.append(("N01-null", None, None, None))
        _k12_n_cases.append(("N02a-str", "not-a-mapping", None, None))
        _k12_n_cases.append(("N02b-list", ["not", "a", "mapping"], None, None))
        for _missing_key in sorted(_TIME_AXIS_REQUIRED_KEYS):
            _raw = dict(_k12_good_raw())
            del _raw[_missing_key]
            _k12_n_cases.append((f"N03-07-missing-{_missing_key}", _raw, None, "缺鍵"))
        _k12_n_cases.append(("N08-unknown-key", _k12_mutate(extra_field="x"), None, "未知鍵"))
        _k12_n_cases.append(("N09-duration-bool", _k12_mutate(duration_seconds=True), None,
                              "duration_seconds 型別非 int 或超出"))
        _k12_n_cases.append(("N10-duration-0", _k12_mutate(duration_seconds=0), None,
                              "duration_seconds 型別非 int 或超出"))
        _k12_n_cases.append(("N11-duration-neg", _k12_mutate(duration_seconds=-1), None,
                              "duration_seconds 型別非 int 或超出"))
        _k12_n_cases.append(("N12-duration-over", _k12_mutate(duration_seconds=3601), None,
                              "duration_seconds 型別非 int 或超出"))
        _k12_n_cases.append(("N13-slots-notlist", _k12_mutate(time_slots="0-90s"), None, "段數不在 2~24"))
        _k12_n_cases.append(("N14-slots-elem-notstr", _k12_mutate(time_slots=["0-45s", 45]), None, None))
        _k12_n_cases.append(("N15-slots-empty", _k12_mutate(time_slots=[]), None, "段數不在 2~24"))
        _k12_n_cases.append(("N16-slots-n1", _k12_mutate(time_slots=["0-90s"]), None, "段數不在 2~24"))
        _k12_n_cases.append(("N17-slots-n25", _k12_mutate(time_slots=[f"seg{i}" for i in range(25)]), None,
                              "段數不在 2~24"))
        _k12_n_cases.append(("N18-leading-zero", _k12_mutate(time_slots=["0-3s", "03-12s"]), None, "段格式錯誤"))
        _k12_n_cases.append(("N19-unicode-digit", _k12_mutate(time_slots=["0-3s", "０-３ｓ"]), None, "段格式錯誤"))
        _k12_n_cases.append(("N20-trailing-ws", _k12_mutate(time_slots=["0-3s", "3-12s "]), None, "段格式錯誤"))
        _k12_n_cases.append(("N21-zero-length",
                              _k12_mutate(duration_seconds=10, time_slots=["0-5s", "5-5s", "5-10s"]),
                              None, "零長或逆序"))
        _k12_n_cases.append(("N22-overlap",
                              _k12_mutate(duration_seconds=15, time_slots=["0-10s", "5-15s"]),
                              None, "不連續"))
        _k12_n_cases.append(("N23-gap",
                              _k12_mutate(duration_seconds=25, time_slots=["0-10s", "15-25s"]),
                              None, "不連續"))
        _k12_n_cases.append(("N24-reverse",
                              _k12_mutate(duration_seconds=30, time_slots=["0-10s", "20-30s", "10-20s"]),
                              None, "不連續"))
        _k12_n_cases.append(("N25-first-nonzero",
                              _k12_mutate(duration_seconds=15, time_slots=["5-10s", "10-15s"]),
                              None, "首段未從 0"))
        _k12_n_cases.append(("N26-last-ne-duration",
                              _k12_mutate(duration_seconds=20, time_slots=["0-10s", "10-15s"]),
                              None, "末段 end"))
        _k12_n_cases.append(("N27-approved-by-wrong", _k12_mutate(approved_by="別人"), None, None))
        _k12_n_cases.append(("N28-fake-date", _k12_mutate(approved_at="2026-13-40"), None, None))
        _k12_n_cases.append(("N29-date-object", _k12_mutate(approved_at=_dt.date(2026, 7, 16)), None, None))
        _k12_n_cases.append(("N30-future-date", _k12_mutate(approved_at=_k12_future), None, None))

        # N31a：漂移（改 slots、digest 刻意不重算 → 仍是原 6 段的，故意跟新 slots 對不上）
        _k12_n31a_raw = _k12_mutate(time_slots=["0-30s", "30-60s", "60-90s"], recompute_digest=False)
        _k12_n_cases.append(("N31a-digest-drift", _k12_n31a_raw, None, "宣告內容與核准摘要不符"))

        # N31b：replay（他批 digest 照搬 — 不同業主、相同批名，r5 要求）
        _k12_owner_a_key = "阿奇/01_腳本生產/第14批"
        _k12_owner_b_key = "瑞祥/01_腳本生產/第14批"
        _k12_replay_slots = ["0-45s", "45-90s"]
        _k12_replay_digest_for_b = _time_axis_canonical_digest(_k12_owner_b_key, 90, _k12_replay_slots)
        _k12_n31b_raw = {
            "duration_seconds": 90,
            "time_slots": _k12_replay_slots,
            "approved_by": "澤君",
            "approved_at": _k12_today,
            "approved_digest": _k12_replay_digest_for_b,  # 瑞祥批的合法 digest，照搬到阿奇批
        }
        _k12_n_cases.append(("N31b-digest-replay", _k12_n31b_raw, _k12_owner_a_key, "宣告內容與核准摘要不符"))

        # N32：③ 恰五鍵混型鍵（出貨審 r1 P0）——unknown 集合同時含 int（YAML `7: x` 風格）
        # 與額外 str 鍵，裸 sorted() 舊版會拋 TypeError；驗 key=str 修法後仍 controlled FAIL。
        _k12_n32_raw = dict(_k12_good_raw())
        _k12_n32_raw[7] = "x"          # YAML `7: x` 風格的整數鍵
        _k12_n32_raw["額外欄位"] = "y"  # 與整數鍵同時存在，unknown 集合真正混型（str+int）
        _k12_n_cases.append(("N32-mixed-type-unknown-key", _k12_n32_raw, None, "未知鍵"))

        for _case_id, _raw, _bk_override, _expect_substr in _k12_n_cases:
            _bk = _bk_override if _bk_override is not None else _k12_batch_key
            # 出貨審 r1 P0：混型鍵舊版會拋例外，這裡包 try/except 讓任何未預期例外都變成
            # 「controlled FAIL」而非讓整個 --fixtures 進程崩潰（斷言本身也驗證絕不拋例外）。
            try:
                _axis, _err = _resolve_time_axis_from_raw(_raw, _bk)
                _raised = None
            except Exception as _k12_exc:
                _axis, _err, _raised = None, None, _k12_exc
            fcheck(f"F-K12-{_case_id} FAIL（axis=None、error 含「time_axis 宣告非法」前綴、絕不拋例外）",
                   _raised is None and _axis is None and _err is not None
                   and _err.startswith("time_axis 宣告非法—"),
                   f"axis={_axis} err={_err} raised={_raised!r}")
            if _expect_substr is not None:
                fcheck(f"F-K12-{_case_id} detail 含分支專屬 reason「{_expect_substr}」（釘對分支、非⑧digest遮蔽）",
                       _err is not None and _expect_substr in _err,
                       f"err={_err}")

        # ── L1-000 批級 check：缺省零註冊 vs 宣告分支 ──
        _k12_l1000_absent = chk_l1_000_time_axis(None, None)
        fcheck("F-K12-L1000-ABSENT 鍵缺席 → None（不得註冊）",
               _k12_l1000_absent is None, str(_k12_l1000_absent))
        _k12_l1000_fail = chk_l1_000_time_axis(None, "time_axis 宣告非法—測試錯誤")
        fcheck("F-K12-L1000-ERROR 宣告非法 → FAIL",
               _k12_l1000_fail is not None and _k12_l1000_fail[0] == "FAIL", str(_k12_l1000_fail))
        _k12_l1000_pass = chk_l1_000_time_axis(_k12_p02_axis, None)
        fcheck("F-K12-L1000-PASS 宣告合法 → PASS",
               _k12_l1000_pass is not None and _k12_l1000_pass[0] == "PASS", str(_k12_l1000_pass))

        # ── C01：CTA 在末段判定（沿用 P02 已驗證合法的 90s/7段 axis）──
        _k12_c01_axis = _k12_p02_axis
        if _k12_c01_axis is not None:
            _k12_c01_cta_slot = _k12_c01_axis["time_slots"][-1]["timestamp"]
            _k12_c01a_data = {"scenes": [{"timestamp": _k12_c01_cta_slot, "type": "CTA",
                                           "台詞_阿奇": "歡迎留言告訴我你的想法"}]}
            _k12_c01a = chk_l1_006_cta(_k12_c01a_data, "c01a.yaml", cta_slot=_k12_c01_cta_slot)
            fcheck("F-K12-C01a CTA 在末段（含引導語）→ PASS", _k12_c01a[0] == "PASS", str(_k12_c01a))

            # 出貨審 r1 形修：CTA 關鍵詞放在「非末段」（首段），末段（=cta_slot）本身無引導語。
            # 若函式錯誤地整段掃描全文找關鍵詞（而非只看 scenes[-1]）會誤判 PASS；
            # 正確實作只看末段 → 應 FAIL，藉此釘死 cta_slot 參數真的只檢查末段。
            _k12_c01b_data = {"scenes": [
                {"timestamp": _k12_p02_slots[0], "type": "一般", "台詞_阿奇": "留言告訴我你的想法"},
                {"timestamp": _k12_c01_cta_slot, "type": "CTA", "台詞_阿奇": "謝謝觀看下次見"},
            ]}
            _k12_c01b = chk_l1_006_cta(_k12_c01b_data, "c01b.yaml", cta_slot=_k12_c01_cta_slot)
            fcheck("F-K12-C01b CTA 關鍵詞在非末段、末段無引導語 → FAIL（釘 cta_slot 只看末段）",
                   _k12_c01b[0] == "FAIL", str(_k12_c01b))

        # ── D01a：缺省差分 fixture（鍵缺席 → 零註冊 + chk 函式逐字零變）──
        import tempfile as _k12_tempfile
        with _k12_tempfile.TemporaryDirectory() as _k12_tmp:
            _k12_empty_batch_dir = Path(_k12_tmp) / "某業主" / "01_腳本生產" / "第99批"
            _k12_empty_batch_dir.mkdir(parents=True, exist_ok=True)
            _k12_d01a_axis1, _k12_d01a_err1 = _resolve_batch_time_axis(_k12_empty_batch_dir)
            fcheck("F-K12-D01a 無 _batch_flags.yml → (None, None) 缺省零註冊",
                   _k12_d01a_axis1 is None and _k12_d01a_err1 is None,
                   f"axis={_k12_d01a_axis1} err={_k12_d01a_err1}")

            (_k12_empty_batch_dir / "_batch_flags.yml").write_text("batch_profile: hybrid\n", encoding="utf-8")
            _k12_d01a_axis2, _k12_d01a_err2 = _resolve_batch_time_axis(_k12_empty_batch_dir)
            fcheck("F-K12-D01a 有 _batch_flags.yml 但無 time_axis 鍵 → (None, None) 缺省零註冊",
                   _k12_d01a_axis2 is None and _k12_d01a_err2 is None,
                   f"axis={_k12_d01a_axis2} err={_k12_d01a_err2}")

            _k12_d01a_l1000 = chk_l1_000_time_axis(_k12_d01a_axis2, _k12_d01a_err2)
            fcheck("F-K12-D01a L1-000 缺省 → None（all_results 無此列）",
                   _k12_d01a_l1000 is None, str(_k12_d01a_l1000))

        # ── 缺省差分：chk_l1_001_schema / chk_l1_006_cta / run_per_file_checks 不傳新參數 = 逐字零變 ──
        _k12_default_slots = [s["timestamp"] for s in _load_l0_time_slots()]
        _k12_default_data = {"scenes": [{"timestamp": ts, "type": "一般", "台詞_阿奇": "測試"}
                                          for ts in _k12_default_slots]}
        _k12_default_data["scenes"][-1]["type"] = "CTA"
        _k12_default_data["scenes"][-1]["台詞_阿奇"] = "歡迎留言告訴我"

        _r_default_l1001 = chk_l1_001_schema(_k12_default_data, "default.yaml")
        _r_explicit_none_l1001 = chk_l1_001_schema(_k12_default_data, "default.yaml", expected_slots=None)
        fcheck("F-K12-DEFAULT-DIFF chk_l1_001_schema 不傳參數 == 顯式傳 None（逐字零變）",
               _r_default_l1001 == _r_explicit_none_l1001,
               f"default={_r_default_l1001} explicit_none={_r_explicit_none_l1001}")
        fcheck("F-K12-DEFAULT-DIFF chk_l1_001_schema PASS 字面保留「6 段時間軸齊全且順序正確」",
               _r_default_l1001[0] == "PASS" and "6 段時間軸齊全且順序正確" in _r_default_l1001[1],
               str(_r_default_l1001))

        _r_default_l1006 = chk_l1_006_cta(_k12_default_data, "default.yaml")
        _r_explicit_none_l1006 = chk_l1_006_cta(_k12_default_data, "default.yaml", cta_slot=None)
        fcheck("F-K12-DEFAULT-DIFF chk_l1_006_cta 不傳參數 == 顯式傳 None（逐字零變）",
               _r_default_l1006 == _r_explicit_none_l1006,
               f"default={_r_default_l1006} explicit_none={_r_explicit_none_l1006}")
        fcheck("F-K12-DEFAULT-DIFF chk_l1_006_cta PASS（60s 缺省末段 CTA 判定不變）",
               _r_default_l1006[0] == "PASS", str(_r_default_l1006))

        # run_per_file_checks 不傳 time_axis/time_axis_error = 行為零變（外部 caller 零變契約）
        _k12_rpf_default = run_per_file_checks(Path("批次資料夾/default.yaml"), _k12_default_data, "阿奇")
        _k12_rpf_explicit_none = run_per_file_checks(
            Path("批次資料夾/default.yaml"), _k12_default_data, "阿奇", time_axis=None, time_axis_error=None,
        )
        fcheck("F-K12-DEFAULT-DIFF run_per_file_checks 不傳 == 顯式傳雙 None（逐字零變）",
               _k12_rpf_default == _k12_rpf_explicit_none,
               f"len_default={len(_k12_rpf_default)} len_explicit={len(_k12_rpf_explicit_none)}")

        # ── run_per_file_checks 錯誤通道 cascade（Delta D：time_axis_error 在求值前攔截）──
        _k12_cascade_results = run_per_file_checks(
            Path("批次資料夾/cascade.yaml"), _k12_default_data, "阿奇",
            time_axis=None, time_axis_error="time_axis 宣告非法—測試錯誤",
        )
        _k12_cascade_map = {cid: (status, detail) for cid, status, _fn, detail in _k12_cascade_results}
        fcheck("F-K12-CASCADE L1-001 FAIL「time_axis 非法、時間軸無法驗」（求值前攔截）",
               _k12_cascade_map.get("L1-001") == ("FAIL", "time_axis 非法、時間軸無法驗"),
               str(_k12_cascade_map.get("L1-001")))
        fcheck("F-K12-CASCADE L1-006 FAIL「time_axis 非法、時間軸無法驗」（求值前攔截）",
               _k12_cascade_map.get("L1-006") == ("FAIL", "time_axis 非法、時間軸無法驗"),
               str(_k12_cascade_map.get("L1-006")))

        # ════════════════════════════════════════════
        # F-CXP-R6：r6 凍結清單四個新檢查的定向 fixtures（P13，2026-08-13）
        #   Codex 三審非阻擋建議：「本次四個新檢查沒有定向 fixtures，無法替上述缺陷背書」→ 本組補齊。
        #   四件對應 Codex 實測到的四個假通過/假失敗案例，全部鎖成回歸測試。
        # ════════════════════════════════════════════
        print("\n[F-CXP-R6] r6 新檢查定向 fixtures（藏鏡人配額／酸度／流量密碼去重）")

        def _r6_scene(ts, typ, line, mirror=None, reply=None, sour=None):
            sc = {"timestamp": ts, "type": typ, "台詞": line}
            if mirror is not None:
                sc["藏鏡人"] = mirror
            if reply is not None:
                sc["藏鏡人接球"] = reply
            if sour is not None:
                sc["藏鏡人酸度"] = sour
            return sc

        def _r6_doc(scenes, duration=None, traffic=None):
            d = {"script_id": "f_cxp_r6", "owner": "瑞祥", "scenes": scenes,
                 "schema_check": {"禁虛構": True}}
            if duration is not None:
                d["duration"] = duration
            if traffic is not None:
                d["schema_check"]["流量密碼"] = traffic
            return d

        # ① 藏鏡人 0 點 → FAIL（結構下限，取代舊 >=2 判定）
        _f_r6_1 = _r6_doc([
            _r6_scene("0-3s", "Hook", "開場金句"),
            _r6_scene("25-40s", "案例轉折", "案例段"),
        ])
        _s1, _d1 = chk_l1_003_mirror(_f_r6_1, "f_r6_1.yaml")
        fcheck("F-CXP-R6-1 藏鏡人 0 點 → FAIL（結構下限 1）",
               _s1 == "FAIL" and "0" in _d1, f"got={_s1}; {_d1[:90]}")

        # ② 25 秒配額測試（r12 TG19773 連動更新：新表 ≤25s 上限＝2）
        #    原 fixture「25s 宣告 2 點 → WARN」在新表下 2 點已屬合法配額內 → 期望值改 PASS，
        #    並**加一件** 25s 宣告 3 點 → WARN，把「超配額仍只 WARN 不擋批」的回歸保護補回來
        #    （淨效果：保護強度不減反增，舊件轉正例、新件接手負例）。
        #    Codex 原病徵仍鎖著：≤25s 不得被「假算超額」FAIL、頂層 block 要讀得到。
        _f_r6_2 = _r6_doc([
            _r6_scene("0-3s", "Hook", "開場", "第一個藏鏡人", "業主接球一", "S1"),
            _r6_scene("12-25s", "案例轉折", "案例", "第二個藏鏡人", "業主接球二", "S2"),
        ], duration="25s")
        _s2, _d2 = chk_l1_003_mirror(_f_r6_2, "f_r6_2.yaml")
        fcheck("F-CXP-R6-2 25s 宣告 2 點 → PASS（TG19773 新表 ≤25s 上限＝2，配額內）",
               _s2 == "PASS", f"got={_s2}; {_d2[:110]}")

        # ②b 25 秒宣告 3 點 → WARN（超新表上限 2；品質提示，永不 FAIL、不擋批）
        _f_r6_2b = _r6_doc([
            _r6_scene("0-3s", "Hook", "開場", "藏鏡人一", "接球一", "S1"),
            _r6_scene("12-25s", "案例轉折", "案例", "藏鏡人二", "接球二", "S2"),
            _r6_scene("20-25s", "收尾", "收束", "藏鏡人三", "接球三", "S1"),
        ], duration="25s")
        _s2b, _d2b = chk_l1_003_mirror(_f_r6_2b, "f_r6_2b.yaml")
        fcheck("F-CXP-R6-2b 25s 宣告 3 點 → WARN（超新表配額 2，不 FAIL、不擋批）",
               _s2b == "WARN" and "配額" in _d2b, f"got={_s2b}; {_d2b[:110]}")

        # ③ 流量密碼 3 個垃圾字串 → FAIL（白名單命中數 0；舊法只 WARN 且 exit 0）
        _f_r6_3 = _r6_doc([
            _r6_scene("0-3s", "Hook", "開場", "藏鏡人", "接球", "S1"),
        ], traffic=["aaa", "bbb", "ccc"])
        _s3, _d3 = chk_l1_004_traffic(_f_r6_3, "f_r6_3.yaml")
        fcheck("F-CXP-R6-3 流量密碼 3 垃圾字串 → FAIL（白名單命中 0）",
               _s3 == "FAIL" and "命中 0" in _d3, f"got={_s3}; {_d3[:90]}")

        # ③b 同元素重複 3 次 → FAIL（去重後只算 1；Codex 原實測「三個真實感」直接 PASS）
        _f_r6_3b = _r6_doc([
            _r6_scene("0-3s", "Hook", "開場", "藏鏡人", "接球", "S1"),
        ], traffic=["真實感", "真實感", "真實感"])
        _s3b, _d3b = chk_l1_004_traffic(_f_r6_3b, "f_r6_3b.yaml")
        fcheck("F-CXP-R6-3b 流量密碼 3 個重複「真實感」→ FAIL（去重後 1）",
               _s3b == "FAIL" and "命中 1" in _d3b, f"got={_s3b}; {_d3b[:90]}")

        # ④ 3 個合法白名單元素 → PASS
        _f_r6_4 = _r6_doc([
            _r6_scene("0-3s", "Hook", "開場", "藏鏡人", "接球", "S1"),
        ], traffic=["真實感", "金錢", "緊迫感"])
        _s4, _d4 = chk_l1_004_traffic(_f_r6_4, "f_r6_4.yaml")
        fcheck("F-CXP-R6-4 流量密碼 3 白名單元素 → PASS",
               _s4 == "PASS" and "命中 3" in _d4, f"got={_s4}; {_d4[:90]}")

        # ⑤ L0 §1.5.2 可選三元素不計數（L0 :294「不是必填、不計數、不設配額」）
        _f_r6_5 = _r6_doc([
            _r6_scene("0-3s", "Hook", "開場", "藏鏡人", "接球", "S1"),
        ], traffic=["真實感", "金錢", "隨機/盲盒", "貼金"])
        _s5, _d5 = chk_l1_004_traffic(_f_r6_5, "f_r6_5.yaml")
        fcheck("F-CXP-R6-5 可選元素（隨機盲盒/貼金）不計入門檻 → FAIL（白名單僅 2）",
               _s5 == "FAIL" and "命中 2" in _d5 and "不計數" in _d5, f"got={_s5}; {_d5[:110]}")

        # ⑥ 酸度分佈 WARN（P9）：宣告 2 點全 S0/S1、無 S2 → WARN 不 FAIL
        _f_r6_6 = _r6_doc([
            _r6_scene("0-3s", "Hook", "開場", "藏鏡人一", "接球一", "S0"),
            _r6_scene("25-40s", "案例轉折", "案例", "藏鏡人二", "接球二", "S1"),
        ])
        _s6, _d6 = chk_l1_003_mirror(_f_r6_6, "f_r6_6.yaml")
        fcheck("F-CXP-R6-6 2 點皆無 S2 → WARN（非 FAIL；得標定稿 §5 偏離記錄）",
               _s6 == "WARN" and "S2" in _d6, f"got={_s6}; {_d6[:110]}")

        # ⑦ S2 超過 2 點 → WARN（品質提示，永不 FAIL）
        _f_r6_7 = _r6_doc([
            _r6_scene("0-3s", "Hook", "開場", "藏鏡人一", "接球一", "S2"),
            _r6_scene("25-40s", "案例轉折", "案例", "藏鏡人二", "接球二", "S2"),
            _r6_scene("52-60s", "CTA", "收尾", "藏鏡人三", "接球三", "S2"),
        ], duration="80s")
        _s7, _d7 = chk_l1_003_mirror(_f_r6_7, "f_r6_7.yaml")
        fcheck("F-CXP-R6-7 S2 共 3 點 → WARN（不 FAIL）",
               _s7 == "WARN" and "S2 共 3" in _d7, f"got={_s7}; {_d7[:110]}")

        # ⑧ 題目鎖收緊（P5）：占位／布林／否定值皆判未鎖，且非 dict 不拋例外
        #    r9 Q4：必填欄擴為七欄（+topic_id/+traffic_candidates），並加同批重複真題檢查。
        try:
            from topic_distributor import topic_lock_status as _tls, assert_topics_locked as _atl
            _lock_ok = {"topic_statement": "自己貼隔熱紙的隱形成本",
                        "topic_source": "情報池 TP-001", "topic_id": "TP-001",
                        "audience_scene": "新手車主選膜時",
                        "can_shoot": "自家車庫", "want_shoot": "願意講",
                        "traffic_candidates": ["成本", "反差"]}
            fcheck("F-CXP-R6-8a 七欄齊備真敘述 → 已鎖（r9 Q4 契約）",
                   _tls({"direction": "真題", "topic_lock": _lock_ok})[0], "")
            _lock_ph = dict(_lock_ok, topic_statement="[待填]")
            fcheck("F-CXP-R6-8b topic_statement=[待填] → 未鎖",
                   not _tls({"direction": "真題", "topic_lock": _lock_ph})[0], "")
            _lock_bool = dict(_lock_ok, topic_statement=True)
            fcheck("F-CXP-R6-8c topic_statement=布林 True → 未鎖",
                   not _tls({"direction": "真題", "topic_lock": _lock_bool})[0], "")
            _lock_neg = dict(_lock_ok, can_shoot="不能拍")
            fcheck("F-CXP-R6-8d can_shoot=「不能拍」→ 未鎖",
                   not _tls({"direction": "真題", "topic_lock": _lock_neg})[0], "")
            _nd_ok, _nd_missing = _tls("不是 dict")
            fcheck("F-CXP-R6-8e 非 dict item → 判未鎖且不拋例外",
                   (not _nd_ok) and bool(_nd_missing), f"{_nd_missing}")
            fcheck("F-CXP-R6-8f assert_topics_locked(非 list) → 未鎖不拋例外",
                   not _atl("不是 list")[0], "")
            # r9 Q4 新增三件
            _lock_no_id = {k: v for k, v in _lock_ok.items() if k != "topic_id"}
            _g_ok, _g_missing = _tls({"direction": "真題", "topic_lock": _lock_no_id})
            fcheck("F-CXP-R9-Q4-a 缺 topic_id → 未鎖（r9 Q4）",
                   (not _g_ok) and any("topic_id" in m for m in _g_missing), f"{_g_missing}")
            _lock_no_tc = dict(_lock_ok, traffic_candidates=[])
            _h_ok, _h_missing = _tls({"direction": "真題", "topic_lock": _lock_no_tc})
            fcheck("F-CXP-R9-Q4-b traffic_candidates 空清單 → 未鎖（r9 Q4）",
                   (not _h_ok) and any("traffic_candidates" in m for m in _h_missing), f"{_h_missing}")
            _dup_plan = [
                {"seq": 1, "direction": "真題A", "topic_lock": dict(_lock_ok)},
                {"seq": 2, "direction": "真題B",
                 "topic_lock": dict(_lock_ok, topic_statement="自己貼隔熱紙的隱形成本！")},
            ]
            _i_ok, _i_unlocked = _atl(_dup_plan)
            fcheck("F-CXP-R9-Q4-c 同批重複真題（正規化 exact-match）→ 未鎖級（r9 Q4）",
                   (not _i_ok) and any("重複真題" in "".join(m) for _s, m in _i_unlocked),
                   f"{_i_unlocked}")
            # r11 T1 新增二件：型別收緊（非法型別不得靠 str() 混過鎖）
            _lock_tc0 = dict(_lock_ok, traffic_candidates=0)
            _j_ok, _j_missing = _tls({"direction": "真題", "topic_lock": _lock_tc0})
            fcheck("F-CXP-R11-T1-a traffic_candidates=0（非 list）→ 未鎖（r11 T1 型別）",
                   (not _j_ok) and any("traffic_candidates" in m for m in _j_missing),
                   f"{_j_missing}")
            _lock_idbool = dict(_lock_ok, topic_id=True)
            _k_ok, _k_missing = _tls({"direction": "真題", "topic_lock": _lock_idbool})
            fcheck("F-CXP-R11-T1-b topic_id=True（bool 非 str）→ 未鎖（r11 T1 型別）",
                   (not _k_ok) and any("topic_id" in m for m in _k_missing),
                   f"{_k_missing}")
        except Exception as _e_r6_8:
            fcheck("F-CXP-R6-8 題目鎖 fixtures 可執行", False, f"{type(_e_r6_8).__name__}: {_e_r6_8}")

        # ⑨ r9 Q7：零件庫三欄 WARN-only（缺欄／非法 enum 只 WARN，合法 → PASS）
        try:
            _q7_ph = {"schema_check": {"標題型": "[編劇填 T1-T6]",
                                       "開頭軸": "[編劇填 O1-O4]",
                                       "結尾型": "[編劇填 E1-E3]"}}
            _q7_bad = {"schema_check": {"標題型": "T9", "開頭軸": "O2", "結尾型": "E4"}}
            # r11 T2 契約收緊：值須與 enum **全等**，帶說明文字的 "O4 提供價值" 不再算合法。
            #   本 fixture 原為 {"標題型":"T3","開頭軸":"O4 提供價值","結尾型":"E1"} 期望 PASS，
            #   隨精確匹配落地改為純型號值；口徑變更據實載於 r11 收尾。
            _q7_ok = {"schema_check": {"標題型": "T3", "開頭軸": "O4", "結尾型": "E1"}}
            # r11 T2 新增一件：兩位數型號不得被「取開頭一位」洗成合法（T10≠T1）
            _t2_t10 = {"schema_check": {"標題型": "T10", "開頭軸": "O1", "結尾型": "E1"}}
        except Exception as _e_r9_q7:
            fcheck("F-CXP-R9-Q7 零件庫三欄 fixtures 可執行", False,
                   f"{type(_e_r9_q7).__name__}: {_e_r9_q7}")

        # ════════════════════════════════════════════
        # F-CXP-R12：C-018／C-019 定向 fixtures（U4，2026-08-13 r12）
        #   評分輪 1 共識扣分第 5 條：「寫給唸」advisory 二件（r2 落地）當時無定向 fixture，
        #   等於沒有回歸保護——本組各補 1 件把 WARN 行為鎖成回歸測試。
        #   🔴 兩件都只斷言 WARN（永不 FAIL 是得標定稿 §2 紅線）：升成 FAIL 即為契約破壞，
        #      本 fixture 會同時擋住「誤升硬閘」與「悄悄失效變 PASS」兩個方向。
        # ════════════════════════════════════════════
        print("\n[F-CXP-R12] C-018／C-019 定向 fixtures（寫給唸 advisory 二件）")
        try:
            # ① C-018：超長句稿（兩句皆 > 26 字 advisory 觸發線，長句比例 1.0 > 0.5）→ WARN
            _r12_long = {"script_id": "f_cxp_r12_c018", "owner": "瑞祥", "scenes": [
                {"timestamp": "0-3s", "type": "hook",
                 "台詞": "今天要跟大家分享一個關於買房子的時候大家最常忽略掉但其實非常重要的關鍵細節。"},
                {"timestamp": "3-12s", "type": "body",
                 "台詞": "因為在整個看屋的流程當中，很多人只看格局跟價格，卻沒有注意到管委會的財務狀況跟公設的維護紀錄。"},
            ]}
            _r12_s1, _r12_d1 = chk_c018_readability(_r12_long, "f_cxp_r12_c018.yaml")
            fcheck("F-CXP-R12-C018 超長句稿 → WARN（advisory，永不 FAIL）",
                   _r12_s1 == "WARN" and "長句" in _r12_d1, f"got={_r12_s1}; {_r12_d1[:110]}")

            # ② C-019：自嗨開場稿（「我們公司成立於 1973 年」＝陳修平公式反例）→ WARN
            _r12_self = {"script_id": "f_cxp_r12_c019", "owner": "瑞祥", "scenes": [
                {"timestamp": "0-3s", "type": "hook", "台詞": "我們公司成立於 1973 年。"},
                {"timestamp": "3-12s", "type": "body", "台詞": "買房要看三件事。"},
            ]}
        except Exception as _e_r12:
            fcheck("F-CXP-R12 C-018／C-019 fixtures 可執行", False,
                   f"{type(_e_r12).__name__}: {_e_r12}")

        # ════════════════════════════════════════════
        # F-CXP-W1（cxp-gapfix-w1，2026-08-13）：體檢 Wave 1 P0 修復包定向 fixtures
        #   W1 C-TOPIC-LOCK／W3 假 topic_id／W4 topic_id 單一真源／W5 batch_flags 嚴格 loader
        #   每條都對「修好前會過、修好後必擋」的具體攻擊路徑各鎖一件回歸測試。
        # ════════════════════════════════════════════
        print("\n[F-CXP-W1] 體檢 Wave 1 P0 修復包定向 fixtures（W1/W3/W4/W5）")
        import tempfile as _w1_tmp

        # ── W5：batch_flags 嚴格 loader（Codex 洞 08）──
        try:
            from topic_intel_policy import (  # type: ignore[import]
                load_batch_flags_strict as _w5_load,
                load_topic_intel_policy as _w5_policy,
            )
            with _w1_tmp.TemporaryDirectory() as _w5_td:
                _w5_root = Path(_w5_td)
                # falsy 五型：檔案存在但 top-level 非 mapping → 一律 error（不得被 `or {}` 洗掉）
                for _name, _content in (("false", "false\n"), ("zero", "0\n"),
                                        ("null", "null\n"), ("empty", ""),
                                        ("list", "- a\n- b\n")):
                    _d = _w5_root / _name
                    _d.mkdir()
                    (_d / "_batch_flags.yml").write_text(_content, encoding="utf-8")
                    _raw, _err = _w5_load(_d)
                    fcheck(f"F-CXP-W1-W5-{_name} _batch_flags.yml={_content.strip()!r} → loader FAIL（不靜默當無 flags）",
                           _err is not None and _raw == {}, f"err={_err!r}")
                    # 三處消費端共用：validator 端同樣 error
                    _vraw, _verr = _load_batch_flags_checked(_d)
                    fcheck(f"F-CXP-W1-W5-{_name}-vsb validator 端同步 fail-closed",
                           _verr is not None, f"verr={_verr!r}")
                    # policy 端 → invalid（不是 off）
                    _pol = _w5_policy(_d)
                    fcheck(f"F-CXP-W1-W5-{_name}-policy topic_intel policy → invalid（≠off 靜默略過）",
                           _pol.get("mode") == "invalid", f"mode={_pol.get('mode')!r}")
                # 合法 mapping 與檔案不存在 → 零影響（不得誤傷）
                _ok_d = _w5_root / "valid"
                _ok_d.mkdir()
                (_ok_d / "_batch_flags.yml").write_text("batch_profile: hybrid_70_15_15\n", encoding="utf-8")
                _ok_raw, _ok_err = _w5_load(_ok_d)
                fcheck("F-CXP-W1-W5-valid 合法 mapping → 無 error 且內容原樣",
                       _ok_err is None and _ok_raw.get("batch_profile") == HYBRID_BATCH_PROFILE,
                       f"raw={_ok_raw!r} err={_ok_err!r}")
                _nf_d = _w5_root / "nofile"
                _nf_d.mkdir()
                _nf_raw, _nf_err = _w5_load(_nf_d)
                fcheck("F-CXP-W1-W5-nofile 檔案不存在 → ({}, None)（合法未宣告，非錯誤）",
                       _nf_err is None and _nf_raw == {}, f"raw={_nf_raw!r} err={_nf_err!r}")
        except Exception as _e_w5:
            fcheck("F-CXP-W1-W5 batch_flags loader fixtures 可執行", False,
                   f"{type(_e_w5).__name__}: {_e_w5}")

        # ── W3：假 topic_id 關死（龍蝦堵法表 P0-1）──
        try:
            from topic_distributor import (  # type: ignore[import]
                resolve_topic_id_source as _w3_resolve,
                assert_topic_ids_resolvable as _w3_assert,
                MANUAL_TOPIC_ID_PREFIX as _W3_MANUAL,
            )
            _w3_lock_base = {
                "topic_statement": "自己貼隔熱紙的隱形成本",
                "topic_source": "情報池", "topic_id": "FAKE-999",
                "audience_scene": "新手車主選膜時",
                "can_shoot": "自家車庫", "want_shoot": "願意講",
                "traffic_candidates": ["成本"],
            }
            _w3_ids = {"cyborg_real_0001", "cyborg_real_0002"}
            # ① 假 id（龍蝦實測 FAKE-999）→ unresolved
            _ok, _kind, _det = _w3_resolve("FAKE-999", "瑞祥", _w3_lock_base,
                                           projection_ids=_w3_ids, projection_error=None)
            fcheck("F-CXP-W1-W3-a 假 topic_id（FAKE-999，不在 projection）→ unresolved",
                   (not _ok) and _kind == "unresolved", f"kind={_kind} {_det[:90]}")
            # ② 真 id → projection
            _ok2, _kind2, _ = _w3_resolve("cyborg_real_0001", "瑞祥", _w3_lock_base,
                                          projection_ids=_w3_ids, projection_error=None)
            fcheck("F-CXP-W1-W3-b 命中 projection record 的 topic_id → 放行（kind=projection）",
                   _ok2 and _kind2 == "projection", f"kind={_kind2}")
            # ③ 人工 namespace ＋具名 locked_by → manual
            _mlock = dict(_w3_lock_base, topic_id=f"{_W3_MANUAL}20260813-001", locked_by="澤君")
            _ok3, _kind3, _ = _w3_resolve(_mlock["topic_id"], "瑞祥", _mlock,
                                          projection_ids=_w3_ids, projection_error=None)
            fcheck("F-CXP-W1-W3-c 人工題 MANUAL- 前綴＋具名 locked_by → 放行（kind=manual）",
                   _ok3 and _kind3 == "manual", f"kind={_kind3}")
            # ④ 人工 namespace 但無 locked_by → 擋（防「加前綴就萬能」）
            _mlock_no = dict(_w3_lock_base, topic_id=f"{_W3_MANUAL}20260813-002")
            _ok4, _kind4, _det4 = _w3_resolve(_mlock_no["topic_id"], "瑞祥", _mlock_no,
                                              projection_ids=_w3_ids, projection_error=None)
            fcheck("F-CXP-W1-W3-d 人工題無具名 locked_by → 擋（MANUAL- 不是萬能鑰匙）",
                   (not _ok4) and "locked_by" in _det4, f"kind={_kind4} {_det4[:90]}")
            # ⑤ 只有裸前綴 MANUAL- → 擋
            _bare = dict(_w3_lock_base, topic_id=_W3_MANUAL, locked_by="澤君")
            _ok5, _, _det5 = _w3_resolve(_W3_MANUAL, "瑞祥", _bare,
                                         projection_ids=_w3_ids, projection_error=None)
            fcheck("F-CXP-W1-W3-e 裸前綴 'MANUAL-'（無識別碼本體）→ 擋",
                   not _ok5, f"{_det5[:90]}")
            # ⑥ projection cache 不在場 → fail-closed（不得當作「無限制」放行）
            _ok6, _, _det6 = _w3_resolve("cyborg_real_0001", "瑞祥", _w3_lock_base,
                                         projection_ids=None, projection_error="cache 不存在（模擬）")
            fcheck("F-CXP-W1-W3-f projection cache 缺 → fail-closed 擋（不放行）",
                   not _ok6, f"{_det6[:90]}")
            # ⑦ 空／非 str topic_id → 擋
            for _bad in ("", "   ", None, True, 123):
                _okx, _, _ = _w3_resolve(_bad, "瑞祥", _w3_lock_base,
                                         projection_ids=_w3_ids, projection_error=None)
                fcheck(f"F-CXP-W1-W3-g topic_id={_bad!r} → 擋（空/非 str）", not _okx, "")
            # ⑧ plan 級：整份含假 id → all_ok=False（骨架機據此 exit 2）
            _w3_plan = [{"seq": 1, "script_id": "audit_01", "topic_lock": dict(_w3_lock_base)}]
            _all_ok, _bad = _w3_assert(_w3_plan, "__不存在的業主__")
            fcheck("F-CXP-W1-W3-h assert_topic_ids_resolvable（未知業主/無 cache）→ 不放行、不拋例外",
                   (not _all_ok) and len(_bad) == 1, f"bad={_bad[:1]}")
        except Exception as _e_w3:
            fcheck("F-CXP-W1-W3 假 topic_id fixtures 可執行", False,
                   f"{type(_e_w3).__name__}: {_e_w3}")

        # ── W4：topic_id 單一真源（Codex 洞 15）──
        try:
            _w4_eq = {"topic_lock": {"topic_id": "cyborg_aaa"},
                      "source_topic_intel": {"topic_id": "cyborg_aaa"}}
            _w4_ne = {"topic_lock": {"topic_id": "cyborg_aaa"},
                      "source_topic_intel": {"topic_id": "cyborg_bbb"}}
        except Exception as _e_w4:
            fcheck("F-CXP-W1-W4 topic_id 單一真源 fixtures 可執行", False,
                   f"{type(_e_w4).__name__}: {_e_w4}")

        # ── W1：C-TOPIC-LOCK 正式檢查（Codex 洞 02／龍蝦 P0-3）──
        try:
            from topic_distributor import topic_lock_hash as _w1_hash  # type: ignore[import]
            _w1_lock = {
                "topic_statement": "自己貼隔熱紙的隱形成本",
                "topic_source": "情報池", "topic_id": "cyborg_real_0001",
                "audience_scene": "新手車主選膜時",
                "can_shoot": "自家車庫", "want_shoot": "願意講",
                "traffic_candidates": ["成本", "反差"],
                "locked_by": "澤君", "locked_at": "2026-08-13",
            }
            _w1_item = {"seq": 1, "script_id": "w1_01", "direction": "真題", "topic_lock": dict(_w1_lock)}

            def _w1_batch(plan_obj, yaml_docs):
                """建臨時批次目錄（topic_plan.json + yaml 清單），回 (batch_dir, valid_yamls)。"""
                _td = _w1_tmp.mkdtemp()
                _bd = Path(_td)
                (_bd / "topic_plan.json").write_text(
                    json.dumps(plan_obj, ensure_ascii=False), encoding="utf-8")
                _vy = [(_bd / f"script_{d.get('script_id','x')}.yaml", d) for d in yaml_docs]
                return _bd, _vy

            # ① legacy 世代（批次明列 allowlist、無任何新世代訊號）→ SKIP 明標
            #   T1 r2：世代改由 allowlist 決定，故 fixture 需把臨時批次注入 allowlist 快取。
            _bd_a, _vy_a = _w1_batch({"plan": [{"script_id": "w1_01"}]}, [{"script_id": "w1_01", "title": "舊稿"}])
            _LEGACY_ALLOWLIST_CACHE = (frozenset({str(_bd_a.resolve())}), None)
            try:
                _s, _d = chk_topic_lock_consistency(_vy_a, _bd_a)
            finally:
                _LEGACY_ALLOWLIST_CACHE = None
            fcheck("F-CXP-W1-W1-a legacy 世代（allowlist 內）→ SKIP 明標（grandfather，不打紅歷史稿）",
                   _s == "SKIP" and "legacy 世代" in _d, f"got={_s}; {_d[:110]}")
            # ② 新格式一致 → PASS
            _plan_ok = {"plan": [dict(_w1_item)]}
            _plan_ok["topic_lock_hash"] = _w1_hash(_plan_ok["plan"])
            _bd_b, _vy_b = _w1_batch(_plan_ok, [{"script_id": "w1_01", "topic_lock": dict(_w1_lock)}])
            _s2, _d2 = chk_topic_lock_consistency(_vy_b, _bd_b)
            fcheck("F-CXP-W1-W1-b 稿 topic_lock 與 plan 逐欄相符＋hash 相符 → PASS",
                   _s2 == "PASS", f"got={_s2}; {_d2[:110]}")
            # ③ 稿件事後偷改鎖（換題）→ FAIL
            _tampered = dict(_w1_lock, topic_statement="偷換成另一個題")
            _bd_c, _vy_c = _w1_batch(_plan_ok, [{"script_id": "w1_01", "topic_lock": _tampered}])
            _s3, _d3 = chk_topic_lock_consistency(_vy_c, _bd_c)
            fcheck("F-CXP-W1-W1-c 稿件 topic_lock 被事後改（鎖A稿B）→ FAIL",
                   _s3 == "FAIL" and "topic_statement" in _d3, f"got={_s3}; {_d3[:130]}")
            # ④ plan 的鎖被事後改（hash 對不上）→ FAIL
            _plan_bad = {"plan": [dict(_w1_item, topic_lock=dict(_w1_lock, topic_id="cyborg_swapped"))],
                         "topic_lock_hash": _plan_ok["topic_lock_hash"]}
            _bd_d, _vy_d = _w1_batch(_plan_bad, [{"script_id": "w1_01",
                                                  "topic_lock": dict(_w1_lock, topic_id="cyborg_swapped")}])
            _s4, _d4 = chk_topic_lock_consistency(_vy_d, _bd_d)
            fcheck("F-CXP-W1-W1-d plan 題目鎖產出後被改（topic_lock_hash 不符）→ FAIL",
                   _s4 == "FAIL" and "topic_lock_hash" in _d4, f"got={_s4}; {_d4[:130]}")
            # ⑤ 手寫 yaml 帶鎖但 plan 無此 script_id → FAIL（龍蝦 P0-3 偷跳路徑）
            _bd_e, _vy_e = _w1_batch(_plan_ok, [{"script_id": "w1_99_手寫", "topic_lock": dict(_w1_lock)}])
            _s5, _d5 = chk_topic_lock_consistency(_vy_e, _bd_e)
            fcheck("F-CXP-W1-W1-e 手寫 yaml（script_id 不在 plan）→ FAIL（不得繞過題目層）",
                   _s5 == "FAIL" and "不在 topic_plan" in _d5, f"got={_s5}; {_d5[:130]}")
            # ⑥ 新格式批混入無鎖稿 → FAIL
            _bd_f, _vy_f = _w1_batch(_plan_ok, [{"script_id": "w1_01", "topic_lock": dict(_w1_lock)},
                                                {"script_id": "w1_02", "title": "無鎖偷混"}])
            _s6, _d6 = chk_topic_lock_consistency(_vy_f, _bd_f)
            fcheck("F-CXP-W1-W1-f 新格式批混入無 topic_lock 稿 → FAIL",
                   _s6 == "FAIL", f"got={_s6}; {_d6[:130]}")
            # ⑦ hash 正規化契約：list 欄順序改變 → hash 改變（不得被排序洗掉）
            _h1 = _w1_hash([dict(_w1_item)])
            _h2 = _w1_hash([dict(_w1_item, topic_lock=dict(_w1_lock, traffic_candidates=["反差", "成本"]))])
            fcheck("F-CXP-W1-W1-g traffic_candidates 順序不同 → lock hash 不同（順序即內容）",
                   _h1 != _h2, f"h1={_h1[:12]} h2={_h2[:12]}")
        except Exception as _e_w1c:
            fcheck("F-CXP-W1-W1 C-TOPIC-LOCK fixtures 可執行", False,
                   f"{type(_e_w1c).__name__}: {_e_w1c}")

        # ════════════════════════════════════════════
        # F-CXP-T1（cxp-enforce-t1 r1，2026-08-13）：T1 硬閘翻轉定向 fixtures
        #   三個閘各鎖「新格式批 FAIL／舊稿批 WARN-or-SKIP」兩個方向，
        #   外加世代 resolver 本身與「零誤殺契約」（舊稿走 enforce=False）各一件。
        #   🔴 契約：任一件轉紅＝硬閘語意或 grandfather 保護被改壞，必須停手回滾。
        # ════════════════════════════════════════════
        print("\n[F-CXP-T1] T1 硬閘翻轉定向 fixtures（零件庫三欄／流量密碼整欄／藏鏡人接球）")
        try:
            # ── 世代 resolver（T1 三閘＋C-TOPIC-LOCK 的唯一開關；r2 改 allowlist 制）──
            _t1_lock_doc = {"script_id": "t1_01", "topic_lock": {"topic_id": "cyborg_0001"}}
            _t1_old_doc = {"script_id": "t1_01", "title": "舊稿無鎖"}
            _t1_gen_new, _t1_why_new = _resolve_enforce_generation(
                None, [(Path("t1_new.yaml"), _t1_lock_doc)])
            fcheck("F-CXP-T1-G-a 批內有稿帶 topic_lock → new 世代（enforce=True）",
                   _t1_gen_new is True and "new 世代" in _t1_why_new, f"got={_t1_gen_new}; {_t1_why_new[:90]}")
            _t1_gen_old, _t1_why_old = _resolve_enforce_generation(
                None, [(Path("t1_old.yaml"), _t1_old_doc)])
            fcheck("F-CXP-T1-G-b 無鎖且無批次目錄 → new 世代（r2 fail-closed；判不出來不得放行）",
                   _t1_gen_old is True and "fail-closed" in _t1_why_old,
                   f"got={_t1_gen_old}; {_t1_why_old[:90]}")
            with _w1_tmp.TemporaryDirectory() as _t1_td:
                _t1_bd = Path(_t1_td)
                (_t1_bd / "topic_plan.json").write_text(
                    json.dumps({"plan": [{"script_id": "t1_01"}], "topic_lock_hash": "deadbeef"},
                               ensure_ascii=False), encoding="utf-8")
                _t1_gen_plan, _t1_why_plan = _resolve_enforce_generation(
                    _t1_bd, [(Path("t1_old.yaml"), _t1_old_doc)])
                fcheck("F-CXP-T1-G-c 稿無鎖但 plan 帶 topic_lock_hash → new 世代（第二條世代路徑）",
                       _t1_gen_plan is True, f"got={_t1_gen_plan}; {_t1_why_plan[:90]}")
                _t1_bd2 = _t1_bd / "legacy"
                _t1_bd2.mkdir()
                (_t1_bd2 / "topic_plan.json").write_text(
                    json.dumps({"plan": [{"script_id": "t1_01"}]}, ensure_ascii=False), encoding="utf-8")
                # 舊 plan（無 hash）＋無鎖稿，且**不在 allowlist** → r2 判 new（r1 會判舊稿）
                _t1_gen_lp, _t1_why_lp = _resolve_enforce_generation(
                    _t1_bd2, [(Path("t1_old.yaml"), _t1_old_doc)])
                fcheck("F-CXP-T1-G-d 舊 plan＋無鎖稿但不在 allowlist → new 世代（r2 防自降級）",
                       _t1_gen_lp is True and "allowlist" in _t1_why_lp,
                       f"got={_t1_gen_lp}; {_t1_why_lp[:110]}")
                # 同一個批次目錄，列進 allowlist → 才是 legacy（唯一的舊稿路徑）
                _LEGACY_ALLOWLIST_CACHE = (frozenset({str(_t1_bd2.resolve())}), None)
                try:
                    _t1_gen_al, _t1_why_al = _resolve_enforce_generation(
                        _t1_bd2, [(Path("t1_old.yaml"), _t1_old_doc)])
                finally:
                    _LEGACY_ALLOWLIST_CACHE = None
                fcheck("F-CXP-T1-G-e 同一批次列進 legacy allowlist → legacy 世代（grandfather 零誤殺）",
                       _t1_gen_al is False and "legacy 世代" in _t1_why_al,
                       f"got={_t1_gen_al}; {_t1_why_al[:110]}")

            # ── T1a：零件庫三欄（C-PARTS-002 硬閘 ／ C-PARTS-001 保留 WARN 路徑）──
            _t1_parts_bad = {"schema_check": {"標題型": "T4", "開頭軸": "[編劇填 O1-O4]"}}
            _a1_s, _a1_d = chk_parts_002_component_enums_enforce(
                _t1_parts_bad, "t1a_bad.yaml", enforce_generation=True)
            fcheck("F-CXP-T1-A-1 新格式批缺欄＋placeholder → C-PARTS-002 FAIL",
                   _a1_s == "FAIL" and "結尾型" in _a1_d and "開頭軸" in _a1_d,
                   f"got={_a1_s}; {_a1_d[:130]}")
            _a2_s, _a2_d = chk_parts_002_component_enums_enforce(
                _t1_parts_bad, "t1a_bad.yaml", enforce_generation=False)
            fcheck("F-CXP-T1-A-2 同一份稿在 legacy 批 → C-PARTS-002 SKIP（grandfather 零誤殺）",
                   _a2_s == "SKIP" and "legacy 世代" in _a2_d, f"got={_a2_s}; {_a2_d[:110]}")
            _t1_parts_ok = {"schema_check": {"標題型": "T4", "開頭軸": "O1", "結尾型": "E1"}}
            _a3_s, _a3_d = chk_parts_002_component_enums_enforce(
                _t1_parts_ok, "t1a_ok.yaml", enforce_generation=True)
            fcheck("F-CXP-T1-A-3 新格式批三欄合法 enum → C-PARTS-002 PASS（正例不誤殺）",
                   _a3_s == "PASS", f"got={_a3_s}; {_a3_d[:110]}")
            _a4_s, _a4_d = chk_parts_002_component_enums_enforce(
                {"title": "x"}, "t1a_nosc.yaml", enforce_generation=True)
            fcheck("F-CXP-T1-A-4 新格式批整塊 schema_check 缺 → FAIL（封『不填免查』旁路）",
                   _a4_s == "FAIL" and "整塊不填" in _a4_d, f"got={_a4_s}; {_a4_d[:110]}")
            _a5_s, _a5_d = chk_parts_002_component_enums_enforce(
                {"schema_check": {"標題型": "T10", "開頭軸": "O1", "結尾型": "E1"}},
                "t1a_t10.yaml", enforce_generation=True)
            fcheck("F-CXP-T1-A-5 新格式批非法 enum（T10）→ FAIL（精確匹配契約沿用 r11 T2）",
                   _a5_s == "FAIL" and "T10" in _a5_d, f"got={_a5_s}; {_a5_d[:110]}")
            # C-PARTS-001 保留舊稿 WARN 路徑（T1a 明令：不得被 002 取代或升 FAIL）

            # ── T1b：流量密碼整欄缺（逆向誘因洞）──
            _t1_traffic_none = {"script_id": "t1b", "schema_check": {"禁虛構": True}}
            _b1_s, _b1_d = chk_l1_004_traffic(_t1_traffic_none, "t1b_none.yaml", enforce_generation=True)
            fcheck("F-CXP-T1-B-1 新格式批整欄未宣告流量密碼 → FAIL（封不填免查）",
                   _b1_s == "FAIL" and "整欄缺" in _b1_d, f"got={_b1_s}; {_b1_d[:130]}")
            _b2_s, _b2_d = chk_l1_004_traffic(_t1_traffic_none, "t1b_none.yaml", enforce_generation=False)
            fcheck("F-CXP-T1-B-2 舊稿批整欄未宣告 → 仍 WARN（130+ 支現役稿零誤殺）",
                   _b2_s == "WARN", f"got={_b2_s}; {_b2_d[:110]}")
            _b3_s, _b3_d = chk_l1_004_traffic(
                {"schema_check": {"流量密碼": ["反差", "恐懼", "知識落差"]}},
                "t1b_ok.yaml", enforce_generation=True)
            fcheck("F-CXP-T1-B-3 新格式批宣告 3 個白名單元素 → PASS（正例不誤殺）",
                   _b3_s == "PASS", f"got={_b3_s}; {_b3_d[:110]}")
            _b4_s, _b4_d = chk_l1_004_traffic(
                {"schema_check": {"流量密碼": ["反差"]}}, "t1b_short.yaml", enforce_generation=True)
            fcheck("F-CXP-T1-B-4 白名單計數 FAIL 既有邏輯不動（宣告 1 < 3 → 照舊 FAIL）",
                   _b4_s == "FAIL" and "白名單命中 1" in _b4_d, f"got={_b4_s}; {_b4_d[:110]}")
            _b5_s, _b5_d = chk_l1_004_traffic(
                {"schema_check": {"流量密碼": ["反差"]}}, "t1b_short.yaml", enforce_generation=False)
            fcheck("F-CXP-T1-B-5 舊稿批宣告不足仍 FAIL（既有硬閘不得被 T1 放寬）",
                   _b5_s == "FAIL", f"got={_b5_s}; {_b5_d[:110]}")

            # ── T1c：藏鏡人接球／酸度欄 ──
            def _t1_mirror_doc(reply=None, sour=None):
                return {"script_id": "t1c", "duration": 60, "scenes": [
                    {"timestamp": "0-3s", "type": "Hook", "台詞": "開場"},
                    _r6_scene("3-12s", "破題", "破題", "藏鏡人拋球", reply, sour),
                ]}
            _c1_s, _c1_d = chk_l1_003_mirror(_t1_mirror_doc(reply=None, sour="S1"),
                                             "t1c_noreply.yaml", enforce_generation=True)
            fcheck("F-CXP-T1-C-1 新格式批缺藏鏡人接球欄 → FAIL",
                   _c1_s == "FAIL" and "接球" in _c1_d, f"got={_c1_s}; {_c1_d[:130]}")
            _c2_s, _c2_d = chk_l1_003_mirror(_t1_mirror_doc(reply=None, sour="S1"),
                                             "t1c_noreply.yaml", enforce_generation=False)
            fcheck("F-CXP-T1-C-2 舊稿批缺接球欄 → 仍 WARN（grandfather 零誤殺）",
                   _c2_s == "WARN" and "shadow" in _c2_d, f"got={_c2_s}; {_c2_d[:130]}")
            _c3_s, _c3_d = chk_l1_003_mirror(_t1_mirror_doc(reply="業主接球", sour=None),
                                             "t1c_nosour.yaml", enforce_generation=True)
            fcheck("F-CXP-T1-C-3 新格式批缺酸度欄 → FAIL（T1c 同升）",
                   _c3_s == "FAIL" and "酸度" in _c3_d, f"got={_c3_s}; {_c3_d[:130]}")
            _c4_s, _c4_d = chk_l1_003_mirror(_t1_mirror_doc(reply="業主接球", sour="S9"),
                                             "t1c_badsour.yaml", enforce_generation=True)
            fcheck("F-CXP-T1-C-4 新格式批酸度值非法（S9）→ FAIL",
                   _c4_s == "FAIL" and "S9" in _c4_d, f"got={_c4_s}; {_c4_d[:130]}")
            _c5_s, _c5_d = chk_l1_003_mirror(_t1_mirror_doc(reply="業主接球", sour="S1"),
                                             "t1c_ok.yaml", enforce_generation=True)
            fcheck("F-CXP-T1-C-5 新格式批接球＋酸度齊備 → PASS（正例不誤殺）",
                   _c5_s == "PASS", f"got={_c5_s}; {_c5_d[:110]}")
            # S2 數量建議在新批仍只 WARN（工單 T1c：品質建議永不升 FAIL）
            _c6_doc = {"script_id": "t1c_s2", "duration": 60, "scenes": [
                _r6_scene("0-3s", "Hook", "開場", "藏鏡人一", "接球一", "S0"),
                _r6_scene("3-12s", "破題", "破題", "藏鏡人二", "接球二", "S1"),
            ]}
            _c6_s, _c6_d = chk_l1_003_mirror(_c6_doc, "t1c_s2.yaml", enforce_generation=True)
            fcheck("F-CXP-T1-C-6 新格式批『>=2 點無 S2』→ 仍 WARN（S2 數量建議不升 FAIL）",
                   _c6_s == "WARN" and "S2" in _c6_d, f"got={_c6_s}; {_c6_d[:130]}")
            # 缺省參數＝T1 前行為（外部 caller 不傳世代時不得被偷偷 enforce）
            _c7_s, _c7_d = chk_l1_003_mirror(_t1_mirror_doc(reply=None, sour="S1"), "t1c_default.yaml")
            fcheck("F-CXP-T1-C-7 未傳 enforce_generation → 退回全域旗標（T1 前行為逐字不變）",
                   _c7_s == ("FAIL" if _MIRROR_REPLY_ENFORCE else "WARN"),
                   f"got={_c7_s}; flag={_MIRROR_REPLY_ENFORCE}; {_c7_d[:100]}")
            _b6_s, _ = chk_l1_004_traffic(_t1_traffic_none, "t1b_default.yaml")
            fcheck("F-CXP-T1-B-6 L1-004 未傳世代 → 退回全域旗標（T1 前行為逐字不變）",
                   _b6_s == ("FAIL" if _MIRROR_REPLY_ENFORCE else "WARN"),
                   f"got={_b6_s}; flag={_MIRROR_REPLY_ENFORCE}")

            # ════════════════════════════════════════
            # F-CXP-T1-R2（cxp-enforce-t1 r2）：Codex 終審兩阻擋項的定向反例
            #   R2-1/2 ＝ 阻擋項 1（世代分岔：壞 JSON plan 下三閘與 C-TOPIC-LOCK 必須同判）
            #   R2-3/4 ＝ 阻擋項 2（刪 topic_lock 自降級）
            #   R2-5/6 ＝ allowlist 本身的 fail-closed 與正向 legacy 路徑
            #   🔴 契約：任一件轉紅＝世代真源又被拆成兩份、或 grandfather 又能被自封。
            # ════════════════════════════════════════
            print("\n[F-CXP-T1-R2] r2 回修反例（世代單一真源／防自降級）")

            # ① Codex 反例①：壞 JSON topic_plan —— 三閘與 C-TOPIC-LOCK 同判（不得分岔）
            with _w1_tmp.TemporaryDirectory() as _r2_td:
                _r2_bd = Path(_r2_td)
                (_r2_bd / "topic_plan.json").write_text("{ 這不是合法 JSON ", encoding="utf-8")
                _r2_docs = [(_r2_bd / "script_x.yaml", {"script_id": "x", "title": "壞 plan 批"})]
                _r2_gen, _r2_why = _resolve_enforce_generation(_r2_bd, _r2_docs)
                fcheck("F-CXP-T1-R2-1 壞 JSON topic_plan → 世代 resolver 判 new（fail-closed，不再 fail-open）",
                       _r2_gen is True and "topic_plan" in _r2_why, f"got={_r2_gen}; {_r2_why[:120]}")
                _r2_tl_s, _r2_tl_d = chk_topic_lock_consistency(
                    _r2_docs, _r2_bd, None,
                    enforce_generation=_r2_gen, generation_reason=_r2_why)
                _r2_parts_s, _ = chk_parts_002_component_enums_enforce(
                    _r2_docs[0][1], "script_x.yaml", enforce_generation=_r2_gen)
                _r2_traffic_s, _ = chk_l1_004_traffic(
                    _r2_docs[0][1], "script_x.yaml", enforce_generation=_r2_gen)
                fcheck("F-CXP-T1-R2-2 壞 JSON plan：C-TOPIC-LOCK 與三閘同判 enforce（Codex 分岔反例已封）",
                       _r2_tl_s == "FAIL" and _r2_parts_s == "FAIL" and _r2_traffic_s == "FAIL",
                       f"topic_lock={_r2_tl_s} parts={_r2_parts_s} traffic={_r2_traffic_s}; {_r2_tl_d[:90]}")

            # ② Codex 反例②：「刪 topic_lock 降級」攻擊 —— 同一批稿刪鎖前後都必須 FAIL
            with _w1_tmp.TemporaryDirectory() as _r2_td2:
                _r2_bd2 = Path(_r2_td2)   # 未列入 allowlist 的新批
                _attack_doc_locked = {
                    "script_id": "atk", "topic_lock": {"topic_id": "cyborg_atk"},
                    "duration": 60,
                    "scenes": [{"timestamp": "0-3s", "type": "Hook", "台詞": "開場"},
                               _r6_scene("3-12s", "破題", "破題", "藏鏡人拋球", None, None)],
                }
                _attack_doc_stripped = {k: v for k, v in _attack_doc_locked.items() if k != "topic_lock"}
                _gen_locked, _ = _resolve_enforce_generation(
                    _r2_bd2, [(_r2_bd2 / "atk.yaml", _attack_doc_locked)])
                _gen_stripped, _why_stripped = _resolve_enforce_generation(
                    _r2_bd2, [(_r2_bd2 / "atk.yaml", _attack_doc_stripped)])
                fcheck("F-CXP-T1-R2-3 刪掉 topic_lock 欄 → 世代仍是 new（不在 allowlist；自降級路徑已封）",
                       _gen_locked is True and _gen_stripped is True,
                       f"locked={_gen_locked} stripped={_gen_stripped}; {_why_stripped[:110]}")
                _atk_parts_s, _ = chk_parts_002_component_enums_enforce(
                    _attack_doc_stripped, "atk.yaml", enforce_generation=_gen_stripped)
                _atk_traffic_s, _ = chk_l1_004_traffic(
                    _attack_doc_stripped, "atk.yaml", enforce_generation=_gen_stripped)
                _atk_mirror_s, _ = chk_l1_003_mirror(
                    _attack_doc_stripped, "atk.yaml", enforce_generation=_gen_stripped)
                _atk_tl_s, _atk_tl_d = chk_topic_lock_consistency(
                    [(_r2_bd2 / "atk.yaml", _attack_doc_stripped)], _r2_bd2, None,
                    enforce_generation=_gen_stripped, generation_reason=_why_stripped)
                fcheck("F-CXP-T1-R2-4 刪鎖後三閘仍 FAIL/FAIL/FAIL＋C-TOPIC-LOCK FAIL（Codex 降級反例已封）",
                       (_atk_parts_s, _atk_traffic_s, _atk_mirror_s, _atk_tl_s)
                       == ("FAIL", "FAIL", "FAIL", "FAIL"),
                       f"parts={_atk_parts_s} traffic={_atk_traffic_s} mirror={_atk_mirror_s} "
                       f"topic_lock={_atk_tl_s}; {_atk_tl_d[:90]}")

                # ③ allowlist 壞掉/缺檔 → fail-closed（全部當 new，不得整批放行）
                _saved_cache = _LEGACY_ALLOWLIST_CACHE
                _LEGACY_ALLOWLIST_CACHE = (frozenset(), "legacy allowlist 檔案不存在（模擬）")
                try:
                    _fc_gen, _fc_why = _resolve_enforce_generation(
                        _r2_bd2, [(_r2_bd2 / "atk.yaml", _attack_doc_stripped)])
                finally:
                    _LEGACY_ALLOWLIST_CACHE = _saved_cache
                fcheck("F-CXP-T1-R2-5 allowlist 缺檔/壞格式 → fail-closed 全部當 new（不得整批放行）",
                       _fc_gen is True and "fail-closed" in _fc_why, f"got={_fc_gen}; {_fc_why[:110]}")

            # ④ 正式 allowlist 檔本身健康度（缺檔＝現役舊批會被誤殺，必須當場擋下）
            _al_set, _al_err = _load_legacy_batch_allowlist(force_reload=True)
            fcheck("F-CXP-T1-R2-6 legacy_batch_allowlist.yaml 存在且 schema 合法（現役舊批 grandfather 來源）",
                   _al_err is None and len(_al_set) > 0,
                   f"err={_al_err}; n={len(_al_set)}")
            _al_missing = [p for p in _al_set if not Path(p).exists()]
            fcheck("F-CXP-T1-R2-7 allowlist 內每個批次目錄都真的存在（防列到不存在路徑）",
                   not _al_missing, f"不存在 {len(_al_missing)} 筆：{_al_missing[:3]}")

            # ════════════════════════════════════════
            # F-CXP-T1-R3（r3）：allowlist **真實壞 YAML** 回歸
            #   Codex r2 新阻擋＝重複鍵旁路：`legacy_batches: []` 後再補一個同名鍵，
            #   PyYAML 默默採最後一鍵 → 攻擊者把整包批次塞進 allowlist 拿 grandfather
            #   （修前實測：0/N new、N/N legacy）。r2 舊 fixture 只注入「模擬錯誤快取」，
            #   沒有真解析壞 YAML，所以漏掉這條路 → 本組一律**實際寫 tmp 檔真解析**。
            #   R3-1 頂層重複鍵／R3-2 巢狀重複鍵／R3-3 型別錯誤／R3-4 語法錯誤
            #        → 四件都必須 fail-closed：受攻擊目標批次 **N/N 全部翻 new**
            #   R3-5 正常檔（含重複「值」但無重複鍵）仍正常載入（防過度嚴格誤殺舊批）
            #   🔴 契約：任一件轉紅＝補一個同名鍵就能整包逃驗。
            # ════════════════════════════════════════
            print("\n[F-CXP-T1-R3] allowlist 真實壞 YAML fail-closed（重複鍵旁路回歸）")

            def _r3_probe(_yaml_text, _targets):
                """把 allowlist 指向真實 tmp 檔 → 真解析 → 回 (err, new 數, legacy 數)。"""
                global _LEGACY_ALLOWLIST_PATH, _LEGACY_ALLOWLIST_CACHE
                _saved_p, _saved_c = _LEGACY_ALLOWLIST_PATH, _LEGACY_ALLOWLIST_CACHE
                with _w1_tmp.TemporaryDirectory() as _td:
                    _p = Path(_td) / "legacy_batch_allowlist.yaml"
                    _p.write_text(_yaml_text, encoding="utf-8")
                    _LEGACY_ALLOWLIST_PATH = _p
                    try:
                        _s, _e = _load_legacy_batch_allowlist(force_reload=True)
                        _n = _l = 0
                        for _t in _targets:
                            _g, _ = _resolve_enforce_generation(Path(_t), [])
                            if _g:
                                _n += 1
                            else:
                                _l += 1
                        return _e, _n, _l, len(_s)
                    finally:
                        _LEGACY_ALLOWLIST_PATH = _saved_p
                        _LEGACY_ALLOWLIST_CACHE = _saved_c

            # 攻擊目標＝正式 allowlist 內的真實批次目錄（本來會拿 grandfather 的那些）
            _r3_targets = sorted(_al_set)
            _r3_n = len(_r3_targets)
            _r3_entries = "\n".join(f'  - "{_t}"' for _t in _r3_targets)

            # 對照組：完全同內容但**單一** legacy_batches 鍵 → 必須 N/N legacy（證明攻擊本體有效）
            _ok_err, _ok_new, _ok_leg, _ok_cnt = _r3_probe(
                f"version: 1\nlegacy_batches:\n{_r3_entries}\n", _r3_targets)
            fcheck(f"F-CXP-T1-R3-5 正常 allowlist（無重複鍵）仍正常載入：{_ok_leg}/{_r3_n} legacy（防過度嚴格誤殺舊批）",
                   _ok_err is None and _ok_leg == _r3_n and _ok_new == 0,
                   f"err={_ok_err}; new={_ok_new} legacy={_ok_leg} n={_ok_cnt}")

            # R3-1 頂層重複鍵：第一鍵空清單、第二鍵偷塞全部批次（Codex 原案例）
            _dup_err, _dup_new, _dup_leg, _ = _r3_probe(
                f"version: 1\nlegacy_batches: []\nlegacy_batches:\n{_r3_entries}\n", _r3_targets)
            fcheck(f"F-CXP-T1-R3-1 頂層重複鍵 allowlist → 拒收＋{_dup_new}/{_r3_n} 全翻 new（Codex 旁路已封；修前為 0/{_r3_n}）",
                   _dup_err is not None and _dup_new == _r3_n and _dup_leg == 0,
                   f"err={_dup_err}; new={_dup_new} legacy={_dup_leg}")

            # R3-2 巢狀重複鍵（不只看頂層）
            _nest_err, _nest_new, _nest_leg, _ = _r3_probe(
                "version: 1\nmeta:\n  owner: a\n  owner: b\n"
                f"legacy_batches:\n{_r3_entries}\n", _r3_targets)
            fcheck(f"F-CXP-T1-R3-2 巢狀重複鍵 allowlist → 一樣拒收＋{_nest_new}/{_r3_n} 全翻 new",
                   _nest_err is not None and _nest_new == _r3_n and _nest_leg == 0,
                   f"err={_nest_err}; new={_nest_new} legacy={_nest_leg}")

            # R3-3 型別錯誤（legacy_batches 是 dict 不是 list）
            _bt_err, _bt_new, _bt_leg, _ = _r3_probe(
                "version: 1\nlegacy_batches:\n  a: 1\n  b: 2\n", _r3_targets)
            fcheck(f"F-CXP-T1-R3-3 型別錯誤 allowlist（真檔解析）→ fail-closed {_bt_new}/{_r3_n} new",
                   _bt_err is not None and _bt_new == _r3_n and _bt_leg == 0,
                   f"err={_bt_err}; new={_bt_new} legacy={_bt_leg}")

            # R3-4 語法錯誤（真的解不動）
            _sx_err, _sx_new, _sx_leg, _ = _r3_probe(
                "version: 1\nlegacy_batches: [\n  - \"x\n   bad: : :\n", _r3_targets)
            fcheck(f"F-CXP-T1-R3-4 語法錯誤 allowlist（真檔解析）→ fail-closed {_sx_new}/{_r3_n} new",
                   _sx_err is not None and _sx_new == _r3_n and _sx_leg == 0,
                   f"err={_sx_err}; new={_sx_new} legacy={_sx_leg}")

            # R3-6 正式 allowlist 檔本身無重複鍵（改用 no-dup loader 後仍健康）
            _al_set2, _al_err2 = _load_legacy_batch_allowlist(force_reload=True)
            fcheck("F-CXP-T1-R3-6 正式 legacy_batch_allowlist.yaml 通過 no-dup loader（本身無重複鍵）",
                   _al_err2 is None and _al_set2 == _al_set,
                   f"err={_al_err2}; n={len(_al_set2)} vs {len(_al_set)}")
        except Exception as _e_t1:
            fcheck("F-CXP-T1 T1 硬閘 fixtures 可執行", False,
                   f"{type(_e_t1).__name__}: {_e_t1}")

        # ════════════════════════════════════════════
        # F-CXP-T2（cxp-enforce-t2 r1，2026-08-13）：registry／receipt／8 硬閘定向 fixtures
        #   工單 Y5：**每閘正反例**＋零誤殺方向（legacy 一律 SKIP）＋版本緩衝三態
        #   ＋registry 壞檔 fail-closed（含 no-dup loader 旁路）。
        #   🔴 契約：任一件轉紅＝梯 2 語意或 grandfather 保護被改壞，停手回滾。
        # ════════════════════════════════════════════
        print("\n[F-CXP-T2] 梯 2 定向 fixtures（registry／receipt／8 方法硬閘）")
        try:
            import chxp_registry as _t2r  # type: ignore[import]

            _t2_reg, _t2_err = _t2r.load_registry(force_reload=True)
            fcheck("F-CXP-T2-R-1 正式 registry 載入成功（no-dup loader＋schema 驗）",
                   _t2_err is None and _t2_reg is not None, f"err={_t2_err}")
            _t2_methods = (_t2_reg or {}).get("methods", [])
            fcheck("F-CXP-T2-R-2 registry 128 條、id 001-128 連號",
                   len(_t2_methods) == 128
                   and [m["id"] for m in _t2_methods] == [f"{i:03d}" for i in range(1, 129)],
                   f"n={len(_t2_methods)}")
            _t2_excluded = [m for m in _t2_methods if m.get("mode") == "excluded"]
            fcheck("F-CXP-T2-R-3 34 條 excluded 在冊且每條都留著理由（不准悄悄消失）",
                   len(_t2_excluded) == 34
                   and all(str(m.get("excluded_reason", "")).strip() for m in _t2_excluded),
                   f"excluded={len(_t2_excluded)}")
            _t2_layer = {m["id"]: m.get("layer") for m in _t2_methods}
            fcheck("F-CXP-T2-R-5 #058＝blocked_entry（獨立入口，不塞 validator）；"
                   "021/022/109＝manual；018/027/028/043/080＝receipt",
                   _t2_layer.get("058") == "blocked_entry"
                   and all(_t2_layer.get(i) == "manual" for i in ("021", "022", "109"))
                   and all(_t2_layer.get(i) == "receipt" for i in ("018", "027", "028", "043", "080")),
                   f"058={_t2_layer.get('058')} 021={_t2_layer.get('021')} 018={_t2_layer.get('018')}")

            # ── 版本緩衝三態（愛馬仕嫁接件：改一條正典不得整批 FAIL）──
            _t2_v_ok = _t2r.check_version({"registry_version": _t2r._REGISTRY_VERSION_EXPECTED})
            fcheck("F-CXP-T2-V-a 版本一致 → PASS", _t2_v_ok[0] == "PASS", f"got={_t2_v_ok}")
            _t2_v_grace = _t2r.check_version({
                "registry_version": "chxp-128-v2",
                "previous_version": _t2r._REGISTRY_VERSION_EXPECTED,
                "registry_owner": "霸告"})
            fcheck("F-CXP-T2-V-b 差一版（registry.previous 命中程式期望）→ WARN grace，不擋批",
                   _t2_v_grace[0] == "WARN" and "grace" in _t2_v_grace[1],
                   f"got={_t2_v_grace}")
            _t2_v_far = _t2r.check_version({
                "registry_version": "chxp-128-v9", "previous_version": "chxp-128-v8"})
            fcheck("F-CXP-T2-V-c 差兩版以上 → FAIL（超出 grace window）",
                   _t2_v_far[0] == "FAIL", f"got={_t2_v_far}")
            fcheck("F-CXP-T2-V-d registry_version 缺 → FAIL（不得靠沒版本躲過比對）",
                   _t2r.check_version({})[0] == "FAIL", f"got={_t2r.check_version({})}")

            # ── registry 壞檔 fail-closed（含重複鍵旁路，同 T1 r3 教訓）──
            def _t2_probe_bad(text: str):
                _p = Path(_w1_tmp.mkdtemp()) / "bad_registry.yaml"
                _p.write_text(text, encoding="utf-8")
                return _t2r.load_registry(force_reload=True, path=_p)

            _t2_ok_min = "registry_version: x\nmethods:\n" + "".join(
                f"- {{id: '{i:03d}', mode: excluded, layer: none, excluded_reason: r}}\n"
                for i in range(1, 129))
            _t2_dup = _t2_ok_min + "methods:\n- {id: '001', mode: always, layer: none}\n"
            _t2_bad_reg, _t2_bad_err = _t2_probe_bad(_t2_dup)
            fcheck("F-CXP-T2-B-a registry 頂層重複鍵 → 拒收（fail-closed，不採最後一鍵）",
                   _t2_bad_reg is None and _t2_bad_err is not None
                   and "重複鍵" in str(_t2_bad_err), f"err={_t2_bad_err}")
            _t2_miss = "registry_version: x\nmethods:\n" + "".join(
                f"- {{id: '{i:03d}', mode: excluded, layer: none}}\n"
                for i in range(1, 128))  # 只有 127 條＝漏登
            fcheck("F-CXP-T2-B-b registry 漏登一條（127 條）→ FAIL（Codex 骨架：漏登＝FAIL）",
                   _t2_probe_bad(_t2_miss)[1] is not None, f"err={_t2_probe_bad(_t2_miss)[1]}")
            _t2_badmode = "registry_version: x\nmethods:\n- {id: '001', mode: 亂填, layer: none}\n"
            fcheck("F-CXP-T2-B-c mode 非法 → FAIL（適用項 mode 缺漏＝FAIL，工單 Y2）",
                   _t2_probe_bad(_t2_badmode)[1] is not None)
            fcheck("F-CXP-T2-B-d registry 檔不存在 → FAIL 不是放行",
                   _t2r.load_registry(force_reload=True,
                                      path=Path("/nonexistent/no_registry.yaml"))[1] is not None)
            _t2r.load_registry(force_reload=True)  # 還原正式 registry 快取

            # ── C-CXP-COVERAGE 兩個方向 ──

            # ── C-CXP-RECEIPT 正反例 ──
            _t2_doc_base = {
                "title": "買方說喜歡不代表簽得下去",
                "scenes": [{"timestamp": "0-3s", "type": "Hook",
                            "台詞_瑞祥": "喜歡是感覺，付款是條件。"}],
            }

            # r3／H2：合規 receipt 現在要求 registry_version＋11 條 always 交代
            #        ＋source_artifact_hashes／receipt_hash（新鮮度錨）。
            #        這個 helper 產「完整合規」的 receipt，供正例使用。
            _t2_always = _t2r.always_applicable_ids(_t2_reg)

            def _t2_full_receipt(doc: dict, used_items: list, **over):
                """把 doc 補成 r3 合規：receipt 欄齊＋hash 新鮮。回新 dict。"""
                rc = {
                    "registry_version": _t2r._REGISTRY_VERSION_EXPECTED,
                    "applicable_ids": [],
                    "used": used_items,
                    "waiver": {i: f"本支未用 #{i}（fixtures 申報）" for i in _t2_always},
                    "source_artifact_hashes": {},
                }
                rc.update(over)
                out = dict(doc, chxp_receipt=rc)
                if "receipt_hash" not in over:
                    rc["receipt_hash"] = _t2r.compute_receipt_hash(out)
                return out

            _t2_ok_doc = _t2_full_receipt(
                _t2_doc_base, [{"method_id": "069", "evidence_ref": "quote:喜歡是感覺"}])
            fcheck("F-CXP-T2-RC-a receipt 正例：合法 id＋quote 證據解得回 → PASS",
                   chk_cxp_receipt(_t2_ok_doc, "t2.yaml", enforce_generation=True)[0] == "PASS",
                   f"got={chk_cxp_receipt(_t2_ok_doc, 't2.yaml', enforce_generation=True)}")
            _t2_no_receipt = chk_cxp_receipt(dict(_t2_doc_base), "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-RC-b receipt 反例：新世代整欄缺 → FAIL（不填不得換免查）",
                   _t2_no_receipt[0] == "FAIL" and "缺 chxp_receipt" in _t2_no_receipt[1],
                   f"got={_t2_no_receipt}")
            _t2_unknown = chk_cxp_receipt(
                dict(_t2_doc_base, chxp_receipt={"used": [{"method_id": "999",
                                                           "evidence_ref": "quote:喜歡是感覺"}]}),
                "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-RC-c receipt 反例：未知 method_id=999 → FAIL（工單 Y2 未知 ID）",
                   _t2_unknown[0] == "FAIL" and "未知 ID" in _t2_unknown[1], f"got={_t2_unknown}")
            _t2_badev = chk_cxp_receipt(
                dict(_t2_doc_base, chxp_receipt={"used": [{"method_id": "069",
                                                           "evidence_ref": "quote:這句稿裡根本沒有"}]}),
                "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-RC-d receipt 反例：quote 證據在稿內找不到 → FAIL（宣告必須兌現）",
                   _t2_badev[0] == "FAIL" and "找不到" in _t2_badev[1], f"got={_t2_badev}")
            _t2_freeev = chk_cxp_receipt(
                dict(_t2_doc_base, chxp_receipt={"used": [{"method_id": "069",
                                                           "evidence_ref": "我有用啊"}]}),
                "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-RC-e receipt 反例：自由文字證據（非 path:/quote:）→ FAIL",
                   _t2_freeev[0] == "FAIL", f"got={_t2_freeev}")
            # 自我兌現防線（本輪 fixtures 抓到的真缺陷，修根因後上鎖）：
            #   quote: 比對必須排除 chxp_receipt／chxp_method_selection 自身，
            #   否則「證據字串本身就在 data 裡」＝任何 quote 都能找到自己。
            _t2_selfref = chk_cxp_receipt(
                dict(_t2_doc_base, chxp_receipt={"used": [{"method_id": "069",
                                                           "evidence_ref": "quote:這串只出現在證據欄本身"}]}),
                "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-RC-e2 反例：quote 只出現在 receipt 自己那行 → FAIL（防證據自我兌現）",
                   _t2_selfref[0] == "FAIL", f"got={_t2_selfref}")
            fcheck("F-CXP-T2-RC-e3 正向鎖：排除 receipt 後，稿件本文的 quote 仍找得到（沒排過頭）",
                   _t2r.resolve_evidence_ref(_t2_ok_doc, "quote:喜歡是感覺")[0] is True,
                   f"got={_t2r.resolve_evidence_ref(_t2_ok_doc, 'quote:喜歡是感覺')}")
            _t2_blocked = chk_cxp_receipt(
                dict(_t2_doc_base, chxp_receipt={"used": [{"method_id": "058",
                                                           "evidence_ref": "quote:喜歡是感覺"}]}),
                "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-RC-f receipt 反例：拿 BLOCKED 的 #058 在稿內冒稱完成 → FAIL",
                   _t2_blocked[0] == "FAIL" and "BLOCKED" in _t2_blocked[1], f"got={_t2_blocked}")
            _t2_manual = chk_cxp_receipt(
                dict(_t2_doc_base, chxp_receipt={"used": [{"method_id": "021",
                                                           "evidence_ref": "quote:喜歡是感覺"}]}),
                "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-RC-g receipt 反例：拿人工層 #021 在稿內冒稱完成 → FAIL（系統零自動對外）",
                   _t2_manual[0] == "FAIL" and "人工清單層" in _t2_manual[1], f"got={_t2_manual}")
            _t2_rc_leg = chk_cxp_receipt(dict(_t2_doc_base), "t2.yaml", enforce_generation=False)
            fcheck("F-CXP-T2-RC-h receipt 零誤殺：舊稿世代缺欄 → SKIP 明標，不打紅",
                   _t2_rc_leg[0] == "SKIP" and "grandfather" in _t2_rc_leg[1], f"got={_t2_rc_leg}")
            _t2_rc_skel = chk_cxp_receipt(
                dict(_t2_doc_base, title="[編劇填]"), "t2.yaml",
                enforce_generation=True, is_skeleton_file=True)
            fcheck("F-CXP-T2-RC-i receipt 骨架階段（title 仍 placeholder）→ SKIP，填完即 fail-closed",
                   _t2_rc_skel[0] == "SKIP", f"got={_t2_rc_skel}")

            # ── 8 個硬閘：**每閘正反例**（工單 Y5 明列）──

            _t2_sel = "chxp_method_selection"
            # #041 演劇情三式（enum＋段落安排＋證據）
            _d041_ok = dict(_t2_doc_base, **{_t2_sel: {"041": {"type": "POV", "段落安排": "起承轉合"}}},
                            chxp_receipt={"used": [{"method_id": "041",
                                                    "evidence_ref": "path:chxp_method_selection.041.段落安排"}]})
            _d041_bad = dict(_t2_doc_base, **{_t2_sel: {"041": {"type": "POV"}}})
            _d041_enum = dict(_t2_doc_base, **{_t2_sel: {"041": {"type": "我自己想的型", "段落安排": "x"}}})
            # #053 懷舊（bool_true）
            _d053_ok = dict(_t2_doc_base, **{_t2_sel: {"053": {"used": True, "回憶點": "卡帶隨身聽"}}},
                            chxp_receipt={"used": [{"method_id": "053",
                                                    "evidence_ref": "path:chxp_method_selection.053.回憶點"}]})
            # #055 荷爾蒙／氣氛（enum＋同意紀錄）
            _d055_ok = dict(_t2_doc_base, **{_t2_sel: {"055": {"type": "氣氛", "同意紀錄": "2026-08-13 口頭同意，存 LINE"}}},
                            chxp_receipt={"used": [{"method_id": "055",
                                                    "evidence_ref": "path:chxp_method_selection.055.同意紀錄"}]})
            # #064 行業揭秘（兩必填欄）
            _d064_ok = dict(_t2_doc_base, **{_t2_sel: {"064": {"used": True, "不為人知的規則": "斡旋可退",
                                                              "原因": "定金性質不同"}}},
                            chxp_receipt={"used": [{"method_id": "064",
                                                    "evidence_ref": "path:chxp_method_selection.064.原因"}]})
            # #068 正／反推
            _d068_ok = dict(_t2_doc_base, **{_t2_sel: {"068": {"type": "反推", "理由": "屋況差",
                                                              "結論": "先不要買"}}},
                            chxp_receipt={"used": [{"method_id": "068",
                                                    "evidence_ref": "path:chxp_method_selection.068.結論"}]})
            # #069 資訊整理
            _d069_ok = dict(_t2_doc_base, **{_t2_sel: {"069": {"used": True, "分類": "三類",
                                                              "順序": "由近到遠"}}},
                            chxp_receipt={"used": [{"method_id": "069", "evidence_ref": "quote:喜歡是感覺"}]})
            # #101 記錄不創造（sources 非空）
            _d101_ok = dict(_t2_doc_base, **{_t2_sel: {"101": {"mode": "整理既有資料",
                                                              "sources": ["內政部實價登錄 2026Q2"]}}},
                            chxp_receipt={"used": [{"method_id": "101",
                                                    "evidence_ref": "path:chxp_method_selection.101.sources"}]})
            # #103 字數區間（唯一數值型；龍蝦 R2 收緊：只 60 秒、只新世代）
            def _mk103(n_chars: int, dur="60s"):
                return {"title": "t", "duration": dur,
                        "scenes": [{"timestamp": "0-3s", "type": "Hook",
                                    "台詞_瑞祥": "字" * n_chars,
                                    "畫面": "拍攝指示不計字" * 20,
                                    "翠文": "字幕也不計字" * 10}]}
            fcheck("F-CXP-T2-G103-g 計字契約：畫面／翠文不計入口白字數（只算唸出來的）",
                   _t2r.count_chinese_chars(_t2r.script_body_text(_mk103(270))) == 270,
                   f"n={_t2r.count_chinese_chars(_t2r.script_body_text(_mk103(270)))}")

            # ── applicable_ids 由機器重算（龍蝦：不准編劇自填 N/A）──
            _t2_comp = _t2r.compute_applicable_ids(_d069_ok, _t2_reg)
            fcheck("F-CXP-T2-A-a 機器重算：選了 069 → 069 在 applicable_ids 內",
                   "069" in _t2_comp, f"computed={_t2_comp[:8]}")
            _t2_comp_none = _t2r.compute_applicable_ids(dict(_t2_doc_base), _t2_reg)
            fcheck("F-CXP-T2-A-b 機器重算：沒選任何型 → 只剩 always 條（069 不在內）",
                   "069" not in _t2_comp_none and len(_t2_comp_none) > 0,
                   f"computed={_t2_comp_none[:8]}")
            _t2_lie = chk_cxp_receipt(
                dict(_d069_ok, chxp_receipt={"applicable_ids": ["999"],
                                             "used": [{"method_id": "069",
                                                       "evidence_ref": "quote:喜歡是感覺"}]}),
                "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-A-c 稿內自填 applicable_ids 與機器重算不符 → 標明「以機器重算為準」（不採信稿內）",
                   "以機器重算為準" in _t2_lie[1], f"got={_t2_lie}")

            # ── registry 不可用時的 fail-closed（不假裝八個閘跑過）──
            _t2_saved_ok = _CHXP_OK
            try:
                globals()["_CHXP_OK"] = False
            finally:
                globals()["_CHXP_OK"] = _t2_saved_ok

            # ════════════════════════════════════════════
            # F-CXP-T2-R3（r3，2026-08-14）：Codex 終審三阻擋的回歸鎖
            #   每一組都對應一個「r1 會放行、r3 必須翻紅」的實測案例。
            #   🔴 任一件轉綠→紅或紅→綠，代表阻擋修補被改壞，停手回滾。
            # ════════════════════════════════════════════
            print("\n[F-CXP-T2-R3] r3 三阻擋回歸鎖（Codex 終審變造案例）")

            def _t2_reg_mutate(mut):
                """回傳被變造的 registry 深拷貝（唯讀，不寫檔）。"""
                import copy as _cp
                r = _cp.deepcopy(_t2_reg)
                mut(r)
                return r

            def _t2_with_reg(reg, fn):
                """把 loader 快取換成變造版跑一次 fn，跑完還原。"""
                _saved = _t2r._REGISTRY_CACHE
                try:
                    _t2r._REGISTRY_CACHE = (reg, None)
                    return fn()
                finally:
                    _t2r._REGISTRY_CACHE = _saved
                    _t2r.load_registry(force_reload=True)

            # ── H1① 分層／計數變造：三個 Codex 實測案例全部要翻 FAIL ──
            def _mut_excluded_minus1(r):
                for m in r["methods"]:
                    if m["mode"] == "excluded":
                        m["mode"] = "audited"
                        break


            def _mut_041_downgrade(r):
                for m in r["methods"]:
                    if m["id"] == "041":
                        m["layer"] = "none"
                        m.pop("gate", None)


            def _mut_058_unblock(r):
                for m in r["methods"]:
                    if m["id"] == "058":
                        m["layer"] = "none"


            def _mut_swap_gate(r):
                """等量替換：#041 降級、另抓一條 none 升級成 gate（總數仍 8）。"""
                for m in r["methods"]:
                    if m["id"] == "041":
                        m["layer"] = "none"
                    elif m["id"] == "042":
                        m["layer"] = "gate"
                        m["gate"] = {"check_id": "C-CXP-042",
                                     "trigger": {"kind": "bool_true",
                                                 "field": "chxp_method_selection.042.used"}}


            # ── H1② gate schema 變造 ──
            def _mut_gate_schema_broken(r):
                for m in r["methods"]:
                    if m["id"] == "069":
                        m["gate"]["trigger"] = {"kind": "亂填", "field": "x"}


            def _mut_gate_enum_empty(r):
                for m in r["methods"]:
                    if m["id"] == "041":
                        m["gate"]["trigger"]["enum"] = []


            def _mut_charcount_broken(r):
                for m in r["methods"]:
                    if m["id"] == "103":
                        m["gate"]["char_count"] = {"min": "240", "max": 300}


            # ── H1③ registry 內容 hash 錨定 ──
            fcheck("F-CXP-T2-R3-H1 正式 registry 內容 hash 與 sidecar 相符 → PASS",
                   _t2r.check_registry_hash()[0] == "PASS", f"got={_t2r.check_registry_hash()}")
            _r3_tmpd = Path(_w1_tmp.mkdtemp())
            _r3_reg_copy = _r3_tmpd / _t2r._REGISTRY_PATH.name
            _r3_reg_copy.write_text(
                _t2r._REGISTRY_PATH.read_text(encoding="utf-8").replace(
                    "registry_owner: 霸告", "registry_owner: 我自己"), encoding="utf-8")
            (_r3_tmpd / _t2r._REGISTRY_SHA_SIDECAR_NAME).write_text(
                (_t2r._REGISTRY_PATH.parent / _t2r._REGISTRY_SHA_SIDECAR_NAME).read_text(encoding="utf-8"),
                encoding="utf-8")
            fcheck("F-CXP-T2-R3-H2 registry 內容被改、sidecar 未同步 → FAIL（內容 hash 錨定）",
                   _t2r.check_registry_hash(_r3_reg_copy)[0] == "FAIL",
                   f"got={_t2r.check_registry_hash(_r3_reg_copy)}")
            _r3_nosidecar = Path(_w1_tmp.mkdtemp()) / "chxp_method_registry.yaml"
            _r3_nosidecar.write_text("registry_version: x\n", encoding="utf-8")
            fcheck("F-CXP-T2-R3-H3 sidecar 不存在 → FAIL（未錨定＝不得放行）",
                   _t2r.check_registry_hash(_r3_nosidecar)[0] == "FAIL")
            _r3_badside = Path(_w1_tmp.mkdtemp())
            (_r3_badside / "chxp_method_registry.yaml").write_text("x: 1\n", encoding="utf-8")
            (_r3_badside / _t2r._REGISTRY_SHA_SIDECAR_NAME).write_text("不是 hash\n", encoding="utf-8")
            fcheck("F-CXP-T2-R3-H4 sidecar 內容非 sha256 格式 → FAIL",
                   _t2r.check_registry_hash(_r3_badside / "chxp_method_registry.yaml")[0] == "FAIL")

            # ── H1④ 真實版本鏈（雙向 grace）──
            fcheck("F-CXP-T2-R3-V1 current=totally-unrelated＋previous 正確 → FAIL"
                   "（r1 誤判 WARN：亂填版本附個正確 previous 就能矇混）",
                   _t2r.check_version({"registry_version": "totally-unrelated",
                                       "previous_version": _t2r._REGISTRY_VERSION_EXPECTED})[0] == "FAIL",
                   f"got={_t2r.check_version({'registry_version': 'totally-unrelated', 'previous_version': _t2r._REGISTRY_VERSION_EXPECTED})}")
            fcheck("F-CXP-T2-R3-V2 前進一版且版本鏈接得上（v2/previous=v1）→ WARN grace",
                   _t2r.check_version({"registry_version": "chxp-128-v2",
                                       "previous_version": "chxp-128-v1"})[0] == "WARN")
            fcheck("F-CXP-T2-R3-V3 前進一版但版本鏈斷（v2/previous=別的）→ FAIL",
                   _t2r.check_version({"registry_version": "chxp-128-v2",
                                       "previous_version": "chxp-999-v1"})[0] == "FAIL",
                   f"got={_t2r.check_version({'registry_version': 'chxp-128-v2', 'previous_version': 'chxp-999-v1'})}")
            fcheck("F-CXP-T2-R3-V4 **反向** grace：registry 落後一版（v0）→ WARN（雙向 grace）",
                   _t2r.check_version({"registry_version": "chxp-128-v0"})[0] == "WARN",
                   f"got={_t2r.check_version({'registry_version': 'chxp-128-v0'})}")
            fcheck("F-CXP-T2-R3-V5 family 不同（other-128-v1）→ FAIL（不是相鄰版本）",
                   _t2r.check_version({"registry_version": "other-128-v1",
                                       "previous_version": "chxp-128-v1"})[0] == "FAIL")
            fcheck("F-CXP-T2-R3-V6 差兩版（v3）→ FAIL",
                   _t2r.check_version({"registry_version": "chxp-128-v3",
                                       "previous_version": "chxp-128-v2"})[0] == "FAIL")

            # ── H2 receipt 收緊：Codex 三個空帳案例全部要翻 FAIL ──
            _r3_empty = chk_cxp_receipt(dict(_t2_doc_base, chxp_receipt={}),
                                        "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-R3-B1 chxp_receipt: {} 缺 used 鍵 → FAIL（r1 為 PASS：缺鍵被轉空陣列）",
                   _r3_empty[0] == "FAIL" and "缺 used 鍵" in _r3_empty[1], f"got={_r3_empty}")
            _r3_explicit_empty = _t2_full_receipt(_t2_doc_base, [])
            fcheck("F-CXP-T2-R3-B2 顯式 used: [] ＋ waiver 交代 11 條 → PASS（空列表允許，但要申報）",
                   chk_cxp_receipt(_r3_explicit_empty, "t2.yaml", enforce_generation=True)[0] == "PASS",
                   f"got={chk_cxp_receipt(_r3_explicit_empty, 't2.yaml', enforce_generation=True)}")
            _r3_badver = _t2_full_receipt(
                _t2_doc_base, [{"method_id": "069", "evidence_ref": "quote:喜歡是感覺"}],
                registry_version="garbage")
            fcheck("F-CXP-T2-R3-B3 receipt.registry_version=garbage → FAIL（r1 不驗此欄）",
                   chk_cxp_receipt(_r3_badver, "t2.yaml", enforce_generation=True)[0] == "FAIL",
                   f"got={chk_cxp_receipt(_r3_badver, 't2.yaml', enforce_generation=True)}")
            _r3_unknown_app = _t2_full_receipt(_t2_doc_base, [], applicable_ids=["999"])
            _r3_ua = chk_cxp_receipt(_r3_unknown_app, "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-R3-B4 applicable_ids 含未知 id \"999\" → FAIL（r1 為 PASS：只當留痕）",
                   _r3_ua[0] == "FAIL" and "未知 method_id" in _r3_ua[1], f"got={_r3_ua}")
            _r3_noalways = dict(_t2_doc_base, chxp_receipt={
                "registry_version": _t2r._REGISTRY_VERSION_EXPECTED,
                "used": [{"method_id": "069", "evidence_ref": "quote:喜歡是感覺"}],
                "source_artifact_hashes": {}, "receipt_hash": "0" * 64})
            _r3_na = chk_cxp_receipt(_r3_noalways, "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-R3-B5 11 條 always 全未申報（無 waiver）→ FAIL（只驗有無申報，不判品質）",
                   _r3_na[0] == "FAIL" and "always-applicable 未交代" in _r3_na[1], f"got={_r3_na}")
            _r3_partial_waiver = _t2_full_receipt(_t2_doc_base, [])
            _r3_partial_waiver["chxp_receipt"]["waiver"].pop(_t2_always[0])
            _r3_partial_waiver["chxp_receipt"]["receipt_hash"] = _t2r.compute_receipt_hash(_r3_partial_waiver)
            fcheck("F-CXP-T2-R3-B6 always 只漏交代一條 → 仍 FAIL（逐條驗，不是抽樣）",
                   chk_cxp_receipt(_r3_partial_waiver, "t2.yaml", enforce_generation=True)[0] == "FAIL")
            _r3_used_always = _t2_full_receipt(
                _t2_doc_base, [{"method_id": _t2_always[0], "evidence_ref": "quote:喜歡是感覺"}])
            _r3_used_always["chxp_receipt"]["waiver"].pop(_t2_always[0])
            _r3_used_always["chxp_receipt"]["receipt_hash"] = _t2r.compute_receipt_hash(_r3_used_always)
            fcheck("F-CXP-T2-R3-B7 always 條在 used 具名（非 waiver）也算交代 → PASS",
                   chk_cxp_receipt(_r3_used_always, "t2.yaml", enforce_generation=True)[0] == "PASS",
                   f"got={chk_cxp_receipt(_r3_used_always, 't2.yaml', enforce_generation=True)}")
            _r3_stale = _t2_full_receipt(_t2_doc_base, [])
            _r3_stale["title"] = "改過標題但沒重算收據"
            fcheck("F-CXP-T2-R3-B8 稿件改過、receipt_hash 未重算 → FAIL（新鮮度）",
                   chk_cxp_receipt(_r3_stale, "t2.yaml", enforce_generation=True)[0] == "FAIL",
                   f"got={chk_cxp_receipt(_r3_stale, 't2.yaml', enforce_generation=True)}")
            _r3_nohash = _t2_full_receipt(_t2_doc_base, [], receipt_hash=None)
            fcheck("F-CXP-T2-R3-B9 缺 receipt_hash 欄 → FAIL（得標骨架欄，不得省略）",
                   chk_cxp_receipt(_r3_nohash, "t2.yaml", enforce_generation=True)[0] == "FAIL")
            _r3_badsah = _t2_full_receipt(_t2_doc_base, [],
                                          source_artifact_hashes={"src.md": "not-a-hash"})
            fcheck("F-CXP-T2-R3-B10 source_artifact_hashes 值非 sha256 → FAIL（格式驗）",
                   chk_cxp_receipt(_r3_badsah, "t2.yaml", enforce_generation=True)[0] == "FAIL")
            # receipt 自指（Codex：path:chxp_receipt.used 讓 RECEIPT 與 069 同時 PASS）
            _r3_selfpath = _t2_full_receipt(
                _t2_doc_base, [{"method_id": "069", "evidence_ref": "path:chxp_receipt.used"}])
            fcheck("F-CXP-T2-R3-B11 證據自指 path:chxp_receipt.used → FAIL（收據不能當自己的證據）",
                   chk_cxp_receipt(_r3_selfpath, "t2.yaml", enforce_generation=True)[0] == "FAIL",
                   f"got={chk_cxp_receipt(_r3_selfpath, 't2.yaml', enforce_generation=True)}")
            _r3_selfpath2 = _t2_full_receipt(
                _t2_doc_base, [{"method_id": "069",
                                "evidence_ref": "path:chxp_receipt.registry_version"}])
            fcheck("F-CXP-T2-R3-B12 證據指向 receipt 其他欄（registry_version）→ FAIL（同一自我兌現家族）",
                   chk_cxp_receipt(_r3_selfpath2, "t2.yaml", enforce_generation=True)[0] == "FAIL")

            # ── H3 兩段式 fail-open：malformed bool 與空白 list ──
            for _r3_mid in ("053", "064", "069"):
                _r3_doc = dict(_t2_doc_base,
                               **{_t2_sel: {_r3_mid: {"used": "true"}}})
            for _r3_bad, _r3_label in (([None], "[null]"), ([""], '[""]'),
                                       (["[編劇填]"], '["[編劇填]"]'),
                                       (["  "], '["  "]（全空白）')):
                _r3_doc = dict(_t2_doc_base,
                               **{_t2_sel: {"101": {"mode": "整理既有資料", "sources": _r3_bad}}})

            # ── r3 零誤殺方向鎖（新增檢查一律不得追殺舊稿）──
            fcheck("F-CXP-T2-R3-Z3 舊稿世代：receipt 缺 used 鍵仍 SKIP",
                   chk_cxp_receipt(dict(_t2_doc_base, chxp_receipt={}),
                                   "t2.yaml", enforce_generation=False)[0] == "SKIP")

            # ════════════════════════════════════════════
            # F-CXP-T2-R4（r4，2026-08-14）：Codex 覆審殘項 J1-J5 的回歸鎖
            #   每件對應一個「r3 會放行、r4 必須翻紅」的實測案例
            #   （before/after 逐案證據＝probe_r4_before.txt／probe_r4_after.txt）。
            #   🔴 任一件轉綠→紅或紅→綠，代表殘項修補被改壞，停手回滾。
            # ════════════════════════════════════════════
            print("\n[F-CXP-T2-R4] r4 覆審殘項回歸鎖（Codex r3 新問題 J1-J5）")

            # ── J1：#058／人工／excluded 的**單因** receipt 路徑 ──
            #   🔴 單因驗證＝其他欄位全部合規（版本對、waiver 11 條齊、兩個 hash
            #      欄齊且新鮮），只多一條該 id，看它會不會**單獨**翻紅。
            #      r3 的 probe 是因為缺版本／waiver／hash 才 FAIL，沒真正驗到 #058。
            _r4_ctrl = _t2_full_receipt(_t2_doc_base, [])
            fcheck("F-CXP-T2-R4-J1a 單因對照組：全合規空 used → PASS（證明其他欄位確實都合規）",
                   chk_cxp_receipt(_r4_ctrl, "t2.yaml", enforce_generation=True)[0] == "PASS",
                   f"got={chk_cxp_receipt(_r4_ctrl, 't2.yaml', enforce_generation=True)}")

            def _r4_single(mid: str):
                return chk_cxp_receipt(
                    _t2_full_receipt(_t2_doc_base,
                                     [{"method_id": mid, "evidence_ref": "quote:喜歡是感覺"}]),
                    "t2.yaml", enforce_generation=True)

            _r4_j1b = _r4_single("058")
            fcheck("F-CXP-T2-R4-J1b 全合規＋只多 #058（BLOCKED）→ 單獨 FAIL"
                   "（r3 需靠其他欄位一起壞才紅）",
                   _r4_j1b[0] == "FAIL" and "BLOCKED" in _r4_j1b[1]
                   and "單獨成立即 FAIL" in _r4_j1b[1], f"got={_r4_j1b}")
            _r4_j1c = _r4_single("021")
            fcheck("F-CXP-T2-R4-J1c 全合規＋只多 #021（人工層）→ 單獨 FAIL",
                   _r4_j1c[0] == "FAIL" and "人工清單層" in _r4_j1c[1], f"got={_r4_j1c}")
            _r4_j1d = _r4_single("001")
            fcheck("F-CXP-T2-R4-J1d 全合規＋只多 #001（excluded 刻意不做）→ FAIL"
                   "（r3 為 PASS：excluded 身分完全沒驗）",
                   _r4_j1d[0] == "FAIL" and "excluded" in _r4_j1d[1], f"got={_r4_j1d}")

            def _mut_058_none(r):
                for m in r["methods"]:
                    if m["id"] == "058":
                        m["layer"] = "none"

            fcheck("F-CXP-T2-R4-J1e registry 變造 #058→none 後，冒稱 #058 仍 FAIL"
                   "（身分以程式端常數為準，r3 是讀 registry 的 layer 欄故一起消失）",
                   _t2_with_reg(_t2_reg_mutate(_mut_058_none),
                                lambda: _r4_single("058"))[0] == "FAIL",
                   f"got={_t2_with_reg(_t2_reg_mutate(_mut_058_none), lambda: _r4_single('058'))}")

            # ── J2：WARN-grace 語意（底層 WARN 不得被吞成 PASS；對照實際載入版本）──
            _r4_live = (_t2_reg or {}).get("registry_version")

            def _r4_ver(ver: str):
                return chk_cxp_receipt(_t2_full_receipt(_t2_doc_base, [], registry_version=ver),
                                       "t2.yaml", enforce_generation=True)

            fcheck("F-CXP-T2-R4-J2a receipt 版本＝實際載入版本 → PASS",
                   _r4_ver(_r4_live)[0] == "PASS", f"got={_r4_ver(_r4_live)}")
            # 🔴 r5／K1 修正：J2b 原本把「未來一版」鎖成 WARN，與工單契約相反
            #    （契約＝「前一版 WARN、其他 FAIL」）。收據宣稱一個還沒發布的
            #    正典版本不是時間差，是造假或工具鏈錯亂，沒有 grace 的理由。
            #    期望改為 FAIL；WARN 的唯一正路移到 J2c（現役宣告的 previous_version）。
            _r4_j2b = _r4_ver("chxp-128-v2")
            fcheck("F-CXP-T2-R5-K1a receipt 版本＝現役的**下一版（未來版）**→ **FAIL**"
                   "（r4 為 WARN：abs(diff)==1 把未來版也放進 grace）",
                   _r4_j2b[0] == "FAIL" and "未來版" in _r4_j2b[1], f"got={_r4_j2b}")
            _r5_prev = (_t2_reg or {}).get("previous_version")
            _r4_j2c = _r4_ver(_r5_prev)
            fcheck("F-CXP-T2-R4-J2c receipt 版本＝現役 registry 宣告的 previous_version → **WARN**"
                   "（唯一的 grace 正路；r3 為 PASS＝底層 WARN 被吞掉）",
                   _r4_j2c[0] == "WARN" and "grace" in _r4_j2c[1],
                   f"prev={_r5_prev} got={_r4_j2c}")
            _r5_k1b = _r4_ver("chxp-128-v0")
            fcheck("F-CXP-T2-R5-K1b receipt 版本＝序號 -1 但**不在版本鏈上**（v0，"
                   f"現役宣告的前一版是 {_r5_prev}）→ **FAIL**"
                   "（r4 為 WARN：只看序號距離，不看版本鏈）",
                   _r5_k1b[0] == "FAIL" and "版本鏈" in _r5_k1b[1], f"got={_r5_k1b}")
            fcheck("F-CXP-T2-R5-K1c receipt 版本＝未來第三版（v4）→ FAIL（跳版＋未來版雙違）",
                   _r4_ver("chxp-128-v4")[0] == "FAIL")
            fcheck("F-CXP-T2-R5-K1d 異 family 同序號（other-128-v1）→ FAIL（不是相鄰版本）",
                   _r4_ver("other-128-v1")[0] == "FAIL")

            def _mut_prev_gone(r):
                r.pop("previous_version", None)

            _r5_k1e = _t2_with_reg(
                _t2_reg_mutate(_mut_prev_gone),
                lambda: chk_cxp_receipt(
                    _t2_full_receipt(_t2_doc_base, [], registry_version="chxp-128-v0"),
                    "t2.yaml", enforce_generation=True))
            fcheck("F-CXP-T2-R5-K1e 現役 registry 缺 previous_version → 沒有可信前一版錨 → FAIL"
                   "（fail-closed，不得因為缺錨就放寬）",
                   _r5_k1e[0] == "FAIL", f"got={_r5_k1e}")
            fcheck("F-CXP-T2-R5-K1f 正向鎖：版本完全相同時，缺 previous_version 仍 PASS"
                   "（K1 只收緊 grace，不誤傷 match 路徑）",
                   _t2_with_reg(
                       _t2_reg_mutate(_mut_prev_gone),
                       lambda: chk_cxp_receipt(
                           _t2_full_receipt(_t2_doc_base, [], registry_version=_r4_live),
                           "t2.yaml", enforce_generation=True))[0] == "PASS")
            fcheck("F-CXP-T2-R4-J2d receipt 版本差兩版（v3）→ FAIL",
                   _r4_ver("chxp-128-v3")[0] == "FAIL")
            fcheck("F-CXP-T2-R4-J2e receipt 版本 garbage → FAIL",
                   _r4_ver("garbage")[0] == "FAIL")
            fcheck("F-CXP-T2-R4-J2f receipt 缺 registry_version 欄 → FAIL（不得靠沒填躲過）",
                   chk_cxp_receipt(_t2_full_receipt(_t2_doc_base, [], registry_version=None),
                                   "t2.yaml", enforce_generation=True)[0] == "FAIL")
            fcheck("F-CXP-T2-R4-J2g registry_version 填 YAML false（型別繞過）→ FAIL",
                   chk_cxp_receipt(_t2_full_receipt(_t2_doc_base, [], registry_version=False),
                                   "t2.yaml", enforce_generation=True)[0] == "FAIL")

            # ── J3：schema 收緊（check_id 白名單／require_fields 空／身分互換）──
            def _mut_cid(new_cid: str):
                def _f(r):
                    for m in r["methods"]:
                        if m["id"] == "041":
                            m["gate"]["check_id"] = new_cid
                return _f


            def _mut_rf_empty(r):
                for m in r["methods"]:
                    if m["id"] == "041":
                        m["gate"]["require_fields"] = []


            def _mut_mode_swap(r):
                """always／audited 身分等量互換（#010↔#018）：兩邊計數都不動。"""
                for m in r["methods"]:
                    if m["id"] == "010":
                        m["mode"] = "audited"
                    elif m["id"] == "018":
                        m["mode"] = "always"


            def _mut_excl_swap(r):
                """excluded 身分等量互換（#001↔#043）：excluded 仍 34 條。"""
                for m in r["methods"]:
                    if m["id"] == "001":
                        m["mode"] = "audited"
                    elif m["id"] == "043":
                        m["mode"] = "excluded"
                        m["excluded_reason"] = "fixture 變造"

            # id↔mode 映射錨本身的正反例
            fcheck("F-CXP-T2-R4-J3f 正式 registry 的 id↔mode 映射 hash 對得上 sidecar → PASS",
                   _t2r.check_id_mode_map(_t2_reg)[0] == "PASS",
                   f"got={_t2r.check_id_mode_map(_t2_reg)}")
            fcheck("F-CXP-T2-R4-J3g 身分互換後映射 hash 必變（同一份 registry 兩個值不相等）",
                   _t2r.id_mode_map_sha256(_t2_reg)
                   != _t2r.id_mode_map_sha256(_t2_reg_mutate(_mut_mode_swap)))
            _r4_nomap = Path(_w1_tmp.mkdtemp())
            (_r4_nomap / "chxp_method_registry.yaml").write_text("x: 1\n", encoding="utf-8")
            (_r4_nomap / _t2r._REGISTRY_SHA_SIDECAR_NAME).write_text(
                "0" * 64 + "  chxp_method_registry.yaml\n", encoding="utf-8")
            fcheck("F-CXP-T2-R4-J3h sidecar 只有整檔 hash、缺 id_mode_map_sha256 行 → FAIL",
                   _t2r.check_id_mode_map(
                       _t2_reg, _r4_nomap / "chxp_method_registry.yaml")[0] == "FAIL")

            # ── J4：空值用錯誤型別繞過（單一非空字串驗證器）──
            for _r4_bad, _r4_label in (([False], "[False]"), ([0], "[0]"),
                                       ([0.0], "[0.0]"), ([True], "[True]"),
                                       (False, "scalar False"), (0, "scalar 0")):
                _r4_doc = dict(_t2_doc_base,
                               **{_t2_sel: {"101": {"mode": "整理既有資料",
                                                    "sources": _r4_bad}}},
                               chxp_receipt={"used": [{"method_id": "101",
                                                       "evidence_ref": f"path:{_t2_sel}.101.mode"}]})
            _r4_j4b = chk_cxp_receipt(
                _t2_full_receipt(_t2_doc_base, [],
                                 waiver={i: False for i in _t2_always}),
                "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-R4-J4b 11 條 waiver 理由全填 YAML false → FAIL"
                   "（r3 為 PASS：false 被當有填＝空帳換個型別就過）",
                   _r4_j4b[0] == "FAIL" and "always-applicable 未交代" in _r4_j4b[1],
                   f"got={_r4_j4b}")
            fcheck("F-CXP-T2-R4-J4c 11 條 waiver 理由全填 0 → FAIL（同一型別家族）",
                   chk_cxp_receipt(
                       _t2_full_receipt(_t2_doc_base, [],
                                        waiver={i: 0 for i in _t2_always}),
                       "t2.yaml", enforce_generation=True)[0] == "FAIL")
            fcheck("F-CXP-T2-R4-J4d waiver list 形式的 reason 填 false → FAIL",
                   chk_cxp_receipt(
                       _t2_full_receipt(_t2_doc_base, [],
                                        waiver=[{"method_id": i, "reason": False}
                                                for i in _t2_always]),
                       "t2.yaml", enforce_generation=True)[0] == "FAIL")
            # 單一驗證器的直接單元鎖（禁止各欄自寫判定 → 全走這一個函式）
            for _r4_v, _r4_expect in ((None, False), (False, False), (True, False),
                                      (0, False), (1, False), (0.0, False),
                                      ("", False), ("   ", False), ("[編劇填]", False),
                                      ("[編劇填來源]", False), ([], False), ({}, False),
                                      ("內政部實價登錄", True), (" 有內容 ", True)):
                fcheck(f"F-CXP-T2-R4-J4e is_nonempty_text({_r4_v!r}) == {_r4_expect}",
                       _t2r.is_nonempty_text(_r4_v) is _r4_expect
                       if not isinstance(_r4_v, (list, dict))
                       else _t2r.is_nonempty_text(_r4_v) is False)
            fcheck("F-CXP-T2-R4-J4f 正向鎖：容器仍看內容（混合清單一空一實 → 有填）",
                   _t2r._is_filled([None, False, "內政部實價登錄"]) is True)

            # ── J5：--stamp 對非法現值：報錯拒 stamp、不寫檔 ──
            import subprocess as _r4_sp

            def _r4_stamp(hash_line: str, tag: str):
                _p = Path(_w1_tmp.mkdtemp()) / f"{tag}.yaml"
                _p.write_text(
                    "title: t\nscenes:\n"
                    "- {timestamp: 0-3s, type: Hook, 台詞_瑞祥: 喜歡是感覺}\n"
                    f"chxp_receipt:\n  used: []\n  {hash_line}\n", encoding="utf-8")
                _before = _p.read_text(encoding="utf-8")
                _r = _r4_sp.run([sys.executable, str(_t2r.__file__), "--stamp", str(_p)],
                                capture_output=True, text=True)
                _after = _p.read_text(encoding="utf-8")
                _val = ""
                for _ln in _after.splitlines():
                    if "receipt_hash" in _ln:
                        _val = _ln.split(":", 1)[1].strip().split("#")[0].strip().strip('"\'')
                return _r.returncode, (_after == _before), _val

            _rc, _unchanged, _val = _r4_stamp("receipt_hash: NOT_A_HASH", "bad")
            fcheck("F-CXP-T2-R4-J5a --stamp 遇非法現值 NOT_A_HASH → 報錯拒 stamp、**不寫檔**"
                   "（r3：寫成 \"<64hash>\"NOT_A_HASH 還回報成功）",
                   _rc == 2 and _unchanged and _val == "NOT_A_HASH",
                   f"rc={_rc} unchanged={_unchanged} val={_val!r}")
            _rc, _unchanged, _val = _r4_stamp("receipt_hash: abc123", "shorthex")
            fcheck("F-CXP-T2-R4-J5b --stamp 遇短 hex（abc123）→ 拒 stamp、不寫檔"
                   "（r3：{0,64} 零長匹配把它寫成 \"<64hash>\"abc123）",
                   _rc == 2 and _unchanged and _val == "abc123",
                   f"rc={_rc} unchanged={_unchanged} val={_val!r}")
            _rc, _unchanged, _val = _r4_stamp(f'receipt_hash: "{"a" * 64}xx"', "tail")
            fcheck("F-CXP-T2-R4-J5c --stamp 遇 64hex 後多兩字 → 拒 stamp、不寫檔（鎖到行尾）",
                   _rc == 2 and _unchanged, f"rc={_rc} unchanged={_unchanged} val={_val!r}")
            _rc, _unchanged, _val = _r4_stamp('receipt_hash: ""', "empty")
            fcheck("F-CXP-T2-R4-J5d 正向鎖：空值起點 → stamp 成功寫入合法 64 hex",
                   _rc == 0 and not _unchanged and re.fullmatch(r"[0-9a-f]{64}", _val),
                   f"rc={_rc} val={_val!r}")
            _rc, _unchanged, _val = _r4_stamp(f'receipt_hash: "{"0" * 64}"  # 佔位', "zeros")
            fcheck("F-CXP-T2-R4-J5e 正向鎖：骨架 64 個 0 佔位（帶行內註解）→ stamp 成功且註解保留",
                   _rc == 0 and re.fullmatch(r"[0-9a-f]{64}", _val) and _val != "0" * 64,
                   f"rc={_rc} val={_val!r}")

            # ════════════════════════════════════════════
            # F-CXP-T2-R5（r5，2026-08-14）：Codex r4 覆審四微洞 K1-K4
            #   K1 的案例已就地改在上面 J2 區塊（含 3 件期望翻轉）；
            #   以下是 K2（Unicode 清洗）／K3（stamp 行錨定）／K4（sidecar 重複鍵）。
            # ════════════════════════════════════════════
            print("\n[F-CXP-T2-R5] r5 覆審四微洞回歸鎖（Codex r4 新問題 K1-K4）")

            # ── K2：只含零寬／不可見字元的欄位＝沒填 ──
            _r5_invis = [("\u200b", "U+200B 零寬空格"), ("\ufeff", "U+FEFF BOM"),
                         ("\u200c", "U+200C ZWNJ"), ("\u200d", "U+200D ZWJ"),
                         ("\u00a0", "U+00A0 不斷行空格"), ("\u2060", "U+2060 word joiner"),
                         ("\u00ad", "U+00AD 軟連字號"), ("\u3000", "全形空格"),
                         ("\u200b \u200b", "零寬＋一般空白混合"),
                         ("\u200b\ufeff\u200d", "多個零寬串接")]
            for _r5_ch, _r5_name in _r5_invis:
                fcheck(f"F-CXP-T2-R5-K2a is_nonempty_text({_r5_name}) → False"
                       f"（r4 為 True：strip() 動不到零寬字元）",
                       _t2r.is_nonempty_text(_r5_ch) is False,
                       f"got={_t2r.is_nonempty_text(_r5_ch)!r} for {_r5_ch!r}")
            _r5_zw_doc = dict(_t2_doc_base,
                              **{_t2_sel: {"101": {"mode": "整理既有資料",
                                                   "sources": ["\u200b"]}}},
                              chxp_receipt={"used": [{"method_id": "101",
                                                      "evidence_ref": f"path:{_t2_sel}.101.mode"}]})
            _r5_k2c = chk_cxp_receipt(
                _t2_full_receipt(_t2_doc_base, [],
                                 waiver={i: "\u200b" for i in _t2_always}),
                "t2.yaml", enforce_generation=True)
            fcheck("F-CXP-T2-R5-K2c 11 條 waiver 理由全填零寬空格 → FAIL"
                   "（r4 為 PASS：receipt 路徑同樣被零寬字元繞過）",
                   _r5_k2c[0] == "FAIL" and "always-applicable 未交代" in _r5_k2c[1],
                   f"got={_r5_k2c}")
            fcheck("F-CXP-T2-R5-K2d waiver list 形式 reason 填 U+FEFF → FAIL",
                   chk_cxp_receipt(
                       _t2_full_receipt(_t2_doc_base, [],
                                        waiver=[{"method_id": i, "reason": "\ufeff"}
                                                for i in _t2_always]),
                       "t2.yaml", enforce_generation=True)[0] == "FAIL")

            def _mut_excl_reason_zw(r):
                """把一條 excluded 的理由換成零寬字元（K2：理由欄的自寫判定旁路）。"""
                for m in r["methods"]:
                    if m.get("mode") == "excluded":
                        m["excluded_reason"] = "\u200b"
                        break


            def _mut_excl_reason_false(r):
                for m in r["methods"]:
                    if m.get("mode") == "excluded":
                        m["excluded_reason"] = False
                        break

            fcheck("F-CXP-T2-R5-K2g 正向鎖：零寬字元夾在真文字中間仍算有填（沒有矯枉過正）",
                   _t2r.is_nonempty_text("內政部\u200b實價登錄") is True)
            fcheck("F-CXP-T2-R5-K2h 正向鎖：strip_invisible 不改動可見內容",
                   _t2r.strip_invisible("\u200b 內政部 實價登錄 \ufeff") == "內政部 實價登錄")

            # ── K3：--stamp 只准寫 chxp_receipt 區塊內的 receipt_hash 行 ──

            _r5_body_decoy = (
                "title: t\n"
                "scenes:\n"
                "- {timestamp: 0-3s, type: Hook, 台詞_瑞祥: 喜歡是感覺}\n"
                "meta_block:\n"
                "  receipt_hash: \"\"\n"          # ← 誘餌：同名欄但不在 chxp_receipt 內
                "chxp_receipt:\n"
                "  used: []\n"
                "  receipt_hash: \"\"\n"
            )
            _r5_meta_val = ""
            _r5_rc_val = ""
            _r5_in_receipt = False

            _r5_body_nohash = (
                "title: t\n"
                "scenes:\n"
                "- {timestamp: 0-3s, type: Hook, 台詞_瑞祥: 喜歡是感覺}\n"
                "meta_block:\n"
                "  receipt_hash: \"\"\n"
                "chxp_receipt:\n"
                "  used: []\n"
            )

            _r5_body_dup = (
                "title: t\n"
                "scenes:\n"
                "- {timestamp: 0-3s, type: Hook, 台詞_瑞祥: 喜歡是感覺}\n"
                "chxp_receipt:\n"
                "  used: []\n"
                "  receipt_hash: \"\"\n"
                "  receipt_hash: \"\"\n"
            )

            _r5_body_2blk = (
                "title: t\n"
                "scenes:\n"
                "- {timestamp: 0-3s, type: Hook, 台詞_瑞祥: 喜歡是感覺}\n"
                "chxp_receipt:\n"
                "  used: []\n"
                "  receipt_hash: \"\"\n"
                "chxp_receipt:\n"
                "  used: []\n"
                "  receipt_hash: \"\"\n"
            )

            _r5_body_nested = (
                "title: t\n"
                "scenes:\n"
                "- {timestamp: 0-3s, type: Hook, 台詞_瑞祥: 喜歡是感覺}\n"
                "chxp_receipt:\n"
                "  used: []\n"
                "  source_artifact_hashes:\n"
                "    receipt_hash: \"deadbeef\"\n"   # 子層同名鍵（非本欄）
                "  receipt_hash: \"\"\n"
            )
            fcheck("F-CXP-T2-R5-K3f 正向鎖：單純的合規稿 stamp 仍成功（K3 沒擋掉正路）",
                   _r4_stamp('receipt_hash: ""', "k3ok")[0] == 0)

            # ── K4：sidecar 重複 id_mode_map_sha256 鍵＝拒載 ──
            def _r5_sidecar(lines: str, tag: str):
                _d = Path(_w1_tmp.mkdtemp())
                (_d / "chxp_method_registry.yaml").write_text("x: 1\n", encoding="utf-8")
                (_d / _t2r._REGISTRY_SHA_SIDECAR_NAME).write_text(lines, encoding="utf-8")
                return _t2r.check_id_mode_map(_t2_reg, _d / "chxp_method_registry.yaml")

            _r5_good = _t2r.id_mode_map_sha256(_t2_reg)
            _r5_k4a = _r5_sidecar(
                "0" * 64 + "  chxp_method_registry.yaml\n"
                f"id_mode_map_sha256: {_r5_good}\n"
                f"id_mode_map_sha256: {'b' * 64}\n", "dup2")
            fcheck("F-CXP-T2-R5-K4a sidecar 兩條互相矛盾的 id_mode_map_sha256（第一條正確）→ "
                   "**拒載 FAIL**（r4：只取第一條就回 PASS＝身分錨歧義）",
                   _r5_k4a[0] == "FAIL" and "重複鍵" in _r5_k4a[1], f"got={_r5_k4a}")
            _r5_k4b = _r5_sidecar(
                "0" * 64 + "  chxp_method_registry.yaml\n"
                f"id_mode_map_sha256: {'b' * 64}\n"
                f"id_mode_map_sha256: {_r5_good}\n", "dup2r")
            fcheck("F-CXP-T2-R5-K4b 同上但順序相反（第二條才正確）→ 一樣拒載 FAIL"
                   "（不因排列順序改變結論）",
                   _r5_k4b[0] == "FAIL" and "重複鍵" in _r5_k4b[1], f"got={_r5_k4b}")
            _r5_k4c = _r5_sidecar(
                "0" * 64 + "  chxp_method_registry.yaml\n"
                f"id_mode_map_sha256: {_r5_good}\n"
                "id_mode_map_sha256: garbage\n", "dupbad")
            fcheck("F-CXP-T2-R5-K4c 一行合法＋一行格式非法 → 仍算重複鍵，拒載 FAIL"
                   "（先數行再解析，避免非法行被無視）",
                   _r5_k4c[0] == "FAIL" and "重複鍵" in _r5_k4c[1], f"got={_r5_k4c}")
            fcheck("F-CXP-T2-R5-K4d 正向鎖：唯一一條且正確 → PASS（K4 沒誤殺正路）",
                   _r5_sidecar("0" * 64 + "  chxp_method_registry.yaml\n"
                               f"id_mode_map_sha256: {_r5_good}\n", "one")[0] == "PASS")
            fcheck("F-CXP-T2-R5-K4e 正式 sidecar 仍只有一條、仍 PASS（現況未被 K4 打到）",
                   _t2r.check_id_mode_map(_t2_reg)[0] == "PASS",
                   f"got={_t2r.check_id_mode_map(_t2_reg)}")

            # ════════════════════════════════════════════
            # F-CXP-T2-R6（r6，2026-08-14）：Codex r5 點名的六殘例
            #   L1 版本字面全等（v3/prev-v1 跳版、v1-evil 冒充）
            #   L2 stamp YAML 結構化定位（nested-only、單邊引號）
            #   L3 sidecar 分詞統一（NBSP）
            #   L4 驗證器 Unicode 類別法（U+034F、quote 證據路徑）
            # ════════════════════════════════════════════
            print("\n[F-CXP-T2-R6] r6 封板輪：Codex r5 點名六殘例")

            # ── L1：版本比對改字面全等（廢 family+序號推導）──
            def _r6_reg_ver(ver: str, prev: str):
                """造一份「現役版本＝ver、previous_version＝prev」的 registry 副本。"""
                import copy as _r6_copy
                _r = _r6_copy.deepcopy(_t2_reg)
                _r["registry_version"] = ver
                _r["previous_version"] = prev
                return _r

            _r6_l1a = _t2r.check_receipt_registry_version(
                "chxp-128-v1", None, _r6_reg_ver("chxp-128-v3", "chxp-128-v1"))
            fcheck("F-CXP-T2-R6-L1a 現役 v3、previous 自報 v1、收據 v1（版本鏈自己斷兩版）→ "
                   "**FAIL**（r5 為 WARN：previous 自報什麼就信什麼，跳版照放）",
                   _r6_l1a[0] == "FAIL", f"got={_r6_l1a}")
            _r6_l1b = _t2r.check_receipt_registry_version(
                "chxp-128-v1-evil", None, _t2_reg)
            fcheck("F-CXP-T2-R6-L1b 收據 chxp-128-v1-evil 冒充 previous(chxp-128-v1-draft) → "
                   "**FAIL**（r5 為 WARN：只比 family+序號，後綴被忽略＝任何後綴都能冒充）",
                   _r6_l1b[0] == "FAIL", f"got={_r6_l1b}")
            _r6_l1c = _t2r.check_receipt_registry_version(
                "chxp-128-v2", None, _r6_reg_ver("chxp-128-v3", "chxp-128-v1"))
            fcheck("F-CXP-T2-R6-L1c 同 L1a 但收據填 v2（既非現役也非自報前一版）→ FAIL",
                   _r6_l1c[0] == "FAIL", f"got={_r6_l1c}")
            _r6_l1d = _t2r.check_receipt_registry_version(
                "chxp-128-v2-draft", None, _r6_reg_ver("chxp-128-v3", "chxp-128-v2-draft"))
            fcheck("F-CXP-T2-R6-L1d 正向鎖：版本鏈自洽（v3←v2-draft）且收據字面全等前一版 → WARN"
                   "（L1 只擋推導，不擋合法 grace）",
                   _r6_l1d[0] == "WARN", f"got={_r6_l1d}")
            fcheck("F-CXP-T2-R6-L1e 正向鎖：收據字面全等現役版本 → 仍 PASS（未誤傷正路）",
                   _t2r.check_receipt_registry_version(_r4_live, None, _t2_reg)[0] == "PASS")

            # ── L2：stamp 用 YAML 解析定位頂層 chxp_receipt.receipt_hash ──
            _r6_body_nested_only = (
                "title: t\n"
                "scenes:\n"
                "- {timestamp: 0-3s, type: Hook, 台詞_瑞祥: 喜歡是感覺}\n"
                "chxp_receipt:\n"
                "  used: []\n"
                "  source_artifact_hashes:\n"
                "    receipt_hash: \"deadbeef\"\n"   # 只有巢狀同名鍵，沒有直屬欄
            )
            fcheck("F-CXP-T2-R6-L2e 正向鎖：一般合規稿 stamp 仍 rc=0（L2 沒擋掉正路）",
                   _r4_stamp('receipt_hash: ""', "l2ok")[0] == 0)

            # ── L3：sidecar 重複鍵計數與取值用同一套分詞（含 NBSP）──
            _r6_l3a = _r5_sidecar(
                "0" * 64 + "  chxp_method_registry.yaml\n"
                f"id_mode_map_sha256: {'b' * 64}\n"
                f"\u00a0id_mode_map_sha256: {_r5_good}\n", "nbsp")
            fcheck("F-CXP-T2-R6-L3a 第二條鍵前放 NBSP（U+00A0）→ **仍算重複鍵，拒載 FAIL**"
                   "（r5：計數只認空格/tab、取值卻認所有 \\s，兩套分詞不一致就被繞過）",
                   _r6_l3a[0] == "FAIL" and "重複鍵" in _r6_l3a[1], f"got={_r6_l3a}")
            _r6_l3b = _r5_sidecar(
                "0" * 64 + "  chxp_method_registry.yaml\n"
                f"id_mode_map_sha256: {'b' * 64}\n"
                f"\u3000id_mode_map_sha256: {_r5_good}\n", "ideospace")
            fcheck("F-CXP-T2-R6-L3b 第二條鍵前放全形空格（U+3000）→ 一樣拒載 FAIL",
                   _r6_l3b[0] == "FAIL" and "重複鍵" in _r6_l3b[1], f"got={_r6_l3b}")
            _r6_l3c = _r5_sidecar(
                "0" * 64 + "  chxp_method_registry.yaml\n"
                f"\u00a0id_mode_map_sha256: {_r5_good}\n", "nbsp-one")
            fcheck("F-CXP-T2-R6-L3c 正向鎖：唯一一條、鍵前有 NBSP → 取值仍解得到、PASS"
                   "（計數與取值同一套分詞，不會一邊看得到一邊看不到）",
                   _r6_l3c[0] == "PASS", f"got={_r6_l3c}")

            # ── L4：驗證器清洗改 Unicode 類別法（Cf/Cc/Mn）＋ quote 證據路徑同接 ──
            _r6_mn = [("\u034f", "U+034F 組合字素連接子（Mn）"),
                      ("\u0300", "U+0300 組合抑音符（Mn）"),
                      ("\u034f\u200b", "Mn＋Cf 混合")]
            for _r6_ch, _r6_name in _r6_mn:
                fcheck(f"F-CXP-T2-R6-L4a is_nonempty_text({_r6_name}) → False"
                       f"（r5 為 True：顯式碼點清單漏列，類別集合又不含 Mn）",
                       _t2r.is_nonempty_text(_r6_ch) is False,
                       f"got={_t2r.is_nonempty_text(_r6_ch)!r} for {_r6_ch!r}")
            _r6_qdoc = {"scenes": [{"台詞_瑞祥": "喜歡是感覺"}]}
            _r6_l4b = _t2r.resolve_evidence_ref(_r6_qdoc, "quote:" + "\u200b" * 4)
            fcheck("F-CXP-T2-R6-L4b evidence_ref quote: 四個 U+200B → 不成立"
                   "（r5：長度 4 過關、只是碰巧稿內找不到；現在清洗後長度 0 直接擋在門口）",
                   _r6_l4b[0] is False and "太短" in _r6_l4b[1], f"got={_r6_l4b}")
            _r6_l4c = _t2r.resolve_evidence_ref(_r6_qdoc, "quote:" + "\u034f" * 4)
            fcheck("F-CXP-T2-R6-L4c evidence_ref quote: 四個 U+034F → 不成立（同上，Mn 類）",
                   _r6_l4c[0] is False and "太短" in _r6_l4c[1], f"got={_r6_l4c}")
            fcheck("F-CXP-T2-R6-L4d 正向鎖：quote: 真實稿內台詞仍解得回（L4 沒擋掉正路）",
                   _t2r.resolve_evidence_ref(_r6_qdoc, "quote:喜歡是感覺")[0] is True)
            fcheck("F-CXP-T2-R6-L4e 正向鎖：稿內夾零寬字元時，乾淨的 quote 仍找得到"
                   "（haystack 與 needle 同一套清洗）",
                   _t2r.resolve_evidence_ref(
                       {"scenes": [{"台詞_瑞祥": "喜歡\u200b是感覺"}]},
                       "quote:喜歡是感覺")[0] is True)
            fcheck("F-CXP-T2-R6-L4f 正向鎖：strip_invisible 仍不改動可見內容（含中間空白）",
                   _t2r.strip_invisible("\u200b 內政部 實價登錄 \ufeff\u034f") == "內政部 實價登錄")

            # ── r4 零誤殺方向鎖（新增檢查一律不得追殺舊稿／骨架）──
            fcheck("F-CXP-T2-R4-Z1 舊稿世代：receipt 冒稱 #058 仍 SKIP（零誤殺優先）",
                   chk_cxp_receipt(
                       dict(_t2_doc_base,
                            chxp_receipt={"used": [{"method_id": "058",
                                                    "evidence_ref": "quote:喜歡是感覺"}]}),
                       "t2.yaml", enforce_generation=False)[0] == "SKIP")
        except Exception as _e_t2:
            fcheck("F-CXP-T2 梯 2 fixtures 可執行", False, f"{type(_e_t2).__name__}: {_e_t2}")

        # cutover 狀態硬斷言（Codex R2 P2，gated --expect-enforce：防誤回退 shadow 而 flag-aware fixtures 仍綠）
        if "--expect-enforce" in sys.argv:
            fcheck("F-CUTOVER 6/24 enforce flags 全 True（_S22/ANCHOR/PLACEHOLDER/LEAK/_S21_6/D20-PRO-LANE）",
                   bool(_S22_ENFORCE and ANCHOR_FIRST_ENFORCE and _OFFPRO_PLACEHOLDER_ENFORCE
                        and _OFFPRO_LEAK_ENFORCE and _S21_6_REPORT_ENFORCE
                        and _HYBRID_PLAN_LOCK_ENFORCE and _HYBRID_METHOD_ENFORCE
                        and _HYBRID_FRIEND_CLOSE_ENFORCE and _HYBRID_PROFESSIONAL_ENFORCE
                        and _TASTE_PANEL_ENFORCE and _D20_PROFESSIONAL_LANE_ENFORCE),
                   f"S22={_S22_ENFORCE} ANCHOR={ANCHOR_FIRST_ENFORCE} PH={_OFFPRO_PLACEHOLDER_ENFORCE} "
                   f"LEAK={_OFFPRO_LEAK_ENFORCE} S216={_S21_6_REPORT_ENFORCE} "
                   f"HPLAN={_HYBRID_PLAN_LOCK_ENFORCE} HMETHOD={_HYBRID_METHOD_ENFORCE} "
                   f"HFRIEND={_HYBRID_FRIEND_CLOSE_ENFORCE} HPRO={_HYBRID_PROFESSIONAL_ENFORCE} "
                   f"TASTE={_TASTE_PANEL_ENFORCE} D20PROLANE={_D20_PROFESSIONAL_LANE_ENFORCE}")

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
