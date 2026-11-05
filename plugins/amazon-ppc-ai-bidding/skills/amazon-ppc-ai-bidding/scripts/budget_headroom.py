"""Budget headroom: profitable campaigns that run out of budget get a budget step; a step that stopped paying goes back.

Kim, 2026-10-20: "if it runs out of budget prematurely, we should look to increase our budget to maximize the goodness
of a low-ACOS campaign". "Low" is judged against the product's own breakeven ACOS (unit profit / price), never one
account-wide number: 24% ACOS loses money at a 17% breakeven and 36% makes money at 44% (logs/2026-10-20-budget-headroom-check.md).

Two ways in:
- plan.py calls `plan_rows` in the weekly run of an AI-managed product: 'Budget step' change rows for its own Sponsored
  Products campaigns, business (B2B) campaigns included. Excluded: B2B campaigns holding a Business invest, a new exact
  keyword or an owner already invested as planned (their budget comes from that invest), and audience campaigns (rulebook
  9.5). Since 2026-10-31 (Kim, decision 174: "invest in validated keywords without a money cap") the product's consumer
  rank campaigns (Invest and Prove first, `rank`) are judged too, without the ACOS condition: one that runs out of budget on
  min_capped_days of the window steps up whatever its ACOS and orders, because losses are accepted for ranking; max_budget,
  the step size and review_after_days still apply, and the stop-loss (not ACOS) is its brake, so it never steps back on
  ACOS. Other campaigns keep the ACOS condition. The rows apply on their own (lanes.AUTO_TYPES).
- `python scripts/budget_headroom.py catalog ...` scans every other campaign (the Scale Insights catalog) for the monthly
  machine check and writes a report and a MAP payload for the team; it writes nothing to Amazon.
`python scripts/budget_headroom.py record ...` adds a step that went out to the ledger (data/budget_steps.json), so the
next check can judge it a week later. log_invest.py records the weekly run's steps itself.

Inputs (references/budget-headroom.md, with the SQL):
- campaign days: one row per campaign per day (MAP `run_report_sql` on sponsored_products_campaigns): campaign_id,
  campaign, date, cost, budget, sales (14-day), orders (14-day), clicks;
- optional Amazon budget recommendations (MAP `get_amazon_ads_campaigns_budget_recs`): the suggested budget caps a step.
"""
import argparse
import datetime as dt
import glob
import json
import math
import os
import re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
TYPE = 'Budget step'
DEFAULTS = dict(
    window_days=14,          # capped days and ACOS are read over the last 14 complete days
    settle_days=2,           # the newest 2 days are left out of ACOS and orders: 14-day attribution is still filling them
    capped_share=0.9,        # a day that spent 90% of its budget ran out of budget
    min_capped_days=5,       # ...on 5 or more of the 14 days
    min_orders=3,
    max_acos_share=0.8,      # ACOS at or below 80% of the product's breakeven ACOS
    step=0.5,                # +50% a step, rounded up to whole dollars, at least +$1
    min_step=1.0,
    max_budget=50.0,         # never past $50/day in one product campaign without a person setting it
    review_after_days=7,     # a step is judged a week after it went out; no second step before then
    step_back_min_clicks=20, # a step goes back when its campaign ran above breakeven on 20+ clicks since the step
)
ASIN_RE = re.compile(r'B0[A-Z0-9]{8}')


def settings(shared):
    return {**DEFAULTS, **((shared or {}).get('budget_headroom') or {})}


def read_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def rows_of(raw):
    """The rows of a MAP SQL result as saved ({'data': [...]}) or a plain list."""
    if isinstance(raw, dict):
        raw = raw.get('data') or raw.get('rows') or raw.get('items') or []
    return raw or []


def _f(r, *keys):
    for k in keys:
        if r.get(k) is not None:
            return r[k]
    return None


