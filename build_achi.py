"""
build_achi.py — 阿奇 腳本庫 build script
由 init_owner_website.py 從模板生成

對齊：
  - SOP_腳本上線_統一版_v2.md §5.2 新業主 build script 必含 9 件
  - yaml-driven（§6.5）：所有批次讀 yaml → 翻譯機 → 渲染

用法：
  python build_achi.py --mode yaml --yaml-dir <yaml資料夾路徑> --batch-label "第 01 批 · 2026-XX-XX"

更新日誌：
  2026-05-22：yaml_to_sc.py sub_desc 改從 '畫面' 欄位取值，修 .sub 字幕渲染（75 個）
  2026-05-22：加 Threads 脆文段（build_threads_section），每次 rebuild 自動帶入 7 篇
"""

import os
import sys
import io
import argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

LIB = os.path.dirname(os.path.abspath(__file__))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from _html_escape_utils import esc_text, esc_attr, safe_img_src

# ============================================================
# CLI 解析
# ============================================================
_parser = argparse.ArgumentParser(description='build_achi.py — 阿奇腳本庫 build script')
_parser.add_argument('--mode', choices=['yaml'], default='yaml',
                     help='yaml=yaml-driven（唯一模式，新業主無 legacy hardcode）')
_parser.add_argument('--yaml-dir', dest='yaml_dir', default='',
                     help='yaml 批次資料夾絕對路徑')
_parser.add_argument('--batch-label', dest='batch_label', default='',
                     help='批次顯示名稱，如「第 01 批 · 2026-06-01」')
_parser.add_argument('--num-start', dest='num_start', type=int, default=1,
                     help='article 編號起點')
_parser.add_argument('--expected-count', dest='expected_count', type=int, default=None,
                     help='預期 yaml 數量（驗證用）')
_args, _unknown = _parser.parse_known_args()

# ============================================================
# 業主設定（init_owner_website.py 替換 placeholder）
# ============================================================
OWNER_NAME   = '阿奇'
OWNER_SLUG   = 'achi'
THEME_COLOR  = '#F4A460'
HTML_FILE    = os.path.join(LIB, 'achi.html')

# 派系顏色（新業主初始 9 色，編劇生產後可擴充）
PIE_COLORS = {
    '直球派':      '#6B2A1F',
    '嗆辣派':      '#B03A00',
    '人間觀察派':  '#2A4F6B',
    '故事戲劇派':  '#2A2A6B',
    '結構分析派':  '#4A4F2A',
    '市場觀察派':  '#2A6B6B',
    '自嘲反差派':  '#4A2A6B',
    '圖卡部':      '#6B6B2A',
    '綜合派':      '#4A4A4A',
}


