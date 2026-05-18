import os, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
LIB = os.path.dirname(os.path.abspath(__file__))

# v2 2026-05-18: align SOP v2 9-feature logic
# Accumulative: 第03批(new) + 第02批(existing)

BATCH_03 = '第 03 批 · 2026-05-18'
BATCH_02 = '第 02 批 · 2026-05-12'

Q = chr(39)

def sc_article(num, title, pie, platforms, cta, scene, timeline, batch=None,
               caption=None, platform_chip=None, po_time=None, hashtag=None, img=None):
    if batch is None:
        batch = BATCH_03
    aid = str(num).zfill(2) + ('b' if batch == BATCH_02 else '')
    pl_tags = ''.join('<span class="tag">' + p + '</span>' for p in platforms)
    派系_tags = '<span class="tag">' + pie + '</span>'
    cta_tag = '<span class="tag pe">' + cta + '</span>'
    tl_html = ''
    for ts, desc, *rest in timeline:
        sub = rest[0] if rest else ''
        tl_html += (
            '<div class="sl"><span class="st">' + ts + '</span>'
            '<p class="sd">' + desc + '</p>'
        )
        if sub:
            tl_html += '<p class="sc-sub">' + sub + '</p>'
        tl_html += '</div>\n'

    cap_escaped = ''
    if caption:
        cap_escaped = caption.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
    cap_attr = ' data-caption="' + cap_escaped + '"' if cap_escaped else ''

    hashtag_attr = ''
    hashtag_html = ''
    if hashtag:
        hashtag_attr = ' data-hashtags="' + ' '.join(hashtag) + '"'
        hashtag_html = '<div class="hashtag-pool">' + ''.join('<span class="hashtag">' + t + '</span>' for t in hashtag) + '</div>\n'

    meta_extra = ''
    if platform_chip:
        meta_extra += '<span class="platform">▶ ' + platform_chip + '</span> '
    if po_time:
        meta_extra += '<span class="po-time">⏰ ' + po_time + '</span>'

    img_html = ''
    dl_btn = ''
    if img:
        img_html = '<div class="sc-img"><img src="' + img + '" class="card-thumb" alt="圖卡預覽" onclick="openLightbox(this); return false;"></div>\n'
        dl_name = os.path.basename(img)
        dl_btn = '<a class="download-btn" href="' + img + '" download="' + dl_name + '">下載圖卡</a>\n'

    copy_label = '複製文案' if cap_escaped else '複製腳本'
    batch_tag = '<div class="batch-tag">' + batch + '</div>\n'

    return (
        '<!-- #' + aid + ' -->\n'
        '<article class="sc" data-id="' + aid + '"' + cap_attr + hashtag_attr + '>\n'
        '<div class="sh" onclick="s(this)">\n'
        '  <div class="tp">\n'
        '    <span class="nm">No.' + str(num).zfill(2) + '</span>\n'
        '    <div class="ac"><button class="db" onclick="d(event,this)">已拍</button></div>\n'
        '  </div>\n'
        '  <div class="tg">\n'
        + 派系_tags + cta_tag + pl_tags +
        '\n  </div>\n' +
        (('  <div class="card-meta-extra">' + meta_extra + '</div>\n') if meta_extra else '') +
        '  <h2 class="ti">' + title + '</h2>\n'
        '  <p class="vi">' + scene + '</p>\n'
        '  <p class="ht">&#9660; Open</p>\n'
        '</div>\n'
        '<div class="sb-body">\n'
        '  <div class="sg">\n' + tl_html + '  </div>\n' +
        img_html + dl_btn + hashtag_html +
        '  <button class="copy-btn" onclick="copyScript(this)">' + copy_label + '</button>\n' +
        batch_tag +
        '</div>\n'
        '</article>'
    )

def gp_group_v2(key, label, arts, collapsed=True):
    inner = '\n'.join(arts)
    cnt = str(len(arts))
    cclass = 'gp collapsed' if collapsed else 'gp'
    return (
        '\n<!-- ' + label + ' -->\n'
        '<div class="' + cclass + '" data-g="' + key + '">\n'
        '<div class="gh" onclick="toggleGroup(this.parentElement)">\n'
        '  <div class="gt">\n'
        '    <span class="gc">' + key + '</span>\n'
        '    <span class="gn">' + label + '</span>\n'
        '    <span class="gx">' + cnt + ' 部</span>\n'
        '  </div>\n'
        '  <span class="gy">▼</span>\n'
        '</div>\n'
        '<div class="gb">\n\n' +
        inner + '\n\n'
        '</div>\n'
        '</div>'
    )

print('build_bappu.py v2 loaded OK')
print('LIB:', LIB)

# ============================================================
# 第 02 批 articles (existing 20 parts)
# ============================================================
def b2(num, title, grp, pl, cta, scene, tl, img=None):
    return sc_article(num, title, grp, pl, cta, scene, tl, batch=BATCH_02, img=img)

b02_01 = b2(1,'他冷戰，我繼續吃飯','故事戲劇派',['IG Reels','Threads'],'個人化諮詢',
    '家中客廳，兩人並坐沙發，叭噗嘴撅著，小C 一臉平靜吃東西',
    [('0-3秒 Hook','小C：他在冷戰，我在吃飯。',''),
     ('3-12秒','小C：冷戰的時候餓著自己，等他先開口，這件事我早就不幹了。',''),
     ('12-25秒','叭噗：你就不覺得你這樣很涼嗎。小C：我很涼，但我吃飽了。你要冷多久？叭噗沉默兩秒：你剩幾口。藏鏡人：就是我跟我男朋友！他先說話的那刻我什麼都好了！',''),
     ('52-60秒 CTA','小C：你們怎麼和好的？底下說說。','')])

b02_02 = b2(2,'點餐 5 分鐘 vs 3 秒的人生','人間觀察派',['IG Reels','TikTok'],'個人化諮詢',
    '餐廳，兩人看菜單，小C 埋頭認真看，叭噗早就闔上',
    [('0-3秒 Hook','叭噗放菜單看她：我已經點完了。小C 眼睛沒離菜單：我知道。再等一下。',''),
     ('12-25秒','小C：再考慮份量——叭噗：我吃飽再看你。小C 放下菜單：我決定了。我要你點的那個。藏鏡人：哈哈哈哈這個操作我懂！！',''),
     ('52-60秒 CTA','叭噗：你們誰更快做決定？轉給另一半看。','')])

