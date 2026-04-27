#!/usr/bin/env python3
"""
build.py — 從 eu-intel/ 目錄的 HTML 日報/週報自動解析新聞，
生成 articles.js 資料檔，供 index.html 使用。

用法：
  python3 eu-intel-site/build.py

流程：
  1. 掃描 eu-intel/daily-report-*.html 和 weekly-report-*.html
  2. 用 BeautifulSoup 解析每則新聞的標題、標籤、摘要、影響、行動、來源
  3. 輸出 eu-intel-site/articles.js（JSON 陣列）
  4. 同時更新 index.html 中的 articles 資料區塊（可選）
"""

import os
import re
import json
import glob
from html.parser import HTMLParser
from datetime import datetime

# ── 簡易 HTML 文字提取器（不依賴 BeautifulSoup）──
class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
        self.skip = False
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip = True
    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = False
    def handle_data(self, data):
        if not self.skip:
            self.result.append(data)
    def get_text(self):
        return ''.join(self.result).strip()

def extract_text(html_str):
    """從 HTML 片段提取純文字"""
    ext = TextExtractor()
    ext.feed(html_str)
    return ext.get_text()

# ── 標籤對應表 ──
TAG_MAP = {
    'tag-tax': '稅務',
    'tag-compliance': '合規',
    'tag-macro': '總經',
    'tag-platform': '平台',
    'tag-logistics': '物流',
    'tag-trade': '貿易',
}

# ── 顏色對應 ──
COLOR_CYCLE = ["#0369a1", "#dc2626", "#ea580c", "#7c3aed", "#0891b2"]

def parse_daily_report(filepath):
    """解析日報 HTML，回傳新聞列表"""
    # 從檔名提取日期
    basename = os.path.basename(filepath)
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', basename)
    if not date_match:
        return []
    date_str = date_match.group(1)

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    articles = []

    # 策略 1: 用 <!-- 新聞 N --> 或 <!-- 新聞 N: 描述 --> 註解分割（最可靠）
    news_blocks = re.findall(
        r'<!-- 新聞 \d+[^-]*-->\s*(.*?)(?=<!-- 新聞 \d+|<div class="divider">|<div class="key-dates">|$)',
        content, re.DOTALL
    )

    # 策略 2: 用 table + border-left 分割（email 格式）
    if not news_blocks:
        news_blocks = re.findall(
            r'<table[^>]*style="margin-bottom:\s*18px[^"]*"[^>]*>.*?<td[^>]*border-left:4px[^>]*>(.*?)</td>\s*</tr>\s*</table>',
            content, re.DOTALL
        )

    # 策略 3: 用 [N] 標題模式分割
    if not news_blocks:
        news_blocks = re.findall(
            r'(?:border-left:4px solid[^>]*>)(.*?)(?=border-left:4px solid|<div style="margin-top|<table[^>]*style="margin-top|$)',
            content, re.DOTALL
        )

    for i, block in enumerate(news_blocks):
        article = {
            'date': date_str,
            'type': 'daily',
            'tags': [],
            'title': '',
            'summary': '',
            'impact': '',
            'action': '',
            'sources': [],
            'color': COLOR_CYCLE[i % len(COLOR_CYCLE)]
        }

        # 提取標籤
        for css_class, tag_name in TAG_MAP.items():
            if css_class in block:
                article['tags'].append(tag_name)

        # 提取標題 — 多種格式
        title_match = re.search(r'class="news-title"[^>]*>(.*?)</span>', block, re.DOTALL)
        if not title_match:
            # table/email 格式: [1] 標題 <span...
            title_match = re.search(r'\[\d+\]\s*(.*?)(?:\s*<span|\s*$)', block, re.DOTALL)
        if title_match:
            article['title'] = extract_text(title_match.group(1)).strip()
            article['title'] = re.sub(r'^\[\d+\]\s*', '', article['title'])

        # 提取摘要
        summary_match = re.search(r'class="summary"[^>]*>(.*?)</div>', block, re.DOTALL)
        if not summary_match:
            summary_match = re.search(r'color:#334155[^>]*>(.*?)</div>', block, re.DOTALL)
        if summary_match:
            article['summary'] = extract_text(summary_match.group(1)).strip()

        # 提取 Impact
        impact_match = re.search(r'class="impact"[^>]*>(.*?)</div>', block, re.DOTALL)
        if not impact_match:
            impact_match = re.search(r'Impact:?</(?:strong|span)>\s*(.*?)</(?:div|td)>', block, re.DOTALL)
        if impact_match:
            text = extract_text(impact_match.group(1)).strip()
            text = re.sub(r'^[🎯\s]*(?:Impact:?\s*)?', '', text)
            article['impact'] = text

        # 提取 Action
        action_match = re.search(r'class="action"[^>]*>(.*?)</div>', block, re.DOTALL)
        if not action_match:
            action_match = re.search(r'Action:?</(?:strong|span)>\s*(.*?)</(?:div|td)>', block, re.DOTALL)
        if action_match:
            text = extract_text(action_match.group(1)).strip()
            text = re.sub(r'^[✅\s]*(?:Action:?\s*)?', '', text)
            article['action'] = text

        # 提取來源
        source_links = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block)
        for url, name in source_links:
            article['sources'].append({'name': extract_text(name), 'url': url})

        if article['title']:
            articles.append(article)

    return articles


