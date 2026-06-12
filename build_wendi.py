# -*- coding: utf-8 -*-
"""
build_wendi.py — 溫蒂腳本庫 build（便當格原創版型 / yaml-driven）

※ 本檔為 parser + 模板渲染程式；解析的腳本台詞是業主原文（已過編劇/算盤/御史驗證），
  非霸告對使用者的狀態宣稱，遮羞詞規則不適用解析到的台詞內容。

設計：
  - 版型＝便當格 Bento（vs 詩婷置中單欄）；配色草木綠＋珊瑚＋奶油；無襯線
  - 藏鏡人＝機械化：從 yaml 藏鏡人欄位對應到時間軸段（每支需 ≥2）
  - C-016：data-cat=""、0 派系名、無派系篩選列、可收合日期群組
  - yaml-driven（§6.5 SOP）：--mode yaml --yaml-dir 為標準模式

用法：
  python build_wendi.py --mode yaml --yaml-dir "<yaml批次資料夾>" --batch-label "第 02 批 · 2026-06-03"
"""
import re
import os
import html as _h
import sys
import io
import argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
LIB = os.path.dirname(os.path.abspath(__file__))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

_p = argparse.ArgumentParser(description='build_wendi.py — 溫蒂腳本庫 build script（yaml-driven）')
_p.add_argument('--mode', choices=['yaml'], default='yaml',
                help='yaml=yaml-driven（標準模式）')
_p.add_argument('--yaml-dir', dest='yaml_dir', default='',
                help='yaml 批次資料夾絕對路徑（必填）')
_p.add_argument('--batch-label', dest='batch_label', default='',
                help='批次顯示名稱，如「第 02 批 · 2026-06-03」')
_p.add_argument('--expected-count', dest='expected_count', type=int, default=None,
                help='預期 yaml 數量（驗證用）')
_p.add_argument('--out', dest='out', default=os.path.join(LIB, 'wendi.html'))
_args, _ = _p.parse_known_args()

OWNER = '溫蒂'
QVER = 'wendi-qver.png'


def esc(x):
    return _h.escape(str(x or ''), quote=False)


def esc_attr(x):
    return _h.escape(str(x or ''), quote=True)


# ============================================================
# 派系 → 卡片視覺類型（內部 map；HTML 不輸出派系名，符合 C-016）
# ============================================================
PIE_TONE = {
    '故事戲劇派': 't-story',
    '直球派': 't-punch',
    '人間觀察派': 't-life',
    '自嘲反差派': 't-story',
    '家人朋友模擬派': 't-story',
}

PLAT_PILL = [
    ('IG Reels', 'ig', 'IG Reels'), ('IG', 'ig', 'IG Reels'),
    ('TikTok', 'tk', 'TikTok'),
    ('Threads', 'th', 'Threads'),
]


def _norm_time(s):
    """取時間前綴數字串供 match：'3-12s 破題' / '3-12s' / '3–12秒' → '3-12'"""
    s = s.replace('–', '-').replace('秒', 's')
    m = re.match(r'\s*(\d+)\s*-\s*(\d+)', s)
    return f'{m.group(1)}-{m.group(2)}' if m else s.strip()


# ============================================================
# 解析藏鏡人互動點行 → {時間key: 台詞}
#  格式：①3-12s【疑問型】「台詞」②25-40s【共鳴型】「台詞」③52-60s【呼籲型】「台詞」
# ============================================================
_MIRROR_ITEM = re.compile(r'[①②③④⑤]\s*([\d\-–]+س?s?)\s*【([^】]*)】\s*「([^」]+)」')


def parse_mirrors(line):
    out = {}
    for m in re.finditer(r'[①②③④⑤]\s*([\d\s\-–]+[s秒]?)\s*【([^】]*)】\s*「([^」]+)」', line):
        tkey = _norm_time(m.group(1))
        out[tkey] = m.group(3).strip()
    return out


# ============================================================
# yaml-driven adapter（yaml dict → render_card 的 script dict）
# ============================================================
def _norm_time_yaml(ts_str):
    """yaml timestamp "0-3s" → key "0-3"（供 mirror 對應）"""
    ts_str = str(ts_str).replace('–', '-').replace('秒', 's')
    m = re.match(r'\s*(\d+)\s*-\s*(\d+)', ts_str)
    return f'{m.group(1)}-{m.group(2)}' if m else ts_str.strip()