def day_rows(raw):
    """Campaign-day rows with one spelling, whatever the SQL called the columns."""
    out = []
    for r in rows_of(raw):
        cid = _f(r, 'campaign_id', 'campaignId')
        d = _f(r, 'date')
        if cid is None or d is None:
            continue
        out.append(dict(campaign_id=str(cid), campaign=_f(r, 'campaign', 'campaignName', 'name') or '', date=str(d)[:10],
                        cost=float(_f(r, 'cost', 'spend') or 0), budget=float(_f(r, 'budget', 'campaignBudgetAmount') or 0),
                        sales=float(_f(r, 'sales', 'sales14d') or 0), orders=int(_f(r, 'orders', 'purchases14d', 'purchases') or 0),
                        clicks=int(_f(r, 'clicks') or 0)))
    return out


def recs_of(raw):
    """{campaign_id: {suggested, time_in_budget, missed_sales_low, missed_sales_high}} from Amazon's budget recommendations."""
    if isinstance(raw, dict) and 'budgetRecommendationsSuccessResults' in raw:
        raw = raw['budgetRecommendationsSuccessResults']
    out = {}
    for r in raw or []:
        m = r.get('sevenDaysMissedOpportunities') or {}
        out[str(r.get('campaignId'))] = dict(suggested=r.get('suggestedBudget'), time_in_budget=m.get('percentTimeInBudget'),
                                             missed_sales_low=m.get('estimatedMissedSalesLower'),
                                             missed_sales_high=m.get('estimatedMissedSalesUpper'))
    return out


def ledger_path(shared, data=None):
    return os.path.join(data or (shared or {}).get('data_dir') or os.path.join(SKILL, 'data'), 'budget_steps.json')


def load_ledger(path):
    if not os.path.exists(path):
        return {'steps': []}
    return read_json(path)


def last_steps(ledger):
    """{campaign_id: the newest step recorded for it}."""
    out = {}
    for s in ledger.get('steps') or []:
        cid = str(s.get('campaign_id'))
        if cid not in out or str(s.get('date')) >= str(out[cid].get('date')):
            out[cid] = s
    return out


def window_stats(days, end, cfg):
    """{campaign_id: stats over the window ending `end` (the newest complete day)}: capped days over the whole window,
    cost / sales / orders / clicks / ACOS without the newest settle_days days."""
    start = (end - dt.timedelta(days=cfg['window_days'] - 1)).isoformat()
    settled = (end - dt.timedelta(days=cfg['settle_days'])).isoformat()
    by = defaultdict(lambda: dict(campaign='', days=0, capped=0, cost=0.0, sales=0.0, orders=0, clicks=0, budget=None, last=''))
    for r in days:
        if not start <= r['date'] <= end.isoformat():
            continue
        s = by[r['campaign_id']]
        s['campaign'] = r['campaign'] or s['campaign']
        s['days'] += 1
        if r['budget'] > 0 and r['cost'] >= cfg['capped_share'] * r['budget']:
            s['capped'] += 1
        if r['date'] >= s['last']:
            s['last'], s['budget'] = r['date'], r['budget']
        if r['date'] <= settled:
            s['cost'] += r['cost']; s['sales'] += r['sales']; s['orders'] += r['orders']; s['clicks'] += r['clicks']
    for s in by.values():
        s['acos'] = round(s['cost'] / s['sales'], 4) if s['sales'] > 0 else None
    return dict(by)


def since(days, cid, start, end):
    """cost, sales, clicks of one campaign from `start` (a step's date) to `end`."""
    cost = sales = clicks = 0.0
    for r in days:
        if r['campaign_id'] == cid and start <= r['date'] <= end:
            cost += r['cost']; sales += r['sales']; clicks += r['clicks']
    return cost, sales, int(clicks)


def step_up(now, cfg, suggested=None):
    """The next budget: +step, rounded up to whole dollars, at least +min_step, never past max_budget or Amazon's
    suggestion (when Amazon suggests more than now). None when there is no room."""
    new = max(math.ceil(now * (1 + cfg['step'])), now + cfg['min_step'])
    new = min(new, cfg['max_budget'])
    if suggested and suggested > now:
        new = min(new, suggested)
    new = float(math.floor(new)) if new != int(new) else float(new)
    return new if new > now else None


def _pct(x):
    return f'{x * 100:.0f}%'


