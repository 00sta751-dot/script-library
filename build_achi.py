"""
build_achi.py — 阿奇 腳本庫 build script
由 init_owner_website.py 從模板生成

對齊：
  - SOP_腳本上線_統一版_v2.md §5.2 新業主 build script 必含 9 件
  - yaml-driven（§6.5）：所有批次讀 yaml → 翻譯機 → 渲染

用法（單批）：
  python build_achi.py --mode yaml --yaml-dir <yaml資料夾路徑> --batch-label "第 01 批 · 2026-XX-XX" --threads-md <脆文.md>
用法（多批累積）：
  python build_achi.py --mode yaml --yaml-dir "<dir1>,<dir2>" --batch-label "第 01 批 · 2026-XX-XX,第 02 批 · 2026-YY-YY" --threads-md "<md2>"

更新日誌：
  2026-05-22：yaml_to_sc.py sub_desc 改從 '畫面' 欄位取值，修 .sub 字幕渲染（75 個）
  2026-05-22：加 Threads 脆文段（build_threads_section），每次 rebuild 自動帶入 7 篇
  2026-06-16：累積式 multi-batch + 防下架鎖（對齊 build_index.py）
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
_parser.add_argument('--threads-md', dest='threads_md', default='',
                     help='脆文 .md 檔案絕對路徑（必填；歷史重建第01批用 --allow-legacy-threads — 2026-06-11）')
_parser.add_argument('--allow-legacy-threads', dest='allow_legacy_threads', action='store_true',
                     help='顯式允許使用第01批硬編脆文路徑（歷史重建專用）')
_parser.add_argument('--allow-drop-batches', dest='allow_drop_batches', action='store_true',
                     help='⚠危險：允許讓舊批次從首頁消失（需澤君明確授權）')
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

from yaml_to_sc import load_yaml_articles
import re

# 解析多 dir / 多 label（逗號分隔；單 dir 向後相容）
_yaml_dirs = [d.strip() for d in _args.yaml_dir.split(',') if d.strip()]
_batch_labels_raw = [lb.strip() for lb in _args.batch_label.split(',') if lb.strip()]

for _d in _yaml_dirs:
    if not os.path.isdir(_d):
        print(f'ERROR: yaml-dir 不存在：{_d}', file=sys.stderr)
        sys.exit(1)

# ---- 防下架鎖：label 數不得超過 dir 數 ----
if len(_batch_labels_raw) > len(_yaml_dirs):
    print(f'ERROR: --batch-label 數量（{len(_batch_labels_raw)}）> --yaml-dir 數量（{len(_yaml_dirs)}），多餘的 label 無法映射到真實 dir，拒絕繼續')
    print(f'  labels: {_batch_labels_raw}')
    print(f'  dirs:   {_yaml_dirs}')
    sys.exit(2)

_num_cursor = _args.num_start
_single_expected = _args.expected_count if len(_yaml_dirs) == 1 else None

# _yaml_batches: list of (batch_label, flat_arts_list)，順序舊→新
_yaml_batches = []
for _dir_i, _yaml_dir_path in enumerate(_yaml_dirs):
    _this_batch_label = (
        _batch_labels_raw[_dir_i]
        if _dir_i < len(_batch_labels_raw)
        else f'yaml-driven · {os.path.basename(_yaml_dir_path)}'
    )
    _this_expected = _single_expected if _dir_i == 0 else None
    print(f'\n  載入 batch {_dir_i+1}/{len(_yaml_dirs)}: {os.path.basename(_yaml_dir_path)} [{_this_batch_label}]')
    _this_yaml_articles = load_yaml_articles(_yaml_dir_path, expected_count=_this_expected)
    _this_flat = []
    for _idx, _ydata in enumerate(_this_yaml_articles, start=0):
        _art = owner_article_adapter(_ydata, num=_num_cursor + _idx, batch_label=_this_batch_label)
        _this_flat.append(_art)
    _num_cursor += len(_this_yaml_articles)
    _yaml_batches.append((_this_batch_label, _this_flat))
    print(f'    {len(_this_yaml_articles)} 部 → num_start={_num_cursor - len(_this_yaml_articles)}')

_yaml_total = sum(len(arts) for _, arts in _yaml_batches)
print(f'\nyaml articles total OK ({_yaml_total} 部 across {len(_yaml_batches)} 批次)')

# 每批產一個「★ 批次 section」（最新批最上，id="sect-new-N"）
_yaml_batch_sections = []
for _b_i, (_b_label, _b_arts) in enumerate(reversed(_yaml_batches)):
    _grp_id = f'new-{len(_yaml_batches) - _b_i}'
    _b_sect = (
        '<header class="section-head" id="sect-' + _grp_id + '">\n'
        '  <span class="roman">★</span>\n'
        '  <span class="label">' + _b_label + ' 更新<span class="en">批次腳本</span></span>\n'
        '  <span class="rule"></span>\n'
        '  <span class="count">' + str(len(_b_arts)) + ' scripts</span>\n'
        '</header>\n'
        '<div class="cards">\n' +
        '\n'.join(_b_arts) + '\n'
        '</div>'
    )
    _yaml_batch_sections.append(_b_sect)
    print(f'  yaml section 組裝: {_b_label} ({len(_b_arts)} 部)')

# 本次用最新批脆文（_yaml_batches 最後一個）
_latest_batch_label = _yaml_batches[-1][0] if _yaml_batches else ''
print(f'\nyaml-driven all_sections assembled: {len(_yaml_batches)} yaml批 sections')

# ============================================================
# 寫入 HTML 檔案
# ============================================================
if not os.path.exists(HTML_FILE):
    print(f'ERROR: HTML 檔案不存在：{HTML_FILE}', file=sys.stderr)
    print('修復步驟：確認 init_owner_website.py 已跑過 --dry-run 以外的完整流程', file=sys.stderr)
    sys.exit(1)

with open(HTML_FILE, 'r', encoding='utf-8') as f:
    c = f.read()

# ---- 找 stats section 結束位置（所有 articles/sections 的起點）----
# 策略：找 <section class="stats"> 的結束 </section> → 到 <footer 之間整段替換
# 這樣不管舊 html 裡有多少 group/section/article 殘留都能完整清掉（修重複 bug 2026-06-16）
_stats_section_end = c.find('</section>', c.find('<section class="stats"'))
if _stats_section_end < 0:
    print('ERROR: 找不到 <section class="stats"> 結尾 </section>，無法定位 sections 插入點', file=sys.stderr)
    sys.exit(1)
_insert_start = _stats_section_end + len('</section>')
print(f'[sections] insert_start at char {_insert_start}（stats section 結尾後）')

# 找 <footer（所有 sections 的結束邊界）
footer_pos = c.find('<footer', _insert_start)
if footer_pos < _insert_start:
    print('ERROR: 找不到 <footer，無法確定 sections 結束邊界', file=sys.stderr)
    sys.exit(1)
tail = c[footer_pos:]
print(f'[sections] footer_pos at char {footer_pos}，tail 從此截斷')

# Threads 脆文段（每次 rebuild 帶入最新批脆文）
# script-library 位於 Claude/Projects/短影音系統/L4_工具腳本/_部署系統/script-library
# 往上 5 層到達 Claude root → Claude/Projects/...
_claude_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..'))

# --threads-md 支援逗號分隔（多批），取最後一個（最新批）
if _args.threads_md:
    _threads_md_list_raw = [t.strip() for t in _args.threads_md.split(',') if t.strip()]
    _threads_md = os.path.normpath(_threads_md_list_raw[-1])  # 只用最新批脆文
    if len(_threads_md_list_raw) > 1:
        print(f'NOTE: 共 {len(_threads_md_list_raw)} 批脆文 md，只渲染最新批（check 16 限制）')
elif _args.allow_legacy_threads:
    _threads_md = os.path.normpath(os.path.join(
        _claude_root, 'Projects',
        '短影音系統', 'L2_業主層', '餐飲_阿奇',
        '01_腳本生產', '第01批_2026-05-22', 'threads_achi_01.md'
    ))
    print('WARNING: --allow-legacy-threads 顯式啟用，脆文使用第01批硬編路徑')
else:
    print('ERROR: 必須帶 --threads-md <本批脆文.md>（或顯式 --allow-legacy-threads 重建第01批）— 2026-06-11 GPT 終驗：默默 fallback 舊批脆文＝footgun，已禁')
    sys.exit(2)
threads_html = build_threads_section(_threads_md)

# 組裝 all_sections：yaml 批次 sections（最新→最舊）+ threads
all_sections_html = '\n\n'.join(_yaml_batch_sections) + '\n\n' + threads_html

# 整段替換：stats section 結尾 → footer 之間，換成乾淨的新 sections（修重複 bug）
nc = c[:_insert_start] + '\n\n' + all_sections_html + '\n' + tail

# CSS patch：補 .group.collapsed > .threads-grid（子選擇器，check_6 通過）
# achi.html 原有後代選擇器版本，改為同時含子選擇器版讓 validate check_6 通過
_OLD_CSS = '.group.collapsed .threads-grid{display:none}'
_NEW_CSS = '.group.collapsed .threads-grid{display:none}\n.group.collapsed > .threads-grid { display: none }'
if _OLD_CSS in nc and '.group.collapsed > .threads-grid' not in nc:
    nc = nc.replace(_OLD_CSS, _NEW_CSS)
    print('[css-patch] 補 .group.collapsed > .threads-grid CSS rule OK')
elif '.group.collapsed > .threads-grid' in nc:
    print('[css-patch] .group.collapsed > .threads-grid 已存在，不重複加')
else:
    print('[css-patch] WARNING: 找不到原有 CSS rule，無法 patch', file=sys.stderr)

# ---- Dynamic stats patch ----
_total_scripts = len(re.findall(r'<article\b', nc))
_sections_count = len(_yaml_batches)  # yaml-driven：每批一個 section

# 取最新批 label 作為日期來源
_batch_source = _batch_labels_raw[-1] if _batch_labels_raw else ''
_batch_date_m = re.search(r'(\d{4})-(\d{2})-(\d{2})', _batch_source)
if _batch_date_m:
    _date_str = f'{_batch_date_m.group(1)}・{_batch_date_m.group(2)}・{_batch_date_m.group(3)}'
else:
    _date_str = None

nc = re.sub(r'共 <b>\d+</b> 部', f'共 <b>{_total_scripts}</b> 部', nc)
nc = re.sub(
    r'<span>\d+ 主題</span>',
    f'<span>{_sections_count} 批次</span>',
    nc
)
nc = re.sub(
    r'(<div class="stat"><div class="n">)\d+(</div><div class="l">Total scripts</div></div>)',
    rf'\g<1>{_total_scripts}\g<2>',
    nc
)
# 替換 Sections/Batches stats 方塊（idempotent）
nc = re.sub(
    r'(<div class="stat"><div class="n">)\d+(</div><div class="l">)Sections(</div></div>)',
    rf'\g<1>{_sections_count}\g<2>批次\g<3>',
    nc
)
nc = re.sub(
    r'(<div class="stat"><div class="n">)\d+(</div><div class="l">批次</div></div>)',
    rf'\g<1>{_sections_count}\g<2>',
    nc
)
if _date_str:
    nc = re.sub(r'\d{4}・\d{2}・\d{2} 更新', f'{_date_str} 更新', nc)
print(f'Stats patch: total={_total_scripts}, sections={_sections_count}, date={_date_str}')

# ---- Fail-closed 防下架鎖（yaml 模式）----
# 從舊 html（c）抓已上線的批次號（sect-new / sect-new-N header）
_existing_batch_labels = set()
for _hdr in re.findall(
    r'<header class="section-head" id="sect-new(?:-\d+)?">.*?</header>', c, re.DOTALL
):
    _hm = re.search(r'第\s*(\d+)\s*批', _hdr)
    if _hm:
        _existing_batch_labels.add(_hm.group(1))

# 本次 build 要寫入的批次（從實際渲染的 _yaml_batches 取）
_new_batch_nums = set()
for _actual_label, _ in _yaml_batches:
    _m = re.search(r'第\s*(\d+)\s*批', _actual_label)
    if _m:
        _new_batch_nums.add(_m.group(1))

_dropped = _existing_batch_labels - _new_batch_nums
if _dropped and not getattr(_args, 'allow_drop_batches', False):
    _dropped_names = ', '.join(f'第{n}批' for n in sorted(_dropped, key=lambda x: int(x)))
    print(f'ERROR: 防下架鎖觸發！本次 build 會讓以下批次從首頁消失：{_dropped_names}')
    print(f'  現有批次（achi.html）: {sorted(_existing_batch_labels, key=lambda x: int(x))}')
    print(f'  本次 build 批次：{sorted(_new_batch_nums, key=lambda x: int(x))}')
    print('  若確實要清空舊批，請加 --allow-drop-batches（危險，需澤君明確授權）')
    sys.exit(2)
elif _dropped and getattr(_args, 'allow_drop_batches', False):
    _dropped_names = ', '.join(f'第{n}批' for n in sorted(_dropped, key=lambda x: int(x)))
    print(f'WARNING: --allow-drop-batches 已開啟，以下批次將從首頁移除：{_dropped_names}')
elif not _existing_batch_labels:
    print('防下架鎖：achi.html 無現有批次（首次建立），不需要檢查')
else:
    print(f'防下架鎖 PASS：現有批次 {sorted(_existing_batch_labels, key=lambda x: int(x))} 均在本次批次 {sorted(_new_batch_nums, key=lambda x: int(x))} 中')

with open(HTML_FILE, 'w', encoding='utf-8') as f:
    f.write(nc)

print(f'HTML 已更新：{HTML_FILE}')
print(f'Total articles: {_total_scripts}')

# ---- Assertions ----
arts = re.findall(r'<article\b', nc)
print('Total articles (re-verify):', len(arts))
_yaml_total_verify = sum(len(arts_b) for _, arts_b in _yaml_batches)
assert len(arts) >= _yaml_total_verify, f'Expected >= {_yaml_total_verify} articles (yaml batches total), got {len(arts)}'
print(f'yaml mode articles assertion OK: {len(arts)} >= {_yaml_total_verify}')

thread_cards = re.findall(r'class="thread-card"', nc)
print(f'Thread cards: {len(thread_cards)}')
assert len(thread_cards) >= 1, f'Expected thread cards, got {len(thread_cards)}'
print('Thread cards assertion OK')

# Threads-label 一致性 assertion：確保渲染的是最新批脆文
_threads_hdr_m = re.search(
    r'<header class="section-head" id="sect-threads">.*?</header>', nc, re.DOTALL
)
if _threads_hdr_m and _yaml_batches:
    _expected_threads_label = _yaml_batches[-1][0]  # 最新批 label（_yaml_batches 按舊→新排列）
    _rendered_threads_label_m = re.search(r'第\s*(\d+)\s*批', _threads_hdr_m.group(0))
    _expected_label_m = re.search(r'第\s*(\d+)\s*批', _expected_threads_label)
    if _rendered_threads_label_m and _expected_label_m:
        _rendered_n = _rendered_threads_label_m.group(1)
        _expected_n = _expected_label_m.group(1)
        assert _rendered_n == _expected_n, (
            f'Threads label 不一致！渲染了第{_rendered_n}批脆文，但最新批應為第{_expected_n}批。'
            f' 請確認 --threads-md 指向最新批脆文 md。'
        )
        print(f'Threads label assertion OK: 第{_rendered_n}批')
    else:
        print('Threads label: 無第N批格式，略過批號比對')

print()
print('next step:')
print(f'  1. python validate_deploy.py（驗 SOP §2 9 件）')
print(f'  2. git add {OWNER_SLUG}.html build_{OWNER_SLUG}.py')
print(f'  3. git commit + push')
print(f'  4. Playwright drive 線上自驗 9 件（SOP §8）')