def wendi_yaml_adapter(yaml_data: dict, num: int) -> dict:
    """yaml dict → render_card 需要的 script dict。

    讀取 yaml 結構：
      title / 派系 / main_platform / suggested_po_time /
      scenes[]（timestamp/type/台詞_溫蒂/翠文/畫面）/
      藏鏡人（位置1/句子1/位置2/句子2）/
      caption / hashtag[] /
      is_fishing（True→force='釣魚部'）
    """
    title = str(yaml_data.get('title', '') or '')

    # 派系 → PIE_TONE 內部 map（C-016 不輸出派系名）
    pie = str(yaml_data.get('派系', '') or '')

    # 平台
    plat = str(yaml_data.get('main_platform', '') or 'IG Reels')

    # 建議 PO 時間
    po = str(yaml_data.get('suggested_po_time', '') or '')

    # force（釣魚部）
    force = ''
    if yaml_data.get('is_fishing') or str(yaml_data.get('required_slot', '') or '').strip() == '釣魚部':
        force = '釣魚部'

    # 藏鏡人 map：從頂層 藏鏡人 dict 建 {時間key: 台詞}，
    # 以及從 scenes 內的 藏鏡人 欄位補充
    mirrors = {}
    top_mirror = yaml_data.get('藏鏡人') or {}
    if isinstance(top_mirror, dict):
        for pos_key in ('位置1', '位置2', '位置3'):
            sent_key = pos_key.replace('位置', '句子')
            pos_val = str(top_mirror.get(pos_key, '') or '')
            sent_val = str(top_mirror.get(sent_key, '') or '')
            if pos_val and sent_val:
                # 位置格式如 "Hook後 0-3s（懸念型）" 或 "轉折段後 25-40s（共鳴型）"
                tkey = _norm_time_yaml(pos_val)
                mirrors[tkey] = sent_val.strip('「」')

    # 時間軸（從 scenes 讀）
    scenes_data = yaml_data.get('scenes') or []
    timeline = []
    for sc in scenes_data:
        ts_raw = str(sc.get('timestamp', '') or '')
        sc_type = str(sc.get('type', '') or '')
        seg = ts_raw.rstrip('s') + ('s' if ts_raw.endswith('s') else '')
        # seg 格式 "0-3s" + type "Hook" → "0-3s Hook"
        seg_label = (seg + ' ' + sc_type).strip() if sc_type else seg

        line = str(sc.get('台詞_溫蒂', '') or '')
        timeline.append((seg_label, line))

        # scenes 內的 藏鏡人 欄位也補入 mirrors（覆蓋頂層，以場景位置為準）
        sc_mirror = str(sc.get('藏鏡人', '') or '').strip()
        if sc_mirror:
            tkey = _norm_time_yaml(ts_raw)
            mirrors[tkey] = sc_mirror.strip('「」')

    # 場景（從第一個 scene 的畫面或整體取）
    scene = ''
    if scenes_data:
        scene = str(scenes_data[0].get('畫面', '') or '')

    # insight（yaml 通常無獨立 insight，用 hook 台詞替代）
    insight = ''
    if scenes_data:
        insight = str(scenes_data[0].get('台詞_溫蒂', '') or '')

    # CTA 關鍵字（從 CTA 段台詞抓「留言 X」）
    cta_kw = ''
    for sc in scenes_data:
        if str(sc.get('type', '') or '').upper() == 'CTA':
            cta_line = str(sc.get('台詞_溫蒂', '') or '')
            km = re.search(r'留言[「『]([^」』]+)[」』]', cta_line)
            if km:
                cta_kw = km.group(1).strip()
            break

    # caption（直接讀頂層 caption）
    caption = str(yaml_data.get('caption', '') or '')

    # hashtag（list → 空格串）
    hashtag_raw = yaml_data.get('hashtag') or []
    if isinstance(hashtag_raw, list):
        hashtags = ' '.join(str(t) for t in hashtag_raw if t)
    else:
        hashtags = str(hashtag_raw)

    return dict(
        no=str(num).zfill(2),
        title=title,
        force=force,
        pie=pie,
        plat=plat,
        po=po,
        timeline=timeline,
        subtitle='',   # yaml 無獨立 subtitle，翠文在 timeline 內（不顯示於 minfo）
        bgm='',
        compliance='',
        mirrors=mirrors,
        cta_kw=cta_kw,
        caption=caption,
        hashtags=hashtags,
        insight=insight,
        scene=scene,
    )


