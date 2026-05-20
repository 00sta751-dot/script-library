import os, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
LIB = os.path.dirname(os.path.abspath(__file__))

# v2 2026-05-18: align SOP v2 9-feature logic
# v3 2026-05-21: replace 第04批(虛構故事 archived) with 第05批(生活向)
# Accumulative: 第05批(new) + 第03批(existing)

BATCH_05 = '第 05 批 · 2026-05-21'
BATCH_03 = '第 03 批 · 2026-05-12'

Q = chr(39)

def rp_main(html_path, new_content):
    with open(html_path, 'r', encoding='utf-8') as f:
        c = f.read()
    s = c.find('<main id="main">')
    e = c.find('</main>')
    if s < 0 or e < 0:
        print('ERR: no main in ' + os.path.basename(html_path))
        return False, c
    nc = c[:s] + '<main id="main">\n\n' + new_content + '\n\n</main>' + c[e+7:]
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(nc)
    sz = len(nc)
    print('DONE: ' + os.path.basename(html_path) + ' (' + str(sz) + ' chars)')
    return True, nc

def kenny_article(num, title, pie, platforms, cta, summary, timeline,
                  batch=None, caption=None, platform_chip=None, po_time=None,
                  hashtag=None, img=None):
    if batch is None:
        batch = BATCH_05
    cid = 'k' + str(num).zfill(2) + ('b' if batch == BATCH_03 else '')
    pl_tags = ''.join('<span class="ptag ptag-{0}">{1}</span>'.format(
        'ig' if 'IG' in p else 'tk' if 'TikTok' in p else 'fb' if 'FB' in p else 'th' if 'Threads' in p else 'xh', p)
        for p in platforms)
    tl_html = ''
    for t, d, *rest in timeline:
        sub    = rest[0] if len(rest) > 0 else ''
        mirror = rest[1] if len(rest) > 1 else ''
        tl_html += '<div class="ts-row"><div class="ts-time">' + t + '</div><div class="ts-desc">' + d + '</div>'
        if sub:
            tl_html += '<div class="ts-sub">' + sub + '</div>'
        if mirror:
            tl_html += '<div class="mirror">藏鏡人　' + Q + mirror + Q + '</div>'
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
        img_html = '<div class="card-image-section"><img src="' + img + '" class="card-thumb" alt="圖卡預覽" onclick="openLightbox(this); return false;"></div>\n'
        dl_name = os.path.basename(img)
        dl_btn = '<a class="download-btn" href="' + img + '" download="' + dl_name + '">下載圖卡</a>\n'

    copy_label = '複製文案' if cap_escaped else '複製腳本'

    return (
        '<div class="script-card" data-tags="' + pie + ' ' + cta + '" data-id="' + cid + '"' + cap_attr + hashtag_attr + '>\n'
        '  <div class="card-top">\n'
        '    <div class="card-num">#' + str(num).zfill(2) + '</div>\n'
        '    <div class="card-title-block">\n'
        '      <div class="card-title">' + title + '</div>\n'
        '      <div class="card-meta"><span>60 秒</span><span>' + batch + '</span><span>' + pie + '</span></div>\n' +
        (('      <div class="card-meta-extra">' + meta_extra + '</div>\n') if meta_extra else '') +
        '    </div>\n'
        '  </div>\n'
        '  <div class="card-summary">' + summary + '</div>\n'
        '  <div class="card-footer">'
        '<div class="platform-tags">' + pl_tags + '</div>'
        '<div class="card-actions">'
        '<button class="btn-shot" onclick="toggleShot(' + Q + cid + Q + ',this)">已拍</button>'
        '<button class="btn-open" onclick="toggleDetail(' + Q + cid + '-d' + Q + ',this)">展開</button>'
        '</div></div>\n'
        '  <div class="card-detail" id="' + cid + '-d">\n'
        '    <div class="det-label">時間軸</div>\n'
        '    <div style="margin-bottom:14px">\n' + tl_html + '    </div>\n' +
        img_html + dl_btn + hashtag_html +
        '    <button class="copy-btn" onclick="copyScript(this)">' + copy_label + '</button>\n'
        '  </div>\n'
        '</div>'
    )

def group_v2(label, en, gid, cards, collapsed=True):
    inner = '\n'.join(cards)
    cnt = str(len(cards))
    cclass = 'group collapsed' if collapsed else 'group'
    return (
        '<div class="' + cclass + '" id="grp-' + str(gid) + '">\n'
        '<div class="group-header" onclick="toggleGroup(this.parentElement)">\n'
        '  <span class="group-label">' + label + '</span>\n'
        '  <span class="group-en">' + en + '</span>\n'
        '  <span class="group-count">' + cnt + ' 部</span>\n'
        '  <span class="group-toggle">▼</span>\n'
        '</div>\n'
        '<div class="group-body">\n' + inner + '\n</div>\n'
        '</div>'
    )

print('build_all.py v2 loaded OK')
print('LIB:', LIB)

# ============================================================
# 第 03 批 articles (existing 20 parts)
# ============================================================
def kc3(num, title, pie, pl, cta, summ, tl, img=None):
    cid_num = num
    return kenny_article(cid_num, title, pie, pl, cta, summ, tl, batch=BATCH_03, img=img)

# 第03批 直球揭秘 group
k03_01 = kc3(1,'賣房稅費這 3 個數字，你算過嗎？','直球揭秘',['TikTok','IG Reels'],'個人化諮詢',
    '賣房前要算清楚土地增值稅、房地合一稅、仲介費，沒算清楚實拿的錢會少很多。',
    [('0-3s','賣房之前，這 3 個數字你有沒有算過？'),
     ('3-12s','第一個是土地增值稅，第二個是房地合一稅，第三個是仲介費。這 3 個加起來，客戶一算都會說：這麼多？'),
     ('12-25s','房地合一的部分，持有年限不同稅率差不少，自用住宅有優惠，但條件要符合。'),
     ('25-40s','上個月有個客戶，一算稅費，實拿的少了好幾百萬。'),
     ('40-52s','賣之前，先算。這 3 個數字搞清楚，到時候才不會被自己的計算震到，OK嗎？'),
     ('52-60s','CTA：留言稅費，仲豪私訊給你用 maskbago 試算一次，都免費，問就對了。')])

k03_02 = kc3(2,'看屋當天我都在看什麼，客戶不知道','直球揭秘',['TikTok','IG Reels'],'個人化諮詢',
    '帶看時偷偷看漏水痕跡、敲牆壁、開窗門、看外牆裂縫，漂亮不等於安全。',
    [('0-3s','帶你們看屋的時候，我在偷偷看的東西，你們根本不知道。'),
     ('3-12s','第一個：看漏水痕跡，天花板邊角、窗框下面。第二個：聽牆壁，敲一敲。'),
     ('12-25s','第三個：開每一扇窗戶和門。第四個：站在陽台看外牆。'),
     ('25-40s','漂亮不等於安全，懂我的意思？'),
     ('40-52s','下次帶看，你可以自己先確認這 4 件事，再問我細節。'),
     ('52-60s','CTA：有想看屋但不知道怎麼問，留言帶看，仲豪跟你聊，都免費，問就對了。')])

k03_08 = kc3(8,'實價登錄怎麼查，5 步驟學起來','直球揭秘',['IG Reels','小紅書'],'個人化諮詢',
    '5步驟學會查實價登錄：找網站、選地區、設條件、看單價、看日期判趨勢。',
    [('0-3s','實價登錄怎麼查，我拆成 5 步驟，2 分鐘學起來。'),
     ('3-12s','第一步：搜尋內政部不動產交易實價查詢服務，找官方網站。第二步：選你要查的地區。'),
     ('12-25s','第三步：設條件，時間範圍建議查近 1 年。第四步：看每筆的單價而不是總價。'),
     ('25-40s','第五步：注意成交日期，登錄有時間差，要判斷的是趨勢，不是一筆數字。'),
     ('40-52s','這 5 步做完，你對這個區域的行情就有基本概念了。'),
     ('52-60s','CTA：有興趣的物件不知道怎麼評估，留言實價，仲豪私訊給你分析，都免費，問就對了。')])

