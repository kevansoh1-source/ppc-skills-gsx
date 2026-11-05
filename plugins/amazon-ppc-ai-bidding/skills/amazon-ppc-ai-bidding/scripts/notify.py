#!/usr/bin/env python3
"""The run's one Slack message (autonomous runs; Kim, 2026-10-22, decision 98).

Kim: "i want the ppc ai bidding skill to handle the bid changes and rank investments, optimisation autonomously, applying
them and then updating the dashboard and letting the humans know what it did. only when it encounters very difficult
situations and decisions it can't resolve then park them 'for human'".

So every applied run gets one message in #3d-ppc-standup (C0EXAMPLE01, Kim 2026-10-22; config.json `notify`), built
here and posted by the agent with the Slack connector (this script never posts):
  1. A short recap of what the run did, tagging the product's book owner: the product and its ASIN, then one line each,
     counts and money only, no research text: bids cut and raised; new rank campaigns and promotions with their $/day;
     stop-loss step-downs; pauses and negatives; budgets; Scale Insights steps done; anything held, and why, in a few words.
     When the product's planned invest a month is above the investment guide (auto.invest_guide_month, $2,000; Kim,
     2026-10-22, decision 99: a guide, not a gate, "if spend is overboard, the humans will notice it and step in anyway"),
     one line says so: "planned invest $X/month (above the $2,000 guide)". The same for the product's investment band
     and the $60 loss line for one search, also information since decision 100 ("we don't want to put a cap and hamper
     the autonomous engine"): "past the product's $X/month invest band: <searches>" and "modelled to lose over the
     $60/month line for one search: <search> ($X/month)". Invest searches Amazon gave no suggested bid for, priced on the
     fallback chain (decision 106, 2026-10-23), get one line too: "priced without Amazon's suggested bid: <search>
     (SoldScope), ...". The weekly leak check (decision 175, 2026-10-31; the efficiency guard of decision 143 before) gets a line
     when it acted: "leak check: the ordinary keywords lost $X over the last 7 settled days: ...". It ends with the
     dashboard link,
     https://your-dashboard.example.com/#/<ASIN>. A run that applied nothing and parked nothing still gets a one-line
     "no changes this run" recap.
  2. A "For PPC" section (was "For human" until 2026-10-25, renamed with the dashboard tab), only when something is
     parked: one line per item, tagging the person who decides, with a one-line recommendation. Who decides: a price and a Scale Insights change beyond the standard setup go to Kim (no
     promotion is parked for money since decision 99); a listing, image or offer change, or
     cutting a product, to Lee; everything else (borderline calls, big cuts, low stock, Auto switched off by a guard) to
     the product's book owner.

What went out is what `dashboard.py applied` recorded (<run>/payloads/applied_rows.json). The parked items are the plan's
human-lane rows (a row a lock holds is reported as held: a person already decided it), its listing and price items ready
for a person (plan.json human_review, phase human_ready), its stock-reorder flag (summary.stock_reorder) and any "Auto
switched off" decision the run's guards opened today (autonomy.switch_off).

The book owner: the product file's registry.book_owner, else config.json notify.book_owners[ASIN], else the owner column
of docs/sweep-tiers.csv (the team's book list, decided 2026-10-18), else notify.fallback_owner (Lee).

The For Growth line (Kim, 2026-10-25, decision 124): when the run raised a For Growth item (<run>/growth.json holds
a trigger and an item), a second, separate message goes to #3-marketing-traffic (C0EXAMPLE02; config.json
notify.growth_channel, growth_channel_id), where Growth already reads the launch and listing posts. It names the product,
the pass (first listing optimization or second optimization onward), why it was raised (the proven SKC keywords, the
ceiling or a rotate-out flag), the seed keywords, and the product's dashboard page, where the For Growth card carries
the paste-ready block. It also names the Monday step the agent does with it: board 2 (9000000011), the product's item moved
into the group "[GROWTH TEAM] - For Listing Optimisation" with status "Optimise Listing", or created there when the product
has no board 2 item (rule 6 of the readiness plan; Kim 2026-10-25; references/for-growth.md, "Telling Growth"). It replaces the PPC team's
manual "Ready for First Listing Optimization" post on AI products.

Usage:
  python scripts/notify.py --asin <ASIN> --run <run> [--date YYYY-MM-DD] [--data <dir>] [--tiers <csv>]
Prints JSON {channel, channel_id, text, mentions, owner, growth}: growth is the For Growth message ({channel,
channel_id, text, monday}) or null when the run raised no For Growth item. Standard library only (plus lanes and
plan_lanes).
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
REPO = os.path.normpath(os.path.join(SKILL, '..', '..', '..'))
sys.path.insert(0, HERE)
import lanes  # noqa: E402
import plan_lanes  # noqa: E402
import referral  # noqa: E402

FOR_HUMAN = 'For PPC'  # the dashboard tab's name for a parked item (Kim, 2026-10-25; was 'For human')
BID_TYPES = ('Bid change', 'Target bid change', 'SB bid change')
PAUSE_TYPES = ('Pause keyword', 'Pause target', 'SB pause keyword')
BUDGET_TYPES = ('Budget step', 'Budget and top of search')
ACTIVE = ('open', 'in_progress', 'waiting_approval')


# ----------------------------------------------------------------------------- reading
def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def read_tiers(path):
    """{ASIN: owner} from the team's book list (docs/sweep-tiers.csv, columns asin and owner); {} when it can't be read."""
    try:
        with open(path, encoding='utf-8', newline='') as fh:
            return {r['asin'].strip(): r['owner'].strip() for r in csv.DictReader(fh)
                    if (r.get('asin') or '').strip() and (r.get('owner') or '').strip()}
    except (OSError, KeyError, csv.Error):
        return {}


def book_owner(asin, product, shared, tiers=None):
    """The name of the product's book owner (module docstring): registry.book_owner, notify.book_owners, the book list
    (`tiers`, read_tiers), else notify.fallback_owner."""
    cfg = (shared or {}).get('notify') or {}
    named = ((product or {}).get('registry') or {}).get('book_owner')
    owner = named or (cfg.get('book_owners') or {}).get(asin) or (tiers or {}).get(asin)
    return owner if isinstance(owner, str) and owner.strip() else cfg.get('fallback_owner', 'Lee')


def tag(name, shared):
    """A Slack mention of a person by their Slack ID (notify.people), or the bare name when the config has no ID for them."""
    uid = (((shared or {}).get('notify') or {}).get('people') or {}).get(name)
    return f'<@{uid}>' if uid else name


def money(v):
    return f'${v:,.2f}' if abs(v - round(v)) > 1e-9 else f'${v:,.0f}'


def plural(n, one, many=None):
    return f"{n:g} {one if n == 1 else (many or one + 's')}"


# ----------------------------------------------------------------------------- the recap
def went_out(plan, applied):
    """The plan's change rows that `applied` recorded as gone out ({row_id: ...})."""
    return [c for c in plan.get('changes') or [] if isinstance(c, dict) and c.get('row_id') in (applied or {})]


