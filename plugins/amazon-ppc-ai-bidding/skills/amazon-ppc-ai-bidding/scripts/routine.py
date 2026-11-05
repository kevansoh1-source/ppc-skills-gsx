#!/usr/bin/env python3
"""The morning routine's work list (Kim, 2026-10-23, decision 107: "I can program this as a routine that runs every day
or every morning at a certain time"). Reads every product file and prints, for today (Singapore), what the AI does, in
order; it changes nothing. The routine itself is SKILL.md, "Morning routine".

  python scripts/routine.py [--date YYYY-MM-DD] [--data DIR]

1. runs: the AI-managed products whose weekly run is due (below), each settling its own due checks first.
2. checks: the AI's own dated items that are due (a Day-1 spend check after an apply, a re-check the last run left): open
   items with a due date on or before today, status open, grouped by product; `with_run` marks a product whose run is
   due today, which settles them in that run.
3. reviews: dated reviews that are due and not done (`reviews` entries without a `done` date). A review of an
   experiment that has ended (a config.json block with `experiment` and `ended`, such as `hold_uplift`, ended 2026-10-25
   by decision 135) is skipped and only counted in `ended_reviews` (Kim, 2026-10-31: "as automatic as possible").
A product's run is due on the later of its registry next_run and its last run plus `routine.run_every_days` (7). One that
already ran today is never listed again, so a second routine the same day does nothing to it.

Not listed: the products lined up but not AI-managed (registry stage queued: until its book owner onboards it,
decision 172); and the items waiting on a person (status decision), which are counted in `waiting_on_people` only.
"""
import argparse
import datetime as dt
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
RUN_STAGES = ('ai', 'onboarding', 'seasonal')


def load(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def sgt_today():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)).date().isoformat()


def add_days(day, n):
    return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()


def due_on(product, every):
    """The day a product's weekly run is due: the later of registry.next_run and last_run.date + every days."""
    reg = product.get('registry') or {}
    last = (product.get('last_run') or {}).get('date')
    days = [d for d in (reg.get('next_run'), add_days(last, every) if last else None) if d]
    return max(days) if days else None


def ended_experiments(cfg):
    """The experiments that have ended: the folder names of config.json blocks carrying `experiment` and `ended`."""
    return {os.path.basename(str(b['experiment']).rstrip('/')) for b in cfg.values()
            if isinstance(b, dict) and b.get('experiment') and b.get('ended')}


def work_list(products, today, every=7, ended=()):
    checks, reviews, runs, people, skipped = [], [], [], 0, 0
    for p in sorted(products, key=lambda x: x.get('asin') or ''):
        asin, name = p.get('asin'), p.get('product') or p.get('name')
        reg = p.get('registry') or {}
        for item in p.get('open_items') or []:
            status = item.get('status')
            if status == 'decision':
                people += 1
            elif status == 'open' and item.get('due') and item['due'] <= today:
                checks.append(dict(asin=asin, product=name, due=item['due'], what=item.get('short') or item.get('text')))
        for r in p.get('reviews') or []:
            if r.get('date') and r['date'] <= today and not r.get('done'):
                if r.get('experiment') in ended:
                    skipped += 1   # the experiment ended: nobody runs its review
                    continue
                reviews.append(dict(asin=asin, product=name, due=r['date'], what=r.get('short') or r.get('what'),
                                    experiment=r.get('experiment')))
        if reg.get('stage') not in RUN_STAGES or (p.get('last_run') or {}).get('date') == today:
            continue
        due = due_on(p, every)
        if due and due <= today:
            runs.append(dict(asin=asin, product=name, due=due, stage=reg.get('stage'),
                             auto=(p.get('auto') or {}).get('enabled') is not False))
    key = lambda x: (x['due'], x['asin'])  # noqa: E731
    running = {r['asin'] for r in runs}
    grouped = {}
    for c in sorted(checks, key=key):
        g = grouped.setdefault(c['asin'], dict(asin=c['asin'], product=c['product'], with_run=c['asin'] in running, items=[]))
        g['items'].append(dict(due=c['due'], what=c['what']))
    # a product whose run is due settles its checks in that run (weekly-run.md steps 1-2); the others are done on their own
    return dict(date=today, runs=sorted(runs, key=key), checks=sorted(grouped.values(), key=lambda g: (not g['with_run'], g['asin'])),
                reviews=sorted(reviews, key=key), ended_reviews=skipped, waiting_on_people=people)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--date', help="today in Singapore (default: now)")
    ap.add_argument('--data', help='shared data folder (default: config.json data_dir, else <skill>/data)')
    a = ap.parse_args(argv)
    cfg = load(os.path.join(SKILL, 'config.json'))
    data = a.data or cfg.get('data_dir') or os.path.join(SKILL, 'data')
    products = [load(f) for f in glob.glob(os.path.join(data, 'asins', '*.json'))]
    every = int((cfg.get('routine') or {}).get('run_every_days', 7))
    print(json.dumps(work_list(products, a.date or sgt_today(), every, ended_experiments(cfg)), indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