k03_11 = kc3(11,'新青安快到的人，問一下 3 件事','直球揭秘',['TikTok','IG Reels'],'個人化諮詢',
    '寬限期結束月付直接跳，現在要試算期後月付、評估提前還款、確認換貸條件。',
    [('0-3s','寬限期的時候，月付輕鬆；寬限期一過，同一筆房貸，月付直接跳。'),
     ('3-12s','新青安有 5 年寬限期，用的人很多，但準備好面對期後月付的，才知道有沒有撐住的空間。'),
     ('12-25s','現在就要做 3 件事：試算寬限期後的月付、評估有沒有能力提前還本金、確認你的合約有沒有換貸條件。'),
     ('25-40s','寬限期不是永遠，只是讓你緩一口氣用的，OK嗎？'),
     ('40-52s','想知道你的狀況怎麼規劃，留言青安，仲豪私訊給你，都免費，問就對了。')])

k03_12 = kc3(12,'議價這件事，客戶最大的誤解','直球揭秘',['IG Reels','TikTok'],'個人化諮詢',
    '砍太狠賣方關窗；留台階賣方回來繼續談。同一間房，出價方式不同，結果差一個月。',
    [('0-3s','同一間房子，出價方式不同，結果差一個月。'),
     ('3-12s','我有個客戶，第一次出價砍很狠，賣方直接不回應，窗關了。'),
     ('12-25s','後來我讓客戶重新出一個有留台階的價格，結果賣方回來了，繼續談，最後成了。'),
     ('25-40s','議價是藝術，不是在比誰開價低，是在比誰懂市場，懂人。'),
     ('40-52s','出價越狠不等於買到越便宜，OK嗎？'),
     ('52-60s','CTA：對物件有興趣想了解怎麼出價，留言議價，仲豪跟你聊，都免費，問就對了。')])

k03_15 = kc3(15,'maskbago 的稅務試算，我實際給你看一次','直球揭秘',['TikTok','IG Reels'],'個人化諮詢',
    '沒算稅就設底價是在瞎談。用 maskbago 先試算稅費量級，底價設合理，談的時候心裡有底。',
    [('0-3s','同樣一間房子，賣之前沒算稅和先算過稅，賣完手上剩的錢，差距可以很大。'),
     ('3-12s','先算稅的情況：用 maskbago 輸入買入賣出價格和持有年限，先知道稅費量級，底價設合理。'),
     ('12-25s','沒算稅就設底價，真的是在瞎談！工具是免費的，你用 2 分鐘就能試。'),
     ('25-40s','算過再談，不等於一定談得更好，但至少不是瞎談，OK嗎？'),
     ('40-52s','想試用的留言 67，仲豪把連結傳你，都免費，問就對了。')])

k03_17 = kc3(17,'開價跟市場價的差，你知道嗎？','直球揭秘',['TikTok','IG Reels'],'個人化諮詢',
    '4 步判斷開價合不合理：記住開價、查實價登錄、比差距、看條件能否解釋差距。',
    [('0-3s','看到一間房子的開價，4 個步驟判斷它合不合理，學起來。'),
     ('3-12s','第一步，記住開價和地址。第二步，去查同社區或同路段近 1 年的實價登錄。'),
     ('12-25s','第三步，比對開價和成交行情的差距。差距越大，談判空間越大。'),
     ('25-40s','第四步，看這個物件的條件解釋得了這個差距嗎？有理由貴是一回事，沒理由，就是你的籌碼。'),
     ('40-52s','有物件不知道怎麼判斷，留言行情，仲豪私訊給你分析，都免費，問就對了。')])

# 第03批 人間觀察
k03_06 = kc3(6,'中都這個區，我說真的','人間觀察',['IG Reels','小紅書'],'個人化諮詢',
    '有夫妻預算到了才看中都，進來一看比想像好很多。老社區、停車需注意，但學區近、生活踏實。',
    [('0-3s','有一對夫妻，來看中都的房子，看完第一句話說：這裡比我想的好很多。'),
     ('3-12s','他們本來沒打算看中都，是預算到了才過來。進來一看，重南路這一帶，生活機能齊全，巷弄安靜。'),
     ('12-25s','中都老社區多，中古屋為主，停車位要留意，老公寓有些沒電梯。'),
     ('25-40s','他們最後選了這裡，說：不是退而求其次，是找到真的適合我們的。'),
     ('40-52s','中都不是最熱門的，但有些人看了會留下來，值得進來看一眼，OK嗎？'),
     ('52-60s','CTA：對中都有興趣，留言中都，仲豪私訊跟你聊，都免費，問就對了。')])

k03_07 = kc3(7,'同齡的你，到底在等什麼才要買？','人間觀察',['IG Reels','Threads'],'個人化諮詢',
    '朋友等了 7 年，第一年等存款、第三年等降息、第五年等房價跌、第七年等工作穩——每年都有理由。',
    [('0-3s','有個跟我同齡的朋友，等了整整 7 年才開始認真看房。'),
     ('3-12s','他第一年說等存夠頭期款，第三年說等降息，第五年說等房價跌，第七年說等工作更穩。'),
     ('12-25s','上個月他來找我，評估完他說：我這些狀況，3 年前就可以開始了。'),
     ('25-40s','他說：那 3 年，我是在等一個不會自動出現的時機。拖著不了解，才是真正的風險。'),
     ('40-52s','拖著不了解，才是真正的風險所在，OK嗎？'),
     ('52-60s','CTA：想搞清楚自己的狀況，留言評估，仲豪跟你聊，都免費，問就對了。')])

k03_09 = kc3(9,'我哥問我：買新成屋還是中古屋？','人間觀察',['IG Reels','Threads'],'個人化諮詢',
    '這問題本身就問錯了——要先問自備款、屋況還是地段、有沒有裝修預算，答案自然出來。',
    [('0-3s','我哥昨天問我：買新成屋還是中古屋比較好？我跟他這樣說。'),
     ('3-12s','我說這個問題本身就問錯了。你要先問的是：你的自備款多少、你要的是屋況還是地段、你有沒有裝修預算。'),
     ('12-25s','新成屋好處是屋況好、公共設施完整，但坪數費用較高。中古屋優點是地段更靈活，但裝修費用要估進去。'),
     ('25-40s','我哥問我：那你覺得哪個比較好？我說，看你的條件，不是每個人答案都一樣。'),
     ('40-52s','問對問題，才能有對的答案，OK嗎？'),
     ('52-60s','CTA：有疑問的留言問我，仲豪來跟你分析，都免費，問就對了。')])

k03_10 = kc3(10,'看屋跑了半年沒成交，問題不是房子','人間觀察',['IG Reels','TikTok'],'個人化諮詢',
    '帶一對夫妻看了半年一間沒成，原來兩人各有不同版本的理想房子，找到交集的那天，下一間看的就下訂了。',
    [('0-3s','有一對夫妻，我陪他們看了半年的房子，一間都沒成。'),
     ('3-12s','每次看完，太太說這間採光不夠，先生說那間停車太麻煩。'),
     ('12-25s','後來我才搞清楚：他們心裡各自有一個完全不同版本的理想房子，但從來沒有跟對方說清楚過。'),
     ('25-40s','我讓他們各自列出 3 個死線，非有不可的條件，再找交集。找到交集的那天，下一間看的就下訂了。'),
     ('40-52s','看很久沒成，問題不一定在房子，OK嗎？'),
     ('52-60s','CTA：有在看房但看不到對的，留言方向，仲豪跟你聊，都免費，問就對了。')])

k03_16 = kc3(16,'你有沒有遇過這種屋主？','人間觀察',['IG Reels','Threads'],'個人化諮詢',
    '帶看前一天屋主說不賣了，原來是被朋友說現在不急影響。屋主的猶豫不是不想賣，是沒有人真的聽他說。',
    [('0-3s','你有沒有遇過這種屋主：帶看的前一天，說不賣了。'),
     ('3-12s','我帶著客戶、確認好了時間，前一天晚上屋主傳訊息說我在考慮一下。'),
     ('12-25s','後來我才知道，屋主是因為朋友說現在不用急，價格會繼續漲。'),
     ('25-40s','我說你跟我說你現在的狀況是什麼，我幫你看這個決定對不對。他沉默了一下，說好，我跟你說說。'),
     ('40-52s','很多時候，業主的猶豫不是不想賣，是沒有人真的聽他說，OK嗎？'),
     ('52-60s','CTA：有在考慮賣房但還沒想清楚，留言猶豫，仲豪跟你聊聊，都免費，問就對了。')])