b02_03 = b2(3,'他帶看回來，第一句話是這個','故事戲劇派',['IG Reels','FB Reels'],'個人化諮詢',
    '家中玄關，叭噗剛開門進來，看起來累但沒說',
    [('0-3秒 Hook','小C：客戶有沒有簽？叭噗換鞋，沒回頭：沒有。',''),
     ('3-12秒','小C 繼續看手機：那就下次。叭噗走進來，坐下。沉默三秒。',''),
     ('12-25秒','小C：我不太會說你辛苦了。但我會去弄個東西給他吃。他知道的。藏鏡人：我也不會說這種話，但我懂這種感覺...',''),
     ('52-60秒 CTA','小C：你跟另一半怎麼陪對方的？','')])

b02_04 = b2(4,'深夜 12 點他說了一句話','故事戲劇派',['IG Reels','小紅書'],'個人化諮詢',
    '臥室，燈光昏黃，兩人快要睡著',
    [('0-3秒 Hook','小C 輕聲：昨晚他說了一句話，我整個睡不著。',''),
     ('3-12秒','叭噗眼睛閉著，很平淡：謝謝你在。小C 停頓：你幹嘛突然說這個。',''),
     ('12-25秒','小C：他是那種——偶爾說一句，就比 365 天都說還準確。藏鏡人：有沒有這種人！不常說但說了就直接中！',''),
     ('52-60秒 CTA','小C：存起來，傳給你另一半。','')])

b02_05 = b2(5,'差點沒去北海道的那次','故事戲劇派',['IG Reels','TikTok'],'個人化諮詢',
    '室內，兩人坐著，像是在回憶',
    [('0-3秒 Hook','叭噗：我們差點因為一件事，沒去成北海道。',''),
     ('3-12秒','小C：出發前一天，我們大吵了一架。叭噗：是很大的那種。那晚我們沒說話。',''),
     ('12-25秒','小C：那個時候我在想，這個旅行要不要取消。叭噗：我在想同一件事。藏鏡人：哦不...他們最後有去嗎...',''),
     ('40-52秒','小C：北海道那次是我們最好的旅行之一。不是因為沒吵架，是因為我們吵完，還是決定出發。藏鏡人：我想存起來！這句話太準了！',''),
     ('52-60秒 CTA','叭噗：你跟另一半有沒有這種經歷？底下說。','')])

b02_06 = b2(6,'吵架後你說的第一句話，決定了你們【圖卡部】','圖卡部',['IG Reels','FB Reels'],'圖卡部（留言和好取圖卡）',
    '兩人面對面，事後回憶狀態',
    [('0-3秒 Hook','小C 直視鏡頭：你們吵架後說的第一句話，是什麼？',''),
     ('12-25秒','小C：不是道歉，不是算了算了，也不是沉默讓對方先說。是有一種說法，讓對方軟下來。叭噗：我們試過很多次，有用的只有幾種。答案在私訊。藏鏡人：我需要知道！我跟我男友每次都卡在這邊！',''),
     ('52-60秒 CTA','留言「和好」，私訊給你 3 個和好開場白','')],
    img='../bappu-batch03-fishing-card.png')

b02_07 = b2(7,'他朋友比我了解他','人間觀察派',['IG Reels','Threads'],'個人化諮詢',
    '朋友聚會後，回到家，兩人聊天',
    [('0-3秒 Hook','小C：他朋友比我了解他。我承認。',''),
     ('12-25秒','叭噗：那些事情不是秘密，就是——沒想到要說。小C：朋友了解你的某一個版本，我了解另一個。沒有誰比較全面。只是不同面。藏鏡人：這個說法有點讓我想傳給另一半看...',''),
     ('52-60秒 CTA','叭噗：你跟另一半有這種感覺嗎？','')])

b02_08 = b2(8,'她在家，我出去——我們的一天','人間觀察派',['IG Reels','FB Reels'],'個人化諮詢',
    '早上，叭噗準備出門，小C 還在工作',
    [('0-3秒 Hook','叭噗穿好外出服看小C：我去了。小C 沒抬頭：嗯。',''),
     ('12-25秒','叭噗：以前我以為，兩個人住在一起，要一起做很多事。後來發現，有自己的生活才不會膩。藏鏡人：天啊這就是我跟另一半的共識...',''),
     ('52-60秒 CTA','小C：你跟另一半是各自有生活，還是要在一起？','')])

b02_09 = b2(9,'我不記得那天說了什麼，但我記得他的表情','人間觀察派',['IG Reels','小紅書'],'個人化諮詢',
    '靜態，小C 對鏡頭，像是在想一件事',
    [('0-3秒 Hook','小C：我不記得那天說了什麼，但我記得他的表情。',''),
     ('12-25秒','小C：他看我的那個眼神，到現在還記得。不是驚喜，不是感動，就是一種——你說什麼我都在聽的眼神。那個很難裝出來。藏鏡人：我突然想起我另一半看我也有這種眼神...',''),
     ('52-60秒 CTA','字幕：轉給另一半，問他你有這個眼神嗎','')])

b02_10 = b2(10,'鞋櫃只有兩格，我的卻放了三雙','自嘲反差派',['IG Reels','TikTok'],'個人化諮詢',
    '玄關，小C 蹲著看鞋櫃，叭噗站在旁邊',
    [('0-3秒 Hook','小C 蹲在鞋櫃前，苦惱：我的鞋子比他的格子還多。叭噗站著：對，你的那格我放不進去。',''),
     ('12-25秒','叭噗：我說沒差，放吧。然後我的拖鞋就擺在外面了。小C 驚訝：你沒有跟我說過這件事。叭噗：說了幹嘛。藏鏡人：哦不...這個細節有點溫...',''),
     ('40-52秒','小C：鞋子這件事，我一直以為是我贏了，然後才發現，是他讓我的。',''),
     ('52-60秒 CTA','叭噗：你們家誰佔了誰的位置？','')])

b02_11 = b2(11,'我問他愛不愛我，他說你問這個幹嘛','自嘲反差派',['IG Reels','TikTok'],'個人化諮詢',
    '沙發，小C靠在叭噗旁邊，傍晚氣氛',
    [('0-3秒 Hook','小C 突然：你愛不愛我？叭噗沒有停下手上的事：你問這個幹嘛。',''),
     ('12-25秒','小C：他的意思是——你知道嗎，這個問題你幹嘛問，你不知道答案嗎。藏鏡人：哈哈哈哈等等這個說法我要傳給另一半看！',''),
     ('25-40秒','叭噗放下東西，看她：你問這個，是沒安全感，還是想讓我說出來？小C 考慮一下：想讓你說出來。叭噗嘆口氣，語氣認真：愛。',''),
     ('52-60秒 CTA','小C：你的另一半是主動說，還是要問才說？底下說說。','')])

