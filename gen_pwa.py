import pandas as pd

xls = pd.ExcelFile('C:/Users/00sta/Documents/Claude/Projects/背景/短影音腳本庫_v6.xlsx')

cat_list = [
    ('揭露型', '🔍', '#e74c3c', '#fef5f5'),
    ('未來預測型', '🔮', '#8e44ad', '#f9f0fc'),
    ('市場觀點型', '📊', '#2980b9', '#f0f7fd'),
    ('真實案例型', '📖', '#27ae60', '#f0faf4'),
    ('暴力直接型', '💥', '#d35400', '#fdf5ef'),
    ('隱性植入型', '🎯', '#c0392b', '#fdf0ef'),
    ('稅法揭密型', '⚖️', '#34495e', '#f2f4f5'),
    ('在地冷知識型', '🗺️', '#16a085', '#eefaf7'),
]
cat_info = {c[0]: {'emoji':c[1],'color':c[2],'bg':c[3]} for c in cat_list}

def esc(s):
    return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

def detect_cat(name):
    mapping = {'揭露':'揭露型','未來':'未來預測型','市場':'市場觀點型','真實':'真實案例型',
               '暴力':'暴力直接型','隱性':'隱性植入型','稅法':'稅法揭密型','在地':'在地冷知識型'}
    for k,v in mapping.items():
        if k in name: return v
    return ''

scripts = []
for sname in xls.sheet_names[1:]:
    df = pd.read_excel(xls, sname, header=None)
    rows = [[str(v) if pd.notna(v) else '' for v in row] for _, row in df.iterrows()]
    title = rows[0][0] if rows else sname
    for e in ['🔍','🔮','📊','📖','💥','🎯','⚖️','🗺️']:
        title = title.replace(e,'').strip()
    meta_raw = rows[1][0] if len(rows)>1 else ''
    version = '藏鏡人版' if '藏' in sname else '獨白版'
    category = detect_cat(sname)
    hook=mood=scene=ref=agent=''
    if meta_raw:
        for p in meta_raw.split('·'):
            p=p.strip()
            if 'Hook' in p: hook=p.split('：',1)[-1].strip() if '：' in p else ''
            elif '情緒' in p: mood=p.split('：',1)[-1].strip() if '：' in p else ''
            elif '場景' in p: scene=p.split('：',1)[-1].strip() if '：' in p else ''
            elif '參考' in p: ref=p.split('：',1)[-1].strip() if '：' in p else ''
            elif '露出' in p: agent=p.strip()
    lines=[]
    for r in rows[3:]:
        t,d,s_=r[0] if len(r)>0 else '',r[1] if len(r)>1 else '',r[2] if len(r)>2 else ''
        if '🔁' in t or '◀' in t or '回到腳本總覽' in t: continue
        if t or d or s_: lines.append((t,d,s_))
    scripts.append(dict(title=title,version=version,category=category,hook=hook,mood=mood,scene=scene,ref=ref,agent=agent,lines=lines))

cats = {}
for s in scripts:
    cats.setdefault(s['category'],[]).append(s)

# === Build cards ===
cards_html = ''
idx = 0
for cat, items in cats.items():
    info = cat_info[cat]
    for s in items:
        ver_cls = 'v-mono' if s['version']=='獨白版' else 'v-mirror'
        ver_label = '🎤 獨白版' if s['version']=='獨白版' else '🎭 藏鏡人版'
        tags=''
        if s['hook']: tags+=f'<span class="chip c-hook">Hook：{esc(s["hook"])}</span>'
        if s['mood']: tags+=f'<span class="chip c-mood">{esc(s["mood"])}</span>'
        tl=''
        for t,d,sub in s['lines']:
            d_h=esc(d)
            d_h=d_h.replace('【藏鏡人】','<b class="sp sp-m">藏鏡人</b> ')
            d_h=d_h.replace('【主角】','<b class="sp sp-h">主角</b> ')
            sub_h=f'<div class="sub-line">📝 {esc(sub)}</div>' if sub else ''
            tl+=f'<div class="tl-row"><div class="tl-time" style="color:{info["color"]}">{esc(t)}</div><div class="tl-txt">{d_h}{sub_h}</div></div>\n'
        scene_h=f'<div class="meta-line">🎬 {esc(s["scene"])}</div>' if s['scene'] else ''
        ref_h=f'<div class="meta-line">📎 {esc(s["ref"])}</div>' if s['ref'] else ''
        cards_html+=f'''<div class="card" data-cat="{cat}" data-ver="{s['version']}" id="c{idx}">
<div class="card-head" style="border-color:{info['color']}" onclick="toggle({idx})">
<div class="card-row1"><span class="vb {ver_cls}">{ver_label}</span><span class="cb" style="color:{info['color']}">{info['emoji']} {cat}</span></div>
<h3 class="ct">{esc(s['title'])}</h3>
<div class="chips">{tags}</div>
<div class="hint" id="h{idx}">▼ 展開腳本</div>
</div>
<div class="card-body" id="b{idx}">
{scene_h}{ref_h}
<div class="tl">{tl}</div>
</div>
</div>
'''
        idx+=1

