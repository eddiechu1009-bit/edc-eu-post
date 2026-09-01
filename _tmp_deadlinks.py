#!/usr/bin/env python3
"""One-off: full scan of every unique source URL in the last 30 days."""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timedelta
from urllib.parse import urlparse
from collections import Counter

SITE = os.path.dirname(os.path.abspath(__file__))
BOT_HOSTILE = {
    'reddit.com','www.reddit.com','euronews.com','www.euronews.com',
    'nytimes.com','www.nytimes.com','bloomberg.com','www.bloomberg.com',
    'ft.com','www.ft.com','wsj.com','www.wsj.com','facebook.com','www.facebook.com',
    'instagram.com','www.instagram.com','linkedin.com','www.linkedin.com',
    'threads.com','www.threads.com','x.com','twitter.com',
}
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

arts = json.load(open(os.path.join(SITE, 'articles.json'), encoding='utf-8'))
cutoff = datetime.now() - timedelta(days=30)
recent = [a for a in arts if datetime.strptime(a['date'], '%Y-%m-%d') >= cutoff]

seen = {}
for a in recent:
    for s in a.get('sources', []):
        seen.setdefault(s['url'], {'date': a['date'], 'name': s['name']})

checkable = {u: v for u, v in seen.items()
             if urlparse(u).netloc.lower() not in BOT_HOSTILE}
print(f"unique={len(seen)} checkable={len(checkable)} skipped={len(seen)-len(checkable)}", flush=True)

dead, other = [], Counter()
for i, (url, meta) in enumerate(sorted(checkable.items()), 1):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5'})
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            dead.append({**meta, 'url': url, 'status': e.code})
            print(f"DEAD {e.code} {meta['date']} {meta['name']} {url}", flush=True)
        else:
            other[e.code] += 1
    except Exception as e:
        other[type(e).__name__] += 1
    if i % 25 == 0:
        print(f"...{i}/{len(checkable)} dead={len(dead)}", flush=True)

print("\n=== RESULT ===")
print(f"checked={len(checkable)} dead={len(dead)} rate={len(dead)/max(1,len(checkable))*100:.1f}%")
print("non-fatal:", dict(other))
for d in dead:
    print(f"  {d['date']} | {d['name']} | {d['status']} | {d['url']}")