def parse_weekly_report(filepath):
    """解析週報 HTML，回傳主題列表"""
    basename = os.path.basename(filepath)
    week_match = re.search(r'W(\d+)', basename)
    date_match = re.search(r'(\d{4})', basename)
    if not week_match or not date_match:
        return []

    week_num = int(week_match.group(1))
    year = int(date_match.group(1))

    # 用週五作為週報日期
    from datetime import datetime, timedelta
    jan1 = datetime(year, 1, 1)
    # ISO week: 找到該週的週五
    day_offset = (week_num - 1) * 7 + (4 - jan1.isoweekday())
    friday = jan1 + timedelta(days=day_offset)
    date_str = friday.strftime('%Y-%m-%d')

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    articles = []

    # 用 <!-- 主題 N --> 註解來分割區塊
    topic_blocks = re.findall(
        r'<!-- 主題 \d+ -->\s*<div class="topic">(.*?)(?=<!-- 主題 \d+ -->|<div class="divider">|<div class="action-list">)',
        content, re.DOTALL
    )

    # 備用：直接用 <div class="topic"> 分割
    if not topic_blocks:
        parts = re.split(r'<div class="topic">', content)
        topic_blocks = parts[1:]  # 跳過第一段（topic 之前的內容）

    for i, block in enumerate(topic_blocks):
        article = {
            'date': date_str,
            'type': 'weekly',
            'tags': [],
            'title': '',
            'summary': '',
            'impact': '',
            'action': '',
            'sources': [],
            'color': COLOR_CYCLE[i % len(COLOR_CYCLE)]
        }

        # 提取標籤
        for css_class, tag_name in TAG_MAP.items():
            if css_class in block:
                article['tags'].append(tag_name)

        # 提取標題
        title_match = re.search(r'class="topic-title"[^>]*>(.*?)</span>', block, re.DOTALL)
        if title_match:
            title = extract_text(title_match.group(1)).strip()
            article['title'] = f"【週報 W{week_num}】{title}"

        # 提取摘要
        summary_match = re.search(r'class="summary"[^>]*>(.*?)</div>', block, re.DOTALL)
        if summary_match:
            article['summary'] = extract_text(summary_match.group(1)).strip()

        # 提取 Impact
        impact_match = re.search(r'(?:賣家影響：|Impact：?)(.*?)(?:</div>|</td>)', block, re.DOTALL)
        if impact_match:
            article['impact'] = extract_text(impact_match.group(1)).strip()

        # 提取 Action
        action_match = re.search(r'(?:Action：?)(.*?)(?:</div>|</td>)', block, re.DOTALL)
        if action_match:
            article['action'] = extract_text(action_match.group(1)).strip()

        # 提取來源
        source_links = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block)
        for url, name in source_links:
            article['sources'].append({'name': extract_text(name), 'url': url})

        if article['title']:
            articles.append(article)

    return articles


def inject_into_html(output_dir, all_articles):
    """將 articles JSON 資料直接注入 index.html 的佔位符"""
    html_path = os.path.join(output_dir, 'index.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()

    # 產生壓縮的 JSON 字串
    json_str = json.dumps(all_articles, ensure_ascii=False)

    # 替換佔位符：/*__ARTICLES_JSON__*/[]/*__END_ARTICLES_JSON__*/
    pattern = r'/\*__ARTICLES_JSON__\*/.*?/\*__END_ARTICLES_JSON__\*/'
    replacement = f'/*__ARTICLES_JSON__*/{json_str}/*__END_ARTICLES_JSON__*/'
    new_html = re.sub(pattern, replacement, html, count=1)

    # 注入最後更新時間（以最新文章日期為準）
    latest_date = all_articles[0]['date'] if all_articles else datetime.now().strftime('%Y-%m-%d')
    update_pattern = r'<span id="lastUpdate">.*?</span>'
    update_replacement = f'<span id="lastUpdate">{latest_date}</span>'
    new_html = re.sub(update_pattern, update_replacement, new_html, count=1)

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(new_html)


def main():
    eu_intel_dir = os.path.join(os.path.dirname(__file__), '..', 'eu-intel')
    output_dir = os.path.dirname(__file__)

    all_articles = []

    # 解析日報（週報內容與日報重複，不另外解析）
    daily_files = sorted(glob.glob(os.path.join(eu_intel_dir, 'daily-report-*.html')), reverse=True)
    for f in daily_files:
        print(f"  📰 解析日報: {os.path.basename(f)}")
        all_articles.extend(parse_daily_report(f))

    # 按日期排序（最新在前）
    all_articles.sort(key=lambda a: a['date'], reverse=True)

    # 輸出 JSON
    output_path = os.path.join(output_dir, 'articles.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 已產出 {len(all_articles)} 則新聞 → {output_path}")

    # 注入資料到 index.html
    inject_into_html(output_dir, all_articles)
    print(f"   ✅ 已注入資料到 index.html")

    # 統計
    tags_count = {}
    for a in all_articles:
        for t in a['tags']:
            tags_count[t] = tags_count.get(t, 0) + 1
    print(f"   分類統計: {tags_count}")
    daily_count = sum(1 for a in all_articles if a['type'] == 'daily')
    weekly_count = sum(1 for a in all_articles if a['type'] == 'weekly')
    print(f"   日報: {daily_count} 則 | 週報: {weekly_count} 則")


if __name__ == '__main__':
    print("🔧 EU Intel Site Builder")
    print("=" * 40)
    main()
