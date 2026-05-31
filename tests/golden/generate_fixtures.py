#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_fixtures.py — 生成 golden fixtures
用途：一次性建立 6 支 canonical + kwargs 快照（改動前後驗 byte 不變）
注意：只在「第一次建立」或「刻意更新快照」時手動跑，平時 test_golden.py 用讀回比對。
"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from yaml_to_sc import load_yaml_articles, normalize_script_to_canonical, yaml_to_sc_kwargs

BASE = r'C:\Users\00sta\Documents\Claude\Projects\短影音系統\L2_業主層'
RUX  = BASE + r'\房仲_瑞祥\01_腳本生產\第34批_試水批_2026-05-23'
BAPPU = BASE + r'\情侶_叭噗_小C\02_腳本生產\第04批_試水批_2026-05-21'
ACHI  = BASE + r'\餐飲_阿奇\01_腳本生產\第01批_2026-05-22'

OUT_DIR = os.path.dirname(__file__)

specs = [
    # (dir, idx, num, fixture_name)
    (RUX,   0,  3401, 'rux_34_01'),
    (RUX,   1,  3402, 'rux_34_02'),
    (BAPPU, 0,  401,  'bappu_04_01'),
    (BAPPU, 1,  402,  'bappu_04_02'),
    (ACHI,  0,  1001, 'achi_01_01'),
    (ACHI,  1,  1002, 'achi_01_02'),
]

for (d, idx, num, name) in specs:
    arts = load_yaml_articles(d)
    raw = arts[idx]
    canonical = normalize_script_to_canonical(raw)
    kwargs = yaml_to_sc_kwargs(raw, num=num)

    # kwargs 含 timeline（list of tuple），需 serialize 成 list of list
    def serialize_kwargs(kw):
        kw2 = dict(kw)
        kw2['timeline'] = [list(t) for t in kw2['timeline']]
        return kw2

    fixture = {
        'canonical': canonical,
        'kwargs': serialize_kwargs(kwargs),
    }
    out_path = os.path.join(OUT_DIR, f'{name}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(fixture, f, ensure_ascii=False, indent=2)
    print(f'[OK] {name}.json')

print('Done. 6 fixtures generated.')