b02_12 = b2(12,'拆解：為什麼長情的人都有一個共同點','拆解派',['Threads','IG Reels'],'個人化諮詢',
    '簡單場景，兩人對鏡頭，像在做分析',
    [('0-3秒 Hook','叭噗：長情不是天生的，是做到了一件事。',''),
     ('12-25秒','叭噗：不是不吵架。不是一直有激情。是：他不好的時候，你還是想留下來。藏鏡人：哦...這個好準...',''),
     ('25-40秒','小C：長情靠的是那個難。不是甜蜜，是決定。',''),
     ('52-60秒 CTA','小C：你跟另一半有這個決定嗎？','')])

b02_13 = b2(13,'拆解：為什麼我們不說「沒關係」','拆解派',['Threads','IG Reels'],'個人化諮詢',
    '兩人坐著，像在聊天',
    [('0-3秒 Hook','小C：我們不說沒關係。說了反而麻煩。',''),
     ('12-25秒','小C：沒關係說完，三天後我們在吵同一件事。有關係的話，不如當下說。藏鏡人：不是我！絕對不是我！（是我）',''),
     ('25-40秒','叭噗：我們後來的規定是，有關係就說，說完才能說沒關係。順序不能反。',''),
     ('52-60秒 CTA','叭噗：你跟另一半說沒關係的次數多嗎？','')])

b02_14 = b2(14,'他帶我第一次去他朋友家','家人朋友模擬派',['IG Reels','FB Reels'],'個人化諮詢',
    '兩人回憶式對話',
    [('0-3秒 Hook','小C：他帶我去他朋友家，是交往之後一段時間，那一次，我好緊張。',''),
     ('3-12秒','叭噗：她出門前換了三套衣服。小C 白眼：我沒有，是兩套。',''),
     ('25-40秒','叭噗：她出去之後，她比我想的放得開。他們開她玩笑，她直接回嗆。小C 笑：因為他們說的，我都有跟叭噗確認過了。',''),
     ('52-60秒 CTA','叭噗：你第一次見另一半的朋友緊張嗎？','')])

b02_15 = b2(15,'他的朋友叫我嫂子，那天我哭了','家人朋友模擬派',['IG Reels','小紅書'],'個人化諮詢',
    '小C 對鏡頭，叭噗在旁邊聽',
    [('0-3秒 Hook','小C 認真：他朋友第一次叫我嫂子，我那天哭了。',''),
     ('12-25秒','小C：喊了那一聲，我覺得我是真的成為他的人了。藏鏡人：哦不...這個太有感了...有沒有人跟我一樣...',''),
     ('25-40秒','叭噗從旁邊說：我跟他們說，她很好，好好對她。他們就叫嫂子了。小C 看他：你跟他們說什麼？叭噗語氣很自然：就這樣。',''),
     ('52-60秒 CTA','小C：存起來，傳給讓你哭過的那個人。','')])

b02_16 = b2(16,'19年只有一個發現','直球情侶版',['IG Reels','FB Reels'],'個人化諮詢',
    '兩人坐著，輕鬆狀態',
    [('0-3秒 Hook','叭噗：19年，我只有一個發現。',''),
     ('12-25秒','叭噗：不是感情需要什麼秘訣，就是一件事。你願意繼續認識他，不是你認識了才愛他，是你愛他才繼續認識。藏鏡人：這個說法...我要消化一下...',''),
     ('52-60秒 CTA','小C：你還在認識你的另一半嗎？','')])

b02_17 = b2(17,'做早餐這件事','直球情侶版',['IG Reels','FB Reels'],'個人化諮詢',
    '廚房，早上，叭噗在做東西，小C還沒起床狀態',
    [('0-3秒 Hook','叭噗在廚房弄東西：她不起來，我就自己做。',''),
     ('12-25秒','叭噗：我不是每天都做。但如果我先醒，就弄一下。不是什麼大事，就是習慣了。藏鏡人：這個畫面好暖...我也想要...',''),
     ('25-40秒','小C：他做的不一定好吃，但他做，比好不好吃更重要。',''),
     ('52-60秒 CTA','叭噗：你跟另一半的早晨是什麼樣子？','')])

b02_18 = b2(18,'開瓶蓋那件小事','直球情侶版',['IG Reels','Threads'],'純雞湯（無硬 CTA）',
    '廚房或餐桌，簡單日常',
    [('0-3秒 Hook','小C：我知道他愛我，是因為一個瓶蓋。',''),
     ('12-25秒','小C：他每次倒飲料，都先幫我開瓶蓋，再開他自己的。他說，就這樣，你的先。叭噗補一句：你的先開比較快涼。小C：我後來查過，根本沒差。藏鏡人：哈哈哈他找了一個理由但理由是假的！！',''),
     ('40-52秒','小C 輕聲：愛不是說的，就是你先開我的那個瓶蓋。是那個先，是習慣了把你放在前面。',''),
     ('52-60秒','（無硬 CTA）你也有那個瓶蓋嗎','')])

b02_19 = b2(19,'第一次帶他回東港','人間觀察派',['IG Reels','小紅書'],'個人化諮詢',
    '旅程回憶，室內對談',
    [('0-3秒 Hook','小C：第一次帶他回我家，他說了一句話，我現在還記得。',''),
     ('12-25秒','叭噗：她家附近的魚市場，早上五點就很多人。我跟她說，你從這裡來的，怪不得你聞魚不怕。她說：這叫做習慣，不叫怪。小C：我那時候心想，他在學我。藏鏡人：他在學她的東西好暖啊...',''),
     ('52-60秒 CTA','小C：你帶另一半回過你長大的地方嗎？','')])

b02_20 = b2(20,'我不懂他的音樂，但我記得歌詞','人間觀察派',['IG Reels','Threads'],'個人化諮詢',
    '家中或車上，音樂播著',
    [('0-3秒 Hook','小C：他聽的音樂我有一半聽不懂，但他喜歡的，我都記得歌詞。',''),
     ('12-25秒','小C：我不一定喜歡那種音樂，但他喜歡，我就記住了。那是他的一部分，我不想錯過。藏鏡人：我要傳給我另一半看！！他從來不記我喜歡什麼！！',''),
     ('52-60秒 CTA','叭噗：你記得另一半喜歡的歌嗎？傳給他看。','')])

print('第02批 articles built OK')

