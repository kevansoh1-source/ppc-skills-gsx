#!/usr/bin/env python3
"""The Hold uplift test (Kim, 2026-10-23, decision 108: "Let's lock this +15% bids for idx 1 to 1.1"): its baseline and
its review. The rule itself is in plan.py (config.json hold_uplift); the protocol is
docs/experiments/hold-uplift-2026-10-23/protocol.md at the repository root.

  baseline --run <run>   the first time a product's run applies the uplift: writes the product's baseline
                         (<experiment>/baseline/<ASIN>.json) from the run's plan.json and keyword report (kw_p*.json, 90
                         days, scaled to 28) for the uplift keywords (index 1.0-1.1) and the comparison group (Hold at
                         0.8-1.0), and adds the dated review to the product file's `reviews`, so the dashboard's "Coming
                         up" shows it. An existing baseline is kept (--force replaces it).
  review --asin <ASIN> --kw <file> [<file> ...]
                         on or after the review date: the product's last 28 days of SI get_keyword_performance (days=28,
                         mode raw, every page) against its baseline. Prints each group's change and the product's verdict
                         and writes <experiment>/results/<ASIN>.json.
  verdict                every product's result together: keep, or roll back (set config.json hold_uplift.enabled
                         false), by the protocol's rule. Prints it; changes nothing.

The rule (protocol.md): keep when the uplift keywords' impressions grew at least `keep_lift_pts` (25) percentage points
more than the comparison group's, and their ad orders did not fall; otherwise roll back.
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(SKILL)))
sys.path.insert(0, HERE)
from plan import files, metrics_rows, num  # noqa: E402

KEEP_LIFT_PTS = 25
FIELDS = ('impressions', 'clicks', 'orders', 'spend', 'sales')
SOURCE = dict(impressions='Impressions', clicks='Clicks', orders='Orders', spend='Spend', sales='Sales')


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
        fh.write('\n')


def config():
    return load(os.path.join(SKILL, 'config.json'))


def experiment_dir(cfg):
    return os.path.join(REPO, (cfg.get('hold_uplift') or {}).get('experiment', 'docs/experiments/hold-uplift-2026-10-23'))


def product_path(asin, cfg, data=None):
    return os.path.join(data or cfg.get('data_dir') or os.path.join(SKILL, 'data'), 'asins', f'{asin}.json')


def keyword_metrics(paths, ids, scale=1.0):
    """{keyword id: {impressions, clicks, orders, spend, sales}} for `ids` from SI keyword-performance pages, x scale."""
    out = {}
    for row in metrics_rows(paths):
        kid = str(row.get('KeywordId') or row.get('keywordId') or '')
        if kid in ids:
            m = out.setdefault(kid, dict.fromkeys(FIELDS, 0.0))
            for field in FIELDS:
                m[field] += num(row.get(SOURCE[field])) * scale
    return {k: {f: round(v, 2) for f, v in m.items()} for k, m in out.items()}


def totals(metrics, ids):
    return {f: round(sum((metrics.get(k) or {}).get(f, 0.0) for k in ids), 2) for f in FIELDS}


def growth(after, before):
    """after / before - 1, in percentage points; None when there was nothing before."""
    return None if not before else round((after / before - 1) * 100, 1)


def cmd_baseline(a):
    cfg = config()
    plan = load(os.path.join(a.run, 'plan.json'))
    if not plan:
        raise SystemExit(f'no plan.json in {a.run}')
    s = (plan.get('summary') or [{}])[0]
    hu = s.get('hold_uplift')
    if not hu or not hu.get('keywords'):
        print(json.dumps(dict(asin=s.get('asin'), baseline=None, why='this run has no Hold uplift keyword'), indent=1))
        return
    asin = s['asin']
    path = os.path.join(experiment_dir(cfg), 'baseline', f'{asin}.json')
    if os.path.exists(path) and not a.force:
        print(json.dumps(dict(asin=asin, baseline=path, kept='a baseline exists (--force replaces it)'), indent=1))
        return
    uplift, comparison = [str(k) for k in hu['keywords']], [str(k) for k in hu.get('comparison') or []]
    metrics = keyword_metrics(files(a.run, 'kw'), set(uplift + comparison), scale=28 / 90)
    rows = {str(c.get('keyword_id')): c for c in plan.get('changes') or [] if c.get('type') == 'Bid change'}
    terms = {t['term']: t for t in plan.get('terms') or []}

    def entry(kid, group):
        c = rows.get(kid) or {}
        t = terms.get(c.get('keyword')) or {}
        return dict(keyword_id=kid, group=group, keyword=c.get('keyword'), bid_before=c.get('current'),
                    bid_after=c.get('new_proposed', c.get('new')), breakeven=c.get('breakeven'), index=t.get('index'),
                    impression_share=t.get('impression_share'), last_28_days=metrics.get(kid))
    hc = cfg.get('hold_uplift') or {}
    base = dict(asin=asin, product=s.get('product'), run=os.path.basename(os.path.abspath(a.run)),
                recorded_on=a.date or dt.date.today().isoformat(), since=hc.get('since'), review_on=hu.get('review_on'),
                pct=hu['pct'], window='the run\'s 90-day keyword report x 28/90, a 28-day rate',
                keywords=[entry(k, 'uplift') for k in uplift] + [entry(k, 'comparison') for k in comparison],
                totals=dict(uplift=totals(metrics, uplift), comparison=totals(metrics, comparison)))
    save(path, base)
    # the dated review on the product's page ("Coming up"), once
    ppath = product_path(asin, cfg, a.data)
    product = load(ppath)
    added = False
    if product is not None and hu.get('review_on'):
        reviews = product.setdefault('reviews', [])
        if not any(r.get('experiment') == 'hold-uplift-2026-10-23' for r in reviews):
            reviews.append(dict(date=hu['review_on'], short=f"Hold +{hu['pct']:g}% test review",
                                what=(f"Hold +{hu['pct']:g}% test review (index 1.0-1.1, decision 108): the 28 days after "
                                      f"against the baseline; keep or roll back by the protocol"),
                                experiment='hold-uplift-2026-10-23'))
            save(ppath, product)
            added = True
    print(json.dumps(dict(asin=asin, baseline=path, uplift=len(uplift), comparison=len(comparison),
                          review_added=added, review_on=hu.get('review_on')), indent=1))


def result_for(base, metrics):
    groups = {}
    for group in ('uplift', 'comparison'):
        ids = [k['keyword_id'] for k in base['keywords'] if k['group'] == group]
        before, after = base['totals'][group], totals(metrics, ids)
        groups[group] = dict(keywords=len(ids), before=before, after=after,
                             **{f'{f}_growth_pts': growth(after[f], before[f]) for f in ('impressions', 'clicks', 'orders')})
    up, comp = groups['uplift'], groups['comparison']
    lift = (None if up['impressions_growth_pts'] is None or comp['impressions_growth_pts'] is None
            else round(up['impressions_growth_pts'] - comp['impressions_growth_pts'], 1))
    orders_held = up['after']['orders'] >= up['before']['orders']
    keep = lift is not None and lift >= KEEP_LIFT_PTS and orders_held
    why = ('no comparison to read' if lift is None else
           f"impressions {up['impressions_growth_pts']:+g} pts against the comparison group's {comp['impressions_growth_pts']:+g} "
           f"({lift:+g} pts, the bar is +{KEEP_LIFT_PTS}); ad orders {up['before']['orders']:g} -> {up['after']['orders']:g}")
    return dict(groups=groups, impressions_lift_pts=lift, orders_held=orders_held, verdict='keep' if keep else 'roll back',
                why=why)


def cmd_review(a):
    cfg = config()
    path = os.path.join(experiment_dir(cfg), 'baseline', f'{a.asin}.json')
    base = load(path)
    if not base:
        raise SystemExit(f'no baseline for {a.asin} ({path})')
    ids = {k['keyword_id'] for k in base['keywords']}
    metrics = keyword_metrics(a.kw, ids)
    res = dict(asin=a.asin, reviewed_on=a.date or dt.date.today().isoformat(), window='last 28 days (SI, days=28)',
               **result_for(base, metrics))
    save(os.path.join(experiment_dir(cfg), 'results', f'{a.asin}.json'), res)
    print(json.dumps(res, indent=1))


def cmd_verdict(a):
    cfg = config()
    results = [load(p) for p in sorted(glob.glob(os.path.join(experiment_dir(cfg), 'results', '*.json')))]
    bases = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(experiment_dir(cfg), 'baseline', '*.json')))
    missing = sorted(set(bases) - {r['asin'] for r in results})
    keep = [r['asin'] for r in results if r['verdict'] == 'keep']
    overall = ('keep' if results and len(keep) * 2 > len(results) else 'roll back') if results else None
    print(json.dumps(dict(products=len(results), keep=keep, roll_back=[r['asin'] for r in results if r['verdict'] != 'keep'],
                          not_reviewed=missing, overall=overall,
                          then=('leave config.json hold_uplift on; record the result' if overall == 'keep' else
                                'set config.json hold_uplift.enabled false; the next runs bring the bids back to breakeven'
                                if overall else 'review the products first')), indent=1))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = p.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('baseline')
    b.add_argument('--run', required=True)
    b.add_argument('--data')
    b.add_argument('--date')
    b.add_argument('--force', action='store_true')
    r = sub.add_parser('review')
    r.add_argument('--asin', required=True)
    r.add_argument('--kw', nargs='+', required=True)
    r.add_argument('--date')
    sub.add_parser('verdict')
    a = p.parse_args(argv)
    dict(baseline=cmd_baseline, review=cmd_review, verdict=cmd_verdict)[a.cmd](a)


if __name__ == '__main__':
    main()
