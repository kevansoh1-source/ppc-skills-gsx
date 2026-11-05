#!/usr/bin/env python3
"""Record what went live, AFTER the apply is verified: invest searches + baselines for the stop-loss, and the harvest bid.

Usage:
  python log_invest.py --asin B0SAMP0001 --run <run_dir> [--data <shared data dir>] [--date 2026-10-24] [--applied-harvest-bid]

Updates <data>/asins/<ASIN>.json:
  invest_log[search] = {since, role, index_then, imp_share_then, organic_then, rank_then[, checkpoint, checkpoint_rank,
                        checkpoint_organic, checkpoint_on]}
    - a search that passed a stop-loss checkpoint (month 3, 6, 9 or 12) with an organic gain keeps that checkpoint's
      reading (plan.json stop_loss): the next checkpoint judges it against it (decision 142)
    - new invest / prove-first searches get today's baseline (rank from radar*.json in the run folder when present)
    - a search that changes between Invest and Prove first keeps its 'since'
    - searches no longer invested move to invest_history, in a run planned with the lanes only by a person's step-down
      on record for this run (G1, below)
  business_invest_log[search] = {since, role, index_then, clicks_then, orders_then, spend_then, sales_then, owner_kind,
                                 campaign_id}
    - the business invests (design 2026-10-21-b2b-lane-and-roles 4f): rows with owner_kind 'business' (a Business invest,
      a business New exact keyword), by the same rules as invest_log, row for row, with the search's B2B record
      (plan['business_terms']) as the baseline: plan.py's business stop-loss judges its B2B orders and ACOS, never rank.
      A business row never touches invest_log, nor a consumer row business_invest_log; ended ones move to
      business_invest_history. A product with no business invest gets neither key. campaign_id is the campaign of the
      row that went out, else of the owner already invested as planned (plan['business_live_invests']), else of the
      search's business owner keyword (plan['business_owners'])
  harvest.default_bid = the plan's harvest default bid (only with --applied-harvest-bid, i.e. the MAP update went through)
And <data>/budget_steps.json: every 'Budget step' row applied_rows.json lists as gone out (budget_headroom.py judges it
a week later).

Only what went out counts, as <run>/payloads/applied_rows.json records it (`dashboard.py applied`): a promotion or
invest-role change starts (or changes) a search's clock only when its row_id is listed, and the clock starts on the day the
record gives it, not --date (a promotion settled a week late starts that week). A change still waiting for a person,
refused or held starts nothing, and a search already logged keeps its entry unchanged while a change of this run on it
(one with a payload) hasn't gone out (its campaign is still live as it was). Without an applied SP invest row, a NEW clock
requires explicit live-owner evidence (`consumer_live_invests` or `business_live_invests`), from --date. A Rank label or
the absence of a change is not activation proof: visibility may have suppressed it, and SB/SI work does not activate SP.
The planner currently emits only business_live_invests; consumer no-row starts must wait for verified activation rather
than infer it. Applied SP rows retain their verified-execution contract: creating a keyword under a paused parent is not
verified activation and must not be recorded as a completed invest. A run planned with the lanes (plan.json summary has `lanes`) and no record went
out with nothing (C7); only an older run without one counts every planned invest search, as before.

G1 (N1): in a run planned with the lanes, a logged search the run no longer invests in leaves invest_log only when a
decision to step it down is on record for this run. That is either:
  - its 'Stop-loss review' row approved, as <run>/payloads/approved_decisions.json records it (`dashboard.py approvals`
    writes who approved each row it lets through, the stop-loss reviews too, which have no payload); or
  - a row that demotes it recorded as gone out from payloads/approved/ or payloads/review/ (applied_rows.json): a cut or
    pause the planner flagged `invested_search` (E1), sent by a person; or
  - (autonomous runs, 2026-10-22) the planner's stop-loss step-down (a row with `stop_loss_step_down`, stop_loss.py)
    recorded as gone out from any folder, auto/ included, or, on an enabled run, one whose plan entry says it had
    nothing to write (the keyword and campaign already at Hold).
An invested cut that went out from auto/ is not a step-down: the search stays logged and its stop-loss decides.
It also records the product's planned invest (`planned_invest`: autonomy.planned_invest_record) for the program total.
Otherwise it stays in the log ("not a rank term this run; kept until the stop-loss review decides"), so E1 keeps sending
its cuts and pauses to a person and its spend stays in Kim's total. Its history entry says which decision ended it
(`stepped_down`). Each log reads only the decisions of its own kind: a business stop-loss review or cut steps down the
business invest, never the consumer one of the same search, and the other way round. Older runs keep the earlier
behaviour. Prints what changed. Never touches Amazon.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from plan import as_written, load_radar, median_rank, norm, payload_files  # noqa: E402
import autonomy  # noqa: E402
import budget_headroom  # noqa: E402
import lanes  # noqa: E402

# the rows that invest in a search: the consumer ones, and the business ones (owner_kind 'business'), which go to the
# business invest log; a row's owner_kind, never its type, decides which log it starts
INVEST_TYPES = ('New exact campaign', 'Reuse exact campaign', 'Budget and top of search', 'Bid change', 'Business invest',
                'New exact keyword')
INVEST_ROLES = ('Invest', 'Prove first')


def read(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def applied_record(run):
    """{row_id: (YYYY-MM-DD, folder)} from <run>/payloads/applied_rows.json ({row_id: {date, folder}}, or the older
    {row_id: date}, whose folder reads None), or None when the run has no such file. An unreadable one stops the command:
    what went live can't be known."""
    path = os.path.join(run, 'payloads', 'applied_rows.json')
    if not os.path.exists(path):
        return None
    try:
        obj = read(path)
    except (OSError, ValueError) as e:
        raise SystemExit(f"can't read {path}: {e}. Nothing written.")
    def day(v):
        """A recorded row's date: {date, folder} (C4), or the older bare date; None when it can't be read."""
        d = v.get('date') if isinstance(v, dict) and set(v) == {'date', 'folder'} else v
        return d if isinstance(d, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) else None
    if not isinstance(obj, dict) or not all(isinstance(k, str) and day(v) for k, v in obj.items()):
        raise SystemExit(f'{path} must be {{"<row_id>": {{"date": "YYYY-MM-DD", "folder": "..."}}, ...}} (or the older '
                         '{"<row_id>": "YYYY-MM-DD"}). Nothing written.')
    return {k: (day(v), v.get('folder') if isinstance(v, dict) else None) for k, v in obj.items()}


