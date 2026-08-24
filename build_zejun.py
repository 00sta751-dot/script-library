"""
build_zejun.py — 澤君 腳本庫 build script
由 init_owner_website.py 從模板生成
# 2026-08-17 shell 註記：<body> 後有「聊天體試拍批」入口橫幅（chat-trial-20260817.html），本腳本為 marker splice、不重生 shell，橫幅可存活重建。
# 2026-08-17 shell 註記2：頁面另含手插「聊天體試拍批」section（sect-chattrial，13 卡原生格式）；splice 不會動它。
# 2026-08-18 shell 註記3：sect-chattrial 內容已換裝「聊天體第01批」26 支中之 13 卡（大整改新法首批，舊試拍批依澤君 TG20654「撤掉」令移除）；splice 不會動它。
# 2026-08-24 shell 註記4：頁面另含手插「帶看實測批」section（sect-tour0822，13 卡，z13=v3 單據版；澤君 TG21765 令上線）；splice 不會動它。

對齊：
  - SOP_腳本上線_統一版_v2.md §5.2 新業主 build script 必含 7 件（圖卡兩件 2026-07-11 退役後 9→7；validate_deploy 側仍 9=待 C 決策）
  - yaml-driven（§6.5）：所有批次讀 yaml → 翻譯機 → 渲染

用法：
  python build_zejun.py --mode yaml --yaml-dir <yaml資料夾路徑> --batch-label "第 01 批 · 2026-XX-XX"
  python build_zejun.py --mode yaml --yaml-dir "<夾1>,<夾2>" --batch-label "標1,標2"
"""

import html as _html_module
import os
import re as _re_module
import sys
import io
import argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

LIB = os.path.dirname(os.path.abspath(__file__))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

# ============================================================
# CLI 解析
# ============================================================
_parser = argparse.ArgumentParser(description='build_zejun.py — 澤君腳本庫 build script')
_parser.add_argument('--mode', choices=['yaml'], default='yaml',
                     help='yaml=yaml-driven（唯一模式，新業主無 legacy hardcode）')
_parser.add_argument('--yaml-dir', dest='yaml_dir', default='',
                     help='yaml 批次資料夾絕對路徑；多批次以逗號分隔')
_parser.add_argument('--batch-label', dest='batch_label', default='',
                     help='批次顯示名稱；多批次以逗號分隔，與 yaml-dir 一一對應')
_parser.add_argument('--num-start', dest='num_start', type=int, default=1,
                     help='article 編號起點')
_parser.add_argument('--expected-count', dest='expected_count', type=int, default=None,
                     help='預期 yaml 數量（驗證用）')
_parser.add_argument('--threads-md', dest='threads_md', default='',
                     help='脆文 .md 檔案絕對路徑；未提供時自動偵測 yaml-dir 下 threads_*.md')
_args, _unknown = _parser.parse_known_args()

# ============================================================
# 業主設定（init_owner_website.py 替換 placeholder）
# ============================================================
OWNER_NAME   = '澤君'
OWNER_SLUG   = 'zejun'
THEME_COLOR  = '#F2B705'
HTML_FILE    = os.path.join(LIB, 'zejun.html')

# 派系顏色（新業主初始 8 色，編劇生產後可擴充）
PIE_COLORS = {
    '直球派':      '#6B2A1F',
    '嗆辣派':      '#B03A00',
    '人間觀察派':  '#2A4F6B',
    '故事戲劇派':  '#2A2A6B',
    '結構分析派':  '#4A4F2A',
    '市場觀察派':  '#2A6B6B',
    '自嘲反差派':  '#4A2A6B',
    '綜合派':      '#4A4A4A',
}

# ============================================================
# HTML escape 工具（P1#2 Codex fix — 防 XSS / DOM 破壞）
# ============================================================
def _esc_text(x):
    """文字內容 escape（不 escape 引號，避免顯示 &quot;）"""
    if x is None:
        return ''
    return _html_module.escape(str(x), quote=False)


def _esc_attr(x):
    """屬性值 escape（escape 引號，在 " " 引號屬性中安全）"""
    if x is None:
        return ''
    return _html_module.escape(str(x), quote=True)


_IMG_SRC_PATTERN = _re_module.compile(
    r'^[a-zA-Z0-9_\-./]+\.(jpg|jpeg|png|gif|webp|svg)$'
)