def guide_line(summary):
    """'planned invest $X/month (above the $2,000 guide)' when the plan's summary flags the product above its investment
    guide (plan_lanes.invest_guide), else None. Information for a person to step in, never a gate (decision 99)."""
    month, guide = summary.get('planned_invest_month'), summary.get('invest_guide_month')
    if summary.get('above_invest_guide') is not True or not isinstance(month, (int, float)):
        return None
    return f"planned invest {money(month)}/month (above the {money(guide) if isinstance(guide, (int, float)) else ''} guide)"


FALLBACK_WORDS = {'soldscope': 'SoldScope', 'estimate': 'an estimate', 'none': 'the no-suggestion bid'}


def fallback_line(summary):
    """'priced without Amazon's suggested bid: <search> (SoldScope), ...' when the plan priced invest searches on the
    fallback chain (plan.py summary bid_fallback; bid_fallback.py, decision 106), else None. Information, so a person can
    check a price Amazon didn't give; never a gate."""
    fb = summary.get('bid_fallback')
    if not isinstance(fb, dict):
        return None
    each = [f"{t} ({FALLBACK_WORDS.get((v or {}).get('source'), 'a fallback')})" for t, v in sorted((fb.get('searches') or {}).items())]
    each += [f'B2B {t} (the no-suggestion bid)' for t in fb.get('business_searches') or []]
    return f"priced without Amazon's suggested bid: {', '.join(each)}" if each else None