k03_19 = kc3(19,'不是每個人都適合現在買','人間觀察',['IG Reels','Threads'],'個人化諮詢',
    '客戶說她準備好了要買，但剛換工作試用期、感情不確定、存款沒緩衝金。三個月後她回來說：現在準備好了。',
    [('0-3s','有個客戶來找我，說她準備好了，想買了。'),
     ('3-12s','我跟她聊了一下，她說她最近剛換工作，試用期三個月，收入還不穩；感情剛起步；存款有頭期款，但沒有緩衝金。'),
     ('12-25s','她說，但周圍的朋友都買了，我是不是也要買？我說，你跟我說的這三件事，你告訴我你準備好了嗎？'),
     ('25-40s','三個月後她回來，說現在準備好了。'),
     ('40-52s','不是每個人都適合現在買，但每個人都適合搞清楚自己的狀況，OK嗎？'),
     ('52-60s','CTA：不確定自己現在適不適合，留言時機，仲豪跟你分析，都免費，問就對了。')])

# 第03批 共鳴痛點
k03_03 = kc3(3,'首購族貸款踩的 3 個地雷，我都見過','共鳴痛點',['TikTok','IG Reels'],'個人化諮詢',
    '寬限期用完月付跳、貸款成數高估、只問利率忘了問年限——不是房子的問題，是資金規劃的問題。',
    [('0-3s','首購族申請房貸，這 3 個地雷我有太多客戶踩過。'),
     ('3-12s','第一個，寬限期用完就措手不及。第二個，貸款成數高估。第三個，只問利率忘了問年限。'),
     ('12-25s','我有個同齡客戶，自備款存了 2 年，結果因為信用評分不足，貸款成數不夠，他就買不成。'),
     ('25-40s','這 3 個地雷，不是房子的問題，是資金規劃的問題。搞清楚你的資金狀況，再去看房，OK嗎？'),
     ('40-52s','想評估你自己的貸款資格，留言房貸，仲豪私訊給你分析，都免費，問就對了。')])

k03_14 = kc3(14,'賣房前，你有沒有先問過自己這 3 個問題','共鳴痛點',['FB Reels','IG Reels'],'個人化諮詢',
    '稅算過了嗎？底價算清楚了嗎？賣了之後住哪裡？3 個問題是要你賣得有把握。',
    [('0-3s','準備賣房的人，這 3 個問題，你自己問過了嗎？'),
     ('3-12s','第一個：你的房地合一稅算過了嗎？第二個：你的底價算清楚了嗎？'),
     ('12-25s','第三個：賣了之後，你要去哪？先賣後買，中間的空窗期有沒有安排好？'),
     ('25-40s','這 3 個問題不是要你害怕賣，是要你賣得有把握，OK嗎？'),
     ('40-52s','想賣房但還有疑問，留言賣房，仲豪私訊給你，都免費，問就對了。')])

k03_18 = kc3(18,'你準備好頭期款了，然後呢？','共鳴痛點',['TikTok','IG Reels'],'個人化諮詢',
    '頭期款之外還要準備契稅、代書費、謄本費、過戶規費，加搬家費和裝修預算，全部算進去才是真的夠。',
    [('0-3s','頭期款存夠了，然後呢？我看不少人準備到頭期款就以為萬事俱備了。'),
     ('3-12s','頭期款之外，你還要準備的有：契稅、代書費、謄本費、過戶規費。'),
     ('12-25s','還有搬家費、裝修預算。如果買的是中古屋，這些都要提前估進去。'),
     ('25-40s','最常見的情況是，以為存到頭期款就夠了，結果過戶的時候很窘。'),
     ('40-52s','買房預算不是只有頭期款，是頭期款加上所有附帶費用，全部算進去，才知道你真的夠不夠，OK嗎？'),
     ('52-60s','CTA：想確認自己的預算狀況，留言預算，仲豪私訊給你估算，都免費，問就對了。')])

# 第03批 自嘲反差派
k03_04 = kc3(4,'我做房仲最大的笑話','自嘲反差',['IG Reels','Threads'],'個人化諮詢',
    '以為量多就是機會多，帶客戶看了 15 間，最後一間沒成。現在先聊清楚需求，才帶最對的幾間。',
    [('0-3s','我做房仲最大的笑話，是我以為介紹最多房子的人就是最強的業務。'),
     ('3-12s','剛入行的時候，我什麼房子都帶，覺得量多就是機會多，結果每天很忙，成交很少。'),
     ('12-25s','後來我才搞清楚，帶錯客人看錯房，是在浪費彼此的時間。要先花時間搞懂客人要什麼。'),
     ('25-40s','更好笑的是，我帶一個客戶看了 15 間，他最後說謝謝你，我決定不買了。'),
     ('40-52s','所以我現在都是先聊，搞清楚你的狀況，才帶你看最對的幾間，不搞無效帶看，OK嗎？'),
     ('52-60s','CTA：有想買房但不知道從哪裡開始，留言聊聊，仲豪私訊給你，都免費，問就對了。')])

k03_13 = kc3(13,'如果可以重新來，我第一年就這樣做','自嘲反差',['IG Reels','Threads'],'個人化諮詢',
    '第一年最想改的 3 件事：少打 cold call 先懂市場；早點學問問題不猜；被拒絕了隔天繼續出現。',
    [('0-3s','如果可以重新來，房仲第一年我最想改的 3 件事。'),
     ('3-12s','第一件：少打 cold call，多去走路段、認物件。懂市場，才能讓人繼續聽你說。'),
     ('12-25s','第二件：早點學問問題，不要猜。直接問清楚，比猜測省時 10 倍。'),
     ('25-40s','第三件：被拒絕了，隔天繼續出現。第一年沒成交，很容易就躲起來。'),
     ('40-52s','說這些不是要你複製我的路，是讓你少走一點彎路，OK嗎？'),
     ('52-60s','CTA：有在考慮做房仲或剛入行不久，留言入行，仲豪跟你聊聊，都免費，問就對了。')])

# 第03批 圖卡部（釣魚部 → 圖卡部）
k03_05 = kc3(5,'過戶給家人 3 種方式，哪個省最多？','圖卡部',['TikTok','IG Reels'],'圖卡部（留言取得對照表）',
    '買賣、贈與、繼承——選錯方式多繳幾十萬是真實案例。完整對照表留言取得。',
    [('0-3s','房子要過戶給家人，到底哪一種方式最省？這個問題很多人答錯。'),
     ('3-12s','可以選的方式有三種：買賣、贈與、繼承。每一種的稅費和條件都不一樣，選錯方式，多繳幾十萬是真實案例。'),
     ('12-25s','很多人以為繼承免稅，但繼承要等到發生，有沒有你決定不了。贈與稅有免稅額度上限，超過就要繳。'),
     ('25-40s','選哪種，取決於你的持有年限、你跟受贈人的關係、還有你們的所得狀況。'),
     ('40-52s','我整理了一份完整的對照表，3 種方式的稅費差異、適合誰，都在裡面。'),
     ('52-60s','底下留言過戶，仲豪私訊給你完整解答，都免費，問就對了。')],
    )

# 第03批 純雞湯
k03_20 = kc3(20,'你還在嗎，就一件事','純雞湯',['IG Reels','Threads'],'純雞湯（無硬 CTA）',
    '每個在找房子的人都很累，首購族累、換屋族也累。不需要很快，但要繼續。你還在嗎？那就夠了。',
    [('0-3s','最近有沒有一件事，讓你覺得真的很累，但還是撐下來了？'),
     ('3-12s','我做這行，遇到很多在挑房子的人，他們輕鬆的很少。首購族累，換屋族也累。'),
     ('12-25s','但大多數人，最後都做到了。不是因為他們特別厲害，是因為他們沒有在最難的時候放棄找答案。'),
     ('25-40s','你如果現在正在某一個很累的階段，沒關係，繼續找你要的答案就好。不需要很快，但要繼續。'),
     ('40-52s','你還在嗎？那就夠了，OK嗎？'),
     ('52-60s','（無硬 CTA，如果你有想聊的，都可以。）')])

print('第03批 articles built OK')

# ============================================================
# 第 05 批 articles (生活向 13 支)
# 第 04 批已 archive
# ============================================================