# ============================================================
# 第 03 批 articles (new 13 parts)
# ============================================================
b03_01 = sc_article(101,'他帶看一整天，進門第一件事','故事戲劇派',['IG Reels','FB Reels'],'個人化諮詢',
    '家中客廳或玄關，叭噗剛開門進來，小C 在客廳，晚上室內燈光，真實生活感',
    [('0-3秒 Hook','叭噗（推門進來，扶著門）：累死了。字幕：他帶看一整天，進門第一句',''),
     ('3-12秒','叭噗：今天帶六組，全部說要考慮。字幕：六組，全考慮',''),
     ('12-25秒','小C（從廚房探頭）：我有留飯。先去換衣服。字幕：留了飯，催他洗。藏鏡人：19 年，她看懂了他的累⋯⋯',''),
     ('25-40秒','叭噗：你怎麼知道我想先吃飯？小C：你每次累到不行才說累。字幕：每次累到不行才說',''),
     ('40-52秒','（小C 把飯推過去，兩人沒再說話）字幕：一眼看出他累到什麼程度',''),
     ('52-60秒 CTA','叭噗（對鏡頭）：你記住另一半的哪個習慣？底下說說。','')],
    caption='帶看六組，全說考慮。他回來推門進來，第一句「累死了」。我沒說加油，我去把飯拿出來。19 年——他的累，不用他說我就知道了。你記住另一半的哪個習慣？底下說說',
    platform_chip='IG Reels / FB Reels', po_time='IG 週六 10PM',
    hashtag=['#情侶日常', '#長情', '#台灣情侶', '#高雄情侶', '#房仲老婆', '#真實情侶', '#19年'])

b03_02 = sc_article(102,'不過夜規定這件事，我們的答案','人間觀察派',['IG Reels','TikTok'],'個人化諮詢',
    '家中沙發，夜間場景，輕鬆對話感',
    [('0-3秒 Hook','小C（直視鏡頭）：我跟他在一起的時候沒有不過夜規定這件事。字幕：沒有不過夜規定',''),
     ('3-12秒','小C：對，一開始就這樣，從來沒訂過。字幕：從來沒訂過規定',''),
     ('12-25秒','叭噗：有人非常需要不過夜規定。有人根本不需要。小C：對，我是那種，訂了規定更焦慮的人。字幕：訂了規定反而焦慮',''),
     ('25-40秒','叭噗：差在哪？我覺得差在你對那個人有沒有底氣。字幕：差在有沒有底氣。藏鏡人：靠的不是規定，是底氣——這個說法！',''),
     ('40-52秒','小C：有底氣，就不需要規定。字幕：有底氣就夠了',''),
     ('52-60秒 CTA','小C：你是規定派還是自然派？轉給另一半，看他怎麼回答。','')],
    caption='我們沒有不過夜規定。19 年，從來沒訂過。有人說這樣不安全——但我發現，訂了規定反而更焦慮。有底氣，就不需要規定。你是規定派還是自然派？轉給另一半看看他怎麼說',
    platform_chip='IG Reels / TikTok', po_time='IG 週六 10PM',
    hashtag=['#情侶日常', '#感情', '#長期感情', '#台灣情侶', '#愛情觀', '#真實情侶'])

b03_04_card = sc_article(104,'【圖卡部】19 年了，你們怎麼不越來越陌生？','圖卡部',['IG Reels','FB Reels'],'圖卡部（留言不陌生取圖卡）',
    '兩人同框，室內，叭噗和小C 對鏡頭說話，認真表情',
    [('0-3秒 Hook','叭噗（對鏡頭）：19 年，常有人問——你們不會越來越陌生嗎？字幕：19 年，不怕陌生？藏鏡人：19 年耶——真的不會嗎？！',''),
     ('3-12秒','小C：老實說，這是長期感情裡最真實的問題。字幕：這是長期感情最真實的問題',''),
     ('12-25秒','叭噗：我們也沒有答案說我們「從來不陌生」——我們中間有段時間，兩個人都像在自己的世界裡。字幕：中間也有那段時間',''),
     ('25-40秒','小C：但我們做了幾件事，讓那個「各自在自己世界」不變成陌生。叭噗：想知道是什麼嗎？字幕：讓各自世界不變陌生的方法。藏鏡人：我要知道！！',''),
     ('40-52秒','叭噗：不過，這件事我不適合在這裡全講。因為每對的狀況都不一樣。字幕：每對的狀況都不同',''),
     ('52-60秒 CTA','叭噗：底下留言「不陌生」，我把我們做的幾件事私訊給你。不用怕，問問不用錢。','')],
    img='../bappu-batch03-fishing-card.png',
    caption='19 年，常有人問：不會越來越陌生嗎？老實說，我們中間也有那段時間。但我們做了幾件事——讓「各自的世界」不變成陌生。留言「不陌生」，我私訊給你',
    platform_chip='IG Reels / FB Reels', po_time='IG 週六 10PM',
    hashtag=['#長期感情', '#情侶日常', '#長情', '#台灣情侶', '#19年', '#感情維持'])

b03_07 = sc_article(107,'旅遊這件事，我們從來沒有完全意見一致','自嘲反差派',['IG Reels','TikTok'],'個人化諮詢',
    '兩人同框，底片相機畫面或家中，輕鬆表情',
    [('0-3秒 Hook','叭噗：我們旅遊，19 年沒有一次完全一致過。字幕：旅遊計畫從來沒全一致。藏鏡人：哈哈哈哈哈這不就是我們！！',''),
     ('3-12秒','小C：我要曬太陽，他要走路。叭噗：我要走路，她要待在旁邊的咖啡廳。小C：對。字幕：他走路，她進咖啡廳',''),
     ('12-25秒','叭噗：去北海道，我拍兩小時，她在民宿看書。晚餐一起吃。小C：完美。字幕：各玩各的，晚餐聚',''),
     ('25-40秒','叭噗：各自玩，再一起吃飯，比全黏在一起更好玩。字幕：各自玩，聚一起，更有趣。藏鏡人：這個模式聽起來很解放⋯⋯我要跟我另一半講！',''),
     ('40-52秒','小C：19 年了，我試過帶他去咖啡廳三次。三次他都出去繞一圈再回來找我。叭噗（聳肩）：確實。字幕：帶他去咖啡廳三次，三次都跑掉',''),
     ('52-60秒 CTA','小C：你跟另一半旅遊也是各玩各的嗎？底下說說。','')],
    caption='我們旅遊 19 年，從來沒一次完全一致。他要走路，我要進咖啡廳。北海道——他拍兩小時，我在民宿看書，晚餐一起吃。各自玩再聚，比全程黏在一起更好玩。你們也各玩各的嗎？底下說說',
    platform_chip='IG Reels / TikTok', po_time='IG 週六 10PM',
    hashtag=['#情侶旅遊', '#情侶日常', '#台灣情侶', '#長情', '#旅遊情侶', '#底片旅遊'])