def organic_lines(summary):
    """The weekly leak check in words (plan.py summary organic, organic_share.py, decision 175), [] when it didn't act. It
    trips on its own, so the message says what it did; rank bids, budgets and Prove-first launches are never part of it."""
    org = summary.get('organic')
    if not isinstance(org, dict) or not org.get('enabled'):
        return []
    g = org.get('leak') or {}
    if not (g.get('acted') or g.get('checked')):   # checked: tripped with nothing to pause (plan.leak_summary, 2026-11-04)
        return []
    n = len(g.get('paused') or []) + len(g.get('sb_paused') or [])
    paused = f"{plural(n, 'keyword')} with 15+ clicks and no orders paused" if n else 'no keyword met the pause bar'
    return [f"leak check: the ordinary keywords lost {money(-g.get('profit', 0))} over the last {g.get('days', 7)} settled "
            f"days: {paused}; rank bids, budgets and new Prove-first campaigns untouched"]


def band_lines(summary):
    """The recap's lines for the Auto promotions past the product's investment band and those modelled past the loss line
    for one search (plan_lanes: summary over_invest_band, invest_band_month, over_loss_line, loss_line_month), [] when
    none. Information for a person to step in, never a gate (Kim, 2026-10-22, decision 100)."""
    lines = []
    over = [str(x).replace(lanes.BUSINESS_LOCK_PREFIX, 'B2B ') for x in summary.get('over_invest_band') or []]
    band = summary.get('invest_band_month')
    if over:
        size = f" {money(band)}/month" if isinstance(band, (int, float)) and not isinstance(band, bool) else ''
        lines.append(f"past the product's{size} invest band: {', '.join(over)}")
    loss = [x for x in summary.get('over_loss_line') or [] if isinstance(x, dict) and x.get('search')]
    line = summary.get('loss_line_month')
    if loss:
        each = []
        for x in loss:
            net = x.get('modelled_net_month')
            name = str(x['search']).replace(lanes.BUSINESS_LOCK_PREFIX, 'B2B ')
            each.append(f'{name} ({money(-net)}/month)' if isinstance(net, (int, float)) and net < 0 else name)
        size = f'{money(line)}/month' if isinstance(line, (int, float)) and not isinstance(line, bool) else 'loss'
        lines.append(f"modelled to lose over the {size} line for one search: {', '.join(each)}")
    return lines


def recap_lines(rows):
    """One line per kind of change that went out, counts and money only; [] when nothing went out."""
    lines = []
    bids = [c for c in rows if c.get('type') in BID_TYPES and not c.get('stop_loss_step_down')]
    up = sum(1 for c in bids if lanes.direction(c) == 'up')
    down = sum(1 for c in bids if lanes.direction(c) == 'down')
    if bids:
        lines.append(f'Bids: {down:g} cut, {up:g} raised')
    promos = [c for c in rows if plan_lanes.is_promotion(c)]
    if promos:
        day = sum(c.get('budget') or 0 for c in promos)
        month = sum(c.get('modelled_spend_month') or 0 for c in promos)
        lines.append(f"Rank campaigns: {plural(len(promos), 'new or promoted search', 'new or promoted searches')} at "
                     f"{money(day)}/day" + (f' (modelled {money(month)} a month)' if month else ''))
    sb_new = [c for c in rows if c.get('type') == 'New SB video campaign']
    if sb_new:
        camps = {c.get('campaign'): c.get('budget') or 0 for c in sb_new}
        lines.append(f"Sponsored Brands video: {plural(len(sb_new), 'keyword')} in "
                     f"{plural(len(camps), 'new campaign')} at {money(sum(camps.values()))}/day")
    steps = {(c.get('owner_kind'), c.get('keyword')) for c in rows if c.get('stop_loss_step_down')}
    if steps:
        lines.append(f"Stop-loss step-downs: {plural(len(steps), 'search', 'searches')} back to Hold (breakeven, top of search 0%)")
    pauses = sum(1 for c in rows if c.get('type') in PAUSE_TYPES and not c.get('stop_loss_step_down'))
    negs = sum(1 for c in rows if c.get('type') in ('Negative exact', 'Archive negative'))
    if pauses or negs:
        lines.append(f'Pauses: {pauses:g}; negatives: {negs:g}')
    budgets = [c for c in rows if c.get('type') in BUDGET_TYPES and not c.get('stop_loss_step_down')]
    if budgets:
        delta = sum((c.get('budget') or 0) - (c.get('budget_now') or 0) for c in budgets
                    if c.get('budget') is not None and c.get('budget_now') is not None)
        lines.append(f"Budgets and top of search: {plural(len(budgets), 'campaign')}"
                     + (f" ({'+' if delta >= 0 else '-'}{money(abs(delta))}/day)" if delta else ''))
    harvest = [c for c in rows if c.get('type') == 'Harvest default bid']
    for c in harvest:
        lines.append(f"Harvest starting bid: {money(c.get('current') or 0)} -> {money(c.get('new') or 0)}")
    shaped = [c for c in rows if c.get('type') == lanes.SHAPE]
    if shaped:
        lines.append(f"Product-page base bid: {plural(len(shaped), 'campaign')} "
                     f"({plural(sum(c.get('bids') or 0 for c in shaped), 'bid')} lowered for product pages)")
    strategy = sum(1 for c in rows if c.get('type') == lanes.STRATEGY)
    if strategy:
        lines.append(f"Down-only bidding: {plural(strategy, 'campaign')} moved off up-and-down")
    si = sum(1 for c in rows if c.get('type') in lanes.SI_TYPES)
    if si:
        lines.append(f"Scale Insights: {plural(si, 'step')} done")
    return lines


