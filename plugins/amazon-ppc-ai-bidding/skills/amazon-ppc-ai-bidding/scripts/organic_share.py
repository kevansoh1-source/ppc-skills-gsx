"""The organic share, the top-10 rule and the weekly leak check (Kim, 2026-10-26, decision 143; reshaped 2026-10-31,
decision 175).

Kim's goal: rank, and about half of a product's units organic ("our goal of ranking and 50% organic units to 50% ppc
units"). None of this touches a rank (Invest or Prove-first) bid, a rank budget or any campaign budget, and none of it caps
the rank investment (decisions 99 and 174). It steers only the keywords that are not rank searches (Hold, Defend, Test,
Discovery, the audience cap, Sponsored Products and Display targets, Sponsored Brands Hold and Discovery), which bid
`thresholds.non_rank_bid_factor` of breakeven (100% since decision 157):

- **The organic share** of sales over the last `share_days` (28) is reported against `target_share` (50%). It no longer
  moves a bid: the organic-share brake (a mature product under 50% organic bid its non-rank keywords at 70%) was dropped on
  2026-10-31 (Kim, decision 175: "drop the under-half organic cut. Just let ordinary keywords stay at 100% of
  break-even"), because it cut visibility while the product is still ranking. Organic share = 1 - PPC sales / sales.
- **The top-10 rule.** A non-rank keyword on a search the product already ranks for organically bids `top10_factor` (75%
  since decision 175; 70% before) of breakeven: its Rank Radar median over the last `top10_days` (14) of readings is
  `top10_rank` (10) or better; a search with no Rank Radar counts when most of its SQP purchases are organic
  (`thresholds.defend_organic_share`, 50%) and it has `top10_sqp_min_purchases` (3) organic purchases or more. Rank and
  high-index searches keep investing whatever their rank (Kim: "continue investing in the ranking and the high-index
  keywords ... Amazon wants us to continue spending").
  Rank Radar is noisy day to day (3 of the gel pens' 30 searches touched the top 10 on single days, 2026-10-21), hence the
  14-day median.
- **The weekly leak check** (decision 175; it replaced the efficiency guard). Ordinary keywords bid breakeven, so they
  should not lose money. It reads the product's ordinary campaigns, Sponsored Products (campaign_days.json) and Sponsored
  Brands (sb_campaign_days.json, the product's SB campaigns by id): every campaign that is not a rank campaign (the SP
  Invest and Prove-first exact campaigns, the AI's SB video series and any SB campaign holding an invest search's exact
  keyword), not B2B and not a multi-product collection, over the last `leak_days` (7) settled days (the newest
  budget_headroom settle_days, 2, left out: attribution is still filling them): profit = orders x profit_per_unit - spend.
  When they lose more than `leak_tolerance` ($10), the run pauses the ordinary SP and SB keywords with
  `leak_pause_clicks` (15)+ clicks and no orders in 90 days. No bid step-down, no hold on new Prove-first launches, never a rank campaign or a
  budget. Without campaign_days.json there is no leak check, and the summary says so.

Input: <run>/sales_daily.json, Scale Insights get_sales_data for the one ASIN, group_by "day", mode "raw", days 28, count 100 (the
daily rows page at count) with no end_date, so it ends at the US marketplace's yesterday (references/data-pull.md).
Without it the share is not reported and the top-10 rule's SQP fallback still runs; the summary says why.
"""
import datetime as dt
import json
import os
import statistics

DEFAULTS = dict(enabled=True, target_share=0.5, share_days=28, top10_rank=10, top10_days=14, top10_factor=0.75,
                top10_sqp_min_purchases=3, leak_days=7, leak_tolerance=10, leak_pause_clicks=15)


def settings(shared):
    """config.json `organic_share`, over the defaults above."""
    out = dict(DEFAULTS)
    out.update({k: v for k, v in ((shared or {}).get('organic_share') or {}).items() if not k.startswith('_')})
    return out


