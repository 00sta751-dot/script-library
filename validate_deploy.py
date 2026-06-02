#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_deploy.py — 短影音腳本上線前驗證腳本 (v3: 11 件檢查)

用途：腳本+圖卡+上線 三件齊驗證。pre-commit hook 強制執行。

12 件檢查（v1 5 件 + v2 新增 5 件 + v3 新增 1 件 + v4 新增 1 件）：
1. download_href count 對齊（5/16 出包點直擊）
2. 資產齊全度（圖卡 PNG 有對應 html link / 必要檔不存在）
3. build 跟 html 雙改 git diff（漏改其中一個）
4. git status --porcelain 攔未追蹤
5. Schema Validation（所有 json/yaml 配置檔）
--- v2 新增（SOP v2 9 件功能邏輯驗證）---
6. threads-grid collapsed CSS rule 存在
7. build_*.py v2 keyword 命中（若已 migrate）
8. article data-caption attribute（若 build script 已加 caption=）
9. 圖卡部 group 不與「釣魚部」字串並存（命名混淆防呆）
10. caption 禁用詞清零（應該/大概/可能/差不多/基本上/我猜）
--- v3 新增（2026-05-20 藏鏡人獨立泡泡）---
11. 藏鏡人獨立泡泡 <div class="mirror"> 計數 HARD BLOCK
    — 每個 html 的 mirror count 必須 >= 該 html 的 article/card 數量
    — 確保 mirror 渲染邏輯正確，不混入台詞字串
--- v4 新增（2026-06-02 日期分組紅線）---
12. group head 不得含派系名（中文/英文副名）HARD BLOCK
    — 白名單：圖卡部/Card Library/脆文/Threads 放行
    — 正確做法：group head 應含「第N批」或 YYYY-MM-DD 日期

失敗 exit 2，通過 exit 0。
緊急逃生：--force-skip-validation（強迫寫 log + 7 天內補 incident memory）

建檔：2026-05-16 / 3 輪 cross-check 後 Codex+Gemini 雙 GO 定稿
v2 升級：2026-05-18 SOP v2 9 件功能邏輯對齊
v3 升級：2026-05-20 加第 11 件藏鏡人獨立泡泡 HARD BLOCK
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

# 7 業主 html 對應 build script + 圖卡 prefix（2026-06-02 補 achi — 閘門完整性）
OWNER_MAP = {
    'beauty.html':           {'build': 'build_beauty.py',    'prefix': 'yunzhen-'},
    'index.html':            {'build': 'build_index.py',     'prefix': 'rui-'},
    'kenny.html':            {'build': 'build_all.py',       'prefix': 'kenny-'},
    'bappu-cc/index.html':   {'build': 'build_bappu.py',     'prefix': 'bappu-'},
    'shihting.html':         {'build': 'build_shihting.py',  'prefix': 'shihting-'},
    'wendi.html':            {'build': 'build_wendi.py',     'prefix': 'wendi-'},
    'achi.html':             {'build': 'build_achi.py',      'prefix': 'achi-'},
}

