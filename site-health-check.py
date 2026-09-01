#!/usr/bin/env python3
"""
site-health-check.py — EDC EU POST 網站健檢腳本
產出結構化的健康數據，供 eu-site-maintenance agent 分析。

用法：
  python eu-intel-site/site-health-check.py
  python eu-intel-site/site-health-check.py --json    # 輸出 JSON 格式
  python eu-intel-site/site-health-check.py --check-links  # 含死連結檢查（較慢）
"""

import os
import sys
import re
import json
import glob
from html import unescape as html_unescape   # 注意：函式內有名為 html 的區域變數，不能 import html
from datetime import datetime, timedelta
from collections import Counter

SITE_DIR = os.path.dirname(os.path.abspath(__file__))
INTEL_DIR = os.path.join(SITE_DIR, '..', 'eu-intel')
MONITOR_LOG_DIR = os.path.join(SITE_DIR, '..', 'share', 'monitor-logs')
WEEKLY_DIR = os.path.join(INTEL_DIR, 'weekly')
EMAILS_DIR = os.path.join(INTEL_DIR, 'emails')
SENT_LOG = os.path.join(INTEL_DIR, '.sent_log')

# 週報回溯檢查的週數（約兩個月，足以看出連續漏產但不會翻到專案初期）
WEEKLY_LOOKBACK = 8


def get_days_computer_on():
    """回傳「當天電腦有開、排程有跑」的日期集合。

    訊號來源：share/monitor-logs/monitor-YYYY-MM-DD.log。KIRO monitor 每小時跑一次，
    只要當天電腦有開機、排程有觸發就會留下 log。沒有 log ⇒ 當天電腦沒開（休假/關機），
    這種日子沒產日報是「合理缺席」，不該算內容空窗。

    回傳空集合代表拿不到 monitor log（例如 starter-kit 複本），呼叫端應退回舊行為
    （不因此判斷放假），以免把真實空窗蓋掉。
    """
    days = set()
    if not os.path.isdir(MONITOR_LOG_DIR):
        return days
    for path in glob.glob(os.path.join(MONITOR_LOG_DIR, 'monitor-*.log')):
        m = re.search(r'monitor-(\d{4}-\d{2}-\d{2})\.log$', os.path.basename(path))
        if m:
            days.add(m.group(1))
    return days


def read_sent_ok_files():
    """回傳 .sent_log 裡曾有 OK 紀錄的檔名集合，以及每個檔名最新狀態。

    auto-send.py 的格式：filename | timestamp | status | note
    同一檔名可能有多行（FAIL 後重試），只要出現過 OK 就算寄成功。
    """
    ok_files = set()
    latest_status = {}
    if not os.path.exists(SENT_LOG):
        return ok_files, latest_status
    with open(SENT_LOG, 'r', encoding='utf-8') as f:
        for line in f:
            parts = [p.strip() for p in line.strip().split('|')]
            if len(parts) < 3:
                continue
            name, status = parts[0], parts[2]
            if status == 'OK':
                ok_files.add(name)
            latest_status[name] = status
    return ok_files, latest_status


def check_weekly_coverage():
    """檢查最近 WEEKLY_LOOKBACK 週的週報是否都有產出。

    日報覆蓋檢查（analyze_articles）只看 type == 'daily'，週報漏產它偵測不到，
    所以這裡獨立檢查 weekly/ 目錄的 ISO 週編號。
    當週（今天所在的週）若還沒到週五就不算缺，週五當天也不算（可能還沒跑）。
    """
    now = datetime.now()
    existing = set()
    for path in glob.glob(os.path.join(WEEKLY_DIR, 'weekly-report-*.html')):
        m = re.search(r'weekly-report-(\d{4})-W(\d{1,2})\.html$', os.path.basename(path))
        if m:
            existing.add((int(m.group(1)), int(m.group(2))))

    days_computer_on = get_days_computer_on()
    have_monitor_data = len(days_computer_on) > 0

    missing = []
    off_weeks = []
    # 從上一週往回數 WEEKLY_LOOKBACK 週（本週尚未收尾，不算缺）
    for i in range(1, WEEKLY_LOOKBACK + 1):
        ref = now - timedelta(weeks=i)
        iso_year, iso_week, _ = ref.isocalendar()
        if (iso_year, iso_week) in existing:
            continue
        # 該週的週五（週報產出日）
        friday = ref + timedelta(days=(4 - ref.isoweekday()))
        friday_str = friday.strftime('%Y-%m-%d')
        label = f"{iso_year}-W{iso_week:02d}"
        if have_monitor_data and friday_str not in days_computer_on:
            off_weeks.append({'week': label, 'friday': friday_str})
        else:
            missing.append({'week': label, 'friday': friday_str})

    return {
        'weeks_checked': WEEKLY_LOOKBACK,
        'weekly_reports_total': len(existing),
        'missing_weeks': missing,
        'off_weeks_computer_off': off_weeks,
    }