# ============================================================
# 解析單部腳本（舊 .md 模式保留函式，但主路由已切到 yaml）
# ============================================================
def parse_scripts(md):
    # 以 "## NN — 標題" 切（13 部在「## 13 部標題／派系一覽」表格之後）
    # 先砍掉開頭的總覽表 + 脆文段
    body = md
    # 脆文段之後不要
    thr_split = re.split(r'\n##\s*7\s*篇\s*Threads', body)
    body = thr_split[0]

    parts = re.split(r'\n##\s+(\d{2})\s*[—\-–]\s*(.+)', body)
    # parts: [前言, no, title, content, no, title, content, ...]
    scripts = []
    for i in range(1, len(parts), 3):
        no = parts[i].strip()
        title = parts[i + 1].strip()
        content = parts[i + 2]
        # 標題可能含【釣魚部】等強制位標記 → 拆出
        force = ''
        fm = re.search(r'【([^】]+)】', title)
        if fm:
            force = fm.group(1).strip()
            title = re.sub(r'【[^】]+】', '', title).strip()

        pie = ''
        mp = re.search(r'派系：\s*([^|｜\n]+)', content)
        if mp:
            pie = mp.group(1).strip()
        plat = ''
        mpl = re.search(r'主推平台：\s*([^|｜\n]+)', content)
        if mpl:
            plat = mpl.group(1).strip()
        po = ''
        mpo = re.search(r'建議PO：\s*([^\n]+)', content)
        if mpo:
            po = mpo.group(1).strip()

        # 時間軸表格 rows： | 0-3s Hook | 台詞 |
        timeline = []
        for rm in re.finditer(r'^\|\s*([0-9][^|]*?)\s*\|\s*(.+?)\s*\|\s*$', content, re.MULTILINE):
            seg = rm.group(1).strip()
            line = rm.group(2).strip()
            if seg in ('時間軸', '--------', ':---') or set(seg) <= set('-: '):
                continue
            timeline.append((seg, line))

        subtitle = ''
        ms = re.search(r'字幕卡：\s*([^\n]+)', content)
        if ms:
            subtitle = ms.group(1).strip()
        bgm = ''
        mb = re.search(r'BGM：\s*([^\n]+)', content)
        if mb:
            bgm = mb.group(1).strip()
        compliance = ''
        mc = re.search(r'合規自查：\s*([^\n]+)', content)
        if mc:
            compliance = mc.group(1).strip()

        mirror_line = ''
        mm = re.search(r'藏鏡人互動點：\s*([^\n]+)', content)
        if mm:
            mirror_line = mm.group(1).strip()
        mirrors = parse_mirrors(mirror_line)

        # caption + hashtag（SOP §2.5/§2.6 必填 — 複製文案功能資料源）
        caption = ''
        mcap = re.search(r'^caption：\s*(.+)$', content, re.MULTILINE)
        if mcap:
            caption = mcap.group(1).strip()
        hashtags = ''
        mhash = re.search(r'^hashtag：\s*(.+)$', content, re.MULTILINE)
        if mhash:
            hashtags = mhash.group(1).strip()
        # insight + 場景（SOP §2.5 article 必有元素）
        insight = ''
        mins = re.search(r'^insight：\s*(.+)$', content, re.MULTILINE)
        if mins:
            insight = mins.group(1).strip()
        scene = ''
        msc = re.search(r'^場景：\s*(.+)$', content, re.MULTILINE)
        if msc:
            scene = msc.group(1).strip()

        # CTA 關鍵字（從最後一段台詞抓 留言「X」）
        cta_kw = ''
        for seg, line in timeline:
            km = re.search(r'留言[「『]([^」』]+)[」』]', line)
            if km:
                cta_kw = km.group(1).strip()

        scripts.append(dict(
            no=no, title=title, force=force, pie=pie, plat=plat, po=po,
            timeline=timeline, subtitle=subtitle, bgm=bgm,
            compliance=compliance, mirrors=mirrors, cta_kw=cta_kw,
            caption=caption, hashtags=hashtags, insight=insight, scene=scene))
    return scripts


# ============================================================
# 解析脆文（新格式：## Threads NN（衍生自...）---分隔）
# ============================================================
def parse_threads_new_fmt(md_text: str) -> list:
    """解析脆文 .md（新格式：## Threads NN（衍生自...） + body + # hashtag）
    格式同 build_shihting.py parse_threads_md。
    回傳 list of dict(tid, src, body, hashtags)
    """
    blocks = re.split(r'\n---\n', md_text.strip())
    results = []
    for blk in blocks:
        blk = blk.strip()
        m_head = re.search(r'##\s+Threads\s+(\d+)[（(]([^）)]+)[）)]', blk)
        if not m_head:
            continue
        tid = m_head.group(1).strip()
        # 2026-06-12 零留尾戰役 WP-D：括號內容本身已含「衍生自 」前綴（## Threads 1（衍生自 script_...）），
        # render_thread 模板又補一次 → 線上出現「衍生自 衍生自」。解析端剝前綴，模板端統一補。
        src = re.sub(r'^衍生自\s*', '', m_head.group(2).strip())

        lines = blk.splitlines()
        body_lines = []
        hashtag = ''
        for ln in lines:
            if re.match(r'##\s+Threads\s+\d+', ln):
                continue
            if re.match(r'主題：', ln):
                continue
            if ln.strip().startswith('#') and not ln.strip().startswith('##'):
                hashtag = ln.strip()
                continue
            body_lines.append(ln)
        body = '\n'.join(body_lines).strip()
        if body or hashtag:
            results.append(dict(tid=tid, src=src, body=body, hashtags=hashtag))
    return results


# ============================================================
# 解析脆文（舊 .md 格式，保留備用）
# ============================================================
def parse_threads(md):
    m = re.search(r'##\s*7\s*篇\s*Threads[^\n]*\n(.+)$', md, re.DOTALL)
    if not m:
        return []
    seg = m.group(1)
    out = []
    for bm in re.finditer(r'###\s*脆文\s*(\d+)（衍生自\s*([^）]+)）\s*\n(?:主題：([^\n]+)\n)?(.*?)(?=\n###\s*脆文|\Z)',
                          seg, re.DOTALL):
        tid = bm.group(1).strip()
        src = bm.group(2).strip()
        body = bm.group(4).strip()
        # 分離 hashtag 行
        thash = ''
        hm = re.search(r'^hashtag：\s*(.+)$', body, re.MULTILINE)
        if hm:
            thash = hm.group(1).strip()
            body = re.sub(r'^hashtag：.*$', '', body, flags=re.MULTILINE)
        body = re.sub(r'\n-{3,}\s*$', '', body).strip()
        out.append(dict(tid=tid, src=src, body=body, hashtags=thash))
    return out