def _safe_img_src(src):
    """img src allowlist：只允許相對路徑 + 安全副檔名，拒絕 javascript: / data: scheme。"""
    if not src:
        return ''
    lower = src.lower()
    for bad_scheme in ('javascript:', 'data:', 'vbscript:'):
        if lower.startswith(bad_scheme):
            raise ValueError(f"img src 不允許 scheme {bad_scheme!r}：{src!r}")
    if not _IMG_SRC_PATTERN.match(src):
        raise ValueError(f"img src 不符合 allowlist（只允許相對路徑 + jpg/png/gif/webp/svg）：{src!r}")
    return _esc_attr(src)


SERIES = ('先別急著簽', '澤君走給你看', '工程師眼睛看房', '月薪8萬房仲日記')


def _series_for(yaml_data):
    """讀 YAML 系列欄；未標系列的專業內容集中到「月薪8萬房仲日記＋專業區」。"""
    raw = str(yaml_data.get('series') or yaml_data.get('系列') or yaml_data.get('series_name') or '')
    for name in SERIES:
        if name in raw:
            return name
    return '月薪8萬房仲日記'


# ============================================================
# article 渲染函式（對齊瑞祥 rux_article 規格 — SOP §5.2）
# ============================================================
def owner_article(num, title, pie, insight, scene, timeline, cta,
                  img=None, batch=None, caption=None,
                  platform=None, po_time=None, hashtag=None, series='月薪8萬房仲日記'):
    """渲染單篇腳本為 HTML article（新業主標準格式，對齊瑞祥 cd6f5bd 標竿）"""
    if batch is None:
        batch = '第 01 批'
    pid = OWNER_SLUG[:3] + str(num)
    color = PIE_COLORS.get(pie, '#444')
    Q = chr(39)

    # 時間軸 HTML（P1#2 fix：ts/say/sub/mirror 全走 _esc_text）
    tl_html = ''
    for ts, say, sub, *rest in timeline:
        mirror = rest[0] if rest else ''
        tl_html += (
            '        <div class="row">'
            '<div class="time">' + _esc_text(ts) + '</div>'
            '<div class="say">' + _esc_text(say) + '</div>'
        )
        if mirror:
            tl_html += '<div class="mirror">藏鏡人　' + Q + _esc_text(mirror) + Q + '</div>'
        if sub:
            tl_html += '<div class="sub">' + _esc_text(sub) + '</div>'
        tl_html += '</div>\n'

    # caption escape（改用統一 _esc_attr）
    cap_escaped = _esc_attr(caption) if caption else ''
    cap_attr = ' data-caption="' + cap_escaped + '"' if cap_escaped else ''
    copy_label = '複製文案' if cap_escaped else '複製腳本'

    # hashtag（P1#2 fix：tag 走 _esc_text，data-hashtags 屬性走 _esc_attr）
    hashtag_attr = ''
    hashtag_html = ''
    if hashtag:
        hashtag_attr = ' data-hashtags="' + _esc_attr(' '.join(hashtag)) + '"'
        hashtag_html = (
            '    <div class="hashtag-pool">\n' +
            ''.join('      <span class="hashtag">' + _esc_text(t) + '</span>\n' for t in hashtag) +
            '    </div>\n'
        )

    # platform / po_time meta（P1#2 fix：走 _esc_text）
    meta_extra = ''
    if platform:
        meta_extra += '      <span class="platform">▶ ' + _esc_text(platform) + '</span>\n'
    if po_time:
        meta_extra += '      <span class="po-time">⏰ ' + _esc_text(po_time) + '</span>\n'

    # article 組裝（P1#2 fix：title/insight/scene/cta/pie/batch 走 _esc_text）
    return (
        '<article class="card" id="' + _esc_attr(pid) + '" data-series="' + _esc_attr(series) + '"' + cap_attr + hashtag_attr + '>\n'
        '  <div class="card-head" style="--pie:' + _esc_attr(color) + '">\n'
        '    <div class="card-meta">\n'
        '      <button class="shot-toggle" type="button" aria-label="切換已拍過">已拍過</button>\n'
        ''  # 派系名為內部標籤、不對外露（C-016）；派系色仍由 card-head 左邊框 var(--pie) 呈現
        '      <span class="num">No. ' + _esc_text(str(num).zfill(2)) + '</span>\n'
        '      <span class="batch">' + _esc_text(batch) + '</span>\n'
        '      <span class="series-stamp">' + _esc_text(series) + '</span>\n'
        '    </div>\n' +
        (('    <div class="card-meta-extra">\n' + meta_extra + '    </div>\n') if meta_extra else '') +
        '    <h3 class="title">' + _esc_text(title) + '</h3>\n'
        '    <div class="insight">' + _esc_text(insight) + '</div>\n'
        '  </div>\n'
        '  <div class="card-body">\n'
        '    <div class="scene"><b>場景</b>　' + _esc_text(scene) + '</div>\n' +
        '    <div class="timeline">\n' +
        tl_html +
        '    </div>\n'
        '    <div class="cta">\n'
        '      <span class="cta-arrow">→</span>\n'
        '      <span>' + _esc_text(cta) + '</span>\n'
        '    </div>\n' +
        hashtag_html +
        '    <button class="copy-btn" onclick="copyScript(this)">' + copy_label + '</button>\n'
        '  </div>\n'
        '</article>'
    )