def check_delivery_status(recent_days=30):
    """比對「.eml 產出」與「.sent_log 有 OK」，抓出產了沒寄的信。

    這是 2026-08 發現 W31 週報產出後未寄送才補上的檢查：
    resend-pending.py 只掃當日 daily + threads，週報寄送失敗沒有任何自動偵測。
    """
    ok_files, latest_status = read_sent_ok_files()
    cutoff = datetime.now() - timedelta(days=recent_days)

    unsent = []
    if os.path.isdir(EMAILS_DIR):
        for path in sorted(glob.glob(os.path.join(EMAILS_DIR, '*.eml'))):
            name = os.path.basename(path)
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            if mtime < cutoff:
                continue
            if name in ok_files:
                continue
            unsent.append({
                'file': name,
                'created': mtime.strftime('%Y-%m-%d %H:%M'),
                'log_status': latest_status.get(name, 'NONE'),  # NONE = auto-send 根本沒被呼叫
                'kind': 'weekly' if 'weekly' in name else
                        ('threads' if 'threads' in name else
                         ('daily' if 'daily' in name else 'other')),
            })

    return {
        'window_days': recent_days,
        'sent_log_exists': os.path.exists(SENT_LOG),
        'unsent_count': len(unsent),
        'unsent': unsent,
    }


def check_file_sizes():
    """檢查網站檔案大小"""
    files = ['index.html', 'articles.json', 'ec-logo.png']
    sizes = {}
    for f in files:
        path = os.path.join(SITE_DIR, f)
        if os.path.exists(path):
            sizes[f] = os.path.getsize(path)
    return sizes


