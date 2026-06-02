#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yaml_to_sc.py — yaml 腳本檔 → sc_article() kwargs 通用翻譯機
用途：叭噗第04批（及未來各批）yaml-driven 腳本轉換

設計原則（A 保守模式）：
  - 業主無關通用設計 / 第 04 批首發叭噗試水，未來 4 業主新批次共用
  - 其他 3 業主 build script 完全不動
  - yaml 結構以實際 04批 schema 為準

主要函數：
  load_yaml_articles(yaml_dir, expected_count) -> list[dict]
  yaml_to_sc_kwargs(yaml_data, num) -> dict          ← 對外 API，輸出不變
  normalize_script_to_canonical(source_dict) -> dict ← v3 新增：canonical 格式層
  canonical_to_sc_kwargs(canonical, original_yaml, num) -> dict  ← v3 內部用
  parse_markdown_body(md_text) -> dict

timestamp 轉換規則：
  "0-3s" → "0-3秒"
  type 非空 → 後綴 " {type}"
  e.g. "0-3s Hook" → "0-3秒 Hook"

v2 2026-05-23：加 6 個新欄位（階段 3 schema 升級）
  新欄位（全 optional，backward compatible）：
  - voice_lock: true/false — 強制使用業主真實語料
  - policy_alignment: {ig: [], fb: [], tiktok: [], threads: []} — 平台政策融入清單
  - trial_reels: true/false — IG Reels Trial 模式
  - publish_mode: manual_today/platform_scheduled/draft_only — 發布模式
  - distribution_mode: organic_only/boost_candidate/paid_ad — 分發模式
  - platform_variants: {ig: {cta, caption_keywords}, fb: {cta}, tiktok: {caption_keywords}, threads: {reply_prompt}}
  legacy_allowed_until: 2026-06-01 — 過渡期標記（既有 yaml 可缺此 6 欄位）

v2.1 2026-05-23：加 markdown body parser（新格式支援）
  新功能：parse_markdown_body(md_text) → dict
  auto-detect：frontmatter 無 scenes key → 自動走 markdown parser
  backward compatible：既有 structured frontmatter yaml 不受影響
  faction 別名：frontmatter 的 faction key 自動映射為 派系

v3 2026-05-31：canonical 格式層（3 業主中性格式）
  新功能：normalize_script_to_canonical(source_dict) -> dict
  canonical schema：
    faction: {primary, alternatives, alias_raw}
    platforms: {primary, secondary, variants}
    scenes: [{slot, role, dialogue:[{speaker,line}], subtitle, visual,
              offscreen_interaction, raw_text}]
  字幕分流：字幕卡/翠文 → subtitle；畫面 → visual；藏鏡人 → offscreen_interaction
  對外 API（yaml_to_sc_kwargs）輸出不變，舊 build script 零影響。