# === Category menu (full names, scrollable) ===
cat_menu=''
for cname,emoji,color,bg in cat_list:
    cat_menu+=f'<button class="cm-btn" data-cat="{cname}" onclick="pickCat(\'{cname}\',this)" style="--ac:{color};--abg:{bg}">{emoji} {cname}</button>\n'

html=f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#1e272e">
<link rel="manifest" href="./manifest.json">
<link rel="apple-touch-icon" href="./icon-192.png">
<title>腳本庫</title>
<style>
:root{{--bg:#f2f3f7;--card:#fff;--tx:#1e272e;--tx2:#636e72;--tx3:#adb5bd;--bd:#e9ecef;--hdr:#1e272e;--r:12px;
--st:env(safe-area-inset-top,0px);--sb:env(safe-area-inset-bottom,0px);}}
*{{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent;}}
html{{scroll-behavior:smooth;}}
body{{font-family:"PingFang TC","Microsoft JhengHei","Noto Sans TC",system-ui,sans-serif;
background:var(--bg);color:var(--tx);line-height:1.6;padding-bottom:calc(56px + var(--sb));-webkit-font-smoothing:antialiased;}}

/* Header */
.hdr{{background:var(--hdr);color:#fff;padding:14px 16px 10px;position:sticky;top:0;z-index:100;
box-shadow:0 2px 10px rgba(0,0,0,.15);text-align:center;}}
.hdr h1{{font-size:1.1rem;font-weight:700;}}
.hdr .sub{{font-size:.68rem;color:rgba(255,255,255,.4);margin-top:2px;}}

/* Toolbar: search + filter */
.toolbar{{position:sticky;top:52px;z-index:90;background:var(--bg);padding:10px 12px 6px;}}
.search{{width:100%;padding:9px 14px;border:none;border-radius:8px;background:var(--card);
font-size:.88rem;outline:none;box-shadow:0 1px 3px rgba(0,0,0,.05);font-family:inherit;}}
.search::placeholder{{color:var(--tx3);}}