def _payload(raw):
    """A saved tool response: the plain JSON, or a [{"type": "text", "text": ...}] wrapper around it."""
    if isinstance(raw, list) and raw and isinstance(raw[0], dict) and 'text' in raw[0]:
        for part in raw:
            try:
                return json.loads(part['text'])
            except (TypeError, ValueError):
                continue
        return None
    return raw


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_sales(run, asin):
    """<run>/sales_daily.json as {'days': {date: {sales, ppc_sales, units, profits}}, 'through': last date}, or None when
    the file is missing. A file for another ASIN stops the run, as the planner's other per-ASIN inputs do."""
    path = os.path.join(run, 'sales_daily.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        text = f.read()
    try:
        data = _payload(json.loads(text))
    except ValueError:
        # Scale Insights appends an account_context object after the result: read the first JSON value only
        data, _ = json.JSONDecoder().raw_decode(text)
        data = _payload(data)
    if not isinstance(data, dict):
        return None
    held = {str(a.get('ASIN')) for a in data.get('ASINs') or [] if isinstance(a, dict) and a.get('ASIN')}
    if held and asin not in held:
        raise SystemExit(f'sales_daily.json holds {", ".join(sorted(held))}, not {asin}: pull it again for {asin}')
    if (data.get('DailyMeta') or {}).get('has_next_page'):
        raise SystemExit('sales_daily.json holds only the first page of daily rows: pull it again with count=100 '
                         '(references/data-pull.md). Nothing planned.')
    days = {}
    for d in data.get('Daily') or []:
        if not isinstance(d, dict) or not d.get('Date'):
            continue
        days[str(d['Date'])[:10]] = dict(sales=_num(d.get('Sales')) or 0.0, ppc_sales=_num(d.get('PPCSales')) or 0.0,
                                         units=_num(d.get('Units')) or 0.0, profits=_num(d.get('Profits')))
    if not days:
        return None
    return dict(days=days, through=max(days))


def _window(sales, days):
    end = dt.date.fromisoformat(sales['through'])
    start = (end - dt.timedelta(days=days - 1)).isoformat()
    return [v for d, v in sorted(sales['days'].items()) if start <= d <= sales['through']], start


def product_share(sales, days):
    """The product's organic share of sales over the last `days` days of the file: dict(share, sales, ppc_sales, start,
    through), or None without sales."""
    if not sales:
        return None
    rows, start = _window(sales, days)
    total = sum(r['sales'] for r in rows)
    ppc = sum(r['ppc_sales'] for r in rows)
    if total <= 0:
        return None
    return dict(share=round(max(0.0, 1 - ppc / total), 3), sales=round(total, 2), ppc_sales=round(ppc, 2), start=start,
                through=sales['through'], days=len(rows))


def leak_reading(days, ordinary, profit_per_unit, s, settle_days=2):
    """The weekly leak check's reading over campaign-day rows (budget_headroom.day_rows; Sponsored Brands rows carry
    channel 'SB'): dict(profit, spend, orders, line, tripped, start, through, days, campaigns, channels), or None without
    rows. `ordinary(campaign_id, campaign_name)` says which
    campaigns count (not rank, not B2B). The window is the last `leak_days` days ending `settle_days` before the newest
    date in the rows."""
    if not days:
        return None
    newest = max(dt.date.fromisoformat(r['date']) for r in days)
    through = newest - dt.timedelta(days=settle_days)
    start = through - dt.timedelta(days=s['leak_days'] - 1)
    rows = [r for r in days if start.isoformat() <= r['date'] <= through.isoformat() and ordinary(r['campaign_id'], r['campaign'])]
    spend = round(sum(r['cost'] for r in rows), 2)
    orders = sum(r['orders'] for r in rows)
    ppu = float(profit_per_unit or 0)
    profit = round(orders * ppu - spend, 2)
    line = -float(s['leak_tolerance'])
    # by channel: Sponsored Products (campaign_days) and Sponsored Brands (sb_campaign_days, rows tagged channel 'SB')
    by = {}
    for r in rows:
        c = by.setdefault(r.get('channel') or 'SP', dict(spend=0.0, orders=0, campaigns=set()))
        c['spend'] += r['cost']; c['orders'] += r['orders']; c['campaigns'].add(r['campaign_id'])
    channels = {k: dict(spend=round(v['spend'], 2), orders=v['orders'], profit=round(v['orders'] * ppu - v['spend'], 2),
                        campaigns=len(v['campaigns'])) for k, v in sorted(by.items())}
    return dict(profit=profit, spend=spend, orders=orders, line=line, tripped=profit < line, start=start.isoformat(),
                through=through.isoformat(), days=s['leak_days'], campaigns=len({r['campaign_id'] for r in rows}),
                channels=channels)


def top10_median(series, s):
    """The median Rank Radar position over the last `top10_days` days of readings (101 = not in the top 100), or None."""
    if not series:
        return None
    last = dt.date.fromisoformat(series[-1][0])
    start = (last - dt.timedelta(days=s['top10_days'] - 1)).isoformat()
    vals = [r for d, r in series if r is not None and d >= start]
    return statistics.median(vals) if vals else None


def top10_searches(terms, radar, s, defend_share):
    """{search: 'Rank Radar median N' | 'SQP: X% of its purchases organic'} for the searches the product ranks for
    organically. A search with a Rank Radar is judged on it alone (whether or not it shows in SQP); one without on its SQP
    organic share."""
    out = {}
    for t, series in radar.items():
        med = top10_median(series, s)
        if med is not None and med <= s['top10_rank']:
            out[t] = f'Rank Radar median {med:g} over {s["top10_days"]} days'
    for t, r in terms.items():
        if t in radar:
            continue
        if (r.get('organic_share') is not None and r['organic_share'] >= defend_share
              and (r.get('organic_purchases') or 0) >= s['top10_sqp_min_purchases']):
            out[t] = f"no Rank Radar; SQP: {r['organic_share']:.0%} of its purchases organic"
    return out


