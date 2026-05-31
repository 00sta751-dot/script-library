#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
template_retriever.py — 按 owner + 主題撈 3-5 張排序範本卡
輸入：owner + industry + topics.yaml（每支 topic/topic_type/platform/desired_hook）
輸出：template_recommendations.yaml + 給編劇看的 .md 範本卡

排序公式（照 §17）：
  industry .25 + topic .20 + hook .15 + transferability .15
  + engagement .10 + platform .10 + freshness .05 = 1.00

兩層檢索：
  同業優先取 2-3 → 跨業 transferability >= 0.75 補到 3-5

防同質：
  同 hook_type ≤ 2 張 / 同 creator(video_id prefix) ≤ 2 張 / 同 structure_family ≤ 2 張

效能回填：
  讀 template_performance_memory.yaml（若存在），加 0.15 × owner_performance_boost（clamp ±0.15）
  bucket：high=1.0 / mid=0.6 / low=0.2 / unknown=0.2（照 §17 修正1）
  used_count < 2 不大幅調（§17：门槛=2）

用法：
  python template_retriever.py --owner 瑞祥 --topics-yaml topics.yaml
  python template_retriever.py --owner 瑞祥 --topics-yaml topics.yaml --index template_index.jsonl

建立：2026-05-31
"""

import os
import re
import sys
import json
import yaml
import argparse
import math
from pathlib import Path
from typing import Optional
from datetime import datetime, date

# UTF-8 輸出防亂碼
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ── 路徑 ──
SCRIPT_LIB = Path(r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\L4_工具腳本\_部署系統\script-library")
DEFAULT_INDEX = SCRIPT_LIB / "template_index.jsonl"
DEFAULT_PERF_MEMORY = SCRIPT_LIB / "template_performance_memory.yaml"
L2_BASE = Path(r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\L2_業主層")

# ── 業主 → 行業對照（retriever 用）──
OWNER_INDUSTRY_MAP = {
    "瑞祥":     "房仲",
    "仲豪":     "房仲",
    "昀臻":     "美容",
    "叭噗_小C": "情侶",       # P1-C 修正：對齊索引 industry tag（cyborg build line 234 抄 yaml industry）
    "阿奇":     "餐飲",
}

# ── 跨業最低 transferability 門檻（照 §12.3）──
CROSS_INDUSTRY_MIN_TRANSFERABILITY = 0.75

# ── 排序公式 7 因子權重（照 §17）──
WEIGHTS = {
    "industry":          0.25,
    "topic":             0.20,
    "hook":              0.15,
    "transferability":   0.15,
    "engagement":        0.10,
    "platform":          0.10,
    "freshness":         0.05,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "權重總和必須為 1.0"

# ── 防同質上限（照 §12.3）──
DIVERSITY_LIMITS = {
    "hook_type":        2,  # 同 hook_type ≤ 2 張（在最終 3-5 張內）
    "creator_account":  2,  # 同 creator_account ≤ 2 張（P1-A 修正：真實帳號，非平台碼）
    "structure_family": 2,  # 同 structure_family ≤ 2 張（P1-B 修正：獨立維度）
}

# ── boost 參數（照 §17）──
BOOST_CLAMP = 0.15
BOOST_WEIGHT = 0.15
BOOST_MIN_USED_COUNT = 2  # used_count < 2 不大幅加權

# ── 效能 bucket 映射（照 §17 修正1：unknown=0.2）──
BUCKET_SCORE = {
    "high":    1.0,
    "mid":     0.6,
    "low":     0.2,
    "unknown": 0.2,
}


def load_index(index_path: Path) -> list[dict]:
    """載入 template_index.jsonl"""
    if not index_path.exists():
        print(f"[ERROR] template_index.jsonl 不存在：{index_path}", file=sys.stderr)
        return []
    cards = []
    with index_path.open(encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    cards.append(json.loads(line))
                except Exception:
                    pass
    return cards


def load_performance_memory(perf_path: Path, owner: str) -> dict:
    """載入效能記憶（若不存在回傳空 dict）
    格式：{template_id: {bucket, used_count, performance_score, ...}}
    """
    if not perf_path.exists():
        return {}
    try:
        data = yaml.safe_load(perf_path.read_text(encoding='utf-8')) or {}
        owner_mem = data.get(owner, {})
        return owner_mem if isinstance(owner_mem, dict) else {}
    except Exception:
        return {}


def load_topics_yaml(topics_path: Path) -> list[dict]:
    """載入 topics.yaml

    格式（每支腳本一筆）：
      - topic: "買房前要先知道的N件事"
        topic_type: "教育型"
        platform: "IG"
        desired_hook: "反差"
        owner: "瑞祥"     # optional，優先用 --owner

    回傳 list[dict]
    """
    if not topics_path.exists():
        print(f"[ERROR] topics yaml 不存在：{topics_path}", file=sys.stderr)
        return []
    try:
        data = yaml.safe_load(topics_path.read_text(encoding='utf-8')) or []
        if isinstance(data, list):
            return data
        # 支援 {topics: [...]} 格式
        if isinstance(data, dict) and 'topics' in data:
            return data['topics']
        return []
    except Exception as e:
        print(f"[ERROR] topics yaml 解析失敗：{e}", file=sys.stderr)
        return []


def _freshness_score(source_path: str) -> float:
    """從 cyborg yaml 路徑名提取日期，計算新鮮度分（0-1）
    越新 → 越高，半衰期 30 天
    """
    m = re.search(r'(\d{4}-\d{2}-\d{2})', source_path)
    if not m:
        return 0.5
    try:
        d = date.fromisoformat(m.group(1))
        today = date.today()
        days_old = (today - d).days
        # 半衰期 30 天：score = e^(-days/30)，min 0.05
        score = math.exp(-days_old / 30)
        return max(0.05, min(1.0, score))
    except Exception:
        return 0.5


def _engagement_score(engagement: dict) -> float:
    """把 engagement 數字映射到 0-1 分（log 正規化）"""
    if not engagement:
        return 0.5
    views = engagement.get('views')
    likes = engagement.get('likes')
    # 優先用 views，其次 likes
    raw = views if views else (likes * 10 if likes else None)
    if raw is None:
        return 0.5
    # log 正規化：100K views → 1.0；100 views → ~0.4
    score = math.log10(max(raw, 1)) / math.log10(100000)
    return max(0.1, min(1.0, score))


def _industry_match_score(card: dict, owner_industry: str) -> float:
    """行業匹配分（0/0.5/1.0）"""
    card_industries = card.get('industry_tags', [])
    if not card_industries or card_industries == ['unknown']:
        return 0.3  # 未知行業：中等
    if owner_industry in card_industries:
        return 1.0
    return 0.0


def _topic_match_score(card: dict, desired_topic: str, topic_type: str) -> float:
    """主題匹配分（關鍵詞比對）"""
    if not desired_topic:
        return 0.5
    card_tags = ' '.join(card.get('topic_tags', []))
    # _narrative_arc_ref 已移除（P0 防抄修正），只用 topic_tags 做關鍵詞比對
    combined = card_tags.lower()
    desired_lower = desired_topic.lower()

    # 關鍵詞拆解比對
    keywords = re.split(r'[\s，。,、？！?!「」『』]', desired_lower)
    keywords = [k for k in keywords if len(k) >= 2]
    if not keywords:
        return 0.5

    hit_count = sum(1 for k in keywords if k in combined)
    ratio = hit_count / len(keywords)

    # topic_type 加成
    type_bonus = 0.0
    if topic_type and topic_type.lower() in combined:
        type_bonus = 0.1

    return min(1.0, ratio * 0.8 + type_bonus)


def _hook_match_score(card: dict, desired_hook: str) -> float:
    """Hook 類型匹配分"""
    if not desired_hook:
        return 0.5
    card_hook = str(card.get('hook_type', ''))
    if desired_hook in card_hook or card_hook in desired_hook:
        return 1.0
    # 部分匹配
    desired_chars = set(desired_hook)
    card_chars = set(card_hook)
    overlap = len(desired_chars & card_chars) / max(len(desired_chars), 1)
    return max(0.2, overlap)


def _platform_match_score(card: dict, desired_platform: str) -> float:
    """平台匹配分"""
    if not desired_platform:
        return 0.5
    card_platform = str(card.get('platform', '')).lower()
    desired_lower = desired_platform.lower()
    if desired_lower in card_platform or card_platform in desired_lower:
        return 1.0
    # 常見跨平台相容性（IG/TikTok 格式相近）
    compat = {
        'ig': ['tiktok', 'reel'],
        'tiktok': ['ig', 'reel'],
        'fb': ['ig'],
        'threads': [],
        'youtube': ['youtube shorts'],
    }
    for key, compatible in compat.items():
        if key in desired_lower:
            for comp in compatible:
                if comp in card_platform:
                    return 0.7
    return 0.3


def score_card(card: dict, owner: str, topic_item: dict, perf_memory: dict) -> float:
    """計算單張範本卡對這支腳本的總分（0-1）"""
    owner_industry = OWNER_INDUSTRY_MAP.get(owner, 'unknown')
    desired_topic = str(topic_item.get('topic', ''))
    topic_type = str(topic_item.get('topic_type', ''))
    desired_platform = str(topic_item.get('platform', ''))
    desired_hook = str(topic_item.get('desired_hook', ''))

    # 7 因子分數
    s_industry = _industry_match_score(card, owner_industry)
    s_topic = _topic_match_score(card, desired_topic, topic_type)
    s_hook = _hook_match_score(card, desired_hook)
    s_transferability = float(card.get('transferability_score', 0.5))
    s_engagement = _engagement_score(card.get('engagement', {}))
    s_platform = _platform_match_score(card, desired_platform)
    s_freshness = _freshness_score(str(card.get('source_path', '')))

    base_score = (
        s_industry       * WEIGHTS['industry'] +
        s_topic          * WEIGHTS['topic'] +
        s_hook           * WEIGHTS['hook'] +
        s_transferability * WEIGHTS['transferability'] +
        s_engagement     * WEIGHTS['engagement'] +
        s_platform       * WEIGHTS['platform'] +
        s_freshness      * WEIGHTS['freshness']
    )

    # 效能 boost（§17）
    tid = card.get('template_id', '')
    perf = perf_memory.get(tid, {})
    if perf:
        used_count = int(perf.get('used_count', 0))
        bucket = str(perf.get('bucket', 'unknown')).lower()
        bucket_val = BUCKET_SCORE.get(bucket, BUCKET_SCORE['unknown'])

        if used_count >= BOOST_MIN_USED_COUNT:
            # raw boost = bucket_val * 0.15，clamp ±0.15，再乘 BOOST_WEIGHT
            raw_boost = (bucket_val - 0.5) * 2 * BOOST_CLAMP  # 映射到 [-0.15, 0.15]
            raw_boost = max(-BOOST_CLAMP, min(BOOST_CLAMP, raw_boost))
            boost = raw_boost * BOOST_WEIGHT  # 實際擾動 ±0.0225
            base_score = max(0.0, min(1.0, base_score + boost))

        # 同範本連用 > 2 批：diversity penalty -0.1
        if used_count > 2:
            base_score = max(0.0, base_score - 0.1)

    return round(base_score, 4)


def _get_creator_account(card: dict) -> str:
    """P1-A 修正：從 creator_account 欄位取真實帳號（build 端已由 url 抽取）。
    若欄位不存在（舊索引），fallback 到 video_id 去除平台前綴後的 ID 前段，
    並記 WARN（避免用平台碼 ig_ 當 creator 導致整個 IG 池被視為同 creator）。
    """
    account = str(card.get('creator_account', '')).strip()
    if account and account != 'unknown_creator':
        return account
    # fallback：舊索引無 creator_account → 用 video_id（去除 ig_/tt_ 等平台前綴）
    vid = str(card.get('video_id', ''))
    # 移除平台前綴（ig_、tt_、yt_ 等），剩下的才是影片 ID
    vid_no_prefix = re.sub(r'^[a-z]{2,4}_', '', vid)
    if vid_no_prefix and len(vid_no_prefix) > 4:
        # 舊索引：記 WARN 並放寬（每個影片 ID 都不同 → 不會過度砍，但也不是真 creator）
        # 回傳 fallback_<前8> 讓 diversity 仍可運作（不同影片 = 不同 fallback key）
        print(f"[WARN] creator_account 缺失，使用 fallback（舊索引）：{vid}", file=sys.stderr)
        return f"fallback_{vid_no_prefix[:8]}"
    return "unknown_creator"


def _get_structure_family(card: dict) -> str:
    """P1-B 修正：從 structure_skeleton 的 function 序列推導 structure_family 標籤。
    structure_family 跟 hook_type 是獨立維度（§17 修正4）。
    推導邏輯：看 structure_skeleton 中每個 slot 的 function 關鍵詞組合。
    """
    skeleton = card.get('structure_skeleton') or []
    if not skeleton:
        hook = card.get('hook_type', '')
        # 沒骨架：用 hook_type 派生，但標記為 inferred
        return f"inferred_{hook.split('|')[0].strip()}" if hook else "unknown_structure"

    # 提取各 slot 的 function 文字
    functions = [str(s.get('function', '')).lower() for s in skeleton if isinstance(s, dict)]

    # 識別結構骨架型態（優先順序：最具識別力的先）
    func_text = ' '.join(functions)

    # 反差/錯誤糾正 → 正解示範
    if ('反差' in func_text or '錯誤' in func_text or '糾正' in func_text) and ('正解' in func_text or '解決' in func_text):
        return "錯誤糾正→正解示範"
    # 懸念 → 揭曉
    if '懸念' in func_text or '揭曉' in func_text or '答案' in func_text:
        return "懸念堆疊→揭曉"
    # 問題 → 解決方案
    if ('問題' in func_text or '挑戰' in func_text) and ('解決' in func_text or '方案' in func_text or '方法' in func_text):
        return "問題→解決方案"
    # 故事 / 旅程弧線
    if '故事' in func_text or '旅程' in func_text or '轉折' in func_text or '反轉' in func_text:
        return "故事旅程弧線"
    # 數字列舉 / 方法列舉
    if '列舉' in func_text or '步驟' in func_text or '方法' in func_text or '件' in func_text:
        return "數字方法列舉"
    # 教學 / 知識分享
    if '教學' in func_text or '說明' in func_text or '示範' in func_text or '知識' in func_text:
        return "教學知識分享"
    # 共鳴 / 情感
    if '共鳴' in func_text or '情感' in func_text or '故事' in func_text:
        return "情感共鳴弧線"
    # CTA 主導型（短片）
    if len(skeleton) <= 3 and 'cta' in func_text.lower():
        return "短片CTA主導"

    # fallback：取前兩個 slot 的 function 組合
    first_two = [f[:8] for f in functions[:2] if f]
    if first_two:
        return f"{'→'.join(first_two)}"
    return "通用起承轉合"


def enforce_diversity(candidates: list[dict]) -> list[dict]:
    """防同質過濾：同 hook_type / creator_account / structure_family 各 ≤ 上限。

    P1-A 修正：creator 改用 _get_creator_account（真實帳號，非平台碼 ig_）。
    P1-B 修正：structure_family 改用 _get_structure_family（獨立維度）。
    """
    counts = {
        "hook_type": {},
        "creator_account": {},
        "structure_family": {},
    }
    result = []
    for card in candidates:
        hook = card.get('hook_type', '') or 'unknown'
        creator = _get_creator_account(card)     # P1-A
        struct_family = _get_structure_family(card)  # P1-B

        # 空 hook_type：算 unknown，不與有名稱的 hook 合並佔額（P2）
        if not hook.strip():
            hook = 'unknown'

        # 檢查各維度上限
        if counts["hook_type"].get(hook, 0) >= DIVERSITY_LIMITS["hook_type"]:
            continue
        if counts["creator_account"].get(creator, 0) >= DIVERSITY_LIMITS["creator_account"]:
            continue
        if counts["structure_family"].get(struct_family, 0) >= DIVERSITY_LIMITS["structure_family"]:
            continue

        result.append(card)
        counts["hook_type"][hook] = counts["hook_type"].get(hook, 0) + 1
        counts["creator_account"][creator] = counts["creator_account"].get(creator, 0) + 1
        counts["structure_family"][struct_family] = counts["structure_family"].get(struct_family, 0) + 1

    return result


def retrieve_for_topic(
    cards: list[dict],
    owner: str,
    topic_item: dict,
    perf_memory: dict,
    n_min: int = 3,
    n_max: int = 5,
) -> list[dict]:
    """對單支腳本主題，撈 n_min~n_max 張範本卡

    兩層檢索：
      同業優先取 2-3 → 跨業 transferability >= 0.75 補到 n_min
    """
    owner_industry = OWNER_INDUSTRY_MAP.get(owner, 'unknown')

    # 計算所有卡的分數
    scored = []
    for card in cards:
        s = score_card(card, owner, topic_item, perf_memory)
        scored.append((card, s))
    scored.sort(key=lambda x: x[1], reverse=True)

    # 第一層：同業
    same_industry = [
        (c, s) for c, s in scored
        if owner_industry in (c.get('industry_tags', []) or [])
        or (not c.get('industry_tags') or c.get('industry_tags') == ['unknown'])
    ]
    # 第二層：跨業高遷移（transferability >= 門檻，且不在同業池）
    same_ids = {c['template_id'] for c, _ in same_industry}
    cross_industry = [
        (c, s) for c, s in scored
        if c['template_id'] not in same_ids
        and float(c.get('transferability_score', 0)) >= CROSS_INDUSTRY_MIN_TRANSFERABILITY
    ]

    # 合併：同業先，跨業補
    combined_cards = [c for c, _ in same_industry[:n_max]] + [c for c, _ in cross_industry]

    # 防同質
    diverse = enforce_diversity(combined_cards)

    # 最終取 n_min ~ n_max
    result = diverse[:n_max]

    # 若不足 n_min，從 same_industry 補（P1-A 修正：仍尊重 creator diversity，記 WARN）
    if len(result) < n_min:
        existing_ids = {c['template_id'] for c in result}
        # 統計目前 creator 分佈
        creator_counts: dict[str, int] = {}
        for c in result:
            acc = _get_creator_account(c)
            creator_counts[acc] = creator_counts.get(acc, 0) + 1

        fallback_added = 0
        for card, _ in same_industry:
            if card['template_id'] in existing_ids:
                continue
            acc = _get_creator_account(card)
            # fallback 補位仍尊重 creator 上限（放寬到 3，比正常 2 多 1）
            if creator_counts.get(acc, 0) >= DIVERSITY_LIMITS["creator_account"] + 1:
                print(
                    f"[WARN] fallback 補位跳過 creator={acc}（已達放寬上限 3）",
                    file=sys.stderr,
                )
                continue
            result.append(card)
            existing_ids.add(card['template_id'])
            creator_counts[acc] = creator_counts.get(acc, 0) + 1
            fallback_added += 1
            if len(result) >= n_min:
                break

        if fallback_added > 0:
            print(
                f"[WARN] 多樣性過濾後不足 {n_min} 張，fallback 補位 {fallback_added} 張"
                f"（diversity 放寬，請確認索引池夠大）",
                file=sys.stderr,
            )

    return result[:n_max]


def format_card_for_editor(card: dict, rank: int) -> str:
    """格式化單張範本卡給編劇看（Markdown）"""
    lines = [
        f"### 範本 {rank}：{card.get('hook_type', '未知 Hook')}（{card.get('platform', '?')}）",
        f"",
        f"- **template_id**：`{card.get('template_id')}`",
        f"- **來源平台**：{card.get('platform')} / 行業：{', '.join(card.get('industry_tags', ['unknown']))}",
        f"- **可遷移性**：{card.get('transferability_score', 0.5):.2f}",
        f"- **Hook 類型**：{card.get('hook_type', '?')}",
        f"- **心理機制**：{card.get('hook_psychology', '?')}",
        f"",
        f"**前 3 秒開場型態**（Hook 手法標籤，不是台詞—禁止逐字抄）：",
        f"> {card.get('first_3_sec_abstract', '（無）')}",
        f"",
        f"**結構骨架**（照這個邏輯填你的台詞）：",
    ]
    for slot_item in (card.get('structure_skeleton') or []):
        lines.append(f"  - `{slot_item.get('slot', '?')}` → {slot_item.get('function', '?')}")

    lines += [
        f"",
        f"**節奏參考**：時長 {card.get('rhythm', {}).get('duration_sec', '?')} 秒 / 語速 {card.get('rhythm', {}).get('voice_pace_wpm', '?')} wpm / 平均剪輯 {card.get('rhythm', {}).get('avg_cut_sec', '?')} 秒",
        f"**分享動機**：{card.get('share_motive', '?')}",
        f"**留存手法**：{card.get('retention_device', '?')}",
        f"**CTA 模式**：{card.get('cta_pattern', '?')}",
        f"",
        f"**改寫引導**：{card.get('adaptation_prompt', '')}",
        f"",
        f"**禁止抄**：{card.get('do_not_copy', '')}",
        f"",
        f"---",
    ]
    return '\n'.join(lines)


def run_retrieval(
    owner: str,
    topics: list[dict],
    index_path: Path,
    out_yaml_path: Path,
    out_md_path: Path,
    n_min: int = 3,
    n_max: int = 5,
) -> bool:
    """執行完整檢索 + 輸出"""
    cards = load_index(index_path)
    if not cards:
        print(f"[ERROR] template_index.jsonl 空或不存在，請先跑 build_template_index.py", file=sys.stderr)
        return False

    perf_memory = load_performance_memory(DEFAULT_PERF_MEMORY, owner)
    if perf_memory:
        print(f"  效能記憶：找到 {len(perf_memory)} 筆 {owner} 歷史效能資料")

    print(f"\n{'='*60}")
    print(f"  template_retriever.py — 範本卡檢索")
    print(f"  業主：{owner}（行業：{OWNER_INDUSTRY_MAP.get(owner, '未知')}）")
    print(f"  索引：{len(cards)} 張範本卡")
    print(f"  主題數：{len(topics)} 支")
    print(f"{'='*60}\n")

    all_recommendations = []
    md_parts = [
        f"# {owner} 範本卡推薦",
        f"",
        f"> 產出時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"> 業主：{owner} / 索引共 {len(cards)} 張 / 每支推薦 {n_min}-{n_max} 張",
        f"",
    ]

    for i, topic_item in enumerate(topics, 1):
        topic_str = str(topic_item.get('topic', f'主題{i}'))
        platform = str(topic_item.get('platform', ''))
        desired_hook = str(topic_item.get('desired_hook', ''))

        print(f"  [{i:02d}] {topic_str[:40]}（{platform} / {desired_hook}）")

        recs = retrieve_for_topic(cards, owner, topic_item, perf_memory, n_min, n_max)

        # 撈到不足 n_min 張 → 記錄並最終 return False（打臉 6/1 強制 ≥3 張規格）
        if len(recs) < n_min:
            print(
                f"  [ERROR] 腳本 {i:02d}（{topic_str[:30]}）只撈到 {len(recs)} 張，"
                f"不足最低要求 {n_min} 張。",
                file=sys.stderr,
            )
            print(
                f"          可能原因：template_index.jsonl 張數不足 / 行業過濾太嚴 / 索引未更新。",
                file=sys.stderr,
            )
            # 繼續跑完其他 topic 讓錯誤全部一次印出，結尾統一 return False
            all_recommendations.append({
                "script_index": i,
                "topic": topic_str,
                "platform": platform,
                "desired_hook": desired_hook,
                "recommended_count": len(recs),
                "template_ids": [c['template_id'] for c in recs],
                "cards": recs,
                "_below_n_min": True,
            })
            continue

        rec_entry = {
            "script_index": i,
            "topic": topic_str,
            "platform": platform,
            "desired_hook": desired_hook,
            "recommended_count": len(recs),
            "template_ids": [c['template_id'] for c in recs],
            "cards": recs,
        }
        all_recommendations.append(rec_entry)

        md_parts.append(f"## 腳本 {i:02d}：{topic_str}")
        md_parts.append(f"")
        md_parts.append(f"平台：{platform} / 期望 Hook：{desired_hook} / 推薦 {len(recs)} 張")
        md_parts.append(f"")
        md_parts.append(f"**在腳本 yaml 填入**：")
        md_parts.append(f"```yaml")
        md_parts.append(f"template_source_ids: {[c['template_id'] for c in recs]}")
        md_parts.append(f"template_adaptation:")
        md_parts.append(f"  learned_structure: \"（你從這些範本學到的骨架邏輯）\"")
        md_parts.append(f"  changed_context: \"（你換成 {owner} 業主的情境）\"")
        md_parts.append(f"```")
        md_parts.append(f"")
        for rank, card in enumerate(recs, 1):
            md_parts.append(format_card_for_editor(card, rank))
        md_parts.append(f"")

        print(f"      → 推薦 {len(recs)} 張：{[c['template_id'] for c in recs]}")

    # 輸出 yaml
    out_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    with out_yaml_path.open('w', encoding='utf-8') as f:
        yaml.dump(
            {
                "owner": owner,
                "generated_at": datetime.now().isoformat(),
                "index_size": len(cards),
                "recommendations": [
                    {
                        "script_index": r["script_index"],
                        "topic": r["topic"],
                        "platform": r["platform"],
                        "desired_hook": r["desired_hook"],
                        "template_ids": r["template_ids"],
                    }
                    for r in all_recommendations
                ],
            },
            f,
            allow_unicode=True,
            default_flow_style=False,
        )
    print(f"\n  ✅ yaml 輸出：{out_yaml_path}")

    # 輸出 md
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.write_text('\n'.join(md_parts), encoding='utf-8')
    print(f"  ✅ md 輸出（編劇用）：{out_md_path}")

    # 任一 topic 不足 n_min 張 → 整體 return False / main() 會 sys.exit(1)
    below_min_count = sum(1 for r in all_recommendations if r.get('_below_n_min'))
    if below_min_count:
        print(
            f"\n[FAIL] {below_min_count} 支腳本推薦不足 {n_min} 張，"
            f"請先補充 template_index.jsonl（執行 build_template_index.py）後重試。",
            file=sys.stderr,
        )
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="範本卡檢索工具")
    parser.add_argument('--owner', required=True, help='業主名（瑞祥/仲豪/昀臻/叭噗_小C/阿奇）')
    parser.add_argument('--topics-yaml', required=True, help='topics yaml 絕對路徑')
    parser.add_argument('--index', default=str(DEFAULT_INDEX), help='template_index.jsonl 路徑')
    parser.add_argument('--out-dir', default=None, help='輸出目錄（預設同 index 目錄）')
    parser.add_argument('--n-min', type=int, default=3, help='最少推薦張數（預設 3）')
    parser.add_argument('--n-max', type=int, default=5, help='最多推薦張數（預設 5）')
    args = parser.parse_args()

    index_path = Path(args.index)
    topics_path = Path(args.topics_yaml)
    out_dir = Path(args.out_dir) if args.out_dir else index_path.parent

    topics = load_topics_yaml(topics_path)
    if not topics:
        print("[ERROR] topics yaml 為空或解析失敗", file=sys.stderr)
        sys.exit(1)

    out_yaml = out_dir / f"template_recommendations_{args.owner}.yaml"
    out_md = out_dir / f"template_recommendations_{args.owner}.md"

    ok = run_retrieval(
        owner=args.owner,
        topics=topics,
        index_path=index_path,
        out_yaml_path=out_yaml,
        out_md_path=out_md,
        n_min=args.n_min,
        n_max=args.n_max,
    )
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