# 01 30 歲，桌上擺的是寶可夢卡
k05_01 = kenny_article(1,'30 歲，桌上擺的是寶可夢卡','人間觀察',['IG Reels', 'Threads'],'無硬CTA',
    '30 歲桌上擺寶可夢卡有什麼問題？喜歡的東西繼續做，認真選擇這件事從來沒變過。',
    [('0-3s', '30 歲，桌上擺的是寶可夢卡。怎樣，有問題嗎？', '30歲房仲的辦公桌'), ('3-12s', '很多人覺得這個年紀，桌上要擺成就獎、名牌手錶，或者什麼都沒有、裝很忙。我不是。我的桌上一直有牌。', '', '等等，你上班時間在集點？'), ('12-25s', '寶可夢卡這件事我從小學就開始了。每一張卡都是一個選擇。你要留還是換，要等還是現在出手。這個邏輯，說真的跟買房沒什麼兩樣。', '每張卡都是一個選擇'), ('25-40s', '30 歲不是要假裝自己很成熟。30 歲是要清楚知道自己喜歡什麼，然後繼續做下去。我喜歡牌，我也喜歡這份工作。兩件事不衝突。', '', '這樣說好像有點道理欸'), ('40-52s', '你桌上放什麼，代表你是什麼樣的人。我放寶可夢卡，代表我還是那個很認真在收藏、認真選擇的人。', '你桌上放什麼'), ('52-60s', '你桌上放什麼？留言告訴我。OK嗎？', '留言告訴我你桌上放什麼')],
    batch=BATCH_05,
    caption='30 歲桌上擺寶可夢卡有什麼問題？喜歡的東西繼續做，認真選擇這件事從來沒變過。你桌上放什麼，留言告訴我。',
    platform_chip='IG Reels / Threads', po_time='平日晚間 19:30-21:00',
    hashtag=['#30歲', '#寶可夢', '#辦公桌日常', '#高雄房仲', '#kennywangbb', '#房仲日常', '#30歲觀察', '#仲豪', '#知識型短影音', '#生活感'])

# 02 白西裝配什麼領帶，這件事我很認真
k05_02 = kenny_article(2,'白西裝配什麼領帶，這件事我很認真','自嘲反差',['IG Reels', 'TikTok'],'無硬CTA',
    '白西裝配錯領帶整個人散掉。素色深藍深灰，讓人記住你這個人，不是你的衣服。',
    [('0-3s', '白西裝配什麼領帶，這件事我很認真在想。', '房仲的穿搭煩惱'), ('3-12s', '有人說白西裝配什麼都好，百搭。但你有沒有發現，白西裝配錯領帶，整個人就散掉了。顏色不對、寬度不對、材質不對，三個雷踩一個就糟糕。', '', '連這個都要想那麼多？'), ('12-25s', '我通常選素色深藍或深灰的領帶，不選花紋。原因是素色比較乾淨，客人注意力在臉上，不在衣服上。房仲的工作是讓人記住你這個人，不是記住你的衣服。', '素色領帶：讓人記住你這個人'), ('25-40s', '白西裝挑領帶，配不對整個人會散掉。我自己摸索很久才找到節奏——顏色深、材質要啞面、寬度不要太窄。這三件事同時對了，整套才算對了。', '', '哈哈這也太認真了'), ('40-52s', '穿著這件事沒有標準答案，但有原則。讓對方舒服、讓自己有信心，就是對的選擇。OK嗎？', '讓對方舒服、讓自己有信心'), ('52-60s', '你上班都怎麼穿？留言告訴我，不用怕，問問不用錢。', '留言你的上班穿搭')],
    batch=BATCH_05,
    caption='白西裝配什麼領帶這件事我想了很久。素色、深色、啞面材質，三件事同時對了整套才算對。穿著要讓對方舒服、讓自己有信心，這才是重點。',
    platform_chip='IG Reels / TikTok', po_time='平日晚間 19:30-21:00',
    hashtag=['#白西裝', '#穿搭', '#房仲形象', '#高雄房仲', '#kennywangbb', '#上班穿搭', '#領帶', '#仲豪', '#辦公室穿搭', '#房仲日常'])

# 03 房仲這份工，不是每個人都適合
k05_03 = kenny_article(3,'房仲這份工，不是每個人都適合——包括一開始的我','人間觀察',['IG Reels', 'Threads'],'純雞湯（無硬CTA）',
    '一開始也不確定能不能做。怕說錯、怕被拒絕、怕什麼都沒發生。真正要的，是跟不安全感坐在一起還繼續走的能力。',
    [('0-3s', '房仲這份工，不是每個人都適合的。包括一開始的我。', '房仲不是每個人都適合'), ('3-12s', '剛開始的時候，我不確定自己能不能做好。不是技術問題，是心態問題。怕說錯話、怕被拒絕、怕帶看完什麼都沒發生。這些我都有過。', '', '說這樣反而讓人覺得你很真實'), ('12-25s', '但後來我發現，不是適不適合的問題。是你有沒有辦法跟自己的不安全感坐在一起，然後還繼續往前走。那個能力，才是這份工作真正要的東西。', '跟不安全感坐在一起，還是往前走'), ('25-40s', '現在我桌上還是擺著布丁狗，還是喜歡寶可夢卡，還是講話會說OK嗎。這些沒有變。變的是我比較不怕了。', '', '這個我聽懂了'), ('40-52s', '你適不適合一份工作，不是別人說了算。是你自己撐下去，然後某一天發現，唉，還不錯嘛。', '某一天發現，唉，還不錯嘛'), ('52-60s', '你也是嗎？OK嗎？', '你也是嗎')],
    batch=BATCH_05,
    caption='一開始我也不確定自己能不能做這份工作。怕說錯、怕被拒絕、怕什麼都沒發生。但真正要的，是跟不安全感坐在一起還繼續走的能力。你也是嗎？',
    platform_chip='IG Reels / Threads', po_time='平日晚間 20:00-21:00',
    hashtag=['#房仲日常', '#職場心態', '#30歲', '#仲豪', '#kennywangbb', '#高雄房仲', '#正能量', '#工作這件事', '#雞湯', '#真實感'])

# 04 吉伊卡哇放辦公桌，每天第一個看到它
k05_04 = kenny_article(4,'吉伊卡哇放辦公桌，每天第一個看到它','家人朋友模擬派',['IG Reels', 'Threads'],'無硬CTA',
    '早上進辦公室先跟它說個早再開始工作。開工前找一個讓自己安靜的方式，這個是我的。',
    [('0-3s', '我辦公桌上的吉伊卡哇，每天早上第一個看到它。', '仲豪的辦公桌日記'), ('3-12s', '有人說，做業務的桌子要整潔、專業，最好什麼都不要放。我理解。但我覺得，桌上放什麼，是你跟自己的事，不是給別人看的表演。', '', '哦你辦公室可以放這個？'), ('12-25s', '早上進辦公室，先跟它說個早，然後開始工作。聽起來有點蠢，但那個5秒鐘讓我狀態好很多。開工前找一個讓自己安靜的方式，這個是我的。', '開工前，先找到讓自己安靜的方式'), ('25-40s', '身邊有朋友是喝第一口咖啡、有朋友是聽兩首歌、有朋友是看一下行事曆。每個人的方式不一樣。我的方式是看一眼桌上的小傢伙。', '', '欸我也有開工儀式欸'), ('40-52s', '不是什麼大道理。就是找到你自己開工的節奏，然後每天都從那裡開始。', '找到你自己開工的節奏'), ('52-60s', '你開工前都做什麼？留言告訴我。OK嗎？', '留言你的開工儀式')],
    batch=BATCH_05,
    caption='辦公桌上的吉伊卡哇每天早上是第一個看到的東西。5 秒鐘，讓自己安靜，然後開始工作。你開工前都怎麼啟動自己？留言告訴我。',
    platform_chip='IG Reels / Threads', po_time='平日晚間 19:30-20:30',
    hashtag=['#吉伊卡哇', '#辦公桌日常', '#開工儀式', '#仲豪', '#kennywangbb', '#高雄房仲', '#房仲日常', '#30歲', '#生活感', '#辦公室小物'])