def applied_rows(run):
    """{row_id: YYYY-MM-DD} from <run>/payloads/applied_rows.json, or None when the run has no such file (applied_record)."""
    record = applied_record(run)
    return None if record is None else {k: d for k, (d, _) in record.items()}


PERSON_FOLDERS = ('approved', 'review')  # the folders only a person's decision sends out (auto/ is the planner's own)


def stepped_down(run, plan, record, business=False):
    """G1: {search: the person's decision to step it down, in words}, from this run only. A search is in it when its
    'Stop-loss review' row is approved in <run>/payloads/approved_decisions.json ({row_id: {by, on, at}}, written by
    `dashboard.py approvals`), or when a cut or pause the planner flagged invested_search (E1) on it went out from
    approved/ or review/ (`record`, applied_record's map, or None). An entry that can't be read counts for nothing.

    Read for one shopper kind: the consumer invest log's (business False: rows without owner_kind 'business') or the
    business invest log's (business True: rows with it). A decision on one kind's row is about that kind's keyword and
    campaign, so it never ends the other kind's invest of the same search."""
    by_id = {c.get('row_id'): c for c in plan.get('changes') or [] if isinstance(c, dict)
             and (c.get('owner_kind') == 'business') == business}
    out = {}
    path = os.path.join(run, 'payloads', 'approved_decisions.json')
    try:
        approved = read(path) if os.path.exists(path) else {}
    except (OSError, ValueError):
        approved = {}  # what was approved can't be read: nothing counts as decided (the search stays, the safe side)
    for rid, info in (approved.items() if isinstance(approved, dict) else ()):
        c = by_id.get(rid) or {}
        who = info.get('by') if isinstance(info, dict) else None
        if c.get('type') == 'Stop-loss review' and c.get('keyword') and isinstance(who, str) and who.strip():
            on = info.get('on') if isinstance(info.get('on'), str) else None
            out.setdefault(norm(c['keyword']), f'the stop-loss review was approved by {who.strip()}'
                                               + (f' on {on}' if on else ''))
    for rid, (day, folder) in sorted((record or {}).items()):
        c = by_id.get(rid) or {}
        if c.get('stop_loss_step_down') is True and c.get('keyword'):
            # autonomous runs (2026-10-22): the planner's own stop-loss step-down (stop_loss.py) ends the invest whichever
            # folder it went out from, auto/ included: the rulebook's exit, applied by the run itself
            out.setdefault(norm(c['keyword']), f'the stop-loss step-down {rid} went out on {day} from payloads/{folder}/'
                                               + (f" ({c['stop_loss_reason']})" if c.get('stop_loss_reason') else ''))
        elif (c.get('invested_search') is True and c.get('keyword') and folder in PERSON_FOLDERS
                and lanes.direction(c) in lanes.CUT_MOVES):
            what = 'a pause' if lanes.direction(c) == 'pause' else 'a cut'
            out.setdefault(norm(c['keyword']), f'{rid} ({what} on the invested search) went out on {day} from '
                                               f'payloads/{folder}/')
    # a step-down with nothing to write (the live keyword and campaign already at Hold, the plan's stop_loss entry says so)
    # ends the invest on an enabled run: nothing has to go out, so the record can't show it (shadow: a person decides)
    if (plan.get('summary') or [{}])[0].get('shadow') is False:
        for s in plan.get('stop_loss') or []:
            if (isinstance(s, dict) and s.get('step_down') == 'nothing to write' and s.get('keyword')
                    and (s.get('owner_kind') == 'business') == business):
                out.setdefault(norm(s['keyword']), 'the stop-loss step-down had nothing to write: the keyword and its '
                                                   'campaign were already at Hold')
    return out