# ============================================================
# 渲染便當格卡片
# ============================================================
def render_card(s):
    tone = PIE_TONE.get(s['pie'], 't-story')
    # 平台 pill
    pills = []
    seen = set()
    for key, cls, label in PLAT_PILL:
        if key in s['plat'] and cls not in seen:
            pills.append(f'<span class="pill {cls}">{esc(label)}</span>')
            seen.add(cls)
    if s['po']:
        pills.append(f'<span class="pill time">{esc(s["po"])}</span>')
    if s['force'] and '釣魚部' in s['force']:
        pass  # 6/7 釣魚下架：不外露「釣魚部」內部術語標籤（C-016 對齊）

    # hook = 第一段台詞
    hook = s['timeline'][0][1] if s['timeline'] else ''

    # 時間軸 rows（藏鏡人按時間段對應內嵌）
    rows = ''
    for seg, line in s['timeline']:
        tkey = _norm_time(seg)
        # seg 形如 "0-3s Hook" → 拆時間 + 段名
        sm = re.match(r'\s*([0-9][\d\-–s秒]*)\s*(.*)', seg)
        tnum = sm.group(1).strip() if sm else seg
        tname = sm.group(2).strip() if sm else ''
        ts_html = esc(tnum) + (f'<br>{esc(tname)}' if tname else '')
        mir = ''
        if tkey in s['mirrors']:
            mir = ('<div class="mirror"><span class="mc">🎭 藏鏡人</span>'
                   f'<span class="mt">{esc(s["mirrors"][tkey])}</span></div>')
        rows += (f'<div class="row"><div class="ts">{ts_html}</div>'
                 f'<div class="rc"><div class="ln">{esc(line)}</div>{mir}</div></div>')

    # 小資訊
    minfo = ''
    if s['subtitle']:
        minfo += f'<div class="minfo"><div class="k">字幕卡</div><div class="v">{esc(s["subtitle"])}</div></div>'
    if s['bgm']:
        minfo += f'<div class="minfo"><div class="k">BGM</div><div class="v">{esc(s["bgm"])}</div></div>'
    if s['compliance']:
        minfo += f'<div class="minfo"><div class="k">合規自查</div><div class="v">{esc(s["compliance"])}</div></div>'

    cta = (f'CTA 關鍵字：<b>{esc(s["cta_kw"])}</b>' if s['cta_kw'] else 'CTA：見腳本結尾')

    # hashtag-pool（SOP §2.5 每卡必含）
    hashtag_html = ''
    if s['hashtags']:
        tags = s['hashtags'].split()
        hashtag_html = ('<div class="hashtag-pool">'
                        + ''.join(f'<span class="hashtag">{esc(t)}</span>' for t in tags)
                        + '</div>')

    # 場景（SOP §2.5）
    scene_html = f'<div class="scene">📍 {esc(s["scene"])}</div>' if s['scene'] else ''
    # insight 卡頭預覽（§2.5 標題下一句重點；無則用 hook fallback）
    preview = s['insight'] or hook

    return (
        f'<article class="card {tone}" data-cat="" id="wendi{esc(s["no"])}"'
        f' data-caption="{esc_attr(s["caption"])}" data-hashtags="{esc_attr(s["hashtags"])}">'
        '<div class="bar"></div>'
        '<div class="card-head" onclick="toggleCard(this)">'
        f'<div class="no">{esc(s["no"])}</div>'
        f'<div class="c-meta">{"".join(pills)}</div>'
        f'<div class="c-ttl">{esc(s["title"])}</div>'
        f'<div class="insight">{esc(preview)}</div>'
        '<div class="more">展開完整腳本</div>'
        '</div>'
        '<div class="card-body">'
        f'{scene_html}'
        f'<div class="tl">{rows}</div>'
        f'<div class="meta-grid">{minfo}</div>'
        f'{hashtag_html}'
        f'<div class="c-foot"><div class="c-cta">{cta}</div>'
        '<button class="copy" onclick="copyCaption(this)">複製文案</button></div>'
        '</div></article>'
    )


def render_thread(t):
    hh = t.get('hashtags', '')
    hash_html = f'<div class="th-hash">{esc(hh)}</div>' if hh else ''
    return (
        f'<div class="th-card" data-hashtags="{esc_attr(hh)}">'
        f'<div class="th-top"><div class="av"><img src="{QVER}" alt="溫蒂"></div>'
        f'<div class="nm">溫蒂<small>衍生自 {esc(t["src"])}</small></div></div>'
        '<button class="th-copy" onclick="copyThread(this)">複製</button>'
        f'<div class="tx">{esc(t["body"])}</div>'
        f'{hash_html}'
        '</div>'
    )