b03_08 = sc_article(108,'有一種人，19 年不分的原因你想不到','拆解派',['IG Reels','FB Reels'],'個人化諮詢',
    '兩人同框，室內，認真說話的氛圍，小C 為主說話者',
    [('0-3秒 Hook','小C：19 年不分的原因，你猜不到。字幕：他為什麼一直都在。藏鏡人：什麼原因？！',''),
     ('3-12秒','小C：不是相似，是相反。字幕：其實是互補，不是匹配',''),
     ('12-25秒','叭噗：我出去她在家。我安靜她說話。各做各的。小C：晚餐一定一起吃。字幕：各自的世界，晚餐聚',''),
     ('25-40秒','小C：有人說要非常契合——其實是互補。你一方，他另一方，加起來才完整。字幕：互補，不是完全合拍。藏鏡人：互補才完整——這個說法我沒想過！',''),
     ('40-52秒','叭噗：我們也是試了很久才知道的。字幕：試了很久才知道',''),
     ('52-60秒 CTA','小C：你跟另一半是哪種搭法？底下說說。','')],
    caption='19 年不分的原因，很多人猜不到。不是因為相似——是因為相反。我出去他在家，我說話他安靜，各做各的。但晚餐一定一起吃。互補才完整，不是完全合拍才長久。你們是哪種搭法？底下說',
    platform_chip='IG Reels / FB Reels', po_time='IG 週六 10PM',
    hashtag=['#長期感情', '#情侶日常', '#台灣情侶', '#感情觀', '#長情', '#互補情侶'])

b03_09 = sc_article(109,'他說他不在乎，但他記了 4 年','故事戲劇派',['IG Reels','TikTok'],'個人化諮詢',
    '兩人同框，家中或旅遊畫面，叭噗稍微不好意思的表情，小C 笑',
    [('0-3秒 Hook','小C：他說不在乎。記了 4 年。字幕：嘴上不在乎，心裡記著。藏鏡人：什麼事？！',''),
     ('3-12秒','小C：我說想去沖繩，他說現在沒辦法。我說沒關係。就結束了。字幕：沒在一起時說的話',''),
     ('12-25秒','小C：4 年後他說，你不是想去沖繩？我說對。他說那規劃一下。就去了。字幕：4 年後才提起，還真的去',''),
     ('25-40秒','叭噗：只是記在腦袋裡。沒什麼大事。小C：你說不在乎。記了 4 年。字幕：說不在乎，真的記著。藏鏡人：這就是長情⋯⋯他的愛在行動裡⋯⋯',''),
     ('40-52秒','小C：他常這樣。說不在乎，記著，哪天就做。字幕：他的愛，在行動裡',''),
     ('52-60秒 CTA','小C：你另一半有這樣的事嗎？存起來傳給他看。','')],
    caption='他說他不在乎那件事。結果記了 4 年。4 年後突然說——那個沖繩，規劃一下。就去了。他的愛不說出口，但它在那邊。你另一半也有這樣的事嗎？存起來傳給他',
    platform_chip='IG Reels / TikTok', po_time='IG 週六 10PM',
    hashtag=['#情侶日常', '#長情', '#台灣情侶', '#感情', '#19年', '#真實情侶', '#旅遊'])

b03_10 = sc_article(110,'我嫁給他之前不知道的一件事','人間觀察派',['IG Reels','FB Reels'],'個人化諮詢',
    '兩人同框，家中，小C 說話，叭噗在旁邊作為「被揭露者」',
    [('0-3秒 Hook','小C：嫁給他之前，有件事我不知道。字幕：婚前沒發現的事。藏鏡人：什麼事？！',''),
     ('3-12秒','小C：他吃得很慢。叭噗：我在享受。小C：吃飯他吃第三口，我快吃完。字幕：他超級慢，我卡著',''),
     ('12-25秒','字幕：不會吵？小C：一開始會等急。後來我帶書，他吃完我們再走。字幕：學著等，現在沒問題',''),
     ('25-40秒','叭噗：她也有我不知道的。小C：什麼？叭噗：妳睡前一定要聊天。小C：對啦。字幕：她睡前必聊天。藏鏡人：互相揭露⋯⋯婚前不知道，婚後接受⋯⋯這才是生活！',''),
     ('40-52秒','小C：婚前不知道，婚後就接受。字幕：發現怪癖，學著包容',''),
     ('52-60秒 CTA','叭噗：你嫁給他（或娶了她）之後，發現什麼你之前不知道的？底下說說。','')],
    caption='婚前沒發現的事——他吃得超慢。他吃第三口，我快吃完了。一開始會等急，後來我帶書去，他吃完我們再走。婚前不知道，婚後學著接受——這才是生活。你婚後發現什麼？底下說說',
    platform_chip='IG Reels / FB Reels', po_time='IG 週六 10PM',
    hashtag=['#情侶日常', '#夫妻日常', '#台灣情侶', '#長情', '#已婚日常', '#真實情侶'])

b03_11 = sc_article(111,'「我愛你」這三個字，我們好像很少說','人間觀察派',['IG Reels','Threads'],'個人化諮詢',
    '兩人同框，家中，認真但輕鬆的氛圍',
    [('0-3秒 Hook','小C：19 年，我們好像很少說「我愛你」。字幕：19 年沒說過幾次。藏鏡人：不浪漫欸——',''),
     ('3-12秒','小C：上週他幫我換水管。漏水很久。字幕：他去換了漏了很久的水管',''),
     ('12-25秒','叭噗：我愛你三個字讓我覺得假。做不就好。小C：他邏輯這樣。我一開始也覺得少了什麼。字幕：他覺得三個字作假，說還不如做',''),
     ('25-40秒','小C：後來我想，如果天天說愛你，水管漏三個月不理——我選哪種？字幕：說愛你 vs 換水管，我要哪種。藏鏡人：毒但真！！！',''),
     ('40-52秒','小C：沒說幾次，但水管換了，燈泡換了，我出門他說等一下。夠了。字幕：他的愛在細節裡',''),
     ('52-60秒 CTA','叭噗：你另一半是話多派還是動作派？底下說說。','')],
    caption='19 年，「我愛你」說得很少。但上週他幫我換了漏了很久的水管。天天說愛你、水管漏三個月不理，和不說但換水管——我要哪種？我知道我要哪種。你另一半是話多派還是動作派？底下說說',
    platform_chip='IG Reels / Threads', po_time='IG 週六 10PM',
    hashtag=['#情侶日常', '#台灣情侶', '#長情', '#感情觀', '#長期感情', '#真實愛情'])