def load_articles():
    """載入 articles.json"""
    path = os.path.join(SITE_DIR, 'articles.json')
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def analyze_articles(articles):
    """分析文章資料"""
    now = datetime.now()
    cutoff_30d = now - timedelta(days=30)

    recent = [a for a in articles if datetime.strptime(a['date'], '%Y-%m-%d') >= cutoff_30d]

    # Tag 統計
    tag_counter = Counter()
    for a in recent:
        tag_counter.update(a.get('tags', []))

    # 國家熱度統計：用關鍵字掃 title + summary + public_impact。
    # （舊版是抓 summary 前 50 字的國旗 emoji，但 summary 格式改成純文字條列後
    #   早就不放國旗了，計數器恆為空 → 這欄變成死欄位，故改關鍵字法。）
    COUNTRY_KEYWORDS = (
        '歐盟', '德國', '法國', '義大利', '西班牙', '英國', '荷蘭', '波蘭', '比利時',
        '瑞典', '愛爾蘭', '奧地利', '捷克', '丹麥', '葡萄牙', '希臘', '匈牙利',
        '羅馬尼亞', '瑞士', '挪威', '芬蘭', '土耳其', '美國', '中國', '日本',
        '印度', '越南',
    )
    country_counter = Counter()
    for a in recent:
        blob = ' '.join(str(a.get(f) or '') for f in ('title', 'summary', 'public_impact'))
        for c in COUNTRY_KEYWORDS:
            if c in blob:
                country_counter[c] += 1

    # 公定假日白名單（不產日報的合理日期）。日報作者在台灣，故 EU + 台灣假日都算合理缺席。
    HOLIDAYS = {
        # ── EU 2026 ──
        '2026-01-01',  # New Year
        '2026-04-03',  # Good Friday
        '2026-04-06',  # Easter Monday
        '2026-05-01',  # Labour Day
        '2026-05-14',  # Ascension Day
        '2026-05-25',  # Whit Monday
        '2026-12-24',  # Christmas Eve
        '2026-12-25',  # Christmas Day
        '2026-12-26',  # Boxing Day
        '2026-12-31',  # New Year's Eve
        # ── 台灣 2026（作者所在地，依行政院人事行政總處公告）──
        '2026-02-16', '2026-02-17', '2026-02-18', '2026-02-19', '2026-02-20',  # 春節
        '2026-02-27', '2026-02-28',  # 和平紀念日
        '2026-04-03', '2026-04-06',  # 兒童節/清明（部分與 EU 重疊）
        '2026-06-19',  # 端午節
        '2026-09-25',  # 中秋節
        '2026-10-09', '2026-10-10',  # 國慶日
        # ── EU 2027（提前登記，避免明年誤報）──
        '2027-01-01',
        '2027-03-26',  # Good Friday
        '2027-03-29',  # Easter Monday
        '2027-05-01',
        '2027-05-06',  # Ascension Day
        '2027-05-17',  # Whit Monday
        '2027-12-24',
        '2027-12-25',
        '2027-12-26',
        '2027-12-31',
    }

    # 「電腦有開」的日子（有 monitor log）。空集合＝拿不到 log，退回舊行為（不靠此判斷放假）。
    days_computer_on = get_days_computer_on()
    have_monitor_data = len(days_computer_on) > 0

    # 覆蓋日期檢查：最近 20 個工作日是否都有日報
    # 跳過三種合理缺席：① 公定假日 ② 電腦沒開（無 monitor log）③ 今天(尚未產出)
    dates_covered = set(a['date'] for a in recent if a['type'] == 'daily')
    missing_days = []
    skipped_off_days = []  # 電腦沒開而略過的工作日，供報告區隔「真空窗 vs 放假」
    check_date = now.date()
    business_days_checked = 0
    while business_days_checked < 20:
        if check_date.weekday() < 5:  # 週一~週五
            date_str = check_date.strftime('%Y-%m-%d')
            if date_str not in dates_covered and check_date < now.date():
                if date_str in HOLIDAYS:
                    pass  # 公定假日，合理缺席
                elif have_monitor_data and date_str not in days_computer_on:
                    skipped_off_days.append(date_str)  # 電腦沒開，合理缺席
                else:
                    missing_days.append(date_str)  # 真空窗：電腦有開卻沒產出
            business_days_checked += 1
        check_date -= timedelta(days=1)

    # 來源統計
    total_sources = sum(len(a.get('sources', [])) for a in recent)
    sources_per_article = total_sources / len(recent) if recent else 0

    # 無標籤文章 = build.py 的 TAG_MAP 沒收錄該 css class（靜默失真）。
    # 網站上這些文章任何分類都篩不到，只有搜尋才找得到。
    untagged_recent = [
        {'date': a['date'], 'type': a.get('type', ''), 'title': (a.get('title') or '')[:60]}
        for a in recent if not a.get('tags')
    ]
    untagged_total = sum(1 for a in articles if not a.get('tags'))

    return {
        'total_articles': len(articles),
        'last_30d_articles': len(recent),
        'tag_distribution': dict(tag_counter.most_common()),
        'untagged_30d': untagged_recent,
        'untagged_total': untagged_total,
        'top_countries': dict(country_counter.most_common(5)),
        'missing_business_days': missing_days[:10],
        'off_days_computer_off': skipped_off_days[:10],  # 電腦沒開的工作日（放假/關機，非故障）
        'total_sources_30d': total_sources,
        'avg_sources_per_article': round(sources_per_article, 2),
        'latest_date': articles[0]['date'] if articles else None,
        'oldest_date': articles[-1]['date'] if articles else None,
    }


