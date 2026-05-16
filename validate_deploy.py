#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_deploy.py — 短影音腳本上線前驗證腳本 (MVP 5 件檢查)

用途：腳本+圖卡+上線 三件齊驗證。pre-commit hook 強制執行。

5 件檢查：
1. download_href count 對齊（5/16 出包點直擊）
2. 資產齊全度（圖卡 PNG 有對應 html link / 必要檔不存在）
3. build 跟 html 雙改 git diff（漏改其中一個）
4. git status --porcelain 攔未追蹤
5. Schema Validation（所有 json/yaml 配置檔）

失敗 exit 2，通過 exit 0。
緊急逃生：--force-skip-validation（強迫寫 log + 7 天內補 incident memory）

建檔：2026-05-16 / 3 輪 cross-check 後 Codex+Gemini 雙 GO 定稿
"""

import os
import sys
import re
import json
import subprocess
from pathlib import Path
from datetime import datetime

# Windows cp950 → utf-8 fix（emoji + 中文 print 不噴）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# === 設定 ===
LIB = Path(__file__).parent.resolve()
LOG_FILE = LIB / '.validate_deploy.log'

# 4 業主 html 對應 build script + 圖卡 prefix
OWNER_MAP = {
    'beauty.html':           {'build': 'build_beauty.py', 'prefix': 'yunzhen-'},
    'index.html':            {'build': 'build_index.py',  'prefix': 'rui-'},
    'kenny.html':            {'build': 'build_all.py',    'prefix': 'kenny-'},
    'bappu-cc/index.html':   {'build': 'build_bappu.py',  'prefix': 'bappu-'},
}


# === 工具 ===

def log(msg):
    print(msg, flush=True)


def write_skip_log(reason):
    """緊急逃生時寫 log"""
    ts = datetime.now().isoformat()
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f'[{ts}] FORCE_SKIP: {reason}\n')


def git_run(args):
    """跑 git 拿輸出"""
    try:
        r = subprocess.run(['git'] + args, capture_output=True, text=True,
                           cwd=str(LIB), encoding='utf-8', errors='replace')
        return r.stdout.strip()
    except Exception as e:
        return ''


# === 5 件檢查 ===

def check_1_download_href_count():
    """檢查 1：download_href count 對齊
    每個 .html header「配套圖卡 X 張」必須 = count(<a class="download-btn">)
    """
    log('=== Check 1：download_href count 對齊 ===')
    fails = []

    for html_rel in OWNER_MAP.keys():
        html_path = LIB / html_rel
        if not html_path.exists():
            continue

        content = html_path.read_text(encoding='utf-8', errors='replace')

        # count download-btn anchors
        btn_count = len(re.findall(r'<a class="download-btn"', content))

        # find header 「配套圖卡 X 張」
        m = re.search(r'配套圖卡\s*(\d+)\s*張', content)
        if not m:
            log(f'  ℹ {html_rel}: 無 header 配套圖卡 X 張（跳過）')
            continue

        header_count = int(m.group(1))

        if btn_count == header_count:
            log(f'  ✅ {html_rel}: header={header_count} = btn={btn_count}')
        else:
            msg = f'❌ {html_rel}: header 寫 {header_count} 張 但實際 download-btn = {btn_count}'
            log(f'  {msg}')
            fails.append(msg)

    return fails


def check_2_asset_completeness():
    """檢查 2：資產齊全度
    每個 .html 內所有 <a class="download-btn" href="./xxx.png"> 的 PNG 必須存在
    """
    log('=== Check 2：資產齊全度 ===')
    fails = []

    for html_rel in OWNER_MAP.keys():
        html_path = LIB / html_rel
        if not html_path.exists():
            continue

        content = html_path.read_text(encoding='utf-8', errors='replace')

        # find all download-btn href
        hrefs = re.findall(r'<a class="download-btn"\s+href="([^"]+)"', content)

        html_dir = html_path.parent
        for href in hrefs:
            asset = html_dir / href
            if asset.exists():
                log(f'  ✅ {html_rel} → {href} 存在')
            else:
                msg = f'❌ {html_rel} 引用 {href} 但檔不存在'
                log(f'  {msg}')
                fails.append(msg)

    return fails


def check_3_build_html_dual_change():
    """檢查 3：build 跟 html 雙改 git diff
    Modified .html 但沒 Modified build_*.py = 漏改
    或反之
    Added (first commit) build_*.py 不算漏改（歷史檔首次上 git 場景）
    """
    log('=== Check 3：build 跟 html 雙改 git diff ===')
    fails = []

    # name-status: A=Added M=Modified D=Deleted R=Renamed
    raw = git_run(['diff', '--cached', '--name-status'])
    if not raw:
        log('  ℹ 沒 staged 檔，跳過（純手動跑時）')
        return fails

    entries = []  # list of (status, path)
    for line in raw.split('\n'):
        parts = line.split('\t')
        if len(parts) >= 2:
            entries.append((parts[0][0], parts[1]))  # status 第一個字元

    log(f'  staged: {entries}')

    # 找 staged 內的 Modified .html / Modified build_*.py / Added build_*.py
    html_modified = [p for st, p in entries if p.endswith('.html') and st == 'M']
    py_modified = [p for st, p in entries if p.endswith('.py') and ('build_' in p or 'update_' in p) and st == 'M']
    py_added = [p for st, p in entries if p.endswith('.py') and ('build_' in p or 'update_' in p) and st == 'A']

    if html_modified and not py_modified:
        msg = f'❌ Modified .html ({html_modified}) 但沒 Modified build_*.py — 手 patch html 沒同步原始碼'
        log(f'  {msg}')
        fails.append(msg)
    elif py_modified and not html_modified:
        msg = f'❌ Modified build_*.py ({py_modified}) 但沒對應 .html — 跑了 build 沒 stage 結果'
        log(f'  {msg}')
        fails.append(msg)
    elif py_added and not html_modified and not py_modified:
        log(f'  ℹ Added (first commit) py: {py_added} — 歷史檔首次上 git，跳過雙改檢查')
    else:
        log(f'  ✅ html_modified={len(html_modified)} / py_modified={len(py_modified)} / py_added={len(py_added)}')

    return fails


def check_4_untracked_files():
    """檢查 4：git status --porcelain 攔未追蹤
    .py / .html / .png 新增檔沒 git add = 漏 commit
    """
    log('=== Check 4：git status --porcelain 攔未追蹤 ===')
    fails = []

    status = git_run(['status', '--porcelain']).split('\n')
    untracked = []
    for line in status:
        if line.startswith('??'):
            f = line[3:].strip()
            if f.endswith(('.py', '.html', '.png', '.jpg', '.json', '.yaml')):
                untracked.append(f)

    if untracked:
        msg = f'❌ 發現未追蹤檔（新增沒 git add）：{untracked}'
        log(f'  {msg}')
        fails.append(msg)
    else:
        log('  ✅ 沒未追蹤檔')

    return fails


def check_5_schema_validation():
    """檢查 5：Schema Validation
    所有 *.json 跑 json.loads
    *.yaml 跑 yaml.safe_load（若有 yaml lib）
    """
    log('=== Check 5：Schema Validation ===')
    fails = []

    # 掃 json
    for jp in LIB.rglob('*.json'):
        if '.git' in jp.parts or '_archive' in jp.parts:
            continue
        try:
            json.loads(jp.read_text(encoding='utf-8', errors='replace'))
            log(f'  ✅ {jp.relative_to(LIB)} JSON OK')
        except Exception as e:
            msg = f'❌ {jp.relative_to(LIB)} JSON parse 失敗: {e}'
            log(f'  {msg}')
            fails.append(msg)

    # 掃 yaml（若 yaml lib 在）
    try:
        import yaml
        for yp in LIB.rglob('*.y*ml'):
            if '.git' in yp.parts or '_archive' in yp.parts:
                continue
            try:
                yaml.safe_load(yp.read_text(encoding='utf-8', errors='replace'))
                log(f'  ✅ {yp.relative_to(LIB)} YAML OK')
            except Exception as e:
                msg = f'❌ {yp.relative_to(LIB)} YAML parse 失敗: {e}'
                log(f'  {msg}')
                fails.append(msg)
    except ImportError:
        log('  ℹ 沒裝 pyyaml，跳過 YAML 檢查')

    return fails


# === main ===

def main():
    # 緊急逃生
    if '--force-skip-validation' in sys.argv:
        reason = ' '.join(sys.argv[2:]) if len(sys.argv) > 2 else 'no reason'
        write_skip_log(reason)
        log(f'⚠ FORCE SKIP — 已寫入 {LOG_FILE.name}，7 天內必補 incident memory')
        sys.exit(0)

    log(f'=== validate_deploy.py 上線前驗證 — {datetime.now().isoformat()} ===')
    log(f'目錄：{LIB}')
    log('')

    all_fails = []
    all_fails += check_1_download_href_count()
    log('')
    all_fails += check_2_asset_completeness()
    log('')
    all_fails += check_3_build_html_dual_change()
    log('')
    all_fails += check_4_untracked_files()
    log('')
    all_fails += check_5_schema_validation()
    log('')

    log('=' * 60)
    if all_fails:
        log(f'❌ 驗證失敗 — 共 {len(all_fails)} 條 P0：')
        for i, f in enumerate(all_fails, 1):
            log(f'  {i}. {f}')
        log('')
        log('修法見：SOP_腳本上線_統一版.md §3 報錯怎麼辦')
        log('嚴禁 git commit --no-verify 繞過')
        sys.exit(2)
    else:
        log('✅ 全部通過 — 5 件齊')
        sys.exit(0)


if __name__ == '__main__':
    main()
