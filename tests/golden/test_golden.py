#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_golden.py — canonical + kwargs golden fixture 驗證
驗兩件：
  1. normalize_script_to_canonical() 輸出與快照一致（canonical dict 正確）
  2. yaml_to_sc_kwargs() 輸出與快照一致（舊 API byte 不變）

執行：python tests/golden/test_golden.py
全 PASS 才算完工。
"""
import json, sys, os

# 確保 script-library 在 path
SCRIPT_LIB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SCRIPT_LIB)

from yaml_to_sc import load_yaml_articles, normalize_script_to_canonical, yaml_to_sc_kwargs

BASE = r'C:\Users\00sta\Documents\Claude\Projects\短影音系統\L2_業主層'
RUX   = BASE + r'\房仲_瑞祥\01_腳本生產\第34批_試水批_2026-05-23'
BAPPU = BASE + r'\情侶_叭噗_小C\02_腳本生產\第04批_試水批_2026-05-21'
ACHI  = BASE + r'\餐飲_阿奇\01_腳本生產\第01批_2026-05-22'

FIXTURES_DIR = os.path.dirname(os.path.abspath(__file__))

SPECS = [
    (RUX,   0,  3401, 'rux_34_01'),
    (RUX,   1,  3402, 'rux_34_02'),
    (BAPPU, 0,  401,  'bappu_04_01'),
    (BAPPU, 1,  402,  'bappu_04_02'),
    (ACHI,  0,  1001, 'achi_01_01'),
    (ACHI,  1,  1002, 'achi_01_02'),
]

PASS = 0
FAIL = 0

def check(label, ok, detail=''):
    global PASS, FAIL
    if ok:
        print(f'  [PASS] {label}')
        PASS += 1
    else:
        print(f'  [FAIL] {label}' + (f' -- {detail}' if detail else ''))
        FAIL += 1


def serialize_kwargs(kw):
    """timeline tuple -> list for JSON compare."""
    kw2 = dict(kw)
    kw2['timeline'] = [list(t) for t in kw2['timeline']]
    return kw2


def deep_eq(a, b, path=''):
    """遞迴比較兩個 JSON-safe 物件，回傳 (ok, diff_message)。"""
    if type(a) != type(b):
        return False, f'{path}: type {type(a).__name__} != {type(b).__name__}'
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            extra_a = set(a.keys()) - set(b.keys())
            extra_b = set(b.keys()) - set(a.keys())
            return False, f'{path}: keys differ (extra_a={extra_a}, extra_b={extra_b})'
        for k in a:
            ok, msg = deep_eq(a[k], b[k], f'{path}.{k}')
            if not ok:
                return False, msg
        return True, ''
    elif isinstance(a, list):
        if len(a) != len(b):
            return False, f'{path}: len {len(a)} != {len(b)}'
        for i, (x, y) in enumerate(zip(a, b)):
            ok, msg = deep_eq(x, y, f'{path}[{i}]')
            if not ok:
                return False, msg
        return True, ''
    else:
        if a != b:
            return False, f'{path}: {repr(a)[:60]} != {repr(b)[:60]}'
        return True, ''


print('\n=== test_golden.py: canonical + kwargs fixtures ===\n')

# 載入各批 yaml（每批只載一次）
_yaml_cache = {}
def get_yaml(d):
    if d not in _yaml_cache:
        _yaml_cache[d] = load_yaml_articles(d)
    return _yaml_cache[d]


for (yaml_dir, idx, num, name) in SPECS:
    print(f'[{name}]')
    fixture_path = os.path.join(FIXTURES_DIR, f'{name}.json')
    if not os.path.exists(fixture_path):
        check(f'{name}: fixture 存在', False, f'找不到 {fixture_path}')
        continue

    with open(fixture_path, 'r', encoding='utf-8') as f:
        fixture = json.load(f)

    arts = get_yaml(yaml_dir)
    raw = arts[idx]

    # --- 1. canonical 驗 ---
    canonical = normalize_script_to_canonical(raw)
    ok, msg = deep_eq(canonical, fixture['canonical'])
    check(f'{name}: canonical 與快照一致', ok, msg)

    if canonical.get('_owner_format') == 'markdown':
        # 瑞祥 markdown 格式：額外驗幾個關鍵欄位
        check(f'{name}: faction.primary 非空',
              bool(canonical['faction']['primary']),
              repr(canonical['faction']['primary']))
        check(f'{name}: platforms.primary 非空',
              bool(canonical['platforms']['primary']),
              repr(canonical['platforms']['primary']))
        check(f'{name}: scenes len == 6',
              len(canonical['scenes']) == 6,
              f'實際 {len(canonical["scenes"])}')
        check(f'{name}: scene[0] dialogue 非空',
              bool(canonical['scenes'][0]['dialogue']),
              '')
        check(f'{name}: scene[0] subtitle 非空',
              bool(canonical['scenes'][0]['subtitle']),
              repr(canonical['scenes'][0]['subtitle']))

    elif canonical.get('_owner_format') == 'structured':
        # 叭噗/阿奇 結構化格式
        owner = canonical.get('owner', '')
        if '叭噗' in owner or '情侶' in name or 'bappu' in name:
            # 雙人對話驗：找 Hook scene，確認 dialogue >= 2 items
            hook_scene = next((s for s in canonical['scenes'] if s['role'] == 'Hook'), None)
            if hook_scene:
                check(f'{name}: 叭噗 Hook dialogue >= 2（雙人）',
                      len(hook_scene['dialogue']) >= 2,
                      f'實際 {len(hook_scene["dialogue"])}')
        if 'achi' in name:
            # 阿奇：驗翠文→subtitle
            scene0 = canonical['scenes'][0]
            check(f'{name}: 阿奇 scene[0] subtitle 非空（翠文映射）',
                  bool(scene0['subtitle']),
                  repr(scene0['subtitle']))
            check(f'{name}: 阿奇 scene[0] visual 非空（畫面映射）',
                  bool(scene0['visual']),
                  repr(scene0['visual']))

    # --- 2. kwargs byte 一致驗 ---
    kwargs = yaml_to_sc_kwargs(raw, num=num)
    kwargs_ser = serialize_kwargs(kwargs)
    ok, msg = deep_eq(kwargs_ser, fixture['kwargs'])
    check(f'{name}: kwargs 與快照一致（舊 API byte 不變）', ok, msg)

    print()


print(f'=== 結果：{PASS}/{PASS+FAIL} PASS ===')
if FAIL > 0:
    print(f'FAIL {FAIL} 件，請修正')
    sys.exit(1)
else:
    print('全 PASS — golden fixtures 驗證通過')
    sys.exit(0)