def check_focus_card():
    """檢查「🔥 X 月焦點專題」卡片的月份是否還是當月。

    2026-09-01 月檢的教訓：這張卡停在「7 月焦點專題」掛了整整兩個月沒人發現，
    因為 check_sidebar_dates() 只掃「📅 關鍵日期總覽」那一張 sidebar-card。
    卡片標題自帶月份，直接比對即可，成本近乎零。
    """
    html_path = os.path.join(SITE_DIR, 'index.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        page = f.read()

    m = re.search(r'🔥\s*(\d{1,2})\s*月焦點專題', page)
    if not m:
        return {'found': False}

    card_month = int(m.group(1))
    now = datetime.now()
    # 月份差（考慮跨年：卡片寫 12 月而現在是 1 月 → 落後 1 個月，不是領先 11 個月）
    behind = (now.month - card_month) % 12
    return {
        'found': True,
        'card_month': card_month,
        'current_month': now.month,
        'months_behind': behind,
        'stale': behind != 0,
    }


def check_sidebar_dates():
    """檢查關鍵日期 sidebar 的狀態"""
    html_path = os.path.join(SITE_DIR, 'index.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()

    # 抓出所有 sidebar-date 條目（只看第一個 sidebar-card，不含 promo）
    sidebar_section = re.search(
        r'📅 關鍵日期總覽.*?</div>\s*</div>',
        html, re.DOTALL
    )
    if not sidebar_section:
        return {'error': 'Cannot find sidebar section'}

    section_html = sidebar_section.group(0)
    # 先抓「整個 <strong>…</strong> + 後面的敘述」，日期解析交給下面的 _latest_date()。
    # （舊版 regex 只吃單一日期 `<strong>(\d+/\d+)</strong>`，遇到 `9/9 / 9/16`、
    #   `10/21 / 10/28`、`10/15-1/14` 這種雙日期／區間寫法會靜默丟棄整筆條目 ——
    #   而這些偏偏都是旺季到倉死線／附加費，過期後永遠不會被報出來。）
    raw_entries = re.findall(
        r'<strong>([^<]+)</strong>\s*([^<]+)',
        section_html
    )

    now = datetime.now()

    def _latest_date(label):
        """從一個 sidebar 標籤裡取出「最後一個」日期。

        支援 `9/1`、`2027/1/1`、`2027/2`、`9/9 / 9/16`（雙日期）、`10/15-1/14`（跨年區間）。
        判斷過期要看區間結束日，所以取最晚的那個；區間內若後一個日期比前一個小
        （10/15 → 1/14），視為跨年，年份 +1。
        """
        tokens = re.findall(r'\d{1,4}/\d{1,2}(?:/\d{1,2})?', label)
        found = []
        prev = None
        for tok in tokens:
            parts = tok.split('/')
            try:
                if len(parts) == 3:
                    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                elif len(parts) == 2 and len(parts[0]) == 4:   # 2027/2
                    year, month, day = int(parts[0]), int(parts[1]), 1
                elif len(parts) == 2:                          # 9/16
                    year, month, day = now.year, int(parts[0]), int(parts[1])
                    if prev is not None and (month, day) < prev:  # 10/15-1/14 跨年
                        year += 1
                else:
                    continue
                found.append(datetime(year, month, day))
                prev = (month, day)
            except ValueError:
                continue
        return max(found) if found else None

    expired = []
    recent_past = []
    upcoming_2w = []
    future = []
    unparsed = []

    for date_str, desc in raw_entries:
        event_date = _latest_date(date_str)
        if event_date is None:
            unparsed.append({'date': date_str.strip(), 'desc': desc.strip()})
            continue

        days_diff = (event_date - now).days
        # desc 直接取自 HTML，`&lt;` 這類實體要還原成 `<` 才好讀
        entry = {'date': date_str.strip(), 'desc': html_unescape(desc.strip()), 'days': days_diff}
        if days_diff < -14:
            expired.append(entry)
        elif days_diff < 0:
            # 剛過期但還沒滿 2 週：先留著（下次月檢才該清），但要列出來避免無聲消失
            recent_past.append(entry)
        elif days_diff <= 14:
            upcoming_2w.append(entry)
        else:
            future.append(entry)

    return {
        'raw_total': len(raw_entries),
        'unparsed': unparsed,
        'total_dates': len(raw_entries) - len(unparsed),
        'expired_over_2w': expired,
        'recent_past': recent_past,
        'upcoming_2w': upcoming_2w,
        'future': future,
    }


def check_dead_links(articles, sample_size=20):
    """檢查隨機樣本的來源連結是否還活著（簡易版）"""
    import urllib.request
    import urllib.error

    # 對 bot 友善度差的網域 — 這些會回 403/406 但連結其實是活的，跳過避免誤判
    BOT_HOSTILE_DOMAINS = {
        'reddit.com', 'www.reddit.com',
        'euronews.com', 'www.euronews.com',
        'nytimes.com', 'www.nytimes.com',
        'bloomberg.com', 'www.bloomberg.com',
        'ft.com', 'www.ft.com',
        'wsj.com', 'www.wsj.com',
        'facebook.com', 'www.facebook.com',
        'instagram.com', 'www.instagram.com',
        'linkedin.com', 'www.linkedin.com',
        'threads.com', 'www.threads.com',
        'x.com', 'twitter.com',
    }

    # 從最近 30 天文章抽樣
    recent_sources = []
    for a in articles[:50]:
        for s in a.get('sources', []):
            recent_sources.append({'article': a['title'][:40], 'url': s['url'], 'name': s['name']})

    # 先過濾掉 bot-hostile 網域
    from urllib.parse import urlparse
    def is_checkable(url):
        try:
            host = urlparse(url).netloc.lower()
            return host not in BOT_HOSTILE_DOMAINS
        except Exception:
            return False

    checkable = [s for s in recent_sources if is_checkable(s['url'])]
    skipped_count = len(recent_sources) - len(checkable)

    # 抽樣檢查
    import random
    sample = random.sample(checkable, min(sample_size, len(checkable)))

    # 用 GET 而不是 HEAD（有些站 HEAD 會回 405），加真實 User-Agent
    UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

    dead_links = []
    for item in sample:
        try:
            req = urllib.request.Request(
                item['url'],
                headers={
                    'User-Agent': UA,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                }
            )
            urllib.request.urlopen(req, timeout=8)
        except urllib.error.HTTPError as e:
            # 只把 404 / 410 當真正的死連結；403/406/429 通常是反 bot 策略
            if e.code in (404, 410):
                dead_links.append({**item, 'status': e.code})
        except Exception as e:
            # Timeout、SSL 錯誤、DNS 等不計入死連結（可能是網路瞬斷）
            pass

    return {
        'sample_size': len(sample),
        'skipped_bot_hostile': skipped_count,
        'total_sources_in_pool': len(recent_sources),
        'dead_count': len(dead_links),
        'dead_links': dead_links,
    }


def main():
    check_links = '--check-links' in sys.argv
    output_json = '--json' in sys.argv

    report = {
        'timestamp': datetime.now().isoformat(),
        'file_sizes': check_file_sizes(),
    }

    articles = load_articles()
    report['content_analysis'] = analyze_articles(articles)
    report['weekly_coverage'] = check_weekly_coverage()
    report['delivery_status'] = check_delivery_status()
    report['sidebar_dates'] = check_sidebar_dates()
    report['focus_card'] = check_focus_card()

    if check_links:
        report['link_health'] = check_dead_links(articles)

    if output_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("  EDC EU POST 網站健檢報告")
        print(f"  時間: {report['timestamp']}")
        print("=" * 60)
        print()

        print("📁 檔案大小")
        for f, size in report['file_sizes'].items():
            print(f"   {f:25s} {size:>10,} bytes ({size/1024:.1f} KB)")
        print()

        ca = report['content_analysis']
        print("📊 最近 30 天內容分析")
        print(f"   總文章數: {ca['total_articles']}")
        print(f"   最近 30 天: {ca['last_30d_articles']}")
        print(f"   最新日期: {ca['latest_date']}")
        print(f"   每篇平均來源數: {ca['avg_sources_per_article']}")
        print()
        print(f"   分類分布:")
        for tag, count in ca['tag_distribution'].items():
            print(f"      {tag}: {count}")
        print()
        print(f"   最常提及國家: {list(ca['top_countries'].keys())}")
        print()
        if ca['missing_business_days']:
            print(f"   ⚠️ 真空窗（電腦有開卻沒產出，需追排程）:")
            for d in ca['missing_business_days']:
                print(f"      {d}")
        else:
            print(f"   ✅ 最近 20 個工作日無真空窗")
        if ca['off_days_computer_off']:
            print(f"   💤 電腦沒開（放假/關機，非故障）: {', '.join(ca['off_days_computer_off'])}")
        print()

        if ca['untagged_30d']:
            print(f"   ⚠️ 無分類標籤（build.py TAG_MAP 可能漏收 css class）: "
                  f"近 30 天 {len(ca['untagged_30d'])} 則 / 全站 {ca['untagged_total']} 則")
            for a in ca['untagged_30d'][:10]:
                print(f"      {a['date']} [{a['type']}] {a['title']}")
        else:
            print(f"   ✅ 近 30 天文章全部有分類標籤")
        print()

        wc = report['weekly_coverage']
        print("📰 週報覆蓋")
        print(f"   週報總數: {wc['weekly_reports_total']}（回溯檢查最近 {wc['weeks_checked']} 週）")
        if wc['missing_weeks']:
            print(f"   ⚠️ 缺週報（電腦有開卻沒產出，需追排程）:")
            for w in wc['missing_weeks']:
                print(f"      {w['week']}（週五 {w['friday']}）")
        else:
            print(f"   ✅ 回溯期內週報無缺漏")
        if wc['off_weeks_computer_off']:
            print(f"   💤 週五電腦沒開: "
                  f"{', '.join(w['week'] for w in wc['off_weeks_computer_off'])}")
        print()

        ds = report['delivery_status']
        print("📮 寄送狀態（.eml 產出 vs .sent_log 有 OK）")
        if not ds['sent_log_exists']:
            print(f"   ⚠️ 找不到 .sent_log，無法驗證寄送")
        elif ds['unsent']:
            print(f"   ⚠️ 產出但未寄送 {ds['unsent_count']} 封（近 {ds['window_days']} 天）:")
            for u in ds['unsent']:
                note = "auto-send 未被呼叫" if u['log_status'] == 'NONE' else f"最新狀態 {u['log_status']}"
                print(f"      [{u['kind']}] {u['file']}（產出 {u['created']}，{note}）")
            print(f"   → 補寄: python eu-intel/auto-send.py --file eu-intel/emails/<檔名> --force")
            print(f"      注意 auto-send.py 會直接 Send()，不是開草稿，寄前先確認收件人")
        else:
            print(f"   ✅ 近 {ds['window_days']} 天所有 .eml 都有寄送成功紀錄")
        print()

        fc = report['focus_card']
        print("🔥 焦點專題卡片")
        if not fc.get('found'):
            print("   ⚠️ 找不到「🔥 X 月焦點專題」卡片（標題被改過？請確認 index.html）")
        elif fc['stale']:
            print(f"   ⚠️ 卡片仍寫「{fc['card_month']} 月」，落後 {fc['months_behind']} 個月"
                  f"（當月 {fc['current_month']} 月）→ 三個專題項目也要一併換掉")
        else:
            print(f"   ✅ 已是當月（{fc['current_month']} 月）")
        print()

        sd = report['sidebar_dates']
        print("📅 關鍵日期 sidebar")
        print(f"   總條目數: {sd['total_dates']} / {sd.get('raw_total', sd['total_dates'])}")
        if sd.get('unparsed'):
            print(f"   ⚠️ 有 {len(sd['unparsed'])} 筆條目解析不出日期（不會被納入過期偵測）:")
            for u in sd['unparsed']:
                print(f"      <strong>{u['date']}</strong> {u['desc']}")
        if sd['expired_over_2w']:
            print(f"   ⚠️ 過期超過 2 週（建議清理）:")
            for e in sd['expired_over_2w']:
                print(f"      {e['date']} - {e['desc']} (過期 {-e['days']} 天)")
        if sd.get('recent_past'):
            print(f"   🕐 剛過期未滿 2 週（先留著，下次月檢再清）:")
            for e in sd['recent_past']:
                print(f"      {e['date']} - {e['desc']} (過期 {-e['days']} 天)")
        if sd['upcoming_2w']:
            print(f"   🔥 兩週內即將發生:")
            for e in sd['upcoming_2w']:
                print(f"      {e['date']} - {e['desc']} ({e['days']} 天後)")
        if not sd['expired_over_2w'] and not sd['upcoming_2w']:
            print(f"   ✅ sidebar 日期狀態正常")
        print()

        if check_links:
            lh = report['link_health']
            print("🔗 連結健康（隨機抽樣）")
            print(f"   抽樣數: {lh['sample_size']}")
            print(f"   死連結: {lh['dead_count']}")
            if lh['dead_links']:
                for dl in lh['dead_links']:
                    print(f"      ❌ {dl['name']} [{dl['status']}]")
                    print(f"         {dl['url']}")
            else:
                print(f"   ✅ 抽樣連結全部正常")
            print()


if __name__ == '__main__':
    main()