b03_12 = sc_article(112,'某一年我突然明白，陪伴的意思','直球情侶版',['IG Reels','Threads'],'純雞湯（無硬 CTA）',
    '兩人同框，底片相機質感畫面或家中，氣氛溫暖',
    [('0-3秒 Hook','小C（輕聲，對鏡頭）：某一年，我才明白陪伴的意思。字幕：那一年我才懂什麼是陪伴。藏鏡人：說下去⋯⋯',''),
     ('3-12秒','小C：不是每秒在一起。是你煩惱時，有個人可以講。字幕：陪伴就是有人聽你',''),
     ('12-25秒','叭噗：我們不是天天聊。各自忙，各自靜。但我知道她在。字幕：她在，就夠了',''),
     ('25-40秒','小C：陪伴不是熱鬧。是最安靜的時候，他還在。字幕：陪伴就是這個。藏鏡人：最溫柔的⋯⋯',''),
     ('40-52秒','叭噗：19 年，幾次我以為撐不住——回頭看，她都在。字幕：他最撐不住的時候，她都在',''),
     ('52-60秒 CTA','小C（輕聲）：你呢？字幕：你的陪伴呢','')],
    caption='陪伴不是每秒在一起。是你最煩惱的時候，有個人在。不用說話，不用給答案——就是在。19 年，幾次他以為撐不住，回頭看，我都在。',
    platform_chip='IG Reels / Threads', po_time='IG 週六 10PM',
    hashtag=['#情侶日常', '#長情', '#台灣情侶', '#陪伴', '#感情', '#純雞湯'])

b03_13 = sc_article(113,'19 年，我沒有為他改變，但我有這個','直球情侶版',['IG Reels','FB Reels'],'個人化諮詢',
    '兩人同框，家中或旅遊底片質感畫面，小C 說話為主',
    [('0-3秒 Hook','小C：19 年，我沒為他改變。字幕：我還是我。藏鏡人：沒改變？！',''),
     ('3-12秒','小C：沒變成另一個人。但有一件事不一樣了。字幕：一個地方有了變化',''),
     ('12-25秒','小C：我以前不知道怎麼說難過。悶著。他問我還好嗎，我說還好，他說我知道你不好。字幕：他看穿我的「還好」',''),
     ('25-40秒','叭噗：後來她會講了。小C：對。不是為了他——說出來我自己比較好。字幕：為了我自己。藏鏡人：好感情讓你更像自己，不是讓你消失——這個很重要。',''),
     ('40-52秒','小C：好感情讓你更像自己。不是讓你消失。字幕：更像自己',''),
     ('52-60秒 CTA','小C：你有一個讓你更像自己的另一半嗎？','')],
    caption='19 年，我沒為他改變。還是內向。還是喜歡一個人。還是話少。但有一件事不一樣了——我學會說「我現在不好」。不是為了他。為了自己。好感情讓你更像自己。不是讓你消失。',
    platform_chip='IG Reels / FB Reels', po_time='IG 週六 10PM',
    hashtag=['#情侶日常', '#長情', '#台灣情侶', '#感情', '#長期感情', '#真實情侶'])

print('第03批 articles built OK')

# ============================================================
# Threads 脆文 第03批
# ============================================================
THREADS_03 = [
    ('T01', '叭噗語氣',
     '帶看帶了一整天。\n六組，全說要考慮。\n進門的時候她沒說加油也沒說辛苦。\n就說，我有留飯，先去換衣服。\n\n19 年了。\n她知道我那時候要的不是加油。\n是飯。\n\n你另一半讀得懂你的累嗎？',
     ''),
    ('T02', '小C 語氣',
     '有人說感情要有不過夜規定才穩。\n我沒覺得這說得通。\n\n我不是反對規定。\n我是覺得，如果你需要規定保護你，\n那你在保護的其實是焦慮，不是感情。\n\n我跟他 19 年沒有規定。\n因為有底氣，就不需要規定守著。\n\n你是規定派還是底氣派？',
     ''),
    ('T03', '小C 語氣',
     '我跟他冷戰，通常是我先開口。\n\n不是認錯。\n就問——你吃飯了嗎。\n\n就這樣。\n沒有跪地認錯，沒有長篇大論。\n回到正常，就是和好。\n\n19 年，這最實用。\n冷戰從不超過兩天。',
     ''),
    ('T04', '兩人語氣',
     '很多人問我們——\n19 年，不怕越來越陌生嗎？\n\n老實說，我們有過那段時間。\n各自在自己的世界，\n對方有點遠。\n\n但我們做了幾件事，\n讓「各自世界」沒變成陌生。\n\n想知道是什麼？\nIG DM 我，跟你說。',
     ''),
    ('T05', '小C 語氣',
     '我去北海道。\n他拍照兩小時。\n我在民宿看書兩小時。\n晚餐一起吃。\n\n朋友說，不膩？\n\n我說，各自玩，再聚一起，\n比全黏著更好玩。\n\n不是每對都適合。\n但你是這種人的話，你懂。',
     ''),
    ('T06', '小C 語氣',
     '19 年。\n他不常說「我愛你」。\n\n上週水管漏水，\n他去換了。\n\n燈泡壞，他換。\n我說出門，他說等一下。\n\n如果要選——\n天天說愛你但水管漏三個月，\n或不說但當天換，\n我選哪個？\n\n我選換水管的那個。',
     ''),
    ('T07', '小C 語氣',
     '19 年，我沒為他改變。\n\n還是內向。\n還是喜歡一個人。\n還是話少。\n\n但有一件事不一樣了——\n我學會說「我現在不好」。\n\n不是為了他。\n為了自己。\n說出來，我自己比較好。\n\n好感情讓你更像自己。\n不是讓你消失。',
     ''),
]

def thread_bappu(tid, label, body, hashtag):
    safe = body.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return (
        '<div class="thread-card">\n'
        '<div class="thread-meta"><span class="thread-id">' + tid + '</span><span class="thread-label">' + label + '</span></div>\n'
        '<div class="thread-text">' + safe + '</div>\n' +
        (('<div class="thread-hash">' + hashtag + '</div>\n') if hashtag else '') +
        '<button class="copy-btn" onclick="copyThread(this)">複製脆文</button>\n'
        '</div>'
    )

