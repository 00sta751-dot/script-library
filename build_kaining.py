"""
build_kaining.py — 楷甯 腳本庫 build script
由 init_owner_website.py 從模板生成

對齊：
  - SOP_腳本上線_統一版_v2.md §5.2 新業主 build script 必含 9 件
  - yaml-driven（§6.5）：所有批次讀 yaml → 翻譯機 → 渲染

用法：
  python build_kaining.py --mode yaml --yaml-dir <yaml資料夾路徑> --batch-label "第 01 批 · 2026-XX-XX"
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
_parser = argparse.ArgumentParser(description='build_kaining.py — 楷甯腳本庫 build script')
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
OWNER_NAME   = '楷甯'
OWNER_SLUG   = 'kaining'
THEME_COLOR  = '#B07D56'
HTML_FILE    = os.path.join(LIB, 'kaining.html')

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
            tl_html += '<div class="mirror">藏鏡人　' + Q + _esc_text(mirror) + Q + '</div>'
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
            '<img src="' + safe_src + '" class="card-thumb" alt="圖卡預覽" '
            'onclick="openLightbox(this); return false;">'
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
        '<article class="card" data-cat="' + _esc_attr(pie) + '" id="' + _esc_attr(pid) + '"' + cap_attr + hashtag_attr + '>\n'
        '  <div class="card-head" style="--pie:' + _esc_attr(color) + '">\n'
        '    <div class="card-meta">\n'
        '      <button class="shot-toggle" type="button" aria-label="切換已拍過">已拍過</button>\n'
        '      <span class="pie">' + _esc_text(pie) + '</span>\n'
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
# 楷甯 article adapter（yaml_to_sc_kwargs → owner_article）
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

# C-016 日期分組（v2.4 — SOP §2.2 / §5.1A）
# 每批一個 section，group head = 批次日期，禁止用派系名當 group head
_all_arts = []
_card_arts = []
for _idx, _ydata in enumerate(yaml_articles, start=0):
    _art = owner_article_adapter(_ydata, num=num_start + _idx, batch_label=batch_label)
    _pie = _ydata.get('派系', '')
    if _pie == '圖卡部' or _ydata.get('img'):
        _card_arts.append(_art)
    else:
        _all_arts.append(_art)

_yaml_total = len(_all_arts) + len(_card_arts)
print(f'yaml articles built OK ({_yaml_total} 部，圖卡部 {len(_card_arts)} 部)')

# 建 sections（日期分組：本批一個 section，最新批在最上）
_all_sections_list = []

# 本批 articles section（group head = batch_label，格式：「第 NN 批 · YYYY-MM-DD」）
if _all_arts:
    _all_sections_list.append(
        section('', batch_label, batch_label, 'b_new', _all_arts, len(_all_arts))
    )
    print(f'  本批 section: {batch_label} ({len(_all_arts)} 部)')

# 圖卡部排在一般 section 後（白名單，允許）
if _card_arts:
    _all_sections_list.append(
        section('', '圖卡部', 'Card Library', 'card', _card_arts, len(_card_arts))
    )
    print(f'  圖卡部 section: {len(_card_arts)} 部')

all_sections = '\n\n'.join(_all_sections_list)
print(f'Sections assembled: {len(_all_sections_list)} 個（日期分組，無派系 group head）')

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
        print('ERROR: 找不到 SECTIONS_PLACEHOLDER 標記', file=sys.stderr)
        sys.exit(1)
    # 找到行尾
    placeholder_end = c.find('\n', placeholder_pos) + 1
else:
    placeholder_end = placeholder_pos + len(PLACEHOLDER) + 1

nc = c[:placeholder_pos] + all_sections + '\n\n' + c[placeholder_end:]

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