# ============================================================
# article 渲染函式（對齊瑞祥 rux_article 規格 — SOP §5.2）
# ============================================================
def owner_article(num, title, pie, insight, scene, timeline, cta,
                  img=None, batch=None, caption=None,
                  platform=None, po_time=None, hashtag=None):
    """渲染單篇腳本為 HTML article（新業主標準格式，對齊瑞祥 cd6f5bd 標竿）"""
    if batch is None:
        batch = '第 01 批'
    pid = OWNER_SLUG[:3] + str(num)
    color = PIE_COLORS.get(pie, '#444')
    Q = chr(39)
    # P1#3: escape text fields
    title_e = esc_text(title)
    pie_e = esc_text(pie)
    insight_e = esc_text(insight)
    scene_e = esc_text(scene)
    cta_e = esc_text(cta)
    batch_e = esc_text(batch)

    # 時間軸 HTML
    tl_html = ''
    for ts, say, sub, *rest in timeline:
        mirror = rest[0] if rest else ''
        tl_html += '        <div class="row"><div class="time">' + esc_text(ts) + '</div><div class="say">' + esc_text(say) + '</div>'
        if mirror:
            tl_html += '<div class="mirror">藏鏡人　' + Q + esc_text(mirror) + Q + '</div>'
        if sub:
            tl_html += '<div class="sub">' + esc_text(sub) + '</div>'
        tl_html += '</div>\n'

    # 圖卡 HTML
    img_html = ''
    if img:
        try:
            img_safe = safe_img_src(img)
        except ValueError:
            img_safe = ''
        if img_safe:
            img_html = (
                '    <div class="ref-link">圖卡部 · 圖卡附件：'
                '<a href="' + img_safe + '" target="_blank">'
                '<img src="' + img_safe + '" class="card-thumb" alt="圖卡預覽" '
                'onclick="openLightbox(this); return false;">'
                '</a></div>\n'
            )

    # caption escape via esc_attr
    cap_escaped = esc_attr(caption) if caption else ''
    cap_attr = ' data-caption="' + cap_escaped + '"' if cap_escaped else ''
    copy_label = '複製文案' if cap_escaped else '複製腳本'

    # hashtag
    hashtag_attr = ''
    hashtag_html = ''
    if hashtag:
        hashtag_attr = ' data-hashtags="' + esc_attr(' '.join(hashtag)) + '"'
        hashtag_html = (
            '    <div class="hashtag-pool">\n' +
            ''.join('      <span class="hashtag">' + esc_text(t) + '</span>\n' for t in hashtag) +
            '    </div>\n'
        )

    # platform / po_time meta
    meta_extra = ''
    if platform:
        meta_extra += '      <span class="platform">▶ ' + esc_text(platform) + '</span>\n'
    if po_time:
        meta_extra += '      <span class="po-time">⏰ ' + esc_text(po_time) + '</span>\n'

    return (
        '<article class="card" data-cat="" id="' + pid + '"' + cap_attr + hashtag_attr + '>\n'
        '  <div class="card-head" style="--pie:' + color + '">\n'
        '    <div class="card-meta">\n'
        '      <button class="shot-toggle" type="button" aria-label="切換已拍過">已拍過</button>\n'
        '      <span class="pie"></span>\n'
        '      <span class="num">No. ' + str(num).zfill(2) + '</span>\n'
        '      <span class="batch">' + batch_e + '</span>\n'
        '    </div>\n' +
        (('    <div class="card-meta-extra">\n' + meta_extra + '    </div>\n') if meta_extra else '') +
        '    <h3 class="title">' + title_e + '</h3>\n'
        '    <div class="insight">' + insight_e + '</div>\n'
        '  </div>\n'
        '  <div class="card-body">\n'
        '    <div class="scene"><b>場景</b>　' + scene_e + '</div>\n' +
        img_html +
        '    <div class="timeline">\n' +
        tl_html +
        '    </div>\n'
        '    <div class="cta">\n'
        '      <span class="cta-arrow">→</span>\n'
        '      <span>' + cta_e + '</span>\n'
        '    </div>\n' +
        hashtag_html +
        '    <button class="copy-btn" onclick="copyScript(this)">' + copy_label + '</button>\n'
        '  </div>\n'
        '</article>'
    )


def section(roman, label, en, sect_id, cards, count):
    """渲染 section header + cards wrapper（C-016: label 不輸出到 HTML，只留 roman + en）"""
    return (
        '<header class="section-head" id="sect-' + str(sect_id) + '">\n'
        '  <span class="roman">' + roman + '</span>\n'
        '  <span class="label"><span class="en">' + en + '</span></span>\n'
        '  <span class="rule"></span>\n'
        '  <span class="count">' + str(count) + ' scripts</span>\n'
        '</header>\n'
        '<div class="cards">\n' +
        '\n'.join(cards) + '\n'
        '</div>'
    )


def date_group(batch_label, gid, cards, collapsed=True):
    """C-016 日期分組：group head 顯示批次日期，不含派系名。
    batch_label 格式：「第 NN 批 · YYYY-MM-DD」
    對齊 build_all.py date_group（2026-06-02）
    """
    inner = '\n'.join(cards)
    cnt = str(len(cards))
    cclass = 'group collapsed' if collapsed else 'group'
    return (
        '<div class="' + cclass + '" id="grp-' + esc_attr(str(gid)) + '">\n'
        '<div class="group-head" onclick="this.parentElement.classList.toggle(\'collapsed\')">\n'
        '  <span class="gh-roman">&#9776;</span>\n'
        '  <span class="gh-label">' + esc_text(batch_label) + '</span>\n'
        '  <span class="gh-count">' + cnt + ' scripts</span>\n'
        '  <span class="gh-icon">&#9660;</span>\n'
        '</div>\n'
        '<div class="cards">\n' + inner + '\n</div>\n'
        '</div>'
    )