# ============================================================
# CSS（便當格版型 — 已截圖驗證版）
# ============================================================
CSS = r''':root{
  --cream:#FBFAF5; --cream2:#F3F1E7; --paper:#FFFFFF;
  --moss:#6FA84A; --moss-d:#4C7A30; --moss-l:#E9F4D8; --moss-glow:#F1F8E7;
  --coral:#FF6F5E; --coral-d:#E8553F; --coral-l:#FFE6E1;
  --ink:#2A3122; --ink2:#5A6150; --ink3:#8C9079; --ink4:#B4B7A4;
  --line:#E6E7D9; --line2:#D8DAC8;
  --display:'Outfit','Noto Sans TC',system-ui,sans-serif;
  --sans:'Noto Sans TC','PingFang TC','Microsoft JhengHei',sans-serif;
  --r-xl:20px; --r-lg:16px; --r-md:12px; --r-sm:8px;
  --sh:0 6px 22px -10px rgba(60,80,30,.16);
  --sh2:0 14px 40px -16px rgba(60,80,30,.26);
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html{scroll-behavior:smooth}
body{background:radial-gradient(circle at 88% -2%,var(--moss-glow) 0,transparent 38%),radial-gradient(circle at 4% 102%,var(--coral-l) 0,transparent 30%),var(--cream);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.75;-webkit-font-smoothing:antialiased;font-feature-settings:"palt";padding-bottom:80px}
img{display:block;max-width:100%}
a{color:inherit;text-decoration:none}
button{font-family:inherit}
.wrap{width:min(960px,92vw);margin:0 auto}
.hero{padding:34px 0 18px}
.bento{display:grid;grid-template-columns:repeat(4,1fr);grid-auto-rows:minmax(96px,auto);gap:13px}
.bento .cell{border-radius:var(--r-lg);padding:18px 20px;position:relative;overflow:hidden;display:flex;flex-direction:column;justify-content:center}
.cell.id{grid-column:span 2;grid-row:span 2;background:linear-gradient(150deg,var(--moss-l),#fff 70%);border:1px solid var(--line);flex-direction:row;align-items:center;gap:18px}
.cell.id .qv{width:124px;height:124px;flex-shrink:0;border-radius:24px;overflow:hidden;background:var(--moss-glow);border:3px solid #fff;box-shadow:var(--sh2);transform:rotate(-3deg)}
.cell.id .qv img{width:100%;height:100%;object-fit:cover}
.cell.id .who .name{font-family:var(--display);font-weight:800;font-size:clamp(30px,6vw,42px);line-height:1.05;letter-spacing:-.01em;color:var(--ink)}
.cell.id .who .name .en{display:block;font-size:15px;font-weight:600;color:var(--moss-d);letter-spacing:.18em;margin-top:3px}
.cell.id .who .slo{margin-top:10px;font-size:14px;color:var(--ink2);font-weight:500;line-height:1.5}
.cell.id .who .slo b{color:var(--coral-d);font-weight:700}
.cell.role{grid-column:span 2;background:var(--ink);color:#fff;border:1px solid var(--ink)}
.cell.role .k{font-size:11px;letter-spacing:.2em;color:var(--moss);font-weight:700;font-family:var(--display)}
.cell.role .v{font-family:var(--display);font-weight:700;font-size:clamp(17px,3.4vw,22px);line-height:1.3;margin-top:3px}
.cell.role .v small{display:block;font-size:13px;font-weight:400;color:#C7CBB8;margin-top:4px;font-family:var(--sans)}
.cell.links{background:var(--paper);border:1px solid var(--line);flex-direction:row;align-items:center;gap:9px;flex-wrap:wrap}
.cell.links a{display:inline-flex;align-items:center;gap:6px;background:var(--cream2);border:1px solid var(--line);border-radius:999px;padding:6px 13px;font-size:12.5px;font-weight:600;color:var(--ink2);transition:.2s}
.cell.links a:hover{background:var(--moss);color:#fff;border-color:var(--moss);transform:translateY(-1px)}
.cell.links a.line{background:var(--coral);color:#fff;border-color:var(--coral)}
.cell.links a.line:hover{background:var(--coral-d);border-color:var(--coral-d)}
.cell.stat{background:linear-gradient(145deg,var(--coral) 0,var(--coral-d) 100%);color:#fff;border:1px solid var(--coral-d)}
.cell.stat .big{font-family:var(--display);font-weight:900;font-size:38px;line-height:1}
.cell.stat .lb{font-size:12px;font-weight:500;color:#FFE2DC;margin-top:2px}
@media(max-width:680px){.bento{grid-template-columns:repeat(2,1fr);gap:10px}.cell.id{grid-column:span 2;flex-direction:column;text-align:center}.cell.id .qv{transform:none}.cell.role{grid-column:span 2}.cell.links,.cell.stat{grid-column:span 1}}
.group{margin-top:30px}
.grp-head{cursor:pointer;user-select:none;-webkit-user-select:none;display:flex;align-items:center;gap:14px;padding:12px 16px;background:var(--paper);border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:var(--sh);position:relative}
.grp-head .tag{font-family:var(--display);font-weight:800;font-size:15px;color:#fff;background:var(--moss-d);border-radius:var(--r-sm);padding:5px 12px;flex-shrink:0}
.grp-head .ttl{font-family:var(--display);font-weight:700;font-size:17px;color:var(--ink)}
.grp-head .ttl small{font-family:var(--sans);font-weight:400;font-size:12.5px;color:var(--ink3);margin-left:8px}
.grp-head .cnt{margin-left:auto;font-size:12.5px;color:var(--ink3);font-weight:500;flex-shrink:0;padding-right:30px}
.grp-head::after{content:'−';position:absolute;right:18px;top:50%;transform:translateY(-50%);width:24px;height:24px;line-height:22px;text-align:center;font-size:16px;color:var(--moss-d);border:1.5px solid var(--moss);border-radius:50%}
.group.collapsed .grp-head::after{content:'+'}
.group.collapsed .cards{display:none}
.cards{margin-top:14px;display:grid;grid-template-columns:repeat(2,1fr);gap:14px;align-items:start}
@media(max-width:680px){.cards{grid-template-columns:1fr}}
.card{background:var(--paper);border:1px solid var(--line);border-radius:var(--r-lg);overflow:hidden;box-shadow:var(--sh);transition:transform .25s,box-shadow .25s}
.card:hover{transform:translateY(-2px);box-shadow:var(--sh2)}
.card .bar{height:5px;background:var(--moss)}
.card.t-story .bar{background:linear-gradient(90deg,var(--moss),var(--moss-d))}
.card.t-punch .bar{background:linear-gradient(90deg,var(--coral),var(--coral-d))}
.card.t-life .bar{background:linear-gradient(90deg,#7BC4C4,#4C7A30)}
.card-head{cursor:pointer;user-select:none;-webkit-user-select:none;padding:16px 18px;position:relative}
.card-head .no{font-family:var(--display);font-weight:900;font-size:30px;color:var(--moss-l);line-height:.9;position:absolute;top:12px;right:16px;letter-spacing:-.02em}
.card.t-punch .card-head .no{color:var(--coral-l)}
.c-meta{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:9px;padding-right:46px}
.pill{font-size:10.5px;font-weight:700;border-radius:999px;padding:2.5px 9px;letter-spacing:.02em}
.pill.ig{background:#FCE6EE;color:#C4587C}
.pill.tk{background:#E5E2F0;color:#6357A0}
.pill.th{background:#E5EAEC;color:#566B76}
.pill.fish{background:var(--coral-l);color:var(--coral-d)}
.pill.time{background:var(--moss-l);color:var(--moss-d)}
.c-ttl{font-family:var(--display);font-weight:700;font-size:17px;line-height:1.4;color:var(--ink);padding-right:40px}
.card-head .insight{margin-top:11px;background:var(--moss-glow);border-left:3px solid var(--moss);border-radius:var(--r-sm);padding:10px 13px;font-size:13.5px;color:var(--ink2);line-height:1.6;font-weight:500}
.card.t-punch .card-head .insight{background:var(--coral-l);border-left-color:var(--coral)}
.scene{margin-bottom:13px;font-size:12.5px;color:var(--ink3);font-weight:500}
.card-head .more{margin-top:12px;display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--moss-d)}
.card.t-punch .card-head .more{color:var(--coral-d)}
.card-head .more::after{content:'▾';transition:transform .25s}
.card.open .card-head .more::after{transform:rotate(-180deg)}
.card-body{display:none;padding:0 18px 18px}
.card.open .card-body{display:block}
.tl{border-top:1px dashed var(--line2);padding-top:14px}
.tl .row{display:flex;gap:12px;padding:9px 0;border-bottom:1px solid var(--cream2)}
.tl .row:last-child{border-bottom:none}
.tl .ts{flex-shrink:0;width:74px;font-size:10.5px;font-weight:700;color:var(--moss-d);font-family:var(--display);line-height:1.55;padding-top:1px}
.card.t-punch .tl .ts{color:var(--coral-d)}
.tl .rc{flex:1;min-width:0}
.tl .ln{font-size:13.5px;color:var(--ink);line-height:1.65}
.mirror{display:flex;align-items:flex-start;gap:8px;margin-top:8px;background:var(--moss-glow);border:1px solid var(--moss-l);border-left:3px solid var(--moss);border-radius:6px;padding:7px 11px;font-size:12.5px;color:var(--ink2);line-height:1.6}
.mirror .mc{flex-shrink:0;background:var(--moss);color:#fff;border-radius:4px;padding:1px 8px;font-size:10.5px;font-weight:700;white-space:nowrap;font-family:var(--display);margin-top:1px}
.mirror .mt{flex:1}
.card.t-punch .mirror{background:var(--coral-l);border-color:#FBD3CB;border-left-color:var(--coral)}
.card.t-punch .mirror .mc{background:var(--coral-d)}
.meta-grid{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.minfo{flex:1;min-width:130px;background:var(--cream);border:1px solid var(--line);border-radius:var(--r-md);padding:10px 13px}
.minfo .k{font-size:10px;letter-spacing:.14em;color:var(--ink3);font-weight:700;font-family:var(--display);margin-bottom:3px}
.minfo .v{font-size:13px;color:var(--ink);line-height:1.6}
.hashtag-pool{display:flex;flex-wrap:wrap;gap:5px;margin-top:13px}
.hashtag{font-size:11px;color:var(--moss-d);background:var(--moss-l);border-radius:5px;padding:2px 8px;font-weight:500;letter-spacing:.01em}
.card.t-punch .hashtag{color:var(--coral-d);background:var(--coral-l)}
.c-foot{display:flex;align-items:center;gap:10px;margin-top:14px;padding-top:13px;border-top:1px dashed var(--line2)}
.c-cta{flex:1;font-size:13px;color:var(--coral-d);font-weight:600;line-height:1.5}
.c-cta b{background:var(--coral-l);border-radius:5px;padding:1px 7px}
.copy{cursor:pointer;border:none;flex-shrink:0;background:var(--moss-d);color:#fff;border-radius:999px;padding:7px 16px;font-size:12px;font-weight:700;font-family:var(--display);transition:.2s}
.copy:hover{background:var(--moss)}
.copy.done{background:var(--coral)}
.thread-sec{margin-top:34px}
.sec-ttl{display:flex;align-items:center;gap:10px;margin-bottom:14px;cursor:pointer;user-select:none;-webkit-user-select:none}
.sec-ttl .ico{font-size:22px}
.sec-ttl h2{font-family:var(--display);font-weight:800;font-size:21px;color:var(--ink)}
.sec-ttl small{color:var(--ink3);font-size:12.5px;font-weight:400;font-family:var(--sans)}
.sec-ttl .ts-toggle{margin-left:auto;color:var(--moss-d);font-size:15px;transition:transform .25s}
.thread-sec.collapsed .ts-toggle{transform:rotate(-90deg)}
.thread-sec.collapsed .threads{display:none}
.threads{display:grid;grid-template-columns:repeat(2,1fr);gap:13px}
@media(max-width:680px){.threads{grid-template-columns:1fr}}
.th-card{background:var(--paper);border:1px solid var(--line);border-radius:var(--r-lg);padding:16px 17px;box-shadow:var(--sh);position:relative}
.th-card .th-top{display:flex;align-items:center;gap:8px;margin-bottom:9px}
.th-card .th-top .av{width:26px;height:26px;border-radius:8px;overflow:hidden;background:var(--moss-l)}
.th-card .th-top .av img{width:100%;height:100%;object-fit:cover}
.th-card .th-top .nm{font-weight:700;font-size:13px;color:var(--ink);font-family:var(--display)}
.th-card .th-top .nm small{display:block;font-weight:400;font-size:11px;color:var(--ink3);font-family:var(--sans)}
.th-card .tx{font-size:13.5px;color:var(--ink);line-height:1.75;white-space:pre-wrap}
.th-card .th-hash{margin-top:9px;font-size:11.5px;color:var(--moss-d);font-weight:500;line-height:1.6}
.th-card .th-copy{position:absolute;top:14px;right:15px;cursor:pointer;border:none;background:var(--cream2);color:var(--ink2);border-radius:999px;padding:4px 11px;font-size:11px;font-weight:700;font-family:var(--display);transition:.2s}
.th-card .th-copy:hover{background:var(--moss);color:#fff}
.th-card .th-copy.done{background:var(--coral);color:#fff}
.foot{margin-top:40px;text-align:center;color:var(--ink3);font-size:12px;line-height:1.9}
.foot .by{font-family:var(--display);font-weight:600;color:var(--ink2)}'''