def plan_step_downs(plan, record, business=False):
    """The searches of one shopper kind whose stop-loss step-down (stop_loss.py, autonomous runs 2026-10-22) is on record this
    run: a row with stop_loss_step_down recorded as gone out from any folder (`record`, applied_record's map, or None), or,
    on an enabled run (summary.shadow False), a stop_loss entry that had nothing to write."""
    out = {norm(c['keyword']) for c in plan.get('changes') or [] if isinstance(c, dict) and c.get('stop_loss_step_down') is True
           and c.get('keyword') and c.get('row_id') in (record or {}) and (c.get('owner_kind') == 'business') == business}
    if (plan.get('summary') or [{}])[0].get('shadow') is False:
        out |= {norm(s['keyword']) for s in plan.get('stop_loss') or [] if isinstance(s, dict) and s.get('keyword')
                and s.get('step_down') == 'nothing to write' and (s.get('owner_kind') == 'business') == business}
    return out


def still_invested(invested, rank, planned, applied, logged, live):
    """Keep logged Rank searches; start no-row ones only with explicit live-owner evidence.

    Missing rows can mean a blocked owner, not a campaign already invested as planned. `live` contains only the relevant
    shopper kind's planner evidence, never SB creations or a list of candidate owners. Pending SP rows still take
    precedence over that evidence, and update_log preserves their existing entries unchanged.
    """
    for t, role in rank:
        if t in invested:
            continue
        if applied is not None and t in planned:
            continue
        if t not in logged and t not in live:
            continue
        invested[t] = role


def waiting_searches(plan, applied, shared, asin, business=False):
    """The searches of one shopper kind with a change this run that could go out (it has a payload) and hasn't: nothing
    about them changed live. A row with no payload (a stop-loss review, a setting in Scale Insights) is never recorded, so
    it holds nothing. Empty when what went out isn't known (applied None).

    Read for one kind, as stepped_down is (business False: rows without owner_kind 'business'; True: rows with it): a
    change waiting on the other kind's row is another campaign, so it never keeps this kind's entry as it was (spec 9b,
    ruling 13)."""
    return set() if applied is None else {norm(c['keyword']) for c in plan['changes']
                                          if c.get('keyword') and (c.get('owner_kind') == 'business') == business
                                          and c.get('row_id') not in applied
                                          and payload_files([as_written(c)], shared, asin)}