def decide(days, be_acos, cfg, today, recs=None, ledger=None, live_budgets=None, exclude=(), rank=()):
    """Every campaign's verdict. be_acos: {campaign_id: breakeven ACOS as a share (0.44)} or a callable taking the
    campaign name. `rank`: the campaign ids of rank campaigns on validated searches (Invest, Prove first), judged without the
    ACOS condition (decision 174). Returns dict(up=[...], back=[...], waiting=[...], watch=[...], at_loss=[...],
    no_breakeven=[...]), each item a dict with the numbers behind it (rank=True on a rank campaign's)."""
    recs, live_budgets = recs or {}, live_budgets or {}
    steps = last_steps(ledger or {})
    latest = max((r['date'] for r in days), default=None)
    end = min(dt.date.fromisoformat(latest), today - dt.timedelta(days=1)) if latest else today - dt.timedelta(days=1)
    stats = window_stats(days, end, cfg)
    out = dict(up=[], back=[], waiting=[], watch=[], at_loss=[], no_breakeven=[], window=dict(
        start=(end - dt.timedelta(days=cfg['window_days'] - 1)).isoformat(), end=end.isoformat(),
        acos_through=(end - dt.timedelta(days=cfg['settle_days'])).isoformat()))
    for cid, s in sorted(stats.items(), key=lambda kv: -kv[1]['cost']):
        if cid in exclude:
            continue
        be = be_acos(s['campaign']) if callable(be_acos) else be_acos.get(cid)
        step = steps.get(cid)
        budget = live_budgets.get(cid, s['budget']) or 0
        if step and cid not in live_budgets and str(step.get('date')) > s['last']:
            budget = float(step['to'])  # stepped after the report's last day: the ledger knows the newer budget
        is_rank = cid in rank
        item = dict(campaign_id=cid, campaign=s['campaign'], budget_now=budget, capped_days=s['capped'], days=s['days'],
                    cost=round(s['cost'], 2), sales=round(s['sales'], 2), orders=s['orders'], clicks=s['clicks'],
                    acos=s['acos'], be_acos=be, **{k: v for k, v in (recs.get(cid) or {}).items()})
        if is_rank:
            item['rank'] = True
        if step:  # judge last step first: a step that stopped paying goes back whatever else is true
            item['last_step'] = step
            day = dt.date.fromisoformat(str(step['date'])[:10])
            if (today - day).days < cfg['review_after_days']:
                out['waiting'].append(dict(item, why=f"stepped ${step['from']:g} -> ${step['to']:g} on {step['date']}: judged after "
                                                      f"{cfg['review_after_days']} days"))
                continue
            c, sl, k = since(days, cid, day.isoformat(), end.isoformat())
            a = c / sl if sl > 0 else None
            if not is_rank and be and k >= cfg['step_back_min_clicks'] and (a is None or a > be) and budget > float(step['from']):
                item.update(budget=float(step['from']), since_cost=round(c, 2), since_sales=round(sl, 2), since_clicks=k,
                            since_acos=None if a is None else round(a, 4))
                out['back'].append(dict(item, why=(f"since its step on {step['date']} it ran at "
                                                    f"{'no sales' if a is None else _pct(a) + ' ACOS'} on {k} clicks, above the "
                                                    f"{_pct(be)} breakeven: back to ${float(step['from']):g}/day")))
                continue
        if s['capped'] < cfg['min_capped_days']:
            continue
        if is_rank:
            # a rank campaign on a validated search: losses are accepted for ranking, so no ACOS or order test (decision 174)
            new = step_up(budget, cfg, (recs.get(cid) or {}).get('suggested'))
            if new is None:
                out['watch'].append(dict(item, why=f"rank campaign at the ${cfg['max_budget']:g} ceiling or Amazon's suggestion"))
                continue
            acos = 'no sales' if s['acos'] is None else f"{_pct(s['acos'])} ACOS"
            out['up'].append(dict(item, budget=new, why=(
                f"rank campaign ran out of budget on {s['capped']} of {s['days']} days ({acos}, {s['orders']} orders): "
                f"losses are accepted for ranking, so step ${budget:g} -> ${new:g}/day (never past ${cfg['max_budget']:g}), "
                f"judged again in {cfg['review_after_days']} days; the stop-loss is its brake (decision 174)")))
            continue
        if not be:
            out['no_breakeven'].append(item)
            continue
        if s['acos'] is None or s['acos'] > be:
            out['at_loss'].append(item)
            continue
        if s['orders'] < cfg['min_orders'] or s['acos'] > cfg['max_acos_share'] * be:
            out['watch'].append(dict(item, why=(f"ACOS {_pct(s['acos'])} is under the {_pct(be)} breakeven but not under "
                                                f"{_pct(cfg['max_acos_share'] * be)}, or it has fewer than {cfg['min_orders']} orders: "
                                                'more budget buys sales and rank, not profit')))
            continue
        new = step_up(budget, cfg, (recs.get(cid) or {}).get('suggested'))
        if new is None:
            out['watch'].append(dict(item, why=f"no room to step: at the ${cfg['max_budget']:g} ceiling or Amazon's suggestion"))
            continue
        tib = (recs.get(cid) or {}).get('time_in_budget')
        tib_text = f", in budget {_pct(tib)} of the time (Amazon)" if tib is not None and tib >= 0 else ''
        out['up'].append(dict(item, budget=new, why=(
            f"ran out of budget on {s['capped']} of {s['days']} days{tib_text} at {_pct(s['acos'])} ACOS against a "
            f"{_pct(be)} breakeven ({s['orders']} orders): step ${budget:g} -> ${new:g}/day, judged again in "
            f"{cfg['review_after_days']} days")))
    return out