def held_text(plan, applied):
    """'Held: ...' in a few words, or None: the rows that did not go out and are not parked for a person."""
    summary = (plan.get('summary') or [{}])[0]
    counts = {}

    def count(why):
        counts[why] = counts.get(why, 0) + 1
    stale = str(summary.get('stale_reason') or '')
    stale_words = ', '.join(w for k, w in (('stock', 'low stock'), ('price changed', 'a recent price change'),
                                          ('Search Query Performance', 'old SQP data'), ('missing', 'a missing input file'),
                                          ("doesn't say", 'an unreadable input file')) if k in stale) or 'data not fresh'
    for c in plan.get('changes') or []:
        if not isinstance(c, dict) or c.get('row_id') in (applied or {}):
            continue
        if c.get('locked_until'):
            count('an earlier decision')
        elif c.get('lane') == 'monitor':
            count(stale_words if stale and str(c.get('lane_reason') or '').startswith('the product data is not fresh')
                  else 'close calls and thin data, judged again next run')
        elif c.get('lane') == 'auto' and summary.get('shadow') is False:
            count('not written this run (see the recorded execution blocker)')
    if not counts:
        return None
    return 'Held: ' + '; '.join(f"{n:g} ({why})" for why, n in counts.items())


# ------------------------------------------------------------------------------- what is parked "For PPC"
def human_group(c):
    """(who decides: 'Kim' or 'owner', what the row is, in a few words) for a human-lane row, from its own fields and the
    planner's lane reasons."""
    reason = str(c.get('lane_reason') or '')
    if c.get('type') == 'Listing price':
        return 'Kim', 'price change'
    if c.get('si_beyond_standard'):
        return 'Kim', 'Scale Insights change beyond the standard setup'
    if c.get('type') == 'Stop-loss review':
        return 'owner', 'stop-loss call with no step-down to write'
    if c.get('type') == lanes.STRATEGY:
        return 'owner', ('down-only bidding on an AMC campaign' if c.get('audience') else
                         'down-only bidding on a campaign shared with other products')
    if reason.startswith('this run has used up'):
        return 'owner', "raise past the run's automatic raises"
    if reason.startswith('cutting the bid by'):
        return 'owner', 'big bid cut (over 50% on 3+ orders)'
    if any(k in reason for k in ('head term', 'search-term fallback', 'niche list', 'flagged "')):
        return 'owner', 'promotion on a head term or the search-term fallback'
    if 'opportunity' in reason or 'spent in 30 days' in reason:
        return 'owner', 'borderline call (short of the evidence ladder, big opportunity)'
    if 'not the standard' in reason or 'top of search' in reason:
        return 'owner', 'non-standard budget or top of search'
    return 'owner', 'other call'