def section(roman, label, en, sect_id, cards, count):
    """渲染 section header + cards wrapper"""
    return (
        '<header class="section-head" id="sect-' + str(sect_id) + '">\n'
        '  <span class="roman">' + roman + '</span>\n'
        '  <span class="label">' + label + '<span class="en">' + en + '</span></span>\n'
        '  <span class="rule"></span>\n'
        '  <span class="count">' + str(count) + ' scripts</span>\n'
        '</header>\n'
        '<div class="cards">\n' +
        '\n'.join(cards) + '\n'
        '</div>'
    )


# ============================================================
# 脆文 Threads 渲染（B-3 — parse/卡片對齊 build_index.py，section-head + threads-grid 群組式）
# ============================================================
def parse_threads_md(md_path):
    """解析脆文 .md → [(tid, label, body, hashtag), ...]。
    支援瑞祥格式（## Threads NN（衍生自…）\n主題：…\n\n<body>\n\n#tags）。
    label 取主題行 × 前段（派系不顯示）；hashtag 取 # 開頭行。對齊 build_index.parse_threads_md。
    """
    with open(md_path, 'r', encoding='utf-8') as _f:
        raw = _f.read()
    blocks = _re_module.split(r'\n---\n', raw.strip())
    results = []
    for blk in blocks:
        blk = blk.strip()
        m_head = _re_module.search(r'##\s+Threads\s+(\d+)', blk)
        if not m_head:
            continue
        tid = 'T' + str(int(m_head.group(1))).zfill(2)
        m_theme = _re_module.search(r'主題：(.+)', blk)
        label = m_theme.group(1).strip().split('×')[0].strip() if m_theme else '觀點型'
        body_lines = []
        hashtag = ''
        in_frontmatter = False
        for ln in blk.splitlines():
            if ln.strip() == '---':
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue
            if _re_module.match(r'##\s+Threads\s+\d+', ln):
                continue
            if _re_module.match(r'主題：', ln):
                continue
            if ln.strip().startswith('#') and not ln.strip().startswith('##'):
                hashtag = ln.strip()
                continue
            if ln.strip().startswith('>'):
                continue
            if _re_module.match(r'^#\s+Threads', ln):
                continue
            body_lines.append(ln)
        body = '\n'.join(body_lines).strip()
        if body or hashtag:
            results.append((tid, label, body, hashtag))
    return results


def thread_card_owner(tid, label, body, hashtag):
    """渲染單篇脆文 .thread-card（複製鍵用 .copy-btn + copyThread()，沿用既有 CSS/JS）"""
    return (
        '<div class="thread-card">\n'
        '  <div class="thread-meta"><span class="thread-id">' + _esc_text(tid) + '</span>'
        '<span class="thread-label">' + _esc_text(label) + '</span></div>\n'
        '  <div class="thread-text">' + _esc_text(body) + '</div>\n' +
        (('  <div class="thread-hash">' + _esc_text(hashtag) + '</div>\n') if hashtag else '') +
        '  <button class="copy-btn" onclick="copyThread(this)">複製脆文</button>\n'
        '</div>'
    )


def sect_threads_owner(threads_data, batch_label):
    """渲染脆文 section（section-head + threads-grid，對齊本業主 shell 分組/收合 JS）"""
    count = len(threads_data)
    return (
        '<header class="section-head" id="sect-threads">\n'
        '  <span class="roman">✦</span>\n'
        '  <span class="label">脆文 Threads<span class="en">' + _esc_text(batch_label) + ' · ' + _esc_text(str(count)) + ' 篇</span></span>\n'
        '  <span class="rule"></span>\n'
        '  <span class="count">' + _esc_text(str(count)) + ' posts</span>\n'
        '</header>\n'
        '<div class="threads-grid">\n' +
        '\n'.join(thread_card_owner(t[0], t[1], t[2], t[3]) for t in threads_data) +
        '\n</div>'
    )


