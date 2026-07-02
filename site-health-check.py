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
from datetime import datetime, timedelta
from collections import Counter

SITE_DIR = os.path.dirname(os.path.abspath(__file__))
INTEL_DIR = os.path.join(SITE_DIR, '..', 'eu-intel')
MONITOR_LOG_DIR = os.path.join(SITE_DIR, '..', 'share', 'monitor-logs')


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

    # 國家旗幟統計（從 summary 開頭抓 emoji）
    country_pattern = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')
    country_counter = Counter()
    for a in recent:
        flags = country_pattern.findall(a.get('summary', '')[:50])
        country_counter.update(flags)

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

    return {
        'total_articles': len(articles),
        'last_30d_articles': len(recent),
        'tag_distribution': dict(tag_counter.most_common()),
        'top_countries': dict(country_counter.most_common(5)),
        'missing_business_days': missing_days[:10],
        'off_days_computer_off': skipped_off_days[:10],  # 電腦沒開的工作日（放假/關機，非故障）
        'total_sources_30d': total_sources,
        'avg_sources_per_article': round(sources_per_article, 2),
        'latest_date': articles[0]['date'] if articles else None,
        'oldest_date': articles[-1]['date'] if articles else None,
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
    # 格式：<strong>4/17</strong> Amazon FBA...
    dates = re.findall(
        r'<strong>(\d{1,4}/\d{1,2}(?:/\d{1,2})?)</strong>\s*([^<]+)',
        section_html
    )

    now = datetime.now()
    expired = []
    upcoming_2w = []
    future = []

    for date_str, desc in dates:
        try:
            # 支援 4/17, 2027/2 等格式
            parts = date_str.split('/')
            if len(parts) == 2:
                if len(parts[0]) == 4:  # 2027/2
                    year, month = int(parts[0]), int(parts[1])
                    day = 1
                else:  # 4/17
                    year, month, day = now.year, int(parts[0]), int(parts[1])
            elif len(parts) == 3:
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            else:
                continue

            event_date = datetime(year, month, day)
            days_diff = (event_date - now).days

            entry = {'date': date_str, 'desc': desc.strip(), 'days': days_diff}
            if days_diff < -14:
                expired.append(entry)
            elif 0 <= days_diff <= 14:
                upcoming_2w.append(entry)
            elif days_diff > 14:
                future.append(entry)
        except (ValueError, IndexError):
            continue

    return {
        'total_dates': len(dates),
        'expired_over_2w': expired,
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
    report['sidebar_dates'] = check_sidebar_dates()

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

        sd = report['sidebar_dates']
        print("📅 關鍵日期 sidebar")
        print(f"   總條目數: {sd['total_dates']}")
        if sd['expired_over_2w']:
            print(f"   ⚠️ 過期超過 2 週（建議清理）:")
            for e in sd['expired_over_2w']:
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