/* Category menu - 2-column grid */
.cat-menu{{padding:6px 12px 4px;position:sticky;top:102px;z-index:80;background:var(--bg);}}
.cm-grid{{display:grid;grid-template-columns:1fr 1fr;gap:6px;}}
.cm-btn{{display:flex;align-items:center;gap:5px;padding:8px 10px;border-radius:8px;
border:1.5px solid var(--bd);background:var(--card);font-size:.78rem;color:var(--tx2);
cursor:pointer;font-family:inherit;text-align:left;transition:all .15s;white-space:nowrap;overflow:hidden;}}
.cm-btn.active{{background:var(--abg);color:var(--ac);border-color:var(--ac);font-weight:700;}}
.cm-all{{grid-column:1/-1;justify-content:center;font-weight:600;}}
.cm-all.active{{background:var(--hdr);color:#fff;border-color:var(--hdr);}}

/* Version filter */
.ver-row{{display:flex;gap:6px;padding:6px 12px 10px;justify-content:center;}}
.vf{{padding:5px 16px;border-radius:20px;border:1.5px solid var(--bd);background:var(--card);
font-size:.76rem;color:var(--tx2);cursor:pointer;font-family:inherit;transition:all .12s;}}
.vf.active{{background:var(--hdr);color:#fff;border-color:var(--hdr);}}

/* Stats */
.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:0 12px 12px;}}
.st-box{{background:var(--card);border-radius:10px;padding:12px 8px;text-align:center;box-shadow:0 1px 2px rgba(0,0,0,.04);}}
.st-n{{font-size:1.4rem;font-weight:800;color:var(--hdr);}}
.st-l{{font-size:.65rem;color:var(--tx3);}}

/* Cards */
.cards{{padding:0 12px;}}
.card{{background:var(--card);border-radius:var(--r);margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.04);overflow:hidden;}}
.card-head{{padding:14px 16px;cursor:pointer;border-left:4px solid var(--bd);}}
.card-row1{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;}}
.vb{{padding:2px 8px;border-radius:5px;font-size:.66rem;font-weight:700;}}
.v-mono{{background:#e8f5e9;color:#2e7d32;}}
.v-mirror{{background:#fff3e0;color:#e65100;}}
.cb{{font-size:.7rem;font-weight:600;}}
.ct{{font-size:.92rem;font-weight:700;line-height:1.5;margin-bottom:4px;}}
.chips{{display:flex;flex-wrap:wrap;gap:4px;}}
.chip{{padding:2px 8px;border-radius:4px;font-size:.64rem;font-weight:500;}}
.c-hook{{background:#fff8e1;color:#f57f17;}}
.c-mood{{background:#fce4ec;color:#c62828;}}
.hint{{font-size:.7rem;color:var(--tx3);text-align:center;margin-top:8px;}}

/* Card body (collapsed) */
.card-body{{max-height:0;overflow:hidden;transition:max-height .35s ease;padding:0 16px;}}
.card-body.open{{max-height:5000px;padding:0 16px 16px;}}
.meta-line{{font-size:.75rem;color:var(--tx2);margin-bottom:5px;line-height:1.5;}}

/* Timeline */
.tl{{margin-top:10px;}}
.tl-row{{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid #f4f5f7;}}
.tl-row:last-child{{border-bottom:none;}}
.tl-time{{width:52px;flex-shrink:0;font-size:.72rem;font-weight:700;padding-top:2px;}}
.tl-txt{{flex:1;min-width:0;font-size:.85rem;line-height:1.7;}}
.sub-line{{margin-top:5px;padding:5px 10px;background:var(--bg);border-radius:6px;font-size:.74rem;color:var(--tx2);line-height:1.4;}}

.sp{{display:inline-block;padding:1px 6px;border-radius:4px;font-size:.66rem;color:#fff;vertical-align:middle;margin-right:2px;}}
.sp-m{{background:#ff9800;}}.sp-h{{background:#42a5f5;}}

/* Bottom nav */
.bnav{{position:fixed;bottom:0;left:0;right:0;background:var(--card);border-top:1px solid var(--bd);
display:flex;justify-content:center;gap:32px;padding:6px 0 calc(6px + var(--sb));z-index:100;}}
.bn{{display:flex;flex-direction:column;align-items:center;gap:1px;font-size:.62rem;color:var(--tx3);
cursor:pointer;border:none;background:none;font-family:inherit;padding:4px 10px;}}
.bn.active{{color:var(--hdr);font-weight:700;}}
.bn-i{{font-size:1.1rem;}}

.empty{{display:none;text-align:center;padding:50px 20px;color:var(--tx3);font-size:.9rem;}}

@media(min-width:600px){{
.cards,.stats,.cat-menu,.toolbar,.ver-row{{max-width:540px;margin-left:auto;margin-right:auto;}}
.cm-grid{{grid-template-columns:repeat(3,1fr);}}
}}
</style>
</head>
<body>

<div class="hdr">
<h1>北高雄房產短影音腳本庫</h1>
<div class="sub">16 支腳本 · 8 類型 · 獨白版 + 藏鏡人版</div>
</div>

<div class="toolbar">
<input class="search" type="text" placeholder="搜尋關鍵字..." oninput="doFilter()">
</div>

<div class="cat-menu">
<div class="cm-grid">
<button class="cm-btn cm-all active" onclick="pickCat('all',this)" style="--ac:#1e272e;--abg:#1e272e">📋 全部顯示</button>
{cat_menu}
</div>
</div>

<div class="ver-row">
<button class="vf active" onclick="pickVer('all',this)">全部</button>
<button class="vf" onclick="pickVer('獨白版',this)">🎤 獨白</button>
<button class="vf" onclick="pickVer('藏鏡人版',this)">🎭 藏鏡人</button>
</div>

<div class="stats">
<div class="st-box"><div class="st-n">16</div><div class="st-l">腳本總數</div></div>
<div class="st-box"><div class="st-n">8</div><div class="st-l">內容類型</div></div>
<div class="st-box"><div class="st-n">2</div><div class="st-l">版本形式</div></div>
</div>

<div class="cards" id="cardList">
{cards_html}
</div>
<div class="empty" id="empty">找不到符合的腳本</div>

<div class="bnav">
<button class="bn active" onclick="goHome()"><span class="bn-i">🏠</span>首頁</button>
<button class="bn" onclick="pickVer('獨白版',document.querySelectorAll('.vf')[1])"><span class="bn-i">🎤</span>獨白版</button>
<button class="bn" onclick="pickVer('藏鏡人版',document.querySelectorAll('.vf')[2])"><span class="bn-i">🎭</span>藏鏡人版</button>
</div>

<script>
var cCat='all',cVer='all';

function pickCat(cat,el){{
  cCat=cat;
  document.querySelectorAll('.cm-btn').forEach(function(b){{b.classList.remove('active');}});
  el.classList.add('active');
  doFilter();
}}

function pickVer(ver,el){{
  cVer=ver;
  document.querySelectorAll('.vf').forEach(function(b){{b.classList.remove('active');}});
  if(el)el.classList.add('active');
  // update bottom nav
  document.querySelectorAll('.bn').forEach(function(b,i){{
    if(i===0) b.classList.toggle('active',ver==='all');
    else if(i===1) b.classList.toggle('active',ver==='獨白版');
    else b.classList.toggle('active',ver==='藏鏡人版');
  }});
  doFilter();
}}

function doFilter(){{
  var q=document.querySelector('.search').value.toLowerCase();
  var cards=document.querySelectorAll('.card');
  var any=false;
  cards.forEach(function(c){{
    var ok1=cCat==='all'||c.dataset.cat===cCat;
    var ok2=cVer==='all'||c.dataset.ver===cVer;
    var ok3=!q||c.textContent.toLowerCase().includes(q);
    var show=ok1&&ok2&&ok3;
    c.style.display=show?'':'none';
    if(show)any=true;
  }});
  document.getElementById('empty').style.display=any?'none':'block';
}}

function toggle(i){{
  var b=document.getElementById('b'+i);
  var h=document.getElementById('h'+i);
  if(b.classList.contains('open')){{
    b.classList.remove('open');
    h.textContent='▼ 展開腳本';
  }}else{{
    b.classList.add('open');
    h.textContent='▲ 收合';
  }}
}}

function goHome(){{
  cCat='all';cVer='all';
  document.querySelector('.search').value='';
  document.querySelectorAll('.cm-btn').forEach(function(b){{b.classList.remove('active');}});
  document.querySelector('.cm-all').classList.add('active');
  document.querySelectorAll('.vf').forEach(function(b){{b.classList.remove('active');}});
  document.querySelectorAll('.vf')[0].classList.add('active');
  document.querySelectorAll('.bn').forEach(function(b,i){{b.classList.toggle('active',i===0);}});
  doFilter();
  window.scrollTo({{top:0,behavior:'smooth'}});
}}

if('serviceWorker' in navigator){{navigator.serviceWorker.register('./sw.js');}}
</script>
</body>
</html>'''

with open('C:/Users/00sta/Documents/Claude/Projects/背景/pwa/index.html','w',encoding='utf-8') as f:
    f.write(html)
print('Done!')