JS = r'''function toggleGroup(id){document.getElementById(id).classList.toggle('collapsed')}
function toggleThreads(){document.getElementById('threadsec').classList.toggle('collapsed')}
function toggleCard(head){head.closest('.card').classList.toggle('open')}
function _copyText(text,btn,okLabel,defLabel){
  function done(){btn.textContent=okLabel;btn.classList.add('done');setTimeout(function(){btn.textContent=defLabel;btn.classList.remove('done')},1600)}
  function fb(){var ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.top='-9999px';document.body.appendChild(ta);ta.focus();ta.select();var ok=false;try{ok=document.execCommand('copy')}catch(e){ok=false}document.body.removeChild(ta);if(ok){done()}else{btn.textContent='請長按手動複製';setTimeout(function(){btn.textContent=defLabel},1800)}}
  if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(text).then(done).catch(fb)}else{fb()}
}
function copyCaption(btn){var c=btn.closest('.card');var cap=c.getAttribute('data-caption')||'';var h=c.getAttribute('data-hashtags')||'';if(!cap){var old=btn.textContent;btn.textContent='本批無文案';setTimeout(function(){btn.textContent='複製文案'},1600);return}_copyText((cap+'\n\n'+h).trim(),btn,'已複製 ✓','複製文案')}
function copyThread(btn){var c=btn.closest('.th-card');var tx=c.querySelector('.tx').innerText;var h=c.getAttribute('data-hashtags')||'';_copyText((tx+(h?'\n\n'+h:'')).trim(),btn,'已複製 ✓','複製')}'''


