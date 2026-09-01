#!/usr/bin/env python3
"""One-off: 30-day country / topic keyword analysis for the monthly review."""
import json, os, sys
from datetime import datetime, timedelta
from collections import Counter

SITE = os.path.dirname(os.path.abspath(__file__))
arts = json.load(open(os.path.join(SITE, 'articles.json'), encoding='utf-8'))
cutoff = datetime.now() - timedelta(days=30)
recent = [a for a in arts if datetime.strptime(a['date'], '%Y-%m-%d') >= cutoff]

def blob(a):
    return ' '.join([a.get('title') or '', a.get('summary') or '',
                     a.get('public_impact') or '', a.get('public_action') or ''])

COUNTRIES = {
    'EU/歐盟': ['歐盟', '歐元區', 'EU '],
    '德國': ['德國', '德 ', 'Bundes'],
    '英國': ['英國', 'UK', 'HMRC', 'BoE'],
    '美國': ['美國', 'Fed', '聯準會'],
    '法國': ['法國'],
    '中國': ['中國', '中國大陸'],
    '西班牙': ['西班牙'],
    '義大利': ['義大利'],
    '荷蘭': ['荷蘭'],
    '波蘭': ['波蘭'],
    '瑞典': ['瑞典'],
    '日本': ['日本'],
    '土耳其': ['土耳其'],
    '愛爾蘭': ['愛爾蘭'],
    '比利時': ['比利時'],
}
TOPICS = {
    '通膨 / CPI / HICP': ['通膨', 'CPI', 'HICP', 'PPI', '物價'],
    'Amazon 平台政策 / FBA / FBM': ['Amazon', 'FBA', 'FBM', 'AWD', 'OTDR'],
    'ECB / 利率': ['ECB', '歐洲央行', '利率', '降息', '升息'],
    '關稅 / 貿易協議': ['關稅', '貿易協議', 'tariff'],
    '物流 / 運價 / 供應鏈': ['運價', '物流', '供應鏈', '海運', '倉儲'],
    '匯率 / EUR-USD': ['匯率', 'EUR/USD', '歐元兌', '歐元走'],
    '零售銷售 / 消費': ['零售銷售', '消費者信心', '買氣'],
    '能源 / 油價': ['油價', '能源', 'Brent', '天然氣'],
    'PPWR / 包裝 / EPR': ['PPWR', '包裝', 'EPR'],
    '就業 / 失業': ['就業', '失業'],
    'Temu / Shein / AliExpress': ['Temu', 'Shein', 'AliExpress'],
    'Q4 旺季 / 大促': ['旺季', 'Prime Big Deal', 'Black Friday', '黑五', 'BFCM', '大促'],
    'DSA / DMA 平台監管': ['DSA', 'DMA'],
    'PMI / 製造業': ['PMI', '製造業'],
    'GPSR / 產品安全': ['GPSR', '產品安全', '召回'],
    '海關改革 / EUR3 / 小包': ['海關', 'EUR3', '小包', 'M-PID'],
    'VAT / 稅務': ['VAT', '加值稅', '電子發票'],
    'DPP / ESPR / 永續': ['DPP', 'ESPR', '永續', '碳'],
    'AI Act / AI 監管': ['AI Act', 'AI 監管', 'AI 透明度'],
    'GDP / 成長': ['GDP'],
}

def count(mapping):
    c = Counter()
    for a in recent:
        b = blob(a)
        for k, kws in mapping.items():
            if any(kw in b for kw in kws):
                c[k] += 1
    return c

print(f"30d articles={len(recent)}  dates={min(a['date'] for a in recent)}~{max(a['date'] for a in recent)}")
by_type = Counter(a.get('type') for a in recent)
print("by type:", dict(by_type))
by_date = Counter(a['date'] for a in recent)
print("per-day counts:", dict(sorted(by_date.items())))
print("\n--- COUNTRIES ---")
for k, v in count(COUNTRIES).most_common():
    print(f"  {k}: {v}")
print("\n--- TOPICS ---")
for k, v in count(TOPICS).most_common():
    print(f"  {k}: {v}")

tags = Counter()
for a in recent:
    tags.update(a.get('tags', []))
print("\n--- TAGS ---", dict(tags.most_common()))
print("tag sum:", sum(tags.values()), "vs articles:", len(recent))

src = sum(len(a.get('sources', [])) for a in recent)
print(f"\nsources: total={src} avg={src/len(recent):.2f}")
low = [(a['date'], len(a.get('sources', [])), (a.get('title') or '')[:40])
       for a in recent if len(a.get('sources', [])) < 3]
print(f"articles with <3 sources: {len(low)}")
for x in low[:15]:
    print("   ", x)
