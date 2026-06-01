"""
build_shihting.py — 詩婷 腳本庫 build script
由 init_owner_website.py 從模板生成

對齊：
  - SOP_腳本上線_統一版_v2.md §5.2 新業主 build script 必含 9 件
  - yaml-driven（§6.5）：所有批次讀 yaml → 翻譯機 → 渲染

用法：
  python build_shihting.py --mode yaml --yaml-dir <yaml資料夾路徑> --batch-label "第 01 批 · 2026-XX-XX"
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
_parser = argparse.ArgumentParser(description='build_shihting.py — 詩婷腳本庫 build script')
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
_parser.add_argument('--threads-md', dest='threads_md', default='',
                     help='脆文 .md 檔案絕對路徑（若提供則渲染脆文 Threads 區塊）')
_args, _unknown = _parser.parse_known_args()

# ============================================================
# 業主設定（init_owner_website.py 替換 placeholder）
# ============================================================
OWNER_NAME   = '詩婷'
OWNER_SLUG   = 'shihting'
THEME_COLOR  = '#D98E5A'
HTML_FILE    = os.path.join(LIB, 'shihting.html')

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
    '故事成長派':  '#C06835',
    '共鳴痛點派':  '#3D8C6F',
    '生活遷移派':  '#5BA88A',
    '純雞湯療癒派': '#D9A05B',
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
            tl_html += ('<div class="shihting-mirror">'
                        '<span class="mirror-chip">🎬 藏鏡人</span>'
                        '<span class="mirror-text">' + _esc_text(mirror) + '</span></div>')
        if sub:
            tl_html += '<div class="sub">' + _esc_text(sub) + '</div>'
        tl_html += '</div>\n'

    # 圖卡 HTML（P1#2 fix：img src 走 _safe_img_src allowlist）
    img_html = ''
    if img:
        safe_src = _safe_img_src(img)
        img_html = (
            '    <div class="ref-link">圖卡部 · 圖卡附件：'
            '<a href="' + safe_src + '" target="_blank">'
            '<img src="' + safe_src + '" class="card-thumb" alt="圖卡預覽">'
            '</a></div>\n'
        )

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
        '<article class="card" data-cat="" id="' + _esc_attr(pid) + '"' + cap_attr + hashtag_attr + '>\n'
        '  <div class="card-head" style="--pie:' + _esc_attr(color) + '">\n'
        '    <div class="card-meta">\n'
        '      <button class="shot-toggle" type="button" aria-label="切換已拍過">已拍過</button>\n'
        '      <span class="num">No. ' + _esc_text(str(num).zfill(2)) + '</span>\n'
        '      <span class="batch">' + _esc_text(batch) + '</span>\n'
        '    </div>\n' +
        (('    <div class="card-meta-extra">\n' + meta_extra + '    </div>\n') if meta_extra else '') +
        '    <h3 class="title">' + _esc_text(title) + '</h3>\n'
        '    <div class="insight">' + _esc_text(insight) + '</div>\n'
        '  </div>\n'
        '  <div class="card-body">\n'
        '    <div class="scene"><b>場景</b>　' + _esc_text(scene) + '</div>\n' +
        img_html +
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
        '<div class="group collapsed" id="grp-' + _esc_attr(str(sect_id)) + '">\n'
        '<header class="section-head" id="sect-' + _esc_attr(str(sect_id)) + '" onclick="toggleGroup(this.parentElement)">\n'
        '  <span class="roman">' + _esc_text(roman) + '</span>\n'
        '  <span class="label">' + _esc_text(label) + '<span class="en">' + _esc_text(en) + '</span></span>\n'
        '  <span class="rule"></span>\n'
        '  <span class="count">' + _esc_text(str(count)) + ' scripts</span>\n'
        '</header>\n'
        '<div class="cards">\n' +
        '\n'.join(cards) + '\n'
        '</div>\n'
        '</div>'
    )


# ============================================================
# 詩婷 article adapter（yaml_to_sc_kwargs → owner_article）
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
    )


# ============================================================
# 脆文 Threads 渲染（詩婷專屬 — 對齊 build_beauty.py parse_threads_md）
# ============================================================

def parse_threads_md(md_path: str):
    """解析脆文 .md 檔，回傳 list of (tid, label, body, hashtag)。
    支援格式：## Threads NN + 主題：X × Y + body + # hashtag
    """
    import re as _re3
    with open(md_path, 'r', encoding='utf-8') as _f:
        raw = _f.read()
    blocks = _re3.split(r'\n---\n', raw.strip())
    results = []
    for blk in blocks:
        blk = blk.strip()
        m_head = _re3.search(r'##\s+Threads\s+(\d+)', blk)
        if not m_head:
            continue
        tid = f'T{int(m_head.group(1)):02d}'
        m_theme = _re3.search(r'主題：(.+)', blk)
        if m_theme:
            theme_raw = m_theme.group(1).strip()
            label = theme_raw.split('×')[0].strip()
        else:
            label = '觀點型'
        lines = blk.splitlines()
        body_lines = []
        hashtag = ''
        in_frontmatter = False
        for ln in lines:
            if ln.strip() == '---':
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue
            if _re3.match(r'##\s+Threads\s+\d+', ln):
                continue
            if _re3.match(r'主題：', ln):
                continue
            if ln.strip().startswith('#') and not ln.strip().startswith('##'):
                hashtag = ln.strip()
                continue
            if ln.strip().startswith('>'):
                continue
            if _re3.match(r'^#\s+Threads', ln):
                continue
            body_lines.append(ln)
        body = '\n'.join(body_lines).strip()
        if body or hashtag:
            results.append((tid, label, body, hashtag))
    return results


def thread_card_shihting(tid: str, label: str, body: str, hashtag: str) -> str:
    """渲染單篇脆文為 .thread-card HTML（詩婷療癒色系）"""
    safe_body = body.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    safe_label = label.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    safe_tid   = tid.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    safe_hash  = hashtag.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return (
        '<div class="thread-card">\n'
        '<div class="thread-meta">'
        '<span class="thread-id">' + safe_tid + '</span>'
        '<span class="thread-label">' + safe_label + '</span>'
        '</div>\n'
        '<div class="thread-text">' + safe_body + '</div>\n' +
        ('<div class="thread-hash">' + safe_hash + '</div>\n' if safe_hash else '') +
        '<button class="copy-thread">複製脆文</button>\n'
        '</div>'
    )


def sect_threads_shihting(threads_data: list, batch_label: str) -> str:
    """渲染脆文區塊（.threads-section + .threads-grid，預設 collapsed）"""
    count = len(threads_data)
    grid_html = '\n'.join(
        thread_card_shihting(t[0], t[1], t[2], t[3]) for t in threads_data
    )
    return (
        '\n<!-- 脆文 Threads —— build_shihting.py 自動生成 -->\n'
        '<div class="threads-section collapsed">\n'
        '<div class="threads-section-head">\n'
        '  <span>🌿</span>\n'
        '  <span class="ts-label">脆文 Threads</span>\n'
        '  <span class="ts-count">' + _esc_text(batch_label) + '・' + _esc_text(str(count)) + ' 篇</span>\n'
        '  <span class="ts-toggle">▼</span>\n'
        '</div>\n'
        '<div class="threads-grid">\n' +
        grid_html + '\n'
        '</div>\n'
        '</div>'
    )


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

# C-016 / 派系清理：攤平所有 yaml articles 成「單一日期批次」section
# （依日期/批次分類，不分派系、HTML 不輸出任何派系名；--pie 顏色保留在卡片）
_all_arts = []
for _idx, _ydata in enumerate(yaml_articles, start=0):
    _art = owner_article_adapter(_ydata, num=num_start + _idx, batch_label=batch_label)
    _all_arts.append(_art)

_yaml_total = len(_all_arts)
print(f'yaml articles built OK ({_yaml_total} 部，依日期批次單一 section)')

# 單一 section：標題＝批次日期（最新批最上），不分派系（對齊 index/beauty C-016）
_all_sections_list = [
    section('★', batch_label + ' 更新', '最新批次', 'new', _all_arts, _yaml_total)
]
all_sections = '\n\n'.join(_all_sections_list)
print('Sections assembled: 1 個（依日期批次，C-016 不分派系）')

# ============================================================
# 脆文渲染（--threads-md 提供時附加在 sections 後）
# ============================================================
_threads_html = ''
if _args.threads_md:
    if not os.path.isfile(_args.threads_md):
        print(f'WARNING: threads-md 不存在，跳過脆文渲染：{_args.threads_md}', file=sys.stderr)
    else:
        _threads_data = parse_threads_md(_args.threads_md)
        if _threads_data:
            _threads_batch = _args.batch_label or batch_label
            _threads_html = sect_threads_shihting(_threads_data, _threads_batch)
            print(f'脆文 Threads 渲染 OK ({len(_threads_data)} 篇)')
        else:
            print('WARNING: threads-md 解析結果為空，跳過脆文渲染', file=sys.stderr)
else:
    # 自動偵測同 yaml-dir 底下的 threads_shihting_*.md
    _auto_threads = sorted([
        os.path.join(_args.yaml_dir, f)
        for f in os.listdir(_args.yaml_dir)
        if f.startswith('threads_') and f.endswith('.md')
    ])
    if _auto_threads:
        _threads_data = []
        for _tm in _auto_threads:
            _threads_data.extend(parse_threads_md(_tm))
        if _threads_data:
            _threads_batch = _args.batch_label or batch_label
            _threads_html = sect_threads_shihting(_threads_data, _threads_batch)
            print(f'脆文 Threads 自動偵測渲染 OK ({len(_threads_data)} 篇)：{[os.path.basename(t) for t in _auto_threads]}')

# ============================================================
# 寫入 HTML 檔案（冪等 replace — Bug1 fix v2）
# 策略：找到兩個 placeholder 的位置，清掉中間舊內容，插入新內容
# 保留 placeholder 標記本身，讓下次 build 還找得到
# ============================================================
if not os.path.exists(HTML_FILE):
    print(f'ERROR: HTML 檔案不存在：{HTML_FILE}', file=sys.stderr)
    print('修復步驟：確認 init_owner_website.py 已跑過 --dry-run 以外的完整流程', file=sys.stderr)
    sys.exit(1)

with open(HTML_FILE, 'r', encoding='utf-8') as f:
    c = f.read()

SECTIONS_PH = '<!-- SECTIONS_PLACEHOLDER — build_' + OWNER_SLUG + '.py 負責替換此區塊 -->'
THREADS_PH  = '<!-- THREADS_PLACEHOLDER — build_' + OWNER_SLUG + '.py 負責替換此區塊 -->'

def _find_ph_end(content, exact, fallback_prefix):
    """找 placeholder 行的行尾位置（含換行），回傳 (ph_start, ph_line_end)"""
    pos = content.find(exact)
    if pos >= 0:
        line_end = content.find('\n', pos)
        if line_end < 0:
            line_end = len(content)
        return pos, line_end + 1
    pos = content.find(fallback_prefix)
    if pos >= 0:
        line_end = content.find('\n', pos)
        if line_end < 0:
            line_end = len(content)
        return pos, line_end + 1
    return -1, -1

# 找 SECTIONS_PLACEHOLDER 的位置
sec_pos, sec_line_end = _find_ph_end(c, SECTIONS_PH, '<!-- SECTIONS_PLACEHOLDER')
if sec_pos < 0:
    print('ERROR: 找不到 SECTIONS_PLACEHOLDER 標記', file=sys.stderr)
    sys.exit(1)

# 找 THREADS_PLACEHOLDER 的位置（在 SECTIONS 之後）
thr_pos, thr_line_end = _find_ph_end(c, THREADS_PH, '<!-- THREADS_PLACEHOLDER')

if thr_pos >= 0 and thr_pos < sec_pos:
    print('ERROR: THREADS_PLACEHOLDER 出現在 SECTIONS_PLACEHOLDER 之前，模板結構異常', file=sys.stderr)
    sys.exit(1)

# 組裝新的 sections 區塊內容（placeholder 行後到 threads placeholder 前）
# 格式：\n<content>\n\n
sections_block = '\n' + all_sections + '\n\n' if all_sections else '\n'

if thr_pos >= 0:
    # 有 THREADS_PLACEHOLDER：
    # 策略：把 SECTIONS_PH 到 THREADS_PH 之間的舊 sections 清掉，
    #        把 THREADS_PH 之後到 wrap 關閉 </div> 之間的舊 threads 清掉，
    #        各自插入新內容，保留 placeholder 標記供下次 build 再找

    threads_block = '\n' + _threads_html + '\n\n' if _threads_html else '\n'

    # 找 wrap 關閉 </div>：在 THREADS_PH 行尾之後、<footer> 之前最後一個 </div>
    footer_pos = c.find('<footer>')
    if footer_pos < 0:
        print('ERROR: 找不到 <footer> 標記，無法定位 wrap 關閉 </div>', file=sys.stderr)
        sys.exit(1)
    wrap_close_pos = c.rfind('</div>', thr_line_end, footer_pos)
    if wrap_close_pos < 0:
        print('ERROR: 找不到 wrap 關閉 </div>（THREADS_PH 與 <footer> 之間）', file=sys.stderr)
        sys.exit(1)
    # wrap_close_pos 指向 </div> 的起點；取從這裡到結尾（含換行後的 footer/js 等）
    tail = c[wrap_close_pos:]

    # 組裝：[頭到 sec 行尾] + [新 sections] + [THREADS_PH 行] + [新 threads] + [</div>...結尾]
    nc = (
        c[:sec_line_end]               # 保留 SECTIONS_PH 行（含換行）
        + sections_block               # 新 sections 內容
        + THREADS_PH + '\n'            # THREADS_PH 行（固定格式）
        + threads_block                # 新 threads 內容
        + tail                         # </div> wrap 關閉 + footer + js...
    )
else:
    # 沒有 THREADS_PLACEHOLDER：模板結構異常，直接報錯（不 fallback append，避免非冪等疊加）
    print('ERROR: 找不到 THREADS_PLACEHOLDER 標記 → 模板缺脆文區塊，請確認 shihting.html 含 <!-- THREADS_PLACEHOLDER ... -->', file=sys.stderr)
    sys.exit(1)

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