# ----------------------------------------------------------------------------- the weekly run (plan.py)
def product_breakeven(product):
    price, profit = product.get('price'), product.get('profit_per_unit')
    return round(profit / price, 4) if price and profit else None


def campaign_days(run, asin):
    """The product's campaign-day rows from <run>/campaign_days*.json (day_rows, campaigns named with the ASIN), or None when
    the run has none. Also read by the leak check (organic_share.leak_reading, decision 175)."""
    paths = sorted(glob.glob(os.path.join(glob.escape(run), 'campaign_days*.json')))
    if not paths:
        return None
    return [r for path in paths for r in day_rows(read_json(path)) if asin in r['campaign']]


def sb_campaign_days(run):
    """The Sponsored Brands campaign-day rows from <run>/sb_campaign_days*.json (MAP sponsored_brands_campaigns, the same
    columns as campaign_days), each tagged channel 'SB', or None when the run has none. The caller keeps the product's own
    SB campaigns by id (SB names don't always carry the ASIN). Read by the leak check only (decision 175)."""
    paths = sorted(glob.glob(os.path.join(glob.escape(run), 'sb_campaign_days*.json')))
    if not paths:
        return None
    return [dict(r, channel='SB') for path in paths for r in day_rows(read_json(path))]


def plan_rows(run, asin, product, shared, today, live_campaigns=(), exclude=(), data=None, rank=()):
    """('Budget step' change rows for one AI-managed product, a summary dict). Reads <run>/campaign_days.json and the
    optional <run>/budget_recs.json; without campaign days it returns no rows and says so. `rank`: the product's rank
    campaign ids (decide). A row for one carries rank_campaign=True."""
    cfg = settings(shared)
    days = campaign_days(run, asin)
    if days is None:
        return [], dict(status='campaign_days.json not pulled: no budget check this run (references/budget-headroom.md)')
    p = os.path.join(run, 'budget_recs.json')
    recs = recs_of(read_json(p)) if os.path.exists(p) else {}
    be = product_breakeven(product)
    live = {str(c.get('campaignId')): (c.get('budget') or {}).get('budget') for c in live_campaigns if c.get('campaignId')}
    verdict = decide(days, lambda name: be, cfg, today, recs, load_ledger(ledger_path(shared, data)), live, set(map(str, exclude)),
                     set(map(str, rank)))
    rows = []
    for direction, items in (('up', verdict['up']), ('back', verdict['back'])):
        for x in items:
            rows.append(dict(step=6, type=TYPE, direction=direction, campaign=x['campaign'], campaign_id=x['campaign_id'],
                             budget_now=x['budget_now'], budget=x['budget'], acos=x['acos'], be_acos=x['be_acos'],
                             capped_days=x['capped_days'], window_days=x['days'], orders14=x['orders'], cost14=x['cost'],
                             sales14=x['sales'], suggested=x.get('suggested'), time_in_budget=x.get('time_in_budget'),
                             why=x['why'], how='MAP update sp_campaigns: budget only (no dynamicBidding)',
                             **({'rank_campaign': True} if x.get('rank') else {})))
    summary = dict(status='ok', window=verdict['window'], breakeven_acos=be, steps_up=len(verdict['up']),
                   rank_steps_up=sum(1 for x in verdict['up'] if x.get('rank')),
                   steps_back=len(verdict['back']), waiting=[dict(campaign=x['campaign'], why=x['why']) for x in verdict['waiting']],
                   watch=len(verdict['watch']), capped_at_loss=len(verdict['at_loss']),
                   need_budget_recs=sorted(x['campaign_id'] for x in verdict['up'] if x.get('suggested') is None))
    return rows, summary


