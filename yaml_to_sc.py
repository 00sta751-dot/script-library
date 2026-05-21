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
  yaml_to_sc_kwargs(yaml_data, num) -> dict

timestamp 轉換規則：
  "0-3s" → "0-3秒"
  type 非空 → 後綴 " {type}"
  e.g. "0-3s Hook" → "0-3秒 Hook"
"""

import os
import glob
import yaml


# === 必填欄位 schema ===
REQUIRED_FIELDS = ['title', '派系', 'scenes', 'caption', 'hashtag']


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


def yaml_to_sc_kwargs(yaml_data: dict, num: int) -> dict:
    """單個 yaml dict → sc_article() kwargs

    Args:
        yaml_data: yaml.safe_load() 後的 dict
        num: article 編號（第04批 = 401-413）

    Returns:
        dict，可直接 **解包 給 sc_article()

    Raises:
        ValueError: 缺必填欄位 / scenes 空 / scene 缺 timestamp
    """
    # 必填欄位驗
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

    # 驗每個 scene 有 timestamp
    for i, sc in enumerate(scenes):
        if 'timestamp' not in sc:
            raise ValueError(
                f'yaml scene[{i}] 缺 timestamp：{yaml_data.get("script_id", "unknown")}'
            )

    # --- platforms ---
    main_platform = yaml_data.get('main_platform', '')
    if '/' in main_platform:
        platforms = [p.strip() for p in main_platform.split('/') if p.strip()]
    else:
        platforms = [main_platform] if main_platform else ['IG Reels']

    # --- cta：從末段 type=CTA 抓，否則固定「個人化諮詢」---
    cta = '個人化諮詢'
    for sc in scenes:
        if sc.get('type', '').upper() == 'CTA':
            parts = []
            if sc.get('台詞_叭噗'):
                parts.append(sc['台詞_叭噗'])
            if sc.get('台詞_小C'):
                parts.append(sc['台詞_小C'])
            if parts:
                cta = parts[0]  # 取第一句 CTA 台詞
            break

    # --- scene（hook 場景描述）：取第一個 scene 的畫面 ---
    scene_desc = ''
    first_scene = scenes[0]
    if first_scene.get('畫面'):
        scene_desc = first_scene['畫面']
    else:
        # fallback：合併第一場台詞
        parts = []
        if first_scene.get('台詞_叭噗'):
            parts.append(f"叭噗：{first_scene['台詞_叭噗']}")
        if first_scene.get('台詞_小C'):
            parts.append(f"小C：{first_scene['台詞_小C']}")
        scene_desc = ' '.join(parts)

    # --- timeline ---
    timeline = []
    for sc in scenes:
        ts = _ts_convert(sc['timestamp'], sc.get('type', ''))

        desc_parts = []
        if sc.get('台詞_叭噗'):
            desc_parts.append(f"叭噗：{sc['台詞_叭噗']}")
        if sc.get('台詞_小C'):
            desc_parts.append(f"小C：{sc['台詞_小C']}")
        if sc.get('畫面'):
            desc_parts.append(f"（{sc['畫面']}）")
        desc = ' '.join(desc_parts)

        sub_desc = ''  # yaml 目前無對應欄位

        # 藏鏡人：去掉「「」」包覆符
        mirror_raw = sc.get('藏鏡人', '') or ''
        mirror = mirror_raw.strip()
        if mirror.startswith('「') and mirror.endswith('」'):
            mirror = mirror[1:-1]

        timeline.append((ts, desc, sub_desc, mirror))

    # --- caption（禁用詞不在 yaml 內容層做替換，保留原文）---
    caption = yaml_data.get('caption', '')

    # --- platform_chip：直接用 main_platform ---
    platform_chip = main_platform

    # --- po_time ---
    po_time = yaml_data.get('suggested_po_time', '')

    # --- hashtag ---
    hashtag = yaml_data.get('hashtag', [])
    if not isinstance(hashtag, list):
        hashtag = [hashtag] if hashtag else []

    return {
        'num': num,
        'title': yaml_data['title'],
        'pie': yaml_data['派系'],
        'platforms': platforms,
        'cta': cta,
        'scene': scene_desc,
        'timeline': timeline,
        'caption': caption,
        'platform_chip': platform_chip,
        'po_time': po_time,
        'hashtag': hashtag,
        'img': yaml_data.get('img') or None,  # top-level img 欄位（如 ../bappu-batch04-fishing-card-007.png）
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
        raise ValueError(f'yaml_dir 內無 script_*.yaml：{yaml_dir}')

    if expected_count is not None and len(files) != expected_count:
        raise ValueError(
            f'yaml 數量不符：找到 {len(files)} 個，預期 {expected_count} 個'
            f'\n  目錄：{yaml_dir}'
        )

    results = []
    for fpath in files:
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
        # 支援多 document yaml（前後 --- 包覆）：取第一個非 None dict
        docs = [d for d in yaml.safe_load_all(content) if d is not None]
        if not docs:
            raise ValueError(f'yaml 無有效內容：{fpath}')
        data = docs[0]
        if not isinstance(data, dict):
            raise ValueError(f'yaml 格式錯誤（非 dict）：{fpath}')
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
    def mock_sc_article(num, title, pie, platforms, cta, scene, timeline,
                        batch=None, caption=None, platform_chip=None,
                        po_time=None, hashtag=None, img=None):
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

    # --- 總結 ---
    total = PASS + FAIL
    print(f'\n=== 結果：{PASS}/{total} PASS ===')
    if FAIL > 0:
        print(f'FAIL {FAIL} 件，請修正後再 ship')
        sys.exit(1)
    else:
        print('全部 PASS — yaml_to_sc.py 準備就緒')
        sys.exit(0)
