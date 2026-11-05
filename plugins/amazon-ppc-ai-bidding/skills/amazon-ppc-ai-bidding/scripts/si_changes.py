#!/usr/bin/env python3
"""The morning check for hand changes in Scale Insights on AI products (Kim, 2026-10-27, decision 155).

On 2026-10-27 10:26 SGT a manual Scale Insights bid import raised about 4,700 bids by about 10% across the account, AI
products included, and turned one product's Auto off. The AI is the only bid owner of an AI product (AGENTS.md rule 2), so
a person's bid, import, budget, placement, status or dayparting change there is a second owner. This reads saved Scale
Insights change-history pages and lists, per AI product, the manual changes of that kind: the routine flags them in the
run's Slack message and moves that product's weekly run up to today, so the AI prices over the hand change the same day.
It changes nothing.

  python scripts/si_changes.py <page.json> [<page.json> ...] [--data DIR] [--since YYYY-MM-DD] [--out FILE]

The pages: Scale Insights get_change_history, source "manual", mode "raw", days 2, count 100, every page saved (they are
large: save each to a file, never paste them). A product's keyword-list edits (blacklist, whitelist, negative lists:
action "other") are the negative audit's and only counted.
"""
import argparse
import glob
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
# the actions that move what an AI product pays or whether it serves: a second bid owner
OWNER_ACTIONS = ('bid', 'import', 'budget', 'placement', 'status', 'dayparting')
AI_STAGES = ('ai', 'onboarding', 'seasonal')


def load(path):
    with open(path, encoding='utf-8') as fh:
        raw = json.loads(fh.read().strip())
    # the tool-result wrapper [{"type": "text", "text": "..."}] or the plain payload
    if isinstance(raw, list) and raw and isinstance(raw[0], dict) and 'text' in raw[0]:
        raw = json.loads(raw[0]['text'])
    return raw


def ai_products(data_dir):
    """{ASIN: product name} for the products whose bids the AI owns."""
    out = {}
    for p in sorted(glob.glob(os.path.join(data_dir, 'asins', '*.json'))):
        product = load(p)
        reg = product.get('registry') or {}
        if reg.get('bid_owner') == 'AI' or reg.get('stage') in AI_STAGES:
            out[product.get('asin') or os.path.basename(p)[:-5]] = product.get('name') or product.get('product') or ''
    return out


def check(pages, products, since=None):
    """{'flagged': {ASIN: {...}}, 'lists_only': {ASIN: n}, 'rows_read': n} from the change-history pages."""
    flagged, lists_only, seen, rows = {}, Counter(), set(), 0
    for page in pages:
        for c in (page or {}).get('Changes') or []:
            key = json.dumps(c, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            rows += 1
            asin = c.get('Asin')
            if (c.get('Source') or '').lower() != 'manual' or asin not in products:
                continue
            if since and (c.get('TimestampUtc') or '')[:10] < since:
                continue
            action = (c.get('Action') or '').lower()
            if action not in OWNER_ACTIONS:
                lists_only[asin] += 1
                continue
            f = flagged.setdefault(asin, dict(name=products[asin], changes=0, actions=Counter(), actors=Counter(),
                                              first=None, last=None, raised=0, lowered=0))
            f['changes'] += 1
            f['actions'][action] += 1
            f['actors'][c.get('Actor') or 'unknown'] += 1
            t = c.get('TimestampUtc')
            f['first'] = min(x for x in (f['first'], t) if x) if t else f['first']
            f['last'] = max(x for x in (f['last'], t) if x) if t else f['last']
            delta = c.get('Delta')
            if isinstance(delta, (int, float)):
                f['raised' if delta > 0 else 'lowered'] += delta != 0
    for f in flagged.values():
        f['actions'], f['actors'] = dict(f['actions']), dict(f['actors'])
    return dict(flagged=flagged, lists_only=dict(lists_only), rows_read=rows)


def message(result):
    """The routine's Slack line (scripts/notify.py posts it with the morning's run), or '' when nothing is flagged."""
    if not result['flagged']:
        return ''
    parts = []
    for asin, f in sorted(result['flagged'].items(), key=lambda x: -x[1]['changes']):
        who = ', '.join(sorted(f['actors']))
        parts.append(f"{asin} {f['name']}: {f['changes']} ({', '.join(f'{n} {a}' for a, n in sorted(f['actions'].items()))}) by {who}")
    return ('Hand changes in Scale Insights on AI products (the AI owns their bids, rule 2; their runs move up to today): '
            + '; '.join(parts))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('pages', nargs='+')
    ap.add_argument('--data', default=os.path.join(SKILL, 'data'))
    ap.add_argument('--since', help='only changes on or after this UTC day')
    ap.add_argument('--out')
    a = ap.parse_args(argv)
    result = check([load(p) for p in a.pages], ai_products(a.data), a.since)
    result['message'] = message(result)
    result['run_today'] = sorted(result['flagged'])
    text = json.dumps(result, indent=1)
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