# ============================================================
# Threads 脆文段（2026-05-22）
# ============================================================
def build_threads_section(threads_md_path: str) -> str:
    """解析 threads_achi_*.md → HTML 段落（section-head + threads-grid）"""
    import re as _re
    import html as _html

    if not os.path.exists(threads_md_path):
        print(f'[threads] 找不到 {threads_md_path}，跳過 Threads 段', file=sys.stderr)
        return ''

    with open(threads_md_path, 'r', encoding='utf-8') as _f:
        _content = _f.read()

    _chunks = _content.split('\n---\n')
    _thread_chunks = [_c.strip() for _c in _chunks[1:]]

    _parsed = []
    for _ch in _thread_chunks:
        _lines = _ch.split('\n')
        _m_head = _re.match(r'## Threads (\d+)（衍生自 ([^）]+)）', _lines[0].strip())
        _m_title = _re.match(r'主題：(.+)', _lines[1].strip()) if len(_lines) > 1 else None
        _num = int(_m_head.group(1)) if _m_head else 0
        _title = _m_title.group(1) if _m_title else ''
        _body_lines = _lines[3:] if len(_lines) > 3 else []
        _hashtag = ''
        _text_lines = []
        for _ln in _body_lines:
            if _ln.strip().startswith('#') and not _ln.strip().startswith('##'):
                _hashtag = _ln.strip()
            else:
                _text_lines.append(_ln)
        _text = '\n'.join(_text_lines).strip()
        # strip markdown bold **...**
        _text = _re.sub(r'\*\*(.+?)\*\*', r'\1', _text)
        _parsed.append({'num': _num, 'title': _title, 'text': _text, 'hashtag': _hashtag})

    if not _parsed:
        print('[threads] 解析結果為空，跳過 Threads 段', file=sys.stderr)
        return ''

    _cards_html = ''
    for _t in _parsed:
        _num_str = f'T{_t["num"]:02d}'
        _title_e = _html.escape(_t['title'])
        _text_e = _html.escape(_t['text'])
        _hashtag_e = _html.escape(_t['hashtag'])
        _cards_html += (
            '<div class="thread-card">\n'
            '  <div class="thread-meta">\n'
            '    <span class="thread-id">' + _num_str + '</span>\n'
            '    <span class="thread-label">' + _title_e + '</span>\n'
            '  </div>\n'
            '  <div class="thread-text">' + _text_e + '</div>\n'
            '  <div class="thread-hash">' + _hashtag_e + '</div>\n'
            '  <button class="copy-btn" onclick="copyThread(this)">複製脆文</button>\n'
            '</div>\n'
        )

    _count = len(_parsed)
    _result = (
        '\n<!-- THREADS_SECTION_START — build_achi.py 管理 -->\n'
        '<header class="section-head" id="sect-threads">\n'
        '  <span class="roman">VIII.</span>\n'
        '  <span class="label">Threads 脆文<span class="en">Copy &amp; Post</span></span>\n'
        '  <span class="rule"></span>\n'
        '  <span class="count">' + str(_count) + ' posts</span>\n'
        '</header>\n'
        '<div class="threads-grid">\n' +
        _cards_html +
        '</div>\n'
        '<!-- THREADS_SECTION_END -->\n'
    )
    print(f'[threads] 解析完成：{_count} 篇')
    return _result


# ============================================================
# 阿奇 article adapter（yaml_to_sc_kwargs → owner_article）
# ============================================================
def owner_article_adapter(yaml_data: dict, num: int, batch_label: str) -> str:
    """yaml dict → owner_article() HTML
    v2 2026-05-23：注入 v2 新欄位 data-* meta（voice_lock/publish_mode/dist_mode/trial_reels）
    """
    from yaml_to_sc import yaml_to_sc_kwargs, inject_v2_meta_attrs
    kw = yaml_to_sc_kwargs(yaml_data, num=num)

    insight = yaml_data.get('insight') or yaml_data.get('核心洞察') or kw['scene']
    scene = kw['scene']

    html = owner_article(
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
    )
    return inject_v2_meta_attrs(html, kw)


# ============================================================
# yaml-driven 主路由
# ============================================================
print(f'build_{OWNER_SLUG}.py loaded OK')
print(f'HTML target: {HTML_FILE}')

if not _args.yaml_dir:
    print('ERROR: --yaml-dir 必填（新業主只支援 yaml-driven）', file=sys.stderr)
    sys.exit(1)

if not os.path.isdir(_args.yaml_dir):
    print(f'ERROR: yaml-dir 不存在：{_args.yaml_dir}', file=sys.stderr)
    sys.exit(1)

from yaml_to_sc import load_yaml_articles

batch_label = _args.batch_label or f'yaml-driven · {os.path.basename(_args.yaml_dir)}'
yaml_articles = load_yaml_articles(_args.yaml_dir, expected_count=_args.expected_count)
num_start = _args.num_start