threads_section = (
    '\n<!-- 脆文 Threads -->\n'
    '<div class="gp collapsed" data-g="threads">\n'
    '<div class="gh" onclick="toggleGroup(this.parentElement)">\n'
    '  <div class="gt">\n'
    '    <span class="gc">T</span>\n'
    '    <span class="gn">脆文 Threads</span>\n'
    '    <span class="gx">第 03 批 · 7 篇</span>\n'
    '  </div>\n'
    '  <span class="gy">▼</span>\n'
    '</div>\n'
    '<div class="gb">\n'
    '<div class="threads-grid">\n' +
    '\n'.join(thread_bappu(t[0], t[1], t[2], t[3]) for t in THREADS_03) +
    '\n</div>\n</div>\n</div>'
)

print('Threads section built OK')

# ============================================================
# Assemble v2 groups (cross-batch merge)
# ============================================================

# 故事戲劇派（02批 4部 + 03批 3部）
gA = gp_group_v2('A', '故事戲劇派', [b02_01, b02_03, b02_04, b02_05, b03_01, b03_09, b03_10])

# 人間觀察派（02批 6部 + 03批 3部）
gB = gp_group_v2('B', '人間觀察派', [b02_02, b02_07, b02_08, b02_09, b02_19, b02_20, b03_02, b03_11])

# 拆解派（02批 2部 + 03批 1部）
gD = gp_group_v2('D', '拆解派', [b02_12, b02_13, b03_08])

# 自嘲反差派（02批 2部 + 03批 1部）
gF = gp_group_v2('F', '自嘲反差派', [b02_10, b02_11, b03_07])

# 家人朋友模擬派（02批 2部）
gC = gp_group_v2('C', '家人朋友模擬派', [b02_14, b02_15])

# 直球情侶版 / 純雞湯（02批 4部 + 03批 2部）
gG = gp_group_v2('G', '直球情侶版 / 純雞湯', [b02_16, b02_17, b02_18, b03_12, b03_13])

# 圖卡部（02批 1部 + 03批 1部）
gH = gp_group_v2('H', '圖卡部', [b02_06, b03_04_card])

all_groups = '\n'.join([gA, gB, gD, gF, gC, gG, gH, threads_section])

# ============================================================
# Write to bappu-cc/index.html
# ============================================================
bappu_path = os.path.join(LIB, 'bappu-cc', 'index.html')
with open(bappu_path, 'r', encoding='utf-8') as f:
    c = f.read()

# Find first gp div (handle both 'gp"' and 'gp collapsed"')
first_gp = c.find('<div class="gp"')
if first_gp < 0:
    first_gp = c.find('<div class="gp ')
main_wrap_close = c.find('</div><!-- .main-wrap -->')
print(f'bappu: first_gp={first_gp}, main_wrap_close={main_wrap_close}')

nc = c[:first_gp] + all_groups + '\n\n' + c[main_wrap_close:]

# ---- V2 CSS patch ----
V2_CSS_MARKER = '/* ========== V2 GROUP COLLAPSED + copyScript (build_bappu.py v2) ========== */'
V2_CSS = """
/* ========== V2 GROUP COLLAPSED + copyScript (build_bappu.py v2) ========== */
.gp.collapsed > .gb{display:none !important}
.gp.collapsed > div.threads-grid{display:none !important}
.group.collapsed > .threads-grid{display:none !important}
.gy{transition:transform .2s;display:inline-block;}
.gp.collapsed .gy{transform:rotate(-90deg);}
.card-meta-extra{font-size:11px;margin:4px 0;display:flex;gap:8px;flex-wrap:wrap;}
.platform{font-size:11px;background:rgba(224,64,251,.12);padding:2px 7px;border-radius:4px;font-weight:600;color:#c800e0;}
.po-time{font-size:11px;opacity:.7;}
.hashtag-pool{display:flex;flex-wrap:wrap;gap:5px;margin:8px 0 4px;}
.hashtag{background:rgba(0,229,255,.1);color:#00b8cc;padding:2px 8px;border-radius:12px;font-size:11px;border:1px solid rgba(0,229,255,.3);}
.sc-img img.card-thumb{max-width:320px;width:100%;height:auto;object-fit:contain;border-radius:6px;cursor:zoom-in;display:block;margin:8px 0;border:1px solid rgba(224,64,251,.4);}
@media (max-width:640px){.sc-img img.card-thumb{max-width:100%;}}
.caption-preview{margin:10px 0 6px;padding:10px 14px;background:rgba(10,0,18,0.6);border-left:3px solid var(--magenta);border-radius:4px;font-size:13px;line-height:1.6;color:var(--text);}
.caption-preview-label{font-size:11px;color:var(--magenta);font-weight:600;margin-bottom:4px;letter-spacing:.04em;}
.caption-preview-text{color:var(--text);white-space:pre-wrap;}
.caption-preview-hash{margin-top:6px;font-size:12px;color:var(--cyan);}
.download-btn{
  display:inline-flex;align-items:center;gap:5px;
  padding:6px 14px;margin:6px 0;
  font-size:12px;font-weight:500;color:white;
  background:linear-gradient(135deg,#E040FB,#00E5FF);
  border:none;border-radius:999px;text-decoration:none;cursor:pointer;
  transition:opacity .2s;
}
.download-btn:hover{opacity:.85;}
.copy-btn{
  display:inline-flex;align-items:center;gap:5px;
  padding:6px 14px;margin:8px 0;
  font-size:12px;font-weight:500;color:white;
  background:linear-gradient(135deg,#E040FB,#00E5FF);
  border:none;border-radius:999px;cursor:pointer;
  transition:opacity .2s;
}
.copy-btn:hover{opacity:.85;}
.copy-btn.copied{background:#5c8a5c;}
.threads-grid{display:grid;grid-template-columns:1fr;gap:14px;padding:8px 0;}
@media(min-width:720px){.threads-grid{grid-template-columns:1fr 1fr}}
.thread-card{background:rgba(255,255,255,.06);border:1px solid rgba(224,64,251,.3);border-radius:10px;padding:16px;}
.thread-meta{display:flex;gap:8px;margin-bottom:8px;align-items:center;}
.thread-id{font-weight:700;color:#E040FB;font-size:14px;}
.thread-label{font-size:11px;opacity:.6;background:rgba(255,255,255,.08);padding:2px 7px;border-radius:4px;}
.thread-text{font-size:13px;line-height:1.85;opacity:.85;white-space:pre-wrap;word-break:break-word;}
.thread-hash{margin-top:6px;font-size:11px;color:#00E5FF;font-weight:500;}
.lightbox-overlay{
  position:fixed;inset:0;background:rgba(0,0,0,.9);display:none;
  align-items:center;justify-content:center;z-index:9999;padding:24px;cursor:zoom-out;
}
.lightbox-overlay.active{display:flex}
.lightbox-overlay img{max-width:min(90vw,900px);max-height:90vh;border-radius:4px;}
.lightbox-close{position:absolute;top:20px;right:24px;background:none;border:none;color:#fff;font-size:32px;cursor:pointer;}
"""