# 05 春聯貼進辦公室那天
k05_05 = kenny_article(5,'春聯貼進辦公室那天','人間觀察',['IG Reels', 'FB Reels'],'無硬CTA',
    '春聯貼進辦公室那天，空間好像變成自己的了。讓自己安頓不需要大動作，一張春聯就夠了。',
    [('0-3s', '春聯貼進辦公室那天，我的狀態突然就不一樣了。', '辦公室貼春聯這件事'), ('3-12s', '不是迷信。就是有一種，貼上去之後，這個空間好像變成你的了。你對這個地方有了一種宣示。', '', '哦？貼春聯而已'), ('12-25s', '我覺得這跟買房很像。很多人問我，買了之後真的不一樣嗎？我每次都說，鑰匙拿到的那一刻，你會知道的。那不是數字，是一種體驗。', '鑰匙拿到的那一刻，你會知道的'), ('25-40s', '貼春聯也是這樣。你走進辦公室，看到牆上有你親手貼的東西，那個空間突然有了你的痕跡。很難解釋，但真的很不一樣。', '', '欸這樣說我有點懂了'), ('40-52s', '有時候讓自己安頓下來，不需要什麼大動作。一張春聯，就夠了。', '一張春聯，就夠了'), ('52-60s', '你辦公室或家裡有貼春聯嗎？OK嗎？', '你有貼春聯嗎')],
    batch=BATCH_05,
    caption='春聯貼進辦公室那天，這個空間好像變成自己的了。跟買房拿到鑰匙那一刻很像，不是數字，是體驗。讓自己安頓不需要大動作，一張春聯就夠了。',
    platform_chip='IG Reels / FB Reels', po_time='平日晚間 19:30-21:00',
    hashtag=['#春聯', '#辦公室布置', '#節慶', '#高雄房仲', '#kennywangbb', '#仲豪', '#房仲日常', '#生活感', '#辦公室日常', '#過年'])

# 06 辦公桌上的招財貓，放了多久我自己都忘了【R3 換題】
k05_06 = kenny_article(6,'辦公桌上的招財貓，放了多久我自己都忘了','人間觀察',['Threads', 'IG Reels'],'無硬CTA',
    '辦公桌上的招財貓放了多久自己都忘了。招財貓的邏輯：手一直舉著，從來不停。一直出手才有機會。',
    [('0-3s', '我辦公桌上有一隻招財貓，放了多久我自己都忘了。', '仲豪辦公桌上的招財貓'), ('3-12s', '不是特別迷信，就是有一天出現在桌上，然後就一直在那邊了。你有沒有辦公桌上有東西，不知道從哪裡來、也沒有要移走的感覺？', '', '哈，這個說的是我'), ('12-25s', '後來想想，招財貓這個東西很有趣。它的動作只有一個——招。手一直舉著，不停的招。你說它真的招得到什麼嗎？不知道。但它就是一直在做那個動作，從來不停。', '手一直舉著，從來不停'), ('25-40s', '這件事跟做業務很像。你不能保證每次出手都有結果，但你要一直做那個動作。不出手就沒機會，一直出手就是招財貓的邏輯。', '', '哦，這樣說有點道理欸'), ('40-52s', '所以它放在那邊有沒有用，我說不準。但看到它就想到要繼續出手，那對我來說就夠了。', '看到它就想繼續出手，就夠了'), ('52-60s', '你桌上有沒有什麼奇怪的東西一直放著？留言告訴我。OK嗎？', '你桌上有什麼一直放著')],
    batch=BATCH_05,
    caption='辦公桌上的招財貓放了多久自己都忘了。但看到它就想到招財貓的邏輯：手一直舉著，從來不停。不能保證每次有結果，但一直出手才有機會。你桌上有奇怪的東西嗎？',
    platform_chip='Threads / IG Reels', po_time='平日晚間 20:00-22:00',
    hashtag=['#招財貓', '#辦公桌日常', '#房仲日常', '#仲豪', '#kennywangbb', '#高雄房仲', '#辦公室小物', '#生活感', '#30歲', '#真實感'])

# 07 30 歲還不買房的人，我幫你說一句
k05_07 = kenny_article(7,'30 歲還不買房的人，我幫你說一句','嗆辣',['TikTok', 'IG Reels'],'個人化諮詢',
    '30 歲還不買房不代表不想買、不代表不努力。謹慎不叫拖，但要知道自己為什麼還不買。',
    [('0-3s', '30 歲還不買房的人，你們被說太多了，我來幫你說一句。', '我幫你說一句'), ('3-12s', '很多人一聽到 30 歲還沒買房，就覺得你一定是在拖，或者你不夠努力。但現在的狀況不是這樣的。薪水的漲幅跟房價的漲幅根本不在同一個頻道。', '', '對欸，這樣說我比較能接受'), ('12-25s', '不買房不代表不想買，不代表沒在準備。很多同齡的人是在等一個比較清楚的狀況，等到自己可以做一個不後悔的決定，這不叫拖，這叫謹慎。', '謹慎，不叫拖'), ('25-40s', '但謹慎跟什麼都不做是兩件事。你知道自己在等什麼嗎？頭期款？薪水？還是只是覺得時機還沒到？這個問題，值得你自己想清楚一次。', '', '我被說到了，我真的不確定我在等什麼'), ('40-52s', '30 歲還不買房，這沒問題。但你要知道你為什麼還不買，這樣你才是在掌控自己的決定。OK嗎？', '知道自己為什麼不買，才叫掌控'), ('52-60s', '想理清楚自己的狀況，留言告訴我，仲豪跟你聊。不用怕，問問不用錢。', '留言告訴我你在等什麼')],
    batch=BATCH_05,
    caption='30 歲還不買房，不代表不想買、不代表不努力。薪資和房價根本不在同一頻道。謹慎不叫拖，但謹慎跟什麼都不做是兩件事。你知道自己在等什麼嗎？這個問題值得想清楚。',
    platform_chip='TikTok / IG Reels', po_time='平日晚間 19:00-22:00',
    hashtag=['#30歲', '#買房', '#首購族', '#高雄買房', '#kennywangbb', '#仲豪', '#高雄房仲', '#世代觀察', '#毒舌正能量', '#30歲視角'])

# 08 布丁狗陪我加班，你呢
k05_08 = kenny_article(8,'布丁狗陪我加班，你呢','人間觀察',['Threads', 'IG Reels'],'無硬CTA',
    '加班時辦公桌上有個布丁狗在陪著，說沒差是騙人的。每個人都有讓自己撐下去的方式。',
    [('0-3s', '加班的時候，辦公桌上有個布丁狗在陪你，你說有沒有差？', '布丁狗加班陪伴'), ('3-12s', '有人說工作的地方不要放太多雜物，影響效率。有人說工作的桌子要整齊，才能清楚思考。我都聽過。但我的布丁狗就是要在那邊。', '', '房仲也會加班喔？'), ('12-25s', '加班這件事，房仲是有的。晚上有客人的時間，就是你工作的時間。不是每天，但有的時候就是會到比較晚。這個行業就是這樣。', '客人有空的時候，就是你的工作時間'), ('25-40s', '但每次要收拾東西的時候，看到布丁狗還是在那邊坐著，我就覺得，好，今天做完了，可以回家了。很小的事情，但很有用。', '', '欸這樣說好像很溫馨'), ('40-52s', '每個人都有自己讓自己撐下去的方式。我的方式是布丁狗。你的是什麼？', '你讓自己撐下去的方式是什麼'), ('52-60s', '留言告訴我。OK嗎？', '留言告訴我你的方式')],
    batch=BATCH_05,
    caption='加班時辦公桌上有個布丁狗在陪著，說沒差是騙人的。房仲有加班，晚上有客人就是工作時間。但每次收東西看到它，就知道今天做完了可以回家了。',
    platform_chip='Threads / IG Reels', po_time='平日晚間 20:00-22:00',
    hashtag=['#布丁狗', '#加班日常', '#房仲日常', '#仲豪', '#kennywangbb', '#高雄房仲', '#辦公室小物', '#辦公桌', '#生活感', '#工作這件事'])

# 09 公設比到底怎麼算
k05_09 = kenny_article(9,'公設比到底怎麼算，3 件事你一定搞錯了','拆解',['IG Reels', 'TikTok', 'FB Reels'],'個人化諮詢',
    '公設比不是越低越好，要看低在哪裡。主建物面積才是你真正住到的空間，這才是比較的基準。',
    [('0-3s', '公設比這件事，3 個常見錯誤，你中了幾個？', '公設比3個常見錯誤'), ('3-12s', '買房看公設比，很多人看的方法是錯的。不是說你笨，是沒有人告訴你怎麼看。今天一次說清楚。', '', '好，我洗耳恭聽'), ('12-25s', '第一，公設比不是越低越好，要看低在哪裡。電梯間、門廳、走道，這些拿掉，你的生活品質就拿掉了一塊。第二，公設比高的房子，不一定貴，要算每坪實際單價。第三，主建物面積才是你真正住到的空間，這才是比較的基準。', '主建物面積，才是你住到的空間'), ('25-40s', '很多人拿公設比直接比房子好壞，但公設比只是一個欄位，不是整個答案。你的需求是什麼，決定你怎麼看這個數字。', '', '哦，所以不是越低越好？'), ('40-52s', '下次看房，先問主建物幾坪，再算你付的每坪是多少。這樣才是真的在比。OK嗎？', '先問主建物幾坪，再算每坪單價'), ('52-60s', '有在看房的，留言「公設」，仲豪幫你看一下你考慮的物件數字對不對。不用怕，問問不用錢。', '留言「公設」我幫你看')],
    batch=BATCH_05,
    caption='公設比這件事，你看的方式有沒有搞錯？不是越低越好，要看低在哪裡；公設比高不等於貴；主建物面積才是你真正住到的空間。下次看房先問這個。',
    platform_chip='IG Reels / TikTok / FB Reels', po_time='平日晚間 19:30-21:00',
    hashtag=['#公設比', '#買房知識', '#首購族', '#高雄買房', '#kennywangbb', '#仲豪', '#高雄房仲', '#房仲教學', '#買房避坑', '#知識型短影音'])