def update_log(log, hist, history_key, rows, rank, applied, waiting, stepped, lanes_era, date, changed, start,
               backfill=None, label='', not_rank='not a rank term this run', ended=frozenset(), live=frozenset()):
    """One invest log's start/keep/end loop, the same rules for the consumer invest_log and the business invest log, row
    for row. Only a row that went out starts a clock, on the day it went out (`applied`: {row_id: date}, or None for an
    older run, where every planned row counts); a no-row Rank search starts only with explicit live-owner evidence
    (`live`, still_invested). A logged search keeps its entry (its role updated) while it is invested, and, when it isn't,
    while a change of this run on it waits (`waiting`), and in a run planned with the lanes until a person's step-down is
    on record (`stepped`, G1); otherwise it moves to `hist` (history_key names it in the message).

    rows: the kind's invest rows of the plan. start(t, role, since) -> (entry, words): a new entry and what the message
    says after its search; backfill(t, entry) -> words or None: fills a kept entry's missing baseline (the consumer rank).
    label follows the search in every message (' (B2B)'), not_rank names a search the run no longer invests in. `ended`:
    the searches whose stop-loss step-down is on record this run (plan_step_downs), which are not invested whatever their
    role. Appends to `changed` in order: the searches not started, the invested ones (sorted), then the log's others."""
    invested, started = {}, {}
    for c in rows:
        if applied is None or c.get('row_id') in applied:
            invested[norm(c['keyword'])] = c['role']
            if applied:  # N8: the clock starts the day its change went out
                day, t = applied[c['row_id']], norm(c['keyword'])
                started[t] = min(started.get(t, day), day)
    planned = {norm(c['keyword']) for c in rows}
    still_invested(invested, rank, planned, applied, log, live)
    # ...except one the planner's stop-loss step-down took back to Hold this run (`ended`, autonomous runs 2026-10-22): it
    # may still read as a rank search, but its keyword and campaign are no longer invested
    for t in ended:
        if t not in started:
            invested.pop(t, None)
    for t in sorted(planned - set(invested) - set(log)):
        changed.append(f'{t}{label}: not started, its change has not gone out')
    for t, role in sorted(invested.items()):
        if t in log:
            if log[t].get('role') != role:
                changed.append(f'{t}{label}: {log[t].get("role")} -> {role} (since {log[t]["since"]} kept)')
                log[t]['role'] = role
            words = backfill(t, log[t]) if backfill else None
            if words:
                changed.append(f'{t}{label}: {words}')
            continue
        log[t], words = start(t, role, started.get(t, date))
        changed.append(f'{t}{label}: {words}')
    for t in list(log):
        if t not in invested:
            if t in waiting:
                changed.append(f'{t}{label}: kept as it was, its change this run has not gone out')
                continue
            if lanes_era and t not in stepped:
                # G1: nobody decided to step it down, so it stays invested: E1 keeps its cuts with a person, and its
                # campaign's (or B2B keyword's) spend stays in Kim's total
                changed.append(f'{t}{label}: {not_rank}; kept until the stop-loss review decides')
                continue
            ended = dict(search=t, ended=date, **log.pop(t))
            if lanes_era:
                ended['stepped_down'] = stepped[t]
                if str(stepped[t]).startswith('the stop-loss'):
                    # the stop-loss ended it (its step-down, or its review approved): the planner holds the search from
                    # re-investment for auto.repromote_cooloff_days after `ended` (plan_lanes.cooloff_table, 2026-10-22)
                    ended['stop_loss'] = True
            hist.append(ended)
            changed.append(f'{t}{label}: no longer invested (moved to {history_key}'
                           + (f': {stepped[t]})' if lanes_era else ')'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--asin', required=True)
    ap.add_argument('--run', required=True)
    ap.add_argument('--skill', default=os.path.dirname(HERE))
    ap.add_argument('--data')
    ap.add_argument('--date', default=dt.date.today().isoformat())
    ap.add_argument('--applied-harvest-bid', action='store_true')
    a = ap.parse_args()
    shared = read(os.path.join(a.skill, 'config.json'))
    data_dir = a.data or shared.get('data_dir') or os.path.join(a.skill, 'data')
    path = os.path.join(data_dir, 'asins', f'{a.asin}.json')
    cfg = read(path)
    plan = read(os.path.join(a.run, 'plan.json'))
    record = applied_record(a.run)
    applied = None if record is None else {k: d for k, (d, _) in record.items()}
    recorded = applied is not None
    lanes_era = 'lanes' in (plan.get('summary') or [{}])[0]
    if applied is None and lanes_era:
        applied = {}  # C7: a run planned with the lanes and no record went out with nothing
    stepped = stepped_down(a.run, plan, record) if lanes_era else {}
    terms = {t['term']: t for t in plan['terms']}
    radar = load_radar(a.run)
    changed = []

    def start(t, role, since):
        """A new consumer entry: the search's record and its Rank Radar rank (the median of its last week) as the baseline."""
        tr = terms.get(t, {})
        series = radar.get(t, [])
        last = series[-1][0] if series else None
        rank_then = median_rank(series, (dt.date.fromisoformat(last) - dt.timedelta(days=6)).isoformat(), last) if last else None
        return (dict(since=since, role=role, index_then=tr.get('index'), imp_share_then=tr.get('impression_share'),
                     organic_then=tr.get('organic_purchases'), rank_then=rank_then),
                f'started {role} on {since} (rank {rank_then}, impression share {tr.get("impression_share")})')

    def backfill(t, entry):
        """A logged consumer entry without a rank baseline takes it from the radar when it can."""
        if entry.get('rank_then') is None and radar.get(t):
            # backfill the rank baseline from the radar's first week after the start date
            since = entry['since']
            week1 = (dt.date.fromisoformat(since) + dt.timedelta(days=13)).isoformat()
            base = median_rank(radar[t], since, week1)
            if base is not None:
                entry['rank_then'] = base
                return f'rank baseline backfilled ({base}) from Rank Radar, first two weeks after {since}'
        return None

    # the consumer invest log reads consumer rows only (no owner_kind 'business'), for its waiting set too: a business
    # change waiting on the same search is another campaign, so it never keeps a consumer entry as it was (spec 9b,
    # ruling 13)
    invest_rows = [c for c in plan['changes'] if c['type'] in INVEST_TYPES and c.get('role') in INVEST_ROLES
                   and c.get('owner_kind') != 'business']
    update_log(cfg.setdefault('invest_log', {}), cfg.setdefault('invest_history', []), 'invest_history', invest_rows,
               [(t, r['sub_role']) for t, r in terms.items() if r['role'] == 'Rank'], applied,
               waiting_searches(plan, applied, shared, a.asin), stepped, lanes_era, a.date, changed, start, backfill,
               ended=plan_step_downs(plan, record) if lanes_era else frozenset(),
               live={norm(x['keyword']) for x in plan.get('consumer_live_invests') or []
                     if x.get('keyword') and x.get('role') in INVEST_ROLES and x.get('campaign_id')})
    # a consumer search that passed a stop-loss checkpoint with an organic gain (plan.py, decision 142) keeps its reading
    # there, and the next checkpoint judges it against that reading, not against its start
    for s in plan.get('stop_loss') or []:
        entry = cfg['invest_log'].get(norm(str(s.get('keyword') or ''))) if isinstance(s, dict) else None
        if (entry is not None and s.get('owner_kind') != 'business' and s.get('checkpoint') and s.get('gains')
                and (entry.get('checkpoint') or 0) < s['checkpoint']):
            # a measure unread today keeps the reading it was judged against, so the next checkpoint still has a base
            entry.update(checkpoint=s['checkpoint'],
                         checkpoint_rank=s['rank_now'] if s.get('rank_now') is not None else s.get('rank_base'),
                         checkpoint_organic=s['organic_now'] if s.get('organic_now') is not None else s.get('organic_base'),
                         checkpoint_on=a.date)
            changed.append(f"{norm(s['keyword'])}: passed its month {s['checkpoint']} stop-loss checkpoint "
                           f"({'; '.join(s['gains'])})")
    # the business invests (design 4f) go to their own log, by the same rules row for row: only a business row that went out
    # starts a clock, on the day it went out; an explicit already-live owner also counts
    # (plan['business_live_invests'], no row). A Rank label or business_owners entry alone does not; a logged one keeps its entry
    # while a business change of this run on it waits, and leaves only by a business step-down on record (G1). Its baseline
    # is the search's B2B record, what plan.py's business stop-loss judges it on (orders and ACOS, never rank), and the
    # campaign holding its keyword. Waiting and step-downs read business rows only: a consumer change is another campaign
    b_terms = {t['term']: t for t in plan.get('business_terms') or []}
    b_live = plan.get('business_live_invests') or []
    b_rows = [c for c in plan['changes'] if c['type'] in INVEST_TYPES and c.get('role') in INVEST_ROLES
              and c.get('owner_kind') == 'business']
    # the campaign each new entry records: the row that went out's, else the owner already invested as planned's
    b_campaign = {}
    for c in b_rows:
        if (applied is None or c.get('row_id') in applied) and c.get('campaign_id'):
            b_campaign[norm(c['keyword'])] = str(c['campaign_id'])
    for x in b_live:
        if x.get('campaign_id'):
            b_campaign.setdefault(norm(x['keyword']), str(x['campaign_id']))
    # Owner IDs remain a fallback for verified applied rows that omitted their campaign. This candidate-owner list is
    # never proof that investment is live: it includes owners held by visibility checks.
    for x in plan.get('business_owners') or []:
        if x.get('campaign_id') and x.get('keyword'):
            b_campaign.setdefault(norm(x['keyword']), str(x['campaign_id']))

    def b_start(t, role, since):
        """A new business entry: the search's B2B record as the baseline, and the campaign holding its keyword."""
        br = b_terms.get(t, {})
        return (dict(since=since, role=role, index_then=br.get('index'), clicks_then=br.get('ad_clicks'),
                     orders_then=br.get('ad_orders'), spend_then=br.get('ad_spend'), sales_then=br.get('ad_sales'),
                     owner_kind='business', campaign_id=b_campaign.get(t)),
                f'started {role} on {since} ({br.get("ad_orders")} B2B orders on {br.get("ad_clicks")} B2B clicks)')

    b_stepped = stepped_down(a.run, plan, record, business=True) if lanes_era else {}
    # read, not setdefault: a product with no business invest keeps its file without the two keys
    b_log, b_hist = cfg.get('business_invest_log') or {}, cfg.get('business_invest_history') or []
    update_log(b_log, b_hist, 'business_invest_history', b_rows,
               [(t, r['sub_role']) for t, r in b_terms.items() if r['role'] == 'Rank']
               + [(norm(x['keyword']), x['role']) for x in b_live], applied,
               waiting_searches(plan, applied, shared, a.asin, business=True), b_stepped, lanes_era, a.date, changed, b_start,
               label=' (B2B)', not_rank='not a business rank term this run',
               ended=plan_step_downs(plan, record, business=True) if lanes_era else frozenset(),
               live={norm(x['keyword']) for x in b_live
                     if x.get('keyword') and x.get('role') in INVEST_ROLES and x.get('campaign_id')})
    if b_log or 'business_invest_log' in cfg:
        cfg['business_invest_log'] = b_log
    if b_hist or 'business_invest_history' in cfg:
        cfg['business_invest_history'] = b_hist
    if a.applied_harvest_bid and plan.get('harvest', {}).get('default_bid') is not None:
        hv = cfg.setdefault('harvest', {})
        if hv.get('default_bid') != plan['harvest']['default_bid']:
            changed.append(f"harvest default bid {hv.get('default_bid')} -> {plan['harvest']['default_bid']}")
            hv['default_bid'] = plan['harvest']['default_bid']
    # budget headroom: a 'Budget step' that went out goes in the shared ledger, so next week's plan judges it
    # (budget_headroom.decide: no second step for 7 days, and back to the old budget if it ran above breakeven)
    run_name = os.path.basename(os.path.abspath(a.run))
    ledger = budget_headroom.ledger_path(shared, data_dir)
    known = {(str(s.get('campaign_id')), str(s.get('date')), s.get('ref')) for s in budget_headroom.load_ledger(ledger).get('steps', [])}
    for c in plan['changes']:
        if ((c.get('type') != budget_headroom.TYPE and not c.get('budget_step_folded'))
                or not record or c.get('row_id') not in record):
            continue   # a rank campaign's step can ride on its Budget and top of search row (decision 174)
        day = record[c['row_id']][0]
        ref = f"{run_name} {c['row_id']}"
        if (str(c['campaign_id']), day, ref) in known:
            continue
        budget_headroom.record_step(ledger, dict(campaign_id=str(c['campaign_id']), campaign=c.get('campaign'), asin=a.asin,
                                                 **{'from': c.get('budget_now'), 'to': c.get('budget')}, date=day,
                                                 by='weekly run', why=c.get('why'), ref=ref))
        changed.append(f"budget step recorded: {c.get('campaign')} ${c.get('budget_now')} -> ${c.get('budget')} on {day}")
    # the product's planned invest after this run (autonomous runs, 2026-10-22): what the run summary's program total adds
    # up across the product files (autonomy.program_month, information only); a plan made before the lanes records nothing
    planned = autonomy.planned_invest_record(plan, applied, a.date)
    if planned is not None:
        if (cfg.get('planned_invest') or {}).get('month') != planned['month']:
            changed.append(f"planned invest ${planned['month']:,.2f} a month (program total)")
        cfg['planned_invest'] = planned
    cfg['last_run'] = dict(date=a.date, run=os.path.basename(os.path.abspath(a.run)), mode=plan['summary'][0].get('mode'))
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(cfg, fh, indent=1, ensure_ascii=False)
    print(json.dumps(dict(file=path, applied_record=recorded, changes=changed or ['nothing new']), indent=1))


if __name__ == '__main__':
    main()