def parked(plan, product, date, applied=None):
    """[(who: 'Kim', 'Lee' or 'owner', one line)]: the run's "For PPC" items (module docstring), in a fixed order."""
    out = []
    summary = (plan.get('summary') or [{}])[0]
    groups = {}
    for c in plan.get('changes') or []:
        if (not isinstance(c, dict) or c.get('lane') != 'human' or c.get('locked_until')
                or c.get('row_id') in (applied or {})):
            continue
        who, what = human_group(c)
        g = groups.setdefault((who, what), dict(n=0, promos=0, month=0.0, price=None))
        g['n'] += 1
        g['promos'] += 1 if plan_lanes.is_promotion(c) else 0   # a promotion's bundle rows go with it, uncounted
        g['month'] += c.get('modelled_spend_month') or 0
        if c.get('type') == 'Listing price':
            g['price'] = (c.get('current'), c.get('new'))
    for (who, what), g in groups.items():
        line = f"{(g['promos'] or g['n']):g} x {what}"
        if g['price'] and all(isinstance(v, (int, float)) for v in g['price']):
            line = f"price {money(g['price'][0])} -> {money(g['price'][1])}"
        elif g['month']:
            line += f" (modelled {money(g['month'])} a month)"
        out.append((who, f'{line}: approve or decline on the dashboard'))
    stock = summary.get('stock_reorder') or {}
    if stock.get('cover_days') is not None:
        out.append(('owner', f"inventory alert: {stock['cover_days']:g} days of cover left. Auto changes continue; "
                             'manage stock and any reorder manually'))
    for item in plan.get('human_review') or []:
        if (not isinstance(item, dict) or item.get('kind') not in ('listing', 'price')
                or (item.get('ai_review') or {}).get('phase') != 'human_ready' or item.get('status', 'open') not in ACTIVE):
            continue
        rec = ((item.get('ai_review') or {}).get('assessment') or {}).get('recommendation') or item.get('action') or ''
        text = f"{item.get('title')}: {rec}".strip().rstrip(':')
        out.append(('Kim' if item['kind'] == 'price' else 'Lee', text if len(text) <= 160 else text[:157] + '...'))
    for o in (product or {}).get('open_items') or []:
        flow = o.get('workflow') or {}
        # a guard's item of the day: Auto switched off, or (decision 163) a Day-1 spend or read-back alert with Auto on
        if o.get('status') == 'decision' and o.get('opened') == date and flow.get('kind') in ('auto_off', 'day1_spend', 'readback'):
            out.append(('owner', f"{o.get('short')}: {flow.get('action') or 'look at it'}"))
    order = {'Kim': 0, 'Lee': 1, 'owner': 2}
    return sorted(out, key=lambda x: order.get(x[0], 3))


# ----------------------------------------------------------------------------- the message
def message(plan, product, shared, asin, applied=None, date=None, tiers=None):
    """The run's Slack message: {channel, channel_id, text, mentions, owner} (module docstring)."""
    cfg = (shared or {}).get('notify') or {}
    summary = (plan.get('summary') or [{}])[0]
    date = date or summary.get('review_date') or dt.date.today().isoformat()
    owner = book_owner(asin, product, shared, tiers)
    name = (product or {}).get('product') or summary.get('product') or asin
    link = f"{cfg.get('dashboard_url', 'https://your-dashboard.example.com/#/')}{asin}"
    mentions = []

    def who(name_):
        mention = tag(name_, shared)
        if mention.startswith('<@') and mention not in mentions:
            mentions.append(mention)
        return mention
    lines = [f'{who(owner)} PPC AI run: {name} ({asin}), {date}']
    rows = went_out(plan, applied)
    recap = recap_lines(rows)
    for line in [referral.line(summary.get('referral')), guide_line(summary), fallback_line(summary)] + organic_lines(summary) + band_lines(summary):
        if line:
            recap.append(line[:1].upper() + line[1:])
    if summary.get('shadow') is not False:
        waiting = sum(1 for c in plan.get('changes') or [] if isinstance(c, dict) and c.get('row_id') not in (applied or {}))
        recap.append(f"Auto is off for this product, so nothing applied on its own; {plural(waiting, 'change')} "
                     'wait for a person on the dashboard')
    held = held_text(plan, applied)
    items = parked(plan, product, date, applied)
    if not recap and not held and not items:
        lines.append('No changes this run.')
    else:
        lines += [f'- {x}' for x in recap] or ['- No changes applied this run.']
        if held:
            lines.append(f'- {held}')
    lines.append(link)
    if items:
        lines.append(f'*{FOR_HUMAN}:*')
        for person, text in items:
            lines.append(f"- {who(owner if person == 'owner' else person)} {text}")
    return dict(channel=cfg.get('channel', '#3d-ppc-standup'), channel_id=cfg.get('channel_id'), text='\n'.join(lines),
                mentions=mentions, owner=owner)