# ============================================================
# 澤君 article adapter（yaml_to_sc_kwargs → owner_article）
# ============================================================
def owner_article_adapter(yaml_data: dict, num: int, batch_label: str) -> str:
    """yaml dict → owner_article() HTML"""
    from yaml_to_sc import yaml_to_sc_kwargs
    kw = yaml_to_sc_kwargs(yaml_data, num=num)

    insight = yaml_data.get('insight') or yaml_data.get('核心洞察') or kw['scene']
    scene = kw['scene']

    return owner_article(
        num=kw['num'],
        title=kw['title'],
        pie=kw['pie'],
        insight=insight,
        scene=scene,
        timeline=kw['timeline'],
        cta=kw['cta'],
        img=kw.get('img'),
        batch=batch_label,
        caption=kw.get('caption'),
        platform=kw.get('platform_chip') or (kw['platforms'][0] if kw.get('platforms') else None),
        po_time=kw.get('po_time'),
        hashtag=kw.get('hashtag'),
        series=_series_for(yaml_data),
    )


# ============================================================
# yaml-driven 主路由
# ============================================================
print(f'build_{OWNER_SLUG}.py loaded OK')
print(f'HTML target: {HTML_FILE}')

if not _args.yaml_dir:
    # 尚未交付首批 YAML 時，允許空批次重建殼；不把空資料誤判成程式壞掉。
    print('yaml-dir 未提供：目前無批次資料，保留既有 HTML 殼（空批次容錯）')
    sys.exit(0)

from yaml_to_sc import load_yaml_articles

# C-016 日期分組（v2.4 — SOP §2.2 / §5.1A）
# 支援 dir1,dir2 + label1,label2；輸入順序為舊→新，輸出最新批在最上。
_yaml_dirs = [d.strip() for d in _args.yaml_dir.split(',') if d.strip()]
for _yaml_dir_path in _yaml_dirs:
    if not os.path.isdir(_yaml_dir_path):
        print(f'ERROR: yaml-dir 不存在：{_yaml_dir_path}', file=sys.stderr)
        sys.exit(1)
_batch_labels_raw = [label.strip() for label in _args.batch_label.split(',') if label.strip()]
if len(_batch_labels_raw) > len(_yaml_dirs):
    print('ERROR: --batch-label 數量不可多於 --yaml-dir', file=sys.stderr)
    sys.exit(1)

_yaml_batches = []
_num_cursor = _args.num_start
_single_expected = _args.expected_count if len(_yaml_dirs) == 1 else None
for _dir_i, _yaml_dir_path in enumerate(_yaml_dirs):
    _this_batch_label = (
        _batch_labels_raw[_dir_i]
        if _dir_i < len(_batch_labels_raw)
        else f'yaml-driven · {os.path.basename(_yaml_dir_path)}'
    )
    _this_yaml_articles = load_yaml_articles(
        _yaml_dir_path,
        expected_count=_single_expected if _dir_i == 0 else None,
    )
    _this_arts = [
        owner_article_adapter(_ydata, num=_num_cursor + _idx, batch_label=_this_batch_label)
        for _idx, _ydata in enumerate(_this_yaml_articles)
    ]
    _num_cursor += len(_this_arts)
    _yaml_batches.append((_this_batch_label, _this_arts))
    print(f'  載入 batch {_dir_i + 1}/{len(_yaml_dirs)}: {_this_batch_label} ({len(_this_arts)} 部)')

_yaml_total = sum(len(_arts) for _, _arts in _yaml_batches)
_latest_batch_label = _yaml_batches[-1][0] if _yaml_batches else ''
print(f'yaml articles built OK ({_yaml_total} 部 across {len(_yaml_batches)} 批次)')

# 單批保持既有 section id 與輸出字串，確保舊用法 byte-identical。
_all_sections_list = []
if len(_yaml_batches) == 1:
    _single_label, _single_arts = _yaml_batches[0]
    if _single_arts:
        _all_sections_list.append(
            section('', _single_label, _single_label, 'b_new', _single_arts, len(_single_arts))
        )
        print(f'  本批 section: {_single_label} ({len(_single_arts)} 部)')
else:
    for _section_i, (_batch_label, _batch_arts) in enumerate(reversed(_yaml_batches), start=1):
        if not _batch_arts:
            continue
        _all_sections_list.append(
            section('', _batch_label, _batch_label, f'b_new_{len(_yaml_batches) - _section_i + 1}', _batch_arts, len(_batch_arts))
        )
        print(f'  批次 section: {_batch_label} ({len(_batch_arts)} 部)')

all_sections = '\n\n'.join(_all_sections_list)
print(f'Sections assembled: {len(_all_sections_list)} 個（日期分組，無派系 group head）')

