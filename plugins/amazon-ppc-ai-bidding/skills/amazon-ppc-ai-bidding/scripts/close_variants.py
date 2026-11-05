#!/usr/bin/env python3
"""Close-variant matching for Amazon negatives and exact keywords.

Amazon applies close variants (plurals, "book marks" vs "bookmarks", "markers"/"marks") to
NEGATIVE keywords as well as positive exact ones. A negative that is a close variant of an
exact campaign's own keyword switches that campaign off for its own search, silently.
Learned on the bookmarks pilot, 2026-10-17: Cross "bible bookmark" at a $1.30 bid had zero
impressions from 2026-07-10 because its ad group held a negative exact "bible bookmarks".
A NEGATIVE PHRASE blocks every search that contains its words in order, so a one-word phrase
negative can switch an exact campaign off too: on the notebooks onboarding (2026-10-17) the
exact campaigns "notebooks for work", "cute notebooks for women" and "notebooks for college
students" each held a phrase negative "for", and "aesthetic notebooks" a phrase "aesthetic".

CLI:
  python close_variants.py "<own keyword>" negatives.json
      negatives.json = MAP list_resources sp_negative_keywords output (raw or tool-result wrapper), read
      WITHOUT a keyword_text_filter: a stem filter misses one-word phrase negatives like "for"
      prints the ENABLED negatives that would block the keyword (archive these): exact negatives that
      are close variants of it, and phrase negatives whose words appear in it, in order
  python close_variants.py --pair "christian bookmarks" "christian book marks"
"""
import json
import re
import sys


def norm_cv(s):
    """Normalise a search/keyword for close-variant comparison (word order is kept)."""
    s = (s or '').lower().strip()
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    s = re.sub(r'\bbook\s+mark', 'bookmark', s)          # "book marks" -> "bookmarks"
    toks = []
    for t in s.split():
        t = re.sub(r'markers?$', 'mark', t)               # bookmarker(s) / marker(s) -> mark
        t = re.sub(r'marks?$', 'mark', t)                 # bookmarks -> bookmark
        if len(t) > 3 and t.endswith('ies'):
            t = t[:-3] + 'y'
        elif len(t) > 3 and t.endswith('es') and t[-3] in 'sxz':
            t = t[:-2]
        elif len(t) > 3 and t.endswith('s') and not t.endswith('ss'):
            t = t[:-1]
        toks.append(t)
    return ' '.join(toks)


def is_close_variant(a, b):
    return norm_cv(a) == norm_cv(b)


def phrase_blocks(phrase, keyword):
    """A negative phrase blocks a search that contains its words in order (close variants applied)."""
    p, k = norm_cv(phrase).split(), norm_cv(keyword).split()
    return bool(p) and any(k[i:i + len(p)] == p for i in range(len(k) - len(p) + 1))


def load_any(path):
    raw = open(path, encoding='utf-8').read().strip()
    o = json.loads(raw)
    if isinstance(o, list) and o and isinstance(o[0], dict) and 'text' in o[0]:
        o = json.loads(o[0]['text'])
    return o


def blocking_negatives(own_keyword, negatives):
    items = negatives.get('items', negatives) if isinstance(negatives, dict) else negatives
    out = []
    for n in items or []:
        if str(n.get('state', 'ENABLED')).upper() != 'ENABLED':
            continue
        txt = n.get('keywordText') or n.get('keyword') or ''
        phrase = 'PHRASE' in str(n.get('matchType') or '').upper()
        if (phrase and phrase_blocks(txt, own_keyword)) or (not phrase and is_close_variant(txt, own_keyword)):
            out.append(n)
    return out


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--pair':
        a, b = sys.argv[2], sys.argv[3]
        print(json.dumps({'a': norm_cv(a), 'b': norm_cv(b), 'close_variant': is_close_variant(a, b)}))
        sys.exit(0)
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    hits = blocking_negatives(sys.argv[1], load_any(sys.argv[2]))
    print(json.dumps([{'keywordId': h.get('keywordId'), 'keywordText': h.get('keywordText'), 'adGroupId': h.get('adGroupId'),
                       'matchType': h.get('matchType')} for h in hits], indent=1))