"""

import os
import re
import glob
import yaml


# === 必填欄位 schema ===
REQUIRED_FIELDS = ['title', '派系', 'scenes', 'caption', 'hashtag']


# ============================================================
# parse_markdown_body — 新格式 yaml 的 markdown body 解析器
# ============================================================
# 新格式（瑞祥第34批等）：frontmatter 只有 meta，scenes/caption/hashtag 在 --- 後的 markdown
# 舊格式（阿奇第01批等）：frontmatter 含 structured scenes list
# auto-detect 在 yaml_to_sc_kwargs() 內：無 scenes key → 呼叫此函式

# 6 段時間軸標題模式（**0-3 秒 Hook** 格式）
_SCENE_HEADER_RE = re.compile(
    r'^\*\*(\d+[-–]\d+\s*秒[^*]*)\*\*\s*$',
    re.MULTILINE
)

# section 標題（## Caption / ## Hashtag / ## 流量密碼 / ## 6 維自評 / ## 視覺場景）
_SECTION_RE = re.compile(r'^##\s+(.+)$', re.MULTILINE)

# 台詞行：「台詞：」或「字幕卡：」
_DIALOGUE_RE = re.compile(r'^台詞：\s*(.+)$', re.MULTILINE)
_SUBTITLE_RE = re.compile(r'^字幕卡：\s*(.+)$', re.MULTILINE)

# 藏鏡人行（在 scene 段落內）
_MIRROR_RE = re.compile(r'藏鏡人[^：:]*[：:]\s*(.+)$', re.MULTILINE)

# 流量密碼行（數字 / 描述 格式）
_TRAFFIC_LINE_RE = re.compile(r'(\d+)\s+([^\s/][^/\n]*)')

# Hashtag backtick list（`#tag1` `#tag2` ...）
_HASHTAG_BACKTICK_RE = re.compile(r'`(#[^`]+)`')


def parse_markdown_body(md_text: str) -> dict:
    """從 markdown body 解析 scenes / caption / hashtag / 流量密碼 / 視覺場景

    支援新格式 yaml（瑞祥第34批）：
      - ## 6 段時間軸 下有 **0-3 秒 Hook** ... 等 6 段
      - ## Caption
      - ## Hashtag（backtick 格式 `#tag`）
      - ## 流量密碼（可選）
      - ## 視覺場景（可選）

    Args:
        md_text: --- 之後的 markdown 純文字

    Returns:
        dict with keys:
          scenes: list[dict]  — timestamp/type/台詞/字幕卡/藏鏡人
          caption: str
          hashtag: list[str]
          流量密碼: str        — raw text（可選）
          視覺場景: str        — raw text（可選）
          _raw_sections: dict  — 所有 ## 段落 raw text（供除錯）
    """
    result = {
        'scenes': [],
        'caption': '',
        'hashtag': [],
        '流量密碼': '',
        '視覺場景': '',
        '_raw_sections': {},
    }

    if not md_text or not md_text.strip():
        return result

    # --- Step 1：切分 ## sections ---
    sec_matches = list(_SECTION_RE.finditer(md_text))
    sections = {}
    for i, m in enumerate(sec_matches):
        sec_name = m.group(1).strip()
        start = m.end()
        end = sec_matches[i + 1].start() if i + 1 < len(sec_matches) else len(md_text)
        sections[sec_name] = md_text[start:end].strip()
    result['_raw_sections'] = dict(sections)

    # --- Step 2：caption ---
    for key in ('Caption', 'caption', 'CAPTION'):
        if key in sections:
            result['caption'] = sections[key].strip()
            break

    # --- Step 3：hashtag（backtick 格式 `#tag`）---
    for key in ('Hashtag', 'hashtag', 'HASHTAG'):
        if key in sections:
            tags = _HASHTAG_BACKTICK_RE.findall(sections[key])
            if tags:
                result['hashtag'] = tags
            else:
                # fallback：每行一個 tag
                lines = [l.strip() for l in sections[key].splitlines() if l.strip().startswith('#')]
                result['hashtag'] = lines
            break

    # --- Step 4：流量密碼 ---
    for key in ('流量密碼',):
        if key in sections:
            result['流量密碼'] = sections[key].strip()
            break

    # --- Step 5：視覺場景 ---
    for key in ('視覺場景',):
        if key in sections:
            result['視覺場景'] = sections[key].strip()
            break

    # --- Step 6：scenes（6 段時間軸）---
    # 先找 "## 6 段時間軸" section，若無則對整個 md_text 找 **時間戳** 段
    timeline_text = sections.get('6 段時間軸', '')
    if not timeline_text:
        # fallback：直接對全文抓
        timeline_text = md_text

    # 找所有 **0-3 秒 Hook** 等標題位置
    scene_headers = list(_SCENE_HEADER_RE.finditer(timeline_text))

    # 時間軸標題解析：「0-3 秒 Hook」→ timestamp="0-3秒", type="Hook"
    _TS_TYPE_RE = re.compile(r'^(\d+[-–]\d+\s*秒)\s*(.*)')

    for i, hm in enumerate(scene_headers):
        header_text = hm.group(1).strip()  # e.g. "0-3 秒 Hook"
        seg_start = hm.end()
        seg_end = scene_headers[i + 1].start() if i + 1 < len(scene_headers) else len(timeline_text)
        seg_body = timeline_text[seg_start:seg_end].strip()

        # 解析 timestamp + type
        ts_match = _TS_TYPE_RE.match(header_text)
        if ts_match:
            timestamp = ts_match.group(1).replace(' ', '').replace('–', '-')  # "0-3秒"
            scene_type = ts_match.group(2).strip()  # "Hook"
        else:
            timestamp = header_text
            scene_type = ''

        # 台詞
        d_match = _DIALOGUE_RE.search(seg_body)
        dialogue = d_match.group(1).strip() if d_match else ''

        # 字幕卡
        sub_match = _SUBTITLE_RE.search(seg_body)
        subtitle = sub_match.group(1).strip() if sub_match else ''

        # 藏鏡人
        mirror_match = _MIRROR_RE.search(seg_body)
        mirror_raw = mirror_match.group(1).strip() if mirror_match else ''
        # 保留「「」」符號，yaml_to_sc_kwargs 的 mirror strip 邏輯統一處理

        # 組 scene dict（對齊舊格式結構）
        sc = {
            'timestamp': timestamp,
            'type': scene_type,
        }
        if dialogue:
            # 用 台詞_旁白 作通用 key（build_index adapter 透過 _get_dialogue_parts 讀）
            sc['台詞_旁白'] = dialogue
        if subtitle:
            sc['字幕卡'] = subtitle
        if mirror_raw:
            sc['藏鏡人'] = mirror_raw
        # 把 scene body raw text 也存一份（供除錯）
        sc['_raw'] = seg_body

        result['scenes'].append(sc)

    return result


def _normalize_yaml_data(yaml_data: dict) -> dict:
    """新格式 yaml 正規化前處理（在驗 REQUIRED_FIELDS 前呼叫）

    1. faction → 派系（別名映射）
    2. 無 scenes key → 呼叫 parse_markdown_body，merge 解析結果
    3. 無 caption → 從 markdown body 補
    4. 無 hashtag → 從 markdown body 補

    修改的是 shallow copy（不改原始 dict）。
    """
    data = dict(yaml_data)  # shallow copy

    # 1. faction → 派系 alias
    if '派系' not in data and 'faction' in data:
        data['派系'] = data['faction']

    # 2. auto-detect：無 scenes key → markdown body parser
    if 'scenes' not in data:
        md_body = data.get('_markdown_body', '')
        if md_body:
            parsed = parse_markdown_body(md_body)
            # merge：只補缺少的欄位，不覆蓋 frontmatter 已有的值
            if parsed['scenes']:
                data['scenes'] = parsed['scenes']
            if not data.get('caption') and parsed['caption']:
                data['caption'] = parsed['caption']
            if not data.get('hashtag') and parsed['hashtag']:
                data['hashtag'] = parsed['hashtag']
            if not data.get('流量密碼') and parsed['流量密碼']:
                data['流量密碼'] = parsed['流量密碼']
            if not data.get('視覺場景') and parsed['視覺場景']:
                data['視覺場景'] = parsed['視覺場景']

    return data


# ============================================================
# normalize_script_to_canonical — v3 中性 canonical 格式層
# ============================================================
# 3 業主格式差異：
#   瑞祥  : faction / platform_primary / markdown body 時間軸（台詞行/字幕卡行）
#   叭噗  : 派系 / main_platform / 結構化 scenes（台詞_叭噗/台詞_小C）
#   阿奇  : 派系 / main_platform / 結構化 scenes（台詞_阿奇/翠文）
#
# 字幕分流鐵律：
#   字幕卡（瑞祥）/ 翠文（阿奇）→ subtitle
#   畫面 → visual
#   藏鏡人 → offscreen_interaction
#   台詞_X → dialogue:[{speaker,line}]（保留順序；雙人對話不壓成一段）
#
# 本函式不改變 yaml_to_sc_kwargs() 的輸出，供 validator 使用。

# inline 藏鏡人格式（markdown body 內）：【藏鏡人 1 共鳴型：「文字」】
_INLINE_MIRROR_RE = re.compile(
    r'【藏鏡人\s*\d*[^：:]*[：:][^「」]*「([^」]+)」[^】]*】',
    re.MULTILINE
)

# markdown body 台詞行：「台詞：文字」
_MD_DIALOGUE_LINE_RE = re.compile(r'^台詞：\s*(.+)$', re.MULTILINE)
# markdown body 字幕卡行
_MD_SUBTITLE_LINE_RE = re.compile(r'^字幕卡：\s*(.+)$', re.MULTILINE)
# markdown body 畫面行
_MD_VISUAL_LINE_RE = re.compile(r'^畫面：\s*(.+)$', re.MULTILINE)


def _canonical_faction(yaml_data: dict) -> dict:
    """從 yaml 抽出 canonical faction dict（支援 派系/faction 兩個 key）。"""
    raw = yaml_data.get('派系') or yaml_data.get('faction') or ''
    parts = [p.strip() for p in str(raw).split('/') if p.strip()]
    _BRACKET_RE = re.compile(r'（[^）]*）')
    clean_parts = [_BRACKET_RE.sub('', p).strip() for p in parts]
    primary = clean_parts[0] if clean_parts else ''
    alternatives = clean_parts[1:] if len(clean_parts) > 1 else []
    return {'primary': primary, 'alternatives': alternatives, 'alias_raw': str(raw)}


def _canonical_platforms(yaml_data: dict) -> dict:
    """從 yaml 抽出 canonical platforms dict。
    優先 main_platform；瑞祥用 platform_primary / platform_secondary。
    """
    primary_raw = yaml_data.get('main_platform') or yaml_data.get('platform_primary') or ''
    secondary_raw = yaml_data.get('platform_secondary') or ''
    variants_raw = yaml_data.get('platform_variants') or {}
    if not isinstance(variants_raw, dict):
        variants_raw = {}
    return {
        'primary': str(primary_raw).strip(),
        'secondary': str(secondary_raw).strip(),
        'variants': variants_raw,
    }


def _canonical_scenes_structured(scenes: list) -> list:
    """結構化 scenes（叭噗/阿奇格式）→ canonical scenes。"""
    canonical = []
    for slot_idx, sc in enumerate(scenes, start=1):
        dialogue = []
        for k, v in sc.items():
            if k.startswith('台詞_') and v:
                speaker = k[len('台詞_'):]
                dialogue.append({'speaker': speaker, 'line': str(v).strip()})

        subtitle = ''
        if sc.get('字幕卡'):
            subtitle = str(sc['字幕卡']).strip()
        elif sc.get('翠文'):
            subtitle = str(sc['翠文']).strip()

        visual = str(sc.get('畫面', '') or '').strip()

        mirror_raw = str(sc.get('藏鏡人', '') or '').strip()
        if mirror_raw.startswith('「') and mirror_raw.endswith('」'):
            mirror_raw = mirror_raw[1:-1]

        raw_parts = [
            f'{k}:{v}' for k, v in sc.items()
            if k not in ('timestamp', 'type') and v
        ]

        canonical.append({
            'slot': slot_idx,
            'role': str(sc.get('type', '') or '').strip(),
            'dialogue': dialogue,
            'subtitle': subtitle,
            'visual': visual,
            'offscreen_interaction': mirror_raw,
            'raw_text': ' | '.join(raw_parts),
            'timestamp': str(sc.get('timestamp', '') or '').strip(),
        })
    return canonical


def _canonical_scenes_markdown(md_body: str) -> list:
    """markdown body（瑞祥格式）→ canonical scenes。
    呼叫既有 parse_markdown_body，再對每個 scene 做欄位分流。
    """
    if not md_body or not md_body.strip():
        return []
    parsed = parse_markdown_body(md_body)
    if not parsed['scenes']:
        return []

    canonical = []
    for slot_idx, sc in enumerate(parsed['scenes'], start=1):
        raw_body = sc.get('_raw', '')

        # dialogue：台詞行（去掉 inline 藏鏡人後）
        dialogue = []
        raw_d = sc.get('台詞_旁白', '')
        if raw_d:
            clean = _INLINE_MIRROR_RE.sub('', raw_d).strip()
            clean = re.sub(r'\s+', ' ', clean).strip()
            if clean:
                dialogue.append({'speaker': '旁白', 'line': clean})
        elif raw_body:
            for d_text in _MD_DIALOGUE_LINE_RE.findall(raw_body):
                clean = _INLINE_MIRROR_RE.sub('', d_text).strip()
                clean = re.sub(r'\s+', ' ', clean).strip()
                if clean:
                    dialogue.append({'speaker': '旁白', 'line': clean})

        # subtitle：字幕卡
        subtitle = str(sc.get('字幕卡', '') or '').strip()
        if not subtitle and raw_body:
            m = _MD_SUBTITLE_LINE_RE.search(raw_body)
            if m:
                subtitle = m.group(1).strip()

        # visual：畫面（瑞祥 markdown 格式通常無畫面行，預設空）
        visual = ''
        if raw_body:
            m = _MD_VISUAL_LINE_RE.search(raw_body)
            if m:
                visual = m.group(1).strip()

        # offscreen_interaction：從 _raw 中的 inline 【藏鏡人...：「...」】 抓（精確）
        # 不用 sc['藏鏡人']（parse_markdown_body 的 _MIRROR_RE 貪婪匹配行尾會抓多）
        mirror = ''
        if raw_body:
            inline_hits = _INLINE_MIRROR_RE.findall(raw_body)
            if inline_hits:
                mirror = ' / '.join(inline_hits)

        canonical.append({
            'slot': slot_idx,
            'role': str(sc.get('type', '') or '').strip(),
            'dialogue': dialogue,
            'subtitle': subtitle,
            'visual': visual,
            'offscreen_interaction': mirror,
            'raw_text': raw_body[:200] if raw_body else '',
            'timestamp': str(sc.get('timestamp', '') or '').strip(),
        })
    return canonical


def normalize_script_to_canonical(source_dict: dict) -> dict:
    """任意業主 raw yaml dict → 中性 canonical dict（v3）。

    Args:
        source_dict: yaml.safe_load() 後的 dict（含 _markdown_body）

    Returns:
        canonical dict：
          script_id, owner, title
          faction: {primary, alternatives, alias_raw}
          platforms: {primary, secondary, variants}
          scenes: [{slot, role, dialogue:[{speaker,line}], subtitle,
                    visual, offscreen_interaction, raw_text, timestamp}]
          caption, hashtag, suggested_po_time
          _owner_format: 'structured' | 'markdown'
    """
    data = dict(source_dict)
    if '派系' not in data and 'faction' in data:
        data['派系'] = data['faction']

    faction = _canonical_faction(data)
    platforms = _canonical_platforms(data)

    owner_format = 'structured'
    if 'scenes' in data and data['scenes']:
        canonical_scenes = _canonical_scenes_structured(data['scenes'])
    else:
        md_body = data.get('_markdown_body', '')
        canonical_scenes = _canonical_scenes_markdown(md_body)
        owner_format = 'markdown'

    caption = str(data.get('caption', '') or '').strip()
    if not caption and owner_format == 'markdown' and data.get('_markdown_body'):
        parsed = parse_markdown_body(data['_markdown_body'])
        caption = parsed.get('caption', '')

    hashtag = data.get('hashtag', [])
    if not hashtag and owner_format == 'markdown' and data.get('_markdown_body'):
        parsed = parse_markdown_body(data['_markdown_body'])
        hashtag = parsed.get('hashtag', [])
    if not isinstance(hashtag, list):
        hashtag = [str(hashtag)] if hashtag else []

    return {
        'script_id': str(data.get('script_id', '') or ''),
        'owner': str(data.get('owner', '') or ''),
        'title': str(data.get('title', '') or ''),
        'faction': faction,
        'platforms': platforms,
        'scenes': canonical_scenes,
        'caption': caption,
        'hashtag': hashtag,
        'suggested_po_time': str(data.get('suggested_po_time', '') or ''),
        '_owner_format': owner_format,
    }


# ============================================================
# canonical_to_sc_kwargs — canonical + original_yaml → sc_article() kwargs
# （內部用；對外仍走 yaml_to_sc_kwargs 確保舊 API byte 不變）
# ============================================================

def canonical_to_sc_kwargs(canonical: dict, original_yaml: dict, num: int) -> dict:
    """canonical dict + original_yaml → sc_article() kwargs。

    platforms / platform_chip 仍使用 original_yaml 的 main_platform（保留舊行為）。
    canonical 的 platforms 供 validator 使用，不改 build 端輸出。
    """
    # platforms（保留舊行為：讀 original_yaml.main_platform）
    main_platform = original_yaml.get('main_platform', '')
    if '/' in main_platform:
        platforms = [p.strip() for p in main_platform.split('/') if p.strip()]
    else:
        platforms = [main_platform] if main_platform else ['IG Reels']

    # cta：從 canonical scenes 的 CTA slot dialogue[0].line
    cta = '個人化諮詢'
    for csc in canonical['scenes']:
        if csc.get('role', '').upper() == 'CTA' and csc.get('dialogue'):
            cta = csc['dialogue'][0]['line']
            break

    # scene desc（hook 視覺場景）
    scene_desc = ''
    if canonical['scenes']:
        first_csc = canonical['scenes'][0]
        if first_csc.get('visual'):
            scene_desc = first_csc['visual']
        else:
            scene_desc = ' '.join(
                f'{d["speaker"]}：{d["line"]}' for d in first_csc.get('dialogue', [])
            )

    # timeline（從 original_yaml scenes，保留舊邏輯確保 byte 一致）
    original_scenes = original_yaml.get('scenes', [])
    timeline = []
    for sc in original_scenes:
        ts = _ts_convert(sc['timestamp'], sc.get('type', ''))
        desc_parts = _get_dialogue_parts(sc)
        if sc.get('畫面'):
            desc_parts.append(f"（{sc['畫面']}）")
        desc = ' '.join(desc_parts)
        sub_desc = sc.get('畫面', '')
        mirror_raw = sc.get('藏鏡人', '') or ''
        mirror = mirror_raw.strip()
        if mirror.startswith('「') and mirror.endswith('」'):
            mirror = mirror[1:-1]
        timeline.append((ts, desc, sub_desc, mirror))

    caption = original_yaml.get('caption', '')
    po_time = original_yaml.get('suggested_po_time', '')
    hashtag = original_yaml.get('hashtag', [])
    if not isinstance(hashtag, list):
        hashtag = [hashtag] if hashtag else []
    platform_chip = main_platform

    voice_lock = original_yaml.get('voice_lock', False)
    if isinstance(voice_lock, str):
        voice_lock = voice_lock.lower() in ('true', 'yes', '1')
    voice_lock = bool(voice_lock)

    policy_alignment = original_yaml.get('policy_alignment') or {}
    if not isinstance(policy_alignment, dict):
        policy_alignment = {}

    trial_reels = original_yaml.get('trial_reels', False)
    if isinstance(trial_reels, str):
        trial_reels = trial_reels.lower() in ('true', 'yes', '1')
    trial_reels = bool(trial_reels)

    publish_mode = str(original_yaml.get('publish_mode') or 'manual_today').strip()
    if publish_mode not in VALID_PUBLISH_MODES:
        publish_mode = 'manual_today'

    distribution_mode = str(original_yaml.get('distribution_mode') or 'organic_only').strip()
    if distribution_mode not in VALID_DISTRIBUTION_MODES:
        distribution_mode = 'organic_only'

    platform_variants_kw = original_yaml.get('platform_variants') or {}
    if not isinstance(platform_variants_kw, dict):
        platform_variants_kw = {}

    return {
        'num': num,
        'title': original_yaml['title'],
        'pie': original_yaml['派系'],
        'platforms': platforms,
        'cta': cta,
        'scene': scene_desc,
        'timeline': timeline,
        'caption': caption,
        'platform_chip': platform_chip,
        'po_time': po_time,
        'hashtag': hashtag,
        'img': original_yaml.get('img') or None,
        'voice_lock': voice_lock,
        'policy_alignment': policy_alignment,
        'trial_reels': trial_reels,
        'publish_mode': publish_mode,
        'distribution_mode': distribution_mode,
        'platform_variants': platform_variants_kw,
    }


# === 新欄位 schema（v2 — 階段 3 升級）===
# 全部 optional（backward compatible）。
# legacy_allowed_until=2026-06-01 — 既有 yaml 過渡期允許缺這 6 欄。
# 2026-06-01 後新批次 validate_script_batch.py 強制驗。
NEW_OPTIONAL_FIELDS_V2 = [
    'voice_lock',          # bool — 強制使用業主真實語料
    'policy_alignment',    # dict{ig,fb,tiktok,threads} — 平台政策融入清單
    'trial_reels',         # bool — IG Reels Trial 模式
    'publish_mode',        # str — manual_today/platform_scheduled/draft_only
    'distribution_mode',   # str — organic_only/boost_candidate/paid_ad
    'platform_variants',   # dict{ig,fb,tiktok,threads} — 平台特化 CTA/keywords
]
LEGACY_ALLOWED_UNTIL = '2026-06-01'

VALID_PUBLISH_MODES = {'manual_today', 'platform_scheduled', 'draft_only'}
VALID_DISTRIBUTION_MODES = {'organic_only', 'boost_candidate', 'paid_ad'}


def _ts_convert(timestamp: str, scene_type: str = '') -> str:
    """timestamp "0-3s" + type "Hook" → "0-3秒 Hook"
    若 timestamp 無 s 結尾（歷史相容），直接回傳加 type。
    """
    ts = timestamp.strip()
    # 把末尾 s 換成 秒（只換最後一個 s，避免撞多音字）
    if ts.endswith('s'):
        ts = ts[:-1] + '秒'
    if scene_type:
        ts = ts + ' ' + scene_type
    return ts


def _get_dialogue_parts(sc: dict) -> list:
    """從 scene dict 收集所有 '台詞_*' key 的值，保留原始欄位順序。
    相容 叭噗/小C/阿奇/任意 業主台詞欄位名稱。
    """
    parts = []
    for k, v in sc.items():
        if k.startswith('台詞_') and v:
            speaker = k[len('台詞_'):]  # e.g. '阿奇', '叭噗', '小C'
            parts.append(f'{speaker}：{v}')
    return parts


def yaml_to_sc_kwargs(yaml_data: dict, num: int) -> dict:
    """單個 yaml dict → sc_article() kwargs

    v3 內部走 normalize_script_to_canonical → canonical_to_sc_kwargs，
    對外輸出 byte 完全不變（舊 build script 零影響）。

    Args:
        yaml_data: yaml.safe_load() 後的 dict
                   （含 _markdown_body key，由 load_yaml_articles 注入）
        num: article 編號（第04批 = 401-413）

    Returns:
        dict，可直接 **解包 給 sc_article()

    Raises:
        ValueError: 缺必填欄位 / scenes 空 / scene 缺 timestamp
    """
    # 前處理：新格式正規化（faction→派系 / markdown body parser / caption/hashtag 補填）
    yaml_data = _normalize_yaml_data(yaml_data)

    # 必填欄位驗（在 canonical 之前，確保錯誤訊息與舊版一致）
    for field in REQUIRED_FIELDS:
        if field not in yaml_data:
            raise ValueError(
                f'yaml 缺必填欄位 [{field}]：{yaml_data.get("script_id", "unknown")}'
            )

    scenes = yaml_data['scenes']
    if not scenes:
        raise ValueError(
            f'yaml scenes 為空 list：{yaml_data.get("script_id", "unknown")}'
        )

    for i, sc in enumerate(scenes):
        if 'timestamp' not in sc:
            raise ValueError(
                f'yaml scene[{i}] 缺 timestamp：{yaml_data.get("script_id", "unknown")}'
            )

    # v3：建 canonical（供 validator 使用；不影響下方 kwargs 組裝）
    canonical = normalize_script_to_canonical(yaml_data)

    # 內部走 canonical_to_sc_kwargs，輸出 byte 與舊版一致
    return canonical_to_sc_kwargs(canonical, yaml_data, num)


def inject_v2_meta_attrs(html: str, kw: dict) -> str:
    """在 HTML 第一個開 tag 後注入 v2 新欄位 data-* attribute。
    供 5 業主 adapter 呼叫（最小侵入，不改渲染函式）。

    注入欄位：
      data-voice-lock="true/false"
      data-publish-mode="manual_today/..."
      data-dist-mode="organic_only/..."
      data-trial-reels="true/false"

    Args:
        html: 業主 article HTML string
        kw:   yaml_to_sc_kwargs() 回傳的 dict

    Returns:
        注入 data-* 後的 HTML string
    """
    import re as _re
    attrs = (
        f' data-voice-lock="{str(kw.get("voice_lock", False)).lower()}"'
        f' data-publish-mode="{kw.get("publish_mode", "manual_today")}"'
        f' data-dist-mode="{kw.get("distribution_mode", "organic_only")}"'
        f' data-trial-reels="{str(kw.get("trial_reels", False)).lower()}"'
    )
    # 找第一個 <article 或 <div 開 tag，在第一個空格（或結尾 >）前插入
    # 例："<article class=\"card\" ...>" → "<article class=\"card\" data-voice-lock=... ...>"
    def _inject(m):
        tag_start = m.group(0)  # e.g. '<article' or '<div'
        return tag_start + attrs
    result = _re.sub(r'<(article|div)\b', _inject, html, count=1)
    return result


def get_new_fields_summary(yaml_data: dict) -> dict:
    """回傳 v2 新欄位的存在狀態摘要（供 validate_script_batch.py 使用）

    Returns:
        dict with keys: has_voice_lock, has_policy_alignment, has_publish_mode,
                        has_distribution_mode, has_platform_variants, has_trial_reels
        每個值為 True（欄位存在且非空）or False。
    """
    return {
        'has_voice_lock':          'voice_lock' in yaml_data,
        'has_policy_alignment':    bool(yaml_data.get('policy_alignment')),
        'has_trial_reels':         'trial_reels' in yaml_data,
        'has_publish_mode':        bool(yaml_data.get('publish_mode')),
        'has_distribution_mode':   bool(yaml_data.get('distribution_mode')),
        'has_platform_variants':   bool(yaml_data.get('platform_variants')),
    }


def load_yaml_articles(yaml_dir: str, expected_count: int = None) -> list:
    """讀資料夾下所有 script_*.yaml，按序排序，回傳 dict 列表

    Args:
        yaml_dir: yaml 檔資料夾（絕對路徑）
        expected_count: 預期 yaml 數量，不符 raise ValueError

    Returns:
        list[dict]，每個是 yaml.safe_load() 後的 dict

    Raises:
        FileNotFoundError: yaml_dir 不存在
        ValueError: 找到的 yaml 數不符 expected_count / yaml 格式錯誤
    """
    if not os.path.isdir(yaml_dir):
        raise FileNotFoundError(f'yaml_dir 不存在：{yaml_dir}')

    pattern = os.path.join(yaml_dir, 'script_*.yaml')
    files = sorted(glob.glob(pattern))

    if not files:
        # fallback：有些批次 yaml 命名無 script_ 前綴（如 yunzhen_12_*.yaml）
        pattern_fallback = os.path.join(yaml_dir, '*.yaml')
        files = sorted(glob.glob(pattern_fallback))
        if files:
            import sys as _sys_fb
            print(f'[load_yaml_articles] script_*.yaml 無結果，fallback *.yaml 找到 {len(files)} 個', file=_sys_fb.stderr)
        else:
            raise ValueError(f'yaml_dir 內無 script_*.yaml 或 *.yaml：{yaml_dir}')

    if expected_count is not None and len(files) != expected_count:
        raise ValueError(
            f'yaml 數量不符：找到 {len(files)} 個，預期 {expected_count} 個'
            f'\n  目錄：{yaml_dir}'
        )

    results = []
    for fpath in files:
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
        # 支援多 document yaml（前後 --- 包覆）：
        # 只取 frontmatter 部分（第一個 --- 到第二個 --- 之間）避免 markdown 內容的
        # **粗體** 語法被 yaml parser 誤判為 alias
        parts = content.split('---')
        if len(parts) >= 3:
            # 格式：空字串 | frontmatter | markdown 內容...
            frontmatter_str = parts[1]
            # markdown body = 第三段起（重新拼接，保留內部 --- 分隔）
            markdown_body = '---'.join(parts[2:]).strip()
        elif len(parts) == 2:
            frontmatter_str = parts[1]
            markdown_body = ''
        else:
            frontmatter_str = content
            markdown_body = ''
        data = yaml.safe_load(frontmatter_str)
        if data is None:
            raise ValueError(f'yaml 無有效內容：{fpath}')
        if not isinstance(data, dict):
            raise ValueError(f'yaml 格式錯誤（非 dict）：{fpath}')
        # 注入 markdown body（供 parse_markdown_body 使用 / 不影響舊格式）
        if markdown_body:
            data['_markdown_body'] = markdown_body
        # faction → 派系 早期映射（讓 build_index.py _yaml_by_pie 分流正確）
        if '派系' not in data and 'faction' in data:
            data['派系'] = data['faction']
        results.append(data)

    return results


# === 8+ case sanity test（pre-ship 必跑）===
if __name__ == '__main__':
    import sys
    import html as html_mod

    YAML_DIR = (
        r'C:\Users\00sta\Documents\Claude\Projects\短影音系統'
        r'\L2_業主層\情侶_叭噗_小C\02_腳本生產'
        r'\第04批_試水批_2026-05-21'
    )

    # 需要 sc_article 做 case 1/2 測試，動態 import（同目錄）
    THIS_DIR = os.path.dirname(os.path.abspath(__file__))
    if THIS_DIR not in sys.path:
        sys.path.insert(0, THIS_DIR)

    # 模擬 sc_article 最小版（避免跑 build_bappu.py 整個 html 產出）
    # **_extra 吸收 v2 新欄位（voice_lock/policy_alignment/...）—不影響 HTML 產出
    def mock_sc_article(num, title, pie, platforms, cta, scene, timeline,
                        batch=None, caption=None, platform_chip=None,
                        po_time=None, hashtag=None, img=None, **_extra):
        # 回傳 HTML 字串（最小版，不依賴 bappu-cc/index.html）
        cap_escaped = ''
        if caption:
            cap_escaped = (caption.replace('&', '&amp;')
                           .replace('"', '&quot;')
                           .replace('<', '&lt;')
                           .replace('>', '&gt;'))
        cap_attr = f' data-caption="{cap_escaped}"' if cap_escaped else ''

        hashtag_html = ''
        if hashtag:
            hashtag_html = ('<div class="hashtag-pool">'
                            + ''.join('<span class="hashtag">' + t + '</span>' for t in hashtag)
                            + '</div>')

        mirror_html = ''
        for ts, desc, *rest in timeline:
            mirror = rest[1] if len(rest) > 1 else ''
            if mirror:
                mirror_html += f'<div class="mirror">藏鏡人　{mirror}</div>\n'

        return (
            f'<article class="sc" data-id="{str(num).zfill(2)}"{cap_attr}>'
            f'<h2>{title}</h2>'
            f'{hashtag_html}'
            f'{mirror_html}'
            f'</article>'
        )

    PASS = 0
    FAIL = 0

    def check(label, condition, detail=''):
        global PASS, FAIL
        if condition:
            print(f'  [PASS] {label}')
            PASS += 1
        else:
            print(f'  [FAIL] {label}{(" — " + detail) if detail else ""}')
            FAIL += 1

    print('\n=== yaml_to_sc.py sanity test (8+ cases) ===\n')

    # --- Case 1：單檔 04_01 → kwargs → mock_sc_article → HTML 非空 ---
    print('[Case 1] 單檔 04_01 → kwargs → HTML 非空')
    try:
        articles = load_yaml_articles(YAML_DIR, expected_count=13)
        kw = yaml_to_sc_kwargs(articles[0], num=401)
        html_out = mock_sc_article(**kw, batch='第 04 批 · 2026-05-21')
        check('HTML 非空', bool(html_out.strip()))
        check('含 data-id="401"', 'data-id="401"' in html_out or 'data-id="01"' in html_out)
        check('data-caption 存在', 'data-caption="' in html_out)
    except Exception as e:
        check('Case 1 無例外', False, str(e))

    # --- Case 2：13 檔 batch loop → 13 HTML，num=401-413 不重複 ---
    print('\n[Case 2] 13 檔 batch loop → 13 HTML，num=401-413')
    try:
        articles = load_yaml_articles(YAML_DIR, expected_count=13)
        nums = []
        htmls = []
        for idx, ydata in enumerate(articles, start=1):
            kw = yaml_to_sc_kwargs(ydata, num=400 + idx)
            kw['batch'] = '第 04 批 · 2026-05-21'
            h = mock_sc_article(**kw)
            htmls.append(h)
            nums.append(400 + idx)
        check('共 13 篇', len(htmls) == 13)
        check('num 401-413 不重複', len(set(nums)) == 13 and min(nums) == 401 and max(nums) == 413)
        check('每篇 HTML 非空', all(h.strip() for h in htmls))
    except Exception as e:
        check('Case 2 無例外', False, str(e))

    # --- Case 3：缺 title yaml → ValueError ---
    print('\n[Case 3] 缺 title yaml → ValueError')
    bad_data = {
        '派系': '模板L_知識反差',
        'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_叭噗': '測試', '畫面': '測試'}],
        'caption': '測試 caption',
        'hashtag': ['#test'],
    }
    try:
        yaml_to_sc_kwargs(bad_data, num=999)
        check('缺 title 應 raise ValueError', False, '未 raise')
    except ValueError as e:
        check('缺 title raise ValueError', '缺必填欄位 [title]' in str(e) or 'title' in str(e))

    # --- Case 4：中文/emoji caption → HTML escape 正確（&quot; 出現）---
    print('\n[Case 4] 中文/emoji caption → HTML escape 正確')
    try:
        articles = load_yaml_articles(YAML_DIR, expected_count=13)
        # 04_01 caption 含純中文，注入 " 確認 escape
        test_data = dict(articles[0])
        test_data['caption'] = '測試 "引號" & 符號'
        kw = yaml_to_sc_kwargs(test_data, num=401)
        h = mock_sc_article(**kw, batch='第 04 批 · 2026-05-21')
        check('caption 含 &quot;', '&quot;' in h)
        check('caption 含 &amp;', '&amp;' in h)
    except Exception as e:
        check('Case 4 無例外', False, str(e))

    # --- Case 5：hashtag list 5 個 → HTML 含 5 個 <span class="hashtag"> ---
    print('\n[Case 5] hashtag list 5 個 → HTML 含 5 個 hashtag span')
    try:
        test_data = {
            'title': '測試',
            '派系': '模板L_知識反差',
            'main_platform': 'IG Reels',
            'suggested_po_time': '週六晚 10PM',
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_叭噗': '測試', '畫面': '測試'}],
            'caption': '測試 caption',
            'hashtag': ['#tag1', '#tag2', '#tag3', '#tag4', '#tag5'],
        }
        kw = yaml_to_sc_kwargs(test_data, num=998)
        h = mock_sc_article(**kw, batch='第 04 批 · 2026-05-21')
        count_hashtag = h.count('<span class="hashtag">')
        check('hashtag span 計數 = 5', count_hashtag == 5, f'實際 {count_hashtag}')
    except Exception as e:
        check('Case 5 無例外', False, str(e))

    # --- Case 6：藏鏡人句子含「「」」符號 → strip 後進 mirror div ---
    print('\n[Case 6] 藏鏡人「「」」符號 strip 後進 mirror')
    try:
        test_data = {
            'title': '測試',
            '派系': '模板L_知識反差',
            'main_platform': 'IG Reels',
            'scenes': [{
                'timestamp': '0-3s',
                'type': 'Hook',
                '台詞_叭噗': '測試',
                '畫面': '測試',
                '藏鏡人': '「哈哈這個太有趣了」',
            }],
            'caption': '測試',
            'hashtag': ['#test'],
        }
        kw = yaml_to_sc_kwargs(test_data, num=997)
        h = mock_sc_article(**kw, batch='test')
        # 藏鏡人文字應去掉「」，只留內文
        check('mirror 不含外層「」', '「哈哈這個太有趣了」' not in h.replace('藏鏡人', ''))
        check('mirror 含內文', '哈哈這個太有趣了' in h)
    except Exception as e:
        check('Case 6 無例外', False, str(e))

    # --- Case 7：scenes 含 type=CTA → ts 含「秒 CTA」---
    print('\n[Case 7] scenes type=CTA → ts 格式正確')
    try:
        articles = load_yaml_articles(YAML_DIR, expected_count=13)
        kw = yaml_to_sc_kwargs(articles[0], num=401)
        # 找 CTA scene 的 timeline tuple
        cta_ts = None
        for ts, desc, *rest in kw['timeline']:
            if 'CTA' in ts:
                cta_ts = ts
                break
        check('timeline 含 CTA ts', cta_ts is not None, '無 CTA ts')
        if cta_ts:
            check('CTA ts 含「秒」', '秒' in cta_ts, f'實際 ts: {cta_ts}')
    except Exception as e:
        check('Case 7 無例外', False, str(e))

    # --- Case 8：main_platform 含「/」分隔 → platforms 拆兩個 ---
    print('\n[Case 8] main_platform 含「/」→ platforms 拆兩個')
    try:
        test_data = {
            'title': '測試',
            '派系': '模板L_知識反差',
            'main_platform': 'IG Reels / FB Reels',
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_叭噗': '測試', '畫面': '測試'}],
            'caption': '測試',
            'hashtag': ['#test'],
        }
        kw = yaml_to_sc_kwargs(test_data, num=996)
        check('platforms 拆兩個', len(kw['platforms']) == 2, f'實際 {kw["platforms"]}')
        check('含 IG Reels', 'IG Reels' in kw['platforms'])
        check('含 FB Reels', 'FB Reels' in kw['platforms'])
    except Exception as e:
        check('Case 8 無例外', False, str(e))

    # --- Case 9（額外）：scenes 空 list → ValueError ---
    print('\n[Case 9] scenes 空 list → ValueError')
    try:
        bad_scenes = {
            'title': '測試',
            '派系': '模板L_知識反差',
            'scenes': [],
            'caption': '測試',
            'hashtag': ['#test'],
        }
        yaml_to_sc_kwargs(bad_scenes, num=995)
        check('scenes 空 應 raise ValueError', False, '未 raise')
    except ValueError:
        check('scenes 空 raise ValueError', True)

    # --- Case 10（額外）：timestamp 轉換 "s" → "秒" ---
    print('\n[Case 10] timestamp "35-52s" → "35-52秒 CTA"')
    result = _ts_convert('35-52s', 'CTA')
    check('timestamp 轉換正確', result == '35-52秒 CTA', f'實際: {result}')

    # --- Case 11（v2 新欄位）：含新欄位 yaml → kwargs 帶回新欄位 ---
    print('\n[Case 11] v2 新欄位 yaml → kwargs 含新欄位值')
    try:
        test_v2 = {
            'title': '新欄位測試',
            '派系': '直球派',
            'main_platform': 'IG Reels',
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_叭噗': '測試', '畫面': '測試'}],
            'caption': '測試 caption',
            'hashtag': ['#test'],
            'voice_lock': True,
            'policy_alignment': {'ig': ['DM Sends 優先'], 'threads': ['Dear Algo 標記']},
            'trial_reels': True,
            'publish_mode': 'manual_today',
            'distribution_mode': 'organic_only',
            'platform_variants': {'ig': {'cta': '留言「諮詢」', 'caption_keywords': ['高雄']}, 'threads': {'reply_prompt': '你覺得呢？'}},
        }
        kw = yaml_to_sc_kwargs(test_v2, num=1101)
        check('voice_lock = True', kw['voice_lock'] is True)
        check('policy_alignment ig 有資料', bool(kw['policy_alignment'].get('ig')))
        check('trial_reels = True', kw['trial_reels'] is True)
        check('publish_mode = manual_today', kw['publish_mode'] == 'manual_today')
        check('distribution_mode = organic_only', kw['distribution_mode'] == 'organic_only')
        check('platform_variants ig 有 cta', bool(kw['platform_variants'].get('ig', {}).get('cta')))
    except Exception as e:
        check('Case 11 無例外', False, str(e))

    # --- Case 12（v2 backward compat）：不含新欄位的 legacy yaml → kwargs 有合理預設 ---
    print('\n[Case 12] legacy yaml（無新欄位）→ kwargs 有合理預設值')
    try:
        legacy_data = {
            'title': 'Legacy 測試',
            '派系': '直球派',
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_叭噗': '測試', '畫面': '測試'}],
            'caption': '測試 caption',
            'hashtag': ['#test'],
        }
        kw = yaml_to_sc_kwargs(legacy_data, num=9000)
        check('voice_lock 預設 False', kw['voice_lock'] is False)
        check('policy_alignment 預設空 dict', kw['policy_alignment'] == {})
        check('publish_mode 預設 manual_today', kw['publish_mode'] == 'manual_today')
        check('distribution_mode 預設 organic_only', kw['distribution_mode'] == 'organic_only')
        check('platform_variants 預設空 dict', kw['platform_variants'] == {})
    except Exception as e:
        check('Case 12 無例外', False, str(e))

    # --- Case 13（v2 enum 驗證）：無效 publish_mode → fallback manual_today ---
    print('\n[Case 13] 無效 publish_mode → fallback manual_today')
    try:
        bad_enum = {
            'title': 'Enum 測試',
            '派系': '直球派',
            'scenes': [{'timestamp': '0-3s', 'type': 'Hook', '台詞_叭噗': '測試', '畫面': '測試'}],
            'caption': '測試 caption',
            'hashtag': ['#test'],
            'publish_mode': 'invalid_mode_xyz',
            'distribution_mode': 'bogus_mode',
        }
        kw = yaml_to_sc_kwargs(bad_enum, num=9001)
        check('無效 publish_mode fallback', kw['publish_mode'] == 'manual_today', f'實際: {kw["publish_mode"]}')
        check('無效 distribution_mode fallback', kw['distribution_mode'] == 'organic_only', f'實際: {kw["distribution_mode"]}')
    except Exception as e:
        check('Case 13 無例外', False, str(e))

    # --- Case 14（get_new_fields_summary）：summary 函式輸出正確 ---
    print('\n[Case 14] get_new_fields_summary 回傳正確 bool')
    try:
        full_data = {
            'voice_lock': True,
            'policy_alignment': {'ig': ['A']},
            'trial_reels': False,
            'publish_mode': 'manual_today',
            'distribution_mode': 'organic_only',
            'platform_variants': {'ig': {}},
        }
        summary = get_new_fields_summary(full_data)
        check('has_voice_lock = True', summary['has_voice_lock'] is True)
        check('has_policy_alignment = True', summary['has_policy_alignment'] is True)
        check('has_trial_reels = True', summary['has_trial_reels'] is True)
        check('has_publish_mode = True', summary['has_publish_mode'] is True)
        check('has_distribution_mode = True', summary['has_distribution_mode'] is True)
        check('has_platform_variants = True', summary['has_platform_variants'] is True)
        # 缺欄位
        empty_summary = get_new_fields_summary({})
        check('空 dict has_voice_lock = False', empty_summary['has_voice_lock'] is False)
        check('空 dict has_policy_alignment = False', empty_summary['has_policy_alignment'] is False)
    except Exception as e:
        check('Case 14 無例外', False, str(e))

    # --- Case 15：新格式 markdown body → parse_markdown_body → scenes/caption/hashtag ---
    print('\n[Case 15] 新格式 markdown body → parse_markdown_body 解析正確')
    RUX34_DIR = (
        r'C:\Users\00sta\Documents\Claude\Projects\短影音系統'
        r'\L2_業主層\房仲_瑞祥\01_腳本生產\第34批_試水批_2026-05-23'
    )
    try:
        rux34_articles = load_yaml_articles(RUX34_DIR)
        # 取第 1 部（script_rux_34_01.yaml）
        rux34_01 = rux34_articles[0]

        # 確認 _markdown_body 有注入
        check('_markdown_body 已注入', '_markdown_body' in rux34_01)

        # 跑 parse_markdown_body
        md_body = rux34_01.get('_markdown_body', '')
        parsed = parse_markdown_body(md_body)

        check('scenes 非空（>=1）', len(parsed['scenes']) >= 1, f'實際 {len(parsed["scenes"])}')
        check('scenes 數 = 6', len(parsed['scenes']) == 6, f'實際 {len(parsed["scenes"])}')
        check('caption 非空', bool(parsed['caption'].strip()), f'caption: {parsed["caption"][:30]}')
        check('hashtag 非空', len(parsed['hashtag']) >= 1, f'hashtag 數: {len(parsed["hashtag"])}')
        check('第一個 hashtag 含 #', parsed['hashtag'][0].startswith('#') if parsed['hashtag'] else False)

        # 確認第一段 (Hook) timestamp 格式
        if parsed['scenes']:
            first_ts = parsed['scenes'][0]['timestamp']
            check('第一段 timestamp 含「秒」', '秒' in first_ts, f'實際 ts: {first_ts}')
            check('第一段 type = Hook', parsed['scenes'][0].get('type', '') == 'Hook',
                  f'實際 type: {parsed["scenes"][0].get("type", "")}')
    except Exception as e:
        check('Case 15 無例外', False, str(e))

    # --- Case 16：新格式 yaml → yaml_to_sc_kwargs 完整流程（faction→派系 + markdown parser）---
    print('\n[Case 16] 新格式 yaml → yaml_to_sc_kwargs 完整流程')
    try:
        rux34_articles = load_yaml_articles(RUX34_DIR)
        rux34_01 = rux34_articles[0]

        kw = yaml_to_sc_kwargs(rux34_01, num=3401)
        check('title 非空', bool(kw['title']))
        check('pie = 人間觀察派', kw['pie'] == '人間觀察派', f'實際: {kw["pie"]}')
        check('timeline 有 6 段', len(kw['timeline']) == 6, f'實際: {len(kw["timeline"])}')
        check('caption 非空', bool(kw['caption'].strip()))
        check('hashtag 非空', len(kw['hashtag']) >= 1)
        check('第一個 hashtag 含 #', kw['hashtag'][0].startswith('#') if kw['hashtag'] else False)

        # 確認舊格式 yaml（阿奇）backward compatible
        ACHI01_DIR = (
            r'C:\Users\00sta\Documents\Claude\Projects\短影音系統'
            r'\L2_業主層\餐飲_阿奇\01_腳本生產\第01批_2026-05-22'
        )
        achi_articles = load_yaml_articles(ACHI01_DIR)
        achi_01 = achi_articles[0]
        kw_achi = yaml_to_sc_kwargs(achi_01, num=1001)
        check('舊格式 title 非空', bool(kw_achi['title']))
        check('舊格式 pie 非空', bool(kw_achi['pie']))
        check('舊格式 timeline 有 6 段', len(kw_achi['timeline']) == 6,
              f'實際: {len(kw_achi["timeline"])}')
        check('舊格式 caption 非空', bool(kw_achi['caption'].strip()))
    except Exception as e:
        check('Case 16 無例外', False, str(e))

    # --- 總結 ---
    total = PASS + FAIL
    print(f'\n=== 結果：{PASS}/{total} PASS ===')
    if FAIL > 0:
        print(f'FAIL {FAIL} 件，請修正後再 ship')
        sys.exit(1)
    else:
        print('全部 PASS — yaml_to_sc.py 準備就緒')
        sys.exit(0)