# ============================================================
# 脆文 Threads 偵測 + 渲染（B-3）
# ============================================================
_threads_html = ''
if _args.threads_md:
    if not os.path.isfile(_args.threads_md):
        print(f'ERROR: --threads-md 檔案不存在：{_args.threads_md}', file=sys.stderr)
        sys.exit(1)
    _threads_sources = [_args.threads_md]
else:
    _threads_sources = sorted(
        os.path.join(_yaml_dirs[-1], _tf)
        for _tf in os.listdir(_yaml_dirs[-1])
        if _tf.startswith('threads_') and _tf.endswith('.md')
    )
if _threads_sources:
    _threads_data = []
    for _tm in _threads_sources:
        _threads_data.extend(parse_threads_md(_tm))
    if _threads_data:
        _threads_html = sect_threads_owner(_threads_data, _latest_batch_label)
        print(f'脆文 Threads 渲染 OK（{len(_threads_data)} 篇）：{[os.path.basename(_t) for _t in _threads_sources]}')
    else:
        print(f'WARNING: 脆文檔解析為空：{_threads_sources}', file=sys.stderr)
else:
    print('脆文 Threads：本批無 threads_*.md，略過')

# ============================================================
# 寫入 HTML 檔案
# ============================================================
if not os.path.exists(HTML_FILE):
    print(f'ERROR: HTML 檔案不存在：{HTML_FILE}', file=sys.stderr)
    print('修復步驟：確認 init_owner_website.py 已跑過 --dry-run 以外的完整流程', file=sys.stderr)
    sys.exit(1)

with open(HTML_FILE, 'r', encoding='utf-8') as f:
    c = f.read()

# 冪等 dual-marker splice（B-2 可重跑 + B-3 脆文注入）
# 保留 SECTIONS_PLACEHOLDER / THREADS_PLACEHOLDER 兩行標記，讓每次 build 都找得到；
# sections 覆蓋 SECTIONS_PH 行後 → THREADS_PH 行前；threads 覆蓋 THREADS_PH 行後 → lightbox anchor 前。
SECTIONS_PH = '<!-- SECTIONS_PLACEHOLDER — build_' + OWNER_SLUG + '.py 負責替換此區塊 -->'
THREADS_PH  = '<!-- THREADS_PLACEHOLDER — build_' + OWNER_SLUG + '.py 負責替換此區塊 -->'
LIGHTBOX_ANCHOR = '<div class="lightbox-overlay" id="lightboxOverlay">'


def _find_ph_end(content, exact, fallback_prefix):
    pos = content.find(exact)
    if pos < 0:
        pos = content.find(fallback_prefix)
    if pos < 0:
        return -1, -1
    line_end = content.find('\n', pos)
    if line_end < 0:
        line_end = len(content)
    return pos, line_end + 1


sec_pos, sec_line_end = _find_ph_end(c, SECTIONS_PH, '<!-- SECTIONS_PLACEHOLDER')
if sec_pos < 0:
    print('ERROR: 找不到 SECTIONS_PLACEHOLDER 標記', file=sys.stderr)
    sys.exit(1)

thr_pos, thr_line_end = _find_ph_end(c, THREADS_PH, '<!-- THREADS_PLACEHOLDER')
if thr_pos < 0:
    print('ERROR: 找不到 THREADS_PLACEHOLDER 標記（請確認 HTML 殼已含此標記）', file=sys.stderr)
    sys.exit(1)
if thr_pos < sec_pos:
    print('ERROR: THREADS_PLACEHOLDER 出現在 SECTIONS_PLACEHOLDER 之前，HTML 結構異常', file=sys.stderr)
    sys.exit(1)

lightbox_pos = c.find(LIGHTBOX_ANCHOR, thr_line_end)
if lightbox_pos < 0:
    print('ERROR: 找不到 lightboxOverlay anchor，無法定位 threads 區塊結尾', file=sys.stderr)
    sys.exit(1)

sections_block = '\n' + all_sections + '\n\n' if all_sections else '\n'
threads_block = '\n' + _threads_html + '\n\n' if _threads_html else '\n'

nc = (
    c[:sec_line_end]
    + sections_block
    + THREADS_PH + '\n'
    + threads_block
    + c[lightbox_pos:]
)

with open(HTML_FILE, 'w', encoding='utf-8') as f:
    f.write(nc)

print(f'HTML 已更新：{HTML_FILE}')
print(f'Total articles: {_yaml_total}')
print()
print('next step:')
print(f'  1. python validate_deploy.py（驗 SOP §2 9 件）')
print(f'  2. git add {OWNER_SLUG}.html build_{OWNER_SLUG}.py')
print(f'  3. git commit + push')
print(f'  4. Playwright drive 線上自驗 9 件（SOP §8）')