# ----------------------------------------------------------------------------- the catalog scan (monthly machine check)
def catalog_report(verdict, today, cfg):
    def line(x):
        acos = '—' if x['acos'] is None else _pct(x['acos'])
        be = '—' if not x['be_acos'] else _pct(x['be_acos'])
        return (f"| {x['campaign'][:80]} | ${x['budget_now']:g} | {x['capped_days']} of {x['days']} | {acos} vs {be} | "
                f"{x['orders']} |")
    out = [f'# Budget headroom: catalog scan ({today.isoformat()})', '',
           f"Window {verdict['window']['start']} to {verdict['window']['end']}; ACOS and orders through "
           f"{verdict['window']['acos_through']} (14-day attribution still fills the newest days). Rule: "
           f"capped on {cfg['min_capped_days']}+ days, {cfg['min_orders']}+ orders, ACOS at or below "
           f"{_pct(cfg['max_acos_share'])} of the product's breakeven ACOS -> +{_pct(cfg['step'])} budget step.", '']
    sections = [('Step up', 'up', 'Proposed: '), ('Step back', 'back', 'Proposed: '), ('Waiting for last step\'s week', 'waiting', ''),
                ('At breakeven: watch, no step', 'watch', ''), ('Capped above breakeven: the budget limits a loss', 'at_loss', None),
                ('Capped, no breakeven on file', 'no_breakeven', None)]
    for title, key, prefix in sections:
        items = verdict[key]
        out += [f'## {title} ({len(items)})', '']
        if not items:
            out += ['None.', '']
            continue
        if prefix is None:
            out += [f"Spend over the window: ${sum(x['cost'] for x in items):,.0f}. Not listed one by one.", '']
            continue
        out += ['| Campaign | Budget now | Capped days | ACOS vs breakeven | Orders | Proposed | Why |', '|---|---|---|---|---|---|---|']
        for x in items:
            new = f"${x['budget']:g}" if key in ('up', 'back') else '—'
            out.append(line(x) + f" {new} | {x.get('why', '')} |")
        out.append('')
    return '\n'.join(out) + '\n'


def ai_campaign_filter(shared, data=None):
    """The ASINs the weekly run owns (registry stage 'ai' or bid_owner 'AI'): the catalog scan leaves them out."""
    folder = os.path.join(data or (shared or {}).get('data_dir') or os.path.join(SKILL, 'data'), 'asins')
    owned = set()
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            if name.endswith('.json'):
                reg = (read_json(os.path.join(folder, name)).get('registry') or {})
                if reg.get('stage') == 'ai' or reg.get('bid_owner') == 'AI':
                    owned.add(name[:-5])
    return owned