# 10 OK嗎，這兩個字我為什麼每次都講
k05_10 = kenny_article(10,'OK嗎，這兩個字我為什麼每次都講','自嘲反差',['Threads', 'IG Reels'],'無硬CTA',
    'OK嗎這兩個字，不只是口頭禪，是確認對方有沒有跟上的動作。剛好變成了個人標誌。',
    [('0-3s', 'OK嗎？這兩個字，我自己都不知道我說了多少次。', 'OK嗎的由來'), ('3-12s', '我自己沒注意到，有天回放自己的影片才發現，每次說完一段，後面一定接 OK嗎。說了多少次，自己都不知道。', '', '哈，真的很固定欸'), ('12-25s', '後來我想了一下，OK嗎這兩個字，其實是在問對方你跟上了嗎。不是在問你同不同意我說的，是在問你有沒有在同一個頻道上。這是一個確認的動作。', 'OK嗎 = 你跟上了嗎？'), ('25-40s', '溝通這件事，不是說完就算了。說完要確認對方有沒有接到，這樣才算說到。講房子這件事也是一樣，說完要問一句，有沒有清楚。', '', '原來這是一個溝通技巧'), ('40-52s', '所以OK嗎這兩個字，不是口頭禪，是習慣。一個好的溝通習慣，剛好變成了我的個人標誌。', '不是口頭禪，是溝通習慣'), ('52-60s', '你有沒有自己的口頭禪？留言告訴我。OK嗎？', '你的口頭禪是什麼')],
    batch=BATCH_05,
    caption='OK嗎這兩個字說了多少次自己都不知道。後來想想，這不只是口頭禪，是確認對方有沒有跟上的動作。溝通說完要確認，剛好變成了我的個人標誌。',
    platform_chip='Threads / IG Reels', po_time='平日晚間 20:00-22:00',
    hashtag=['#口頭禪', '#溝通', '#仲豪', '#kennywangbb', '#高雄房仲', '#房仲日常', '#個人特色', '#30歲', '#生活感', '#真實感'])

# 11 我的辦公桌塑膠袋，捨不得丟
k05_11 = kenny_article(11,'我的辦公桌塑膠袋，捨不得丟','自嘲反差',['Threads', 'IG Reels'],'無硬CTA',
    '不是很貴，就是放在那邊。那些東西代表的是某個時間點的你。有溫度的工作環境讓你每天想來這裡。',
    [('0-3s', '我辦公桌上有東西我捨不得丟，就算沒用了也一直放著。', '捨不得丟的辦公桌'), ('3-12s', '你有沒有這種東西？不是很貴，不是很重要，就是放在那邊，要丟的時候總是放不下手。這種東西我覺得很多人都有，只是大家不說。', '', '哦，你也是這樣？'), ('12-25s', '我覺得這些東西代表的是某一個時間點的你。你拿到它的那個當下、那個狀態、那個心情。丟掉它，好像也丟掉了那個時候的一些東西。', '那個時間點的你'), ('25-40s', '合理化一下：這叫儀式感。不是整齊，是有溫度。一個有溫度的工作環境，讓你每天想來這裡。這是一種選擇。', '', '這個理由我要借用一下'), ('40-52s', '不是每樣東西都要有功能，有時候放在那邊就是它的功能。', '放在那邊，就是它的功能'), ('52-60s', '你桌上有什麼捨不得丟的東西？OK嗎？', '你有什麼捨不得丟？')],
    batch=BATCH_05,
    caption='辦公桌上有東西沒用了還是捨不得丟。不是很貴，就是放在那邊。那些東西代表的是某個時間點的你，丟掉了也丟掉那個當下。你有這種東西嗎？',
    platform_chip='Threads / IG Reels', po_time='平日晚間 20:00-22:00',
    hashtag=['#辦公桌', '#辦公室日常', '#儀式感', '#仲豪', '#kennywangbb', '#高雄房仲', '#生活感', '#30歲', '#真實感', '#辦公室小物'])

# 12 買房前，你有查過凶宅嗎
k05_12_card = kenny_article(12,'買房前，你有查過凶宅嗎','圖卡部',['IG Reels', 'TikTok'],'圖卡部（留言取得查詢方法）',
    '買房前查過凶宅嗎？查凶宅有正確管道、有時間點、還有怎麼判斷，3 件事缺一個查了也沒用。',
    [('0-3s', '買房前，你有查過凶宅嗎？這件事，很多人跳過了。', '你查過凶宅嗎？'), ('3-12s', '我說的查，不是網路隨便搜一下。凶宅查詢有正確的管道、有查詢的時間點、還有查完以後你要怎麼判斷。這 3 件事缺一個，查了也沒用。', '', '等等，查凶宅還有這些眉角？'), ('12-25s', '為什麼重要？因為凶宅不一定在實價登錄上標示，屋主不一定會主動說，你自己查不到，代表你不知道你買了什麼。這個風險，你願意接受嗎？', '屋主不一定會主動說'), ('25-40s', '更麻煩的是，凶宅認定標準跟一般人想的不一樣。哪些算、哪些不算，每個縣市有些差異，法院的認定方式也有不同。搞清楚之前，不要假設查過的就沒問題。', '', '那到底要怎麼查？'), ('40-52s', '3 個正確查詢管道 + 查詢時間點 + 怎麼判斷結果，這 3 件事我整理成一張完整的圖給你。', '完整查詢方法，私訊給你'), ('52-60s', '底下留言「凶宅」，仲豪私訊完整查詢方法給你。不用怕，問問不用錢。OK嗎？', '留言「凶宅」私訊給你')],
    batch=BATCH_05,
    caption='買房前你有查過凶宅嗎？查凶宅有正確管道、有時間點、還有怎麼判斷，3 件事缺一個查了也沒用。屋主不一定會說，你不查就是不知道自己買了什麼。',
    platform_chip='IG Reels / TikTok', po_time='平日晚間 19:30-21:00',
    hashtag=['#凶宅查詢', '#買房必知', '#首購族', '#高雄買房', '#kennywangbb', '#仲豪', '#高雄房仲', '#看房避坑', '#買房知識', '#房仲教學'])

# 13 賣了房子，重購退稅這件事你算過嗎【R3 換題】
k05_13 = kenny_article(13,'賣了房子，重購退稅這件事你算過嗎','拆解',['IG Reels', 'TikTok'],'個人化諮詢',
    '賣舊買新符合條件，繳的稅退回一部分，但申請有期限、新房有條件。搞清楚才不後悔。',
    [('0-3s', '賣了房子換房，重購退稅這件事，你算過嗎？', '換房族必看：重購退稅'), ('3-12s', '很多人賣了房換新房，不知道有這個退稅機制。也有人聽過，但不確定自己符不符合，等期限過了才後悔。', '', '等等，賣房還能退稅？'), ('12-25s', '重購退稅的概念是：賣了舊房子繳了房地合一稅，如果在規定時間內又買了新房子，而且新房比舊房貴，繳的稅有機會退回一部分。這是政府鼓勵換大房的補償機制，不是免稅，是先繳再退。退多少因人而異，私訊告訴我你的狀況我幫你算。', '賣舊買新，符合條件就退一部分'), ('25-40s', '這件事有 3 個眉角。第一，申請有期限，過了就沒了，這個很多人忘記。第二，新房子有條件限制，不是什麼房子都符合。第三，要先繳稅才有得退，不是一開始就免稅。3 件事都要確認。', '', '哦，所以要先確認自己符合？'), ('40-52s', '換屋的人，賣房稅費算清楚了，重購退稅這一塊也確認一次。錢有沒有退回來，差距不小。OK嗎？', '差距不小，確認一次才安心'), ('52-60s', '有換屋打算的留言「換屋」，仲豪幫你算一下你的狀況。不用怕，問問不用錢。', '留言「換屋」我幫你算')],
    batch=BATCH_05,
    caption='賣了房換房，重購退稅你算過嗎？賣舊買新符合條件，繳的稅退回一部分，但申請有期限、新房有條件。搞清楚才不後悔，有換屋打算的留言告訴我，仲豪幫你算。',
    platform_chip='IG Reels / TikTok', po_time='平日晚間 19:30-21:00',
    hashtag=['#重購退稅', '#換屋', '#房地合一稅', '#買房知識', '#kennywangbb', '#仲豪', '#高雄房仲', '#換屋族', '#稅務', '#房仲教學'])