if V2_CSS_MARKER not in nc:
    style_end = nc.find('</style>')
    if style_end >= 0:
        nc = nc[:style_end] + V2_CSS + nc[style_end:]
        print('V2 CSS patch injected')

# ---- V2 JS patch ----
V2_JS_MARKER = '// ===== V2 JS: toggleGroup + copyScript + copyThread + lightbox (build_bappu.py v2) ====='
V2_JS = r"""// ===== V2 JS: toggleGroup + copyScript + copyThread + lightbox (build_bappu.py v2) =====
function toggleGroup(grp){grp.classList.toggle('op');}
function copyScript(btn){
  var art=btn.closest('article.sc');if(!art) return;
  var cap=art.dataset.caption;var hRaw=art.dataset.hashtags||'';var h=hRaw.trim()?hRaw.trim():'';
  if(!cap){
    var origDisabled = btn.textContent;
    btn.textContent = '本批無 caption';
    btn.style.opacity = '.5';
    setTimeout(function(){ btn.textContent = origDisabled; btn.style.opacity = ''; }, 2000);
    return;
  }
  var text=cap;if(h) text=text+'\n\n'+h;
  var orig=btn.textContent;
  function doCopy(t){
    if(navigator.clipboard&&navigator.clipboard.writeText) return navigator.clipboard.writeText(t);
    var ta=document.createElement('textarea');ta.value=t;ta.style.cssText='position:fixed;top:-9999px;left:-9999px;opacity:0';
    document.body.appendChild(ta);ta.focus();ta.select();try{document.execCommand('copy');}catch(e){}document.body.removeChild(ta);return Promise.resolve();
  }
  doCopy(text).then(function(){btn.textContent='已複製 ✓';btn.classList.add('copied');setTimeout(function(){btn.textContent=orig;btn.classList.remove('copied');},2000);}).catch(function(){btn.textContent='複製失敗';setTimeout(function(){btn.textContent=orig;},2000);});
}
function copyThread(btn){
  var card=btn.closest('.thread-card');if(!card) return;
  var tEl=card.querySelector('.thread-text');var hEl=card.querySelector('.thread-hash');
  var text=(tEl?tEl.textContent.trim():'')+(hEl?'\n\n'+hEl.textContent.trim():'');
  var orig=btn.textContent;
  function doCopyThread(t){
    if(navigator.clipboard&&navigator.clipboard.writeText) return navigator.clipboard.writeText(t);
    var ta=document.createElement('textarea');ta.value=t;ta.style.cssText='position:fixed;top:-9999px;left:-9999px;opacity:0';
    document.body.appendChild(ta);ta.focus();ta.select();try{document.execCommand('copy');}catch(e){}document.body.removeChild(ta);return Promise.resolve();
  }
  doCopyThread(text).then(function(){btn.textContent='已複製 ✓';btn.classList.add('copied');setTimeout(function(){btn.textContent='複製脆文';btn.classList.remove('copied');},2000);}).catch(function(){btn.textContent='複製失敗';setTimeout(function(){btn.textContent='複製脆文';},2000);});
}
function openLightbox(img){
  var ov=document.getElementById('lightboxOverlay'),lbI=document.getElementById('lightboxImg');
  if(!ov||!lbI) return;lbI.src=img.src;ov.classList.add('active');
}
// init: all groups collapsed
(function(){
  document.querySelectorAll('.gp').forEach(function(g){g.classList.add('collapsed');});
})();
// lightbox close
(function(){
  var ov=document.getElementById('lightboxOverlay');var cls=document.getElementById('lightboxClose');
  if(!ov) return;
  if(cls) cls.addEventListener('click',function(){ov.classList.remove('active');document.getElementById('lightboxImg').src='';});
  ov.addEventListener('click',function(e){if(e.target===ov){ov.classList.remove('active');document.getElementById('lightboxImg').src='';}});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&ov.classList.contains('active')){ov.classList.remove('active');document.getElementById('lightboxImg').src='';}});
})();
window.toggleGroup=toggleGroup;window.copyScript=copyScript;window.copyThread=copyThread;window.openLightbox=openLightbox;
// v2.1: caption preview
(function v21CaptionPreview(){
  document.querySelectorAll('article.sc[data-caption]').forEach(function(a){
    if(a.querySelector('.caption-preview'))return;
    var cap=a.dataset.caption||'';var hashtags=a.dataset.hashtags||'';
    var btn=a.querySelector('.copy-btn');if(!btn||!cap)return;
    var p=document.createElement('div');p.className='caption-preview';
    p.innerHTML='<div class="caption-preview-label">📋 將複製到剪貼簿（影片 PO 文案 + hashtag）：</div>'+
                '<div class="caption-preview-text">'+cap.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</div>'+
                (hashtags?'<div class="caption-preview-hash">'+hashtags.replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</div>':'');
    btn.parentNode.insertBefore(p,btn);
  });
})();
"""

if V2_JS_MARKER not in nc:
    script_end = nc.rfind('</script>')
    if script_end >= 0:
        nc = nc[:script_end] + V2_JS + '\n' + nc[script_end:]
        print('V2 JS patch injected')

# lightbox overlay HTML if missing
if 'lightboxOverlay' not in nc:
    lb_html = (
        '\n<div class="lightbox-overlay" id="lightboxOverlay">'
        '<button class="lightbox-close" id="lightboxClose">×</button>'
        '<img id="lightboxImg" src="" alt="圖卡預覽">'
        '</div>'
    )
    nc = nc.replace('</body>', lb_html + '\n</body>')
    print('lightbox overlay injected')

with open(bappu_path, 'w', encoding='utf-8') as f:
    f.write(nc)
print('bappu-cc/index.html DONE:', len(nc), 'chars')

arts = re.findall(r'<article class="sc"', nc)
print('Total articles:', len(arts))
dl_count = len(re.findall(r'<a class="download-btn"', nc))
print(f'download-btn count: {dl_count}')
assert len(arts) >= 20, f'Expected >= 20 articles, got {len(arts)}'
assert dl_count >= 1, f'Expected >= 1 download-btn, got {dl_count}'
assert '圖卡部' in nc, 'Missing 圖卡部'
print('All assertions PASS')