def growth_message(growth_run, product, shared, asin):
    """The For Growth line for #3-marketing-traffic (module docstring), or None when growth.json raised no item."""
    run = growth_run or {}
    item = run.get('item') if isinstance(run.get('item'), dict) else None
    if not run.get('trigger') or not item:
        return None
    cfg = (shared or {}).get('notify') or {}
    g = item.get('growth') or {}
    name = g.get('product') or (product or {}).get('product') or (product or {}).get('name') or asin
    link = f"{cfg.get('dashboard_url', 'https://your-dashboard.example.com/#/')}{asin}"
    why = (item.get('workflow') or {}).get('why') or run.get('trigger_reason') or run['trigger']
    seeds = [x.get('term') for x in g.get('weave_in') or [] if isinstance(x, dict) and x.get('term')]
    lines = [f"Ready for listing optimisation: {name} ({asin}), {g.get('pass') or 'listing pass'}",
             f'- Why: {why}']
    if seeds:
        lines.append(f"- Seed keywords: {'; '.join(seeds)}")
    lines.append(f'- The paste-ready block is on the For Growth card: {link}')
    monday = {'board': cfg.get('growth_monday_board', 9000000011), 'asin': asin,
              'group': cfg.get('growth_monday_group', 'new_group3973'),
              'group_title': cfg.get('growth_monday_group_title', '[GROWTH TEAM] - For Listing Optimisation'),
              'status': cfg.get('growth_monday_status', 'Optimise Listing'),
              'if_missing': cfg.get('growth_monday_if_missing', 'create'), 'item_name': f'{name} ({asin})'}
    return dict(channel=cfg.get('growth_channel', '#3-marketing-traffic'), channel_id=cfg.get('growth_channel_id'),
                text='\n'.join(lines), monday=monday)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--asin', required=True)
    ap.add_argument('--run', required=True, help='the run folder (plan.json, payloads/applied_rows.json)')
    ap.add_argument('--date', help='YYYY-MM-DD, the run day in Singapore (default: the plan\'s review_date)')
    ap.add_argument('--skill', default=SKILL)
    ap.add_argument('--data', help='shared data folder holding asins/<ASIN>.json')
    ap.add_argument('--tiers', help='the book list CSV (default: config.json notify.tiers_csv, from the repo root)')
    a = ap.parse_args(argv)
    shared = read_json(os.path.join(a.skill, 'config.json'), {})
    data = a.data or shared.get('data_dir') or os.path.join(a.skill, 'data')
    product = read_json(os.path.join(data, 'asins', f'{a.asin}.json'), {})
    plan = read_json(os.path.join(a.run, 'plan.json'))
    if plan is None:
        sys.exit(f'No plan.json in {a.run}')
    if (plan.get('summary') or [{}])[0].get('asin') not in (None, a.asin):
        sys.exit(f"{a.run} holds the plan for {plan['summary'][0].get('asin')}, not {a.asin}")
    raw = read_json(os.path.join(a.run, 'payloads', 'applied_rows.json'), {}) or {}
    tiers = read_tiers(a.tiers or os.path.join(REPO, (shared.get('notify') or {}).get('tiers_csv', 'docs/sweep-tiers.csv')))
    out = message(plan, product, shared, a.asin, raw, a.date, tiers)
    out['growth'] = growth_message(read_json(os.path.join(a.run, 'growth.json')), product, shared, a.asin)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