def cmd_catalog(a):
    shared = read_json(os.path.join(a.skill, 'config.json'))
    cfg = settings(shared)
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    days = [r for path in a.days for r in day_rows(read_json(path))]  # SQL pages of 1,000 rows each
    be_raw = read_json(a.be)  # {ASIN: breakeven ACOS}: a percent (44.0) or a share (0.44)
    be = {k: (v / 100 if v and v > 1 else v) for k, v in be_raw.items()}
    owned = set() if a.include_ai else ai_campaign_filter(shared, a.data)

    def be_of(name):
        m = ASIN_RE.search(name or '')
        return be.get(m.group(0)) if m else None
    exclude = {r['campaign_id'] for r in days if (m := ASIN_RE.search(r['campaign'])) and m.group(0) in owned}
    recs = recs_of(read_json(a.recs)) if a.recs else {}
    verdict = decide(days, be_of, cfg, today, recs, load_ledger(a.ledger or ledger_path(shared, a.data)), exclude=exclude)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, 'budget_headroom.json'), 'w', encoding='utf-8') as fh:
        json.dump(verdict, fh, indent=1, ensure_ascii=False)
    with open(os.path.join(a.out, 'budget_headroom.md'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(catalog_report(verdict, today, cfg))
    payload = [dict(type='sp_campaigns', campaignId=x['campaign_id'], budget=dict(budget=x['budget'], budgetType='DAILY'))
               for x in verdict['up'] + verdict['back']]
    with open(os.path.join(a.out, 'budget_steps_payload.json'), 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, indent=1)
    need = sorted(x['campaign_id'] for x in verdict['up'] if x.get('suggested') is None)
    if need:
        with open(os.path.join(a.out, 'need_budget_recs.json'), 'w', encoding='utf-8') as fh:
            json.dump(need, fh, indent=1)
    print(json.dumps(dict(up=len(verdict['up']), back=len(verdict['back']), waiting=len(verdict['waiting']), watch=len(verdict['watch']),
                          at_loss=len(verdict['at_loss']), no_breakeven=len(verdict['no_breakeven']), excluded_ai_campaigns=len(exclude),
                          need_budget_recs=len(need), out=a.out), indent=1))


def record_step(path, step):
    ledger = load_ledger(path)
    ledger.setdefault('steps', []).append(step)
    ledger['steps'].sort(key=lambda s: (str(s.get('date')), str(s.get('campaign_id'))))
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(ledger, fh, indent=1, ensure_ascii=False)
        fh.write('\n')


def cmd_record(a):
    shared = read_json(os.path.join(a.skill, 'config.json'))
    path = a.ledger or ledger_path(shared, a.data)
    step = {'campaign_id': str(a.campaign_id), 'campaign': a.campaign, 'asin': a.asin, 'from': a.from_budget, 'to': a.to_budget,
            'date': a.date, 'by': a.by, 'why': a.why, 'ref': a.ref}
    record_step(path, {k: v for k, v in step.items() if v is not None})
    print(f'recorded in {path}: {a.campaign_id} ${a.from_budget:g} -> ${a.to_budget:g} on {a.date}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--skill', default=SKILL)
    ap.add_argument('--data')
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('catalog', help='scan every campaign not owned by the weekly run; report + MAP payload, no writes')
    c.add_argument('--days', required=True, nargs='+', help='campaign days JSON pages (MAP run_report_sql results)')
    c.add_argument('--be', required=True, help='{ASIN: breakeven ACOS} JSON (Scale Insights BreakEvenAcosPercent)')
    c.add_argument('--recs', help="Amazon budget recommendations JSON (get_amazon_ads_campaigns_budget_recs result)")
    c.add_argument('--ledger')
    c.add_argument('--today')
    c.add_argument('--include-ai', action='store_true', help='also list AI-managed products (normally the weekly run has them)')
    c.add_argument('--out', required=True)
    c.set_defaults(fn=cmd_catalog)
    r = sub.add_parser('record', help='add a budget step that went out to the ledger')
    r.add_argument('--campaign-id', required=True)
    r.add_argument('--campaign', required=True)
    r.add_argument('--asin')
    r.add_argument('--from', dest='from_budget', type=float, required=True)
    r.add_argument('--to', dest='to_budget', type=float, required=True)
    r.add_argument('--date', required=True)
    r.add_argument('--by', required=True)
    r.add_argument('--why')
    r.add_argument('--ref')
    r.add_argument('--ledger')
    r.set_defaults(fn=cmd_record)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