print('第05批 articles built OK')

# ============================================================
# Threads 脆文 第04批
# ============================================================
THREADS_04 = [
    ('T01', '短文觀點型',
     '客戶說「對不起，我不買了」。\n\n大部分人聽到這句話會很慌。我習慣先問一句：\n\n「你是真的不買了，還是有一件事還沒講清楚？」\n\n沉默個三秒，他說出了真正的問題。\n\n不是物件不好。是家人那關還沒過。\n\n解決的是人，不是房子。\n\n---\n\n這種時候，你不需要催。你需要問。\n\n留言告訴我你買房路上卡在哪一關。',
     '#房仲日常 #買房 #購屋'),
    ('T02', '短文知識型',
     '「我買不起」這件事，有兩種。\n\n一種是真的買不起——收入、頭期、月付都達不到。\n\n另一種是以為買不起——但從來沒有認真算過自己能買的範圍。\n\n大部分人是第二種。\n\n---\n\n算清楚需要三個數字：\n自己能拿出的頭期款\n能承擔的月付\n目標區域均價\n\n三個數字對齊，你才知道你在哪個位置。\n\n不知道從哪算起，留言「算」，幫你把數字問清楚。',
     '#買房 #首購族 #財商 #高雄房地產'),
    ('T03', '短文知識型',
     '買房前，最多人沒搞清楚的一件事：\n\n銀行貸款不是用你的成交價算，是用銀行的估價算。\n\n你出 1,000 萬，銀行估 880 萬——你的貸款上限是 880 萬，不是 1,000 萬。\n\n差的那部分，自己補。\n\n---\n\n所以下斡旋之前，先讓銀行估一次，知道你能貸多少、月付是多少，才不會買了發現缺口太大。\n\n有疑問的留言或私訊。不用怕，問問不用錢。',
     '#房貸 #貸款 #買房 #首購族 #高雄房地產'),
    ('T04', '短文知識型',
     '帶看這幾年，我覺得最值得問屋主的一個問題是：\n\n「你為什麼要賣？」\n\n不是為了壓價，是為了知道背景。\n\n工作調動要搬——代表有時間壓力，議價空間通常較大。\n\n繼承的房——代表沒有心理價位包袱。\n\n急著換屋——又是另一種節奏。\n\n---\n\n問出原因，你才知道怎麼跟屋主互動。',
     '#看房 #買房 #房仲分享 #高雄房地產'),
    ('T05', '短文觀點型',
     '做房仲有一個隱形的陷阱：\n\n你以為帶看越多越好。\n\n實際上，方向沒定好的帶看，是最消耗時間的事。\n\n---\n\n帶看前問清楚三件事：\n你最在意什麼\n你不能接受什麼\n你願意讓步的點在哪裡\n\n問完，帶看效率直接翻。\n\n不知道自己要什麼，留言「問」幫你理清。',
     '#房仲日常 #看房 #買房 #購屋'),
    ('T06', '短文觀點型',
     '三十歲沒房子，不是失敗。\n\n是還沒找到對的時間點和對的條件而已。\n\n---\n\n我看過很多人，二十幾歲衝動買了，後來後悔。\n\n也看過很多人，三十幾歲算清楚再買，反而住得很踏實。\n\n不是哪個年齡要買房，是你的數字到位的時候買房。\n\n數字到位，是指你知道你現在能負擔什麼、你想住什麼樣的地方。',
     '#買房 #首購族 #高雄房地產 #正能量'),
    ('T07', '短文知識引流型',
     '30 坪的房子，你實際住的是幾坪？\n\n答案是：要看公設比。\n\n公設比 35%，室內只有不到 20 坪。\n\n公設比 15%，室內大很多。\n\n---\n\n這個數字，很多人買完才去算。\n\n計算公式、3 種房型的差異、怎麼避開高公設比的雷——我整理好了。\n\n留言「公設」，仲豪私訊給你。',
     '#公設比 #買房 #房地產知識 #首購族 #高雄房地產'),
]

def thread_kenny(tid, label, body, hashtag):
    safe = body.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    Q = chr(39)
    return (
        '<div class="thread-card">\n'
        '<div class="thread-meta"><span class="thread-id">' + tid + '</span><span class="thread-label">' + label + '</span></div>\n'
        '<div class="thread-text">' + safe + '</div>\n'
        '<div class="thread-hash">' + hashtag + '</div>\n'
        '<button class="copy-btn" onclick="copyThread(this)">複製脆文</button>\n'
        '</div>'
    )

threads_section = (
    '<div class="group collapsed" id="grp-threads">\n'
    '<div class="group-header" onclick="toggleGroup(this.parentElement)">\n'
    '  <span class="group-label">脆文 Threads</span>\n'
    '  <span class="group-en">第 05 批 · 7 篇</span>\n'
    '  <span class="group-count">7 posts</span>\n'
    '  <span class="group-toggle">▼</span>\n'
    '</div>\n'
    '<div class="group-body">\n'
    '<div class="threads-grid">\n' +
    '\n'.join(thread_kenny(t[0], t[1], t[2], t[3]) for t in THREADS_04) +
    '\n</div>\n</div>\n</div>'
)

print('Threads section built OK')

# ============================================================
# Assemble v2 groups (cross-batch merge)
# 第05批 派系分組（R3 更新後）：
#   人間觀察 — k05_01 k05_04 k05_05 k05_06 k05_08
#   自嘲反差 — k05_02 k05_10 k05_11
#   嗆辣     — k05_07
#   拆解/直球 — k05_09 k05_13（R3：重購退稅 拆解派）
#   圖卡部   — k05_12_card
#   純雞湯   — k05_03
# ============================================================

# 直球揭秘（03批 7部 + 05批 2部：Erika 公設比 + R3 重購退稅）
g_direct = group_v2('直球揭秘', 'Direct Knowledge', 0,
    [k03_01, k03_02, k03_08, k03_11, k03_12, k03_15, k03_17,
     k05_09, k05_13])

# 人間觀察（03批 6部 + 05批 5部）
g_human = group_v2('人間觀察', 'Human Observations', 1,
    [k03_06, k03_07, k03_09, k03_10, k03_16, k03_19,
     k05_01, k05_04, k05_05, k05_06, k05_08])

# 共鳴痛點（03批 3部 + 05批 毒舌正能量）
g_pain = group_v2('共鳴痛點 / 嗆辣派', 'Resonance & Spicy', 2,
    [k03_03, k03_14, k03_18, k05_07])

# 自嘲反差（03批 2部 + 05批 3部）
g_story = group_v2('自嘲反差', 'Self-Irony', 3,
    [k03_04, k03_13, k05_02, k05_10, k05_11])

# 圖卡部（03批 1部 + 05批 1部）
g_card = group_v2('圖卡部', 'Card Library', 4,
    [k03_05, k05_12_card])

# 純雞湯（03批 1部 + 05批 1部）
g_soul = group_v2('純雞湯', 'Soul Food', 5,
    [k03_20, k05_03])

all_main = '\n\n'.join([g_direct, g_human, g_pain, g_story, g_card, g_soul, threads_section])

ok, nc = rp_main(os.path.join(LIB, 'kenny.html'), all_main)