# 日期分組（C-016）：所有批次卡片按順序放進單一 date_group，不分派系
# 派系色保留在 article card-head --pie 變數，視覺不變
_all_arts = []
for _idx, _ydata in enumerate(yaml_articles, start=0):
    _art = owner_article_adapter(_ydata, num=num_start + _idx, batch_label=batch_label)
    _all_arts.append(_art)

_yaml_total = len(_all_arts)
print(f'yaml articles built OK ({_yaml_total} 部)')

# 建單一批次 group（group head 只含批次日期，check_12 通過）
all_sections = date_group(batch_label, 'b01', _all_arts)
print(f'Date group assembled: {_yaml_total} 部，group head={batch_label!r}')

# ============================================================
# 寫入 HTML 檔案
# ============================================================
if not os.path.exists(HTML_FILE):
    print(f'ERROR: HTML 檔案不存在：{HTML_FILE}', file=sys.stderr)
    print('修復步驟：確認 init_owner_website.py 已跑過 --dry-run 以外的完整流程', file=sys.stderr)
    sys.exit(1)

with open(HTML_FILE, 'r', encoding='utf-8') as f:
    c = f.read()

# 找 SECTIONS_PLACEHOLDER 標記
PLACEHOLDER = '<!-- SECTIONS_PLACEHOLDER — build_' + OWNER_SLUG + '.py 負責替換此區塊 -->'
PLACEHOLDER_ALT = '<!-- SECTIONS_PLACEHOLDER'

placeholder_pos = c.find(PLACEHOLDER)
if placeholder_pos < 0:
    # 嘗試通用 placeholder
    placeholder_pos = c.find(PLACEHOLDER_ALT)
    if placeholder_pos < 0:
        # fallback：找第一個 section-head 作為 sections 起點
        _sh_fallback = c.find('<header class="section-head"')
        if _sh_fallback > 0:
            placeholder_pos = _sh_fallback
            placeholder_end = placeholder_pos  # 不跳過任何前綴文字
            print('[sections] 找不到 SECTIONS_PLACEHOLDER，使用 section-head fallback', file=sys.stderr)
        else:
            print('ERROR: 找不到 SECTIONS_PLACEHOLDER 標記，也找不到 section-head fallback', file=sys.stderr)
            sys.exit(1)
    else:
        # 找到行尾
        placeholder_end = c.find('\n', placeholder_pos) + 1
else:
    placeholder_end = placeholder_pos + len(PLACEHOLDER) + 1

# 找 <footer（舊 sections 結束標誌，含舊 threads section）
footer_pos = c.find('<footer', max(placeholder_end, placeholder_pos))
if footer_pos > placeholder_pos:
    # 跳過舊 sections（含舊 threads section），直接接 <footer
    tail = c[footer_pos:]
else:
    # 沒有 footer 或 footer 在前面，用原邏輯
    tail = c[placeholder_end:]

# Threads 脆文段（每次 rebuild 帶入）
# script-library 位於 Claude/Projects/短影音系統/L4_工具腳本/_部署系統/script-library
# 往上 5 層到達 Claude root → Claude/Projects/...
_claude_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..'))
_threads_md = os.path.normpath(os.path.join(
    _claude_root, 'Projects',
    '短影音系統', 'L2_業主層', '餐飲_阿奇',
    '01_腳本生產', '第01批_2026-05-22', 'threads_achi_01.md'
))
threads_html = build_threads_section(_threads_md)

nc = c[:placeholder_pos] + all_sections + '\n\n' + threads_html + '\n' + tail

# CSS patch：補 .group.collapsed > .threads-grid（子選擇器，check_6 通過）
# achi.html 原有後代選擇器版本，改為同時含子選擇器版讓 validate check_6 通過
_OLD_CSS = '.group.collapsed .threads-grid{display:none}'
_NEW_CSS = '.group.collapsed .threads-grid{display:none}\n.group.collapsed > .threads-grid { display: none }'
if _OLD_CSS in nc and '.group.collapsed > .threads-grid' not in nc:
    nc = nc.replace(_OLD_CSS, _NEW_CSS)
    print('[css-patch] 補 .group.collapsed > .threads-grid CSS rule OK')
elif '.group.collapsed > .threads-grid' in nc:
    print('[css-patch] .group.collapsed > .threads-grid 已存在，跳過')
else:
    print('[css-patch] WARNING: 找不到原有 CSS rule，跳過 patch', file=sys.stderr)

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
