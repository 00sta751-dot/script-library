"""
build_achi.py — 阿奇 腳本庫 build script
由 init_owner_website.py 從模板生成

對齊：
  - SOP_腳本上線_統一版_v2.md §5.2 新業主 build script 必含 9 件
  - yaml-driven（§6.5）：所有批次讀 yaml → 翻譯機 → 渲染

用法：
  python build_achi.py --mode yaml --yaml-dir <yaml資料夾路徑> --batch-label "第 01 批 · 2026-XX-XX"
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
        '<article class="card" data-cat="' + esc_attr(pie) + '" id="' + pid + '"' + cap_attr + hashtag_attr + '>\n'
        '  <div class="card-head" style="--pie:' + color + '">\n'
        '    <div class="card-meta">\n'
        '      <button class="shot-toggle" type="button" aria-label="切換已拍過">已拍過</button>\n'
        '      <span class="pie">' + pie_e + '</span>\n'
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
# 阿奇 article adapter（yaml_to_sc_kwargs → owner_article）
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

# 依派系分流
_yaml_by_pie = {}
for _idx, _ydata in enumerate(yaml_articles, start=0):
    _pie = _ydata.get('派系', '未分類')
    _art = owner_article_adapter(_ydata, num=num_start + _idx, batch_label=batch_label)
    _yaml_by_pie.setdefault(_pie, []).append(_art)

_yaml_total = sum(len(v) for v in _yaml_by_pie.values())
print(f'yaml articles built OK ({_yaml_total} 部):')
for _pie, _arts in sorted(_yaml_by_pie.items()):
    print(f'  {_pie}: {len(_arts)} 部')

# 建 sections（每派系一個 section）
_section_idx = 0
_all_sections_list = []

# 圖卡部獨立收集
_card_arts = []

for _pie, _arts in sorted(_yaml_by_pie.items()):
    if _pie == '圖卡部':
        _card_arts.extend(_arts)
        continue
    _roman_num = ['I.','II.','III.','IV.','V.','VI.','VII.','VIII.','IX.','X.','XI.','XII.']
    _roman = _roman_num[_section_idx] if _section_idx < len(_roman_num) else str(_section_idx + 1) + '.'
    _all_sections_list.append(
        section(_roman, _pie, _pie, _section_idx, _arts, len(_arts))
    )
    _section_idx += 1

# 圖卡部排在一般 section 後
if _card_arts:
    _roman_num = ['I.','II.','III.','IV.','V.','VI.','VII.','VIII.','IX.','X.','XI.','XII.']
    _roman = _roman_num[_section_idx] if _section_idx < len(_roman_num) else str(_section_idx + 1) + '.'
    _all_sections_list.append(
        section(_roman, '圖卡部', 'Card Library', _section_idx, _card_arts, len(_card_arts))
    )
    _section_idx += 1

all_sections = '\n\n'.join(_all_sections_list)
print(f'Sections assembled: {_section_idx} 個')

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