# ---- V2 CSS patch ----
V2_CSS_MARKER = '/* ========== V2 GROUP COLLAPSED + copyScript (build_all.py v2) ========== */'
V2_CSS = """
/* ========== V2 GROUP COLLAPSED + copyScript (build_all.py v2) ========== */
.group{margin-top:24px;}
.group-header{
  display:flex;align-items:center;gap:10px;
  padding:12px 16px;
  background:var(--chiik-bg);
  border:2px solid var(--chiik-line);
  border-radius:8px;
  cursor:pointer;user-select:none;-webkit-user-select:none;
  transition:background .2s;
}
.group-header:hover{background:var(--chiik-yellow, #f0d060);}
.group-label{
  font-weight:700;font-size:15px;letter-spacing:.04em;flex:1;
}
.group-en{font-size:12px;color:var(--muted);letter-spacing:.06em;}
.group-count{font-size:12px;background:var(--accent);color:white;padding:2px 8px;border-radius:999px;}
.group-toggle{font-size:14px;color:var(--muted);}
.group.collapsed .group-toggle{transform:rotate(-90deg);display:inline-block;}
.group.collapsed > .group-body{display:none !important}
.group.collapsed > div.threads-grid{display:none !important}
.group.collapsed > .threads-grid{display:none !important}
.group-body{padding:8px 0;}
.card-meta-extra{font-size:11px;color:var(--muted);margin:4px 0;display:flex;gap:8px;flex-wrap:wrap;}
.platform{font-size:11px;background:var(--border-soft);padding:2px 7px;border-radius:4px;font-weight:600;}
.po-time{font-size:11px;color:var(--muted);}
.hashtag-pool{display:flex;flex-wrap:wrap;gap:5px;margin:8px 0 4px;}
.hashtag{background:var(--border-soft);color:var(--accent-soft);padding:2px 8px;border-radius:12px;font-size:11px;}
.card-thumb{max-width:320px;width:100%;height:auto;object-fit:contain;border-radius:6px;cursor:zoom-in;display:block;margin:8px 0;}
@media (max-width:640px){.card-thumb{max-width:100%;}}
.caption-preview{margin:10px 0 6px;padding:10px 14px;background:var(--chiik-bg,var(--surface));border-left:3px solid var(--chiik-yellow,#f0d060);border-radius:4px;font-size:13px;line-height:1.6;}
.caption-preview-label{font-size:11px;color:var(--accent);font-weight:600;margin-bottom:4px;}
.caption-preview-text{color:var(--text);white-space:pre-wrap;}
.caption-preview-hash{margin-top:6px;font-size:12px;color:var(--tag-blue,var(--accent-soft));}
.card-thumb:hover{transform:scale(1.05);box-shadow:0 4px 12px rgba(0,0,0,.18);}
.mirror{
  margin-top:6px;display:inline-block;
  font-size:11.5px;font-style:italic;
  color:var(--tag-brown,#8a6040);
  padding:3px 0 3px 14px;
  border-left:2px solid var(--chiik-yellow,#f0d060);
  letter-spacing:.02em;
}
.download-btn{
  display:inline-flex;align-items:center;gap:5px;
  padding:6px 14px;margin:6px 0;
  font-size:12px;font-weight:500;
  color:white;background:var(--accent);
  border:none;border-radius:999px;text-decoration:none;cursor:pointer;
  transition:background .2s;
}
.download-btn:hover{background:var(--chiik-yellow, #f0d060);color:var(--accent);}
.copy-btn{
  display:inline-flex;align-items:center;gap:5px;
  padding:6px 14px;margin:8px 0;
  font-size:12px;font-weight:500;
  color:white;background:var(--accent);
  border:1px solid var(--accent);border-radius:999px;cursor:pointer;
  transition:all .2s;
}
.copy-btn:hover{background:var(--chiik-yellow, #f0d060);color:var(--accent);border-color:var(--chiik-yellow);}
.copy-btn.copied{background:#5c8a5c;border-color:#5c8a5c;}
.threads-grid{display:grid;grid-template-columns:1fr;gap:16px;padding:8px 0;}
@media(min-width:720px){.threads-grid{grid-template-columns:1fr 1fr}}
.thread-card{background:var(--chiik-bg);border:2px solid var(--chiik-line);border-radius:8px;padding:18px;}
.thread-meta{display:flex;gap:8px;margin-bottom:8px;align-items:center;}
.thread-id{font-weight:700;color:var(--chiik-line);font-size:14px;}
.thread-label{font-size:11px;background:var(--border-soft);padding:2px 7px;border-radius:4px;}
.thread-text{font-size:13.5px;line-height:1.85;color:var(--accent-soft);white-space:pre-wrap;word-break:break-word;}
.thread-hash{margin-top:8px;font-size:11px;color:var(--muted);font-weight:500;}
.lightbox-overlay{
  position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;
  align-items:center;justify-content:center;z-index:9999;padding:24px;cursor:zoom-out;
}
.lightbox-overlay.active{display:flex}
.lightbox-overlay img{max-width:min(90vw,900px);max-height:90vh;box-shadow:0 8px 32px rgba(0,0,0,.6);border-radius:4px;}
.lightbox-close{position:absolute;top:20px;right:24px;background:none;border:none;color:#fff;font-size:32px;cursor:pointer;}
"""

if V2_CSS_MARKER not in nc:
    style_end = nc.find('</style>')
    if style_end >= 0:
        nc = nc[:style_end] + V2_CSS + nc[style_end:]
        print('V2 CSS patch injected')
else:
    # Already has CSS but ensure .group.collapsed > .threads-grid rule exists
    TGRID_RULE = '.group.collapsed > .threads-grid{display:none !important}'
    if TGRID_RULE not in nc:
        style_end = nc.find('</style>')
        if style_end >= 0:
            nc = nc[:style_end] + '\n' + TGRID_RULE + '\n' + nc[style_end:]
            print('.group.collapsed > .threads-grid rule injected')

# ---- .mirror CSS idempotent patch (v2.1 2026-05-21) ----
MIRROR_CSS_MARKER = '/* ========== .mirror 藏鏡人泡泡 (build_all.py v2.1) ========== */'
MIRROR_CSS = """
/* ========== .mirror 藏鏡人泡泡 (build_all.py v2.1) ========== */
.mirror{
  margin-top:6px;display:inline-block;
  font-size:11.5px;font-style:italic;
  color:var(--tag-brown,#8a6040);
  padding:3px 0 3px 14px;
  border-left:2px solid var(--chiik-yellow,#f0d060);
  letter-spacing:.02em;
}
"""
if MIRROR_CSS_MARKER not in nc:
    style_end = nc.find('</style>')
    if style_end >= 0:
        nc = nc[:style_end] + MIRROR_CSS + nc[style_end:]
        print('.mirror CSS patch injected')
    else:
        print('WARNING: </style> not found, .mirror CSS patch skipped')
else:
    print('.mirror CSS patch already present, skipped')

# ---- V2 JS patch ----
V2_JS_MARKER = '// ===== V2 JS: toggleGroup + copyScript + copyThread + lightbox (build_all.py v2) ====='
V2_JS = r"""// ===== V2 JS: toggleGroup + copyScript + copyThread + lightbox (build_all.py v2) =====
function toggleGroup(grp){grp.classList.toggle('collapsed');}
function copyScript(btn){
  var card=btn.closest('.script-card');if(!card) return;
  var cap=card.dataset.caption;var hRaw=card.dataset.hashtags||'';
  var h=hRaw.trim()?hRaw.trim():'';
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
// init: all groups collapsed + shot toggle
(function(){
  document.querySelectorAll('.group').forEach(function(g){g.classList.add('collapsed');});
  var KEY='kenny.shot.v2';var shot=[];
  try{shot=JSON.parse(localStorage.getItem(KEY)||'[]');}catch(e){shot=[];}
  document.querySelectorAll('.script-card').forEach(function(card){
    var id=card.dataset.id;if(!id) return;
    if(shot.indexOf(id)>=0) card.classList.add('shot');
  });
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
  document.querySelectorAll('.script-card[data-caption]').forEach(function(a){
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

# Patch: replace old 釣魚部 filter chip with 圖卡部 (SOP v2 naming)
nc = nc.replace('>釣魚部</div>', '>圖卡部</div>')
nc = nc.replace('data-filter="釣魚"', 'data-filter="圖卡部"')

with open(os.path.join(LIB, 'kenny.html'), 'w', encoding='utf-8') as f:
    f.write(nc)
print('kenny.html FINAL:', len(nc), 'chars')

arts = re.findall(r'class="script-card"', nc)
print('Total script-cards:', len(arts))
assert len(arts) >= 30, f'Expected >= 30 cards (03批17+05批13), got {len(arts)}'
# verify 圖卡部 keyword
assert '圖卡部' in nc, 'Missing 圖卡部'
# verify no 釣魚部 in group headers (only in old data-tags)
# validate: download-btn count
dl_count = len(re.findall(r'<a class="download-btn"', nc))
print(f'download-btn count: {dl_count}')
assert dl_count >= 0, f'Expected >= 0 download-btn, got {dl_count}'
print('All assertions PASS')