# ============================================================
# main
# ============================================================
def main():
    # ==== yaml-driven 模式（標準，唯一支援路徑）====
    if not _args.yaml_dir:
        print('ERROR: --yaml-dir 必填（新業主標準模式：--mode yaml --yaml-dir <路徑>）', file=sys.stderr)
        sys.exit(1)

    yaml_dir = os.path.abspath(_args.yaml_dir)
    if not os.path.isdir(yaml_dir):
        print(f'ERROR: yaml-dir 不存在：{yaml_dir}', file=sys.stderr)
        sys.exit(1)

    from yaml_to_sc import load_yaml_articles
    yaml_articles = load_yaml_articles(yaml_dir, expected_count=_args.expected_count)

    if not yaml_articles:
        print('ERROR: yaml-dir 內沒有找到任何 script_*.yaml，中止出貨', file=sys.stderr)
        sys.exit(1)

    batch_label = _args.batch_label or os.path.basename(yaml_dir)
    print(f'build_wendi.py loaded OK（yaml-driven）')
    print(f'yaml-dir: {yaml_dir}')
    print(f'batch-label: {batch_label}')
    print(f'yaml 數量: {len(yaml_articles)}')

    scripts = []
    for idx, ydata in enumerate(yaml_articles, start=1):
        s = wendi_yaml_adapter(ydata, num=idx)
        scripts.append(s)

    print(f'parsed: {len(scripts)} 腳本（yaml-driven）')

    if len(scripts) != 13:
        print(f'WARNING: 腳本數 {len(scripts)} != 13（非標準批次，請確認）', file=sys.stderr)

    # 藏鏡人完整性（SOP §2.5 / L0 §9 每支 >=2；S 級不出貨缺藏鏡人的頁）
    miss = [s['no'] for s in scripts if len(s['mirrors']) < 2]
    if miss:
        print(f'ERROR: 以下腳本藏鏡人 <2，中止出貨：{miss}', file=sys.stderr)
        sys.exit(1)

    # 脆文（yaml-dir 下的 threads_*.md，若存在；走新格式解析器）
    threads = []
    import glob as _glob
    for threads_md_path in sorted(_glob.glob(os.path.join(yaml_dir, 'threads_*.md'))):
        with open(threads_md_path, 'r', encoding='utf-8') as f:
            threads_md = f.read()
        parsed = parse_threads_new_fmt(threads_md)
        if parsed:
            threads.extend(parsed)
        else:
            # fallback：舊格式（## 7 篇 Threads 大標）
            threads.extend(parse_threads(threads_md))
    print(f'脆文: {len(threads)} 篇')

    cards = '\n'.join(render_card(s) for s in scripts)
    threads_html = '\n'.join(render_thread(t) for t in threads)

    # batch_id：從 batch_label 取第一個「第 XX 批」供 id 用
    batch_id_m = re.search(r'第\s*(\d+)\s*批', batch_label)
    batch_id = 'b' + batch_id_m.group(1).zfill(2) if batch_id_m else 'bnew'

    section = (
        f'<section class="group collapsed" id="{esc(batch_id)}">'
        f'<div class="grp-head" onclick="toggleGroup(\'{esc_attr(batch_id)}\')">'
        # 2026-06-12 WP-D：tag 徽章已含「第 NN 批」，ttl 只放日期段（舊版 ttl 重放整個
        # batch_label → 線上 head 顯示「第 02 批第 02 批 · 2026-06-03」+ 空 <small>）
        f'<span class="tag">{esc(batch_label.split("·")[0].strip())}</span>'
        f'<span class="ttl">{esc(batch_label.split("·", 1)[1].strip() if "·" in batch_label else batch_label)}</span>'
        f'<span class="cnt">{len(scripts)} 支</span></div>'
        f'<div class="cards">{cards}</div></section>'
    )
    thr_section = (
        f'<section class="thread-sec collapsed" id="threadsec">'
        f'<div class="sec-ttl" onclick="toggleThreads()"><span class="ico">🧵</span>'
        f'<h2>Threads 脆文</h2><small>{len(threads)} 篇 · 可直接複製貼文</small>'
        f'<span class="ts-toggle">▾</span></div>'
        f'<div class="threads">{threads_html}</div></section>'
    ) if threads else ''

    page = f'''<!DOCTYPE html>
<html lang="zh-Hant-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#FBFAF5">
<meta property="og:title" content="溫蒂的腳本｜24歲・嘉義人在高雄">
<meta property="og:image" content="{QVER}">
<title>溫蒂的腳本 ｜ 24歲・嘉義人在高雄 🌿</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800;900&family=Noto+Sans+TC:wght@400;500;700;900&display=swap" rel="stylesheet">
<!-- 此頁由 build_wendi.py 機械化讀腳本生成；勿手改，改 build_wendi.py 重跑 -->
<style>
{CSS}
</style>
</head>
<body>
<div class="wrap">
<header class="hero"><div class="bento">
<div class="cell id"><div class="qv"><img src="{QVER}" alt="溫蒂"></div>
<div class="who"><div class="name">溫蒂<span class="en">WENDY · SKIN</span></div>
<div class="slo">24歲嘉義人，一個人在高雄開工作室。<br><b>不完美，但敢走自己的路。</b></div></div></div>
<div class="cell role"><div class="k">WHO I AM</div>
<div class="v">高雄左營 · 油痘肌調理師<small>體內 + 體外同時調理，不只清粉刺</small></div></div>
<div class="cell links">
<a href="https://www.instagram.com/_yu0812_" target="_blank" rel="noopener">📸 IG</a>
<a href="https://www.tiktok.com/@_yu0812_" target="_blank" rel="noopener">🎵 TikTok</a>
<a href="https://www.threads.net/@_yu0812_" target="_blank" rel="noopener">🧵 Threads</a>
<a class="line" href="https://page.line.me/162vpemu" target="_blank" rel="noopener">💬 LINE 預約</a></div>
<div class="cell stat"><div class="big">{len(scripts)}</div><div class="lb">支腳本 · {esc(batch_label)}</div></div>
</div></header>
{section}
{thr_section}
<footer class="foot"><div class="by">溫蒂的腳本庫 · WENDY</div>
<div>高雄左營 · 油痘肌調理師 ｜ 體內 + 體外同時調理</div></footer>
</div>
<script>
{JS}
</script>
</body>
</html>'''

    with open(_args.out, 'w', encoding='utf-8') as f:
        f.write(page)
    size = os.path.getsize(_args.out)
    print(f'HTML 已生成：{_args.out}  ({size} bytes)')
    print(f'Total articles: {len(scripts)}')
    print()
    print('next step:')
    print(f'  1. python validate_deploy.py')
    print(f'  2. git add wendi.html build_wendi.py')
    print(f'  3. git commit + push（霸告親手）')
    print(f'  4. Playwright drive 線上自驗 9 件（SOP §8）')


if __name__ == '__main__':
    main()
