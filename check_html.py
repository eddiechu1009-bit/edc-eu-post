"""Check if any article summary/title contains HTML that would break card structure"""
import json, re

with open('eu-intel-site/articles.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Simulate deduplicateAndMerge
daily = [a for a in data if a['type'] == 'daily']
weekly = [a for a in data if a['type'] == 'weekly']

for a in daily:
    a['featured'] = False

for w in weekly:
    clean = re.sub(r'【週報\s*W\d+】', '', w['title']).strip()
    matched = False
    for d in daily:
        words_a = set(re.sub(r'[^\w\u4e00-\u9fff]', ' ', d['title']).split())
        words_b = set(re.sub(r'[^\w\u4e00-\u9fff]', ' ', clean).split())
        words_a = {w for w in words_a if len(w) > 1}
        words_b = {w for w in words_b if len(w) > 1}
        if not words_a or not words_b:
            continue
        overlap = len(words_a & words_b)
        if overlap / min(len(words_a), len(words_b)) >= 0.35:
            d['featured'] = True
            matched = True
            break
    if not matched:
        w['featured'] = True
        daily.append(w)

daily.sort(key=lambda a: (a['date'], not a.get('featured', False)), reverse=True)
articles = daily

print(f"Total articles after merge: {len(articles)}")

# Check ALL articles for problematic content
problems_found = 0
for i, a in enumerate(articles):
    issues = []
    for field in ['title', 'summary', 'impact', 'action']:
        val = a.get(field, '')
        if not val:
            continue
        # Check for HTML tags that would break card div structure
        if re.search(r'</?(div|table|tr|td|p|h[1-6]|section|article|main|body|html)', val, re.I):
            issues.append(f"{field} has block HTML tags")
        # Check for unclosed tags
        opens = len(re.findall(r'<[a-z]', val, re.I))
        closes = len(re.findall(r'</', val))
        if opens != closes:
            issues.append(f"{field} has unbalanced tags (open={opens} close={closes})")
        # Check for backticks (break template literals)
        if '`' in val:
            issues.append(f"{field} has backtick")
    
    if issues:
        problems_found += 1
        tags_str = ','.join(a['tags'])
        print(f"\n❌ Article {i} [{a['date']}] [{tags_str}]: {a['title'][:50]}")
        for issue in issues:
            print(f"   {issue}")

if problems_found == 0:
    print("\n✅ No HTML structure problems found in any article")
else:
    print(f"\n⚠️ Found {problems_found} articles with potential issues")