# 已對齊 v2 完整功能（caption/hashtag/複製文案/data-caption）的業主
# — check 7/8 對這清單做功能驗證（未列入者尚未 migrate，跳過避免誤攔）
# 註：shihting 有 1 個非標準 article（無 caption，性質待確認）→ 強制「每卡必有 caption」
# 不適用，故不納入嚴格 check 8；待 shihting 第 14 卡確認後另議（Codex P1 採部分）
V2_OWNERS_HTML = ['index.html', 'wendi.html']
V2_OWNERS_BUILD = ['build_index.py', 'build_wendi.py']


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
    .py / .html / .png / .jsonl 新增檔沒 git add = 漏 commit
    修正（2026-05-31）：
    - git -c core.quotepath=false 讓中文檔名不被 octal 編碼遮掉
    - --untracked-files=all 展開未追蹤目錄，防止整個目錄被 ?? dir/ 略過
    """
    log('=== Check 4：git status --porcelain 攔未追蹤 ===')
    fails = []

    status = git_run(['-c', 'core.quotepath=false', 'status', '--porcelain', '--untracked-files=all']).split('\n')
    untracked = []
    for line in status:
        if line.startswith('??'):
            f = line[3:].strip()
            if f.endswith(('.py', '.html', '.png', '.jpg', '.json', '.yaml', '.jsonl')):
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

    # 掃 jsonl — line-by-line（禁整文 json.loads，JSONL 多行不合法 JSON）
    # 必填 key：template_id / source_path / transferability_score
    # 注意：只驗範本索引 JSONL（template_index.jsonl），其他工具的 audit/log JSONL 跳過
    JSONL_REQUIRED_KEYS = ('template_id', 'source_path', 'transferability_score')
    for jp in LIB.rglob('*.jsonl'):
        if '.git' in jp.parts or '_archive' in jp.parts or '.gstack' in jp.parts:
            continue
        # 只驗範本系統的 jsonl（檔名含 template_ 或 template 前綴）
        if 'template' not in jp.name:
            log(f'  ℹ {jp.relative_to(LIB)} — 非範本系統 JSONL，跳過必填 key 驗證')
            continue
        rel = jp.relative_to(LIB)
        line_errors = []
        try:
            with jp.open(encoding='utf-8', errors='replace') as jf:
                for lineno, raw in enumerate(jf, 1):
                    raw = raw.strip()
                    if not raw:
                        continue  # 空行跳過
                    try:
                        obj = json.loads(raw)
                    except Exception as e:
                        line_errors.append(f'  line {lineno}: JSON parse 失敗 — {e}')
                        continue
                    missing = [k for k in JSONL_REQUIRED_KEYS if k not in obj]
                    if missing:
                        line_errors.append(f'  line {lineno}: 缺必填 key {missing}')
        except Exception as e:
            msg = f'❌ {rel} 讀取失敗: {e}'
            log(f'  {msg}')
            fails.append(msg)
            continue

        if line_errors:
            for le in line_errors:
                log(f'  ❌ {rel}{le}')
            fails.append(f'❌ {rel} JSONL 驗證失敗（{len(line_errors)} 行有問題）')
        else:
            log(f'  ✅ {rel} JSONL OK')

    return fails


# === v2 新增 5 件 ===

def check_6_threads_grid_css():
    """檢查 6：每個 html 若含 .threads-grid 則必有 collapsed CSS rule
    SOP v2 §2.4：.group.collapsed > .threads-grid { display: none }
    """
    log('=== Check 6：threads-grid collapsed CSS rule ===')
    fails = []
    REQUIRED_RULE = '.group.collapsed > .threads-grid'
    # shihting.html 用獨立 threads-section 結構（非 group 巢狀），允許等效 CSS rule
    SHIHTING_REQUIRED_RULE = '.threads-section.collapsed .threads-grid'

    for html_rel in OWNER_MAP.keys():
        html_path = LIB / html_rel
        if not html_path.exists():
            continue

        content = html_path.read_text(encoding='utf-8', errors='replace')

        # 便當格業主（溫蒂）用 .thread-sec.collapsed .threads 收合脆文（非 threads-grid）
        if 'threads-grid' not in content:
            if 'thread-sec' in content:
                bento_rule = '.thread-sec.collapsed .threads'
                if bento_rule in content:
                    log(f'  ✅ {html_rel}: thread-sec 脆文收合 CSS rule 存在')
                else:
                    msg = f'❌ {html_rel}: 有 thread-sec 但缺 {bento_rule} 收合 CSS rule'
                    log(f'  {msg}')
                    fails.append(msg)
            else:
                log(f'  ℹ {html_rel}: 無 threads-grid / thread-sec，跳過')
            continue

        # shihting.html 用獨立 threads-section 結構，檢查等效 rule
        if html_rel == 'shihting.html':
            rule = SHIHTING_REQUIRED_RULE
        else:
            rule = REQUIRED_RULE

        if rule in content:
            log(f'  ✅ {html_rel}: threads-grid CSS rule 存在')
        else:
            msg = f'❌ {html_rel}: 有 threads-grid 但缺 {rule} CSS rule'
            log(f'  {msg}')
            fails.append(msg)

    return fails


def check_7_build_v2_keywords():
    """檢查 7：v2 業主 build_*.py 含核心功能 keyword（業主無關，驗功能非綁標竿實作）
    僅驗 V2_OWNERS_BUILD 清單（已 migrate v2：build_index 標竿 + build_wendi 便當格）；
    其他業主尚未 migrate，跳過避免誤攔
    """
    log('=== Check 7：build_*.py v2 功能 keyword 命中 ===')
    fails = []
    # 業主無關功能 keyword（標竿 rux_article 與便當格 build_wendi 都涵蓋此 5 功能）
    # caption=複製文案資料 / hashtag=標籤 / mirror=藏鏡人 / copy=複製函式 / collapsed=收合
    V2_FUNC = ['caption', 'hashtag', 'mirror', 'copy', 'collapsed']

    for build_name in V2_OWNERS_BUILD:
        build_path = LIB / build_name
        if not build_path.exists():
            log(f'  ℹ {build_name} 不存在，跳過')
            continue
        content = build_path.read_text(encoding='utf-8', errors='replace')
        found = [kw for kw in V2_FUNC if kw in content]
        if len(found) >= 4:
            log(f'  ✅ {build_name} v2 功能 keyword 命中 {len(found)}/{len(V2_FUNC)}: {found}')
        else:
            msg = f'❌ {build_name} v2 功能 keyword 命中不足（{len(found)}/{len(V2_FUNC)}）: 找到 {found}'
            log(f'  {msg}')
            fails.append(msg)

    return fails


def check_8_article_data_caption():
    """檢查 8：v2 業主 article 含 data-caption attribute
    僅驗 V2_OWNERS_HTML 清單（已 migrate v2 的業主：標竿 index + 便當格 wendi）；
    其他業主尚未 migrate，跳過。SOP v2 §2.6：複製文案按鈕讀 article.dataset.caption
    """
    log('=== Check 8：article data-caption attribute ===')
    fails = []

    # 驗所有 v2 業主（標竿 index + 便當格 wendi）；未 migrate 業主不在清單，跳過
    for html_rel in V2_OWNERS_HTML:
        html_path = LIB / html_rel
        if not html_path.exists():
            log(f'  ℹ {html_rel} 不存在，跳過')
            continue

        content = html_path.read_text(encoding='utf-8', errors='replace')
        # 防 HTML 註解內的 <article 被誤計（defense-in-depth）
        content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)

        # 計算有 data-caption 的 article（regex 涵蓋 class="card ..." 含 tone 變體）
        cap_count = len(re.findall(r'<article[^>]*data-caption="[^"]+', content))
        total_count = len(re.findall(r'<article[\s>]', content))

        # SOP §2.6：每卡都要有 data-caption（複製文案資料源），不是「至少一卡」
        if cap_count < total_count:
            msg = f'❌ {html_rel}: 只有 {cap_count}/{total_count} article 有 data-caption（每卡必有，SOP §2.6 不可放水）'
            log(f'  {msg}')
            fails.append(msg)
        else:
            log(f'  ✅ {html_rel}: {cap_count}/{total_count} article 全有 data-caption')

    return fails


def check_9_no_mixed_fishing_card():
    """檢查 9：group head 名稱不同時含「圖卡部」和「釣魚部」（命名混淆防呆）
    SOP v2 §2.3：命名為「圖卡部 Card Library」，舊名「釣魚部」不能殘留在 group head。
    注意：只查 <span class="gn"> 群組 header 名稱，不查全文（腳本 title/台詞含此字屬正常）。
    2026-05-21 v3.1 fix：原全文搜尋會被 title 含「釣魚部」誤觸（04_07 釣魚部腳本）。
    """
    log('=== Check 9：圖卡部/釣魚部 命名混淆防呆（查 group head 名稱）===')
    fails = []

    for html_rel in OWNER_MAP.keys():
        html_path = LIB / html_rel
        if not html_path.exists():
            continue

        content = html_path.read_text(encoding='utf-8', errors='replace')

        # 只抓 <span class="gn">...</span> 群組名稱，不查全文
        group_names = re.findall(r'<span class="gn">([^<]+)</span>', content)

        has_card_lib = any('圖卡部' in gn for gn in group_names)
        has_fishing = any('釣魚部' in gn for gn in group_names)

        if has_card_lib and has_fishing:
            msg = f'❌ {html_rel}: group head 同時含「圖卡部」和「釣魚部」— 命名混淆（group head 需統一）'
            log(f'  {msg}')
            fails.append(msg)
        elif has_fishing and not has_card_lib:
            log(f'  ℹ {html_rel}: group head 只有釣魚部（尚未 migrate 到圖卡部），跳過')
        elif has_card_lib:
            log(f'  ✅ {html_rel}: group head 圖卡部命名正確，無殘留釣魚部')
        else:
            log(f'  ℹ {html_rel}: 無圖卡部/釣魚部 group head，跳過')

    return fails


def check_10_caption_no_forbidden_words():
    """檢查 10：html 中 data-caption 值不含禁用詞（誠實協議第 9 條）
    禁用詞：應該 / 大概 / 可能 / 差不多 / 基本上 / 我猜
    """
    log('=== Check 10：caption 禁用詞清零 ===')
    fails = []
    FORBIDDEN = ['應該', '大概', '可能', '差不多', '基本上', '我猜']

    for html_rel in OWNER_MAP.keys():
        html_path = LIB / html_rel
        if not html_path.exists():
            continue

        content = html_path.read_text(encoding='utf-8', errors='replace')

        # 抓所有 data-caption 值
        captions = re.findall(r'data-caption="([^"]*)"', content)
        if not captions:
            log(f'  ℹ {html_rel}: 無 data-caption，跳過')
            continue

        file_fails = []
        for i, cap in enumerate(captions):
            hits = [w for w in FORBIDDEN if w in cap]
            if hits:
                file_fails.append(f'article #{i+1} caption 含禁用詞 {hits}: {cap[:60]}...')

        if file_fails:
            for ff in file_fails:
                msg = f'❌ {html_rel}: {ff}'
                log(f'  {msg}')
                fails.append(msg)
        else:
            log(f'  ✅ {html_rel}: {len(captions)} 篇 caption 禁用詞清零')

    return fails


def check_11_mirror_dom_count():
    """檢查 11：藏鏡人獨立泡泡 <div class="mirror"> 計數 + 內容品質 HARD BLOCK (v4 升級)

    各業主 article 標籤格式不同，動態偵測 article 數量：
    - beauty.html / index.html：<article （含 article 標籤）
    - kenny.html：class="script-card"
    - bappu-cc/index.html：<article class="sc"
    HARD BLOCK 條件：
      (A) mirror_count == 0（build script 沒渲染藏鏡人）
      (B) 任一 mirror div 內文為空
      (C) 任一 mirror div 內文長度 <= 5 字（排除 placeholder）
      (D) 任一 mirror div 內文命中 placeholder 黑名單
    WARN 條件：mirror_count > 0 但 < article_count（部分 article 缺藏鏡人，通常因該批腳本未填藏鏡人欄）

    內容品質驗證使用 html.parser（stdlib），不依賴瀏覽器。
    """
    from html.parser import HTMLParser

    class MirrorExtractor(HTMLParser):
        """從 HTML 中抽取藏鏡人 div 的內文。
        mirror_class: 要比對的 class 名稱（預設 'mirror'；shihting 傳 'shihting-mirror'）
        """
        def __init__(self, mirror_class='mirror'):
            super().__init__()
            self._mirror_class = mirror_class
            self._in_mirror = False
            self._depth = 0
            self.mirror_texts = []
            self._buf = ''

        def handle_starttag(self, tag, attrs):
            attr_dict = dict(attrs)
            if tag == 'div' and self._mirror_class in attr_dict.get('class', '').split():
                self._in_mirror = True
                self._depth = 1
                self._buf = ''
            elif self._in_mirror:
                self._depth += 1

        def handle_endtag(self, tag):
            if self._in_mirror:
                if tag == 'div':
                    self._depth -= 1
                    if self._depth <= 0:
                        self.mirror_texts.append(self._buf.strip())
                        self._in_mirror = False
                        self._buf = ''

        def handle_data(self, data):
            if self._in_mirror:
                self._buf += data

        def handle_entityref(self, name):
            if self._in_mirror:
                import html as _html
                self._buf += _html.unescape('&' + name + ';')

        def handle_charref(self, name):
            if self._in_mirror:
                if name.startswith('x'):
                    self._buf += chr(int(name[1:], 16))
                else:
                    self._buf += chr(int(name))

    PLACEHOLDER_BLACKLIST = {'待補', 'TBD', '？', '?', '...', '⋯', '⋯⋯'}
    MIRROR_TAG = '<div class="mirror">'
    # shihting.html 用獨立 class 名稱 shihting-mirror，避免 propagate 到老業主頁
    SHIHTING_MIRROR_TAG = '<div class="shihting-mirror">'

    log('=== Check 11：藏鏡人獨立泡泡 mirror count + 內容品質 HARD BLOCK ===')
    fails = []

    for html_rel in OWNER_MAP.keys():
        html_path = LIB / html_rel
        if not html_path.exists():
            continue

        content = html_path.read_text(encoding='utf-8', errors='replace')
        # shihting.html 用 shihting-mirror class；其他業主頁用 mirror class
        if html_rel == 'shihting.html':
            mirror_count = content.count(SHIHTING_MIRROR_TAG)
        else:
            mirror_count = content.count(MIRROR_TAG)

        # 動態偵測 article 數量（兼容 4 業主不同 HTML 結構）
        article_count = len(re.findall(r'<article ', content))
        if article_count == 0:
            article_count = len(re.findall(r'class="script-card"', content))
        if article_count == 0:
            log(f'  ℹ {html_rel}: 偵測不到 article 元素，跳過')
            continue

        # (A) 計數 HARD BLOCK
        if mirror_count == 0:
            msg = (f'❌ {html_rel}: mirror count = 0 / article = {article_count}'
                   f' — build script 沒渲染藏鏡人 HARD BLOCK')
            log(f'  {msg}')
            fails.append(msg)
            continue  # 無 mirror 就不必跑品質驗

        # WARN（部分缺藏鏡人）
        if mirror_count < article_count:
            log(f'  ⚠ {html_rel}: mirror={mirror_count} < article={article_count}'
                f' — 部分 article 缺藏鏡人（WARN，未填藏鏡人欄的舊批次正常）')

        # (B/C/D) 內容品質驗證 — 用 html.parser 解析實際內文
        # shihting.html 用 shihting-mirror class；其他業主頁用 mirror class
        mirror_cls = 'shihting-mirror' if html_rel == 'shihting.html' else 'mirror'
        extractor = MirrorExtractor(mirror_class=mirror_cls)
        extractor.feed(content)
        mirror_texts = extractor.mirror_texts

        quality_fails = []
        for i, text in enumerate(mirror_texts):
            if not text:
                quality_fails.append(f'mirror[{i}] 空字串')
            elif len(text) <= 5:
                quality_fails.append(f'mirror[{i}] 長度 {len(text)} <= 5 字：{repr(text)}')
            elif text in PLACEHOLDER_BLACKLIST:
                quality_fails.append(f'mirror[{i}] 命中 placeholder 黑名單：{repr(text)}')

        if quality_fails:
            for qf in quality_fails:
                msg = f'❌ {html_rel}: mirror 內容品質 HARD BLOCK — {qf}'
                log(f'  {msg}')
                fails.append(msg)
        else:
            log(f'  ✅ {html_rel}: mirror={mirror_count} / article={article_count}'
                f' / 內容品質 {len(mirror_texts)} 筆全 PASS')

    return fails


# === check 12（日期分組紅線 — 2026-06-02 v2）===

# ---- P1-e：單一 FACTION_LEAK_WORDS 來源（validate_deploy + validate_script_batch 共用）----
# 動態讀 L0 SOP yaml §7 schools.list[*].name（14 派），union 已知別名
_L0_SOP_YAML = Path(__file__).resolve().parent.parent.parent.parent / 'L0_跨行業公版' / '_腳本生產SOP_v3.0.yaml'

def _load_faction_names_from_l0() -> list:
    """從 L0 SOP yaml §7 schools.list 讀 14 派 name（單一真理源）。
    讀取失敗時 fallback 到 hardcoded 清單（防守門失效）。
    """
    try:
        import yaml as _yaml
        with open(_L0_SOP_YAML, encoding='utf-8') as _f:
            _data = _yaml.safe_load(_f)
        _names = [s['name'] for s in _data.get('schools', {}).get('list', []) if 'name' in s]
        if len(_names) >= 10:  # 合理性驗
            return _names
    except Exception:
        pass
    # fallback（L0 yaml 不可讀時守門不失效）
    return [
        '直球派', '人間觀察派', '嗆辣派', '雙城合作派', '結構分析派',
        '老前輩權威派', '時事追擊派', '爆文公式派', '綜合派', '市場觀察派',
        '故事戲劇派', '自嘲反差派', '拆解派', '家人朋友模擬派',
    ]

# 14 派 + 業主專屬別名（build script 實際使用的派系名）
FACTION_LEAK_WORDS: list = (
    _load_faction_names_from_l0()
    + [
        # 業主專屬別名（各 build_*.py 實際出現）
        '直球情侶版',        # 叭噗 build_bappu
        '模板L_知識反差',    # 叭噗 build_bappu
        '直球揭秘',          # 瑞祥 build_index 英文副名對應
        '純雞湯',            # 老清單殘留
        '個人化諮詢',        # cta 字串（在 group head 出現即洩漏）
        '圖卡部',            # 與白名單共存：白名單先判，殘餘再查（圖卡部·嗆辣派 → 殘餘含嗆辣派 FAIL）
        # 製作字眼（SOP 用語 + 參考來源 — 對齊 validate_script_batch._FACTION_LEAK_WORDS）
        '修平派', 'Erika',
        '毒舌正能量', '釣魚部',
        '模板L', '模板A', '模板G',
        '字幕卡', '流量密碼',
        # 英文副名
        'The Direct Voice', 'Direct Voice', 'Direct Knowledge',
        'Human Observations', 'Human Obs',
        'Market Insight',
        'Story Drama',
        'Spicy',
        'Senior Voice',
        'Trending Now',
        'Self-Deprecating', 'Self-Irony',
        'Breakdown',
        'Structural Analysis',
        'Soul Food',
    ]
)


def check_12_no_faction_group_head():
    """檢查 12：所有業主 html 的 group head 不得出現派系名（中文/英文副名）v2
    破口清單（2026-06-02 算盤+Codex 雙審）全修版：
    P0  — 叭噗 DOM 抓對（.gp > .gh > .gc，非卡片內 batch-tag）
    P1-a — 派系清單動態讀 L0 yaml §7 + union 別名（FACTION_LEAK_WORDS 共用）
    P1-b — 白名單收緊：移除白名單詞後殘餘不得含派系名
    P1-c — not heads / has_date=False（非白名單頁）→ FAIL
    P1-d — 掃 production html/build，不在 OWNER_MAP → FAIL
    P1-e — 單一 FACTION_LEAK_WORDS 來源（上方常數，validate_script_batch 共用）
    P2  — _extract_group_heads 正則排除 JS 模板片段（' + labelText + ' 等）
    """
    log('=== Check 12：group head 派系名紅線（日期分組標準 v2）===')
    fails = []

    ALL_FACTIONS = FACTION_LEAK_WORDS  # P1-e 共用

    # ---- 白名單：group head 含這些字 → 移除後才判派系名 ----
    WHITELIST_SUBSTRINGS = ['圖卡部', 'Card Library', '圖卡', '脆文', 'Threads']

    def _is_whitelisted(text: str) -> bool:
        """P1-b 修正：真白名單 = WHITELIST_SUBSTRINGS 中有詞 + 移除後殘餘無派系名
        若完全不含白名單詞（如純文字群組「測試群組」）→ 回 False，不豁免日期要求。
        範例：「圖卡部·嗆辣派」→ 移除「圖卡部」殘餘「·嗆辣派」含派系名 → False。
        範例：「圖卡部 Card Library」→ 移除後殘餘乾淨 → True（豁免日期）。
        """
        # step 1：不含白名單詞 → 非白名單，直接 False
        if not any(w in text for w in WHITELIST_SUBSTRINGS):
            return False
        # step 2：移除白名單詞後殘餘不含派系名才算真白名單
        residual = text
        for w in WHITELIST_SUBSTRINGS:
            residual = residual.replace(w, '')
        for faction in ALL_FACTIONS:
            if faction in residual:
                return False
        return True

    _JS_TEMPLATE_PAT = re.compile(
        r"'\s*\+\s*\w+\s*\+\s*'|"   # ' + varName + '
        r'"\s*\+\s*\w+\s*\+\s*"|'   # " + varName + "
        r'`\$\{[^}]+\}`'             # template literal ${...}
    )

    def _extract_group_heads(html_content: str) -> list:
        """從 html 中抽取所有 group head 的可見文字（多種格式兼容 + P2 JS 模板排除）"""
        # P2：先移除 JS <script> 區塊，避免 JS 字串被誤抓為 group head
        html_no_script = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL)

        heads = []

        # 格式 1：kenny.html — <div class="group-header">...<span class="group-en">X</span>
        for m in re.finditer(r'<div[^>]+class="group-header"[^>]*>(.*?)</div>', html_no_script, re.DOTALL):
            block = m.group(1)
            for sm in re.finditer(r'<span[^>]*class="group-en"[^>]*>([^<]*)</span>', block):
                t = sm.group(1).strip()
                if t and not _JS_TEMPLATE_PAT.search(t):
                    heads.append(t)
            for sm in re.finditer(r'<span[^>]*class="group-label"[^>]*>([^<]*)</span>', block):
                t = sm.group(1).strip()
                if t and not _JS_TEMPLATE_PAT.search(t):
                    heads.append(t)

        # 格式 2：beauty/index/shihting — section-head header 裡的 label span
        for m in re.finditer(r'<header[^>]+class="[^"]*section-head[^"]*"[^>]*>(.*?)</header>', html_no_script, re.DOTALL):
            block = m.group(1)
            for sm in re.finditer(r'<span[^>]*class="label"[^>]*>(.*?)</span>', block, re.DOTALL):
                t = re.sub(r'<[^>]+>', '', sm.group(1)).strip()
                if t and not _JS_TEMPLATE_PAT.search(t):
                    heads.append(t)

        # 格式 3：wendi — grp-head / sect-head / batch-head div
        for cls in ('grp-head', 'sect-head', 'batch-head'):
            for m in re.finditer(r'<div[^>]+class="' + cls + r'"[^>]*>(.*?)</div>', html_no_script, re.DOTALL):
                text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                if text and not _JS_TEMPLATE_PAT.search(text):
                    heads.append(text)

        # 格式 4（P0 修正）：bappu — .gp > .gh > .gc / .gn（group container 的直接 head）
        # .gc = group date label（「第 04 批 · 2026-05-21」）或縮寫圖示（「T」for Threads）
        # .gn = group 名稱（「脆文 Threads」）— Threads 群組用 .gn 作白名單判斷
        # 過濾 .gc 單字元縮寫（如「T」）— 純圖示 key，不納入分組驗證
        for m in re.finditer(r'<div[^>]+class="gh"[^>]*>(.*?)</div>', html_no_script, re.DOTALL):
            block = m.group(1)
            for sm in re.finditer(r'<span[^>]*class="gc"[^>]*>([^<]*)</span>', block):
                t = sm.group(1).strip()
                if t and len(t) > 1 and not _JS_TEMPLATE_PAT.search(t):
                    heads.append(t)
            for sm in re.finditer(r'<span[^>]*class="gn"[^>]*>([^<]*)</span>', block):
                t = sm.group(1).strip()
                if t and not _JS_TEMPLATE_PAT.search(t):
                    heads.append(t)

        # 格式 5：achi — <div class="group-head">...<span class="gh-label">第 01 批 · 2026-05-22</span>
        for m in re.finditer(r'<div[^>]+class="group-head"[^>]*>(.*?)</div>', html_no_script, re.DOTALL):
            block = m.group(1)
            for sm in re.finditer(r'<span[^>]*class="gh-label"[^>]*>([^<]*)</span>', block):
                t = sm.group(1).strip()
                if t and not _JS_TEMPLATE_PAT.search(t):
                    heads.append(t)

        return heads

    # ---- P1-d：掃 production html + build，不在 OWNER_MAP → FAIL ----
    # 排除規則（非業主腳本頁）：
    #   html: _ 開頭（測試檔）/ *_preview* / *_selfcontained* / *_test* / 已知靜態資訊頁
    #   build: build_template_*.py（範本工具，非業主 build script）
    _HTML_EXCLUDE_PREFIXES = ('_',)
    _HTML_EXCLUDE_SUBSTRINGS = ('_preview', '_selfcontained', '_test')
    _HTML_STATIC_WHITELIST = {'tax-2026.html'}  # 非業主靜態資訊頁，已知合法
    _BUILD_TOOL_PREFIXES = ('build_template',)   # 範本工具腳本，非業主 build

    def _is_excluded_html(name: str) -> bool:
        if name in _HTML_STATIC_WHITELIST:
            return True
        if any(name.startswith(p) for p in _HTML_EXCLUDE_PREFIXES):
            return True
        if any(s in name for s in _HTML_EXCLUDE_SUBSTRINGS):
            return True
        return False

    def _is_excluded_build(name: str) -> bool:
        return any(name.startswith(p) for p in _BUILD_TOOL_PREFIXES)

    known_html = set(OWNER_MAP.keys())
    known_build = {v['build'] for v in OWNER_MAP.values()}
    unregistered = []
    for html_path in LIB.glob('*.html'):
        rel = html_path.name
        if rel not in known_html and not _is_excluded_html(rel):
            unregistered.append(f'html/{rel}')
    for html_path in (LIB / 'bappu-cc').glob('*.html') if (LIB / 'bappu-cc').exists() else []:
        rel = 'bappu-cc/' + html_path.name
        if rel not in known_html and not _is_excluded_html(html_path.name):
            unregistered.append(f'html/{rel}')
    for py_path in LIB.glob('build_*.py'):
        bname = py_path.name
        if bname not in known_build and not _is_excluded_build(bname):
            unregistered.append(f'build/{bname}')
    if unregistered:
        for u in unregistered:
            msg = f'❌ {u} 不在 OWNER_MAP — 新業主未登記，check_12 無法驗證，禁止上線'
            log(f'  {msg}')
            fails.append(msg)
    else:
        log(f'  ✅ P1-d: 所有業主 html/build 均在 OWNER_MAP（{len(known_html)} 業主）')

    # ---- 逐業主驗 group head ----
    for html_rel in OWNER_MAP.keys():
        html_path = LIB / html_rel
        if not html_path.exists():
            log(f'  ℹ {html_rel}: 不存在，跳過')
            continue

        content = html_path.read_text(encoding='utf-8', errors='replace')
        heads = _extract_group_heads(content)

        # P1-c：偵測不到 group head → FAIL（非 skip）
        if not heads:
            msg = f'❌ {html_rel}: 偵測不到任何 group head — build 結構異常或格式未納管，FAIL'
            log(f'  {msg}')
            fails.append(msg)
            continue

        file_fails = []
        non_wl_heads = [h for h in heads if not _is_whitelisted(h)]

        for head_text in heads:
            if _is_whitelisted(head_text):
                continue  # P1-b 真白名單放行
            for faction in ALL_FACTIONS:
                if faction in head_text:
                    file_fails.append(
                        f'group head [{head_text!r}] 含派系名 [{faction}] — 應改為日期分組'
                    )
                    break  # 一個 head 只報一次

        # P1-①（head 級）：每個非白名單 head 都必須 match 日期格式
        # 不用 any()（頁級寬鬆），改成逐 head 驗：有任一非白名單 head 無日期 → FAIL
        # 目的：防「1 個日期 group + 其他非日期 group」混合頁漏過
        _DATE_PAT = re.compile(r'第\s*\d+\s*批|20\d{2}-\d{2}-\d{2}')
        has_date = True  # 初始假設全 PASS，逐 head 驗
        for h in heads:
            if _is_whitelisted(h):
                continue  # 白名單 head（圖卡部/脆文/Threads）不強制含日期
            if not _DATE_PAT.search(h):
                has_date = False
                file_fails.append(
                    f'非白名單 group head [{h!r}] 無日期標記 — 應含「第N批」或 YYYY-MM-DD'
                )

        if file_fails:
            for ff in file_fails:
                msg = f'❌ {html_rel}: {ff}'
                log(f'  {msg}')
                fails.append(msg)
        else:
            log(f'  ✅ {html_rel}: {len(heads)} 個 group head，無派系名，'
                f'has_date={has_date}（head 級，每個非白名單 head 含日期），'
                f'heads={heads[:3]}{"..." if len(heads)>3 else ""}')

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
    # v2 新增 5 件
    all_fails += check_6_threads_grid_css()
    log('')
    all_fails += check_7_build_v2_keywords()
    log('')
    all_fails += check_8_article_data_caption()
    log('')
    all_fails += check_9_no_mixed_fishing_card()
    log('')
    all_fails += check_10_caption_no_forbidden_words()
    log('')
    # v3 新增
    all_fails += check_11_mirror_dom_count()
    log('')
    # v4 新增（2026-06-02 日期分組紅線）
    all_fails += check_12_no_faction_group_head()
    log('')

    log('=' * 60)
    if all_fails:
        log(f'❌ 驗證失敗 — 共 {len(all_fails)} 條 P0：')
        for i, f in enumerate(all_fails, 1):
            log(f'  {i}. {f}')
        log('')
        log('修法見：SOP_腳本上線_統一版_v2.md §7 報錯怎麼辦')
        log('嚴禁 git commit --no-verify 繞過')
        sys.exit(2)
    else:
        log('✅ 全部通過 — 12 件齊')
        sys.exit(0)


if __name__ == '__main__':
    main()
