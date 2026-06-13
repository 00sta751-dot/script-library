#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_template_index.py — 爆款範本卡索引建立工具
掃 cyborg_*.yaml（主源）→ 輸出 template_index.jsonl

設計原則：
  - 範本卡只存「骨架/抽象」，不存逐字台詞（防抄）
  - 主源：cyborg_*.yaml（選題情報池，多 root 含 legacy；批次 C 已遷出 L0）
  - （歷史規格「補源人類可讀拆解 md」從未實作，md 不進 index；WP-A 後該庫亦遷出 L0）
  - status=rejected / 隔離待補目錄 → 跳過
  - 缺值一律填預設，不拋出 exception

用法：
  python build_template_index.py
  python build_template_index.py --out /absolute/path/to/template_index.jsonl
  python build_template_index.py --include-rejected  # 含已拒絕

輸出：template_index.jsonl（每行一個 JSON 物件）
每筆欄位（照 §12.3）：
  template_id, source_path, platform, industry_tags, topic_tags,
  hook_type, hook_psychology, first_3_sec_abstract, structure_skeleton,
  rhythm, share_motive, retention_device, cta_pattern,
  transferability_score, engagement, do_not_copy, adaptation_prompt

建立：2026-05-31
"""

import os
import re
import sys
import json
import yaml
import argparse
import hashlib
from pathlib import Path
from typing import Optional

# UTF-8 輸出防亂碼
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ── 路徑 ──
# 潮汐批次 C Step 1：多 root 掃描（不 import trend-daily，跨 repo）
# 與 trend-daily/topic_intel_paths.py 同源（compare gate 驗等值）
_TI_CONFIG_PATH = Path(r"C:\Users\00sta\claude-state\topic_intel_paths.json")

# DEFAULTS 值必須與 trend-daily/topic_intel_paths.py DEFAULTS 完全一致
_TI_DEFAULTS: dict = {
    "schema_version": 2,  # Codex r2-P2#4：與 topic_intel_paths.py DEFAULTS 完全一致（含 schema metadata）
    "active_root": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_選題情報池",
    "old_root": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\L0_跨行業公版\_趨勢報告",
    "legacy_root": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_選題情報池\_legacy_backlog",
    "quarantine_dir": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_選題情報池\_隔離待補",
    "old_quarantine_dir": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\L0_跨行業公版\_趨勢報告\_隔離待補",
    "collision_quarantine_dir": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_選題情報池\_collision_quarantine",
    # WP-A 爆款拆解 md 庫落點（與 topic_intel_paths.py DEFAULTS 同步）。Step 6 已切新池（2026-06-13，md 已遷出 L0）
    "dissect_lib_root": r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\_選題情報池\_爆款拆解庫",
    "migration_lock": r"C:\Users\00sta\claude-state\flags\topic_intel_migration.lock",
}


def _load_ti_config() -> dict:
    """小型 loader：讀同一個 topic_intel_paths.json（fail-open）"""
    # 沙盒縱深防禦：與 trend-daily resolver 同步支援 env 覆蓋（測試不得碰真池）
    _env_cfg = os.environ.get("TOPIC_INTEL_CONFIG_PATH", "").strip()
    if _env_cfg:
        p = Path(_env_cfg)
        if not p.exists():
            raise FileNotFoundError(f"[build-index] TOPIC_INTEL_CONFIG_PATH 指定的 config 不存在: {p}")
        cfg = json.loads(p.read_text(encoding="utf-8"))
        for k, v in _TI_DEFAULTS.items():
            cfg.setdefault(k, v)
        print(f"[build-index] config 來源=env override: {p}", file=sys.stderr)
        return cfg
    if _TI_CONFIG_PATH.exists():
        try:
            raw = _TI_CONFIG_PATH.read_text(encoding="utf-8")
            cfg = json.loads(raw)
            # 補缺 key
            for k, v in _TI_DEFAULTS.items():
                if k not in cfg:
                    print(f"[build-index] WARN: config 缺 key={k}，補 DEFAULTS", file=sys.stderr)
                    cfg[k] = v
            return cfg
        except Exception as e:
            print(f"[build-index] WARN: config 解析失敗 {_TI_CONFIG_PATH}: {e}，使用 DEFAULTS", file=sys.stderr)
    else:
        print(f"[build-index] WARN: config 不存在 {_TI_CONFIG_PATH}，使用 DEFAULTS", file=sys.stderr)
    return dict(_TI_DEFAULTS)


def _get_scan_roots() -> list[tuple[str, Path]]:
    """掃描順序：old -> legacy -> active（後掃優先；legacy 只收 processed）"""
    cfg = _load_ti_config()
    return [
        ("old", Path(cfg["old_root"])),
        ("legacy", Path(cfg["legacy_root"])),
        ("active", Path(cfg["active_root"])),
    ]


def _get_quarantine_roots() -> list[Path]:
    """隔離目錄清單（old + active 兩處，不進 index）"""
    cfg = _load_ti_config()
    return [
        Path(cfg["old_quarantine_dir"]),
        Path(cfg["quarantine_dir"]),
        Path(cfg["collision_quarantine_dir"]),
    ]


def _is_migration_locked() -> bool:
    cfg = _load_ti_config()
    return Path(cfg["migration_lock"]).exists()


CYBORG_DIR = Path(_TI_DEFAULTS["old_root"])  # fallback 向下相容（build_index 內部以 scan_roots 為準）
# DISSECT_DIR（爆款拆解 md 庫死常數）已移除 — WP-A 2026-06-13：本工具從不 iterate 此庫
# （template_index 零依賴 md，歷史 docstring「補源 md」從未實作）。md 庫落點現由
# trend-daily/topic_intel_paths.py 的 dissect_lib_root() 統一管理。
DEFAULT_OUT = Path(r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\L4_工具腳本\_部署系統\script-library\template_index.jsonl")

# ── Hook 心理學映射（type → psychology）──
HOOK_PSYCH_MAP = {
    "反差":   "認知衝突，打破預期，觀眾想知道「為什麼」",
    "懸念":   "信息缺口，觀眾必須看完才能填補",
    "故事":   "情感投入，跟著主角走完一段旅程",
    "數字":   "具體化信任感，讓人有快速理解的錨點",
    "問句":   "直接對話感，觸發觀眾自我投射",
    "衝突":   "戲劇張力，觀眾想知道結果",
    "共鳴":   "「說出我心裡的話」，觸發轉發衝動",
    "實用":   "立即可用的信息，降低觀看成本",
    "情緒":   "強烈情感觸發，喜/怒/驚/悲帶動擴散",
}

def _hook_psychology(hook_type: str) -> str:
    """從 hook_type 推斷心理機制（防空值）"""
    if not hook_type:
        return "未分類"
    for key, psych in HOOK_PSYCH_MAP.items():
        if key in hook_type:
            return psych
    return f"觸發觀看動機（type={hook_type}）"


def _hook_type_to_abstract_label(hook_type: str) -> str:
    """P0 修正：把 hook_type 轉成抽象「型態/手法標籤」，不儲存逐字台詞。
    hook_type 已是抽象（如「反差|故事|數字」），直接用它當標籤。
    若空值，回傳 '未分類開場'。
    """
    if not hook_type:
        return "未分類開場"
    # hook_type 已是抽象標籤（如「故事|反差|數字」）—直接取第一個 | 前的主型態
    main_type = hook_type.split('|')[0].strip()
    if not main_type:
        return hook_type.strip() or "未分類開場"
    return f"{main_type}型開場"



def _extract_creator_account(url: str, platform: str, video_id: str) -> str:
    """從 url 提取創作者帳號（P1-A 防同 creator 多樣性用）。
    IG：instagram.com/<account>/reel/<id> → account
    TikTok：tiktok.com/@<account>/video/<id> → account
    FB：無固定格式 → fallback video_id 前 8 字元
    若無法抽取 → 回傳 'unknown_creator'
    """
    if not url:
        return "unknown_creator"
    # IG 格式
    m = re.search(r'instagram\.com/([^/?#]+)/(?:reel|p)/', url)
    if m:
        account = m.group(1).strip()
        return account if account else "unknown_creator"
    # TikTok 格式
    m = re.search(r'tiktok\.com/@([^/?#]+)/video/', url)
    if m:
        return m.group(1).strip()
    # YouTube 格式（無 creator，用頻道 ID）
    m = re.search(r'youtube\.com/(?:watch\?v=|shorts/)([^/?#&]+)', url)
    if m:
        return f"yt_{m.group(1)[:8]}"
    # fallback：video_id 前 12 字元（含平台前綴）
    if video_id:
        return video_id[:12]
    return "unknown_creator"


def _make_template_id(source_path: str, video_id: str) -> str:
    """產生唯一 template_id（video_id 為主，無則 hash source_path）"""
    if video_id:
        # 清理特殊字元
        clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(video_id))
        return f"tmpl_{clean}"
    h = hashlib.md5(source_path.encode()).hexdigest()[:8]
    return f"tmpl_{h}"


def _extract_structure_skeleton(narrative_arc: str, hook_type: str) -> list[dict]:
    """從 narrative_arc 文字提取結構骨架（6 slot 框架）

    輸出格式：[{slot, function}, ...]
    骨架只給功能描述，不給台詞。
    """
    if not narrative_arc:
        return [
            {"slot": "0-3秒", "function": "Hook（觸發觀看）"},
            {"slot": "3-12秒", "function": "破題（建立框架）"},
            {"slot": "12-25秒", "function": "核心論述（展開內容）"},
            {"slot": "25-40秒", "function": "案例轉折（具體化）"},
            {"slot": "40-52秒", "function": "完播鉤子（繼續看）"},
            {"slot": "52-60秒", "function": "CTA（行動引導）"},
        ]

    # 嘗試從 narrative_arc 識別段落
    skeleton = []
    # 常見起承轉合模式
    arc_lower = narrative_arc.lower()

    # 判斷 hook 功能
    hook_func = f"Hook（{hook_type}）" if hook_type else "Hook（觸發觀看）"
    skeleton.append({"slot": "0-3秒", "function": hook_func})

    # 判斷中段結構
    if "起：" in narrative_arc or "起承" in narrative_arc:
        skeleton.append({"slot": "3-12秒", "function": "破題（起：交代背景脈絡）"})
        skeleton.append({"slot": "12-25秒", "function": "核心論述（承：展開核心論點）"})
        skeleton.append({"slot": "25-40秒", "function": "案例轉折（轉：引入反轉/衝突）"})
        skeleton.append({"slot": "40-52秒", "function": "完播鉤子（合：整合收束）"})
    elif "故事" in narrative_arc or "案例" in narrative_arc:
        skeleton.append({"slot": "3-12秒", "function": "破題（設定場景/人物）"})
        skeleton.append({"slot": "12-25秒", "function": "核心論述（展開故事衝突）"})
        skeleton.append({"slot": "25-40秒", "function": "案例轉折（關鍵轉折點）"})
        skeleton.append({"slot": "40-52秒", "function": "完播鉤子（結果揭曉，帶出核心訊息）"})
    elif "懸念" in narrative_arc or "揭曉" in narrative_arc:
        skeleton.append({"slot": "3-12秒", "function": "破題（強化懸念，製造期待）"})
        skeleton.append({"slot": "12-25秒", "function": "核心論述（鋪墊線索，堆疊張力）"})
        skeleton.append({"slot": "25-40秒", "function": "案例轉折（接近揭曉，加速節奏）"})
        skeleton.append({"slot": "40-52秒", "function": "完播鉤子（揭曉/驚喜，引發反應）"})
    else:
        skeleton.append({"slot": "3-12秒", "function": "破題（建立核心命題）"})
        skeleton.append({"slot": "12-25秒", "function": "核心論述（展開論點/內容）"})
        skeleton.append({"slot": "25-40秒", "function": "案例轉折（具體案例或反轉）"})
        skeleton.append({"slot": "40-52秒", "function": "完播鉤子（留住觀眾繼續看）"})

    skeleton.append({"slot": "52-60秒", "function": "CTA（行動引導/分享誘因）"})
    return skeleton


def _infer_share_motive(narrative_arc: str, hook_type: str) -> str:
    """推斷分享動機（不看逐字台詞，看結構特徵）"""
    if not narrative_arc:
        return "未知"
    arc = narrative_arc
    if "共鳴" in arc or "也曾" in arc or "你也" in arc:
        return "情感共鳴（說出我的心聲）"
    if "知識" in arc or "資訊" in arc or "教學" in arc or "方法" in arc:
        return "資訊價值（實用知識值得分享）"
    if "搞笑" in arc or "幽默" in arc or "娛樂" in arc or "爆笑" in arc:
        return "娛樂娛樂（這個太好笑了，分享給朋友）"
    if "揭曉" in arc or "驚喜" in arc or "想不到" in arc or "反差" in hook_type:
        return "驚訝反應（你絕對想不到，快告訴你）"
    if "信任" in arc or "真實" in arc or "幕後" in arc:
        return "信任建立（真誠，值得推薦）"
    return "待人工補充"


def _infer_retention_device(narrative_arc: str, duration: float) -> str:
    """推斷完播留存手法（不看台詞）"""
    if duration and duration < 20:
        return "短片完整性（<20秒整段觀看）"
    if not narrative_arc:
        return "未知"
    if "懸念" in narrative_arc or "揭曉" in narrative_arc:
        return "信息缺口（懸念未解，不看完不甘心）"
    if "故事" in narrative_arc or "反轉" in narrative_arc:
        return "故事懸念（想知道結局）"
    if "反差" in narrative_arc or "衝突" in narrative_arc:
        return "衝突張力（想知道怎麼解決）"
    if "列舉" in narrative_arc or "步驟" in narrative_arc or "項" in narrative_arc:
        return "系列完整性（N件事要全部看完）"
    return "內容密度（信息密集，持續提供價值）"


def _infer_cta_pattern(narrative_arc: str, platform: str) -> str:
    """推斷 CTA 模式（不看台詞）"""
    if not narrative_arc:
        return "通用互動引導"
    if "聯繫" in narrative_arc or "私訊" in narrative_arc or "DM" in narrative_arc:
        return "私訊引導（DM/加LINE）"
    if "留言" in narrative_arc or "討論" in narrative_arc:
        return "留言互動（問問題 / 你呢？）"
    if "追蹤" in narrative_arc or "更多" in narrative_arc:
        return "追蹤引導（更多內容在這裡）"
    if "分享" in narrative_arc or "傳" in narrative_arc:
        return "分享引導（傳給需要的人）"
    return "軟性 CTA（邀請互動，非硬推）"


def _to_int_or_none(val) -> Optional[int]:
    """把 yaml 值轉 int，'None' / None / 空字串 → None"""
    if val is None:
        return None
    if isinstance(val, str) and val.strip().lower() in ('none', '', 'null'):
        return None
    try:
        return int(float(str(val)))
    except (ValueError, TypeError):
        return None


def _engagement_from_supporting(supporting: dict, duration: float) -> dict:
    """從 supporting_data 提取參與度數字"""
    view = supporting.get("view_count")
    like = supporting.get("like_count")
    comment = supporting.get("comment_count")
    return {
        "views": _to_int_or_none(view),
        "likes": _to_int_or_none(like),
        "comments": _to_int_or_none(comment),
        "duration_sec": float(duration) if duration else None,
    }


def parse_cyborg_yaml(path: Path, include_rejected: bool = False) -> Optional[dict]:
    """解析單個 cyborg yaml → 範本卡 dict，失敗回傳 None"""
    try:
        text = path.read_text(encoding='utf-8')
        # 移除 frontmatter 分隔符
        text = re.sub(r'^---\s*\n', '', text, count=1)
        text = re.sub(r'\n---\s*$', '', text)
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            return None
    except Exception as e:
        print(f"  [SKIP] {path.name}: yaml parse 失敗 ({e})", file=sys.stderr)
        return None

    # status 過濾
    status = str(data.get('status', 'pending')).lower()
    if not include_rejected and status in ('rejected', 'stale'):
        return None
    # 隔離目錄（上層含 _隔離待補 的跳過）
    if '_隔離待補' in str(path.parent):
        return None

    video_id = str(data.get('video_id', ''))
    platform = str(data.get('platform', ''))
    industry = str(data.get('industry', 'unknown'))
    applicable_owners = data.get('applicable_owners') or []
    transferability = data.get('transferability_score')
    if transferability is None:
        transferability = 0.5  # 缺值預設 0.5（照 §12.3）

    # 從 url 提取 creator_account（防抄 + P1-A creator 維度用）
    raw_url = str(data.get('url', '')).strip()
    creator_account = _extract_creator_account(raw_url, platform, video_id)

    # dissect 段
    dissect = data.get('dissect') or {}
    hook_struct = dissect.get('hook_structure') or {}
    if isinstance(hook_struct, str):
        # 有些 yaml hook_structure 是 JSON string
        try:
            hook_struct = json.loads(hook_struct)
        except Exception:
            hook_struct = {}

    hook_type = str(hook_struct.get('type', '')).strip()
    # P0 修正：first_3_sec_abstract 只存 Hook「型態/手法標籤」，不存逐字台詞
    # 來源：hook_structure.type（已是抽象標籤如「反差|故事|數字」）
    # 禁止存 first_3_sec_text 原文（防抄）
    first_3sec = _hook_type_to_abstract_label(hook_type)

    narrative_arc = str(dissect.get('narrative_arc', '')).strip()
    audio = dissect.get('audio_features') or {}
    if isinstance(audio, str):
        try:
            audio = json.loads(audio)
        except Exception:
            audio = {}

    editing = dissect.get('editing_rhythm') or {}
    if isinstance(editing, str):
        try:
            editing = json.loads(editing)
        except Exception:
            editing = {}

    supporting = data.get('supporting_data') or {}
    duration = supporting.get('duration_sec') or 0

    # 節奏（只存骨架，不存台詞）
    rhythm = {
        "duration_sec": float(duration) if duration else None,
        "voice_pace_wpm": audio.get('voice_pace_wpm'),
        "avg_cut_sec": editing.get('avg_cut_sec'),
        "has_bgm": bool(audio.get('bgm_present')),
        "bgm_style": str(audio.get('bgm_style', '')),
    }

    # 推斷 topic_tags（從 industry / narrative_arc 推斷，不看台詞）
    topic_tags = []
    if 'unknown' not in industry.lower():
        topic_tags.append(industry)
    if applicable_owners:
        topic_tags.extend([f"owner:{o}" for o in applicable_owners])
    # 從 narrative arc 補 topic tag
    arc_lower = narrative_arc.lower()
    if "房" in arc_lower or "仲介" in arc_lower or "買房" in arc_lower:
        if "房仲" not in topic_tags:
            topic_tags.append("房仲")
    if "美容" in arc_lower or "保養" in arc_lower or "皮膚" in arc_lower:
        if "美容" not in topic_tags:
            topic_tags.append("美容")
    if "餐" in arc_lower or "料理" in arc_lower or "食物" in arc_lower:
        if "餐飲" not in topic_tags:
            topic_tags.append("餐飲")

    # industry_tags
    industry_tags = [industry] if industry and industry != 'unknown' else []

    template_id = _make_template_id(str(path), video_id)

    card = {
        "template_id": template_id,
        "source_path": str(path),
        "platform": platform,
        "video_id": video_id,
        "status": status,
        "industry_tags": industry_tags,
        # 保序去重（不可用 set：hash 隨機化會讓重建 byte 不穩，破壞遷移 byte-gate — 批次 C Step 0）
        "topic_tags": list(dict.fromkeys(topic_tags)),
        "hook_type": hook_type,
        "hook_psychology": _hook_psychology(hook_type),
        # first_3_sec_abstract：只存抽象描述，不存完整台詞
        "first_3_sec_abstract": first_3sec,
        "structure_skeleton": _extract_structure_skeleton(narrative_arc, hook_type),
        "rhythm": rhythm,
        "share_motive": _infer_share_motive(narrative_arc, hook_type),
        "retention_device": _infer_retention_device(narrative_arc, duration),
        "cta_pattern": _infer_cta_pattern(narrative_arc, platform),
        "transferability_score": float(transferability),
        "engagement": _engagement_from_supporting(supporting, duration),
        # creator_account：從 url 抽取的帳號（防同 creator 多樣性用）
        "creator_account": creator_account,
        # do_not_copy：明示不能抄逐字台詞
        "do_not_copy": "逐字台詞（見 transcript_preview）；視覺特效名稱；創作者個人 IP 梗",
        # adaptation_prompt：給編劇用的改寫引導
        "adaptation_prompt": (
            f"把這支的 {hook_type} Hook 邏輯套進你的業主場景。"
            f"結構骨架照 structure_skeleton，每 slot 換成業主情境台詞。"
            f"節奏參考 rhythm（語速/剪輯節奏），不要逐字抄開場台詞。"
        ),
        # _narrative_arc_ref 已移除（2026-05-31 P0 修正）
        # 原欄位截前 12 字仍含具體情節（人名/地名/事件），違反防抄鐵律。
        # 結構資訊已由 structure_skeleton 涵蓋。
    }

    return card


def scan_cyborg_dir(cyborg_dir: Path, include_rejected: bool = False,
                    legacy_mode: bool = False) -> list[dict]:
    """掃 cyborg_dir（不進隔離子目錄）
    legacy_mode=True：只收 status=processed（legacy_backlog 用）
    """
    # 取隔離目錄集合（跳過）
    _quar_roots = set()
    for qp in _get_quarantine_roots():
        _quar_roots.add(qp.resolve())

    cards = []
    yaml_files = sorted(cyborg_dir.glob("cyborg_*.yaml"))
    for f in yaml_files:
        # 跳過在任何隔離子目錄下的檔
        try:
            if f.resolve().parent.resolve() in _quar_roots:
                continue
        except Exception:
            pass
        card = parse_cyborg_yaml(f, include_rejected=include_rejected)
        if card is None:
            continue
        # legacy_mode：只收 processed
        if legacy_mode and card.get("status") != "processed":
            continue
        cards.append(card)
    return cards


def build_index(out_path: Path, include_rejected: bool = False) -> int:
    """主程式：掃多 root 來源 → 建 jsonl → 回傳寫入筆數
    掃描順序：old -> legacy -> active（後掃勝；legacy 只收 processed）
    同 template_id 衝突：sha256 相同=取 active（最後）；不同=列 stderr + exit 3
    """
    scan_roots = _get_scan_roots()

    print(f"\n{'='*60}")
    print(f"  build_template_index.py — 爆款範本卡索引建立")
    print(f"{'='*60}")
    for tag, root in scan_roots:
        print(f"  [{tag}] {root}")
    print(f"  輸出：{out_path}\n")

    # 主源：多 root cyborg yaml（先 per-root 去重，再跨 root sha256 碰撞檢測）
    print("── 掃 cyborg_*.yaml（multi-root）──")

    import hashlib as _hlib

    def _sha_card(card: dict) -> str:
        try:
            return _hlib.sha256(Path(card["source_path"]).read_bytes()).hexdigest()
        except Exception:
            return ""

    # per-root 先去重（維持改前「同 root 同 template_id 後掃覆蓋」語意）
    # root_deduped: list of (tag, {tid: card})
    root_deduped: list[tuple[str, dict[str, dict]]] = []
    for tag, root in scan_roots:
        if not root.exists():
            print(f"  [{tag}] 目錄不存在，跳過", file=sys.stderr)
            continue
        is_legacy = (tag == "legacy")
        root_cards = scan_cyborg_dir(root, include_rejected=include_rejected, legacy_mode=is_legacy)
        print(f"  [{tag}] → {len(root_cards)} 張（per-root 去重前）")
        per_root: dict[str, dict] = {}
        for card in root_cards:
            per_root[card["template_id"]] = card  # 後掃覆蓋 = root 內後日期勝
        print(f"  [{tag}] → {len(per_root)} 張（per-root 去重後）")
        root_deduped.append((tag, per_root))

    # 跨 root 合併：同 template_id 出現在多 root
    # sha256 相同（同檔重複）→ 後 root 覆蓋；sha256 不同 → 真 collision exit 3
    merged: dict[str, tuple[str, dict]] = {}  # tid -> (root_tag, card)
    collision_ids: list[str] = []
    for tag, per_root in root_deduped:
        for tid, card in per_root.items():
            if tid not in merged:
                merged[tid] = (tag, card)
            else:
                prev_tag, prev_card = merged[tid]
                sha_new = _sha_card(card)
                sha_old = _sha_card(prev_card)
                if sha_new and sha_old and sha_new != sha_old:
                    print(
                        f"[build-index] COLLISION: template_id={tid} "
                        f"root_a={prev_tag}(sha={sha_old[:8]}) "
                        f"root_b={tag}(sha={sha_new[:8]}) 內容不同",
                        file=sys.stderr,
                    )
                    collision_ids.append(tid)
                else:
                    # sha 相同或讀不到：後 root 覆蓋（active 優先）
                    merged[tid] = (tag, card)

    if collision_ids:
        print(
            f"[build-index] FAIL: {len(set(collision_ids))} 個 template_id 跨 root sha256 衝突，"
            "不自動合併，請人工裁決後再跑。",
            file=sys.stderr,
        )
        sys.exit(3)

    all_cards = [card for (_tag, card) in merged.values()]
    deduped = all_cards  # 已去重
    total_pre = sum(len(pr) for _, pr in root_deduped)
    removed = total_pre - len(deduped)
    if removed > 0:
        print(f"  → 跨 root 去重移除 {removed} 筆（同 template_id，後 root 覆蓋）")

    # 寫 jsonl
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', encoding='utf-8') as fout:
        for card in deduped:
            fout.write(json.dumps(card, ensure_ascii=False) + '\n')

    print(f"\n  ✅ 寫出 {len(deduped)} 筆範本卡 → {out_path}")

    # 簡單摘要
    platforms = {}
    industries = {}
    hook_types = {}
    for c in deduped:
        p = c.get('platform', 'unknown')
        platforms[p] = platforms.get(p, 0) + 1
        for i in (c.get('industry_tags') or []):
            industries[i] = industries.get(i, 0) + 1
        ht = c.get('hook_type', '')
        if ht:
            hook_types[ht] = hook_types.get(ht, 0) + 1

    print(f"\n  平台分布：{platforms}")
    print(f"  行業分布：{industries}")
    print(f"  Hook 類型分布：{hook_types}")

    return len(deduped)


def main():
    parser = argparse.ArgumentParser(description="爆款範本卡索引建立工具")
    parser.add_argument('--out', default=str(DEFAULT_OUT), help='輸出路徑（絕對路徑 jsonl）')
    parser.add_argument('--include-rejected', action='store_true', help='含 rejected/stale 範本（預設跳過）')
    parser.add_argument('--print-roots', action='store_true',
                        help='印 resolved roots json 後 exit 0（給 compare gate 用）')
    args = parser.parse_args()

    # --print-roots：印 resolved roots json 後 exit 0（compare gate 用）
    if args.print_roots:
        roots = _get_scan_roots()
        _cfg = _load_ti_config()
        print(json.dumps(
            {
                "roots": {tag: str(root) for tag, root in roots},
                "dissect_lib_root": str(Path(_cfg["dissect_lib_root"])),  # WP-A：與 resolver 比對一致
                "schema_version": _cfg.get("schema_version", _TI_DEFAULTS.get("schema_version")),  # Codex r2-P2#4
            },
            ensure_ascii=False,
        ))
        sys.exit(0)

    # migration lock 擋（非 dry-run）
    if _is_migration_locked():
        print(
            "[build-index] migration lock 在，拒跑。請等遷移完成後再跑。",
            file=sys.stderr,
        )
        sys.exit(6)

    count = build_index(Path(args.out), include_rejected=args.include_rejected)
    # count <= 0 → 空索引或失敗，exit 1 讓呼叫者（pre-commit / CI）知道沒有可用範本卡
    sys.exit(0 if count > 0 else 1)


if __name__ == '__main__':
    main()
